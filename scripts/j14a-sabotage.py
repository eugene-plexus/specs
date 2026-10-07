"""J14a.1 sabotage pass: the code the slice changed, and only that.

`person-held-keys.md` §12. Restores from a COPY, never `git checkout --`, and
opens with a baseline per gate. Each entry puts one rule of the slice back
the way it was, or takes one check out, and names the gate that must notice:

- `site`: the site host's whole suite (the verifier, the held changes, the
  gate, J51's reductions, J52's approval of the rules as a whole);
- `agent`: the link page's key and approval routes and the links store;
- `control`: the root's 202 and the names it sends;
- `workbench`: Workbench's 202;
- `browser`: `j14a-browser-check.py`, the system Chrome against the real
  page script, for what only a browser can show (a key WebCrypto lets out).

Usage: python specs/scripts/j14a-sabotage.py [--gate NAME ...]
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("d:/py/eugene-plexus")
TIMEOUT = 900

SH = "site-host"
SIGN = "src/eugene_plexus_site_host/signing.py"
HOST = "src/eugene_plexus_site_host/host.py"
POLICY = "src/eugene_plexus_site_host/policy.py"
LINKS = "src/eugene_plexus_site_host/links.py"
APP = "src/eugene_plexus_site_host/app.py"
AG = "agent"
AG_LINKS = "src/eugene_plexus_agent/site_links.py"
AG_PAGE = "src/eugene_plexus_agent/routes/site_link.py"
AG_JS = "src/eugene_plexus_agent/static_site_keys.js"
CT = "control"
CT_SITES = "src/eugene_plexus_control/routes/sites.py"
WB = "workbench"
WB_REMOTE = "src/eugene_plexus_workbench/node_folders.py"


def pytest(repo: str, *tests: str) -> list[str]:
    return [str(ROOT / repo / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", "-q", "-x",
            "--no-header", "-p", "no:cacheprovider", *tests]


GATES: dict[str, tuple[str, list[str]]] = {
    "site": (SH, pytest(SH)),
    "agent": (AG, pytest(AG, "tests/test_site_keys_page.py", "tests/test_site_link_page.py",
                         "tests/test_site_links.py")),
    "control": (CT, pytest(CT, "tests/test_sites.py")),
    "workbench": (WB, pytest(WB, "tests/test_job_sites.py")),
    "browser": ("specs", [sys.executable, str(ROOT / "specs/scripts/j14a-browser-check.py")]),
}

# (label, gate, repo, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str, str]] = [
    # --- the verifier ---------------------------------------------------------------
    ("THE FINDING: the signature is not checked", "site", SH, SIGN,
     "    if not verify(found, message, signature):", "    if False:"),
    ("a key whose id is not the hash of its own public key is trusted", "site", SH, SIGN,
     "    if _RAW_LENGTH.get(alg) != len(raw) or key_id(raw) != id_:",
     "    if _RAW_LENGTH.get(alg) != len(raw):"),
    ("the bytes need not be the site's own canonical form", "site", SH, SIGN,
     "    if not isinstance(value, dict) or canonical(value) != text:",
     "    if not isinstance(value, dict):"),
    ("only typ and v are compared: a signature for one change applies another", "site", SH, SIGN,
     "    for name, wanted in expected.items():",
     "    for name, wanted in list(expected.items())[:2]:"),
    ("the sequence is not checked: an old approval replays", "site", SH, SIGN,
     "    if seq <= last_seq:", "    if seq < 0:"),
    ("the time is not checked: a stale approval applies", "site", SH, SIGN,
     "    if not moment - FRESH_SECONDS <= iat <= moment + AHEAD_SECONDS:", "    if False:"),
    ("a held change never expires", "site", SH, SIGN,
     "            if item.expires_at > now:", "            if True:"),
    ("the same change asked twice is held twice", "site", SH, SIGN,
     "                    and canonical(item.arguments) == same", "                    and False"),
    ("the held list is unbounded", "site", SH, SIGN,
     "            if len(items) >= MAX_HELD:", "            if False:"),
    ("the loopback API answers anyone", "site", SH, APP,
     '        return secrets.compare_digest(given.encode(), f"Bearer {token}".encode())',
     "        return True"),
    ("a pinned key is taken from the file without checking it", "site", SH, LINKS,
     "                    parse_key(k.id, k.alg.value, k.publicKey, k.label) for k in entry.keys or []",
     "                    PersonKey(k.id, k.alg.value, __import__('base64').b64decode(k.publicKey), k.label)\n"
     "                    for k in entry.keys or []"),
    # --- the gate and the held changes ---------------------------------------------------
    ("THE FINDING (J48): an unsigned site runs tools", "site", SH, HOST,
     "            if reason := self._unapproved():\n                raise Refused(reason)\n            target = self._target(call)",
     "            target = self._target(call)"),
    ("a site with no owner key reads as signed", "site", SH, HOST,
     '        if owner is None or not self.keys_of(owner):\n            return "unsigned"',
     '        if owner is None or not self.keys_of(owner):\n            return "signed"'),
    ("J52: rules made on the root's word run tools once a key exists", "site", SH, HOST,
     '        return "signed" if self.policy.approved() else "unconfirmed"', '        return "signed"'),
    ("THE FINDING (J50): a change that gives access is applied on the root's word", "site", SH, HOST,
     "                if changes and not reduces and self.keys_of(owner):", "                if False:"),
    ("J51 over-reach: a new person on a folder counts as taking access away", "site", SH, HOST,
     "                    p.subject in before and (before[p.subject] or not p.writable)",
     "                    p.subject in before or True"),
    ("J51 over-reach: a reader made a writer counts as taking access away", "site", SH, HOST,
     "                    p.subject in before and (before[p.subject] or not p.writable)",
     "                    p.subject in before"),
    ("J51 over-reach: letting Eugene's owner in counts as taking access away", "site", SH, HOST,
     "                return SiteSettings.model_validate(arguments).ownerInDevMode is False",
     "                return True"),
    ("J51 over-reach: turning a server on counts as taking access away", "site", SH, HOST,
     "                return SiteServerEnable.model_validate(arguments).enabled is False",
     "                return True"),
    ("J51 over-reach: a new tool counts as taking access away", "site", SH, HOST,
     "                        if grant.name not in before:\n                            return False",
     "                        if False:\n                            return False"),
    ("J51: a removal leaves approved rules unapproved", "site", SH, HOST,
     "                    # Less than the owner approved is still theirs (J51).\n                    self.policy.authorize()",
     "                    pass"),
    ("J51: a removal approves rules nobody approved", "site", SH, HOST,
     "                if reduces and approved and not self.policy.approved():",
     "                if reduces and not self.policy.approved():"),
    ("an approval does not spend its sequence number", "site", SH, HOST,
     "                    self.sequence.accept(subject, checked.seq)", "                    pass"),
    ("a signed change leaves approved rules unapproved", "site", SH, HOST,
     "                    if approved:\n                        self.policy.authorize()",
     "                    if False:\n                        self.policy.authorize()"),
    ("a signed change approves rules nobody approved as a whole", "site", SH, HOST,
     "                    if approved:\n                        self.policy.authorize()",
     "                    if True:\n                        self.policy.authorize()"),
    ("any linked person's key approves the owner's change", "site", SH, HOST,
     "                        keys=self.keys_of(subject),",
     "                        keys={k.id: k for x in self.links.all() for k in x.keys},"),
    ("one person is listed another's held changes", "site", SH, HOST,
     "        for held in self.held.for_subject(subject):", "        for held in self.held.all():"),
    ("one person turns down another's held change", "site", SH, HOST,
     "        if held is None or held.subject != subject:\n            raise NotHeld(ident)\n        self.held.remove(ident)",
     "        if held is None:\n            raise NotHeld(ident)\n        self.held.remove(ident)"),
    ("two approvals of one change both apply it", "site", SH, HOST,
     "            if ident != RULES and self.held.get(ident) is None:\n                raise NotHeld(ident)",
     "            if False:\n                raise NotHeld(ident)"),
    ("leaving keeps the changes the old enrollment's root asked for", "site", SH,
     "src/eugene_plexus_site_host/identity.py",
     "        for name in (ENROLLMENT_FILE, KEY_FILE, PINS_FILE, HELD_FILE):",
     "        for name in (ENROLLMENT_FILE, KEY_FILE, PINS_FILE):"),
    ("a name the root gave is shown as if the site vouched for it (J54)", "site", SH, HOST,
     '            return f"{name} (as Eugene names them; no account on this machine)"',
     "            return name"),
    ("a grant the server's own list refuses is held anyway", "site", SH, HOST,
     "                    if is_destructive(tool) and not grant.standing:\n                        raise Refused(",
     "                    if False:\n                        raise Refused("),
    ("the digest leaves out who may use each folder", "site", SH, POLICY,
     '        rules = {\n            "folders": self.folders,',
     '        rules = {\n            "folders": [{k: v for k, v in f.items() if k != "people"} '
     'for f in self.folders],'),
    ("rules with folders count as granting nothing", "site", SH, POLICY,
     "            not self.folders\n            and not self.access", "            not self.access"),
    # --- the agent's page -------------------------------------------------------------
    ("a key is pinned without this page's token", "agent", AG, AG_PAGE,
     "    if found is None or not secrets.compare_digest(given, found[1].csrf):",
     "    if found is None:"),
    ("a key is pinned from a form post", "agent", AG, AG_PAGE,
     '    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":',
     "    if False:"),
    ("the list is asked for the person the browser names", "agent", AG, AG_PAGE,
     '        params = {"subject": link.subject, **({"key": key} if key else {})}',
     '        params = {"subject": request.query_params.get("subject") or link.subject, '
     '**({"key": key} if key else {})}'),
    ("an approval carries the person the browser names", "agent", AG, AG_PAGE,
     '            "subject": link.subject,\n            "envelope": value.get("envelope"),',
     '            "subject": value.get("subject") or link.subject,\n            "envelope": value.get("envelope"),'),
    ("the unlinked page may run script", "agent", AG, AG_PAGE,
     '    page = _page("Link your account", body, script=link is not None)',
     '    page = _page("Link your account", body, script=True)'),
    ("a P-256 key that is no point on the curve is pinned", "agent", AG, AG_LINKS,
     "            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)", "            pass"),
    ("a pinned key whose id is not its own is kept", "agent", AG, AG_LINKS,
     '    if entry.get("id") != key_id(raw):\n        return None', "    if False:\n        return None"),
    ("a person keeps any number of keys", "agent", AG, AG_LINKS,
     "            if len(link.keys) >= MAX_KEYS:", "            if False:"),
    ("one account removes another's key", "agent", AG, AG_LINKS,
     '            link = next((link for link in links if link.account == account), None)\n'
     '            if link is None or not any(k["id"] == ident for k in link.keys):\n                return False',
     '            link = next((link for link in links if any(k["id"] == ident for k in link.keys)), None)\n'
     '            if link is None or not any(k["id"] == ident for k in link.keys):\n                return False'),
    ("THE BROWSER: the private half is made extractable", "browser", AG, AG_JS,
     'generateKey({ name: "Ed25519" }, false, ["sign", "verify"])',
     'generateKey({ name: "Ed25519" }, true, ["sign", "verify"])'),
    # --- the root and Workbench ---------------------------------------------------------
    ("a held change comes back as a refusal", "control", CT, CT_SITES,
     '    if outcome.get("status") == "held":', "    if False:"),
    ("the root sends no names with a change", "control", CT, CT_SITES,
     "        _names(state, named.values()),", "        None,"),
    ("the site's signing state is left out of the site view", "control", CT, CT_SITES,
     '            for k in ("links", "linkPage", "sharing", "signing")',
     '            for k in ("links", "linkPage", "sharing")'),
    ("Workbench reads the root's 202 as a refusal", "workbench", WB, WB_REMOTE,
     "        if response.status_code == 202:", "        if False:"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, argv = GATES[name]
    try:
        done = subprocess.run(argv, cwd=ROOT / repo, capture_output=True, text=True,
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
    backup = Path(tempfile.mkdtemp(prefix="j14a-sabotage-"))
    for _label, _gate, repo, relative, _old, _new in chosen:
        destination = backup / repo / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / repo / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, gate, repo, relative, old, new in chosen:
        path = ROOT / repo / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, _out = run_gate(gate)
        finally:
            shutil.copy2(backup / repo / relative, path)  # restore FROM THE COPY
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
