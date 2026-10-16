"""Real pinned Caddy, disposable ports: shared API routes and legacy migration.

Run in Linux with the agent's dependencies and --caddy <binary>. No live DNS,
services, credentials or trust stores are used. Backends are recording fixtures.
"""
from __future__ import annotations

import argparse
import contextlib
import http.client
import importlib.util
import json
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent/src"))
from eugene_plexus_agent.entrypoint import EntryConfig  # noqa: E402

spec = importlib.util.spec_from_file_location("proxy_checks", Path(__file__).with_name("entrypoint-proxy-checks.py"))
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class Backend(BaseHTTPRequestHandler):
    seen = []
    release = threading.Event()

    def do_GET(self):
        self.answer()

    def do_POST(self):
        self.answer()

    def answer(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.seen.append((self.server.kind, self.path, dict(self.headers), body.decode()))
        if self.server.kind == "gateway" and self.headers.get("Authorization") != "Bearer fixture-key":
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(200)
        if self.path == "/v1/chat/completions":
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.release.wait(10)
            self.wfile.write(b"data: last\n\n")
            return
        content = json.dumps({"kind": self.server.kind, "path": self.path, "body": body.decode()}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        # A permissive upstream policy must not override the shared-origin policy.
        self.send_header("Content-Security-Policy", "default-src * 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_):
        pass


def main(binary, result_file=None):
    directory = Path(tempfile.mkdtemp(prefix="ep-two-host-proxy-"))
    print(f"Artifacts: {directory}", flush=True)
    servers = []
    ports = {}
    try:
        for kind in ("agent", "gateway", "workbench"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
            server.kind = kind
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
            ports[kind] = server.server_port
        port = proxy.free_port()
        base = {
            "listen_port": port,
            "proxy": {"addresses": ["127.0.0.2"], "transport": "http"},
            "console": proxy.service("eugene", ["198.51.100.0/24"]),
            "workbench": proxy.service("workbench", ["0.0.0.0/0"]),
            "inference_on_console": {"networks": ["203.0.113.0/24"]},
            "inference": proxy.service("legacy", ["203.0.113.0/24"]),
        }

        def connect(path, *, host="eugene.example.org", visitor="203.0.113.4", key=True, method="GET", body=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3, source_address=("127.0.0.2", 0))
            headers = {"Host": host, "X-Forwarded-For": visitor, "X-Forwarded-Proto": "https",
                       "X-Eugene-Plexus-Peer": "spoof", "X-Eugene-Entry-Token": "spoof"}
            if key:
                headers["Authorization"] = "Bearer fixture-key"
            conn.request(method, path, body=body, headers=headers)
            return conn, conn.getresponse()

        def request(path, **kw):
            conn, response = connect(path, **kw)
            try:
                return response.status, response.read(), dict(response.headers)
            finally:
                conn.close()

        checks = []
        def check(name, condition):
            assert condition, name
            checks.append(name)
            print("PASS " + name, flush=True)

        with proxy.running(binary, directory / "migration", EntryConfig.model_validate(base), ports):
            status, body, headers = request("/inference/v1/models?limit=2")
            check("prefix stripped exactly and query retained", status == 200 and json.loads(body)["path"] == "/v1/models?limit=2")
            check("shared API documents cannot execute in the console origin", "sandbox" in headers.get("Content-Security-Policy", "") and headers.get("X-Content-Type-Options") == "nosniff")
            check("authorization still reaches the gateway", request("/inference/v1/models", key=False)[0] == 401)
            check("legacy inference clients still work", request("/v1/models", host="legacy.example.org")[0] == 200)
            check("public sign-in remains available", request("/oidc/account")[0] == 200)
            check("Workbench keeps its own hostname", json.loads(request("/", host="workbench.example.org")[1])["kind"] == "workbench")
            before = len(Backend.seen)
            for path in ("/inference/v1/config", "/inference/v1/auth/login", "/inference/oidc/account", "/inference", "/v1/config"):
                check("refused " + path, request(path)[0] == 403)
            check("refused paths reached no backend", len(Backend.seen) == before)
            check("console permission cannot bypass the API network policy", request("/inference/v1/models", visitor="198.51.100.4")[0] == 403)
            check("private console still answers", request("/v1/config", visitor="198.51.100.4")[0] == 200)
            check("existing engines page is preserved", json.loads(request("/inference/", visitor="198.51.100.4")[1])["kind"] == "agent")
            status, body, _ = request("/inference/v1/embeddings", method="POST", body='{"input":"hello"}')
            check("POST bodies survive routing", status == 200 and json.loads(body)["body"] == '{"input":"hello"}')
            conn, stream = connect("/inference/v1/chat/completions", method="POST", body='{"stream":true}')
            try:
                check("first SSE event arrives before completion", stream.status == 200 and stream.readline() == b"data: first\n")
                Backend.release.set()
                check("remaining SSE events arrive", b"data: last" in stream.read())
            finally:
                conn.close()
            check("spoofed internal authority is stripped", all(
                not any(k.lower().startswith("x-eugene") for k in row[2])
                for row in Backend.seen if row[0] == "gateway"
            ))
        # Only two hostnames after the owner removes the compatibility alias.
        base.pop("inference")
        base["console_direct"] = True
        with proxy.running(binary, directory / "two-hosts", EntryConfig.model_validate(base), ports):
            check("two-host API also works with a direct-only console", request("/inference/v1/models")[0] == 200)
            check("removed alias no longer routes", request("/v1/models", host="legacy.example.org")[0] == 421)
        base.pop("inference_on_console")
        base["console_direct"] = False
        with proxy.running(binary, directory / "disabled", EntryConfig.model_validate(base), ports):
            before = len(Backend.seen)
            check("disabled API cannot fall through to console", request("/inference/v1/models", visitor="198.51.100.4")[0] == 403 and len(Backend.seen) == before)
        result = json.dumps({"checks": checks, "passed": len(checks)}, indent=2) + "\n"
        (directory / "result.json").write_text(result)
        if result_file:
            Path(result_file).write_text(result, encoding="utf-8")
    finally:
        Backend.release.set()
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--caddy", required=True)
    parser.add_argument("--result-file")
    args = parser.parse_args()
    main(args.caddy, args.result_file)
