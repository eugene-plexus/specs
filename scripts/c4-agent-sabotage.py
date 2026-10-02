"""Sabotage for C4's agent half: an app that is not ours is started, told
where things are and kept from the hub's secrets the way the design says
(docs/design/c4-open-webui.md §1-§2).

Each sabotage edits the agent's source, runs the tests that should catch
it, and restores every file it touched from a byte copy taken first. A
baseline run that must pass opens it. A timeout counts as caught.

    python scripts/c4-agent-sabotage.py [--agent ../agent]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

APPS = "src/eugene_plexus_agent/apps.py"
LAUNCHER = "src/eugene_plexus_agent/app_launcher.py"
ACCOUNTS = "src/eugene_plexus_agent/app_accounts.py"
CATALOGUE = "src/eugene_plexus_agent/apps_catalogue.yaml"
TESTS = [
    "tests/test_app_start.py",
    "tests/test_apps.py",
    "tests/test_app_accounts.py",
    "tests/test_sign_in_with_eugene.py",
]

# (name, [(file, old, new), ...]): every edit is applied, or none is.
SABOTAGES: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "a secret is written into the spec the agent writes",
        [
            (
                APPS,
                '            values["oidcClientId"] = client_id\n',
                '            values["oidcClientId"] = client_id\n'
                '            values["oidcClientSecret"] = (\n'
                "                self._store.oidc_secret_file(self.record.id).read_text()\n"
                "            )\n",
            )
        ],
    ),
    (
        "the own-account path fills in inside the agent and keeps what it filled",
        [
            (
                ACCOUNTS,
                "            spawn = planner.base_plan()\n",
                "            spawn = planner.plan()\n",
            ),
            (
                ACCOUNTS,
                "    env = {k: v for k, v in plan.env.items() "
                'if k.startswith("EUGENE_PLEXUS_APP_") or k in _PASSED}\n',
                "    env = dict(plan.env)\n",
            ),
        ],
    ),
    (
        "the reset is set at every start",
        [
            (
                LAUNCHER,
                "    return previous is not None and previous != digest\n",
                "    return True\n",
            )
        ],
    ),
    (
        "the reset is never set",
        [
            (
                LAUNCHER,
                "    return previous is not None and previous != digest\n",
                "    return False\n",
            )
        ],
    ),
    (
        "the first start resets too",
        [
            (
                LAUNCHER,
                "    return previous is not None and previous != digest\n",
                "    return previous != digest\n",
            )
        ],
    ),
    (
        "an inherited reset value is kept at a start with no change",
        [(LAUNCHER, "        out.pop(reset, None)\n", "        pass\n")],
    ),
    (
        "healthPath is ignored by both supervisors",
        [
            (
                APPS,
                "{self.record.manifest.healthPath or '/healthz'}\"",
                '/healthz"',
            )
        ],
    ),
    (
        "healthPath is ignored by the own-account supervisor",
        [
            (
                ACCOUNTS,
                "                response = await client.get(planner.health_url)\n",
                '                response = await client.get(f"http://127.0.0.1:{planner.record.port}'
                '/healthz")\n',
            )
        ],
    ),
    (
        "the pypi requirement is not pinned",
        [
            (
                APPS,
                '        return f"{manifest.package}=={manifest.version}"\n',
                "        return manifest.package\n",
            )
        ],
    ),
    (
        "any pypi version is taken as exact",
        [
            (
                APPS,
                "        if not _EXACT_RELEASE.fullmatch(manifest.version):\n",
                "        if not manifest.version:\n",
            )
        ],
    ),
    (
        "the attribute is not checked at verify",
        [
            (
                APPS,
                '    "    target = getattr(importlib.import_module(name), attr, None)\\n"\n',
                '    "    sys.exit(0)\\n"\n',
            )
        ],
    ),
    (
        "an attribute that cannot be called passes verify",
        [(APPS, '    "    if not callable(target):\\n"\n', '    "    if False:\\n"\n')],
    ),
    (
        "args are passed unfilled",
        [
            (
                LAUNCHER,
                "    argv.extend(_fill(text, values)[0] for text in args)\n",
                "    argv.extend(args)\n",
            )
        ],
    ),
    (
        "the agent-account path does not fill in",
        [
            (
                APPS,
                "            argv, env, notes = app_launcher.render_start(spec, base.env)\n",
                "            argv, env, notes = base.argv, base.env, []\n",
            )
        ],
    ),
    (
        "an EUGENE_PLEXUS_ name is allowed",
        [
            (
                APPS,
                "        if name.upper().startswith(OUR_PREFIX):\n",
                "        if name.startswith(OUR_PREFIX) and False:\n",
            )
        ],
    ),
    (
        "an eugene_plexus_ name in lower case is allowed",
        [
            (
                APPS,
                "        if name.upper().startswith(OUR_PREFIX):\n",
                "        if name.startswith(OUR_PREFIX):\n",
            )
        ],
    ),
    (
        "an unknown placeholder is allowed",
        [
            (
                APPS,
                "            if placeholder not in app_launcher.PLACEHOLDERS:\n",
                "            if False:\n",
            )
        ],
    ),
    (
        "a secret may ride in an argument",
        [
            (
                APPS,
                "            if name in app_launcher.SECRET_PLACEHOLDERS:\n",
                "            if False:\n",
            )
        ],
    ),
    (
        "the app secret is made again at each start",
        [(LAUNCHER, "    if existing:\n        return existing\n", "")],
    ),
    (
        "a secret carried in the spec is used",
        [
            (
                LAUNCHER,
                "        if v is not None and k in PLACEHOLDERS and k not in SECRET_PLACEHOLDERS\n",
                "        if v is not None and k in PLACEHOLDERS\n",
            )
        ],
    ),
    (
        "a variable with no value is set to half a value",
        [
            (
                LAUNCHER,
                "        if missing:\n            out.pop",
                "        if False:\n            out.pop",
            )
        ],
    ),
    (
        "the launcher does not forward why it reset",
        [(LAUNCHER, '            forwarder.add(f"[launcher] {note}")\n', "            pass\n")],
    ),
    (
        "the console script is not named after its package",
        [
            (
                APPS,
                '    "sys.argv=sys.argv[2:];sys.exit(f())"\n',
                '    "sys.argv=sys.argv[1:];sys.exit(f())"\n',
            )
        ],
    ),
    (
        "the app's directory stays on its import path",
        [
            (
                APPS,
                '    "import importlib,sys;sys.path[:]=[p for p in sys.path if p];"\n',
                '    "import importlib,sys;"\n',
            )
        ],
    ),
    (
        "appUrl is loopback, not where the console opens it",
        [
            (
                APPS,
                "        return self._origins(app_id)[0]\n",
                "        return self._origins(app_id)[-1]\n",
            )
        ],
    ),
    (
        "Open WebUI is asked for readiness at /healthz",
        [(CATALOGUE, "  healthPath: /ready\n", "")],
    ),
    (
        "Open WebUI's licence is not carried",
        [
            (
                CATALOGUE,
                "  licenseUrl: https://github.com/open-webui/open-webui/blob/v0.11.4/LICENSE\n",
                "",
            )
        ],
    ),
]


def run(agent: Path) -> bool:
    python = agent / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = agent / ".venv" / "bin" / "python"
    try:
        done = subprocess.run(
            [str(python), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
            cwd=agent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, default=Path(__file__).resolve().parents[2] / "agent")
    agent = parser.parse_args().agent.resolve()
    if not run(agent):
        print("BASELINE FAILED: the tests do not pass unsabotaged")
        return 2
    print("baseline passes", flush=True)
    caught = 0
    for name, edits in SABOTAGES:
        originals: dict[Path, bytes] = {}
        try:
            for rel, old, new in edits:
                path = agent / rel
                original = originals.setdefault(path, path.read_bytes())
                text = path.read_bytes().decode("utf-8")
                if "\r\n" in original.decode("utf-8"):  # a Windows checkout
                    old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
                if text.count(old) != 1:
                    print(f"NOT APPLIED ({text.count(old)} matches in {rel}): {name}")
                    return 2
                path.write_bytes(text.replace(old, new).encode("utf-8"))
            passed = run(agent)
        finally:
            for path, original in originals.items():
                path.write_bytes(original)
        caught += not passed
        print(f"{'CAUGHT ' if not passed else 'ESCAPED'} {name}", flush=True)
    print(f"{caught}/{len(SABOTAGES)} caught")
    return 0 if caught == len(SABOTAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
