#!/usr/bin/env python3
"""Linux MV5b acceptance. CI only: installs the catalogue package, with stub models.

Run from the sibling repository root with the candidate agent and Workbench installed.
All state, managed Python, logs and traces stay under --output in .codex-tmp/.
The package is real; inference quality is deliberately outside this acceptance.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def check_network(trace: str) -> int:
    addresses = re.findall(r'inet_addr\("([^"]+)"\)|inet_pton\(AF_INET6, "([^"]+)"', trace)
    assert addresses, "No network syscall evidence was collected"
    for ipv4, ipv6 in addresses:
        address = ipaddress.ip_address(ipv4 or ipv6)
        assert address.is_loopback, f"Connection or bind off loopback: {address}"
    return len(addresses)


def extraction(body: dict[str, Any]) -> str:
    text = json.dumps(body.get("messages", []))
    markers = [m for m in ("MV5B_ADA", "MV5B_BOB") if m in text]
    return json.dumps({"facts": [{
        "what": f"The person prefers {marker}.", "when": "N/A", "where": "N/A",
        "who": "The person", "why": "N/A", "fact_type": "world", "entities": [],
    } for marker in markers]})


class Gateway(BaseHTTPRequestHandler):
    """A deterministic OpenAI/Cohere fixture, with authenticated model discovery."""

    key = "acceptance-client-key"
    calls: list[str] = []

    def log_message(self, *_args: Any) -> None:
        pass

    def answer(self, value: Any, code: int = 200) -> None:
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def allowed(self) -> bool:
        if self.headers.get("authorization") == f"Bearer {self.key}":
            self.calls.append(self.path)
            return True
        self.answer({"error": {"message": "invalid client key"}}, 401)
        return False

    def do_GET(self) -> None:
        if self.allowed():
            self.answer({"data": [{"id": ident, "object": "model", "x_eugene_plexus": {
                "locality": "local", "surfaces": [surface], "ready_backends": 1,
            }} for ident, surface in [("owner-choice", "chat"), ("embed", "embeddings"),
                                      ("rerank", "rerank")]]})

    def do_POST(self) -> None:
        if not self.allowed():
            return
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if self.path.endswith("/embeddings"):
            inputs = body.get("input", [])
            if not isinstance(inputs, list):
                inputs = [inputs]
            self.answer({"object": "list", "model": "embed", "data": [
                {"index": i, "object": "embedding", "embedding": [1.0] + [0.0] * 383}
                for i in range(len(inputs))]})
        elif self.path.endswith("/rerank"):
            self.answer({"results": [{"index": i, "relevance_score": 1.0 / (i + 1)}
                                     for i in range(len(body.get("documents", [])))]})
        else:
            self.answer({"id": "fixture", "model": body.get("model"), "object": "chat.completion",
                         "choices": [{"index": 0, "finish_reason": "stop", "message": {
                             "role": "assistant", "content": extraction(body)}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


async def wait_ready(manager: Any, record: Any) -> None:
    import httpx

    deadline = time.perf_counter() + 120
    async with httpx.AsyncClient(trust_env=False) as client:
        while time.perf_counter() < deadline:
            try:
                if (await client.get(f"http://127.0.0.1:{record.port}/health")).is_success:
                    return
            except httpx.HTTPError:
                pass
            error = manager.view(record).lastError
            assert not error, error
            await asyncio.sleep(0.2)
    raise AssertionError(f"Hindsight did not become healthy: {manager.view(record)}")


async def acceptance(output: Path) -> dict[str, Any]:
    import httpx
    import psutil

    from eugene_plexus_agent import app_accounts, app_launcher, apps
    from eugene_plexus_agent._generated.models import AppOrigin, AppSettingsUpdate
    from eugene_plexus_agent._private_files import write_private
    from eugene_plexus_workbench.memory_servers import Servers, clear
    from eugene_plexus_workbench.settings import Settings
    from eugene_plexus_workbench.store import Store

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{gateway.server_port}"
    async def resolve() -> tuple[str, None]:
        return url, None
    catalogue = apps.load_catalogue()
    store = apps.AppStore(output / "apps.yaml")
    manager = apps.AppManager(store=store, catalogue=catalogue, get_config=lambda _: None,
        bind_host=lambda: "0.0.0.0", advertise_host=lambda: None, node_name=lambda: "ci",
        resolve_gateway=resolve, accounts=app_accounts.AccountSupport(None, "CI agent account"))
    hs = next(m for m in catalogue if m.id == "hindsight")
    wb = Store(output / "workbench.sqlite3")
    await wb.open()
    await wb.put_setting("memoryEnabled", True)
    trace_dir = output / "network"
    trace_dir.mkdir()
    original_argv = apps.entry_argv
    def traced(python: Path, manifest: Any) -> list[str]:
        command = original_argv(python, manifest)
        if manifest.id != "hindsight":
            return command
        return ["strace", "-ff", "-e", "trace=connect,bind", "-o", str(trace_dir / "trace"), *command]
    # Trace every connect/bind from Hindsight and its detached postgres too. Never payloads.
    apps.entry_argv = traced
    cleanup = app_launcher.pg0_cleanup
    actions: list[str] = []
    def recorded(python: str, action: str, env: dict[str, str]) -> None:
        actions.append(action)
        cleanup(python, action, env)
    app_launcher.pg0_cleanup = recorded
    try:
        write_private(store.key_file(hs.id), Gateway.key)
        manager.installer.start(hs, store=store, uv=manager.uv(),
                                on_installed=lambda m: manager.installed_callback(m, AppOrigin.catalogue))
        outcome = await manager.installer.wait(hs.id)
        assert outcome is not None and outcome.state.value == "done", outcome
        record = store.get(hs.id)
        assert record is not None and record.settings.memoryModel is None
        assert not manager.supervisor.is_running(hs.id)
        assert manager.view(record).detail == apps.CHOOSE_MEMORY_MODEL
        python = apps.venv_python(store.version_dir(record.id, record.version) / "venv")
        packages = subprocess.check_output([str(python), "-c",
            "import importlib.metadata as m,json;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"], text=True)
        installed = json.loads(packages)
        assert installed["hindsight-api-slim"] == "1.0.0" and "torch" not in installed
        await manager.update_settings(record, AppSettingsUpdate(memoryModel="owner-choice"))
        await wait_ready(manager, record)
        base = f"http://127.0.0.1:{record.port}"
        rest = (store.data_dir(hs.id) / app_launcher.APP_SECRET_FILE).read_text().strip()
        token = store.link_secret_file(hs.id).read_text().strip()
        assert rest != token
        # REST and MCP have independent credentials: neither substitutes for the other.
        async with httpx.AsyncClient(trust_env=False) as client:
            for key in (None, "wrong", token):
                response = await client.post(base + "/v1/default/banks/check/memories/recall",
                    json={"query": "check"}, headers={"Authorization": f"Bearer {key}"} if key else {})
                assert response.status_code in (401, 403), response.status_code
            response = await client.post(base + "/v1/default/banks/check/memories/recall",
                json={"query": "check"}, headers={"Authorization": f"Bearer {rest}"})
            assert response.status_code in (200, 404), response.text
            for key in (None, "wrong", rest):
                response = await client.post(base + "/mcp/check/", json={"jsonrpc": "2.0", "id": 1,
                    "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "acceptance", "version": "1"}}}, headers={
                    "Accept": "application/json, text/event-stream", **({"Authorization": f"Bearer {key}"} if key else {})})
                assert response.status_code in (401, 403), response.status_code
        consumer = apps.InstalledApp(manifest=next(m for m in catalogue if m.id == "workbench"),
            origin=AppOrigin.catalogue, port=manager.allocate_port(), installed_at=record.installed_at)
        link = manager.memory_link(consumer)
        assert token not in json.dumps(link)
        assert stat.S_IMODE(store.link_secret_file(hs.id).stat().st_mode) == 0o600
        third = apps.InstalledApp(manifest=next(m for m in catalogue if m.id == "open-webui"),
            origin=AppOrigin.catalogue, port=manager.allocate_port(), installed_at=record.installed_at)
        assert manager.memory_link(third) == {}
        settings = Settings(memory_server_url=link["EUGENE_PLEXUS_APP_MEMORY_SERVER_URL"],
            memory_server_token_file=Path(link["EUGENE_PLEXUS_APP_MEMORY_SERVER_TOKEN_FILE"]),
            memory_server_model_file=Path(link["EUGENE_PLEXUS_APP_MEMORY_SERVER_MODEL_FILE"]))
        servers = Servers(wb, settings)
        rows = []
        for person, marker in (("ada", "MV5B_ADA"), ("bob", "MV5B_BOB")):
            bank_url = servers.linked_url(person)
            name, verbs = await servers.discover(bank_url, servers.link_token(), "linked")
            assert verbs["retain"]["tool"] == "sync_retain"
            await wb.put_memory_server(person, bank_url, "", name, verbs, linked=True)
            row = await wb.memory_server(person)
            assert row["token"] == "" and token not in json.dumps(row)
            await servers.call(row, "outside", "retain", {"content": f"I prefer {marker}.",
                               "document_id": person}, seconds=120)
            rows.append(row)
        for row, own, other in ((rows[0], "MV5B_ADA", "MV5B_BOB"), (rows[1], "MV5B_BOB", "MV5B_ADA")):
            memories = await servers.call(row, "outside", "recall", {"query": "What do I prefer?", "max_tokens": 1000})
            text = " ".join(item.text for item in memories)
            assert own in text and other not in text, (own, text)
        state = SimpleNamespace(store=wb, memory_servers=servers)
        cleared = await clear(state, "ada")
        assert cleared and cleared["cleared"] and cleared["left"] == 0, cleared
        assert not await servers.call(rows[0], "outside", "list", {"limit": 100})
        assert await servers.call(rows[1], "outside", "list", {"limit": 100})
        instance = store.data_dir(hs.id) / ".pg0/instances/hindsight/instance.json"
        info = json.loads(instance.read_text())
        assert Path(info["data_dir"]).resolve().is_relative_to(store.data_dir(hs.id).resolve())
        assert info["port"] == record.aux_port != record.port
        postgres_pid = info["pid"]
        await manager.stop(hs.id)
        assert not psutil.pid_exists(postgres_pid), "Named postgres survived Stop"
        await manager.start(record)
        await wait_ready(manager, record)
        # Kill Hindsight alone; pg_ctl's postgres can outlive it. Restart must clean it first.
        pid = manager.supervisor.status(hs.id)[3]
        assert pid is not None
        children = psutil.Process(pid).children(recursive=True)
        child = next(p for p in children if p.name().startswith("python"))
        child.kill()
        await manager.restart(record)
        await wait_ready(manager, record)
        assert await servers.call(rows[1], "outside", "list", {"limit": 100}), "Hard kill lost Bob's bank"
        await manager.aclose()
        info = json.loads(instance.read_text())
        assert not psutil.pid_exists(info["pid"]), "Postgres survived agent shutdown"
        await manager.uninstall(hs.id, purge=True)
        assert actions[-2:] == ["stop", "drop"]
        assert not store.app_dir(hs.id).exists(), "Purge left app data or credentials"
        trace = "\n".join(p.read_text(errors="replace") for p in trace_dir.glob("trace*"))
        sockets = check_network(trace)
        assert any(p.endswith("/chat/completions") for p in Gateway.calls)
        assert any(p.endswith("/embeddings") for p in Gateway.calls)
        assert any(p.endswith("/rerank") for p in Gateway.calls)
        return {"passed": True, "package": "hindsight-api-slim[embedded-db]==1.0.0",
            "checks": ["explicit-model", "REST-auth", "MCP-auth", "bank-isolation", "bank-purge",
                       "private-link", "contained-pg0-data", "named-stop", "named-drop", "hard-kill-recovery",
                       "agent-shutdown", "complete-purge", "loopback-only"],
            "network_syscalls": sockets, "cleanup": actions}
    finally:
        try:
            if store.get(hs.id):
                await manager.uninstall(hs.id, purge=True)
        finally:
            await manager.aclose()
            await wb.close()
            apps.entry_argv = original_argv
            app_launcher.pg0_cleanup = cleanup
            gateway.shutdown()
            gateway.server_close()
            thread.join(5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".codex-tmp/mv5b-hindsight"))
    args = parser.parse_args()
    assert sys.platform == "linux", "This acceptance is Linux-only"
    assert shutil.which("strace"), "strace is required for network evidence"
    output = args.output.resolve()
    assert ".codex-tmp" in output.parts, "Acceptance state belongs under .codex-tmp/"
    assert not output.exists(), "Use a fresh acceptance output directory"
    output.mkdir(parents=True)
    for key in list(os.environ):
        if key.startswith("EUGENE_PLEXUS_"):
            del os.environ[key]
    os.environ["TMPDIR"] = str(output)
    receipt: dict[str, Any] = {"passed": False}
    try:
        receipt = asyncio.run(acceptance(output))
    except BaseException as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
