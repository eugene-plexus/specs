"""A process an acceptance script started that never answers: the failure names why.

specs#127 (LS7a: the agent never answered on Linux, the script printed no log),
#123 (gemini-acceptance) and #117 (mv5b-hindsight-acceptance) asked for the
same. These checks start no agent and no component.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import acceptance_logs  # noqa: E402


def load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exits(code: int, *lines: str) -> subprocess.Popen[bytes]:
    """A real process that prints `lines`, exits with `code`, and is done."""
    script = "".join(f"print({line!r}, flush=True);" for line in lines) + f"raise SystemExit({code})"
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL
    )
    process.wait(timeout=30)
    return process


class HelperTests(unittest.TestCase):
    def test_tail_keeps_the_last_lines_and_says_when_there_are_none(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "agent.log"
            log.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
            kept = acceptance_logs.tail(log, 3).splitlines()
            self.assertEqual(kept, ["line 97", "line 98", "line 99"])
            log.write_text("", encoding="utf-8")
            self.assertIn("is empty", acceptance_logs.tail(log))
            self.assertIn("cannot be read", acceptance_logs.tail(Path(raw) / "missing.log"))

    def test_exit_note_names_the_exit_code_and_a_running_process(self) -> None:
        self.assertIn("exited with code 3", acceptance_logs.exit_note(exits(3), "the agent"))
        self.assertIn("never started", acceptance_logs.exit_note(None, "the agent"))
        running = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL
        )
        try:
            self.assertIn("still running", acceptance_logs.exit_note(running, "the agent"))
        finally:
            running.kill()
            running.wait(timeout=30)

    def test_bind_failure_reads_uvicorn_on_linux_and_windows(self) -> None:
        for text in (
            "ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 41234): "
            "address already in use",
            "ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 41234): "
            "only one usage of each socket address (protocol/network address/port) is normally permitted",
        ):
            self.assertTrue(acceptance_logs.bind_failure(text), text)
        self.assertFalse(acceptance_logs.bind_failure("ModuleNotFoundError: No module named 'x'"))

    def test_report_names_each_log_and_logs_under_skips_empty_ones(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            (base / "sub").mkdir()
            (base / "a.log").write_text("one\ntwo\n", encoding="utf-8")
            (base / "sub" / "b.log").write_text("three\n", encoding="utf-8")
            (base / "empty.log").write_text("", encoding="utf-8")
            found = acceptance_logs.logs_under(base)
            self.assertEqual({p.name for p in found}, {"a.log", "b.log"})
            text = acceptance_logs.report(found, 5, base=base)
            self.assertIn("--- a.log (last 5 lines) ---", text)
            self.assertIn("--- sub", text)
            self.assertIn("three", text)


class Ls7Tests(unittest.TestCase):
    """The script's own behaviour, with the agent replaced by a process that exits."""

    def run_main(self, code: int, *lines: str) -> tuple[str, list[list[str]], BaseException | None]:
        ls7 = load("ls7_under_test", "ls7-copy-acceptance.py")
        real = subprocess.Popen
        started: list[list[str]] = []

        def fake(argv: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            if "eugene_plexus_agent" not in argv:
                return real(argv, **kwargs)  # the stand-in Strata's venv, and the like
            started.append(list(argv))
            script = "".join(f"print({line!r}, flush=True);" for line in lines) + f"raise SystemExit({code})"
            return real([sys.executable, "-c", script], **kwargs)

        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
        error: BaseException | None = None
        with mock.patch.object(ls7.subprocess, "Popen", fake), contextlib.redirect_stdout(out):
            try:
                ls7.main()
            except AssertionError as e:
                error = e
        return out.buffer.getvalue().decode("utf-8"), started, error  # type: ignore[attr-defined]

    def test_an_agent_that_exits_fails_at_once_and_its_log_is_printed(self) -> None:
        printed, started, error = self.run_main(7, "agent says: no module named widgets")
        self.assertIsNotNone(error)
        self.assertIn("the agent had exited with code 7", str(error))
        self.assertIn("agent says: no module named widgets", printed)
        self.assertEqual(len(started), 1, "a failure that is not a bind failure is not retried")

    def test_a_bind_failure_in_the_log_starts_the_agent_once_more_then_gives_up(self) -> None:
        printed, started, error = self.run_main(
            1,
            "ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 1): "
            "address already in use",
        )
        self.assertIsNotNone(error)
        self.assertEqual(len(started), 2)
        self.assertIn("starting it once more", printed)
        self.assertEqual(printed.count("address already in use"), 2, "both starts' output is kept")


class Mv5bTests(unittest.TestCase):
    def test_not_healthy_names_the_last_answer_and_the_units_journal_without_secrets(self) -> None:
        module = load("hindsight_under_test", "mv5b-hindsight-acceptance.py")
        module.REPORT_SECRETS[:] = ["s3cr3t"]
        done = subprocess.CompletedProcess([], 0, stdout="started\nlogin s3cr3t\n", stderr="")
        record = mock.Mock(id="hindsight")
        manager = mock.Mock()
        manager.view.return_value = "App(status=starting)"
        with mock.patch.object(module.subprocess, "run", return_value=done) as run:
            text = module.not_healthy(manager, record, "ConnectError('refused')")
        self.assertIn("ConnectError('refused')", text)
        self.assertIn("eugene-plexus-app@hindsight.service", run.call_args.args[0])
        self.assertIn("started", text)
        self.assertNotIn("s3cr3t", text)
        module.REPORT_SECRETS.clear()


if __name__ == "__main__":
    unittest.main()
