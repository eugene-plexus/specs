"""Job Sites, slice 1 (docs/design/remote-nodes.md §5): a machine on another
network joins over the public node route, and its files are its owner's.

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

**The file read** then runs the agent's real relay (`NodeFileHelper`) and the
real helper worker wheel, over that real public route with the pins the site
saved: a service install's OS account is the one thing a test process cannot
give the site agent itself (C1's disposable runners own that check).

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
`EUGENE_PLEXUS_*` environment, and never touches an installed Eugene.
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
import ssl
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
        [found, "version"], capture_output=True, text=True
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
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=control_port, log_level="warning")
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
        ).stdout.strip()
        (work / "root.json").write_text(json.dumps(spec), encoding="utf-8")
        command = ["wsl", "-d", "Ubuntu", "--", "bash", "-lc",
                   f"env -u EUGENE_PLEXUS_AGENT_CONFIG_FILE {venv} {script} --serve-root {wsl_path(work)}"]
    else:
        command = [sys.executable, __file__, "--serve-root", str(work)]
    return subprocess.Popen(
        command, env=clean_environment(), stdout=open(work / "root.out", "wb"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
    )


def routable(wsl: bool) -> str:
    if wsl:
        out = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "hostname", "-I"], capture_output=True, text=True
        ).stdout.split()
        return out[0]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        return str(sock.getsockname()[0])


def agent_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "eugene_plexus_agent", *args]


async def relay_read(
    site: Path, port: int, worker_port: int, token: str, package: Any
) -> tuple[Any, Any]:
    """The agent's real relay, as the site's, over the real public route."""
    from eugene_plexus_agent import tokens
    from eugene_plexus_agent._generated.models import ComponentStatus
    from eugene_plexus_agent.node_file_helper import NodeFileHelper
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.root_tls import RootLink
    from fastapi import FastAPI

    store = NodeIdentityStore(site / "node.yaml")
    store.load()
    record = store.record
    signer = tokens.Signer(
        key=tokens.load_private(str(record.token_private_key)), issuer=f"node:{record.name}"
    )
    app = FastAPI()
    app.state.node_identity = store
    app.state.root_link = RootLink(store)
    app.state.auth_state = SimpleNamespace(
        trust=SimpleNamespace(
            agent_token=lambda aud: signer.mint(
                typ=tokens.TYP_SERVICE, sub="agent", aud=[aud], ttl_seconds=600
            )[0]
        )
    )
    kind = "windows_service" if os.name == "nt" else "systemd"
    app.state.apps = SimpleNamespace(
        accounts=SimpleNamespace(available=True, kind=kind),
        store=SimpleNamespace(
            get=lambda _: SimpleNamespace(enabled=True, port=worker_port, manifest=package)
        ),
        supervisor=SimpleNamespace(
            status=lambda _: (ComponentStatus.running, None, None, None, None),
            admin_token=lambda _: token,
        ),
        installer=SimpleNamespace(snapshot=lambda _: None),
    )
    relay = NodeFileHelper(app)

    async def nothing(_config: dict[str, Any]) -> None:
        pass

    relay.reconcile = nothing  # type: ignore[method-assign]
    return relay, app


def run(args: argparse.Namespace) -> None:
    import httpx

    from eugene_plexus_agent import root_tls
    from eugene_plexus_agent.apps import AppStore, venv_python
    from eugene_plexus_agent.node_file_helper import manifest

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
        ok("the site joined over the public route as ada's, files only, with no address; "
           "her password is kept nowhere on it")

        # ---- the site runs, and only connects out --------------------------
        site_port = free_port()
        site_process = subprocess.Popen(
            agent_command("--unattended"),
            env={**site_env, "EUGENE_PLEXUS_AGENT_BIND_PORT": str(site_port)},
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

        # ---- files: the real relay and helper over the real public route --
        folder = work / "shared"
        folder.mkdir()
        (folder / "note.txt").write_text("Notes from ada's desk", encoding="utf-8")
        package = manifest(SimpleNamespace(store=AppStore(work / "relay" / "apps.yaml")), work / "relay")
        uv = shutil.which("uv") or str(Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv"))
        env_dir = work / "worker-env"
        subprocess.run([uv, "venv", "--python", sys.executable, str(env_dir)], check=True, capture_output=True)
        python = venv_python(env_dir)
        subprocess.run([uv, "pip", "install", "--python", str(python), "--no-deps", str(package.source)],
                       check=True, capture_output=True)
        worker_port, worker_token = free_port(), secrets.token_urlsafe(24)
        data = work / "worker-data"
        data.mkdir()
        worker = subprocess.Popen(
            [str(python), "-m", package.entry],
            cwd=data,
            env={
                **clean_environment(),
                "EUGENE_PLEXUS_APP_DATA_DIR": str(data),
                "EUGENE_PLEXUS_APP_BIND_PORT": str(worker_port),
                "EUGENE_PLEXUS_APP_ADMIN_TOKEN": worker_token,
                "EUGENE_PLEXUS_APP_ACCOUNT_KIND": "windows_service" if os.name == "nt" else "systemd",
                "NODE_HELPER_PROTECTED_ROOTS": json.dumps([str(site)]),
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        asyncio.run(files_through_the_site(
            work, site, worker_port, worker_token, package, http, workbench, ada, bo, owner, folder, control
        ))
        left = workbench.call("job-sites/desk/leave", ada)
        assert left.status_code == 204
        assert "desk" not in {n["name"] for n in http.get(f"{control}/v1/nodes").json()["nodes"]}
        ok("ada takes her machine out herself; it is gone at once")
    finally:
        for process in (site_process, worker):
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


async def files_through_the_site(
    work: Path, site: Path, worker_port: int, worker_token: str, package: Any,
    http: Any, workbench: Workbench, ada: str, bo: str, owner: str, folder: Path, control: str,
) -> None:
    relay, _app = await relay_read(site, 0, worker_port, worker_token, package)
    task = asyncio.create_task(relay.run())

    async def call(route: str, token: str, /, **body: Any) -> Any:
        return await asyncio.to_thread(lambda: workbench.call(route, token, **body))

    try:
        assert (await call("job-sites/desk/enabled", ada, enabled=True)).status_code == 200
        deadline = time.perf_counter() + 30
        while True:
            sites = (await call("job-sites", ada)).json()["sites"]
            if sites and sites[0]["ready"]:
                break
            if time.perf_counter() > deadline:
                raise AssertionError(f"the site's helper never became ready: {sites}")
            await asyncio.sleep(0.5)
        added = await call("job-sites/desk/folders", ada, name="Notes", path=str(folder), writable=False)
        assert added.status_code == 201, added.text
        folder_id = added.json()["id"]
        before = await call("node-helpers/execute", ada, folderId=folder_id, tool="read_text",
                            arguments={"path": "note.txt"})
        assert before.status_code == 403, before.text
        granted = await call(f"job-sites/desk/folders/{folder_id}/people", ada,
                             people=[{"name": "ada", "writable": False}, {"name": "bo", "writable": False}])
        assert granted.status_code == 200, granted.text
        ok("ada turns on her site's helper, registers a folder, and grants it, herself included")

        read = await call("node-helpers/execute", bo, folderId=folder_id, tool="read_text",
                          arguments={"path": "note.txt"})
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["status"] == "done" and "Notes from ada's desk" in json.dumps(body["result"])
        assert body["jobSite"] is True and body["installMode"] == "production"
        ok("a person she granted reads the file through the public route, marked as a job site's")

        mine = await call("node-helpers/execute", owner, folderId=folder_id, tool="read_text",
                          arguments={"path": "note.txt"})
        assert mine.status_code == 403
        patched = await asyncio.to_thread(
            http.patch, f"{control}/v1/node-helpers/desk/folders/{folder_id}", json={"ownerAccess": "read"}
        )
        assert patched.status_code == 403
        listing = (await asyncio.to_thread(http.get, f"{control}/v1/node-helpers")).json()
        desk = next(h for h in listing["helpers"] if h["node"] == "desk")
        assert desk["hidden"] and desk["folders"] == []
        ok("production: Eugene's owner cannot read it, by grant or by listing")

        switched = await asyncio.to_thread(http.patch, f"{control}/v1/config", json={"installMode": "dev"})
        assert switched.status_code == 200, switched.text
        mode = await asyncio.to_thread(
            workbench.http.post, f"{control}/oidc/install-mode",
            auth=(workbench.client["client"]["clientId"], workbench.client["clientSecret"]),
        )
        assert mode.json()["mode"] == "dev" and mode.json()["changedAt"]
        listing = (await asyncio.to_thread(http.get, f"{control}/v1/node-helpers")).json()
        desk = next(h for h in listing["helpers"] if h["node"] == "desk")
        assert not desk["hidden"] and desk["folders"][0]["id"] == folder_id
        patched = await asyncio.to_thread(
            http.patch, f"{control}/v1/node-helpers/desk/folders/{folder_id}", json={"ownerAccess": "read"}
        )
        assert patched.status_code == 200, patched.text
        mine = await call("node-helpers/execute", owner, folderId=folder_id, tool="read_text",
                          arguments={"path": "note.txt"})
        assert mine.status_code == 200 and mine.json()["installMode"] == "dev", mine.text
        ok("dev mode: the owner sees the site's folders, grants themselves one and reads it, "
           "and every app can tell everyone")

        back = await asyncio.to_thread(http.patch, f"{control}/v1/config", json={"installMode": "production"})
        assert back.status_code == 200
        mine = await call("node-helpers/execute", owner, folderId=folder_id, tool="read_text",
                          arguments={"path": "note.txt"})
        assert mine.status_code == 403
        ok("back in production the owner's own grant stops at once")
    finally:
        task.cancel()
        with __import__("contextlib").suppress(asyncio.CancelledError):
            await task


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
