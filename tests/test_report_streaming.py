import json
import os
from unittest.mock import patch

import pytest

from rankprobe.report import write_report


def test_complete_json_keeps_original_bytes_and_all_rows(tmp_path):
    report = {"report_type": "audit", "findings": [], "diagnostics": {"rows": [
        {"query_id": "查询-" + str(i), "item_id": "0001", "score": 2**63+i,
         "relevance": None} for i in range(2000)]}}
    expected = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").replace("\n", os.linesep).encode("utf-8")
    json_file, html_file = write_report(report, tmp_path)
    assert json_file.read_bytes() == expected
    assert json.loads(json_file.read_text(encoding="utf-8")) == report
    assert html_file.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_partial_json_disk_failure_preserves_both_existing_reports(tmp_path):
    write_report({"findings": []}, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    def interrupted(value, handle, **options):
        handle.write('{"unfinished":')
        raise OSError("simulated disk full while writing JSON")

    with patch("rankprobe.report.json.dump", side_effect=interrupted):
        with pytest.raises(OSError, match="disk full"):
            write_report({"findings": [], "value": 1}, tmp_path, overwrite=True)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_invalid_value_after_valid_prefix_leaves_no_partial_new_report(tmp_path):
    destination = tmp_path / "new-report"
    report = {"many_valid_values": list(range(5000)), "invalid_tail": float("nan")}
    with pytest.raises(ValueError):
        write_report(report, destination)
    assert not (destination / "report.json").exists()
    assert not (destination / "report.html").exists()
    assert not list(destination.glob(".rankprobe-*"))
