"""2b.3b sabotage pass: each person's workspaces, rules and keys at the site
host and the root, and only the code that changed.

`job-sites-own-enrollment.md` §3.3. Restores from a COPY, never
`git checkout --`, and opens with a baseline per gate. Each entry puts one
rule of the slice back, or takes one check out, and names the gate that must
notice:

- `site`: the site host's suites for the changed files, on Windows;
- `linux`: the hidden-path code in WSL2's Linux, under Landlock, with the
  editable venv at `~/venvs/site-host-linux` (`uv pip install -e
  site-host[dev]`);
- `control`: the root's suites for job sites, people and sign-in.

Usage: python specs/scripts/b23b-sabotage.py [--gate NAME ...] [--label TEXT ...]
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 300

SH = "site-host"
PKG = "site-host/src/eugene_plexus_site_host/"
CT = "control/src/eugene_plexus_control/"
CT_ROUTES = CT + "routes/sites.py"
CT_OIDC = CT + "routes/oidc.py"
CT_PEOPLE = CT + "routes/people.py"
CT_SITES = CT + "sites.py"
CT_PERMISSIONS = CT + "permissions.py"
HOST = PKG + "host.py"
POLICY = PKG + "policy.py"
FIO = PKG + "folder_io.py"
WT = PKG + "workspace_tools.py"
FS = PKG + "file_server.py"
AUDIT = PKG + "audit.py"
TESTS = (
    "tests/test_people.py",
    "tests/test_host.py",
    "tests/test_routing.py",
    "tests/test_signing.py",
    "tests/test_passkeys.py",
    "tests/test_local_servers.py",
    "tests/test_worker.py",
    "tests/test_workspace_tools.py",
)
LINUX_TESTS = ("tests/test_people.py", "tests/test_workspace_tools.py")

CT_TESTS = (
    "tests/test_site_people.py",
    "tests/test_sites.py",
    "tests/test_site_links.py",
    "tests/test_oidc.py",
)

GATES: dict[str, tuple[str, list[str]]] = {
    "site": (SH, [
        str(ROOT / SH / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *TESTS,
    ]),
    "linux": (SH, [
        "wsl", "-e", "bash", "-lc",
        "cd /mnt/d/py/eugene-plexus/site-host && ~/venvs/site-host-linux/bin/python -m pytest "
        "-q -x --no-header -p no:cacheprovider " + " ".join(LINUX_TESTS),
    ]),
    "control": ("control", [
        str(ROOT / "control" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *CT_TESTS,
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- held for each person's own key (J67, J68) ------------------------------------
    ("THE RULE: a linked person's change with no key applies on the root's word", "site", HOST,
     "if changes and not reduces and (subject != owner or self.has_key(subject)):",
     "if changes and not reduces and self.has_key(subject):"),
    ("THE RULE: one person's key approves another's held change", "site", HOST,
     "elif held is None or held.subject != subject:", "elif held is None:"),
    ("a person's rules count as approved whatever their digest", "site", POLICY,
     "return self.grants_nothing(subject) or self.authorized.get(subject) == self.digest(subject)",
     "return True"),
    ("a non-owner takes the owner's actions", "site", HOST,
     "if name in OWNER_ACTIONS and subject != owner:", "if False:"),
    ("a person with no link keeps workspaces", "site", HOST,
     "subject == OPERATOR or self.links.for_subject(subject) is None", "subject == OPERATOR"),
    ("a rule loosened by the root applies at once", "site", HOST,
     "                    not any(looser(after[g], before[g]) for g in GROUPS)\n",
     "                    True\n"),
    ("a deny pattern dropped applies at once", "site", HOST,
     "and set(workspace[\"deny\"]) <= kept", "and True"),
    ("a read-only workspace takes a change rule", "site", HOST,
     "if not writable and groups[\"change\"] != \"deny\":", "if False:"),
    # --- whose workspace, whose approval (J69, J79) ----------------------------------
    ("an unlinked holder's workspace is served by the owner's worker", "site", HOST,
     "            if linked or not mine\n", "            if True\n"),
    ("THE RULE: the owner's state stops everyone's own workspaces", "site", HOST,
     "(name, workspace, rules, subject if mine else owner)", "(name, workspace, rules, owner)"),
    ("a shared workspace runs under its user's approval, not the owner's", "site", HOST,
     "(name, workspace, rules, subject if mine else owner)", "(name, workspace, rules, subject)"),
    ("names are not unique in a person's view", "site", POLICY,
     'names = unique_names([w["name"] for w, _, _ in rows])',
     'names = [w["name"] for w, _, _ in rows]'),
    ("a read-only workspace's change rule is reported as stored", "site", POLICY,
     '        groups["change"] = "deny"\n', "        pass\n"),
    ("version 1's owner on their own list is kept as a person", "site", POLICY,
     '            if p.get("subject") != owner\n', "            if True\n"),
    ("version 1's reader becomes a writer", "site", POLICY,
     '"change": "allow" if writable and p.get("writable") else "deny",', '"change": "allow",'),
    # --- rules (J70, J72, J78) ----------------------------------------------------------
    ("THE RULE: an ask call runs without the person's word", "site", HOST,
     "                    if not call.asked:\n", "                    if False:\n"),
    ("a denied group runs when its workspace is named", "site", HOST,
     '            if decision == "deny":\n', "            if False:\n"),
    ("deny on reading is still offered", "site", HOST,
     'readable = [n for n in folders if rules[n]["read"] != "deny"]', "readable = list(folders)"),
    ("Workbench is never told where to ask", "site", HOST,
     'return [n for n, rules in self.rules.items() if group and rules[group] == "ask"]',
     "return []"),
    ("a local tool's ask is not enforced", "site", HOST,
     'return target.allowed[tool] or ("ask" if is_destructive(offered) else "allow")',
     'return "allow"'),
    ("a destructive local tool is granted allow by default", "site", HOST,
     '    return "ask" if is_destructive(tool) else "allow"\n', '    return "allow"\n'),
    ("the file server reads wherever it may write", "site", FS,
     "may = writable if params.name in DESTRUCTIVE else reads", "may = frozenset(folders)"),
    # --- what the root learns (J76, J80) ------------------------------------------------
    ("the report carries a workspace's path", "site", HOST,
     '            "holder": workspace["holder"],\n',
     '            "holder": workspace["holder"],\n            "path": workspace["path"],\n'),
    ("an audit line belongs to the caller, not the workspace's holder", "site", HOST,
     'entry["reader"] = self._reader(target, arguments) or entry["reader"]',
     'entry["reader"] = call.subject'),
    ("THE RULE: every person reads every audit line", "site", AUDIT,
     "if reader is None or whose == reader or (owner and whose is None):", "if True:"),
    # --- hidden paths (J70) --------------------------------------------------------------
    ("THE RULE: a named hidden path is opened", "site", FIO,
     "    hidden.check(names)\n", "    pass\n"),
    ("a listing shows what is hidden", "site", FIO,
     "entries = [e.name for e in listed if not hidden.hides([*names, e.name], _is_dir(e))]",
     "entries = [e.name for e in listed]"),
    ("Windows: a hidden name in other case is shown", "site", FIO,
     "lines = [p.casefold() if _CASELESS else p for p in patterns or []]",
     "lines = list(patterns or [])"),
    ("Windows: a short name reaches a hidden long one", "site", FIO,
     "if _CASELESS and any(_SHORT_NAME.fullmatch(n) for n in names):", "if False:"),
    ("a search walks into what is hidden", "site", WT,
     'if hidden and hidden.hides(path, entry.kind == "dir"):', "if False:"),
    ("a glob's leading folders reach a hidden one", "site", WT,
     "        hidden.check(start)\n", "        pass\n"),
    ("the worker drops a workspace's hidden paths", "site", FS,
     "[str(p) for p in deny] if isinstance(deny, list) else None,", "None,"),
    ("Linux: a named hidden path is opened", "linux", FIO,
     "    hidden.check(names)\n", "    pass\n"),
    ("Linux: a search walks into what is hidden", "linux", WT,
     'if hidden and hidden.hides(path, entry.kind == "dir"):', "if False:"),
    # --- the root: permissions (J77) ---------------------------------------------------
    ("THE RULE: a person without add-job-sites adds a machine", "control", CT_ROUTES,
     "    if not permissions.has(machine.state, subject, permissions.ADD_JOB_SITES):\n",
     "    if False:\n"),
    ("a person without use-job-sites links at the machine's page", "control", CT_OIDC,
     "        and not permissions.has(\n", "        and False and not permissions.has(\n"),
    ("a person without use-job-sites links on a Linux system install", "control", CT_ROUTES,
     'if not permissions.has(machine.state, str(person["id"]), permissions.USE_JOB_SITES):',
     "if False:"),
    ("one's own workspaces are listed without use-job-sites", "control", CT_ROUTES,
     "own=permissions.has(state, subject, permissions.USE_JOB_SITES),", "own=True,"),
    ("a call into one's own workspace runs without use-job-sites", "control", CT_ROUTES,
     "if server == helpers.FILES and not uses and names_own_workspace(summary, subject):",
     "if False:"),
    ("a setting turned off still lets everyone on the defaults", "control", CT_PERMISSIONS,
     "return state.config.get(DEFAULTS[permission]) is not False", "return True"),
    ("a person on the defaults carries the key into the log", "control", CT_PEOPLE,
     "    if chosen is not None:\n        # Kept only when set",
     "    if True:\n        # Kept only when set"),
    # --- the root: a linked person's own (J67, J68, J72, J76) -----------------------------
    ("THE RULE: anyone reaches a site's per-person routes", "control", CT_ROUTES,
     "or helpers.linked(summary, subject) is None:", "or False:"),
    ("a linked person sees everyone's links", "control", CT_ROUTES,
     '"links": [mine] if mine else [],', '"links": summary.get("links") or [],'),
    ("a linked person sees the owner's workspaces as their own", "control", CT_ROUTES,
     '"workspaces": _own_workspaces(state, summary, subject),',
     '"workspaces": _own_workspaces(state, summary, record.owner),'),
    ("a site from before 2b.3b is asked to keep people's workspaces", "control", CT_ROUTES,
     'if not (summary.get("signing") or {}).get("people"):', "if False:"),
    ("an unlinked holder's own workspaces are listed", "control", CT_SITES,
     "mine_ok = own and linked(summary, subject) is not None", "mine_ok = own"),
    ("the root's names do not match the site's", "control", CT_SITES,
     "        candidate, n = name, 1\n        while candidate.casefold() in taken:",
     "        candidate, n = name, 1\n        while False:"),
    ("THE RULE: asked is not carried to the site", "control", CT_ROUTES,
     "asked=bool(body.asked),", "asked=False,"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    where = str(ROOT / repo)
    try:
        done = subprocess.run(command, cwd=where, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    backup = Path(tempfile.mkdtemp(prefix="b23b-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, gate, relative, old, new in chosen:
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, _out = run_gate(gate)
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] ({gate}) {label}")
            caught += 1
        else:
            print(f"[ESCAPED] ({gate}) {label}")
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(chosen)} sabotages")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
