# 什么时候值得用，数据多了怎么办？

先带着一个具体问题来：同一套评测前后的分数变了，你想知道是不是查询、候选、标签或导出方式也变了。RankProbe 帮你找到需要核对的证据；它不能仅凭一份报告判断模型该不该上线。

## 怎样才算帮上了忙？

保留一条简短的任务记录就够了，不需要上传原数据：

1. 原来要决定什么？例如“导出格式变化后，分数还能直接比较吗？”
2. 报告指出了哪项具体证据？记下对应发现、查询范围和比较条件。
3. 你做了什么，或者为什么决定不改？有效同分和合法的候选差异也可以保留。
4. 用原始输入、相同协议和新目录复核后，决定有没有依据？不要只看警告少了几个。

如果一个问题没有改变任何决定，也没有减少需要核对的范围，先记作“帮助尚未确认”。示例能运行、检查全绿、有人下载过，都不能代替这条实际任务证据。

## 用户多，与一份文件变大，是两回事

RankProbe 在各自电脑或 CI 里运行，没有一个接收所有用户预测数据的中央服务。安装者增加不会把全部计算集中到一台机器。先遇到的压力更可能是各自机器上的大文件，以及不同导出格式带来的维护工作。

目前读取后的行、查询分组、比较结果仍保存在内存中。比较 n 份运行会生成 n(n−1)/2 对：10 份是45对，100份是4950对。HTML只显示部分证据，完整JSON仍可能很大。

报告JSON现在分段写入临时文件，不再额外拼成一整份字符串。两个报告都成功生成后才替换目标文件；写出失败会保留已有报告。这减少的是写出阶段的额外内存，不等于整个评测器已经流式运行，也没有统一的最大行数或吞吐保证。

## 遇到变慢或内存不足

- 先保留原始导出与已完成的旧报告，确认生成输入的程序已经成功结束。不要一边持续写入，一边把那份变化中的文件当作固定评测输入。
- 比较时先选与当前决定有关的两份运行，避免一次生成大量无关配对。
- 可以从原来源另存一份只含所需列的文件，保留全部行、编号、分数、标签、未知值和顺序，不要通过删难例或改标签“解决”内存问题。
- 如需按完整查询分批做独立诊断，明确各批范围；不要直接平均各批指标或把分批诊断冒充同一份全量比较。
- 提问题时提供版本、系统/Python、输入格式、约有多少行/查询/运行，以及最小可分享的复现。不要上传私人预测或包含敏感编号的完整报告。

输入前后的摘要能发现许多文件变化，但不是数据来源认证，也不证明上游导出完整。仅有当前输入，仍无法发现全部数据泄漏或未记录的筛选。

## English

Use a concrete decision, finding, action and same-protocol recheck to assess usefulness. A clean or popular report is not evidence of model quality or repeat use. Computation is local; more installations are not centralized server load. Input rows and comparison data remain in memory, and all-pairs comparison grows as n(n−1)/2. Staged incremental JSON writing reduces an extra serialization copy, not total audit memory. Keep stable complete exports and existing reports; do not drop rows or average batch metrics to force a result. File an issue with version, format and approximate workload plus a shareable synthetic reproduction, rather than private data.
