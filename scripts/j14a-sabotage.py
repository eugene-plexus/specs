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

J14a.2 (per-user installs) adds two narrow gates over the code it changed:
- `agent2`: the connection's account on each platform (`loopback_peer`), the
  per-user page, the supervisor's approve page, the join's key page, and the
  service run's worker grant;
- `site2`: the site host reading its approve page.

J14a.3 (passkeys from Workbench, §12.5) adds gates over the code it changed:
- `site3`: the codes, the pairing MAC, the passkey store, the assertion
  checks, the hold counting either key, and the site's actions;
- `agent3`: the link page's code and passkey list;
- `control3`: the root's four routes and its update check;
- `workbench3`: Workbench's relays and its RP ID check;
- `web3`: Workbench's page: the MAC, the challenge, user verification, the code
  never sent;
- `browser3`: `j14a3-browser-check.py`, the system Chrome against the site.

Usage: python specs/scripts/j14a-sabotage.py [--gate NAME ...] [--label TEXT ...]
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Upper-case drive: vitest started from `d:/...` loads jest-dom's matchers onto
# a second copy of `expect` and 16 of web3's tests fail at baseline.
ROOT = Path("D:/py/eugene-plexus")
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
SH_SETTINGS = "src/eugene_plexus_site_host/settings.py"
AG_PEER = "src/eugene_plexus_agent/loopback_peer.py"
AG_SUPERVISOR = "src/eugene_plexus_agent/site_host.py"
AG_CLI = "src/eugene_plexus_agent/site_cli.py"
PK = "src/eugene_plexus_site_host/passkeys.py"
WB_API = "src/eugene_plexus_workbench/job_sites_api.py"
WB_PK = "web/src/lib/passkeys.ts"
WB_JS = "web/src/components/JobSites.tsx"


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
    "agent2": (AG, pytest(AG, "tests/test_loopback_peer.py", "tests/test_site_keys_page.py",
                          "tests/test_site_link_page.py", "tests/test_site_link_cli.py",
                          "tests/test_site_host.py")),
    "site2": (SH, pytest(SH, "tests/test_app.py", "tests/test_signing.py")),
    "site3": (SH, pytest(SH, "tests/test_passkeys.py", "tests/test_signing.py",
                         "tests/test_routing.py")),
    "agent3": (AG, pytest(AG, "tests/test_site_passkeys_page.py", "tests/test_site_link_page.py",
                          "tests/test_site_keys_page.py")),
    "control3": (CT, pytest(CT, "tests/test_sites.py", "-k", "passkey or held")),
    "workbench3": (WB, pytest(WB, "tests/test_job_sites.py", "-k", "passkey or relying")),
    # From web/ itself, and under "D:" not "d:": with a lowercase drive vite
    # loads vitest twice and jest-dom extends the other copy's `expect`.
    "web3": (f"{WB}/web", ["cmd", "/c", "npm", "test", "--",
                           "src/lib/passkeys.test.ts", "src/components/JobSites.test.tsx"]),
    "browser3": ("specs", [sys.executable, str(ROOT / "specs/scripts/j14a3-browser-check.py")]),
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
    # --- J14a.2: who is at the other end, per platform -----------------------------------
    ("J14a.2 Linux: the server's own row is read as the caller's", "agent2", AG, AG_PEER,
     "        if fields[1] == local and fields[2] == remote:",
     "        if fields[2] == local and fields[1] == remote:"),
    ("J14a.2 Linux: one of several rows is taken", "agent2", AG, AG_PEER,
     "    if len(uids) != 1:\n        raise PeerUnknown(\"The program that opened this page could not "
     "be found.\")\n    uid = uids.pop()",
     "    if not uids:\n        raise PeerUnknown(\"The program that opened this page could not "
     "be found.\")\n    uid = uids.pop()"),
    ("J14a.2 macOS: the server end's uid is read as the caller's", "agent2", AG, AG_PEER,
     "            if (lport, fport) != (client_port, server_port):",
     "            if lport not in (client_port, server_port):"),
    ("J14a.2 macOS: the same ports between other addresses count", "agent2", AG, AG_PEER,
     "            if (\n                not inp[_VFLAG_AT] & 0x1",
     "            if False and (\n                not inp[_VFLAG_AT] & 0x1"),
    ("J14a.2 macOS: a socket record of an unknown layout is trusted", "agent2", AG, AG_PEER,
     "            if len(sock) != _XSOCKET_N_LEN:", "            if False:"),
    # --- J14a.2: the per-user page ---------------------------------------------------------
    ("THE FINDING (J14a.2): a per-user page serves any account on the machine", "agent2", AG,
     AG_PAGE, "        if account != own:", "        if False:"),
    ("J14a.2: a per-user page links people", "agent2", AG, AG_PAGE,
     '    """Linking people: a Windows service install only (J36, J38)."""\n'
     '    supervisor = getattr(request.app.state, "site_host", None)\n'
     "    return bool(supervisor is not None and supervisor.link_page_offered())",
     '    """Linking people: a Windows service install only (J36, J38)."""\n'
     '    supervisor = getattr(request.app.state, "site_host", None)\n'
     "    return bool(supervisor is not None and supervisor.key_page_offered())"),
    ("J14a.2: the per-user page offers to remove its only link", "agent2", AG, AG_PAGE,
     "    if _per_user(request):\n        # Linked at",
     "    if False:\n        # Linked at"),
    ("J14a.2: a per-user install offers no key page", "agent2", AG, AG_SUPERVISOR,
     '            and self.mode() == "user"', '            and self.mode() == "service"'),
    ("J14a.2: a Linux system install is offered the per-user page", "agent2", AG, AG_SUPERVISOR,
     '            and self.mode() == "user"', '            and self.mode() in ("user", "root")'),
    ("J14a.2: the site host is not told its approve page", "agent2", AG, AG_SUPERVISOR,
     '            environment["SITE_HOST_APPROVE_PAGE"] = page', "            pass"),
    ("J14a.2: the join names no key page", "agent2", AG, AG_CLI,
     "    if port is not None and not _system_install(config_dir):", "    if False:"),
    ("J14a.2: a system install's join opens a browser from its elevated session", "agent2", AG,
     AG_CLI, "    if port is not None and not _system_install(config_dir):",
     "    if port is not None:"),
    ("J14a.2: --no-browser opens one anyway", "agent2", AG, AG_CLI,
     '        opened = not getattr(args, "no_browser", False)', "        opened = True"),
    ("the service run's finding: the worker grant goes on uv's link alone", "agent2", AG,
     AG_SUPERVISOR, "    return named | {Path(os.path.realpath(folder)) for folder in named}",
     "    return named"),
    # --- J14a.2: the site host's approve page ------------------------------------------------
    ("J14a.2: the site host never reads its approve page", "site2", SH, SH_SETTINGS,
     '        approve_page=values.get("SITE_HOST_APPROVE_PAGE") or None,',
     "        approve_page=None,"),
    ("J14a.2: the site names only the link page's approve page", "site2", SH, HOST,
     "        if self.settings.approve_page:\n            return self.settings.approve_page",
     "        if False:\n            return self.settings.approve_page"),
    # --- J14a.3: the site's codes and pairing ------------------------------------------------
    ("J14a.3 THE FINDING: a change is held only for a key at the machine", "site3", SH, HOST,
     "                if changes and not reduces and self.has_key(owner):",
     "                if changes and not reduces and self.keys_of(owner):"),
    ("J14a.3: the pairing MAC is not checked", "site3", SH, PK,
     "            if not hmac.compare_digest(wanted, given):", "            if False:"),
    ("J14a.3: the MAC's key is the code itself, not PBKDF2 over it", "site3", SH, PK,
     '    return hashlib.pbkdf2_hmac("sha256", normalize(code).encode("ascii"), salt, ITERATIONS, 32)',
     '    return normalize(code).encode("ascii")'),
    ("J14a.3: the salt leaves out the person", "site3", SH, PK,
     '    salt = f"{BINDING_TYPE}:{site}:{person}".encode()',
     '    salt = f"{BINDING_TYPE}:{site}".encode()'),
    ("J14a.3: a code works more than once", "site3", SH, PK,
     "                raise NotSigned(\n                    \"The code does not match the one shown at the machine, or the passkey \"\n"
     "                    \"was changed on its way here.\"\n                )\n            self._codes.pop(subject, None)",
     "                raise NotSigned(\n                    \"The code does not match the one shown at the machine, or the passkey \"\n"
     "                    \"was changed on its way here.\"\n                )"),
    ("J14a.3: wrong pairings never end the code", "site3", SH, PK,
     "                if current.tries <= 0:", "                if False:"),
    ("J14a.3: a code never expires", "site3", SH, PK,
     "            if found is None or found.expires_at <= time.time():",
     "            if found is None:"),
    ("J14a.3: only the owner gets a code, no more", "site3", SH, HOST,
     "        if subject != self.identity.owner():\n            raise NotHeld(subject)\n        code, expires",
     "        if False:\n            raise NotHeld(subject)\n        code, expires"),
    ("J14a.3: a passkey from an earlier link still counts", "site3", SH, HOST,
     "            if p.account == link.account and p.linked_at == link.linked_at",
     "            if p.account == link.account"),
    ("J14a.3: a stored passkey whose id is not its own is kept", "site3", SH, PK,
     "    return item if key_id(item.public) == item.id else None", "    return item"),
    ("J14a.3: the summary does not say the site takes passkeys", "site3", SH, HOST,
     '                "passkeys": True,', '                "passkeys": False,'),
    ("J14a.3: a refused pairing's audit line carries the MAC", "site3", SH, HOST,
     '            "arguments": None if name == "audit.read" or name in PASSKEY_ACTIONS else arguments,',
     '            "arguments": None if name == "audit.read" else arguments,'),
    # --- J14a.3: the assertion ---------------------------------------------------------------
    ("J14a.3: the client data's type is not checked", "site3", SH, PK,
     '    if not isinstance(data, dict) or data.get("type") != "webauthn.get":',
     "    if not isinstance(data, dict):"),
    ("J14a.3: the challenge is not checked", "site3", SH, PK,
     '    if not hmac.compare_digest(str(data.get("challenge") or ""), challenge(envelope_text)):',
     "    if False:"),
    ("J14a.3: a cross-origin use is taken", "site3", SH, PK,
     '    if data.get("crossOrigin") not in (None, False) or "topOrigin" in data:', "    if False:"),
    ("J14a.3: the origin is not checked", "site3", SH, PK,
     '    if origin.scheme != "https" or not (', "    if False and not ("),
    ("J14a.3: a name that merely ends like the RP ID passes", "site3", SH, PK,
     '        host == passkey.rp_id or host.endswith("." + passkey.rp_id)',
     "        host == passkey.rp_id or host.endswith(passkey.rp_id)"),
    ("J14a.3: the RP ID hash is not checked", "site3", SH, PK,
     "    if len(auth) < 37 or not hmac.compare_digest(",
     "    if len(auth) < 37 or False and not hmac.compare_digest("),
    ("J14a.3: user verification is not required", "site3", SH, PK,
     "    if not flags & _UP or not flags & _UV:", "    if not flags & _UP:"),
    ("J14a.3: presence is not required", "site3", SH, PK,
     "    if not flags & _UP or not flags & _UV:", "    if not flags & _UV:"),
    ("J14a.3: the signature is not verified", "site3", SH, PK,
     "    if not _verify(passkey.alg, passkey.public, sig, auth + hashlib.sha256(client).digest()):",
     "    if False:"),
    ("J14a.3: a counter that goes back is taken", "site3", SH, PK,
     "    if (count or passkey.sign_count) and count <= passkey.sign_count:", "    if False:"),
    ("J14a.3: the credential is not matched to the key", "site3", SH, PK,
     "    if credential_id != passkey.credential_id:", "    if False:"),
    ("J14a.3: a passkey approval skips the sequence", "site3", SH, HOST,
     "                last_seq=self.sequence.last(subject),\n            )\n            self.passkeys.counted(found.id, count)",
     "                last_seq=0,\n            )\n            self.passkeys.counted(found.id, count)"),
    ("J14a.3: a passkey approval takes the envelope's own args", "site3", SH, HOST,
     "                args=args,\n                key=approval.key,\n                last_seq=self.sequence.last(subject),\n            )\n            self.passkeys.counted",
     "                args=json.loads(approval.envelope)[\"args\"],\n                key=approval.key,\n                last_seq=self.sequence.last(subject),\n            )\n            self.passkeys.counted"),
    # --- J14a.3: the agent's page ------------------------------------------------------------
    ("J14a.3: a code is shown without the page's token", "agent3", AG, AG_PAGE,
     "        account, link = _linked(request)\n        await _posted_form(request, account)\n",
     "        account, link = _linked(request)\n"),
    ("J14a.3: a passkey is removed without the page's token", "agent3", AG, AG_PAGE,
     "        form = await _posted_form(request, account)", "        form = await request.form()"),
    ("J14a.3: any id reaches the site host", "agent3", AG, AG_PAGE,
     '        if not isinstance(ident, str) or not _KEY_ID.fullmatch(ident):\n            raise NotHere("That passkey',
     '        if not isinstance(ident, str):\n            raise NotHere("That passkey'),
    ("J14a.3: the page breaks when the site host cannot say", "agent3", AG, AG_PAGE,
     "    except HostUnavailable:\n        return \"\"\n    if answer.status_code != 200:\n        return \"\"",
     "    except ValueError:\n        return \"\"\n    if answer.status_code != 200:\n        return \"\""),
    # --- J14a.3: the root ---------------------------------------------------------------------
    ("J14a.3: a site that does not take passkeys is sent the action", "control3", CT, CT_SITES,
     '    if not (summary.get("signing") or {}).get("passkeys"):', "    if False:"),
    ("J14a.3: the root names another action", "control3", CT, CT_SITES,
     '        "passkey.pair",', '        "passkey.add",'),
    ("J14a.3: the root approves a different held change", "control3", CT, CT_SITES,
     '    arguments = {"id": ident, **body.model_dump(mode="json", exclude={"refreshToken"})}',
     '    arguments = {"id": "rules", **body.model_dump(mode="json", exclude={"refreshToken"})}'),
    # --- J14a.3: Workbench --------------------------------------------------------------------
    ("J14a.3: a pairing for another RP ID is carried", "workbench3", WB, WB_API,
     "    if rp is None or body.rpId != rp:", "    if rp is None:"),
    ("J14a.3: a plain-HTTP Workbench offers a passkey", "workbench3", WB, WB_API,
     "    return urlsplit(origin).hostname if origin else None",
     '    return urlsplit(origin).hostname if origin else "workbench.example"'),
    ("J14a.3: the browser's MAC is over unsorted keys", "web3", WB, WB_PK,
     "  const sorted = Object.keys(object).sort();", "  const sorted = Object.keys(object);"),
    ("J14a.3: the browser's PBKDF2 takes fewer rounds", "web3", WB, WB_PK,
     "export const ITERATIONS = 600_000;", "export const ITERATIONS = 100_000;"),
    ("J14a.3: the challenge is the envelope, not its hash", "web3", WB, WB_PK,
     '  const challenge = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(envelope));',
     "  const challenge = new TextEncoder().encode(envelope);"),
    ("J14a.3: user verification only preferred", "web3", WB, WB_PK,
     '      authenticatorSelection: { residentKey: "preferred", userVerification: "required" },',
     '      authenticatorSelection: { residentKey: "preferred", userVerification: "preferred" },'),
    ("J14a.3: the code is sent with the pairing", "web3", WB, WB_JS,
     "          label,\n          mac,\n", "          label,\n          mac,\n          code,\n"),
    ("J14a.3: the browser's salt leaves out the person (in Chrome)", "browser3", WB, WB_PK,
     "      salt: encoder.encode(`${BINDING_TYPE}:${value.site}:${value.person}`),",
     "      salt: encoder.encode(`${BINDING_TYPE}:${value.site}`),"),
    # --- J14a.3 (J60): a passkey removed from Workbench ------------------------------------------
    ("J14a.3: a passkey removed from Workbench stays", "site3", SH, HOST,
     '                    await asyncio.to_thread(\n'
     '                        self.passkey_remove, owner, removed.id, "from Workbench"\n'
     '                    )',
     "                    pass"),
    ("J14a.3: a removal from Workbench is recorded as at the machine", "site3", SH, HOST,
     'self.passkey_remove, owner, removed.id, "from Workbench"',
     "self.passkey_remove, owner, removed.id"),
    ("J14a.3: the root removes a different passkey", "control3", CT, CT_SITES,
     '"passkey.remove", {"id": ident}', '"passkey.remove", {"id": "0" * 32}'),
    ("J14a.3: Workbench relays any passkey id", "workbench3", WB, WB_API,
     "/passkeys/{_passkey(ident)}/remove", "/passkeys/{ident}/remove"),
    ("J14a.3: the last-key warning never shows", "web3", WB, WB_JS,
     "  const lastKey = (held?.keys.length ?? 0) <= 1;", "  const lastKey = false;"),
    ("J14a.3: Remove skips its confirmation", "web3", WB, WB_JS,
     "onClick={() => setRemoving(p.id)}", "onClick={() => void remove(p.id)}"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, argv = GATES[name]
    where = str(ROOT / repo)
    where = where[0].upper() + where[1:]
    try:
        done = subprocess.run(argv, cwd=where, capture_output=True, text=True,
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
