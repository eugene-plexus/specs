"""Real control authorization -> outbound agent relay -> installed site host,
on an ordinary LAN node (Job Sites J6, J6d, J6g).

The site host is installed from the sibling `site-host` checkout the way the
agent installs it (`EUGENE_PLEXUS_AGENT_SITE_HOST_SOURCE`) and started in node
mode with the environment the agent's relay builds. The relay is the agent's
real `SiteHostRelay`; control is the real root, in process. Workbench is
played by a client with its credentials, sending MCP 2026-07-28 requests to
`/oidc/sites/mcp`; on a node the person's grants travel with each call and
the host checks the folder it names against them.

Run with control's development dependencies, agent's runtime dependencies, uv,
and sibling control, agent, site-host and Workbench checkouts. Everything uses
temporary files and random loopback ports. This proves packaging, transport
and held-handle IO; C1's disposable-runner acceptance owns the separate
Windows service/Linux DynamicUser account boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPOS = Path(__file__).resolve().parents[2]
for repo in ("control", "agent"):
    sys.path.insert(0, str(REPOS / repo / "src"))
sys.path.insert(0, str(REPOS / "control"))
# Do not inherit a developer's installed Eugene settings.
for name in list(os.environ):
    if name.startswith("EUGENE_PLEXUS_"):
        os.environ.pop(name)

import httpx
from eugene_plexus_agent import site_host
from eugene_plexus_agent._generated.models import ComponentStatus
from eugene_plexus_agent.apps import AppStore, venv_python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eugene_plexus_control import applied, keyring_store, node_helpers
from eugene_plexus_control.app import create_app
from tests.conftest import PASSPHRASE, enroll, login, settings_for
from tests.test_oidc import CALLBACK, _tokens


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


async def check(root: Path) -> None:
    keyring_store._probe_done, keyring_store._probe_result = True, False
    node_helpers.POLL_SECONDS = 0.1
    folder = root / "shared"
    folder.mkdir()
    file = folder / "note.txt"
    file.write_text("Private desktop notes", encoding="utf-8")
    # Catch drift between the two consumers of the audited C6 file operations.
    for name in ("folder_io.py", "folder_linux.py", "folder_windows.py"):
        original = REPOS / "workbench/src/eugene_plexus_workbench" / name
        copy = REPOS / "site-host/src/eugene_plexus_site_host" / name
        # The repositories have different Git EOL settings on Windows.
        # Compare source text with only newline normalization, not checkout bytes.
        assert original.read_text(encoding="utf-8") == copy.read_text(encoding="utf-8"), (
            f"C6 code drift: {name}"
        )
    os.environ[site_host.SOURCE_OVERRIDE] = str(REPOS / "site-host")
    where, version = site_host.source()
    uv = shutil.which("uv") or str(
        Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    )
    environment = root / "site-host-env"
    await asyncio.to_thread(
        subprocess.run,
        [uv, "venv", "--python", "3.12", str(environment)],
        check=True,
        capture_output=True,
    )
    python = venv_python(environment)
    await asyncio.to_thread(
        subprocess.run,
        [uv, "pip", "install", "--python", str(python), where],
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    node_dir = root / "node"
    node_dir.mkdir()
    data = node_dir / "apps" / site_host.HELPER_ID / "data"
    data.mkdir(parents=True)
    local_token = "temporary-host-credential-for-acceptance"
    kind = "windows_service" if os.name == "nt" else "systemd"
    app = FastAPI()
    app.state.settings = SimpleNamespace(config_file=node_dir / "agent.yaml")
    installed = SimpleNamespace(
        enabled=True, port=port, version=version, manifest=SimpleNamespace(entry=site_host.ENTRY)
    )
    app.state.apps = SimpleNamespace(
        accounts=SimpleNamespace(available=True, kind=kind),
        store=SimpleNamespace(
            get=lambda _: installed, app_dir=AppStore(node_dir / "apps.yaml").app_dir
        ),
        supervisor=SimpleNamespace(
            status=lambda _: (ComponentStatus.running, None, None, None, None),
            admin_token=lambda _: local_token,
        ),
        installer=SimpleNamespace(snapshot=lambda _: None),
    )
    with TestClient(create_app(settings_for(root / "control"))) as client:
        assert client.post("/v1/auth/initialize", json={"passphrase": PASSPHRASE}).status_code == 204
        client.headers["Authorization"] = "Bearer " + login(client)
        keys, result = enroll(client, "desktop")
        assert result.status_code == 201
        assert client.put("/v1/node-helpers/desktop", json={"enabled": True}).status_code == 200
        app.state.node_identity = SimpleNamespace(
            record=SimpleNamespace(
                enrolled=True,
                name="desktop",
                signing_public_key=keys.signing_public,
                control_url="http://control",
                job_site=None,
                site_owner=None,
            )
        )
        app.state.auth_state = SimpleNamespace(
            trust=SimpleNamespace(agent_token=lambda _: keys.service_token())
        )
        relay = site_host.SiteHostRelay(app)
        env = relay.environment(app.state.apps)
        assert env is not None and env["SITE_HOST_MODE"] == "node"
        process = await asyncio.to_thread(
            subprocess.Popen,
            [str(python), "-m", site_host.ENTRY],
            cwd=data,
            env={
                **os.environ,
                **env,
                "EUGENE_PLEXUS_APP_DATA_DIR": str(data),
                "EUGENE_PLEXUS_APP_BIND_PORT": str(port),
                "EUGENE_PLEXUS_APP_ADMIN_TOKEN": local_token,
                "EUGENE_PLEXUS_APP_ACCOUNT_KIND": kind,
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=1) as http:
                deadline = time.perf_counter() + 20
                while True:
                    try:
                        if (await http.get(f"http://127.0.0.1:{port}/healthz")).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None or time.perf_counter() > deadline:
                        raise RuntimeError("The site host did not start")
                    await asyncio.sleep(0.05)

            async def transport(request: httpx.Request) -> httpx.Response:
                response = await asyncio.to_thread(
                    client.request,
                    request.method,
                    request.url.path,
                    headers=dict(request.headers),
                    content=request.content,
                )
                return httpx.Response(
                    response.status_code, content=response.content, headers=response.headers
                )

            async def started(_config: dict[str, Any]) -> None:
                pass  # The real host was started above; C1 checks the service launcher.

            relay.reconcile = started  # type: ignore[method-assign]
            relay._root = "http://control"
            relay._root_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
            task = asyncio.create_task(relay.run())
            try:
                deadline = time.perf_counter() + 10
                while not getattr(
                    getattr(client.app.state, "node_helper_broker", None), "reports", None
                ):
                    if time.perf_counter() > deadline:
                        raise RuntimeError("The agent did not poll")
                    await asyncio.sleep(0.02)
                registered = await asyncio.to_thread(
                    client.post,
                    "/v1/node-helpers/desktop/folders",
                    json={"name": "Notes", "path": str(folder), "writable": True},
                )
                assert registered.status_code == 201, registered.text
                grant = registered.json()
                taken = await asyncio.to_thread(
                    client.post,
                    "/v1/node-helpers/desktop/folders",
                    json={"name": "notes", "path": str(folder)},
                )
                assert taken.status_code == 409, taken.text
                private = await asyncio.to_thread(
                    client.post,
                    "/v1/node-helpers/desktop/folders",
                    json={"name": "Private", "path": str(node_dir)},
                )
                assert private.status_code == 400, private.text
                wb = client.post(
                    "/v1/oidc/clients",
                    json={
                        "name": "Workbench",
                        "owner": "app:workbench@server",
                        "redirectUris": [CALLBACK],
                    },
                ).json()
                created = client.post(
                    "/v1/people",
                    json={
                        "name": "ada",
                        "password": PASSPHRASE,
                        "apps": [wb["client"]["clientId"]],
                        "helperGrants": [{"folderId": grant["id"], "writable": True}],
                    },
                ).json()
                tokens = _tokens(client, wb, name="ada")
                auth = (wb["client"]["clientId"], wb["clientSecret"])

                async def mcp(request: dict[str, Any]) -> httpx.Response:
                    return await asyncio.to_thread(
                        client.post,
                        "/oidc/sites/mcp",
                        auth=auth,
                        json={
                            "refreshToken": tokens["refresh_token"],
                            "node": "desktop",
                            "server": "files",
                            "request": request,
                        },
                    )

                def result(answer: httpx.Response) -> dict[str, Any]:
                    assert answer.status_code == 200, answer.text
                    body = answer.json()
                    assert body["status"] == "done" and body["jobSite"] is False, body
                    value: dict[str, Any] = body["response"]["result"]
                    return value

                listed = result(await mcp(rpc("tools/list")))
                enums = {
                    t["name"]: t["inputSchema"]["properties"]["folder"]["enum"]
                    for t in listed["tools"]
                }
                assert enums == {
                    "list_directory": ["Notes"],
                    "read_text": ["Notes"],
                    "write_text": ["Notes"],
                }, enums

                def call(tool: str, **arguments: Any) -> dict[str, Any]:
                    return rpc(
                        "tools/call", {"name": tool, "arguments": {"folder": "Notes", **arguments}}
                    )

                read = result(await mcp(call("read_text", path="note.txt")))
                assert read["isError"] is False
                assert read["structuredContent"]["text"] == "Private desktop notes", read
                digest = read["structuredContent"]["sha256"]
                written = result(
                    await mcp(
                        call(
                            "write_text",
                            path="note.txt",
                            text="Updated by Ada",
                            expectedSha256=digest,
                        )
                    )
                )
                assert written["isError"] is False, written
                assert file.read_text(encoding="utf-8") == "Updated by Ada"
                outside = result(await mcp(call("read_text", path="../control/control.yaml")))
                assert outside["isError"] is True, outside
                elsewhere = await mcp(
                    rpc("tools/call", {"name": "read_text",
                                       "arguments": {"folder": "Other", "path": "x"}})
                )
                assert elsewhere.status_code == 403, elsewhere.text
                client.patch(f"/v1/people/{created['id']}", json={"helperGrants": []})
                assert (await mcp(call("read_text", path="note.txt"))).status_code == 403
                assert b"Updated by Ada" not in applied.canonical_bytes(
                    client.app.state.machine.state
                )
                print(
                    "PASS: installed site host, outbound polling, real sign-in and grants, "
                    "one file server whose folder argument names the person's grants, "
                    "read/edit, containment, revocation, no file content in replicated state"
                )
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr:
                process.stderr.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="eugene-node-files-") as temporary:
        target = Path(temporary).resolve()
        assert target.is_relative_to(Path(tempfile.gettempdir()).resolve())
        asyncio.run(check(target))
