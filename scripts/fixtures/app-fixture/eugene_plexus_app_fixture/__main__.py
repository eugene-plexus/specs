"""An app that does exactly what `AppManifest` says an app owes the agent.

Stdlib only, so installing it measures the registry and not a package
index. It is the smallest honest spoke:

* binds `EUGENE_PLEXUS_APP_BIND_PORT` and answers `GET /healthz`;
* serves a config trio (`/v1/config`, `/v1/config/schema`, `PATCH
  /v1/config`) that requires `EUGENE_PLEXUS_APP_ADMIN_TOKEN` as the bearer
  and refuses anything else -- a hub credential included;
* `GET /ask?model=<id>` sends one chat completion to
  `EUGENE_PLEXUS_APP_GATEWAY_URL` with the key in
  `EUGENE_PLEXUS_APP_KEY_FILE`, the way any outside client would, and
  reports what came back;
* `GET /env` lists the NAMES of the `EUGENE_PLEXUS_*` variables it was
  started with -- never a value -- so the acceptance run can assert that
  no hub credential reached it;
* `GET /` is a page, so there is something for Open to open.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

_STATE = {"greeting": "hello"}
_SCHEMA = {
    "component": "fixture",
    "fields": [
        {
            "key": "greeting",
            "label": "Greeting",
            "description": "What the fixture's page says.",
            "category": "general",
            "valueType": "string",
            "default": "hello",
        }
    ],
    "categories": {"general": "General"},
}


def _admin_token() -> str:
    return os.environ.get("EUGENE_PLEXUS_APP_ADMIN_TOKEN", "")


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object, content_type: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        token = _admin_token()
        return bool(token) and self.headers.get("authorization") == f"Bearer {token}"

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/healthz":
            self._send(200, {"status": "ok"})
        elif url.path == "/":
            page = f"<!doctype html><title>Fixture</title><p>{_STATE['greeting']}</p>"
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif url.path == "/env":
            self._send(200, sorted(k for k in os.environ if k.startswith("EUGENE_PLEXUS_")))
        elif url.path == "/ask":
            self._ask(parse_qs(url.query).get("model", [""])[0])
        elif url.path in ("/v1/config", "/v1/config/schema"):
            if not self._authorized():
                self._send(401, {"detail": "this app accepts only its admin token"})
            else:
                self._send(200, dict(_STATE) if url.path == "/v1/config" else _SCHEMA)
        else:
            self._send(404, {"detail": "not here"})

    def do_PATCH(self) -> None:
        if urlsplit(self.path).path != "/v1/config":
            self._send(404, {"detail": "not here"})
            return
        if not self._authorized():
            self._send(401, {"detail": "this app accepts only its admin token"})
            return
        length = int(self.headers.get("content-length") or 0)
        patch = json.loads(self.rfile.read(length) or b"{}")
        applied, rejected = [], []
        for key, value in patch.items():
            if key != "greeting":
                rejected.append({"key": key, "message": "no such setting"})
            elif value is None:
                _STATE["greeting"] = "hello"
                applied.append(key)
            else:
                _STATE["greeting"] = str(value)
                applied.append(key)
        self._send(200, {"applied": applied, "rejected": rejected, "requiresRestart": False})

    def _ask(self, model: str) -> None:
        gateway = os.environ.get("EUGENE_PLEXUS_APP_GATEWAY_URL")
        key_file = os.environ.get("EUGENE_PLEXUS_APP_KEY_FILE")
        if not gateway or not key_file or not Path(key_file).is_file():
            self._send(503, {"detail": "no gateway or no key", "gateway": gateway})
            return
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                "max_tokens": 20,
            }
        ).encode()
        request = urllib.request.Request(
            gateway.rstrip("/") + "/v1/chat/completions",
            data=body,
            headers={
                "authorization": "Bearer " + Path(key_file).read_text(encoding="utf-8").strip(),
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                answer = json.loads(response.read())
                self._send(
                    200,
                    {
                        "status": response.status,
                        "driver": answer.get("x_eugene_plexus", {}).get("driver"),
                    },
                )
        except urllib.error.HTTPError as exc:
            self._send(200, {"status": exc.code, "body": exc.read().decode(errors="replace")[:300]})

    def log_message(self, *_args: object) -> None:
        return None


def main() -> None:
    host = os.environ.get("EUGENE_PLEXUS_APP_BIND_HOST", "127.0.0.1")
    port = int(os.environ["EUGENE_PLEXUS_APP_BIND_PORT"])
    print(f"fixture app on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
