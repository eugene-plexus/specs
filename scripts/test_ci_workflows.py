from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

import edge_marker
import ship
import yaml
from ci_plan import CHECKS, OUTPUTS, REF_INPUTS

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"

# Pinned integration as it stood unsplit (main at 049a602): 15 install steps,
# then these acceptance steps, by script (or step name), with the profile
# each runs in ("every" profile, "full" only, or "always-full": even after a
# failure, full only) and its systems. A change here is a gate change.
SETUP_STEPS = 15
FULL, EVERY = "full", "every"
PINNED_STEPS = {
    "row65-ollama-protocol.py": (EVERY, "both"),
    "run-operations-checks.py": (FULL, "both"),
    "s10-starter-check.py": (FULL, "both"),
    "r7-signing-checks.py": (EVERY, "both"),
    "test_s8_harness.py": (EVERY, "both"),
    "harness-acceptance.py": (EVERY, "both"),
    "r7-rotation-acceptance.py": (FULL, "both"),
    "row3-per-node-keys-acceptance.py": (EVERY, "both"),
    # Row 70 (2026-10-21): group policies at the root and through an agent.
    "row70-group-policy-acceptance.py": (EVERY, "both"),
    "r8-profile-acceptance.py": (EVERY, "both"),
    "ls1-eligibility-acceptance.py": (EVERY, "both"),
    "ls2-discover-acceptance.py": (FULL, "both"),
    "ls3-prepared-acceptance.py": (FULL, "both"),
    "ls4-sources-acceptance.py": (FULL, "both"),
    "ls5-preparation-checks.py": (FULL, "both"),
    "ls5-preparation-acceptance.py": (FULL, "both"),
    "runtime-stop-acceptance.py": (EVERY, "both"),
    "ls6-fit-acceptance.py": (FULL, "both"),
    "ls7-copy-acceptance.py": (FULL, "both"),
    "ls7b-facts-acceptance.py": (FULL, "both"),
    "ls8-delete-acceptance.py": (FULL, "both"),
    "a3-client-keys-acceptance.py": (FULL, "both"),
    "a5-scoped-keys-acceptance.py": (FULL, "both"),
    "a6-local-only-acceptance.py": (EVERY, "both"),
    "a6b-failover-acceptance.py": (FULL, "both"),
    "p2-media-acceptance.py": (FULL, "both"),
    "p3-audio-checks.py": (FULL, "both"),
    "p3-audio-acceptance.py": (FULL, "both"),
    "p4-images-acceptance.py": (FULL, "both"),
    "p5-videos-acceptance.py": (FULL, "both"),
    "p6-acceptance.py": (FULL, "both"),
    "p8-search-acceptance.py": (FULL, "both"),
    "google-search-acceptance.py": (FULL, "both"),
    "gemini-acceptance.py": (FULL, "both"),
    "tools-assumed-acceptance.py": (FULL, "both"),
    "genui-inference-acceptance.py": (FULL, "both"),
    "genui-inference-sabotage.py": (FULL, "both"),
    "Keep UI inference prerequisite evidence": ("always-full", "both"),
    "c2-sign-in-acceptance.py": (EVERY, "both"),
    "c3-workbench-acceptance.py": (EVERY, "both"),
    "row7-person-removal-acceptance.py": (EVERY, "both"),
    "update-all-acceptance.py": (FULL, "both"),
    "standby-acceptance.py": (FULL, "both"),
    "job-sites-acceptance.py": (FULL, "linux"),
    "a7-recovery-checks.py": (FULL, "both"),
    "r8-profile-checks.py": (FULL, "both"),
}


def workflow(name: str) -> dict:
    return yaml.load(
        (WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )


def can_run_on_windows(job: dict) -> bool:
    """True when a job may run on a Windows runner (a matrix it cannot read counts)."""
    runs_on = job.get("runs-on", "")
    if isinstance(runs_on, str) and "matrix." not in runs_on:
        return "windows" in runs_on
    matrix = (job.get("strategy") or {}).get("matrix")
    if not isinstance(matrix, dict):
        return True
    names = matrix.get("os") or []
    if isinstance(names, str):
        return "windows" in names
    names = [*names, *(entry.get("os", "") for entry in matrix.get("include") or [])]
    return any("windows" in name for name in names)


class WiringTests(unittest.TestCase):
    def test_no_step_on_windows_runs_under_the_default_shell(self) -> None:
        """The runner's default pwsh fails a step only on the exit code of its last
        native command: a failing command followed by a passing one is green, and
        the agent's Windows pytest step once passed with 2 failed tests (W0.13).
        Every run step of a job that can run on Windows names its shell, as a
        step, job or workflow default."""
        default = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            document = workflow(path.name)
            workflow_shell = ((document.get("defaults") or {}).get("run") or {}).get("shell")
            for job_id, job in (document.get("jobs") or {}).items():
                if not can_run_on_windows(job):
                    continue
                job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell")
                for number, step in enumerate(job.get("steps") or [], 1):
                    if "run" in step and not (step.get("shell") or job_shell or workflow_shell):
                        default.append(f"{path.name} {job_id} step {number}: {step.get('name', '')}")
        self.assertEqual(default, [])

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
        # Dispatches, the weekly run and calls (which carry the caller's event
        # and run ID) each get a group of their own: none waits or is replaced.
        self.assertIn(
            "github.event_name != 'push' && github.event_name != 'pull_request' && "
            "format('-run-{0}', github.run_id)",
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

    def test_durable_run_protocol_uses_the_planned_library_ref(self) -> None:
        step = next(
            step
            for step in workflow("ci.yml")["jobs"]["r7-signing"]["steps"]
            if step.get("name") == "Verify durable run protocol when both consumers provide it"
        )
        self.assertEqual(step["env"]["LIBRARY_REF"], "${{ needs.plan.outputs.library_ref }}")
        self.assertIn('"specs/scripts/run-operations-checks.py"', step["run"])

    def test_every_pinned_integration_step_runs_once_per_system(self) -> None:
        job = workflow("ci.yml")["jobs"]["r7-signing"]
        legs = job["strategy"]["matrix"]["include"]
        systems = {"ubuntu-latest": "L", "windows-latest": "W"}
        self.assertEqual(
            sorted((leg["os"], leg["shard"]) for leg in legs),
            sorted(
                (system, f"{letter}{part}")
                for system, letter in systems.items()
                for part in "123"
            ),
        )
        clause = re.compile(r"matrix\.shard == '([LW][123])'")
        steps = job["steps"]
        first = next(i for i, step in enumerate(steps) if "matrix.shard" in step.get("if", ""))
        self.assertEqual(steps[first - 1]["name"], "Check installed dependency consistency")
        # Every part installs the same components: no setup step is split.
        self.assertEqual(first, SETUP_STEPS)
        for step in steps[:first]:
            self.assertNotIn("matrix.shard", step.get("if", ""))
        found: dict[str, tuple[str, str]] = {}
        for step in steps[first:]:
            with self.subTest(step=step["name"]):
                condition = step.get("if", "")
                parts = clause.findall(condition)
                linux = [part for part in parts if part.startswith("L")]
                windows = [part for part in parts if part.startswith("W")]
                self.assertEqual(len(linux), 1)
                self.assertLessEqual(len(windows), 1)
                # The part clause is ANDed onto a condition the unsplit job had.
                bare = " || ".join(f"matrix.shard == '{part}'" for part in linux + windows)
                part = f"({bare})" if windows else bare
                full = "needs.plan.outputs.full == 'true'"
                gates = {
                    bare: "every",
                    f"{part} && {full}": "full",
                    f"always() && {part} && {full}": "always-full",
                    f"{part} && runner.os == 'Linux' && {full}": "full",
                }
                self.assertIn(condition, gates)
                script = re.search(r"specs/scripts/([\w.-]+\.py)", step.get("run", ""))
                key = script.group(1) if script else step["name"]
                self.assertNotIn(key, found)
                found[key] = (gates[condition], "both" if windows else "linux")
        # The unsplit job's steps, each with its profile and systems: dropping
        # a step, or moving it between profiles or systems, fails here.
        self.assertEqual(found, PINNED_STEPS)
        self.assertEqual(len(steps), SETUP_STEPS + len(PINNED_STEPS))

    def test_publish_edge_reads_aggregates_that_need_every_part(self) -> None:
        jobs = workflow("ci.yml")["jobs"]
        aggregate = jobs["pinned-integration"]
        self.assertEqual(aggregate["needs"], ["plan", "r7-signing"])
        self.assertEqual(
            aggregate["if"], "${{ !cancelled() && needs.plan.outputs.runtime == 'true' }}"
        )
        names = {
            aggregate["name"].replace("${{ matrix.os }}", system)
            for system in aggregate["strategy"]["matrix"]["os"]
        }
        self.assertEqual(names, set(edge_marker.RUNTIME_JOBS))
        check = aggregate["steps"][0]
        self.assertEqual(check["env"]["PARTS"], "${{ needs.r7-signing.result }}")
        self.assertIn('if [ "$PARTS" != success ]; then', check["run"])
        self.assertIn("exit 1", check["run"])
        # Every part's name falls under the prefix Publish Edge requires to pass.
        self.assertTrue(jobs["r7-signing"]["name"].startswith(edge_marker.RUNTIME_PREFIX))
        self.assertEqual(jobs["r7-signing"]["strategy"]["fail-fast"], "false")

    def test_a_reduced_run_on_main_needs_the_previous_push_to_have_passed(self) -> None:
        guard = workflow("ci.yml")["jobs"]["previous-push"]
        self.assertEqual(guard["needs"], "plan")
        self.assertEqual(
            guard["if"],
            "github.repository == 'eugene-plexus/specs' && github.event_name == 'push' "
            "&& github.ref == 'refs/heads/main' && needs.plan.outputs.full == 'false'",
        )
        self.assertEqual(guard["name"], ship.GUARD_JOB)
        step = guard["steps"][-1]
        self.assertEqual(step["env"]["PREVIOUS"], "${{ github.event.before }}")
        self.assertEqual(step["run"], 'python3 scripts/previous_push.py "$PREVIOUS"')
        self.assertGreater(int(guard["timeout-minutes"]), 55)
        checks = next(
            step["run"]
            for step in workflow("ci.yml")["jobs"]["plan"]["steps"]
            if step.get("name") == "Check CI planning"
        )
        self.assertIn("test_ship.py", checks)

    def test_no_ci_job_asks_for_more_than_its_callers_grant(self) -> None:
        # A called workflow's job asking for more than its caller grants fails
        # the caller at startup, even when the job is skipped (run 39627576506).
        # Release qualification and the components' Candidate integration grant
        # contents: read (and packages, which no CI job asks for).
        ci = workflow("ci.yml")
        self.assertEqual(ci["permissions"], {"contents": "read"})
        for name, job in ci["jobs"].items():
            with self.subTest(job=name):
                self.assertIn(job.get("permissions", {"contents": "read"}), [{"contents": "read"}])
        granted = workflow("release-qualification.yml")["permissions"]
        self.assertEqual(granted.get("contents"), "read")

    def test_the_branch_reaches_the_planner_as_one_argument(self) -> None:
        select = next(
            step
            for step in workflow("ci.yml")["jobs"]["plan"]["steps"]
            if step.get("id") == "select"
        )
        self.assertIn("command.append(f\"--branch={os.environ['CI_BRANCH']}\")", select["run"])

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

    def test_tool_picture_contract_runs_in_contract_validation(self) -> None:
        steps = workflow("ci.yml")["jobs"]["validate-openapi"]["steps"]
        self.assertIn(
            "python scripts/test_tool_pictures_contract.py",
            [step.get("run") for step in steps],
        )

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
