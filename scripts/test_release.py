"""release.py's own logic, offline: versions, resuming, the record and the release body,
and patch releases from a release line (against the bare repositories of
release-patch-acceptance.py)."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import release  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "release_patch_acceptance", SCRIPTS / "release-patch-acceptance.py"
)
assert _spec is not None and _spec.loader is not None
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)

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


# --- patch releases ------------------------------------------------------------

TAGS = ["v0.1.0-alpha.2", "v0.2.0", "v0.2.3", "v0.3.0"]


def git_env() -> dict[str, str]:
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def plain_git(
    repo: Path, *args: str, env: dict[str, str] | None = None, stdin: str = ""
) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env={**git_env(), **(env or {})},
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class PatchVersionTests(unittest.TestCase):
    def test_patch_version_must_follow_the_latest(self) -> None:
        self.assertEqual(
            release.patch_previous(
                "v0.3.1", (0, 3), TAGS, "v0.3.0", security=False, rehearsal=False
            ),
            "v0.3.0",
        )
        for version in ("v0.3.2", "v0.3.0"):  # a skip, and a reuse
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(release.Stop, "must follow v0.3.0"),
            ):
                release.patch_previous(
                    version, (0, 3), TAGS, "v0.3.0", security=False, rehearsal=False
                )
        with self.assertRaisesRegex(release.Stop, "older than the latest.*--security"):
            release.patch_previous(
                "v0.2.4", (0, 2), TAGS, "v0.3.0", security=False, rehearsal=False
            )

    def test_an_older_line_takes_a_security_fix_as_its_next_patch(self) -> None:
        self.assertEqual(
            release.patch_previous(
                "v0.2.4", (0, 2), TAGS, "v0.3.0", security=True, rehearsal=False
            ),
            "v0.2.3",
        )
        with self.assertRaisesRegex(release.Stop, "must follow v0.2.3"):
            release.patch_previous(
                "v0.2.5", (0, 2), TAGS, "v0.3.0", security=True, rehearsal=False
            )

    def test_a_version_must_be_on_the_checkouts_line(self) -> None:
        with self.assertRaisesRegex(release.Stop, "not on line v0.3"):
            release.patch_previous(
                "v0.4.1", (0, 3), TAGS, "v0.3.0", security=False, rehearsal=False
            )
        with self.assertRaisesRegex(release.Stop, "no release"):
            release.patch_previous(
                "v0.5.1", (0, 5), TAGS, "v0.3.0", security=False, rehearsal=False
            )

    def test_a_suffix_needs_rehearsal_and_a_rehearsal_needs_its_suffix(self) -> None:
        self.assertEqual(
            release.patch_previous(
                "v0.3.1-rehearsal.1",
                (0, 3),
                TAGS,
                "v0.3.0",
                security=False,
                rehearsal=True,
            ),
            "v0.3.0",
        )
        with self.assertRaisesRegex(release.Stop, "three numbers"):
            release.patch_previous(
                "v0.3.1-rehearsal.1",
                (0, 3),
                TAGS,
                "v0.3.0",
                security=False,
                rehearsal=False,
            )
        with self.assertRaisesRegex(release.Stop, "rehearsal.N"):
            release.patch_previous(
                "v0.3.1", (0, 3), TAGS, "v0.3.0", security=False, rehearsal=True
            )


class PushGuardTests(unittest.TestCase):
    def test_the_push_guard_refuses_main_dist_and_edge_on_a_line(self) -> None:
        line = {"branch": "release/v0.3", "version": "v0.3.1", "root": "nowhere"}
        repo = Path(tempfile.gettempdir()) / "agent"
        with (
            mock.patch.object(release, "LINE", line),
            mock.patch.object(release, "git") as git,
        ):
            for ref in (
                "main",
                "refs/heads/main",
                "refs/heads/dist",
                "refs/heads/edge",
                "refs/heads/release/v0.2",
                "refs/tags/v0.3.2",
            ):
                with self.subTest(ref=ref), self.assertRaises(release.Refused):
                    release.push(repo, "HEAD", ref)
            with self.assertRaises(release.Refused):
                release.push(repo, "", "refs/heads/release/v0.3", delete=True)
            with self.assertRaises(release.Refused):
                release.push(
                    repo, "", "refs/heads/release-candidate/v0.4.0", delete=True
                )
            self.assertEqual(git.call_count, 0)
            for ref in (
                "refs/heads/release/v0.3",
                "refs/heads/release/v0.3-dist",
                "refs/heads/release-candidate/v0.3.1",
                "refs/tags/v0.3.1",
            ):
                release.push(repo, "abc", ref)
            self.assertEqual(
                [c.args[-1] for c in git.call_args_list],
                [
                    "abc:refs/heads/release/v0.3",
                    "abc:refs/heads/release/v0.3-dist",
                    "abc:refs/heads/release-candidate/v0.3.1",
                    "abc:refs/tags/v0.3.1",
                ],
            )

    def test_edge_is_never_pushed_and_only_scratch_branches_are_deleted(self) -> None:
        with (
            mock.patch.object(release, "LINE", None),
            mock.patch.object(release, "git") as git,
        ):
            with self.assertRaises(release.Refused):
                release.push(Path("specs"), "HEAD", "refs/heads/edge")
            with self.assertRaises(release.Refused):
                release.push(Path("specs"), "", "refs/heads/main", delete=True)
            release.push(Path("specs"), "HEAD", "refs/heads/main")
            release.push(Path("specs"), "", "release-candidate/v0.4.0", delete=True)
        self.assertEqual(
            [c.args[1:] for c in git.call_args_list],
            [
                ("push", "-q", "origin", "HEAD:refs/heads/main"),
                (
                    "push",
                    "-q",
                    "origin",
                    "--delete",
                    "refs/heads/release-candidate/v0.4.0",
                ),
            ],
        )


class DocsOnlyTests(unittest.TestCase):
    def test_docs_only_refuses_renames_modes_submodules_and_other_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            repo = Path(scratch)
            plain_git(repo, "init", "-q")
            (repo / "docs").mkdir()
            (repo / "scripts").mkdir()
            (repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
            (repo / "scripts" / "x.py").write_text("x = 1\n", encoding="utf-8")
            plain_git(repo, "add", "-A")
            plain_git(repo, "commit", "-q", "-m", "base")
            base = plain_git(repo, "rev-parse", "HEAD")
            blob = plain_git(repo, "rev-parse", "HEAD:docs/a.md")
            new = plain_git(repo, "hash-object", "-w", "--stdin", stdin="changed\n")

            def tree_commit(*operations: list[str]) -> str:
                env = {"GIT_INDEX_FILE": str(repo / ".git" / "scratch-index")}
                plain_git(repo, "read-tree", base, env=env)
                for operation in operations:
                    plain_git(repo, *operation, env=env)
                tree = plain_git(repo, "write-tree", env=env)
                return plain_git(repo, "commit-tree", tree, "-p", base, "-m", "x")

            def cacheinfo(mode: str, sha: str, path: str) -> list[str]:
                return ["update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}"]

            good = tree_commit(
                cacheinfo("100644", new, "docs/a.md"),
                cacheinfo("100644", blob, "docs/b.md"),
            )
            self.assertEqual(
                release.docs_only(repo, base, good), ["docs/a.md", "docs/b.md"]
            )
            bad = {
                "another path": [cacheinfo("100644", new, "scripts/x.py")],
                "a rename": [
                    ["update-index", "--force-remove", "docs/a.md"],
                    cacheinfo("100644", blob, "docs/c.md"),
                ],
                "a deletion": [["update-index", "--force-remove", "docs/a.md"]],
                "a mode change": [cacheinfo("100755", blob, "docs/a.md")],
                "a submodule": [cacheinfo("160000", base, "docs/sub")],
                "a symlink": [cacheinfo("120000", blob, "docs/link")],
            }
            for name, operations in bad.items():
                with (
                    self.subTest(name),
                    self.assertRaisesRegex(release.Refused, "documentation-only"),
                ):
                    release.docs_only(repo, base, tree_commit(*operations))


class DistTests(unittest.TestCase):
    def test_the_dist_parent_is_the_last_releases_dist_never_origin_dist(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            repo = Path(scratch)
            plain_git(repo, "init", "-q")
            empty = plain_git(repo, "hash-object", "-t", "tree", "-w", "--stdin")

            def commit(message: str, *parents: str) -> str:
                flags = [x for p in parents for x in ("-p", p)]
                return plain_git(repo, "commit-tree", empty, *flags, "-m", message)

            pin = commit("the last release's dist")
            earlier_candidate = commit("an earlier candidate", pin)
            main_dist = commit("main's dist")
            ref = "refs/remotes/origin/release/v0.3-dist"
            self.assertEqual(release.dist_parent(repo, pin, "release/v0.3-dist"), pin)
            plain_git(repo, "update-ref", ref, pin)
            self.assertEqual(release.dist_parent(repo, pin, "release/v0.3-dist"), pin)
            plain_git(repo, "update-ref", ref, earlier_candidate)
            self.assertEqual(
                release.dist_parent(repo, pin, "release/v0.3-dist"), earlier_candidate
            )
            plain_git(repo, "update-ref", ref, main_dist)
            with self.assertRaisesRegex(release.Stop, "does not hold"):
                release.dist_parent(repo, pin, "release/v0.3-dist")

    def test_built_from_reads_the_message_and_refuses_one_that_names_no_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            repo = Path(scratch)
            plain_git(repo, "init", "-q")
            empty = plain_git(repo, "hash-object", "-t", "tree", "-w", "--stdin")
            source = plain_git(repo, "commit-tree", empty, "-m", "source")
            other = plain_git(repo, "commit-tree", empty, "-m", "other")
            dist = plain_git(
                repo,
                "commit-tree",
                empty,
                "-p",
                other,
                "-p",
                source,
                "-m",
                f"Publish\n\nbuilt-from: eugene-plexus/ui@{source}",
            )
            self.assertEqual(release.built_from(repo, "ui", dist), source)
            forged = plain_git(
                repo,
                "commit-tree",
                empty,
                "-p",
                other,
                "-m",
                f"Publish\n\nbuilt-from: eugene-plexus/ui@{source}",
            )
            with self.assertRaisesRegex(release.Stop, "not one of its parents"):
                release.built_from(repo, "ui", forged)


class LockTests(unittest.TestCase):
    def test_a_dependency_change_stops_the_candidate_until_the_lock_is_resolved(
        self,
    ) -> None:
        sources = {name: "s" for name in release.LINE_REPOS}
        heads = {**sources, "gateway": "h"}

        def dependencies(repo: Path, ref: str) -> list[str]:
            if repo.name == "gateway" and ref == "h":
                return ["hatchling", "httpx", "rich"]
            return ["hatchling", "httpx"]

        with (
            tempfile.TemporaryDirectory() as scratch,
            mock.patch.object(release, "SPECS", Path(scratch)),
            mock.patch.object(release, "LINE", {"branch": "release/v0.3"}),
            mock.patch.object(release.ship, "dependencies", side_effect=dependencies),
        ):
            listed = Path(scratch) / "release" / "requirements.in"
            listed.parent.mkdir()
            listed.write_text("hatchling\nhttpx\n", encoding="utf-8")
            release.check_lock(sources, sources)  # nothing moved
            with self.assertRaisesRegex(release.Stop, "gateway.*--resolve"):
                release.check_lock(sources, heads)
            listed.write_text("hatchling\nhttpx\nrich\n", encoding="utf-8")
            release.check_lock(sources, heads)  # resolved on the line


class DocsToMainTests(unittest.TestCase):
    """The notes and the record reach specs main; only a real race is retried."""

    def setUp(self) -> None:
        self.scratch = Path(tempfile.mkdtemp(prefix="ep-docs-main-"))
        env = mock.patch.dict(
            os.environ, fixture.hermetic_env(self.scratch), clear=True
        )
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(fixture.remove_tree, self.scratch)
        self.bare = self.scratch / "origin.git"
        self.git(self.scratch, "init", "-q", "--bare", str(self.bare))
        self.specs = self.scratch / "specs"
        self.git(self.scratch, "clone", "-q", self.bare.as_uri(), str(self.specs))
        self.commit(self.specs, {"docs/a.md": "a\n", "scripts/x.py": "x = 1\n"}, "base")
        self.git(self.specs, "push", "-q", "origin", "main")
        self.git(self.specs, "checkout", "-q", "-b", "release/v0.3")
        self.commit(
            self.specs,
            {
                "docs/acceptance/v0.3.1-release-run.md": "# v0.3.1 release run\n",
                "docs/releases/v0.3.1.md": "# Eugene Plexus v0.3.1\n",
                "release/manifest.json": "{}\n",
            },
            "the line's candidate and record",
        )
        self.git(self.specs, "push", "-q", "origin", "release/v0.3")
        line = {
            "branch": "release/v0.3",
            "version": "v0.3.1",
            "root": str(self.scratch),
        }
        for name, value in (("SPECS", self.specs), ("LINE", line)):
            patch = mock.patch.object(release, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.r = release.Release("v0.3.1", None)

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()

    def commit(self, work: Path, files: dict[str, str], message: str) -> None:
        for name, text in files.items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text, encoding="utf-8", newline="\n")
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "-m", message)

    def test_a_refused_push_names_its_cause_and_is_not_retried(self) -> None:
        hooks = self.bare / "hooks"
        hook = hooks / "pre-receive"
        hook.write_text(
            '#!/bin/sh\necho attempt >> attempts.log\necho "denied by policy" >&2\nexit 1\n',
            encoding="utf-8",
            newline="\n",
        )
        os.chmod(hook, 0o755)
        self.git(self.bare, "config", "core.hooksPath", hooks.as_posix())
        with self.assertRaisesRegex(
            release.Failed, "(?s)did not move.*denied by policy"
        ):
            release.push_docs_to_main(self.r)
        attempts = (self.bare / "attempts.log").read_text(encoding="utf-8")
        self.assertEqual(attempts.count("attempt"), 1)

    def test_main_that_moved_meanwhile_is_retried_on_its_new_head(self) -> None:
        other = self.scratch / "other"
        self.git(self.scratch, "clone", "-q", self.bare.as_uri(), str(other))
        real, calls = release.push, []

        def racing(repo: Path, src: str, ref: str, **kwargs: bool) -> None:
            calls.append(ref)
            if len(calls) == 1:  # another session lands on main after the fetch
                self.commit(other, {"docs/other.md": "other\n"}, "another session")
                self.git(other, "push", "-q", "origin", "main")
            real(repo, src, ref, **kwargs)

        with mock.patch.object(release, "push", side_effect=racing):
            release.push_docs_to_main(self.r)
        self.assertEqual(len(calls), 2)
        parent = self.git(self.bare, "rev-parse", "main^")
        self.assertEqual(
            self.git(self.bare, "log", "-1", "--format=%s", parent), "another session"
        )
        self.assertEqual(
            sorted(
                self.git(self.bare, "diff", "--name-only", parent, "main").splitlines()
            ),
            ["docs/acceptance/v0.3.1-release-run.md", "docs/releases/v0.3.1.md"],
        )


class SeamTests(unittest.TestCase):
    def test_every_push_and_gh_call_goes_through_one_function(self) -> None:
        """A patch release's guard sees every push; the acceptance's stand-in
        sees every GitHub call. No ship.* helper that pushes is reachable."""
        for script in ("release.py", "release-line.py"):
            tree = ast.parse((SCRIPTS / script).read_text(encoding="utf-8"))
            owner: dict[int, str] = {}
            for function in ast.walk(tree):
                if isinstance(function, ast.FunctionDef):
                    for node in ast.walk(function):
                        owner[id(node)] = function.name
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in ("push", "gh"):
                    want = "push" if node.value == "push" else "run_gh"
                    self.assertEqual(
                        owner.get(id(node)),
                        want,
                        f"{script}:{node.lineno}: {node.value!r}",
                    )
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "ship"
                ):
                    self.assertNotIn(
                        node.attr,
                        ("publish_dist", "pin_in_agent", "ship", "wait_for_edge"),
                        f"{script}:{node.lineno}",
                    )


class PatchLineTests(unittest.TestCase):
    """open, pick and release.py on the bare repositories of the acceptance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = Path(tempfile.mkdtemp(prefix="ep-patch-test-"))
        cls.fx = fixture.Fixture(cls.scratch).build()

    @classmethod
    def tearDownClass(cls) -> None:
        fixture.remove_tree(cls.scratch)

    def ok(self, result: tuple[int, str], code: int = 0) -> str:
        self.assertEqual(result[0], code, result[1][-3000:])
        return result[1]

    def test_a_patch_never_pushes_main_dist_or_edge(self) -> None:
        fx = self.fx
        fx.reset_pushes()
        self.ok(fx.line("open", "v1.2"))
        fixes = [f"{n}:{fx.fix[n]}" for n in ("agent", "gateway", "workbench")]
        self.ok(fx.line("pick", "v1.2", *fixes))
        specs = fx.lines / "v1.2" / "specs"
        notes = specs / "docs" / "releases" / "v1.2.1.md"
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text("# Eugene Plexus v1.2.1\n\nA patch.\n", encoding="utf-8")
        self.ok(fx.release(specs, "v1.2.1", stop_after="tag"))
        pushed = {ref for _, ref, _, _ in fx.pushes()}
        self.assertEqual(
            pushed,
            {
                "refs/heads/release/v1.2",
                "refs/heads/release/v1.2-dist",
                "refs/heads/release-candidate/v1.2.1",
                "refs/tags/v1.2.1",
            },
        )
        # The candidate is v1.2.0's commits plus the picks.
        shell = fx.show("specs", "v1.2.1:scripts/install.sh")
        self.assertIn(f"PIN_CONTROL={fx.pins['control']}", shell)
        self.assertIn(f"PIN_SITE_HOST={fx.pins['site-host']}", shell)
        gateway = fx.rev("gateway", "release/v1.2")
        self.assertIn(f"PIN_GATEWAY={gateway}", shell)
        self.assertIn(
            f"(cherry picked from commit {fx.fix['gateway']})",
            fx.show("gateway", gateway),
        )
        self.assertNotIn(fx.later["gateway"], shell)

    def test_an_older_line_needs_security_and_a_new_dependency_needs_the_lock(
        self,
    ) -> None:
        fx = self.fx
        fx.reset_pushes()
        self.assertIn("--security", self.ok(fx.line("open", "v1.1"), 2))
        self.ok(fx.line("open", "v1.1", "--security"))
        self.ok(fx.line("pick", "v1.1", f"gateway:{fx.feature['gateway']}"))
        specs = fx.lines / "v1.1" / "specs"
        self.assertIn("--security", self.ok(fx.release(specs, "v1.1.1"), 2))
        out = self.ok(
            fx.release(specs, "v1.1.1", "--security", stop_after="candidate"), 2
        )
        self.assertRegex(out, "gateway.*--resolve")
        self.assertEqual(
            {ref for _, ref, _, _ in fx.pushes()}, {"refs/heads/release/v1.1"}
        )


if __name__ == "__main__":
    unittest.main()
