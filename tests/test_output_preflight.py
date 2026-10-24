"""An occupied report must be rejected before reading or auditing inputs."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rankprobe import cli


class OutputPreflightTests(unittest.TestCase):
    def invoke(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            status = cli.main(arguments)
        return status, error.getvalue()

    def input_file(self, root):
        source = root / "own export.csv"
        source.write_text("query_id,item_id,score,relevance\nq1,a,1,1\nq1,b,0,0\nq2,c,1,\n",
                          encoding="utf-8")
        return source

    def test_occupied_report_rejects_before_loading_and_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.input_file(root)
            commands = [["audit", str(source)],
                        ["compare", "--run", f"left={source}", "--run", f"right={source}"],
                        ["demo"]]
            for arguments in commands:
                with self.subTest(command=arguments[0]):
                    target = root / arguments[0]
                    target.mkdir()
                    original = target / "report.json"
                    original.write_bytes(b'{"unknown": null, "keep": "original report"}\n')
                    before = original.read_bytes()
                    with patch.object(cli, "_load_checked", wraps=cli._load_checked) as loading, \
                            patch.object(cli, "audit_run", wraps=cli.audit_run) as audit, \
                            patch.object(cli, "compare_runs", wraps=cli.compare_runs) as comparison:
                        status, error = self.invoke([*arguments, "--out", str(target)])
                    self.assertEqual(status, 2, error)
                    self.assertEqual(original.read_bytes(), before)
                    self.assertFalse((target / "report.html").exists())
                    loading.assert_not_called()
                    audit.assert_not_called()
                    comparison.assert_not_called()
                    self.assertIn("--overwrite", error)

    def test_file_parent_rejects_before_input_loading_at_each_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.input_file(root)
            commands = [["audit", str(source)],
                        ["compare", "--run", f"left={source}", "--run", f"right={source}"],
                        ["demo"]]
            for arguments in commands:
                parent = root / (arguments[0] + " parent file")
                parent.write_bytes(b"keep the original parent file")
                for parts in (("new report",), ("missing", "new report")):
                    with self.subTest(command=arguments[0], depth=len(parts)):
                        target = parent.joinpath(*parts)
                        with patch.object(cli, "_load_checked", wraps=cli._load_checked) as loading, \
                                patch.object(cli, "audit_run", wraps=cli.audit_run) as audit, \
                                patch.object(cli, "compare_runs", wraps=cli.compare_runs) as comparison:
                            status, error = self.invoke([*arguments, "--out", str(target)])
                        self.assertEqual(status, 2, error)
                        self.assertEqual(parent.read_bytes(), b"keep the original parent file")
                        loading.assert_not_called()
                        audit.assert_not_called()
                        comparison.assert_not_called()
                        self.assertIn("--out", error)

    def test_unrelated_files_and_explicit_overwrite_still_allow_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.input_file(root)
            for overwrite in (False, True):
                with self.subTest(overwrite=overwrite):
                    target = root / str(overwrite)
                    target.mkdir()
                    unrelated = target / "keep.txt"
                    unrelated.write_bytes(b"unrelated saved file")
                    if overwrite:
                        (target / "report.json").write_bytes(b"old report")
                    status, error = self.invoke(["audit", str(source), "--out", str(target),
                        "--cutoffs", "1,2", "--fail-on", "never", *(["--overwrite"] if overwrite else [])])
                    self.assertEqual(status, 0, error)
                    report = json.loads((target / "report.json").read_text(encoding="utf-8"))
                    self.assertEqual(report["summary"]["unknown_candidates"], 1)
                    self.assertEqual(report["summary"]["assumed_nonrelevant_candidates"], 0)
                    self.assertTrue((target / "report.html").is_file())
                    self.assertEqual(unrelated.read_bytes(), b"unrelated saved file")


if __name__ == "__main__":
    unittest.main()
