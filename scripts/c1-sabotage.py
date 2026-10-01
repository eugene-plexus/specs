"""Sabotage pass for C1 (apps in accounts of their own; the log ingress).

Each sabotage puts one defect back into a component's working tree, runs
the tests that guard it, and requires them to FAIL. Restores are from byte
copies taken before the first edit, never `git checkout --`
(feedback: sabotage-runs-restore-from-a-copy), and the pass opens with a
baseline that must pass.

What only a runner proves -- that the account really cannot open
`node.yaml` -- is `c1-app-accounts-acceptance.py` on GitHub's Windows and
Ubuntu runners, which failed 14 checks on each before C1 and passes after.

    python scripts/c1-sabotage.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
CONTROL = ROOT / "control"
GATEWAY = ROOT / "gateway"
UI = ROOT / "ui"
A = AGENT / "src/eugene_plexus_agent"
INGRESS_ROUTE = A / "routes/log_ingress.py"
INGRESS = A / "log_ingress.py"
ACCOUNTS = A / "app_accounts.py"
LAUNCHER = A / "app_launcher.py"
APPS = A / "apps.py"
APPS_ROUTE = A / "routes/apps.py"
AGENT_LIMITS = A / "client_admission.py"
CONTROL_LIMITS = CONTROL / "src/eugene_plexus_control/client_admission.py"
GATEWAY_MODEL = GATEWAY / "src/eugene_plexus_gateway/_generated/client_key_models.py"
UI_APPS = UI / "src/app/apps/page.tsx"
UI_KEYS = UI / "src/components/home/ClientKeyLimitsEditor.tsx"


def python(repo: Path) -> Path:
    windows = repo / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else repo / ".venv" / "bin" / "python"


def pytest(repo: Path, *tests: str):
    return lambda: [str(python(repo)), "-m", "pytest", "-q", "-p", "no:warnings", "-p",
                    "no:cacheprovider", *tests]


RUNNERS = {
    AGENT: pytest(AGENT, "tests/test_app_accounts.py", "tests/test_log_ingress.py",
                  "tests/test_apps.py", "tests/test_client_admission.py"),
    CONTROL: pytest(CONTROL, "tests/test_client_admission.py"),
    GATEWAY: pytest(GATEWAY, "tests/test_admission.py"),
    UI: lambda: ["npx", "vitest", "run", "src/app/apps/page.test.tsx",
                 "src/components/home/ClientKeyLimitsEditor.test.tsx"],
}

SABOTAGES: list[tuple[str, Path, Path, str, str]] = [
    (
        "ingress: a key without writeLogs may send",
        AGENT, INGRESS_ROUTE,
        "    if not standing.may_write:\n",
        "    if False:\n",
    ),
    (
        "ingress: an operator session is taken as a sender",
        AGENT, INGRESS_ROUTE,
        "classes=(tokens.TYP_CLIENT,))",
        "classes=(tokens.TYP_CLIENT, tokens.TYP_SESSION))",
    ),
    (
        "ingress: no rate per key",
        AGENT, INGRESS_ROUTE,
        "        if wait is not None:\n",
        "        if False:\n",
    ),
    (
        "ingress: control characters in a record reach the log",
        AGENT, INGRESS,
        '        line = _CONTROL.sub(" ", line).rstrip()\n',
        "        line = line.rstrip()\n",
    ),
    (
        "ingress: a long record is not cut",
        AGENT, INGRESS,
        "    if len(text) > MAX_RECORD_CHARS:\n",
        "    if False:\n",
    ),
    (
        "launch spec: the admin token is written beside it",
        AGENT, ACCOUNTS,
        '        "EUGENE_PLEXUS_APP_ADMIN_TOKEN",\n',
        "",
    ),
    (
        "supervisor: an app running before the agent started is restarted",
        AGENT, ACCOUNTS,
        '            if current.state in ("running", "starting"):\n',
        "            if False:\n",
    ),
    (
        "supervisor: the agent stopping stops the apps",
        AGENT, ACCOUNTS,
        "    async def stop_all(self) -> None:\n"
        '        """The agent is stopping. The apps are not."""\n',
        "    async def stop_all(self) -> None:\n"
        '        """The agent is stopping. The apps are not."""\n'
        "        for app_id in list(self._planners):\n"
        "            await asyncio.to_thread(self.runner.stop, app_id)\n",
    ),
    (
        "supervisor: a removal that fails is swallowed",
        AGENT, ACCOUNTS,
        "        await asyncio.to_thread(self.runner.remove, app_id, purge=purge)\n",
        "        with contextlib.suppress(Exception):\n"
        "            await asyncio.to_thread(self.runner.remove, app_id, purge=purge)\n",
    ),
    (
        "launcher: systemd's own variables reach the app",
        AGENT, LAUNCHER,
        '    for name in ("CREDENTIALS_DIRECTORY", "STATE_DIRECTORY", "INVOCATION_ID", "NOTIFY_SOCKET"):\n',
        '    for name in ():\n',
    ),
    (
        "launcher: a crash reads as a clean stop",
        AGENT, LAUNCHER,
        "    return 0 if _STOP.is_set() else code\n",
        "    return 0\n",
    ),
    (
        "manager: an app that runs model-chosen actions installs without an account",
        AGENT, APPS,
        "        if self.accounts.available or manifest.localActions is False:\n",
        "        if True:\n",
    ),
    (
        "manager: the catalogue does not say whether this node makes accounts",
        AGENT, APPS,
        "            ownAccounts=self.accounts.available,\n",
        "",
    ),
    (
        "install route: an app's key may not send logs",
        AGENT, APPS_ROUTE,
        'ClientKeyCreateRequest(name=f"app:{app_id}@{node}", limits=ClientKeyLimits(writeLogs=True))',
        'ClientKeyCreateRequest(name=f"app:{app_id}@{node}", limits=ClientKeyLimits())',
    ),
    (
        "agent limits: writeLogs is dropped on the way to the ingress",
        AGENT, AGENT_LIMITS,
        '        **({"writeLogs": True} if value.get("writeLogs") else {}),\n',
        "",
    ),
    (
        "control limits: writeLogs is dropped at the root",
        CONTROL, CONTROL_LIMITS,
        '        **({"writeLogs": True} if value.get("writeLogs") else {}),\n',
        "",
    ),
    (
        "gateway: its model of a key's limits does not know writeLogs",
        GATEWAY, GATEWAY_MODEL,
        "    writeLogs: bool | None = Field(\n        False,\n",
        "    writeLogs_unknown: bool | None = Field(\n        False,\n",
    ),
    (
        "ui: an app that needs an account can be installed without one",
        UI, UI_APPS,
        "  const needsAccount = manifest.localActions !== false && !ownAccounts;\n",
        "  const needsAccount = false;\n",
    ),
    (
        "ui: the send-logs switch changes nothing",
        UI, UI_KEYS,
        "          onChange={(e) => onChange({ ...value, writeLogs: e.target.checked })}\n",
        "          onChange={() => onChange({ ...value })}\n",
    ),
]


def run(repo: Path) -> int:
    result = subprocess.run(RUNNERS[repo](), cwd=repo, capture_output=True, text=True, timeout=1200,
                            encoding="utf-8", errors="replace",
                            shell=sys.platform == "win32" and repo == UI)
    tail = (result.stdout + result.stderr).strip().splitlines()
    summary = next((line for line in reversed(tail) if "passed" in line or "failed" in line), "")
    print(f"    {repo.name}: exit={result.returncode}  {summary.strip()}", flush=True)
    return result.returncode


def main() -> None:
    files = {path for _, _, path, _, _ in SABOTAGES}
    copies = {path: path.read_bytes() for path in files}
    caught, escaped = 0, []
    try:
        print("baseline: every guard passes unsabotaged", flush=True)
        if any(run(repo) != 0 for repo in RUNNERS):
            raise SystemExit("BASELINE FAILED; fix that first")
        print("baseline PASS\n", flush=True)
        for label, repo, path, old, new in SABOTAGES:
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            if source.count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once: {label}")
            print(f"sabotage: {label}", flush=True)
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run(repo)
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n", flush=True)
            else:
                escaped.append(label)
                print("    ESCAPED\n", flush=True)
        print(f"{caught} of {len(SABOTAGES)} caught")
        for label in escaped:
            print(f"ESCAPED: {label}")
        if escaped:
            sys.exit(1)
    finally:
        for path, raw in copies.items():
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
