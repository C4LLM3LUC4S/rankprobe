# RankProbe · 排名评测核查

**评测分数变了，是排序变好了，还是比较条件变了？**

**Did the ranking improve, or did the evaluation change? Check with a local report.**

> This repository contains RankProbe only. Versioned downloads now come from this repository; the original alpha-4 release remains unchanged in the course repository.
> RankProbe 现在从独立仓库提供版本下载；原课程仓库中的 alpha-4 发行仍原样保留。

**Community release `0.1.0a9` — find the rejected entry in a saved MTEB export, still alpha.** The local conversion recipe now names the file, selected subset/split and query/document pair when a score or ID is invalid. Inspect that source entry, retain the original file and retry with a new export. Core parsing and metric rules are unchanged. See the [release notes](docs/releases/0.1.0a9.md) and [delivery scope and maintenance policy](docs/initial-delivery.md). Independent adoption and measured human benefit remain future validation work.

**Find out when a ranking score depends on ties, duplicated candidates, or a changed evaluation pool.**

Give RankProbe your exported recommendation or retrieval scores. It checks for tied scores, repeated items, missing queries and changed candidate sets, then shows what to inspect next. You get a local HTML report to read and JSON for further analysis. Relevance labels are optional: without them, structural checks still work, while label-dependent scores may be unavailable. It uses the Python standard library and needs no model inference, cloud account or API key.

**[Download the complete offline bundle](https://github.com/C4LLM3LUC4S/rankprobe/releases/download/v0.1.0a9/RankProbe-0.1.0a9.zip)** · [Release notes and checksums](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a9). Extract it and open `START_HERE.md`; no Git or package-index connection is needed to install its bundled wheel. [Public source](https://github.com/C4LLM3LUC4S/rankprobe) is on the default branch.

[中文说明](README.zh-CN.md) · [Input contract](docs/input-format.md) · [Metric semantics](docs/metrics.md) · [CLI / Python API](docs/usage.md) · [First local report](docs/try-it.md) · [Limitations](docs/limitations.md)

For a source-only first report with **your own files**, run `python quickstart.py --input predictions.csv`, or repeat `--run NAME=FILE` for a comparison. Optional qrels, cutoffs and format flags are documented in [Start here](START_HERE.md). This installs nothing, preserves inputs and keeps missing labels unknown. The alpha-7 bundle includes this launcher. To preserve an old result, follow the [source and report recovery guide](docs/source-recovery.md). Development follows [product tasks and acceptance](docs/product-scope.md).

Using BEIR? The [export/evaluation recipe](docs/beir-workflow.md) preserves the retrieved snapshot, makes self-match filtering and export depth explicit, and transfers existing qrels without inventing labels.

Using RecBole nonsequential full-sort scores? The [safe export recipe](docs/recbole-workflow.md) records padding/history exclusions, preserves external tokens and rejects unexpected nonfinite scores without inventing judgments.

Using ReChorus? The [runner capture recipes](docs/rechorus-workflow.md) preserve sampled candidates before the native top-100 presentation export, or explicitly handle masks in the checked base full-sort contract. Stable source identities are available for cross-run comparisons.

Have saved MTEB retrieval predictions? The [score-file recipe](docs/mteb-workflow.md) selects one subset and split for the existing CSV interface, explains cache and output-folder choices, and distinguishes saved candidates from the later scoring stage. Metric-only result JSON is insufficient.

## Quick start

Before expanding a job, read [what makes a useful audit and how workload grows](docs/reliability.md). Local installations do not share a central compute service; large exports and all-pairs comparisons still consume local memory.

For an immediate source preview, download and fully extract this repository, then run `python quickstart.py`. It opens a built-in synthetic report without installation or network access and preserves earlier reports. See [START_HERE](START_HERE.md). The regular installed-package path follows below.

Requires Python 3.10 or newer. The complete [GitHub release bundle](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a9) includes offline instructions, packages, source and original fixtures. The commands below use a source checkout; PyPI is not part of this release.

On Windows, choose a short extraction path. If creating the environment fails with a long-path hint from pip/ensurepip, start again from a shorter folder.

Or obtain it with Git:

```sh
git clone --branch main https://github.com/C4LLM3LUC4S/rankprobe.git
cd rankprobe
```

From the package folder, use a separate environment without activating it.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m rankprobe demo --out reports/demo
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m rankprobe demo --out reports/demo
```

Open `reports/demo/report.html` offline. See the [complete first-use walkthrough](docs/try-it.md) for a comparison with expected values and framework environment guidance.

You do not need an active experiment to try the tool. The demo and first-report fixtures are self-contained; your own exports are optional. Example practice checks the workflow, while practical value needs later evidence from an actual task.

In the remaining examples, `python` means the same environment interpreter: use `.\.venv\Scripts\python.exe` on Windows or `.venv/bin/python` on macOS / Linux. To use a supplied example:

```sh
python -m rankprobe audit examples/ties.csv --cutoffs 1,5 --out reports/ties
python -m rankprobe audit examples/ties.csv --tie-policy input --cutoffs 1,5 --out reports/ties-input
python -m rankprobe compare --run baseline=examples/clean.csv --run changed=examples/mismatch.csv --out reports/compare
```

Reports are written to the selected output directory; existing report files are refused unless `--overwrite` is explicit. `report.json` is intended for programmatic inspection; `report.html` is self-contained and can be opened offline. Reports include input identifiers and example rows, so review them before sharing.

In a comparison, start with **Comparison results**: submitted-run values sit beside matched-pool values and the right-minus-left delta. Each value shows its coverage and reference scope. Expand coverage details to see which queries were excluded, then follow the relevant finding's suggested next step. A displayed delta is an arithmetic difference under the stated protocol, not a significance test.

## What it checks

| Question | Evidence in the report |
| --- | --- |
| Could tied scores change the result? | Exact-score tie groups, input-order versus deterministic ranking, and metric bounds across permutations within ties |
| Does a query list the same item repeatedly? | Duplicate pairs, score or relevance conflicts, and a declared deduplication policy |
| Are two runs being evaluated on the same cases? | Query coverage, per-query candidate sets, relevance differences, and evidence that requires manual follow-up |
| What assumptions produced these metrics? | Cutoffs, gain, tie policy, unjudged treatment, relevance source, and denominator scope |

A tie is often legitimate. Repeated candidates can come from a declared sampling protocol. RankProbe reports their effects; it does not label every occurrence a bug or silently claim one universal correct score.

## Bring your own predictions

One CSV row is a scored `(query_id, item_id)` pair. A query is one ranking event, which may be a search query, recommendation target, or reranking request. Multiple events for the same user need separate query IDs.

```csv
query_id,item_id,score,relevance
q1,doc_a,0.9,1
q1,doc_b,0.7,0
q2,doc_c,0.4,2
```

Scores must be finite numbers; larger scores rank first. Relevance is nonnegative, with `> 0` treated as relevant by MRR and Recall. Missing relevance is **unknown**, unless you explicitly choose `--unjudged nonrelevant`. JSONL uses the same field names.

From `0.1.0a4`, MRR can use a known first-relevant prefix even when later labels are unknown. Earlier reports used a stricter eligibility rule. Read the [metric semantics and migration note](docs/metrics.md#mrrk) before comparing conditional averages across versions.

```sh
python -m rankprobe audit predictions.jsonl --out reports/my-run
```

Independent judgments use a CSV or JSONL file with `query_id,item_id,relevance`. Provide complete qrels only when you can justify that assumption:

```sh
python -m rankprobe audit examples/unjudged.csv --qrels examples/qrels.csv --qrels-complete --out reports/qrels
```

TREC retrieval outputs can be read directly, without reformatting scores:

```sh
python -m rankprobe audit results.run --qrels judgments.qrels --out reports/retrieval
```

For `.txt` files, select `--input-format trec` and `--qrels-format trec` explicitly. The run's score determines ordering; its declared rank is ignored. A qrels relevance of `-1` remains unknown. Declaring complete qrels while an explicit unjudged entry remains is rejected. See the [synthetic retrieval walkthrough](examples/trec/README.md) for a case where dropping a difficult query doubles MRR without improving the common queries.

MRR and NDCG are reported with their evaluated-query counts and scope. Recall is available only with explicitly declared complete qrels. Candidate-pool metrics do not measure full-corpus retrieval quality. A completeness flag records your assertion; RankProbe cannot verify it from scores alone.

For the next step after a finding, see [case actions and rechecks](docs/case-actions.md). It separates executed public-input checks from pending follow-up experiments and synthetic controls.

The optional [fitted-score MovieLens case](examples/movielens-scores/README.md) uses actual public ratings and two small NumPy models to check shared observed-item pools, presentation rounding and recovery from retained exact scores. It keeps dataset-derived rows local and does not change the model-free core.

## Existing framework outputs

Export a small ReChorus-style NPZ locally with the optional NumPy adapter:

```sh
python -m pip install -e ".[adapters]"
python scripts/export_rechorus.py local_test_predictions.npz --out local_export.csv --positive-index 0 --limit-queries 100
python -m rankprobe audit local_export.csv --out reports/local-export
```

The adapter has an explicit one-positive-column assumption; all other labels remain unknown in this recipe. Only add `--other-candidates nonrelevant` when your verified evaluation protocol justifies that assertion. It remaps item IDs, omits the `user_id` array, and treats each matrix row as a distinct query. Read [adapter assumptions](docs/adapters.md) before comparing exports. Run model-dependent capture in your existing framework interpreter; audit the resulting file with the core environment above. Synthetic fixtures are included; private predictions, MovieLens data, and third-party code are not redistributed.

RankProbe is an independent evaluator, not a compatibility wrapper for MTEB, RecBole, or ReChorus. Tie rules and metric definitions can differ. For example, its default `item_id` tie rule is ascending string order, whereas `trec_eval` uses a different convention. See [known public context](docs/known-cases.md) and the [reproducible trec_eval cross-check](docs/trec-reference.md) to distinguish shared-protocol agreement from expected differences.

## Development

```sh
python -m pip install -e ".[dev,adapters]"
python -m pytest
python -m ruff check .
python -m build
python scripts/check_distribution.py
python scripts/check_wheel_install.py --wheel dist/rankprobe-0.1.0a9-py3-none-any.whl
```

The full-test CI matrix targets Python 3.10, 3.12, and 3.13 on Ubuntu and Windows, including fresh built-wheel installation and both command-line entry points. Separate Python 3.15 jobs on both systems check core source installation, distribution builds and the isolated wheel; they do not establish full-suite, NumPy-adapter or native-framework coverage on 3.15. Python 3.14 is not in this matrix. See [installation checks](docs/installation-checks.md) and inspect the exact commit's workflow runs for results.

The bounded [initial engineering scope](docs/initial-delivery.md) is complete; `0.1.0a9` remains an alpha. The [verification record](docs/verification.md) distinguishes executed checks from pending evidence. There are no claimed independent external adopters, revenue, benchmark certification, or published research results. [The validation plan](docs/validation-plan.md) and [roadmap](docs/roadmap.md) describe what would establish practical value. Contributions should add an independently checkable example and document changed semantics. Please report problems with a small synthetic input instead of uploading private data.

## License and citation

See [LICENSE](LICENSE). Original synthetic examples follow this repository's license; framework outputs and datasets retain their own terms. A [CITATION.cff](CITATION.cff) file describes this software without claiming a paper or DOI.
