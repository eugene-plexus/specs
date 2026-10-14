"""LS5's real wait helper retains a stalled run and diagnostic failures."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
import unittest

import httpx

SOURCE = Path(__file__).with_name("ls5-preparation-acceptance.py")


class Clock:
    now = 0.0

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class WaitChecks(unittest.TestCase):
    def setUp(self) -> None:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        functions: list[ast.stmt] = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in {"wait", "until"}
        ]
        self.namespace: dict[str, Any] = {"time": Clock(), "httpx": httpx, "Any": Any}
        exec(
            compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"),
            self.namespace,
        )

    def test_ready_returns_its_record(self) -> None:
        record = {"step": "ready", "id": "fixture"}
        self.namespace["record"] = lambda _: record
        self.assertIs(self.namespace["until"]("fixture", ("ready",), 0.5), record)

    def test_stalled_run_retains_its_state_and_observed_reason(self) -> None:
        self.namespace["record"] = lambda _: {
            "step": "awaiting_confirmation",
            "error": "not enough free disk space",
        }
        with self.assertRaisesRegex(
            AssertionError, "awaiting_confirmation.*not enough free disk"
        ):
            self.namespace["until"]("fixture", ("preparing", "failed", "ready"), 0.5)

    def test_a_failed_diagnostic_does_not_replace_the_timeout(self) -> None:
        def unavailable() -> None:
            raise httpx.ConnectError("diagnostic refused")

        with self.assertRaisesRegex(
            AssertionError, "timed out: fixture.*ConnectError.*diagnostic refused"
        ):
            self.namespace["wait"](
                lambda: False, "fixture", 0.5, diagnostic=unavailable
            )


if __name__ == "__main__":
    unittest.main()
