"""Row 59: Tavily, and remote MCP on the Responses door, through real processes.

A disposable standalone agent (row 2's harness, `s8-ui-acceptance.py --serve`)
lists a real inference-driver over a scripted backend, a real tool-driver and
a real gateway. Three stand-ins, each on an OS-chosen port:

* `fixture` (127.0.0.1): the scripted model backend, and a stub of Tavily's
  `POST /search` that records the key it was sent.
* `mcp`: a Streamable HTTP MCP server on this runner's **own private
  address** (not loopback), recording the headers it was sent. Under the
  default reach it must be refused for that address; under the owner's
  expert reach it is reached.

What it shows, through the unchanged OpenAI SDK where a caller is involved:

1. Tavily (59a): the tool-driver, set up through the agent's proxy as the
   console does, answers a `web_search` with Tavily's results and answer;
   Tavily saw the key as a bearer, and the depth.
2. The address rule under the default (`internet`): a server on this
   network, on loopback, on 169.254.169.254 and over plain http are each
   refused with a 400 naming the rule, and the MCP server saw nothing.
3. The owner turns on *Internet and this network* through the proxy; the
   schema warns beside it. Loopback and the metadata address stay refused.
4. A list and a call round-trip (`mcp_list_tools`, `mcp_call`, the answer),
   whole and streamed; the server saw the caller's token and header.
5. Approvals: the default `always` ends the response with an
   `mcp_approval_request` and runs nothing; the answer runs it once; an
   approval for an id the conversation does not carry is refused.
6. The caller's token is in no log (both run at DEBUG), no metrics row or
   file, no config file and no response; the metrics row has `mcpCalls`.

`--sabotage` then runs it again with the tool-driver's address check
replaced by one that allows everything, and passes only if step 2 fails.
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
MODEL = "row59-fixture"
MCP_TOKEN = "row59-mcp-token-" + secrets.token_hex(12)
MCP_HEADER = "row59-header-" + secrets.token_hex(8)
TAVILY_KEY = "tvly-row59-" + secrets.token_hex(8)
TAVILY_ANSWER = "ROW59-TAVILY-ANSWER: Eugene Plexus is a control plane."
TAVILY_URL = "https://github.com/eugene-plexus"


class AddressCheckFailed(AssertionError):
    """Step 2 failed: an address the default reach must refuse was not refused."""


def harness():
    spec = importlib.util.spec_from_file_location("row59_harness", HERE / "s8-ui-acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_address() -> str:
    """This runner's own address on its network: where the route out leaves.

    A UDP `connect` sends nothing; it only picks the interface. The address
    must be private and not loopback, or the check that it is refused under
    the default reach proves nothing.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    found = ipaddress.ip_address(address)
    assert found.is_private and not found.is_loopback and not found.is_link_local, (
        f"this runner's address {address} is not a private one; the check needs one"
    )
    return address


# --------------------------------------------------------------------------- #
# The stand-ins
# --------------------------------------------------------------------------- #


def answer(body: dict) -> tuple[str | None, list[dict] | None]:
    messages = body["messages"]
    names = [t["function"]["name"] for t in body.get("tools") or []]
    last = messages[-1]
    if last["role"] == "tool":
        return f"FINAL: {last['content']}", None
    if "echo" in names:
        call = {"name": "echo", "arguments": json.dumps({"text": "hello"})}
    elif "web_search" in names:
        call = {"name": "web_search", "arguments": json.dumps({"query": "eugene plexus"})}
    else:
        return "PLAIN", None
    return None, [{"id": "call_row59_" + secrets.token_hex(4), "type": "function", "function": call}]


def fixture_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse

    app = FastAPI()
    seen: list[dict] = []
    tavily: list[dict] = []

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/seen")
    async def requests():
        return {"model": seen, "tavily": tavily}

    @app.post("/tavily/search")
    async def search(request: Request):
        body = await request.json()
        tavily.append({"authorization": request.headers.get("authorization"), "body": body})
        return {
            "query": body.get("query"),
            "answer": TAVILY_ANSWER,
            "results": [
                {
                    "title": "Eugene Plexus on GitHub",
                    "url": TAVILY_URL,
                    "content": "A self-hosted control plane.",
                    "score": 0.9,
                }
            ],
            "response_time": "0.1",
        }

    @app.get("/model/props")
    async def props():
        return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

    @app.get("/model/v1/models")
    async def models():
        return {"data": [{"id": MODEL, "object": "model"}]}

    @app.post("/model/v1/chat/completions")
    async def complete(body: dict):
        seen.append(body)
        text, calls = answer(body)
        usage = {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}
        finish = "tool_calls" if calls else "stop"
        if not body.get("stream"):
            return {
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish,
                        "message": {"role": "assistant", "content": text, "tool_calls": calls},
                    }
                ],
                "usage": usage,
            }

        async def frames():
            def frame(delta, reason=None, usage=None):
                chunk = {
                    "id": "chatcmpl-row59",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": MODEL,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                    "usage": usage,
                }
                return "data: " + json.dumps(chunk) + "\n\n"

            yield frame({"role": "assistant"})
            for call in calls or []:
                yield frame(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["function"]["name"],
                                    "arguments": call["function"]["arguments"],
                                },
                            }
                        ]
                    }
                )
            if text:
                yield frame({"content": text})
            yield frame({}, finish, usage)
            yield "data: [DONE]\n\n"

        return StreamingResponse(frames(), media_type="text/event-stream")

    return app


def mcp_app():
    """A Streamable HTTP MCP server with two tools, refusing a wrong token."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, Response

    app = FastAPI()
    seen: list[dict] = []
    tools = [
        {
            "name": "echo",
            "description": "Says the text back, in capitals.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }
    ]

    @app.get("/healthz")
    async def health():
        return {}

    @app.get("/seen")
    async def requests():
        return seen

    @app.api_route("/mcp", methods=["POST", "DELETE"])
    async def mcp(request: Request):
        headers = {k.lower(): v for k, v in request.headers.items()}
        if request.method == "DELETE":
            seen.append({"method": "DELETE", "headers": headers})
            return Response(status_code=200)
        message = json.loads(await request.body())
        seen.append({"method": message.get("method"), "headers": headers, "message": message})
        if headers.get("authorization") != f"Bearer {MCP_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if "id" not in message:
            return Response(status_code=202)
        method = message["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "row59", "version": "1"},
            }
            return JSONResponse(
                {"jsonrpc": "2.0", "id": message["id"], "result": result},
                headers={"Mcp-Session-Id": "row59-session"},
            )
        if method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            text = str((message["params"].get("arguments") or {}).get("text", ""))
            result = {"content": [{"type": "text", "text": "ECHO: " + text.upper()}]}
        else:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "no"}}
            )
        return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "result": result})

    return app


def serve(kind: str, directory: Path, port: int, host: str, sabotage: bool) -> None:
    import logging

    import uvicorn

    if kind == "fixture":
        uvicorn.run(fixture_app(), host=host, port=port, access_log=False)
        return
    if kind == "mcp":
        uvicorn.run(mcp_app(), host=host, port=port, access_log=False)
        return
    bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
    if kind == "tool":
        # The tool-driver's own entry point, with the environment the agent
        # would give it, so its logging is the shipped one (at DEBUG here).
        for key, value in bootstrap.items():
            os.environ[f"EUGENE_PLEXUS_TOOL_DRIVER_{key.upper()}"] = str(value)
        os.environ["EUGENE_PLEXUS_TOOL_DRIVER_CONFIG_FILE"] = str(directory / "tool.yaml")
        os.environ["EUGENE_PLEXUS_TOOL_DRIVER_BIND_PORT"] = str(port)
        if sabotage:
            from eugene_plexus_tool_driver import egress_guard

            egress_guard.refusal = lambda address, reach, scheme: None
            print("SABOTAGE: the address check allows every address", flush=True)
        from eugene_plexus_tool_driver.__main__ import main

        main()
        return
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    if kind == "model":
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        app = create_app(settings=Settings(config_file=directory / "driver.yaml", **bootstrap))
    else:
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "gateway.yaml",
                metrics_file=directory / "metrics.sqlite3",
                **bootstrap,
            )
        )
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def exercise(directory: Path, *, sabotage: bool) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    shared = harness()
    lan = private_address()
    ports: dict[str, int] = {}
    for name in ("agent", "machine", "fixture", "mcp", "model", "tool", "gateway"):
        ports[name] = shared.free_port(*ports.values())
    assert not set(ports.values()) & set(range(8079, 8084)), ports
    hosts = {name: "127.0.0.1" for name in ports}
    hosts["mcp"] = lan
    processes: list[subprocess.Popen] = []
    logs = []
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["PYTHONPYCACHEPREFIX"] = str(directory / "pycache")
    env.pop("OPENAI_API_KEY", None)
    client = httpx.Client(timeout=60, trust_env=False)

    def base(name: str) -> str:
        return f"http://{hosts[name]}:{ports[name]}"

    def write(name: str, filename: str, body: Any) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(body) if filename.endswith(".json") else yaml.safe_dump(body),
            encoding="utf-8",
        )

    def wait(check, label: str, seconds: float = 45) -> None:
        deadline = time.perf_counter() + seconds
        last: BaseException | None = None
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last = exc
            time.sleep(0.2)
        raise AssertionError(f"timed out: {label} ({last!r})")

    def start(name: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        if name == "agent":
            command = [
                sys.executable,
                str(HERE / "s8-ui-acceptance.py"),
                "--serve",
                str(work),
                "--port",
                str(ports[name]),
                "--machine-port",
                str(ports["machine"]),
            ]
        else:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
                "--host",
                hosts[name],
                *(["--sabotage"] if sabotage else []),
            ]
        processes.append(
            subprocess.Popen(
                command,
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        )
        wait(lambda: client.get(base(name) + "/healthz").status_code == 200, name)

    try:
        write(
            "agent",
            "agent.yaml",
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "components": [],
            },
        )
        start("agent")
        passphrase = secrets.token_urlsafe(24)
        client.post(
            base("agent") + "/v1/auth/initialize", json={"passphrase": passphrase}
        ).raise_for_status()
        operator = client.post(
            base("agent") + "/v1/auth/login", json={"passphrase": passphrase}
        ).json()["sessionToken"]
        as_operator = {"Authorization": "Bearer " + operator}
        identity = NodeIdentityStore(directory / "agent/node.yaml")
        identity.load()
        trust = NodeTrust(identity, directory / "agent/trust_bundle.json")
        trust.load()

        def bootstrap(kind: str) -> dict[str, str]:
            token, _ = trust.mint_service(sub=kind, audience=trust.recipient)
            return {
                "agent_url": base("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        def proxy(target: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
            return client.request(
                method, base("agent") + f"/api/proxy/{target}{path}", headers=as_operator, **kwargs
            )

        start("fixture")
        start("mcp")
        write("model", "bootstrap.json", bootstrap("inference-driver"))
        write(
            "model",
            "driver.yaml",
            {
                "provider": "openai_compat_custom",
                "baseUrl": base("fixture") + "/model",
                "modelId": MODEL,
                "backendLocality": "local",
            },
        )
        start("model")
        client.post(
            base("agent") + "/v1/components",
            headers=as_operator,
            json={"name": "row59-model", "kind": "inference-driver", "url": base("model")},
        ).raise_for_status()
        write("tool", "bootstrap.json", bootstrap("tool-driver"))
        write("tool", "tool.yaml", {"probeMinutes": 0, "logLevel": "DEBUG"})
        start("tool")
        client.post(
            base("agent") + "/v1/components",
            headers=as_operator,
            json={"name": "tavily", "kind": "tool-driver", "url": base("tool")},
        ).raise_for_status()
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 1})
        start("gateway")

        # --- 1. Tavily, set up as the console does ---------------------------
        patched = proxy(
            "tavily",
            "PATCH",
            "/v1/config",
            json={
                "provider": "tavily",
                "apiKey": TAVILY_KEY,
                "baseUrl": base("fixture") + "/tavily",
                "searchDepth": "advanced",
            },
        )
        assert patched.status_code == 200 and not patched.json()["rejected"], patched.text
        tested = proxy("tavily", "POST", "/v1/config/test").json()
        assert tested["ok"] is True, tested
        made = client.post(
            base("agent") + "/v1/auth/client-keys",
            headers=as_operator,
            json={
                "name": "row59-sdk",
                "limits": {"allowedModels": [MODEL], "requestsPerMinute": 1000},
            },
        )
        made.raise_for_status()
        key = made.json()["token"]
        as_client = {"Authorization": "Bearer " + key}

        def models() -> set[str]:
            listed = client.get(base("gateway") + "/v1/models", headers=as_client).json()
            return {m["id"] for m in listed.get("data", [])}

        wait(lambda: MODEL in models(), "the gateway lists the fixture model")

        def responses(**body: Any) -> httpx.Response:
            return client.post(
                base("gateway") + "/v1/responses",
                headers=as_client,
                json={"model": MODEL, "input": "Use the tool.", **body},
            )

        def found_the_tool_driver() -> bool:
            # Refused by the tool-driver before any address is looked at, so
            # the wait holds with the address check sabotaged too.
            probe = responses(
                tools=[
                    {
                        "type": "mcp",
                        "server_label": "probe",
                        "server_url": "https://user:secret@mcp.invalid/mcp",
                        "require_approval": "never",
                    }
                ]
            )
            return probe.status_code == 400 and "user name or password" in probe.text

        wait(found_the_tool_driver, "the gateway reaches the tool-driver for remote MCP")

        import openai

        sdk = openai.OpenAI(
            base_url=base("gateway") + "/v1", api_key=key, max_retries=0, timeout=90
        )
        searched = sdk.responses.create(
            model=MODEL, input="What is Eugene Plexus?", tools=[{"type": "web_search"}]
        )
        kinds = [item.type for item in searched.output]
        assert kinds == ["web_search_call", "message"], kinds
        sources = [s.url for s in searched.output[0].action.sources]
        assert sources == [TAVILY_URL], sources
        stub = client.get(base("fixture") + "/seen").json()
        asked = stub["tavily"][-1]
        assert asked["authorization"] == f"Bearer {TAVILY_KEY}", asked
        assert TAVILY_KEY not in json.dumps(asked["body"]), "the key rode in the body"
        assert asked["body"]["search_depth"] == "advanced", asked["body"]
        told = stub["model"][-1]["messages"][-1]
        assert told["role"] == "tool" and TAVILY_ANSWER in told["content"], told
        print(
            f"PASS 59a: Tavily answered a web_search through the OpenAI SDK {openai.__version__}; "
            "it was sent the key as a bearer and the advanced depth, and its answer reached the model",
            flush=True,
        )

        # --- 2. the address rule, under the default ----------------------------
        def mcp_tool(url: str, **extra: Any) -> dict[str, Any]:
            return {
                "type": "mcp",
                "server_label": "fixture",
                "server_url": url,
                "authorization": MCP_TOKEN,
                "headers": {"X-Row59": MCP_HEADER},
                **extra,
            }

        lan_url = f"http://{lan}:{ports['mcp']}/mcp"

        def refused(url: str, words: str) -> None:
            response = responses(tools=[mcp_tool(url, require_approval="never")])
            if response.status_code != 400 or words not in response.text:
                raise AddressCheckFailed(
                    f"{url} was not refused naming {words!r}: HTTP {response.status_code} "
                    f"{response.text[:400]}"
                )
            assert MCP_TOKEN not in response.text and MCP_HEADER not in response.text

        refused(f"https://{lan}:{ports['mcp']}/mcp", "private network")
        refused(f"https://127.0.0.1:{ports['fixture']}/mcp", "loopback")
        refused("https://169.254.169.254/mcp", "link-local")
        refused("https://localhost/mcp", "loopback")
        refused(lan_url, "plain http")
        assert client.get(base("mcp") + "/seen").json() == [], "the server was reached"
        print(
            f"PASS the default reach refused {lan} (this network), loopback, localhost, "
            "169.254.169.254 and plain http, each naming its rule; the server saw nothing",
            flush=True,
        )

        # --- 3. the owner's expert reach, through the console's path ------------
        turned = proxy("gateway", "PATCH", "/v1/config", json={"remoteMcp": "network"})
        assert turned.status_code == 200 and turned.json()["applied"] == ["remoteMcp"], turned.text
        schema = proxy("gateway", "GET", "/v1/config/schema").json()
        field = next(f for f in schema["fields"] if f["key"] == "remoteMcp")
        assert field["status"]["level"] == "warning", field
        assert field["enumLabels"][2] == "Internet and this network (expert)", field
        refused(f"https://127.0.0.1:{ports['fixture']}/mcp", "loopback")
        refused("https://169.254.169.254/mcp", "link-local")
        print(
            "PASS the owner chose Internet and this network through the proxy, with the "
            "warning beside it; loopback and the metadata address stay refused",
            flush=True,
        )

        # --- 4. a list and a call, whole and streamed --------------------------
        tool = mcp_tool(lan_url, require_approval="never")
        whole = sdk.responses.create(model=MODEL, input="Use the tool.", tools=[tool])
        kinds = [item.type for item in whole.output]
        assert kinds == ["mcp_list_tools", "mcp_call", "message"], kinds
        listed, called, _ = whole.output
        assert [t.name for t in listed.tools] == ["echo"], listed
        assert called.output == "ECHO: HELLO" and called.error is None, called
        assert whole.output_text == "FINAL: ECHO: HELLO", whole.output_text
        echoed = whole.model_dump()["tools"][0]
        assert echoed.get("authorization") is None and echoed.get("headers") is None, echoed
        assert MCP_TOKEN not in whole.model_dump_json() and MCP_HEADER not in whole.model_dump_json()
        server = client.get(base("mcp") + "/seen").json()
        methods = [s["method"] for s in server]
        assert "tools/list" in methods and "tools/call" in methods, methods
        assert all(s["headers"].get("authorization") == f"Bearer {MCP_TOKEN}" for s in server)
        assert all(s["headers"].get("x-row59") == MCP_HEADER for s in server)
        names, final = [], None
        for event in sdk.responses.create(
            model=MODEL, input="Use the tool.", tools=[tool], stream=True
        ):
            names.append(event.type)
            if event.type == "response.completed":
                final = event.response
        assert final is not None, names
        for wanted in (
            "response.mcp_list_tools.completed",
            "response.mcp_call.in_progress",
            "response.mcp_call.completed",
        ):
            assert wanted in names, (wanted, names)
        assert [i.type for i in final.output] == ["mcp_list_tools", "mcp_call", "message"]
        print(
            "PASS a list and a call round-trip whole and streamed (mcp_list_tools, mcp_call, "
            "the answer); the server saw the caller's token and header on every request",
            flush=True,
        )

        # --- 5. approvals ------------------------------------------------------------
        before = methods.count("tools/call")
        waiting = sdk.responses.create(
            model=MODEL, input="Use the tool.", tools=[mcp_tool(lan_url)]
        )
        kinds = [item.type for item in waiting.output]
        assert kinds == ["mcp_list_tools", "mcp_approval_request"], kinds
        asked = waiting.output[-1]
        calls = [s["method"] for s in client.get(base("mcp") + "/seen").json()]
        assert calls.count("tools/call") == before, "a call ran before it was approved"
        history = [
            {"role": "user", "content": "Use the tool."},
            *[item.model_dump(exclude_none=True) for item in waiting.output],
        ]
        approved = sdk.responses.create(
            model=MODEL,
            tools=[mcp_tool(lan_url)],
            input=[
                *history,
                {"type": "mcp_approval_response", "approval_request_id": asked.id, "approve": True},
            ],
        )
        assert [i.type for i in approved.output] == ["mcp_call", "message"], approved.output
        assert approved.output[0].approval_request_id == asked.id
        assert approved.output_text == "FINAL: ECHO: HELLO", approved.output_text
        calls = [s["method"] for s in client.get(base("mcp") + "/seen").json()]
        assert calls.count("tools/call") == before + 1
        forged = responses(
            tools=[mcp_tool(lan_url)],
            input=[
                {"role": "user", "content": "Use the tool."},
                {"type": "mcp_approval_response", "approval_request_id": "mcpr_forged", "approve": True},
            ],
        )
        assert forged.status_code == 400 and "mcpr_forged" in forged.text, forged.text
        calls = [s["method"] for s in client.get(base("mcp") + "/seen").json()]
        assert calls.count("tools/call") == before + 1
        print(
            "PASS approvals: the default asked and ran nothing; the answer ran the call once; "
            "an approval for an id the conversation does not carry was refused",
            flush=True,
        )
        sdk.close()

        # --- 6. the caller's credential is nowhere -----------------------------------
        def rows() -> list[dict]:
            return proxy("gateway", "GET", "/v1/metrics/requests").json()["requests"]

        wait(lambda: any(r.get("mcpCalls") for r in rows()), "a metrics row with mcpCalls")
        recorded = json.dumps(rows())
        assert MCP_TOKEN not in recorded and MCP_HEADER not in recorded
        leaked = [
            str(path)
            for path in directory.rglob("*")
            if path.is_file()
            and "pycache" not in path.parts
            and path.parent.name != "mcp"
            and (MCP_TOKEN.encode() in path.read_bytes() or MCP_HEADER.encode() in path.read_bytes())
        ]
        assert not leaked, f"the caller's credential is on disk: {leaked}"
        print(
            "PASS the caller's token and header are in no log (gateway and tool-driver at "
            "DEBUG), no metrics row or file and no config; the metrics row has mcpCalls",
            flush=True,
        )
    finally:
        (directory / "agent/stop").touch()
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()
        client.close()


def run(sabotage: bool) -> None:
    temporary = HERE.parent.parent / ".codex-tmp"
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="row59-", dir=temporary) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory, sabotage=sabotage)
        except BaseException as exc:
            if sabotage and isinstance(exc, AddressCheckFailed):
                raise
            for log in directory.glob("*/process.log"):
                print(log, log.read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["fixture", "mcp", "model", "tool", "gateway"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--sabotage",
        action="store_true",
        help="after the run, run again with the address check disabled; pass only if it fails",
    )
    args = parser.parse_args()
    if args.serve:
        assert args.port not in range(8079, 8084), "default ports are forbidden"
        serve(args.serve, args.directory, args.port, args.host, args.sabotage)
        return 0
    run(sabotage=False)
    if args.sabotage:
        try:
            run(sabotage=True)
        except AddressCheckFailed as caught:
            print(f"PASS sabotage: with the address check disabled the run fails: {caught}")
            return 0
        raise AssertionError("with the address check disabled, the run still passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
