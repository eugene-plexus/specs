from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml
from ci_plan import CHECKS

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"


def workflow(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


class WiringTests(unittest.TestCase):
    def test_release_candidate_inline_imports_resolve(self) -> None:
        steps = workflow("release-qualification.yml")["jobs"]["candidate"]["steps"]
        script = next(step["run"] for step in steps if step.get("id") == "pins")
        imports = script.split("root = Path.cwd()", 1)[0]
        subprocess.run([sys.executable, "-c", imports], cwd=WORKFLOWS.parent.parent, check=True)

    def test_planner_outputs_and_scoped_jobs_are_connected(self) -> None:
        jobs = workflow("ci.yml")["jobs"]
        self.assertEqual(set(jobs["plan"]["outputs"]), set(CHECKS))
        for name, gate in {
            "r7-signing": "runtime",
            "r7-launch-boundary": "launch",
            "s10-instruments": "instruments",
            "posix-installers": "installers",
            "dev-tasks": "dev",
            "offline-removal": "uninstall",
            "validate-openapi": "contracts",
            "lint-openapi": "contracts",
            "macos": "macos",
        }.items():
            with self.subTest(job=name):
                self.assertEqual(jobs[name]["needs"], "plan")
                self.assertIn(f"needs.plan.outputs.{gate}", jobs[name]["if"])

    def test_reusable_workflows_accept_declared_inputs(self) -> None:
        for path in WORKFLOWS.glob("*.yml"):
            for name, job in workflow(path.name).get("jobs", {}).items():
                target = job.get("uses", "")
                if target.startswith("./.github/workflows/"):
                    with self.subTest(workflow=path.name, job=name):
                        called = workflow(Path(target).name)["on"]["workflow_call"]
                        self.assertLessEqual(
                            set(job.get("with", {})), set(called.get("inputs", {}))
                        )

    def test_only_publisher_moves_edge_and_publication_is_not_canceled(self) -> None:
        publisher = workflow("edge.yml")
        self.assertEqual(publisher["on"]["workflow_run"]["workflows"], ["CI", "Container image"])
        self.assertEqual(publisher["concurrency"]["cancel-in-progress"], "false")
        checkout = publisher["jobs"]["publish"]["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "main")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        build = workflow("container.yml")["jobs"]["build-verify-publish"]
        tagging = next(step["run"] for step in build["steps"] if step.get("id") == "push")
        self.assertNotIn('"$IMAGE:edge"', tagging)
        self.assertNotIn('"$IMAGE:$RELEASE_TAG"', tagging)

    def test_release_cannot_publish_by_rebuilding_or_without_qualification(self) -> None:
        jobs = workflow("container.yml")["jobs"]
        promotion = jobs["promote-release"]
        commands = "\n".join(step.get("run", "") for step in promotion["steps"])
        self.assertIn("python scripts/release_gate.py", commands)
        self.assertIn("--prefer-index=false", commands)
        self.assertNotIn("docker build ", commands)
        self.assertNotIn("compose-acceptance", commands)
        qualification = workflow("release-qualification.yml")["jobs"]
        self.assertEqual(qualification["integration"]["with"]["profile"], "full")
        self.assertEqual(qualification["container"]["with"]["publish"], "false")
        self.assertEqual(
            set(qualification["receipt"]["needs"]),
            {"candidate", "components", "integration", "container"},
        )

    def test_nested_acceptance_runs_once_and_metadata_can_skip_container_build(self) -> None:
        for name in ("a4-macos.yml", "c1-app-accounts.yml", "c4-open-webui.yml"):
            self.assertNotIn("push", workflow(name)["on"])
        jobs = workflow("container.yml")["jobs"]
        self.assertEqual(jobs["build-verify-publish"]["needs"], "coverage")
        self.assertIn("needs.coverage.outputs.container", jobs["build-verify-publish"]["if"])

    def test_release_browser_checks_use_shipped_not_rebuilt_static_files(self) -> None:
        steps = workflow("release-qualification.yml")["jobs"]["components"]["steps"]
        script = next(
            step["run"] for step in steps if step.get("name", "").startswith("Console regression")
        )
        self.assertNotIn("build:python", script)
        browser_commands = [
            line for line in script.splitlines() if "browser-acceptance.mjs" in line
        ]
        self.assertEqual(len(browser_commands), 5)
        self.assertTrue(all("python/eugene_plexus_ui/static" in line for line in browser_commands))


if __name__ == "__main__":
    unittest.main()
