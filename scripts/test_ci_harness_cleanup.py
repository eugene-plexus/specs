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
        method = next(
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "stops_by_the_file"
        )
        self.child = Mock(pid=123)
        self.psutil = Mock(Error=RuntimeError, STATUS_ZOMBIE="zombie")
        self.psutil.Process.return_value.children.return_value = [self.child]
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
            compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"),
            namespace,
        )
        self.stop = namespace["stops_by_the_file"]
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


if __name__ == "__main__":
    unittest.main()
