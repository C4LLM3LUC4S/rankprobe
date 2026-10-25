"""An opt-in CI tolerance cannot pass on changed or unavailable comparison scope."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from unittest.mock import patch

import pytest

from rankprobe.audit import compare_runs
from rankprobe.cli import main
from rankprobe.model import Protocol, Row
from rankprobe.regression_guard import decide, make_policy


GOOD = "query_id,item_id,score,relevance\nq1,a,2,1\nq1,b,1,0\nq2,a,2,1\nq2,b,1,0\n"
BAD = GOOD.replace("q1,a,2,1\nq1,b,1,0", "q1,a,1,1\nq1,b,2,0")


def invoke(arguments):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        result = main(arguments)
    return result, out.getvalue(), err.getvalue()


def files(tmp_path, baseline=GOOD, candidate=BAD):
    left, right = tmp_path / "frozen baseline.csv", tmp_path / "new candidate.csv"
    left.write_text(baseline, encoding="utf-8")
    right.write_text(candidate, encoding="utf-8")
    return left, right


def command(left, right, target, drop="0.1", minimum=2, sha=None):
    return ["compare", "--run", f"frozen={left}", "--run", f"new={right}",
            "--cutoffs", "1", "--max-mrr-drop", f"mrr@1={drop}",
            "--min-guard-queries", str(minimum), "--guard-baseline-sha256",
            sha or hashlib.sha256(left.read_bytes()).hexdigest(), "--fail-on", "never", "--out", str(target)]


def read(target):
    assert (target / "report.html").is_file()
    return json.loads((target / "report.json").read_text(encoding="utf-8"))


def test_existing_compare_passes_structural_checks_but_opt_in_catches_drop(tmp_path):
    left, right = files(tmp_path)
    before = {p: p.read_bytes() for p in (left, right)}
    old = ["compare", "--run", f"frozen={left}", "--run", f"new={right}", "--cutoffs", "1",
           "--out", str(tmp_path / "old")]
    assert invoke(old)[0] == 0
    assert "regression_guard" not in read(tmp_path / "old")
    target = tmp_path / "guarded"
    assert invoke(command(left, right, target))[0] == 1
    report = read(target)
    guard = report["regression_guard"]
    assert guard["status"] == "failed_drop" and guard["delta_right_minus_left"] == -0.5
    assert guard["query_ids"] == ["q1", "q2"] and not guard["reasons"]
    identity = report["provenance"]["regression_guard"]["source_identity"]
    assert identity["status"] == "available" and len(identity["sha256"]) == 64
    html = (target / "report.html").read_text(encoding="utf-8")
    assert html.index('id="regression-guard"') < html.index('id="pairs"')
    assert "MRR 下降超过门槛" in html and "统计显著" in html
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("baseline,candidate,drop", [(GOOD, BAD, "0.5"), (BAD, GOOD, "0"), (GOOD, GOOD, "0")])
def test_exact_boundary_improvement_and_unchanged_pass(tmp_path, baseline, candidate, drop):
    left, right = files(tmp_path, baseline, candidate)
    target = tmp_path / "fresh"
    assert invoke(command(left, right, target, drop))[0] == 0
    assert read(target)["regression_guard"]["status"] == "pass"


@pytest.mark.parametrize("candidate,reason", [
    (GOOD.split("q2,a")[0], "comparison_scope_mismatch"),
    (GOOD.replace("q1,b,1,0\n", ""), "comparison_scope_mismatch"),
    (GOOD.replace("q1,a,2,1", "q1,a,2,"), "comparison_scope_mismatch"),
    (GOOD + "q1,a,3,1\n", "duplicate_candidates"),
])
def test_changed_query_candidate_judgment_and_duplicate_block(tmp_path, candidate, reason):
    left, right = files(tmp_path, GOOD, candidate)
    target = tmp_path / "fresh"
    assert invoke(command(left, right, target, "1"))[0] == 1
    guard = read(target)["regression_guard"]
    assert guard["status"] == "blocked"
    assert reason in {r["code"] for r in guard["reasons"]}


def test_same_count_different_eligible_sets_cannot_pass(tmp_path):
    left, right = files(tmp_path, GOOD.replace("q1,a,2,1", "q1,a,2,"),
                        GOOD.replace("q2,a,2,1", "q2,a,2,"))
    target = tmp_path / "fresh"
    assert invoke(command(left, right, target, "1", minimum=1))[0] == 1
    report = read(target)
    assert report["runs"]["frozen"]["metrics"]["mrr@1"]["evaluated_queries"] == 1
    assert report["runs"]["new"]["metrics"]["mrr@1"]["evaluated_queries"] == 1
    assert report["regression_guard"]["status"] == "blocked"


def test_unknowns_after_first_relevant_remain_unknown_but_mrr_can_pass(tmp_path):
    text = GOOD.replace("q1,b,1,0", "q1,b,1,")
    left, right = files(tmp_path, text, text)
    target = tmp_path / "fresh"
    assert invoke(command(left, right, target, "0"))[0] == 0
    report = read(target)
    assert report["regression_guard"]["status"] == "pass"
    for run in report["runs"].values():
        assert run["audit"]["summary"]["unknown_candidates"] == 1
        assert run["audit"]["summary"]["assumed_nonrelevant_candidates"] == 0


def test_unavailable_mrr_minimum_hash_and_zero_assumption_block(tmp_path):
    unknown = GOOD.replace("q1,a,2,1", "q1,a,2,").replace("q2,a,2,1", "q2,a,2,")
    left, right = files(tmp_path, unknown, unknown)
    for name, options, reason in (
        ("unavailable", {}, "metric_unavailable"),
        ("minimum", {"minimum": 3}, "insufficient_full_query_scope"),
        ("hash", {"sha": "0" * 64}, "baseline_hash_mismatch"),
    ):
        target = tmp_path / name
        assert invoke(command(left, right, target, **options))[0] == 1
        guard = read(target)["regression_guard"]
        assert guard["status"] == "blocked" and reason in {r["code"] for r in guard["reasons"]}
        assert guard["baseline_value"] is None
    target = tmp_path / "zero-assumption"
    assert invoke(command(left, right, target) + ["--unjudged", "nonrelevant"])[0] == 1
    assert "zero_label_assumption" in {r["code"] for r in read(target)["regression_guard"]["reasons"]}


@pytest.mark.parametrize("change", ["missing", "badsha", "badmetric", "absentcutoff", "negative", "nan", "minimum", "three"])
def test_invalid_guard_options_fail_before_inputs_or_output(tmp_path, change):
    left, right = files(tmp_path)
    target = tmp_path / "not-created"
    args = command(left, right, target)
    if change == "missing":
        at = args.index("--min-guard-queries")
        del args[at:at + 2]
    elif change == "three":
        args += ["--run", f"third={right}"]
    else:
        flag, value = {"badsha": ("--guard-baseline-sha256", "z" * 64),
                       "badmetric": ("--max-mrr-drop", "ndcg@1=0.1"),
                       "absentcutoff": ("--max-mrr-drop", "mrr@2=0.1"),
                       "negative": ("--max-mrr-drop", "mrr@1=-0.1"),
                       "nan": ("--max-mrr-drop", "mrr@1=NaN"),
                       "minimum": ("--min-guard-queries", "0")}[change]
        args[args.index(flag) + 1] = value
    with patch("rankprobe.cli._load_checked", side_effect=AssertionError("No input read")):
        try:
            result = invoke(args)[0]
        except SystemExit as exc:
            result = exc.code
    assert result == 2 and not target.exists()


def test_output_preflight_and_existing_report_are_preserved(tmp_path):
    left, right = files(tmp_path)
    target = tmp_path / "old"
    target.mkdir()
    marker = target / "report.html"
    marker.write_text("original", encoding="utf-8")
    with patch("rankprobe.cli._load_checked", side_effect=AssertionError("No input read")):
        assert invoke(command(left, right, target))[0] == 2
    assert marker.read_text(encoding="utf-8") == "original"


def test_complete_qrels_closure_does_not_create_guard_eligibility(tmp_path):
    unknown = GOOD.replace(",0\n", ",\n")
    left, right = files(tmp_path, unknown, unknown)
    judgments = tmp_path / "positive only.csv"
    judgments.write_text("query_id,item_id,relevance\nq1,a,1\nq2,a,1\n", encoding="utf-8")
    target = tmp_path / "closure"
    assert invoke(command(left, right, target) + ["--qrels", str(judgments), "--qrels-complete"])[0] == 1
    report = read(target)
    assert "zero_label_assumption" in {r["code"] for r in report["regression_guard"]["reasons"]}
    assert report["runs"]["frozen"]["audit"]["summary"]["implicit_complete_qrels_zeros"] == 2


def test_decision_checks_reference_and_rule_even_with_finite_matching_counts():
    report = compare_runs({"a": [Row("q", "a", 1, 1)], "b": [Row("q", "a", 1, 1)]}, Protocol(cutoffs=(1,)))
    sources = [{"role": "predictions", "run_name": "a", "sha256": "a" * 64}]
    policy = make_policy("mrr@1", 0, 1, "a" * 64)
    for key, value in (("reference", "known_qrels_pool"), ("eligibility_rule", "legacy_all_known")):
        metric = report["pairs"][0]["matched_pool_comparison"]["right_metrics"]["mrr@1"]
        old = metric[key]
        metric[key] = value
        decision = decide(report, policy, sources)
        assert decision["status"] == "blocked"
        assert "metric_rule_mismatch" in {r["code"] for r in decision["reasons"]}
        metric[key] = old
