"""Command-line entry points for local ranking audits."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sys
from typing import Sequence, TextIO

from . import __version__
from .audit import audit_run, compare_runs
from .io import _float, _input_format, read_predictions, read_qrels
from .model import Protocol
from .report import check_report_destination, write_report


_CORE_FILES = (
    "__init__.py", "__main__.py", "audit.py", "cli.py", "demo.py",
    "io.py", "metrics.py", "model.py", "report.py",
)


def _core_source_identity() -> dict:
    scheme = "rankprobe-core-python-v1"
    try:
        package = files("rankprobe")
        hashes = {
            name: hashlib.sha256(package.joinpath(name).read_bytes()).hexdigest()
            for name in _CORE_FILES
        }
    except OSError:
        return {
            "scheme": scheme,
            "status": "unavailable",
            "reason": "The core Python source files could not all be read.",
        }
    manifest = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("ascii")
    return {
        "scheme": scheme, "status": "available",
        "sha256": hashlib.sha256(manifest).hexdigest(), "files": hashes,
    }


def _console(message: str, *, file: TextIO | None = None) -> None:
    stream = sys.stdout if file is None else file
    try:
        print(message, file=stream)
    except UnicodeEncodeError:
        encoding = stream.encoding or "ascii"
        escaped = message.encode(encoding, errors="backslashreplace").decode(encoding)
        print(escaped, file=stream)


def _cutoffs(value: str) -> tuple[int, ...]:
    try:
        numbers = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "cutoffs must be comma-separated positive integers, for example 1,5,10"
        ) from exc
    if not numbers or any(item < 1 for item in numbers):
        raise argparse.ArgumentTypeError("cutoffs must be positive integers")
    return tuple(sorted(set(numbers)))


def _threshold(value: str) -> int | float:
    try:
        return _float(value, "relevance threshold")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _run(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "use --run NAME=FILE, for example --run baseline=baseline.csv"
        )
    name, filename = value.split("=", 1)
    if not name.strip() or not filename.strip():
        raise argparse.ArgumentTypeError("--run needs both a nonempty name and a file path")
    return name.strip(), Path(filename)


def _mrr_drop(value: str) -> tuple[str, float]:
    try:
        metric, drop = value.split("=", 1)
        return metric, _float(drop, "MRR drop")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use mrr@K=DROP, for example mrr@10=0.01") from exc


def _guard_policy(arguments: argparse.Namespace) -> dict | None:
    if arguments.command != "compare":
        return None
    values = (arguments.max_mrr_drop, arguments.min_guard_queries, arguments.guard_baseline_sha256)
    if not any(value is not None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("use --max-mrr-drop, --min-guard-queries and --guard-baseline-sha256 together")
    from .regression_guard import make_policy

    metric, drop = arguments.max_mrr_drop
    policy = make_policy(metric, drop, arguments.min_guard_queries, arguments.guard_baseline_sha256)
    if len(arguments.run) != 2:
        raise ValueError("the optional MRR guard needs exactly two --run inputs; the first is the frozen baseline")
    if int(metric.split("@")[1]) not in arguments.cutoffs:
        raise ValueError("the guarded MRR cutoff must be included in --cutoffs")
    return policy


def _guard_source_identity() -> dict:
    try:
        digest = hashlib.sha256(files("rankprobe").joinpath("regression_guard.py").read_bytes()).hexdigest()
    except OSError:
        return {"status": "unavailable", "file": "regression_guard.py"}
    return {"status": "available", "file": "regression_guard.py", "sha256": digest}


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--qrels", type=Path, help="CSV/JSONL judgments or four-column TREC qrels"
    )
    parser.add_argument(
        "--qrels-format",
        choices=("auto", "csv", "jsonl", "trec"),
        default="auto",
        help="judgment format; auto recognizes .csv/.jsonl/.qrels (use trec for .txt)",
    )
    parser.add_argument(
        "--qrels-complete",
        action="store_true",
        help="assert supplied judgments cover the intended relevance universe (required for Recall)",
    )
    parser.add_argument(
        "--unjudged",
        choices=("unknown", "nonrelevant"),
        default="unknown",
        help="unknown keeps missing labels unknown; nonrelevant explicitly treats them as zero (default: unknown)",
    )
    parser.add_argument(
        "--cutoffs",
        type=_cutoffs,
        default=(1, 5, 10),
        metavar="K,K,...",
        help="positive cutoffs (default: 1,5,10)",
    )
    parser.add_argument(
        "--gain",
        choices=("linear", "exp2"),
        default="linear",
        help="NDCG gain function (default: linear)",
    )
    parser.add_argument(
        "--tie-policy",
        choices=("item_id", "input"),
        default="item_id",
        help="break equal scores by item ID or original input order (default: item_id)",
    )
    parser.add_argument(
        "--relevance-threshold",
        type=_threshold,
        default=0.0,
        help="binary relevance means label > threshold (default: 0)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="DIR",
        help="write report.json and self-contained report.html here",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace only report.json/report.html if they exist; retain other files",
    )
    parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default="error",
        help="exit 1 on findings at this severity or higher (default: error); invalid input always exits 2",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rankprobe",
        description="Inspect ranking evaluations for ties, duplicates, relevance coverage, and protocol differences. Runs locally; makes no network requests.",
    )
    parser.add_argument("--version", action="version", version=f"RankProbe {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="audit one prediction file")
    audit.add_argument(
        "predictions",
        type=Path,
        help="CSV/JSONL scores or a six-column TREC .run/.trec file",
    )
    audit.add_argument("--name", default=None, help="display name (default: input file stem)")
    _common(audit)
    compare = commands.add_parser(
        "compare", help="audit multiple runs and check whether they are comparable"
    )
    compare.add_argument(
        "--run",
        type=_run,
        action="append",
        required=True,
        metavar="NAME=FILE",
        help="repeat once per run; use distinct names",
    )
    compare.add_argument("--max-mrr-drop", type=_mrr_drop, metavar="mrr@K=DROP",
                         help="optional declared absolute MRR tolerance; requires both guard options below")
    compare.add_argument("--min-guard-queries", type=int, metavar="N",
                         help="declared minimum count; every submitted query must remain eligible")
    compare.add_argument("--guard-baseline-sha256", metavar="HEX",
                         help="predeclared SHA256 of the first --run input, which is the frozen baseline")
    for command in (audit, compare):
        command.add_argument(
            "--input-format",
            choices=("auto", "csv", "jsonl", "trec"),
            default="auto",
            help="prediction format (all runs in compare); auto recognizes .csv/.jsonl/.run/.trec",
        )
    _common(compare)
    demo = commands.add_parser(
        "demo", help="generate a report from a small built-in example with deliberate pitfalls"
    )
    _common(demo)
    return parser


def _protocol(arguments: argparse.Namespace) -> Protocol:
    return Protocol(
        cutoffs=arguments.cutoffs,
        tie_policy=arguments.tie_policy,
        gain=arguments.gain,
        relevance_threshold=arguments.relevance_threshold,
        unjudged=arguments.unjudged,
        qrels_complete=arguments.qrels_complete,
    )


def _finding_exit(report: dict, fail_on: str) -> int:
    levels = {"error": 2, "warning": 1, "info": 0}
    threshold = {"error": 2, "warning": 1, "never": 3}[fail_on]
    return int(
        any(
            levels.get(str(finding.get("severity", "info")).lower(), 0) >= threshold
            for finding in report.get("findings", [])
        )
    )


def _source(path: Path, role: str, run_name: str | None = None) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    result = {"role": role, "filename": path.name, "sha256": digest.hexdigest(), "bytes": size}
    if run_name is not None:
        result["run_name"] = run_name
    return result


def _load_checked(
    path: Path, loader, role: str, run_name: str | None = None, *, format: str = "auto"
):
    before = _source(path, role, run_name)
    data = loader(path) if format == "auto" else loader(path, format=format)
    after = _source(path, role, run_name)
    if before["sha256"] != after["sha256"] or before["bytes"] != after["bytes"]:
        raise ValueError(f"{path.name}: input changed while being read; retry with a stable file")
    after["input_format"] = _input_format(path, format, qrels=role == "qrels")
    if after["input_format"] == "trec" and role == "predictions":
        after["ordering_note"] = (
            "TREC rank, iteration and run tag fields do not determine ranking. "
            "Scores descend; the selected tie policy resolves equal scores."
        )
    return data, after


def _protect_inputs(paths: list[Path], output: Path) -> None:
    destinations = [output / filename for filename in ("report.json", "report.html")]
    for source in paths:
        for destination in destinations:
            try:
                same_path = source.resolve() == destination.resolve()
            except RuntimeError as exc:
                # Python 3.10-3.12 use RuntimeError for symbolic-link loops.
                raise ValueError(f"cannot resolve input or output path: {exc}") from exc
            same_file = (
                source.exists() and destination.exists() and source.samefile(destination)
            )
            if same_path or same_file:
                raise ValueError(
                    f"output report would replace input {source.name!r}; choose another --out directory"
                )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        guard_policy = _guard_policy(arguments)
        inputs = [arguments.qrels] if arguments.qrels else []
        if arguments.command == "audit":
            inputs.append(arguments.predictions)
        elif arguments.command == "compare":
            inputs.extend(path for _, path in arguments.run)
        _protect_inputs(inputs, arguments.out)
        check_report_destination(arguments.out, overwrite=arguments.overwrite)
        protocol = _protocol(arguments)
        qrels, sources = None, []
        if arguments.qrels_format != "auto" and not arguments.qrels:
            raise ValueError("--qrels-format requires --qrels FILE")
        if arguments.qrels:
            qrels, source = _load_checked(
                arguments.qrels, read_qrels, "qrels", format=arguments.qrels_format
            )
            sources.append(source)
        if arguments.command == "audit":
            name = arguments.name or arguments.predictions.stem
            rows, source = _load_checked(
                arguments.predictions, read_predictions, "predictions", name,
                format=arguments.input_format,
            )
            report = audit_run(rows, protocol, qrels=qrels, run_name=name)
            sources.append(source)
        elif arguments.command == "compare":
            if len(arguments.run) < 2:
                raise ValueError("compare needs at least two --run NAME=FILE arguments")
            names = [name for name, _ in arguments.run]
            if len(set(names)) != len(names):
                raise ValueError(
                    "run names must be unique; each --run NAME=FILE needs a different name"
                )
            runs = {}
            for name, path in arguments.run:
                runs[name], source = _load_checked(
                    path, read_predictions, "predictions", name, format=arguments.input_format
                )
                sources.append(source)
            report = compare_runs(runs, protocol, qrels=qrels)
        else:
            from .demo import demo_rows

            report = audit_run(demo_rows(), protocol, qrels=qrels, run_name="built-in-demo")
            report["demo_note"] = (
                "Synthetic demonstration with intentional ties, duplicate candidates and an unknown relevance label. It is not a model evaluation."
            )
        report["provenance"] = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rankprobe_version": __version__,
            "core_source_identity": _core_source_identity(),
            "command": arguments.command,
            "sources": sources,
            "source_path_policy": "Only filenames are stored; absolute local paths and raw command lines are omitted.",
        }
        if guard_policy is not None:
            from .regression_guard import decide

            report["regression_guard"] = decide(report, guard_policy, sources)
            report["provenance"]["regression_guard"] = {
                "policy": guard_policy, "source_identity": _guard_source_identity(),
            }
        json_path, html_path = write_report(report, arguments.out, overwrite=arguments.overwrite)
    except (ValueError, OSError) as exc:
        _console(f"rankprobe: {exc}", file=sys.stderr)
        return 2
    counts = {
        severity: sum(finding.get("severity") == severity for finding in report.get("findings", []))
        for severity in ("error", "warning", "info")
    }
    _console(
        f"RankProbe: {counts['error']} errors, {counts['warning']} warnings, {counts['info']} informational findings"
    )
    _console(f"HTML: {html_path.resolve()}")
    _console(f"JSON: {json_path.resolve()}")
    guard = report.get("regression_guard")
    if guard:
        _console(f"MRR guard: {guard['status']} — {guard['next_step']}")
    return max(_finding_exit(report, arguments.fail_on), int(bool(guard and guard["status"] != "pass")))


if __name__ == "__main__":
    raise SystemExit(main())
