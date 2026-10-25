# 把 MRR 容忍规则接到 CI / An optional MRR regression guard

每次导出后，你可能想问：“和固定基线相比，这次 MRR 有没有下降太多？”普通 `compare` 会检查可比范围、同分和标签等问题，但不会把指标下降本身当成错误。现在可以显式声明一条 MRR 容忍规则；不加下面三个参数，原来的行为保持不变。

## 先固定要检查什么

在查看新结果前，保存基线原文件、它的 SHA256、实际标签文件和命令，并固定评测协议、MRR 截断位置、最大绝对下降量和最少查询数。不要在结果不好时换基线、减查询、补零或提高容忍值来通过。基线摘要只核对文件一致，不能证明它覆盖了预期测试集或来源可靠。

命令只自动核对基线文件的指定摘要；标签和协议不是与历史快照自动核验的。报告会保存本次实际标签来源摘要和协议，仍需由你的 CI 配置独立固定、检查这些材料。

例如：对双方全部提交查询检查 MRR@10，允许最多下降 **0.01 个 MRR 单位**，至少有 100 个查询。这不是下降 1%，也不是统计显著性检验。0.01 和 100 只是这里展示的工程约定，应由你的任务要求决定；它们不是通用推荐值或样本量保证。

Windows PowerShell，在已安装核心的目录中：

```powershell
# 先核对保留的 baseline.csv；把事先记录的完整摘要填到下方，不要每次自动信任改过的基线。
(Get-FileHash .\baseline.csv -Algorithm SHA256).Hash
.\.venv\Scripts\python.exe -I -m rankprobe compare --run baseline=baseline.csv --run candidate=candidate.csv --qrels judgments.csv --cutoffs 10 --max-mrr-drop mrr@10=0.01 --min-guard-queries 100 --guard-baseline-sha256 YOUR_SAVED_64_DIGIT_SHA256 --out reports/new-regression-check
```

macOS/Linux 使用 `.venv/bin/python` 替换解释器路径；可用 `sha256sum baseline.csv` 核对摘要。第一份 `--run` 是已固定的基线，第二份是新结果。三个 guard 参数必须一起提供，且只能有这两份输入；所选 cutoff 必须包含在 `--cutoffs` 中。输出用新目录，原报告先留着。普通 CSV/JSONL/TREC、标签和显式协议选项仍按[输入合同](input-format.md)处理。

## 结果怎么看？

HTML 最上方和 JSON 的 `regression_guard` 会保存判定、实际分数、声明门槛及原因：

| 判定 | 含义与下一步 |
| --- | --- |
| `pass` | 这份输入满足已声明的规则：`candidate - baseline >= -max_absolute_drop`。保留输入、协议、基线摘要和报告。 |
| `failed_drop` | 下降量超过门槛。保留失败结果，检查实际排序变化；修改后另做一次新比较。 |
| `blocked` | 本次条件不支持判定。先核对完整导出、基线、标签和查询范围；不能把不可算值当零或通过。 |

guard 的失败和阻塞都会先保留完整 HTML/JSON，再返回 **1**。输入、参数或保存失败仍返回 **2**；此时完整报告未获确认。`--fail-on never` 只影响普通发现，不能绕过你已经声明的 guard；`pass` 时若普通发现达到所选阈值，命令仍返回 1。[CI 保留报告](local-ci.md)的要求照旧。

## 这条规则为什么严格？

它只使用本次从两份原始输入、同一个当前协议重新计算的 MRR，不读取旧报告里的平均分相减。双方查询、候选和已解析标签必须完全一致，不能有重复候选或错误级发现。所选 MRR 的合格查询 ID 必须等于全部提交且匹配的查询 ID，并满足声明的最少数量；仅有相同数量、不同查询不够。

这条初版规则要求 `--unjudged unknown`，也不接受由完整 qrels 闭包引入的隐含零。普通比较仍允许有依据的显式标签约定；guard 更严格不表示那些约定本身有错。MRR 使用 `submitted_candidates` 参考范围和 `known_first_relevant_prefix` 资格规则：首个相关项之前都已知时，之后的未知仍可保留，不能为检查而补零。见[指标语义](metrics.md)。

判定使用原始 binary64 分数差和已声明阈值，边界相等时通过，没有隐藏的容差调整。JSON 保留完整值，HTML 缩短的小数不能替代判定依据。`provenance.regression_guard` 另存规则与 guard 模块源码摘要；它和核心源码身份一起帮助核对实现，不能认证实际运行环境或来源。

## English

Ordinary `compare` fails on selected finding severities; a lower metric alone is not such a finding. Opt into this engineering check with all three flags: `--max-mrr-drop mrr@K=DROP`, `--min-guard-queries N`, and the first input's predeclared `--guard-baseline-sha256 HEX`. Freeze the baseline, judgments, protocol and threshold before inspecting the candidate. The cutoff must be requested, and exactly two runs are supported.

The guard uses this invocation's original inputs and common current protocol. It requires identical complete query/candidate/resolved-label populations, no duplicate input candidates or error findings, and the same fully eligible MRR query IDs/reference/rule on both sides. Unknowns remain unknown; a nonrelevance assumption or implicit complete-qrels zero blocks this strict first version. Unknown labels after an already determined first relevant result need not block MRR eligibility. Missing or restricted results cannot become a pass merely by meeting a minimum count.

Only the baseline file's supplied digest is automatically pinned. This report records the actual judgment-source hashes and protocol, but does not compare them with a historical snapshot; freeze and check those separately in the owning CI configuration.

`pass`, `failed_drop` and `blocked` are saved in the report. A complete failed/blocked guard exits 1 even with `--fail-on never`; parameter/input/output failure exits 2. The absolute tolerance is a task owner's rule, not a relative percentage, significance test, quality certificate or automatic leakage check. The pinned hash cannot authenticate the baseline or its intended task universe. Keep the complete report and matching source; no upload, model inference or automatic input repair occurs.
