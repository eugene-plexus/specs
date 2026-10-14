"""P3 distinguishes a streamed response from buffering despite startup delay."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
import unittest

SOURCE = Path(__file__).with_name("p3-audio-acceptance.py")


class StreamingChecks(unittest.TestCase):
    def setUp(self) -> None:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        functions: list[ast.stmt] = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "streamed"
        ]
        self.namespace: dict[str, Any] = {"CHUNKS": 6, "GAP": 0.4}
        exec(
            compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"),
            self.namespace,
        )

    def test_the_windows_ci_arrivals_stream_despite_startup_delay(self) -> None:
        arrivals = [1.4713992, 1.8707242, 2.266271, 2.6934095, 3.0891985, 3.4841687]
        self.assertIn("first byte 1.47 s", self.namespace["streamed"](arrivals, "pcm"))

    def test_prompt_streaming_still_passes(self) -> None:
        self.namespace["streamed"]([0.05, 0.45, 0.85, 1.25, 1.65, 2.05], "pcm")

    def test_buffered_and_mostly_buffered_delivery_are_refused(self) -> None:
        for arrivals in (
            [4.0],
            [4.0, 4.001, 4.002, 4.003, 4.004, 4.005],
            [2.0, 2.0, 2.0, 2.0, 2.0, 2.4],
        ):
            with self.subTest(arrivals=arrivals), self.assertRaises(AssertionError):
                self.namespace["streamed"](arrivals, "pcm")


if __name__ == "__main__":
    unittest.main()
