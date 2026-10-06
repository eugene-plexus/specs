"""Job Sites, slices 1 and 2 (docs/design/remote-nodes.md §3.4, §5, §6.2,
§6.3): a machine on another network joins over the public node route, its
files are its owner's, and what it runs is decided on the machine (J8): MCP
between site and root (J6), one file server per machine whose tools take a
folder (J6g), and local servers its administrator added at it.

**The root** is the real control root behind the real entry point: Caddy
2.11.7 (pinned, checksum-verified) running the configuration the agent's own
`caddy_config` generates for a bare-address nodes origin with `public_nodes`,
in front of `control` with the nodes origin and probe the agent hands it. The
names Caddy answers for its own networks are a TEST-NET range, so every
connection the site makes is a public one.

**The site** is a real agent: joined with the real CLI (`join --job-site`,
the owner's password on stdin), then started and left to run, so its own
trust-bundle pull and its own file-helper poll cross the public route, pinned
to the root's identity key (J7a). Nothing listens for it but loopback.

**The files** then run through the agent's real relay (`SiteHostRelay`) and
the real site host, installed from this checkout of `site-host` the way the
agent installs it (`EUGENE_PLEXUS_AGENT_SITE_HOST_SOURCE`) and started with
the environment the relay builds, over that real public route with the pins
the site saved: a service install's OS account is the one thing a test
process cannot give the site agent itself (C1's disposable runners own that
check), so the host is started here rather than by the site agent's app
manager. A local server is added the way `eugene-plexus-agent site server
add` adds one after its elevation check (the check itself is the agent's unit
test); the host learns it at its next start, as the agent restarts it.

**Editing the root's state** is played by a hook this script adds to the root
it hosts (`/acceptance/forge`, on the control port, loopback only): it queues
an operation the root's own checks would not, and it names a different owner
for the site. Rule 2 of §3.3 says neither is enough to get in.

**Workbench** is played by a client with Workbench's own credentials: a
registered sign-in client and each person's refresh token from the real
sign-in page, calling the routes Workbench calls. Workbench's own half (the
mode line, the redaction) is its own test suite's.

Topologies:
* Linux, one host (CI): `python job-sites-acceptance.py`.
* Windows with WSL2 (the doc's stand-in): `python job-sites-acceptance.py
  --root-wsl`. The root runs in WSL2 behind its NAT with one port reached
  through it; the site is this Windows machine.

Everything uses temporary directories and free ports, clears the ambient
`EUGENE_PLEXUS_*` environment, and never touches an installed Eugene. No child
inherits this script's standard input: from Git Bash on Windows that is a pipe,
and two children hung at start on it (the site agent, and the build backend
uv ran for the site host).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PASSPHRASE = "a long passphrase for job sites"
PASSWORD = "ada's own long password"
CALLBACK = "http://127.0.0.1:9/callback"
LAN = ["203.0.113.0/24"]  # TEST-NET-3: the root's own networks, which the site is never in
CADDY_VERSION = "2.11.7"
SPECS = Path(__file__).resolve().parents[1]
REPOS = SPECS.parent
PASSES: list[str] = []


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


def clean_environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


for _name in [n for n in os.environ if n.startswith("EUGENE_PLEXUS_")]:
    os.environ.pop(_name)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------- #
# The root (POSIX: the entry point is the Linux container's)
# --------------------------------------------------------------------------- #


def caddy_binary(cache: Path) -> Path:
    found = shutil.which("caddy")
    if found and CADDY_VERSION in subprocess.run(
        [found, "version"], capture_output=True, text=True, stdin=subprocess.DEVNULL
    ).stdout:
        return Path(found)
    target = cache / "caddy"
    if target.exists():
        return target
    machine = {"x86_64": "amd64", "aarch64": "arm64"}[os.uname().machine]
    name = f"caddy_{CADDY_VERSION}_linux_{machine}.tar.gz"
    sums = (SPECS / "docker/caddy-checksums.sha512").read_text(encoding="utf-8")
    expected = next(line.split()[0] for line in sums.splitlines() if line.endswith(name))
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    urllib.request.urlretrieve(
        f"https://github.com/caddyserver/caddy/releases/download/v{CADDY_VERSION}/{name}", archive
    )
    if hashlib.sha512(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit(f"{name} does not match its pinned checksum")
    with tarfile.open(archive) as tar:
        tar.extract("caddy", cache)
    archive.unlink()
    target.chmod(0o755)
    return target


def serve_root(directory: Path) -> None:
    """Run the root until `stop` appears. Writes `ready.json` when serving."""
    import uvicorn
    from eugene_plexus_agent.entrypoint import EntryConfig, caddy_config
    from eugene_plexus_control.app import create_app
    from eugene_plexus_control.settings import Settings

    spec = json.loads((directory / "root.json").read_text(encoding="utf-8"))
    ip, port, control_port = spec["ip"], int(spec["port"]), int(spec["controlPort"])
    entry = EntryConfig.model_validate(
        {
            "listen_port": port,
            "internal_ca": True,
            "console_direct": True,
            "console": {"origin": f"https://eugene.job-sites.test:{port}", "networks": LAN},
            "workbench": {"origin": f"https://workbench.job-sites.test:{port}", "networks": LAN},
            "nodes": {"origin": f"https://{ip}:{port}", "networks": LAN},
            "public_nodes": True,
        }
    )
    assert entry.nodes is not None
    # State on this host's own filesystem: Caddy's admin socket cannot live
    # on a drive WSL mounts from Windows. Only the hand-off files are shared.
    state = Path(tempfile.mkdtemp(prefix="ep-job-sites-root-"))
    settings = Settings(
        config_file=state / "control.yaml",
        state_dir=state / "control-state",
        nodes_origin=entry.nodes.origin,
        nodes_public=True,
        nodes_probe=f"127.0.0.1:{port}",
    )
    app = create_app(settings)
    forge_hook(app)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=control_port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    work = state / "caddy"
    work.mkdir(mode=0o700)
    document = caddy_config(
        entry, work, secrets.token_urlsafe(16), {"agent": free_port(), "control": control_port}
    )
    (work / "caddy.json").write_text(json.dumps(document), encoding="utf-8")
    caddy = subprocess.Popen(
        [str(caddy_binary(Path(spec["cache"]))), "run", "--config", str(work / "caddy.json")],
        stdout=subprocess.DEVNULL,
        stderr=open(state / "caddy.log", "wb"),  # noqa: SIM115
    )
    try:
        deadline = time.perf_counter() + 30
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    pass
                with socket.create_connection(("127.0.0.1", control_port), timeout=1):
                    break
            except OSError:
                if time.perf_counter() > deadline or caddy.poll() is not None:
                    log = (state / "caddy.log").read_text(errors="replace")[-2000:]
                    raise SystemExit("the root did not start:\n" + log) from None
                time.sleep(0.2)
        (directory / "ready.json").write_text(
            json.dumps(
                {"controlUrl": f"http://127.0.0.1:{control_port}", "nodesUrl": entry.nodes.origin}
            ),
            encoding="utf-8",
        )
        while not (directory / "stop").exists():
            time.sleep(0.3)
    finally:
        caddy.terminate()
        server.should_exit = True
        thread.join(timeout=10)
        shutil.rmtree(state, ignore_errors=True)


def forge_hook(app: Any) -> None:
    """Stand in for an owner who edits the root's state directly (rule 2 of
    §3.3): queue an operation the root's routes would refuse, or name another
    owner for a site. Harness only: the root this script hosts, its loopback
    control port."""
    from dataclasses import replace

    from eugene_plexus_control import node_helpers as helpers

    async def forge(body: dict[str, Any]) -> dict[str, Any]:
        machine = app.state.machine
        if body["kind"] == "owner":
            record = machine.state.nodes[body["node"]]
            nodes = {**machine.state.nodes, body["node"]: replace(record, owner=body["owner"])}
            machine._state = replace(machine.state, nodes=nodes)
            return {"owner": body["owner"]}
        config = helpers.configuration(machine.state, body["node"])
        broker = app.state.node_helper_broker
        envelope = helpers.envelope(
            machine.state,
            config,
            body["subject"],
            server=body["server"],
            request=body["request"],
            grants=body.get("grants") or [],
        )
        return await broker.submit(config, lambda: envelope, write=True)

    app.add_api_route("/acceptance/forge", forge, methods=["POST"])


# --------------------------------------------------------------------------- #
# Playing Workbench: its client credentials and a person's own sign-in
# --------------------------------------------------------------------------- #


def sign_in(http: Any, control: str, client: dict[str, Any], name: str, password: str) -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    page = http.get(
        f"{control}/oidc/authorize",
        params={
            "response_type": "code",
            "client_id": client["client"]["clientId"],
            "redirect_uri": CALLBACK,
            "scope": "openid profile",
            "state": "s",
            "nonce": "n",
            "code_challenge": challenge.rstrip(b"=").decode(),
            "code_challenge_method": "S256",
        },
    )
    request = re.search(r'name="request" value="([^"]+)"', page.text)
    assert request, page.text[:300]
    answer = http.post(
        f"{control}/oidc/authorize",
        data={"request": request.group(1), "name": name, "password": password},
        follow_redirects=False,
    )
    assert answer.status_code == 302, answer.text[:300]
    code = re.search(r"code=([^&]+)", answer.headers["location"])
    assert code
    tokens = http.post(
        f"{control}/oidc/token",
        auth=(client["client"]["clientId"], client["clientSecret"]),
        data={
            "grant_type": "authorization_code",
            "code": code.group(1),
            "code_verifier": verifier,
            "redirect_uri": CALLBACK,
        },
    )
    assert tokens.status_code == 200, tokens.text
    return str(tokens.json()["refresh_token"])


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """One MCP request of the 2026-07-28 revision, as Workbench sends it."""
    return {
        "jsonrpc": "2.0",
        "id": secrets.token_hex(4),
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


class Workbench:
    def __init__(self, http: Any, control: str, client: dict[str, Any]) -> None:
        self.http, self.control, self.client = http, control, client

    def call(self, route: str, token: str, /, **body: Any) -> Any:
        return self.http.post(
            f"{self.control}/oidc/{route}",
            auth=(self.client["client"]["clientId"], self.client["clientSecret"]),
            json={"refreshToken": token, **body},
            timeout=40,
        )

    def mcp(self, token: str, server: str, method: str, params: dict[str, Any] | None = None) -> Any:
        return self.call("sites/mcp", token, node="desk", server=server, request=rpc(method, params))


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def wsl_path(path: Path) -> str:
    drive, rest = path.resolve().drive, path.resolve().as_posix()[2:]
    return f"/mnt/{drive[0].lower()}{rest}"


def start_root(work: Path, wsl: bool, ip: str, port: int, control_port: int) -> Any:
    (work / "root.json").write_text(
        json.dumps(
            {
                "ip": ip,
                "port": port,
                "controlPort": control_port,
                "cache": "~/.cache/ep-job-sites" if wsl else str(work / "cache"),
            }
        ),
        encoding="utf-8",
    )
    if wsl:
        venv = os.environ.get("EP_WSL_PYTHON", "~/.cache/ep-job-sites/venv/bin/python")
        script = wsl_path(Path(__file__))
        cache = json.loads((work / "root.json").read_text())["cache"]
        spec = json.loads((work / "root.json").read_text())
        spec["cache"] = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "bash", "-lc", f"echo {cache}"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        ).stdout.strip()
        (work / "root.json").write_text(json.dumps(spec), encoding="utf-8")
        command = ["wsl", "-d", "Ubuntu", "--", "bash", "-lc",
                   f"env -u EUGENE_PLEXUS_AGENT_CONFIG_FILE {venv} {script} --serve-root {wsl_path(work)}"]
    else:
        command = [sys.executable, __file__, "--serve-root", str(work)]
    return subprocess.Popen(
        command, env=clean_environment(), stdout=open(work / "root.out", "wb"),  # noqa: SIM115
        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    )


def routable(wsl: bool) -> str:
    if wsl:
        out = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "hostname", "-I"], capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
        ).stdout.split()
        return out[0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        return str(sock.getsockname()[0])


def agent_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "eugene_plexus_agent", *args]


def run(args: argparse.Namespace) -> None:
    import httpx

    from eugene_plexus_agent import root_tls

    work = Path(tempfile.mkdtemp(prefix="ep-job-sites-"))
    ip = routable(args.root_wsl)
    port, control_port = free_port(), free_port()
    root = start_root(work, args.root_wsl, ip, port, control_port)
    site_process: subprocess.Popen[bytes] | None = None
    worker: subprocess.Popen[bytes] | None = None
    try:
        deadline = time.perf_counter() + 90
        while not (work / "ready.json").exists():
            if root.poll() is not None or time.perf_counter() > deadline:
                raise SystemExit("the root did not start:\n" + (work / "root.out").read_text())
            time.sleep(0.3)
        ready = json.loads((work / "ready.json").read_text())
        control, nodes = ready["controlUrl"], ready["nodesUrl"]
        http = httpx.Client(trust_env=False, timeout=30)
        unverified = httpx.Client(trust_env=False, timeout=30, verify=False)

        # ---- the owner sets the root up ----------------------------------
        assert http.post(f"{control}/v1/auth/initialize", json={"passphrase": PASSPHRASE}).status_code == 204
        session = http.post(f"{control}/v1/auth/login", json={"passphrase": PASSPHRASE}).json()
        http.headers["Authorization"] = "Bearer " + session["sessionToken"]
        client = http.post(
            f"{control}/v1/oidc/clients",
            json={"name": "Workbench", "owner": "app:workbench@root", "redirectUris": [CALLBACK]},
        ).json()
        app_id = client["client"]["clientId"]
        for name in ("ada", "bo"):
            made = http.post(
                f"{control}/v1/people",
                json={"name": name, "password": PASSWORD, "apps": [app_id]},
            )
            assert made.status_code == 201, made.text
        plain = httpx.Client(trust_env=False, timeout=30)
        workbench = Workbench(plain, control, client)
        ada = sign_in(plain, control, client, "ada", PASSWORD)
        bo = sign_in(plain, control, client, "bo", PASSWORD)
        owner = sign_in(plain, control, client, "operator", PASSPHRASE)
        ok("the root is set up: two people and Workbench's sign-in")

        # ---- J3: the public route carries the node paths only --------------
        refused = unverified.get(f"{nodes}/v1/nodes")
        assert refused.status_code == 403 and "machines only" in refused.text, refused.text
        assert unverified.post(f"{nodes}/v1/auth/login", json={}).status_code == 403
        assert unverified.get(f"{nodes}/v1/trust/bundle").status_code == 401
        ok("from another network the nodes name refuses the API, sign-in, and an untokened bundle")

        # ---- J7a: the signed TLS list ---------------------------------------
        invite = workbench.call("job-sites/invite", ada, nodeName="desk")
        assert invite.status_code == 200, invite.text
        invitation = invite.json()
        assert invitation["nodesUrl"] == nodes
        claims = asyncio.run(root_tls.fetch_list(nodes, invitation["rootKey"]))
        assert claims["origin"] == nodes and claims["keys"]
        ok("the root signs the TLS key its bare-address nodes name presents, and it verifies")
        refused = workbench.call("job-sites/invite", owner)
        assert refused.status_code == 403, refused.text
        ok("J9: a person invites their own machine from Workbench; Eugene's owner cannot")

        # ---- a leaked token: nothing without the person --------------------
        site = work / "site"
        site.mkdir()
        site_env = {
            **clean_environment(),
            "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(site / "agent.yaml"),
            "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(site / "engines"),
        }
        join = [
            "join", "--control", nodes, "--token", invitation["token"], "--name", "desk",
            "--job-site", "--owner", "ada", "--password-stdin",
        ]
        wrong_key = subprocess.run(
            agent_command(*join, "--root-key", base64.b64encode(b"\x01" * 32).decode()),
            input=PASSWORD, capture_output=True, text=True, env=site_env, timeout=120,
        )
        assert wrong_key.returncode != 0 and "pinned key" in (wrong_key.stdout + wrong_key.stderr)
        ok("a join command naming another root's key sends nothing and records nothing")
        leaked = subprocess.run(
            agent_command(*join, "--root-key", invitation["rootKey"]),
            input="not her password", capture_output=True, text=True, env=site_env, timeout=120,
        )
        assert leaked.returncode != 0, leaked.stdout + leaked.stderr
        nodes_now = http.get(f"{control}/v1/nodes").json()["nodes"]
        assert "desk" not in {n["name"] for n in nodes_now}
        ordinary = http.post(f"{control}/v1/nodes/join-token", json={}).json()["token"]
        stray = subprocess.run(
            agent_command("join", "--control", nodes, "--token", ordinary, "--name", "rogue",
                          "--root-key", invitation["rootKey"], "--job-site", "--owner", "ada",
                          "--password-stdin"),
            input=PASSWORD, capture_output=True, text=True,
            env={**site_env, "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(work / "rogue" / "agent.yaml")},
            timeout=120,
        )
        assert stray.returncode != 0
        assert "rogue" not in {n["name"] for n in http.get(f"{control}/v1/nodes").json()["nodes"]}
        ok("a leaked token yields nothing without its person's password, and an ordinary "
           "node's token cannot join from outside")

        # ---- the site joins, confirmed at the machine ----------------------
        joined = subprocess.run(
            agent_command(*join, "--root-key", invitation["rootKey"]),
            input=PASSWORD, capture_output=True, text=True, env=site_env, timeout=120,
        )
        assert joined.returncode == 0, joined.stdout + joined.stderr
        assert "jobSite: true" in (site / "node.yaml").read_text(encoding="utf-8")
        assert json.loads((site / root_tls.PINS_FILE).read_text())["origin"] == nodes
        assert PASSWORD not in "".join(p.read_text(errors="ignore") for p in site.rglob("*") if p.is_file())
        node = http.get(f"{control}/v1/nodes/desk").json()
        assert node["grants"] == ["files"] and node["ownerName"] == "ada" and not node.get("url")
        ada_id = node["owner"]
        assert f"siteOwner: {ada_id}" in (site / "node.yaml").read_text(encoding="utf-8")
        ok("the site joined over the public route as ada's, files only, with no address, and "
           "pinned her as its owner; her password is kept nowhere on it")

        # ---- the site runs, and only connects out --------------------------
        site_port = free_port()
        site_process = subprocess.Popen(
            agent_command("--unattended"),
            env={**site_env, "EUGENE_PLEXUS_AGENT_BIND_PORT": str(site_port)},
            stdin=subprocess.DEVNULL,
            stdout=open(work / "site.out", "wb"),  # noqa: SIM115
            stderr=subprocess.STDOUT,
        )
        deadline = time.perf_counter() + 60
        while True:
            try:
                if plain.get(f"http://127.0.0.1:{site_port}/healthz", timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if site_process.poll() is not None or time.perf_counter() > deadline:
                raise SystemExit(
                    f"the site agent did not start (exit {site_process.poll()}):\n"
                    + (work / "site.out").read_text(errors="replace")
                )
            time.sleep(0.3)
        # The site has no console; a token its own key signs for itself is
        # what reads it (the `files` grant's own-machine rule).
        from eugene_plexus_agent import tokens as agent_tokens
        from eugene_plexus_agent.node_identity import NodeIdentityStore

        site_store = NodeIdentityStore(site / "node.yaml")
        site_store.load()
        site_signer = agent_tokens.Signer(
            key=agent_tokens.load_private(str(site_store.record.token_private_key)),
            issuer="node:desk",
        )
        local, _ = site_signer.mint(
            typ=agent_tokens.TYP_SERVICE, sub="agent", aud=["node:desk"], ttl_seconds=3600
        )
        site_http = httpx.Client(
            trust_env=False, timeout=30, headers={"Authorization": f"Bearer {local}"}
        )
        identity = site_http.get(f"http://127.0.0.1:{site_port}/v1/node").json()
        assert identity["jobSite"] is True and identity.get("advertiseUrl") in (None, ""), identity
        lan_ip = routable(False)
        try:
            with socket.create_connection((lan_ip, site_port), timeout=2):
                raise AssertionError("the site answered on its network address")
        except OSError:
            pass
        ok("the site agent says it is a job site, has no address, and listens on loopback only")

        deadline = time.perf_counter() + 40
        while not http.get(f"{control}/v1/nodes/desk").json().get("lastContactAt"):
            if time.perf_counter() > deadline:
                raise AssertionError("the site never reached the root:\n" + (work / "site.out").read_text())
            time.sleep(1)
        node = http.get(f"{control}/v1/nodes/desk").json()
        assert node["lastError"] is None
        listed = http.get(f"{control}/v1/node-helpers").json()
        desk = next(h for h in listed["helpers"] if h["node"] == "desk")
        assert desk["jobSite"] and desk["hidden"] and desk["online"] and desk["folders"] == []
        ok("Eugene's owner sees it online, with its last contact, and nothing of its files")

        # The bundle reaches the site only by its own pull, through the
        # public route with its own token: remove another node and watch.
        before = site_http.get(f"http://127.0.0.1:{site_port}/v1/node").json()["trustBundleVersion"]
        throwaway = http.post(f"{control}/v1/nodes/join-token", json={}).json()["token"]
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        def key() -> str:
            raw = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            return base64.b64encode(raw).decode()

        http.post(
            f"{control}/v1/nodes/enroll",
            json={"token": throwaway, "name": "spare", "publicKey": key(),
                  "signingPublicKey": key(), "tokenPublicKey": key()},
        ).raise_for_status()
        revoked = http.delete(f"{control}/v1/nodes/spare").json()["version"]
        assert revoked > before
        deadline = time.perf_counter() + 75
        while site_http.get(f"http://127.0.0.1:{site_port}/v1/node").json()["trustBundleVersion"] < revoked:
            if time.perf_counter() > deadline:
                raise AssertionError("the site never pulled the new bundle")
            time.sleep(2)
        ok("the site pulls each new trust bundle itself, pinned, with its own token")

        placed = http.post(f"{control}/v1/runtimes", json={"node": "desk", "spec": {"name": "m"}})
        assert placed.status_code == 409, placed.text
        ok("J4: nothing runs on a job site")
        site_process.terminate()
        site_process.wait(timeout=30)
        site_process = None

        # ---- files: the real relay and site host over the real public route
        folder = work / "shared"
        folder.mkdir()
        (folder / "note.txt").write_text("Notes from ada's desk", encoding="utf-8")
        people = {p["name"]: p["id"] for p in http.get(f"{control}/v1/people").json()["people"]}
        host = SiteHost(work, site)
        asyncio.run(files_through_the_site(
            host, http, workbench, ada, bo, owner, folder, control, people
        ))
        worker = None
        left = workbench.call("job-sites/desk/leave", ada)
        assert left.status_code == 204
        assert "desk" not in {n["name"] for n in http.get(f"{control}/v1/nodes").json()["nodes"]}
        ok("ada takes her machine out herself; it is gone at once")
    finally:
        for process in (site_process, worker, *SiteHost.running):
            if process is not None and process.poll() is None:
                process.kill()
        (work / "stop").write_text("")
        try:
            root.wait(timeout=30)
        except subprocess.TimeoutExpired:
            root.kill()
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"kept {work}")


class SiteHost:
    """The site host, installed from the `site-host` checkout the way the
    agent installs it, and started with the environment the agent's relay
    builds; restarted, as the agent restarts it, when that changes."""

    running: list[subprocess.Popen[bytes]] = []

    def __init__(self, work: Path, site: Path) -> None:
        from eugene_plexus_agent import site_host
        from eugene_plexus_agent.apps import venv_python

        os.environ[site_host.SOURCE_OVERRIDE] = str(REPOS / "site-host")
        where, self.version = site_host.source()
        assert self.version.startswith("local-") and Path(where) == (REPOS / "site-host").resolve()
        uv = shutil.which("uv") or str(
            Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
        )
        env_dir = work / "site-host-env"
        subprocess.run([uv, "venv", "--python", "3.12", str(env_dir)], check=True,
                       capture_output=True, stdin=subprocess.DEVNULL)
        self.python = venv_python(env_dir)
        installed = subprocess.run(
            [uv, "pip", "install", "--python", str(self.python), where],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        assert installed.returncode == 0, installed.stderr[-2000:]
        self.site, self.port, self.token = site, free_port(), secrets.token_urlsafe(24)
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, environment: dict[str, str]) -> None:
        from eugene_plexus_agent.site_host import ENTRY, HELPER_ID

        self.stop()
        data = self.site / "apps" / HELPER_ID / "data"
        data.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            [str(self.python), "-m", ENTRY],
            cwd=data,
            stdin=subprocess.DEVNULL,
            env={
                **clean_environment(),
                **environment,
                "EUGENE_PLEXUS_APP_DATA_DIR": str(data),
                "EUGENE_PLEXUS_APP_BIND_PORT": str(self.port),
                "EUGENE_PLEXUS_APP_ADMIN_TOKEN": self.token,
                "EUGENE_PLEXUS_APP_ACCOUNT_KIND": "windows_service" if os.name == "nt" else "systemd",
            },
            stdout=subprocess.DEVNULL,
            stderr=open(self.site / "site-host.err", "ab"),  # noqa: SIM115
        )
        SiteHost.running.append(self.process)
        deadline = time.perf_counter() + 30
        while True:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return
            except OSError:
                if self.process.poll() is not None or time.perf_counter() > deadline:
                    raise SystemExit(
                        "the site host did not start:\n"
                        + (self.site / "site-host.err").read_text(errors="replace")[-2000:]
                    ) from None
                time.sleep(0.2)

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=20)


def site_relay(host: SiteHost) -> Any:
    """The agent's real relay, as the site's, over the real public route,
    with a stand-in for the app manager a service install would give it."""
    from eugene_plexus_agent import tokens
    from eugene_plexus_agent._generated.models import ComponentStatus
    from eugene_plexus_agent.apps import AppStore
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.root_tls import RootLink
    from eugene_plexus_agent.site_host import ENTRY, SiteHostRelay
    from fastapi import FastAPI

    store = NodeIdentityStore(host.site / "node.yaml")
    store.load()
    record = store.record
    signer = tokens.Signer(
        key=tokens.load_private(str(record.token_private_key)), issuer=f"node:{record.name}"
    )
    app = FastAPI()
    app.state.node_identity = store
    app.state.root_link = RootLink(store)
    app.state.settings = SimpleNamespace(config_file=host.site / "agent.yaml")
    app.state.auth_state = SimpleNamespace(
        trust=SimpleNamespace(
            agent_token=lambda aud: signer.mint(
                typ=tokens.TYP_SERVICE, sub="agent", aud=[aud], ttl_seconds=600
            )[0]
        )
    )
    kind = "windows_service" if os.name == "nt" else "systemd"
    apps = AppStore(host.site / "apps.yaml")
    installed = SimpleNamespace(
        enabled=True, port=host.port, version=host.version, manifest=SimpleNamespace(entry=ENTRY)
    )
    app.state.apps = SimpleNamespace(
        accounts=SimpleNamespace(available=True, kind=kind),
        store=SimpleNamespace(get=lambda _: installed, app_dir=apps.app_dir),
        supervisor=SimpleNamespace(
            status=lambda _: (ComponentStatus.running, None, None, None, None),
            admin_token=lambda _: host.token,
        ),
        installer=SimpleNamespace(snapshot=lambda _: None),
    )
    relay = SiteHostRelay(app)

    async def reconcile(_config: dict[str, Any]) -> None:
        # The agent restarts the host when what it is told changes.
        wanted = relay.environment(app.state.apps)
        if wanted is not None and wanted != getattr(relay, "_started_with", None):
            relay._started_with = wanted
            await asyncio.to_thread(host.start, wanted)

    relay.reconcile = reconcile  # type: ignore[method-assign]
    return relay


async def files_through_the_site(
    host: SiteHost, http: Any, workbench: Workbench, ada: str, bo: str, owner: str,
    folder: Path, control: str, people: dict[str, str],
) -> None:
    import yaml
    from eugene_plexus_agent import site_cli

    relay = site_relay(host)
    task = asyncio.create_task(relay.run())

    async def call(route: str, token: str, /, **body: Any) -> Any:
        return await asyncio.to_thread(lambda: workbench.call(route, token, **body))

    async def mcp(token: str, server: str, method: str, params: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(lambda: workbench.mcp(token, server, method, params))

    async def forge(**body: Any) -> Any:
        return await asyncio.to_thread(
            lambda: http.post(f"{control}/acceptance/forge", json={"node": "desk", **body})
        )

    async def settle(predicate: Any, what: str) -> dict[str, Any]:
        """The site's next report, which the root keeps as a cache."""
        deadline = time.perf_counter() + 30
        while True:
            sites = (await call("job-sites", ada)).json()["sites"]
            if sites and predicate(sites[0]):
                return dict(sites[0])
            if time.perf_counter() > deadline:
                raise AssertionError(f"{what}: {sites}")
            await asyncio.sleep(0.3)

    read = {"name": "read_text", "arguments": {"folder": "Notes", "path": "note.txt"}}
    try:
        # ---- the site keeps its own list ---------------------------------------
        assert (await call("job-sites/desk/enabled", ada, enabled=True)).status_code == 200
        await settle(lambda s: s["ready"], "the site host never became ready")
        added = await call(
            "job-sites/desk/folders", ada, name="Notes", path=str(folder), writable=True
        )
        assert added.status_code == 201, added.text
        folder_id = added.json()["id"]
        assert added.json()["people"] == []
        again = await call("job-sites/desk/folders", ada, name="notes", path=str(folder))
        assert again.status_code == 422 and "registered already" in again.text, again.text
        await settle(lambda s: s["folders"], "the site never reported its folder")
        ok("ada's site registers a folder itself, under a name unique on it, and nobody "
           "may use it yet")

        # ---- default deny, and an edit to the root's state grants nothing ------
        refused = await mcp(bo, "files", "tools/list")
        assert refused.status_code == 403, refused.text
        forged = await forge(kind="enqueue", subject=people["bo"], server="files",
                             request=rpc("tools/call", read))
        assert forged.status_code == 200, forged.text
        assert forged.json()["status"] == "failed" and "has not given you" in forged.json()["message"]
        ok("default deny: the site refuses bo even when the root itself sends his call (rule 2)")

        # ---- tools/list and a read through the public route --------------------
        granted = await call(f"job-sites/desk/folders/{folder_id}/people", ada,
                             people=[{"name": "ada", "writable": False}, {"name": "bo", "writable": False}])
        assert granted.status_code == 200, granted.text
        assert {p["name"] for p in granted.json()["people"]} == {"ada", "bo"}
        await settle(lambda s: len(s["folders"][0]["people"]) == 2, "the grant never reported")
        listed = await call("sites/servers", bo)
        files = next(s for s in listed.json()["servers"] if s["server"] == "files")
        assert files["jobSite"] and files["folders"] == [{"id": folder_id, "name": "Notes", "writable": False}]
        tools = await mcp(bo, "files", "tools/list")
        assert tools.status_code == 200, tools.text
        offered = {t["name"]: t["inputSchema"]["properties"]["folder"]["enum"]
                   for t in tools.json()["response"]["result"]["tools"]}
        assert offered == {"list_directory": ["Notes"], "read_text": ["Notes"]}, offered
        got = await mcp(bo, "files", "tools/call", read)
        body = got.json()
        assert got.status_code == 200 and body["status"] == "done", got.text
        assert "Notes from ada's desk" in json.dumps(body["response"])
        assert body["jobSite"] is True and body["installMode"] == "production"
        ok("tools/list and a read through the public route, by the site's own list, one file "
           "server whose folder argument names only bo's folders")

        # ---- a write needs a standing pre-approval -----------------------------
        write = {"name": "write_text", "arguments": {
            "folder": "Notes", "path": "note.txt", "text": "bo was here", "expectedSha256": ""}}
        denied = await mcp(bo, "files", "tools/call", write)
        assert denied.json()["status"] == "failed" and "not change files" in denied.json()["message"]
        assert (folder / "note.txt").read_text(encoding="utf-8") == "Notes from ada's desk"
        await call(f"job-sites/desk/folders/{folder_id}/people", ada,
                   people=[{"name": "ada", "writable": False}, {"name": "bo", "writable": True}])
        await settle(lambda s: any(p["writable"] for p in s["folders"][0]["people"]), "write grant")
        wrote = await mcp(bo, "files", "tools/call", {"name": "write_text", "arguments": {
            "folder": "Notes", "path": "new.txt", "text": "bo was here", "expectedSha256": ""}})
        assert wrote.json()["status"] == "done", wrote.text
        assert (folder / "new.txt").read_text(encoding="utf-8") == "bo was here"
        ok("a write needs the site owner's standing pre-approval, and runs with it")

        # ---- the audit log is the owner's alone ---------------------------------
        log = await call("job-sites/desk/audit", ada, limit=50)
        assert log.status_code == 200, log.text
        entries = log.json()["entries"]
        decided = {(e["subject"], e.get("tool"), e["decision"]) for e in entries}
        assert (people["bo"], "read_text", "refused") in decided
        assert (people["bo"], "write_text", "refused") in decided
        assert (people["bo"], "write_text", "allowed") in decided
        assert "bo was here" not in json.dumps(entries) and "Notes from ada" not in json.dumps(entries)
        for someone in (bo, owner):
            assert (await call("job-sites/desk/audit", someone)).status_code == 404
        ok("the site's audit log records who asked and what it decided, never contents, and only "
           "its owner reads it")

        # ---- the pinned owner holds ----------------------------------------------
        assert (await forge(kind="owner", owner=people["bo"])).status_code == 200
        await asyncio.sleep(2)  # a poll or two, each naming bo
        node_yaml = (host.site / "node.yaml").read_text(encoding="utf-8")
        assert f"siteOwner: {people['ada']}" in node_yaml
        taken = await call(f"job-sites/desk/folders/{folder_id}/people", bo,
                           people=[{"name": "bo", "writable": True}])
        assert taken.status_code == 422 and "Only this machine's owner" in taken.text, taken.text
        assert (await forge(kind="owner", owner=people["ada"])).status_code == 200
        ok("the site keeps the owner it pinned at its join when the root names someone else")

        # ---- a fifth tool, added at the machine ------------------------------------
        fixture = host.site / "local_server.py"
        fixture.write_bytes((REPOS / "site-host" / "tests" / "fixtures" / "local_server.py").read_bytes())
        if not site_cli.elevated():
            unelevated = subprocess.run(
                agent_command("site", "server", "add", "notes-tool", "--name", "Notes tool",
                              "--command", str(host.python), "--arg=-I", "--arg", str(fixture)),
                capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                env={**clean_environment(),
                     "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(host.site / "agent.yaml")},
            )
            assert unelevated.returncode != 0 and "administrator" in unelevated.stderr
        # What the CLI does after its elevation check: this process stands in
        # for the machine's administrator, whose check is the agent's unit test.
        elevated, site_cli.elevated = site_cli.elevated, lambda: True
        try:
            site_cli.add_server(host.site, server_id="notes-tool", name="Notes tool",
                                command=str(host.python), args=["-I", str(fixture)], env=[],
                                system=False)
        finally:
            site_cli.elevated = elevated
        listed = await settle(lambda s: s["servers"], "the local server never reported")
        assert listed["servers"][0]["server"]["id"] == "notes-tool"
        assert not listed["servers"][0]["server"]["enabled"]
        on = await call("job-sites/desk/servers/notes-tool/enabled", ada, enabled=True)
        assert on.status_code == 200, on.text
        assert {t["name"] for t in on.json()["server"]["tools"]} == {"echo", "touch"}
        plain = await call("job-sites/desk/servers/notes-tool/access", ada,
                           people=[{"name": "bo", "tools": [{"name": "touch"}]}])
        assert plain.status_code == 422 and "standing" in plain.text, plain.text
        given = await call("job-sites/desk/servers/notes-tool/access", ada,
                           people=[{"name": "bo", "tools": [{"name": "echo"}]}])
        assert given.status_code == 200, given.text
        await settle(lambda s: s["servers"][0]["people"], "the tool grant never reported")
        mine = await call("sites/servers", bo)
        assert any(s["server"] == "notes-tool" and s["kind"] == "local" for s in mine.json()["servers"])
        tools = await mcp(bo, "notes-tool", "tools/list")
        assert [t["name"] for t in tools.json()["response"]["result"]["tools"]] == ["echo"]
        echoed = await mcp(bo, "notes-tool", "tools/call", {"name": "echo", "arguments": {"text": "hi"}})
        assert echoed.json()["status"] == "done" and "echo: hi" in json.dumps(echoed.json()), echoed.text
        ok("a fifth tool, from a local server added at the machine, works through the same "
           "route, with no change to control, the agent or Workbench")

        # ---- J9: a system server needs an administrator's consent -----------------
        servers = yaml.safe_load((host.site / site_cli.SERVERS_FILE).read_text(encoding="utf-8"))
        servers["servers"].append({**servers["servers"][0], "id": "settings-tool",
                                   "name": "Settings tool", "system": True})
        (host.site / site_cli.SERVERS_FILE).write_text(yaml.safe_dump(servers), encoding="utf-8")
        await settle(lambda s: len(s["servers"]) == 2, "the system server never reported")
        system = await call("job-sites/desk/servers/settings-tool/enabled", ada, enabled=True)
        assert system.status_code == 422 and "consent" in system.text.lower(), system.text
        ok("J9: a server marked system will not turn on without an administrator's consent "
           "recorded at the machine")

        # ---- production: Eugene's owner cannot read it -----------------------------
        assert (await mcp(owner, "files", "tools/call", read)).status_code == 403
        patched = await asyncio.to_thread(
            http.patch, f"{control}/v1/node-helpers/desk/folders/{folder_id}", json={"ownerAccess": "read"}
        )
        assert patched.status_code == 403
        listing = (await asyncio.to_thread(http.get, f"{control}/v1/node-helpers")).json()
        desk = next(h for h in listing["helpers"] if h["node"] == "desk")
        assert desk["hidden"] and desk["folders"] == []
        ok("production: Eugene's owner cannot read it, by grant or by listing")

        # ---- dev mode: only with the site owner's opt-in (J6e) ---------------------
        switched = await asyncio.to_thread(http.patch, f"{control}/v1/config", json={"installMode": "dev"})
        assert switched.status_code == 200, switched.text
        listing = (await asyncio.to_thread(http.get, f"{control}/v1/node-helpers")).json()
        desk = next(h for h in listing["helpers"] if h["node"] == "desk")
        assert not desk["hidden"] and desk["folders"][0]["id"] == folder_id
        assert desk["ownerInDevMode"] is False
        patched = await asyncio.to_thread(
            http.patch, f"{control}/v1/node-helpers/desk/folders/{folder_id}", json={"ownerAccess": "read"}
        )
        assert patched.status_code == 200, patched.text
        # The root sends it (its grant exists, in dev mode); the site refuses it.
        closed = await mcp(owner, "files", "tools/call", read)
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "failed"
        assert "Dev mode alone opens nothing" in closed.json()["message"]
        opted = await call("job-sites/desk/settings", ada, ownerInDevMode=True)
        assert opted.status_code == 200, opted.text
        assert opted.json()["ownerInDevMode"] is True, opted.text
        await settle(lambda s: s["ownerInDevMode"], "the opt-in never reported")
        mine = await mcp(owner, "files", "tools/call", read)
        assert mine.status_code == 200 and mine.json()["status"] == "done", mine.text
        assert mine.json()["installMode"] == "dev"
        ok("dev mode: the owner grants themselves a folder, and it opens only once the site's "
           "owner lets them in there (J6e)")

        back = await asyncio.to_thread(http.patch, f"{control}/v1/config", json={"installMode": "production"})
        assert back.status_code == 200
        assert (await mcp(owner, "files", "tools/call", read)).status_code == 403
        ok("back in production the owner's own grant stops at once")
    finally:
        task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await task
        host.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-root", type=Path)
    parser.add_argument("--root-wsl", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.serve_root:
        serve_root(args.serve_root)
        return 0
    if os.name == "nt" and not args.root_wsl:
        raise SystemExit("on Windows the root runs in WSL2: pass --root-wsl")
    run(args)
    print(f"{len(PASSES)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
