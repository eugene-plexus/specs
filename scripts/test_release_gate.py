from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from edge_marker import REPOSITORY, fingerprint
from release_gate import acceptance_digest, resolve, validate


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ep-release-gate-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for arguments in (
            ("init", "-q"),
            ("config", "user.name", "CI fixture"),
            ("config", "user.email", "ci@example.invalid"),
            ("config", "commit.gpgsign", "false"),
        ):
            self.git(*arguments)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/install.sh").write_text(
            "echo install\n", encoding="utf-8", newline="\n"
        )
        (self.root / "docs/acceptance").mkdir(parents=True)
        (self.root / "docs/acceptance/release.md").write_text(
            "Reviewed real install and upgrade evidence.\n", encoding="utf-8", newline="\n"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.git("tag", "v1.2.3")
        self.run = {
            "path": ".github/workflows/release-qualification.yml",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "head_sha": self.commit,
            "head_repository": {"full_name": REPOSITORY},
        }
        self.report = {
            "specsCommit": self.commit,
            "releaseTag": "v1.2.3",
            "runtimeFingerprint": fingerprint(self.root, "HEAD"),
            "acceptanceRecord": "docs/acceptance/release.md",
            "acceptanceSha256": acceptance_digest(
                self.root, self.commit, "docs/acceptance/release.md"
            ),
            "imageDigest": "sha256:" + "a" * 64,
        }

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], text=True).strip()

    def test_exact_successful_qualification_is_accepted(self) -> None:
        self.assertEqual(
            validate(self.root, self.report, self.run, "v1.2.3"), self.report["imageDigest"]
        )

    def test_failed_wrong_or_foreign_workflow_is_refused(self) -> None:
        for key, value in (
            ("conclusion", "failure"),
            ("status", "in_progress"),
            ("path", ".github/workflows/ci.yml"),
            ("event", "pull_request"),
            ("head_sha", "b" * 40),
            ("head_repository", {"full_name": "other/specs"}),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate(self.root, self.report, dict(self.run, **{key: value}), "v1.2.3")

    def test_changed_inputs_missing_digest_and_wrong_record_are_refused(self) -> None:
        for key, value in (
            ("runtimeFingerprint", "unqualified"),
            ("imageDigest", ""),
            ("releaseTag", "v1.2.2"),
            ("acceptanceSha256", "incorrect"),
            ("acceptanceRecord", "../../secret.md"),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate(self.root, dict(self.report, **{key: value}), self.run, "v1.2.3")

    def test_real_runtime_change_cannot_reuse_receipt(self) -> None:
        (self.root / "scripts/install.sh").write_text(
            "echo changed\n", encoding="utf-8", newline="\n"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "Changed installer")
        self.git("tag", "v1.2.4")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            validate(self.root, dict(self.report, releaseTag="v1.2.4"), self.run, "v1.2.4")

    def test_nested_pins_are_read_from_the_pinned_agent(self) -> None:
        from ci_plan import COMPONENTS

        agent = self.root / "agent"
        source = agent / "src/eugene_plexus_agent"
        source.mkdir(parents=True)
        (self.root / "release").mkdir()
        (self.root / "release/manifest.json").write_text(
            json.dumps({"components": {name: "a" * 40 for name in COMPONENTS}}),
            encoding="utf-8",
            newline="\n",
        )
        (source / "apps_catalogue.yaml").write_text(
            json.dumps(
                [
                    {
                        "id": "workbench",
                        "version": "b" * 40,
                        "source": "https://github.com/eugene-plexus/workbench/archive/"
                        + "b" * 40
                        + ".tar.gz",
                    }
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        (source / "site_host.py").write_text(
            'SITE_HOST_COMMIT = "' + "c" * 40 + '"\n', encoding="utf-8", newline="\n"
        )
        pins = resolve(self.root, agent)
        self.assertEqual(pins["workbench"], "b" * 40)
        self.assertEqual(pins["site-host"], "c" * 40)
        (self.root / "scripts/install.sh").write_text(
            "PIN_SITE_HOST=" + "d" * 40 + "\n", encoding="utf-8", newline="\n"
        )
        with self.assertRaisesRegex(ValueError, "disagree"):
            resolve(self.root, agent)


if __name__ == "__main__":
    unittest.main()
