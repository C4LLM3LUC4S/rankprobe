"""A failed rollback must not delete the only remaining previous report."""

from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rankprobe.audit import audit_run
from rankprobe.cli import main
from rankprobe.model import Protocol, Row
from rankprobe.report import write_report


class ReportRecoveryTests(unittest.TestCase):
    def original(self, folder):
        value = audit_run([Row("q1", "a", 1, 1), Row("q2", "b", 0, None)],
                          Protocol(cutoffs=(1,)))
        write_report(value, folder)
        return {name: (folder / name).read_bytes() for name in ("report.json", "report.html")}

    def test_failed_restore_retains_every_old_file_and_allows_copy_recovery(self):
        for blocked in ({"report.json.backup"}, {"report.json.backup", "report.html.backup"}):
            with self.subTest(blocked=blocked), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary) / "old report"
                before = self.original(folder)
                (folder / "notes.txt").write_bytes(b"unrelated file")
                actual = os.replace

                def fail(source, target):
                    source, target = Path(source), Path(target)
                    if source.name == "report.html" and target == folder / "report.html":
                        raise OSError("injected late installation error")
                    if source.name in blocked and target.parent == folder:
                        raise PermissionError("injected rollback lock")
                    return actual(source, target)

                with patch("rankprobe.report.os.replace", side_effect=fail):
                    with self.assertRaises(OSError) as failed:
                        write_report({"findings": [], "marker": "new result"}, folder, overwrite=True)
                survivors = {path.name: path for path in folder.rglob("*.backup")}
                recovered = Path(temporary) / "recovered report"
                recovered.mkdir()
                for name, content in before.items():
                    original = folder / name
                    source = original if original.exists() else survivors.get(name + ".backup")
                    self.assertIsNotNone(source, name + " was lost after failed rollback")
                    self.assertEqual(source.read_bytes(), content)
                    (recovered / name).write_bytes(source.read_bytes())
                self.assertIn("Backups retained", str(failed.exception))
                self.assertTrue(failed.exception.recovery_dir.is_dir())
                self.assertEqual((folder / "notes.txt").read_bytes(), b"unrelated file")
                self.assertEqual({name: (recovered / name).read_bytes() for name in before}, before)

    def test_unlink_failure_does_not_prevent_restoring_other_originals(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "report"
            before = self.original(folder)
            actual_replace, actual_unlink = os.replace, Path.unlink

            def fail_install(source, target):
                if Path(source).name == "report.html" and Path(target) == folder / "report.html":
                    raise OSError("injected late installation error")
                return actual_replace(source, target)

            def fail_unlink(path, *args, **kwargs):
                if path == folder / "report.json":
                    raise PermissionError("injected new-file cleanup error")
                return actual_unlink(path, *args, **kwargs)

            with patch("rankprobe.report.os.replace", side_effect=fail_install), \
                    patch.object(Path, "unlink", fail_unlink):
                with self.assertRaises(OSError):
                    write_report({"findings": []}, folder, overwrite=True)
            self.assertEqual({name: (folder / name).read_bytes() for name in before}, before)

    def test_cli_points_to_actual_retained_backups_without_touching_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "original.csv"
            source.write_bytes(b"query_id,item_id,score,relevance\nq1,a,1,1\n")
            original = source.read_bytes()
            folder = root / "report"
            before = self.original(folder)
            actual = os.replace

            def fail(source_path, target):
                source_path, target = Path(source_path), Path(target)
                if source_path.name == "report.html" and target == folder / "report.html":
                    raise OSError("injected HTML write failure")
                if source_path.name.endswith(".backup") and target.parent == folder:
                    raise PermissionError("injected rollback lock")
                return actual(source_path, target)

            error = io.StringIO()
            with patch("rankprobe.report.os.replace", side_effect=fail), redirect_stderr(error):
                code = main(["audit", str(source), "--out", str(folder), "--overwrite"])
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", error.getvalue())
            self.assertIn("Backups retained", error.getvalue())
            self.assertEqual(source.read_bytes(), original)
            backup = next(folder.glob(".rankprobe-backup-*"))
            self.assertIn(str(backup), error.getvalue())
            self.assertEqual({name: (backup / (name + ".backup")).read_bytes() for name in before}, before)

    def test_cleanup_lock_keeps_new_complete_pair_and_reports_retained_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "report"
            before = self.original(folder)
            actual = Path.unlink

            def fail(path, *args, **kwargs):
                if path.name.endswith(".backup"):
                    raise PermissionError("injected old-backup cleanup lock")
                return actual(path, *args, **kwargs)

            error = io.StringIO()
            with patch.object(Path, "unlink", fail), redirect_stderr(error):
                write_report({"findings": [], "marker": "new complete result"}, folder, overwrite=True)
            self.assertIn(b"new complete result", (folder / "report.json").read_bytes())
            self.assertTrue((folder / "report.html").is_file())
            backup = next(folder.glob(".rankprobe-backup-*"))
            self.assertIn(str(backup), error.getvalue())
            self.assertEqual({name: (backup / (name + ".backup")).read_bytes() for name in before}, before)


if __name__ == "__main__":
    unittest.main()
