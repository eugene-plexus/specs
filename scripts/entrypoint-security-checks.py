"""Exercise the installed Caddy and agent routing code on disposable local ports.

Runs inside the built container in CI; also runnable in an isolated Linux venv.
Never changes system trust, DNS, installed services or an existing data directory.
"""

from __future__ import annotations

import http.client
import contextlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from eugene_plexus_agent.entrypoint import EntryConfig, caddy_config, install


class Echo(BaseHTTPRequestHandler):
    release_stream = threading.Event()

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.release_stream.wait(timeout=10)
            self.wfile.write(b"data: last\n\n")
            self.wfile.flush()
            return
        content = json.dumps({"headers": dict(self.headers), "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(content)

    def do_POST(self):
        # Actually read the body to exercise Caddy's streaming request limit.
        remaining = int(self.headers.get("Content-Length", "0"))
        while remaining:
            part = self.rfile.read(min(remaining, 65536))
            if not part:
                break
            remaining -= len(part)
        self.do_GET()

    def log_message(self, *args):
        pass


def main():
    binary = os.environ.get("CADDY_TEST_BINARY") or shutil.which("caddy")
    assert binary, "the image must include Caddy"
    assert subprocess.check_output([binary, "version"], text=True).startswith("v2.11.7 ")
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="ep-entry-check-") as folder:
        directory = Path(folder)
        directory.chmod(0o700)
        def service(host, networks):
            return {"origin": f"https://{host}.home.arpa:{port}", "networks": networks}
        config = EntryConfig.model_validate({
            "listen_port": port, "internal_ca": True,
            "console": service("eugene", ["198.51.100.0/24"]),
            "workbench": service("workbench", ["0.0.0.0/0", "::/0"]),
            "inference": service("inference", ["127.0.0.1/32"]),
            "nodes": service("nodes", ["198.51.100.0/24"]),
        })
        startup = directory / "entrypoint.json"
        startup.write_text(config.model_dump_json())
        prior_bundle = os.environ.get("SSL_CERT_FILE")
        # The agent's own settings, not a stand-in: a stand-in carrying four
        # fields stopped this check the day `prepare` read a fifth.
        from eugene_plexus_agent.settings import Settings

        application = SimpleNamespace(state=SimpleNamespace(settings=Settings(
            config_file=directory / "agent.yaml", entrypoint_config=startup,
            entrypoint_binary=binary, bind_port=backend.server_port,
        )), add_middleware=lambda *args, **kwargs: None)
        try:
            install(application)
            bundle = Path(os.environ["SSL_CERT_FILE"])
            assert bundle.is_file() and b"BEGIN CERTIFICATE" in bundle.read_bytes()
            assert (directory / "entrypoint/tls/pki/authorities/local/root.crt").is_file()
        finally:
            if prior_bundle is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = prior_bundle
        directory = directory / "entrypoint"
        upstream = backend.server_port
        document = caddy_config(config, directory, "disposable-proxy-secret", {
            "agent": upstream, "workbench": upstream, "gateway": upstream, "control": upstream,
        })
        path = directory / "caddy.json"
        path.write_text(json.dumps(document))
        subprocess.run([binary, "validate", "--config", str(path)], check=True)
        with (directory / "caddy.log").open("w+") as log:
            process = subprocess.Popen([binary, "run", "--config", str(path)], stdout=log, stderr=log)
            try:
                root = directory / "tls/pki/authorities/local/root.crt"
                deadline = time.perf_counter() + 30
                while not root.is_file():
                    assert time.perf_counter() < deadline and process.poll() is None
                    time.sleep(0.1)
                context = ssl.create_default_context(cafile=str(root))

                def request(host, target="/", *, headers=None, method="GET", body=None):
                    connection = http.client.HTTPSConnection(host + ".home.arpa", port, context=context, timeout=5)
                    connection._create_connection = lambda *args, **kwargs: socket.create_connection(("127.0.0.1", port), timeout=5)
                    try:
                        connection.request(method, target, headers=headers or {}, body=body)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()

                while True:
                    try:
                        if request("workbench")[0] == 200:
                            break
                    except (OSError, http.client.HTTPException):
                        assert time.perf_counter() < deadline and process.poll() is None
                        time.sleep(0.1)
                assert request("eugene")[0] == 403
                assert request("eugene", "/api/proxy/control/v1/config")[0] == 403
                assert request("nodes", "/v1/nodes")[0] == 403
                assert request("eugene", "/oidc/authorize")[0] == 200
                assert request("inference", "/v1/models")[0] == 200
                assert request("inference", "/v1/audio/speech")[0] == 200
                assert request("inference", "/v1/responses/input_tokens")[0] == 200
                assert request("inference", "/v1/config")[0] == 403
                assert request("inference", "/v1/auth/login")[0] == 403
                from eugene_plexus_agent._http import ssl_context
                agent_connection = http.client.HTTPSConnection("workbench.home.arpa", port, context=ssl_context(), timeout=5)
                agent_connection._create_connection = lambda *args, **kwargs: socket.create_connection(("127.0.0.1", port), timeout=5)
                agent_connection.request("GET", "/")
                assert agent_connection.getresponse().status == 200
                agent_connection.close()
                assert request("workbench", headers={"Host": f"eugene.home.arpa:{port}"})[0] == 421
                assert request("workbench", headers={"Host": "attacker.example"})[0] == 421
                try:
                    request("unknown")
                except ssl.SSLError:
                    pass
                else:
                    raise AssertionError("unknown TLS host was accepted")
                forged = {
                    "Forwarded": "for=198.51.100.10;host=attacker.example;proto=http",
                    "X-Forwarded-For": "198.51.100.10",
                    "X-Forwarded-Host": "attacker.example",
                    "X-Forwarded-Proto": "http",
                    "X-Eugene-Plexus-Peer": "198.51.100.10",
                    "X-Eugene-Plexus-Forwarded-For": "198.51.100.10",
                    "X-Eugene-Entry-Token": "forged",
                    "X-Eugene-Entry-Client": "198.51.100.10",
                }
                assert request("eugene", headers=forged)[0] == 403
                status, payload = request("workbench", headers=forged)
                assert status == 200
                forwarded = {k.lower(): v for k, v in json.loads(payload)["headers"].items()}
                for name in ("forwarded", "x-eugene-plexus-peer", "x-eugene-plexus-forwarded-for",
                             "x-eugene-entry-token", "x-eugene-entry-client"):
                    assert name not in forwarded, (name, forwarded)
                assert forwarded.get("x-forwarded-for") in (None, "127.0.0.1")
                assert forwarded.get("x-forwarded-proto") in (None, "https")
                status, payload = request("eugene", "/oidc/authorize", headers=forged)
                forwarded = {k.lower(): v for k, v in json.loads(payload)["headers"].items()}
                assert forwarded["x-eugene-entry-token"] == "disposable-proxy-secret"
                assert forwarded["x-eugene-entry-client"] == "127.0.0.1"
                assert forwarded["host"] == f"eugene.home.arpa:{port}"
                assert request("workbench", method="POST", body=b"x" * (33 * 1024 * 1024))[0] == 413
                assert request("workbench", headers={"X-Oversized": "x" * 40000})[0] == 431
                # Reload through the permissioned socket: unavailable apps must
                # stop routing and become available again without restarting Caddy.
                import httpx
                with httpx.Client(transport=httpx.HTTPTransport(uds=str(directory / "admin.sock")), trust_env=False) as admin:
                    stream = http.client.HTTPSConnection("workbench.home.arpa", port, context=context, timeout=5)
                    stream._create_connection = lambda *args, **kwargs: socket.create_connection(("127.0.0.1", port), timeout=5)
                    stream.request("GET", "/stream")
                    ongoing = stream.getresponse()
                    assert ongoing.status == 200 and ongoing.read(13) == b"data: first\n\n"
                    missing = caddy_config(config, directory, "disposable-proxy-secret", {"agent": upstream})
                    assert admin.post("http://localhost/load", json=missing).status_code == 200
                    assert request("workbench")[0] == 503
                    Echo.release_stream.set()
                    assert ongoing.read() == b"data: last\n\n"
                    stream.close()
                    assert admin.post("http://localhost/load", json=document).status_code == 200
                    assert request("workbench")[0] == 200
                print("PASS: CA provisioning, real HTTPS routing, SNI/Host isolation, access policies, header spoofing, request limits and streaming through reload")
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read()[-6000:])
                raise
            finally:
                process.terminate()
                process.wait(timeout=15)
                backend.shutdown()
                backend.server_close()


if __name__ == "__main__":
    main()
