"""Sabotage pass for Job Sites, slice 2 (docs/design/remote-nodes.md §3.4,
§6.2, §6.3): MCP between site and root (J6) and site-final policy (J8).

Each sabotage puts back one way the slice could be wrong -- in the site host,
the control root, the agent or Workbench -- runs the gate that should see it,
and requires that gate to FAIL.

Restores are from byte copies taken before the first edit, never `git
checkout --`. It opens with a baseline assertion that every gate it uses
passes unsabotaged, and refuses to start if any anchor is not found exactly
once.

    python scripts/job-sites-mcp-sabotage.py [label filter | --from=N | --gate=NAME]

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
SITE_HOST = ROOT / "site-host" / "src" / "eugene_plexus_site_host"
CONTROL = ROOT / "control" / "src" / "eugene_plexus_control"
AGENT = ROOT / "agent" / "src" / "eugene_plexus_agent"
WORKBENCH = ROOT / "workbench" / "src" / "eugene_plexus_workbench"
WINDOWS = os.name == "nt"


def venv(repo: str) -> str:
    leaf = "Scripts/python.exe" if WINDOWS else "bin/python"
    return str(ROOT / repo / ".venv" / leaf)


def pytest(repo: str, *tests: str) -> tuple[list[str], Path]:
    return [venv(repo), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], ROOT / repo


GATES: dict[str, tuple[list[str], Path]] = {
    "site-host": pytest("site-host"),
    "agent": pytest(
        "agent", "tests/test_site_host.py", "tests/test_root_tls.py", "tests/test_job_site.py"
    ),
    "control": pytest("control", "tests/test_node_helpers.py", "tests/test_job_sites.py"),
    "workbench": pytest("workbench", "tests/test_node_folders.py", "tests/test_job_sites.py"),
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


HOST = SITE_HOST / "host.py"
FILE_SERVER = SITE_HOST / "file_server.py"
RELAY = AGENT / "site_host.py"
SITE_CLI = AGENT / "site_cli.py"
BROKER = CONTROL / "node_helpers.py"
ROUTES = CONTROL / "routes" / "node_helpers.py"
TOOLS = WORKBENCH / "tools.py"
SABOTAGES: list[Sabotage] = [
    # --- the site host: one file server, folder by folder (J6g) ----------------------
    Sabotage(
        "a call may name a folder the person was not given",
        one(
            HOST,
            "        if not isinstance(name, str) or name not in target.folders:\n",
            "        if not isinstance(name, str):\n",
        ),
        "site-host",
    ),
    Sabotage(
        "a reader may write, if the folder allows it",
        one(
            HOST,
            '        if tool == "write_text" and name not in target.writable:\n',
            "        if False:\n",
        ),
        "site-host",
    ),
    Sabotage(
        "the file server itself serves any folder name it holds for any tool",
        one(
            FILE_SERVER,
            '        if folder is None or (params.name == "write_text" and name not in writable):\n',
            "        if folder is None:\n",
        ),
        "site-host",
    ),
    Sabotage(
        "write_text lists every folder the person may read",
        one(
            FILE_SERVER,
            '        names = writable if name == "write_text" else readable\n',
            "        names = readable\n",
        ),
        "site-host",
    ),
    Sabotage(
        "a person is offered every folder on the machine",
        one(
            HOST,
            "                    for folder, writable in self.policy.folders_for(call.subject)\n",
            "                    for folder, writable in [(f, f['writable']) for f in self.policy.folders]\n",
        ),
        "site-host",
    ),
    Sabotage(
        "a person's writable outruns a read-only folder",
        one(
            SITE_HOST / "policy.py",
            '                found.append((folder, bool(person["writable"] and folder["writable"])))\n',
            '                found.append((folder, bool(person["writable"])))\n',
        ),
        "site-host",
    ),
    Sabotage(
        "a read-only folder takes a writer",
        one(HOST, '            if person.writable and not folder["writable"]:\n', "            if False:\n"),
        "site-host",
    ),
    Sabotage(
        "Eugene's owner can be put on a folder's list",
        one(
            HOST,
            "            if person.subject == OPERATOR:\n                raise Refused(\n"
            '                    "Eugene\'s owner is not a person here. Let them in for dev mode in this "\n'
            "                    \"site's settings instead.\"\n                )\n"
            '            if any(p["subject"] == person.subject for p in people):\n'
            '                raise Refused("Each person is named once.")\n'
            '            if person.writable',
            '            if any(p["subject"] == person.subject for p in people):\n'
            '                raise Refused("Each person is named once.")\n'
            '            if person.writable',
        ),
        "site-host",
    ),
    Sabotage(
        "anyone the root names changes the site's list (rule 2)",
        one(
            HOST,
            '                if name == "folder.inspect" or action.subject != self.settings.owner:\n',
            '                if name == "folder.inspect":\n',
        ),
        "site-host",
    ),
    Sabotage(
        "two folders on a machine may share a name",
        one(
            HOST,
            "        if name.casefold() in {n.casefold() for n in self.policy.names().values()}:\n",
            "        if False:\n",
        ),
        "site-host",
    ),
    Sabotage(
        "an older duplicate name is not told apart",
        one(FILE_SERVER, "        while candidate.casefold() in taken:\n", "        while False:\n"),
        "site-host",
    ),
    Sabotage(
        "on a node, every grant may write",
        one(
            HOST,
            '                        "writable": g.writable,\n                    },\n                    g.writable,\n',
            '                        "writable": g.writable,\n                    },\n                    True,\n',
        ),
        "site-host",
    ),
    Sabotage(
        "Eugene's owner's dev grant is not checked against the folder",
        one(HOST, '                or grant.identity != folder["identity"]\n', ""),
        "site-host",
    ),
    Sabotage(
        "dev mode is not required for Eugene's owner",
        one(HOST, '        if call.installMode.value != "dev":\n', "        if False:\n"),
        "site-host",
    ),
    Sabotage(
        "the site's opt-in is not required for Eugene's owner (J6e)",
        one(HOST, "        if not self.policy.owner_in_dev_mode:\n", "        if False:\n"),
        "site-host",
    ),
    Sabotage(
        "tools/list is not cut to the person's tools",
        one(
            HOST,
            '            response["result"]["tools"] = [t for t in listed if t.get("name") in target.allowed]\n',
            '            response["result"]["tools"] = listed\n',
        ),
        "site-host",
    ),
    Sabotage(
        "an operation may run twice",
        one(
            HOST,
            "        if not ident or ident in self.used or not now < expires <= now + 30:\n",
            "        if not ident or not now < expires <= now + 30:\n",
        ),
        "site-host",
    ),
    Sabotage(
        "a local server may take the file server's name",
        one(
            SITE_HOST / "settings.py",
            '    if any(s.id.startswith("files") for s in servers):\n',
            "    if False:\n",
        ),
        "site-host",
    ),
    Sabotage(
        "a local servers file the agent did not write is taken",
        one(
            SITE_HOST / "settings.py",
            "    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected):\n",
            "    if False:\n",
        ),
        "site-host",
    ),
    # --- the agent: the relay, the owner pin, the site CLI --------------------------
    Sabotage(
        "an operation for another machine's key is relayed",
        one(RELAY, '            or command.get("nodeKey") != identity.signing_public_key\n', ""),
        "agent",
    ),
    Sabotage(
        "on a node, a grant may write a read-only folder",
        one(RELAY, '                or (grant.get("writable") and not folder["writable"])\n', ""),
        "agent",
    ),
    Sabotage(
        "the root's grants never reach the host",
        one(RELAY, '                    "grants": command.get("grants") or [],\n',
            '                    "grants": [],\n'),
        "agent",
    ),
    Sabotage(
        "a job site takes whichever owner the root names last",
        one(
            AGENT / "node_identity.py",
            "            if self._record.site_owner:\n                return self._record.site_owner\n",
            "",
        ),
        "agent",
    ),
    Sabotage(
        "anyone may add a local server",
        one(SITE_CLI, "    system: bool,\n) -> str:\n    _need_elevation()\n",
            "    system: bool,\n) -> str:\n"),
        "agent",
    ),
    Sabotage(
        "a local server is added without its program's hash",
        one(SITE_CLI, '        "sha256": hashlib.sha256(program.read_bytes()).hexdigest(),\n',
            '        "sha256": "0" * 64,\n'),
        "agent",
    ),
    Sabotage(
        "a system server is added without the administrator's consent",
        one(SITE_CLI, '        "consentedAt": datetime.now(UTC).isoformat() if system else None,\n',
            '        "consentedAt": None,\n'),
        "agent",
    ),
    Sabotage(
        "the host is told a hash that is not its file's",
        one(RELAY, '            "SITE_HOST_LOCAL_SERVERS_SHA256": hashlib.sha256(data).hexdigest(),\n',
            '            "SITE_HOST_LOCAL_SERVERS_SHA256": hashlib.sha256(b"").hexdigest(),\n'),
        "agent",
    ),
    Sabotage(
        "site server add --command starts the agent again",
        one(SITE_CLI, '        "--command", dest="program", required=True,',
            '        "--command", required=True,'),
        "agent",
    ),
    Sabotage(
        "the site host is an app the owner may remove",
        one(AGENT / "apps.py",
            'NODE_FILES_ENTRIES = frozenset({"eugene_plexus_site_host", "eugene_plexus_node_helper"})',
            'NODE_FILES_ENTRIES = frozenset({"eugene_plexus_node_helper"})'),
        "agent",
    ),
    Sabotage(
        "a root a few seconds ahead fails a site's join again",
        one(AGENT / "root_tls.py", "            leeway=tokens.LEEWAY_SECONDS,\n", ""),
        "agent",
    ),
    Sabotage(
        "a site's join does not pin the owner who confirmed it",
        one(AGENT / "enrollment.py", '        site_owner=_str_or_none(body.get("owner")),\n', ""),
        "acceptance",
    ),
    # --- control: the envelope, the site's list, the owner's routes -----------------
    Sabotage(
        "a person is given every folder on an ordinary node",
        one(BROKER, '        chosen = [(f, held[f["id"]]) for f in config["folders"] if f["id"] in held]\n',
            '        chosen = [(f, True) for f in config["folders"]]\n'),
        "control",
    ),
    Sabotage(
        "a call naming a folder the root did not give reaches the node",
        one(ROUTES, '            named = next((g for g in grants if g["name"] == folder), None)\n'
            '            if named is None:\n',
            '            named = next((g for g in grants if g["name"] == folder), grants[0])\n'
            '            if named is None:\n'),
        "control",
    ),
    Sabotage(
        "anyone's call is queued for a job site",
        one(ROUTES, "            if not listed:\n", "            if False:\n"),
        "control",
    ),
    Sabotage(
        "Eugene's owner's own grants work in production",
        one(BROKER, "    if install_mode(state) != DEV or summary is None or not is_site(state, node):\n",
            "    if summary is None or not is_site(state, node):\n"),
        "control",
    ),
    Sabotage(
        "anyone manages any job site",
        one(ROUTES,
            "    if record is None or not helpers.is_site(machine.state, node) or record.owner != subject:\n",
            "    if record is None or not helpers.is_site(machine.state, node):\n"),
        "control",
    ),
    Sabotage(
        "a machine that speaks no MCP is sent it anyway",
        one(ROUTES, '    if status.get("online") and report.get("ready") and report.get("protocol") != helpers.PROTOCOL:\n',
            "    if False:\n"),
        "control",
    ),
    Sabotage(
        "two folders on one node may share a name",
        one(ROUTES,
            "        if name.casefold() in {n.casefold() for n in helpers.folder_names(current).values()}:\n",
            "        if False:\n"),
        "control",
    ),
    Sabotage(
        "the console's file routes need no capability",
        one(CONTROL / "capabilities.py", "ADMINISTRATIVE = frozenset({MEMBERSHIP, INSTALL_MODE, NODE_FILES})",
            "ADMINISTRATIVE = frozenset({MEMBERSHIP, INSTALL_MODE})"),
        "control",
    ),
    Sabotage(
        "enrolment does not tell a site its owner",
        one(CONTROL / "routes" / "nodes.py", "        owner=machine.state.nodes[body.name].owner,\n", ""),
        "control",
    ),
    Sabotage(
        "every operation says production",
        one(BROKER, '        "installMode": install_mode(state),\n', '        "installMode": "production",\n'),
        "control",
    ),
    # --- Workbench: one server per machine, narrowed to the chat ---------------------
    Sabotage(
        "a chat's file tools offer every folder on the machine",
        one(TOOLS, '    kept = [name for name in folder["enum"] if name in names]\n',
            '    kept = list(folder["enum"])\n'),
        "workbench",
    ),
    Sabotage(
        "Workbench's MCP requests lack clientCapabilities",
        one(WORKBENCH / "node_folders.py", '                "io.modelcontextprotocol/clientCapabilities": {},\n', ""),
        "workbench",
    ),
    Sabotage(
        "a job site's result is not marked as one",
        one(TOOLS, '                    call.update(jobSite=True, site=server.get("site"), mode=meta["mode"])\n',
            "                    pass\n"),
        "workbench",
    ),
    Sabotage(
        "a chat may choose a job site's server it was not given",
        one(WORKBENCH / "api.py", '                    servers.update(s["id"] for s in await remote.local_servers(person))\n',
            '                    servers.update(body.settings.toolServers)\n'),
        "workbench",
    ),
]


def run_gate(gate: str) -> int:
    command, cwd = GATES[gate]
    env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=1800,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        env=env,
        shell=False,
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
    elif only and only.startswith("--gate="):
        chosen = [s for s in SABOTAGES if s.gate == only.split("=", 1)[1]]
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
