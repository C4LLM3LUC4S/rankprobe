"""Network recovery must not weaken immutable-input or existing-file checks."""

import hashlib
import importlib.util
from pathlib import Path
import ssl
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest


@pytest.fixture
def recipe():
    path = Path(__file__).resolve().parents[1] / "scripts/check_movielens_scores.py"
    spec = importlib.util.spec_from_file_location("movielens_download_recipe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(module, "ARCHIVE_BYTES", 3), patch.object(
        module, "ARCHIVE_SHA256", hashlib.sha256(b"abc").hexdigest()
    ):
        yield module


def response(body):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = body
    return result


def test_transient_connection_retry_keeps_exact_hash(recipe, tmp_path):
    target = tmp_path / "source.zip"
    with patch.object(recipe, "urlopen", side_effect=[URLError(TimeoutError()), response(b"abc")]) as request, patch.object(recipe.time, "sleep") as delay:
        recipe.fetch_archive(target)
    assert request.call_count == 2
    delay.assert_called_once_with(1)
    assert target.read_bytes() == b"abc"


def test_exhausted_retry_has_offline_recovery_and_no_partial_file(recipe, tmp_path):
    target = tmp_path / "source.zip"
    with patch.object(recipe, "urlopen", side_effect=TimeoutError()) as request, patch.object(recipe.time, "sleep") as delay:
        with pytest.raises(recipe.GateError, match="after 3 attempts.*--archive"):
            recipe.fetch_archive(target)
    assert request.call_count == 3
    assert [call.args[0] for call in delay.call_args_list] == [1, 2]
    assert not target.exists()


@pytest.mark.parametrize("error", [URLError(ssl.SSLCertVerificationError("untrusted")),
                                   HTTPError("https://example.invalid", 403, "forbidden", {}, None)])
def test_certificate_and_permanent_http_fail_without_retry(recipe, tmp_path, error):
    with patch.object(recipe, "urlopen", side_effect=error) as request, patch.object(recipe.time, "sleep") as delay:
        with pytest.raises(recipe.GateError):
            recipe.fetch_archive(tmp_path / "source.zip")
    request.assert_called_once()
    delay.assert_not_called()


def test_retryable_http_status_remains_bounded(recipe, tmp_path):
    error = HTTPError("https://example.invalid", 503, "unavailable", {}, None)
    with patch.object(recipe, "urlopen", side_effect=[error, response(b"abc")]) as request, patch.object(recipe.time, "sleep"):
        recipe.fetch_archive(tmp_path / "source.zip")
    assert request.call_count == 2


def test_bad_content_is_never_retried_or_written(recipe, tmp_path):
    with patch.object(recipe, "urlopen", return_value=response(b"xyz")) as request, patch.object(recipe.time, "sleep") as delay:
        with pytest.raises(recipe.GateError, match="SHA256 differs"):
            recipe.fetch_archive(tmp_path / "source.zip")
    request.assert_called_once()
    delay.assert_not_called()
    assert not (tmp_path / "source.zip").exists()


def test_existing_archive_is_untouched_and_network_not_called(recipe, tmp_path):
    target = tmp_path / "source.zip"
    target.write_bytes(b"old")
    with patch.object(recipe, "urlopen") as request:
        with pytest.raises(recipe.GateError, match="new archive path"):
            recipe.fetch_archive(target)
    request.assert_not_called()
    assert target.read_bytes() == b"old"
