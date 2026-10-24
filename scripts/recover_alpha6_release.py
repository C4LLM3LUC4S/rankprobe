"""Publish only the five original alpha-6 draft assets after verifying them."""

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "C4LLM3LUC4S/rankprobe"
SOURCE = "22cd7b8cf2ba47553df233e456f54cfaed7885ad"
ORIGINAL_CI = f"https://github.com/{REPOSITORY}/actions/runs/40067031529"
VERSION = "0.1.0a6"
TAG = "v" + VERSION
RELEASE_ID = 422541718
RELEASE_PATH = f"repos/{REPOSITORY}/releases/{RELEASE_ID}"
REF_PATH = f"repos/{REPOSITORY}/git/ref/tags/{TAG}"
ASSETS = {
    "rankprobe-0.1.0a6-py3-none-any.whl": (671393305, 47224,
        "faaa5cfa138aa8447dc8e6421730da1cdbfc5fde1cc40ab17423bc71dd40c23f"),
    "rankprobe-0.1.0a6.tar.gz": (671393307, 319323,
        "7dfdfe3cf187e16daf0bff1be3a1d1832193a2ee1dac87d722e630500aed0646"),
    "RankProbe-0.1.0a6.zip": (671393302, 769839,
        "254ee0cc677acef3c07021a4a5a508ae8846613f85e3bfc4f61d0eb4d7f31eef"),
    "RELEASE_INFO.json": (671393300, 885,
        "d04940b6309c61c3430efb620e49251a270daba9a23d48e2aee88f9188cc9f62"),
    "SHA256SUMS": (671393306, 364,
        "c699a7024abe67f54e462e93ca86517c7046994668f49cb1b51175017d7b6b48"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_data(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique)


def runner_only():
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and "GH_TOKEN" in os.environ,
            "Publication requires this repository's main GitHub Actions token")


def api(path, *, binary=False, publish=False, allow_missing=False):
    runner_only()
    require(path == RELEASE_PATH or path.startswith(f"repos/{REPOSITORY}/releases/assets/")
            or path == REF_PATH, "Unexpected API path")
    arguments = ["gh", "api", "--hostname", "github.com", path, "--method",
                 "PATCH" if publish else "GET", "-H", "Accept: " +
                 ("application/octet-stream" if binary else "application/vnd.github+json")]
    if publish:
        require(path == RELEASE_PATH and not binary, "Only the fixed draft may be published")
        arguments += ["--input", "-"]
    require(not allow_missing or (path == REF_PATH and not publish and not binary),
            "Only the original pending tag may be absent")
    result = subprocess.run(arguments, input=b'{"draft":false}' if publish else None,
                            capture_output=True, check=False, timeout=180)
    if result.returncode:
        if allow_missing and re.search(rb"\(HTTP 404\)\s*$", result.stderr):
            return None
        result.check_returncode()
    return result.stdout if binary else json_data(result.stdout)


def verify_release(release):
    require(release["id"] == RELEASE_ID and release["tag_name"] == TAG
            and release["target_commitish"] == SOURCE and release["prerelease"] is True
            and type(release["draft"]) is bool, "Release identity differs from the original draft")
    assets = release["assets"]
    require(len(assets) == len(ASSETS) and {asset["name"] for asset in assets} == set(ASSETS),
            "Remote asset names or count differ")
    for asset in assets:
        asset_id, size, sha256 = ASSETS[asset["name"]]
        require(asset["id"] == asset_id and asset["size"] == size
                and asset["state"] == "uploaded" and asset.get("digest") == "sha256:" + sha256,
                "Remote asset identity differs: " + asset["name"])


def verify_payload(name, data):
    _, size, sha256 = ASSETS[name]
    require(len(data) == size and digest(data) == sha256, "Original asset bytes differ: " + name)


def verify_tag(required):
    tag = api(REF_PATH, allow_missing=not required)
    require(tag is not None or not required, "Original release tag is unavailable")
    if tag is not None:
        require(tag["ref"] == "refs/tags/" + TAG and tag["object"]["type"] == "commit"
                and tag["object"]["sha"] == SOURCE, "Tag differs from the original source")


def original_source():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT)
    require(git("rev-parse", SOURCE + "^{commit}").decode().strip() == SOURCE,
            "The original public source commit is unavailable")
    files = {}
    for entry in git("ls-tree", "-rz", "--full-tree", SOURCE).split(b"\0"):
        if not entry:
            continue
        header, raw_name = entry.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        name = raw_name.decode("utf-8")
        require(mode in {"100644", "100755"} and kind == "blob", "Non-regular original source")
        safe_path(name)
        files[name] = git("cat-file", "blob", blob)
    return files


def safe_path(name):
    path = PurePosixPath(name)
    require(bool(path.parts) and path.as_posix() == name.rstrip("/")
            and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and ":" not in name, "Unsafe archive path")


def verify_packages(directory, source):
    wheel_name = f"rankprobe-{VERSION}-py3-none-any.whl"
    sdist_name = f"rankprobe-{VERSION}.tar.gz"
    core = {name.removeprefix("src/"): data for name, data in source.items()
            if name.startswith("src/rankprobe/")}
    require(bool(core), "Original core source is missing")
    with zipfile.ZipFile(directory / wheel_name) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)) and wheel.testzip() is None, "Invalid wheel")
        for name in names:
            safe_path(name)
        require(all((entry.external_attr >> 16) & 0o170000 in {0, 0o100000}
                    for entry in wheel.infolist()), "Non-regular wheel member")
        require({name for name in names if name.startswith("rankprobe/")} == set(core),
                "Wheel core file set differs")
        for name, data in core.items():
            require(wheel.read(name) == data, "Wheel source differs: " + name)
        metadata = BytesParser().parsebytes(wheel.read(f"rankprobe-{VERSION}.dist-info/METADATA"))
        require(metadata["Name"] == "rankprobe" and metadata["Version"] == VERSION,
                "Wheel metadata differs")
        require(all("extra ==" in value for value in metadata.get_all("Requires-Dist", [])),
                "Unexpected core runtime dependency")
    expected = {name for name in source if not name.startswith(".github/")
                and name not in {".gitattributes", ".gitignore", "CONTRIBUTING.md"}}
    generated = {"PKG-INFO", "setup.cfg", *("src/rankprobe.egg-info/" + name for name in
                 ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt",
                  "requires.txt", "top_level.txt"))}
    observed = set()
    with tarfile.open(directory / sdist_name, "r:gz") as archive:
        names = set()
        for member in archive:
            safe_path(member.name)
            require(member.name not in names and (member.isdir() or member.isfile()), "Invalid sdist member")
            names.add(member.name)
            prefix = f"rankprobe-{VERSION}/"
            require(member.name == prefix[:-1] or member.name.startswith(prefix), "Unexpected sdist root")
            if member.isfile():
                name = member.name[len(prefix):]
                require(name in expected | generated, "Unexpected sdist file")
                if name in expected:
                    require(archive.extractfile(member).read() == source[name], "Sdist source differs: " + name)
                    observed.add(name)
        require(observed == expected, "Sdist source file set differs")


def verify_bundle(directory, source, destination):
    info = json_data((directory / "RELEASE_INFO.json").read_bytes())
    identity = {"schema_version": 1, "project": "RankProbe", "version": VERSION,
                "repository": REPOSITORY, "source_commit": SOURCE, "source_path": "",
                "ci_url": ORIGINAL_CI}
    require(all(info.get(key) == value for key, value in identity.items()), "Release information differs")
    sums = {}
    for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        sha256, name = line.split("  ", 1)
        require(name in set(ASSETS) - {"SHA256SUMS"} and name not in sums
                and sha256 == ASSETS[name][2], "Checksum entry differs")
        sums[name] = sha256
    require(set(sums) == set(ASSETS) - {"SHA256SUMS"}, "Checksum coverage differs")
    package_names = set(ASSETS) - {"RELEASE_INFO.json", "SHA256SUMS"}
    require(set(info["assets"]) == package_names, "Release information asset set differs")
    for name, entry in info["assets"].items():
        require(entry == {"bytes": ASSETS[name][1], "sha256": ASSETS[name][2]}, "Asset receipt differs")
    with zipfile.ZipFile(directory / f"RankProbe-{VERSION}.zip") as bundle:
        names = bundle.namelist()
        require(len(names) == len(set(names)) and bundle.testzip() is None, "Invalid bundle")
        for entry in bundle.infolist():
            safe_path(entry.filename)
            require((entry.external_attr >> 16) & 0o170000 in {0, 0o100000}, "Non-regular bundle member")
        source_names = {"source/" + name for name in source}
        distribution_names = {"dist/" + name for name in package_names if not name.endswith(".zip")}
        require(set(names) == source_names | distribution_names |
                {"BUILD_INFO.json", "MANIFEST.json", "START_HERE.md"}, "Bundle file set differs")
        manifest = json_data(bundle.read("MANIFEST.json"))
        require(manifest["schema_version"] == 1 and manifest["source_commit"] == SOURCE
                and set(manifest["files"]) == set(names) - {"MANIFEST.json"}, "Manifest coverage differs")
        for name, expected in manifest["files"].items():
            data = bundle.read(name)
            require(expected == {"bytes": len(data), "sha256": digest(data)}, "Manifest entry differs")
        build = json_data(bundle.read("BUILD_INFO.json"))
        require(build == {key: value for key, value in info.items() if key != "assets"},
                "Build information differs")
        for name, data in source.items():
            require(bundle.read("source/" + name) == data, "Bundled source differs: " + name)
        for name in distribution_names:
            require(bundle.read(name) == (directory / name.removeprefix("dist/")).read_bytes(),
                    "Bundled distribution differs")
        destination.mkdir(exist_ok=False)
        for name in names:
            path = destination.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(bundle.read(name))
    verify_packages(directory, source)


def installed_task(directory, extracted):
    workspace = directory / "offline task"
    workspace.mkdir(exist_ok=False)
    venv = workspace / "fresh environment"
    environment = {name: os.environ[name] for name in
                   ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LD_LIBRARY_PATH")
                   if name in os.environ}
    environment.update({"PIP_NO_INDEX": "1", "PIP_CONFIG_FILE": os.devnull,
                        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1"})

    def run(name, command, expected=0):
        result = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=180)
        (workspace / (name + ".stdout.txt")).write_text(result.stdout, encoding="utf-8")
        (workspace / (name + ".stderr.txt")).write_text(result.stderr, encoding="utf-8")
        require(result.returncode == expected and "Traceback" not in result.stderr, "Installed task failed: " + name)
        return result.stdout

    run("venv", [sys.executable, "-I", "-m", "venv", str(venv)])
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = directory / "downloads" / f"rankprobe-{VERSION}-py3-none-any.whl"
    run("install", [str(python), "-I", "-m", "pip", "--isolated", "install", "--no-index",
                    "--no-deps", "--no-cache-dir", f"{wheel.as_uri()}#sha256={ASSETS[wheel.name][2]}"])
    probe = json_data(run("probe", [str(python), "-I", "-c",
        "import importlib.metadata as m,json,rankprobe,sys; "
        "print(json.dumps({'version':m.version('rankprobe'),'module':rankprobe.__file__,"
        "'isolated':sys.flags.isolated,'packages':sorted(d.metadata['Name'].lower() for d in m.distributions())}))"]))
    require(probe["version"] == VERSION and probe["isolated"] == 1
            and Path(probe["module"]).resolve().is_relative_to(venv)
            and set(probe["packages"]) <= {"pip", "setuptools", "rankprobe"}, "Installed isolation differs")
    fixtures = extracted / "source" / "examples" / "trec"
    originals = {path.name: digest(path.read_bytes()) for path in fixtures.iterdir() if path.is_file()}
    def rows(name):
        return [line.split() for line in (fixtures / name).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    baseline, reordered, complete = (rows(name) for name in
                                    ("baseline.run", "reordered.run", "reordered-complete.run"))
    require([row[2:5] for row in baseline if row[0] == "q2"] ==
            [["doc_e", "1", "0.9"], ["doc_f", "2", "0.8"]]
            and not any(row[0] == "q2" for row in reordered)
            and [row for row in complete if row[0] != "q2"] == reordered,
            "Original q2 export evidence differs")
    core = {path.name: digest(path.read_bytes()) for path in
            (extracted / "source" / "src" / "rankprobe").glob("*.py")}
    core_sha = digest(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("ascii"))
    reports = []
    first_hashes = {}
    for name, filename, exit_code in (("first", "reordered.run", 1), ("recheck", "reordered-complete.run", 0)):
        command = [str(python), "-I", "-m", "rankprobe", "compare", "--run",
                   f"baseline={fixtures / 'baseline.run'}", "--run", f"candidate={fixtures / filename}",
                   "--qrels", str(fixtures / "judgments.qrels"), "--cutoffs", "1,2", "--out", name]
        if name == "first":
            command += ["--fail-on", "warning"]
        run(name, command, exit_code)
        report_dir = workspace / name
        require((report_dir / "report.html").is_file(), "Installed HTML report missing")
        reports.append(json_data((report_dir / "report.json").read_bytes()))
        if name == "first":
            first_hashes = {name: digest((report_dir / name).read_bytes())
                            for name in ("report.json", "report.html")}
    first, recheck = reports
    finding = next(f for f in first["findings"] if f["code"] == "query_coverage_mismatch")
    require(finding["evidence"]["left_only"] == ["q2"]
            and not any(f["code"] == "query_coverage_mismatch" for f in recheck["findings"]),
            "Original query-coverage control differs")
    for report in reports:
        require(report["provenance"]["rankprobe_version"] == VERSION
                and report["provenance"]["core_source_identity"]["sha256"] == core_sha,
                "Installed report source differs")
        require(all(item["sha256"] == originals[item["filename"]]
                    for item in report["provenance"]["sources"]), "Report input identities differ")
        require(report["protocol"] == first["protocol"] and report["protocol"]["unjudged"] == "unknown"
                and report["protocol"]["qrels_complete"] is False, "Installed protocol differs")
        for run_report in report["runs"].values():
            audit = run_report["audit"]
            require(audit["summary"]["unknown_candidates"] == 1
                    and audit["summary"]["assumed_nonrelevant_candidates"] == 0
                    and audit["metrics"]["mrr@2"]["excluded_query_ids"] == ["q3"]
                    and audit["metrics"]["recall@2"]["value"] is None, "Unknown labels changed")
        deltas = report["pairs"][0]["matched_pool_comparison"]["delta_right_minus_left"]
        require(deltas["mrr@2"]["delta"] == deltas["ndcg@2"]["delta"] == 0, "Matched metric control differs")
    require(all(run_report["audit"]["metrics"]["mrr@2"]["value"] == 0.25
                for run_report in recheck["runs"].values()), "Restored query population differs")
    require(originals == {path.name: digest(path.read_bytes()) for path in fixtures.iterdir() if path.is_file()},
            "Original TREC fixtures changed")
    require(first_hashes == {name: digest((workspace / "first" / name).read_bytes()) for name in first_hashes},
            "First report changed during recheck")
    return {"status": "passed", "unknown_labels_preserved": True, "original_inputs_unchanged": True,
            "query_coverage_recheck": True, "isolated_offline_install": True}


def recover(out):
    runner_only()
    out.mkdir(parents=True, exist_ok=False)
    # The runner token is inherited by gh, never read, printed, or stored here.
    os.environ["GH_CONFIG_DIR"] = str(out / "empty-gh-config")
    result = {"status": "failed", "release_id": RELEASE_ID, "source_commit": SOURCE,
              "asset_sha256": {}, "publication_attempted": False}
    try:
        release = api(RELEASE_PATH)
        verify_release(release)
        downloads = out / "downloads"
        downloads.mkdir()
        for name, (asset_id, _, _) in ASSETS.items():
            data = api(f"repos/{REPOSITORY}/releases/assets/{asset_id}", binary=True)
            verify_payload(name, data)
            with (downloads / name).open("xb") as handle:
                handle.write(data)
            result["asset_sha256"][name] = digest(data)
        source = original_source()
        extracted = out / "original bundle"
        verify_bundle(downloads, source, extracted)
        result["installed_task"] = installed_task(out, extracted)
        require(result["installed_task"]["status"] == "passed", "Installed task did not pass")
        current = api(RELEASE_PATH)
        verify_release(current)
        require(release["draft"] or current["draft"] is False,
                "An already published release changed back to a draft; no write attempted")
        verify_tag(required=not current["draft"])
        if current["draft"]:
            result["publication_attempted"] = True
            published = api(RELEASE_PATH, publish=True)
            verify_release(published)
            require(published["draft"] is False, "The fixed draft was not published")
        final = api(RELEASE_PATH)
        verify_release(final)
        require(final["draft"] is False, "Final release remains a draft")
        verify_tag(required=True)
        for name, (asset_id, _, _) in ASSETS.items():
            verify_payload(name, api(f"repos/{REPOSITORY}/releases/assets/{asset_id}", binary=True))
        result["status"] = "published" if result["publication_attempted"] else "verified_already_published"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not args.publish:
        print(json.dumps({"operation": "dry_run", "release_id": RELEASE_ID, "tag": TAG,
                          "source_commit": SOURCE, "assets": ASSETS, "network_or_mutation": False}))
        return 0
    if args.out is None:
        parser.error("--publish requires a new --out directory")
    result = recover(args.out.resolve())
    print(json.dumps(result, indent=2))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
