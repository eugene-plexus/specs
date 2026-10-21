from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml
from ci_plan import CHECKS, OUTPUTS, REF_INPUTS

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"


def workflow(name: str) -> dict:
    return yaml.load(
        (WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )


class WiringTests(unittest.TestCase):
    def test_container_checks_install_yaml_in_the_selected_interpreter(self) -> None:
        steps = workflow("container.yml")["jobs"]["build-verify-publish"]["steps"]
        setup = next(
            i for i, step in enumerate(steps) if "setup-python@" in step.get("uses", "")
        )
        install = next(
            i
            for i, step in enumerate(steps)
            if "python -m pip install PyYAML==6.0.3" in step.get("run", "")
        )
        acceptance = next(
            i
            for i, step in enumerate(steps)
            if "compose-acceptance.sh" in step.get("run", "")
        )
        self.assertLess(setup, install)
        self.assertLess(install, acceptance)

    def test_release_candidate_inline_imports_resolve(self) -> None:
        steps = workflow("release-qualification.yml")["jobs"]["candidate"]["steps"]
        script = next(step["run"] for step in steps if step.get("id") == "pins")
        imports = script.split("root = Path.cwd()", 1)[0]
        subprocess.run(
            [sys.executable, "-c", imports], cwd=WORKFLOWS.parent.parent, check=True
        )

    def test_branch_pushes_run_ci_and_main_pushes_are_never_cancelled(self) -> None:
        ci = workflow("ci.yml")
        self.assertEqual(ci["on"]["push"]["branches"], ["**", "!edge", "!dependabot/**"])
        self.assertEqual(ci["on"]["pull_request"]["branches"], ["main"])
        self.assertTrue(ci["on"]["schedule"])
        group = ci["concurrency"]["group"]
        cancel = ci["concurrency"]["cancel-in-progress"]
        # Main's pushes each get a group of their own; others keep the old group.
        self.assertTrue(
            group.startswith(
                "ci-${{ github.repository }}-${{ github.event_name }}-${{ github.ref }}"
            )
        )
        self.assertIn(
            "github.event_name == 'push' && github.ref == 'refs/heads/main' && "
            "format('-{0}', github.sha)",
            group,
        )
        self.assertIn("github.ref != 'refs/heads/main'", cancel)
        self.assertIn("github.event_name == 'pull_request'", cancel)
        self.assertNotIn("schedule", cancel)
        self.assertNotIn("workflow_dispatch", cancel)
        macos = workflow("macos-push.yml")["concurrency"]
        self.assertIn("github.sha", macos["group"])
        self.assertEqual(macos["cancel-in-progress"], "false")

    def test_only_a_specs_branch_push_resolves_component_branches(self) -> None:
        select = next(
            step
            for step in workflow("ci.yml")["jobs"]["plan"]["steps"]
            if step.get("id") == "select"
        )
        self.assertEqual(
            select["env"]["CI_BRANCH"],
            "${{ github.repository == 'eugene-plexus/specs' && github.event_name == 'push' "
            "&& github.ref != 'refs/heads/main' && github.ref_name || '' }}",
        )
        # Main pushes and PRs keep their base; a dispatch may give one.
        self.assertEqual(
            select["env"]["CI_BASE"],
            "${{ github.event.before || github.event.pull_request.base.sha || inputs.base }}",
        )
        for name in REF_INPUTS:
            self.assertEqual(select["env"][f"{name.upper()}_REF"], f"${{{{ inputs.{name}_ref }}}}")

    def test_every_job_tests_the_planned_component_refs(self) -> None:
        ci = workflow("ci.yml")
        text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        jobs_text = text.split("\n  s10-instruments:\n", 1)[1]
        for name in REF_INPUTS:
            with self.subTest(ref=name):
                self.assertNotIn(f"inputs.{name}_ref", jobs_text)
        for job in ci["jobs"].values():
            for step in job.get("steps", []):
                repository = step.get("with", {}).get("repository", "")
                component = repository.removeprefix("eugene-plexus/").replace("-", "_")
                if component in REF_INPUTS:
                    self.assertIn(f"needs.plan.outputs.{component}_ref", step["with"]["ref"])

    def test_planner_outputs_and_scoped_jobs_are_connected(self) -> None:
        jobs = workflow("ci.yml")["jobs"]
        self.assertEqual(set(jobs["plan"]["outputs"]), set(OUTPUTS))
        self.assertLessEqual(set(CHECKS), set(OUTPUTS))
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
        self.assertEqual(
            publisher["on"]["workflow_run"]["workflows"], ["CI", "Container image"]
        )
        self.assertEqual(publisher["concurrency"]["cancel-in-progress"], "false")
        checkout = publisher["jobs"]["publish"]["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "main")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        build = workflow("container.yml")["jobs"]["build-verify-publish"]
        tagging = next(
            step["run"] for step in build["steps"] if step.get("id") == "push"
        )
        self.assertNotIn('"$IMAGE:edge"', tagging)
        self.assertNotIn('"$IMAGE:$RELEASE_TAG"', tagging)

    def test_release_cannot_publish_by_rebuilding_or_without_qualification(
        self,
    ) -> None:
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

    def test_qualification_runs_before_the_tag_and_a_rehearsal_earns_no_receipt(
        self,
    ) -> None:
        qualification = workflow("release-qualification.yml")
        inputs = qualification["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["release_tag"]["required"], "false")
        self.assertTrue(qualification["on"]["schedule"])
        self.assertEqual(qualification["jobs"]["receipt"]["if"], "inputs.release_tag")
        script = next(
            step["run"]
            for step in qualification["jobs"]["candidate"]["steps"]
            if step.get("id") == "pins"
        )
        self.assertIn("if tagged and tagged != commit", script)
        self.assertIn("acceptance_digest(", script.split("else:", 1)[0])
        # The candidate image is built from the qualified commit, not a tag ref.
        container = workflow("container.yml")
        for job in ("coverage", "build-verify-publish"):
            with self.subTest(job=job):
                self.assertEqual(
                    container["jobs"][job]["steps"][0]["with"]["ref"], "${{ github.sha }}"
                )
        self.assertIn("inputs.profile && github.run_id", container["concurrency"]["group"])
        # Publication still needs the tag, checked out, at the qualified inputs.
        promote = container["jobs"]["promote-release"]["steps"][0]
        self.assertEqual(promote["with"]["ref"], "${{ inputs.release_tag }}")

    def test_nested_acceptance_runs_once_and_metadata_can_skip_container_build(
        self,
    ) -> None:
        for name in ("a4-macos.yml", "c1-app-accounts.yml", "c4-open-webui.yml"):
            self.assertNotIn("push", workflow(name)["on"])
        # macOS on a push runs beside CI, not in it, so Edge does not wait for it.
        self.assertIn(
            "github.event_name != 'push'", workflow("ci.yml")["jobs"]["macos"]["if"]
        )
        pushed = workflow("macos-push.yml")
        self.assertIn("push", pushed["on"])
        self.assertEqual(
            pushed["jobs"]["macos"]["uses"], "./.github/workflows/a4-macos.yml"
        )
        self.assertNotIn(
            "macOS after push", workflow("edge.yml")["on"]["workflow_run"]["workflows"]
        )
        jobs = workflow("container.yml")["jobs"]
        self.assertEqual(jobs["build-verify-publish"]["needs"], "coverage")
        self.assertIn(
            "needs.coverage.outputs.container", jobs["build-verify-publish"]["if"]
        )

    def test_release_browser_checks_use_shipped_not_rebuilt_static_files(self) -> None:
        steps = workflow("release-qualification.yml")["jobs"]["components"]["steps"]
        script = next(
            step["run"]
            for step in steps
            if step.get("name", "").startswith("Console regression")
        )
        self.assertNotIn("build:python", script)
        browser_commands = [
            line for line in script.splitlines() if "browser-acceptance.mjs" in line
        ]
        self.assertEqual(len(browser_commands), 5)
        self.assertTrue(
            all("python/eugene_plexus_ui/static" in line for line in browser_commands)
        )


if __name__ == "__main__":
    unittest.main()
