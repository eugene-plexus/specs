from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

import previous_push

COMMIT = "a" * 40


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def run(status: str, conclusion: str | None = None, number: int = 1) -> dict:
    return {
        "id": number,
        "head_sha": COMMIT,
        "head_branch": "main",
        "event": "push",
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://example.invalid/runs/{number}",
    }


class WaitTests(unittest.TestCase):
    def wait(self, answers: list[dict | None]) -> tuple[bool, str, float]:
        clock = Clock()
        replies = iter(answers)
        last: list[dict | None] = [None]

        def lookup(commit: str) -> dict | None:
            self.assertEqual(commit, COMMIT)
            last[0] = next(replies, last[0])
            return last[0]

        passed, reason = previous_push.wait(COMMIT, lookup, sleep=clock.sleep, clock=clock)
        return passed, reason, clock.now

    def test_a_running_previous_push_is_waited_for_then_its_success_passes(self) -> None:
        passed, reason, waited = self.wait(
            [None, run("queued"), run("in_progress"), run("completed", "success")]
        )
        self.assertTrue(passed)
        self.assertIn("passed CI", reason)
        self.assertEqual(waited, 3 * previous_push.POLL_SECONDS)

    def test_a_failed_or_cancelled_previous_push_fails_and_names_its_run(self) -> None:
        for conclusion in ("failure", "cancelled", "timed_out", "skipped"):
            with self.subTest(conclusion=conclusion):
                passed, reason, _ = self.wait([run("completed", conclusion, 7)])
                self.assertFalse(passed)
                self.assertIn(conclusion, reason)
                self.assertIn("runs/7", reason)
                # What clears it, and that a pin-only fix does not.
                self.assertIn("re-run of that run that passes", reason)
                self.assertIn("plan is full coverage", reason)
                self.assertIn("pin-only fix is a reduced push and is held", reason)
                self.assertNotIn("push a fix", reason)

    def test_a_failing_lookup_keeps_waiting_until_github_answers(self) -> None:
        clock = Clock()
        replies = iter(
            [OSError("connection reset"), ValueError("bad JSON"), run("completed", "success")]
        )

        def lookup(commit: str) -> dict | None:
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply

        passed, _ = previous_push.wait(COMMIT, lookup, sleep=clock.sleep, clock=clock)
        self.assertTrue(passed)
        self.assertEqual(clock.now, 2 * previous_push.POLL_SECONDS)

    def test_a_lookup_failing_to_the_deadline_fails_and_says_why(self) -> None:
        clock = Clock()

        def lookup(commit: str) -> dict | None:
            raise OSError("GitHub is down")

        passed, reason = previous_push.wait(COMMIT, lookup, sleep=clock.sleep, clock=clock)
        self.assertFalse(passed)
        self.assertIn("GitHub is down", reason)
        self.assertGreaterEqual(clock.now, previous_push.WAIT_SECONDS)

    @patch("previous_push.api")
    def test_one_api_error_is_retried_with_backoff(self, api) -> None:
        slept: list[float] = []
        error = subprocess.CalledProcessError(1, ["gh", "api"])
        api.side_effect = [error, {"message": "Server Error"}, {"workflow_runs": [run("queued")]}]
        self.assertEqual(previous_push.newest_run(COMMIT, sleep=slept.append)["status"], "queued")
        self.assertEqual(slept, list(previous_push.RETRY_SECONDS[:2]))
        api.side_effect = [error] * (len(previous_push.RETRY_SECONDS) + 1)
        slept.clear()
        with self.assertRaises(subprocess.CalledProcessError):
            previous_push.newest_run(COMMIT, sleep=slept.append)
        self.assertEqual(slept, list(previous_push.RETRY_SECONDS))

    def test_no_run_for_the_previous_push_fails(self) -> None:
        passed, reason, waited = self.wait([None])
        self.assertFalse(passed)
        self.assertIn("No CI run", reason)
        self.assertGreaterEqual(waited, previous_push.APPEAR_SECONDS)

    def test_a_run_still_going_at_the_deadline_fails(self) -> None:
        passed, reason, waited = self.wait([run("in_progress")])
        self.assertFalse(passed)
        self.assertIn("still running", reason)
        self.assertGreaterEqual(waited, previous_push.WAIT_SECONDS)

    @patch("previous_push.api")
    def test_only_the_newest_push_run_on_main_counts(self, api) -> None:
        newer = run("completed", "success", 9)
        api.return_value = {
            "workflow_runs": [
                run("completed", "failure", 3),
                newer,
                dict(run("completed", "success", 12), event="workflow_dispatch"),
                dict(run("completed", "success", 13), head_branch="row"),
                dict(run("completed", "success", 14), head_sha="b" * 40),
            ]
        }
        self.assertEqual(previous_push.newest_run(COMMIT), newer)
        query = api.call_args.args[0]
        self.assertIn(f"head_sha={COMMIT}", query)
        self.assertIn("event=push", query)
        self.assertIn("branch=main", query)


if __name__ == "__main__":
    unittest.main()
