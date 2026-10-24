import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import subprocess
import tarfile
import zipfile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/recover_alpha6_release.py"
SPEC = importlib.util.spec_from_file_location("alpha6_recovery", SCRIPT)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def zipped(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture
def build(monkeypatch):
    for name, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": recovery.REPOSITORY,
                        "GITHUB_REF": "refs/heads/main", "GH_TOKEN": "test-token-never-retained"}.items():
        monkeypatch.setenv(name, value)

    def make(*, bundle_change=None, wheel_change=None, sdist_change=None, info_change=None,
             manifest_change=None):
        source = {"pyproject.toml": b'version = "0.1.0a6"\n',
                  "src/rankprobe/__init__.py": b'__version__ = "0.1.0a6"\n',
                  "examples/trec/baseline.run": b"q1 Q0 a 1 1 base\n"}
        wheel_name = f"rankprobe-{recovery.VERSION}-py3-none-any.whl"
        wheel_files = {"rankprobe/__init__.py": source["src/rankprobe/__init__.py"],
                       f"rankprobe-{recovery.VERSION}.dist-info/METADATA":
                       b"Name: rankprobe\nVersion: 0.1.0a6\n"}
        if wheel_change:
            wheel_change(wheel_files)
        wheel = zipped(wheel_files)
        sdist_files = {**source, "setup.cfg": b"[egg_info]\ntag_build = \ntag_date = 0\n\n"}
        if sdist_change:
            sdist_change(sdist_files)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, data in sdist_files.items():
                member = tarfile.TarInfo(f"rankprobe-{recovery.VERSION}/" + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        sdist = buffer.getvalue()
        identity = {"schema_version": 1, "project": "RankProbe", "version": recovery.VERSION,
                    "repository": recovery.REPOSITORY, "source_commit": recovery.SOURCE,
                    "source_path": "", "ci_url": recovery.ORIGINAL_CI, "scope": "original fixture"}
        package_files = {wheel_name: wheel, f"rankprobe-{recovery.VERSION}.tar.gz": sdist}
        members = {"source/" + name: data for name, data in source.items()}
        members.update({"dist/" + name: data for name, data in package_files.items()})
        members.update({"BUILD_INFO.json": encoded(identity), "START_HERE.md": b"Original fixture\n"})
        if bundle_change:
            bundle_change(members)
        manifest = {"schema_version": 1, "source_commit": recovery.SOURCE,
                    "files": {name: {"bytes": len(data), "sha256": recovery.digest(data)}
                              for name, data in members.items()}}
        if manifest_change:
            manifest_change(manifest)
        members["MANIFEST.json"] = encoded(manifest)
        package_files[f"RankProbe-{recovery.VERSION}.zip"] = zipped(members)
        info = {**identity, "assets": {name: {"bytes": len(data), "sha256": recovery.digest(data)}
                                      for name, data in package_files.items()}}
        if info_change:
            info_change(info)
        files = {**package_files, "RELEASE_INFO.json": encoded(info)}
        files["SHA256SUMS"] = "".join(f"{recovery.digest(data)}  {name}\n"
                                    for name, data in files.items()).encode()
        specs = {name: (recovery.ASSETS[name][0], len(data), recovery.digest(data))
                 for name, data in files.items()}
        monkeypatch.setattr(recovery, "ASSETS", specs)
        monkeypatch.setattr(recovery, "original_source", lambda: source)
        events = []
        monkeypatch.setattr(recovery, "installed_task", lambda *args:
                            events.append(("installed_task",)) or {"status": "passed"})
        release = {"id": recovery.RELEASE_ID, "tag_name": recovery.TAG,
                   "target_commitish": recovery.SOURCE, "prerelease": True, "draft": True,
                   "assets": [{"id": asset_id, "name": name, "size": size, "state": "uploaded",
                               "digest": "sha256:" + sha256} for name, (asset_id, size, sha256)
                              in specs.items()]}
        reads = []

        def api(path, *, binary=False, publish=False, allow_missing=False):
            events.append((path, binary, publish))
            if path == recovery.REF_PATH:
                return None if release["draft"] else {"ref": "refs/tags/" + recovery.TAG,
                    "object": {"type": "commit", "sha": recovery.SOURCE}}
            if path == recovery.RELEASE_PATH:
                if publish:
                    release["draft"] = False
                reads.append(copy.deepcopy(release))
                return copy.deepcopy(release)
            require_id = int(path.rsplit("/", 1)[1])
            return next(data for name, data in files.items() if specs[name][0] == require_id)

        monkeypatch.setattr(recovery, "api", api)
        return {"source": source, "files": files, "release": release, "events": events,
                "reads": reads, "api": api}
    return make


def writes(fixture):
    return [event for event in fixture["events"] if len(event) == 3 and event[2]]


def test_fixed_draft_is_published_only_after_source_and_installed_checks(build, tmp_path):
    fixture = build()
    result = recovery.recover(tmp_path / "new recovery")
    assert result["status"] == "published"
    assert writes(fixture) == [(recovery.RELEASE_PATH, False, True)]
    assert fixture["events"].index(("installed_task",)) < fixture["events"].index(writes(fixture)[0])
    assert len(fixture["reads"]) == 4
    assert "test-token-never-retained" not in (tmp_path / "new recovery/summary.json").read_text()


def test_already_published_original_bytes_are_verified_without_any_write(build, tmp_path):
    fixture = build()
    fixture["release"]["draft"] = False
    assert recovery.recover(tmp_path / "read only")["status"] == "verified_already_published"
    assert not writes(fixture)


@pytest.mark.parametrize("field,value", [("id", 1), ("size", 1), ("digest", "sha256:wrong")])
def test_changed_remote_asset_identity_refuses_before_download(build, tmp_path, field, value):
    fixture = build()
    fixture["release"]["assets"][0][field] = value
    assert recovery.recover(tmp_path / "wrong asset")["status"] == "failed"
    assert len(fixture["events"]) == 1
    assert not writes(fixture)


def test_downloaded_byte_change_stops_before_install_or_publication(build, tmp_path):
    fixture = build()
    name = next(iter(fixture["files"]))
    fixture["files"][name] += b"changed"
    assert recovery.recover(tmp_path / "corrupt")["status"] == "failed"
    assert ("installed_task",) not in fixture["events"]
    assert not writes(fixture)


@pytest.mark.parametrize("change", [
    {"info_change": lambda info: info.update(source_commit="b" * 40)},
    {"info_change": lambda info: info.update(ci_url="https://github.com/other/run/1")},
    {"bundle_change": lambda files: files.pop("source/pyproject.toml")},
    {"bundle_change": lambda files: files.update({"source/private.csv": b"unexpected"})},
    {"bundle_change": lambda files: files.update({"source/pyproject.toml": b"different source"})},
    {"manifest_change": lambda manifest: manifest["files"].pop("START_HERE.md")},
    {"wheel_change": lambda files: files.update({"rankprobe/__init__.py": b"different core"})},
    {"sdist_change": lambda files: files.update({"src/rankprobe/__init__.py": b"different core"})},
    {"sdist_change": lambda files: files.pop("examples/trec/baseline.run")},
])
def test_consistently_hashed_but_wrong_source_or_package_is_not_published(build, tmp_path, change):
    fixture = build(**change)
    result = recovery.recover(tmp_path / "wrong source")
    assert result["status"] == "failed", result
    assert ("installed_task",) not in fixture["events"]
    assert not writes(fixture)


def test_final_metadata_change_blocks_publication(build, monkeypatch, tmp_path):
    fixture = build()
    def change_after_install(*args):
        fixture["release"]["target_commitish"] = "b" * 40
        return {"status": "passed"}
    monkeypatch.setattr(recovery, "installed_task", change_after_install)
    assert recovery.recover(tmp_path / "changed during checks")["status"] == "failed"
    assert not writes(fixture)


def test_already_published_release_that_reverts_to_draft_is_not_republished(build, monkeypatch, tmp_path):
    fixture = build()
    fixture["release"]["draft"] = False
    def change_after_install(*args):
        fixture["release"]["draft"] = True
        return {"status": "passed"}
    monkeypatch.setattr(recovery, "installed_task", change_after_install)
    assert recovery.recover(tmp_path / "reverted public release")["status"] == "failed"
    assert not writes(fixture)


def test_installed_task_failure_leaves_draft_unchanged(build, monkeypatch, tmp_path):
    fixture = build()
    monkeypatch.setattr(recovery, "installed_task", lambda *args: {"status": "failed"})
    assert recovery.recover(tmp_path / "failed install")["status"] == "failed"
    assert fixture["release"]["draft"] is True and not writes(fixture)


@pytest.mark.parametrize("object_type,sha", [("commit", "b" * 40), ("tag", recovery.SOURCE)])
def test_wrong_existing_tag_blocks_publication(build, monkeypatch, tmp_path, object_type, sha):
    fixture = build()
    def api(path, **kwargs):
        if path == recovery.REF_PATH:
            return {"ref": "refs/tags/" + recovery.TAG, "object": {"type": object_type, "sha": sha}}
        return fixture["api"](path, **kwargs)
    monkeypatch.setattr(recovery, "api", api)
    assert recovery.recover(tmp_path / "wrong tag")["status"] == "failed"
    assert not writes(fixture)


@pytest.mark.parametrize("status", [403, 500, 503])
def test_unknown_tag_read_failure_blocks_publication(build, monkeypatch, tmp_path, status):
    fixture = build()
    def api(path, **kwargs):
        if path == recovery.REF_PATH:
            raise subprocess.CalledProcessError(1, ["gh", "api", path], stderr=f"HTTP {status}")
        return fixture["api"](path, **kwargs)
    monkeypatch.setattr(recovery, "api", api)
    assert recovery.recover(tmp_path / "tag read failed")["status"] == "failed"
    assert not writes(fixture)


def test_dry_run_has_no_network_or_file_write(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("No subprocess in dry run")
    monkeypatch.setattr(recovery.subprocess, "run", forbidden)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--out", str(tmp_path / "unused")])
    assert recovery.main() == 0
    assert json.loads(capsys.readouterr().out)["network_or_mutation"] is False
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("name,value", [("GITHUB_ACTIONS", "false"), ("GITHUB_REPOSITORY", "other/repo"),
                                       ("GITHUB_REF", "refs/heads/feature"), ("GH_TOKEN", None)])
def test_non_runner_context_refuses_before_any_network_or_output(build, monkeypatch, tmp_path, name, value):
    fixture = build()
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="GitHub Actions token"):
        recovery.recover(tmp_path / "forbidden")
    assert not fixture["events"] and not (tmp_path / "forbidden").exists()


def test_api_publication_body_and_scope_cannot_create_upload_or_delete(monkeypatch):
    for name, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": recovery.REPOSITORY,
                        "GITHUB_REF": "refs/heads/main", "GH_TOKEN": "not-a-real-token"}.items():
        monkeypatch.setenv(name, value)
    captured = []
    def run(arguments, **kwargs):
        captured.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, stdout=b"{}")
    monkeypatch.setattr(recovery.subprocess, "run", run)
    recovery.api(recovery.RELEASE_PATH, publish=True)
    assert captured[0][1]["input"] == b'{"draft":false}'
    assert "PATCH" in captured[0][0] and recovery.RELEASE_PATH in captured[0][0]
    with pytest.raises(ValueError, match="fixed draft"):
        recovery.api(f"repos/{recovery.REPOSITORY}/releases/assets/1", publish=True)
    with pytest.raises(ValueError, match="Unexpected API path"):
        recovery.api(f"repos/{recovery.REPOSITORY}/releases", publish=True)
    assert len(captured) == 1


@pytest.mark.parametrize("status,allowed", [(404, True), (403, False), (500, False), (503, False)])
def test_api_only_allows_explicit_pending_tag_404(monkeypatch, status, allowed):
    for name, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": recovery.REPOSITORY,
                        "GITHUB_REF": "refs/heads/main", "GH_TOKEN": "not-a-real-token"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(recovery.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, stdout=b"",
                                                    stderr=f"gh: refused (HTTP {status})\n".encode()))
    if allowed:
        assert recovery.api(recovery.REF_PATH, allow_missing=True) is None
    else:
        with pytest.raises(subprocess.CalledProcessError):
            recovery.api(recovery.REF_PATH, allow_missing=True)
