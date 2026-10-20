"""LT1, the check of record: nothing between two machines crosses in clear text.

`docs/design/tls-between-machines.md` ??5. Two machines on a real wire: a root
container (control, `agent-a` with the gateway grant, and a gateway, all
spawned by `agent-a` as an install spawns them) and a worker container
(`agent-b`, with an inference-driver it spawns over a stub OpenAI-compatible
engine), on a Docker bridge network of their own. `tcpdump` runs in the
worker's network namespace from the moment the worker exists, so the capture
holds every byte the two machines exchanged: enrolment, the address
announcement, trust pulls, the gateway's topology reads and the prompt.

**Why two containers and not one host with a relay** (??7.1 step 0): control
refuses a loopback advertise address for a remote node, and a worker that
advertises a LAN address binds `0.0.0.0`, so a relay cannot stand in front of
it. A bridge is a real wire, and it runs on GitHub's Linux runners.

**Nothing this harness does crosses the wire.** Every call it makes is a
`docker exec` into the container concerned, to that container's loopback.
So every byte in the capture is one machine talking to the other, and the
assertion "no canary, no `Bearer`, no `eyJ`" is about the install alone.

Checks, in order:

1.  The two machines are joined: the worker enrols with a join token and the
    root's gateway lists the worker's model.
2.  A prompt carrying a random canary goes through the root's gateway to the
    worker's driver and comes back: the stub echoes it, and the stub on the
    worker counts the request it served (the subject is observed, not
    assumed).
3.  The capture saw the two machines talk: payload bytes in both directions
    between the two addresses (an empty capture is not a pass).
4.  The canary is nowhere in the capture, in any packet or any flow's
    payload stream.
5.  No `Bearer` and no `eyJ` (the start of every JWT) anywhere in it either.

6.  Every connection between the two machines is TLS: each flow's first
    byte is a TLS record.

**It fails before LT1**, on checks 4 to 6: every connection between the two
machines is `http://`. Committed failing (??7.1 step 0).

**Sabotage, by `--labels`** (??5), run after check 2 on the same pair, so the
capture judged in checks 3 to 6 holds them too:

* `bad-signature`: an announcement for the worker carrying another key,
  signed by a key that is not the worker's, is refused (401) and the root
  keeps the worker's real key.
* `wrong-pin`: a man in the middle. An iptables rule in the root sends its
  connections to the worker's machine port to a third container, which
  terminates TLS with a key of its own. The prompt fails, the root reports
  the worker's link as refused, and the impostor received the handshake
  (the redirect happened) and not one byte of application data.
* `root-stopped`: control is frozen (SIGSTOP). A prompt still goes root
  gateway -> worker over TLS, on the pins the root's machine holds.
* `removed-machine`: the operator removes the worker. Its key leaves the
  root's machine table and its model leaves the gateway. Last, because it
  is final.
* `automatic`: before the worker joins, the install is set to `automatic`
  (an install upgraded from before LT1). Once the worker has a key on record
  and answers on its machine port, the root switches to required by itself
  (LT-C2). Changes the setup, so run it on its own.

Run on a Linux host with Docker (WSL2 with `docker.io` on Amish_Station, or a
GitHub Linux runner):

    python3 scripts/lt1-machine-tls-acceptance.py \\
        --sources ../.worktrees/lt1 --output /tmp/lt1-run \\
        [--labels bad-signature,wrong-pin,root-stopped,removed-machine | automatic]

`--sources` holds the component checkouts side by side (agent, control,
gateway, inference-driver, library). Their working trees are copied as git
sees them (tracked and untracked, ignored files left out), so uncommitted
edits are what runs. Writes `result.json`, `result.md`, `wire.pcap` and every
process log into `--output` (a new directory). Exits 1 when a check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPOS = ("control", "agent", "gateway", "inference-driver", "library")
MODEL = "lt1-stub"
STUB_PORT = 9000
DRIVER_PORT = 8090
CONTROL_PORT = 8083
AGENT_PORT = 8079
MACHINE_PORT = 8083
GATEWAY_PORT = 8080
VENV = "/opt/ep/venv"
PYTHON = f"{VENV}/bin/python"

DOCKERFILE = f"""\
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends tcpdump iptables procps \\
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv {VENV}
COPY src /src
RUN {VENV}/bin/pip install --quiet --no-cache-dir {" ".join(f"/src/{r}" for r in REPOS)}
"""


# --------------------------------------------------------------------------- #
# Inside a container: what the host asks for over `docker exec`
# --------------------------------------------------------------------------- #


def inside(command: str, argument: dict) -> object:
    """One step, run in a container; its answer is printed as JSON."""
    import httpx

    if command == "call":
        headers = {}
        if argument.get("token"):
            headers["Authorization"] = f"Bearer {argument['token']}"
        with httpx.Client(
            trust_env=False, timeout=float(argument.get("timeout", 30))
        ) as client:
            try:
                response = client.request(
                    argument["method"],
                    argument["url"],
                    headers=headers,
                    json=argument.get("json"),
                )
            except httpx.HTTPError as exc:
                return {"status": -1, "error": f"{type(exc).__name__}: {exc}"}
        try:
            body: object = response.json()
        except ValueError:
            body = response.text[:2000]
        return {"status": response.status_code, "body": body}

    if command == "write":
        path = Path(argument["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(argument["text"], encoding="utf-8")
        return {"written": str(path)}

    if command == "spawn":
        log = open(argument["log"], "ab")  # noqa: SIM115 - handed to the child
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS_")
        }
        env.update(argument.get("env") or {})
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            argument["argv"],
            cwd=argument.get("cwd") or "/",
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return {"pid": proc.pid}

    if command == "stub":
        stub_server(int(argument["port"]), Path(argument["stats"]))
        return {}

    if command == "mitm":
        impostor(int(argument["port"]), Path(argument["record"]))
        return {}

    if command == "forge":
        import base64

        import nacl.signing

        stranger = nacl.signing.SigningKey.generate()
        fields = {
            "machineUrl": argument["machineUrl"],
            "tlsPin": argument["tlsPin"],
            "url": argument["url"],
            "name": argument["name"],
            "sequence": 10**9,
        }
        message = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
        body = {k: v for k, v in fields.items() if k != "name"}
        body["signature"] = base64.b64encode(stranger.sign(message).signature).decode()
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.patch(argument["target"], json=body)
        return {"status": response.status_code, "body": response.text[:400]}

    raise SystemExit(f"unknown inside command {command!r}")


def impostor(port: int, record: Path) -> None:
    """A man in the middle: TLS with a key of its own on `port`. It counts the
    handshakes it completes and keeps every byte of application data it is
    sent, which must be none."""
    import asyncio
    import datetime
    import ssl
    import tempfile

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "eugene-plexus-machine")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30)).sign(key, hashes.SHA256())
    )  # fmt: skip
    pem = Path(tempfile.mkdtemp()) / "impostor.pem"
    pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        + cert.public_bytes(serialization.Encoding.PEM)
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(pem, pem)
    seen = {"handshakes": 0, "applicationBytes": 0}
    record.write_text(json.dumps(seen), encoding="utf-8")

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        seen["handshakes"] += 1
        record.write_text(json.dumps(seen), encoding="utf-8")
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(65536), 10)
                if not chunk:
                    break
                seen["applicationBytes"] += len(chunk)
                record.write_text(json.dumps(seen), encoding="utf-8")
        except (TimeoutError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    async def run() -> None:
        server = await asyncio.start_server(handle, "0.0.0.0", port, ssl=context)
        async with server:
            await server.serve_forever()

    asyncio.run(run())


def stub_server(port: int, stats_path: Path) -> None:
    """An OpenAI-compatible engine that echoes the last user message."""
    import uvicorn
    from fastapi import Body, FastAPI

    app = FastAPI()
    stats = {"served": 0}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models() -> dict:
        return {
            "object": "list",
            "data": [{"id": MODEL, "object": "model", "created": 0}],
        }

    @app.post("/v1/chat/completions")
    async def completions(body: dict = Body(...)) -> dict:  # noqa: B008 - FastAPI's idiom
        said = str((body.get("messages") or [{}])[-1].get("content") or "")
        stats["served"] += 1
        stats_path.write_text(json.dumps(stats), encoding="utf-8")
        return {
            "id": "chatcmpl-lt1",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"echo: {said}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
        }

    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


# --------------------------------------------------------------------------- #
# The host: docker, and reading the capture
# --------------------------------------------------------------------------- #


def docker(*args: str, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=capture, text=True, check=False, timeout=900
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker {' '.join(args[:3])}: {result.stderr or result.stdout}"
        )
    return (result.stdout or "").strip()


def _ls_files(root: Path) -> list[bytes]:
    """Tracked and untracked files, ignored ones left out. A Windows worktree
    seen from WSL names its git directory by a Windows path, which only
    Windows' git can follow, so that is the fallback."""
    argv = ["ls-files", "-co", "--exclude-standard", "-z"]
    result = subprocess.run(
        ["git", "-C", str(root), *argv], capture_output=True, check=False
    )
    if result.returncode != 0 and shutil.which("git.exe") and shutil.which("wslpath"):
        windows = subprocess.run(
            ["wslpath", "-w", str(root)], capture_output=True, text=True, check=True
        ).stdout.strip()
        result = subprocess.run(
            ["git.exe", "-C", windows, *argv], capture_output=True, check=False
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"git ls-files in {root}: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout.split(b"\0")


def copy_sources(sources: Path, into: Path) -> str:
    """Each repo's working tree as git sees it; returns a digest of it all."""
    digest = hashlib.sha256(DOCKERFILE.encode())
    for repo in REPOS:
        root = sources / repo
        listed = _ls_files(root)
        for raw in sorted(p for p in listed if p):
            rel = raw.decode()
            if rel.startswith("tests/") or "/tests/" in rel:
                continue
            source = root / rel
            if not source.is_file():
                continue
            target = into / repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            digest.update(f"{repo}/{rel}\0".encode())
            digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


def build_image(sources: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="ep-lt1-build-") as tmp:
        context = Path(tmp)
        tag = "ep-lt1:" + copy_sources(sources, context / "src")
        if docker("images", "-q", tag):
            return tag
        (context / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        print(f"building {tag}", flush=True)
        docker("build", "-q", "-t", tag, str(context))
        return tag


def pcap_flows(data: bytes) -> dict[tuple[str, int, str, int], bytearray]:
    """TCP payload per (src, sport, dst, dport), in capture order. libpcap, Ethernet."""
    flows: dict[tuple[str, int, str, int], bytearray] = {}
    if len(data) < 24:
        return flows
    magic = data[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    offset = 24
    while offset + 16 <= len(data):
        _, _, caplen, _ = struct.unpack(endian + "IIII", data[offset : offset + 16])
        frame = data[offset + 16 : offset + 16 + caplen]
        offset += 16 + caplen
        if linktype == 1:  # Ethernet
            if len(frame) < 14 or frame[12:14] != b"\x08\x00":
                continue
            packet = frame[14:]
        elif linktype == 113:  # Linux cooked (`-i any`)
            if len(frame) < 16 or frame[14:16] != b"\x08\x00":
                continue
            packet = frame[16:]
        else:
            continue
        if len(packet) < 20 or packet[9] != 6:
            continue
        ihl = (packet[0] & 0x0F) * 4
        total = struct.unpack("!H", packet[2:4])[0]
        src = ".".join(str(b) for b in packet[12:16])
        dst = ".".join(str(b) for b in packet[16:20])
        tcp = packet[ihl:total]
        if len(tcp) < 20:
            continue
        sport, dport = struct.unpack("!HH", tcp[:4])
        payload = tcp[(tcp[12] >> 4) * 4 :]
        if payload:
            flows.setdefault((src, sport, dst, dport), bytearray()).extend(payload)
    return flows


class Record:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, passed: bool | None, **observed: object) -> None:
        status = "pass" if passed else ("not checked" if passed is None else "FAIL")
        self.checks.append({"check": name, "status": status, "observed": observed})
        print(
            f"{status.upper():12} {name} {json.dumps(observed, default=str)}",
            flush=True,
        )

    @property
    def failed(self) -> bool:
        return any(c["status"] != "pass" for c in self.checks)

    def markdown(self) -> str:
        lines = [
            "# LT1 machine TLS acceptance",
            "",
            "| Check | Result | Observed |",
            "|---|---|---|",
        ]
        for row in self.checks:
            observed = json.dumps(row["observed"], default=str).replace("|", "/")
            lines.append(f"| {row['check']} | {row['status']} | `{observed}` |")
        return "\n".join(lines) + "\n"


class Pair:
    """The two containers, the network between them and the capture."""

    def __init__(self, image: str, output: Path) -> None:
        self.image = image
        self.output = output
        self.run_id = secrets.token_hex(3)
        self.network = f"ep-lt1-{self.run_id}"
        subnet_octet = 100 + secrets.randbelow(100)
        self.subnet = f"172.31.{subnet_octet}.0/24"
        self.ip = {
            "root": f"172.31.{subnet_octet}.2",
            "worker": f"172.31.{subnet_octet}.3",
            "mitm": f"172.31.{subnet_octet}.4",
        }
        self.containers: list[str] = []
        self.capture_dir = output / "capture"
        self.capture_dir.mkdir()
        os.chmod(self.capture_dir, 0o777)

    def name(self, role: str) -> str:
        return f"ep-lt1-{self.run_id}-{role}"

    def up(self, role: str) -> None:
        if not self.containers:
            docker("network", "create", "--subnet", self.subnet, self.network)
        name = self.name(role)
        docker(
            "run", "-d", "--name", name, "--hostname", f"lt1-{role}",
            "--network", self.network, "--ip", self.ip[role], "--cap-add", "NET_ADMIN",
            "--mount", f"type=bind,src={HERE.parent},dst=/instruments,readonly",
            self.image, "sleep", "infinity",
        )  # fmt: skip
        self.containers.append(name)

    def up_extra(self, role: str) -> None:
        """Another container on the bridge, not captured (the impostor)."""
        name = self.name(role)
        docker(
            "run", "-d", "--name", name, "--network", self.network, "--ip", self.ip[role],
            "--mount", f"type=bind,src={HERE.parent},dst=/instruments,readonly",
            self.image, "sleep", "infinity",
        )  # fmt: skip
        self.containers.append(name)

    def capture(self) -> None:
        name = self.name("capture")
        docker(
            "run", "-d", "--name", name, "--network", f"container:{self.name('worker')}",
            "--cap-add", "NET_RAW", "--cap-add", "NET_ADMIN",
            "--mount", f"type=bind,src={self.capture_dir},dst=/capture",
            self.image, "tcpdump", "-i", "eth0", "-s", "0", "-U", "-Z", "root",
            "-w", "/capture/wire.pcap", "tcp",
        )  # fmt: skip
        self.containers.insert(0, name)
        deadline = time.perf_counter() + 20
        while not (self.capture_dir / "wire.pcap").exists():
            if time.perf_counter() > deadline:
                raise RuntimeError(
                    "tcpdump did not start: " + docker("logs", name, check=False)
                )
            time.sleep(0.2)

    def stop_capture(self) -> bytes:
        name = self.name("capture")
        docker("kill", "--signal", "INT", name, check=False)
        docker("wait", name, check=False)
        return (self.capture_dir / "wire.pcap").read_bytes()

    def exec(
        self, role: str, command: str, argument: dict, *, detach: bool = False
    ) -> object:
        argv = ["exec"]
        if detach:
            argv.append("-d")
        argv += [self.name(role), PYTHON, "/instruments/" + HERE.name, "--inside", command,
                 "--argument", json.dumps(argument)]  # fmt: skip
        out = docker(*argv)
        if detach:
            return None
        return json.loads(out.splitlines()[-1]) if out else None

    def call(
        self, role: str, method: str, url: str, token: str | None = None, **kw
    ) -> dict:
        argument = {"method": method, "url": url, "token": token, **kw}
        return self.exec(role, "call", argument)  # type: ignore[return-value]

    def write(self, role: str, path: str, text: str) -> None:
        self.exec(role, "write", {"path": path, "text": text})

    def collect_logs(self) -> None:
        for role in ("root", "worker"):
            if self.name(role) in self.containers:
                # `docker cp <c>:/data <new dir>` makes <new dir> the copy of /data.
                docker(
                    "cp",
                    f"{self.name(role)}:/data",
                    str(self.output / role),
                    check=False,
                )

    def down(self) -> None:
        for name in self.containers:
            docker("rm", "-f", name, check=False)
        docker("network", "rm", self.network, check=False)


def wait_for(check, label: str, timeout: float = 90.0):
    deadline = time.perf_counter() + timeout
    last: object = None
    while time.perf_counter() < deadline:
        last = check()
        if last:
            return last
        time.sleep(1.0)
    raise AssertionError(
        f"timed out after {timeout:.0f} s waiting for {label} (last: {last!r})"
    )


def agent_yaml(advertise: str, components: list[dict]) -> str:
    import json as _json

    # YAML is a superset of JSON: no yaml module on the host side.
    return _json.dumps(
        {
            "firstRunComplete": True,
            "updateChecks": False,
            "advertiseUrl": advertise,
            "securityMode": "prompt_on_startup",
            "components": components,
        }
    )


def start_agent(pair: Pair, role: str, directory: str) -> None:
    pair.exec(
        role,
        "spawn",
        {
            "argv": [PYTHON, "-m", "eugene_plexus_agent", "--unattended"],
            "cwd": directory,
            "log": f"{directory}/agent.log",
            "env": {
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": f"{directory}/agent.yaml",
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "0.0.0.0",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(AGENT_PORT),
                "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "false",
            },
        },
    )


def exercise(pair: Pair, record: Record, labels: list[str]) -> bytes:
    passphrase = secrets.token_urlsafe(18)
    canary = "LT1CANARY" + secrets.token_hex(12)
    local = "http://127.0.0.1"
    root_ip, worker_ip = pair.ip["root"], pair.ip["worker"]

    # ---- the root: agent-a spawns control and the gateway ---------------------
    pair.up("root")
    root_dir = "/data/a"
    pair.write("root", f"{root_dir}/control.yaml", "{}\n")
    pair.write(
        "root", f"{root_dir}/gateway.yaml", json.dumps({"routingRefreshSeconds": 1})
    )
    pair.write(
        "root",
        f"{root_dir}/agent.yaml",
        agent_yaml(
            f"http://{root_ip}:{AGENT_PORT}",
            [
                {
                    "name": "control",
                    "kind": "control",
                    "url": f"{local}:{CONTROL_PORT}",
                    "spawn": {"configFile": f"{root_dir}/control.yaml"},
                },
                {
                    "name": "gateway",
                    "kind": "gateway",
                    "url": f"{local}:{GATEWAY_PORT}",
                    "spawn": {"configFile": f"{root_dir}/gateway.yaml"},
                },
            ],
        ),
    )
    start_agent(pair, "root", root_dir)
    wait_for(
        lambda: (
            pair.call("root", "GET", f"{local}:{AGENT_PORT}/healthz")["status"] == 200
        ),
        "agent-a",
    )
    wait_for(
        lambda: (
            pair.call("root", "GET", f"{local}:{CONTROL_PORT}/healthz")["status"] == 200
        ),
        "control",
    )
    answer = pair.call(
        "root",
        "POST",
        f"{local}:{CONTROL_PORT}/v1/auth/initialize",
        json={"passphrase": passphrase},
    )
    assert answer["status"] == 204, f"control initialize: {answer}"

    def login(role: str, url: str) -> str:
        def attempt():
            got = pair.call(
                role, "POST", url + "/v1/auth/login", json={"passphrase": passphrase}
            )
            return got if got["status"] == 200 else None

        return str(wait_for(attempt, f"sign-in at {url}", 30)["body"]["sessionToken"])

    root_session = login("root", f"{local}:{CONTROL_PORT}")
    if "automatic" in labels:
        got = pair.call(
            "root",
            "PATCH",
            f"{local}:{CONTROL_PORT}/v1/config",
            root_session,
            json={"machineEncryption": "automatic"},
        )
        assert got["status"] == 200, f"machineEncryption automatic: {got}"

    def join_token(grants: list[str]) -> str:
        got = pair.call(
            "root",
            "POST",
            f"{local}:{CONTROL_PORT}/v1/nodes/join-token",
            root_session,
            json={"grants": grants},
        )
        assert got["status"] in (200, 201), f"join token: {got}"
        return str(got["body"]["token"])

    def enroll(role: str, control_url: str, token: str, name: str) -> None:
        agent = f"{local}:{AGENT_PORT}"
        got = pair.call(
            role, "POST", agent + "/v1/auth/initialize", json={"passphrase": passphrase}
        )
        assert got["status"] == 200, f"{name} initialize: {got}"
        standalone = got["body"]["sessionToken"]
        got = pair.call(
            role,
            "POST",
            agent + "/v1/node/enroll",
            standalone,
            json={"controlUrl": control_url, "token": token, "name": name},
        )
        assert got["status"] == 200, f"{name} enroll: {got}"

    enroll("root", f"{local}:{CONTROL_PORT}", join_token(["gateway"]), "agent-a")
    worker_token = join_token([])

    # ---- the worker, captured from its first packet ---------------------------
    pair.up("worker")
    pair.capture()
    worker_dir = "/data/b"
    pair.exec(
        "worker",
        "spawn",
        {
            "argv": [PYTHON, "/instruments/" + HERE.name, "--inside", "stub", "--argument",
                     json.dumps({"port": STUB_PORT, "stats": f"{worker_dir}/stub.json"})],
            "log": "/tmp/stub.log",
        },
    )  # fmt: skip
    pair.write(
        "worker",
        f"{worker_dir}/inference-driver.yaml",
        json.dumps(
            {
                "provider": "openai_compat_custom",
                "baseUrl": f"{local}:{STUB_PORT}",
                "modelId": MODEL,
                "backendLocality": "local",
            }
        ),
    )
    pair.write(
        "worker",
        f"{worker_dir}/agent.yaml",
        agent_yaml(
            f"http://{worker_ip}:{AGENT_PORT}",
            [
                {
                    "name": "lt1-driver",
                    "kind": "inference-driver",
                    "url": f"{local}:{DRIVER_PORT}",
                    "spawn": {"configFile": f"{worker_dir}/inference-driver.yaml"},
                }
            ],
        ),
    )
    start_agent(pair, "worker", worker_dir)
    wait_for(
        lambda: (
            pair.call("worker", "GET", f"{local}:{AGENT_PORT}/healthz")["status"] == 200
        ),
        "agent-b",
    )
    enroll("worker", f"http://{root_ip}:{CONTROL_PORT}", worker_token, "agent-b")

    operator = login("root", f"{local}:{AGENT_PORT}")

    def listed() -> bool:
        got = pair.call("root", "GET", f"{local}:{GATEWAY_PORT}/v1/models", operator)
        ids = {m.get("id") for m in (got.get("body") or {}).get("data", [])}
        return MODEL in ids

    try:
        wait_for(listed, "the root's gateway to list the worker's model", 120)
        record.add(
            "the worker joined and the root's gateway lists its model",
            True,
            model=MODEL,
        )
    except AssertionError as exc:
        record.add(
            "the worker joined and the root's gateway lists its model",
            False,
            error=str(exc),
        )
        raise

    # ---- the prompt -----------------------------------------------------------
    got = pair.call(
        "root",
        "POST",
        f"{local}:{GATEWAY_PORT}/v1/chat/completions",
        operator,
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": f"repeat {canary}"}],
        },
        timeout=60,
    )
    content = ""
    if got["status"] == 200:
        content = got["body"]["choices"][0]["message"]["content"]
    stats = pair.call("worker", "GET", f"{local}:{STUB_PORT}/health")  # alive
    served = json.loads(
        docker("exec", pair.name("worker"), "cat", f"{worker_dir}/stub.json") or "{}"
    ).get("served", 0)
    record.add(
        "a prompt with the canary went root -> worker and came back",
        got["status"] == 200 and canary in content and served >= 1,
        status=got["status"],
        echoed=canary in content,
        servedOnWorker=served,
        stub=stats.get("status"),
        **(
            {}
            if got["status"] == 200
            else {"answer": got.get("body") or got.get("error")}
        ),
    )

    def chat(text: str) -> dict:
        return pair.call(
            "root",
            "POST",
            f"{local}:{GATEWAY_PORT}/v1/chat/completions",
            operator,
            json={"model": MODEL, "messages": [{"role": "user", "content": text}]},
            timeout=60,
        )

    def worker_record() -> dict:
        got = pair.call(
            "root", "GET", f"{local}:{CONTROL_PORT}/v1/nodes/agent-b", root_session
        )
        return got.get("body") or {}

    def root_table() -> dict:
        raw = docker("exec", pair.name("root"), "cat", f"{root_dir}/machine_pins.json")
        return json.loads(raw or "{}")

    worker_door = f"{worker_ip}:{MACHINE_PORT}"
    for label in labels:
        if label == "automatic":

            def switched() -> bool:
                node = pair.call(
                    "root", "GET", f"{local}:{AGENT_PORT}/v1/node", operator
                )
                return bool(
                    ((node.get("body") or {}).get("machine") or {}).get("required")
                )

            try:
                waited = wait_for(switched, "the install to switch to required", 150)
                record.add(
                    "automatic: the install switched to required by itself",
                    bool(waited),
                )
            except AssertionError as exc:
                record.add("automatic: the install switched to required by itself", False,
                           error=str(exc))  # fmt: skip

        elif label == "bad-signature":
            before = worker_record()
            got = pair.exec(
                "root",
                "forge",
                {
                    "target": f"{local}:{CONTROL_PORT}/v1/nodes/agent-b",
                    "name": "agent-b",
                    "url": f"http://{worker_ip}:{AGENT_PORT}",
                    "machineUrl": f"https://{pair.ip['mitm']}:{MACHINE_PORT}",
                    "tlsPin": "M" * 43,
                },
            )
            after = worker_record()
            record.add(
                "bad-signature: a key the worker did not sign is refused",
                got["status"] == 401 and after.get("tlsPins") == before.get("tlsPins")
                and bool(before.get("tlsPins")),
                status=got["status"],
                pinsBefore=before.get("tlsPins"),
                pinsAfter=after.get("tlsPins"),
            )  # fmt: skip

        elif label == "wrong-pin":
            mitm_record = "/tmp/impostor.json"
            pair.up_extra("mitm")
            pair.exec(
                "mitm",
                "spawn",
                {
                    "argv": [PYTHON, "/instruments/" + HERE.name, "--inside", "mitm", "--argument",
                             json.dumps({"port": 8443, "record": mitm_record})],
                    "log": "/tmp/mitm.log",
                },
            )  # fmt: skip
            rule = ["-t", "nat", "OUTPUT", "-p", "tcp", "-d", worker_ip, "--dport",
                    str(MACHINE_PORT), "-j", "DNAT", "--to-destination",
                    f"{pair.ip['mitm']}:8443"]  # fmt: skip
            time.sleep(2)
            docker("exec", pair.name("root"), "iptables", "-t", "nat", "-A", *rule[2:])
            try:
                # A NAT rule moves new connections only, and the gateway's
                # pooled session to the real worker never idles (it polls
                # every second). So the gateway starts again, with none.
                docker("exec", pair.name("root"), "pkill", "-f", "eugene_plexus_gateway",
                       check=False)  # fmt: skip
                time.sleep(1)
                wait_for(
                    lambda: (
                        pair.call("root", "GET", f"{local}:{GATEWAY_PORT}/healthz")[
                            "status"
                        ]
                        == 200
                    ),
                    "the gateway to start again",
                    60,
                )
                time.sleep(5)
                got = chat("this must not reach anyone")
                link: dict = {}

                def refused() -> bool:
                    nonlocal link
                    link = worker_record().get("machineTls") or {}
                    return link.get("state") == "refused"

                try:
                    wait_for(refused, "the root to report the worker's key refused", 60)
                except AssertionError:
                    pass
                seen = json.loads(
                    docker("exec", pair.name("mitm"), "cat", mitm_record) or "{}"
                )
                logged = "is not the one it registered" in docker(
                    "exec",
                    pair.name("root"),
                    "cat",
                    f"{root_dir}/agent.log",
                    check=False,
                )
                record.add(
                    "wrong-pin: an impostor's key is refused and is sent nothing",
                    got["status"] != 200
                    and seen.get("handshakes", 0) >= 1
                    and seen.get("applicationBytes", -1) == 0
                    and link.get("state") == "refused"
                    and logged,
                    chat=got["status"],
                    impostor=seen,
                    link=link,
                    refusalLogged=logged,
                )  # fmt: skip
            finally:
                docker(
                    "exec", pair.name("root"), "iptables", "-t", "nat", "-D", *rule[2:]
                )
            wait_for(
                lambda: chat("back again")["status"] == 200,
                "the route to come back",
                120,
            )

        elif label == "root-stopped":
            pids = docker(
                "exec", pair.name("root"), "pgrep", "-f", "eugene_plexus_control"
            )
            pids_list = pids.split()
            for pid in pids_list:
                docker("exec", pair.name("root"), "kill", "-STOP", pid)
            try:
                time.sleep(3)
                again = "LT1CANARY" + secrets.token_hex(12)
                got = chat(f"repeat {again}")
                ok = got["status"] == 200 and again in str(got.get("body"))
                record.add(
                    "root-stopped: with control frozen, a prompt still reaches the worker",
                    ok and bool(pids_list),
                    status=got["status"],
                    frozen=pids_list,
                )
            finally:
                for pid in pids_list:
                    docker("exec", pair.name("root"), "kill", "-CONT", pid)

        elif label == "removed-machine":
            got = pair.call(
                "root",
                "DELETE",
                f"{local}:{CONTROL_PORT}/v1/nodes/agent-b",
                root_session,
            )

            def gone() -> bool:
                table = root_table()
                return worker_door not in (table.get("machines") or {}) and not listed()

            try:
                wait_for(
                    gone, "the worker to leave the root's table and the gateway", 120
                )
                left = True
            except AssertionError:
                left = False
            after = chat("to a machine that was removed")
            record.add(
                "removed-machine: its key leaves the table and nothing routes to it",
                got["status"] == 202 and left and after["status"] != 200,
                removal=got["status"],
                table=sorted((root_table().get("machines") or {}).keys()),
                chat=after["status"],
            )
        else:
            raise SystemExit(f"unknown label {label!r}")

    # Let the background traffic run a little longer: trust pulls, the
    # announcement loop and the gateway's polls all belong in the capture.
    time.sleep(5)
    return canary.encode()


def judge(record: Record, wire: bytes, canary: bytes, pair: Pair) -> None:
    flows = pcap_flows(wire)
    root_ip, worker_ip = pair.ip["root"], pair.ip["worker"]
    to_worker = sum(
        len(v) for (s, _, d, _), v in flows.items() if s == root_ip and d == worker_ip
    )
    to_root = sum(
        len(v) for (s, _, d, _), v in flows.items() if s == worker_ip and d == root_ip
    )
    ports = sorted(
        {f"{d}:{dp}" for (s, _, d, dp) in flows if {s, d} == {root_ip, worker_ip}}
    )
    record.add(
        "the capture saw the two machines talk, both ways",
        to_worker > 0 and to_root > 0,
        bytesRootToWorker=to_worker,
        bytesWorkerToRoot=to_root,
        pcapBytes=len(wire),
        destinations=ports,
    )
    streams = b"\n".join(bytes(v) for v in flows.values())

    def where(needle: bytes) -> list[str]:
        return sorted(
            {
                f"{s}:{sp}->{d}:{dp}"
                for (s, sp, d, dp), v in flows.items()
                if needle in v
            }
        )

    plain = sorted(
        f"{s}:{sp}->{d}:{dp}"
        for (s, sp, d, dp), v in flows.items()
        if {s, d} == {root_ip, worker_ip} and v[:1] != b"\x16"
    )
    record.add(
        "every connection between the machines is TLS", not plain, plain=plain[:12]
    )
    found = canary in wire or canary in streams
    record.add("the canary is nowhere on the wire", not found, flows=where(canary))
    for needle in (b"Bearer", b"eyJ"):
        hit = needle in wire or needle in streams
        record.add(
            f"no {needle.decode()} on the wire", not hit, flows=where(needle)[:12]
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inside", help=argparse.SUPPRESS)
    parser.add_argument("--argument", default="{}", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sources", type=Path, help="directory holding the component checkouts"
    )
    parser.add_argument("--output", type=Path, help="a new directory for the results")
    parser.add_argument("--image", help="use this image instead of building one")
    parser.add_argument(
        "--keep", action="store_true", help="leave the containers running"
    )
    parser.add_argument(
        "--labels",
        default="",
        help="sabotage to run: bad-signature,wrong-pin,root-stopped,removed-machine | automatic",
    )
    args = parser.parse_args()

    if args.inside:
        print(
            json.dumps(inside(args.inside, json.loads(args.argument)), default=str),
            flush=True,
        )
        return
    if args.output is None or (args.sources is None and args.image is None):
        parser.error("--output and --sources (or --image) are required")
    args.output.mkdir(parents=True, exist_ok=False)
    image = args.image or build_image(args.sources.resolve())
    record = Record()
    pair = Pair(image, args.output.resolve())
    wire = b""
    try:
        try:
            canary = exercise(pair, record, [x for x in args.labels.split(",") if x])
        finally:
            if pair.name("capture") in pair.containers:
                wire = pair.stop_capture()
            pair.collect_logs()
        judge(record, wire, canary, pair)
    except Exception as exc:
        record.add("the run completed", False, error=f"{type(exc).__name__}: {exc}")
    finally:
        if not args.keep:
            pair.down()
        (args.output / "result.json").write_text(
            json.dumps({"image": image, "checks": record.checks}, indent=2),
            encoding="utf-8",
        )
        (args.output / "result.md").write_text(record.markdown(), encoding="utf-8")
        if wire:
            (args.output / "wire.pcap").write_bytes(wire)
    sys.exit(1 if record.failed else 0)


if __name__ == "__main__":
    main()
