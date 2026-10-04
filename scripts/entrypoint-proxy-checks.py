"""Real Caddy: trusted proxy boundaries and live supplied-certificate rotation.

Disposable processes, ports and files only. Also runs inside the shipped image.
"""
from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from eugene_plexus_agent.entrypoint import EntryConfig, EntryPoint, TrustedProxy, caddy_config


class Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(port, host="eugene.example.org", *, source="127.0.0.2", headers=(), context=None):
    cls = http.client.HTTPSConnection if context else http.client.HTTPConnection
    extra = {"context": context} if context else {}
    conn = cls(host, port, timeout=3, source_address=(source, 0), **extra)
    conn._create_connection = lambda *args, **kw: socket.create_connection(
        ("127.0.0.1", port), timeout=3, source_address=(source, 0)
    )
    try:
        conn.putrequest("GET", "/", skip_host=True)
        conn.putheader("Host", host)
        for name, value in headers:
            conn.putheader(name, value)
        conn.endheaders()
        cert = conn.sock.getpeercert(binary_form=True) if context else None
        reply = conn.getresponse()
        return reply.status, reply.read(), cert
    finally:
        conn.close()


@contextlib.contextmanager
def running(binary, directory, config, ports):
    directory.mkdir(mode=0o700)
    path = directory / "caddy.json"
    path.write_text(json.dumps(caddy_config(config, directory, "test-ingress-secret", ports)))
    subprocess.run([binary, "validate", "--config", str(path)], check=True, capture_output=True)
    with (directory / "log.txt").open("w+") as log:
        process = subprocess.Popen([binary, "run", "--config", str(path)], stdout=log, stderr=log)
        try:
            deadline = time.perf_counter() + 15
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", config.listen_port), timeout=1):
                        break
                except OSError:
                    assert time.perf_counter() < deadline and process.poll() is None
                    time.sleep(.05)
            yield process
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read()[-4000:])
            raise
        finally:
            process.terminate()
            process.wait(timeout=15)


def service(host, allowed):
    return {"origin": f"https://{host}.example.org", "networks": allowed}


def proxy_checks(binary, base, upstream):
    port = free_port()
    config = EntryConfig.model_validate({
        "listen_port": port, "proxy": {"addresses": ["127.0.0.2"]},
        "console": service("eugene", ["198.51.100.0/24"]),
        "workbench": service("workbench", ["0.0.0.0/0", "::/0"]),
        "nodes": service("nodes", ["198.51.100.0/24"]),
    })
    with running(binary, base / "proxy", config, {"agent": upstream, "workbench": upstream, "control": upstream}):
        def forwarded(ip, proto="https"):
            return [("X-Forwarded-For", ip), ("X-Forwarded-Proto", proto)]
        assert request(port, source="127.0.0.1", headers=forwarded("198.51.100.4"))[0] == 403
        assert request(port)[0] == 403
        for ip in ("", "garbage", "127.0.0.2", "127.0.0.2, garbage"):
            assert request(port, headers=forwarded(ip))[0] == 403, ip
        for proto in ("http", "https,http", ""):
            assert request(port, headers=forwarded("198.51.100.4", proto))[0] == 403, proto
        assert request(port, headers=forwarded("198.51.100.4") + [("X-Forwarded-Proto", "http")])[0] == 403
        assert request(port, headers=forwarded("203.0.113.4"))[0] == 403
        assert request(port, "nodes.example.org", headers=forwarded("203.0.113.4"))[0] == 403
        # NPM appends the actual client after a caller-supplied XFF value.
        assert request(port, headers=forwarded("198.51.100.4, 203.0.113.4"))[0] == 403
        assert request(port, headers=forwarded("198.51.100.4") + [("X-Forwarded-For", "203.0.113.4")])[0] == 403
        assert request(port, "unknown.example.org", headers=forwarded("198.51.100.4"))[0] == 421
        status, body, _ = request(port, headers=forwarded("198.51.100.4") + [("X-Eugene-Entry-Token", "forged"), ("X-Eugene-Entry-Client", "attacker")])
        assert status == 200
        headers = {k.lower(): v for k, v in json.loads(body).items()}
        assert headers["x-eugene-entry-client"] == "198.51.100.4"
        assert headers["x-eugene-entry-token"] == "test-ingress-secret"
        status, body, _ = request(port, "workbench.example.org", headers=forwarded("2001:db8::4") + [("X-Eugene-Entry-Token", "forged")])
        assert status == 200 and "x-eugene-entry-token" not in body.decode().lower()
    print("PASS: real private-HTTP proxy refuses untrusted hops, missing/invalid metadata, spoofed chains and public admin; verified IPv4/IPv6 clients route correctly", flush=True)


def certificate_checks(binary, base, upstream):
    now = datetime.now(UTC)
    root_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable acceptance CA")])
    root = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(root_key, hashes.SHA256()))
    ca = base / "root.pem"
    ca.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    cert, key = base / "certificate.pem", base / "key.pem"
    def issue(serial):
        leaf_key = ec.generate_private_key(ec.SECP256R1())
        leaf = (x509.CertificateBuilder().subject_name(x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, "eugene.example.org")
                ])).issuer_name(name)
                .public_key(leaf_key.public_key()).serial_number(serial)
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("eugene.example.org"), x509.DNSName("workbench.example.org")]), critical=False)
                .sign(root_key, hashes.SHA256()))
        cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    issue(100)
    config = EntryConfig.model_validate({
        "listen_port": free_port(), "certificate": str(cert), "private_key": str(key),
        "console": service("eugene", ["127.0.0.0/8"]),
        "workbench": service("workbench", ["127.0.0.0/8"]),
    })
    directory = base / "certificates"
    context = ssl.create_default_context(cafile=str(ca))
    def serial():
        status, _, der = request(config.listen_port, context=context)
        assert status == 200
        return x509.load_der_x509_certificate(der).serial_number
    with running(binary, directory, config, {"agent": upstream}) as process:
        assert serial() == 100
        app = SimpleNamespace(state=SimpleNamespace(apps=None, settings=SimpleNamespace(bind_port=upstream), agent_state=SimpleNamespace(list_components=lambda: [])))
        entry = EntryPoint(app, config, directory, "test-ingress-secret")
        entry.process = process
        entry._applied = entry.ports()
        entry._applied_certificates = entry.certificate_fingerprint()
        async def reload():
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(directory / "admin.sock")), trust_env=False) as admin, httpx.AsyncClient(trust_env=False) as backend:
                await entry._sync(admin, backend)
        cert.write_text("incomplete certificate rotation")
        try:
            asyncio.run(reload())
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("invalid renewed certificate was accepted")
        assert serial() == 100
        issue(101)
        asyncio.run(reload())
        assert serial() == 101 and process.poll() is None
    print("PASS: supplied certificates rotate without process restart; failed rotation keeps the working certificate", flush=True)
    config = config.model_copy(update={"proxy": TrustedProxy(addresses=["127.0.0.2"], transport="https")})
    with running(binary, base / "proxy-tls", config, {"agent": upstream}):
        headers = [("X-Forwarded-For", "127.0.0.1"), ("X-Forwarded-Proto", "https")]
        assert request(config.listen_port, context=context, headers=headers)[0] == 200
        assert request(config.listen_port, context=context, headers=headers, source="127.0.0.1")[0] == 403
    print("PASS: verified HTTPS between proxy and Eugene enforces the same trusted-hop boundary", flush=True)


def main():
    binary = os.environ.get("CADDY_TEST_BINARY") or shutil.which("caddy")
    assert binary
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="ep-proxy-check-") as tmp:
            proxy_checks(binary, Path(tmp), backend.server_port)
            certificate_checks(binary, Path(tmp), backend.server_port)
    finally:
        backend.shutdown()
        backend.server_close()


if __name__ == "__main__":
    main()
