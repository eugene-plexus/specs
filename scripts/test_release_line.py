"""release-line.py against the bare repositories of release-patch-acceptance.py:
open starts each repository at the tag's pins, and pick takes only fixes from main."""

from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "release_patch_acceptance", SCRIPTS / "release-patch-acceptance.py"
)
assert _spec is not None and _spec.loader is not None
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


class LineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = Path(tempfile.mkdtemp(prefix="ep-line-test-"))
        cls.fx = fixture.Fixture(cls.scratch).build()
        code, out = cls.fx.line("open", "v1.2")
        if code != 0:
            fixture.remove_tree(cls.scratch)
            raise AssertionError(out)
        cls.line = cls.fx.lines / "v1.2"

    @classmethod
    def tearDownClass(cls) -> None:
        fixture.remove_tree(cls.scratch)

    def picks(self, repo: str) -> list[str]:
        head = self.fx.rev(repo, "release/v1.2")
        log = self.fx.git(
            self.fx.bare / f"{repo}.git",
            "log",
            "--format=%B",
            f"{self.fx.pins[repo]}..{head}",
        )
        return re.findall(r"\(cherry picked from commit ([a-f0-9]{40})\)", log)

    def test_open_starts_every_repository_at_the_tags_pins(self) -> None:
        fx = self.fx
        for name in fixture.COMPONENTS:
            with self.subTest(name):
                # ui and Workbench start at the source their dist was built from.
                self.assertEqual(fx.rev(name, "release/v1.2"), fx.source[name])
                self.assertEqual(
                    fx.git(self.line / name, "rev-parse", "--abbrev-ref", "HEAD"),
                    "release/v1.2",
                )
        tooling = fx.rev("specs", "release/v1.2")
        self.assertEqual(
            fx.git(fx.bare / "specs.git", "rev-parse", f"{tooling}^"),
            fx.rev("specs", "v1.2.0"),
        )
        changed = fx.git(
            fx.bare / "specs.git", "diff", "--name-only", "v1.2.0", tooling
        ).splitlines()
        self.assertEqual(sorted(changed), sorted(fixture.TOOLING))
        self.assertTrue((self.line / "line.json").is_file())

    def test_open_refuses_an_older_line_without_security(self) -> None:
        code, out = self.fx.line("open", "v1.1")
        self.assertEqual(code, 2, out)
        self.assertIn("--security", out)
        self.assertFalse((self.fx.lines / "v1.1").exists())

    def test_pick_refuses_a_commit_not_on_main(self) -> None:
        code, out = self.fx.line("pick", "v1.2", f"control:{self.fx.side['control']}")
        self.assertEqual(code, 2, out)
        self.assertIn("not on main", out)
        self.assertEqual(
            self.fx.rev("control", "release/v1.2"), self.fx.pins["control"]
        )

    def test_pick_twice_applies_once(self) -> None:
        fix = self.fx.fix["gateway"]
        code, out = self.fx.line("pick", "v1.2", f"gateway:{fix}")
        self.assertEqual(code, 0, out)
        code, out = self.fx.line("pick", "v1.2", f"gateway:{fix[:10]}")
        self.assertEqual(code, 0, out)
        self.assertIn("already", out)
        self.assertEqual(self.picks("gateway"), [fix])

    def test_a_conflicting_pick_is_aborted_and_names_its_files(self) -> None:
        code, out = self.fx.line("pick", "v1.2", f"library:{self.fx.later['library']}")
        self.assertEqual(code, 2, out)
        self.assertIn("core.py", out)
        worktree = self.line / "library"
        self.assertEqual(self.fx.git(worktree, "status", "--porcelain"), "")
        self.assertEqual(
            self.fx.git(worktree, "rev-parse", "HEAD"), self.fx.pins["library"]
        )
        self.assertEqual(
            self.fx.rev("library", "release/v1.2"), self.fx.pins["library"]
        )


if __name__ == "__main__":
    unittest.main()
