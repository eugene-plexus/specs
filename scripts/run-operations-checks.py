"""Cross-component run protocol: close every browser, crash between side effects,
restart Library/agent, and finish exactly one declaration. Uses isolated ASGI
process boundaries and a fake engine; no GPU, download or user install is touched.
"""

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
from eugene_plexus_agent.admission import LibraryFitClient
from eugene_plexus_agent.run_worker import RunWorker, runtime_spec
from eugene_plexus_library._generated.models import LibraryModel
from eugene_plexus_library.routes.run_operations import router
from eugene_plexus_library.run_operations import Journal
from eugene_plexus_library.store import StateStore
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent


class Engine:
    def __init__(self):
        self.installed = False
        self.installs = 0
        self.declarations = {}
        self.starts = 0
        self.crash_after_launch = False

    async def engines(self):
        return [
            {
                "engine": "llama_cpp",
                "available": self.installed,
                "modelFormats": ["gguf"],
                "acquisition": {"installable": True},
            }
        ]

    async def install(self, engine, *, previous=None):
        self.installs += 1
        self.installed = True
        return None

    async def context_size(self, library, model, engine):
        return 4096

    async def launch(self, model, profile, *, start):
        spec = runtime_spec(model, profile, start=start)
        self.declarations.setdefault(spec.name, spec.model_dump(mode="json"))
        if start and not self.starts:
            self.starts += 1
        if self.crash_after_launch:
            self.crash_after_launch = False
            raise httpx.ConnectError("crash after runtime declaration")
        return {"name": spec.name, "status": "loading" if start else "stopped"}

    async def runtime(self, name):
        return {"name": name, "status": "ready"}


async def check(directory):
    app = FastAPI(title="Eugene Plexus durable run protocol", version="1.0.0")
    app.include_router(router)
    actual = app.openapi()
    canonical = json.loads((ROOT / "openapi/run-operations.json").read_text())
    assert actual["paths"] == canonical["paths"], "run protocol paths drifted"
    assert actual["components"] == canonical["components"], "run protocol schemas drifted"
    app.state.auth_state = SimpleNamespace(auth_disabled=True)
    store = StateStore(directory / "state.json")
    store.load()
    model = LibraryModel(
        id="m", name="Example 8B", path="/models/m.gguf", format="gguf", status="present"
    )
    store.replace_models([model], scanned_at=datetime.now(UTC))
    app.state.state_store = store
    now = [1_800_000_000.0]
    app.state.run_operations = Journal(directory / "runs.sqlite3", clock=lambda: now[0])
    engine = Engine()
    node = FastAPI()
    real = httpx.ASGITransport(app=app)
    drop_checkpoint = [False]

    async def transport(request):
        response = await real.handle_async_request(request)
        await response.aread()
        # The side effect happened but the response was lost.
        if request.url.path.endswith("/profile") and drop_checkpoint[0]:
            drop_checkpoint[0] = False
            raise httpx.ConnectError("crash after profile persistence", request=request)
        return response

    client = LibraryFitClient("http://library", None, transport=httpx.MockTransport(transport))
    async with httpx.AsyncClient(transport=real, base_url="http://library") as operator:
        intent = {"node": "worker", "modelId": "m"}
        response = await operator.put("/v1/run-operations/job", json=intent)
        assert response.status_code == 202, response.text
        assert (await operator.put("/v1/run-operations/job", json=intent)).json()["id"] == "job"
        # No browser exists after this request. Only the assigned agent advances.
        for _ in range(2):
            await RunWorker(node, node_actions=engine).tick(client, node="worker")
        assert app.state.run_operations.get("job")["step"] == "awaiting-install"
        await operator.post("/v1/run-operations/job/answer", json={"answer": "install"})
        await RunWorker(node, node_actions=engine).tick(client, node="worker")
        assert app.state.run_operations.get("job")["step"] == "settings"
        drop_checkpoint[0] = True
        await RunWorker(node, node_actions=engine).tick(client, node="worker")
        assert len(store.list_profiles("m")) == 1
        now[0] += 121
        # Library and agent both restart. State comes from disk, not Python objects.
        recovered = StateStore(directory / "state.json")
        recovered.load()
        app.state.state_store = recovered
        app.state.run_operations = Journal(directory / "runs.sqlite3", clock=lambda: now[0])
        await RunWorker(node, node_actions=engine).tick(client, node="worker")
        engine.crash_after_launch = True
        await RunWorker(node, node_actions=engine).tick(client, node="worker")
        assert engine.starts == 1
        assert app.state.run_operations.get("job")["step"] == "launching"
        now[0] += 121
        for _ in range(2):
            await RunWorker(node, node_actions=engine).tick(client, node="worker")
        assert app.state.run_operations.get("job")["step"] == "ready"
        assert (
            len(recovered.list_profiles("m"))
            == engine.installs
            == engine.starts
            == len(engine.declarations)
            == 1
        )
        # Ready receipts keep retries inert, including a retry after restart.
        assert (await operator.put("/v1/run-operations/job", json=intent)).json()["step"] == "ready"
        await RunWorker(node, node_actions=engine).tick(client, node="worker")
        assert engine.starts == 1
    if client._own_client is not None:
        await client._own_client.aclose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="ep-run-check-") as directory:
        asyncio.run(check(Path(directory)))
    print(
        "PASS: protocol conformance, durable install decision, restart after profile and runtime "
        "commits, one profile/install/runtime/start"
    )
