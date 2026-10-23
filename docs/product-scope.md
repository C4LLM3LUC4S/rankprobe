# Product tasks and acceptance / 产品任务与验收

RankProbe serves recommendation, retrieval and reranking users who already have score-bearing exports. The task is to explain an evaluation difference, identify evidence to inspect, take a justified action and recheck it locally. It complements existing evaluators rather than promising one universally correct score.

| User question | Useful result | Acceptance and boundary |
| --- | --- | --- |
| Did a larger average actually reflect better ordering? | Coverage and matched, metric-eligible deltas | Check query/candidate identities and population; changed coverage alone is not a model gain |
| Did presentation or export change the scores? | Ties, duplicate conflicts and source fingerprints | Recover from retained scores, preserve originals, compare again; lost precision cannot be reconstructed |
| Why does my evaluator disagree? | Explicit gain, tie, cutoff and judgment scope | Align only justified protocols; preserve unknown labels and the original comparison |
| What do I do after a warning? | A concrete next check and an acceptance condition | Follow [case actions](case-actions.md); a warning disappearing alone is insufficient |
| Can I use my own files without rebuilding an environment? | A new local report from existing CSV/JSONL/TREC files | Source launcher accepts own inputs; advanced protocols and framework captures retain their documented environments |

Priorities: complete own-export onboarding, make findings and scope understandable, then improve specific capture/recovery obstacles supported by reproducible input. Add integrations only when users can retain identities, scores, judgments and provenance. More metrics or automatic repair would not by themselves answer these questions.

Engineering cases and a guided public-data action are available. Independent user adoption, previously unnoticed real incidents, repeat use and measured active human time remain unverified. A synthetic trap or machine runtime cannot establish those outcomes. Input rows and report identifiers remain local; users decide what they may share.

中文：验收看“自己的导出→看懂发现→采取有依据的行动→复核”，不看功能数量。报告生成成功、测试通过和示例中的差异，只证明各自路径；真实帮助需要实际任务证据。没有标签仍可查结构问题，无法计算的指标保持未知，不为了显示分数补零。
