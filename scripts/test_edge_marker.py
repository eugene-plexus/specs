from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import edge_marker


class EdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ep-edge-marker-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for arguments in (
            ("init", "-q"),
            ("config", "user.name", "CI fixture"),
            ("config", "user.email", "ci@example.invalid"),
            ("config", "commit.gpgsign", "false"),
        ):
            self.command(*arguments)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/install.sh").write_text("echo old\n", encoding="utf-8", newline="\n")
        self.base = self.commit()
        self.runs: dict[tuple[str, str], dict] = {}
        self.runtime: set[str] = set()
        self.receipts(self.base)

    def command(self, *arguments: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], text=True).strip()

    def commit(self) -> str:
        self.command("add", ".")
        self.command("commit", "-qm", "Fixture", "--allow-empty")
        return self.command("rev-parse", "HEAD")

    def change(self, name: str, content: str) -> str:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return self.commit()

    def receipts(self, commit: str, *, runtime: bool = True, image: bool = True) -> None:
        self.runs["ci.yml", commit] = {"head_sha": commit, "id": len(self.runs) + 1}
        if runtime:
            self.runtime.add(commit)
        if image:
            self.runs["container.yml", commit] = {"head_sha": commit, "id": len(self.runs) + 1}

    def choose(self, head: str, marker: str | None = None):
        return edge_marker.choose(
            self.root,
            head,
            marker,
            lambda workflow, commit: self.runs.get((workflow, commit)),
            lambda receipt: receipt["head_sha"] in self.runtime,
        )

    def test_bootstrap_requires_runtime_and_image_evidence(self) -> None:
        self.assertEqual(self.choose(self.base)["specsCommit"], self.base)
        self.runtime.clear()
        self.assertIsNone(self.choose(self.base))

    def test_docs_commit_reuses_exact_runtime_and_image_inputs(self) -> None:
        head = self.change("docs/change.md", "Documentation only\n")
        self.receipts(head, runtime=False, image=False)
        receipt = self.choose(head, self.base)
        self.assertEqual(receipt["specsCommit"], head)
        self.assertEqual(receipt["runtimeCommit"], self.base)
        self.assertEqual(receipt["imageCommit"], self.base)

    def test_canceled_runtime_then_green_docs_cannot_launder_a_change(self) -> None:
        changed = self.change("scripts/install.sh", "echo UNTESTED\n")
        self.runs["container.yml", changed] = {"head_sha": changed, "id": 20}
        head = self.change("docs/change.md", "Does not make the installer tested\n")
        self.receipts(head, runtime=False, image=False)
        self.assertIsNone(self.choose(head, self.base))
        self.receipts(changed)
        self.assertEqual(self.choose(head, self.base)["runtimeCommit"], changed)

    def test_missing_image_keeps_previous_edge(self) -> None:
        head = self.change("scripts/install.sh", "echo NEW\n")
        self.receipts(head, image=False)
        self.assertIsNone(self.choose(head, self.base))

    def test_dependency_and_nested_pin_changes_invalidate_both_fingerprints(self) -> None:
        for name in (
            "release/requirements.lock",
            "release/manifest.json",
            "scripts/new-harness.py",
            ".github/workflows/container.yml",
            "docker/Dockerfile",
        ):
            with self.subTest(name=name):
                previous = self.command("rev-parse", "HEAD")
                before = edge_marker.fingerprint(self.root, previous)
                image_before = edge_marker.fingerprint(self.root, previous, image=True)
                head = self.change(
                    name,
                    json.dumps({"components": {"agent": "b" * 40}})
                    if name.endswith("manifest.json")
                    else "changed\n",
                )
                self.assertNotEqual(edge_marker.fingerprint(self.root, head), before)
                self.assertNotEqual(
                    edge_marker.fingerprint(self.root, head, image=True), image_before
                )

    def test_manifest_whitespace_does_not_invalidate_evidence(self) -> None:
        base = self.change("release/manifest.json", '{"components":{"agent":"abc"}}')
        head = self.change("release/manifest.json", '{\n  "components": {"agent": "abc"}\n}\n')
        for image in (False, True):
            self.assertEqual(
                edge_marker.fingerprint(self.root, base, image=image),
                edge_marker.fingerprint(self.root, head, image=image),
            )

    def test_script_markdown_is_not_treated_as_documentation(self) -> None:
        head = self.change("scripts/fixtures/prompt.md", "Runtime fixture\n")
        self.assertNotEqual(
            edge_marker.fingerprint(self.root, head), edge_marker.fingerprint(self.root, self.base)
        )

    def test_no_backward_or_divergent_marker_move(self) -> None:
        head = self.change("docs/change.md", "newer\n")
        self.assertIsNone(self.choose(self.base, self.base))
        with self.assertRaisesRegex(ValueError, "not an ancestor"):
            self.choose(self.base, head)

    @patch("edge_marker.api")
    @patch("edge_marker.image_digest")
    @patch("edge_marker.image_receipt")
    @patch("edge_marker.current_marker")
    def test_digest_mismatch_never_moves_native_marker(self, marker, image, digest, api) -> None:
        marker.return_value = None
        image.return_value = "sha256:" + "a" * 64
        digest.side_effect = ["sha256:" + "a" * 64, "sha256:" + "b" * 64]
        receipt = self.choose(self.base)
        with patch("edge_marker.subprocess.run"):
            with self.assertRaisesRegex(ValueError, "digest differs"):
                edge_marker.publish(self.root, receipt)
        api.assert_not_called()

    @patch("edge_marker.current_marker")
    def test_stale_evaluation_cannot_retag_image(self, marker) -> None:
        receipt = self.choose(self.base)
        marker.return_value = self.base
        with patch("edge_marker.subprocess.run") as command:
            with self.assertRaisesRegex(ValueError, "changed during evaluation"):
                edge_marker.publish(self.root, receipt)
            command.assert_not_called()

    @patch("edge_marker.api")
    def test_running_or_failed_named_gate_does_not_count(self, api) -> None:
        passed = {
            "id": 1,
            "head_sha": self.base,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        for conclusion in (None, "failure", "cancelled"):
            with self.subTest(conclusion=conclusion):
                newer = dict(passed, id=2, conclusion=conclusion)
                api.side_effect = [{"workflow_runs": [passed, newer]}, newer]
                self.assertIsNone(edge_marker.successful_run("ci.yml", self.base))
        api.side_effect = None
        api.return_value = {"workflow_runs": [dict(passed, event="workflow_dispatch")]}
        self.assertIsNone(edge_marker.successful_run("ci.yml", self.base))

    @patch("edge_marker.api")
    def test_stale_success_listing_cannot_hide_a_running_rerun(self, api) -> None:
        passed = {
            "id": 1,
            "head_sha": self.base,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        api.side_effect = [
            {"workflow_runs": [passed]},
            dict(passed, status="in_progress", conclusion=None),
        ]
        self.assertIsNone(edge_marker.successful_run("ci.yml", self.base))

    @patch("edge_marker.api")
    @patch("edge_marker.image_digest")
    @patch("edge_marker.image_receipt")
    @patch("edge_marker.current_marker")
    def test_verified_publication_fast_forwards_a_real_git_ref(
        self, marker, image, digest, api
    ) -> None:
        self.command("update-ref", "refs/heads/edge", self.base)
        head = self.change("docs/change.md", "accepted documentation\n")
        self.receipts(head, runtime=False, image=False)
        receipt = self.choose(head, self.base)
        marker.return_value = self.base
        image.return_value = "sha256:" + "a" * 64
        real_run = subprocess.run
        events = []

        def inspect(reference):
            events.append("verify")
            return "sha256:" + "a" * 64

        digest.side_effect = inspect

        def command(arguments, **options):
            if arguments[0] == "docker":
                events.append("registry")
                return subprocess.CompletedProcess(arguments, 0)
            return real_run(arguments, **options)

        def update(path, *, method, body):
            events.append("marker")
            self.assertEqual(path, "git/refs/heads/edge")
            self.assertEqual(method, "PATCH")
            self.assertFalse(body["force"])
            self.command("update-ref", "refs/heads/edge", body["sha"], self.base)

        api.side_effect = update
        with patch("edge_marker.subprocess.run", side_effect=command):
            edge_marker.publish(self.root, receipt)
        self.assertEqual(self.command("rev-parse", "refs/heads/edge"), head)
        self.assertEqual(events, ["verify", "registry", "verify", "marker"])
        self.assertEqual(receipt["imageDigest"], "sha256:" + "a" * 64)

    @patch("edge_marker.api")
    def test_image_receipt_is_bound_to_its_run_commit_and_inputs(self, api) -> None:
        receipt = self.choose(self.base)
        api.return_value = {
            "artifacts": [{"name": "verified-container", "expired": False, "id": 7}],
            "total_count": 1,
        }
        built = {
            "specsCommit": self.base,
            "imageFingerprint": receipt["imageFingerprint"],
            "digest": "sha256:" + "a" * 64,
        }

        def archive(document):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as bundle:
                bundle.writestr("image-receipt.json", json.dumps(document))
            return buffer.getvalue()

        with patch("edge_marker.subprocess.check_output", return_value=archive(built)) as command:
            with patch("edge_marker.fingerprint", return_value=receipt["imageFingerprint"]):
                self.assertEqual(edge_marker.image_receipt(self.root, receipt), built["digest"])
                api.assert_called_once_with(
                    f"actions/runs/{receipt['imageRun']}/artifacts?per_page=100"
                )
                command.assert_called_once_with(
                    ["gh", "api", f"repos/{edge_marker.REPOSITORY}/actions/artifacts/7/zip"]
                )
                for key, value in (
                    ("specsCommit", "b" * 40),
                    ("imageFingerprint", "wrong"),
                    ("digest", "bad"),
                ):
                    with self.subTest(key=key):
                        with patch(
                            "edge_marker.subprocess.check_output",
                            return_value=archive(dict(built, **{key: value})),
                        ):
                            with self.assertRaisesRegex(ValueError, "does not match"):
                                edge_marker.image_receipt(self.root, receipt)

    @patch("edge_marker.api")
    def test_skipped_container_build_is_not_an_image_receipt(self, api) -> None:
        passed = {
            "id": 1,
            "head_sha": self.base,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        api.side_effect = [
            {"workflow_runs": [passed]},
            passed,
            {"jobs": [{"name": "build-verify-publish", "conclusion": "skipped"}], "total_count": 1},
        ]
        self.assertIsNone(edge_marker.successful_run("container.yml", self.base))

    @patch("edge_marker.api")
    def test_skipped_or_partial_runtime_jobs_are_not_evidence(self, api) -> None:
        for conclusion in ("skipped", "failure", None):
            api.return_value = {
                "jobs": [
                    {"name": "Pinned integration (ubuntu-latest)", "conclusion": "success"},
                    {"name": "Pinned integration (windows-latest)", "conclusion": conclusion},
                ],
                "total_count": 2,
            }
            self.assertFalse(edge_marker.runtime_passed({"id": 1}))
        api.return_value["jobs"][1]["conclusion"] = "success"
        self.assertTrue(edge_marker.runtime_passed({"id": 1}))


if __name__ == "__main__":
    unittest.main()
