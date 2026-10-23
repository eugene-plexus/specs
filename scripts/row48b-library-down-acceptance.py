"""48b: real control, agent, Library and gateway; a stand-in engine/driver.

All state lives under .codex-tmp, all listeners use free ports, and no
ambient install variables reach a process. Unit tests inject the gateway
clock past 400 seconds; this process test uses profileCacheSeconds: 1.
"""

from __future__ import annotations

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import yaml


def isolated_env(root: Path, source=None):
    env = {k: v for k, v in (os.environ if source is None else source).items()
           if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(TEMP=str(root), TMP=str(root), TMPDIR=str(root),
               PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring", PYTHONUNBUFFERED="1")
    return env


def free_ports(count: int):
    sockets = []
    try:
        while len(sockets) < count:
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            if sock.getsockname()[1] in range(8079, 8084):
                sock.close()
            else:
                sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def wait(read, label, seconds=40):
    deadline = time.perf_counter() + seconds
    last = None
    while time.perf_counter() < deadline:
        try:
            if answer := read():
                return answer
        except (httpx.HTTPError, OSError, KeyError, ValueError, IndexError) as exc:
            last = exc
        time.sleep(0.1)
    raise AssertionError(f"Timed out: {label}: {last}")


def child_settings(root: Path, kind: str, agent_url: str):
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust
    identity = NodeIdentityStore(root / "node.yaml")
    identity.load()
    trust = NodeTrust(identity, root / BUNDLE_FILE)
    trust.load()
    token, _ = trust.mint_service(sub=kind, audience=trust.recipient)
    result = dict(trust_bundle_file=str(trust.bundle_path), trust_authority=trust.authority,
                  auth_recipient=trust.recipient, service_token=token)
    if kind == "gateway":
        result["agent_url"] = agent_url
    return result


def serve(kind: str, root: Path, port: int, model: str | None):
    assert port not in range(8079, 8084)
    if kind == "engine":
        # Keep the same open local file for this process's lifetime.
        assert model is not None
        with open(model, "rb") as weights:
            assert weights.read(4) == b"GGUF"
            class Engine(BaseHTTPRequestHandler):
                def log_message(self, *_): pass
                def reply(self, body):
                    data = json.dumps(body).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                def do_GET(self):
                    self.reply({"n_ctx": 128, "total_slots": 1} if self.path == "/props"
                               else {"status": "ok"})
                def do_POST(self):
                    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    with (root / "requests.jsonl").open("a", encoding="utf-8") as out:
                        out.write(json.dumps(request) + "\n")
                    self.reply({"content": "still serving", "modelId": "fixture",
                                "backend": "openai_compat_http", "finishReason": "stop"})
            ThreadingHTTPServer(("127.0.0.1", port), Engine).serve_forever()
        return

    import uvicorn
    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings
        app = create_app(Settings(config_file=root / "control.yaml", state_dir=root / "control-state"))
    elif kind == "agent":
        from eugene_plexus_agent._generated.models import EngineKind, Origin
        from eugene_plexus_agent.engines import ADAPTERS
        from eugene_plexus_agent.engines.base import DiscoveredBinary
        from eugene_plexus_agent.engines.llama_cpp import LlamaCppAdapter
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings
        class StandIn(LlamaCppAdapter):
            def discover(self, *, configured=None):
                return DiscoveredBinary(Path(sys.executable), Origin.configured, "fixture")
            def build_argv(self, spec, binary, port):
                return [sys.executable, str(Path(__file__).resolve()), "--serve", "engine",
                        "--directory", str(root), "--port", str(port), "--model", spec.modelPath]
        ADAPTERS[EngineKind.llama_cpp] = StandIn()
        os.environ["EUGENE_PLEXUS_AGENT_ENGINE_ROOT"] = str(root / "engines")
        app = create_app(settings=Settings(config_file=root / "agent.yaml", bind_port=port,
                                          machine_port=free_ports(1)[0], default_topology=False))
    elif kind == "library":
        from eugene_plexus_library.app import create_app
        from eugene_plexus_library.settings import Settings
        child = json.loads((root / "library-child.json").read_text(encoding="utf-8"))
        app = create_app(Settings(config_file=root / "library.yaml", state_file=root / "library-state.json", **child))
    else:
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings
        child = json.loads((root / "gateway-child.json").read_text(encoding="utf-8"))
        app = create_app(Settings(config_file=root / "gateway.yaml", metrics_file=root / "metrics.sqlite3", **child))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="warning"))
    async def run():
        task = asyncio.create_task(server.serve())
        while not task.done() and not (root / f"{kind}.stop").exists():
            await asyncio.sleep(0.1)
        server.should_exit = True
        await task
    asyncio.run(run())


def write_model(path: Path):
    def string(value):
        data = value.encode()
        return struct.pack("<Q", len(data)) + data
    kv = {"general.architecture": "llama", "general.name": "fixture", "llama.context_length": 128}
    data = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv))
    for key, value in kv.items():
        data += string(key)
        data += struct.pack("<I", 8) + string(value) if isinstance(value, str) else struct.pack("<II", 4, value)
    path.write_bytes(data)


def exercise(root: Path):
    control_port, agent_port, library_port, gateway_port, engine_port, driver_port = free_ports(6)
    urls = {name: f"http://127.0.0.1:{port}" for name, port in (
        ("control", control_port), ("agent", agent_port), ("library", library_port),
        ("gateway", gateway_port), ("engine", engine_port))}
    share = root / "share"
    share.mkdir()
    drive = None
    if os.name == "nt":
        for letter in "ZYXWVUTSRQPONMLKJIHGFED":
            if not Path(f"{letter}:/").exists():
                assigned = subprocess.run(["subst", f"{letter}:", str(share)], capture_output=True)
                if assigned.returncode == 0:
                    drive = f"{letter}:"
                    break
        assert drive, "No free subst drive for the disposable share"
    folder = Path(drive + "\\") if drive else share
    model = folder / "fixture.gguf"
    write_model(model)
    (root / "agent.yaml").write_text(yaml.safe_dump({
        "firstRunComplete": True, "updateChecks": False, "advertiseUrl": urls["agent"],
        "securityMode": "prompt_on_startup", "modelCopyEnabled": True,
        "modelCopyDir": str(root / "copies"), "modelCopyMinFreeGb": 0,
        "components": [{"name": name, "kind": kind, "url": url} for name, kind, url in (
            ("library", "library", urls["library"]), ("gateway", "gateway", urls["gateway"]),
            ("driver", "inference-driver", f"http://127.0.0.1:{driver_port}"))],
        "runtimes": []}), encoding="utf-8")
    (root / "library.yaml").write_text(yaml.safe_dump({"modelRoots": [str(folder)], "scanOnStartup": True}), encoding="utf-8")
    (root / "gateway.yaml").write_text(yaml.safe_dump({"profileCacheSeconds": 1, "routingRefreshSeconds": 1,
        "metricsEnabled": False, "idleCheckSeconds": 3600}), encoding="utf-8")
    (root / "control.yaml").write_text("{}\n", encoding="utf-8")

    class Driver(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def reply(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self.reply({"backend": "openai_compat_http", "runtime": "fixture", "models": [
                {"id": "fixture", "surfaces": ["chat"], "capabilities": {"supportedSettings": ["temperature", "maxTokens", "topP"]}}]})
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            response = httpx.post(urls["engine"] + "/generate", content=data, trust_env=False)
            response.raise_for_status()
            self.reply(response.json())
    driver = ThreadingHTTPServer(("127.0.0.1", driver_port), Driver)
    threading.Thread(target=driver.serve_forever, daemon=True).start()
    processes = {}
    logs = []
    client = httpx.Client(timeout=20, trust_env=False)
    def call(name, method, path, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, urls[name] + path, headers=headers, **kwargs)
    def start(kind, port):
        (root / f"{kind}.stop").unlink(missing_ok=True)
        log = (root / f"{kind}.log").open("ab")
        logs.append(log)
        processes[kind] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", kind,
            "--directory", str(root), "--port", str(port)], cwd=root, env=isolated_env(root),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        wait(lambda: call(kind, "GET", "/healthz").status_code == 200, f"{kind} ready")
    def stop(kind):
        (root / f"{kind}.stop").touch()
        processes[kind].wait(timeout=25)
    try:
        start("control", control_port)
        passphrase = secrets.token_urlsafe(24)
        response = call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        assert response.status_code == 204, response.text
        root_token = call("control", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        start("agent", agent_port)
        token = call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).json()["sessionToken"]
        join = call("control", "POST", "/v1/nodes/join-token", root_token, json={"grants": ["gateway"]}).json()["token"]
        enrolled = call("agent", "POST", "/v1/node/enroll", token, json={"controlUrl": urls["control"], "token": join, "name": "fixture-node"})
        assert enrolled.status_code == 200, enrolled.text
        token = call("agent", "POST", "/v1/auth/login", json={"passphrase": passphrase}).json()["sessionToken"]
        for kind, port in (("library", library_port), ("gateway", gateway_port)):
            (root / f"{kind}-child.json").write_text(json.dumps(child_settings(root, kind, urls["agent"])), encoding="utf-8")
            start(kind, port)
        listed = wait(lambda: call("library", "GET", "/v1/models", token).json().get("models"), "model scanned")
        model_id = listed[0]["id"]
        profile = call("library", "POST", f"/v1/models/{model_id}/profiles", token,
                       json={"name": "tuned", "engine": "llama_cpp", "default": True, "temperature": 0.23})
        assert profile.status_code in (200, 201), profile.text
        created = call("agent", "POST", "/v1/runtimes", token, json={"name": "fixture", "engine": "llama_cpp",
            "modelPath": str(model), "modelAlias": "fixture", "port": engine_port, "autoDriver": False,
            "flags": {"gpuLayers": 0, "contextSize": 128}})
        assert created.status_code in (200, 201), created.text
        def runtime():
            return call("agent", "GET", "/v1/runtimes/fixture", token).json()
        def ready():
            view = runtime()
            return view if view.get("status") == "ready" else None
        view = wait(ready, "engine ready from copy")
        assert view["localPathSource"] == "copy" and not view.get("localPathNote"), view
        def chat():
            return call("gateway", "POST", "/v1/chat/completions", token,
                        json={"model": "fixture", "messages": [{"role": "user", "content": "hello"}]})
        def tuned_chat():
            response = chat()
            request = json.loads((root / "requests.jsonl").read_text(encoding="utf-8").splitlines()[-1]) if response.status_code == 200 else {}
            return response.status_code == 200 and request.get("temperature") == 0.23
        wait(tuned_chat, "routing observes the runtime and chat uses its tuned profile")
        stop("library")
        if drive:
            subprocess.run(["subst", drive, "/D"], check=True)
        else:
            share.rename(root / "offline")
        time.sleep(1.1)
        response = chat()
        assert response.status_code == 200, response.text
        assert json.loads((root / "requests.jsonl").read_text(encoding="utf-8").splitlines()[-1])["temperature"] == 0.23
        info = call("gateway", "GET", "/v1/info", token).json()["library"]
        assert info["reachable"] is False and info["modelsOnSavedSettings"] == 1, info
        response = call("agent", "GET", "/api/proxy/library/v1/models", token)
        assert response.status_code == 502 and "Running models keep serving" in response.json()["detail"]["detail"], response.text
        print("PASS Library stopped: chat keeps the profile temperature and the console proxy explains what works", flush=True)
        response = call("agent", "POST", "/v1/runtimes/fixture/stop", token, json={})
        assert response.status_code in (200, 202), response.text
        response = call("agent", "POST", "/v1/runtimes/fixture/start", token, json={})
        assert response.status_code in (200, 202), response.text
        view = wait(ready, "restart with source folder unreachable")
        assert view["localPathSource"] == "copy" and view["localPathNote"].startswith("Started from this machine's copy."), view
        assert str(folder) in view["localPathNote"], view
        print("PASS Source folder unavailable: the actual runtime restarts from its recorded copy with the note", flush=True)
        if drive:
            subprocess.run(["subst", drive, str(share)], check=True)
        else:
            (root / "offline").rename(share)
        start("library", library_port)
        call("agent", "POST", "/v1/runtimes/fixture/stop", token, json={}).raise_for_status()
        call("agent", "POST", "/v1/runtimes/fixture/start", token, json={}).raise_for_status()
        view = wait(ready, "checked restart after recovery")
        assert view.get("localPathNote") is None, view
        print("PASS Library and source restored: the next checked start clears the note", flush=True)
    except BaseException:
        for log in logs:
            log.flush()
        for path in root.glob("*.log"):
            print(f"{path.name}:\n{path.read_text(encoding='utf-8', errors='replace')[-5000:]}", flush=True)
        raise
    finally:
        for kind in reversed(list(processes)):
            if processes[kind].poll() is None:
                try:
                    stop(kind)
                except (subprocess.TimeoutExpired, OSError):
                    processes[kind].kill()
                    processes[kind].wait(timeout=10)
        driver.shutdown()
        driver.server_close()
        client.close()
        for log in logs:
            log.close()
        if drive:
            subprocess.run(["subst", drive, "/D"], capture_output=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["control", "agent", "library", "gateway", "engine"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--model")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.model)
    else:
        temporary = Path(__file__).resolve().parents[2] / ".codex-tmp"
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="row48b-", dir=temporary) as directory:
            exercise(Path(directory).resolve())


if __name__ == "__main__":
    main()
