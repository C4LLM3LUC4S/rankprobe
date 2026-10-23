"""Unreadable text stays rejected; a fresh source export keeps the evaluation data."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from rankprobe import Row
from rankprobe.io import InputError, read_predictions, read_qrels


ROOT = Path(__file__).resolve().parents[1]


def fixture_text(kind, format):
    if kind == "predictions":
        if format == "csv":
            return "query_id,item_id,score,relevance\n查询_001,0007,9007199254740993,2\n查询_001,0008,0.125,\n"
        if format == "jsonl":
            return ('{"query_id":"查询_001","item_id":"0007","score":9007199254740993,"relevance":2}\n'
                    '{"query_id":"查询_001","item_id":"0008","score":0.125,"relevance":null}\n')
        return "查询_001 Q0 0007 1 9007199254740993 original\n查询_001 Q0 0008 2 0.125 original\n"
    if format == "csv":
        return "query_id,item_id,relevance\n查询_001,0007,2\n查询_001,0008,0\n"
    if format == "jsonl":
        return ('{"query_id":"查询_001","item_id":"0007","relevance":2}\n'
                '{"query_id":"查询_001","item_id":"0008","relevance":0}\n')
    return "查询_001 0 0007 2\n查询_001 0 0008 -1\n"


def write_source(folder, kind, format, encoding="utf-16"):
    suffix = format if format != "trec" else ("run" if kind == "predictions" else "qrels")
    path = folder / f"original {kind}.{suffix}"
    text = fixture_text(kind, format)
    raw = text.encode(encoding) if encoding != "invalid-tail" else text.encode("utf-8") + b"\xff"
    path.write_bytes(raw)
    return path, text, raw


def check_values(path, kind, format):
    if kind == "predictions":
        assert read_predictions(path) == [
            Row("查询_001", "0007", 9007199254740993, 2 if format != "trec" else None),
            Row("查询_001", "0008", 0.125),
        ]
    else:
        assert read_qrels(path) == {"查询_001": {"0007": 2, "0008": None if format == "trec" else 0}}


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
@pytest.mark.parametrize("format", ["csv", "jsonl", "trec"])
@pytest.mark.parametrize("encoding", ["utf-16", "gb18030", "invalid-tail"])
def test_api_rejects_bad_encoding_and_accepts_unchanged_source_values(tmp_path, kind, format, encoding):
    source, text, original = write_source(tmp_path, kind, format, encoding)
    loader = read_predictions if kind == "predictions" else read_qrels
    with pytest.raises(InputError) as failure:
        loader(source)
    assert isinstance(failure.value.__cause__, UnicodeDecodeError)
    message = str(failure.value)
    assert str(source) in message and "cannot read input as UTF-8" in message
    assert "original source" in message and "do not ignore or replace" in message
    assert "Decoder detail:" in message and "UTF-8 文件后重试" in message
    assert source.read_bytes() == original
    recovered = source.with_name("reexported" + source.suffix)
    recovered.write_text(text, encoding="utf-8-sig", newline="")
    check_values(recovered, kind, format)
    assert recovered.read_text(encoding="utf-8-sig") == text
    assert source.read_bytes() == original


def invoke(folder, *arguments, ascii_stderr=False):
    script = "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    script += "sys.stdout.reconfigure(encoding='utf-8'); "
    if ascii_stderr:
        script += ("import io; sys.stderr=io.TextIOWrapper(sys.stderr.buffer,"
                   "encoding='ascii',errors='strict'); ")
    else:
        script += "sys.stderr.reconfigure(encoding='utf-8'); "
    script += "from rankprobe.cli import main; raise SystemExit(main(sys.argv[1:]))"
    return subprocess.run([sys.executable, "-I", "-c", script, str(ROOT / "src"),
                           *map(str, arguments)], cwd=folder, capture_output=True,
                          timeout=30, check=False)


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
@pytest.mark.parametrize("format", ["csv", "jsonl", "trec"])
def test_cli_failed_input_can_be_reexported_without_a_partial_report(tmp_path, kind, format):
    source, text, original = write_source(tmp_path, kind, format)
    predictions = tmp_path / "valid predictions.csv"
    predictions.write_text("query_id,item_id,score\n查询_001,0007,3\n查询_001,0008,2\n查询_001,0009,1\n",
                           encoding="utf-8")
    out = tmp_path / "new report"

    def run(path):
        inputs = [path] if kind == "predictions" else [predictions, "--qrels", path]
        return invoke(tmp_path, "audit", *inputs, "--cutoffs", "1,2", "--out", out)

    failed = run(source)
    assert failed.returncode == 2 and not failed.stdout and not out.exists()
    stderr = failed.stderr.decode("utf-8")
    assert "cannot read input as UTF-8" in stderr and "Traceback" not in stderr
    recovered = source.with_name("fresh" + source.suffix)
    recovered.write_text(text, encoding="utf-8-sig", newline="")
    good_bytes = recovered.read_bytes()
    result = run(recovered)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert not result.stderr and (out / "report.html").is_file()
    report = json.loads((out / "report.json").read_text("utf-8"))
    expected_unknowns = (2 if format == "trec" else 1)
    assert report["summary"]["unknown_candidates"] == expected_unknowns
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert source.read_bytes() == original and recovered.read_bytes() == good_bytes
    check_values(recovered, kind, format)


def test_source_launcher_explains_recovery_from_an_unrelated_folder(tmp_path):
    source, _, original = write_source(tmp_path, "predictions", "csv")
    out = tmp_path / "launcher report"
    result = subprocess.run([sys.executable, "-I", str(ROOT / "quickstart.py"), "--no-open",
                             "--input", str(source), "--out", str(out)], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 2 and not out.exists()
    assert "UTF-8 文件后重试" in result.stderr and "Traceback" not in result.stderr
    assert source.read_bytes() == original


def test_strict_ascii_console_still_reports_the_recovery_and_exit_two(tmp_path):
    source, _, original = write_source(tmp_path, "predictions", "jsonl")
    out = tmp_path / "ascii report"
    result = invoke(tmp_path, "audit", source, "--out", out, ascii_stderr=True)
    assert result.returncode == 2 and not result.stdout and not out.exists()
    stderr = result.stderr.decode("ascii")
    assert "cannot read input as UTF-8" in stderr and "Decoder detail:" in stderr
    assert "Traceback" not in stderr and source.read_bytes() == original


@pytest.mark.parametrize("format", ["csv", "trec"])
def test_missing_file_is_not_misdiagnosed_as_an_encoding_error(tmp_path, format):
    missing = tmp_path / "missing.txt"
    with pytest.raises(InputError) as failure:
        read_predictions(missing, format=format)
    assert isinstance(failure.value.__cause__, OSError)
    assert "cannot read input:" in str(failure.value)
    assert "UTF-8" not in str(failure.value)
