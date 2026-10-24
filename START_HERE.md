# 第一次使用 / Start here

需要 Python 3.10 或更新版本。下载本仓库的 Code → Download ZIP，**完整解压**，在项目文件夹打开终端：

```powershell
python quickstart.py
```

程序会生成并打开一份演示报告，数据中有意放入了同分、重复项目和缺失标签。无需安装依赖或联网下载，也不会修改现有 Python 环境。每次默认使用新目录，旧报告会保留。这个入口直接运行你下载的源码；需要安装到独立环境时，见 [中文说明](README.zh-CN.md)。

没有弹出浏览器时，打开终端打印的 `report.html`。在无图形界面环境使用 `python quickstart.py --no-open`；可用 `--out "path with spaces/new-report"` 指定一个新目录。若目录已存在，换一个新目录，不会覆盖旧报告。

先看“需要核对的地方”。每项会说明发现了什么、可能影响什么，以及下一步该检查哪里。没有标签的项目仍是未知，不会自动算成不相关。

比较两份结果时，先看同一张指标卡里的两次分数，不要把 MRR 和 NDCG 互相比大小。再看分数旁的查询数量：两次平均分使用的数据不同，就不能只凭平均分更高判断改进。

## 直接检查自己的文件

有自己的预测文件时，可以直接检查。路径从当前终端所在目录算起，带空格时加引号：

```powershell
python quickstart.py --input "my exports/predictions.csv"
python quickstart.py --run "before=my exports/before.run" --run "after=my exports/after.run" --qrels "my exports/judgments.qrels" --cutoffs 1,5,10
```

第一条检查一份文件，第二条比较前后两次结果。CSV/JSONL 每行需要 `query_id,item_id,score`，标签可以不提供；TREC 格式的 `.run`/`.qrels` 文件也可以直接读取。没有标签时，仍能检查重复、同分和集合变化，部分指标则无法计算。

如果 TREC 文件使用 `.txt` 后缀，请加 `--input-format trec`；标签文件也使用 `.txt` 时，再加 `--qrels-format trec`。更多评测选项见[使用说明](docs/usage.md)。

程序只读取原文件，并把结果保存到新目录。看完后可以按[发现问题、处理、再检查](docs/case-actions.md)选择下一步；先确认问题再修改导出，不必为了消除警告而改数据。

## 遇到问题时

- 找不到文件：检查终端所在目录和文件路径，带空格的路径要加引号。
- 提示 `cannot read input as UTF-8`：文件没能按 UTF-8 读出来。回到生成它的程序，另存一份 UTF-8 文件，再用新路径重试；原文件先留着。不要选择“忽略”或“替换”错误字符，编号、分数、标签、缺失值和行顺序都要保持原样。具体检查方法见[文件编码说明](docs/input-format.md#text-encoding-errors)。
- 输出目录已存在：用 `--out` 指定新目录，保留原报告。
- 显示 `Not available` 或“无法计算”：查看标签和查询范围，不能把它当作零分。
- 命令返回退出码 `1`：报告已生成，但有需要优先处理的问题，打开打印的 HTML 路径查看。
- 命令返回退出码 `2`：这次操作失败，按终端提示检查命令、输入格式或输出权限。

alpha-6 离线包已包含这些参数，以及分段写入报告和完整任务验收说明，见[本版说明](docs/releases/0.1.0a6.md)。旧报告先原样保留；换版本时，按[源码与报告恢复](docs/source-recovery.md)保存输入、命令和对应源码。

## English

With Python 3.10+, extract the complete source ZIP and run `python quickstart.py`. It previews the checked-out source with a built-in synthetic fixture, creates a unique report folder and opens the local HTML. It installs nothing and does not alter an existing environment. Use `--no-open` on headless systems, or `--out` with a new writable folder. For installation and real exports, follow the [main guide](README.md).

Verified alpha-4 offline packages remain at their [original release location](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/releases/tag/v0.1.0a4). The independent repository's [alpha-5 release](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a5) is also preserved. The [alpha-6 bundle](https://github.com/C4LLM3LUC4S/rankprobe/releases/tag/v0.1.0a6) includes staged report writing and the current launcher; see [source and report recovery](docs/source-recovery.md) before rerunning old inputs.

Use `python quickstart.py --input predictions.csv` for your own file, or repeat `--run NAME=FILE` at least twice to compare. Optional `--qrels`, `--cutoffs` and explicit format flags use the existing parser. Unknown labels remain unknown. Exit 1 still produces a report; exit 2 is a failed operation. See [product tasks and acceptance](docs/product-scope.md).

If a file cannot be read as UTF-8, re-export a new UTF-8 copy from its original source and keep the original. Do not skip or replace undecodable bytes. Check identifiers, numeric values, labels, unknowns and row order before retrying; see [encoding recovery](docs/input-format.md#text-encoding-errors).
