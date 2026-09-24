"""Apps sabotage pass: put each finding back and prove a check notices.

Design: docs/design/apps-and-spokes.md. Restores from a COPY, never
`git checkout --`, and opens with a baseline assertion that the gate
passes unsabotaged (memory: `sabotage-runs-restore-from-a-copy`).

The properties are the ones the design rests on, and each sabotage is a
plausible wrong implementation rather than a random mutation:

* an app is handed **no hub credential** -- the wrong version reuses the
  agent's own environment, or a component's prefix;
* an unreadable `apps.yaml` costs **the apps and nothing else**;
* the key is minted with **the caller's** credential and **once**, and an
  uninstall whose revocation fails **removes nothing**;
* an app's settings are reached with **its admin token**, and a reset
  (`null`) reaches it as a reset;
* a package `python -m` cannot run is **refused at install**, and an
  install is **committed by its install.json** and nothing else.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
AGENT = "agent"
APPS = "src/eugene_plexus_agent/apps.py"
ROUTES = "src/eugene_plexus_agent/routes/apps.py"
HEALTH = "src/eugene_plexus_agent/routes/health.py"
NODE = "src/eugene_plexus_agent/routes/node.py"
FILES = (APPS, ROUTES, HEALTH, NODE)
GATE = ("tests/test_apps.py", "tests/test_config.py", "tests/test_health.py")
UNIT_TIMEOUT = 900

# (label, file, old, new)
SABOTAGES: list[tuple[str, str, str, str]] = [
    # --- no hub credential --------------------------------------------------
    (
        "an app inherits the agent's whole environment",
        APPS,
        "        self.admin_token = secrets.token_urlsafe(32)\n        env = child_environment()\n",
        "        self.admin_token = secrets.token_urlsafe(32)\n        env = dict(__import__('os').environ)\n",
    ),
    (
        "an app is planned with the gateway's prefix, so its bootstrap passes through",
        APPS,
        "        self.admin_token = secrets.token_urlsafe(32)\n        env = child_environment()\n",
        "        self.admin_token = secrets.token_urlsafe(32)\n"
        "        env = child_environment(component_prefix='EUGENE_PLEXUS_AGENT')\n",
    ),
    (
        "the admin token is minted once and reused across spawns",
        APPS,
        "        self.admin_token = secrets.token_urlsafe(32)\n",
        "        self.admin_token = self.admin_token or secrets.token_urlsafe(32)\n",
    ),
    (
        "the install tools run with the hub's variables in their environment",
        APPS,
        "        # the user's proxy, because a package index is egress.\n        env = child_environment()\n",
        "        # the user's proxy, because a package index is egress.\n"
        "        env = dict(__import__('os').environ)\n",
    ),
    # --- apps.yaml degrades alone -------------------------------------------
    (
        "an unreadable apps.yaml raises instead of degrading",
        APPS,
        "        try:\n            self.load()\n        except Exception as exc:\n            reason =",
        "        try:\n            self.load()\n        except ZeroDivisionError as exc:\n            reason =",
    ),
    (
        "healthz stays silent about an unreadable apps.yaml",
        HEALTH,
        "    if apps is not None and apps.store.degraded_reason:",
        "    if False:",
    ),
    # --- the catalogue and custom entries -----------------------------------
    (
        "an install is allowed on a node that has not enrolled",
        APPS,
        "        if not enrolled:",
        "        if False:",
    ),
    (
        "a custom app can be added with the expert switch off",
        ROUTES,
        "    if not _custom_allowed(request):\n        raise _problem(status.HTTP_403_FORBIDDEN, \"Custom apps are off\", _CUSTOM_OFF)\n    if manager.manifest(body.id)",
        "    if manager.manifest(body.id)",
    ),
    (
        "the installer's own uv is not looked for beside the install",
        APPS,
        '    beside = Path(sys.prefix).parent / "bin" / name',
        '    beside = Path(sys.prefix) / "nowhere" / name',
    ),
    # --- the key ------------------------------------------------------------
    (
        "a retry mints a second key nobody will revoke",
        ROUTES,
        "    if existing is not None and key_file.is_file():\n        return\n",
        "",
    ),
    (
        "the key is minted on the agent's own authority, not the caller's",
        ROUTES,
        '        ClientKeyCreateRequest(name=f"app:{app_id}@{node}"),\n'
        '        authorization=request.headers.get("authorization"),',
        '        ClientKeyCreateRequest(name=f"app:{app_id}@{node}"),\n        authorization=None,',
    ),
    (
        "a failed revocation is swallowed and the app removed anyway",
        ROUTES,
        "        if exc.status_code != status.HTTP_404_NOT_FOUND:\n            raise\n",
        "        pass\n",
    ),
    (
        "the app is removed before its key is revoked",
        ROUTES,
        "    await _revoke_key(request, manager, app_id)\n    await manager.uninstall(app_id, purge=purge)\n",
        "    await manager.uninstall(app_id, purge=purge)\n    await _revoke_key(request, manager, app_id)\n",
    ),
    # --- settings through the agent -----------------------------------------
    (
        "the operator's own bearer is forwarded to the app",
        ROUTES,
        '            headers={"Authorization": f"Bearer {token}"},',
        '            headers={"Authorization": request.headers.get("authorization", "")},',
    ),
    (
        "a reset (null) is dropped on the way to the app",
        ROUTES,
        'body.model_dump(mode="json"))',
        'body.model_dump(mode="json", exclude_none=True))',
    ),
    (
        "an app's malformed answer surfaces as this agent's 500",
        ROUTES,
        "    except ValidationError as exc:\n        record = _apps(request).store.get(app_id)",
        "    except ZeroDivisionError as exc:\n        record = _apps(request).store.get(app_id)",
    ),
    # --- install, update, stop ----------------------------------------------
    (
        "a package whose -m target has no __main__ passes verification",
        APPS,
        "    \"if spec.submodule_search_locations is not None and u.find_spec(name + '.__main__') is None:\\n\"",
        "    \"if False:\\n\"",
    ),
    (
        "an install is committed without its install.json",
        APPS,
        "        write_private(\n            target / INSTALL_METADATA,",
        "        (lambda *a, **k: None)(\n            target / INSTALL_METADATA,",
    ),
    (
        "a failed install leaves its half-built environment behind",
        APPS,
        "            progress.message = \"failed\"\n            if not committed:\n                _remove_quietly(target)",
        "            progress.message = \"failed\"\n            if not committed:\n                pass",
    ),
    (
        "an update forgets the version it replaced",
        APPS,
        "                    previous_version=(\n                        existing.version if existing.version != manifest.version else None\n                    ),",
        "                    previous_version=None,",
    ),
    (
        "old environments are never pruned",
        APPS,
        "            prune_versions(self.store, record.id, keep)",
        "            pass",
    ),
    (
        "boot starts an app the operator stopped",
        APPS,
        "            if not record.enabled:\n                continue\n",
        "",
    ),
    (
        "stop is not remembered across a restart",
        ROUTES,
        "    record.enabled = False\n    manager.store.put(record)\n",
        "    record.enabled = False\n",
    ),
    # --- reach --------------------------------------------------------------
    (
        "reach does not count an app's port",
        NODE,
        "        for record in manager.store.installed():\n            if not manager.supervisor.is_running(record.id):",
        "        for record in []:\n            if not manager.supervisor.is_running(record.id):",
    ),
]


def run_gate() -> tuple[int, str]:
    py = ROOT / AGENT / ".venv" / "Scripts" / "python.exe"
    try:
        done = subprocess.run(
            [str(py), "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *GATE],
            cwd=ROOT / AGENT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UNIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="apps-sabotage-"))
    for relative in FILES:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / AGENT / relative, destination)
    print(f"copy in {backup}\n")

    code, out = run_gate()
    print(f"[baseline] {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    print()

    caught = escaped = 0
    for label, relative, old, new in SABOTAGES:
        path = ROOT / AGENT / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate()
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    code, out = run_gate()
    print(f"[restored] {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
