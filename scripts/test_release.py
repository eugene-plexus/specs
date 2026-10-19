"""release.py's own logic, offline: versions, resuming, the record and the release body."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release  # noqa: E402

PINS = {
    "agent": "a" * 40,
    "control": "c" * 40,
    "gateway": "9" * 40,
    "library": "1" * 40,
    "inference-driver": "2" * 40,
    "tool-driver": "3" * 40,
    "ui": "4" * 40,
    "workbench": "5" * 40,
    "site-host": "6" * 40,
}


def made(scratch: Path) -> release.Release:
    with mock.patch.object(release, "SPECS", scratch):
        r = release.Release("v0.3.1", None)
    r.state.update(
        previous="v0.3.0",
        candidate="7" * 40,
        pins=PINS,
        consoleSource="8" * 40,
        consoleFiles=287,
        workbenchSource="b" * 40,
        evidence={
            "windows": {
                "installSeconds": 18.0,
                "firstToken": 67.3,
                "consoleFiles": 287,
                "liveInstallUnchanged": True,
                "passed": True,
            },
            "wsl": {"installSeconds": 12.2, "firstToken": 80.4, "passed": True},
            "upgrade": {"checks": "31/31", "passed": True},
            "systemUpdate": {"passed": True},
            "recovery": {"timings": {"rootBackupSeconds": 8.5}, "passed": True},
        },
        qualifiedDigest="sha256:" + "d" * 64,
    )
    (r.dir / "candidate").mkdir(parents=True)
    (r.dir / "candidate" / "manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "install.sh": {"sha256": "e" * 64},
                    "install.ps1": {"sha256": "f" * 64},
                }
            }
        ),
        encoding="utf-8",
    )
    return r


class VersionTests(unittest.TestCase):
    def test_three_part_versions_only(self) -> None:
        self.assertEqual(release.version_key("v0.3.10"), (0, 3, 10))
        for bad in ("v0.3", "v0.3.1.1", "0.3.1", "v0.3.1-rc.1"):
            with self.subTest(bad=bad), self.assertRaises(release.Stop):
                release.version_key(bad)


class StateTests(unittest.TestCase):
    def test_reopening_a_phase_reruns_it_and_everything_after(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            with mock.patch.object(release, "SPECS", Path(scratch)):
                r = release.Release("v0.3.1", None)
                for phase in release.PHASES[:6]:
                    r.mark(phase)
                r.reopen("evidence")
                again = release.Release("v0.3.1", None)
            self.assertEqual(
                again.state["done"], ["preflight", "candidate", "artifacts"]
            )

    def test_a_new_candidate_forgets_the_old_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            with mock.patch.object(release, "SPECS", Path(scratch)):
                r = release.Release("v0.3.1", None)
                r["evidence"] = {"windows": {"passed": True, "candidate": "old"}}
                r.reopen("evidence")
                self.assertIn(
                    "evidence", r.state
                )  # its own rerun keeps what still describes the candidate
                r.reopen("candidate")
                self.assertNotIn("evidence", release.Release("v0.3.1", None).state)

    def test_a_missing_value_names_the_phase_to_rerun(self) -> None:
        with (
            tempfile.TemporaryDirectory() as scratch,
            mock.patch.object(release, "SPECS", Path(scratch)),
        ):
            with self.assertRaisesRegex(release.Stop, "--from"):
                release.Release("v0.3.1", None)["candidate"]


class RecordTests(unittest.TestCase):
    def test_the_record_carries_pins_hashes_results_and_the_old_limits(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            r = made(root)
            old = root / "docs" / "acceptance" / "v0.3.0-release-run.md"
            old.parent.mkdir(parents=True)
            old.write_text(
                "# old\n\n## Untested paths and limits\n\n- No GPU in a packaged install.\n",
                encoding="utf-8",
            )
            added = (
                "docs/acceptance/feature-a.md\ndocs/acceptance/v0.3.0-release-run.md\n"
            )
            with (
                mock.patch.object(release, "SPECS", root),
                mock.patch.object(release, "git", return_value=added),
            ):
                text = release.record_text(r)
        self.assertIn(f"| agent | `{'a' * 40}` |", text)
        self.assertIn(f"| install.sh | `{'e' * 64}` |", text)
        self.assertIn("NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF=v0.3.1", text)
        self.assertIn("| Windows 11 | 18.0 s | 67.3 s | Passed", text)
        self.assertIn("31/31 checks passed", text)
        self.assertIn("- [feature-a](feature-a.md)", text)
        self.assertNotIn("[v0.3.0-release-run]", text)
        self.assertIn("- No GPU in a packaged install.", text)
        self.assertIn("rootBackupSeconds 8.5 s", text)

    def test_the_release_body_summarises_the_notes_and_names_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            r = made(root)
            notes = root / "docs" / "releases" / "v0.3.1.md"
            notes.parent.mkdir(parents=True)
            notes.write_text(
                "# Eugene Plexus v0.3.1\n\nA smaller release.\n\n## Faster downloads\n\nx\n\n"
                "## Other changes\n\ny\n\n## Updating\n\nz\n",
                encoding="utf-8",
            )
            with mock.patch.object(release, "SPECS", root):
                body = release.release_body(r)
        self.assertTrue(body.startswith("A smaller release.\n"))
        self.assertIn("- Faster downloads", body)
        self.assertNotIn("- Other changes", body)
        self.assertIn("blob/v0.3.1/docs/releases/v0.3.1.md", body)
        self.assertIn(f"Verified container digest: `sha256:{'d' * 64}`", body)


class CandidateGuardTests(unittest.TestCase):
    def test_a_runtime_change_after_the_candidate_stops_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            r = made(Path(scratch))
            with mock.patch.object(
                release, "git", return_value="docs/x.md\nrelease/manifest.json"
            ):
                with self.assertRaisesRegex(release.Stop, "--from candidate"):
                    release.record(r)


if __name__ == "__main__":
    unittest.main()
