"""Real control authorization -> outbound agent relay -> installed helper wheel.

Run with control's development dependencies, agent's runtime dependencies, uv,
and sibling control, agent and Workbench checkouts. Everything uses temporary
files and random loopback ports. This proves
packaging, transport and held-handle IO; C1's disposable-runner acceptance owns
the separate Windows service/Linux DynamicUser account boundary.
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

REPOS = Path(__file__).resolve().parents[2]
for repo in ("control", "agent"):
    sys.path.insert(0, str(REPOS / repo / "src"))
sys.path.insert(0, str(REPOS / "control"))
# Do not inherit a developer's installed Eugene settings.
for name in list(os.environ):
    if name.startswith("EUGENE_PLEXUS_"):
        os.environ.pop(name)

import httpx
from eugene_plexus_agent._generated.models import ComponentStatus
from eugene_plexus_agent.apps import AppStore, venv_python
from eugene_plexus_agent.node_file_helper import NodeFileHelper, manifest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eugene_plexus_control import applied, keyring_store, node_helpers
from eugene_plexus_control.app import create_app
from tests.conftest import PASSPHRASE, enroll, login, settings_for
from tests.test_oidc import CALLBACK, _tokens


async def check(root: Path) -> None:
    keyring_store._probe_done, keyring_store._probe_result = True, False
    node_helpers.POLL_SECONDS = 0.1
    folder = root / "shared"
    folder.mkdir()
    file = folder / "note.txt"
    file.write_text("Private desktop notes", encoding="utf-8")
    store = AppStore(root / "node" / "apps.yaml")
    package = manifest(SimpleNamespace(store=store), root / "control")
    wheel = Path(package.source)
    # Catch drift between the two consumers of the audited C6 file operations.
    for name in ("folder_io.py", "folder_linux.py", "folder_windows.py"):
        original = REPOS / "workbench/src/eugene_plexus_workbench" / name
        copy = REPOS / "agent/src/eugene_plexus_agent/_node_file_helper" / name
        assert original.read_bytes() == copy.read_bytes(), f"C6 code drift: {name}"
    uv = shutil.which("uv") or str(
        Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    )
    environment = root / "worker-env"
    await asyncio.to_thread(
        subprocess.run,
        [uv, "venv", "--python", sys.executable, str(environment)],
        check=True,
        capture_output=True,
    )
    python = venv_python(environment)
    await asyncio.to_thread(
        subprocess.run,
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    data = root / "worker-data"
    data.mkdir()
    local_token = "temporary-worker-credential-for-acceptance"
    env = {
        **os.environ,
        "EUGENE_PLEXUS_APP_DATA_DIR": str(data),
        "EUGENE_PLEXUS_APP_BIND_PORT": str(port),
        "EUGENE_PLEXUS_APP_ADMIN_TOKEN": local_token,
        "EUGENE_PLEXUS_APP_ACCOUNT_KIND": "windows_service" if os.name == "nt" else "systemd",
        "NODE_HELPER_PROTECTED_ROOTS": json.dumps([str(root / "control")]),
    }
    process = await asyncio.to_thread(
        subprocess.Popen,
        [str(python), "-m", package.entry],
        cwd=data,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=1) as http:
            deadline = time.perf_counter() + 10
            while True:
                try:
                    if (await http.get(f"http://127.0.0.1:{port}/healthz")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None or time.perf_counter() > deadline:
                    raise RuntimeError("Bundled worker did not start")
                await asyncio.sleep(0.05)
        with TestClient(create_app(settings_for(root / "control"))) as client:
            assert (
                client.post("/v1/auth/initialize", json={"passphrase": PASSPHRASE}).status_code
                == 204
            )
            client.headers["Authorization"] = "Bearer " + login(client)
            keys, result = enroll(client, "desktop")
            assert result.status_code == 201
            assert client.put("/v1/node-helpers/desktop", json={"enabled": True}).status_code == 200
            app = FastAPI()
            app.state.node_identity = SimpleNamespace(
                record=SimpleNamespace(
                    enrolled=True,
                    name="desktop",
                    signing_public_key=keys.signing_public,
                    control_url="http://control",
                )
            )
            app.state.auth_state = SimpleNamespace(
                trust=SimpleNamespace(agent_token=lambda _: keys.service_token())
            )
            app.state.apps = SimpleNamespace(
                accounts=SimpleNamespace(
                    available=True, kind="windows_service" if os.name == "nt" else "systemd"
                ),
                store=SimpleNamespace(
                    get=lambda _: SimpleNamespace(enabled=True, port=port, manifest=package)
                ),
                supervisor=SimpleNamespace(
                    status=lambda _: (ComponentStatus.running, None, None, None, None),
                    admin_token=lambda _: local_token,
                ),
                installer=SimpleNamespace(snapshot=lambda _: None),
            )
            relay = NodeFileHelper(app)

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

            async def installed(_config: dict) -> None:
                pass  # Real wheel already installed above; C1 checks the service launcher.

            relay.reconcile = installed
            relay._root = "http://control"
            relay._root_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
            task = asyncio.create_task(relay.run())
            try:
                deadline = time.perf_counter() + 5
                while not getattr(
                    getattr(client.app.state, "node_helper_broker", None), "reports", None
                ):
                    if time.perf_counter() > deadline:
                        raise RuntimeError("Agent did not poll")
                    await asyncio.sleep(0.02)
                registered = await asyncio.to_thread(
                    client.post,
                    "/v1/node-helpers/desktop/folders",
                    json={"name": "Notes", "path": str(folder), "writable": True},
                )
                assert registered.status_code == 201, registered.text
                grant = registered.json()
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

                async def execute(tool: str, args: dict) -> httpx.Response:
                    return await asyncio.to_thread(
                        client.post,
                        "/oidc/node-helpers/execute",
                        auth=auth,
                        json={
                            "refreshToken": tokens["refresh_token"],
                            "folderId": grant["id"],
                            "tool": tool,
                            "arguments": args,
                        },
                    )

                read = await execute("read_text", {"path": "note.txt"})
                assert (
                    read.status_code == 200
                    and read.json()["result"]["text"] == "Private desktop notes"
                ), read.text
                digest = read.json()["result"]["sha256"]
                written = await execute(
                    "write_text",
                    {"path": "note.txt", "text": "Updated by Ada", "expectedSha256": digest},
                )
                assert written.json()["status"] == "done", written.text
                assert file.read_text() == "Updated by Ada"
                assert (await execute("read_text", {"path": "../control/control.yaml"})).json()[
                    "status"
                ] == "failed"
                client.patch(f"/v1/people/{created['id']}", json={"helperGrants": []})
                assert (await execute("read_text", {"path": "note.txt"})).status_code == 403
                assert b"Updated by Ada" not in applied.canonical_bytes(
                    client.app.state.machine.state
                )
                print(
                    "PASS: installed wheel, outbound polling, real sign-in and grants, "
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
