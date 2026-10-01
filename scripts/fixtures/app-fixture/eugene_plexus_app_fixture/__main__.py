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
* `GET /` is a page, so there is something for Open to open;
* `GET /probe?root=<dir>` (C1, `workbench.md` §2) says who the app runs
  as and which files under `root` it can open -- names only, never a byte
  of what they hold -- plus, on Windows, which of its account's stored
  credentials mention Eugene. It is how the acceptance run proves an app
  cannot read the install's keys, rather than assuming it.
"""

from __future__ import annotations

import json
import os
import sys
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
        elif url.path == "/probe":
            self._send(200, _probe(parse_qs(url.query).get("root", [""])[0]))
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


_PROBE_LIMIT = 20000


def _whoami() -> str:
    if sys.platform == "win32":
        import subprocess

        # `whoami` names LocalSystem `nt authority\system` and a virtual
        # service account `nt service\<name>`, which is the distinction
        # the run asserts; the API calls name LocalSystem after the machine.
        system = os.environ.get("SystemRoot", r"C:\Windows")
        try:
            out = subprocess.run(
                [os.path.join(system, "System32", "whoami.exe")],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return out.stdout.strip() or "?"
        except OSError:
            return os.environ.get("USERNAME", "?")
    import pwd

    uid = os.getuid()
    try:
        return f"{pwd.getpwuid(uid).pw_name} (uid {uid})"
    except KeyError:
        return f"uid {uid}"


def _readable(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def _credentials() -> list[str] | None:
    """Target names of this account's stored credentials that mention
    Eugene -- what an app could read from the keyring. Windows only."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = ctypes.windll.advapi32
    count = wintypes.DWORD()
    found = ctypes.POINTER(ctypes.POINTER(_Credential))()
    if not advapi.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(found)):
        return []  # ERROR_NOT_FOUND: this account has none
    try:
        names = [found[i].contents.TargetName or "" for i in range(count.value)]
    finally:
        advapi.CredFree(found)
    return sorted(n for n in names if "eugene" in n.lower())


def _probe(root: str) -> dict:
    readable: list[str] = []
    unlistable: list[str] = []
    walked = 0
    base = Path(root) if root else None
    if base is not None and base.is_dir():
        for directory, dirnames, filenames in os.walk(
            base, onerror=lambda e: unlistable.append(str(e.filename))
        ):
            for name in filenames:
                walked += 1
                if walked > _PROBE_LIMIT:
                    break
                path = os.path.join(directory, name)
                if not os.path.islink(path) and _readable(path):
                    readable.append(os.path.relpath(path, base).replace(os.sep, "/"))
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(directory, d))]
    return {
        "user": _whoami(),
        "root": root,
        "rootListable": bool(base is not None and _listable(base)),
        "readable": sorted(readable),
        "unlistable": sorted(
            os.path.relpath(p, base).replace(os.sep, "/") if base else p for p in unlistable
        ),
        "walkedFiles": walked,
        "truncated": walked > _PROBE_LIMIT,
        "credentials": _credentials(),
        "keyFileReadable": _readable(os.environ.get("EUGENE_PLEXUS_APP_KEY_FILE") or "\0"),
    }


def _listable(path: Path) -> bool:
    try:
        next(iter(os.scandir(path)), None)
        return True
    except OSError:
        return False


def main() -> None:
    host = os.environ.get("EUGENE_PLEXUS_APP_BIND_HOST", "127.0.0.1")
    port = int(os.environ["EUGENE_PLEXUS_APP_BIND_PORT"])
    print(f"fixture app on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


if __name__ == "__main__":
    main()
