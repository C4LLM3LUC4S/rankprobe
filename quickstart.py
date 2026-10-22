"""Preview the source checkout without installing packages or changing environments."""

import argparse
from datetime import datetime
from pathlib import Path
import sys
import uuid
import webbrowser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="new report folder; defaults to a unique folder under reports")
    parser.add_argument("--no-open", action="store_true", help="print the report location without opening a browser")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path, help="audit your own CSV, JSONL or TREC score file")
    inputs.add_argument("--run", action="append", help="compare runs; repeat NAME=FILE at least twice")
    parser.add_argument("--qrels", type=Path, help="optional existing judgments; missing labels stay unknown")
    parser.add_argument("--cutoffs", help="comma-separated cutoffs, for example 1,5,10")
    parser.add_argument("--input-format", choices=("auto", "csv", "jsonl", "trec"), default="auto")
    parser.add_argument("--qrels-format", choices=("auto", "csv", "jsonl", "trec"), default="auto")
    args = parser.parse_args()
    if args.run and len(args.run) < 2:
        parser.error("compare needs at least two --run NAME=FILE arguments")
    if not (args.input or args.run) and (args.qrels or args.qrels_format != "auto" or args.input_format != "auto"):
        parser.error("file and format options require --input FILE or at least two --run NAME=FILE")
    if sys.version_info < (3, 10):
        parser.exit(2, "RankProbe needs Python 3.10 or newer. Reopen with a supported Python.\n")
    root = Path(__file__).resolve().parent
    if not (root / "src/rankprobe/cli.py").is_file():
        parser.exit(2, "Extract the complete source ZIP before running quickstart.py.\n")
    sys.path.insert(0, str(root / "src"))
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    label = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = args.out.resolve() if args.out else root / "reports" / ("first-report-" + label)
    if output.exists():
        parser.exit(2, "Output already exists. Choose a new --out folder; existing reports are preserved.\n")
    from rankprobe.cli import main as run
    print("RankProbe source preview / 源码预览；不安装依赖，不修改已有环境。")
    if args.input:
        command = ["audit", str(args.input)]
    elif args.run:
        command = ["compare"]
        for entry in args.run:
            command.extend(["--run", entry])
    else:
        command = ["demo"]
        print("Synthetic example / 合成示例：同分、重复候选和未知标签，并非模型评测。")
    if args.input or args.run:
        print("Local files / 本地文件：仅生成本地报告；缺失标签保持未知，分享前检查报告中的标识符。")
    for option, value in (("--qrels", args.qrels), ("--cutoffs", args.cutoffs),
                          ("--input-format", args.input_format), ("--qrels-format", args.qrels_format)):
        if value is not None:
            command.extend([option, str(value)])
    command.extend(["--out", str(output)])
    try:
        status = run(command)
    except OSError as exc:
        parser.exit(2, f"Could not save the report: {exc}. Choose a writable --out folder.\n")
    if status not in (0, 1):
        return status
    if status == 1:
        print("Report completed with error findings / 报告已生成并包含错误级发现；请先检查报告。")
    report = (output / "report.html").resolve()
    print("Open report / 打开报告：" + str(report))
    if not args.no_open:
        try:
            webbrowser.open(report.as_uri())
        except (OSError, webbrowser.Error):
            print("Browser unavailable. Open the HTML file at the printed location.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
