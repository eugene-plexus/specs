"""Sabotage pass for Job Sites (docs/design/job-sites-own-enrollment.md): slice
2b.1, a site as its own enrollment (J19, J23, J31-J33), and the slice 1 and 2
properties that outlived it (site-final policy J8, one files server per
machine J6g, the signed TLS list J7a, Workbench's marking of a site's result).

Each sabotage puts back one way the slice could be wrong -- in the control
root, the site host, the agent or Workbench -- runs the gate that should see
it, and requires that gate to FAIL.

Restores are from byte copies taken before the first edit, never `git
checkout --`. It opens with a baseline assertion that every gate it uses
passes unsabotaged, and refuses to start if any anchor is not found exactly
once.

    python scripts/job-sites-sabotage.py [label filter | --from=N | --gate=NAME | --anchors]

`--anchors` only checks that every anchor is found exactly once. The
acceptance gate runs `job-sites-acceptance.py --root-wsl` on Windows (the
root in WSL2) and on its own on Linux, with the agent's venv python. It uses
the local clones of every repo, so it sees each edit made here.
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
        "agent", "tests/test_site_host.py", "tests/test_entrypoint.py", "tests/test_entrypoint_setup.py"
    ),
    "control": pytest(
        "control", "tests/test_sites.py", "tests/test_replay_equivalence.py", "tests/test_tokens.py"
    ),
    "workbench": pytest("workbench", "tests/test_job_sites.py", "tests/test_node_folders.py"),
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
CHANNEL = SITE_HOST / "channel.py"
IDENTITY = SITE_HOST / "identity.py"
JOIN = SITE_HOST / "join.py"
LINK = SITE_HOST / "root_link.py"
RELAY = AGENT / "site_host.py"
SITE_CLI = AGENT / "site_cli.py"
ENTRY = AGENT / "entrypoint.py"
TOOLS = WORKBENCH / "tools.py"
FOLDERS = WORKBENCH / "node_folders.py"
SITES = CONTROL / "routes" / "sites.py"
NODES = CONTROL / "routes" / "nodes.py"
APPLIED = CONTROL / "applied.py"
BROKER = CONTROL / "sites.py"
SITE_TOKENS = CONTROL / "site_tokens.py"
TRUST = CONTROL / "trust.py"
TOKENS = "tokens.py"


SABOTAGES: list[Sabotage] = [
    # === control: a site's own token (J23) ============================================
    Sabotage(
        "a site key is placed in the trust bundle every node receives",
        one(
            TRUST,
            "    seen = {k.kid for k in keys}\n",
            "    for _site in state.sites.values():\n"
            "        _pub = tokens.load_public(_site.tokenPublicKey)\n"
            "        keys.append(\n"
            "            tokens.TrustKey(\n"
            "                kid=tokens.thumbprint(_pub),\n"
            '                issuer="site:" + _site.id,\n'
            "                public=_pub,\n"
            "                grants=frozenset({tokens.GRANT_NODE}),\n"
            "            )\n"
            "        )\n"
            "    seen = {k.kid for k in keys}\n",
        ),
        "control",
    ),
    Sabotage(
        "a site token may live for a day",
        one(SITE_TOKENS, "    if exp - iat > MAX_LIFETIME_SECONDS:\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "the site token's lifetime ceiling is a day",
        one(SITE_TOKENS, "MAX_LIFETIME_SECONDS = 300\n", "MAX_LIFETIME_SECONDS = 86400\n"),
        "control",
    ),
    Sabotage(
        "a site token's audience is not checked",
        (
            (SITE_TOKENS, "            audience=AUDIENCE,\n", ""),
            (
                SITE_TOKENS,
                '            options={"require": ["iss", "sub", "aud", "iat", "exp"]},\n',
                '            options={"require": ["iss", "sub", "aud", "iat", "exp"], "verify_aud": False},\n',
            ),
        ),
        "control",
    ),
    Sabotage(
        "a site token's subject is not checked",
        one(SITE_TOKENS, '    if claims.get("sub") != SUBJECT:\n', "    if False:\n"),
        "control",
    ),
    Sabotage(
        "a site token signed with a header other than EdDSA is read",
        one(SITE_TOKENS, '    if header.get("alg") != "EdDSA":\n', "    if False:\n"),
        "control",
        escapes="decode() is given algorithms=['EdDSA'] too, so a second mechanism refuses it",
    ),
    # === control: the registry, the broker, the queue ==================================
    Sabotage(
        "deletePerson keeps the person's sites",
        one(
            APPLIED,
            "        sites={k: v for k, v in state.sites.items() if v.owner != person_id},\n",
            "        sites=state.sites,\n",
        ),
        "control",
    ),
    Sabotage(
        "removeSite removes nothing",
        one(
            APPLIED,
            "    return replace(state, sites={k: v for k, v in state.sites.items() if k != site})\n",
            "    return state\n",
        ),
        "control",
    ),
    Sabotage(
        "a site may be owned by someone who is not on the install",
        one(APPLIED, '    if owner not in state.people:\n        raise ApplyError(f"entry {index}: a site\'s owner', '    if False:\n        raise ApplyError(f"entry {index}: a site\'s owner'),
        "control",
    ),
    Sabotage(
        "a snapshot forgets when a site enrolled",
        one(APPLIED, '        "enrolledAt": site.enrolledAt,\n        "hostNode": site.hostNode,\n', '        "hostNode": site.hostNode,\n'),
        "control",
    ),
    Sabotage(
        "the broker answers a report from an earlier enrollment",
        one(
            BROKER,
            '        seen = self.reports.get(bound["site"])\n'
            '        if seen is None or seen[1] != bound["enrolledAt"]:\n'
            "            return None\n"
            "        return seen[2]\n",
            '        seen = self.reports.get(bound["site"])\n'
            "        if seen is None:\n"
            "            return None\n"
            "        return seen[2]\n",
        ),
        "control",
    ),
    Sabotage(
        "the broker's last contact counts an earlier enrollment's poll",
        one(
            BROKER,
            '        seen = self.reports.get(bound["site"])\n'
            '        if seen is None or seen[1] != bound["enrolledAt"]:\n'
            "            return None\n"
            "        return time.perf_counter() - seen[0]\n",
            '        seen = self.reports.get(bound["site"])\n'
            "        if seen is None:\n"
            "            return None\n"
            "        return time.perf_counter() - seen[0]\n",
        ),
        "control",
    ),
    Sabotage(
        "an offer nobody claimed is never offered again (the lease)",
        one(
            BROKER,
            '                    stale = job.state == "offered" and now - job.offered_at > OFFER_SECONDS\n',
            "                    stale = False\n",
        ),
        "control",
    ),
    Sabotage(
        "a removed site's queued call waits for its timeout",
        one(
            BROKER,
            "        for job in [j for j in self.jobs.values() if j.site == site]:\n",
            "        for job in []:\n",
        ),
        "control",
    ),
    Sabotage(
        "one site may claim another's operation",
        one(BROKER, "            or job.site != site\n            or job.state != \"offered\"\n", "            or job.state != \"offered\"\n"),
        "control",
    ),
    Sabotage(
        "one site may answer another's operation",
        one(
            BROKER,
            '        if job is None or job.site != site or job.state != "running" or job.result.done():\n',
            '        if job is None or job.state != "running" or job.result.done():\n',
        ),
        "control",
    ),
    Sabotage(
        "a call is queued for a site that changed enrollment",
        one(SITES, '    if record is None or record.enrolledAt != bound["enrolledAt"]:\n', "    if record is None:\n"),
        "control",
    ),
    Sabotage(
        "removing a site leaves its report and queue in the broker",
        one(SITES, "    helpers.broker(request).forget(site)\n", "    pass\n"),
        "control",
    ),
    # === control: joining ===============================================================
    Sabotage(
        "a node's join token is accepted at /v1/sites/enroll",
        one(SITES, "    if invitation.owner is None:\n        if public:\n", "    if False:\n        if public:\n"),
        "control",
    ),
    Sabotage(
        "a site invitation is accepted at /v1/nodes/enroll",
        one(NODES, "    if invitation.owner is not None:\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "the owner's password is not checked at site enroll",
        one(
            NODES,
            '    if not matched or proof.name.strip().casefold() != person["name"].casefold():\n',
            "    if False:\n",
        ),
        "control",
    ),
    Sabotage(
        "another person's name with the right password confirms the join",
        one(
            NODES,
            '    if not matched or proof.name.strip().casefold() != person["name"].casefold():\n',
            "    if not matched:\n",
        ),
        "control",
    ),
    Sabotage(
        "the invitation is spent before the password is checked",
        (
            (
                SITES,
                "    owner = _confirm_site_owner(request, invitation.owner, body.owner)\n",
                "    store.consume(body.token, node_name=None)\n"
                "    owner = _confirm_site_owner(request, invitation.owner, body.owner)\n",
            ),
            (SITES, "    try:\n        store.consume(body.token, node_name=None)\n", "    try:\n        pass\n"),
        ),
        "control",
    ),
    Sabotage(
        "a locked root spends the invitation",
        one(SITES, '    if auth.signing_key is None:\n        raise problem(\n            503,\n            "Locked",\n', '    if False:\n        raise problem(\n            503,\n            "Locked",\n'),
        "control",
    ),
    Sabotage(
        "a key already enrolled as a site may enroll again",
        one(SITES, "        s.tokenPublicKey == body.tokenPublicKey for s in state.sites.values()\n", "        False\n"),
        "control",
    ),
    Sabotage(
        "a node can join from outside, through the public route",
        one(NODES, "    if via_public_sites(request):\n        # J3, J31", "    if False:\n        # J3, J31"),
        "control",
    ),
    Sabotage(
        "a person may hold any number of invitations",
        one(SITES, "    if store.outstanding_for(subject) >= INVITES_PER_PERSON:\n", "    if False:\n"),
        "control",
    ),
    Sabotage(
        "Eugene's owner may invite a site for themselves",
        one(
            SITES,
            '    if subject == helpers.OPERATOR:\n        raise problem(\n            403,\n            "Job sites belong to people",',
            '    if False:\n        raise problem(\n            403,\n            "Job sites belong to people",',
        ),
        "control",
    ),
    Sabotage(
        "the Workbench invite needs the public route again (no LAN-only join address)",
        one(SITES, '    configured = request.app.state.machine.state.config.get("siteJoinUrl")\n', "    configured = None\n"),
        "control",
    ),
    # === control: production and dev (J13, J33), the console =============================
    Sabotage(
        "/v1/sites shows dev mode's view in production",
        one(
            SITES,
            '        "dev": _dev_view(request, record) if helpers.install_mode(state) == helpers.DEV else None,\n',
            '        "dev": _dev_view(request, record),\n',
        ),
        "control",
    ),
    Sabotage(
        "Eugene's owner may grant themselves a folder in production",
        one(
            SITES,
            "    if helpers.install_mode(machine.state) != helpers.DEV:\n"
            "        raise problem(\n            409,\n",
            "    if False:\n        raise problem(\n            409,\n",
        ),
        "control",
    ),
    Sabotage(
        "Eugene's owner's call reaches a site in production",
        one(
            SITES,
            "            if helpers.install_mode(machine.state) != helpers.DEV:\n"
            "                raise problem(\n                    403,\n",
            "            if False:\n                raise problem(\n                    403,\n",
        ),
        "control",
    ),
    Sabotage(
        "dev grants outlive a switch to production",
        one(BROKER, "    if install_mode(state) != DEV or summary is None:\n        return []\n", "    if summary is None:\n        return []\n"),
        "control",
    ),
    Sabotage(
        "anyone signed in may manage someone else's site",
        one(SITES, "    if record is None or record.owner != subject:\n", "    if record is None:\n"),
        "control",
    ),
    Sabotage(
        "a node may say which sites another node hosts",
        one(SITES, "    if actor.issuer_node != name:\n", "    if False:\n"),
        "control",
    ),
    # === control: a retired files node (J19, J20, control#6) ==============================
    Sabotage(
        "a retired files node is listed in /v1/nodes",
        one(NODES, "            if not is_retired_site(record)\n", "            if True\n"),
        "control",
    ),
    Sabotage(
        "a retired files node is a node by name",
        one(NODES, "    if record is None or is_retired_site(record):\n", "    if record is None:\n"),
        "control",
    ),
    Sabotage(
        "a retired files node is in the trust bundle",
        one(TRUST, "        if not record.tokenPublicKey or is_retired_site(record):\n", "        if not record.tokenPublicKey:\n"),
        "control",
    ),
    Sabotage(
        "a retired files node may announce an address (control#6)",
        one(NODES, "    if is_retired_site(record):\n        # control#6", "    if False:\n        # control#6"),
        "control",
    ),
    Sabotage(
        "a retired files node is given a placement",
        one(CONTROL / "routes" / "topology.py", "    if tokens.GRANT_FILES in record.grants:\n", "    if False:\n"),
        "control",
    ),
    # === site host: its own enrollment (J23) ================================================
    Sabotage(
        "the channel runs an operation queued for an earlier enrollment of this site",
        one(
            CHANNEL,
            '        if op.get("site") != enrollment.site or op.get("enrolledAt") != enrollment.enrolledAt:\n',
            '        if op.get("site") != enrollment.site:\n',
        ),
        "site-host",
    ),
    Sabotage(
        "the channel runs an operation for another site",
        one(
            CHANNEL,
            '        if op.get("site") != enrollment.site or op.get("enrolledAt") != enrollment.enrolledAt:\n',
            '        if op.get("enrolledAt") != enrollment.enrolledAt:\n',
        ),
        "site-host",
    ),
    Sabotage(
        "a root that refuses the site's token is not noticed",
        one(CHANNEL, "        if answer.status_code == 401:\n            raise Removed(_problem(answer))\n", ""),
        "site-host",
    ),
    Sabotage(
        "leave does not forget the enrollment",
        one(CHANNEL, "            self.identity.forget()\n", "            pass\n"),
        "site-host",
    ),
    Sabotage(
        "leave keeps the site's key",
        one(IDENTITY, "        for name in (ENROLLMENT_FILE, KEY_FILE, PINS_FILE):\n", "        for name in (ENROLLMENT_FILE, PINS_FILE):\n"),
        "site-host",
    ),
    Sabotage(
        "the site's token lives for fifteen minutes",
        one(IDENTITY, "TOKEN_SECONDS = 240\n", "TOKEN_SECONDS = 900\n"),
        "site-host",
    ),
    Sabotage(
        "the site's token is addressed to anyone",
        one(IDENTITY, '                "aud": AUDIENCE,\n', '                "aud": "nodes",\n'),
        "site-host",
    ),
    Sabotage(
        "a join keeps the enrollment when another root answered",
        one(JOIN, "    if root_key and granted != root_key:\n", "    if False:\n"),
        "site-host",
    ),
    Sabotage(
        "a join over HTTPS sends before the root's key is pinned",
        (
            (JOIN, "            pins.adopt(await fetch_list(url, root_key))\n", "            pass\n"),
            (
                JOIN,
                "        client = pinned_client(url, pins.accepts, timeout=30.0)\n",
                "        client = client_for(url, timeout=30.0, follow_redirects=False)\n",
            ),
        ),
        "site-host",
    ),
    Sabotage(
        "a join over HTTPS needs no root key",
        one(JOIN, "        if not root_key:\n            raise JoinError(\n", "        if False:\n            raise JoinError(\n"),
        "site-host",
    ),
    Sabotage(
        "a second join replaces the enrollment",
        one(JOIN, "    if existing is not None:\n        raise JoinError(\n", "    if False:\n        raise JoinError(\n"),
        "site-host",
    ),
    Sabotage(
        "an owner named in the launch environment decides who manages the site",
        one(
            HOST,
            "            owner = self.identity.owner()\n            if owner is None or action.subject != owner:\n",
            '            owner = __import__("os").environ.get("SITE_HOST_OWNER") or self.identity.owner()\n'
            "            if owner is None or action.subject != owner:\n",
        ),
        "site-host",
    ),
    Sabotage(
        "anyone the root names may manage the site",
        one(HOST, "            if owner is None or action.subject != owner:\n", "            if owner is None:\n"),
        "site-host",
    ),
    Sabotage(
        "the health answer carries a path and the owner",
        one(
            SITE_HOST / "app.py",
            '                "lastContactAt": contact.isoformat() if contact else None,\n',
            '                "lastContactAt": contact.isoformat() if contact else None,\n'
            '                "path": str(settings.data_dir),\n'
            '                "owner": enrollment.ownerName if enrollment else None,\n',
        ),
        "site-host",
    ),
    # --- the root's TLS pin (J7a), moved into the site host with the join ------------------
    Sabotage(
        "a TLS key list signed for another origin is accepted",
        one(LINK, '    if claims.get("origin") != origin:\n', "    if False:\n"),
        "site-host",
    ),
    Sabotage(
        "a TLS key list is read as any kind of token",
        one(LINK, '    if header.get("typ") != TYP_ROOT_TLS:\n', "    if False:\n"),
        "site-host",
    ),
    Sabotage(
        "a root a few seconds ahead fails a site's join again",
        one(LINK, "            leeway=LEEWAY_SECONDS,\n", ""),
        "site-host",
    ),
    Sabotage(
        "an older list brings back a dropped key",
        one(LINK, '        if int(claims["iat"]) < self.iat:\n', "        if False:\n"),
        "site-host",
    ),
    Sabotage(
        "an expired key is still accepted",
        one(LINK, "        return self.keys.get(pin, 0) > time.time()\n", "        return pin in self.keys\n"),
        "site-host",
    ),
    Sabotage(
        "a list is trusted without naming the key this connection showed",
        one(LINK, "    if not seen or seen[-1] not in listed:\n", "    if not seen:\n"),
        "site-host",
    ),
    Sabotage(
        "a list's expired keys name the connection's key",
        one(LINK, '    listed = {k["spki"] for k in claims["keys"] if k["notAfter"] > now}\n', '    listed = {k["spki"] for k in claims["keys"]}\n'),
        "site-host",
    ),
    Sabotage(
        "a pinned client sends before checking the key",
        one(LINK, "        if not accept(pin):\n            raise PinRefused(pin)\n", "        pass\n"),
        "site-host",
    ),
    # === agent: it hosts a site without holding it (J21, J32) ================================
    Sabotage(
        "the supervisor tells the host an owner in its environment",
        one(
            RELAY,
            '            "SITE_HOST_PROTECTED_ROOTS": json.dumps([str(self.config_dir)]),\n',
            '            "SITE_HOST_PROTECTED_ROOTS": json.dumps([str(self.config_dir)]),\n'
            '            "SITE_HOST_OWNER": "someone",\n',
        ),
        "agent",
    ),
    Sabotage(
        "slice 2's node-files app is not removed",
        one(RELAY, "        if record is not None and record.manifest.entry in SITE_HOST_ENTRIES:\n", "        if False:\n"),
        "agent",
    ),
    Sabotage(
        "the hosted-site report names another node",
        one(RELAY, '                f"{root}/v1/nodes/{identity.name}/hosted-sites",\n', '                f"{root}/v1/nodes/some-other-node/hosted-sites",\n'),
        "agent",
    ),
    Sabotage(
        "the site host runs without an administrator's say-so",
        one(RELAY, '    return isinstance(value, dict) and value.get("enabled") is True\n', "    return True\n"),
        "agent",
    ),
    Sabotage(
        "site join passes the password as an argument",
        one(
            SITE_CLI,
            '        "--data-dir",\n        str(data),\n    ]\n    if args.root_key:\n',
            '        "--data-dir",\n        str(data),\n        "--password",\n        password,\n    ]\n    if args.root_key:\n',
        ),
        "agent",
    ),
    Sabotage(
        "a system install's site join does not need an administrator",
        one(SITE_CLI, "    if _system_install(config_dir):\n        _need_elevation()\n    password = _password(args)\n", "    password = _password(args)\n"),
        "agent",
    ),
    Sabotage(
        "a system install's site leave does not need an administrator",
        one(SITE_CLI, "    if _system_install(config_dir):\n        _need_elevation()\n    python = Path(args.python) if args.python else _host_python(config_dir)\n    data = Path(args.data_dir) if args.data_dir else _host_data(config_dir)\n    if python is not None and data.exists():", "    python = Path(args.python) if args.python else _host_python(config_dir)\n    data = Path(args.data_dir) if args.data_dir else _host_data(config_dir)\n    if python is not None and data.exists():"),
        "agent",
    ),
    Sabotage(
        "an app that merely has the site host's id is hidden from its owner",
        one(AGENT / "apps.py", "    return app_id in SITE_HOST_IDS and entry in SITE_HOST_ENTRIES\n", "    return app_id in SITE_HOST_IDS\n"),
        "agent",
    ),
    # --- the public route (J31) --------------------------------------------------------------
    Sabotage(
        "the public route does not mark its requests for the root",
        one(ENTRY, "        headers = {\"Host\": [urlsplit(nodes.origin).netloc], ENTRY_HEADER: [PUBLIC_SITES]}\n", "        headers = {\"Host\": [urlsplit(nodes.origin).netloc]}\n"),
        "agent",
    ),
    Sabotage(
        "the public route serves the trust bundle",
        one(ENTRY, '    "GET": ["/v1/trust/tls"],\n', '    "GET": ["/v1/trust/tls", "/v1/trust/bundle"],\n'),
        "acceptance",
    ),
    Sabotage(
        "the public route serves node enrollment",
        one(ENTRY, '        "/v1/sites/enroll",\n', '        "/v1/sites/enroll",\n        "/v1/nodes/enroll",\n'),
        "acceptance",
    ),
    Sabotage(
        "an old public_nodes setting is no longer read",
        one(ENTRY, 'validation_alias=AliasChoices("public_sites", "public_nodes")', 'validation_alias="public_sites"'),
        "agent",
    ),
    Sabotage(
        "public_sites needs no nodes name",
        one(ENTRY, "        if self.public_sites and not self.nodes:\n", "        if False:\n"),
        "agent",
    ),
    # === Workbench: a site is its id, and its results are marked (J19, J18) ===============
    Sabotage(
        "a call is sent with a node name in place of the site id",
        one(FOLDERS, '                    "site": site,\n                    "server": server,\n', '                    "node": site,\n                    "server": server,\n'),
        "workbench",
    ),
    Sabotage(
        "a tool call is run against the site's label, not its id",
        one(TOOLS, 'self.person, server["site"], server["server"], tool, call["arguments"]', 'self.person, server["label"], server["server"], tool, call["arguments"]'),
        "workbench",
    ),
    Sabotage(
        "no site call or server is marked jobSite (production redaction would not hide it)",
        (
            (
                TOOLS,
                '                {\n                    "jobSite": True,\n                    "site": server.get("site"),\n',
                '                {\n                    "site": server.get("site"),\n',
            ),
            (
                TOOLS,
                '                    call.update(\n                        jobSite=True,\n                        site=server.get("site"),\n',
                '                    call.update(\n                        site=server.get("site"),\n',
            ),
            (
                FOLDERS,
                '                "reason": s.get("reason"),\n                "jobSite": True,\n',
                '                "reason": s.get("reason"),\n',
            ),
        ),
        "workbench",
    ),
    Sabotage(
        "a site result is not marked jobSite (production redaction would not hide it)",
        one(FOLDERS, '        meta = {"jobSite": True, "mode": mode}\n', '        meta = {"jobSite": False, "mode": mode}\n'),
        "workbench",
    ),
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
        "the person's password is not checked at the machine",
        one(
            CONTROL / "routes" / "nodes.py",
            '    if not matched or proof.name.strip().casefold() != person["name"].casefold():\n',
            "    if False:\n",
        ),
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
            "            self._only_owner(person.subject)\n"
            '            if any(p["subject"] == person.subject for p in people):\n'
            '                raise Refused("Each person is named once.")\n'
            '            if person.writable',
            "            self._only_owner(person.subject)\n"
            '            if any(p["subject"] == person.subject for p in people):\n'
            '                raise Refused("Each person is named once.")\n'
            '            if person.writable',
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
        "anyone may add a local server",
        one(SITE_CLI, "    system: bool,\n) -> str:\n    _root_owns_the_list(config_dir)\n    _need_elevation()\n",
            "    system: bool,\n) -> str:\n    _root_owns_the_list(config_dir)\n"),
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
        "site server add --command starts the agent again",
        one(SITE_CLI, '        "--command", dest="program", required=True,',
            '        "--command", required=True,'),
        "agent",
    ),
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
    anchors_only = only == "--anchors"
    if anchors_only:
        only = None
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
    if anchors_only:
        print(f"{len(chosen)} sabotages, every anchor found exactly once")
        return
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
