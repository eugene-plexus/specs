"""Job Sites, slice 2b.1 (docs/design/job-sites-own-enrollment.md §0, §2.2,
§2.3, §3, §3.1): a Job Site is its own enrollment, held by the **site host**
program and never by a node. It joins a root with a site invitation that names
its owner, polls the root with its own key, and answers what the root queues
for it; its files are its owner's, and what it runs is decided on the machine
(slice 2's J6/J8, unchanged).

**The root** is the real control root behind the real entry point: Caddy
2.11.7 (pinned, checksum-verified) running the configuration the agent's own
`caddy_config` generates for a bare-address nodes origin with `public_sites`,
in front of `control` with the nodes origin and probe the agent hands it. The
names Caddy answers for its own networks are a TEST-NET range, so every
connection the site makes is a public one. A second control, with no entry
point in front of it and `siteJoinUrl` set to its own HTTP address, is the
LAN-only install (J31).

**The site** is the real site host (`site-host`), installed from a checkout the
way the agent installs it (`--site-host-source`, or `EP_SITE_HOST_SOURCE`, else
the sibling checkout, else the agent's pinned archive) and run with the
launch environment the agent builds. It joins with its own `join` command, the
owner's password as the first line of its standard input, pinned to the root's
identity key over HTTPS (J7a) and pinning nothing over plain HTTP. Then it
serves: it reads its enrollment from its data directory and polls the root
itself. No agent relays for it: a service install's OS account is the one
thing a test process cannot give it (C1's disposable runners own that check),
so the account kind is the one the agent would report for this OS.

**Editing the root's state** is played by a hook this script adds to the root
it hosts (`/acceptance/forge`, on the control port, loopback only): it queues
an operation the root's own checks would not (naming another owner, or another
enrollment of the same site), and it names a different owner for the site.
Rule 2 of §3.3 says neither is enough to get in.

**Workbench** is played by a client with Workbench's own credentials: a
registered sign-in client and each person's refresh token from the real
sign-in page, calling the routes Workbench calls. Workbench's own half is its
own test suite's.

Topologies:
* Linux, one host (CI): `python job-sites-acceptance.py`.
* Windows with WSL2 (the doc's stand-in): `python job-sites-acceptance.py
  --root-wsl`. The root runs in WSL2 behind its NAT with its ports reached
  through it; the site is this Windows machine.

Everything uses temporary directories and free ports, clears the ambient
`EUGENE_PLEXUS_*` environment, and never touches an installed Eugene. No child
inherits this script's standard input: from Git Bash on Windows that is a pipe,
and two children hung at start on it (the site agent, and the build backend
uv ran for the site host).
"""

from __future__ import annotations

import argparse
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
SITE_HOST_ENTRY = "eugene_plexus_site_host"


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
    lan_port = int(spec["lanPort"])
    entry = EntryConfig.model_validate(
        {
            "listen_port": port,
            "internal_ca": True,
            "console_direct": True,
            "console": {"origin": f"https://eugene.job-sites.test:{port}", "networks": LAN},
            "workbench": {"origin": f"https://workbench.job-sites.test:{port}", "networks": LAN},
            "nodes": {"origin": f"https://{ip}:{port}", "networks": LAN},
            "public_sites": True,
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
        nodes_probe=f"127.0.0.1:{port}",
    )
    app = create_app(settings)
    forge_hook(app)
    # The LAN-only install: no entry point, no nodes name (J31).
    lan_app = create_app(
        Settings(config_file=state / "lan.yaml", state_dir=state / "lan-state")
    )
    servers = [
        uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
        for a, p in ((app, control_port), (lan_app, lan_port))
    ]
    threads = [threading.Thread(target=s.run, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    work = state / "caddy"
    work.mkdir(mode=0o700)
    document = caddy_config(
        entry, work, secrets.token_urlsafe(16), {"agent": free_port(), "control": control_port}
    )
    (work / "caddy.json").write_text(json.dumps(document), encoding="utf-8")
    caddy = subprocess.Popen(
        [str(caddy_binary(Path(spec["cache"]))), "run", "--config", str(work / "caddy.json")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=open(state / "caddy.log", "wb"),  # noqa: SIM115
    )
    try:
        deadline = time.perf_counter() + 30
        while True:
            try:
                for where in (port, control_port, lan_port):
                    with socket.create_connection(("127.0.0.1", where), timeout=1):
                        pass
                break
            except OSError:
                if time.perf_counter() > deadline or caddy.poll() is not None:
                    log = (state / "caddy.log").read_text(errors="replace")[-2000:]
                    raise SystemExit("the root did not start:\n" + log) from None
                time.sleep(0.2)
        (directory / "ready.json").write_text(
            json.dumps(
                {
                    "controlUrl": f"http://127.0.0.1:{control_port}",
                    "nodesUrl": entry.nodes.origin,
                    "lanUrl": f"http://127.0.0.1:{lan_port}",
                }
            ),
            encoding="utf-8",
        )
        while not (directory / "stop").exists():
            time.sleep(0.3)
    finally:
        caddy.terminate()
        for server in servers:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=10)
        shutil.rmtree(state, ignore_errors=True)


def forge_hook(app: Any) -> None:
    """Stand in for an owner who edits the root's state directly (rule 2 of
    §3.3): queue an operation the root's routes would refuse, or name another
    owner for a site. Harness only: the root this script hosts, its loopback
    control port."""
    from dataclasses import replace

    from eugene_plexus_control import sites as helpers

    async def forge(body: dict[str, Any]) -> dict[str, Any]:
        machine = app.state.machine
        record = machine.state.sites[body["site"]]
        if body["kind"] == "owner":
            sites = {**machine.state.sites, record.id: replace(record, owner=body["owner"])}
            machine._state = replace(machine.state, sites=sites)
            return {"owner": body["owner"]}
        real = helpers.binding(record)
        named = {**real, "enrolledAt": body.get("enrolledAt") or real["enrolledAt"]}
        fields: dict[str, Any] = (
            {"kind": "manage", "action": body["action"], "arguments": body["arguments"]}
            if body["kind"] == "manage"
            else {
                "server": body["server"],
                "request": body["request"],
                "grants": body.get("grants") or [],
            }
        )
        envelope = helpers.envelope(machine.state, named, body["subject"], **fields)
        broker = helpers.broker(SimpleNamespace(app=app))
        return await broker.submit(real, lambda: envelope, write=True)

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

    def mcp(
        self, token: str, site: str, server: str, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        return self.call("sites/mcp", token, site=site, server=server, request=rpc(method, params))


# --------------------------------------------------------------------------- #
# The site host, installed from a checkout and run as the agent would run it
# --------------------------------------------------------------------------- #


def site_host_source(chosen: str | None) -> str:
    """What to install: the option, else `EP_SITE_HOST_SOURCE`, else the
    sibling checkout, else the agent's pinned archive (CI's, once pinned)."""
    given = chosen or os.environ.get("EP_SITE_HOST_SOURCE")
    if given:
        return str(Path(given).resolve())
    sibling = REPOS / "site-host"
    if sibling.is_dir():
        return str(sibling)
    from eugene_plexus_agent.site_host import SITE_HOST_SOURCE

    return SITE_HOST_SOURCE


def install_site_host(work: Path, source: str) -> Path:
    from eugene_plexus_agent.apps import venv_python

    uv = shutil.which("uv") or str(
        Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    )
    env_dir = work / "site-host-env"
    subprocess.run(
        [uv, "venv", "--python", "3.12", str(env_dir)],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
    )
    python = venv_python(env_dir)
    installed = subprocess.run(
        [uv, "pip", "install", "--python", str(python), source],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    assert installed.returncode == 0, installed.stderr[-2000:]
    return Path(python)


class SiteHost:
    """One site on this machine: its data directory, its `join`, and the
    host process started with the environment the agent builds."""

    running: list[subprocess.Popen[bytes]] = []

    def __init__(self, python: Path, data: Path) -> None:
        self.python, self.data = python, data
        data.mkdir(parents=True, exist_ok=True)
        self.port = free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.environment: dict[str, str] = {}

    @property
    def command(self) -> list[str]:
        if os.environ.get("EP_SITE_HOST_DEBUG"):
            return [str(self.python), "-c",
                    "import logging,sys;logging.basicConfig(level=logging.DEBUG);"
                    "from eugene_plexus_site_host.__main__ import main;main(sys.argv[1:])"]
        return [str(self.python), "-m", SITE_HOST_ENTRY]

    def join(
        self, url: str, token: str, owner: str, label: str, password: str, root_key: str | None
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            *self.command, "join", "--url", url, "--token", token, "--owner", owner,
            "--label", label, "--data-dir", str(self.data),
        ]
        if root_key:
            arguments += ["--root-key", root_key]
        return subprocess.run(
            arguments, input=password + "\n", capture_output=True, text=True,
            env=clean_environment(), timeout=120,
        )

    def leave(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.command, "leave", "--data-dir", str(self.data)], capture_output=True,
            text=True, env=clean_environment(), timeout=120, stdin=subprocess.DEVNULL,
        )

    def start(self, environment: dict[str, str] | None = None) -> None:
        self.stop()
        self.environment = environment if environment is not None else self.environment
        self.process = subprocess.Popen(
            self.command,
            cwd=self.data,
            stdin=subprocess.DEVNULL,
            env={
                **clean_environment(),
                "SITE_HOST_PROTECTED_ROOTS": "[]",
                **self.environment,
                "EUGENE_PLEXUS_APP_DATA_DIR": str(self.data),
                "EUGENE_PLEXUS_APP_BIND_PORT": str(self.port),
                "EUGENE_PLEXUS_APP_ACCOUNT_KIND": "windows_service" if os.name == "nt" else "systemd",
            },
            stdout=subprocess.DEVNULL,
            stderr=open(self.data.parent / f"{self.data.name}.err", "ab"),  # noqa: SIM115
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
                        + (self.data.parent / f"{self.data.name}.err").read_text(errors="replace")[-2000:]
                    ) from None
                time.sleep(0.2)

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def health(self, http: Any) -> dict[str, Any]:
        return dict(http.get(f"http://127.0.0.1:{self.port}/healthz", timeout=5).json())

    def wait_for(self, http: Any, predicate: Any, what: str, seconds: float = 40) -> dict[str, Any]:
        deadline = time.perf_counter() + seconds
        while True:
            try:
                value = self.health(http)
                if predicate(value):
                    return value
            except Exception:  # noqa: BLE001 - a health read may race a restart
                value = {}
            if time.perf_counter() > deadline:
                raise AssertionError(f"{what}: {value}\n" + self.log())
            time.sleep(0.5)

    def log(self) -> str:
        path = self.data.parent / f"{self.data.name}.err"
        return path.read_text(errors="replace")[-2000:] if path.exists() else ""


def site_token(data: Path) -> str:
    """A token the site's own key signs, as its host signs one for a poll."""
    import jwt
    from cryptography.hazmat.primitives import serialization

    site = json.loads((data / "site.json").read_text(encoding="utf-8"))["site"]
    key = serialization.load_pem_private_key((data / "site_key.pem").read_bytes(), password=None)
    now = int(time.time())
    return str(
        jwt.encode(
            {"iss": f"site:{site}", "sub": "site", "aud": "control", "iat": now, "exp": now + 240},
            key,  # type: ignore[arg-type]
            algorithm="EdDSA",
        )
    )


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def wsl_path(path: Path) -> str:
    drive, rest = path.resolve().drive, path.resolve().as_posix()[2:]
    return f"/mnt/{drive[0].lower()}{rest}"


def start_root(work: Path, wsl: bool, ip: str, ports: tuple[int, int, int]) -> Any:
    port, control_port, lan_port = ports
    spec = {
        "ip": ip,
        "port": port,
        "controlPort": control_port,
        "lanPort": lan_port,
        "cache": "~/.cache/ep-job-sites" if wsl else str(work / "cache"),
    }
    if wsl:
        spec["cache"] = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "bash", "-lc", f"echo {spec['cache']}"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        ).stdout.strip()
    (work / "root.json").write_text(json.dumps(spec), encoding="utf-8")
    if wsl:
        venv = os.environ.get("EP_WSL_PYTHON", "~/.cache/ep-job-sites/venv/bin/python")
        script = wsl_path(Path(__file__))
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

    work = Path(tempfile.mkdtemp(prefix="ep-job-sites-"))
    ip = routable(args.root_wsl)
    ports = (free_port(), free_port(), free_port())
    root = start_root(work, args.root_wsl, ip, ports)
    hosts: list[SiteHost] = []
    try:
        deadline = time.perf_counter() + 90
        while not (work / "ready.json").exists():
            if root.poll() is not None or time.perf_counter() > deadline:
                raise SystemExit("the root did not start:\n" + (work / "root.out").read_text())
            time.sleep(0.3)
        ready = json.loads((work / "ready.json").read_text())
        control, nodes, lan = ready["controlUrl"], ready["nodesUrl"], ready["lanUrl"]
        http = httpx.Client(trust_env=False, timeout=30)
        unverified = httpx.Client(trust_env=False, timeout=30, verify=False)
        python = install_site_host(work, site_host_source(args.site_host_source))

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
        people = {p["name"]: p["id"] for p in http.get(f"{control}/v1/people").json()["people"]}
        plain = httpx.Client(trust_env=False, timeout=30)
        workbench = Workbench(plain, control, client)
        ada = sign_in(plain, control, client, "ada", PASSWORD)
        bo = sign_in(plain, control, client, "bo", PASSWORD)
        owner = sign_in(plain, control, client, "operator", PASSPHRASE)
        ok("the root is set up: two people and Workbench's sign-in")

        # ---- 1. J31: the public route carries six site paths and nothing else
        tls = unverified.get(f"{nodes}/v1/trust/tls")
        assert tls.status_code == 200 and tls.json().get("jws"), tls.text
        for method, path in (
            ("GET", "/v1/trust/bundle"),
            ("GET", "/v1/nodes"),
            ("POST", "/v1/nodes/enroll"),
            ("POST", "/v1/nodes/join-token"),
            ("GET", "/v1/sites"),
            ("POST", "/v1/sites/invitations"),
            ("POST", "/v1/auth/login"),
            ("POST", "/oidc/sites/mcp"),
        ):
            refused = unverified.request(method, f"{nodes}{path}", json={})
            assert refused.status_code == 403 and "machines only" in refused.text, (
                method, path, refused.status_code, refused.text[:200],
            )
        for path in (
            "/v1/sites/enroll",
            "/v1/sites/poll",
            "/v1/sites/operations/x/claim",
            "/v1/sites/operations/x/result",
            "/v1/sites/leave",
        ):
            reached = unverified.post(f"{nodes}{path}", json={})
            assert reached.status_code in (401, 422), (path, reached.status_code, reached.text[:200])
        ok("from another network the nodes name answers the six site paths (the signed TLS list "
           "and the five site routes) and refuses the trust bundle, a node's enrollment and "
           "everything else")

        # ---- 2. an invitation names a person -----------------------------
        mine = http.post(
            f"{control}/v1/sites/invitations", json={"owner": people["ada"], "label": "desk"}
        )
        assert mine.status_code == 201, mine.text
        assert mine.json()["ownerName"] == "ada" and mine.json()["joinUrl"] == nodes
        nobody = http.post(f"{control}/v1/sites/invitations", json={"owner": "nobody-here"})
        assert nobody.status_code == 422, nobody.text
        invite = workbench.call("job-sites/invite", ada, label="desk")
        assert invite.status_code == 200, invite.text
        invitation = invite.json()
        assert invitation["joinUrl"] == nodes and invitation["owner"] == "ada", invitation
        assert invitation["rootKey"] == mine.json()["rootKey"] and invitation["rootKey"]
        refused = workbench.call("job-sites/invite", owner)
        assert refused.status_code == 403, refused.text
        ok("a site invitation names a person; Workbench's invite answers the nodes origin as "
           "joinUrl, and Eugene's owner (who owns no sites) cannot invite from there")

        # ---- 3. the join, confirmed at the machine, pinned to the root --
        desk = SiteHost(python, work / "desk" / "data")
        hosts.append(desk)
        wrong_key = desk.join(
            nodes, invitation["token"], "ada", "desk", PASSWORD,
            base64.b64encode(b"\x01" * 32).decode(),
        )
        assert wrong_key.returncode != 0 and "could not be trusted" in (
            wrong_key.stdout + wrong_key.stderr
        ), wrong_key.stdout + wrong_key.stderr
        assert not (desk.data / "site.json").exists()
        leaked = desk.join(nodes, invitation["token"], "ada", "desk", "not her password", invitation["rootKey"])
        assert leaked.returncode != 0 and "refused" in (leaked.stdout + leaked.stderr), (
            leaked.stdout + leaked.stderr
        )
        assert http.get(f"{control}/v1/sites").json()["sites"] == []
        assert not (desk.data / "site.json").exists()
        joined = desk.join(nodes, invitation["token"], "ada", "desk", PASSWORD, invitation["rootKey"])
        assert joined.returncode == 0, joined.stdout + joined.stderr
        assert "ada's job site desk" in joined.stdout, joined.stdout
        record = json.loads((desk.data / "site.json").read_text(encoding="utf-8"))
        assert record["owner"] == people["ada"] and record["ownerName"] == "ada", record
        assert record["rootKey"] == invitation["rootKey"] and record["url"] == nodes
        assert json.loads((desk.data / "root_tls.json").read_text())["origin"] == nodes
        assert PASSWORD not in "".join(
            p.read_text(errors="ignore") for p in desk.data.rglob("*") if p.is_file()
        )
        site_id = record["site"]
        assert re.fullmatch(r"s-[a-z2-7]{26}", site_id), site_id
        reused = desk.join(nodes, invitation["token"], "ada", "other", PASSWORD, invitation["rootKey"])
        assert reused.returncode != 0
        ok("over the public route a wrong root key sends nothing, a wrong password refuses the "
           "join and keeps the invitation, and the right one joins, pinned to the root's identity "
           "key, as ada's site; her password is kept nowhere on it")

        # ---- 4. started, it polls; the console lists it -------------------
        desk.start()
        health = desk.wait_for(
            http, lambda h: h.get("lastContactAt") and h.get("reason") is None,
            "the site host never reached its root",
        )
        assert health["ready"] is True and health["site"] == site_id, health
        deadline = time.perf_counter() + 40
        while True:
            listed = http.get(f"{control}/v1/sites").json()
            entry = next((s for s in listed["sites"] if s["id"] == site_id), None)
            if entry and entry["online"] and entry["ready"]:
                break
            if time.perf_counter() > deadline:
                raise AssertionError(f"the console never listed the site online: {listed}")
            time.sleep(1)
        assert entry["label"] == "desk" and entry["ownerName"] == "ada", entry
        assert entry["lastContactAt"] and entry["hostNode"] is None
        assert entry["dev"] is None and listed["installMode"]["mode"] == "production", listed
        assert listed["joinUrl"] == nodes
        assert socket.create_connection(("127.0.0.1", desk.port), timeout=2)
        try:
            with socket.create_connection((routable(False), desk.port), timeout=2):
                raise AssertionError("the site host answered on its network address")
        except OSError:
            pass
        ok("started, the site host polls the root with its own key; the console lists it online "
           "with its owner and last contact, shows no folders in production (dev is null), and "
           "the host listens on loopback only")

        # ---- 5. ada's folders, bo's read, the audit log -------------------
        folder = work / "shared"
        folder.mkdir()
        (folder / "note.txt").write_text("Notes from ada's desk", encoding="utf-8")

        def call(route: str, token: str, /, **body: Any) -> Any:
            return workbench.call(route, token, **body)

        def mcp(token: str, server: str, method: str, params: dict[str, Any] | None = None) -> Any:
            return workbench.mcp(token, site_id, server, method, params)

        def forge(**body: Any) -> Any:
            return http.post(f"{control}/acceptance/forge", json={"site": site_id, **body}, timeout=40)

        def settle(predicate: Any, what: str) -> dict[str, Any]:
            """The site's next report, which the root keeps as a cache."""
            deadline = time.perf_counter() + 30
            while True:
                sites = call("job-sites", ada).json()["sites"]
                if sites and predicate(sites[0]):
                    return dict(sites[0])
                if time.perf_counter() > deadline:
                    raise AssertionError(f"{what}: {sites}")
                time.sleep(0.3)

        read = {"name": "read_text", "arguments": {"folder": "Notes", "path": "note.txt"}}
        mine_only = call("job-sites", bo).json()["sites"]
        assert mine_only == [], mine_only
        added = call(f"job-sites/{site_id}/folders", ada, name="Notes", path=str(folder), writable=True)
        assert added.status_code == 201, added.text
        folder_id = added.json()["id"]
        assert added.json()["people"] == []
        again = call(f"job-sites/{site_id}/folders", ada, name="notes", path=str(folder))
        assert again.status_code == 422 and "registered already" in again.text, again.text
        settle(lambda s: s["folders"], "the site never reported its folder")
        stranger = call(f"job-sites/{site_id}/folders", bo, name="Mine", path=str(folder))
        assert stranger.status_code == 404, stranger.text
        assert mcp(bo, "files", "tools/list").status_code == 403
        forged = forge(kind="enqueue", subject=people["bo"], server="files", request=rpc("tools/call", read))
        assert forged.status_code == 200, forged.text
        assert forged.json()["status"] == "failed" and "has not given you" in forged.json()["message"]
        granted = call(f"job-sites/{site_id}/folders/{folder_id}/people", ada,
                       people=[{"name": "ada", "writable": False}, {"name": "bo", "writable": False}])
        assert granted.status_code == 200, granted.text
        assert {p["name"] for p in granted.json()["people"]} == {"ada", "bo"}
        settle(lambda s: len(s["folders"][0]["people"]) == 2, "the grant never reported")
        listed_servers = call("sites/servers", bo).json()["servers"]
        files = next(s for s in listed_servers if s["server"] == "files")
        assert files["site"] == site_id and files["folders"] == [
            {"id": folder_id, "name": "Notes", "writable": False}
        ]
        tools = mcp(bo, "files", "tools/list")
        assert tools.status_code == 200, tools.text
        offered = {t["name"]: t["inputSchema"]["properties"]["folder"]["enum"]
                   for t in tools.json()["response"]["result"]["tools"]}
        assert offered == {"list_directory": ["Notes"], "read_text": ["Notes"]}, offered
        got = mcp(bo, "files", "tools/call", read)
        body = got.json()
        assert got.status_code == 200 and body["status"] == "done", got.text
        assert "Notes from ada's desk" in json.dumps(body["response"])
        assert body["installMode"] == "production"
        write = {"name": "write_text", "arguments": {
            "folder": "Notes", "path": "note.txt", "text": "bo was here", "expectedSha256": ""}}
        denied = mcp(bo, "files", "tools/call", write)
        assert denied.json()["status"] == "failed" and "not change files" in denied.json()["message"]
        assert (folder / "note.txt").read_text(encoding="utf-8") == "Notes from ada's desk"
        call(f"job-sites/{site_id}/folders/{folder_id}/people", ada,
             people=[{"name": "ada", "writable": False}, {"name": "bo", "writable": True}])
        settle(lambda s: any(p["writable"] for p in s["folders"][0]["people"]), "write grant")
        wrote = mcp(bo, "files", "tools/call", {"name": "write_text", "arguments": {
            "folder": "Notes", "path": "new.txt", "text": "bo was here", "expectedSha256": ""}})
        assert wrote.json()["status"] == "done", wrote.text
        assert (folder / "new.txt").read_text(encoding="utf-8") == "bo was here"
        log = call(f"job-sites/{site_id}/audit", ada, limit=50)
        assert log.status_code == 200, log.text
        entries = log.json()["entries"]
        decided = {(e["subject"], e.get("tool"), e["decision"]) for e in entries}
        assert (people["bo"], "read_text", "refused") in decided
        assert (people["bo"], "write_text", "refused") in decided
        assert (people["bo"], "write_text", "allowed") in decided
        assert "bo was here" not in json.dumps(entries) and "Notes from ada" not in json.dumps(entries)
        for someone in (bo, owner):
            assert call(f"job-sites/{site_id}/audit", someone).status_code == 404
        ok("ada registers a folder through Workbench's routes (a name unique on the site), "
           "nobody else may; default deny holds even when the root itself sends bo's call; "
           "after ada gives bo read access he lists and reads the file through /oidc/sites/mcp; "
           "a write needs ada's standing pre-approval; the audit log names who asked and what "
           "was decided, never contents, and only its owner reads it")

        # ---- 6. editing the root's state is not enough -------------------
        assert forge(kind="owner", owner=people["bo"]).status_code == 200
        time.sleep(2)  # a poll or two, each naming bo
        assert json.loads((desk.data / "site.json").read_text())["owner"] == people["ada"]
        taken = call(f"job-sites/{site_id}/folders/{folder_id}/people", bo,
                     people=[{"name": "bo", "writable": True}])
        assert taken.status_code == 422 and "Only this machine's owner" in taken.text, taken.text
        manage = forge(kind="manage", subject=people["bo"], action="folder.people",
                       arguments={"id": folder_id, "people": [{"subject": people["bo"], "writable": True}]})
        assert manage.status_code == 200, manage.text
        assert manage.json()["status"] == "failed" and "Only this machine's owner" in manage.json()["message"], manage.text
        assert forge(kind="owner", owner=people["ada"]).status_code == 200
        other = forge(kind="enqueue", enrolledAt="2001-01-01T00:00:00+00:00", subject=people["ada"],
                      server="files", request=rpc("tools/call", read))
        assert other.status_code == 200, other.text
        assert other.json()["status"] == "failed" and "not for this site" in other.json()["message"], other.text
        assert (folder / "new.txt").read_text(encoding="utf-8") == "bo was here"
        ok("rule 2: the root naming bo as the site's owner, an operation queued in his name, and "
           "one bound to an earlier enrollment all get nothing run: the site refuses (its pinned "
           "owner; 'not for this site')")

        # ---- 7. the site's token opens its own routes only ---------------
        token = site_token(desk.data)
        bearer = {"Authorization": "Bearer " + token}
        for base in (control, nodes):
            client_ = unverified if base == nodes else plain
            for path in ("/v1/nodes", "/v1/sites", "/v1/config", "/v1/people"):
                refused = client_.get(f"{base}{path}", headers=bearer)
                assert refused.status_code in (401, 403), (base, path, refused.status_code)
            assert client_.post(f"{base}/v1/sites/invitations", headers=bearer,
                                json={"owner": people["ada"]}).status_code in (401, 403)
        own = plain.post(f"{control}/v1/sites/operations/none/claim", headers=bearer)
        assert own.status_code == 404, own.text  # its own route, answered
        tampered = plain.post(f"{control}/v1/sites/leave", headers={"Authorization": "Bearer " + token[:-4] + "AAAA"})
        assert tampered.status_code == 401, tampered.text
        ok("the site's token opens its own routes only: GET /v1/nodes and GET /v1/sites are "
           "refused with it (directly and through the nodes name), and so is minting an invitation")

        # ---- a fifth tool, added at the machine --------------------------
        local_server_check(desk, work, call, mcp, settle, site_id, ada, bo)

        # ---- production, then dev mode (J6e) ---------------------------------
        assert mcp(owner, "files", "tools/call", read).status_code == 403
        patched = http.patch(f"{control}/v1/sites/{site_id}/folders/{folder_id}", json={"ownerAccess": "read"})
        assert patched.status_code in (403, 409), patched.text
        assert [s["dev"] for s in http.get(f"{control}/v1/sites").json()["sites"]] == [None]
        switched = http.patch(f"{control}/v1/config", json={"installMode": "dev"})
        assert switched.status_code == 200, switched.text
        listing = http.get(f"{control}/v1/sites").json()
        dev = next(s for s in listing["sites"] if s["id"] == site_id)["dev"]
        assert dev and dev["folders"][0]["id"] == folder_id and dev["ownerInDevMode"] is False, dev
        patched = http.patch(f"{control}/v1/sites/{site_id}/folders/{folder_id}", json={"ownerAccess": "read"})
        assert patched.status_code == 200, patched.text
        closed = mcp(owner, "files", "tools/call", read)
        assert closed.status_code == 200 and closed.json()["status"] == "failed", closed.text
        assert "Dev mode alone opens nothing" in closed.json()["message"]
        opted = call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=True)
        assert opted.status_code == 200 and opted.json()["ownerInDevMode"] is True, opted.text
        settle(lambda s: s["ownerInDevMode"], "the opt-in never reported")
        opened = mcp(owner, "files", "tools/call", read)
        assert opened.status_code == 200 and opened.json()["status"] == "done", opened.text
        assert opened.json()["installMode"] == "dev"
        back = http.patch(f"{control}/v1/config", json={"installMode": "production"})
        assert back.status_code == 200
        assert mcp(owner, "files", "tools/call", read).status_code == 403
        assert [s["dev"] for s in http.get(f"{control}/v1/sites").json()["sites"]] == [None]
        ok("production: Eugene's owner cannot read it, by grant or by listing; dev mode adds a "
           "section to the console and opens only once the site's owner lets them in (J6e); "
           "back in production it stops at once")

        # ---- 9. a node says which site it hosts (J32) --------------------
        hosting = enroll_node(http, control, "amish")
        hosted = http.put(f"{control}/v1/nodes/amish/hosted-sites",
                          headers={"Authorization": "Bearer " + hosting}, json={"sites": [site_id]})
        assert hosted.status_code == 204, hosted.text
        listed = http.get(f"{control}/v1/sites").json()["sites"]
        assert next(s for s in listed if s["id"] == site_id)["hostNode"] == "amish"
        liar = http.put(f"{control}/v1/nodes/someone/hosted-sites",
                        headers={"Authorization": "Bearer " + hosting}, json={"sites": [site_id]})
        assert liar.status_code == 403, liar.text
        ok("a node says which site it hosts: with its own token the console shows hostNode, and a "
           "node speaks for no other")

        # ---- 8. a LAN-only install: plain HTTP, no entry point -----------
        lan_site = lan_only_join(args, http, httpx, python, work, lan, hosts)
        ok("J31: on a LAN-only install, with siteJoinUrl set to control's own HTTP address and "
           "no entry point in the way, a second site host joins over plain HTTP (pinning nothing) "
           "and polls")

        # ---- 10. removed from the console -------------------------------
        removed = lan_site.remove()
        assert removed.status_code == 204, removed.text
        health = lan_site.host.wait_for(
            http, lambda h: "does not know this site" in (h.get("reason") or ""),
            "the removed site's host never said it was refused", seconds=60,
        )
        assert (lan_site.host.data / "site.json").exists() and health["site"] == lan_site.site
        assert lan_site.site not in {s["id"] for s in lan_site.sites()}
        ok("removing the site from the console refuses its host's next poll; its /healthz says "
           "the root does not know it, and the enrollment stays on its disk")

        # ---- 11. the agent's `site join` ---------------------------------
        agent_site_join(args, python, work, nodes, http, control, people, invitation)

        # ---- 12. the site leaves ----------------------------------------
        desk.stop()
        left = desk.leave()
        assert left.returncode == 0 and "no longer a job site" in left.stdout, left.stdout + left.stderr
        assert not (desk.data / "site.json").exists() and not (desk.data / "site_key.pem").exists()
        assert site_id not in {s["id"] for s in http.get(f"{control}/v1/sites").json()["sites"]}
        refused = plain.post(f"{control}/v1/sites/leave", headers={"Authorization": "Bearer " + token})
        assert refused.status_code == 401, refused.text
        ok("the site's own `leave` tells the root and forgets its enrollment: the root lists it "
           "no more and its old token is refused")
    finally:
        for host in hosts:
            host.stop()
        for process in SiteHost.running:
            if process.poll() is None:
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


def enroll_node(http: Any, control: str, name: str) -> str:
    """A real enrollment of a node (a join token and its three keys), and a
    token its own key signs: all a node needs to say which site it hosts."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from eugene_plexus_agent import tokens as agent_tokens

    def public(key: Ed25519PrivateKey) -> str:
        raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    join_token = http.post(f"{control}/v1/nodes/join-token", json={}).json()["token"]
    signing, sealing, token_key = (Ed25519PrivateKey.generate() for _ in range(3))
    made = http.post(
        f"{control}/v1/nodes/enroll",
        json={"token": join_token, "name": name, "publicKey": public(sealing),
              "signingPublicKey": public(signing), "tokenPublicKey": public(token_key)},
    )
    assert made.status_code == 201, made.text
    signer = agent_tokens.Signer(key=token_key, issuer=f"node:{name}")
    token, _ = signer.mint(
        typ=agent_tokens.TYP_SERVICE, sub="agent", aud=["control"], ttl_seconds=600
    )
    return str(token)


class LanSite:
    def __init__(self, host: SiteHost, http: Any, control: str, site: str) -> None:
        self.host, self.http, self.control, self.site = host, http, control, site

    def remove(self) -> Any:
        return self.http.delete(f"{self.control}/v1/sites/{self.site}")

    def sites(self) -> list[dict[str, Any]]:
        return list(self.http.get(f"{self.control}/v1/sites").json()["sites"])


def lan_only_join(
    args: argparse.Namespace, http: Any, httpx: Any, python: Path, work: Path, lan: str,
    hosts: list[SiteHost],
) -> LanSite:
    root = httpx.Client(trust_env=False, timeout=30)
    assert root.post(f"{lan}/v1/auth/initialize", json={"passphrase": PASSPHRASE}).status_code == 204
    session = root.post(f"{lan}/v1/auth/login", json={"passphrase": PASSPHRASE}).json()
    root.headers["Authorization"] = "Bearer " + session["sessionToken"]
    made = root.post(f"{lan}/v1/people", json={"name": "ada", "password": PASSWORD, "apps": []})
    assert made.status_code == 201, made.text
    before = root.get(f"{lan}/v1/sites").json()
    assert before["joinUrl"] is None, before
    set_ = root.patch(f"{lan}/v1/config", json={"siteJoinUrl": lan})
    assert set_.status_code == 200, set_.text
    assert root.get(f"{lan}/v1/sites").json()["joinUrl"] == lan
    invitation = root.post(f"{lan}/v1/sites/invitations", json={"owner": made.json()["id"], "label": "lan"})
    assert invitation.status_code == 201, invitation.text
    assert invitation.json()["joinUrl"] == lan
    host = SiteHost(python, work / "lan" / "data")
    hosts.append(host)
    joined = host.join(lan, invitation.json()["token"], "ada", "lan", PASSWORD, None)
    assert joined.returncode == 0, joined.stdout + joined.stderr
    record = json.loads((host.data / "site.json").read_text(encoding="utf-8"))
    assert record["url"] == lan and not (host.data / "root_tls.json").exists()
    host.start()
    host.wait_for(
        root, lambda h: h.get("lastContactAt") and h.get("reason") is None,
        "the LAN site never reached its root",
    )
    deadline = time.perf_counter() + 40
    while True:
        sites = root.get(f"{lan}/v1/sites").json()["sites"]
        if sites and sites[0]["online"] and sites[0]["ownerName"] == "ada":
            break
        if time.perf_counter() > deadline:
            raise AssertionError(f"the LAN site never listed online: {sites}")
        time.sleep(1)
    return LanSite(host, root, lan, record["site"])


def local_server_check(
    desk: SiteHost, work: Path, call: Any, mcp: Any, settle: Any, site_id: str, ada: str, bo: str,
) -> None:
    """A fifth tool, added the way `eugene-plexus-agent site server add` adds
    one after its elevation check (the check itself is the agent's unit test
    and the real CLI is run in check 11), and the host learns it at its next
    start, as the agent restarts it."""
    import yaml
    from eugene_plexus_agent import site_cli
    from eugene_plexus_agent.site_host import SERVERS_COPY, local_servers

    config = work / "desk-config"
    config.mkdir()
    fixture = work / "local_server.py"
    fixture.write_bytes((REPOS / "site-host" / "tests" / "fixtures" / "local_server.py").read_bytes())
    elevated, site_cli.elevated = site_cli.elevated, lambda: True
    try:
        site_cli.add_server(config, server_id="notes-tool", name="Notes tool",
                            command=str(desk.python), args=["-I", str(fixture)], env=[], system=False)
    finally:
        site_cli.elevated = elevated

    def restart_with_servers() -> None:
        data = json.dumps(local_servers(config), ensure_ascii=False).encode()
        copy = work / "desk-state" / SERVERS_COPY
        copy.parent.mkdir(exist_ok=True)
        copy.write_bytes(data)
        desk.start({
            "SITE_HOST_PROTECTED_ROOTS": json.dumps([str(config)]),
            "SITE_HOST_LOCAL_SERVERS_FILE": str(copy),
            "SITE_HOST_LOCAL_SERVERS_SHA256": hashlib.sha256(data).hexdigest(),
        })
        # No wait here, on purpose: the root's long poll for the host just
        # stopped may take the next call and answer a closed socket. The root
        # offers an operation nobody claimed again after five seconds
        # (control `sites.OFFER_SECONDS`), so the restarted host still gets it.

    restart_with_servers()
    listed = settle(lambda s: s["servers"], "the local server never reported")
    assert listed["servers"][0]["server"]["id"] == "notes-tool"
    assert not listed["servers"][0]["server"]["enabled"]
    on = call(f"job-sites/{site_id}/servers/notes-tool/enabled", ada, enabled=True)
    assert on.status_code == 200, on.text
    assert {t["name"] for t in on.json()["server"]["tools"]} == {"echo", "touch"}
    plain = call(f"job-sites/{site_id}/servers/notes-tool/access", ada,
                 people=[{"name": "bo", "tools": [{"name": "touch"}]}])
    assert plain.status_code == 422 and "standing" in plain.text, plain.text
    given = call(f"job-sites/{site_id}/servers/notes-tool/access", ada,
                 people=[{"name": "bo", "tools": [{"name": "echo"}]}])
    assert given.status_code == 200, given.text
    settle(lambda s: s["servers"][0]["people"], "the tool grant never reported")
    mine = call("sites/servers", bo)
    assert any(s["server"] == "notes-tool" and s["kind"] == "local" for s in mine.json()["servers"])
    tools = mcp(bo, "notes-tool", "tools/list")
    assert [t["name"] for t in tools.json()["response"]["result"]["tools"]] == ["echo"]
    echoed = mcp(bo, "notes-tool", "tools/call", {"name": "echo", "arguments": {"text": "hi"}})
    assert echoed.json()["status"] == "done" and "echo: hi" in json.dumps(echoed.json()), echoed.text
    # J9: a server marked system will not turn on without an administrator's consent.
    servers = yaml.safe_load((config / site_cli.SERVERS_FILE).read_text(encoding="utf-8"))
    servers["servers"].append({**servers["servers"][0], "id": "settings-tool",
                               "name": "Settings tool", "system": True})
    (config / site_cli.SERVERS_FILE).write_text(yaml.safe_dump(servers), encoding="utf-8")
    restart_with_servers()
    settle(lambda s: len(s["servers"]) == 2, "the system server never reported")
    system = call(f"job-sites/{site_id}/servers/settings-tool/enabled", ada, enabled=True)
    assert system.status_code == 422 and "consent" in system.text.lower(), system.text
    ok("a fifth tool, from a local server added at the machine, works through the same route, "
       "with no change to control or Workbench; a server marked system will not turn on without "
       "an administrator's consent recorded at the machine (J9)")


def agent_site_join(
    args: argparse.Namespace, python: Path, work: Path, nodes: str, http: Any, control: str,
    people: dict[str, str], invitation: dict[str, Any],
) -> None:
    from eugene_plexus_agent import site_cli

    config = work / "agent-config"
    config.mkdir()
    environment = {**clean_environment(), "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(config / "agent.yaml")}
    join = ["site", "join", "--url", nodes, "--token", "x", "--owner", "ada", "--label", "away",
            "--root-key", invitation["rootKey"], "--password-stdin"]
    if not site_cli.elevated():
        refused = subprocess.run(
            agent_command(*join), input=PASSWORD + "\n", capture_output=True, text=True,
            env=environment, timeout=120,
        )
        assert refused.returncode == 2 and "administrator" in refused.stderr.lower(), (
            refused.returncode, refused.stderr,
        )
        assert not (config / "site-host.json").exists()
        ok("the agent's `site join` refuses an unelevated caller, and changes nothing "
           "(not elevated here, so the elevated join is the disposable runners' to run)")
        return
    # Elevated: the real CLI, pointed at a site host this script installed.
    minted = http.post(f"{control}/v1/sites/invitations", json={"owner": people["ada"], "label": "away"})
    assert minted.status_code == 201, minted.text
    data = work / "away" / "data"
    data.mkdir(parents=True)
    done = subprocess.run(
        agent_command("site", "join", "--url", nodes, "--token", minted.json()["token"],
                      "--owner", "ada", "--label", "away", "--root-key", minted.json()["rootKey"],
                      "--password-stdin", "--python", str(python), "--data-dir", str(data)),
        input=PASSWORD + "\n", capture_output=True, text=True, env=environment, timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    record = json.loads((data / "site.json").read_text(encoding="utf-8"))
    assert record["label"] == "away" and record["owner"] == people["ada"]
    assert record["site"] in {s["id"] for s in http.get(f"{control}/v1/sites").json()["sites"]}
    ok("the agent's elevated `site join` installed nothing of its own and joined the site host "
       "it was pointed at, as ada's")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-root", type=Path)
    parser.add_argument("--root-wsl", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--site-host-source",
        help="what to install as the site host: a checkout or an archive URL "
        "(else EP_SITE_HOST_SOURCE, else the sibling checkout, else the agent's pin)",
    )
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
