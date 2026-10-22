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

**A machine key change** (row 3, `docs/design/rows/row-03.md` section 5), by
`--labels key-change,root-key-change`. Each changes keys, so run them on a
pair of their own:

* `key-change`: the worker changes its key while the root sends one prompt a
  second through its gateway to the worker, and opens a new pinned TLS
  connection to the worker's agent every second. None may fail. After the
  drop the worker presents the new key, the root's record, its signed list
  and its machine table hold one pin, and an impostor holding the worker's
  OLD key is refused and sent nothing. Then a second change with the root's
  control stopped (SIGSTOP) once both keys are recorded: the worker keeps
  presenting its key for 35 s; control is killed, comes back sealed, is
  unlocked, and the change finishes.
* `root-key-change`: the root changes its own key while the worker opens a
  new pinned TLS connection to the root's control and to its agent every
  second, and prompts run root -> worker. None may fail, and the worker's
  table ends with the root's new key alone. Then the worker is stopped
  (agent and driver), the root changes its key again from start to drop,
  and the worker is started: within 2 minutes it holds the root's new key
  and serves prompts again, with nobody doing anything (the orchestrator's
  required check, 2026-10-21).
* `key-schedule` (part 3b, R3-SCHEDULE): the worker says when its key changes
  by itself (a year after it was made, plus its spread). Its agent is
  stopped, its key's certificate is dated so the key falls due four minutes
  later (the same key, so the same pin), and it is started. With a prompt a
  second through the root's gateway and a new pinned connection a second to
  the worker running from before the change starts, the worker changes its
  key by itself (`reason: scheduled`): none may fail, it presents the new
  key, and it is due again a year on.

Run on a Linux host with Docker (WSL2 with `docker.io` on Amish_Station, or a
GitHub Linux runner):

    python3 scripts/lt1-machine-tls-acceptance.py \\
        --sources ../.worktrees/lt1 --output /tmp/lt1-run \\
        [--labels bad-signature,wrong-pin,root-stopped,removed-machine | automatic
         | key-change,root-key-change,key-schedule]

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
import re
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

    if command == "bench":
        import statistics
        import time as clock

        took: list[float] = []
        headers = {"Authorization": f"Bearer {argument['token']}"}
        body = {
            "model": argument["model"],
            "messages": [{"role": "user", "content": "hi"}],
        }
        with httpx.Client(trust_env=False, timeout=60) as client:
            for _ in range(int(argument["n"])):
                started = clock.perf_counter()
                response = client.post(argument["url"], headers=headers, json=body)
                took.append((clock.perf_counter() - started) * 1000)
                response.raise_for_status()
        took.sort()
        return {
            "n": len(took),
            "p50Ms": round(statistics.median(took), 2),
            "p95Ms": round(took[int(len(took) * 0.95) - 1], 2),
            "meanMs": round(statistics.fmean(took), 2),
        }

    if command == "mitm":
        pem = argument.get("pem")
        impostor(int(argument["port"]), Path(argument["record"]), Path(pem) if pem else None)
        return {}

    if command == "peer-pin":
        # The key a machine port presents to a new handshake, checked
        # against nothing: what is seen, not what is trusted.
        import base64
        import socket
        import ssl

        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection(
                (argument["host"], int(argument["port"])), timeout=10
            ) as raw, context.wrap_socket(raw) as tls:
                der = tls.getpeercert(True)
        except OSError as exc:
            return {"pin": None, "error": f"{type(exc).__name__}: {exc}"}
        spki = (
            x509.load_der_x509_certificate(der)
            .public_key()
            .public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        digest = hashlib.sha256(spki).digest()
        return {"pin": base64.urlsafe_b64encode(digest).rstrip(b"=").decode()}

    if command == "load":
        load(argument)
        return {}

    if command == "age-key":
        # Part 3b: this machine's key as one made `days` ago. The same key,
        # so the same pin; only its certificate's date moves, which is what
        # the agent reads a key's age from. Run with the agent stopped.
        import datetime

        import yaml
        from eugene_plexus_agent import node_identity

        path = Path(argument["path"])
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        made = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            days=float(argument["days"])
        )
        raw["tlsCertificate"] = node_identity.machine_certificate(
            raw["tlsPrivateKey"], made=made
        )
        path.write_text(
            yaml.safe_dump(raw, sort_keys=True, default_flow_style=False), encoding="utf-8"
        )
        os.chmod(path, 0o600)
        return {
            "pin": node_identity.machine_pin(raw["tlsCertificate"]),
            "madeAt": node_identity.machine_key_made_at(raw["tlsCertificate"]).isoformat(),
        }

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


def load(argument: dict) -> None:
    """Traffic until a stop file appears, one request a second, each result a
    line in `out`. `chat`: a prompt through a gateway (a pooled client, as
    the root's gateway's own clients are). `get`: each URL in turn with a NEW
    client every time, so every request is a new TLS handshake, through the
    agent's own `_http` and the machine table in `pins` (what a component on
    that machine dials with)."""
    import time as clock

    import httpx

    out, stop = Path(argument["out"]), Path(argument["stop"])
    if argument.get("pins"):
        os.environ["EUGENE_PLEXUS_MACHINE_PINS_FILE"] = argument["pins"]
    from eugene_plexus_agent import _http

    urls = list(argument.get("urls") or [])
    chat = httpx.Client(trust_env=False, timeout=30)
    n = 0
    while not stop.exists():
        started = clock.perf_counter()
        row: dict = {"t": round(clock.time(), 3)}
        try:
            if argument["kind"] == "chat":
                marker = f"load-{n}"
                response = chat.post(
                    argument["url"],
                    headers={"Authorization": f"Bearer {argument['token']}"},
                    json={
                        "model": argument["model"],
                        "messages": [{"role": "user", "content": marker}],
                    },
                )
                row["status"] = response.status_code
                row["ok"] = response.status_code == 200 and marker in response.text
            else:
                url = urls[n % len(urls)]
                row["url"] = url
                with _http.sync_client_for(url, timeout=10) as client:
                    response = client.get(url)
                row["status"] = response.status_code
                row["ok"] = response.status_code == 200
        except Exception as exc:  # recorded, never raised: the run judges it
            row["ok"] = False
            row["error"] = f"{type(exc).__name__}: {exc}"[:400]
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        n += 1
        clock.sleep(max(0.0, 1.0 - (clock.perf_counter() - started)))
    chat.close()


def impostor(port: int, record: Path, key_pem: Path | None = None) -> None:
    """A man in the middle: TLS with a key of its own on `port`, or with
    `key_pem` (a key and certificate, PEM: a machine's OLD key, row 3). It
    counts the handshakes it completes and keeps every byte of application
    data it is sent, which must be none."""
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
    if key_pem is not None:
        pem = key_pem
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
        self.measurements: dict = {}

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
        #: The script `exec` runs inside a container (LT2 reuses this class).
        self.script = HERE.name
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
        """Another container on the bridge, not captured (the impostor).
        Once: a second impostor check reuses it."""
        name = self.name(role)
        if name in self.containers:
            return
        docker(
            "run", "-d", "--name", name, "--network", self.network, "--ip", self.ip[role],
            "--mount", f"type=bind,src={HERE.parent},dst=/instruments,readonly",
            self.image, "sleep", "infinity",
        )  # fmt: skip
        self.containers.append(name)

    def capture(self, role: str = "worker") -> None:
        name = self.name("capture")
        docker(
            "run", "-d", "--name", name, "--network", f"container:{self.name(role)}",
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
        argv += [self.name(role), PYTHON, "/instruments/" + self.script, "--inside", command,
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


class Up:
    """What `bring_up` leaves running, for the checks that follow."""

    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


def bring_up(
    pair: Pair,
    record: Record,
    labels: list[str],
    passphrase: str,
    *,
    capture: bool = True,
) -> Up:
    """The root and the worker, joined, with the worker's model listed by the
    root's gateway. The capture starts with the worker (`Pair.capture`)."""
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
    if capture:
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
    return Up(
        local=local,
        root_dir=root_dir,
        worker_dir=worker_dir,
        root_session=root_session,
        operator=operator,
        login=login,
        listed=listed,
    )


def impostor_check(
    pair: Pair,
    record: Record,
    up: Up,
    *,
    chat,
    worker_record,
    check: str,
    key_pem: str | None = None,
) -> None:
    """A man in the middle of the root's connections to the worker's machine
    port: a third container, TLS with a key of its own (or `key_pem`, the
    worker's old key, row 3). The prompt fails, the root reports the
    worker's link refused, and the impostor got a handshake and not one byte
    of application data."""
    local, root_dir, worker_ip = up.local, up.root_dir, pair.ip["worker"]
    mitm_record = "/tmp/impostor.json"
    pair.up_extra("mitm")
    argument: dict = {"port": 8443, "record": mitm_record}
    if key_pem is not None:
        pair.write("mitm", "/tmp/old-key.pem", key_pem)
        argument["pem"] = "/tmp/old-key.pem"
    pair.exec(
        "mitm",
        "spawn",
        {
            "argv": [PYTHON, "/instruments/" + HERE.name, "--inside", "mitm", "--argument",
                     json.dumps(argument)],
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
                pair.call("root", "GET", f"{local}:{GATEWAY_PORT}/healthz")["status"]
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
        seen = json.loads(docker("exec", pair.name("mitm"), "cat", mitm_record) or "{}")
        logged = "is not the one it registered" in docker(
            "exec",
            pair.name("root"),
            "cat",
            f"{root_dir}/agent.log",
            check=False,
        )
        record.add(
            check,
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
        docker("exec", pair.name("root"), "iptables", "-t", "nat", "-D", *rule[2:])
        docker("exec", pair.name("mitm"), "pkill", "-f", "--inside mitm", check=False)
    wait_for(
        lambda: chat("back again")["status"] == 200,
        "the route to come back",
        120,
    )


class Loads:
    """Traffic in the containers (`--inside load`) for the length of a
    change, and what became of every request."""

    def __init__(self, pair: Pair) -> None:
        self.pair = pair
        self.running: list[tuple[str, str, str]] = []

    def start(self, role: str, name: str, argument: dict) -> None:
        out, stop = f"/tmp/load-{name}.jsonl", f"/tmp/load-{name}.stop"
        docker("exec", self.pair.name(role), "rm", "-f", out, stop, check=False)
        self.pair.exec(
            role,
            "spawn",
            {
                "argv": [PYTHON, "/instruments/" + HERE.name, "--inside", "load",
                         "--argument", json.dumps({**argument, "out": out, "stop": stop})],
                "log": f"/tmp/load-{name}.log",
            },
        )  # fmt: skip
        self.running.append((role, name, out))

    def stop(self) -> dict:
        for role, name, _ in self.running:
            self.pair.write(role, f"/tmp/load-{name}.stop", "stop")
        time.sleep(3)
        summary: dict = {}
        for role, name, out in self.running:
            raw = docker("exec", self.pair.name(role), "cat", out, check=False)
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            failed = [r for r in rows if not r.get("ok")]
            summary[name] = {"requests": len(rows), "failed": len(failed), "failures": failed[:5]}
        self.running = []
        return summary


def _loads_ok(summary: dict, least: int) -> bool:
    return all(v["failed"] == 0 and v["requests"] >= least for v in summary.values())


def _claims(jws: str) -> dict:
    """A signed list's payload, read for what it says (the agent checked
    the signature; this is the observer)."""
    import base64

    payload = jws.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def key_changes(
    pair: Pair, record: Record, up: Up, *, label: str, chat, worker_record
) -> None:
    """Row 3, section 5: `key-change` (the worker's key) and
    `root-key-change` (the root's), each with its own failure case."""
    local = up.local
    root_ip, worker_ip = pair.ip["root"], pair.ip["worker"]
    agent = f"{local}:{AGENT_PORT}"
    control = f"{local}:{CONTROL_PORT}"
    sessions = {"root": up.operator, "worker": up.login("worker", agent)}
    holder = {"control": up.root_session}

    def machine(role: str) -> dict:
        got = pair.call(role, "GET", f"{agent}/v1/node", sessions[role])
        return ((got.get("body") or {}).get("machine")) or {}

    def change_state(role: str) -> str | None:
        return (machine(role).get("keyChange") or {}).get("state")

    def presented(from_role: str, host: str) -> str | None:
        got = pair.exec(from_role, "peer-pin", {"host": host, "port": MACHINE_PORT})
        return got.get("pin")  # type: ignore[union-attr]

    def node_record(name: str) -> dict:
        got = pair.call("root", "GET", f"{control}/v1/nodes/{name}", holder["control"])
        return got.get("body") or {}

    def signed_list() -> dict:
        got = pair.call("root", "GET", f"{control}/v1/trust/machines")
        return _claims(str((got.get("body") or {}).get("jws") or "a.e30.b"))

    def table(role: str, directory: str) -> dict:
        raw = docker("exec", pair.name(role), "cat", f"{directory}/machine_pins.json", check=False)
        try:
            return json.loads(raw or "{}")
        except ValueError:
            return {}

    def start(role: str) -> dict:
        got = pair.call(role, "POST", f"{agent}/v1/node/machine-key", sessions[role])
        assert got["status"] == 202, f"{role}: the key change did not start: {got}"
        return got["body"]

    def finished(role: str, timeout: float = 330) -> str | None:
        try:
            wait_for(
                lambda: change_state(role) in ("done", "failed", "stopped"),
                f"{role}'s key change to finish",
                timeout,
            )
        except AssertionError:
            pass
        return change_state(role)

    worker_door = f"{worker_ip}:{MACHINE_PORT}"
    root_door = f"{root_ip}:{MACHINE_PORT}"
    chat_load = {
        "kind": "chat",
        "url": f"{local}:{GATEWAY_PORT}/v1/chat/completions",
        "token": up.operator,
        "model": MODEL,
    }

    if label == "key-change":
        old = machine("worker").get("pin")
        old_pem = docker("exec", pair.name("worker"), "cat", f"{up.worker_dir}/machine_tls.pem")
        loads = Loads(pair)
        loads.start("root", "chat", chat_load)
        loads.start(
            "root",
            "to-worker",
            {
                "kind": "get",
                "urls": [f"http://{worker_ip}:{AGENT_PORT}/healthz"],
                "pins": f"{up.root_dir}/machine_pins.json",
            },
        )
        began = time.perf_counter()
        start("worker")
        state = finished("worker")
        took = round(time.perf_counter() - began)
        time.sleep(3)  # and the seconds just after the drop
        summary = loads.stop()
        new = machine("worker").get("pin")
        record.add(
            "key-change: under load, no prompt and no new connection failed",
            state == "done" and _loads_ok(summary, 10) and bool(new) and new != old,
            state=state,
            seconds=took,
            loads=summary,
        )

        def one_pin() -> bool:
            listed = {n.get("name"): n for n in signed_list().get("nodes") or []}
            return (
                (table("root", up.root_dir).get("machines") or {}).get(worker_door) == [new]
                and node_record("agent-b").get("tlsPins") == [new]
                and (listed.get("agent-b") or {}).get("pins") == [new]
            )

        try:
            wait_for(one_pin, "every list to hold the worker's new key alone", 90)
            lists = True
        except AssertionError:
            lists = False
        seen = presented("root", worker_ip)
        record.add(
            "key-change: after the drop the worker presents the new key, and the lists hold "
            "one pin",
            lists and seen == new,
            presented=seen,
            new=new,
            old=old,
            record=node_record("agent-b").get("tlsPins"),
            table=(table("root", up.root_dir).get("machines") or {}).get(worker_door),
        )
        impostor_check(
            pair,
            record,
            up,
            chat=chat,
            worker_record=worker_record,
            check="key-change: an impostor holding the worker's old key is refused and sent "
            "nothing",
            key_pem=old_pem,
        )

        # Root death between the announcement of both keys and the switch.
        current = machine("worker").get("pin")
        upcoming = start("worker").get("nextPin")
        wait_for(
            lambda: len(node_record("agent-b").get("tlsPins") or []) == 2,
            "the root to record both of the worker's keys",
            60,
        )
        pids = docker("exec", pair.name("root"), "pgrep", "-f", "eugene_plexus_control").split()
        for pid in pids:
            docker("exec", pair.name("root"), "kill", "-STOP", pid)
        time.sleep(35)
        during = change_state("worker")
        kept = presented("root", worker_ip)
        for pid in pids:
            docker("exec", pair.name("root"), "kill", "-KILL", pid)
        try:
            wait_for(
                lambda: pair.call("root", "GET", f"{control}/healthz")["status"] == 200,
                "control to start again",
                120,
            )
            holder["control"] = up.login("root", control)  # unlocks it
        except AssertionError as exc:
            record.add("key-change: control came back after it was killed", False, error=str(exc))
            return
        state = finished("worker")
        after = presented("root", worker_ip)
        record.add(
            "key-change: with control down the worker kept its key, and the change finished "
            "after a restart",
            bool(pids) and during == "waiting" and kept == current and state == "done"
            and after == upcoming,
            stopped=pids,
            stateWhileDown=during,
            presentedWhileDown=kept,
            current=current,
            state=state,
            presentedAfter=after,
            upcoming=upcoming,
        )  # fmt: skip
        return

    if label == "key-schedule":
        import datetime

        before = machine("worker")
        old = before.get("pin")
        made = before.get("keyMadeAt")
        due = before.get("keyChangeDueAt")
        year = (
            datetime.datetime.fromisoformat(due) - datetime.datetime.fromisoformat(made)
            if made and due
            else None
        )
        # A year, plus this key's spread: up to a twelfth of it (Troy's call).
        record.add(
            "key-schedule: the worker says its key changes by itself a year after it was made",
            year is not None
            and datetime.timedelta(days=365) <= year < datetime.timedelta(days=365 + 365 / 12),
            keyMadeAt=made,
            keyChangeDueAt=due,
        )
        if year is None:
            return
        # The yearly case: the machine is running when its key falls due, so it
        # starts at the next check. Its key is dated to fall due a few minutes
        # from now (a key already overdue when first seen would catch up
        # within a week, which the agent's own tests cover).
        lead = 240.0
        age_days = (year - datetime.timedelta(seconds=lead)) / datetime.timedelta(days=1)
        docker("exec", pair.name("worker"), "pkill", "-f", "eugene_plexus_", check=False)
        wait_for(
            lambda: pair.call("worker", "GET", f"{agent}/healthz", timeout=3)["status"] != 200,
            "the worker's agent to stop",
            60,
        )
        time.sleep(3)
        aged = pair.exec(
            "worker", "age-key", {"path": f"{up.worker_dir}/node.yaml", "days": age_days}
        )
        start_agent(pair, "worker", up.worker_dir)
        wait_for(
            lambda: chat("before the scheduled change")["status"] == 200,
            "the worker to serve prompts again",
            120,
        )
        # Traffic for the whole change: a prompt a second through the root's
        # gateway, and a new pinned connection a second to the worker's agent.
        loads = Loads(pair)
        loads.start("root", "chat", chat_load)
        loads.start(
            "root",
            "to-worker",
            {
                "kind": "get",
                "urls": [f"http://{worker_ip}:{AGENT_PORT}/healthz"],
                "pins": f"{up.root_dir}/machine_pins.json",
            },
        )
        loads_from = datetime.datetime.now(datetime.UTC)

        def scheduled_finished() -> bool:
            # This change, not the one an earlier label left `done`: started by
            # the schedule, after the restart, and over.
            kc = machine("worker").get("keyChange") or {}
            started_at = kc.get("startedAt")
            return (
                kc.get("reason") == "scheduled"
                and bool(started_at)
                and datetime.datetime.fromisoformat(started_at) > loads_from
                and kc.get("state") in ("done", "failed", "stopped")
            )

        try:
            wait_for(scheduled_finished, "the worker's scheduled key change to finish", lead + 360)
        except AssertionError:
            pass
        state = change_state("worker")
        time.sleep(3)  # and the seconds just after the drop
        summary = loads.stop()
        after = machine("worker")
        change = after.get("keyChange") or {}
        started = change.get("startedAt")
        new = after.get("pin")
        seen = presented("root", worker_ip)
        due_after = after.get("keyChangeDueAt")
        ahead = (
            datetime.datetime.fromisoformat(due_after) - datetime.datetime.now(datetime.UTC)
            if due_after
            else None
        )
        covered = bool(started) and datetime.datetime.fromisoformat(started) > loads_from
        record.add(
            "key-schedule: a key that falls due changes by itself, under load, with nothing "
            "refused",
            aged.get("pin") == old  # type: ignore[union-attr]
            and state == "done"
            and change.get("reason") == "scheduled"
            and covered
            and _loads_ok(summary, 10)
            and bool(new) and new != old and seen == new
            and ahead is not None and ahead > datetime.timedelta(days=364),
            agedPin=aged.get("pin"),  # type: ignore[union-attr]
            agedMadeAt=aged.get("madeAt"),  # type: ignore[union-attr]
            state=state,
            reason=change.get("reason"),
            startedAt=started,
            loadsFrom=loads_from.isoformat(),
            loads=summary,
            old=old,
            new=new,
            presented=seen,
            keyChangeDueAt=due_after,
        )  # fmt: skip
        return

    # ---- root-key-change ----------------------------------------------------
    old = machine("root").get("pin")
    loads = Loads(pair)
    loads.start("root", "chat", chat_load)
    loads.start(
        "worker",
        "to-root",
        {
            "kind": "get",
            "urls": [
                f"http://{root_ip}:{CONTROL_PORT}/v1/trust/machines",
                f"http://{root_ip}:{AGENT_PORT}/healthz",
            ],
            "pins": f"{up.worker_dir}/machine_pins.json",
        },
    )
    began = time.perf_counter()
    start("root")
    state = finished("root")
    took = round(time.perf_counter() - began)
    time.sleep(3)
    summary = loads.stop()
    new = machine("root").get("pin")

    def worker_has(pin: str | None) -> bool:
        return (table("worker", up.worker_dir).get("machines") or {}).get(root_door) == [pin]

    try:
        wait_for(lambda: worker_has(new), "the worker's table to hold the root's new key alone", 90)
        held = True
    except AssertionError:
        held = False
    seen = presented("worker", root_ip)
    record.add(
        "root-key-change: the worker's calls to the root kept working, and its controlPins end "
        "as the new key",
        state == "done" and _loads_ok(summary, 10) and held and seen == new and new != old
        and signed_list().get("controlPins") == [new],
        state=state,
        seconds=took,
        loads=summary,
        presented=seen,
        controlPins=signed_list().get("controlPins"),
    )  # fmt: skip

    # A worker off for the whole change: stopped before it starts, started
    # after the old key left, and nobody does anything.
    docker("exec", pair.name("worker"), "pkill", "-f", "eugene_plexus_", check=False)
    wait_for(
        lambda: pair.call("worker", "GET", f"{agent}/healthz", timeout=3)["status"] != 200,
        "the worker's agent to stop",
        60,
    )
    time.sleep(3)
    start("root")
    state = finished("root")
    newer = machine("root").get("pin")
    start_agent(pair, "worker", up.worker_dir)
    back = time.perf_counter()
    try:
        wait_for(lambda: worker_has(newer), "the worker to take the root's new key", 120)
        wait_for(
            lambda: chat("after the worker came back")["status"] == 200,
            "a prompt to reach the worker again",
            max(1.0, 120 - (time.perf_counter() - back)),
        )
        recovered = True
    except AssertionError:
        recovered = False
    took = round(time.perf_counter() - back)
    logged = "checking the root's signed machine list" in docker(
        "exec", pair.name("worker"), "cat", f"{up.worker_dir}/agent.log", check=False
    )
    record.add(
        "root-key-change: a worker off for the whole change takes the root's new key by "
        "itself within 2 minutes",
        state == "done" and recovered and took <= 120 and newer != new and logged,
        state=state,
        seconds=took,
        newer=newer,
        worker=(table("worker", up.worker_dir).get("machines") or {}).get(root_door),
        tookTheListWithoutTheOldKey=logged,
    )


def exercise(pair: Pair, record: Record, labels: list[str], measure: int = 0) -> bytes:
    passphrase = secrets.token_urlsafe(18)
    canary = "LT1CANARY" + secrets.token_hex(12)
    up = bring_up(pair, record, labels, passphrase)
    local, root_dir, worker_dir = up.local, up.root_dir, up.worker_dir
    root_session, operator, listed = up.root_session, up.operator, up.listed
    worker_ip = pair.ip["worker"]

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

    if measure:
        # §3.8: the path's own cost, timed in the root container so no docker
        # exec is in it. Recorded, never judged: run it on main and on this
        # branch and compare.
        timing = pair.exec(
            "root",
            "bench",
            {
                "url": f"{local}:{GATEWAY_PORT}/v1/chat/completions",
                "token": operator,
                "model": MODEL,
                "n": measure,
            },
        )
        record.measurements = {"chatRootToWorker": timing}
        print(f"MEASURED     {json.dumps(timing)}", flush=True)

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
            impostor_check(
                pair,
                record,
                up,
                chat=chat,
                worker_record=worker_record,
                check="wrong-pin: an impostor's key is refused and is sent nothing",
            )

        elif label in ("key-change", "root-key-change", "key-schedule"):
            # One label's failure is recorded and the next still runs.
            try:
                key_changes(
                    pair, record, up, label=label, chat=chat, worker_record=worker_record
                )
            except Exception as exc:
                record.add(
                    f"{label}: the run completed", False, error=f"{type(exc).__name__}: {exc}"
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
    hit = b"Bearer" in wire or b"Bearer" in streams
    record.add("no Bearer on the wire", not hit, flows=where(b"Bearer")[:12])
    # A token, not the three bytes "eyJ": those turn up by chance in megabytes of
    # TLS ciphertext (about one run in seven once the key-change load ran). A JWT
    # in clear text is header.payload. with both parts base64url.
    jwt = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")
    hit = bool(jwt.search(wire) or jwt.search(streams))
    tokens = sorted(
        f"{s}:{sp}->{d}:{dp}" for (s, sp, d, dp), v in flows.items() if jwt.search(v)
    )
    record.add("no eyJ on the wire", not hit, flows=tokens[:12])


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
    parser.add_argument(
        "--measure",
        type=int,
        default=0,
        help="time this many chats root -> worker (§3.8)",
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
            canary = exercise(
                pair, record, [x for x in args.labels.split(",") if x], args.measure
            )
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
            json.dumps(
                {
                    "image": image,
                    "checks": record.checks,
                    "measurements": record.measurements,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (args.output / "result.md").write_text(record.markdown(), encoding="utf-8")
        if wire:
            (args.output / "wire.pcap").write_bytes(wire)
    sys.exit(1 if record.failed else 0)


if __name__ == "__main__":
    main()
