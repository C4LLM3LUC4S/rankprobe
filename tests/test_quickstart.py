"""Own files follow the same source-only path as the first-run preview."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def invoke(cwd, *arguments):
    return subprocess.run([sys.executable, "-I", str(ROOT / "quickstart.py"), "--no-open", *map(str, arguments)],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_demo_remains_available_without_own_file_options(tmp_path):
    output = tmp_path / "original demo path"
    process = invoke(tmp_path, "--out", output)
    assert process.returncode == 0, process.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["provenance"]["command"] == "demo"
    assert "demo_note" in report
    assert "Synthetic demonstration" in process.stdout


def test_own_score_file_from_unrelated_directory_preserves_unknowns_and_inputs(tmp_path):
    source = tmp_path / "own scores.csv"
    source.write_text("query_id,item_id,score\nq1,a,0.9\nq1,b,0.8\n", encoding="utf-8")
    before = digest(source)
    out = tmp_path / "own report"
    process = invoke(tmp_path, "--input", source, "--cutoffs", "1,2", "--out", out)
    assert process.returncode == 0, process.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["provenance"]["command"] == "audit"
    assert report["provenance"]["sources"][0]["sha256"] == before
    assert "demo_note" not in report
    assert "Synthetic demonstration" not in process.stdout
    assert digest(source) == before
    assert (out / "report.html").is_file()
    # Exact label semantics are checked through the existing report, never imputed by the launcher.
    assert all(item["value"] is None for item in report["metrics"].values())
    assert report["summary"]["unknown_candidates"] == 2
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0


def test_two_own_runs_with_existing_qrels_and_explicit_trec_formats(tmp_path):
    left, right, labels = (tmp_path / name for name in ("left.txt", "right.txt", "labels.txt"))
    left.write_text("q1 Q0 a 1 0.9 x\nq1 Q0 b 2 0.8 x\n", encoding="utf-8")
    right.write_text("q1 Q0 a 1 0.8 y\nq1 Q0 b 2 0.9 y\n", encoding="utf-8")
    labels.write_text("q1 0 a 1\nq1 0 b 0\n", encoding="utf-8")
    originals = [digest(path) for path in (left, right, labels)]
    out = tmp_path / "compared"
    process = invoke(tmp_path, "--run", f"left={left}", "--run", f"right={right}",
                     "--qrels", labels, "--input-format", "trec", "--qrels-format", "trec",
                     "--cutoffs", "1,2", "--out", out)
    assert process.returncode == 0, process.stderr
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["provenance"]["command"] == "compare"
    assert report["pairs"][0]["matched_pool_comparison"]["delta_right_minus_left"]["mrr@1"]["delta"] == -1
    assert [digest(path) for path in (left, right, labels)] == originals


@pytest.mark.parametrize("arguments", [[], ["--run", "one=a.csv"],
    ["--input", "a.csv", "--run", "b=b.csv"], ["--qrels", "labels.csv"]])
def test_incomplete_or_conflicting_options_do_not_create_a_report(tmp_path, arguments):
    if not arguments:
        arguments = ["--input", "missing.csv"]
    out = tmp_path / "absent"
    process = invoke(tmp_path, *arguments, "--out", out)
    assert process.returncode == 2
    assert not out.exists()


def test_invalid_source_and_existing_destination_are_preserved(tmp_path):
    source = tmp_path / "invalid.csv"
    source.write_text("query_id,item_id,score\nq1,a,not-a-score\n", encoding="utf-8")
    before = digest(source)
    out = tmp_path / "report"
    invalid = invoke(tmp_path, "--input", source, "--out", out)
    assert invalid.returncode == 2 and not out.exists()
    out.mkdir()
    (out / "keep.txt").write_text("unchanged", encoding="utf-8")
    refused = invoke(tmp_path, "--input", source, "--out", out)
    assert refused.returncode == 2
    assert "Output already exists" in refused.stderr
    assert (out / "keep.txt").read_text(encoding="utf-8") == "unchanged"
    assert digest(source) == before


def test_completed_error_findings_still_print_the_report_location(tmp_path):
    left, right = tmp_path / "left.csv", tmp_path / "right.csv"
    left.write_text("query_id,item_id,score,relevance\nq1,a,1,1\n", encoding="utf-8")
    right.write_text("query_id,item_id,score,relevance\nq1,a,1,0\n", encoding="utf-8")
    out = tmp_path / "completed"
    process = invoke(tmp_path, "--run", f"left={left}", "--run", f"right={right}", "--out", out)
    assert process.returncode == 1, (process.stdout, process.stderr)
    assert (out / "report.html").is_file()
    assert "Report completed with error findings" in process.stdout
    assert str(out / "report.html") in process.stdout
