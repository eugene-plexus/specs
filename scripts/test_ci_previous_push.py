from __future__ import annotations

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
