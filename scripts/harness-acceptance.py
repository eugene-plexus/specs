"""The shared acceptance harness is the real server (roadmap row 2, the check of record).

Ten acceptance scripts start their agent through `s8-ui-acceptance.py --serve`.
It used to build its own app and server, so a check through it tested the
harness: no console log copy, no machine port, no client doors. It now runs the
agent's own start path (`serve`, which calls `build_server`). This script starts
the harness the way those scripts do, on free ports, with one declared
component (control), and checks what an install has:

1. `GET /v1/logs` holds the agent's own boot line, "console output is mirrored to".
2. `GET /v1/node` lists the machine port as listening, and a TLS handshake to
   it completes with the key the node names as its pin.
3. The console answers over TLS beside plain HTTP (the client doors, LT2). The
   doors present the owner's own certificate here (`clientCertificateFile`),
   because a certificate from the install's CA needs an address other
   machines reach, and this run is loopback only. `lt2-client-tls-acceptance.py`
   checks the install CA's leaf; this check is that the harness's agent has
   the doors at all.
4. The stop file ends the process within 15 s, and no process it started is
   left (control, the declared component, included).
5. `Settings` as the harness builds it equals `load_settings()` with the
   variables an install sets, so the harness sets nothing an install does not.

Needs the agent and control installed in this interpreter (the Pinned
integration job has both). Run: python scripts/harness-acceptance.py
Exits 1 when a check fails, with the agent's log.

`--sabotage` runs the same checks against a copy of the harness that builds its
own app again (what it did before) and passes only when check 3 fails. Run once
by hand when the checks change.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime
import hashlib
import importlib.util
import ipaddress
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import psutil
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "s8-ui-acceptance.py"
PASSPHRASE = "harness-acceptance-passphrase"
STOP_WITHIN_SECONDS = 15

#: What the harness did before it ran the agent's own start path: a hand-built
#: app and server. `--sabotage` puts it back, and check 3 must notice.
OLD_SERVE = '''
def serve(root, port, machine_port=None):
    import asyncio
    import uvicorn
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.console_logging import install_console_capture
    from eugene_plexus_agent.settings import Settings
    install_console_capture(log_dir=root / "logs")
    app = create_app(settings=Settings(config_file=root / "agent.yaml", bind_port=port,
                                      default_topology=False))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))

    async def run():
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / "stop").exists():
            await asyncio.sleep(.1)
        server.should_exit = True
        await task
    asyncio.run(run())


'''


class Failed(Exception):
    """A check did not hold; the message names what was observed."""


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("s8_harness_under_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spki_pin(der_certificate: bytes) -> str:
    """base64url SHA-256 of the SubjectPublicKeyInfo: the machine key's pin."""
    key = x509.load_der_x509_certificate(der_certificate).public_key()
    spki = key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.urlsafe_b64encode(hashlib.sha256(spki).digest()).rstrip(b"=").decode()


def handshake(port: int) -> tuple[str, str]:
    """(TLS version, the pin of the key it presents) of a TLS handshake to a port."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname="127.0.0.1") as tls:
                der = tls.getpeercert(binary_form=True)
                assert der is not None
                return str(tls.version()), spki_pin(der)
    except (OSError, ssl.SSLError) as exc:
        raise Failed(f"the TLS handshake to 127.0.0.1:{port} did not complete: {exc}") from exc


def own_certificate(directory: Path) -> tuple[Path, Path]:
    """A self-signed certificate for 127.0.0.1, as an owner would supply, and its key."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "harness-acceptance")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = directory / "owner.crt", directory / "owner.key"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


class Run:
    def __init__(self, harness: Path, output: Path) -> None:
        self.harness_path = harness
        self.root = output
        self.harness = load_module(harness)
        self.port = self.harness.free_port()
        self.control_port = self.harness.free_port(self.port)
        self.proc: subprocess.Popen[bytes] | None = None
        self.client: httpx.Client | None = None
        self.token = ""
        self.cert_file: Path | None = None
        self.results: list[tuple[str, bool, str]] = []

    # ---- the agent, started the way the callers start it ----------------------

    def start(self) -> None:
        (self.root / "home").mkdir(parents=True)
        self.cert_file, key_file = own_certificate(self.root)
        (self.root / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
                    "clientCertificateFile": str(self.cert_file),
                    "clientKeyFile": str(key_file),
                    "components": [
                        {
                            "name": "control",
                            "kind": "control",
                            "url": f"http://127.0.0.1:{self.control_port}",
                            "spawn": {"configFile": str(self.root / "control.yaml")},
                        }
                    ],
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env.update(
            HOME=str(self.root / "home"),
            USERPROFILE=str(self.root / "home"),
            NO_PROXY="localhost,127.0.0.1,::1",
            PYTHONUTF8="1",
        )
        log = (self.root / "agent.log").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, str(self.harness_path), "--serve", str(self.root),
             "--port", str(self.port)],
            cwd=self.root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )  # fmt: skip
        self.client = httpx.Client(trust_env=False, timeout=10)
        self.wait("the agent's /healthz", lambda: self.get(f"http://127.0.0.1:{self.port}/healthz"))
        self.wait(
            "control's /healthz",
            lambda: self.get(f"http://127.0.0.1:{self.control_port}/healthz"),
            seconds=120,
        )
        assert self.client is not None
        initialized = self.client.post(
            f"http://127.0.0.1:{self.port}/v1/auth/initialize", json={"passphrase": PASSPHRASE}
        )
        initialized.raise_for_status()
        self.token = initialized.json()["sessionToken"]

    def kill_family(self) -> None:
        """A run that could not finish must not leave its agent or control running."""
        assert self.proc is not None
        with contextlib.suppress(psutil.Error, OSError):
            for process in psutil.Process(self.proc.pid).children(recursive=True):
                with contextlib.suppress(psutil.Error, OSError):
                    process.kill()
        with contextlib.suppress(OSError):
            self.proc.kill()

    def get(self, url: str) -> bool:
        assert self.client is not None
        try:
            return self.client.get(url).status_code == 200
        except httpx.HTTPError:
            return False

    def wait(self, what: str, ready: Any, seconds: float = 60) -> None:
        assert self.proc is not None
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            if ready():
                return
            if self.proc.poll() is not None:
                raise Failed(f"the agent exited with code {self.proc.returncode} before {what}")
            time.sleep(0.2)
        raise Failed(f"{what} did not come up within {seconds:.0f} s")

    def node(self) -> dict[str, Any]:
        assert self.client is not None
        answer = self.client.get(
            f"http://127.0.0.1:{self.port}/v1/node",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        answer.raise_for_status()
        body: dict[str, Any] = answer.json()
        return body

    # ---- the checks -------------------------------------------------------------

    def record(self, name: str, check: Any) -> None:
        try:
            detail = check()
        except Failed as exc:
            self.results.append((name, False, str(exc)))
        except Exception as exc:  # a check that crashes is a failed check, with its cause
            self.results.append((name, False, f"{type(exc).__name__}: {exc}"))
        else:
            self.results.append((name, True, str(detail or "")))

    def logs_are_mirrored(self) -> str:
        assert self.client is not None
        answer = self.client.get(
            f"http://127.0.0.1:{self.port}/v1/logs",
            headers={"Authorization": f"Bearer {self.token}"},
            params={"tail": 500},
        )
        answer.raise_for_status()
        lines = [str(line.get("text")) for line in answer.json().get("lines") or []]
        found = [line for line in lines if "console output is mirrored to" in line]
        if not found:
            raise Failed(
                f"GET /v1/logs has {len(lines)} lines and none says 'console output is "
                f"mirrored to'; the first is {lines[0] if lines else '(none)'!r}"
            )
        return found[0]

    def machine_port_is_up(self) -> str:
        machine = self.node().get("machine")
        if not machine:
            raise Failed("GET /v1/node has no `machine`: this agent opened no machine port")
        if not machine.get("listening"):
            raise Failed(
                f"the machine port {machine.get('port')} is not listening; the agent says: "
                f"{machine.get('error')}"
            )
        version, pin = handshake(int(machine["port"]))
        if pin != machine.get("pin"):
            raise Failed(
                f"port {machine['port']} presents key {pin}, but GET /v1/node says "
                f"{machine.get('pin')}"
            )
        return f"port {machine['port']} listening, {version}, key {pin}"

    def console_answers_over_tls(self) -> str:
        doors = self.node().get("clientTls")
        if doors is None:
            raise Failed("GET /v1/node has no `clientTls`: this agent has no client doors")
        console = next((d for d in doors.get("doors") or [] if d.get("name") == "console"), None)
        if console is None or not console.get("tls"):
            raise Failed(
                f"the console door does not take TLS; it says {console}; "
                f"the certificate state is {doors.get('state')!r}, error {doors.get('error')!r}"
            )
        assert self.cert_file is not None
        try:
            with httpx.Client(trust_env=False, timeout=10, verify=str(self.cert_file)) as secure:
                answer = secure.get(f"https://127.0.0.1:{self.port}/healthz")
        except httpx.HTTPError as exc:
            raise Failed(f"https://127.0.0.1:{self.port}/healthz did not answer: {exc}") from exc
        if answer.status_code != 200:
            raise Failed(f"https /healthz answered {answer.status_code}")
        if not self.get(f"http://127.0.0.1:{self.port}/healthz"):
            raise Failed("TLS answers, but plain HTTP no longer does on the same port")
        return f"https (the owner's certificate, verified) and http both answer 200 on port {self.port}"

    def stops_by_the_file(self) -> str:
        assert self.proc is not None
        family = psutil.Process(self.proc.pid).children(recursive=True)
        (self.root / "stop").touch()
        started = time.perf_counter()
        try:
            self.proc.wait(timeout=STOP_WITHIN_SECONDS)
        except subprocess.TimeoutExpired:
            self.kill_family()
            raise Failed(
                f"the stop file did not end the agent within {STOP_WITHIN_SECONDS} s"
            ) from None
        took = time.perf_counter() - started
        time.sleep(1)
        left = [p for p in family if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
        for process in left:
            with contextlib.suppress(psutil.Error, OSError):
                process.kill()
        if left:
            raise Failed(
                "left running after the stop: "
                + ", ".join(f"{p.pid} {self._name(p)}" for p in left)
            )
        return (
            f"exited in {took:.1f} s with code {self.proc.returncode}; "
            f"{len(family)} process(es) under it, none left"
        )

    @staticmethod
    def _name(process: psutil.Process) -> str:
        with contextlib.suppress(psutil.Error, OSError):
            return process.name()
        return "?"

    def settings_match_an_install(self) -> str:
        """`Settings` the harness builds equals what an install's variables load."""
        from eugene_plexus_agent.settings import Settings, load_settings

        built = self.harness.harness_settings(Settings, self.root, self.port, 49999).model_dump()
        variables = {
            "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(self.root / "agent.yaml"),
            "EUGENE_PLEXUS_AGENT_BIND_PORT": str(self.port),
            "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "0",
            "EUGENE_PLEXUS_AGENT_MACHINE_PORT": "49999",
        }
        os.environ.update(variables)
        try:
            loaded = load_settings().model_dump()
        finally:
            for name in variables:
                os.environ.pop(name, None)
        different = {k: (built[k], loaded[k]) for k in built if built[k] != loaded[k]}
        if different:
            raise Failed(f"the harness sets what an install does not: {different}")
        return "the same Settings as an install's variables give"


def run(harness: Path, output: Path | None, keep: bool, *, expect_failure: bool = False) -> Run:
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    root = output or Path(tempfile.mkdtemp(prefix="ep-harness-"))
    run_ = Run(harness, root)
    stopped = False
    try:
        run_.record("5. Settings equal an install's", run_.settings_match_an_install)
        try:
            run_.start()
        except Failed as exc:
            run_.results.append(("start the agent through the harness", False, str(exc)))
        else:
            run_.record("1. GET /v1/logs holds the console copy line", run_.logs_are_mirrored)
            run_.record("2. the machine port listens and answers TLS", run_.machine_port_is_up)
            run_.record("3. the console answers over TLS beside plain HTTP",
                        run_.console_answers_over_tls)
        if run_.proc is not None and run_.proc.poll() is None:
            run_.record("4. the stop file ends the agent and every child", run_.stops_by_the_file)
            stopped = True
    finally:
        if run_.proc is not None and run_.proc.poll() is None and not stopped:
            run_.kill_family()
        if run_.client is not None:
            run_.client.close()
    failed = any(not ok for _, ok, _ in run_.results) and not expect_failure
    if failed or keep:
        print(f"harness run kept in {root}")
        log = root / "agent.log"
        if failed and log.exists():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            print("--- the agent's log (last 60 lines)")
            print("\n".join(lines[-60:]))
    else:
        shutil.rmtree(root, ignore_errors=True)
    return run_


def report(run_: Run) -> bool:
    for name, ok, detail in sorted(run_.results):
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return all(ok for _, ok, _ in run_.results)


def sabotaged_copy(directory: Path) -> Path:
    source = HARNESS.read_text(encoding="utf-8")
    start = source.index("def serve(")
    end = source.index("def check(")
    copy = directory / "s8-ui-acceptance-sabotaged.py"
    copy.write_text(
        source[:start] + OLD_SERVE.lstrip("\n") + source[end:], encoding="utf-8", newline="\n"
    )
    return copy


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--output", type=Path, help="a new directory to keep the run in")
    parser.add_argument("--keep", action="store_true", help="keep the run directory on a pass")
    parser.add_argument(
        "--sabotage",
        action="store_true",
        help="check the checks: the old hand-built harness must fail check 3",
    )
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error(f"--output {args.output} exists; name a new directory")
    if not args.sabotage:
        return 0 if report(run(HARNESS, args.output, args.keep)) else 1
    with tempfile.TemporaryDirectory(prefix="ep-harness-sabotage-") as scratch:
        outcome = run(sabotaged_copy(Path(scratch)), args.output, args.keep, expect_failure=True)
        report(outcome)
    by_name = {name: ok for name, ok, _ in outcome.results}
    caught = by_name.get("3. the console answers over TLS beside plain HTTP") is False
    print(
        "CAUGHT: check 3 fails for a harness that builds its own app"
        if caught
        else "NOT CAUGHT: check 3 passed for a harness that builds its own app"
    )
    return 0 if caught else 1


if __name__ == "__main__":
    sys.exit(main())
