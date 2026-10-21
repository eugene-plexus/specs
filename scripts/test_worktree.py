from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
import venv as venv_module
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import worktree

IDENTITY = ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid")

PYPROJECT = """\
[project]
name = "alpha-pkg"
version = "0.0.0"

[project.optional-dependencies]
dev = []
service = []

[tool.hatch.build.targets.wheel]
packages = ["src/alpha_pkg"]
"""

WORKFLOW = """\
jobs:
  test:
    steps:
      - run: pip install -e ".[dev]"
"""


def git(path: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *IDENTITY, "-c", "commit.gpgsign=false", "-C", str(path), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_ok(path: Path, *arguments: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(path), *arguments], capture_output=True, text=True
        ).returncode
        == 0
    )


class WorktreeCase(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(worktree, "log")  # progress lines on stderr
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="ep-worktree-", ignore_cleanup_errors=True
        )
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repos = self.base / "repos"
        self.origins = self.base / "origins"
        self.root = self.base / "wt"
        self.repos.mkdir()
        self.origins.mkdir()
        # alpha is a Python repo whose .gitignore does not list .venv, like ui.
        self.make_repo(
            "alpha",
            {
                "pyproject.toml": PYPROJECT,
                "src/alpha_pkg/__init__.py": "",
                ".github/workflows/ci.yml": WORKFLOW,
            },
        )
        self.make_repo("beta", {"README.md": "beta\n"})
        self.alpha = self.repos / "alpha"
        self.beta = self.repos / "beta"

    def make_repo(self, name: str, files: dict[str, str]) -> Path:
        origin = self.origins / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        repo = self.repos / name
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        for relative, text in files.items():
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "First")
        git(repo, "remote", "add", "origin", str(origin))
        git(repo, "push", "-q", "origin", "main")
        return repo

    def push_from_elsewhere(self, name: str, branch: str | None = None) -> str:
        """Commit to the origin from a second clone, as another machine would."""
        other = self.base / f"other-{name}-{branch or 'main'}"
        subprocess.run(
            ["git", "clone", "-q", str(self.origins / f"{name}.git"), str(other)], check=True
        )
        if branch:
            git(other, "checkout", "-q", "-b", branch)
        (other / "elsewhere.txt").write_text("from elsewhere\n", encoding="utf-8")
        git(other, "add", ".")
        git(other, "commit", "-qm", "Elsewhere")
        git(other, "push", "-q", "origin", branch or "main")
        return git(other, "rev-parse", "HEAD")

    def call(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        options = ["--root", str(self.root), "--repos-root", str(self.repos)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = worktree.main([*arguments, *options])
        return code, out.getvalue(), err.getvalue()

    def tree(self, branch: str, repo: str) -> Path:
        return self.root / branch / repo


class AddTests(WorktreeCase):
    def test_new_branch_starts_at_origin_main_and_does_not_track_it(self) -> None:
        code, out, _ = self.call("add", "row-1", "alpha", "beta", "--no-venv")
        self.assertEqual(code, 0, out)
        for repo in ("alpha", "beta"):
            path = self.tree("row-1", repo)
            self.assertEqual(git(path, "rev-parse", "--abbrev-ref", "HEAD"), "row-1")
            self.assertEqual(
                git(path, "rev-parse", "HEAD"), git(self.repos / repo, "rev-parse", "origin/main")
            )
            self.assertFalse(git_ok(path, "config", "--get", "branch.row-1.remote"))
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 2, out)
        self.assertIn("new from origin/main", lines[0])
        self.assertTrue(lines[0].startswith("alpha"))
        self.assertEqual(git(self.alpha, "branch", "--show-current"), "main")

    def test_it_fetches_before_it_branches(self) -> None:
        newer = self.push_from_elsewhere("alpha")
        self.assertNotEqual(git(self.alpha, "rev-parse", "origin/main"), newer)
        self.assertEqual(self.call("add", "row-2", "alpha", "--no-venv")[0], 0)
        self.assertEqual(git(self.tree("row-2", "alpha"), "rev-parse", "HEAD"), newer)

    def test_base_option_sets_the_starting_point(self) -> None:
        first = git(self.alpha, "rev-parse", "HEAD")
        self.push_from_elsewhere("alpha")
        code, out, _ = self.call("add", "row-3", "alpha", "--no-venv", "--base", first)
        self.assertEqual(code, 0, out)
        self.assertEqual(git(self.tree("row-3", "alpha"), "rev-parse", "HEAD"), first)

    def test_branch_already_on_origin_is_checked_out_tracking_it(self) -> None:
        pushed = self.push_from_elsewhere("alpha", "row-4")
        code, out, _ = self.call("add", "row-4", "alpha", "--no-venv")
        self.assertEqual(code, 0, out)
        path = self.tree("row-4", "alpha")
        self.assertEqual(git(path, "rev-parse", "HEAD"), pushed)
        self.assertEqual(git(path, "rev-parse", "--abbrev-ref", "@{upstream}"), "origin/row-4")
        self.assertIn("tracking origin/row-4", out)

    def test_existing_local_branch_is_used_not_recreated(self) -> None:
        git(self.alpha, "branch", "row-5")
        code, out, _ = self.call("add", "row-5", "alpha", "--no-venv")
        self.assertEqual(code, 0, out)
        self.assertIn("existing local branch", out)

    def test_second_run_says_the_worktree_exists_and_carries_on(self) -> None:
        self.assertEqual(self.call("add", "row-6", "alpha", "--no-venv")[0], 0)
        code, out, _ = self.call("add", "row-6", "alpha", "--no-venv")
        self.assertEqual(code, 0, out)
        self.assertIn("[exists]", out)

    def test_other_branch_at_the_same_path_is_refused(self) -> None:
        git(self.alpha, "branch", "other")
        path = self.tree("row-7", "alpha")
        path.parent.mkdir(parents=True)
        git(self.alpha, "worktree", "add", str(path), "other")
        code, out, _ = self.call("add", "row-7", "alpha", "--no-venv")
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
        self.assertIn("on other", out)

    def test_one_bad_repo_does_not_stop_the_others(self) -> None:
        code, out, _ = self.call("add", "row-8", "nowhere", "beta", "--no-venv")
        self.assertEqual(code, 1)
        self.assertIn("nowhere: FAILED", out)
        self.assertTrue(self.tree("row-8", "beta").is_dir())

    def test_unknown_base_and_bad_branch_names_fail_loudly(self) -> None:
        code, out, _ = self.call("add", "row-9", "alpha", "--no-venv", "--base", "origin/nope")
        self.assertEqual(code, 1)
        self.assertIn("origin/nope", out)
        self.assertFalse(self.tree("row-9", "alpha").exists())
        for bad in ("bad..name", "has space", "ends.lock"):
            code, _, err = self.call("add", bad, "alpha", "--no-venv")
            self.assertEqual(code, 1, bad)
            self.assertIn("not a usable branch name", err)

    def test_a_branch_and_repos_without_a_subcommand_means_add(self) -> None:
        code, out, _ = self.call("row-10", "beta", "--no-venv")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.tree("row-10", "beta").is_dir())


class VenvTests(WorktreeCase):
    def fake_install(self, target: Path | None, calls: list[list[str]]):
        """Stand in for the editable install: a .pth file that points at `target`."""

        def install(tree: Path, venv: Path, extras, uv) -> None:
            calls.append(list(extras))
            if target is None:
                return
            python = worktree.venv_python(venv)
            purelib = subprocess.run(
                [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (Path(purelib) / "editable.pth").write_text(str(target) + "\n", encoding="utf-8")

        return install

    def add(self, branch: str, target: Path | None, calls: list[list[str]], *, real: bool = False):
        def quick(venv: Path, python, uv) -> None:
            venv_module.create(venv, with_pip=False)  # no ensurepip: seconds saved per test

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(worktree, "install_editable", self.fake_install(target, calls))
            )
            if not real:
                stack.enter_context(patch.object(worktree, "create_venv", quick))
            return self.call("add", branch, "alpha", "--python", sys.executable, "--no-uv")

    def test_the_real_venv_creation_makes_a_usable_python(self) -> None:
        path = self.tree("row-v0", "alpha")
        code, out, err = self.add("row-v0", path / "src", [], real=True)
        self.assertEqual(code, 0, out + err)
        python = worktree.venv_python(path / ".venv")
        self.assertTrue(python.is_file())
        self.assertIn(f"{sys.version_info.major}.{sys.version_info.minor}", out)

    def test_import_resolving_into_the_worktree_passes(self) -> None:
        calls: list[list[str]] = []
        path = self.tree("row-v1", "alpha")
        code, out, err = self.add("row-v1", path / "src", calls)
        self.assertEqual(code, 0, out + err)
        self.assertIn("import ok: alpha_pkg -> src/alpha_pkg/__init__.py", out)
        self.assertEqual(calls, [["dev"]])
        # The venv is invisible to git, though alpha's .gitignore never mentions it.
        self.assertEqual(git(path, "status", "--porcelain"), "")
        self.assertEqual((path / ".venv" / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_import_resolving_into_the_main_checkout_fails(self) -> None:
        calls: list[list[str]] = []
        code, out, _ = self.add("row-v2", self.alpha / "src", calls)
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
        self.assertIn("another checkout's code", out)

    def test_a_package_that_is_not_installed_fails(self) -> None:
        code, out, _ = self.add("row-v3", None, [])
        self.assertEqual(code, 1)
        self.assertIn("not installed", out)

    def test_a_second_run_reuses_a_venv_that_passes(self) -> None:
        calls: list[list[str]] = []
        path = self.tree("row-v4", "alpha")
        self.assertEqual(self.add("row-v4", path / "src", calls)[0], 0)
        code, out, _ = self.add("row-v4", path / "src", calls)
        self.assertEqual(code, 0, out)
        self.assertIn("reused", out)
        self.assertEqual(len(calls), 1)

    def test_a_second_run_repairs_a_venv_that_points_elsewhere(self) -> None:
        calls: list[list[str]] = []
        path = self.tree("row-v5", "alpha")
        self.assertEqual(self.add("row-v5", self.alpha / "src", calls)[0], 1)
        code, out, _ = self.add("row-v5", path / "src", calls)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(calls), 2)

    def test_the_python_version_is_checked_unless_overridden(self) -> None:
        worktree.check_version("3.12.10", pinned=True)
        with self.assertRaisesRegex(worktree.WorktreeError, "3.14.0"):
            worktree.check_version("3.14.0", pinned=True)
        worktree.check_version("3.14.0", pinned=False)


class ParsingTests(unittest.TestCase):
    AGENT = """\
      - run: |
          if [[ "$RUNNER_OS" == "Windows" ]]; then
            pip install -e ".[dev,service,tray]"
          else
            pip install -e ".[dev]"
          fi
      - run: pip install -e ".[dev]"
    """

    def test_extras_follow_the_ci_of_this_os(self) -> None:
        available = ["service", "tray", "dev"]
        self.assertEqual(
            worktree.ci_extras(self.AGENT, available, windows=True), ["dev", "service", "tray"]
        )
        self.assertEqual(worktree.ci_extras(self.AGENT, available, windows=False), ["dev"])

    def test_extras_default_to_dev_and_ignore_names_the_pyproject_lacks(self) -> None:
        self.assertEqual(worktree.ci_extras("", ["dev"], windows=False), ["dev"])
        self.assertEqual(worktree.ci_extras("", [], windows=False), [])
        text = 'pip install -c c.txt -e ".[dev, bogus]"'
        self.assertEqual(worktree.ci_extras(text, ["dev"], windows=True), ["dev"])

    def test_package_comes_from_the_hatch_wheel_or_the_project_name(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            folder = Path(name)
            (folder / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
            package = worktree.read_package(folder)
            self.assertEqual(package.module, "alpha_pkg")
            self.assertEqual(package.location, PurePosixPath("src/alpha_pkg"))
            self.assertEqual(package.extras, ("dev", "service"))
            (folder / "pyproject.toml").write_text(
                PYPROJECT.replace("src/alpha_pkg", "python/ui_pkg"), encoding="utf-8"
            )
            self.assertEqual(worktree.read_package(folder).location, PurePosixPath("python/ui_pkg"))
            (folder / "pyproject.toml").write_text(
                '[project]\nname = "Plain-Name"\n', encoding="utf-8"
            )
            self.assertEqual(
                worktree.read_package(folder).location, PurePosixPath("src/plain_name")
            )

    def test_npm_runs_only_when_asked_and_only_where_there_is_a_lockfile(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            folder = Path(name)
            self.assertEqual(worktree.prepare_npm(folder, True), "")
            (folder / "web").mkdir()
            (folder / "web" / "package-lock.json").write_text("{}", encoding="utf-8")
            calls: list[list[object]] = []
            with (
                patch.object(worktree, "log"),
                patch.object(worktree.shutil, "which", return_value="npm"),
                patch.object(
                    worktree, "run", side_effect=lambda command, **_: calls.append(command)
                ),
            ):
                self.assertIn("not run", worktree.prepare_npm(folder, False))
                self.assertEqual(calls, [])
                self.assertEqual(worktree.prepare_npm(folder, True), "ci ok in web")
            self.assertEqual(calls, [["npm", "ci"]])


class RemoveAndListTests(WorktreeCase):
    def test_dirty_worktree_blocks_the_removal_until_forced(self) -> None:
        self.assertEqual(self.call("add", "row-r1", "alpha", "beta", "--no-venv")[0], 0)
        (self.tree("row-r1", "alpha") / "scratch.txt").write_text("x", encoding="utf-8")
        code, out, _ = self.call("remove", "row-r1")
        self.assertEqual(code, 1)
        self.assertIn("alpha: uncommitted changes", out)
        self.assertIn("nothing removed", out)
        self.assertTrue(self.tree("row-r1", "beta").is_dir())
        code, out, _ = self.call("remove", "row-r1", "--force")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.root / "row-r1").exists())
        self.assertTrue((self.alpha / "src").is_dir())

    def test_clean_removal_deletes_the_branch_only_when_asked(self) -> None:
        self.assertEqual(self.call("add", "row-r2", "alpha", "--no-venv")[0], 0)
        code, out, _ = self.call("remove", "row-r2")
        self.assertEqual(code, 0, out)
        self.assertEqual(git(self.alpha, "branch", "--list", "row-r2"), "row-r2")
        self.assertEqual(self.call("add", "row-r2", "alpha", "--no-venv")[0], 0)
        code, out, _ = self.call("remove", "row-r2", "--delete-branch")
        self.assertEqual(code, 0, out)
        self.assertEqual(git(self.alpha, "branch", "--list", "row-r2"), "")

    def test_unmerged_work_keeps_its_branch_unless_forced(self) -> None:
        self.assertEqual(self.call("add", "row-r3", "alpha", "--no-venv")[0], 0)
        path = self.tree("row-r3", "alpha")
        (path / "work.txt").write_text("work\n", encoding="utf-8")
        git(path, "add", "work.txt")
        git(path, "commit", "-qm", "Work")
        code, out, _ = self.call("remove", "row-r3", "--delete-branch")
        self.assertEqual(code, 1)
        self.assertIn("kept branch row-r3", out)
        self.assertEqual(git(self.alpha, "branch", "--list", "row-r3"), "row-r3")
        self.assertEqual(self.call("add", "row-r3", "alpha", "--no-venv")[0], 0)
        code, out, _ = self.call("remove", "row-r3", "--delete-branch", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(git(self.alpha, "branch", "--list", "row-r3"), "")

    def test_worktrees_outside_the_root_are_left_alone(self) -> None:
        elsewhere = self.base / "elsewhere" / "alpha"
        git(self.alpha, "worktree", "add", "-q", "-b", "row-r4", str(elsewhere), "main")
        code, out, _ = self.call("remove", "row-r4", "--force")
        self.assertEqual(code, 0)
        self.assertIn("no worktrees", out)
        self.assertTrue(elsewhere.is_dir())

    def test_remove_with_a_venv_in_the_tree(self) -> None:
        path = self.tree("row-r5", "alpha")
        self.assertEqual(self.call("add", "row-r5", "alpha", "--no-venv")[0], 0)
        venv = path / ".venv"
        venv.mkdir()
        (venv / ".gitignore").write_text("*\n", encoding="utf-8")
        (venv / "python.txt").write_text("stand-in\n", encoding="utf-8")
        code, out, _ = self.call("remove", "row-r5")
        self.assertEqual(code, 0, out)
        self.assertFalse(path.exists())

    def test_list_shows_branch_state_and_sync(self) -> None:
        self.assertEqual(self.call("add", "row-l1", "alpha", "beta", "--no-venv")[0], 0)
        (self.tree("row-l1", "alpha") / "scratch.txt").write_text("x", encoding="utf-8")
        beta = self.tree("row-l1", "beta")
        git(beta, "push", "-q", "-u", "origin", "row-l1")
        (beta / "work.txt").write_text("work\n", encoding="utf-8")
        git(beta, "add", "work.txt")
        git(beta, "commit", "-qm", "Work")
        code, out, _ = self.call("list")
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertIn("row-l1", lines)
        alpha = next(line for line in lines if line.strip().startswith("alpha"))
        beta_line = next(line for line in lines if line.strip().startswith("beta"))
        self.assertIn("dirty", alpha)
        self.assertIn("not on origin", alpha)
        self.assertIn("clean", beta_line)
        self.assertIn("ahead 1 behind 0", beta_line)
        self.assertIn(self.tree("row-l1", "beta").as_posix(), beta_line)

    def test_list_with_nothing_says_so(self) -> None:
        code, out, _ = self.call("list")
        self.assertEqual(code, 0)
        self.assertIn("no worktrees", out)


class ReposRootTests(WorktreeCase):
    def test_siblings_are_found_from_the_main_checkout_and_from_a_worktree(self) -> None:
        specs = self.make_repo("specs", {"scripts/worktree.py": "# stand-in\n"})
        main_script = specs / "scripts" / "worktree.py"
        self.assertEqual(worktree.default_repos_root(main_script), self.repos)
        linked = self.root / "row-s1" / "specs"
        git(specs, "worktree", "add", "-q", "-b", "row-s1", str(linked))
        found = worktree.default_repos_root(linked / "scripts" / "worktree.py")
        self.assertEqual(found, self.repos)
        self.assertNotEqual(found, linked.parent)

    def test_only_main_checkouts_count_as_repos(self) -> None:
        self.assertEqual(self.call("add", "row-s2", "alpha", "--no-venv")[0], 0)
        self.assertEqual(
            [path.name for path in worktree.known_repos(self.repos)], ["alpha", "beta"]
        )
        # A worktree has a .git file, not a directory: it is never taken for a repo.
        self.assertEqual([path.name for path in worktree.known_repos(self.root / "row-s2")], [])


if __name__ == "__main__":
    unittest.main()
