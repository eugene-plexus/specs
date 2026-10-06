"""Issue and renew real TLS-ALPN certificates with Caddy and Let's Encrypt's Pebble.

No public CA requests or system DNS/trust changes. Test-only Pebble is downloaded
at a pinned release/digest into a temporary directory, never shipped in the image.
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import ipaddress
import json
import os
import platform
import shutil
import socket
import socketserver
import ssl
import struct
import subprocess
import tarfile
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from eugene_plexus_agent.entrypoint import EntryConfig, caddy_config

SHA256 = {
    "x86_64": ("amd64", "4f2fcb5bca8c85c9cf73ad140fccfc0d2be40bd81ab99879c79b7b8a0b4f70ed"),
    "aarch64": ("arm64", "b53fd072a69eb7692451de4e8b0667e0bdf5cccd7e36fc51b8eaf2fcc135ed9f"),
}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LocalDNS(socketserver.BaseRequestHandler):
    """Only the two disposable test names; Pebble alone uses this resolver."""
    def handle(self):
        tcp = isinstance(self.request, socket.socket)
        if tcp:
            length = self.request.recv(2)
            if len(length) != 2:
                return
            size = struct.unpack("!H", length)[0]
            data = b""
            while len(data) < size:
                chunk = self.request.recv(size - len(data))
                if not chunk:
                    return
                data += chunk
        else:
            data, sock = self.request
        end, labels = 12, []
        while data[end]:
            size = data[end]
            labels.append(data[end + 1:end + 1 + size].decode("ascii"))
            end += size + 1
        end += 1
        kind = struct.unpack("!H", data[end:end + 2])[0]
        name = ".".join(labels)
        question = data[12:end + 4]
        answer = b""
        if name in ("eugene.example.org", "workbench.example.org") and kind == 1:
            answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4) + socket.inet_aton("127.0.0.1")
        response = data[:2] + struct.pack("!HHHHH", 0x8180, 1, bool(answer), 0, 0) + question + answer
        if tcp:
            self.request.sendall(struct.pack("!H", len(response)) + response)
        else:
            sock.sendto(response, self.client_address)


def wait(operation, seconds=90):
    deadline = time.perf_counter() + seconds
    last = None
    while time.perf_counter() < deadline:
        try:
            result = operation()
            if result:
                return result
        except (OSError, httpx.HTTPError, http.client.HTTPException) as exc:
            last = str(exc)
        time.sleep(.2)
    raise AssertionError(f"certificate operation timed out: {last}")


def main():
    binary = os.environ.get("CADDY_TEST_BINARY") or shutil.which("caddy")
    assert binary
    with tempfile.TemporaryDirectory(prefix="ep-acme-check-") as tmp, contextlib.ExitStack() as stack:
        folder = Path(tmp)
        arch, digest = SHA256[platform.machine()]
        with httpx.Client(timeout=60, follow_redirects=True, trust_env=False) as download:
            archive = download.get(f"https://github.com/letsencrypt/pebble/releases/download/v2.10.1/pebble-linux-{arch}.tar.gz")
            archive.raise_for_status()
        assert hashlib.sha256(archive.content).hexdigest() == digest
        with tarfile.open(fileobj=io.BytesIO(archive.content)) as bundle:
            member = next(m for m in bundle.getmembers() if Path(m.name).name == "pebble" and m.isfile())
            pebble = folder / "pebble"
            pebble.write_bytes(bundle.extractfile(member).read())
            pebble.chmod(0o700)

        # The ACME API itself also uses verified TLS, with an ephemeral local CA.
        now = datetime.now(UTC)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable API CA")])
        root = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
                .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                .sign(ca_key, hashes.SHA256()))
        api_key = ec.generate_private_key(ec.SECP256R1())
        cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
                .issuer_name(ca_name).public_key(api_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.DNSName("localhost")]), False)
                .sign(ca_key, hashes.SHA256()))
        ca_file, cert_file, key_file = folder / "api-ca.pem", folder / "api.pem", folder / "api-key.pem"
        ca_file.write_bytes(root.public_bytes(serialization.Encoding.PEM))
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(api_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.create_default_context(cafile=str(ca_file))
        api_port, management_port, tls_port = free_port(), free_port(), free_port()
        dns = socketserver.ThreadingUDPServer(("127.0.0.1", 0), LocalDNS)
        threading.Thread(target=dns.serve_forever, daemon=True).start()
        stack.callback(dns.server_close)
        stack.callback(dns.shutdown)
        tcp_dns = socketserver.ThreadingTCPServer(dns.server_address, LocalDNS)
        threading.Thread(target=tcp_dns.serve_forever, daemon=True).start()
        stack.callback(tcp_dns.server_close)
        stack.callback(tcp_dns.shutdown)
        config_file = folder / "pebble.json"
        config_file.write_text(json.dumps({"pebble": {
            "listenAddress": f"127.0.0.1:{api_port}", "managementListenAddress": f"127.0.0.1:{management_port}",
            "certificate": str(cert_file), "privateKey": str(key_file), "tlsPort": tls_port,
            "httpPort": free_port(), "profiles": {"default": {"description": "Short acceptance certificates", "validityPeriod": 45}},
        }}))
        log = stack.enter_context((folder / "pebble.log").open("w+"))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PEBBLE_", "EUGENE_PLEXUS_"))}
        env.update(PEBBLE_VA_NOSLEEP="1", PEBBLE_WFE_NONCEREJECT="0", PEBBLE_AUTHZREUSE="0")
        ca_process = subprocess.Popen([str(pebble), "-config", str(config_file), "-dnsserver", f"127.0.0.1:{dns.server_address[1]}"], stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env)
        def stop(proc):
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)
        stack.callback(stop, ca_process)
        client = stack.enter_context(httpx.Client(verify=context, timeout=3, trust_env=False))
        wait(lambda: client.get(f"https://127.0.0.1:{api_port}/dir").status_code == 200)
        issued_root = client.get(f"https://127.0.0.1:{management_port}/roots/0")
        issued_root.raise_for_status()
        issued_context = ssl.create_default_context(cadata=issued_root.text)
        config = EntryConfig.model_validate({
            "listen_port": tls_port,
            "acme": {"email": "acceptance@example.org", "accept_terms": True},
            "console": {"origin": "https://eugene.example.org", "networks": ["198.51.100.0/24"]},
            "workbench": {"origin": "https://workbench.example.org", "networks": ["0.0.0.0/0"]},
        })
        directory = folder / "entry"
        directory.mkdir(mode=0o700)
        document = caddy_config(config, directory, "test-only", {"agent": 9})
        # Only the test authority and renewal schedule change. The actual
        # production TLS-ALPN challenge, names and routing remain as generated.
        automation = document["apps"]["tls"]["automation"]
        automation["renew_interval"] = "1s"
        policy = automation["policies"][0]
        policy["renewal_window_ratio"] = .5
        issuer = policy["issuers"][0]
        issuer.update(ca=f"https://127.0.0.1:{api_port}/dir", test_ca=f"https://127.0.0.1:{api_port}/dir", trusted_roots_pem_files=[str(ca_file)])
        path = directory / "caddy.json"
        path.write_text(json.dumps(document))
        proxy_log = stack.enter_context((folder / "caddy.log").open("w+"))
        def start():
            proc = subprocess.Popen([binary, "run", "--config", str(path)], stdin=subprocess.DEVNULL, stdout=proxy_log, stderr=proxy_log)
            stack.callback(stop, proc)
            return proc
        process = start()
        def serial(host):
            conn = http.client.HTTPSConnection(host, tls_port, context=issued_context, timeout=2)
            conn._create_connection = lambda *a, **kw: socket.create_connection(("127.0.0.1", tls_port), timeout=2)
            try:
                conn.request("GET", "/")
                der = conn.sock.getpeercert(binary_form=True)
                response = conn.getresponse()
                assert response.status == (403 if host.startswith("eugene.") else 503)
                response.read()
                return x509.load_der_x509_certificate(der).serial_number
            finally:
                conn.close()
        try:
            first = wait(lambda: serial("eugene.example.org"))
            wait(lambda: serial("workbench.example.org"))
            renewed = wait(lambda: (value if (value := serial("eugene.example.org")) != first else None))
            assert renewed != first
            stop(process)
            start()
            assert wait(lambda: serial("eugene.example.org")) == renewed
            print("PASS: real ACME TLS-ALPN issuance, automatic renewal and persisted certificates survive restart; administration remains private and HTTP validation is disabled", flush=True)
        except BaseException:
            for output in (log, proxy_log):
                output.flush()
                output.seek(0)
                print(output.read()[-5000:])
            raise


if __name__ == "__main__":
    main()
