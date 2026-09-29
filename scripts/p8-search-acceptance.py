"""P8: web search run by this install, through real signed processes.

A control root, an enrolled agent, a gateway, two inference-drivers and two
search accounts, all started here with isolated state and ports. **The
search accounts are tool-drivers the agent spawns itself** (`POST
/v1/components`, kind `tool-driver`), configured through the agent's proxy
by name -- the path the console takes -- so supervision, the env prefix,
the master key that seals a Brave key and the proxy are all exercised.

* `model` -- the real inference-driver (`openai_compat_custom`, local) over
  a fixture playing a local engine's OpenAI chat API **with tool calling**:
  offered a `web_search` function it calls it; handed the results it
  answers citing the first address; offered Claude Code's own `WebSearch`
  it calls that, and answers once the result comes back.
* `router` -- the real `openrouter` provider over a fixture whose model
  lists `web_search_options`: a backend that searches itself, which must
  be forwarded the request natively and never searched for twice. It also
  lists one image model, which answers P8e's `image_generation` tool for
  the local model: the chat model is told in words and the caller gets the
  image.
* `searx` -- a tool-driver over a fixture playing SearXNG with the answer
  measured from a real instance on 2026-09-29, and able to answer as an
  instance with JSON output switched off (a 403 with an HTML body).
* `brave` -- a tool-driver over a fixture playing Brave's documented API,
  checking the subscription token.

The OpenAI and Anthropic SDKs make the requests, unchanged, from their own
interpreter: this one if it has both, else `$EP_SDK_PYTHON`.

`--clients` adds the two clients P8 exists for, as they are installed on
this box: **Claude Code**'s WebSearch and **Codex**'s live search, each
pointed at the gateway with an isolated config directory.

`--searxng URL` re-points the SearXNG account at a real instance (on this
box, the one started in WSL for P8-0) for a last search whose sources are
real.

Run in an environment containing every Python component, the tool-driver
included (on this box, `agent/.venv`). Logs and state stay in a temporary
tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import yaml
from fastapi import Request

NODE_NAME = "p8-agent"
MODEL = "p8-local"
ROUTED = "acme/searcher"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEARXNG_ANSWER = FIXTURES / "searxng-answer.json"
BRAVE_KEY = "BSA-p8-fixture-subscription-token"
ANSWER_MARK = "P8-FIXTURE-ANSWER"
FINAL_MARK = "P8-FINAL-ANSWER"
SECRET_QUERY = "zebra-quartz-canary"
#: P8e: the image model the router account lists, and what the model asks for.
PAINTER = "acme/painter"
IMAGE_MARK = "P8E-IMAGE-ANSWER"
IMAGE_PROMPT = "a red fox in snow, walrus-opal-canary"
#: A 1x1 PNG, the image the fixture makes.
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

SDK_SNIPPET = r"""
import json, sys, warnings
warnings.simplefilter("ignore")
import openai, anthropic
args = json.loads(sys.argv[1])
oa = openai.OpenAI(base_url=args["base"] + "/v1", api_key=args["key"], max_retries=0, timeout=120)
an = anthropic.Anthropic(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=120)
out = []
for job in args["jobs"]:
    kind = job.pop("kind")
    try:
        if kind == "chat":
            r = oa.chat.completions.create(**job)
            m = r.choices[0].message
            out.append({"status": 200, "content": m.content,
                        "annotations": [a.model_dump() for a in (m.annotations or [])],
                        "extra": (r.model_extra or {}).get("x_eugene_plexus")})
        elif kind == "chat_stream":
            text, cites, extra = [], [], None
            for chunk in oa.chat.completions.create(stream=True, **job):
                for c in chunk.choices:
                    if c.delta.content:
                        text.append(c.delta.content)
                    for a in (c.delta.model_extra or {}).get("annotations") or []:
                        cites.append(a)
                extra = (chunk.model_extra or {}).get("x_eugene_plexus") or extra
            out.append({"status": 200, "content": "".join(text), "annotations": cites, "extra": extra})
        elif kind == "responses":
            r = oa.responses.create(**job)
            out.append({"status": 200, "output": [i.model_dump() for i in r.output],
                        "text": r.output_text})
        elif kind == "responses_stream":
            names, final = [], None
            with oa.responses.stream(**job) as stream:
                for event in stream:
                    names.append(event.type)
                final = stream.get_final_response()
            out.append({"status": 200, "events": names, "output": [i.model_dump() for i in final.output]})
        elif kind == "messages":
            r = an.messages.create(**job)
            out.append({"status": 200, "content": [b.model_dump() for b in r.content],
                        "usage": r.usage.model_dump(), "stop": r.stop_reason})
        elif kind == "messages_stream":
            names = []
            with an.messages.stream(**job) as stream:
                for event in stream:
                    names.append(event.type + ":" + getattr(getattr(event, "content_block", None), "type", ""))
                final = stream.get_final_message()
            out.append({"status": 200, "events": names, "content": [b.model_dump() for b in final.content],
                        "usage": final.usage.model_dump()})
    except (openai.APIStatusError, anthropic.APIStatusError) as e:
        out.append({"status": e.status_code, "error": str(e.message)})
out.append({"sdk": {"openai": openai.__version__, "anthropic": anthropic.__version__}})
print(json.dumps(out))
"""


def sdk_python() -> str:
    if importlib.util.find_spec("openai") and importlib.util.find_spec("anthropic"):
        return sys.executable
    path = os.environ.get("EP_SDK_PYTHON")
    if path:
        return path
    raise SystemExit(
        "The OpenAI and Anthropic Python SDKs are needed: pip install openai==3.20.0 anthropic "
        "here, or set EP_SDK_PYTHON to an interpreter that has both."
    )


# --------------------------------------------------------------------------- #
# The fixture: a local engine that calls tools, SearXNG, Brave, OpenRouter
# --------------------------------------------------------------------------- #


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)\]]+", text or "")
    return match.group(0) if match else None


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def model_turn(body: dict) -> tuple[str | None, list[dict] | None]:
    """What the scripted local model says to one chat request.

    It reads the turn the way a model does: a tool result since its own
    last call is something to answer from, not a reason to call again.
    **Not "the last message is the tool result"**: Claude Code puts a
    reminder in the same user turn as the tool result, so the tool message
    is followed by user text, and a script keyed on the last message
    called WebSearch forever (found by the first `--clients` run).
    """
    messages = body.get("messages") or []
    tools = [t.get("function", {}).get("name") for t in body.get("tools") or []]
    last = messages[-1] if messages else {}
    search = next((n for n in tools if n in ("web_search", "eugene_web_search")), None)
    called = max((i for i, m in enumerate(messages) if m.get("role") == "assistant" and m.get("tool_calls")),
                 default=-1)
    answered = [m for m in messages[called + 1:] if m.get("role") == "tool"] if called >= 0 else []
    result = _message_text(answered[-1]) if answered else ""
    if answered and search and result.startswith("Web search results"):
        url = _first_url(result)
        return f"{ANSWER_MARK}: Eugene Plexus is a control plane. Source: [the page]({url}).", None
    if answered and "could not be run" in result:
        return f"{ANSWER_MARK}: the search failed -- {result[:300]}", None
    if answered and "WebSearch" in tools:
        # Claude Code's main loop, handed its WebSearch result.
        return f"{FINAL_MARK}: found {_first_url(result)}", None
    # P8e: offered image_generation, it makes one; told it is made, it says so.
    if answered and result.startswith("An image was made"):
        return f"{IMAGE_MARK}: your image is ready ({len(result)} characters told).", None
    if answered and "could not be made" in result:
        return f"{IMAGE_MARK}: the image failed -- {result[:300]}", None
    if "image_generation" in tools and not search and last.get("role") == "user":
        return None, [{"name": "image_generation", "arguments": {"prompt": IMAGE_PROMPT}}]
    if search and last.get("role") == "user":
        # The person's words, not Codex's environment block: the gateway
        # joins Codex's two user messages, and that block comes first.
        asked = re.sub(r"<environment_context>.*?</environment_context>", "", _message_text(last),
                       flags=re.S).strip()
        query = asked.split("query:", 1)[1].strip() if "query:" in asked else asked[:80]
        return None, [{"name": search, "arguments": {"query": query}}]
    if "WebSearch" in tools:
        # Claude Code's main loop: it has a WebSearch tool of its own, which
        # it runs as a separate request with the server tool.
        return None, [{"name": "WebSearch", "arguments": {"query": "eugene plexus"}}]
    return "P8-PLAIN: no search tool was offered.", None


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

        app = FastAPI()
        state = {"searx": "ok", "counts": {}, "seen": {}}
        answer = json.loads(SEARXNG_ANSWER.read_text(encoding="utf-8"))

        def count(name: str, body: object = None) -> None:
            state["counts"][name] = state["counts"].get(name, 0) + 1
            if body is not None:
                state["seen"].setdefault(name, []).append(body)

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return state["counts"]

        @app.get("/seen")
        async def seen(name: str):
            return state["seen"].get(name, [])

        @app.post("/mode")
        async def mode(searx: str):
            state["searx"] = searx
            return {}

        # --- SearXNG, as measured -------------------------------------------
        @app.get("/searx/search")
        async def searx(request: Request):
            count("searx", dict(request.query_params))
            if state["searx"] == "json_off":
                return PlainTextResponse(
                    "<!doctype html><title>403 Forbidden</title><h1>Forbidden</h1>",
                    status_code=403,
                    media_type="text/html",
                )
            if request.query_params.get("format") != "json":
                return PlainTextResponse("<html>results</html>", media_type="text/html")
            return answer

        # --- Brave, as documented --------------------------------------------
        @app.get("/brave/res/v1/web/search")
        async def brave(request: Request):
            count("brave", dict(request.query_params))
            if request.headers.get("x-subscription-token") != BRAVE_KEY:
                return JSONResponse({"type": "ErrorResponse", "error": {"code": "SUBSCRIPTION_TOKEN_INVALID"}},
                                    status_code=401)
            return {"type": "search", "web": {"results": [
                {"title": "Brave result for <strong>eugene</strong>", "url": "https://brave.example/eugene",
                 "description": "From Brave's own index.", "page_age": "2026-09-01T00:00:00"}]}}

        # --- a local engine that calls tools ---------------------------------
        @app.get("/model/props")
        async def props():
            return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

        @app.get("/model/v1/models")
        async def models():
            return {"data": [{"id": MODEL, "object": "model"}]}

        @app.post("/model/v1/chat/completions")
        async def complete(request: Request):
            body = await request.json()
            count("model", {"tools": [t.get("function", {}).get("name") for t in body.get("tools") or []],
                            "tool_choice": body.get("tool_choice"),
                            "roles": [m.get("role") for m in body.get("messages") or []],
                            "last": _message_text((body.get("messages") or [{}])[-1]),
                            "web_search_options": body.get("web_search_options")})
            text, calls = model_turn(body)
            tool_calls = [
                {"id": f"call_{secrets.token_hex(4)}", "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                for c in calls or []
            ]
            finish = "tool_calls" if tool_calls else "stop"
            usage = {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
            if body.get("stream"):
                async def frames():
                    if text:
                        for piece in (text[: len(text) // 2], text[len(text) // 2:]):
                            yield "data: " + json.dumps({"model": MODEL, "choices": [
                                {"index": 0, "delta": {"content": piece}, "finish_reason": None}]}) + "\n\n"
                    for index, call in enumerate(tool_calls):
                        args = call["function"]["arguments"]
                        yield "data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": {"tool_calls": [
                            {"index": index, "id": call["id"], "type": "function",
                             "function": {"name": call["function"]["name"], "arguments": args[:6]}}]},
                            "finish_reason": None}]}) + "\n\n"
                        yield "data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": {"tool_calls": [
                            {"index": index, "function": {"arguments": args[6:]}}]}, "finish_reason": None}]}) + "\n\n"
                    yield "data: " + json.dumps({"model": MODEL, "choices": [
                        {"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}) + "\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(frames(), media_type="text/event-stream")
            return {"model": MODEL, "usage": usage, "choices": [{"index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": text, "tool_calls": tool_calls or None}}]}

        # --- OpenRouter, a model that searches itself --------------------------
        @app.get("/v1/models/user")
        async def listing():
            return {"data": [{
                "id": ROUTED, "name": ROUTED, "context_length": 32768,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                "supported_parameters": ["max_tokens", "temperature", "tools", "tool_choice",
                                         "web_search_options"],
            }, {
                # An image model is listed here and described on /images/models (P4, measured).
                "id": PAINTER, "name": PAINTER, "context_length": 4096,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
                "supported_parameters": [],
            }]}

        # --- OpenRouter's image model, for P8e's image_generation tool ------
        @app.get("/v1/images/models")
        async def images():
            return {"data": [{"id": PAINTER, "supports_streaming": False, "supported_parameters": {
                "output_format": {"type": "enum", "values": ["png", "jpeg"]},
                "n": {"type": "range", "min": 1, "max": 1},
                "input_references": {"type": "range", "min": 0, "max": 0},
            }}]}

        @app.post("/v1/images/generations")
        async def paint(request: Request):
            body = await request.json()
            count("painter", body)
            if "[refuse]" in body.get("prompt", ""):
                return JSONResponse({"error": {"message": "the provider refused this prompt", "code": 400}},
                                    status_code=400)
            return {"created": int(time.time()), "data": [{"b64_json": PNG_B64, "media_type": "image/png"}],
                    "usage": {"prompt_tokens": 6, "completion_tokens": 4096, "total_tokens": 4102}}

        @app.get("/v1/videos/models")
        async def no_videos():
            return {"data": []}

        @app.post("/v1/chat/completions")
        async def routed(request: Request):
            body = await request.json()
            count("router", {"web_search_options": body.get("web_search_options"),
                             "tools": [t.get("function", {}).get("name") for t in body.get("tools") or []]})
            cite = {"type": "url_citation", "url_citation": {"url": "https://provider.example/source",
                                                             "title": "Provider's source",
                                                             "start_index": 0, "end_index": 0}}
            message = {"role": "assistant", "content": "Searched by the provider itself.",
                       "annotations": [cite] if "web_search_options" in body else None}
            return {"model": ROUTED, "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}

    elif kind in ("model", "router"):
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(settings=Settings(config_file=directory / "driver.yaml", **bootstrap))
    elif kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(config_file=directory / "agent.yaml", default_topology=False, bind_port=port)
        )
    elif kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(
            settings=Settings(
                config_file=directory / "gateway.yaml",
                metrics_file=directory / "metrics.sqlite3",
                **bootstrap,
            )
        )
    else:
        raise SystemExit(f"unknown process kind {kind!r}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def exercise(directory: Path, *, clients: bool, searxng: str | None, browser: bool = False) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ["control", "agent", "gateway", "fixture", "model", "router", "searx", "brave", "dead"]
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(zip(names, [sock.getsockname()[1] for sock in sockets], strict=True))
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs = []
    client = httpx.Client(timeout=120, trust_env=False)
    passphrase = secrets.token_urlsafe(24)
    passed = 0
    sdk = sdk_python()

    def ok(message: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {message}", flush=True)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method, url(name) + path,
            headers={"Authorization": "Bearer " + token} if token else None, **kwargs,
        )

    def write(name, filename, data):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data), encoding="utf-8",
        )

    def wait(check, label, seconds=40):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as e:
                last = e
            time.sleep(0.2)
        raise AssertionError(f"timed out: {label} ({last!r})")

    def start(name, extra_env=None):
        work = directory / name
        work.mkdir(exist_ok=True)
        output = (work / "process.log").open("ab")
        logs.append(output)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env.pop("OPENAI_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env.update(extra_env or {})
        processes[name] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name,
             "--directory", str(work), "--port", str(ports[name])],
            cwd=work, env=env, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        response.raise_for_status()
        return response.json()["sessionToken"]

    def counts():
        return call("fixture", "GET", "/stats").json()

    def seen(name):
        return call("fixture", "GET", "/seen", params={"name": name}).json()

    def by_sdk(token, jobs):
        result = subprocess.run(
            [sdk, "-c", SDK_SNIPPET, json.dumps({"base": url("gateway"), "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=600,
            env={k: v for k, v in os.environ.items()
                 if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")},
        )
        assert result.returncode == 0, result.stderr[-3000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    def proxy(target, method, path, token, **kwargs):
        return call("agent", method, f"/api/proxy/{target}{path}", token, **kwargs)

    try:
        # --- a signed one-node install ---------------------------------------
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        root_session = login("control")
        write("agent", "agent.yaml", {
            "firstRunComplete": True, "advertiseUrl": url("agent"),
            "securityMode": "prompt_on_startup", "components": [],
        })
        start("agent")
        call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        standalone = login("agent")
        join = call("control", "POST", "/v1/nodes/join-token", root_session, json={"grants": ["gateway"]})
        join.raise_for_status()
        call("agent", "POST", "/v1/node/enroll", standalone, json={
            "controlUrl": url("control"), "token": join.json()["token"], "name": NODE_NAME,
        }).raise_for_status()
        operator = login("agent")

        agent_dir = directory / "agent"
        store = NodeIdentityStore(agent_dir / "node.yaml")
        store.load()
        trust = NodeTrust(store, agent_dir / "trust_bundle.json")
        trust.load()

        def bootstrap(sub):
            token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
            return {
                "agent_url": url("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        def driver(name, config, env):
            write(name, "bootstrap.json", bootstrap("inference-driver"))
            write(name, "driver.yaml", config)
            start(name, env)
            call("agent", "POST", "/v1/components", operator, json={
                "name": name, "kind": "inference-driver", "url": url(name),
            }).raise_for_status()

        start("fixture")
        driver("model", {"provider": "openai_compat_custom", "baseUrl": url("fixture") + "/model",
                         "modelId": MODEL, "backendLocality": "local"}, {})
        driver("router", {"provider": "openrouter", "baseUrl": url("fixture")},
               {"OPENAI_API_KEY": "fixture-not-a-key"})
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2})
        start("gateway")

        # --- 1. two search accounts, spawned and configured by the agent ------
        for name in ("searx", "brave"):
            call("agent", "POST", "/v1/components", operator, json={
                "name": name, "kind": "tool-driver", "url": url(name),
                "spawn": {"configFile": f"{name}.yaml"},
            }).raise_for_status()

        def running(name):
            listed = call("agent", "GET", "/v1/components", operator).json()["components"]
            entry = next(c for c in listed if c["name"] == name)
            return entry["status"] == "running" and call(name, "GET", "/healthz").status_code == 200

        for name in ("searx", "brave"):
            wait(lambda name=name: running(name), f"the agent runs the {name} tool-driver")
        ok("the agent spawns two tool-drivers from its own topology (kind tool-driver)")

        # Configured through the agent's proxy BY NAME -- the console's path.
        patched = proxy("searx", "PATCH", "/v1/config", operator,
                        json={"provider": "searxng", "baseUrl": url("fixture") + "/searx", "probeMinutes": 0})
        assert patched.status_code == 200 and patched.json()["applied"], patched.text
        test = proxy("searx", "POST", "/v1/config/test", operator).json()
        assert test["ok"] is True and "searxng answered" in test["summary"], test
        info = proxy("searx", "GET", "/v1/info", operator).json()
        assert info["tools"] == ["web_search"] and info["egress"] == "internet", info
        ok(f"the SearXNG account is set up through the proxy by name; its Test ran a real search ({test['summary']})")

        brave_patch = proxy("brave", "PATCH", "/v1/config", operator,
                            json={"provider": "brave", "baseUrl": url("fixture") + "/brave", "apiKey": BRAVE_KEY})
        assert brave_patch.status_code == 200, brave_patch.text
        assert proxy("brave", "GET", "/v1/config", operator).json()["apiKey"] == "<redacted>"
        leaked = [p for p in directory.rglob("*") if p.is_file() and p.suffix in (".yaml", ".json")
                  and BRAVE_KEY in p.read_text(encoding="utf-8", errors="ignore")]
        assert not leaked, f"the Brave key is on disk in plaintext: {leaked}"
        assert proxy("brave", "POST", "/v1/config/test", operator).json()["ok"] is True
        ok("the Brave key is sealed at rest (no plaintext in any file under the install) and redacted on read")

        def mint(name, **limits):
            response = call("agent", "POST", "/v1/auth/client-keys", operator, json={
                "name": name, "limits": {"allowedModels": None, "requestsPerMinute": 1000, **limits},
            })
            response.raise_for_status()
            return response.json()["token"]

        key = mint("Everything")
        wait(lambda: {MODEL, f"router/{ROUTED}"} <= {
            m["id"] for m in call("gateway", "GET", "/v1/models", key).json().get("data", [])
        }, "the models are routable")

        def searched_once():
            response = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": MODEL, "messages": [{"role": "user", "content": "warm up"}],
                "web_search_options": {}})
            return response.status_code == 200
        wait(searched_once, "the gateway has found the search accounts")

        # --- 2. chat, through the OpenAI SDK --------------------------------
        before = counts().get("searx", 0)
        chat, streamed, sdk_versions = by_sdk(key, [
            {"kind": "chat", "model": MODEL, "web_search_options": {},
             "messages": [{"role": "user", "content": "What is Eugene Plexus?"}]},
            {"kind": "chat_stream", "model": MODEL, "web_search_options": {},
             "messages": [{"role": "user", "content": "What is Eugene Plexus?"}]},
        ])
        first_url = json.loads(SEARXNG_ANSWER.read_text(encoding="utf-8"))["results"][0]["url"]
        assert chat["status"] == 200, chat
        assert chat["content"].startswith(ANSWER_MARK) and first_url in chat["content"], chat
        assert [a["url_citation"]["url"] for a in chat["annotations"]] == [first_url], chat["annotations"]
        assert chat["extra"]["web_searches"] == 1 and chat["extra"]["attempts"] == 1, chat["extra"]
        told = [s for s in seen("model") if s["roles"] and s["roles"][-1] == "tool"]
        assert told and first_url in told[-1]["last"] and "Cite the pages" in told[-1]["last"], told[-1:]
        # The first turn of a search: the user's words last, the tool offered.
        asked = [s for s in seen("model") if s["tools"] == ["web_search"] and s["roles"][-1] == "user"]
        assert asked and asked[-1]["tool_choice"] == "required", asked[-1:]
        assert streamed["content"].startswith(ANSWER_MARK), streamed
        assert streamed["annotations"] and streamed["annotations"][0]["url_citation"]["url"] == first_url
        assert counts()["searx"] - before == 2
        ok(f"chat via the OpenAI SDK {sdk_versions['sdk']['openai']}: the local model searched, answered "
           "citing the page, url_citation annotations, web_searches 1, attempts 1; streamed too")

        # --- 3. Responses, through the SDK, and Codex's default --------------
        responses, streamed = by_sdk(key, [
            {"kind": "responses", "model": MODEL, "input": "What is Eugene Plexus?",
             "tools": [{"type": "web_search"}]},
            {"kind": "responses_stream", "model": MODEL, "input": "What is Eugene Plexus?",
             "tools": [{"type": "web_search"}]},
        ])[:2]
        kinds = [i["type"] for i in responses["output"]]
        assert kinds == ["web_search_call", "message"], kinds
        search_item = responses["output"][0]
        assert search_item["status"] == "completed" and search_item["action"]["type"] == "search"
        assert first_url in [s["url"] for s in search_item["action"]["sources"]]
        annotations = responses["output"][1]["content"][0]["annotations"]
        assert annotations and annotations[0]["url"] == first_url, annotations
        for name in ("response.web_search_call.in_progress", "response.web_search_call.searching",
                     "response.web_search_call.completed", "response.output_text.annotation.added"):
            assert name in streamed["events"], (name, streamed["events"])
        assert [i["type"] for i in streamed["output"]] == ["web_search_call", "message"]
        ok("Responses via the SDK: a web_search_call item with its sources before the cited message; "
           "the stream says in_progress, searching, completed")

        before = counts().get("searx", 0)
        codex_default = call("gateway", "POST", "/v1/responses", key, json={
            "model": MODEL, "input": "hello",
            "tools": [{"type": "web_search", "external_web_access": False}]})
        assert codex_default.status_code == 200, codex_default.text
        assert "external_web_access is false" in codex_default.headers["x-eugene-plexus-web-search"]
        assert "tools.web_search" in codex_default.headers["x-eugene-plexus-ignored-settings"]
        assert counts().get("searx", 0) == before
        ok("Codex's default (external_web_access false) is removed and the reason given; nothing searched")

        # --- 4. messages, through the Anthropic SDK ---------------------------
        claude_search = {
            "model": MODEL, "max_tokens": 1000,
            "system": "You are an assistant for performing a web search tool use",
            "messages": [{"role": "user", "content": "Perform a web search for the query: eugene plexus"}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        }
        batch, stream = by_sdk(key, [
            {"kind": "messages", **claude_search},
            {"kind": "messages_stream", **claude_search},
        ])[:2]
        assert batch["status"] == 200, batch
        assert [b["type"] for b in batch["content"]] == ["server_tool_use", "web_search_tool_result", "text"]
        assert batch["content"][0]["input"] == {"query": "eugene plexus"}
        assert batch["content"][1]["content"][0]["url"] == first_url
        assert batch["usage"]["server_tool_use"]["web_search_requests"] == 1, batch["usage"]
        assert stream["status"] == 200, stream
        starts = [e for e in stream["events"] if e.startswith("content_block_start")]
        assert starts == ["content_block_start:server_tool_use",
                          "content_block_start:web_search_tool_result",
                          "content_block_start:text"], starts
        assert [b["type"] for b in stream["content"]] == ["server_tool_use", "web_search_tool_result", "text"]
        ok(f"messages via the Anthropic SDK {sdk_versions['sdk']['anthropic']}: Claude Code's WebSearch "
           "request answered with server_tool_use, web_search_tool_result and text; streamed in order")

        # --- 5. what a key may do ------------------------------------------------
        no_tools = mint("No tools", allowedTools=[])
        refused = by_sdk(no_tools, [{"kind": "messages", **claude_search}])[0]
        assert refused["status"] == 400 and "tool scope" in refused["error"], refused
        local = mint("Local only", localOnly=True)
        kept_local = call("gateway", "POST", "/v1/responses", local, json={
            "model": MODEL, "input": "hello", "tools": [{"type": "web_search"}]})
        assert kept_local.status_code == 200, kept_local.text
        assert "local-only" in kept_local.headers["x-eugene-plexus-web-search"]
        ok("a key denied web_search is refused naming its tool scope; a local-only key never searches")

        # --- 6. a search account that fails, and the one behind it -------------
        call("fixture", "POST", "/mode", params={"searx": "json_off"})
        failed = call("gateway", "POST", "/v1/chat/completions", key, json={
            "model": MODEL, "messages": [{"role": "user", "content": "q"}], "web_search_options": {}})
        # SearXNG refused; Brave answered instead (a second account is tried
        # when the first could not do the job).
        assert failed.status_code == 200, failed.text
        assert "brave.example" in failed.json()["choices"][0]["message"]["content"], failed.json()
        wait(lambda: proxy("searx", "GET", "/healthz", operator).json()["details"].get("code") == "json_disabled",
             "the SearXNG account reports json_disabled")
        health = proxy("searx", "GET", "/healthz", operator).json()
        assert health["status"] == "degraded" and "search.formats" in health["details"]["error"], health
        ok("SearXNG with JSON output off: its health names search.formats, and Brave answered the search")

        call("agent", "DELETE", "/v1/components/brave", operator).raise_for_status()
        wait(lambda: not any(
            m for m in [call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": MODEL, "messages": [{"role": "user", "content": "q"}],
                "web_search_options": {}}).json()["choices"][0]["message"]["content"]]
            if "brave.example" in m), "the gateway no longer uses the removed Brave account", 30)
        alone = call("gateway", "POST", "/v1/chat/completions", key, json={
            "model": MODEL, "messages": [{"role": "user", "content": "q"}], "web_search_options": {}})
        assert alone.status_code == 200, alone.text
        content = alone.json()["choices"][0]["message"]["content"]
        assert "the search failed" in content and "search.formats" in content, content
        ok("with only the failing account left, the model is told why the search failed and still answers (200)")
        call("fixture", "POST", "/mode", params={"searx": "ok"})

        # --- 7. a backend that searches itself -----------------------------------
        before = counts().get("searx", 0)
        native = call("gateway", "POST", "/v1/chat/completions", key, json={
            "model": f"router/{ROUTED}", "messages": [{"role": "user", "content": "q"}],
            "web_search_options": {"search_context_size": "low"}})
        assert native.status_code == 200, native.text
        routed = seen("router")[-1]
        assert routed["web_search_options"] == {"search_context_size": "low"}, routed
        assert "web_search" not in routed["tools"]
        assert counts().get("searx", 0) == before, "forwarded, not run twice"
        ok("a model whose listing names web_search_options is forwarded the request natively, never searched for")

        # --- 7b. image_generation on /v1/responses (P8e) --------------------------
        wait(lambda: f"router/{PAINTER}" in {
            m["id"] for m in call("gateway", "GET", "/v1/models", key).json().get("data", [])
        }, "the image model is routable")
        drawn, streamed = by_sdk(key, [
            {"kind": "responses", "model": MODEL, "input": "Draw me a fox.",
             "tools": [{"type": "image_generation", "output_format": "png"}]},
            {"kind": "responses_stream", "model": MODEL, "input": "Draw me a fox.",
             "tools": [{"type": "image_generation"}]},
        ])[:2]
        assert drawn["status"] == 200, drawn
        assert [i["type"] for i in drawn["output"]] == ["image_generation_call", "message"], drawn["output"]
        item = drawn["output"][0]
        assert item["status"] == "completed" and item["result"] == PNG_B64, item
        assert item["revised_prompt"] == IMAGE_PROMPT and item["output_format"] == "png", item
        assert drawn["text"].startswith(IMAGE_MARK), drawn["text"]
        painted = seen("painter")
        assert painted and painted[-1]["prompt"] == IMAGE_PROMPT and painted[-1]["model"] == PAINTER, painted[-1:]
        told = [s for s in seen("model") if s["roles"] and s["roles"][-1] == "tool" and "An image" in s["last"]]
        assert told and PNG_B64 not in told[-1]["last"], "the model is told in words, never given the bytes"
        for name in ("response.image_generation_call.in_progress", "response.image_generation_call.generating",
                     "response.image_generation_call.completed"):
            assert name in streamed["events"], (name, streamed["events"])
        assert [i["type"] for i in streamed["output"]] == ["image_generation_call", "message"]
        assert streamed["output"][0]["result"] == PNG_B64
        ok("image_generation via the SDK: a local model made an image through the router's image model; "
           "the caller got an image_generation_call with the bytes, the model only words; streamed "
           "in_progress, generating, completed")

        search_only = mint("Search only", allowedTools=["web_search"])
        refused = by_sdk(search_only, [{"kind": "responses", "model": MODEL, "input": "Draw me a fox.",
                                        "tools": [{"type": "image_generation"}]}])[0]
        assert refused["status"] == 400 and "tool scope" in refused["error"], refused
        before = len(seen("painter"))
        failed = by_sdk(key, [{"kind": "responses", "model": MODEL, "input": "Draw me a fox.",
                               "tools": [{"type": "image_generation", "model": "no-such-model"}]}])[0]
        assert failed["status"] == 200, failed  # the one image model answers a model it does not serve
        assert len(seen("painter")) == before + 1
        ok("a key without image_generation in its tool scope is refused naming it; an unserved tool model "
           "falls back to the one image model there is")

        image_rows = []

        def images_recorded():
            image_rows[:] = [g for r in call("gateway", "GET", "/v1/metrics/requests", operator,
                                              params={"limit": 60}).json()["requests"]
                             for g in r.get("imageGenerations") or []]
            return len(image_rows) >= 2
        wait(images_recorded, "the image metrics rows")
        assert {g["provider"] for g in image_rows} == {f"router/{PAINTER}"}, image_rows
        assert all(g["tool"] == "image_generation" and g["outcome"] == "ok" for g in image_rows), image_rows
        raw = b"".join(p.read_bytes() for p in (directory / "gateway").glob("metrics.sqlite3*"))
        assert b"walrus-opal-canary" not in raw, "a prompt was kept"
        ok("metrics keep one imageGenerations row per image, with the image model, and no prompt text")

        # --- 8. metrics ---------------------------------------------------------------
        call("gateway", "POST", "/v1/chat/completions", key, json={
            "model": MODEL, "messages": [{"role": "user", "content": f"query: {SECRET_QUERY}"}],
            "web_search_options": {}}).raise_for_status()
        rows = []

        def recorded():
            rows[:] = call("gateway", "GET", "/v1/metrics/requests", operator,
                           params={"limit": 60}).json()["requests"]
            return any(r.get("webSearches") for r in rows)
        wait(recorded, "the metrics rows")
        versions = {s["version"] for r in rows for s in r.get("webSearches") or []}
        assert {"web_search_options", "web_search", "web_search_20250305"} <= versions, versions
        assert all(r["attempts"] == 1 for r in rows if r.get("webSearches")), "turns counted as a cascade"
        raw = b"".join(p.read_bytes() for p in (directory / "gateway").glob("metrics.sqlite3*"))
        assert SECRET_QUERY.encode() not in raw, "a query was kept"
        ok(f"metrics keep one row per search ({sorted(versions)}), no query text, turns not a cascade")

        # --- 9. the clients P8 exists for ------------------------------------------
        if clients:
            # Claude Code: its WebSearch is a request of its own with the server tool.
            config_dir = directory / "claude-config"
            config_dir.mkdir(exist_ok=True)
            (config_dir / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("ANTHROPIC_", "CLAUDE_", "EUGENE_PLEXUS_", "OPENAI_"))}
            env.update({"CLAUDE_CONFIG_DIR": str(config_dir), "ANTHROPIC_BASE_URL": url("gateway"),
                        "ANTHROPIC_AUTH_TOKEN": key, "DISABLE_AUTOUPDATER": "1"})
            claude = shutil.which("claude")
            assert claude, "claude is not on PATH"
            ran = subprocess.run(
                [claude, "-p", "Search the web for eugene plexus and tell me what it is",
                 "--model", MODEL, "--allowedTools", "WebSearch"],
                capture_output=True, text=True, timeout=300, env=env, stdin=subprocess.DEVNULL,
                cwd=directory,
            )
            (directory / "claude-code.out").write_text(ran.stdout + "\n---\n" + ran.stderr, encoding="utf-8")
            assert ran.returncode == 0, ran.stdout[-2000:] + ran.stderr[-2000:]
            assert FINAL_MARK in ran.stdout or first_url in ran.stdout, ran.stdout[-2000:]
            version = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()
            ok(f"Claude Code ({version}) ran WebSearch on a local model through this install and answered")

            # Codex: live search.
            codex_home = directory / "codex-home"
            codex_home.mkdir(exist_ok=True)
            (codex_home / "config.toml").write_text(
                f'model = "{MODEL}"\nmodel_provider = "ep"\nweb_search = "live"\n'
                "[model_providers.ep]\n"
                'name = "eugene"\n'
                f'base_url = "{url("gateway")}/v1"\n'
                'env_key = "EP_TEST_KEY"\n'
                'wire_api = "responses"\n',
                encoding="utf-8",
            )
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("OPENAI_", "CODEX_", "EUGENE_PLEXUS_"))}
            env.update({"CODEX_HOME": str(codex_home), "EP_TEST_KEY": key})
            codex = shutil.which("codex")
            assert codex, "codex is not on PATH"
            before = counts().get("searx", 0)
            ran = subprocess.run(
                [codex, "exec", "--skip-git-repo-check", "--ephemeral",
                 "Search the web for eugene plexus and tell me what it is"],
                capture_output=True, text=True, timeout=300, env=env, stdin=subprocess.DEVNULL,
                cwd=directory,
            )
            (directory / "codex.out").write_text(ran.stdout + "\n---\n" + ran.stderr, encoding="utf-8")
            assert ran.returncode == 0, ran.stdout[-2000:] + ran.stderr[-2000:]
            assert ANSWER_MARK in ran.stdout, ran.stdout[-2000:] + ran.stderr[-1500:]
            assert counts().get("searx", 0) > before, "Codex's live search never reached the account"
            # Codex prints each web_search_call item as `web search: <query>`
            # (measured): the query must be on the item from the moment it is
            # added, or the first line is empty.
            shown = [line for line in (ran.stdout + ran.stderr).splitlines()
                     if line.startswith("web search:")]
            assert shown and all(line.strip() != "web search:" for line in shown), shown
            assert any("Search the web for eugene plexus" in line for line in shown), shown
            version = subprocess.run([codex, "--version"], capture_output=True, text=True).stdout.strip()
            ok(f"Codex ({version}) with web_search = \"live\" searched through this install and answered; "
               "it accepts the web_search_call items")

        # --- 10. the console, in a real browser ---------------------------------------
        if browser:
            import eugene_plexus_ui

            static = Path(eugene_plexus_ui.static_dir())
            bundle = "".join(p.read_text(encoding="utf-8", errors="ignore")
                             for p in static.rglob("*.js"))
            assert "search-add-button" in bundle, (
                f"the UI this agent serves ({static}) has no search-account page: run "
                "`npm run build:python` in ../ui first"
            )
            # The browser reaches the gateway through the agent's proxy, which
            # finds it in the agent's topology.
            call("agent", "POST", "/v1/components", operator, json={
                "name": "gateway", "kind": "gateway", "url": url("gateway")}).raise_for_status()
            results_file = directory / "browser-results.json"
            npx = "npx.cmd" if os.name == "nt" else "npx"
            run = subprocess.run(
                [npx, "playwright", "test", "e2e/search-account.spec.ts", "--reporter=line"],
                cwd=Path(__file__).resolve().parents[2] / "ui",
                env={**os.environ, "EP_UI_URL": url("agent"), "EP_PASSPHRASE": passphrase,
                     "EP_SEARX_URL": url("fixture") + "/searx", "EP_MODEL": MODEL,
                     "EP_ANSWER_MARK": ANSWER_MARK, "EP_RESULTS_FILE": str(results_file)},
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
            )
            found = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
            for step in ("add", "tree", "playground"):
                assert found.get(step, {}).get("ok"), (
                    step, found, "\n".join((run.stdout + run.stderr).splitlines()[-30:]))
            ok(f"in Chrome: the page added a SearXNG account and its test search ran; the tree lists "
               f"it under Backends; the playground searched and showed the source "
               f"({found['playground']['detail']})")

        # --- 11. a real SearXNG ------------------------------------------------------
        if searxng:
            proxy("searx", "PATCH", "/v1/config", operator, json={"baseUrl": searxng}).raise_for_status()
            real = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": MODEL, "messages": [{"role": "user", "content": "SearXNG metasearch engine"}],
                "web_search_options": {}})
            assert real.status_code == 200, real.text
            cited = real.json()["choices"][0]["message"].get("annotations") or []
            assert cited and "brave.example" not in cited[0]["url_citation"]["url"], real.json()
            fixture_urls = {r["url"] for r in json.loads(SEARXNG_ANSWER.read_text(encoding="utf-8"))["results"]}
            assert cited[0]["url_citation"]["url"] not in fixture_urls, "that was the fixture, not the instance"
            ok(f"a real SearXNG at {searxng} answered; the model cited {cited[0]['url_citation']['url']}")

        print(f"\n{passed} checks passed.", flush=True)
    finally:
        for name, process in list(processes.items()):
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for output in logs:
            output.close()
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--clients", action="store_true", help="also run Claude Code and Codex")
    parser.add_argument("--searxng", help="a real SearXNG instance's address")
    parser.add_argument("--browser", action="store_true",
                        help="also drive the console in the system Chrome (needs ../ui built)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary tree")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return
    root = Path(tempfile.mkdtemp(prefix="p8-search-"))
    print(f"state and logs: {root}", flush=True)
    try:
        exercise(root, clients=args.clients, searxng=args.searxng, browser=args.browser)
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
