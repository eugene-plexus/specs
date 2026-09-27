"""In-app updates sabotage pass: put each hole back and prove a check notices.

2026-09-27: each node checks its channel for a newer version and can
install it from the app (docs/design/in-app-updates.md).

Restores from a COPY, never `git checkout --`, and opens with a baseline
assertion that every gate passes unsabotaged (memory:
`sabotage-runs-restore-from-a-copy`).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
INFO = ("agent", "src/eugene_plexus_agent/install_info.py")
CHECK = ("agent", "src/eugene_plexus_agent/updates.py")
APPLY = ("agent", "src/eugene_plexus_agent/update_apply.py")
ROUTES = ("agent", "src/eugene_plexus_agent/routes/updates.py")
NODE = ("agent", "src/eugene_plexus_agent/routes/node.py")
PS1 = ("agent", "src/eugene_plexus_agent/update_templates/run-update.ps1.template")
SH = ("agent", "src/eugene_plexus_agent/update_templates/run-update.sh.template")
UI_UPDATES = ("ui", "src/lib/updates.ts")
UI_CARD = ("ui", "src/components/NodeUpdateCard.tsx")
UI_HOOK = ("ui", "src/lib/useNodeUpdates.ts")
UI_ISSUES = ("ui", "src/lib/issues.ts")
TIMEOUT = 900

SABOTAGES: list[tuple[str, tuple[str, str], str, str]] = [
    # --- what is installed -----------------------------------------------------
    (
        "a development checkout reads as a stamped commit",
        INFO,
        "    if _FULL_COMMIT.fullmatch(value):\n",
        "    if value:\n",
    ),
    (
        "a package with no stamp reads as stamped",
        INFO,
        "        # Installed before components recorded their commit.\n"
        "        return InstalledComponentState.unrecorded, None\n",
        "        return InstalledComponentState.stamped, None\n",
    ),
    (
        "a container is not recognised",
        INFO,
        "    if container() is not None:\n        return InstallMechanism.container\n",
        "",
    ),
    # --- the channels ----------------------------------------------------------
    (
        "a commit whose container build failed is offered",
        CHECK,
        '        passed = all(r.get("conclusion") == "success" for r in commit_runs)\n',
        "        passed = True\n",
    ),
    (
        "a commit with no CI is offered",
        CHECK,
        '        has_ci = any(r.get("name") == "CI" for r in commit_runs)\n',
        "        has_ci = True\n",
    ),
    (
        "the pins are read from main, not from the commit offered",
        CHECK,
        '        pins = parse_pins(_get_text(get, f"{RAW}/{sha}/scripts/install.sh"))\n',
        '        pins = parse_pins(_get_text(get, f"{RAW}/main/scripts/install.sh"))\n',
    ),
    (
        "an installer that pins too little is compared anyway",
        CHECK,
        "    if missing:\n        raise CheckFailed(\n",
        "    if False:\n        raise CheckFailed(\n",
    ),
    (
        "a draft counts as a release",
        CHECK,
        '        and not r.get("draft")\n',
        "",
    ),
    (
        "releases are not newest first",
        CHECK,
        '    published.sort(key=lambda r: str(r.get("published_at") or ""), reverse=True)\n',
        "",
    ),
    (
        "an unrecorded component is not behind",
        CHECK,
        "    return [name for name in COMPONENT_NAMES if have.get(name) != target.components.get(name)]\n",
        "    return [\n        name\n        for name in COMPONENT_NAMES\n"
        "        if have.get(name) is not None and have.get(name) != target.components.get(name)\n    ]\n",
    ),
    (
        "a container's own tag is ignored",
        CHECK,
        "            (UpdateChannel.releases if _TAG.match(tag) else UpdateChannel.edge),\n",
        "            UpdateChannel.edge,\n",
    ),
    (
        "a release install is not recognised as one",
        CHECK,
        "            return UpdateChannel.releases, UpdateChannelSource.inferred\n    return UpdateChannel.edge",
        "            pass\n    return UpdateChannel.edge",
    ),
    (
        "a failed check forgets what the last one found",
        CHECK,
        "                result.newest = previous.newest\n",
        "                pass\n",
    ),
    (
        "a development checkout is offered an update",
        CHECK,
        "            available=bool(stale) and not install.development,\n",
        "            available=bool(stale),\n",
    ),
    # --- what a person is told -------------------------------------------------
    (
        "a container is told it can update itself",
        APPLY,
        "    if mechanism is InstallMechanism.container:\n        return UpdateApply(\n"
        "            possible=False,\n",
        "    if mechanism is InstallMechanism.container:\n        return UpdateApply(\n"
        "            possible=True,\n",
    ),
    (
        "a release container is told to re-pull the tag it has",
        APPLY,
        '    new_image = f"{repo}:{release}" if pinned else image\n',
        "    new_image = image\n",
    ),
    (
        "Unraid is given general Docker words",
        APPLY,
        '    if container.host == "unraid":\n',
        '    if container.host == "unraid-never":\n',
    ),
    (
        "a system install without its root unit is told it can update",
        APPLY,
        "        if system_unit_ready:\n            return UpdateApply(possible=True)\n",
        "        return UpdateApply(possible=True)\n",
    ),
    # --- the scripts -----------------------------------------------------------
    (
        "a per-user Windows install is updated as a service",
        APPLY,
        '    flags = ["-Update"] if service else ["-NoService", "-Update"]\n',
        '    flags = ["-Update"]\n',
    ),
    (
        "a quote in a folder name is not doubled",
        APPLY,
        """    return "'" + value.replace("'", "''") + "'"\n""",
        """    return "'" + value + "'"\n""",
    ),
    (
        "PowerShell splits a folder name with a space in it (found by running it)",
        PS1,
        "$argLine = ($argList | ForEach-Object { '\"' + ($_ -replace '\"', '\\\"') + '\"' }) -join ' '\n",
        "$argLine = $argList\n",
    ),
    (
        "the Windows script leaves the running record behind",
        PS1,
        "Remove-Item -LiteralPath (Join-Path $dir 'running.json') -Force -ErrorAction SilentlyContinue\n",
        "",
    ),
    (
        "the Linux script writes a quote into its record unescaped",
        SH,
        """esc() { printf '%s' "$1" | sed 's/\\\\/\\\\\\\\/g; s/"/\\\\"/g' | tr -d '\\000-\\037'; }\n""",
        """esc() { printf '%s' "$1"; }\n""",
    ),
    # --- starting one ----------------------------------------------------------
    (
        "the service's update task does not run as SYSTEM",
        APPLY,
        '            create += ["/RU", "SYSTEM", "/RL", "HIGHEST"]\n',
        "            pass\n",
    ),
    (
        "a release installer is run without checking its checksum",
        APPLY,
        "    if sha256 is not None:\n        digest",
        "    if False:\n        digest",
    ),
    (
        "a task that could not be registered leaves a running record",
        APPLY,
        "        if proc.returncode != 0:\n            (directory / RUNNING_FILE).unlink(missing_ok=True)\n"
        '            raise _failed("registering the update task", proc)\n',
        "        if proc.returncode != 0:\n"
        '            raise _failed("registering the update task", proc)\n',
    ),
    (
        "a system install downloads the installer for root to run",
        APPLY,
        "        # The ONLY thing this account hands root: which release or commit.\n",
        '        _download(target.installers["install.sh"].url, None, directory / "install.sh", get)\n'
        "        # The ONLY thing this account hands root: which release or commit.\n",
    ),
    (
        "an update that never reported back still reads as running",
        APPLY,
        "    if age > RUNNING_EXPIRES_SECONDS:\n        return None\n    return run\n",
        "    return run\n",
    ),
    # --- the routes ------------------------------------------------------------
    (
        "an update installs whatever the caller names",
        ROUTES,
        "    if body.target != target.ref or not valid_ref(body.target):\n",
        "    if not valid_ref(body.target):\n",
    ),
    (
        "a container is started anyway",
        ROUTES,
        "    if not view.apply.possible:\n",
        "    if False:\n",
    ),
    (
        "an install already up to date is updated again",
        ROUTES,
        "    if not view.available:\n",
        "    if False:\n",
    ),
    (
        "GET /v1/node says nothing about the version",
        NODE,
        "    identity.install, identity.update = await asyncio.to_thread(node_update_view, request)\n",
        "",
    ),
    # --- the UI ------------------------------------------------------------
    (
        "an update in progress is not shown as one",
        UI_UPDATES,
        "  if (update.running) {\n",
        "  if (false) {\n",
    ),
    (
        "a container is offered the Update button",
        UI_UPDATES,
        "    if (!update.apply.possible) {\n",
        "    if (false) {\n",
    ),
    (
        "the button sends something other than what the machine found",
        UI_UPDATES,
        "      target: update.newest?.ref ?? null,\n",
        "      target: update.newest?.release ?? null,\n",
    ),
    (
        "a failed update's own words are dropped",
        UI_UPDATES,
        '  const failed = last?.outcome === "failed" ? last : null;\n',
        "  const failed = null as UpdateRun | null;\n",
    ),
    (
        "a development checkout is offered an update in the page",
        UI_UPDATES,
        "  if (identity.install?.development) {\n",
        "  if (false) {\n",
    ),
    (
        "a machine from before updates is not told how to get them",
        UI_UPDATES,
        '      steps: [{ text: "On that machine, run:", command: installerCommand(identity.os) }],\n',
        "      steps: [],\n",
    ),
    (
        "Update does not say what it costs before it runs",
        UI_CARD,
        "              prompt={`${name} restarts, and the models on it stop for a minute or two.`}\n",
        "",
    ),
    (
        "the update is sent to this machine instead of the one on the card",
        UI_CARD,
        '      await api.post(target, "/v1/node/update", { target: view.target });\n',
        '      await api.post("agent", "/v1/node/update", { target: view.target });\n',
    ),
    (
        "every machine is read as another machine, this one included",
        UI_HOOK,
        "        const target = targetFor(name, localName);\n",
        "        const target = targetFor(name, null);\n",
    ),
    (
        "a machine that is behind is not listed",
        UI_ISSUES,
        "  issues.push(...updates, ...(updates.length === 0 ? versionsDifferIssues(sources.perNode) : []));\n",
        "  issues.push(...(updates.length === 0 ? versionsDifferIssues(sources.perNode) : []));\n",
    ),
    (
        "versions differ is said beside a machine that is simply behind",
        UI_ISSUES,
        "  issues.push(...updates, ...(updates.length === 0 ? versionsDifferIssues(sources.perNode) : []));\n",
        "  issues.push(...updates, ...versionsDifferIssues(sources.perNode));\n",
    ),
    (
        "a failed update is listed as merely available",
        UI_ISSUES,
        '  if (last?.outcome === "failed" && update.available) {\n',
        "  if (false) {\n",
    ),
]

FILES = sorted({target for _, target, _, _ in SABOTAGES})


def run(repo: str) -> tuple[int, str]:
    if repo == "ui":
        argv = ["npx.cmd", "vitest", "run", "src/lib/updates", "src/lib/issues", "src/app/nodes"]
    else:
        py = ROOT / repo / ".venv" / "Scripts" / "python.exe"
        argv = [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
        argv += ["tests/test_updates.py", "tests/test_build_stamp.py", "tests/test_config.py"]
    try:
        done = subprocess.run(
            argv,
            cwd=ROOT / repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    only = sys.argv[1:]
    sabotages = [s for s in SABOTAGES if not only or any(o in s[0] for o in only)]
    repos = sorted({repo for _, (repo, _), _, _ in sabotages})
    backup = Path(tempfile.mkdtemp(prefix="updates-sabotage-"))
    for repo, relative in FILES:
        destination = backup / repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")
    for repo in repos:
        code, out = run(repo)
        print(f"[baseline {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, (repo, relative), old, new in sabotages:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8", newline="").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="").write(source.replace(old, new, 1))
        try:
            code, _ = run(repo)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(sabotages)} sabotages")
    for repo in repos:
        code, out = run(repo)
        print(f"[restored {repo}] {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
