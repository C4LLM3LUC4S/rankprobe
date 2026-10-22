# 第一次使用 / Start here

需要 Python 3.10 或更新版本。下载本仓库的 Code → Download ZIP，**完整解压**，在项目文件夹打开终端：

```powershell
python quickstart.py
```

自动生成并打开一个合成示例报告。无需 pip、虚拟环境、API 密钥或网络下载；不会修改现有 Python 环境。每次默认使用新的报告目录，旧文件保留。这是明确标记的**源码预览**，不等于已经安装独立 wheel。正式安装和自己的数据接入见 [中文说明](README.zh-CN.md) 与 [首次比较](docs/try-it.md)。

没有弹出浏览器时，打开终端打印的 `report.html`。在无图形界面环境使用 `python quickstart.py --no-open`；可用 `--out "path with spaces/new-report"` 指定一个新目录。若目录已存在，换一个新目录，不会覆盖旧报告。

先读报告中的发现及建议行动。示例中的同分和重复是有意放入的控制案例；缺失标签仍为未知。数值只能在声明的指标、可算查询和参考范围中解读，不能据此认证模型质量。

## 直接检查自己的文件

源码入口也能不安装就检查自己的合法导出。文件路径相对于终端目录，带空格时加引号：

```powershell
python quickstart.py --input "my exports/predictions.csv"
python quickstart.py --run "before=my exports/before.run" --run "after=my exports/after.run" --qrels "my exports/judgments.qrels" --cutoffs 1,5,10
```

第一条核查单文件，第二条比较两个运行。CSV/JSONL 需要 `query_id,item_id,score`，标签可选；`.run`/`.qrels` 可直接读。TREC 内容的 `.txt` 加 `--input-format trec` 和（提供 qrels 时）`--qrels-format trec`。无标签仍能查重复、同分与集合变化；指标可能不可用，不会自动补零或声明标签完整。高级协议用完整 CLI，见[使用说明](docs/usage.md)。

每次默认用新目录，原文件只读。退出码 1 表示报告完成且含错误级发现，仍会显示报告路径；2 表示命令、输入或输出失败。按[发现→行动→复核](docs/case-actions.md)处理问题。原 alpha-4 离线资产早于这个源码入口，不包含新参数。

With Python 3.10+, extract the complete source ZIP and run `python quickstart.py`. It previews the checked-out source with a built-in synthetic fixture, creates a unique report folder and opens the local HTML. It installs nothing and does not alter an existing environment. Use `--no-open` on headless systems, or `--out` with a new writable folder. For installation and real exports, follow the [main guide](README.md).

Verified alpha-4 offline packages remain at their [original release location](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/releases/tag/v0.1.0a4). Those archives are immutable and predate this source convenience launcher.

Use `python quickstart.py --input predictions.csv` for your own file, or repeat `--run NAME=FILE` at least twice to compare. Optional `--qrels`, `--cutoffs` and explicit format flags use the existing parser. Unknown labels remain unknown. Exit 1 still produces a report; exit 2 is a failed operation. See [product tasks and acceptance](docs/product-scope.md).
