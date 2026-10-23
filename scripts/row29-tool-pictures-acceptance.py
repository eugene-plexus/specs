"""Row 29: real MCP and Job Site pictures reach a fixture vision backend.

CI only: root, row 2's shared agent harness, its gateway and inference-driver,
Workbench installed from the candidate archive, and a site host with a real
worker/channel and stdio MCP server. No engine or hardware measurement. All
ports come from the shared harness; ambient EUGENE_PLEXUS_* values are cleared.

Run with CI's component interpreter. --workbench chooses the candidate ref;
the site host comes from CI's sibling checkout. --output preserves evidence.
The two 4 MiB paths run with vision and text models. Fourteen small pictures
then prove Workbench keeps eight and the gateway's effective limit keeps four.
"""

import argparse
import asyncio
import base64
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
APP = "workbench-row29"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def picture(index: int, large: bool) -> bytes:
    """A valid PNG with distinct pixels and optional inert padding inside the PNG."""

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    head = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    )
    head += chunk(b"IDAT", zlib.compress(bytes([0, index, 80, 120])))
    tail = chunk(b"IEND", b"")
    size = 4 * 1024 * 1024 if large else 256
    return (
        head
        + chunk(b"tEXt", b"pad\0" + bytes(size - len(head) - len(tail) - 16))
        + tail
    )


def picture_url(index: int, large: bool) -> str:
    return "data:image/png;base64," + base64.b64encode(picture(index, large)).decode()


def verify(body, expected, *, large, attached, omitted, unseen=0):
    """Check received bytes, tool provenance and every replay claim, independently."""
    images, text = [], []
    for message in body["messages"]:
        content = message.get("content")
        if message["role"] == "tool":
            assert isinstance(content, str), (
                "The backend received media in a tool message"
            )
            text.append(content)
        if isinstance(content, list):
            for position, part in enumerate(content):
                if part["type"] == "image_url":
                    assert message["role"] == "user", (
                        "A picture arrived on the wrong role"
                    )
                    assert position and content[position - 1]["type"] == "text"
                    assert (
                        "returned by tool call row29-" in content[position - 1]["text"]
                    )
                    images.append(part["image_url"]["url"])
    assert images == [picture_url(i, large) for i in expected], (
        "Wrong or missing tool pictures"
    )
    words = "\n".join(text)
    assert words.count("It is attached.") == attached, (
        "Workbench attached the wrong pictures"
    )
    assert words.count("not attached: this request holds at most 4 pictures") == omitted
    assert words.count("The person sees it; you do not.") == unseen


def mcp_server():
    from mcp.server import MCPServer
    from mcp.types import CallToolResult, ImageContent

    server = MCPServer("Row 29 pictures", log_level="ERROR")

    @server.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    async def screenshot(index: int, large: bool) -> CallToolResult:
        """Return the requested fixture picture."""
        return CallToolResult(
            content=[
                ImageContent(
                    type="image",
                    mimeType="image/png",
                    data=base64.b64encode(picture(index, large)).decode(),
                )
            ]
        )

    return server


def fixture_app():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    seen = []

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/seen")
    async def received():
        return seen[-1] if seen else {}

    @app.get("/v1/models/user")
    async def models():
        return {
            "data": [
                {
                    "id": model,
                    "name": model,
                    "context_length": 32768,
                    "architecture": {
                        "input_modalities": ["text", "image"]
                        if model == "vision"
                        else ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": [
                        "tools",
                        "tool_choice",
                        "parallel_tool_calls",
                        "temperature",
                        "top_p",
                        "max_tokens",
                        "response_format",
                    ],
                }
                for model in ("vision", "text")
            ]
        }

    @app.post("/v1/chat/completions")
    async def complete(body: dict):
        seen.append(body)
        words = " ".join(
            str(m.get("content") or "") for m in body["messages"] if m["role"] == "user"
        )
        goal = re.search(r"row29 count=(\d+) large=(\d)", words)
        assert goal, "The fixture did not receive the test's request"
        count = sum(m["role"] == "tool" for m in body["messages"])
        more = count < int(goal[1])
        delta = {"content": "Pictures checked."}
        if more:
            picture_tools = [
                offered["function"]["name"]
                for offered in body["tools"]
                if {"index", "large"}
                <= set(offered["function"].get("parameters", {}).get("properties", {}))
            ]
            assert len(picture_tools) == 1, (
                "The picture tool was not offered exactly once"
            )
            tool = picture_tools[0]
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"row29-{count}",
                        "type": "function",
                        "function": {
                            "name": tool,
                            "arguments": json.dumps(
                                {"index": count, "large": goal[2] == "1"}
                            ),
                        },
                    }
                ]
            }
        finish = "tool_calls" if more else "stop"
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        if not body.get("stream"):
            message = {"role": "assistant", **delta}
            for call in message.get("tool_calls", []):
                call.pop("index", None)
            return {
                "model": body["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": usage,
            }

        async def frames():
            for event in [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    "usage": usage,
                },
            ]:
                yield "data: " + json.dumps({"model": body["model"], **event}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def serve_site(directory, port):
    import uvicorn

    sys.path.insert(0, str(HERE.parent.parent / "site-host" / "src"))
    from eugene_plexus_site_host import local_channel
    from eugene_plexus_site_host._generated.models import SiteLocalServer
    from eugene_plexus_site_host.app import create_app
    from eugene_plexus_site_host.settings import Settings
    from eugene_plexus_site_host.worker import Worker

    channel = (
        rf"\\.\pipe\row29-{secrets.token_hex(8)}"
        if os.name == "nt"
        else str(directory / "worker.sock")
    )
    entry = SiteLocalServer.model_validate(
        {
            "id": "pictures",
            "name": "Pictures",
            "command": sys.executable,
            "args": [str(Path(__file__).resolve()), "--mcp-stdio"],
            "sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        }
    )
    settings = Settings(
        data_dir=directory,
        port=port,
        channel=channel,
        links_file=directory / "links.json",
        local_servers=(entry,),
        account_kind="windows_service" if os.name == "nt" else "systemd",
    )
    app = create_app(settings)
    original = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(application):
        async with original(application):
            worker = Worker(
                account=local_channel.own_account(),
                channel=channel,
                host=local_channel.own_account(),
                servers=(entry,),
                protected=[],
                workspace=directory,
            )
            task = asyncio.create_task(worker.run())
            try:
                yield
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def serve(kind, directory, port):
    import uvicorn

    if kind == "agent":
        load("row29_harness", "s8-ui-acceptance.py").serve(directory, port)
        return
    if kind == "site":
        serve_site(directory, port)
        return
    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(
                config_file=directory / "control.yaml", state_dir=directory / "state"
            )
        )
    elif kind == "fixture":
        app = fixture_app()
    elif kind == "mcp":
        app = mcp_server().streamable_http_app(json_response=True)
    else:
        raise ValueError(f"Unknown fixture process: {kind}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(work, workbench_ref):
    harness = load("row29_ports", "s8-ui-acceptance.py")
    c3 = load("row29_browser", "c3-workbench-acceptance.py")
    r7 = load("row29_archive", "row7-person-removal-acceptance.py")
    commit = r7.resolve(workbench_ref)
    ports = {}
    for name in ("control", "agent", "gateway", "model", "fixture", "site", "mcp"):
        ports[name] = harness.free_port(*ports.values())
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
    processes, logs = [], []
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith("EUGENE_PLEXUS_")
    }
    env.update(
        OPENAI_API_KEY="row29-fixture",  # gitleaks:allow (a fake)
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    password = secrets.token_urlsafe(24)
    client = httpx.Client(timeout=40, trust_env=False)

    def wait(check, label, seconds=90):
        deadline, last = time.perf_counter() + seconds, None
        while time.perf_counter() < deadline:
            try:
                value = check()
                if value:
                    return value
            except (
                httpx.HTTPError,
                KeyError,
                ValueError,
                IndexError,
                StopIteration,
            ) as exc:
                last = str(exc)[:400]
            time.sleep(0.2)
        raise AssertionError(f"Timed out waiting for {label}: {last}")

    def call(name, method, path, token=None, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        result = client.request(method, urls[name] + path, headers=headers, **kwargs)
        result.raise_for_status()
        return result.json() if result.content else None

    def start(name):
        directory = work / name
        directory.mkdir(exist_ok=True)
        log = (directory / "process.log").open("ab")
        logs.append(log)
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--serve",
                    name,
                    "--directory",
                    str(directory),
                    "--port",
                    str(ports[name]),
                ],
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        )
        if name != "mcp":
            wait(lambda: client.get(urls[name] + "/healthz").status_code == 200, name)

    try:
        start("fixture")
        start("mcp")
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": password})
        root = call("control", "POST", "/v1/auth/login", json={"passphrase": password})[
            "sessionToken"
        ]
        call(
            "control",
            "PATCH",
            "/v1/config",
            root,
            json={"siteJoinUrl": urls["control"]},
        )
        directory = work / "agent"
        directory.mkdir()
        (directory / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        (directory / "model.yaml").write_text(
            yaml.safe_dump({"provider": "openrouter", "baseUrl": urls["fixture"]}),
            encoding="utf-8",
        )
        components = [
            {
                "name": name,
                "kind": kind,
                "url": urls[name],
                "spawn": {"configFile": str(directory / f"{name}.yaml")},
            }
            for name, kind in (("gateway", "gateway"), ("model", "inference-driver"))
        ]
        (directory / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "allowCustomApps": True,
                    "securityMode": "prompt_on_startup",
                    "uvBinary": c3.uv_binary(),
                    "components": components,
                }
            ),
            encoding="utf-8",
        )
        start("agent")
        token = call(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": password}
        )["sessionToken"]
        join = call(
            "control",
            "POST",
            "/v1/nodes/join-token",
            root,
            json={"nodeName": "row29", "grants": ["gateway"]},
        )["token"]
        call(
            "agent",
            "POST",
            "/v1/node/enroll",
            token,
            json={"controlUrl": urls["control"], "token": join, "name": "row29"},
        )
        wait(
            lambda: client.get(urls["agent"] + "/healthz").status_code == 200,
            "agent after enrollment",
        )
        token = call("agent", "POST", "/v1/auth/login", json={"passphrase": password})[
            "sessionToken"
        ]
        entry = next(
            e["manifest"]
            for e in call("agent", "GET", "/v1/app-catalogue", token)["apps"]
            if e["manifest"]["id"] == "workbench"
        )
        manifest = {
            **entry,
            "id": APP,
            "localActions": False,
            "version": commit,
            "source": f"https://github.com/eugene-plexus/workbench/archive/{commit}.tar.gz",
        }
        call("agent", "POST", "/v1/app-catalogue/custom", token, json=manifest)
        call("agent", "POST", f"/v1/apps/{APP}/install", token)

        def installed():
            state = call("agent", "GET", f"/v1/apps/{APP}/install", token)
            assert state["state"] != "failed", state
            return state["state"] == "done"

        wait(installed, "Workbench install", 600)
        app = wait(
            lambda: (
                a
                if (a := call("agent", "GET", f"/v1/apps/{APP}", token))["status"]
                == "running"
                else None
            ),
            "Workbench",
        )
        browser = c3.Browser(app["uiUrl"])
        assert browser.sign_in(password).startswith("/#signin=")
        wait(
            lambda: len(browser.get("/api/models").json()["models"]) >= 2,
            "both model capabilities",
        )
        direct = browser.post(
            "/api/tools/servers",
            json={"name": "Pictures", "url": urls["mcp"] + "/mcp", "token": ""},
        )
        direct.raise_for_status()

        # Shared servers need the install owner; a Job Site belongs to a person.
        person_password = secrets.token_urlsafe(24)
        person = call(
            "control",
            "POST",
            "/v1/people",
            root,
            json={"name": "ada", "password": person_password},
        )
        browser.http.close()
        browser = c3.Browser(app["uiUrl"])
        assert browser.sign_in(person_password, person["name"]).startswith("/#signin=")

        # Enroll a real site, with a disposable unsigned fixture policy and own-account worker.
        sys.path.insert(0, str(HERE.parent.parent / "site-host" / "src"))
        from eugene_plexus_site_host import local_channel
        from eugene_plexus_site_host.identity import Identity
        from eugene_plexus_site_host.join import join as site_join
        from eugene_plexus_site_host.policy import Policy

        site_dir = work / "site"
        site_dir.mkdir()
        me = browser.get("/api/me").json()
        assert me["sub"] == person["id"]
        assert me["username"] == person["name"]
        invitation = call(
            "control",
            "POST",
            "/v1/sites/invitations",
            root,
            json={"owner": person["id"], "label": "Pictures"},
        )
        enrolled = asyncio.run(
            site_join(
                Identity(site_dir),
                url=urls["control"],
                token=invitation["token"],
                owner=person["name"],
                password=person_password,
                label="Pictures",
                root_key=None,
                host_version=None,
            )
        )
        (site_dir / "links.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "links": [
                        {
                            "subject": me["sub"],
                            "name": me["name"],
                            "account": local_channel.own_account(),
                            "accountName": "row29",
                            "linkedAt": enrolled.enrolledAt,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        Policy(
            site_dir / "policy.json",
            owner=me["sub"],
            enabled={"pictures": True},
            access=[
                {
                    "subject": me["sub"],
                    "server": "pictures",
                    "tools": [{"name": "screenshot", "decision": "allow"}],
                }
            ],
        ).save()
        start("site")
        site_id = f"site:{enrolled.site}:pictures"
        wait(
            lambda: any(
                s["id"] == site_id and s["available"]
                for s in browser.get("/api/tools/servers").json()["servers"]
            ),
            "site tool listing",
        )

        def run(server, vision, *, count=1, large=True, gateway_limit=12):
            configured = call(
                "agent",
                "PATCH",
                "/api/proxy/gateway/v1/config",
                token,
                json={"maxImagesPerRequest": gateway_limit},
            )
            assert not configured.get("rejected"), configured
            chat = browser.post(
                "/api/chats", json={"model": "model/vision" if vision else "model/text"}
            ).json()["id"]
            browser.patch(
                f"/api/chats/{chat}", json={"settings": {"toolServers": [server]}}
            ).raise_for_status()
            browser.post(
                f"/api/chats/{chat}/messages",
                json={"content": f"row29 count={count} large={int(large)}"},
            ).raise_for_status()
            approved = set()

            def finished():
                answer = browser.get(f"/api/chats/{chat}").json()["messages"][-1]
                for turn in answer.get("toolRounds", []):
                    for item in turn["calls"]:
                        if item["status"] == "pending" and item["id"] not in approved:
                            browser.post(
                                f"/api/chats/{chat}/messages/{answer['id']}/tools/decision",
                                json={"callId": item["id"], "approve": True},
                            ).raise_for_status()
                            approved.add(item["id"])
                if answer["status"] != "running":
                    assert answer["status"] == "done", answer.get("error")
                    return answer

            answer = wait(finished, "the tool loop", 120)
            blocks = [
                b
                for t in answer["toolRounds"]
                for c in t["calls"]
                for b in c.get("content", [])
                if b["type"] == "image"
            ]
            assert len(blocks) == count, "Workbench did not keep every tool picture"
            for index, block in enumerate(blocks):
                got = browser.get(f"/api/files/{block['fileId']}")
                got.raise_for_status()
                assert got.content == picture(index, large), "A kept picture changed"
            body = call("fixture", "GET", "/seen")
            newest = min(count, 8, gateway_limit) if vision else 0
            verify(
                body,
                list(range(count - newest, count)),
                large=large,
                attached=min(count, 8) if vision else 0,
                omitted=max(0, min(count, 8) - gateway_limit) if vision else 0,
                unseen=max(0, count - 8) if vision else count,
            )
            print(
                f"PASS {server}: vision={vision}, {count} kept, {newest} delivered",
                flush=True,
            )

        for server in (direct.json()["id"], site_id):
            run(server, True)
            run(server, False)
        run(direct.json()["id"], True, count=14, large=False)
        run(direct.json()["id"], True, count=14, large=False, gateway_limit=4)
        browser.http.close()
    finally:
        (work / "agent" / "stop").touch()
        import psutil

        for process in reversed(processes):
            with contextlib.suppress(psutil.NoSuchProcess):
                top = psutil.Process(process.pid)
                for child in top.children(recursive=True):
                    with contextlib.suppress(psutil.NoSuchProcess):
                        child.kill()
                with contextlib.suppress(psutil.NoSuchProcess):
                    top.kill()
            process.wait(timeout=20)
        client.close()
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve", choices=["agent", "control", "fixture", "site", "mcp"]
    )
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--mcp-stdio", action="store_true")
    parser.add_argument("--workbench", default=os.getenv("R29_WORKBENCH_REF", "main"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for name in list(os.environ):
        if name.upper().startswith("EUGENE_PLEXUS_"):
            del os.environ[name]
    if args.mcp_stdio:
        mcp_server().run(transport="stdio")
    elif args.serve:
        assert args.port and args.port not in set(range(8079, 8084))
        serve(args.serve, args.directory, args.port)
    elif args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        exercise(args.output.resolve(), args.workbench)
    else:
        with tempfile.TemporaryDirectory(prefix="row29-") as directory:
            exercise(Path(directory), args.workbench)


if __name__ == "__main__":
    main()
