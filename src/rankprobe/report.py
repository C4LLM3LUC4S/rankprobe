"""Self-contained, escaped HTML reports and careful report file writing."""

from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

EVIDENCE_LIMIT = 20
TABLE_LIMIT = 60

FINDING_NEXT_STEPS = {
    "query_coverage_mismatch": "Check the missing query IDs against the intended evaluation set. Restore omitted predictions if accidental; inspect the matched-pool results before interpreting an aggregate change.",
    "candidate_set_mismatch": "Inspect the query IDs and candidate differences; check whether selection changed intentionally. For reranking, export scores from the same actual candidate stage. For complete retrieval systems, evaluate the original runs under a separately justified retrieval protocol. Do not intersect results or invent missing scores or judgments to force a matched-pool delta.",
    "cross_run_label_mismatch": "Resolve the listed query-item judgment differences at their source. Rerun both exports with the same judgments before attributing a change to the model.",
    "unknown_judgments": "Inspect metric coverage and exclusion reasons. Obtain missing judgments where possible; do not select a zero assumption just to make a metric available.",
    "explicit_unjudged_qrels": "Review the listed unjudged pairs against the judgment source. Keep them unknown unless an explicit convention is justified; these qrels do not support a completeness assertion.",
    "qrels_queries_without_predictions": "Check whether the listed queries should have predictions. Restore missing exports or state the narrower evaluation universe alongside the result.",
    "missing_qrels_queries": "Check query ID alignment and supply judgments for the missing queries. Reconsider the completeness assertion if those judgments do not exist.",
    "duplicate_candidates": "Trace the repeated pairs to the export or sampling step. Inspect duplicate sensitivity before deciding whether to fix the source or document intentional repetitions.",
    "score_ties": "Inspect tie bounds and the input-order probe. Check score precision and declare the same tie policy for all compared runs.",
    "constant_scores": "Check that the exported values are the intended model scores. Inspect the constant-score control; tie ordering alone can produce a nonzero metric.",
    "limited_reference_pool": "Report the displayed reference pool with NDCG. Supply independent, justified complete judgments before interpreting full Recall; a flag alone does not establish completeness.",
    "unjudged_assumed_nonrelevant": "Document why the zero assumption is justified and compare with unknown labels preserved. This assumption does not add source judgments.",
    "empty_run": "Check the export path and filters, then supply prediction rows before interpreting ranking metrics.",
}

FINDING_COPY_ZH = {
    "query_coverage_mismatch": ("两份结果包含的查询不同", "平均分可能因为少算了某些查询而变化，并不一定是排序变好了。", "先核对缺少的查询。如果确实漏导出，从原始预测中恢复后再比较；如果范围本来就不同，请说明原因。"),
    "candidate_set_mismatch": ("同一查询的候选项不同", "分数差异可能来自候选项变化，也可能来自排序变化。", "先确认要比较同一批候选的排序，还是两个完整检索系统。前者需要同一阶段的原始分数；后者需要另行明确检索评测规则，不要删掉不同项来强行对齐。"),
    "cross_run_label_mismatch": ("两份结果使用的标签不一致", "相同查询和候选的标签不同，或一边有标签、另一边没有。", "回到标签来源核对。用一致的标签重新评测之前，不把差异归因于模型。"),
    "unknown_judgments": ("有些候选还不知道是否相关", "缺少相关性标签时，部分查询或指标可能无法计算；这不表示它们得了零分。", "展开指标明细，查看哪些查询没参与计算。能找到原有标签时再补充，不要为了显示分数把未知标签填成零。"),
    "explicit_unjudged_qrels": ("标签文件里有“还没判断”的标记", "这个来源没有给出相关性判断。如果预测文件里已有标签，会保留已有标签；其余项目按你选定的未知标签规则处理。", "先核对原始标签的约定。这类标记不能支持“标签完整”的声明，也不要为了算出分数把未知填成零。"),
    "qrels_queries_without_predictions": ("有标签的查询没有出现在预测结果中", "报告只能分析已经提交的预测，不能替缺失查询生成分数。", "确认这些查询是否本应参与评测。若是漏导出，请从原始结果恢复；否则说明本次只评测了哪些查询。"),
    "missing_qrels_queries": ("部分查询找不到对应的标签", "查询标识可能没有对上，也可能缺少标签资料。", "先核对查询标识和标签文件。资料不完整时，重新考虑是否有依据声明标签完整。"),
    "duplicate_candidates": ("同一查询中有候选重复出现", "重复项可能影响排序位置和分数。是否需要修正，要看它们为何重复。", "检查导出或采样步骤，再看去重前后的指标差异。如果重复是有意保留的，记录原因和处理规则。"),
    "score_ties": ("有候选的分数完全相同", "同分候选换一种顺序，指标可能就会变化。", "查看同分换序能带来多大差异，再检查分数精度。比较多个运行时，使用同一种同分处理规则。"),
    "constant_scores": ("有些查询里的候选分数全都一样", "对这些查询来说，排序完全取决于同分处理方式。即使算出了非零分数，也不能说明候选分数区分出了相关项目。", "先确认导出的是你想检查的模型分数，再看看报告里的固定分数对照。"),
    "limited_reference_pool": ("分数只反映当前提供的候选和标签", "NDCG 使用的比较范围有限，不能直接当成整个检索库的表现。", "报告分数时说明计算范围。Recall 需要有依据的完整相关项信息，打开一个开关不能让标签变完整。"),
    "unjudged_assumed_nonrelevant": ("这次把未标注项目按不相关处理", "这是评测时采用的假设，并没有增加任何真实标签。", "记录采用这个假设的依据，并保留一份未知标签不填零的结果作为对照。"),
    "empty_run": ("没有读到候选分数", "当前没有可用于排序评测的记录。", "检查导出路径和筛选条件，确认文件里有预期的查询、候选及原始分数后再运行。"),
}


def _float_text(value: float, *, signed: bool = False) -> str:
    compact = format(value, "+.6g" if signed else ".6g")
    # A rounded 1 (or any other whole number) can falsely suggest an exact
    # result. Use the shortest round-trippable spelling at that boundary.
    if math.isfinite(value) and float(compact).is_integer() and float(compact) != value:
        return format(value, "+") if signed else repr(value)
    return compact


def _text(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return _float_text(value) if math.isfinite(value) else "Not finite"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _esc(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _table(records: list[Mapping[str, Any]], limit: int = TABLE_LIMIT) -> str:
    if not records:
        return '<p class="muted">No rows to display.</p>'
    keys = list(dict.fromkeys(str(key) for row in records[:limit] for key in row))
    # Evidence remains downloadable as JSON; cap visual complexity in a browser.
    keys = keys[:12]
    head = "".join(f'<th scope="col">{_esc(_label(key))}</th>' for key in keys)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(row.get(key))}</td>" for key in keys) + "</tr>"
        for row in records[:limit]
    )
    note = (
        f'<p class="muted">Showing {min(len(records), limit)} of {len(records)} rows. '
        'See <a href="report.json">report.json</a> for the full stored evidence.</p>'
        if len(records) > limit
        else ""
    )
    return f'<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable data table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}'


def _content(value: Any, limit: int = TABLE_LIMIT) -> str:
    if isinstance(value, Mapping):
        rows = [{"field": _label(str(key)), "value": item} for key, item in value.items()]
        return _table(rows, limit)
    if isinstance(value, (list, tuple)):
        if not value:
            return '<p class="muted">No entries.</p>'
        if all(isinstance(item, Mapping) for item in value):
            return _table(list(value), limit)
        items = "".join(f"<li>{_esc(item)}</li>" for item in value[:limit])
        note = (
            f'<p class="muted">Showing {limit} of {len(value)} entries; full data is in report.json.</p>'
            if len(value) > limit
            else ""
        )
        return f"<ul>{items}</ul>{note}"
    return f"<p>{_esc(value)}</p>"


def _metrics(value: Any, json_path: str | None = None) -> str:
    if isinstance(value, Mapping):
        records = []
        for name, metric in value.items():
            if isinstance(metric, Mapping):
                visible = {
                    key: metric[key]
                    for key in (
                        "value",
                        "delta",
                        "min",
                        "max",
                        "width",
                        "status",
                        "evaluated_queries",
                        "total_queries",
                        "excluded_queries",
                        "reference",
                        "reason",
                    )
                    if key in metric
                }
                records.append({"metric": name, **visible})
            else:
                records.append({"metric": name, "value": metric})
        note = '<p class="muted" lang="zh-CN">表里的 Value 是分数，Evaluated queries / Total queries 表示用了多少查询。partial 表示计算范围有限；not_checked 表示这次没有条件计算。Min 和 Max 是同分候选换序时可能得到的范围，不是置信区间。</p><details><summary>English field guide</summary><p class="muted">Status <strong>partial</strong> means limited coverage or a candidate-pool reference; <strong>not_checked</strong> means the data or protocol does not support this metric. A missing value is not zero.</p></details>'
        details = []
        for name, metric in list(value.items())[:TABLE_LIMIT]:
            if not isinstance(metric, Mapping):
                continue
            coverage = {
                key: metric[key]
                for key in (
                    "eligibility_rule",
                    "query_universe",
                    "qrels_only_queries",
                    "exclusion_reasons",
                    "eligible_query_ids",
                    "excluded_query_ids",
                )
                if key in metric
            }
            if coverage:
                location = (
                    f'<p class="code">JSON: {_esc(json_path)}[{_esc(json.dumps(str(name)))}]</p>'
                    if json_path
                    else ""
                )
                details.append(
                    f'<details><summary>{_esc(name)}: coverage details</summary>{location}{_diagnostics(coverage, EVIDENCE_LIMIT)}</details>'
                )
        return note + _table(records) + "".join(details)
    return _content(value)


def _partial_perfect_context(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    notes = []
    for name, metric in list(value.items())[:TABLE_LIMIT]:
        if not (
            isinstance(name, str)
            and re.fullmatch(r"(?:mrr|ndcg|recall)@[1-9][0-9]*", name)
            and isinstance(metric, Mapping)
        ):
            continue
        score = metric.get("value")
        evaluated, total = metric.get("evaluated_queries"), metric.get("total_queries")
        if (
            metric.get("status") == "partial"
            and isinstance(score, (int, float))
            and not isinstance(score, bool)
            and score == 1
            and type(evaluated) is int
            and type(total) is int
            and 0 < evaluated < total
        ):
            query_word = "query" if evaluated == 1 else "queries"
            notes.append(
                f'<p lang="zh-CN">这里的 {_esc(name)} = 1 只来自 {_esc(evaluated)} / {_esc(total)} 个查询。'
                '其余查询没有参与这个平均分，所以不能理解为所有查询都排得很好。下方明细会列出未能算分的原因。</p>'
                f'<details><summary>English explanation</summary><p class="muted">{_esc(name)} = 1 is the average over '
                f'{_esc(evaluated)} eligible {query_word} out of {_esc(total)} submitted queries. '
                'Excluded queries are not included in this average, so the value does not establish '
                'perfect results across all submitted queries. See coverage details for exclusion '
                'reasons.</p></details>'
            )
    return "".join(notes)


def _metric_cell(metric: Any, *, delta: bool = False) -> str:
    if not isinstance(metric, Mapping):
        return _text(metric)
    value = metric.get("delta" if delta else "value")
    if delta and isinstance(value, float) and math.isfinite(value):
        rendered = _float_text(value, signed=True)
    elif delta and type(value) is int:
        rendered = f"{value:+}"
    else:
        rendered = _text(value)
    lines = [rendered, f"status: {_text(metric.get('status'))}"]
    if "evaluated_queries" in metric:
        count = _text(metric["evaluated_queries"])
        total = f" / {_text(metric['total_queries'])}" if "total_queries" in metric else ""
        lines.append(f"metric-eligible queries: {count}{total}")
    for key in (("reference", "reason") if delta else ("reference",)):
        if key in metric:
            lines.append(f"{key}: {_text(metric[key])}")
    return "\n".join(lines)


def _comparison_reader(
    pair: Mapping[str, Any], sources: list[Mapping[str, Any]], protocol: Any,
) -> str:
    left, right = pair.get("left"), pair.get("right")
    coverage = pair.get("query_coverage", {})
    coverage = coverage if isinstance(coverage, Mapping) else {}
    matched = pair.get("matched_pool_comparison", {})
    matched = matched if isinstance(matched, Mapping) else {}
    candidates = pair.get("candidate_sets", {})
    candidates = candidates if isinstance(candidates, Mapping) else {}
    counts = (
        f'<p lang="zh-CN"><strong>先看比较用了哪些查询：</strong>'
        f'{_esc(left)} 提交了 {_esc(coverage.get("left_queries"))} 个，'
        f'{_esc(right)} 提交了 {_esc(coverage.get("right_queries"))} 个。'
        f'其中 {_esc(matched.get("query_count"))} 个查询在两边都出现，而且候选项相同。'
        '每个指标还可能因为标签不足等原因少算一些查询，具体数量标在分数旁。</p>'
    )
    different_queries = any(
        isinstance(coverage.get(key), int) and coverage[key] > 0
        for key in ("left_only_count", "right_only_count")
    )
    if different_queries:
        action = (
            '两份结果包含的查询不同。先找到缺少的是哪些查询；如果是漏导出，从原始结果恢复后再比较。'
            '如果本来就只想评测其中一部分，请说明这个范围。'
        )
    elif isinstance(candidates.get("differing_queries"), int) and candidates["differing_queries"] > 0:
        action = (
            '同一个查询的候选项不同。先确认你要比较的是“同一批候选怎样排序”，还是两个完整检索系统。'
            '不要删掉不同的候选、编造分数或补标签来凑成相同集合。'
        )
    else:
        action = (
            '比较同一张卡片里的两个结果，同时核对分数旁的查询数量和计算范围。'
            '如果某个值无法计算，先展开下方明细查看原因，不要把它当作零分。'
        )

    def compact(metric: Any, *, delta: bool = False) -> str:
        if not isinstance(metric, Mapping):
            return _esc(None)
        value = metric.get("delta" if delta else "value")
        if delta and isinstance(value, float) and math.isfinite(value):
            text = _float_text(value, signed=True)
        elif delta and type(value) is int:
            text = f"{value:+}"
        else:
            text = _text(value)
        if value is None:
            text = "无法计算 / Not available"
        count = ""
        if "evaluated_queries" in metric:
            total = f' / {_esc(metric["total_queries"])}' if "total_queries" in metric else ""
            count = (
                f' <small>（用了 {_esc(metric["evaluated_queries"])}{total} 个查询）</small>'
            )
        scope = (
            ' <small>· 仅限当前范围</small>'
            if metric.get("status") == "partial" else ""
        )
        return f'<strong>{_esc(text)}</strong>{count}{scope}'

    cutoffs = protocol.get("cutoffs", ()) if isinstance(protocol, Mapping) else ()
    cutoffs = [k for k in cutoffs if type(k) is int and k > 0] if isinstance(cutoffs, (list, tuple)) else []
    previews = []
    if cutoffs:
        k = max(cutoffs)
        for metric in ("mrr", "ndcg"):
            name = f"{metric}@{k}"
            if not any(name in source for source in sources):
                continue
            references = []
            for source in sources[2:4]:
                value = source.get(name, {})
                references.append(value.get("reference") if isinstance(value, Mapping) else None)
            reference_labels = {
                "submitted_candidates": "本次提交的候选项（submitted candidates）",
                "candidate_pool": "本次提交的候选项（candidate pool）",
                "known_qrels_pool": "已有标签对应的项目（supplied judgments）",
                "complete_qrels": "使用者声明完整的标签集合（declared complete judgments）",
                "unavailable": "暂无可用的计算范围",
            }
            reference_text = [
                reference_labels.get(value, value) if isinstance(value, str) else value
                for value in references
            ]
            reference = (
                _esc(reference_text[0]) if references[0] == references[1] else
                f'{_esc(left)}: {_esc(reference_text[0])}; {_esc(right)}: {_esc(reference_text[1])}'
            )
            previews.append(
                f'<div class="metric-preview"><h4>{_esc(name)}</h4><dl>'
                '<dt>同一批查询和候选上的平均分</dt>'
                f'<dd>{_esc(left)}: {compact(sources[2].get(name))}<br>'
                f'{_esc(right)}: {compact(sources[3].get(name))}</dd>'
                f'<dt>分数差（{_esc(right)} − {_esc(left)}）</dt>'
                f'<dd>{compact(sources[4].get(name), delta=True)}</dd></dl>'
                f'<p class="muted">计算范围：{reference}。</p>'
                '<details><summary>查看两次运行各自的平均分</summary><p>这里各自使用能够算分的查询，两边的查询可能不同，不能只看谁的平均分更高。</p><dl>'
                '<dt>各自平均 / Per-run averages</dt>'
                f'<dd>{_esc(left)}: {compact(sources[0].get(name))}<br>'
                f'{_esc(right)}: {compact(sources[1].get(name))}</dd></dl></details></div>'
            )
    preview = ""
    if previews:
        preview = (
            f'<p>先看前 {_esc(k)} 个结果的表现。这是你要求的最大截断位置（k={_esc(k)}）；'
            '其他位置的分数保留在下方完整表格里。</p>'
            f'<div class="metric-previews">{"".join(previews)}</div>'
        )
    return (
        '<aside class="comparison-reader" aria-label="Comparison reading guide">'
        '<h4 lang="zh-CN">这两份结果可以直接比较吗？</h4>'
        f'{counts}<p lang="zh-CN">下面先比较共同部分，分数只代表标出的查询和计算范围。'
        '请在同一张卡片内比较两次运行；MRR 和 NDCG 的计分方式不同，不能互相比较大小。</p>'
        f'{preview}<p lang="zh-CN"><strong>下一步：</strong>{action}</p>'
        '<details><summary>指标说明与 English reading guide</summary>'
        '<p lang="zh-CN">MRR 看第一个相关结果出现得有多早；NDCG 看相关结果是否排在前面，以及相关程度。'
        '“无法计算”表示当前资料不足以给出这个值，不是零分。不同指标可能使用不同数量的查询。</p>'
        '<p>Compare the two runs within one metric. The main values are matched averages: they use shared query/candidate pools, restricted to metric-eligible queries. '
        'Per-run averages are folded separately because they may cover different queries. The common-query count is not the number eligible for every metric. '
        'Values apply only to the shown eligible queries and reference scope. MRR and NDCG values are not directly comparable. '
        'A missing value is not zero. Expand the full table for statuses, references and excluded query IDs.</p></details></aside>'
    )


def _pairwise_results(report: Mapping[str, Any]) -> str:
    runs = report.get("runs", {})
    pairs = report.get("pairs", [])
    if not isinstance(runs, Mapping) or not runs or not isinstance(pairs, list):
        return _diagnostics(pairs)
    sections = []
    for index, pair in enumerate(pairs[:TABLE_LIMIT]):
        if not isinstance(pair, Mapping):
            sections.append(_diagnostics(pair))
            continue
        left, right = pair.get("left"), pair.get("right")
        left_run, right_run = runs.get(left, {}), runs.get(right, {})
        left_metrics = left_run.get("metrics", {}) if isinstance(left_run, Mapping) else {}
        right_metrics = right_run.get("metrics", {}) if isinstance(right_run, Mapping) else {}
        matched = pair.get("matched_pool_comparison", {})
        if not isinstance(matched, Mapping):
            matched = {}
        matched_left = matched.get("left_metrics", {})
        matched_right = matched.get("right_metrics", {})
        deltas = matched.get("delta_right_minus_left", {})
        sources = [left_metrics, right_metrics, matched_left, matched_right, deltas]
        sources = [source if isinstance(source, Mapping) else {} for source in sources]
        records = [
            {
                "metric": name,
                "submitted_left": _metric_cell(sources[0].get(name)),
                "submitted_right": _metric_cell(sources[1].get(name)),
                "matched_left": _metric_cell(sources[2].get(name)),
                "matched_right": _metric_cell(sources[3].get(name)),
                "matched_delta_right_minus_left": _metric_cell(sources[4].get(name), delta=True),
            }
            for name in dict.fromkeys(name for source in sources for name in source)
        ]
        detail = {key: item for key, item in pair.items() if key != "matched_pool_comparison"}
        detail["matched_pool_scope"] = {
            key: item for key, item in matched.items()
            if key not in {"left_metrics", "right_metrics", "delta_right_minus_left"}
        }
        coverage = "".join(
            f'<details><summary>Matched {_esc(side)}: metric coverage</summary>{_metrics(metrics, f"pairs[{index}].matched_pool_comparison.{side}_metrics")}</details>'
            for side, metrics in (("left", sources[2]), ("right", sources[3]))
        )
        sections.append(
            f'<article class="finding" id="pair-{index}"><h3>{_esc(left)} → {_esc(right)}</h3>'
            f'{_comparison_reader(pair, sources, report.get("protocol"))}'
            '<details><summary>Full metric table and coverage / <span lang="zh-CN">完整指标与范围</span></summary>'
            f'<p>File-level pair status: <strong>{_esc(pair.get("status"))}</strong>. '
            f'Structurally matched queries: {_esc(matched.get("query_count"))}. '
            'The metric-eligible counts below may be smaller.</p>'
            '<p class="muted">Submitted averages can cover different queries. The matched delta applies only to its stated eligible queries and reference pool; it is not a full-run improvement or a provenance check. Positive delta means right minus left is positive.</p>'
            '<p class="muted">Scroll the table horizontally on narrow screens. Keyboard users can focus it and use the arrow keys.</p>'
            f'{_table(records)}<p class="code">JSON: pairs[{index}].matched_pool_comparison; submitted metrics: runs[run_name].metrics</p>'
            f'<details><summary>Pair scope and mismatches</summary>{_diagnostics(detail, EVIDENCE_LIMIT)}</details>{coverage}</details></article>'
        )
    if len(pairs) > TABLE_LIMIT:
        sections.append(f'<p class="muted">Showing {TABLE_LIMIT} of {len(pairs)} pairs. Full stored results are in report.json.</p>')
    return "".join(sections)


def _compared_runs(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _diagnostics(value)
    sections = []
    for index, (name, run) in enumerate(list(value.items())[:TABLE_LIMIT]):
        if not isinstance(run, Mapping) or not isinstance(run.get("audit"), Mapping):
            sections.append(
                f'<details><summary>{_esc(name)}: run diagnostics</summary>{_diagnostics(run)}</details>'
            )
            continue
        audit = run.get("audit", {})
        summary = audit.get("summary", {}) if isinstance(audit, Mapping) else {}
        focused_keys = {
            "tie_analysis": "同分会影响多少 / Tie sensitivity",
            "duplicates": "重复项会影响多少 / Duplicate sensitivity",
            "negative_controls": "改变分数和顺序后的核查 / Negative controls",
        }
        focused = "".join(
            f'<details id="run-{index}-{key}"><summary>{_esc(name)}：{label}</summary>'
            f'{_diagnostics(audit[key])}</details>'
            for key, label in focused_keys.items() if audit.get(key)
        )
        remaining = {
            key: item for key, item in audit.items()
            if key not in {"metrics", "summary", "findings", "protocol", *focused_keys}
        } if isinstance(audit, Mapping) else {}
        sections.append(
            f'<article class="finding" id="run-{index}"><h3>{_esc(name)}</h3>'
            f'<details><summary>这份输入包含什么 / Run summary</summary>{_content(summary)}</details>'
            f'<details id="run-{index}-metrics"><summary>{_esc(name)}：分数与查询范围 / Metrics and coverage</summary>'
            f'{_metrics(run.get("metrics", {}), f"runs[{json.dumps(str(name))}].metrics")}</details>'
            f'{focused}<details><summary>其他技术字段 / Remaining diagnostics</summary>'
            f'{_diagnostics(remaining)}</details></article>'
        )
    if len(value) > TABLE_LIMIT:
        sections.append(f'<p class="muted">Showing {TABLE_LIMIT} of {len(value)} runs. Full stored results are in report.json.</p>')
    return "".join(sections)


def _finding_target(report: Mapping[str, Any], finding: Mapping[str, Any]) -> tuple[str, str] | None:
    """Only link to a diagnostic that this bounded report actually renders."""
    code = finding.get("code")
    evidence = finding.get("evidence", {})
    evidence = evidence if isinstance(evidence, Mapping) else {}
    runs, pairs = report.get("runs"), report.get("pairs")
    if isinstance(runs, Mapping) and runs:
        name = finding.get("run_name", evidence.get("run_name"))
        for index, (run_name, run) in enumerate(list(runs.items())[:TABLE_LIMIT]):
            if name != run_name or not isinstance(run, Mapping) or not isinstance(run.get("audit"), Mapping):
                continue
            key, label = (
                ("tie_analysis", "同分影响") if code == "score_ties"
                else ("negative_controls", "固定分数与顺序核查") if code == "constant_scores"
                else ("duplicates", "重复项影响") if code == "duplicate_candidates"
                else ("metrics", "分数与查询范围")
            )
            if key == "metrics" or run["audit"].get(key):
                return f"run-{index}-{key}", f"看 {run_name} 的{label}"
            return f"run-{index}", f"查看 {run_name} 的运行记录"
        if isinstance(pairs, list) and "left" in evidence and "right" in evidence:
            for index, pair in enumerate(pairs[:TABLE_LIMIT]):
                if isinstance(pair, Mapping) and all(pair.get(k) == evidence[k] for k in ("left", "right")):
                    return f"pair-{index}", "查看这两份结果的比较"
    keys = (
        ("tie_analysis", "查看同分影响") if code == "score_ties"
        else ("negative_controls", "查看固定分数与顺序核查") if code == "constant_scores"
        else ("duplicates", "查看重复项影响") if code == "duplicate_candidates"
        else ("metrics", "查看分数与查询范围")
    )
    for key, label in (keys, ("pairs", "查看比较结果"), ("runs", "查看报告中的运行")):
        if report.get(key):
            return key, label
    return None


def _score_export_recheck() -> str:
    return (
        '<section id="score-export-recheck"><h2>有同分，需要改吗？ / Recheck a score export</h2>'
        '<p lang="zh-CN">先确认同分来自哪里，再决定要不要改文件。不要只为了让警告消失而改分数。</p>'
        '<ul lang="zh-CN">'
        '<li><strong>原始分数本来就相同：</strong>可以保留，说明采用的同分规则，并查看同分换序能影响哪些指标。</li>'
        '<li><strong>导出时丢了精度，原始分数还在：</strong>从同一次运行保留的分数重新导出，另存文件和报告。'
        '先确认查询、候选、标签和评测设置都没变，再核对分数、同分情况和指标差异。</li>'
        '<li><strong>没有保留原始分数：</strong>先记录无法恢复的限制。不要凭名次、标签或已舍入的值拼出新分数。</li>'
        '</ul><p lang="zh-CN">复核看的是导出是否忠实于原记录，不是警告全部消失。'
        '恢复正确后，原始分数仍可能有同分；指标相同也不能单独证明文件恢复正确。</p>'
        '<details><summary>English guidance</summary><p>Retain genuine ties and declare the tie policy. '
        'If export rounding discarded precision, re-export retained scores from the same run into new files. '
        'Check query/candidate identities, judgments, protocol and score fidelity before metrics. '
        'Without retained evidence, record the limit; ranks or labels cannot reconstruct original scores. '
        'A zero metric delta or an empty warning list alone does not validate recovery.</p></details></section>'
    )


def _finding_evidence(code: str, evidence: Any) -> str:
    if code == "score_ties" and isinstance(evidence, Mapping):
        examples = evidence.get("examples")
        if isinstance(examples, list) and all(isinstance(row, Mapping) for row in examples):
            rows = []
            for example in examples[:EVIDENCE_LIMIT]:
                row = dict(example)
                if isinstance(row.get("item_ids"), (list, tuple)):
                    row["item_ids"] = row["item_ids"][:EVIDENCE_LIMIT]
                rows.append(row)
            counts = {key: value for key, value in evidence.items() if key != "examples"}
            return (
                _diagnostics(counts, EVIDENCE_LIMIT)
                + '<p lang="zh-CN">下面是检查程序保留的同分样例，不是全部同分组；'
                '每组候选标识也可能只保留或展示了一部分。完整 JSON 保存的是程序实际记录的证据。</p>'
                + _table(rows, EVIDENCE_LIMIT)
            )
    return _diagnostics(evidence, EVIDENCE_LIMIT)


def _diagnostics(value: Any, limit: int = TABLE_LIMIT) -> str:
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, Mapping) for item in value) and any(
            any(isinstance(child, (Mapping, list, tuple)) for child in item.values())
            for item in value
        ):
            entries = []
            for index, item in enumerate(value[:limit]):
                name = (
                    f"{item['left']} → {item['right']}"
                    if "left" in item and "right" in item
                    else f"Entry {index + 1}: query {item['query_id']}"
                    if isinstance(item.get("query_id"), str)
                    else f"Entry {index + 1}"
                )
                entries.append(
                    f"<details><summary>{_esc(name)}</summary>{_diagnostics(item, limit)}</details>"
                )
            if len(value) > limit:
                entries.append(
                    f'<p class="muted">Showing {limit} of {len(value)} entries. Full stored evidence is in report.json.</p>'
                )
            return "".join(entries)
        return _content(value, limit)
    if not isinstance(value, Mapping):
        return _content(value, limit)
    sections = []
    scalars = {
        key: item for key, item in value.items() if not isinstance(item, (Mapping, list, tuple))
    }
    if scalars:
        sections.append(_content(scalars, limit))
    for key, item in value.items():
        if isinstance(item, (Mapping, list, tuple)):
            if key == "files" and value.get("scheme") == "rankprobe-core-python-v1" and isinstance(item, Mapping):
                rendered = _table([
                    {"filename": name, "sha256": digest} for name, digest in item.items()
                ], limit)
            else:
                rendered = (
                    _metrics(item)
                    if key
                    in {"metric_bounds", "metrics", "original", "reversed", "deduplicated", "raw_rows"}
                    or str(key).endswith("_metrics")
                    or str(key).startswith("delta_")
                    else _diagnostics(item, limit)
                )
            sections.append(
                f"<details><summary>{_esc(_label(str(key)))}</summary>{rendered}</details>"
            )
    return "".join(sections)


def _findings(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = report.get("findings", [])
    return (
        [finding if isinstance(finding, Mapping) else {"message": finding} for finding in value]
        if isinstance(value, list)
        else []
    )


def _severity(finding: Mapping[str, Any]) -> str:
    value = str(finding.get("severity", finding.get("level", "info"))).lower()
    return value if value in {"error", "warning", "info"} else "info"


def render_html(report: Mapping[str, Any]) -> str:
    """Render an audit or comparison without requests, scripts, or unsafe markup."""
    findings = _findings(report)
    counts = {
        level: sum(_severity(item) == level for item in findings)
        for level in ("error", "warning", "info")
    }
    kind = str(report.get("report_type", report.get("kind", "audit")))
    run_name = report.get("run_name", report.get("name"))
    subtitle = (
        f"Run: {_esc(run_name)}" if run_name is not None else "Ranking evaluation diagnostics"
    )
    summary = report.get("summary", {})
    protocol = report.get("protocol", {})
    protocol_navigation = '<a href="#protocol">评测设置 / Protocol</a>' if protocol else ""
    sections: list[str] = []
    comparison_section = None
    result_navigation = ""
    if summary:
        sections.append(f'<section id="summary"><h2>这份输入包含什么 / Run summary</h2><details><summary>查看数量与技术字段</summary>{_content(summary)}</details></section>')
    if protocol:
        sections.append(
            f'<section id="protocol"><h2>这次怎样计算分数 / Evaluation protocol</h2><p lang="zh-CN">计算方式会影响分数。比较前请核对截断位置、同分顺序、标签处理和参考范围是否一致；只看指标名称相同还不够。</p><details><summary>查看全部评测设置 / All settings</summary>{_content(protocol)}</details></section>'
        )
    if isinstance(summary, Mapping) and summary.get("unknown_candidates", 0):
        sections.insert(
            0,
            f'<section class="boundary"><h2>有些项目还没有标签</h2><p lang="zh-CN">输入中有 {_esc(summary["unknown_candidates"])} 个候选项目没有已知标签。部分查询可能因此无法计算分数。请先看每个指标用了多少查询，以及这次怎样处理缺失标签。</p><details><summary>English explanation</summary><p>Relevance coverage is incomplete. Check each metric\'s coverage, reference and stated treatment of unjudged candidates before interpreting results.</p></details></section>',
        )
    for key, title in (
        ("metrics", "重新计算的分数 / Recomputed metrics"),
        ("comparison", "Run comparison"),
        ("comparisons", "Run comparisons"),
        ("runs", "分别查看每次运行 / Compared runs"),
        ("pairs", "比较结果 / Comparison results"),
        ("tie_analysis", "同分顺序会影响多少 / Tie sensitivity"),
        ("duplicates", "重复项目会影响多少 / Duplicate sensitivity"),
        ("negative_controls", "改变输入顺序后的核查 / Negative controls"),
        ("checks", "哪些检查已经进行 / Check coverage"),
        ("limitations", "哪些情况还不能判断 / Coverage and limitations"),
        ("provenance", "输入来源与运行环境 / Reproducibility metadata"),
    ):
        if key in report and report[key]:
            if key == "metrics":
                rendered = (
                    '<p lang="zh-CN">先看每个分数用了多少查询，再看分数大小。MRR 关注第一个相关结果排得多靠前，NDCG 还考虑其他相关结果的位置和相关程度；两种指标不能直接比大小。展开范围明细，可以查看哪些查询没有参与计算及原因。</p>'
                    + _partial_perfect_context(report[key]) + _metrics(report[key], "metrics")
                )
            elif key == "pairs":
                rendered = _pairwise_results(report)
            elif key == "runs":
                rendered = _compared_runs(report[key])
            else:
                rendered = _diagnostics(report[key])
            section = f'<section id="{key}"><h2>{title}</h2>{rendered}</section>'
            if key == "pairs":
                comparison_section = section
                result_navigation = '<a href="#pairs">Comparison results</a>'
                if report.get("runs"):
                    result_navigation += '<a href="#runs">Run diagnostics</a>'
            else:
                sections.append(section)
    cards: list[str] = []
    for index, finding in enumerate(findings):
        severity = _severity(finding)
        code = finding.get("code", finding.get("id", f"finding-{index + 1}"))
        title = finding.get("title", _label(str(code)))
        message = finding.get("message", finding.get("description", ""))
        status = finding.get("status")
        severity_label = {"error": "优先处理 / ERROR", "warning": "需要核对 / WARNING", "info": "补充说明 / INFO"}[severity]
        badge = f'<span class="badge {severity}">{severity_label}</span>'
        state = f'<span class="status">{_esc(status)}</span>' if status is not None else ""
        evidence = finding.get("evidence", finding.get("examples"))
        location = f'<p class="code">JSON: findings[{index}].evidence</p>'
        details = (
            f'<details id="finding-{index}-evidence"><summary>查看这项发现的证据 / Inspect evidence</summary>'
            f'{location}{_finding_evidence(str(code), evidence)}</details>'
            if evidence is not None
            else ""
        )
        scope = (
            f'<p class="muted">Scope: {_esc(finding["scope"])}</p>' if "scope" in finding else ""
        )
        run_context = (
            f'<p class="muted" lang="zh-CN">对应运行：<strong>{_esc(finding["run_name"])}</strong></p>'
            if finding.get("run_name") is not None else ""
        )
        next_step = FINDING_NEXT_STEPS.get(str(code))
        related = _finding_target(report, finding)
        related_link = (
            f' <a href="#{related[0]}">{_esc(related[1])}</a>.' if related and next_step else ""
        )
        action = (
            f'<p><strong>Next step:</strong> {_esc(next_step)}{related_link}</p>' if next_step else ""
        )
        reader_copy = FINDING_COPY_ZH.get(str(code))
        recheck = (
            '<p lang="zh-CN"><a href="#score-export-recheck">需不需要改分数？改完怎样复核？</a></p>'
            if str(code) in {"score_ties", "constant_scores"} else ""
        )
        if reader_copy:
            heading, explanation, next_action = reader_copy
            link = f' <a href="#{related[0]}">{_esc(related[1])}</a>。' if related else ""
            cards.append(
                f'<article class="finding {severity}" id="finding-{index}">{badge}<h3 lang="zh-CN">{_esc(heading)}</h3>{run_context}'
                f'<p lang="zh-CN">{_esc(explanation)}</p><p lang="zh-CN"><strong>下一步：</strong>{_esc(next_action)}{link}</p>'
                f'{recheck}{details}'
                f'<details><summary>English description / 技术详情与证据</summary>{state}<h4>{_esc(title)}</h4><p>{_esc(message)}</p>'
                f'<p class="code">{_esc(code)}</p>{scope}{action}</details></article>'
            )
        else:
            cards.append(
                f'<article class="finding {severity}" id="finding-{index}">{badge}{state}<h3>{_esc(title)}</h3>{run_context}<p>{_esc(message)}</p><p class="code">{_esc(code)}</p>{scope}{action}{details}</article>'
            )
    findings_html = (
        "".join(cards)
        or '<div class="empty"><h3>这次检查没有列出问题 / No findings were reported.</h3><p lang="zh-CN">你可以保留报告和评测设置，用于下次比较。这只说明当前检查没有发现问题；标签是否正确、数据是否有泄漏，仍需要其他证据。</p><p>This means the configured checks found no issues in the supplied data. It does not establish data provenance, relevance quality, or absence of leakage.</p></div>'
    )
    if any(f.get("code") in {"score_ties", "constant_scores"} for f in findings):
        sections.append(_score_export_recheck())
    sections.insert(
        0,
        f'<section id="findings"><h2>需要核对的地方 / Findings <span class="count">{len(findings)}</span></h2><p class="muted" lang="zh-CN">先读每项发现和建议的下一步，再按需展开证据。警告提醒你核对一种情况，并不等于评测一定有错。</p>{findings_html}</section>',
    )
    if comparison_section:
        sections.insert(0, comparison_section)
    if report.get("demo_note"):
        sections.insert(
            0,
            f'<section class="boundary"><h2>这是一份演示报告 / Synthetic demonstration</h2><p lang="zh-CN">数据中有意放入了同分、重复项目和缺失标签，用来演示怎样发现和核对问题。请把它当作阅读练习，不代表真实模型的效果。</p><details><summary>查看原始说明 / Original note</summary><p>{_esc(report["demo_note"])}</p></details></section>',
        )
    boundaries = (
        "RankProbe inspects the supplied predictions and optional judgments. It cannot establish that labels are correct, "
        "the candidate pool represents production traffic, or training data is free of leakage. Missing judgments are not "
        "evidence of non-relevance unless the stated protocol explicitly makes that assumption. Metrics and findings "
        "describe this supplied run; they are not a certificate of model quality."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="light"><title>RankProbe — {_esc(kind)} report</title>
<style>
:root{{--ink:#14283b;--muted:#536779;--line:#d8e2eb;--paper:#fff;--bg:#eef3f7;--accent:#075c65;--error:#a52c32;--warning:#825000}}
.table-wrap:focus-visible{{outline:3px solid #dc8400;outline-offset:4px}}
.comparison-reader{{padding:16px;background:#f2f7fa;border:1px solid var(--line);border-radius:6px}}.comparison-reader h4{{margin:0 0 10px;font-size:17px}}.metric-previews{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:14px}}.metric-preview{{padding:14px;background:white;border:1px solid var(--line);border-radius:6px;min-width:0;overflow-wrap:anywhere}}.metric-preview h4{{font-family:ui-monospace,monospace}}.metric-preview dl{{margin:0}}.metric-preview dt{{font-weight:600;margin-top:10px}}.metric-preview dd{{margin:3px 0 0}}.metric-preview small{{color:var(--muted)}}
*{{box-sizing:border-box}}h1,h2,h3,p,summary,li{{overflow-wrap:anywhere}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:var(--accent);text-underline-offset:3px}}a:focus-visible,summary:focus-visible{{outline:3px solid #dc8400;outline-offset:4px}}.skip{{position:absolute;top:-70px;left:16px;padding:10px;background:white}}.skip:focus{{top:10px;z-index:1}}header{{background:#102c40;color:white;padding:44px max(24px,calc((100vw - 1080px)/2)) 34px}}.eyebrow{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#9ed5d2}}h1{{font-size:clamp(30px,5vw,44px);line-height:1.15;margin:10px 0}}header p{{color:#ccdae5;margin:10px 0}}nav{{display:flex;flex-wrap:wrap;gap:20px;margin-top:20px}}nav a{{color:#c1eee8}}main{{max-width:1128px;margin:auto;padding:24px}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}}.stat{{background:white;border:1px solid var(--line);border-top:4px solid var(--accent);padding:16px 20px;border-radius:8px}}.stat.error{{border-top-color:var(--error)}}.stat.warning{{border-top-color:#bd790e}}.stat strong{{display:block;font-size:30px;line-height:1.1}}.stat span{{color:var(--muted)}}section{{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin:0 0 22px;padding:24px}}h2{{font-size:22px;margin:0 0 12px;line-height:1.3}}h3{{font-size:18px;line-height:1.4;margin:10px 0}}p{{margin:10px 0}}.muted,.code,.status{{color:var(--muted)}}.code{{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}}.finding{{border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:6px;margin-top:16px;padding:18px}}.finding.error{{border-left-color:var(--error)}}.finding.warning{{border-left-color:#bd790e}}.badge{{display:inline-block;padding:2px 8px;font-size:11px;font-weight:750;letter-spacing:.06em;border-radius:4px;background:#e6f3f2;color:#0b5559}}.badge.error{{background:#fce9e9;color:var(--error)}}.badge.warning{{background:#fff1cf;color:var(--warning)}}.status{{font-size:12px;margin-left:10px}}.count{{font-size:14px;color:var(--muted)}}details{{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}}summary{{cursor:pointer;font-weight:600;color:var(--accent);padding:4px 0}}.table-wrap{{overflow-x:auto;margin-top:14px}}table{{width:100%;border-collapse:collapse;font-size:14px;text-align:left}}th{{background:#f2f6f9;font-weight:650}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere;min-width:100px;max-width:520px}}td{{white-space:pre-wrap}}.boundary{{background:#f8f3e7;border-color:#e6d9b9}}.empty{{padding:14px;background:#f1f6f8;border-radius:6px}}footer{{max-width:1080px;margin:0 auto;padding:0 24px 30px;color:var(--muted);font-size:13px}}@media(max-width:600px){{header{{padding:30px 18px}}main{{padding:14px}}section{{padding:17px}}.stat{{padding:12px}}.stat strong{{font-size:25px}}.stat span{{font-size:12px}}.finding{{padding:13px}}nav{{gap:14px;font-size:14px}}}}@media print{{body{{background:white}}header{{background:white;color:var(--ink);padding:12px 0}}header p{{color:var(--muted)}}nav,.skip{{display:none}}main{{padding:0}}section,.finding{{break-inside:avoid}}details> *{{display:block}}footer{{padding:0}}}}
</style></head><body><a class="skip" href="#main">Skip to report</a>
<header><div class="eyebrow">推荐与检索评测核查 · Ranking evaluation diagnostics</div><h1>RankProbe</h1><p>{subtitle}</p><nav aria-label="Report navigation">{result_navigation}<a href="#findings">需要核对的地方 / Findings</a>{protocol_navigation}<a href="#boundaries">怎样理解这份报告</a><a href="report.json" download>下载详细结果 JSON</a></nav></header>
<main id="main"><div class="stats" aria-label="Finding counts"><div class="stat error"><strong>{counts["error"]}</strong><span>优先处理 / Errors</span></div><div class="stat warning"><strong>{counts["warning"]}</strong><span>需要核对 / Warnings</span></div><div class="stat"><strong>{counts["info"]}</strong><span>补充说明 / Information</span></div></div>
{"".join(sections)}<section id="boundaries" class="boundary"><h2>怎样理解这份报告 / Interpretation limits</h2><p lang="zh-CN">报告检查的是你提供的预测和标签。它不能证明标签正确、候选项目能代表实际业务，或训练数据没有泄漏。缺失标签也不表示项目不相关，除非你明确选择了这种评测假设。先按发现定位原始数据，再决定是否需要调整导出或比较条件。</p><p lang="zh-CN">每项发现最多展示 {EVIDENCE_LIMIT} 条证据。下载的 JSON 保留检查程序存储的证据；程序内部也可能只保存了部分样例。</p><details><summary>English explanation</summary><p>{boundaries}</p><p>Evidence tables show at most {EVIDENCE_LIMIT} entries per finding. The downloadable JSON contains the evidence stored by the audit engine; engine-level sampling limits may also apply.</p></details></section></main>
<footer>RankProbe · Offline report · Schema {_esc(report.get("schema_version", "unspecified"))}. No external resources are requested by this document.</footer></body></html>"""


def write_report(
    report: Mapping[str, Any], output_dir: str | Path, *, overwrite: bool = False
) -> tuple[Path, Path]:
    """Stage both outputs before replacement; retain unrelated files and roll back failures."""
    output = Path(output_dir)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    html_text = render_html(report)
    if (output.exists() or output.is_symlink()) and not output.is_dir():
        raise NotADirectoryError(
            f"--out must name a directory; {output} is a file or unresolved link. "
            "Choose another --out directory."
        )
    output.mkdir(parents=True, exist_ok=True)
    destinations = [output / "report.json", output / "report.html"]
    exists_message = (
        f"Report already exists in {output}. Choose a new --out directory or pass --overwrite."
    )
    if any(path.is_dir() for path in destinations):
        raise IsADirectoryError(
            "A report destination is a directory; choose another --out directory."
        )
    if not overwrite and any(path.exists() or path.is_symlink() for path in destinations):
        raise FileExistsError(exists_message)
    with tempfile.TemporaryDirectory(prefix=".rankprobe-", dir=output) as temporary:
        staging = Path(temporary)
        staged = [staging / path.name for path in destinations]
        for path, content in zip(staged, (json_text, html_text)):
            path.write_text(content, encoding="utf-8")
        backups: dict[Path, Path] = {}
        installed: list[Path] = []
        reserved: list[Path] = []
        try:
            if overwrite:
                for destination in destinations:
                    if destination.exists() or destination.is_symlink():
                        backup = staging / (destination.name + ".backup")
                        os.replace(destination, backup)
                        backups[destination] = backup
            else:
                # The earlier existence check gives a useful fast error, but
                # another writer can pass it too. Reserve both final names
                # atomically before replacing either staged report.
                for destination in destinations:
                    try:
                        descriptor = os.open(
                            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                        )
                    except FileExistsError as exc:
                        raise FileExistsError(exists_message) from exc
                    reserved.append(destination)
                    os.close(descriptor)
            for source, destination in zip(staged, destinations):
                os.replace(source, destination)
                installed.append(destination)
        except OSError:
            for destination in installed:
                destination.unlink(missing_ok=True)
            for destination in reserved:
                destination.unlink(missing_ok=True)
            for destination, backup in backups.items():
                os.replace(backup, destination)
            raise
    return destinations[0], destinations[1]


# Kept as a discoverable name for library callers.
render_report = render_html
