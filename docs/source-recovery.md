# 旧报告怎么保留，换版本后怎么再检查？

只想看旧报告，直接打开原来的 `report.html` 就行，不需要重新安装。想重新计算，则还需要原始预测文件、标签文件和当时的命令；报告中的证据可能只展示一部分，不能拿它还原完整输入。

## 现在先留好这些

- 整个结果目录，至少包括 `report.html` 和 `report.json`。
- 原始 CSV、JSONL 或 TREC 文件，以及实际使用的 qrels。没有提供的标签继续是未知。
- 当时运行的命令、工作目录和显式协议选项，包括 cutoff、标签假设与比较范围。
- 对应发行的完整 ZIP、`RELEASE_INFO.json` 和 `SHA256SUMS`。ZIP 中的 `BUILD_INFO.json` 写明公开源码提交，`MANIFEST.json` 列出内部文件的大小和摘要。

自己的输入、报告和私有代码保存在本地即可，不必上传 GitHub。摘要能核对文件是否变化，不能证明数据来源真实或实验质量可靠。

## 覆盖报告时保存失败了

先保留原报告目录，不要接着反复覆盖。程序会尝试把旧文件放回原位置；如果这一步也受阻，终端会打印 **Backups retained** 和实际备份目录。

打开提示中的 `.rankprobe-backup-...` 目录。`report.json.backup` 和 `report.html.backup` 是尚未放回去的原文件；已经恢复的那份仍在原报告目录。把两份原文件复制到一个新目录，去掉文件名末尾的 `.backup`，再打开 `report.html`。直接复制这些文件就能保留原数值和元数据，不需要重新评测。

普通保存失败后，如果旧文件已经全部恢复，仍使用原报告即可。这次失败不代表输入有问题，也不能把一个不完整的新报告当作成功结果。

## 换电脑或找回源码

1. 优先使用当时保存的完整发行 ZIP，核对校验文件后完整解压到新目录。不要把新版文件覆盖进去。
2. 需要从 Git 找回时，读取 `BUILD_INFO.json` 的 `repository`、`source_commit` 和 `source_path`，在该仓库检出那个完整提交。独立仓库的 `source_path` 是空字符串；早期课程仓库发行位于 `tools/rankprobe`。不要仅凭版本号猜仓库或提交。
3. 按该包的 `START_HERE.md` 创建独立环境，离线安装其中的 wheel；源码说明中的路径以 `source/` 为起点。
4. 用原输入和原命令写到一个新的输出目录，保留旧报告。先核对查询、候选、标签、覆盖范围和协议，再比较同一指标。

原 alpha-4 下载仍在[课程仓库原发行页](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/releases/tag/v0.1.0a4)。[alpha-5](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a5)、[alpha-6](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a6) 和 [alpha-7](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a7) 来自本独立仓库；新的 [alpha-8](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a8) 也保留对应源码。各版都有自己的校验文件，不能互相覆盖。

没有原输入或当时命令，就先把旧报告当作已有记录阅读，不要补零、编造标签或声称已经复现。跨指标资格规则变更时，按[指标语义](metrics.md)从原始输入重新计算，不能直接相减旧条件均值。

## English

Read a saved HTML report directly. Recomputing needs the original prediction files, actual qrels and command/protocol settings; sampled report evidence is not a replacement for those inputs. Keep the complete result folder, original exports, commands, release ZIP, release information and checksums locally.

Use the ZIP's `BUILD_INFO.json` to identify the public repository, exact source commit and package path, and `MANIFEST.json` to check its members. Install its bundled wheel in a fresh environment and rerun into a new output folder. Preserve old reports, unknown judgments and original inputs. Do not infer a commit from the version alone, combine versions in one folder, or modify hashes to make incompatible records pass. Checksums establish consistency, not authentic provenance or model quality. If inputs or settings are missing, keep that limitation explicit.

If an overwrite fails and rollback cannot restore every old file, the error prints **Backups retained** and a retained `.rankprobe-backup-...` directory. Files ending in `.backup` are the originals still awaiting restoration; successfully restored originals remain in the report directory. Copy both original files into a new folder, remove the `.backup` suffix where needed, and open `report.html`. This retains their bytes and metadata without recomputing. Keep both locations until you have checked the pair.
