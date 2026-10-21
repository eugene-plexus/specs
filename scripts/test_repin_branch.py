"""repin-branch.py rebases a row's specs branch and re-pins the consumers (W0.14).

Real git repositories in a temporary folder: a specs checkout with a two-commit
branch `row1`, a bare origin for each repo, and consumer repos whose `row1`
branch pins a specs commit of that branch in SPECS_REF and in the generated
stamp. Then `main` of specs moves by one commit.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "repin_branch", Path(__file__).with_name("repin-branch.py")
)
repin_branch = importlib.util.module_from_spec(_spec)
sys.modules["repin_branch"] = repin_branch
_spec.loader.exec_module(repin_branch)  # type: ignore[union-attr]

IDENTITY = ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid")
BRANCH = "row1"
PY_STAMP = '''"""Generated Pydantic v2 models - DO NOT EDIT BY HAND.

Regenerate with:

    python scripts/codegen.py

Source: https://github.com/eugene-plexus/specs at commit {sha}
"""

SPECS_REF = "{sha}"
'''
TS_STAMP = """// Generated TypeScript types - DO NOT EDIT BY HAND.
//
// Regenerate with:
//   npm run codegen
//
// Source: https://github.com/eugene-plexus/specs at commit {sha}

export const SPECS_REF = "{sha}";
"""
PY_STAMP_PATH = "src/eugene_plexus_{name}/_generated/__init__.py"
TS_STAMP_PATH = "src/generated/index.ts"
GATEWAY_YAML = "title: gateway\nfield_one: 1\nfield_two: 2\nfield_three: 3\n"


def git(path: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *IDENTITY, "-c", "commit.gpgsign=false", "-C", str(path), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class RepinCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="ep-repin-test-", ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.repos = self.base / "repos"
        self.origins = self.base / "origins"
        self.root = self.base / "wt"
        self.repos.mkdir()
        self.origins.mkdir()

        self.make_repo(
            "specs",
            {
                "README.md": "specs\n",
                "openapi/gateway.yaml": GATEWAY_YAML,
                "openapi/library.yaml": "title: library\nversion: 1\n",
            },
        )
        self.initial = git(self.repos / "specs", "rev-parse", "HEAD")
        specs = self.worktree("specs")
        write(specs / "openapi/gateway.yaml", GATEWAY_YAML + "field_four: 4\n")
        self.first = self.commit(specs, "Add field_four to gateway")
        write(specs / "openapi/widget.yaml", "title: widget\n")
        self.head = self.commit(specs, "Add the widget contract")
        git(specs, "push", "-q", "origin", BRANCH)

        self.consumer("gateway", self.head, PY_STAMP, PY_STAMP_PATH.format(name="gateway"))
        self.consumer("agent", self.first, PY_STAMP, PY_STAMP_PATH.format(name="agent"))
        self.consumer("ui", self.head, TS_STAMP, TS_STAMP_PATH)
        # A consumer that pins a commit of main has nothing to re-pin.
        self.consumer("library", self.initial, PY_STAMP, PY_STAMP_PATH.format(name="library"))

    # -- fixtures ---------------------------------------------------------------

    def make_repo(self, name: str, files: dict[str, str]) -> Path:
        origin = self.origins / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        repo = self.repos / name
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        # The script commits and rebases with the repo's own identity.
        for key, value in (
            ("user.name", "Fixture"),
            ("user.email", "fixture@example.invalid"),
            ("commit.gpgsign", "false"),
            ("core.autocrlf", "false"),
        ):
            git(repo, "config", key, value)
        for relative, text in files.items():
            write(repo / relative, text)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "First")
        git(repo, "remote", "add", "origin", str(origin))
        git(repo, "push", "-q", "origin", "main")
        return repo

    def worktree(self, name: str) -> Path:
        """The repo's worktree on the row's branch, made if it is not there yet."""
        path = self.root / BRANCH / name
        if not path.exists():
            git(self.repos / name, "worktree", "add", "-q", "--no-track", "-b", BRANCH, str(path))
        return path

    def commit(self, path: Path, message: str) -> str:
        git(path, "add", "-A")
        git(path, "commit", "-qm", message)
        return git(path, "rev-parse", "HEAD")

    def consumer(self, name: str, pin: str, stamp: str, stamp_path: str) -> None:
        self.make_repo(
            name,
            {
                "README.md": f"{name}\n",
                "SPECS_REF": f"{self.initial}\n",
                stamp_path: stamp.format(sha=self.initial),
                stamp_path.rsplit("/", 1)[0] + "/models.py": "class Model: ...\n",
            },
        )
        path = self.worktree(name)
        (path / "SPECS_REF").write_bytes(f"{pin}\n".encode("ascii"))
        write(path / stamp_path, stamp.format(sha=pin))
        write(path / "CHANGES.md", f"the row's own change in {name}\n")
        self.commit(path, f"Pin specs {pin[:7]}")
        git(path, "push", "-q", "origin", BRANCH)

    def advance_main(self, *, conflicting: bool = False, duplicate: bool = False) -> str:
        """Move specs main by one commit, as another row's merge would."""
        main = self.repos / "specs"
        if conflicting:
            write(main / "openapi/gateway.yaml", GATEWAY_YAML + "field_four: 99\n")
            self.commit(main, "Main also adds field_four")
        elif duplicate:
            write(main / "openapi/gateway.yaml", GATEWAY_YAML + "field_four: 4\n")
            self.commit(main, "Main already has field_four")
        else:
            write(main / "openapi/library.yaml", "title: library\nversion: 2\n")
            self.commit(main, "Bump the library contract")
        git(main, "push", "-q", "origin", "main")
        return git(main, "rev-parse", "HEAD")

    # -- helpers ------------------------------------------------------------------

    def call(self, *arguments: str, branch: str = BRANCH) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        options = ["--root", str(self.root), "--repos-root", str(self.repos), "--co-author", ""]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = repin_branch.main([branch, *arguments, *options])
        return code, out.getvalue(), err.getvalue()

    def head_of(self, name: str) -> str:
        return git(self.worktree(name), "rev-parse", "HEAD")

    def pin_of(self, name: str) -> str:
        return (self.worktree(name) / "SPECS_REF").read_text(encoding="utf-8").strip()

    def origin_branch(self, name: str) -> str:
        return git(self.origins / f"{name}.git", "rev-parse", BRANCH)

    def snapshot(self) -> dict[str, object]:
        names = ("specs", "gateway", "agent", "ui", "library")
        state: dict[str, object] = {
            name: (
                self.head_of(name),
                git(self.worktree(name), "status", "--porcelain", "--untracked-files=no"),
            )
            for name in names
        }
        state["pins"] = tuple(self.pin_of(name) for name in names[1:])
        return state

    def assert_untouched(self, before: dict[str, object]) -> None:
        self.assertEqual(self.snapshot(), before)
        specs = self.worktree("specs")
        self.assertFalse(repin_branch.rebase_in_progress(specs))
        self.assertEqual(git(specs, "status", "--porcelain", "--untracked-files=no"), "")


class RepinTests(RepinCase):
    def test_rebases_specs_and_re_pins_each_consumer(self) -> None:
        main = self.advance_main()
        old_stamps = {
            "gateway": (
                self.worktree("gateway") / PY_STAMP_PATH.format(name="gateway")
            ).read_bytes(),
            "ui": (self.worktree("ui") / TS_STAMP_PATH).read_bytes(),
        }
        code, out, err = self.call()
        self.assertEqual(code, 0, err + out)

        specs = self.worktree("specs")
        new_head = git(specs, "rev-parse", "HEAD")
        new_first = git(specs, "rev-parse", "HEAD~1")
        self.assertNotEqual(new_head, self.head)
        self.assertEqual(git(specs, "rev-parse", "HEAD~2"), main)
        self.assertEqual(
            git(specs, "log", "--format=%s", f"{main}..HEAD").splitlines(),
            ["Add the widget contract", "Add field_four to gateway"],
        )

        # The pin of a repo that named the branch head is the new head; the one
        # that named the first commit is the new first commit.
        self.assertEqual(self.pin_of("gateway"), new_head)
        self.assertEqual(self.pin_of("ui"), new_head)
        self.assertEqual(self.pin_of("agent"), new_first)
        # SPECS_REF is the bare SHA and a newline: ASCII, LF, no BOM.
        raw = (self.worktree("gateway") / "SPECS_REF").read_bytes()
        self.assertEqual(raw, new_head.encode("ascii") + b"\n")

        # The stamp changes in the SHA and nowhere else.
        for name, path in (
            ("gateway", PY_STAMP_PATH.format(name="gateway")),
            ("ui", TS_STAMP_PATH),
        ):
            stamp = (self.worktree(name) / path).read_bytes()
            self.assertEqual(stamp, old_stamps[name].replace(self.head.encode(), new_head.encode()))
            self.assertNotIn(self.head.encode(), stamp)
            self.assertEqual(stamp.count(new_head.encode()), 2)

        # One commit each: the pin and the stamp, signed off, with the named message.
        for name in ("gateway", "agent", "ui"):
            tree = self.worktree(name)
            self.assertEqual(git(tree, "rev-list", "--count", "origin/main..HEAD"), "2")
            self.assertEqual(
                git(tree, "diff", "--name-only", "HEAD~1", "HEAD").splitlines(),
                sorted(["SPECS_REF", self.stamp_path(name)]),
            )
            subject = git(tree, "log", "-1", "--format=%s")
            self.assertEqual(
                subject, f"Re-pin specs {self.pin_of(name)[:7]} after rebasing {BRANCH}"
            )
            self.assertIn("Signed-off-by: Fixture", git(tree, "log", "-1", "--format=%B"))
            self.assertEqual(git(tree, "status", "--porcelain", "--untracked-files=no"), "")

        # The consumer pinned to a commit of main is left alone.
        self.assertEqual(self.pin_of("library"), self.initial)
        self.assertEqual(
            git(self.worktree("library"), "rev-list", "--count", "origin/main..HEAD"), "1"
        )

        # Nothing is pushed without --push.
        self.assertEqual(self.origin_branch("specs"), self.head)
        self.assertNotEqual(self.origin_branch("gateway"), self.head_of("gateway"))
        self.assertIn(f"{self.head[:7]} -> {new_head[:7]}", out)
        self.assertIn("not pushed", out)

        # What main changed in the contracts is named, with the regeneration warning.
        self.assertIn("openapi/library.yaml", out)
        self.assertNotIn("openapi/widget.yaml", out)
        self.assertIn("needs a", out)
        self.assertIn("regeneration", out)

    def stamp_path(self, name: str) -> str:
        return TS_STAMP_PATH if name == "ui" else PY_STAMP_PATH.format(name=name)

    def test_the_commit_names_a_co_author_when_given(self) -> None:
        self.advance_main()
        out, err = io.StringIO(), io.StringIO()
        options = ["--root", str(self.root), "--repos-root", str(self.repos)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = repin_branch.main(
                [BRANCH, *options, "--co-author", "Some Model <noreply@example.invalid>"]
            )
        self.assertEqual(code, 0, err.getvalue())
        body = git(self.worktree("gateway"), "log", "-1", "--format=%B")
        self.assertIn("Co-Authored-By: Some Model <noreply@example.invalid>", body)
        self.assertIn("Signed-off-by:", body)

    def test_without_a_contract_change_on_main_it_says_no_regeneration_is_needed(self) -> None:
        main = self.repos / "specs"
        write(main / "README.md", "specs, edited\n")
        self.commit(main, "Edit the readme")
        git(main, "push", "-q", "origin", "main")
        code, out, err = self.call()
        self.assertEqual(code, 0, err)
        self.assertIn("no regeneration is needed", out)
        self.assertNotIn("Contracts that changed", out)

    def test_when_main_has_not_moved_nothing_is_rebased_or_re_pinned(self) -> None:
        before = self.snapshot()
        code, out, err = self.call("--dry-run")
        self.assertEqual(code, 0, err + out)
        self.assertIn("already based on origin/main", out)
        code, out, err = self.call()
        self.assertEqual(code, 0, err + out)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("committed", out)

    def test_a_conflict_aborts_the_rebase_and_names_the_files(self) -> None:
        self.advance_main(conflicting=True)
        before = self.snapshot()
        code, out, err = self.call()
        self.assertEqual(code, 1)
        self.assertIn("openapi/gateway.yaml", err)
        self.assertIn("aborted", err)
        self.assert_untouched(before)
        self.assertEqual(self.head_of("specs"), self.head)

    def test_a_dropped_commit_stops_and_puts_the_branch_back(self) -> None:
        self.advance_main(duplicate=True)
        before = self.snapshot()
        code, out, err = self.call()
        self.assertEqual(code, 1)
        self.assertIn("2 before, 1 after", err)
        self.assertIn("Add field_four to gateway", err)
        self.assertIn(self.head[:7], err)
        self.assert_untouched(before)

    def test_dry_run_changes_nothing(self) -> None:
        self.advance_main()
        before = self.snapshot()
        trees = git(self.repos / "specs", "worktree", "list", "--porcelain")
        code, out, err = self.call("--dry-run")
        self.assertEqual(code, 0, err + out)
        self.assert_untouched(before)
        self.assertEqual(git(self.repos / "specs", "worktree", "list", "--porcelain"), trees)
        self.assertEqual(self.origin_branch("specs"), self.head)
        self.assertIn("Dry run", out)
        self.assertIn("would re-pin", out)
        self.assertIn("commit 2 of 2", out)
        self.assertIn("commit 1 of 2", out)  # the agent's pin
        self.assertIn("openapi/library.yaml", out)
        self.assertIn(
            f"{self.initial[:7]}  unchanged: pin {self.initial[:7]} is a commit of main", out
        )

    def test_dry_run_reports_a_conflict_and_changes_nothing(self) -> None:
        self.advance_main(conflicting=True)
        before = self.snapshot()
        trees = git(self.repos / "specs", "worktree", "list", "--porcelain")
        code, out, err = self.call("--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("openapi/gateway.yaml", err)
        self.assert_untouched(before)
        self.assertEqual(git(self.repos / "specs", "worktree", "list", "--porcelain"), trees)

    def test_an_uncommitted_change_stops_everything(self) -> None:
        self.advance_main()
        write(self.worktree("gateway") / "README.md", "edited\n")
        code, out, err = self.call()
        self.assertEqual(code, 1)
        self.assertIn("uncommitted changes", err)
        self.assertIn("gateway", err)
        self.assertEqual(self.head_of("specs"), self.head)
        self.assertEqual(self.pin_of("agent"), self.first)

    def test_a_stamp_that_disagrees_with_the_pin_stops_before_the_rebase(self) -> None:
        self.advance_main()
        agent = self.worktree("agent")
        write(agent / self.stamp_path("agent"), PY_STAMP.format(sha=self.initial))
        self.commit(agent, "Stamp drifted")
        code, out, err = self.call()
        self.assertEqual(code, 1)
        self.assertIn("run the repo's codegen first", err)
        self.assertEqual(self.head_of("specs"), self.head)

    def test_a_branch_with_no_specs_worktree_stops(self) -> None:
        code, out, err = self.call(branch="no-such-row")
        self.assertEqual(code, 1)
        self.assertIn("no specs worktree of no-such-row", err)

    def test_push_forces_specs_then_pushes_each_re_pinned_consumer(self) -> None:
        self.advance_main()
        library_before = self.origin_branch("library")
        code, out, err = self.call("--push")
        self.assertEqual(code, 0, err + out)
        new_head = self.head_of("specs")
        self.assertEqual(self.origin_branch("specs"), new_head)
        for name in ("gateway", "agent", "ui"):
            self.assertEqual(self.origin_branch(name), self.head_of(name))
        self.assertEqual(self.origin_branch("library"), library_before)
        self.assertEqual(out.count(", pushed"), 3)
        self.assertNotIn("not pushed", out)

    def test_push_refuses_to_delete_commits_only_origin_has(self) -> None:
        self.advance_main()
        other = self.base / "other-specs"
        subprocess.run(
            ["git", "clone", "-q", "-b", BRANCH, str(self.origins / "specs.git"), str(other)],
            check=True,
        )
        write(other / "extra.md", "someone else's work\n")
        self.commit(other, "A commit made elsewhere")
        git(other, "push", "-q", "origin", BRANCH)
        before = self.snapshot()
        code, out, err = self.call("--push")
        self.assertEqual(code, 1)
        self.assertIn("A commit made elsewhere", err)
        self.assert_untouched(before)

    def test_a_failing_hook_restores_that_repo_and_the_rest_go_on(self) -> None:
        self.advance_main()
        hook = self.repos / "agent" / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\necho 'hook says no'\nexit 1\n")
        os.chmod(hook, 0o755)
        code, out, err = self.call()
        self.assertEqual(code, 1)
        self.assertIn("hook says no", out)
        self.assertIn("FAILED", out)
        agent = self.worktree("agent")
        self.assertEqual(self.pin_of("agent"), self.first)  # put back
        self.assertEqual(git(agent, "status", "--porcelain", "--untracked-files=no"), "")
        self.assertEqual(git(agent, "rev-list", "--count", "origin/main..HEAD"), "1")
        new_head = self.head_of("specs")
        self.assertEqual(self.pin_of("gateway"), new_head)  # the others were done
        self.assertEqual(self.pin_of("ui"), new_head)

        # Run again with the hook gone: the specs branch is already rebased, and
        # the agent's old pin is found by the subject of the commit it named.
        hook.unlink()
        code, out, err = self.call()
        self.assertEqual(code, 0, err + out)
        self.assertEqual(self.pin_of("agent"), git(self.worktree("specs"), "rev-parse", "HEAD~1"))
        self.assertEqual(git(agent, "rev-list", "--count", "origin/main..HEAD"), "2")
        self.assertEqual(
            git(self.worktree("gateway"), "rev-list", "--count", "origin/main..HEAD"), "2"
        )
        self.assertIn("pin is current", out)
        # A third run has nothing left to do.
        before = self.snapshot()
        code, out, err = self.call()
        self.assertEqual(code, 0, err + out)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
