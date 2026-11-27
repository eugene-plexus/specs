"""Use the existing stop budget for children instead of a fixed sleep."""

import ast
import contextlib
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock


class HarnessCleanupTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).with_name("harness-acceptance.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Run"
        )
        methods = [
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"stops_by_the_file", "kill_family"}
        ]
        self.child = Mock(pid=123)
        self.child.children.return_value = []
        self.child.ppid.return_value = 42
        self.child.create_time.return_value = 2.0
        self.psutil = Mock(Error=RuntimeError, STATUS_ZOMBIE="zombie")
        self.psutil.NoSuchProcess = ProcessLookupError
        parent = self.psutil.Process.return_value
        parent.pid = 42
        parent.ppid.return_value = 1
        parent.create_time.return_value = 1.0
        parent.children.return_value = [self.child]
        self.clock = Mock()
        self.clock.perf_counter.side_effect = [0, 2, 4]
        namespace = {
            "psutil": self.psutil,
            "time": self.clock,
            "subprocess": subprocess,
            "contextlib": contextlib,
            "Failed": RuntimeError,
            "STOP_WITHIN_SECONDS": 15,
        }
        exec(
            compile(
                ast.Module(
                    body=[
                        ast.parse("from __future__ import annotations").body[0],
                        *[
                            node for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name == "descendants"
                        ],
                        *methods,
                    ],
                    type_ignores=[],
                ),
                str(source),
                "exec",
            ),
            namespace,
        )
        self.stop = namespace["stops_by_the_file"]
        self.kill_family = namespace["kill_family"]
        self.run = SimpleNamespace(
            proc=Mock(pid=42, returncode=0),
            root=MagicMock(),
            kill_family=Mock(),
            _name=lambda process: "conhost.exe",
        )

    def test_child_exiting_after_one_second_but_within_budget_is_not_a_leak(self):
        self.psutil.wait_procs.return_value = ([self.child], [])
        self.assertIn("none left", self.stop(self.run))
        self.psutil.wait_procs.assert_called_once_with([self.child], timeout=13)
        self.child.kill.assert_not_called()

    def test_child_alive_at_deadline_still_fails_and_is_cleaned(self):
        self.psutil.wait_procs.return_value = ([], [self.child])
        with self.assertRaisesRegex(
            RuntimeError, "left running after the stop: 123 conhost.exe"
        ):
            self.stop(self.run)
        self.psutil.wait_procs.assert_called_once_with([self.child], timeout=13)
        self.child.kill.assert_called_once_with()

    def test_reused_intermediate_pid_does_not_claim_an_unrelated_process(self):
        alien = Mock(pid=456)
        # psutil's recursive walk checks every age against the root. A stale
        # PPID can therefore admit a process newer than the root but older
        # than its alleged immediate parent. Direct children() rejects it.
        self.psutil.Process.return_value.children.side_effect = (
            lambda recursive=False: [self.child, alien] if recursive else [self.child]
        )
        self.psutil.wait_procs.side_effect = (
            lambda family, timeout: ([self.child], [alien] if alien in family else [])
        )
        self.assertIn("none left", self.stop(self.run))
        self.psutil.wait_procs.assert_called_once_with([self.child], timeout=13)
        alien.kill.assert_not_called()

    def test_real_grandchild_is_still_checked(self):
        grandchild = Mock(pid=456)
        grandchild.children.return_value = []
        grandchild.ppid.return_value = 123
        grandchild.create_time.return_value = 3.0
        self.psutil.Process.return_value.children.side_effect = (
            lambda recursive=False: [self.child, grandchild] if recursive else [self.child]
        )
        self.child.children.return_value = [grandchild]
        self.psutil.wait_procs.return_value = ([self.child], [grandchild])
        with self.assertRaisesRegex(RuntimeError, "456 conhost.exe"):
            self.stop(self.run)
        grandchild.kill.assert_called_once_with()

    def test_emergency_cleanup_also_avoids_the_unrelated_process(self):
        alien = Mock(pid=456)
        self.psutil.Process.return_value.children.side_effect = (
            lambda recursive=False: [self.child, alien] if recursive else [self.child]
        )
        self.kill_family(self.run)
        self.child.kill.assert_called_once_with()
        self.run.proc.kill.assert_called_once_with()
        alien.kill.assert_not_called()

    def test_child_disappearing_during_capture_does_not_abort_shutdown(self):
        self.child.children.side_effect = ProcessLookupError
        self.psutil.wait_procs.return_value = ([self.child], [])
        self.assertIn("none left", self.stop(self.run))

    def test_parent_reused_during_capture_does_not_claim_new_children(self):
        self.psutil.Process.return_value.is_running.return_value = False
        self.kill_family(self.run)
        self.child.kill.assert_not_called()

    def test_child_exiting_during_final_status_check_is_gone(self):
        self.child.status.side_effect = ProcessLookupError
        self.psutil.wait_procs.return_value = ([], [self.child])
        self.assertIn("none left", self.stop(self.run))
        self.child.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
