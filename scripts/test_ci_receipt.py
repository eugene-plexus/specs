import copy
import unittest

from ci_receipt import equivalent_run, make_receipt


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.expected = make_receipt(
            "a" * 40,
            "b" * 40,
            {"full": True},
            {"workbench": "c" * 40},
            {"agent": "d" * 40},
        )
        self.run = {
            "id": 1,
            "head_sha": "a" * 40,
            "head_branch": "row",
            "head_repository": {"full_name": "eugene-plexus/specs"},
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/eugene-plexus/specs/actions/runs/1",
        }

    def test_same_immutable_inputs_reuse_push_or_dispatch(self):
        for event in ("push", "workflow_dispatch"):
            self.run["event"] = event
            self.assertEqual(
                equivalent_run(
                    self.expected, "row", [self.run], lambda run: self.expected
                ),
                self.run["html_url"],
            )

    def test_changed_candidate_coverage_or_fallback_requires_new_run(self):
        for key in ("candidates", "main_refs", "checks", "base", "specs_commit"):
            older = copy.deepcopy(self.expected)
            older[key] = (
                {"different": "e" * 40} if isinstance(older[key], dict) else "e" * 40
            )
            self.assertIsNone(
                equivalent_run(self.expected, "row", [self.run], lambda run: older)
            )

    def test_missing_receipt_never_counts_as_coverage(self):
        self.assertIsNone(
            equivalent_run(self.expected, "row", [self.run], lambda run: None)
        )
        self.run.update(status="in_progress", conclusion=None)
        with self.assertRaisesRegex(RuntimeError, "still recording its inputs"):
            equivalent_run(self.expected, "row", [self.run], lambda run: None)

    def test_failure_is_named_and_not_silently_rerun(self):
        self.run["conclusion"] = "failure"
        with self.assertRaisesRegex(RuntimeError, "same inputs already failed"):
            equivalent_run(self.expected, "row", [self.run], lambda run: self.expected)

    def test_main_push_has_different_coverage_from_a_dispatch(self):
        self.run["head_branch"] = "main"
        self.assertIsNone(
            equivalent_run(self.expected, "main", [self.run], lambda run: self.expected)
        )
        self.run["event"] = "workflow_dispatch"
        self.assertEqual(
            equivalent_run(
                self.expected, "main", [self.run], lambda run: self.expected
            ),
            self.run["html_url"],
        )

    def test_foreign_repository_pr_and_wrong_branch_are_not_reused(self):
        for field, value in (
            ("head_repository", {"full_name": "someone/specs"}),
            ("event", "pull_request"),
            ("head_branch", "another-row"),
        ):
            other = {**self.run, field: value}
            self.assertIsNone(
                equivalent_run(self.expected, "row", [other], lambda run: self.expected)
            )

    def test_active_matching_run_is_reused_but_cancelled_run_is_not(self):
        self.run.update(status="in_progress", conclusion=None)
        self.assertEqual(
            equivalent_run(self.expected, "row", [self.run], lambda run: self.expected),
            self.run["html_url"],
        )
        self.run.update(status="completed", conclusion="cancelled")
        self.assertIsNone(
            equivalent_run(self.expected, "row", [self.run], lambda run: self.expected)
        )

    def test_floating_refs_cannot_be_evidence_of_equivalence(self):
        with self.assertRaisesRegex(ValueError, "immutable"):
            make_receipt("a" * 40, "b" * 40, {}, {"ui": "main"}, {})


if __name__ == "__main__":
    unittest.main()
