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

**Slice 2b.2 (§2.4, §3.2): the site host runs no tool.** Each linked person's
tools run in a worker, as that person's own OS account, over a local channel
(a Unix socket, or a named pipe on Windows) the host serves. This script plays
the machine's privileged starter, which is not under test here (the agent's,
root's and the installer's own checks are): it writes the links file
(`SITE_HOST_LINKS_FILE`, ada -> the account the workers run as), gives the host
its channel (`SITE_HOST_CHANNEL`) and its local-server list
(`SITE_HOST_LOCAL_SERVERS_FILE`, read as YAML by the host AND by each worker;
the JSON copy and its hash are gone), and starts a real worker, from the same
installed site-host environment, beside each host.

* With **passwordless sudo on Linux** (CI's runner) it creates throwaway
  accounts (`epa`, `epj` for two people, `eps` for the site host, `epz` for a
  stranger; `userdel -r` in teardown), installs the site host under a root-owned
  `/opt/ep-acc-*` so every account can run it, and runs the host and each worker
  as their own account. Every earlier check then runs through the real
  accounts: the host as `eps`, the owner's worker as `epa`. `--no-sudo` forces
  the single-account mode below.
* Without it (Windows with `--root-wsl`, or Linux without sudo) there is one
  account here, so the harness's "worker" is the real worker with only its
  account refusal removed (`STAND_IN`): without that the real worker refuses to
  run as the site host's own account, which is what the one-account run would be
  (see the note printed by check 14). What the OS does between accounts is then
  not checked, and each such check prints a `SKIP:` line saying so.

Mechanisms that changed since 2b.1: the local-server check writes the YAML list
the agent's `site server add` writes (`servers_path`), and the host and the
workers are restarted to read it; the site's own files are read through the
host's account (`sudo -u`) when the host runs as another account; the agent's
`site join` is no longer elevated on a per-user install and links the owner at
the machine, so check 11 runs it for real; the nodes name carries seven paths
(`POST /v1/sites/links/check`, J36), which check 1 and check 18 assert.

**J14a (person-held-keys.md §12): the owner's own key.** The starter pins the
owner's key in the links file, as the agent's loopback page does on a Windows
service install; this script makes it with `cryptography` where a browser
would make it with WebCrypto (`j14a-browser-check.py` drives the browser
itself). Until it is pinned the site runs no tool (J48). Once it is, a change
that gives access answers 202 *held*, and is applied only once this script
approves it at the machine through the site host's own `/v1/held`, signing
the envelope the site host gave with the owner's key: so every grant below
goes through the real verifier. A change the root forges in the owner's name
is held, never applied; an old approval replayed against the same change asked
again is refused.

**J14a.3 (§12.5): a passkey from Workbench, through the root.** The owner's
key at the machine is taken away, so the site is as a Linux system install
leaves it (no page at the machine, no key) and runs no tool. The starter asks
the site host for a code (`/v1/passkeys/code`, as `--site-pair` does); a
passkey made here as a browser's authenticator makes it (the real byte layout
of WebAuthn, `j14a3-browser-check.py` drives Chrome's) is paired through the
root's `/oidc/job-sites/{site}/passkeys` with the MAC over it, and its
assertions approve the site's rules and a held change through
`/oidc/job-sites/{site}/held/...`. A root that swaps the public key, and an
assertion over another change, are refused by the site.

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
import contextlib
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
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


def install_site_host_for_all(base: Path, source: str) -> Path:
    """Sudo mode: the site host's environment under a root-owned `base`
    (0755), so the host's account and every worker's can run it and none can
    write it (§2.4: the program that runs as the person is root-owned)."""
    uv = shutil.which("uv") or str(Path(sys.executable).parent / "uv")
    environment = {
        "UV_PYTHON_INSTALL_DIR": str(base / "py"),
        "UV_CACHE_DIR": str(base / "uvcache"),
        "UV_LINK_MODE": "copy",
    }
    sudo("env", *[f"{k}={v}" for k, v in environment.items()], uv, "venv", "--python", "3.12",
         str(base / "env"))
    python = base / "env" / "bin" / "python"
    sudo("env", *[f"{k}={v}" for k, v in environment.items()], uv, "pip", "install",
         "--compile-bytecode", "--python", str(python), source)
    sudo("rm", "-rf", str(base / "uvcache"))
    sudo("chmod", "-R", "a+rX", str(base))
    return python


class Account:
    """A throwaway OS account (sudo mode only), removed in teardown."""

    made: list[Account] = []

    def __init__(self, prefix: str) -> None:
        import pwd

        self.name = prefix + secrets.token_hex(3)
        sudo("useradd", "-m", "-s", "/usr/sbin/nologin", self.name)
        Account.made.append(self)
        entry = pwd.getpwnam(self.name)
        self.uid, self.home = str(entry.pw_uid), entry.pw_dir

    def remove(self) -> None:
        sudo("pkill", "-KILL", "-u", self.name, check=False)
        time.sleep(0.3)
        sudo("userdel", "-r", "-f", self.name, check=False)


def sudo(*argv: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(
        ["sudo", "-n", *argv], capture_output=True, text=True, input=input,
        stdin=None if input is not None else subprocess.DEVNULL, timeout=300,
    )
    if check and done.returncode != 0:
        raise AssertionError(f"sudo {' '.join(argv)}: {done.stderr or done.stdout}")
    return done


def sudo_available() -> bool:
    if not sys.platform.startswith("linux") or not shutil.which("sudo"):
        return False
    return subprocess.run(
        ["sudo", "-n", "true"], capture_output=True, stdin=subprocess.DEVNULL
    ).returncode == 0


def as_user(user: Account | None, argv: list[str], environment: dict[str, str]) -> list[str]:
    """`argv` as `user`, with exactly `environment` and nothing of this
    script's; unchanged for no user (the caller passes `environment` itself)."""
    if user is None:
        return argv
    base = {"HOME": user.home, "PATH": "/usr/local/bin:/usr/bin:/bin", **environment}
    return ["sudo", "-n", "-u", user.name, "env", "-i", *[f"{k}={v}" for k, v in base.items()], *argv]


def kill_user(user: Account, signal: str = "TERM") -> None:
    sudo("pkill", f"-{signal}", "-u", user.name, check=False)


def put_file(path: Path, data: bytes, mode: int = 0o644, *, root: bool) -> None:
    """Write a file the way the machine's administrator would: root-owned and
    read-only to everyone else in sudo mode, plain otherwise."""
    if not root:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
    try:
        sudo("install", "-D", "-m", f"{mode:o}", "-o", "root", "-g", "root", handle.name, str(path))
    finally:
        os.unlink(handle.name)


#: The real worker with its one account refusal removed, for the one-account
#: run only (see the docstring): `accounts.refuse_to_serve` is what forbids
#: serving as the site host's own account, and with one account that is the
#: only account there is. Everything else is the worker's own code.
STAND_IN = (
    "import sys;from eugene_plexus_site_host import accounts, worker;"
    "accounts.refuse_to_serve=lambda *a,**k:None;worker.main(sys.argv[1:])"
)

#: A stranger's connection to the channel, from whatever account runs it.
RAW_CONNECT = (
    "import asyncio,json,sys\n"
    "from eugene_plexus_site_host import local_channel\n"
    "async def main():\n"
    "    conn = await local_channel.connect(sys.argv[1], sys.argv[2], "
    "{'protocol': 1, 'pid': 0, 'account': 'x'})\n"
    "    print(json.dumps(await asyncio.wait_for(conn.receive(), 10)))\n"
    "asyncio.run(main())\n"
)

#: What the site host's account tries on the links file: every write refused.
TRY_TO_LINK = (
    "import sys,os\n"
    "out=[]\n"
    "for label, action in ("
    "('append', lambda: open(sys.argv[1], 'a').write('x')),"
    "('truncate', lambda: open(sys.argv[1], 'w').write('{}')),"
    "('create beside', lambda: open(os.path.join(os.path.dirname(sys.argv[1]), 'links2.json'), 'w')),"
    "('rename', lambda: os.rename(sys.argv[1], sys.argv[1] + '.old')),"
    "('unlink', lambda: os.unlink(sys.argv[1]))):\n"
    "    try:\n"
    "        action(); out.append(label + ': WROTE')\n"
    "    except PermissionError: out.append(label + ': PermissionError')\n"
    "print('|'.join(out))\n"
)


class SiteHost:
    """One site on this machine: its data directory, its `join`, the host
    process started with the environment the agent builds, and the starter's
    part beside it: the links file, the channel, the local-server list and the
    workers (`Worker`)."""

    running: list[subprocess.Popen[bytes]] = []
    temps: list[Path] = []

    def __init__(
        self,
        python: Path,
        data: Path,
        *,
        user: Account | None = None,
        site_dir: Path | None = None,
        channel: str | None = None,
        logs: Path | None = None,
    ) -> None:
        self.python, self.data, self.user = python, data, user
        data.mkdir(parents=True, exist_ok=True)
        self.label = data.parent.name
        self.logs = logs or data.parent
        self.port = free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.environment: dict[str, str] = {}
        self.site_dir = site_dir or data.parent / "site"
        self.links_file = self.site_dir / "links.json"
        self.servers_file = self.site_dir / "servers.yaml"
        self.protected: list[str] = []
        self.linked: list[dict[str, Any]] = []
        self.keys: dict[str, tuple[str, Any, str]] = {}
        self.last_approval: tuple[str, dict[str, Any]] | None = None
        self.workers: dict[str, Worker] = {}
        if channel is None:
            if os.name == "nt":
                channel = rf"\\.\pipe\eugene-plexus-site-{secrets.token_hex(6)}"
            else:
                short = Path(tempfile.mkdtemp(prefix="ep-js-", dir="/tmp"))
                SiteHost.temps.append(short)
                channel = str(short / "c.sock")
        self.channel = channel
        self._account: str | None = None

    # --- the host's own account ------------------------------------------------

    @property
    def account(self) -> str:
        """The account this host runs as: a uid in decimal, or a SID."""
        if self._account is None:
            if self.user is not None:
                self._account = self.user.uid
            else:
                self._account = account_of(self.python)
        return self._account

    @property
    def command(self) -> list[str]:
        if os.environ.get("EP_SITE_HOST_DEBUG"):
            return [str(self.python), "-c",
                    "import logging,sys;logging.basicConfig(level=logging.DEBUG);"
                    "from eugene_plexus_site_host.__main__ import main;main(sys.argv[1:])"]
        return [str(self.python), "-m", SITE_HOST_ENTRY]

    # --- the starter's part ------------------------------------------------------

    def link(self, subject: str, name: str, account: str, account_name: str) -> None:
        self.linked = [e for e in self.linked if e["subject"] != subject]
        entry: dict[str, Any] = {"subject": subject, "name": name, "account": account,
                                 "accountName": account_name,
                                 "linkedAt": "2026-10-06T00:00:00+00:00"}
        if subject in self.keys:
            entry["keys"] = [self._key_entry(subject)]
        self.linked.append(entry)

    # --- J14a: the person's own key, and approving at the machine ------------------

    def _key_entry(self, subject: str) -> dict[str, Any]:
        ident, _key, public = self.keys[subject]
        return {"id": ident, "alg": "Ed25519", "publicKey": public, "label": "the harness",
                "addedAt": "2026-10-06T00:00:00+00:00"}

    def pin(self, subject: str) -> str:
        """The starter pins `subject`'s key at the machine (J14a): made here as
        their browser would make it, its public half on their link."""
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        key = Ed25519PrivateKey.generate()
        raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ident = hashlib.sha256(raw).hexdigest()[:32]
        self.keys[subject] = (ident, key, base64.b64encode(raw).decode())
        for entry in self.linked:
            if entry["subject"] == subject:
                entry["keys"] = [self._key_entry(subject)]
        self.write_links()
        return ident

    def held_api(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        """The site host's own `/v1/held`, with the token in its data directory."""
        token = self.read("local_token").strip()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            return exc.code, None

    def held(self, subject: str) -> list[dict[str, Any]]:
        ident = self.keys[subject][0]
        status, value = self.held_api(
            "GET", f"/v1/held?subject={urllib.parse.quote(subject)}&key={ident}"
        )
        assert status == 200, status
        return list(value["items"])

    def approve(self, subject: str) -> list[dict[str, Any]]:
        """The person approves, at the machine, everything held for them, one
        at a time: each approval moves their sequence on, so the list is read
        again after each, as the page does."""
        ident, key, _ = self.keys[subject]
        answers: list[dict[str, Any]] = []
        for _ in range(16):
            items = self.held(subject)
            if not items:
                return answers
            item = items[0]
            approval = {
                "subject": subject, "envelope": item["envelope"], "key": ident,
                "signature": base64.b64encode(key.sign(item["envelope"].encode())).decode(),
            }
            status, answer = self.held_api("POST", f"/v1/held/{item['id']}/approve", approval)
            assert status == 200 and answer["status"] == "done", (status, answer, item)
            self.last_approval = (item["id"], approval)
            answers.append(answer)
        raise AssertionError("more than 16 changes were held")

    def reject_all(self, subject: str) -> int:
        items = [i for i in self.held(subject) if i["id"] != "rules"]
        for item in items:
            status, _ = self.held_api(
                "POST", f"/v1/held/{item['id']}/reject", {"subject": subject}
            )
            assert status == 204, status
        return len(items)

    def write_links(self) -> None:
        put_file(self.links_file, json.dumps({"version": 1, "links": self.linked}).encode(),
                 root=self.user is not None)

    def add_worker(self, name: str, account: str, user: Account | None, protect: list[str]) -> Worker:
        worker = Worker(self, name, account, user, protect)
        self.workers[name] = worker
        return worker

    def start_workers(self) -> None:
        for worker in self.workers.values():
            worker.start()

    def stop_workers(self) -> None:
        for worker in self.workers.values():
            worker.stop()

    # --- running the host's own commands ------------------------------------------

    def run(self, *arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        argv = as_user(self.user, [*self.command, *arguments], {})
        return subprocess.run(
            argv, input=stdin, capture_output=True, text=True,
            env=clean_environment(), timeout=120, cwd="/" if self.user else self.data,
            stdin=None if stdin is not None else subprocess.DEVNULL,
        )

    def join(
        self, url: str, token: str, owner: str, label: str, password: str, root_key: str | None
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            "join", "--url", url, "--token", token, "--owner", owner,
            "--label", label, "--data-dir", str(self.data),
        ]
        if root_key:
            arguments += ["--root-key", root_key]
        return self.run(*arguments, stdin=password + "\n")

    def leave(self) -> subprocess.CompletedProcess[str]:
        return self.run("leave", "--data-dir", str(self.data))

    def pair(self) -> subprocess.Popen[str]:
        """`pair`, as `install.sh --site-pair` runs it (J14a.3): it shows the
        code and waits for the passkey."""
        argv = as_user(self.user, [*self.command, "pair", "--data-dir", str(self.data),
                                   "--port", str(self.port)], {})
        return subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=clean_environment(), cwd="/" if self.user else self.data,
            stdin=subprocess.DEVNULL,
        )

    def check_person(self, name: str, password: str) -> subprocess.CompletedProcess[str]:
        return self.run("check-person", "--name", name, "--data-dir", str(self.data),
                        stdin=password + "\n")

    # --- reading the host's own directory (it may belong to another account) --------

    def read(self, name: str) -> str:
        if self.user is None:
            return (self.data / name).read_text(encoding="utf-8")
        return sudo("-u", self.user.name, "cat", str(self.data / name)).stdout

    def exists(self, name: str) -> bool:
        if self.user is None:
            return (self.data / name).exists()
        return sudo("-u", self.user.name, "test", "-e", str(self.data / name), check=False).returncode == 0

    def all_text(self) -> str:
        if self.user is None:
            return "".join(p.read_text(errors="ignore") for p in self.data.rglob("*") if p.is_file())
        return sudo("-u", self.user.name, "find", str(self.data), "-type", "f", "-exec", "cat", "{}", "+").stdout

    def record(self) -> dict[str, Any]:
        return dict(json.loads(self.read("site.json")))

    # --- the process ----------------------------------------------------------------

    def start(self, environment: dict[str, str] | None = None) -> None:
        self.stop()
        self.environment = environment if environment is not None else self.environment
        launch = {
            "SITE_HOST_PROTECTED_ROOTS": json.dumps(self.protected),
            "SITE_HOST_CHANNEL": self.channel,
            "SITE_HOST_LINKS_FILE": str(self.links_file),
            "SITE_HOST_LOCAL_SERVERS_FILE": str(self.servers_file),
            **self.environment,
            "EUGENE_PLEXUS_APP_DATA_DIR": str(self.data),
            "EUGENE_PLEXUS_APP_BIND_PORT": str(self.port),
            "EUGENE_PLEXUS_APP_ACCOUNT_KIND": "windows_service" if os.name == "nt" else "systemd",
        }
        self.process = subprocess.Popen(
            as_user(self.user, self.command, launch),
            cwd="/" if self.user else self.data,
            stdin=subprocess.DEVNULL,
            env={**clean_environment(), **launch} if self.user is None else clean_environment(),
            stdout=subprocess.DEVNULL,
            stderr=open(self.logs / f"{self.label}.err", "ab"),  # noqa: SIM115
        )
        SiteHost.running.append(self.process)
        deadline = time.perf_counter() + 30
        while True:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return
            except OSError:
                if self.process.poll() is not None or time.perf_counter() > deadline:
                    raise SystemExit("the site host did not start:\n" + self.log()) from None
                time.sleep(0.2)

    def restart_all(self, environment: dict[str, str] | None = None) -> None:
        """The host and every worker, as the agent restarts them when the
        links page, the channel or the local-server list changes."""
        self.stop_workers()
        self.start(environment)
        self.start_workers()

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            if self.user is not None:
                kill_user(self.user)
            else:
                process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                if self.user is not None:
                    kill_user(self.user, "KILL")
                process.kill()
                process.wait(timeout=20)

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
        parts = []
        for path in [self.logs / f"{self.label}.err", *(w.log_path for w in self.workers.values())]:
            if path.exists():
                parts.append(f"--- {path.name}\n" + path.read_text(errors="replace")[-1500:])
        return "\n".join(parts)


class Worker:
    """One person's worker beside a host: `python -I -m
    eugene_plexus_site_host.worker`, as that person's account (sudo mode) or,
    in the one-account run, as `STAND_IN`."""

    def __init__(
        self, host: SiteHost, name: str, account: str, user: Account | None, protect: list[str]
    ) -> None:
        self.host, self.name, self.account, self.user, self.protect = host, name, account, user, protect
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path = host.logs / f"{host.label}.{name}.worker.err"

    def arguments(self, account: str | None = None, host_account: str | None = None) -> list[str]:
        args = [
            "--account", account or self.account, "--channel", self.host.channel,
            "--host", host_account or self.host.account, "--servers", str(self.host.servers_file),
        ]
        for path in self.protect:
            args += ["--protect", path]
        return args

    def command(self, *arguments: str) -> list[str]:
        python = str(self.host.python)
        if self.user is None:
            return [python, "-I", "-c", STAND_IN, *arguments]
        return [python, "-I", "-m", "eugene_plexus_site_host.worker", *arguments]

    def start(self) -> None:
        self.stop()
        self.process = subprocess.Popen(
            as_user(self.user, self.command(*self.arguments()), {}),
            cwd="/" if self.user else self.host.data,
            stdin=subprocess.DEVNULL,
            env=clean_environment(),
            stdout=subprocess.DEVNULL,
            stderr=open(self.log_path, "ab"),  # noqa: SIM115
        )
        SiteHost.running.append(self.process)

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        if self.user is not None:
            kill_user(self.user)
        else:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            if self.user is not None:
                kill_user(self.user, "KILL")
            process.kill()
            process.wait(timeout=15)


def account_of(python: Path) -> str:
    """The uid or SID this script's own account has, as the site host's code
    says it (not as this script guesses it)."""
    done = subprocess.run(
        [str(python), "-I", "-c", "from eugene_plexus_site_host import accounts;print(accounts.own())"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def site_token(host: SiteHost) -> str:
    """A token the site's own key signs, as its host signs one for a poll."""
    import jwt
    from cryptography.hazmat.primitives import serialization

    site = json.loads(host.read("site.json"))["site"]
    key = serialization.load_pem_private_key(host.read("site_key.pem").encode(), password=None)
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
    sudo_mode = sudo_available() and not args.no_sudo
    base: Path | None = None
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
        source = site_host_source(args.site_host_source)
        if sudo_mode:
            base = Path(f"/opt/ep-acc-{secrets.token_hex(4)}")
            sudo("install", "-d", "-m", "755", str(base))
            python = install_site_host_for_all(base, source)
            acc_a, acc_j, acc_s, acc_z = (Account(p) for p in ("epa", "epj", "eps", "epz"))
            sudo("install", "-d", "-m", "755", "-o", "root", str(base / "site"))
            sudo("install", "-d", "-m", "755", "-o", acc_s.name, str(base / "run"))
            sudo("install", "-d", "-m", "755", "-o", acc_s.name, str(base / "desk"))
            sudo("install", "-d", "-m", "700", "-o", acc_s.name, str(base / "desk" / "data"))
            sudo("install", "-d", "-m", "777", str(base / "shared"))
            print(f"sudo mode: host as {acc_s.name}, people as {acc_a.name} and {acc_j.name} "
                  f"under {base}", flush=True)
        else:
            python = install_site_host(work, source)
            print("one-account mode: " + ("--no-sudo" if args.no_sudo else "no passwordless sudo "
                  "here") + "; workers are the stand-in for a second account", flush=True)

        # ---- the owner sets the root up ----------------------------------
        assert http.post(f"{control}/v1/auth/initialize", json={"passphrase": PASSPHRASE}).status_code == 204
        session = http.post(f"{control}/v1/auth/login", json={"passphrase": PASSPHRASE}).json()
        http.headers["Authorization"] = "Bearer " + session["sessionToken"]
        client = http.post(
            f"{control}/v1/oidc/clients",
            json={"name": "Workbench", "owner": "app:workbench@root", "redirectUris": [CALLBACK]},
        ).json()
        app_id = client["client"]["clientId"]
        for name in ("ada", "bo", "jo"):
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
        jo = sign_in(plain, control, client, "jo", PASSWORD)
        owner = sign_in(plain, control, client, "operator", PASSPHRASE)
        ok("the root is set up: three people and Workbench's sign-in")

        # ---- 1. J31: the public route carries seven site paths and nothing else
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
            "/v1/sites/links/check",
        ):
            reached = unverified.post(f"{nodes}{path}", json={})
            assert reached.status_code in (401, 422), (path, reached.status_code, reached.text[:200])
        wrong_way = unverified.get(f"{nodes}/v1/sites/links/check")
        assert wrong_way.status_code == 403 and "machines only" in wrong_way.text, wrong_way.text
        ok("from another network the nodes name answers the seven site paths (the signed TLS list "
           "and the six site routes, the person check among them) and refuses the trust bundle, "
           "a node's enrollment, the person check by any other method, and everything else")

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
        if sudo_mode:
            assert base is not None
            desk = SiteHost(python, base / "desk" / "data", user=acc_s, site_dir=base / "site",
                            channel=str(base / "run" / "c.sock"), logs=work)
        else:
            desk = SiteHost(python, work / "desk" / "data")
        hosts.append(desk)
        desk.protected = [str(desk.site_dir)]
        wrong_key = desk.join(
            nodes, invitation["token"], "ada", "desk", PASSWORD,
            base64.b64encode(b"\x01" * 32).decode(),
        )
        assert wrong_key.returncode != 0 and "could not be trusted" in (
            wrong_key.stdout + wrong_key.stderr
        ), wrong_key.stdout + wrong_key.stderr
        assert not desk.exists("site.json")
        leaked = desk.join(nodes, invitation["token"], "ada", "desk", "not her password", invitation["rootKey"])
        assert leaked.returncode != 0 and "refused" in (leaked.stdout + leaked.stderr), (
            leaked.stdout + leaked.stderr
        )
        assert http.get(f"{control}/v1/sites").json()["sites"] == []
        assert not desk.exists("site.json")
        joined = desk.join(nodes, invitation["token"], "ada", "desk", PASSWORD, invitation["rootKey"])
        assert joined.returncode == 0, joined.stdout + joined.stderr
        assert "ada's job site desk" in joined.stdout, joined.stdout
        record = desk.record()
        assert record["owner"] == people["ada"] and record["ownerName"] == "ada", record
        assert record["rootKey"] == invitation["rootKey"] and record["url"] == nodes
        assert json.loads(desk.read("root_tls.json"))["origin"] == nodes
        assert PASSWORD not in desk.all_text()
        site_id = record["site"]
        assert re.fullmatch(r"s-[a-z2-7]{26}", site_id), site_id
        reused = desk.join(nodes, invitation["token"], "ada", "other", PASSWORD, invitation["rootKey"])
        assert reused.returncode != 0
        ok("over the public route a wrong root key sends nothing, a wrong password refuses the "
           "join and keeps the invitation, and the right one joins, pinned to the root's identity "
           "key, as ada's site; her password is kept nowhere on it")

        # ---- 4. started, it polls; the console lists it -------------------
        # The machine's starter, played: the owner's link, the channel, a worker per
        # linked person (sudo mode: ada as epa and jo as epj; one account: ada's
        # link is this account and jo has none, so her calls run in ada's worker).
        if sudo_mode:
            desk.link(people["ada"], "ada", acc_a.uid, acc_a.name)
            desk.link(people["jo"], "jo", acc_j.uid, acc_j.name)
            desk.add_worker("ada", acc_a.uid, acc_a, desk.protected)
            desk.add_worker("jo", acc_j.uid, acc_j, desk.protected)
        else:
            desk.link(people["ada"], "ada", desk.account, "harness")
            desk.add_worker("ada", desk.account, None, desk.protected)
        desk.write_links()
        desk.start()
        desk.start_workers()
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
        if sudo_mode:
            assert base is not None
            folder = base / "shared"  # root's, mode 0777: what the OS lets each account do is its own
        else:
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
                sites = [x for x in call("job-sites", ada).json()["sites"] if x["id"] == site_id]
                if sites and predicate(sites[0]):
                    return dict(sites[0])
                if time.perf_counter() > deadline:
                    raise AssertionError(f"{what}: {sites}")
                time.sleep(0.3)

        def workers_up(*names: str) -> None:
            """The root's cache of the site's last report says each named
            person's worker is connected."""
            deadline = time.perf_counter() + 40
            while True:
                sites = [x for x in call("job-sites", ada).json()["sites"] if x["id"] == site_id]
                links = {e["subject"]: e for e in (sites[0].get("links") or [])} if sites else {}
                if all(links.get(people[n], {}).get("available") for n in names):
                    return
                if time.perf_counter() > deadline:
                    raise AssertionError(f"a worker never connected for {names}: {links}" + chr(10) + desk.log())
                time.sleep(0.5)

        workers_up(*(["ada", "jo"] if sudo_mode else ["ada"]))

        def signing(state: str) -> dict[str, Any]:
            return settle(lambda s: (s.get("signing") or {}).get("state") == state,
                          f"the site never reported its signing state as {state}")

        # ---- 4b. no tool runs until the owner's key is pinned (J14a, J48) -----
        # Straight to the site, past the root's own checks: the site's refusal.
        unsigned = forge(kind="enqueue", subject=people["ada"], server="files",
                         request=rpc("tools/list"))
        assert unsigned.json()["status"] == "failed", unsigned.text
        assert "own key" in unsigned.json()["message"], unsigned.text
        signing("unsigned")
        desk.pin(people["ada"])
        signing("signed")  # no rules yet: nothing to approve as a whole (J52)
        ok("J14a: until its owner's key is pinned at the machine the site runs no tool and says "
           "why; with the key and no rules yet it is signed")

        read = {"name": "read_text", "arguments": {"folder": "Notes", "path": "note.txt"}}
        mine_only = call("job-sites", bo).json()["sites"]
        assert mine_only == [], mine_only
        added = call(f"job-sites/{site_id}/folders", ada, name="Notes", path=str(folder), writable=True)
        assert added.status_code == 202 and added.json()["held"] is True, added.text
        assert "approve it there with your key" in added.json()["message"], added.text
        assert settle(lambda s: s.get("signing", {}).get("held") == 1, "held")["folders"] == []
        (registered,) = desk.approve(people["ada"])
        folder_id = registered["result"]["id"]
        assert registered["result"]["people"] == []
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
        assert granted.status_code == 202, granted.text
        (words,) = desk.held(people["ada"])
        # Bo has no account here: his name is the root's, and the page says so (J54).
        assert any("bo (as Eugene names them" in w for w in words["words"]), words
        desk.approve(people["ada"])
        reported = settle(lambda s: len(s["folders"][0]["people"]) == 2, "the grant never reported")
        assert {p["name"] for p in reported["folders"][0]["people"]} == {"ada", "bo"}
        listed_servers = call("sites/servers", bo).json()["servers"]
        files = next(s for s in listed_servers if s["server"] == "files")
        assert files["site"] == site_id and files["folders"] == [
            {"id": folder_id, "name": "Notes", "writable": False}
        ]
        tools = mcp(bo, "files", "tools/list")
        assert tools.status_code == 200, tools.text
        offered = {t["name"]: t["inputSchema"]["properties"]["folder"]["enum"]
                   for t in tools.json()["response"]["result"]["tools"]}
        # 2b.3a: a reader may also search; a writer also edits.
        assert offered == {name: ["Notes"] for name in ("list_directory", "read_text", "glob", "grep")}, offered
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
        assert call(f"job-sites/{site_id}/folders/{folder_id}/people", ada,
                    people=[{"name": "ada", "writable": False},
                            {"name": "bo", "writable": True}]).status_code == 202
        desk.approve(people["ada"])
        settle(lambda s: any(p["writable"] for p in s["folders"][0]["people"]), "write grant")
        wrote = mcp(bo, "files", "tools/call", {"name": "write_text", "arguments": {
            "folder": "Notes", "path": "new.txt", "text": "bo was here", "expectedSha256": ""}})
        assert wrote.json()["status"] == "done", wrote.text
        assert (folder / "new.txt").read_text(encoding="utf-8") == "bo was here"
        workspace_tools_check(folder, work, lambda params: mcp(bo, "files", "tools/call", params))
        ok("2b.3a, through the root: bo finds files by name (newest first, .gitignore and a link "
           "to outside the folder passed over), searches their contents with line numbers, reads "
           "any part of a 20,000-line file with the whole file's hash, and edits one exact passage "
           "in place; a stale hash, an ambiguous passage and a pattern that never finishes are "
           "refused or stopped, and every answer stays under 70,000 bytes")
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
           "was decided, never contents, and only its owner reads it; each grant answered 202 "
           "held and was applied only once ada's key approved it at the machine (J14a)")

        # ---- 6. editing the root's state is not enough -------------------
        assert forge(kind="owner", owner=people["bo"]).status_code == 200
        time.sleep(2)  # a poll or two, each naming bo
        assert desk.record()["owner"] == people["ada"]
        taken = call(f"job-sites/{site_id}/folders/{folder_id}/people", bo,
                     people=[{"name": "bo", "writable": True}])
        assert taken.status_code == 422 and "Only this machine's owner" in taken.text, taken.text
        manage = forge(kind="manage", subject=people["bo"], action="folder.people",
                       arguments={"id": folder_id, "people": [{"subject": people["bo"], "writable": True}]})
        assert manage.status_code == 200, manage.text
        assert manage.json()["status"] == "failed" and "Only this machine's owner" in manage.json()["message"], manage.text
        assert forge(kind="owner", owner=people["ada"]).status_code == 200
        # J14a: the root forging a grant in the owner's own name is held, never applied.
        in_her_name = forge(kind="manage", subject=people["ada"], action="folder.people",
                            arguments={"id": folder_id, "people": [
                                {"subject": people["ada"], "writable": False},
                                {"subject": people["bo"], "writable": True},
                                {"subject": people["jo"], "writable": True}]})
        assert in_her_name.json()["status"] == "held", in_her_name.text
        assert desk.reject_all(people["ada"]) == 1
        assert not any(p["name"] == "jo" for p in settle(lambda s: True, "")["folders"][0]["people"])
        other = forge(kind="enqueue", enrolledAt="2001-01-01T00:00:00+00:00", subject=people["ada"],
                      server="files", request=rpc("tools/call", read))
        assert other.status_code == 200, other.text
        assert other.json()["status"] == "failed" and "not for this site" in other.json()["message"], other.text
        assert (folder / "new.txt").read_text(encoding="utf-8") == "bo was here"
        ok("rule 2: the root naming bo as the site's owner, an operation queued in his name, and "
           "one bound to an earlier enrollment all get nothing run: the site refuses (its pinned "
           "owner; 'not for this site'); a grant the root forges in ada's own name is held, not "
           "applied, and she turns it down at the machine (J14a)")

        # ---- 7. the site's token opens its own routes only ---------------
        token = site_token(desk)
        bearer = {"Authorization": "Bearer " + token}
        for origin in (control, nodes):
            client_ = unverified if origin == nodes else plain
            for path in ("/v1/nodes", "/v1/sites", "/v1/config", "/v1/people"):
                refused = client_.get(f"{origin}{path}", headers=bearer)
                assert refused.status_code in (401, 403), (origin, path, refused.status_code)
            assert client_.post(f"{origin}/v1/sites/invitations", headers=bearer,
                                json={"owner": people["ada"]}).status_code in (401, 403)
        own = plain.post(f"{control}/v1/sites/operations/none/claim", headers=bearer)
        assert own.status_code == 404, own.text  # its own route, answered
        tampered = plain.post(f"{control}/v1/sites/leave", headers={"Authorization": "Bearer " + token[:-4] + "AAAA"})
        assert tampered.status_code == 401, tampered.text
        ok("the site's token opens its own routes only: GET /v1/nodes and GET /v1/sites are "
           "refused with it (directly and through the nodes name), and so is minting an invitation")

        # ---- a fifth tool, added at the machine --------------------------
        local_server_check(desk, work, base, call, mcp, settle, site_id, ada, bo, people["ada"])

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
        assert opted.status_code == 202, opted.text
        desk.approve(people["ada"])
        assert desk.last_approval is not None
        replay = desk.last_approval[1]
        settle(lambda s: s["ownerInDevMode"], "the opt-in never reported")
        opened = mcp(owner, "files", "tools/call", read)
        assert opened.status_code == 200 and opened.json()["status"] == "done", opened.text
        assert opened.json()["installMode"] == "dev"
        back = http.patch(f"{control}/v1/config", json={"installMode": "production"})
        assert back.status_code == 200
        assert mcp(owner, "files", "tools/call", read).status_code == 403
        assert [s["dev"] for s in http.get(f"{control}/v1/sites").json()["sites"]] == [None]
        # J51: turning it off is applied at once; J14a: asked again, the old
        # approval of the same change does not apply it a second time.
        off = call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=False)
        assert off.status_code == 200 and off.json()["ownerInDevMode"] is False, off.text
        assert call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=True).status_code == 202
        (again,) = desk.held(people["ada"])
        status, replayed = desk.held_api("POST", f"/v1/held/{again['id']}/approve", replay)
        assert status == 200 and replayed["status"] == "failed", (status, replayed)
        assert "older than one already used" in replayed["message"], replayed
        assert desk.reject_all(people["ada"]) == 1
        ok("production: Eugene's owner cannot read it, by grant or by listing; dev mode adds a "
           "section to the console and opens only once the site's owner lets them in (J6e); "
           "back in production it stops at once; the opt-in was held for ada's key, turning it "
           "off needed none (J51), and her old approval did not apply it when asked again")

        # ---- J14a.3: a passkey from Workbench, through the root ------------
        passkey_check(desk, call, forge, settle, site_id, ada, people["ada"])
        desk.pin(people["ada"])  # the key at the machine again, for the checks below

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
        agent_site_join(python, work, nodes)
        per_user_site(python, work, nodes, http, control, people, workbench, ada, source,
                      acc_z if sudo_mode else None, args.stranger_command)

        # ---- 13-18. slice 2b.2: whose account runs a call ----------------------
        two_b_two(SimpleNamespace(
            desk=desk, sudo_mode=sudo_mode, folder=folder, people=people, ada=ada, bo=bo, jo=jo,
            call=call, mcp=mcp, settle=settle, site_id=site_id, folder_id=folder_id, http=http,
            plain=plain, unverified=unverified, control=control, nodes=nodes,
            acc_a=acc_a if sudo_mode else None, acc_j=acc_j if sudo_mode else None,
            acc_s=acc_s if sudo_mode else None, acc_z=acc_z if sudo_mode else None,
        ))

        # ---- 12. the site leaves ----------------------------------------
        desk.stop_workers()
        desk.stop()
        left = desk.leave()
        assert left.returncode == 0 and "no longer a job site" in left.stdout, left.stdout + left.stderr
        assert not desk.exists("site.json") and not desk.exists("site_key.pem")
        assert site_id not in {s["id"] for s in http.get(f"{control}/v1/sites").json()["sites"]}
        refused = plain.post(f"{control}/v1/sites/leave", headers={"Authorization": "Bearer " + token})
        assert refused.status_code == 401, refused.text
        ok("the site's own `leave` tells the root and forgets its enrollment: the root lists it "
           "no more and its old token is refused")
    finally:
        for host in hosts:
            host.stop_workers()
            host.stop()
        for process in SiteHost.running:
            if process.poll() is None:
                process.kill()
        for account in Account.made:
            account.remove()
        if base is not None:
            sudo("rm", "-rf", str(base), check=False)
        for short in SiteHost.temps:
            shutil.rmtree(short, ignore_errors=True)
        (work / "stop").write_text("")
        try:
            root.wait(timeout=30)
        except subprocess.TimeoutExpired:
            root.kill()
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"kept {work}")


class Passkey:
    """A passkey as a browser's authenticator holds it (ES256), made for one
    relying party: what Workbench's page gets from WebAuthn, here."""

    def __init__(self, rp_id: str) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.spki = self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.id = hashlib.sha256(self.spki).hexdigest()[:32]
        self.credential_id = _b64url(secrets.token_bytes(16))
        self.count = 0

    def pairing(self, code: str, site: str, person: str) -> dict[str, Any]:
        """What Workbench sends: the public half and the MAC its browser
        computed from the code typed (`SitePasskeyBinding`)."""
        import hmac

        public = base64.b64encode(self.spki).decode()
        binding = json.dumps(
            {"typ": "eugene-plexus/site-passkey", "v": 1, "site": site, "person": person,
             "credentialId": self.credential_id, "publicKey": public, "alg": -7,
             "rpId": self.rp_id},
            sort_keys=True, separators=(",", ":"),
        )
        normalized = code.upper().replace("-", "")
        secret = hashlib.pbkdf2_hmac(
            "sha256", normalized.encode(), f"eugene-plexus/site-passkey:{site}:{person}".encode(),
            600_000, 32,
        )
        mac = _b64url(hmac.new(secret, binding.encode(), hashlib.sha256).digest())
        return {"credentialId": self.credential_id, "publicKey": public, "alg": -7,
                "rpId": self.rp_id, "label": "the harness's passkey", "mac": mac}

    def approval(self, envelope: str) -> dict[str, Any]:
        """`navigator.credentials.get()` over the envelope, as Workbench sends it."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        self.count += 1
        client = json.dumps({
            "type": "webauthn.get",
            "challenge": _b64url(hashlib.sha256(envelope.encode()).digest()),
            "origin": f"https://{self.rp_id}",
            "crossOrigin": False,
        }).encode()
        auth = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05])
                + self.count.to_bytes(4, "big"))
        signature = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"envelope": envelope, "key": self.id, "credentialId": self.credential_id,
                "authenticatorData": _b64url(auth), "clientDataJSON": _b64url(client),
                "signature": _b64url(signature)}


def workspace_tools_check(folder: Path, work: Path, call_tool: Any) -> None:
    """2b.3a's tools on a real site, through the root (`job-sites-own-enrollment.md`
    §3.3): a small repository inside the shared folder, and a link from it to
    a folder outside, which no tool may follow."""
    repo = folder / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "build").mkdir()
    (repo / "src" / "app.py").write_text(
        "def greet():\n    return 'hello'\n\ndef part():\n    return 'hello'\n",
        encoding="utf-8", newline="\n",
    )
    # Sudo mode: the worker runs as another account, which the folder (0777)
    # lets change what it may.
    os.chmod(repo / "src" / "app.py", 0o666)
    (repo / "build" / "app.py").write_text("hello = 'built'\n", encoding="utf-8", newline="\n")
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8", newline="\n")
    long = repo / "long.txt"
    long.write_text("".join(f'line {n} "quoted"\n' for n in range(1, 20001)),
                    encoding="utf-8", newline="\n")
    outside = work / "outside-the-folder"
    outside.mkdir()
    (outside / "secret.py").write_text("hello = 'outside'\n", encoding="utf-8", newline="\n")
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(outside), str(repo / "linked"))
    else:
        (repo / "linked").symlink_to(outside, target_is_directory=True)

    def use(name: str, **arguments: Any) -> tuple[bool, Any]:
        answer = call_tool({"name": name, "arguments": {"folder": "Notes", **arguments}})
        assert answer.status_code == 200, answer.text
        value = answer.json()
        assert value["status"] == "done", answer.text
        assert len(json.dumps(value["response"], ensure_ascii=False).encode()) < 70_000
        result = value["response"]["result"]
        text = result["content"][0]["text"]
        return bool(result["isError"]), (text if result["isError"] else json.loads(text))

    error, found = use("glob", pattern="**/*.py", path="repo")
    assert not error and found["paths"] == ["repo/src/app.py"], found
    assert found["skipped"] == {"ignored": 1, "links": 1}, found
    error, lines = use("grep", pattern="hello", path="repo", output="content")
    assert not error, lines
    assert lines["lines"] == "repo/src/app.py:2:    return 'hello'\nrepo/src/app.py:5:    return 'hello'", lines
    digest = hashlib.sha256(long.read_bytes()).hexdigest()
    error, first = use("read_text", path="repo/long.txt")
    assert not error and first["sha256"] == digest and first["totalLines"] == 20000, first
    assert first["toLine"] < 2000 and "size limit" in first["stoppedShort"], first
    error, last = use("read_text", path="repo/long.txt", offset=19999, limit=5)
    assert not error and last["text"] == 'line 19999 "quoted"\nline 20000 "quoted"\n', last
    error, read = use("read_text", path="repo/src/app.py")
    assert not error, read
    error, twice = use("edit_text", path="repo/src/app.py", oldText="'hello'",
                       newText="'hello, bo'", expectedSha256=read["sha256"])
    assert error and "appears 2 times" in twice, twice
    before = os.stat(repo / "src" / "app.py").st_ino
    error, edited = use("edit_text", path="repo/src/app.py", oldText="def greet():\n    return 'hello'",
                        newText="def greet():\n    return 'hello, bo'", expectedSha256=read["sha256"])
    assert not error and edited["replaced"] == 1, edited
    assert (repo / "src" / "app.py").read_text(encoding="utf-8").startswith(
        "def greet():\n    return 'hello, bo'\n")
    assert os.stat(repo / "src" / "app.py").st_ino == before
    error, stale = use("edit_text", path="repo/src/app.py", oldText="part", newText="piece",
                       expectedSha256=read["sha256"])
    assert error and "changed" in stale, stale
    # A pattern that would run for years on this line stops at the search's
    # own 10 s, under the site host's 25 s for a call (J74).
    (repo / "slow.txt").write_text("a" * 60 + "\n", encoding="utf-8", newline="\n")
    started = time.perf_counter()
    error, stopped = use("grep", pattern="(a|aa)+c", path="repo/slow.txt")
    assert not error and "stopped after 10 seconds" in stopped["stoppedShort"], stopped
    assert time.perf_counter() - started < 20


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def passkey_check(
    desk: Any, call: Any, forge: Any, settle: Any, site_id: str, ada: str, subject: str
) -> None:
    """J14a.3: the owner without a key at the machine, as a Linux system
    install leaves them, pairs a passkey from Workbench through the root and
    approves with it there."""
    def signing(state: str) -> dict[str, Any]:
        return settle(lambda s: (s.get("signing") or {}).get("state") == state,
                      f"the site never reported its signing state as {state}")

    def listed(key: str | None) -> dict[str, Any]:
        answer = call(f"job-sites/{site_id}/held", ada, **({"key": key} if key else {}))
        assert answer.status_code == 200, answer.text
        return dict(answer.json())

    # The key at the machine goes: no page, no key, as a Linux system install.
    for entry in desk.linked:
        if entry["subject"] == subject:
            entry.pop("keys", None)
    desk.keys.pop(subject, None)
    desk.write_links()
    signing("unsigned")
    assert settle(lambda s: s["signing"].get("passkeys") is True, "passkeys")["signing"]
    # A change while unsigned is the root's word, so there are rules to approve.
    opened = call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=True)
    assert opened.status_code == 200, opened.text

    # The starter's code, as `install.sh --site-pair` shows it: the site
    # host's own `pair`, as the site host's account, waiting for the passkey.
    pairing = desk.pair()
    assert pairing.stdout is not None
    shown: list[str] = []
    code = None
    deadline = time.perf_counter() + 30
    while code is None and time.perf_counter() < deadline:
        line = pairing.stdout.readline()
        if not line:
            break
        shown.append(line)
        found = re.fullmatch(r"\s+([0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5})\s*", line)
        code = found.group(1) if found else None
    assert code is not None, "".join(shown)
    made = {"code": code}
    passkey = Passkey("workbench.example")
    honest = passkey.pairing(made["code"].lower(), site_id, subject)
    swapped = {**honest, "publicKey": base64.b64encode(Passkey("workbench.example").spki).decode()}
    refused = call(f"job-sites/{site_id}/passkeys", ada, **swapped)
    assert refused.status_code == 422 and "does not match" in refused.text, refused.text
    paired = call(f"job-sites/{site_id}/passkeys", ada, **honest)
    assert paired.status_code == 201 and paired.json()["id"] == passkey.id, paired.text
    rest, _ = pairing.communicate(timeout=30)
    assert pairing.returncode == 0 and f"({passkey.id[:8]})" in rest, "".join(shown) + rest
    signing("unconfirmed")
    # The code is single use: the same pairing again is refused.
    again = call(f"job-sites/{site_id}/passkeys", ada, **honest)
    assert again.status_code == 422 and "No code is waiting" in again.text, again.text
    assert made["code"] not in desk.all_text(), "the code was written to the site's directory"
    ok("J14a.3: with no key at the machine (a Linux system install's state) the site runs no "
       "tool; the code the site host's own `pair` shows (what --site-pair runs), typed into "
       "Workbench, pairs a passkey through the root, whose MAC the site checks, and `pair` says "
       "it arrived: a swapped public key is refused, and the code works once")

    held = listed(passkey.id)
    assert [p["id"] for p in held["passkeys"]] == [passkey.id]
    rules = next(i for i in held["items"] if i["id"] == "rules")
    approved = call(f"job-sites/{site_id}/held/rules/approve", ada, **passkey.approval(rules["envelope"]))
    assert approved.status_code == 200, approved.text
    signing("signed")
    off = call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=False)
    assert off.status_code == 200, off.text  # a reduction (J51)
    asked = call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=True)
    assert asked.status_code == 202 and asked.json()["held"] is True, asked.text
    held = listed(passkey.id)
    change = next(i for i in held["items"] if i["id"] != "rules")
    other = change["envelope"].replace('"ownerInDevMode":true', '"ownerInDevMode":false')
    forged = call(f"job-sites/{site_id}/held/{change['id']}/approve", ada, **passkey.approval(other))
    assert forged.status_code == 422 and "differs" in forged.text, forged.text
    done = call(f"job-sites/{site_id}/held/{change['id']}/approve", ada,
                **passkey.approval(change["envelope"]))
    assert done.status_code == 200, done.text
    settle(lambda s: s["ownerInDevMode"] is True, "the approved change never reported")
    assert call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=False).status_code == 200
    # Turned down from Workbench: dropped, never applied.
    assert call(f"job-sites/{site_id}/settings", ada, ownerInDevMode=True).status_code == 202
    waiting = next(i for i in listed(None)["items"] if i["id"] != "rules")
    rejected = call(f"job-sites/{site_id}/held/{waiting['id']}/reject", ada)
    assert rejected.status_code == 204, rejected.text
    assert settle(lambda s: True, "")["ownerInDevMode"] is False
    log = call(f"job-sites/{site_id}/audit", ada, limit=50).json()["entries"]
    reasons = " ".join(e.get("reason") or "" for e in log)
    assert "paired from Workbench" in reasons and "Approved from Workbench with passkey" in reasons
    assert "Turned down from Workbench." in reasons and honest["mac"] not in json.dumps(log)
    ok("J14a.3: the passkey's assertions, carried by the root, approve the site's rules and a "
       "held change; an assertion over another change is refused; a change turned down from "
       "Workbench is dropped; the audit log names each, never the MAC")

    # A lost phone (J60): removed from Workbench, through the root, with no
    # passkey and no visit to the machine. It was the owner's last key, so
    # the site runs no tool again, and the passkey approves nothing more.
    removed = call(f"job-sites/{site_id}/passkeys/{passkey.id}/remove", ada)
    assert removed.status_code == 204, removed.text
    signing("unsigned")
    gone = call(f"job-sites/{site_id}/passkeys/{passkey.id}/remove", ada)
    assert gone.status_code == 422 and "not paired" in gone.text, gone.text
    stale = call(f"job-sites/{site_id}/held", ada, key=passkey.id)
    assert stale.status_code == 422, stale.text
    log = call(f"job-sites/{site_id}/audit", ada, limit=5).json()["entries"]
    assert any(e.get("reason") == "Removed from Workbench." for e in log), log
    ok("J14a.3: a passkey removed from Workbench through the root (a lost phone) is gone from "
       "the site; with no key left it runs no tool, and the passkey lists and approves nothing")


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
    desk: SiteHost, work: Path, base: Path | None, call: Any, mcp: Any, settle: Any, site_id: str,
    ada: str, bo: str, owner_subject: str,
) -> None:
    """A fifth tool, added the way `eugene-plexus-agent site server add` adds
    one after its elevation check (the check itself is the agent's unit test
    and the real CLI is run in check 11), written to the YAML list the host AND
    its workers read (`SITE_HOST_LOCAL_SERVERS_FILE`; in sudo mode root's, in a
    root-owned directory, like the links), then the host and every worker are
    restarted to read it, as the agent restarts them. The tool then runs in the
    owner's worker."""
    import yaml
    from eugene_plexus_agent import site_cli
    from eugene_plexus_agent.site_host import servers_path

    config = work / "desk-config"
    config.mkdir()
    fixture = (base or work) / "local_server.py"
    put_file(fixture, (REPOS / "site-host" / "tests" / "fixtures" / "local_server.py").read_bytes(),
             root=base is not None)
    elevated, site_cli.elevated = site_cli.elevated, lambda: True
    try:
        site_cli.add_server(config, server_id="notes-tool", name="Notes tool",
                            command=str(desk.python), args=["-I", str(fixture)], env=[], system=False)
    finally:
        site_cli.elevated = elevated

    def restart_with_servers() -> None:
        put_file(desk.servers_file, servers_path(config).read_bytes(), root=desk.user is not None)
        desk.protected = [str(desk.site_dir), str(config)]
        for worker in desk.workers.values():
            worker.protect = desk.protected
        desk.restart_all()
        # No wait here, on purpose: the root's long poll for the host just
        # stopped may take the next call and answer a closed socket. The root
        # offers an operation nobody claimed again after five seconds
        # (control `sites.OFFER_SECONDS`), so the restarted host still gets it.

    restart_with_servers()
    listed = settle(lambda s: s["servers"], "the local server never reported")
    assert listed["servers"][0]["server"]["id"] == "notes-tool"
    assert not listed["servers"][0]["server"]["enabled"]
    on = call(f"job-sites/{site_id}/servers/notes-tool/enabled", ada, enabled=True)
    assert on.status_code == 202, on.text
    (enabled,) = desk.approve(owner_subject)
    assert {t["name"] for t in enabled["result"]["server"]["tools"]} == {"echo", "touch"}
    plain = call(f"job-sites/{site_id}/servers/notes-tool/access", ada,
                 people=[{"name": "bo", "tools": [{"name": "touch"}]}])
    assert plain.status_code == 422 and "standing" in plain.text, plain.text
    given = call(f"job-sites/{site_id}/servers/notes-tool/access", ada,
                 people=[{"name": "bo", "tools": [{"name": "echo"}]}])
    assert given.status_code == 202, given.text
    desk.approve(owner_subject)
    settle(lambda s: s["servers"][0]["people"], "the tool grant never reported")
    mine = call("sites/servers", bo)
    assert any(s["server"] == "notes-tool" and s["kind"] == "local" for s in mine.json()["servers"])
    tools = mcp(bo, "notes-tool", "tools/list")
    assert [t["name"] for t in tools.json()["response"]["result"]["tools"]] == ["echo"]
    echoed = mcp(bo, "notes-tool", "tools/call", {"name": "echo", "arguments": {"text": "hi"}})
    assert echoed.json()["status"] == "done" and "echo: hi" in json.dumps(echoed.json()), echoed.text
    # J9: a server marked system will not turn on without an administrator's consent.
    servers = yaml.safe_load(servers_path(config).read_text(encoding="utf-8"))
    servers["servers"].append({**servers["servers"][0], "id": "settings-tool",
                               "name": "Settings tool", "system": True})
    servers_path(config).write_text(yaml.safe_dump(servers), encoding="utf-8")
    restart_with_servers()
    settle(lambda s: len(s["servers"]) == 2, "the system server never reported")
    system = call(f"job-sites/{site_id}/servers/settings-tool/enabled", ada, enabled=True)
    assert system.status_code == 422 and "consent" in system.text.lower(), system.text
    ok("a fifth tool, from a local server added at the machine, works through the same route, "
       "with no change to control or Workbench; a server marked system will not turn on without "
       "an administrator's consent recorded at the machine (J9)")


def agent_site_join(python: Path, work: Path, nodes: str) -> None:
    """What needs an administrator: a system install's join, and any
    local-server change. A per-user install's own join needs none and is
    run for real by `per_user_site` (2b.2, §2.2; J14a.2)."""
    from eugene_plexus_agent import site_cli
    from eugene_plexus_agent.site_host import servers_path

    config = work / "agent-config"
    config.mkdir()
    environment = {**clean_environment(), "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(config / "agent.yaml")}
    refusals = []
    if not site_cli.elevated():
        refused = subprocess.run(
            agent_command("site", "server", "add", "notes", "--name", "Notes", "--command", str(python)),
            capture_output=True, text=True, env=environment, timeout=120, stdin=subprocess.DEVNULL,
        )
        assert refused.returncode == 2 and "administrator" in refused.stderr.lower(), (
            refused.returncode, refused.stderr,
        )
        assert not servers_path(config).exists()
        refusals.append("`site server add` refuses an unelevated caller and writes nothing")
        if os.name == "nt":
            # A system install's join needs an administrator: ProgramData is the system's place.
            program_data = work / "ProgramData"
            system = program_data / "EugenePlexus"
            system.mkdir(parents=True)
            refused = subprocess.run(
                agent_command("site", "join", "--url", nodes, "--token", "x", "--owner", "ada",
                              "--label", "sys", "--password-stdin"),
                input=PASSWORD + "\n", capture_output=True, text=True, timeout=120,
                env={**environment, "PROGRAMDATA": str(program_data),
                     "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(system / "agent.yaml")},
            )
            assert refused.returncode == 2 and "administrator" in refused.stderr.lower(), (
                refused.returncode, refused.stderr,
            )
            refusals.append("a system install's `site join` refuses an unelevated caller")
    else:
        print("SKIP: the agent's unelevated refusals (this account is elevated here); "
              "the agent's own tests carry them", flush=True)
    if refusals:
        ok("unelevated: " + "; ".join(refusals))


class PageClient:
    """The agent's own key page, used as its page script uses it (J14a.2):
    the cookie and CSRF token the page sets, a key made here (WebCrypto's
    part, played by `cryptography`; `j14a-browser-check.py` drives Chrome
    itself), the public half pinned at `/link/key`, and each held change
    signed exactly as the site host worded it."""

    def __init__(self, base: str) -> None:
        import httpx
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.http = httpx.Client(base_url=base, trust_env=False, timeout=30)
        self.key = Ed25519PrivateKey.generate()
        self.ident = ""

    @staticmethod
    def csrf(page: str) -> str:
        found = re.search(r"data-csrf='([^']+)'", page)
        assert found, page[:500]
        return found.group(1)

    def post(self, path: str, token: str, body: dict[str, Any]) -> Any:
        return self.http.post(path, content=json.dumps(body), headers={
            "Content-Type": "application/json", "X-Eugene-Csrf": token})

    def pin(self) -> str:
        from cryptography.hazmat.primitives import serialization

        page = self.http.get("/link")
        assert page.status_code == 200, page.text[:500]
        raw = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        pinned = self.post("/link/key", self.csrf(page.text),
                           {"alg": "Ed25519", "publicKey": base64.b64encode(raw).decode()})
        assert pinned.status_code == 200, pinned.text
        self.ident = str(pinned.json()["id"])
        assert self.ident == hashlib.sha256(raw).hexdigest()[:32]
        return str(page.text)

    def approve_all(self) -> list[dict[str, Any]]:
        page = self.http.get("/link/approve")
        assert page.status_code == 200, page.text[:500]
        token = self.csrf(page.text)
        listed = self.http.get(f"/link/approve/items?key={self.ident}")
        assert listed.status_code == 200, listed.text
        items = list(listed.json()["items"])
        for item in items:
            signature = base64.b64encode(self.key.sign(item["envelope"].encode())).decode()
            done = self.post(f"/link/approve/items/{item['id']}", token,
                             {"envelope": item["envelope"], "key": self.ident,
                              "signature": signature})
            assert done.status_code == 200 and done.json()["status"] == "done", done.text
        return items


def per_user_site(
    python: Path, work: Path, nodes: str, http: Any, control: str, people: dict[str, str],
    workbench: Workbench, ada: str, source: str, stranger: Account | None,
    stranger_command: str | None = None,
) -> None:
    """J14a.2, a real per-user install: the agent from this checkout, as this
    script's own account and unelevated, joined to the root as a node. It
    installs the site host itself (its own child); `site join` links the
    owner to this account and names the key page; a client in this account
    pairs a key through the agent's real `/link` page and approves held
    changes there, and only then does ada's call run. Another account's
    connection to the page is refused (sudo mode)."""
    import httpx

    config = work / "per-user"
    config.mkdir()
    port = free_port()
    # Started as a person starts one, from a terminal: not as a child of
    # whatever unit runs this script. CI's runner is a systemd system
    # service, and an agent that inherits its INVOCATION_ID reads its own
    # cgroup as a system install's and hosts no site of its own.
    inherited_unit = ("INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID")
    env = {
        **{k: v for k, v in clean_environment().items() if k not in inherited_unit},
        "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(config / "agent.yaml"),
        "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
        "EUGENE_PLEXUS_AGENT_BIND_PORT": str(port),
        "EUGENE_PLEXUS_AGENT_SITE_HOST_SOURCE": source,
        "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    join_token = http.post(f"{control}/v1/nodes/join-token", json={}).json()["token"]
    joined = subprocess.run(
        agent_command("join", "--control", control, "--token", join_token, "--name", "per-user"),
        env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
    )
    assert joined.returncode == 0, joined.stdout + joined.stderr
    log = open(config / "agent.out", "wb")  # noqa: SIM115 - closed in the finally
    agent = subprocess.Popen(
        agent_command("--unattended"), env=env, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.perf_counter() + 90
        while True:
            try:
                if httpx.get(f"{base}/healthz", trust_env=False, timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if agent.poll() is not None or time.perf_counter() > deadline:
                raise AssertionError("the per-user agent did not start:\n"
                                     + (config / "agent.out").read_text(errors="replace")[-3000:])
            time.sleep(0.5)
        minted = http.post(f"{control}/v1/sites/invitations",
                           json={"owner": people["ada"], "label": "per-user"})
        assert minted.status_code == 201, minted.text
        try:
            done = subprocess.run(
                agent_command("site", "join", "--url", nodes, "--token", minted.json()["token"],
                              "--owner", "ada", "--label", "per-user", "--root-key",
                              minted.json()["rootKey"], "--password-stdin", "--no-browser"),
                input=PASSWORD + "\n", capture_output=True, text=True, env=env, timeout=420,
            )
        except subprocess.TimeoutExpired:
            raise AssertionError(
                "the per-user agent never prepared its site host for `site join`:\n"
                + (config / "agent.out").read_text(errors="replace")[-3000:]
            ) from None
        assert done.returncode == 0, done.stdout + done.stderr
        assert f"open {base}/link in your browser" in done.stdout, done.stdout
        links = json.loads((config / "site" / "links.json").read_text(encoding="utf-8"))["links"]
        mine = account_of(python)
        assert [(e["subject"], e["account"]) for e in links] == [(people["ada"], mine)], links
        site_id = json.loads((config / "apps" / "site-host" / "data" / "site.json")
                             .read_text(encoding="utf-8"))["site"]
        approve_page = f"{base}/link/approve"

        def view(predicate: Any, what: str, seconds: float = 90) -> dict[str, Any]:
            deadline = time.perf_counter() + seconds
            while True:
                sites = [s for s in workbench.call("job-sites", ada).json()["sites"]
                         if s["id"] == site_id]
                if sites and predicate(sites[0]):
                    return dict(sites[0])
                if time.perf_counter() > deadline:
                    raise AssertionError(f"{what}: {sites}\n"
                                         + (config / "agent.out").read_text(errors="replace")[-3000:])
                time.sleep(0.5)

        view(lambda s: (s.get("signing") or {}) == {"state": "unsigned", "held": 0,
                                                     "approvePage": approve_page,
                                                     "passkeys": True}
             and s.get("linkPage") is None, "the site never named its approve page")
        view(lambda s: any(x["available"] for x in s.get("links") or []), "no worker connected")
        # Rules sent before the key are the root's word (J48): applied, and no tool runs.
        folder = work / "per-user-folder"
        folder.mkdir()
        (folder / "note.txt").write_text("a note at ada's own desk", encoding="utf-8")
        added = workbench.call(f"job-sites/{site_id}/folders", ada, name="Desk", path=str(folder),
                               writable=True)
        assert added.status_code == 201, added.text
        folder_id = added.json()["id"]
        granted = workbench.call(f"job-sites/{site_id}/folders/{folder_id}/people", ada,
                                 people=[{"name": "ada", "writable": False}])
        assert granted.status_code == 200, granted.text
        view(lambda s: s["folders"] and s["folders"][0]["people"], "the grant never reported")
        read_note = {"name": "read_text", "arguments": {"folder": "Desk", "path": "note.txt"}}
        refused = workbench.mcp(ada, site_id, "files", "tools/call", read_note)
        assert refused.status_code == 200, refused.text
        assert refused.json()["status"] == "failed", refused.text
        assert approve_page in refused.json()["message"], refused.text
        ok("J14a.2, a real per-user install: the agent, unelevated as this account, installs its "
           "own site host; `site join` links ada to this account and names the key page; the "
           "site has an approve page and no link page, and runs no tool until her key, saying "
           "where to add it")

        # ---- the key, made and pinned through the agent's own page ----------
        client = PageClient(base)
        page = client.pin()
        assert "<title>Your key</title>" in page and "/link/start" not in page
        pinned = json.loads((config / "site" / "links.json").read_text(encoding="utf-8"))["links"]
        assert [k["id"] for k in pinned[0]["keys"]] == [client.ident], pinned
        view(lambda s: s["signing"]["state"] == "unconfirmed", "the rules never awaited the key")
        (rules,) = client.approve_all()
        assert rules["id"] == "rules" and rules["action"] == "rules.confirm", rules
        view(lambda s: s["signing"]["state"] == "signed", "the site never reported itself signed")
        read = workbench.mcp(ada, site_id, "files", "tools/call", read_note)
        assert read.json()["status"] == "done", read.text
        assert "a note at ada's own desk" in json.dumps(read.json()["response"])
        # A change that gives access is held for her key, then applied.
        writable = workbench.call(f"job-sites/{site_id}/folders/{folder_id}/people", ada,
                                  people=[{"name": "ada", "writable": True}])
        assert writable.status_code == 202 and writable.json()["held"] is True, writable.text
        assert approve_page in writable.json()["message"], writable.text
        (change,) = client.approve_all()
        assert change["action"] == "folder.people", change
        view(lambda s: s["folders"][0]["people"][0]["writable"], "the write grant never reported")
        ok("J14a.2: through the agent's own page, in this account, a key is made and pinned, the "
           "rules sent before it are approved as a whole, and ada's call runs; a change from "
           "Workbench that gives access is held, approved there with that key, and applied")

        # ---- another account on this machine --------------------------------
        if stranger is None and not stranger_command:
            print("SKIP: another account's connection to the per-user page is refused (needs a "
                  "second account: sudo mode, or --stranger-command; the agent's own tests carry "
                  "the refusal)", flush=True)
        else:
            probe = ("import urllib.request,urllib.error\n"
                     f"try:\n    r=urllib.request.urlopen('{base}/link')\n    print(r.status)\n"
                     "except urllib.error.HTTPError as e:\n    print(e.code, e.read().decode())\n")
            if stranger is not None:
                argv = as_user(stranger, ["/usr/bin/python3", "-c", probe], {})
                who = stranger.name
            else:
                assert stranger_command is not None
                argv = [*shlex.split(stranger_command), "python3", "-c", probe]
                who = stranger_command
            seen = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                                  stdin=subprocess.DEVNULL)
            assert seen.stdout.startswith("403") and "serves no one else here" in seen.stdout, (
                seen.stdout, seen.stderr)
            ok(f"J14a.2: another account on this machine ({who}) is refused by the per-user "
               "page, read from its own connection")
    finally:
        subprocess.run(agent_command("site", "leave"), env=env, capture_output=True, text=True,
                       timeout=120, stdin=subprocess.DEVNULL)
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(agent.pid)], capture_output=True)
        else:
            import signal

            with contextlib.suppress(ProcessLookupError):
                os.killpg(agent.pid, signal.SIGTERM)
        try:
            agent.wait(timeout=30)
        except subprocess.TimeoutExpired:
            agent.kill()
        log.close()


def two_b_two(c: SimpleNamespace) -> None:
    """Slice 2b.2's checks, 13 to 18: whose account runs a call (§2.4, §3.2,
    J24, J27, J36). `c` carries what `run()` has built."""
    desk: SiteHost = c.desk
    sudo_mode: bool = c.sudo_mode
    folder: Path = c.folder
    people: dict[str, str] = c.people
    ada, bo, jo = c.ada, c.bo, c.jo

    def write(token: str, name: str, text: str) -> Any:
        return c.mcp(token, "files", "tools/call", {"name": "write_text", "arguments": {
            "folder": "Notes", "path": name, "text": text, "expectedSha256": ""}})

    def read_file(token: str, name: str) -> Any:
        return c.mcp(token, "files", "tools/call", {"name": "read_text", "arguments": {
            "folder": "Notes", "path": name}})

    def served(reply: Any) -> bool:
        return bool(reply.status_code == 200 and reply.json()["status"] == "done")

    # ---- 13. a call runs as the person -------------------------------------
    given = c.call(f"job-sites/{c.site_id}/folders/{c.folder_id}/people", ada, people=[
        {"name": "ada", "writable": True}, {"name": "bo", "writable": True},
        {"name": "jo", "writable": True}])
    assert given.status_code == 202, given.text
    desk.approve(people["ada"])
    c.settle(lambda s: bool(s["folders"]) and sum(p["writable"] for p in s["folders"][0]["people"]) == 3, "write grants")
    for token, name in ((ada, "ada.txt"), (jo, "jo.txt"), (bo, "bo.txt")):
        reply = write(token, name, f"written for {name}")
        assert served(reply), reply.text
        assert (folder / name).read_text(encoding="utf-8") == f"written for {name}"
    if sudo_mode:
        a, j = int(c.acc_a.uid), int(c.acc_j.uid)
        owners = {n: os.stat(folder / n).st_uid for n in ("ada.txt", "jo.txt", "bo.txt")}
        # bo has no link: his call runs in the OWNER's worker, as the owner (J27).
        assert owners == {"ada.txt": a, "jo.txt": j, "bo.txt": a}, (owners, a, j)
        secret = "only jo may read this"
        assert served(write(jo, "secret.txt", secret))
        sudo("chmod", "600", str(folder / "secret.txt"))
        mine = read_file(jo, "secret.txt")
        assert served(mine) and secret in json.dumps(mine.json()), mine.text
        theirs = read_file(ada, "secret.txt")
        assert secret not in json.dumps(theirs.json()), theirs.text
        failed = theirs.json()["status"] == "failed" or "isError" in json.dumps(theirs.json())
        assert failed, theirs.text
        decided = {(e["subject"], e.get("tool"), e["decision"])
                   for e in c.call(f"job-sites/{c.site_id}/audit", ada, limit=200).json()["entries"]}
        assert (people["ada"], "read_text", "allowed") in decided, decided
        ok("each call runs as its person's own OS account: ada's write is a file owned by "
           f"{c.acc_a.name}, jo's by {c.acc_j.name} (her own link), and bo's, who has no link, "
           f"by {c.acc_a.name} (the owner's worker, J27); a 0600 file jo owns is read by jo and "
           "refused to ada, whose call the site's policy allowed (the audit log says so): the "
           "operating system decided")
    else:
        if os.name != "nt":
            own = os.getuid()
            assert {os.stat(folder / n).st_uid for n in ("ada.txt", "jo.txt", "bo.txt")} == {own}
        ok("one account: ada's, jo's and bo's writes all run in the one worker, whose "
           "account is the link's (jo and bo have no link of their own, J27)")
        print("SKIP: each person's calls running as a DIFFERENT OS account, and the OS refusing "
              "ada a file jo owns, need a second account: passwordless sudo on Linux (CI's "
              "runner) provides them", flush=True)

    # ---- 14. a worker that is not the account it names is refused -----------------
    host_account = desk.account
    if sudo_mode:
        wrong = c.acc_j.uid
    elif os.name == "nt":
        wrong = "S-1-5-21-1111111111-2222222222-3333333333-1999"
    else:
        wrong = str(os.getuid() + 1)
    impostor = Worker(desk, "impostor", wrong, None, desk.protected)
    ran = subprocess.run(
        [str(desk.python), "-I", "-m", "eugene_plexus_site_host.worker", *impostor.arguments()],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, env=clean_environment(), timeout=60,
    )
    assert ran.returncode != 0 and "not the account it was started for" in ran.stderr, (
        ran.returncode, ran.stdout, ran.stderr,
    )
    assert "refused" not in ran.stderr  # it never got as far as the host
    assert served(read_file(ada, "note.txt"))  # and the real worker is undisturbed
    sentence = "a worker started for another account refuses to run, before it connects"
    if sudo_mode:
        raw = subprocess.run(
            as_user(c.acc_z, [str(desk.python), "-I", "-c", RAW_CONNECT, desk.channel, host_account], {}),
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=clean_environment(), timeout=60,
        )
        assert raw.returncode == 0, raw.stderr
        said = json.loads(raw.stdout.strip().splitlines()[-1])
        assert said.get("t") == "refused", said
        assert served(read_file(ada, "note.txt"))
        sentence += (f"; a stranger account ({c.acc_z.name}) connecting to the host's channel is "
                     "sent {\"t\": \"refused\"} (no link names it) and disconnected")
    else:
        print("SKIP: a raw connection to the channel from an account no link names needs a "
              "second account (this one is ada's), so only the sudo run makes it", flush=True)
        lone = Worker(desk, "lone", host_account, None, desk.protected)
        real = subprocess.run(
            [str(desk.python), "-I", "-m", "eugene_plexus_site_host.worker",
             *lone.arguments(host_account, host_account)],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=clean_environment(), timeout=60,
        )
        assert real.returncode != 0 and "site host's own account" in real.stderr, (
            real.returncode, real.stderr,
        )
        sentence += ("; the real worker, as the site host's own account and not told it shares "
                     "it, refuses (a service install's rule), and a per-user install's starter "
                     "says --shared-account (J38)")
    ok(sentence)

    # ---- 15. neither the root nor the site host can make a link ------------------------
    ada_id = people["ada"]
    for method, path in (
        ("POST", "/v1/sites/links"), ("PUT", "/v1/sites/links"),
        ("POST", f"/v1/sites/{c.site_id}/links"), ("PUT", f"/v1/sites/{c.site_id}/links/{ada_id}"),
        ("POST", "/v1/site/links"), ("PUT", f"/v1/site/links/{ada_id}"),
        ("PUT", f"/v1/sites/{c.site_id}/links"), ("POST", f"/oidc/job-sites/{c.site_id}/links"),
    ):
        reply = c.http.request(method, f"{c.control}{path}", json={"subject": ada_id, "account": "0"})
        assert reply.status_code in (404, 405), (method, path, reply.status_code, reply.text[:200])
    for method, path in (("POST", "/links"), ("PUT", "/links"), ("POST", "/v1/links"), ("POST", "/link"),
                         ("PUT", "/link/confirm")):
        reply = c.plain.request(method, f"http://127.0.0.1:{desk.port}{path}", json={"subject": ada_id})
        assert reply.status_code in (404, 405), (method, path, reply.status_code)
    from eugene_plexus_agent.routes.site_link import api as agent_links

    assert {(r.path, tuple(sorted(r.methods))) for r in agent_links.routes} == {
        ("/v1/site/links/{subject}", ("DELETE",))
    }, "the agent's /v1 link route must only ever remove"
    sentence = ("the root has no route that makes a link (POST/PUT on every plausible path is 404 "
                "or 405), nor does the site host's own app, and the agent's one /v1 link route is "
                "DELETE and removes (its tests: test_site_link_page.py "
                "test_the_root_removes_a_link, test_no_one_but_the_root_may_remove_a_link)")
    if sudo_mode:
        directory, links = os.stat(desk.site_dir), os.stat(desk.links_file)
        assert (directory.st_uid, directory.st_mode & 0o777) == (0, 0o755), directory
        assert (links.st_uid, links.st_mode & 0o777) == (0, 0o644), links
        before = desk.links_file.read_bytes()
        tried = subprocess.run(
            as_user(c.acc_s, [str(desk.python), "-I", "-c", TRY_TO_LINK, str(desk.links_file)], {}),
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=clean_environment(), timeout=60,
        )
        assert tried.returncode == 0, tried.stderr
        assert tried.stdout.strip() == "append: PermissionError|truncate: PermissionError|" \
            "create beside: PermissionError|rename: PermissionError|unlink: PermissionError", tried.stdout
        assert desk.links_file.read_bytes() == before and not (desk.site_dir / "links2.json").exists()
        sentence += (f"; the links file and its directory are root's (0644 in 0755), and the site "
                     f"host's own account ({c.acc_s.name}) cannot append to, truncate, replace, "
                     "rename or remove it, or create a file beside it")
    else:
        print("SKIP: the site host's account failing to write the links file needs the host to "
              "run as an account other than the one that owns the file (the sudo run)", flush=True)
    ok(sentence)

    # ---- 16. no worker, no tools ----------------------------------------------------
    stopped = desk.workers["jo" if sudo_mode else "ada"]
    if sudo_mode:
        expected = "Your worker on desk is not running"
    elif desk.account.startswith("S-"):  # Windows: a worker lives while its person is signed in (J25)
        expected = "desk's owner is not signed in there"
    else:
        expected = "The owner's worker on desk is not running"
    stopped.stop()
    deadline = time.perf_counter() + 40
    while True:
        refused = read_file(jo, "note.txt")
        body = refused.json()
        if body["status"] == "failed" and expected in body["message"]:
            break
        if time.perf_counter() > deadline:
            raise AssertionError(f"jo's call was never refused for a missing worker: {refused.text}")
        time.sleep(0.5)
    assert "Notes from ada" not in refused.text
    if sudo_mode:
        assert served(read_file(ada, "note.txt"))  # another person's worker is not jo's
    stopped.start()
    deadline = time.perf_counter() + 40
    while not served(read_file(jo, "note.txt")):
        if time.perf_counter() > deadline:
            raise AssertionError("jo's calls were never served after her worker came back")
        time.sleep(0.5)
    ok("with the worker that would run a call stopped, the call is refused and says why "
       f"({expected!r}), and nothing runs in anyone else's; started again, it is served")

    # ---- 17. the person check -----------------------------------------------------------
    good = desk.check_person("ada", PASSWORD)
    assert good.returncode == 0, good.stdout + good.stderr
    answer = json.loads(good.stdout.strip().splitlines()[-1])
    assert answer == {"subject": people["ada"], "name": "ada"}, answer
    bad = desk.check_person("ada", "not her password")
    assert bad.returncode != 0 and "That name or password is not right." in bad.stderr, (
        bad.returncode, bad.stdout, bad.stderr,
    )
    assert PASSWORD not in good.stdout + good.stderr + bad.stdout + bad.stderr
    ok("`check-person`, run at the machine with the password on standard input, prints ada's "
       "subject and name through the root; a wrong password exits non-zero with the root's "
       "sentence and nothing else")

    # ---- 18. the seventh public path --------------------------------------------------------
    assert desk.record()["url"] == c.nodes  # check 17 went through the nodes name, pinned
    bearer = {"Authorization": "Bearer " + site_token(desk)}
    unknown = c.unverified.post(f"{c.nodes}/v1/sites/links/check", headers=bearer,
                                json={"name": "nobody-here", "password": "x"})
    assert unknown.status_code == 401, unknown.text  # the root's answer, not the entry point's
    bare = c.unverified.post(f"{c.nodes}/v1/sites/links/check", json={"name": "ada", "password": PASSWORD})
    assert bare.status_code == 401, bare.text  # a site's token is what it takes
    ok("through the nodes name the person check reaches the root (check 17 did it for real, "
       "pinned to the root's key): the root's own 401 for an unknown person, and a refusal "
       "without a site's token; every other path stays refused (checks 1 and 7)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-root", type=Path)
    parser.add_argument("--root-wsl", action="store_true")
    parser.add_argument(
        "--stranger-command",
        help="a command prefix that runs a program as another account here, for the per-user "
        "page's refusal without sudo (in WSL: 'wsl.exe -d Ubuntu -u someone --')",
    )
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--no-sudo", action="store_true",
        help="do not create throwaway accounts even when passwordless sudo is available",
    )
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
