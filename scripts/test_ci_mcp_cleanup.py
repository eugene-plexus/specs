"""Exercise the teardown without starting an agent or loading its dependencies."""

import ast
import subprocess
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch


class McpCleanupTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).with_name("row59-remote-mcp-acceptance.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"stop_process", "cleanup_processes"}
        ]
        namespace = {"subprocess": subprocess, "ExitStack": ExitStack, "Path": Path}
        exec(
            compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"),
            namespace,
        )
        self.stop = namespace["stop_process"]
        self.namespace = namespace

    def test_agent_observes_stop_file_and_exits_before_any_termination(self):
        process = Mock()
        self.stop(process, graceful=True)
        process.wait.assert_called_once_with(timeout=45)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_a_graceful_shutdown_timeout_is_not_reported_as_success(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("agent", 45), 0]
        with self.assertRaisesRegex(AssertionError, "agent did not stop"):
            self.stop(process, graceful=True)
        process.terminate.assert_called_once_with()

    def test_unresponsive_stand_in_is_killed_and_reaped(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture", 10), 0]
        self.stop(process, graceful=False)
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_args.kwargs, {"timeout": 5})

    def test_stop_file_error_still_cleans_processes_logs_and_client(self):
        stop = self.namespace["stop_process"] = Mock()
        process, log, client = Mock(), Mock(), Mock()
        with patch.object(
            Path, "touch", side_effect=PermissionError("stop unavailable")
        ):
            with self.assertRaisesRegex(PermissionError, "stop unavailable"):
                self.namespace["cleanup_processes"](
                    Path("fixture"), [("agent", process)], [log], client
                )
        stop.assert_called_once_with(process, graceful=False)
        log.close.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_one_sibling_cleanup_error_does_not_skip_the_agent_or_logs(self):
        stop = self.namespace["stop_process"] = Mock(
            side_effect=[OSError("fixture failed"), None]
        )
        agent, fixture, log, client = Mock(), Mock(), Mock(), Mock()
        with patch.object(Path, "touch"):
            with self.assertRaisesRegex(OSError, "fixture failed"):
                self.namespace["cleanup_processes"](
                    Path("fixture"),
                    [("agent", agent), ("fixture", fixture)],
                    [log],
                    client,
                )
        self.assertEqual(stop.call_count, 2)
        self.assertEqual(stop.call_args.args, (agent,))
        self.assertEqual(stop.call_args.kwargs, {"graceful": True})
        log.close.assert_called_once_with()
        client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
