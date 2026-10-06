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

    python scripts/job-sites-sabotage.py [label filter | --from=N | --gate=NAME | --labels=FILE | --anchors]

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
    # Slice 2b.2: each person's worker, the link page and the links file.
    "agent-site": pytest(
        "agent",
        "tests/test_site_links.py",
        "tests/test_site_link_page.py",
        "tests/test_site_link_cli.py",
        "tests/test_site_workers.py",
        "tests/test_site_workers_win32_calls.py",
        "tests/test_site_host.py",
        "tests/test_entrypoint.py",
        "tests/test_entrypoint_setup.py",
    ),
    "control-links": pytest(
        "control", "tests/test_sites.py", "tests/test_site_links.py", "tests/test_oidc.py"
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


# === Slice 2b.2: each person's worker, as that person (§3.2, §3.2.1; J24-J27, J36-J38) =====
CHANNEL_LOCAL = SITE_HOST / "local_channel.py"
WORKERS = SITE_HOST / "workers.py"
ACCOUNTS = SITE_HOST / "accounts.py"
WORKER = SITE_HOST / "worker.py"
HOST_LINKS = SITE_HOST / "links.py"
HOST_SETTINGS = SITE_HOST / "settings.py"
SITE_LINKS = AGENT / "site_links.py"
SITE_WORKERS = AGENT / "site_workers.py"
LINK_ROUTE = AGENT / "routes" / "site_link.py"
DEPENDENCIES = AGENT / "dependencies.py"
OIDC = CONTROL / "oidc.py"
OIDC_ROUTE = CONTROL / "routes" / "oidc.py"


def e(
    label: str, path: Path, old: str, new: str, gate: str, escapes: str | None = None
) -> Sabotage:
    return Sabotage(label, one(path, old, new), gate, escapes)


SABOTAGES.extend(
    [
        # --- site host: the local channel -------------------------------------------
        e(
            "the channel grants clients the right to create another pipe instance",
            CHANNEL_LOCAL,
            "    CLIENT_ACCESS = 0x00120083\n",
            "    CLIENT_ACCESS = 0x00120087\n",
            "site-host",
        ),
        e(
            "the channel grants clients generic write",
            CHANNEL_LOCAL,
            "    CLIENT_ACCESS = 0x00120083\n",
            "    CLIENT_ACCESS = 0x0012019F\n",
            "site-host",
        ),
        e(
            "the first pipe instance is not exclusive",
            CHANNEL_LOCAL,
            "            if first:\n                mode |= FILE_FLAG_FIRST_PIPE_INSTANCE\n",
            "            if first:\n                pass\n",
            "site-host",
        ),
        e(
            "the pipe's security descriptor names no owner",
            CHANNEL_LOCAL,
            'f"O:{owner}D:P(A;;GA;;;SY)',
            'f"D:P(A;;GA;;;SY)',
            "site-host",
        ),
        e(
            "the pipe answers clients on other machines",
            CHANNEL_LOCAL,
            "                PIPE_REJECT_REMOTE_CLIENTS,\n                PIPE_UNLIMITED_INSTANCES,\n",
            "                0,\n                PIPE_UNLIMITED_INSTANCES,\n",
            "site-host",
        ),
        e(
            "a worker's account is the one its hello claims, not the one the system reports",
            CHANNEL_LOCAL,
            "            conn.hello = hello\n            conn.start_reading(rest)\n",
            '            conn.hello = hello\n            conn.account = str(hello.get("account") or account)\n'
            "            conn.start_reading(rest)\n",
            "site-host",
        ),
        e(
            "a worker's hello is not required to say hello",
            CHANNEL_LOCAL,
            '            if hello.get("t") != "hello":\n                pipe.close()\n                return\n',
            '            if False:\n                pipe.close()\n                return\n',
            "site-host",
        ),
        e(
            "a failed RevertToSelf leaves the thread running as the worker",
            CHANNEL_LOCAL,
            "            if not _RevertToSelf():\n"
            "                # A thread left running as someone else must not run on.\n"
            "                os._exit(70)\n",
            "            _RevertToSelf()\n",
            "site-host",
        ),
        e(
            "workers connect at a level that lets the site host act as them",
            CHANNEL_LOCAL,
            "                FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION,\n",
            "                FILE_FLAG_OVERLAPPED,\n",
            "site-host",
        ),
        e(
            "a worker does not check who owns the pipe it found",
            CHANNEL_LOCAL,
            "        if owner != host:\n            _CloseHandle(handle)\n",
            "        if False:\n            _CloseHandle(handle)\n",
            "site-host",
        ),
        e(
            "an outgoing frame may be any size",
            CHANNEL_LOCAL,
            "\n    if len(data) > MAX_FRAME:\n",
            "\n    if False:\n",
            "site-host",
        ),
        e(
            "an incoming frame may be any size (the buffer)",
            CHANNEL_LOCAL,
            "                if len(self._buffer) > MAX_FRAME:\n",
            "                if False:\n",
            "site-host",
        ),
        e(
            "an incoming frame may be any size (the line)",
            CHANNEL_LOCAL,
            "            if len(line) + 1 > MAX_FRAME:\n",
            "            if False:\n",
            "site-host",
        ),
        e(
            "a first frame may be any size",
            CHANNEL_LOCAL,
            "            if len(data) > MAX_FRAME:\n",
            "            if False:\n",
            "site-host",
        ),
        # --- site host: one worker per linked account ---------------------------------
        e(
            "a worker from an account no one linked is served",
            WORKERS,
            "        link = self.links.for_account(conn.account)\n        if link is None:\n",
            "        link = self.links.for_account(conn.account)\n        if False:\n",
            "site-host",
        ),
        e(
            "an unlinked worker is not told it was refused",
            WORKERS,
            '                        "t": "refused",\n',
            '                        "t": "ignored",\n',
            "site-host",
        ),
        e(
            "a replaced worker is not told it was replaced",
            WORKERS,
            '                await old.conn.send({"t": "replaced"})\n',
            "                pass\n",
            "site-host",
        ),
        e(
            "a replaced worker's connection stays open",
            WORKERS,
            "            await self._drop(old)\n",
            "            pass\n",
            "site-host",
        ),
        e(
            "prune keeps a worker whose link was removed",
            WORKERS,
            "            if self.links.for_account(account) is None:\n                await self._drop(worker)\n",
            "            if False:\n                await self._drop(worker)\n",
            "site-host",
        ),
        e(
            "a worker that goes away stays in the table",
            WORKERS,
            "            if self._by_account.get(worker.conn.account) is worker:\n"
            "                del self._by_account[worker.conn.account]\n"
            "            worker.fail_all()\n"
            "            with contextlib.suppress(Exception):\n"
            "                await worker.conn.close()\n",
            "            worker.fail_all()\n"
            "            with contextlib.suppress(Exception):\n"
            "                await worker.conn.close()\n",
            "site-host",
        ),
        e(
            "a worker that goes away leaves its calls waiting",
            WORKERS,
            "                del self._by_account[worker.conn.account]\n            worker.fail_all()\n            with",
            "                del self._by_account[worker.conn.account]\n            with",
            "site-host",
        ),
        e(
            "an unanswered call is reported as a worker that went away",
            WORKERS,
            "        except TimeoutError:\n            raise WorkerTimeout from None\n",
            "        except TimeoutError:\n            raise WorkerGone from None\n",
            "site-host",
        ),
        e(
            "a call's id stays pending after it ends",
            WORKERS,
            "        finally:\n            worker.pending.pop(ident, None)\n",
            "        finally:\n            pass\n",
            "site-host",
        ),
        e(
            "a message that is not a result answers a call",
            WORKERS,
            '                if message.get("t") != "result":\n                    continue\n',
            '                if False:\n                    continue\n',
            "site-host",
        ),
        # --- site host: who is never a person ------------------------------------------
        e(
            "an account with a well-known SID outside the person ranges may be a person",
            ACCOUNTS,
            '        if not account.startswith("S-1-5-21-") and not account.startswith("S-1-12-1-"):\n',
            "        if False:\n",
            "site-host",
        ),
        e(
            "an Entra ID account is not a person",
            ACCOUNTS,
            '        if not account.startswith("S-1-5-21-") and not account.startswith("S-1-12-1-"):\n',
            '        if not account.startswith("S-1-5-21-"):\n',
            "site-host",
        ),
        e(
            "a window-manager virtual account is only 'not a person's account'",
            ACCOUNTS,
            '_PROGRAM_PREFIXES = ("S-1-5-80-", "S-1-5-82-", "S-1-5-90-", "S-1-5-96-")\n',
            '_PROGRAM_PREFIXES = ("S-1-5-80-", "S-1-5-82-", "S-1-5-96-")\n',
            "site-host",
        ),
        e(
            "a Linux system uid is a person",
            ACCOUNTS,
            "LINUX_UID_MIN = 1000\n",
            "LINUX_UID_MIN = 100\n",
            "site-host",
        ),
        e(
            "macOS uses Linux's lowest uid",
            ACCOUNTS,
            '    floor = MACOS_UID_MIN if sys.platform == "darwin" else LINUX_UID_MIN\n',
            "    floor = LINUX_UID_MIN\n",
            "site-host",
        ),
        e(
            "nobody is a person",
            ACCOUNTS,
            "    if uid == 65534:\n",
            "    if False:\n",
            "site-host",
        ),
        e(
            "root is not named as root",
            ACCOUNTS,
            "    if uid == 0:\n",
            "    if False:\n",
            "site-host",
        ),
        e(
            "a worker may run as an account other than the one it was started for",
            ACCOUNTS,
            "    if mine != expected:\n",
            "    if False:\n",
            "site-host",
        ),
        e(
            "a worker may run as the site host's own account",
            ACCOUNTS,
            "    if host is not None and mine == host and not shared:\n",
            "    if False:\n",
            "site-host",
        ),
        e(
            "the shared-account flag is ignored",
            ACCOUNTS,
            "    if host is not None and mine == host and not shared:\n",
            "    if host is not None and mine == host:\n",
            "site-host",
        ),
        e(
            "an elevated worker serves",
            ACCOUNTS,
            "    if elevated():\n        return",
            "    if False:\n        return",
            "site-host",
        ),
        # --- site host: the worker ------------------------------------------------------
        e(
            "a worker takes the local servers the site host names in the call",
            WORKER,
            '            server = self.local.server(self._entry(work.get("server")), outcome)\n',
            '            if isinstance(work.get("servers"), list):\n'
            "                from ._generated.models import SiteLocalServer\n\n"
            "                self.local = LocalServers(\n"
            '                    tuple(SiteLocalServer.model_validate(s) for s in work["servers"]),\n'
            "                    self.local.data_dir,\n"
            "                )\n"
            '            server = self.local.server(self._entry(work.get("server")), outcome)\n',
            "site-host",
        ),
        e(
            "a worker takes the protected roots the site host names in the call",
            WORKER,
            "                folders, frozenset(str(w) for w in writable), list(self.protected), outcome\n",
            "                folders,\n"
            "                frozenset(str(w) for w in writable),\n"
            '                [Path(p) for p in work.get("protected", self.protected)],\n'
            "                outcome,\n",
            "site-host",
        ),
        # Registering a folder is checked twice (the path, then the identity), so
        # either alone escapes by design; both removed is the mistake.
        Sabotage(
            "a worker inspects a folder without its protected roots",
            (
                (
                    WORKER,
                    "            full = folder_io.check_root_path(path, self.protected)\n",
                    "            full = folder_io.check_root_path(path, [])\n",
                ),
                (
                    WORKER,
                    "folder_io.inspect, full, self.protected)",
                    "folder_io.inspect, full, [])",
                ),
            ),
            "site-host",
        ),
        e(
            "a worker keeps going after the site host refuses it",
            WORKER,
            '                        file=sys.stderr,\n                    )\n                    raise Stopped\n                if message.get("t") == "replaced":\n',
            '                        file=sys.stderr,\n                    )\n                    continue\n                if message.get("t") == "replaced":\n',
            "site-host",
        ),
        e(
            "a worker keeps going after another worker replaced it",
            WORKER,
            '                        "eugene-plexus-site-worker: another worker for this account took over",\n'
            "                        file=sys.stderr,\n                    )\n                    raise Stopped\n",
            '                        "eugene-plexus-site-worker: another worker for this account took over",\n'
            "                        file=sys.stderr,\n                    )\n                    continue\n",
            "site-host",
        ),
        e(
            "a worker the site host refused reconnects",
            WORKER,
            "            except Stopped:\n                return\n",
            "            except Stopped:\n                pass\n",
            "site-host",
        ),
        e(
            "a worker that must not serve starts serving",
            WORKER,
            '        sys.exit(f"eugene-plexus-site-worker: {why}")\n',
            '        print(f"eugene-plexus-site-worker: {why}", file=sys.stderr)\n',
            "site-host",
        ),
        e(
            "a per-user worker is never told it may share the host's account",
            WORKER,
            "args.host, shared=args.shared_account):",
            "args.host, shared=False):",
            "site-host",
        ),
        e(
            "a worker ignores the protected roots it was started with",
            WORKER,
            "    protected = [Path(sys.prefix), Path(__file__).parent, *(Path(p) for p in args.protect)]\n",
            "    protected = [Path(sys.prefix), Path(__file__).parent]\n",
            "site-host",
        ),
        e(
            "a worker reads no local-server list of its own",
            WORKER,
            "        servers=read_servers(Path(args.servers) if args.servers else None),\n",
            "        servers=(),\n",
            "site-host",
        ),
        # --- site host: routing a call to a person's worker ---------------------------
        e(
            "an unlinked person's calls are refused rather than run as the owner",
            HOST,
            "        link = self.links.for_subject(owner) if owner else None\n",
            "        link = self.links.for_subject(subject)\n",
            "site-host",
        ),
        e(
            "a linked person whose worker is absent runs as the owner",
            HOST,
            "            if not self.workers.connected(own.account):\n"
            "                raise Refused(self._not_running(own, own=True))\n"
            "            return own.account\n",
            "            if self.workers.connected(own.account):\n                return own.account\n",
            "site-host",
        ),
        e(
            "a machine that serves only its owner serves everyone",
            HOST,
            "        if subject != owner and not self.settings.sharing:\n",
            "        if False:\n",
            "site-host",
        ),
        e(
            "the owner's absent worker is not said",
            HOST,
            "        if not self.workers.connected(link.account):\n"
            "            raise Refused(self._not_running(link, own=subject == owner))\n",
            "        if False:\n            pass\n",
            "site-host",
        ),
        e(
            "a folder is opened in the site host rather than by the owner's worker",
            HOST,
            '            answer = await self._ask(account, {"op": "inspect", "path": path.strip()})\n',
            "            _full = folder_io.check_root_path(path.strip(), self.protected)\n"
            "            answer = {\n"
            '                "path": _full,\n'
            '                "identity": await asyncio.to_thread(folder_io.inspect, _full, self.protected),\n'
            "            }\n",
            "site-host",
        ),
        e(
            "the report says a linked person's worker is running when it is not",
            HOST,
            "            available = self.workers.connected(link.account)\n",
            "            available = True\n",
            "site-host",
        ),
        e(
            "a removed link's worker is never pruned",
            HOST,
            "        self._spawn(self.workers.prune())\n",
            "        pass\n",
            "site-host",
        ),
        # --- site host: the links file and settings ---------------------------------------
        e(
            "two links for one person are both kept",
            HOST_LINKS,
            "                entry.subject in by_subject\n                or entry.account in by_account\n",
            "                entry.account in by_account\n",
            "site-host",
        ),
        e(
            "a third entry for a dropped person revives it",
            HOST_LINKS,
            "                or entry.subject in broken_subjects\n",
            "",
            "site-host",
        ),
        e(
            "the earlier half of a duplicate is kept",
            HOST_LINKS,
            "                        by_subject.pop(earlier.subject, None)\n"
            "                        by_account.pop(earlier.account, None)\n",
            "                        pass\n",
            "site-host",
        ),
        e(
            "a changed links file is not read again",
            HOST_LINKS,
            "        if stamp == self._stamp:\n",
            "        if self._stamp is not None:\n",
            "site-host",
        ),
        e(
            "the host does not say when it has no channel for workers",
            HOST_SETTINGS,
            "        if self.channel is None:\n",
            "        if False:\n",
            "site-host",
        ),
        e(
            "the starter's protected roots are not the host's",
            HOST_SETTINGS,
            "    protected = (data, Path(sys.prefix), Path(__file__).parent, *(Path(p) for p in roots))\n",
            "    protected = (data, Path(sys.prefix), Path(__file__).parent)\n",
            "site-host",
        ),
        # --- agent: the links file --------------------------------------------------
        e(
            "a person may be linked to two accounts",
            SITE_LINKS,
            "                if link.subject == subject:\n",
            "                if False:\n",
            "agent-site",
        ),
        e(
            "an account may be linked to two people",
            SITE_LINKS,
            "                if link.account == account:\n                    raise LinkError(\n",
            "                if False:\n                    raise LinkError(\n",
            "agent-site",
        ),
        e(
            "an account that is never a person's is linked",
            SITE_LINKS,
            "        if why := not_a_person(account):\n            raise LinkError(",
            "        if False:\n            raise LinkError(",
            "agent-site",
        ),
        e(
            "Eugene's own accounts may be linked",
            SITE_LINKS,
            "        if account in never:\n",
            "        if False:\n",
            "agent-site",
        ),
        e(
            "the agent links an account whose SID is outside the person ranges",
            SITE_LINKS,
            '        if not account.startswith(("S-1-5-21-", "S-1-12-1-")):\n',
            "        if False:\n",
            "agent-site",
        ),
        e(
            "the agent links nobody (65534)",
            SITE_LINKS,
            "    if uid < (MACOS_UID_MIN if sys.platform == \"darwin\" else LINUX_UID_MIN) or uid == 65534:\n",
            '    if uid < (MACOS_UID_MIN if sys.platform == "darwin" else LINUX_UID_MIN):\n',
            "agent-site",
        ),
        e(
            "the agent's Linux uid floor is lower",
            SITE_LINKS,
            "LINUX_UID_MIN = 1000\n",
            "LINUX_UID_MIN = 100\n",
            "agent-site",
        ),
        e(
            "a linked account's worker cannot read the server list's grant: wrong right",
            SITE_LINKS,
            '        grants = [f"*{link.account}:R" for link in links if link.account.startswith("S-")]\n',
            '        grants = [f"*{link.account}:F" for link in links if link.account.startswith("S-")]\n',
            "agent-site",
        ),
        e(
            "the site host's account may write beside the links",
            SITE_LINKS,
            '        grants.append(f"{SITE_HOST_ACCOUNT}:(OI)(CI)RX")\n',
            '        grants.append(f"{SITE_HOST_ACCOUNT}:(OI)(CI)F")\n',
            "agent-site",
        ),
        e(
            "the site folder inherits permissions from the install",
            SITE_LINKS,
            '    _icacls(folder, "/inheritance:r", "/grant:r", *grants)\n',
            '    _icacls(folder, "/grant:r", *grants)\n',
            "agent-site",
        ),
        # --- agent: starting each person's worker -----------------------------------
        e(
            "a worker is started with the person's unfiltered token",
            SITE_WORKERS,
            "        limited = _limited(token)\n",
            "        limited = token\n",
            "agent-site",
        ),
        e(
            "a full token's filtered twin is not used",
            SITE_WORKERS,
            "        return win32security.GetTokenInformation(token, win32security.TokenLinkedToken)\n",
            "        return token\n",
            "agent-site",
        ),
        e(
            "a token with administrators enabled is not filtered",
            SITE_WORKERS,
            "    if not _admin_enabled(token):\n        return token\n    return _filter_by_hand(token)\n",
            "    return token\n",
            "agent-site",
        ),
        e(
            "the administrators group is never found enabled",
            SITE_WORKERS,
            "        if sid == admins and attributes & 0x4:  # SE_GROUP_ENABLED\n",
            "        if False:\n",
            "agent-site",
        ),
        e(
            "a worker is started for an account that is not a person's",
            SITE_WORKERS,
            "        linked = {link.account for link in self.links.load() if not not_a_person(link.account)}\n",
            "        linked = {link.account for link in self.links.load()}\n",
            "agent-site",
        ),
        e(
            "a worker keeps running after its link was removed",
            SITE_WORKERS,
            "            elif account not in linked or program is None or entry.program != program:\n",
            "            elif program is None or entry.program != program:\n",
            "agent-site",
        ),
        e(
            "a worker keeps running on an old program",
            SITE_WORKERS,
            "            elif account not in linked or program is None or entry.program != program:\n",
            "            elif account not in linked or program is None:\n",
            "agent-site",
        ),
        e(
            "a worker is started for everyone signed in, linked or not",
            SITE_WORKERS,
            "        for account in linked:\n            if account in self.running or account not in sessions:\n",
            "        for account in sessions:\n            if account in self.running or account not in sessions:\n",
            "agent-site",
        ),
        e(
            "a worker is started in a session of someone else",
            SITE_WORKERS,
            "        if user != account:\n",
            "        if False:\n",
            "agent-site",
        ),
        e(
            "a worker is not put in its job",
            SITE_WORKERS,
            "            win32job.AssignProcessToJobObject(job, process)\n",
            "            pass\n",
            "agent-site",
        ),
        e(
            "the job does not close with the agent",
            SITE_WORKERS,
            '    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE\n',
            '    info["BasicLimitInformation"]["LimitFlags"] |= 0\n',
            "agent-site",
        ),
        # Found by the Windows acceptance (run 2): one job for every worker.
        e(
            "every worker shares one job",
            SITE_WORKERS,
            "        job = _worker_job()\n",
            '        job = self.__dict__.setdefault("_shared_job", _worker_job())\n',
            "agent-site",
        ),
        e(
            "stopping a worker leaves its job open",
            SITE_WORKERS,
            "                win32process.TerminateProcess(entry.handle, 1)\n            _close(entry.job)\n",
            "                win32process.TerminateProcess(entry.handle, 1)\n",
            "agent-site",
        ),
        e(
            "a worker that cannot join its job leaves the job open",
            SITE_WORKERS,
            "            win32process.TerminateProcess(process, 1)\n            _close(job)\n            raise\n",
            "            win32process.TerminateProcess(process, 1)\n            raise\n",
            "agent-site",
        ),
        # Found by the Windows acceptance (run 1): a venv is not an install.
        e(
            "site join takes any venv's interpreter for the installed site host",
            SITE_CLI,
            "    store = AppStore(config_dir / APPS_FILE)\n    try:\n        store.load()\n",
            "    for found in (config_dir / APPS_DIR / HELPER_ID / \"versions\").glob(\"*/venv\"):\n"
            "        if venv_python(found).exists():\n"
            "            return venv_python(found)\n"
            "    store = AppStore(config_dir / APPS_FILE)\n    try:\n        store.load()\n",
            "agent-site",
        ),
        # Found by CI on Linux after landing: a broken service install read as per-user.
        e(
            "a service install with broken accounts hosts the site as the agent's own child",
            RELAY,
            "            InstallMechanism.windows_service,\n            InstallMechanism.systemd_system,\n",
            "",
            "agent-site",
        ),
        e(
            "a worker runs before it is in the job",
            SITE_WORKERS,
            "            win32con.CREATE_SUSPENDED\n            | win32process.CREATE_NO_WINDOW\n",
            "            win32process.CREATE_NO_WINDOW\n",
            "agent-site",
        ),
        e(
            "a disconnected session is preferred to an active one",
            SITE_WORKERS,
            "        if user not in found or rank < found[user][1]:\n",
            "        if user not in found:\n",
            "agent-site",
        ),
        e(
            "sessions that are neither active nor disconnected count",
            SITE_WORKERS,
            "        if state not in (win32ts.WTSActive, win32ts.WTSDisconnected):\n            continue\n",
            "",
            "agent-site",
        ),
        e(
            "a crashing worker restarts at once, always",
            SITE_WORKERS,
            "        return due is None or time.perf_counter() >= due[0]\n",
            "        return True\n",
            "agent-site",
        ),
        e(
            "a per-user worker keeps running on an old program",
            SITE_WORKERS,
            "        if self.process is not None and self._program_running != self.program:\n            await self.stop()\n",
            "",
            "agent-site",
        ),
        e(
            "a worker is run without Python's isolated mode",
            SITE_WORKERS,
            '            "-I",\n',
            "",
            "agent-site",
        ),
        e(
            "a worker is not told it shares the host's account",
            SITE_WORKERS,
            "        if self.shared:\n            args.append(\"--shared-account\")\n",
            "",
            "agent-site",
        ),
        e(
            "a worker is not told which paths are never a folder",
            SITE_WORKERS,
            '            args += ["--protect", str(path)]\n',
            "            pass\n",
            "agent-site",
        ),
        # --- agent: the link page ------------------------------------------------------
        e(
            "the link page serves a connection from another address",
            LINK_ROUTE,
            '        or client[0] != "127.0.0.1"\n',
            "",
            "agent-site",
        ),
        e(
            "the link page serves a request made to another address",
            LINK_ROUTE,
            '        or server[0] != "127.0.0.1"\n',
            "",
            "agent-site",
        ),
        e(
            "the link page serves a TLS connection",
            LINK_ROUTE,
            '        or scope.get("scheme") != "http"\n',
            "",
            "agent-site",
        ),
        e(
            "the link page serves a request that came through the entry point",
            LINK_ROUTE,
            '        or (scope.get("state") or {}).get("via_entrypoint")\n',
            "",
            "agent-site",
        ),
        e(
            "the link page serves a request carrying a forwarding header",
            LINK_ROUTE,
            "        or any(name in request.headers for name in _FORWARDING)\n",
            "",
            "agent-site",
        ),
        e(
            "the link page is opened by an account that is never a person's",
            LINK_ROUTE,
            "    if why := not_a_person(account):\n        raise NotHere(f\"This page was opened by",
            "    if False:\n        raise NotHere(f\"This page was opened by",
            "agent-site",
        ),
        e(
            "the link page serves other systems",
            LINK_ROUTE,
            '    if sys.platform != "win32":\n        raise NotHere("This page runs on a Windows service install.")\n',
            "",
            "agent-site",
            escapes="the refusal is for other systems: its test is skipped on Windows and runs in CI on Linux",
        ),
        e(
            "an attempt survives a different account at the other end",
            LINK_ROUTE,
            "        if attempt.account != account:\n",
            "        if False:\n",
            "agent-site",
        ),
        e(
            "attempts never expire",
            LINK_ROUTE,
            "            if now - attempt.started > ATTEMPT_SECONDS:\n",
            "            if False:\n",
            "agent-site",
        ),
        e(
            "attempts are never bounded",
            LINK_ROUTE,
            "        while len(self.attempts) >= MAX_ATTEMPTS:\n",
            "        while False:\n",
            "agent-site",
        ),
        e(
            "the callback's state is not checked",
            LINK_ROUTE,
            '        if request.query_params.get("state") != attempt.state:\n',
            "        if False:\n",
            "agent-site",
        ),
        e(
            "a callback carrying an error is read as a sign-in",
            LINK_ROUTE,
            '        if request.query_params.get("error"):\n',
            "        if False:\n",
            "agent-site",
        ),
        e(
            "a callback with no code goes on",
            LINK_ROUTE,
            "        if not code:\n",
            "        if False:\n",
            "agent-site",
        ),
        e(
            "the root's refusal of the code is not noticed",
            LINK_ROUTE,
            "    if answer.status_code != 200:\n",
            "    if False:\n",
            "agent-site",
        ),
        e(
            "the ID token's nonce is not checked",
            LINK_ROUTE,
            '    if claims.get("nonce") != attempt.nonce:\n',
            "    if False:\n",
            "agent-site",
        ),
        Sabotage(
            "the ID token's audience is not checked",
            (
                (LINK_ROUTE, "            audience=CLIENT_ID,\n", ""),
                (
                    LINK_ROUTE,
                    '            options={"require": ["iss", "sub", "aud", "exp", "iat"]},\n',
                    '            options={"require": ["iss", "sub", "aud", "exp", "iat"], "verify_aud": False},\n',
                ),
            ),
            "agent-site",
        ),
        e(
            "the ID token's issuer is not checked",
            LINK_ROUTE,
            "            issuer=_issuer(request),\n",
            "",
            "agent-site",
        ),
        e(
            "an ID token with no expiry is accepted",
            LINK_ROUTE,
            '            options={"require": ["iss", "sub", "aud", "exp", "iat"]},\n',
            '            options={"require": ["iss", "sub", "aud", "iat"]},\n',
            "agent-site",
        ),
        e(
            "the role claim is not checked on the link page",
            LINK_ROUTE,
            '    if claims.get("eugene_role") != "member" or claims.get("sub") == "operator":\n',
            '    if claims.get("sub") == "operator":\n',
            "agent-site",
        ),
        e(
            "the owner's subject is not refused on the link page",
            LINK_ROUTE,
            '    if claims.get("eugene_role") != "member" or claims.get("sub") == "operator":\n',
            '    if claims.get("eugene_role") != "member":\n',
            "agent-site",
        ),
        e(
            "the confirmation's CSRF token is not compared",
            LINK_ROUTE,
            "        if csrf is None or not secrets.compare_digest(csrf, attempt.csrf) or attempt.person is None:\n",
            "        if csrf is None or attempt.person is None:\n",
            "agent-site",
        ),
        e(
            "a confirmation before any sign-in links someone",
            LINK_ROUTE,
            "        if csrf is None or not secrets.compare_digest(csrf, attempt.csrf) or attempt.person is None:\n",
            "        if csrf is None or not secrets.compare_digest(csrf, attempt.csrf):\n",
            "agent-site",
        ),
        e(
            "the removal's CSRF token is not compared",
            LINK_ROUTE,
            "        if found is None or csrf is None or not secrets.compare_digest(csrf, found[1].csrf):\n",
            "        if found is None:\n",
            "agent-site",
        ),
        e(
            "removing a link removes whoever is first, not this account's",
            LINK_ROUTE,
            "        link = store.for_account(account)\n        if link is not None:\n            store.remove(link.subject)\n",
            "        link = (store.load() or [None])[0]\n        if link is not None:\n            store.remove(link.subject)\n",
            "agent-site",
        ),
        e(
            "the page's cookie is sent on cross-site requests",
            LINK_ROUTE,
            'samesite="strict"',
            'samesite="none"',
            "agent-site",
        ),
        e(
            "the page's cookie is readable by scripts",
            LINK_ROUTE,
            "        COOKIE, key, httponly=True,",
            "        COOKIE, key, httponly=False,",
            "agent-site",
        ),
        e(
            "the page may be framed",
            LINK_ROUTE,
            '            "X-Frame-Options": "DENY",\n',
            "",
            "agent-site",
        ),
        e(
            "the link is made with no list of Eugene's own accounts",
            LINK_ROUTE,
            "                never=supervisor.never_linked(),\n",
            "                never=frozenset(),\n",
            "agent-site",
        ),
        e(
            "the link page is offered whenever there is a site host",
            LINK_ROUTE,
            "    return bool(supervisor is not None and supervisor.link_page_offered())\n",
            "    return supervisor is not None\n",
            "agent-site",
        ),
        e(
            "anyone may ask the agent to remove a link",
            LINK_ROUTE,
            '@api.delete("/v1/site/links/{subject}", status_code=204, dependencies=[Depends(require_control)])\n',
            '@api.delete("/v1/site/links/{subject}", status_code=204)\n',
            "agent-site",
        ),
        e(
            "the root removes a link on a machine where root links people",
            LINK_ROUTE,
            '    if supervisor is not None and supervisor.mode() == "root":\n',
            "    if False:\n",
            "agent-site",
        ),
        e(
            "any bearer may do what only the control root may",
            DEPENDENCIES,
            '    if _is_control(claims):\n        return claims\n    raise _refuse(claims, "do this; only the control root may")\n',
            "    return claims\n",
            "agent-site",
        ),
        e(
            "a service token from any issuer is the control root",
            DEPENDENCIES,
            "        and claims.iss == tokens.ISSUER_CONTROL\n",
            "",
            "agent-site",
        ),
        e(
            "a service token with any subject is the control root",
            DEPENDENCIES,
            "        and claims.sub == tokens.SUB_CONTROL\n",
            "",
            "agent-site",
        ),
        # --- agent: the machine's own CLI ----------------------------------------------
        e(
            "SYSTEM links itself when it runs the link",
            SITE_CLI,
            '    mine = _own_sid()\n    if mine == "S-1-5-18":\n',
            "    mine = _own_sid()\n    if False:\n",
            "agent-site",
        ),
        e(
            "root links root when it runs the link",
            SITE_CLI,
            '    if sys.platform != "win32" and mine == "0":\n',
            "    if False:\n",
            "agent-site",
        ),
        e(
            "a system install is taken for a person's",
            SITE_CLI,
            "        return where.startswith(program_data)\n",
            "        return False\n",
            "agent-site",
        ),
        e(
            "joining a system install needs no administrator",
            SITE_CLI,
            "    if _system_install(config_dir):\n        _need_elevation()\n    password = _password(args)\n",
            "    password = _password(args)\n",
            "agent-site",
        ),
        e(
            "leaving a system install needs no administrator",
            SITE_CLI,
            "    if _system_install(config_dir):\n        _need_elevation()\n    python = Path(args.python) if args.python else _host_python(config_dir)\n",
            "    python = Path(args.python) if args.python else _host_python(config_dir)\n",
            "agent-site",
        ),
        e(
            "linking someone needs no administrator",
            SITE_CLI,
            "\n    _need_elevation()\n    python = Path(args.python)",
            "\n    python = Path(args.python)",
            "agent-site",
        ),
        e(
            "unlinking someone needs no administrator",
            SITE_CLI,
            "def unlink(config_dir: Path, person: str) -> str:\n    _need_elevation()\n",
            "def unlink(config_dir: Path, person: str) -> str:\n",
            "agent-site",
        ),
        e(
            "the agent joins a Linux system install, which is root's",
            SITE_CLI,
            'if sys.platform == "linux" and _system_install(config_dir):\n        raise SiteError(\n            "On a Linux system install root makes',
            'if False:\n        raise SiteError(\n            "On a Linux system install root makes',
            "agent-site",
        ),
        e(
            "the agent links people on a Linux system install, which is root's",
            SITE_CLI,
            'if sys.platform == "linux" and _system_install(config_dir):\n        raise SiteError(\n            "On a Linux system install root links',
            'if False:\n        raise SiteError(\n            "On a Linux system install root links',
            "agent-site",
        ),
        e(
            "the agent edits root's local-server list on a Linux system install",
            SITE_CLI,
            'if sys.platform == "linux" and _system_install(config_dir):\n        raise SiteError(\n            "On a Linux system install root keeps',
            'if False:\n        raise SiteError(\n            "On a Linux system install root keeps',
            "agent-site",
        ),
        e(
            "removing a local server on Linux ignores root's ownership of the list",
            SITE_CLI,
            "def remove_server(config_dir: Path, server_id: str) -> str:\n    _root_owns_the_list(config_dir)\n",
            "def remove_server(config_dir: Path, server_id: str) -> str:\n",
            "agent-site",
        ),
        e(
            "SYSTEM may be linked as the owner's account",
            SITE_CLI,
            '    accounts = {"S-1-5-18"}\n',
            "    accounts: set[str] = set()\n",
            "agent-site",
        ),
        e(
            "leaving a site keeps its links",
            SITE_CLI,
            "    for entry in links.load():\n        links.remove(entry.subject)\n    return \"This machine is no longer a job site.",
            "    for entry in []:\n        links.remove(entry.subject)\n    return \"This machine is no longer a job site.",
            "agent-site",
        ),
        # --- agent: the entry point's public paths ---------------------------------------
        e(
            "a node's enrollment is reachable from anywhere",
            ENTRY,
            '        "/v1/sites/enroll",\n',
            '        "/v1/sites/enroll",\n        "/v1/nodes/enroll",\n',
            "agent-site",
        ),
        e(
            "the trust bundle is reachable from anywhere",
            ENTRY,
            '    "GET": ["/v1/trust/tls"],\n',
            '    "GET": ["/v1/trust/tls", "/v1/trust/bundle"],\n',
            "agent-site",
        ),
        e(
            "a machine's person check is not reachable from the site",
            ENTRY,
            '        "/v1/sites/links/check",\n',
            "",
            "agent-site",
        ),
        # --- control: the built-in client (J37) ---------------------------------------
        e(
            "the link client accepts localhost",
            OIDC,
            '_SITE_LINK_REDIRECT = re.compile(r"http://127[.]0[.]0[.]1:',
            '_SITE_LINK_REDIRECT = re.compile(r"http://(?:127[.]0[.]0[.]1|localhost):',
            "control-links",
        ),
        e(
            "the link client's redirect may carry more after the path",
            OIDC,
            "_SITE_LINK_REDIRECT.fullmatch(uri)",
            "_SITE_LINK_REDIRECT.match(uri)",
            "control-links",
        ),
        e(
            "the link client's redirect may use a port above 65535",
            OIDC,
            "    return match is not None and int(match.group(1)) <= 65535\n",
            "    return match is not None\n",
            "control-links",
        ),
        e(
            "the link client may redirect anywhere",
            OIDC,
            "    if client.get(\"builtin\"):\n        return is_site_link_redirect(uri)\n",
            '    if client.get("builtin"):\n        return True\n',
            "control-links",
        ),
        e(
            "the link client may present a secret in a header",
            OIDC_ROUTE,
            '        if scheme == "basic" or form.get("client_secret") is not None:\n',
            '        if form.get("client_secret") is not None:\n',
            "control-links",
        ),
        e(
            "the link client may present a secret in the form",
            OIDC_ROUTE,
            '        if scheme == "basic" or form.get("client_secret") is not None:\n',
            '        if scheme == "basic":\n',
            "control-links",
        ),
        e(
            "the link client gets a refresh token",
            OIDC_ROUTE,
            "                with_refresh=not builtin,\n",
            "                with_refresh=True,\n",
            "control-links",
        ),
        e(
            "the link client may use any grant",
            OIDC_ROUTE,
            '    if builtin and grant != "authorization_code":\n',
            "    if False:\n",
            "control-links",
        ),
        e(
            "the app list applies to the link client",
            OIDC_ROUTE,
            '        and not client.get("builtin")\n        and not oidc.may_use(',
            "        and not oidc.may_use(",
            "control-links",
        ),
        e(
            "the app list is skipped for every client",
            OIDC_ROUTE,
            '        and not client.get("builtin")\n        and not oidc.may_use(',
            "        and False\n        and not oidc.may_use(",
            "control-links",
        ),
        e(
            "Eugene's owner may use the link client",
            OIDC_ROUTE,
            '    if client.get("builtin") and subject is oidc.OWNER:\n',
            "    if False:\n",
            "control-links",
        ),
        # --- control: the check of a person typed at a machine (J36) ------------------------
        e(
            "a check is not counted per site",
            SITES,
            '    buckets = [LINK_CHECK_SITE_BUCKET + site.id, f"oidc-name:{name.casefold()}"]\n',
            '    buckets = [f"oidc-name:{name.casefold()}"]\n',
            "control-links",
        ),
        e(
            "a check is not counted per name",
            SITES,
            '    buckets = [LINK_CHECK_SITE_BUCKET + site.id, f"oidc-name:{name.casefold()}"]\n',
            "    buckets = [LINK_CHECK_SITE_BUCKET + site.id]\n",
            "control-links",
        ),
        e(
            "a failed check is not counted",
            SITES,
            "        for bucket in buckets:\n            auth.record_login_failure(\n",
            "        for bucket in []:\n            auth.record_login_failure(\n",
            "control-links",
        ),
        e(
            "a check of Eugene's owner goes on",
            SITES,
            "    if name.casefold() == oidc.OPERATOR_NAME:\n",
            "    if False:\n",
            "control-links",
        ),
        e(
            "a check of a person whose sign-in is off passes",
            SITES,
            '    if person.get("disabled"):\n        raise problem(\n            403,\n            "Signing in is turned off",\n            f"{person[\'name\']} cannot sign in on this install, so cannot link an account.",',
            '    if False:\n        raise problem(\n            403,\n            "Signing in is turned off",\n            f"{person[\'name\']} cannot sign in on this install, so cannot link an account.",',
            "control-links",
        ),
        e(
            "a wrong name is answered differently from a wrong password",
            SITES,
            "    verifier = person[\"passwordVerifier\"] if person else _DUMMY_VERIFIER\n",
            '    if person is None:\n        raise problem(401, "No such person", "Nobody has that name.")\n'
            '    verifier = person["passwordVerifier"] if person else _DUMMY_VERIFIER\n',
            "control-links",
        ),
        e(
            "a check is answered while Eugene is locked",
            SITES,
            "    if auth.signing_key is None:\n"
            '        raise problem(503, "Eugene is locked", "Unlock Eugene before linking people.")\n',
            "",
            "control-links",
            escapes="a locked root is refused earlier, by the site-token dependency (dependencies.py)",
        ),
        # --- control: removing a link (§3.2) ----------------------------------------------
        e(
            "anyone may remove anyone's link",
            SITES,
            "    if target != subject and not owns:\n",
            "    if False:\n",
            "control-links",
        ),
        e(
            "the site's owner may only remove their own link",
            SITES,
            "    target = body.person or subject\n",
            "    target = subject\n",
            "control-links",
        ),
        e(
            "anyone signed in may remove links on any site",
            SITES,
            "    if record is None or not (owns or helpers.may_use_site(summary, subject)):\n",
            "    if record is None:\n",
            "control-links",
        ),
        e(
            "a site the person has no part in is a different answer from no site",
            SITES,
            "    if record is None or not (owns or helpers.may_use_site(summary, subject)):\n"
            '        raise problem(404, "No such job site", "You have no such job site.")\n',
            "    if record is None or not (owns or helpers.may_use_site(summary, subject)):\n"
            '        raise problem(403, "Not yours", "That site is not yours.")\n',
            "control-links",
        ),
        e(
            "a removal made only at the machine looks like it was done",
            SITES,
            "    if code == 409:\n        raise problem(409, \"Removed at the machine only\", _agent_words(payload))\n",
            "",
            "control-links",
        ),
        # --- control: what a person is told about their link ----------------------------------
        e(
            "everyone is told they are linked when the owner is",
            BROKER,
            '    mine = next((entry for entry in links if entry.get("subject") == subject), None)\n',
            '    mine = next((entry for entry in links if entry.get("subject") == owner), None)\n',
            "control-links",
        ),
        e(
            "a linked person is told where to link",
            BROKER,
            '    if mine is not None:\n        return {"linked": True, "account": mine.get("accountName"), "linkPage": None}\n',
            '    if mine is not None:\n        return {"linked": True, "account": mine.get("accountName"), "linkPage": (summary or {}).get("linkPage")}\n',
            "control-links",
        ),
        e(
            "an unlinked person is not told whose account their calls run as",
            BROKER,
            '        "account": theirs.get("accountName") if theirs else None,\n',
            '        "account": None,\n',
            "control-links",
        ),
        e(
            "a site that says nothing about links is reported as having none",
            BROKER,
            "    if reported is None:\n        # A site that predates linking says nothing about it; neither do we.\n        return {}\n",
            "    if reported is None:\n        reported = []\n",
            "control-links",
        ),
        e(
            "a person who is only linked is not told the site exists",
            BROKER,
            '        or any(entry.get("subject") == subject for entry in (summary or {}).get("links") or [])\n',
            "",
            "control-links",
        ),
        e(
            "the link page's address is not passed to the owner's console",
            SITES,
            '("links", "linkPage", "sharing")',
            '("links", "sharing")',
            "control-links",
        ),
    ]
)


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
    elif only and only.startswith("--labels="):
        wanted = set(Path(only.split("=", 1)[1]).read_text(encoding="utf-8").splitlines())
        chosen = [s for s in SABOTAGES if s.label in wanted]
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
