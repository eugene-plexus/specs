"""ship.py pushes merged specs commits first and the pin commit alone (P11).

Real git repositories in a temporary directory: a bare origin for specs and
for one component, a specs clone with a merged commit not yet pushed, and the
agent files ship.py reads its nested pins from.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ship
from ci_plan import COMPONENTS, plan

A, B = "a" * 40, "b" * 40


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *arguments], text=True).strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def repository(path: Path) -> None:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for key, value in (
        ("user.name", "Ship fixture"),
        ("user.email", "ship@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        git(path, "config", key, value)


def commit(path: Path, message: str) -> str:
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


class ShipTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="ep-ship-")
        self.addCleanup(temporary.cleanup)
        top = Path(temporary.name)
        self.root = top / "work"
        self.origins = top / "origins"
        for name in ("specs", "control"):
            bare = self.origins / f"{name}.git"
            bare.mkdir(parents=True)
            git(bare, "init", "-q", "--bare", "-b", "main")
            # Each push to main leaves its own entry.
            git(bare, "config", "core.logAllRefUpdates", "always")

        control = self.root / "control"
        repository(control)
        write(
            control / "pyproject.toml",
            '[project]\nname = "c"\ndependencies = ["httpx"]\n\n'
            '[build-system]\nrequires = ["hatchling"]\n',
        )
        self.pinned = commit(control, "Control as pinned")
        git(control, "remote", "add", "origin", str(self.origins / "control.git"))
        git(control, "push", "-q", "-u", "origin", "main")
        write(control / "src.py", "print('new')\n")
        self.control = commit(control, "Control work to ship")

        agent = self.root / "agent"
        repository(agent)
        write(
            agent / ship.CATALOGUE,
            f"source: https://github.com/eugene-plexus/workbench/archive/{A}.tar.gz\n"
            f"  version: {A}\n",
        )
        write(agent / ship.SITE_HOST_PY, f'SITE_HOST_COMMIT = "{B}"\n')
        commit(agent, "Agent")

        self.specs = self.root / "specs"
        repository(self.specs)
        components = {name: A for name in COMPONENTS} | {"control": self.pinned}
        write(
            self.specs / "release/manifest.json",
            json.dumps({"format": 1, "components": components}, indent=2) + "\n",
        )
        write(self.specs / "scripts/install.sh", f"PIN_AGENT={A}\necho install\n")
        write(self.specs / "scripts/install.ps1", f'  "agent" = "{A}"\n')
        write(self.specs / "scripts/release-inputs.py", "")  # the generated block: nothing here
        self.initial = commit(self.specs, "Specs as shipped")
        git(self.specs, "remote", "add", "origin", str(self.origins / "specs.git"))
        git(self.specs, "push", "-q", "-u", "origin", "main")
        write(self.specs / "scripts/new-check.py", "print('merged work')\n")
        self.merged = commit(self.specs, "Merged work: a new check")

        for name, value in (
            ("SPECS", self.specs),
            ("ROOT", self.root),
            ("MANIFEST", self.specs / "release/manifest.json"),
        ):
            patcher = patch.object(ship, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(ship, "static_checks", lambda plan: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # GitHub's verdict on main's last run: green unless a test says otherwise.
        self.red_main = patch.object(ship, "failed_main_run", return_value=None)
        self.failed_main_run = self.red_main.start()
        self.addCleanup(self.red_main.stop)

    def pushes(self) -> list[str]:
        """Each value origin's main took, oldest first."""
        bare = self.origins / "specs.git"
        return git(bare, "reflog", "show", "--format=%H", "refs/heads/main").split()[::-1]

    def ship(self, **options: bool) -> tuple[str | None, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            shipped = ship.ship(["control"], co_author=None, **options)
        return shipped, output.getvalue()

    def test_merged_commits_go_first_and_the_pin_commit_alone(self) -> None:
        shipped, output = self.ship(dry_run=False)
        self.assertEqual(self.pushes(), [self.initial, self.merged, shipped])
        self.assertEqual(git(self.specs, "rev-parse", f"{shipped}^"), self.merged)
        self.assertIn("pushed 1 merged commit(s)", output)
        manifest = json.loads(git(self.specs, "show", f"{shipped}:release/manifest.json"))
        self.assertEqual(manifest["components"]["control"], self.control)
        self.assertEqual(git(self.origins / "control.git", "rev-parse", "main"), self.control)
        # Each push plans its own change: the merged script selects full
        # coverage, the pin push's change is the pins alone.
        self.assertTrue(plan(self.specs, self.initial, self.merged)["full"])
        selected = plan(self.specs, self.merged, shipped)
        self.assertFalse(selected["full"])
        self.assertTrue(selected["runtime"])

    def test_one_push_carries_merged_commits_with_the_pins(self) -> None:
        shipped, output = self.ship(dry_run=False, one_push=True)
        self.assertEqual(self.pushes(), [self.initial, shipped])
        self.assertEqual(git(self.specs, "rev-parse", f"{shipped}^"), self.merged)
        self.assertNotIn("merged commit(s) to", output)

    def test_with_nothing_merged_the_pin_commit_is_the_only_push(self) -> None:
        git(self.specs, "reset", "-q", "--hard", self.initial)
        shipped, _ = self.ship(dry_run=False)
        self.assertEqual(self.pushes(), [self.initial, shipped])

    def test_dry_run_pushes_nothing_and_says_what_it_would_split(self) -> None:
        shipped, output = self.ship(dry_run=True)
        self.assertIsNone(shipped)
        self.assertEqual(self.pushes(), [self.initial])
        self.assertEqual(git(self.origins / "control.git", "rev-parse", "main"), self.pinned)
        self.assertIn("would push 1 merged commit(s) first, on their own", output)
        self.assertIn("the pin commit would be pushed alone", output)
        self.assertEqual(git(self.specs, "rev-parse", "HEAD"), self.merged)

    def test_a_red_main_is_named_when_ci_would_hold_the_first_push(self) -> None:
        self.failed_main_run.return_value = ("failure", "https://example.invalid/runs/5")
        # Merged work that plans full coverage stands alone: no hold, no warning.
        _, output = self.ship(dry_run=True)
        self.assertNotIn("runs/5", output)
        # With nothing merged, the pin push is reduced and would be held.
        git(self.specs, "reset", "-q", "--hard", self.initial)
        _, output = self.ship(dry_run=True)
        self.assertIn("CI's run of main's head failure: https://example.invalid/runs/5", output)
        self.assertIn("re-run and passes or a full-plan push lands", output)
        self.failed_main_run.assert_called_with(self.initial)

    def test_a_stop_before_the_first_push_pushes_nothing(self) -> None:
        write(
            self.root / "control/pyproject.toml",
            '[project]\nname = "c"\ndependencies = ["httpx", "rich"]\n\n'
            '[build-system]\nrequires = ["hatchling"]\n',
        )
        commit(self.root / "control", "A dependency change")
        with self.assertRaisesRegex(ship.Stop, "dependencies changed"):
            self.ship(dry_run=False)
        self.assertEqual(self.pushes(), [self.initial])
        self.assertEqual(git(self.origins / "control.git", "rev-parse", "main"), self.pinned)

    # What main() says when a step stops it: pushes already made are not "not shipped".

    def main(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["ship.py", "control", *arguments]),
            patch.dict("os.environ", {"EP_SHIP_CO_AUTHOR": ""}),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = ship.main()
        return code, out.getvalue(), err.getvalue()

    def test_a_wait_that_fails_after_the_pushes_does_not_say_not_shipped(self) -> None:
        cause = "specs: `gh run list` failed: HTTP 403: API rate limit exceeded"
        with patch.object(ship, "wait_for_edge", side_effect=ship.Stop(cause)):
            code, out, err = self.main("--wait")
        shipped = git(self.specs, "rev-parse", "HEAD")
        self.assertEqual(self.pushes(), [self.initial, self.merged, shipped])
        self.assertNotEqual(code, 0)
        self.assertNotIn("Not shipped", err + out)
        self.assertIn(f"Pushed; could not watch CI: {cause}", err)
        # Each push is listed: the component's main, the merged specs commit, the pin commit.
        self.assertIn(f"control main {self.control[:7]}", err)
        self.assertIn(f"specs main {self.merged[:7]}", err)
        self.assertIn(f"specs main {shipped[:7]}", err)

    def test_a_stop_after_a_push_says_what_was_pushed(self) -> None:
        cause = "specs: `git commit` failed: boom"
        with patch.object(ship, "commit_files", side_effect=ship.Stop(cause)):
            code, out, err = self.main()
        self.assertNotEqual(code, 0)
        self.assertNotIn("Not shipped", err + out)
        self.assertIn(cause, err)
        self.assertIn(f"control main {self.control[:7]}", err)

    def test_a_stop_before_any_push_still_says_not_shipped(self) -> None:
        write(
            self.root / "control/pyproject.toml",
            '[project]\nname = "c"\ndependencies = ["httpx", "rich"]\n\n'
            '[build-system]\nrequires = ["hatchling"]\n',
        )
        commit(self.root / "control", "A dependency change")
        code, out, err = self.main("--wait")
        self.assertNotEqual(code, 0)
        self.assertIn("Not shipped: control: its dependencies changed", err)
        self.assertNotIn("Pushed", err)
        self.assertEqual(self.pushes(), [self.initial])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
