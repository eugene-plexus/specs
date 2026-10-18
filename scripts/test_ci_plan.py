from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ci_plan import CHECKS, COMPONENTS, plan


class PlanTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
