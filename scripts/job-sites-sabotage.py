"""Sabotage pass for Job Sites, slice 1 (docs/design/remote-nodes.md §5).

Each sabotage puts back one way the slice could be wrong -- in the control
root, the agent, the shared token module, Workbench or the console -- runs the
gate that should see it, and requires that gate to FAIL.

Restores are from byte copies taken before the first edit, never `git
checkout --`. It opens with a baseline assertion that every gate it uses
passes unsabotaged, and refuses to start if any anchor is not found exactly
once.

    python scripts/job-sites-sabotage.py [label filter | --from=N]

The acceptance gate runs `job-sites-acceptance.py --root-wsl` on Windows (the
root in WSL2) and on its own on Linux, with the agent's venv python.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
CONTROL = ROOT / "control" / "src" / "eugene_plexus_control"
AGENT = ROOT / "agent" / "src" / "eugene_plexus_agent"
WORKBENCH = ROOT / "workbench" / "src" / "eugene_plexus_workbench"
UI = ROOT / "ui" / "src"
WINDOWS = os.name == "nt"


def venv(repo: str) -> str:
    leaf = "Scripts/python.exe" if WINDOWS else "bin/python"
    return str(ROOT / repo / ".venv" / leaf)


def pytest(repo: str, *tests: str) -> tuple[list[str], Path]:
    return [venv(repo), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], ROOT / repo


GATES: dict[str, tuple[list[str], Path]] = {
    "control": pytest(
        "control", "tests/test_job_sites.py", "tests/test_tokens.py", "tests/test_node_helpers.py"
    ),
    "agent": pytest(
        "agent",
        "tests/test_job_site.py",
        "tests/test_root_tls.py",
        "tests/test_node_file_helper.py",
        "tests/test_tokens.py",
    ),
    "workbench": pytest("workbench", "tests/test_job_sites.py"),
    "ui": (
        ["npx.cmd" if WINDOWS else "npx", "vitest", "run", "src/lib/joinCommand.test.ts"],
        ROOT / "ui",
    ),
    "acceptance": (
        [venv("agent"), str(SPECS / "scripts" / "job-sites-acceptance.py")]
        + (["--root-wsl"] if WINDOWS else []),
        SPECS,
    ),
}


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    gate: str
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


def one(path: Path, old: str, new: str) -> tuple[tuple[Path, str, str], ...]:
    return ((path, old, new),)


TOKENS = "tokens.py"
SABOTAGES: list[Sabotage] = [
    # --- the shared token module (one copy stands for all six) ----------------------
    Sabotage(
        "a job site's key may address any machine",
        one(
            CONTROL / TOKENS,
            "                sub == SUB_AGENT and all(a in (key.issuer, RECIPIENT_CONTROL) for a in aud)",
            "                True",
        ),
        "control",
    ),
    Sabotage(
        "a job site's key is listed with the node grant too",
        one(
            CONTROL / "trust.py",
            "                    frozenset({tokens.GRANT_FILES})\n",
            "                    frozenset({tokens.GRANT_FILES, tokens.GRANT_NODE})\n",
        ),
        "control",
    ),
    # --- the control root: joining ----------------------------------------------------
    Sabotage(
        "the public route lets an ordinary node join",
        one(
            CONTROL / "routes" / "nodes.py",
            "    if via_public_nodes(request) and not job_site:\n",
            "    if False:\n",
        ),
        "control",
    ),
    Sabotage(
        "the person's password is not checked at the machine",
        one(
            CONTROL / "routes" / "nodes.py",
            '    if not matched or proof.name.strip().casefold() != person["name"].casefold():\n',
            "    if False:\n",
        ),
        "control",
    ),
    Sabotage(
        "a wrong password spends the invitation",
        one(
            CONTROL / "routes" / "nodes.py",
            "        owner = _confirm_site_owner(request, invitation.owner, body.owner)\n",
            "        store.consume(body.token, node_name=body.name)\n"
            "        owner = _confirm_site_owner(request, invitation.owner, body.owner)\n",
        ),
        "control",
    ),
    Sabotage(
        "a job site may send an address",
        one(CONTROL / "routes" / "nodes.py", "    if job_site and announced_url:\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "a files invitation may also grant the gateway",
        one(CONTROL / "routes" / "nodes.py", "    if tokens.GRANT_GATEWAY in grants:\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "a job site is shown by its probe's error, not its contact",
        one(CONTROL / "routes" / "nodes.py", "        probe = None\n    owner =", "        pass\n    owner ="),
        "control",
    ),
    # --- the control root: what a site's token opens --------------------------------
    Sabotage(
        "a site's token opens every route",
        one(CONTROL / "dependencies.py", "    if not sites:\n        _refuse_job_site(", "    if False:\n        _refuse_job_site("),
        "control",
    ),
    Sabotage(
        "the bundle needs no token through the public route",
        one(CONTROL / "routes" / "control.py", "    if authorization or via_public_nodes(request):\n", "    if authorization:\n"),
        "control",
    ),
    Sabotage(
        "a bogus bearer on the bundle is ignored",
        one(CONTROL / "routes" / "control.py", "    if authorization or via_public_nodes(request):\n", "    if via_public_nodes(request):\n"),
        "control",
    ),
    Sabotage(
        "a placement on a job site is forwarded",
        one(CONTROL / "routes" / "topology.py", "    if tokens.GRANT_FILES in record.grants:\n", "    if False:\n"),
        "control",
    ),
    # --- the control root: membership is not access ----------------------------------
    Sabotage(
        "the owner's own grants reach job sites in production",
        one(CONTROL / "node_helpers.py", "            if dev or not is_site(state, node)\n", "            if True\n"),
        "control",
    ),
    Sabotage(
        "Eugene's owner may grant people a site's folder",
        one(CONTROL / "node_helpers.py", '        if is_site(state, config["node"]):\n', "        if False:\n"),
        "control",
    ),
    Sabotage(
        "production shows Eugene's owner a site's folders",
        one(CONTROL / "routes" / "node_helpers.py", "            if not dev:\n", "            if False:\n"),
        "control",
    ),
    Sabotage(
        "the owner may grant themselves a site's folder in production",
        one(
            CONTROL / "routes" / "node_helpers.py",
            "    if helpers.is_site(machine.state, node) and helpers.install_mode(machine.state) != helpers.DEV:\n",
            "    if False:\n",
        ),
        "control",
    ),
    Sabotage(
        "Eugene's owner may turn a site's helper on",
        one(CONTROL / "routes" / "node_helpers.py", "    _not_a_site(request, node)\n    config = {**helpers", "    config = {**helpers"),
        "control",
    ),
    Sabotage(
        "anyone signed in may manage someone else's site",
        one(
            CONTROL / "routes" / "node_helpers.py",
            " or record.owner != subject:\n",
            ":\n",
        ),
        "control",
    ),
    Sabotage(
        "Eugene's owner may invite a site for themselves",
        one(CONTROL / "routes" / "node_helpers.py", '    if subject == "operator":\n        raise problem(\n            403,', '    if False:\n        raise problem(\n            403,'),
        "control",
    ),
    Sabotage(
        "a person may invite without the public route",
        one(CONTROL / "routes" / "node_helpers.py", "    if not _can_invite(request):\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "a person may hold any number of invitations",
        one(CONTROL / "routes" / "node_helpers.py", "    if store.outstanding_for(subject) >= INVITES_PER_PERSON:\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "a site is not told its owner",
        one(CONTROL / "routes" / "node_helpers.py", '"siteOwner": owner}', '"siteOwner": None}'),
        "control",
    ),
    Sabotage(
        "a mode change is not dated",
        one(CONTROL / "routes" / "config.py", "        accepted[config_module.MODE_CHANGED_AT] = datetime.now(UTC).isoformat()\n", "        pass\n"),
        "control",
    ),
    Sabotage(
        "the TLS list is signed as something else",
        one(CONTROL / "root_tls.py", 'TYP_ROOT_TLS = "ep-root-tls+jwt"', 'TYP_ROOT_TLS = "ep-trust-bundle+jwt"'),
        "control",
    ),
    # --- the agent: J7a ------------------------------------------------------------
    Sabotage(
        "a list is trusted without naming the key this connection showed",
        one(AGENT / "root_tls.py", "    if not seen or seen[-1] not in listed:\n", "    if not seen:\n"),
        "agent",
    ),
    Sabotage(
        "a list for another origin is accepted",
        one(AGENT / "root_tls.py", '    if claims.get("origin") != origin:\n', "    if False:\n"),
        "agent",
    ),
    Sabotage(
        "a pinned client sends before checking the key",
        one(AGENT / "root_tls.py", "        if not accept(pin):\n            raise PinRefused(pin)\n", "        pass\n"),
        "agent",
    ),
    Sabotage(
        "an older list brings back a dropped key",
        one(AGENT / "root_tls.py", '        if int(claims["iat"]) < self.iat:\n', "        if False:\n"),
        "agent",
    ),
    Sabotage(
        "an expired key is still accepted",
        one(AGENT / "root_tls.py", "        return self.keys.get(pin, 0) > time.time()\n", "        return pin in self.keys\n"),
        "agent",
    ),
    Sabotage(
        "a join answered by another root is kept",
        one(AGENT / "enrollment.py", "    if root_key and control_public_key != root_key:\n", "    if False:\n"),
        "agent",
    ),
    Sabotage(
        "a job site sends an address when it joins",
        one(AGENT / "enrollment.py", "    if owner is not None:\n        advertise_url = None\n", "    if owner is not None:\n"),
        "agent",
    ),
    # --- the agent: what a site does -------------------------------------------------
    Sabotage(
        "a site starts what it is asked to",
        one(AGENT / "node_work.py", "    if is_job_site(request.app):\n        raise HTTPException(409, JOB_SITE_REFUSAL)\n\n\ndef launch_lock", "    pass\n\n\ndef launch_lock"),
        "agent",
    ),
    Sabotage(
        "a site asks for run operations",
        one(AGENT / "run_worker.py", "            if is_job_site(self.app):\n", "            if False:\n"),
        "agent",
    ),
    Sabotage(
        "the helper turns the system's proxy off again",
        one(AGENT / "node_file_helper.py", "client_for(root, timeout=15.0, follow_redirects=False)", "client_for(root, timeout=15.0, follow_redirects=False, trust_env=False)"),
        "agent",
    ),
    Sabotage(
        "Eugene's owner may register a folder on a site",
        one(AGENT / "node_file_helper.py", "                if not self._site_owner or command.get(\"subject\") != self._site_owner:\n", "                if False:\n"),
        "agent",
    ),
    Sabotage(
        "the worker takes a registration for nobody",
        one(AGENT / "_node_file_helper" / "__main__.py", '                if not isinstance(command.get("subject"), str) or set(args) != {"path"}:\n', '                if set(args) != {"path"}:\n'),
        "agent",
    ),
    # --- the agent: the entry point (J3) ------------------------------------------
    Sabotage(
        "the public route is not marked for the root",
        one(AGENT / "entrypoint.py", 'headers = {"Host": [urlsplit(nodes.origin).netloc], ENTRY_HEADER: [PUBLIC_NODES]}', 'headers = {"Host": [urlsplit(nodes.origin).netloc]}'),
        "agent",
    ),
    Sabotage(
        "the public route carries every path",
        one(AGENT / "entrypoint.py", '{"host": [nodes.host], "method": [method], "path": paths}', '{"host": [nodes.host], "method": [method]}'),
        "agent",
    ),
    Sabotage(
        "a caller's mark survives the other routes",
        one(AGENT / "entrypoint.py", "    CLIENT_HEADER,\n    ENTRY_HEADER,\n]", "    CLIENT_HEADER,\n]"),
        "agent",
    ),
    Sabotage(
        "any name may be an address",
        one(AGENT / "entrypoint.py", "            if service.is_address and service is not self.nodes:\n", "            if False:\n"),
        "agent",
    ),
    Sabotage(
        "a site pulls the bundle without its token",
        one(
            AGENT / "app.py",
            "                    if record.job_site and link is not None:\n",
            "                    if False:\n",
        ),
        "acceptance",
    ),
    # --- Workbench (J13a, J18) ---------------------------------------------------------
    Sabotage(
        "production hides only nothing from the owner",
        one(WORKBENCH / "api.py", "        views = redact_for_owner(views, (await install_mode(request))[\"mode\"])\n", "        pass\n"),
        "workbench",
    ),
    Sabotage(
        "a switch to dev shows what production made",
        one(WORKBENCH / "api.py", "and not (mode == \"dev\" and call.get(\"mode\") == \"dev\")", "and not (mode == \"dev\")"),
        "workbench",
    ),
    Sabotage(
        "the mode-change notice never clears",
        one(WORKBENCH / "api.py", '"installModeNotice": bool(mode["changedAt"] and mode["changedAt"] != seen),', '"installModeNotice": bool(mode["changedAt"]),'),
        "workbench",
    ),
    # --- the console ------------------------------------------------------------------
    Sabotage(
        "a job site's join command says nothing of its owner or the root's key",
        one(UI / "lib" / "joinCommand.ts", '      "-JobSite",\n', ""),
        "ui",
    ),
]


def run_gate(gate: str) -> int:
    command, cwd = GATES[gate]
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=1500, stdin=subprocess.DEVNULL,
        encoding="utf-8", errors="replace", env=env, shell=False,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    print(f"    [{gate}] exit={result.returncode}  {lines[-1] if lines else ''}", flush=True)
    return result.returncode


def main() -> None:
    # A gate's last line may hold any character; a cp1252 console cannot.
    sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only and only.startswith("--from="):
        chosen = SABOTAGES[int(only.split("=", 1)[1]) - 1 :]
    else:
        chosen = [s for s in SABOTAGES if only is None or only in s.label]
    files = {path for s in chosen for path, _, _ in s.edits}
    copies = {path: path.read_bytes() for path in files}
    for sabotage in chosen:
        for path, old, _ in sabotage.edits:
            if copies[path].decode("utf-8").replace("\r\n", "\n").count(old) != 1:
                raise SystemExit(f"anchor not found exactly once in {path.name}: {sabotage.label}")
    caught = 0
    escaped: list[str] = []
    expected: list[str] = []
    try:
        for gate in sorted({s.gate for s in chosen}):
            print(f"baseline: {gate} must pass unsabotaged", flush=True)
            if run_gate(gate) != 0:
                raise SystemExit(f"BASELINE FAILED: {gate} does not pass unsabotaged")
        print("baselines PASS\n", flush=True)
        for sabotage in chosen:
            print(f"sabotage: {sabotage.label}", flush=True)
            sources: dict[Path, str] = {}
            for path, old, new in sabotage.edits:
                source = sources.get(path, copies[path].decode("utf-8").replace("\r\n", "\n"))
                sources[path] = source.replace(old, new)
            for path, source in sources.items():
                path.write_text(source, encoding="utf-8", newline="\n")
            try:
                code = run_gate(sabotage.gate)
            finally:
                for path in sources:
                    path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT", flush=True)
            elif sabotage.escapes:
                expected.append(sabotage.label)
                print(f"    escaped, as expected: {sabotage.escapes}", flush=True)
            else:
                escaped.append(sabotage.label)
                print("    ESCAPED", flush=True)
    finally:
        for path, data in copies.items():
            path.write_bytes(data)
    print(
        f"\n{caught} of {len(chosen)} caught; {len(expected)} expected escapes; "
        f"{len(escaped)} unexpected escapes",
        flush=True,
    )
    for label in escaped:
        print(f"  ESCAPED: {label}", flush=True)
    raise SystemExit(1 if escaped else 0)


if __name__ == "__main__":
    main()
