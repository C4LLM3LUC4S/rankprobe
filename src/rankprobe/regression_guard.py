"""An optional engineering rule over a newly computed, fully matched MRR pair."""

from __future__ import annotations

import math
import re


FORMAT = "rankprobe-mrr-regression-guard-v1"
RULE = "known_first_relevant_prefix"


def make_policy(metric: str, max_drop: float, min_queries: int, baseline_sha256: str) -> dict:
    if not isinstance(metric, str) or re.fullmatch(r"mrr@[1-9][0-9]*", metric) is None:
        raise ValueError("--max-mrr-drop needs mrr@K=DROP, for example mrr@10=0.01")
    if type(max_drop) not in (int, float) or not math.isfinite(max_drop) or not 0 <= max_drop <= 1:
        raise ValueError("MRR drop must be a finite number from 0 to 1")
    if type(min_queries) is not int or min_queries < 1:
        raise ValueError("--min-guard-queries must be a positive integer")
    if not isinstance(baseline_sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", baseline_sha256) is None:
        raise ValueError("--guard-baseline-sha256 needs the frozen baseline file's 64-digit SHA256")
    return {"metric": metric, "max_absolute_drop": max_drop,
            "min_queries": min_queries, "baseline_sha256": baseline_sha256.lower(),
            "coverage_rule": "all_submitted_queries", "reference": "submitted_candidates",
            "eligibility_rule": RULE}


def decide(report: dict, policy: dict, sources: list[dict]) -> dict:
    """Call only with this invocation's compare_runs result; not a saved-report reader."""
    reasons = []

    def block(code, message):
        reasons.append({"code": code, "message": message})

    names = list(report["runs"])
    left, right = names
    baseline = next(source for source in sources
                    if source["role"] == "predictions" and source["run_name"] == left)
    pair = report["pairs"][0]
    matched = pair["matched_pool_comparison"]
    query_ids = matched["query_ids"]
    metric = policy["metric"]
    a, b = matched["left_metrics"][metric], matched["right_metrics"][metric]
    delta = matched["delta_right_minus_left"][metric]
    if baseline["sha256"] != policy["baseline_sha256"]:
        block("baseline_hash_mismatch", "基线文件与事先固定的摘要不符，请核对原文件。 / Baseline SHA256 does not match the declared frozen file.")
    if pair["status"] != "comparable":
        block("comparison_scope_mismatch", "两份结果的查询、候选或已解析标签不一致，不能按局部差值放行。 / Query, candidate or resolved-label scope differs.")
    if any(f["severity"] == "error" for f in report["findings"]):
        block("error_findings", "报告包含错误级发现，先核查原始输入。 / Resolve error findings before a regression decision.")
    if any(run["audit"]["summary"]["duplicate_rows"] for run in report["runs"].values()):
        block("duplicate_candidates", "输入含重复候选，先核查导出，不能只按去重后的分数放行。 / Duplicate input candidates need source review.")
    if (report["protocol"]["unjudged"] != "unknown"
            or any(run["audit"]["summary"]["assumed_nonrelevant_candidates"]
                   or run["audit"]["summary"]["implicit_complete_qrels_zeros"]
                   for run in report["runs"].values())):
        block("zero_label_assumption", "这条检查要求保留未知标签，不能用补零假设放行。 / This guard requires unknown judgments to stay unknown.")
    if (not query_ids or len(query_ids) < policy["min_queries"]
            or any(run["queries"] != len(query_ids) for run in report["runs"].values())):
        block("insufficient_full_query_scope", "完整匹配的查询数量不足，或未覆盖双方全部提交查询。 / The complete matched query population is too small or incomplete.")
    if any(m["eligible_query_ids"] != query_ids or m["evaluated_queries"] != len(query_ids)
           for m in (a, b)):
        block("incomplete_metric_eligibility", "并非每个提交查询都能计算这项 MRR；未知标签不能当零或排除后放行。 / Every submitted query must be metric-eligible.")
    if any(m["reference"] != policy["reference"] or m.get("eligibility_rule") != policy["eligibility_rule"]
           for m in (a, b)):
        block("metric_rule_mismatch", "MRR 参考范围或资格规则不匹配。 / MRR reference or eligibility rule differs.")
    values = (a["value"], b["value"], delta.get("delta"))
    if delta["status"] != "checked" or any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        block("metric_unavailable", "没有可用的完整 MRR 差值，不能视为零或通过。 / A checked finite MRR delta is unavailable.")
    status = "blocked" if reasons else "failed_drop" if delta["delta"] < -policy["max_absolute_drop"] else "pass"
    actions = {
        "blocked": "先核对原基线、完整导出、标签和查询范围，再用新目录重试；不要删查询、补零或事后改门槛。",
        "failed_drop": "保留两份输入、报告和声明门槛，检查排序变化；如需修改模型，另做新比较，不覆盖这次失败。",
        "pass": "这份输入满足了已声明的 MRR 容忍规则。保留基线、协议、门槛和报告，供下次按相同约定检查。",
    }
    return {"format": FORMAT, "status": status, "policy": policy, "baseline": left, "candidate": right,
            "baseline_actual_sha256": baseline["sha256"], "metric": metric,
            "baseline_value": a["value"], "candidate_value": b["value"],
            "delta_right_minus_left": delta.get("delta"),
            "query_ids": query_ids, "evaluated_queries": {left: a["evaluated_queries"], right: b["evaluated_queries"]},
            "reasons": reasons, "next_step": actions[status],
            "scope": "A predeclared absolute MRR tolerance over the supplied, fully matched query/candidate pool under one current protocol; not statistical significance, model-quality, provenance or leakage certification."}
