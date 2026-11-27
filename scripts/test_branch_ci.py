"""Dispatch only when no existing run proves the same coverage."""

import importlib.util
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

import ci_receipt

spec = importlib.util.spec_from_file_location(
    "branch_ci", Path(__file__).with_name("branch-ci.py")
)
branch_ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(branch_ci)
URL = "https://github.com/eugene-plexus/specs/actions/runs/321"


class DispatchTests(unittest.TestCase):
    def call_main(self):
        with (
            patch("sys.argv", ["branch-ci.py", "row"]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            return branch_ci.main()

    def test_reuses_matching_run_without_dispatch(self):
        with (
            patch.object(branch_ci, "dispatch", return_value=("row", {}, {})),
            patch.object(branch_ci, "find_equivalent", return_value=URL),
            patch.object(branch_ci.subprocess, "run") as submit,
        ):
            self.assertEqual(self.call_main(), 0)
            submit.assert_not_called()

    def test_dispatch_returns_its_own_url_using_structured_json(self):
        response = subprocess.CompletedProcess(
            [], 0, json.dumps({"workflow_run_id": 321, "html_url": URL}), ""
        )
        with patch.object(branch_ci.subprocess, "run", return_value=response) as submit:
            self.assertEqual(branch_ci.submit("row", {"base": "a" * 40}), URL)
        args, kwargs = submit.call_args
        self.assertIn("--input", args[0])
        self.assertIn("X-GitHub-Api-Version: 2026-03-10", args[0])
        self.assertEqual(
            json.loads(kwargs["input"]), {"ref": "row", "inputs": {"base": "a" * 40}}
        )

    def test_new_inputs_dispatch_once(self):
        with (
            patch.object(
                branch_ci, "dispatch", return_value=("row", {"profile": "full"}, {})
            ),
            patch.object(branch_ci, "find_equivalent", return_value=None),
            patch.object(branch_ci, "submit", return_value=URL) as submit,
        ):
            self.assertEqual(self.call_main(), 0)
            submit.assert_called_once_with("row", {"profile": "full"})

    def test_pending_plan_is_polled_then_reused(self):
        with (
            patch.object(branch_ci, "dispatch", return_value=("row", {}, {})),
            patch.object(
                branch_ci,
                "find_equivalent",
                side_effect=[ci_receipt.PendingPlan("planning"), URL],
            ),
            patch.object(branch_ci.time, "sleep") as sleep,
            patch.object(branch_ci, "submit") as submit,
        ):
            self.assertEqual(self.call_main(), 0)
            sleep.assert_called_once_with(5)
            submit.assert_not_called()

    def test_failed_or_unavailable_evidence_is_not_silently_retried(self):
        for error in (
            RuntimeError("same inputs already failed"),
            RuntimeError("HTTP 503"),
        ):
            with (
                self.subTest(error=str(error)),
                patch.object(branch_ci, "dispatch", return_value=("row", {}, {})),
                patch.object(branch_ci, "find_equivalent", side_effect=error),
                patch.object(branch_ci, "submit") as submit,
            ):
                self.assertEqual(self.call_main(), 2)
                submit.assert_not_called()

    def test_pending_plan_timeout_does_not_duplicate_it(self):
        with (
            patch.object(branch_ci, "dispatch", return_value=("row", {}, {})),
            patch.object(
                branch_ci,
                "find_equivalent",
                side_effect=ci_receipt.PendingPlan("planning"),
            ),
            patch.object(branch_ci.time, "sleep"),
            patch.object(branch_ci, "submit") as submit,
        ):
            self.assertEqual(self.call_main(), 2)
            submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
