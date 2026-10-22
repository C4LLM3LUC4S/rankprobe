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
    args = parser.parse_args()
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
    print("Synthetic example / 合成示例：同分、重复候选和未知标签，并非模型评测。")
    try:
        status = run(["demo", "--out", str(output)])
    except OSError as exc:
        parser.exit(2, f"Could not save the report: {exc}. Choose a writable --out folder.\n")
    if status:
        return status
    report = (output / "report.html").resolve()
    print("Open report / 打开报告：" + str(report))
    if not args.no_open:
        try:
            webbrowser.open(report.as_uri())
        except (OSError, webbrowser.Error):
            print("Browser unavailable. Open the HTML file at the printed location.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
