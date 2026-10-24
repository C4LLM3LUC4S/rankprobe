"""A rejected CSV header points back to a fresh, data-preserving source export."""

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from rankprobe import Row
from rankprobe.io import read_predictions, read_qrels


PACKAGE_PARENT = Path(sys.modules["rankprobe"].__file__).resolve().parent.parent


def invoke(folder, *arguments):
    script = "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    script += "sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8'); "
    script += "from rankprobe.cli import main; raise SystemExit(main(sys.argv[1:]))"
    return subprocess.run(
        [sys.executable, "-I", "-c", script, str(PACKAGE_PARENT), *map(str, arguments)],
        cwd=folder, capture_output=True, encoding="utf-8", timeout=30, check=False,
    )


@pytest.mark.parametrize("kind", ["predictions", "qrels"])
def test_tab_header_recovery_rejects_without_output_then_keeps_source_values(tmp_path, kind):
    if kind == "predictions":
        tokens = [["query_id", "item_id", "score", "relevance"],
                  ["查询_001", "0008", "1.25", ""], ["查询_001", "0009", "0.5", "1"]]
        required = "item_id, query_id, score"
    else:
        tokens = [["query_id", "item_id", "relevance"],
                  ["查询_001", "0008", "1"], ["查询_001", "0009", "0"]]
        required = "item_id, query_id, relevance"
    original = tmp_path / "original.csv"
    original.write_text("\n".join("\t".join(row) for row in tokens) + "\n", encoding="utf-8")
    original_bytes = original.read_bytes()
    predictions = tmp_path / "predictions.csv"
    predictions.write_text("query_id,item_id,score\n查询_001,0008,3\n查询_001,0009,2\n查询_001,0010,1\n",
                           encoding="utf-8")

    def arguments(path):
        return [path] if kind == "predictions" else [predictions, "--qrels", path]

    output = tmp_path / "report"
    failed = invoke(tmp_path, "audit", *arguments(original), "--out", output)
    assert failed.returncode == 2
    assert failed.stdout == "" and "Traceback" not in failed.stderr
    assert f"{original}: missing columns: {required}" in failed.stderr
    assert "comma-separated" in failed.stderr and "exact column names" in failed.stderr
    assert "new CSV from the original source" in failed.stderr
    assert "unknown labels" in failed.stderr and "row order" in failed.stderr
    assert "原文件" in failed.stderr and "英文逗号" in failed.stderr
    assert not output.exists()
    assert original.read_bytes() == original_bytes

    # This is an explicitly authored source re-export, not delimiter guessing.
    fresh = tmp_path / "fresh.csv"
    with fresh.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(tokens)
    with fresh.open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == tokens
    succeeded = invoke(tmp_path, "audit", *arguments(fresh), "--out", output,
                       "--cutoffs", "1,2", "--fail-on", "never")
    assert succeeded.returncode == 0, succeeded.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["unknown_candidates"] == 1
    assert report["summary"]["assumed_nonrelevant_candidates"] == 0
    assert report["protocol"]["unjudged"] == "unknown"
    if kind == "predictions":
        assert read_predictions(fresh) == [Row("查询_001", "0008", 1.25), Row("查询_001", "0009", 0.5, 1)]
    else:
        assert read_qrels(fresh) == {"查询_001": {"0008": 1, "0009": 0}}
    assert original.read_bytes() == original_bytes
    assert report["provenance"]["sources"][-1]["sha256"] == hashlib.sha256(
        (fresh if kind == "predictions" else predictions).read_bytes()
    ).hexdigest()


def test_valid_comma_csv_with_quoted_tabs_keeps_literal_identifiers_and_unknowns(tmp_path):
    predictions = tmp_path / "predictions.csv"
    predictions.write_text('query_id,item_id,score,relevance,metadata\n"q\t001",0008,1.25,,"tab\ttext; stays"\n',
                           encoding="utf-8")
    qrels = tmp_path / "qrels.csv"
    qrels.write_text('query_id,item_id,relevance\n"q\t001",0008,1\n', encoding="utf-8")
    before = {path: path.read_bytes() for path in (predictions, qrels)}
    assert read_predictions(predictions) == [Row("q\t001", "0008", 1.25)]
    assert read_qrels(qrels) == {"q\t001": {"0008": 1}}
    assert all(path.read_bytes() == payload for path, payload in before.items())
