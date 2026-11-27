"""A transient Windows directory lock is not a reason to rerun acceptance."""

import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import ci_cleanup


def locked():
    error = PermissionError("fixture directory is still in use")
    error.winerror = 32
    return error


class CleanupTests(unittest.TestCase):
    def test_transient_sharing_violation_is_named_then_cleanup_finishes(self):
        directory = Mock(name="temporary directory")
        directory.name = tempfile.gettempdir()
        directory.cleanup.side_effect = [locked(), None]
        output = io.StringIO()
        with patch.object(ci_cleanup.time, "sleep"), redirect_stdout(output):
            ci_cleanup.cleanup(directory, Path(directory.name).resolve())
        self.assertEqual(directory.cleanup.call_count, 2)
        self.assertIn("fixture directory is still in use", output.getvalue())

    def test_persistent_lock_still_fails(self):
        directory = Mock()
        directory.name = tempfile.gettempdir()
        directory.cleanup.side_effect = locked()
        with (
            patch.object(ci_cleanup.time, "perf_counter", side_effect=[0, 11]),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(PermissionError):
                ci_cleanup.cleanup(directory, Path(directory.name).resolve())

    def test_other_errors_are_not_retried(self):
        directory = Mock()
        directory.name = tempfile.gettempdir()
        directory.cleanup.side_effect = PermissionError("access denied")
        with self.assertRaisesRegex(PermissionError, "access denied"):
            ci_cleanup.cleanup(directory, Path(directory.name).resolve())
        self.assertEqual(directory.cleanup.call_count, 1)

    def test_changed_directory_target_is_never_cleaned(self):
        directory = Mock()
        directory.name = tempfile.gettempdir()
        with self.assertRaisesRegex(RuntimeError, "target changed"):
            ci_cleanup.cleanup(directory, Path(directory.name).resolve() / "different")
        directory.cleanup.assert_not_called()

    def test_finalizer_cannot_bypass_a_refused_cleanup(self):
        factory = tempfile.TemporaryDirectory
        created = []

        def capture(**kwargs):
            directory = factory(**kwargs)
            created.append(directory)
            return directory

        try:
            with (
                patch.object(
                    ci_cleanup.tempfile, "TemporaryDirectory", side_effect=capture
                ),
                patch.object(
                    ci_cleanup, "cleanup", side_effect=RuntimeError("target changed")
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "target changed"):
                    with ci_cleanup.temporary_directory(prefix="ep-cleanup-guard-"):
                        pass
            created[0]._finalizer()  # simulate collection after the guard refused
            self.assertTrue(Path(created[0].name).exists())
        finally:
            for directory in created:
                directory.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows cwd locking")
    def test_real_child_releases_directory_before_cleanup_completes(self):
        process = None
        timer = None
        try:
            with ci_cleanup.temporary_directory(prefix="ep-cleanup-test-") as folder:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "import sys; print('ready', flush=True); sys.stdin.readline()",
                    ],
                    cwd=folder,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                self.assertEqual(process.stdout.readline().strip(), "ready")
                timer = threading.Timer(0.5, lambda: process.communicate("exit\n"))
                timer.start()
            self.assertFalse(Path(folder).exists())
        finally:
            if timer is not None:
                timer.join(timeout=5)
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
