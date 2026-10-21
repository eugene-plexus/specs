from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ci_plan import CHECKS, COMPONENTS, REF_INPUTS, branch_base, plan, resolve_refs


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ep-ci-plan-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.command("init", "-q")
        self.command("config", "user.name", "CI fixture")
        self.command("config", "user.email", "ci@example.invalid")
        self.command("config", "commit.gpgsign", "false")
        self.manifest = {"format": 1, "components": {name: "a" * 40 for name in COMPONENTS}}
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.write("scripts/install.sh", "PIN_AGENT=" + "a" * 40 + "\necho install\n")
        self.write("scripts/install.ps1", '  "agent" = "' + "a" * 40 + '"\nWrite-Output install\n')
        self.base = self.commit()

    def command(self, *arguments: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], text=True).strip()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def commit(self) -> str:
        self.command("add", ".")
        self.command("commit", "-qm", "Fixture", "--allow-empty")
        return self.command("rev-parse", "HEAD")

    def selected(self) -> dict[str, bool]:
        return plan(self.root, self.base, self.commit())


class PlanTests(Fixture):
    def test_documentation_does_not_run_runtime_checks(self) -> None:
        self.write("docs/acceptance/example.md", "Evidence, not a runtime input.\n")
        self.assertFalse(any(self.selected().values()))

    def test_manifest_whitespace_only_runs_integrity_checks(self) -> None:
        self.write("release/manifest.json", json.dumps(self.manifest, indent=2) + "\n")
        self.assertEqual(
            {name for name, enabled in self.selected().items() if enabled}, {"instruments"}
        )

    def test_ui_pin_needs_smoke_and_container_not_engine_matrix(self) -> None:
        self.manifest["components"]["ui"] = "b" * 40
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.assertEqual(
            {name for name, enabled in self.selected().items() if enabled},
            {"runtime", "instruments", "container"},
        )

    def test_agent_pin_selects_platform_boundaries(self) -> None:
        self.manifest["components"]["agent"] = "b" * 40
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.write("scripts/install.sh", "PIN_AGENT=" + "b" * 40 + "\necho install\n")
        self.write("scripts/install.ps1", '  "agent" = "' + "b" * 40 + '"\nWrite-Output install\n')
        selected = self.selected()
        self.assertTrue(
            all(
                selected[name] for name in ("runtime", "launch", "installers", "macos", "container")
            )
        )
        self.assertFalse(selected["full"])

    def test_installer_logic_cannot_hide_behind_a_pin_change(self) -> None:
        self.manifest["components"]["agent"] = "b" * 40
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.write("scripts/install.sh", "PIN_AGENT=" + "b" * 40 + "\necho CHANGED\n")
        self.assertTrue(all(self.selected().values()))

    def test_unrecognized_inputs_fall_back_to_full(self) -> None:
        for name in (
            "release/requirements.lock",
            "scripts/new-check.py",
            "scripts/fixtures/prompt.md",
            ".gitattributes",
            ".github/workflows/new.yml",
            "platform/manifest.json",
            "openapi/agent.yaml",
        ):
            with self.subTest(name=name):
                base = self.command("rev-parse", "HEAD")
                self.write(name, "changed\n")
                self.assertTrue(all(plan(self.root, base, self.commit()).values()))

    def test_nested_installer_pin_change_is_not_hidden_by_a_ui_pin(self) -> None:
        self.write(
            "scripts/install.sh",
            "PIN_AGENT=" + "a" * 40 + "\nPIN_SITE_HOST=" + "a" * 40 + "\necho install\n",
        )
        base = self.commit()
        self.manifest["components"]["ui"] = "b" * 40
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.write(
            "scripts/install.sh",
            "PIN_AGENT=" + "a" * 40 + "\nPIN_SITE_HOST=" + "c" * 40 + "\necho install\n",
        )
        self.assertTrue(all(plan(self.root, base, self.commit()).values()))

    def test_unknown_history_and_explicit_full_cannot_skip_checks(self) -> None:
        for base in ("", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                self.assertTrue(all(plan(self.root, base, "HEAD").values()))
        self.assertEqual(plan(self.root, self.base, "HEAD", full=True), dict.fromkeys(CHECKS, True))

    def test_dependency_settings_and_unknown_components_require_full(self) -> None:
        self.manifest["python"] = "3.13"
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.assertTrue(all(self.selected().values()))
        self.manifest["components"]["new-component"] = "b" * 40
        self.write("release/manifest.json", json.dumps(self.manifest))
        self.assertTrue(all(self.selected().values()))


class BranchTests(Fixture):
    """A branch push: planned from its merge-base, with component candidates."""

    def branch(self) -> tuple[str, str]:
        """Main moves on with a script change after the branch leaves it."""
        self.command("checkout", "-q", "-b", "row")
        self.write("docs/design/row.md", "The row's design.\n")
        head = self.commit()
        self.command("checkout", "-q", "-")
        self.write("scripts/new-check.py", "print('main moved')\n")
        main = self.commit()
        self.command("checkout", "-q", "row")
        return head, main

    def test_a_docs_branch_is_planned_from_its_merge_base_not_from_main(self) -> None:
        head, main = self.branch()
        base = branch_base(self.root, head, main)
        self.assertEqual(base, self.base)
        self.assertFalse(any(plan(self.root, base, head).values()))
        # Against main's head the branch would seem to undo main's script.
        self.assertTrue(all(plan(self.root, main, head).values()))

    def test_unknown_merge_base_means_full(self) -> None:
        self.assertEqual(branch_base(self.root, "HEAD", "no-such-ref"), "")
        self.assertTrue(all(plan(self.root, "", "HEAD").values()))

    def test_a_component_candidate_selects_its_pin_checks(self) -> None:
        head = self.commit()
        selected = plan(self.root, self.base, head, candidates=frozenset({"agent"}))
        self.assertEqual(
            {name for name, enabled in selected.items() if enabled},
            {"runtime", "instruments", "container", "launch", "installers", "macos"},
        )
        selected = plan(self.root, self.base, head, candidates=frozenset({"control"}))
        self.assertEqual(
            {name for name, enabled in selected.items() if enabled},
            {"runtime", "instruments", "container"},
        )

    def test_a_site_host_candidate_selects_everything(self) -> None:
        head = self.commit()
        self.assertTrue(
            all(plan(self.root, self.base, head, candidates=frozenset({"site-host"})).values())
        )

    def test_a_candidate_cannot_excuse_installer_pins_the_manifest_did_not_move(self) -> None:
        self.write("scripts/install.sh", "PIN_AGENT=" + "b" * 40 + "\necho install\n")
        head = self.commit()
        self.assertTrue(
            all(plan(self.root, self.base, head, candidates=frozenset({"agent"})).values())
        )

    def test_refs_come_from_inputs_first_then_same_named_branches(self) -> None:
        branches = {"agent": "a" * 40, "site-host": "c" * 40}
        asked = []

        def lookup(repository: str, branch: str) -> str | None:
            asked.append((repository, branch))
            return branches.get(repository)

        refs = resolve_refs("row", {"agent": "b" * 40}, lookup)
        self.assertEqual(refs, {"agent": "b" * 40, "site_host": "c" * 40})
        self.assertNotIn(("agent", "row"), asked)
        self.assertEqual(len(asked), len(REF_INPUTS) - 1)

    def test_main_pushes_and_scheduled_runs_look_up_no_branches(self) -> None:
        def lookup(repository: str, branch: str) -> str | None:
            raise AssertionError("no branch lookup without a branch")

        self.assertEqual(resolve_refs("", {}, lookup), {})
        self.assertEqual(resolve_refs("", {"gateway": "d" * 40}, lookup), {"gateway": "d" * 40})


if __name__ == "__main__":
    unittest.main()
