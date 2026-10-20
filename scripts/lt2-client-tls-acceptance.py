"""LT2, the check of record: clients and browsers reach the install over TLS.

`docs/design/tls-for-clients.md` §10. The Docker pair of LT1 (a root with
control, `agent-a` and a gateway; a worker with an inference-driver over a stub
engine), plus a **client** container on the same bridge. `tcpdump` runs in the
client's network namespace from the moment it exists, so the capture holds
every byte the client exchanged with the install.

The client trusts the install CA the way a person's device does: in its own
system store (`update-ca-certificates`, read by curl through OpenSSL) and in
Chromium's NSS store. No request in this check passes a flag that turns
verification off.

**Nothing this harness does crosses the wire but the client's own traffic.**
The CA is read in the root container over its loopback, and set-up calls are
`docker exec`s to each container's loopback, as in LT1.

Checks, in order:

1.  The pair is up and joined (LT1's `bring_up`).
2.  The root serves the install CA (`GET /v1/trust/ca`, at the console and at
    control, the same certificate), and it is a CA constrained to private
    addresses and local names (§3, LT2-C2), the constraint marked critical.
3.  The root's console and the worker's console answer the client over
    `https://` on their own ports, with leaves the client verifies.
4.  A prompt with a random canary goes from the client to the root's gateway
    on 8080 over `https://`, through to the worker, and comes back.
5.  Chromium, with the CA in its NSS store, opens the console over
    `https://` and signs in with the passphrase.
6.  A second browser, not captured, opens the console over `http://`; the
    page moves itself to `https://` (the probe, §6).
7.  The root's console counts the client's plain connections by door (§6).
8.  The capture: the client talked to the install; every connection to a
    door of the install is TLS but the deliberately plain probes (sent from
    local ports 41000-41099); no canary, passphrase, `Bearer` or `eyJ` in it.

**It fails before LT2**, at check 2: no node serves a CA and no door answers
TLS. Committed failing (§9, the build order in the handoff).

**Sabotage, by `--labels`** (§10), each after check 7 on the same pair:

* `foreign-address`: the worker asks for a leaf naming an address it does not
  hold. Control refuses it; the same request for its own names, sent the
  same way, is accepted (the instrument works).
* `other-key`: a CSR for a key the worker did not register is refused.
* `plain-off`: the owner turns plain HTTP off. A plain request from the
  client to the gateway and to the console is refused with the `https://`
  URL named; over `https://` both still answer, and plain from the root's own
  loopback still answers. Plain is turned back on.
* `forged-public-name`: the CA's key, taken from the root (the passphrase
  opens it, as a thief with the root's disk and passphrase would), signs a
  leaf for a public name. curl and Chromium refuse it on the name
  constraint, while a leaf for a private address signed the same way is
  accepted (the forgery itself works; only the constraint stops it).

Run on a Linux host with Docker (WSL2 on Amish_Station, or a GitHub Linux
runner), after `npm run build:python` in the ui checkout:

    python3 scripts/lt2-client-tls-acceptance.py \\
        --sources ../.worktrees/lt1 --output /tmp/lt2-run \\
        [--labels foreign-address,other-key,plain-off,forged-public-name]

Writes `result.json`, `result.md`, `wire.pcap` and the process logs into
`--output` (a new directory). Exits 1 when a check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve()
_SPEC = importlib.util.spec_from_file_location(
    "lt1", HERE.parent / "lt1-machine-tls-acceptance.py"
)
assert _SPEC is not None and _SPEC.loader is not None
lt1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lt1)

REPOS = (*lt1.REPOS, "ui")
UI_STATIC = "python/eugene_plexus_ui/static"
AGENT_PORT = lt1.AGENT_PORT
GATEWAY_PORT = lt1.GATEWAY_PORT
MACHINE_PORT = lt1.MACHINE_PORT
PYTHON = lt1.PYTHON
PLAIN_PORTS = (41000, 41099)
#: §3: what the CA may sign for.
PERMITTED_IP = {
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "fc00::/7",
    "fe80::/10",
    "::1/128",
}
PERMITTED_DNS = {"local", "home.arpa", "internal", "lan", "localhost"}
PUBLIC_NAME = "bank.example.com"

DOCKERFILE = f"""\
FROM python:3.12-slim-bookworm
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \\
        tcpdump iptables procps curl ca-certificates libnss3-tools \\
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv {lt1.VENV} \\
    && {lt1.VENV}/bin/pip install --quiet --no-cache-dir playwright==1.48.0 \\
    && {lt1.VENV}/bin/playwright install --with-deps chromium \\
    && rm -rf /var/lib/apt/lists/*
COPY src /src
RUN {lt1.VENV}/bin/pip install --quiet --no-cache-dir {" ".join(f"/src/{r}" for r in REPOS)}
"""


# --------------------------------------------------------------------------- #
# Inside a container
# --------------------------------------------------------------------------- #


def inside(command: str, argument: dict) -> object:
    """One step, run in a container; its answer is printed as JSON."""
    import subprocess

    if command == "run":
        done = subprocess.run(
            argument["argv"], capture_output=True, text=True, check=False, timeout=180
        )
        return {
            "rc": done.returncode,
            "out": done.stdout[-4000:],
            "err": done.stderr[-2000:],
        }

    if command == "https":
        import httpx

        headers = {}
        if argument.get("token"):
            headers["Authorization"] = f"Bearer {argument['token']}"
        # Only ever to this container's own loopback (the machine port), so
        # nothing about the install's trust is being tested by this call.
        with httpx.Client(trust_env=False, verify=False, timeout=30) as client:
            response = client.request(
                argument["method"],
                argument["url"],
                headers=headers,
                json=argument.get("json"),
            )
        try:
            body: object = response.json()
        except ValueError:
            body = response.text[:2000]
        return {"status": response.status_code, "body": body}

    if command == "inspect-ca":
        return _inspect_ca(argument["pem"])

    if command == "trust-ca":
        return _trust_ca(argument["pem"])

    if command == "browser":
        return _browser(argument)

    if command == "csr":
        return _csr(argument)

    if command == "steal-ca":
        return _steal_ca(argument)

    if command == "tls-server":
        _tls_server(int(argument["port"]), argument["pem"])
        return {}

    return lt1.inside(command, argument)


def _inspect_ca(pem: str) -> dict:
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(pem.encode())
    basic = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    try:
        constraints = cert.extensions.get_extension_for_class(x509.NameConstraints)
    except x509.ExtensionNotFound:
        return {
            "subject": cert.subject.rfc4514_string(),
            "ca": basic.value.ca,
            "constraints": None,
        }
    permitted = constraints.value.permitted_subtrees or []
    return {
        "subject": cert.subject.rfc4514_string(),
        "ca": basic.value.ca,
        "critical": constraints.critical,
        "ip": sorted(str(n.value) for n in permitted if isinstance(n, x509.IPAddress)),
        "dns": sorted(str(n.value) for n in permitted if isinstance(n, x509.DNSName)),
        "other": [
            str(n)
            for n in permitted
            if not isinstance(n, x509.IPAddress | x509.DNSName)
        ],
        "excluded": [str(n) for n in constraints.value.excluded_subtrees or []],
        "notAfter": cert.not_valid_after_utc.isoformat(),
    }


def _trust_ca(pem: str) -> dict:
    """The device's step: the CA into the system store and Chromium's NSS store."""
    import subprocess

    Path("/usr/local/share/ca-certificates/eugene-plexus.crt").write_text(
        pem, encoding="utf-8"
    )
    system = subprocess.run(["update-ca-certificates"], capture_output=True, text=True)
    nss = Path("/root/.pki/nssdb")
    nss.mkdir(parents=True, exist_ok=True)
    ca = Path("/tmp/eugene-plexus-ca.pem")
    ca.write_text(pem, encoding="utf-8")
    if not (nss / "cert9.db").exists():
        subprocess.run(
            ["certutil", "-d", f"sql:{nss}", "-N", "--empty-password"],
            check=True,
            text=True,
        )
    added = subprocess.run(
        [
            "certutil",
            "-d",
            f"sql:{nss}",
            "-A",
            "-t",
            "C,,",
            "-n",
            "eugene-plexus",
            "-i",
            str(ca),
        ],
        capture_output=True,
        text=True,
    )
    return {
        "system": system.returncode,
        "nss": added.returncode,
        "nssErr": added.stderr[-400:],
    }


def _browser(argument: dict) -> dict:
    """Chromium, with whatever the NSS store trusts and no flag that skips it."""
    from playwright.sync_api import Error, sync_playwright

    out: dict = {}
    args = []
    if argument.get("resolve"):
        args.append("--host-resolver-rules=" + argument["resolve"])
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        try:
            page = browser.new_context().new_page()
            failures: list[str] = []
            page.on(
                "requestfailed",
                lambda r: failures.append(f"{r.url} {r.failure}"),
            )
            out["failed"] = failures
            try:
                response = page.goto(argument["url"], wait_until="load", timeout=30000)
                out["status"] = response.status if response else None
                out["url"] = page.url
            except Error as exc:
                out["error"] = str(exc).splitlines()[0][:300]
                return out
            if argument.get("passphrase"):
                # The console may move itself (sign-in, the probe) as it
                # loads; the sign-in is sent once it has settled.
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Error:
                    pass
                out["settledAt"] = page.url
                out["login"] = page.evaluate(
                    """async (passphrase) => {
                        const r = await fetch('/v1/auth/login', {method: 'POST',
                            headers: {'content-type': 'application/json'},
                            body: JSON.stringify({passphrase})});
                        return r.status;
                    }""",
                    argument["passphrase"],
                )
            if argument.get("wait_for_https"):
                try:
                    page.wait_for_url("https://**", timeout=30000)
                    out["moved"] = page.url
                except Error as exc:
                    out["moved"] = None
                    out["stayed"] = page.url
                    out["waitError"] = str(exc).splitlines()[0][:200]
        except Error as exc:
            out["error"] = str(exc).splitlines()[0][:300]
        finally:
            browser.close()
    return out


def _agent_token(directory: Path) -> tuple[str, str]:
    """This node's own service token for control, minted the way its agent does."""
    from eugene_plexus_agent import tokens
    from eugene_plexus_agent.node_identity import NodeIdentityStore

    store = NodeIdentityStore(directory / "node.yaml")
    store.load()
    record = store.record
    signer = tokens.Signer(
        key=tokens.load_private(record.token_private_key),
        issuer=tokens.node_recipient(record.name),
    )
    token, _ = signer.mint(
        typ=tokens.TYP_SERVICE,
        sub=tokens.SUB_AGENT,
        aud=[tokens.RECIPIENT_CONTROL],
        ttl_seconds=600,
    )
    return token, str(record.tls_private_key)


def _csr(argument: dict) -> dict:
    """A CSR from the worker for `names`, with its own machine key or a new one."""
    import ipaddress

    import httpx
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    token, own_key = _agent_token(Path(argument["dir"]))
    if argument.get("other_key"):
        key = ec.generate_private_key(ec.SECP256R1())
    else:
        key = serialization.load_pem_private_key(own_key.encode(), password=None)
    sans: list[x509.GeneralName] = []
    for name in argument["names"]:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            sans.append(x509.DNSName(name))
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, argument["node"])])
        )
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())  # type: ignore[arg-type]
    )
    pem = csr.public_bytes(serialization.Encoding.PEM).decode()
    with httpx.Client(trust_env=False, verify=False, timeout=30) as client:
        response = client.post(
            argument["url"],
            json={"csr": pem},
            headers={"Authorization": f"Bearer {token}"},
        )
    try:
        body: object = response.json()
    except ValueError:
        body = response.text[:400]
    issued = isinstance(body, dict) and bool(body.get("certificate"))
    detail = body.get("detail") if isinstance(body, dict) else body
    return {"status": response.status_code, "issued": issued, "detail": detail}


def _steal_ca(argument: dict) -> dict:
    """What a thief holding the root's disk and its passphrase can do: open the
    sealed CA key, then sign leaves with it. Returns two leaf+key PEMs."""
    import base64
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from eugene_plexus_control import security
    from eugene_plexus_control.log_store import LogStore
    from eugene_plexus_control.state_machine import StateMachine

    candidates = [Path(p) for p in argument.get("state_dirs", [])]
    candidates += sorted(Path(argument["root"]).rglob("control-state")) + [
        Path("/control-state")
    ]
    found = next((p for p in candidates if p.is_dir() and any(p.iterdir())), None)
    if found is None:
        return {"error": f"no control state under {argument['root']}"}
    machine = StateMachine(LogStore(found))
    machine.load()
    identity = machine.state.identity
    sealed = getattr(identity, "sealedInstallCaKey", None)
    ca_pem = getattr(identity, "installCaCertificate", None)
    if not sealed or not ca_pem:
        return {"error": "control holds no install CA"}
    master = security.derive_master_key(
        argument["passphrase"], base64.b64decode(identity.salt)
    )
    ca_key = serialization.load_der_private_key(
        security.open_b64(sealed, master), password=None
    )
    ca = x509.load_pem_x509_certificate(ca_pem.encode())
    now = datetime.datetime.now(datetime.UTC)

    def leaf(names: list[str]) -> str:
        key = ec.generate_private_key(ec.SECP256R1())
        sans: list[x509.GeneralName] = []
        for name in names:
            try:
                sans.append(x509.IPAddress(ipaddress.ip_address(name)))
            except ValueError:
                sans.append(x509.DNSName(name))
        cert = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
            )
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None), critical=True
            )
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]
        )
        return (
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
            + cert.public_bytes(serialization.Encoding.PEM).decode()
        )

    return {
        "public": leaf([PUBLIC_NAME]),
        "private": leaf(["forged.local", argument["private_ip"]]),
        "state": str(found),
    }


def _tls_server(port: int, pem: str) -> None:
    """Answers `200 forged` over TLS with the given leaf and key."""
    import asyncio
    import ssl

    path = Path(tempfile.mkdtemp()) / "leaf.pem"
    path.write_text(pem, encoding="utf-8")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(path, path)

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            writer.write(
                b"HTTP/1.1 200 OK\r\ncontent-length: 6\r\nconnection: close\r\n\r\nforged"
            )
            await writer.drain()
        except (
            TimeoutError,
            ConnectionError,
            asyncio.IncompleteReadError,
            ssl.SSLError,
        ):
            pass
        finally:
            writer.close()

    async def run() -> None:
        server = await asyncio.start_server(handle, "0.0.0.0", port, ssl=context)
        async with server:
            await server.serve_forever()

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# The host
# --------------------------------------------------------------------------- #


def copy_sources(sources: Path, into: Path) -> str:
    """As LT1's, plus the UI's built static files, which git ignores."""
    digest = hashlib.sha256(DOCKERFILE.encode())
    for repo in REPOS:
        root = sources / repo
        for raw in sorted(p for p in lt1._ls_files(root) if p):
            rel = raw.decode()
            if rel.startswith(("tests/", "e2e/")) or "/tests/" in rel:
                continue
            source = root / rel
            if not source.is_file():
                continue
            target = into / repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            digest.update(f"{repo}/{rel}\0".encode())
            digest.update(source.read_bytes())
    static = sources / "ui" / UI_STATIC
    if not (static / "index.html").is_file():
        raise SystemExit(
            f"the UI is not built: run `npm run build:python` in {sources / 'ui'} first"
        )
    for source in sorted(p for p in static.rglob("*") if p.is_file()):
        rel = source.relative_to(sources / "ui").as_posix()
        target = into / "ui" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest.update(f"ui/{rel}\0".encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


def build_image(sources: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="ep-lt2-build-") as tmp:
        context = Path(tmp)
        tag = "ep-lt2:" + copy_sources(sources, context / "src")
        if lt1.docker("images", "-q", tag):
            return tag
        (context / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        print(f"building {tag}", flush=True)
        lt1.docker("build", "-q", "-t", tag, str(context))
        return tag


class Run:
    """The pair, the client, and the values the checks share."""

    def __init__(self, pair: lt1.Pair, record: lt1.Record) -> None:
        self.pair, self.record = pair, record
        self.passphrase = secrets.token_urlsafe(18)
        self.canary = "LT2CANARY" + secrets.token_hex(12)
        prefix = pair.ip["root"].rsplit(".", 1)[0]
        pair.ip["client"] = f"{prefix}.5"
        pair.ip["visitor"] = f"{prefix}.6"
        pair.script = HERE.name
        self.root_ip, self.worker_ip = pair.ip["root"], pair.ip["worker"]
        self.ca = ""
        self.plain_sent = 0

    # ---- helpers -------------------------------------------------------------

    def run(self, role: str, argv: list[str]) -> dict:
        return self.pair.exec(role, "run", {"argv": argv})  # type: ignore[return-value]

    def curl(self, url: str, *extra: str, plain_probe: bool = False) -> dict:
        """curl from the client, with the system store and no `-k`."""
        argv = [
            "curl",
            "-sS",
            "--max-time",
            "60",
            "-o",
            "/tmp/body",
            "-w",
            "%{http_code}",
        ]
        if plain_probe:
            argv += ["--local-port", f"{PLAIN_PORTS[0]}-{PLAIN_PORTS[1]}"]
            self.plain_sent += 1
        got = self.run("client", [*argv, *extra, url])
        body = self.run("client", ["cat", "/tmp/body"])["out"]
        return {
            "rc": got["rc"],
            "status": got["out"].strip(),
            "err": got["err"].strip(),
            "body": body,
        }

    def node(self, role: str, token: str) -> dict:
        got = self.pair.call(
            role, "GET", f"http://127.0.0.1:{AGENT_PORT}/v1/node", token
        )
        return got.get("body") if isinstance(got.get("body"), dict) else {}

    # ---- the checks ----------------------------------------------------------

    def exercise(self, labels: list[str]) -> None:
        pair, record = self.pair, self.record
        up = lt1.bring_up(pair, record, [], self.passphrase, capture=False)
        self.up = up

        # The client, captured from its first packet.
        pair.up_extra("client")
        pair.capture("client")

        # 2. The CA, read on the root's own loopback, once the root's agent
        # holds a leaf from it (it asks as soon as it has joined).
        console_ca = ""

        def served() -> bool:
            nonlocal console_ca
            console_ca = self.run(
                "root", ["curl", "-sS", f"http://127.0.0.1:{AGENT_PORT}/v1/trust/ca"]
            )["out"]
            return "BEGIN CERTIFICATE" in console_ca

        try:
            lt1.wait_for(served, "the root's console to serve the install CA", 90)
        except AssertionError:
            pass
        control_ca = self.run(
            "root", ["curl", "-sS", f"http://127.0.0.1:{MACHINE_PORT}/v1/trust/ca"]
        )["out"]
        seen: dict = {}
        if "BEGIN CERTIFICATE" in console_ca:
            seen = pair.exec("root", "inspect-ca", {"pem": console_ca})  # type: ignore[assignment]
        constrained = (
            seen.get("ca") is True
            and seen.get("critical") is True
            and set(seen.get("ip") or []) == PERMITTED_IP
            and set(seen.get("dns") or []) == PERMITTED_DNS
            and not seen.get("other")
        )
        record.add(
            "the root serves the install CA, constrained to private addresses and local names",
            bool(seen) and constrained and console_ca.strip() == control_ca.strip(),
            console=console_ca[:120],
            sameAtControl=console_ca.strip() == control_ca.strip(),
            ca=seen,
        )
        if not seen:
            raise AssertionError(
                "no install CA: nothing past this point can be checked"
            )
        self.ca = console_ca
        trusted = pair.exec("client", "trust-ca", {"pem": console_ca})
        assert trusted["system"] == 0 and trusted["nss"] == 0, (
            f"trusting the CA: {trusted}"
        )  # type: ignore[index]

        # 3. Each console over TLS, with the leaf its node was issued.
        for role, ip in (("root", self.root_ip), ("worker", self.worker_ip)):
            last: dict = {}

            def answers(ip: str = ip) -> bool:
                nonlocal last
                last = self.curl(f"https://{ip}:{AGENT_PORT}/healthz")
                return last["status"] == "200"

            try:
                lt1.wait_for(answers, f"the {role}'s console over https", 150)
            except AssertionError:
                pass
            record.add(
                f"the {role}'s console answers the client over https on {AGENT_PORT}",
                last.get("status") == "200",
                **last,
            )

        # 4. The canary, client -> root gateway (https) -> worker.
        body = json.dumps(
            {
                "model": lt1.MODEL,
                "messages": [{"role": "user", "content": f"repeat {self.canary}"}],
            }
        )
        self.run("client", ["sh", "-c", f"cat > /tmp/chat.json <<'EOF'\n{body}\nEOF"])
        got = self.curl(
            f"https://{self.root_ip}:{GATEWAY_PORT}/v1/chat/completions",
            "-H", f"Authorization: Bearer {up.operator}",
            "-H", "content-type: application/json",
            "--data-binary", "@/tmp/chat.json",
        )  # fmt: skip
        record.add(
            "a prompt with the canary went client -> root gateway over https and came back",
            got["status"] == "200" and self.canary in got["body"],
            status=got["status"],
            echoed=self.canary in got["body"],
            err=got["err"][:300],
        )

        # 5. Chromium signs in to the console over https.
        browsed = pair.exec(
            "client",
            "browser",
            {
                "url": f"https://{self.root_ip}:{AGENT_PORT}/",
                "passphrase": self.passphrase,
            },
        )
        record.add(
            "Chromium opens the console over https and signs in",
            browsed.get("status") == 200 and browsed.get("login") == 200,  # type: ignore[union-attr]
            **browsed,  # type: ignore[arg-type]
        )

        # 6. A page opened over http moves itself to https (not captured).
        pair.up_extra("visitor")
        pair.exec("visitor", "trust-ca", {"pem": console_ca})
        moved = pair.exec(
            "visitor",
            "browser",
            {"url": f"http://{self.root_ip}:{AGENT_PORT}/", "wait_for_https": True},
        )
        record.add(
            "a console page opened over http moves itself to https",
            str(moved.get("moved") or "").startswith(
                f"https://{self.root_ip}:{AGENT_PORT}/"
            ),  # type: ignore[union-attr]
            **moved,  # type: ignore[arg-type]
        )

        # 7. The doors count plain connections by client address.
        probe = self.curl(
            f"http://{self.root_ip}:{GATEWAY_PORT}/healthz", plain_probe=True
        )
        counted: dict = {}

        def counts() -> bool:
            nonlocal counted
            doors = (self.node("root", up.operator).get("clientTls") or {}).get(
                "doors"
            ) or []
            counted = {
                str(d.get("port")): {
                    c.get("address"): c.get("count")
                    for c in d.get("plainClients") or []
                }
                for d in doors
            }
            return bool((counted.get(str(GATEWAY_PORT)) or {}).get(pair.ip["client"]))

        try:
            lt1.wait_for(
                counts, "the gateway door to count the client's plain connection", 30
            )
        except AssertionError:
            pass
        record.add(
            "the root counts plain connections per door and client",
            bool((counted.get(str(GATEWAY_PORT)) or {}).get(pair.ip["client"])),
            probe=probe["status"],
            doors=counted,
        )

        for label in labels:
            getattr(self, "label_" + label.replace("-", "_"))()
        time.sleep(3)

    # ---- sabotage ------------------------------------------------------------

    def _csr(self, names: list[str], *, other_key: bool = False) -> dict:
        return self.pair.exec(  # type: ignore[return-value]
            "worker",
            "csr",
            {
                "dir": self.up.worker_dir,
                "node": "agent-b",
                "names": names,
                "other_key": other_key,
                "url": f"https://{self.root_ip}:{MACHINE_PORT}/control/v1/nodes/agent-b/certificate",
            },
        )

    def label_foreign_address(self) -> None:
        own = self._csr([self.worker_ip, "agent-b.local"])
        foreign = self._csr([self.worker_ip, self.pair.ip["mitm"]])
        self.record.add(
            "foreign-address: a leaf for an address the worker does not hold is refused",
            own["status"] == 200
            and own["issued"]
            and foreign["status"] in (400, 403)
            and not foreign["issued"],
            own=own,
            foreign=foreign,
        )

    def label_other_key(self) -> None:
        own = self._csr([self.worker_ip])
        other = self._csr([self.worker_ip], other_key=True)
        self.record.add(
            "other-key: a CSR for a key the worker did not register is refused",
            own["status"] == 200
            and other["status"] in (400, 403)
            and not other["issued"],
            own=own,
            other=other,
        )

    def _plain_setting(self, value: str) -> dict:
        return self.pair.exec(  # type: ignore[return-value]
            "root",
            "https",
            {
                "method": "PATCH",
                "url": f"https://127.0.0.1:{MACHINE_PORT}/control/v1/config",
                "token": self.up.root_session,
                "json": {"clientPlainHttp": value},
            },
        )

    def label_plain_off(self) -> None:
        up = self.up
        set_off = self._plain_setting("off")
        state: dict = {}

        def taken() -> bool:
            nonlocal state
            state = self.node("root", up.operator).get("clientTls") or {}
            return state.get("plainAllowed") is False

        try:
            lt1.wait_for(taken, "the root's doors to take plain off", 120)
        except AssertionError:
            pass
        gateway = self.curl(
            f"http://{self.root_ip}:{GATEWAY_PORT}/v1/models", plain_probe=True
        )
        console = self.curl(f"http://{self.root_ip}:{AGENT_PORT}/", plain_probe=True)
        tls_gateway = self.curl(
            f"https://{self.root_ip}:{GATEWAY_PORT}/v1/models",
            "-H", f"Authorization: Bearer {up.operator}",
        )  # fmt: skip
        tls_console = self.curl(f"https://{self.root_ip}:{AGENT_PORT}/healthz")
        loopback = self.run(
            "root",
            ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://127.0.0.1:{GATEWAY_PORT}/healthz"],
        )["out"].strip()  # fmt: skip
        https_named = f"https://{self.root_ip}:"
        self.record.add(
            "plain-off: plain HTTP from another machine is refused with the https URL named",
            set_off.get("status") == 200
            and state.get("plainAllowed") is False
            and gateway["status"] == "403"
            and https_named in gateway["body"]
            and console["status"] == "403"
            and https_named in console["body"]
            and tls_gateway["status"] == "200"
            and tls_console["status"] == "200"
            and loopback == "200",
            setting=set_off.get("status"),
            plainAllowed=state.get("plainAllowed"),
            gateway=gateway["status"],
            gatewayBody=gateway["body"][:200],
            console=console["status"],
            consoleBody=console["body"][:200],
            tlsGateway=tls_gateway["status"],
            tlsConsole=tls_console["status"],
            loopback=loopback,
        )
        back = self._plain_setting("on")
        assert back.get("status") == 200, f"plain back on: {back}"

    def label_forged_public_name(self) -> None:
        pair = self.pair
        stolen = pair.exec(
            "root",
            "steal-ca",
            {
                "root": self.up.root_dir,
                "passphrase": self.passphrase,
                "private_ip": pair.ip["mitm"],
            },
        )
        if "error" in stolen:  # type: ignore[operator]
            self.record.add("forged-public-name: the CA key was taken", False, **stolen)  # type: ignore[arg-type]
            return
        if lt1.Pair.name(pair, "mitm") not in pair.containers:
            pair.up_extra("mitm")
        for port, which in ((8443, "public"), (8444, "private")):
            pair.exec(
                "mitm",
                "spawn",
                {
                    "argv": [PYTHON, "/instruments/" + HERE.name, "--inside", "tls-server",
                             "--argument", json.dumps({"port": port, "pem": stolen[which]})],  # type: ignore[index]
                    "log": f"/tmp/forged-{which}.log",
                },
            )  # fmt: skip
        time.sleep(3)
        mitm = pair.ip["mitm"]
        public = self.curl(
            f"https://{PUBLIC_NAME}:8443/", "--resolve", f"{PUBLIC_NAME}:8443:{mitm}"
        )
        private = self.curl(f"https://{mitm}:8444/")
        chromium_public = pair.exec(
            "client",
            "browser",
            {
                "url": f"https://{PUBLIC_NAME}:8443/",
                "resolve": f"MAP {PUBLIC_NAME} {mitm}",
            },
        )
        chromium_private = pair.exec(
            "client", "browser", {"url": f"https://{mitm}:8444/"}
        )
        self.record.add(
            "forged-public-name: a leaf for a public name signed by the CA is refused",
            public["rc"] == 60
            and private["status"] == "200"
            and "error" in chromium_public  # type: ignore[operator]
            and chromium_private.get("status") == 200,  # type: ignore[union-attr]
            curlPublic={"rc": public["rc"], "err": public["err"][:240]},
            curlPrivate=private["status"],
            chromiumPublic=chromium_public,
            chromiumPrivate=chromium_private,
        )


def judge(run: Run, wire: bytes) -> None:
    record, pair = run.record, run.pair
    flows = lt1.pcap_flows(wire)
    client = pair.ip["client"]
    install = {run.root_ip, run.worker_ip}
    doors = {AGENT_PORT, GATEWAY_PORT}
    sent = sum(
        len(v) for (s, _, d, _), v in flows.items() if s == client and d in install
    )
    received = sum(
        len(v) for (s, _, d, _), v in flows.items() if d == client and s in install
    )
    record.add(
        "the capture saw the client talk to the install, both ways",
        sent > 0 and received > 0,
        bytesSent=sent,
        bytesReceived=received,
        pcapBytes=len(wire),
    )
    deliberate = range(PLAIN_PORTS[0], PLAIN_PORTS[1] + 1)
    plain = sorted(
        f"{s}:{sp}->{d}:{dp}"
        for (s, sp, d, dp), v in flows.items()
        if s == client and d in install and dp in doors and sp not in deliberate
        and v[:1] != b"\x16"
    )  # fmt: skip
    probes = {
        sp
        for (s, sp, d, dp) in flows
        if s == client and d in install and sp in deliberate
    }
    record.add(
        "every connection from the client to a door is TLS, but the deliberate plain probes",
        not plain and len(probes) >= 1,
        plain=plain[:12],
        deliberatePlain=len(probes),
    )
    streams = b"\n".join(bytes(v) for v in flows.values())

    def where(needle: bytes) -> list[str]:
        return sorted(
            f"{s}:{sp}->{d}:{dp}" for (s, sp, d, dp), v in flows.items() if needle in v
        )

    for label, needle in (
        ("the canary", run.canary.encode()),
        ("the passphrase", run.passphrase.encode()),
        ("Bearer", b"Bearer"),
        ("eyJ", b"eyJ"),
    ):
        hit = needle in wire or needle in streams
        record.add(f"{label} is nowhere on the wire", not hit, flows=where(needle)[:12])


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
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
        help="sabotage to run: foreign-address,other-key,plain-off,forged-public-name",
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
    labels = [x for x in args.labels.split(",") if x]
    for label in labels:
        if not hasattr(Run, "label_" + label.replace("-", "_")):
            parser.error(f"unknown label {label!r}")
    args.output.mkdir(parents=True, exist_ok=False)
    image = args.image or build_image(args.sources.resolve())
    record = lt1.Record()
    pair = lt1.Pair(image, args.output.resolve())
    run = Run(pair, record)
    wire = b""
    try:
        try:
            run.exercise(labels)
        finally:
            if pair.name("capture") in pair.containers:
                wire = pair.stop_capture()
            pair.collect_logs()
        judge(run, wire)
    except Exception as exc:
        record.add("the run completed", False, error=f"{type(exc).__name__}: {exc}")
    finally:
        if not args.keep:
            pair.down()
        (args.output / "result.json").write_text(
            json.dumps({"image": image, "checks": record.checks}, indent=2),
            encoding="utf-8",
        )
        (args.output / "result.md").write_text(
            record.markdown().replace("# LT1 machine TLS", "# LT2 client TLS"),
            encoding="utf-8",
        )
        if wire:
            (args.output / "wire.pcap").write_bytes(wire)
    sys.exit(1 if record.failed else 0)


if __name__ == "__main__":
    main()
