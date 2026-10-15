"""Measure a running local model through an isolated real Eugene gateway/driver.

No engine lifecycle operations or installed configuration changes. Uses the
already-running Strata endpoint supplied by the operator. Gateway credentials,
discovery/admission fixture and SQLite stores are private and temporary.
Run with agent/.venv; sibling Workbench source supplies the exact G3 validator.
This is a generation sample, not a protocol or renderer conformance claim.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workbench" / "src"))
os.environ["EP_GATEWAY_SRC"] = str(ROOT / "gateway" / "src")
os.environ["EP_DRIVER_SRC"] = str(ROOT / "inference-driver" / "src")


def harness() -> Any:
    spec = importlib.util.spec_from_file_location(
        "a2ui_inference_harness",
        Path(__file__).with_name("genui-inference-acceptance.py"),
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def validate(tmp: Path, data: Any) -> dict[str, Any]:
    from eugene_plexus_workbench import a2ui_state as ui  # type: ignore[import-untyped]
    from eugene_plexus_workbench.a2ui import A2UI  # type: ignore[import-untyped]
    from eugene_plexus_workbench.interactions import Surface  # type: ignore[import-untyped]
    from eugene_plexus_workbench.store import Store  # type: ignore[import-untyped]

    store = Store(tmp / "validation.sqlite3")
    service: Any = SimpleNamespace(store=store)
    unused: Any = None
    adapter = A2UI(unused, service, unused)
    origin = Surface(
        id="sample",
        owner="sample",
        chat_id="sample",
        message_id="sample",
        run_id="sample",
        protocol=ui.PROTOCOL,
        version=ui.VERSION,
        connection_id="sample",
        view={},
        fallback="Sample",
        actions=[],
        expires_at=time.time() + 3600,
        binding={
            "namespace": "sample",
            "source": "sample",
            "tool": "sample",
            "producer": {
                "version": ui.VERSION,
                "catalogId": ui.CATALOG,
                "actionTool": "submit",
            },
        },
    )
    try:
        updates = await adapter.plan(origin, data)
        assert len(updates) == 1 and updates[0].state == "active"
        adapter.validate_surface(updates[0].surface)
        assert updates[0].surface.view["ready"], "unresolved component references"
        return updates[0].surface.view
    finally:
        await store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strata-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    url = urlsplit(args.strata_url)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
    ):
        parser.error(
            "Use the running loopback Strata HTTP endpoint, without credentials."
        )
    gate = harness()
    h = gate.h
    import httpx
    from eugene_plexus_workbench import a2ui_state as ui
    from eugene_plexus_workbench.a2ui import A2UI

    assert A2UI  # Preflight imports before issuing any model requests.

    with httpx.Client(trust_env=False, timeout=10) as client:
        discovered = client.get(args.strata_url.rstrip("/") + "/v1/models")
        discovered.raise_for_status()
        assert any(m["id"] == args.model for m in discovered.json()["data"]), (
            "The chosen model is not running"
        )
    schemas = {
        name: json.loads((ui.SCHEMAS / name).read_text(encoding="utf-8"))
        for name in (
            "server_to_client.json",
            "common_types.json",
            "forms-v1.json",
        )
    }
    prompt = (
        "Generate A2UI 0.9.1 with the supplied schemas. Return one JSON object with exactly "
        "mimeType='application/a2ui+json', messages=[A2UI server messages], and a readable fallback. "
        "Use catalogId='" + ui.CATALOG + "'. Create one surface before updating it. "
        "The root component ID is root. Use only this catalog, static children, absolute data paths, "
        "and event actions. No templates, URLs, images, HTML or executable code. "
        "Resolve every component reference. Each component uses {id,component,...}. "
        "Button uses child (a Text component ID), action:{event:{name,context}}. "
        "updateDataModel uses value, not contents. Keep the result short. Schemas: "
        + json.dumps(schemas, separators=(",", ":"))
    )
    cases = [
        ("text", "A single Text reading 'A2UI ready'.", {"Text"}),
        (
            "form",
            "An RSVP form: name TextField bound to /name, a CheckBox bound to /attending, "
            "a submit Button with event name rsvp and context for both bound values. Initialize name "
            "to Ada and attending to true. Require nonempty name using a required check.",
            {"Column", "TextField", "CheckBox", "Button", "Text"},
        ),
        (
            "layout",
            "A Row holding two Cards with Text children bound to /city and /weather. "
            "Initialize city to Chicago and weather to Sunny.",
            {"Row", "Card", "Text"},
        ),
    ]
    logging.basicConfig(level=logging.ERROR)
    h.Driver = gate.JoinedDriver
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="a2ui-model-") as directory:
        tmp = Path(directory)
        mods = h.load_gateway()
        trust = h.Trust(tmp / "trust", mods)
        discovery = h.handler_for(
            h.Agent, "a2ui-discovery", components=[], admissions=[]
        )
        server, port = h.serve(discovery)
        driver = gateway = None
        try:
            driver = h.Driver(
                "a2ui-strata",
                {
                    "provider": "strata_local",
                    "baseUrl": args.strata_url,
                    "modelId": args.model,
                },
                tmp,
                f"http://127.0.0.1:{port}",
            )
            with httpx.Client(trust_env=False, timeout=30) as client:
                driver.wait(client)
            discovery.components = [
                {
                    "name": driver.name,
                    "kind": "inference-driver",
                    "url": driver.url,
                    "status": "running",
                }
            ]
            gateway = h.Gateway(tmp, port, [], trust, mods, "a2ui")
            sources = {
                "gateway": str(mods.file),
                "driver": driver.code().strip(),
                "validator": str(ui.__file__),
            }
            for label, task, required in cases:
                started = time.perf_counter()
                response = gateway.http.post(
                    "/v1/chat/completions",
                    headers=gateway.keyed,
                    json={
                        "model": args.model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": task},
                        ],
                        "temperature": 0,
                        "max_tokens": 4096,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=180,
                )
                row: dict[str, Any] = {
                    "case": label,
                    "status": response.status_code,
                    "seconds": round(time.perf_counter() - started, 3),
                    "jsonValid": False,
                    "catalogValid": False,
                    "taskValid": False,
                }
                if response.status_code == 200:
                    body = response.json()
                    choice = body["choices"][0]
                    row.update(finish=choice["finish_reason"], usage=body.get("usage"))
                    try:
                        data = json.loads(choice["message"].get("content") or "")
                        row["jsonValid"] = True
                        state = asyncio.run(validate(tmp, data))
                        row["catalogValid"] = True
                        types = {c["component"] for c in state["components"]}
                        assert required <= types
                        if label == "text":
                            assert any(
                                c.get("text") == "A2UI ready"
                                for c in state["components"]
                            )
                        elif label == "layout":
                            assert state["dataModel"] == {
                                "city": "Chicago",
                                "weather": "Sunny",
                            }
                        else:
                            assert state["dataModel"] == {
                                "name": "Ada",
                                "attending": True,
                            }
                            button = next(
                                c
                                for c in state["components"]
                                if c["component"] == "Button"
                            )
                            assert button["action"]["event"]["name"] == "rsvp"
                            assert any(
                                c.get("checks")
                                for c in state["components"]
                                if c["component"] == "TextField"
                            )
                        row["taskValid"] = True
                        row["surface"] = data
                    except Exception as exc:
                        row["errorType"] = type(exc).__name__
                        row["output"] = (choice["message"].get("content") or "")[:20000]
                else:
                    row["response"] = response.text[:1000]
                rows.append(row)
                print(
                    json.dumps(
                        {k: v for k, v in row.items() if k not in {"surface", "output"}}
                    ),
                    flush=True,
                )
        finally:
            if gateway is not None:
                gateway.stop()
            if driver is not None:
                driver.stop()
            server.shutdown()
            server.server_close()
    args.report.write_text(
        json.dumps(
            {
                "model": args.model,
                "transport": "isolated Eugene gateway + Strata driver; running engine",
                "python": sys.version.split()[0],
                "sources": sources,
                "samples": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0 if all(row["taskValid"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
