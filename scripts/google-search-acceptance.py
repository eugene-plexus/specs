"""Google Search as a search account, beside Brave, through real signed processes.

`docs/design/google-search-account.md` (Troy's GS1-GS9). A control root, an
enrolled agent, a gateway, an inference-driver and two search accounts, all
started here with isolated state and ports. **The search accounts are
tool-drivers the agent spawns** and that are configured through its proxy by
name, as the console does:

* `google` -- `provider: google` over a fixture playing Google's
  `generateContent` with the `googleSearch` tool as Google answered it live on
  2026-10-09: a grounded answer, `groundingMetadata` with chunks whose `uri`
  is a Google redirect (here, the fixture's own redirect host, answering 302
  to the real address), supports citing them, and `searchEntryPoint`
  HTML (Search Suggestions). The model listing it picks from is paginated.
* `brave` -- `provider: brave` over a fixture playing Brave's documented API.
* `model` -- a local engine that calls tools: offered `web_search` it calls
  it; handed the results it answers citing the first address.

The OpenAI and Anthropic SDKs make the requests, unchanged, from their own
interpreter: this one if it has both, else `$EP_SDK_PYTHON`.

Checks: the Google account is set up by name with its key sealed; it picks
the cheapest model from the key's listing and says which; by default Brave
is searched first (both bill per search; by name), and `webSearchOrder` set
on the gateway puts Google first with no restart, as the routing view says;
Google's answer reaches the model verbatim with the redirect links resolved
to real addresses (the page itself never fetched); the Search Suggestions
reach every door's extension unmodified and nowhere else (not the model, not
the metrics, not a log); a domain filter keeps only matching sources and
leaves Google's answer out; the key rides `x-goog-api-key` only.

`--live` re-points the Google account at Google with `GEMINI_API_KEY` from
`C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or `$EP_KEYS`),
sealed into the account through the proxy as a person would, for one real
search (inside Google's 5,000 free a month).

Run in an environment containing every Python component, the tool-driver
included (on this box, `agent/.venv`). Logs and state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx
import yaml
from fastapi import Request

NODE_NAME = "gs-agent"
MODEL = "gs-local"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))
GOOGLE_KEY = "AIzaFixture-" + "google-search-not-a-key"  # gitleaks:allow (a fake)
BRAVE_KEY = "BSA-gs-fixture-subscription-token"  # gitleaks:allow (a fake)
ANSWER_MARK = "GS-FIXTURE-ANSWER"
GOOGLE_ANSWER = "The GS fixture's grounded answer: Raspberry Pi 5 8GB sells for about $80."
#: Google's Search Suggestions, shaped like the live HTML (a style block, a
#: container, chips that link to google.com), with a marker to look for.
SUGGESTIONS = (
    "<style>\n.container { display: flex; }\n.chip { border-radius: 16px; }\n</style>\n"
    '<div class="container">\n  <div class="carousel">\n'
    '<a class="chip" href="https://www.google.com/search?q=gs+marker+raspberry+pi+5&amp;client=app-vertex-grounding">'
    "gs marker raspberry pi 5</a>\n  </div>\n</div>"
)
SUGGESTIONS_MARK = "gs+marker+raspberry+pi+5"
SOURCES = ["https://www.pishop.us/raspberry-pi-5", "https://www.raspberrypi.com/products/raspberry-pi-5/"]

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
            text, extra = [], None
            for chunk in oa.chat.completions.create(stream=True, **job):
                for c in chunk.choices:
                    if c.delta.content:
                        text.append(c.delta.content)
                extra = (chunk.model_extra or {}).get("x_eugene_plexus") or extra
            out.append({"status": 200, "content": "".join(text), "extra": extra})
        elif kind == "responses":
            r = oa.responses.create(**job)
            out.append({"status": 200, "output": [i.model_dump() for i in r.output], "text": r.output_text})
        elif kind == "responses_stream":
            done = []
            with oa.responses.stream(**job) as stream:
                for event in stream:
                    if event.type == "response.output_item.done":
                        done.append(event.item.model_dump())
                final = stream.get_final_response()
            out.append({"status": 200, "done_items": done, "output": [i.model_dump() for i in final.output]})
        elif kind == "messages":
            r = an.messages.create(**job)
            out.append({"status": 200, "content": [b.model_dump() for b in r.content]})
        elif kind == "messages_stream":
            with an.messages.stream(**job) as stream:
                for _ in stream:
                    pass
                final = stream.get_final_message()
            out.append({"status": 200, "content": [b.model_dump() for b in final.content]})
    except (openai.APIStatusError, anthropic.APIStatusError) as e:
        out.append({"status": e.status_code, "error": str(e.message)})
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


def _key(name: str) -> str:
    for line in KEYS_FILE.read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise SystemExit(f"no {name} in {KEYS_FILE}")


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)\]]+", text or "")
    return match.group(0) if match else None


def _text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def model_turn(body: dict) -> tuple[str | None, list[dict] | None]:
    """The scripted local model: called with a search tool it searches;
    handed the results it answers citing the first address."""
    messages = body.get("messages") or []
    tools = [t.get("function", {}).get("name") for t in body.get("tools") or []]
    search = next((n for n in tools if n in ("web_search", "eugene_web_search")), None)
    called = max((i for i, m in enumerate(messages) if m.get("role") == "assistant" and m.get("tool_calls")),
                 default=-1)
    answered = [m for m in messages[called + 1:] if m.get("role") == "tool"] if called >= 0 else []
    result = _text(answered[-1]) if answered else ""
    if answered and result.startswith("Web search results"):
        return f"{ANSWER_MARK}: about $80. Source: [the page]({_first_url(result)}).", None
    if answered:
        return f"{ANSWER_MARK}: the search said: {result[:300]}", None
    if search and messages and messages[-1].get("role") == "user":
        return None, [{"name": search, "arguments": {"query": "price of a Raspberry Pi 5 8GB"}}]
    return "GS-PLAIN: no search tool was offered.", None


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, Response, StreamingResponse

        app = FastAPI()
        state: dict = {"counts": {}, "seen": {}, "key_in_url": 0, "pages_fetched": 0}

        def count(name: str, body: object = None) -> None:
            state["counts"][name] = state["counts"].get(name, 0) + 1
            if body is not None:
                state["seen"].setdefault(name, []).append(body)

        def google_error(code: int, status: str, message: str) -> JSONResponse:
            return JSONResponse({"error": {"code": code, "status": status, "message": message}}, status_code=code)

        def keyed(request: Request) -> JSONResponse | None:
            if GOOGLE_KEY in str(request.url):
                state["key_in_url"] += 1
            if request.headers.get("x-goog-api-key") != GOOGLE_KEY:
                return google_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.")
            return None

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return {**state["counts"], "key_in_url": state["key_in_url"], "pages_fetched": state["pages_fetched"]}

        @app.get("/seen")
        async def seen(name: str):
            return state["seen"].get(name, [])

        # --- Google: the listing (two pages) and generateContent ------------
        @app.get("/google/v1beta/models")
        async def google_models(request: Request, pageToken: str | None = None):
            if refused := keyed(request):
                return refused
            count("google_list")
            if pageToken == "p2":
                return {"models": [
                    {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]}
            return {"models": [
                {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.1-pro-preview", "supportedGenerationMethods": ["generateContent"]},
            ], "nextPageToken": "p2"}

        @app.post("/google/v1beta/models/{call}")
        async def google_generate(call: str, request: Request):
            if refused := keyed(request):
                return refused
            body = await request.json()
            model, _, method = call.partition(":")
            count("google", {"model": model, "method": method, "body": body})
            if method != "generateContent":
                return google_error(404, "NOT_FOUND", f"no method {method}")
            if {"googleSearch": {}} not in (body.get("tools") or []):
                return google_error(400, "INVALID_ARGUMENT", "this fixture answers only grounded searches")
            redirect = f"http://127.0.0.1:{port}/grounding-api-redirect"
            return {
                "candidates": [{
                    "content": {"role": "model", "parts": [
                        {"text": GOOGLE_ANSWER, "thoughtSignature": "c2lnbmF0dXJl"}]},
                    "finishReason": "STOP", "index": 0,
                    "groundingMetadata": {
                        "searchEntryPoint": {"renderedContent": SUGGESTIONS},
                        "groundingChunks": [
                            {"web": {"uri": f"{redirect}/0", "title": "pishop.us"}},
                            {"web": {"uri": f"{redirect}/1", "title": "raspberrypi.com"}},
                        ],
                        "groundingSupports": [
                            {"segment": {"endIndex": 40, "text": "Raspberry Pi 5 8GB sells for about $80."},
                             "groundingChunkIndices": [0, 1]},
                            {"segment": {"startIndex": 41, "endIndex": 80, "text": "Official resellers list it."},
                             "groundingChunkIndices": [1]},
                        ],
                        "webSearchQueries": ["price of a Raspberry Pi 5 8GB"],
                    },
                }],
                "usageMetadata": {"promptTokenCount": 24, "candidatesTokenCount": 40, "totalTokenCount": 64},
                "modelVersion": model,
            }

        @app.get("/grounding-api-redirect/{index}")
        async def google_redirect(index: int):
            count("redirect")
            return Response(status_code=302, headers={"location": SOURCES[index]})

        @app.get("/page/{anything:path}")
        async def page(anything: str):
            state["pages_fetched"] += 1
            return Response("<html>a page</html>", media_type="text/html")

        # --- Brave, as documented -------------------------------------------
        @app.get("/brave/res/v1/web/search")
        async def brave(request: Request):
            count("brave", dict(request.query_params))
            if request.headers.get("x-subscription-token") != BRAVE_KEY:
                return JSONResponse({"type": "ErrorResponse", "error": {"code": "SUBSCRIPTION_TOKEN_INVALID"}},
                                    status_code=401)
            return {"type": "search", "web": {"results": [
                {"title": "Brave's result", "url": "https://brave.example/pi5",
                 "description": "From Brave's own index."}]}}

        # --- a local engine that calls tools ----------------------------------
        @app.get("/model/props")
        async def props():
            return {"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": False}}

        @app.get("/model/v1/models")
        async def models():
            return {"data": [{"id": MODEL, "object": "model"}]}

        @app.post("/model/v1/chat/completions")
        async def complete(request: Request):
            body = await request.json()
            count("model", {"messages": body.get("messages")})
            text, calls = model_turn(body)
            tool_calls = [{"id": f"call_{secrets.token_hex(4)}", "type": "function",
                           "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                          for c in calls or []]
            finish = "tool_calls" if tool_calls else "stop"
            usage = {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
            if body.get("stream"):
                async def frames():
                    if text:
                        yield "data: " + json.dumps({"model": MODEL, "choices": [
                            {"index": 0, "delta": {"content": text}, "finish_reason": None}]}) + "\n\n"
                    for index, call in enumerate(tool_calls):
                        yield "data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": {
                            "tool_calls": [{"index": index, **call}]}, "finish_reason": None}]}) + "\n\n"
                    yield "data: " + json.dumps({"model": MODEL, "choices": [
                        {"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}) + "\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(frames(), media_type="text/event-stream")
            return {"model": MODEL, "usage": usage, "choices": [{"index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": text, "tool_calls": tool_calls or None}}]}

    elif kind == "model":
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
        app = create_app(settings=Settings(config_file=directory / "gateway.yaml",
                                           metrics_file=directory / "metrics.sqlite3", **bootstrap))
    else:
        raise SystemExit(f"unknown process kind {kind!r}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path, *, live: bool) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ["control", "agent", "gateway", "fixture", "model", "google", "brave"]
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
        return client.request(method, url(name) + path,
                              headers={"Authorization": "Bearer " + token} if token else None, **kwargs)

    def write(name, filename, data):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data), encoding="utf-8")

    def wait(check, label, seconds=40):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError, StopIteration) as e:
                last = e
            time.sleep(0.2)
        raise AssertionError(f"timed out: {label} ({last!r})")

    def start(name, extra_env=None):
        work = directory / name
        work.mkdir(exist_ok=True)
        output = (work / "process.log").open("ab")
        logs.append(output)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        for inherited in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            env.pop(inherited, None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env.update(extra_env or {})
        processes[name] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name,
             "--directory", str(work), "--port", str(ports[name])],
            cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        response.raise_for_status()
        return response.json()["sessionToken"]

    def stats():
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
        # --- a signed one-node install ----------------------------------------
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        root_session = login("control")
        write("agent", "agent.yaml", {"firstRunComplete": True, "updateChecks": False,
                                      "advertiseUrl": url("agent"),
                                      "securityMode": "prompt_on_startup", "components": []})
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
            return {"agent_url": url("agent"), "trust_bundle_file": str(trust.bundle_path),
                    "trust_authority": trust.authority, "auth_recipient": trust.recipient,
                    "service_token": token}

        start("fixture")
        write("model", "bootstrap.json", bootstrap("inference-driver"))
        write("model", "driver.yaml", {"provider": "openai_compat_custom", "baseUrl": url("fixture") + "/model",
                                       "modelId": MODEL, "backendLocality": "local"})
        start("model")
        call("agent", "POST", "/v1/components", operator, json={
            "name": "model", "kind": "inference-driver", "url": url("model")}).raise_for_status()
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2})
        start("gateway")

        # --- 1. two search accounts, spawned and set up by name -----------------
        for name in ("google", "brave"):
            call("agent", "POST", "/v1/components", operator, json={
                "name": name, "kind": "tool-driver", "url": url(name),
                "spawn": {"configFile": f"{name}.yaml"}}).raise_for_status()

        def running(name):
            listed = call("agent", "GET", "/v1/components", operator).json()["components"]
            entry = next(c for c in listed if c["name"] == name)
            return entry["status"] == "running" and call(name, "GET", "/healthz").status_code == 200

        for name in ("google", "brave"):
            wait(lambda name=name: running(name), f"the agent runs the {name} tool-driver")
        patched = proxy("google", "PATCH", "/v1/config", operator, json={
            "provider": "google", "baseUrl": url("fixture") + "/google/v1beta", "apiKey": GOOGLE_KEY})
        assert patched.status_code == 200, patched.text
        assert proxy("google", "GET", "/v1/config", operator).json()["apiKey"] == "<redacted>"
        info = proxy("google", "GET", "/v1/info", operator).json()
        assert info["provider"] == "google" and info.get("billing") == "per_search", info
        assert info["tools"] == ["web_search"] and info["egress"] == "internet", info
        proxy("brave", "PATCH", "/v1/config", operator, json={
            "provider": "brave", "baseUrl": url("fixture") + "/brave", "apiKey": BRAVE_KEY}).raise_for_status()
        leaked = [p for p in directory.rglob("*") if p.is_file() and p.suffix in (".yaml", ".json")
                  and GOOGLE_KEY in p.read_text(encoding="utf-8", errors="ignore")]
        assert not leaked, f"the Google key is on disk in plaintext: {leaked}"
        ok("a Google search account and a Brave one, spawned by the agent and set up through its proxy by "
           "name; the Gemini key sealed at rest and redacted on read; Google bills per search")

        response = call("agent", "POST", "/v1/auth/client-keys", operator, json={
            "name": "Everything", "limits": {"allowedModels": None, "requestsPerMinute": 1000}})
        response.raise_for_status()
        key = response.json()["token"]
        wait(lambda: MODEL in {m["id"] for m in call("gateway", "GET", "/v1/models", key).json().get("data", [])},
             "the model is routable")

        def order():
            view = call("gateway", "GET", "/v1/admin/routing", operator).json()
            return [(a["name"], a["placed_by"], a["runs"]) for a in view.get("search_accounts") or []]

        wait(lambda: [n for n, _, runs in order() if runs] == ["brave", "google"], "both accounts in the view")

        # --- 2. the default order, then the person's ---------------------------
        before = stats()
        first = by_sdk(key, [{"kind": "chat", "model": MODEL, "web_search_options": {},
                              "messages": [{"role": "user", "content": "How much is a Pi 5?"}]}])[0]
        assert first["status"] == 200 and "brave.example" in (first["content"] or ""), first
        assert stats().get("brave", 0) == before.get("brave", 0) + 1 and stats().get("google", 0) == 0, stats()
        assert order() == [("brave", "default", True), ("google", "default", True)], order()
        set_order = call("gateway", "PATCH", "/v1/config", operator, json={"webSearchOrder": ["google"]})
        assert set_order.status_code == 200, set_order.text
        wait(lambda: order()[0] == ("google", "order", True), "the routing view shows the order set")
        assert order()[1] == ("brave", "default", True), order()
        ok("by default Brave is searched first (both bill per search, then by name), as the routing view says; "
           "webSearchOrder ['google'] on the gateway puts Google first with no restart, Brave after by default")

        # --- 3. Google's answer, sources and suggestions on chat ----------------
        chat, streamed = by_sdk(key, [
            {"kind": "chat", "model": MODEL, "web_search_options": {},
             "messages": [{"role": "user", "content": "How much is a Pi 5?"}]},
            {"kind": "chat_stream", "model": MODEL, "web_search_options": {},
             "messages": [{"role": "user", "content": "How much is a Pi 5?"}]},
        ])[:2]
        for result in (chat, streamed):
            assert result["status"] == 200, result
            assert SOURCES[0] in result["content"], result
            assert result["extra"]["search_suggestions"] == [SUGGESTIONS], result["extra"]
        assert chat["annotations"] and chat["annotations"][0]["url_citation"]["url"] == SOURCES[0], chat
        asked = seen("google")[-1]
        assert asked["model"] == "gemini-3.5-flash-lite", asked
        assert "price of a Raspberry Pi 5 8GB" in asked["body"]["contents"][0]["parts"][0]["text"], asked
        tool_message = next(m for m in reversed(seen("model")[-1]["messages"]) if m.get("role") == "tool")
        said = _text(tool_message)
        assert f"Answer from the search provider: {GOOGLE_ANSWER}" in said, said
        assert SOURCES[0] in said and SOURCES[1] in said and "grounding-api-redirect" not in said, said
        assert "Raspberry Pi 5 8GB sells for about $80." in said, said
        assert SUGGESTIONS_MARK not in said, "the suggestions HTML reached the model"
        assert stats()["pages_fetched"] == 0 and stats()["redirect"] >= 2, stats()
        schema = proxy("google", "GET", "/v1/config/schema", operator).json()
        field = next(f for f in schema["fields"] if f["key"] == "searchModel")
        assert "gemini-3.5-flash-lite" in json.dumps(field), field
        ok("chat, plain and streamed: the model read Google's answer verbatim and its sources at their real "
           "addresses (Google's redirect asked, the page never fetched); the answer cites the real address; "
           "the Search Suggestions came back in x_eugene_plexus unmodified and never reached the model; the "
           "cheapest model on the key's listing was used, and the account's settings name it")

        # --- 4. the other two doors -------------------------------------------------
        responses, responses_stream, messages, messages_stream = by_sdk(key, [
            {"kind": "responses", "model": MODEL, "input": "How much is a Pi 5?",
             "tools": [{"type": "web_search"}]},
            {"kind": "responses_stream", "model": MODEL, "input": "How much is a Pi 5?",
             "tools": [{"type": "web_search"}]},
            {"kind": "messages", "model": MODEL, "max_tokens": 200,
             "messages": [{"role": "user", "content": "How much is a Pi 5?"}],
             "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]},
            {"kind": "messages_stream", "model": MODEL, "max_tokens": 200,
             "messages": [{"role": "user", "content": "How much is a Pi 5?"}],
             "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]},
        ])[:4]
        for result in (responses, responses_stream):
            assert result["status"] == 200, result
            calls = [i for i in result["output"] if i["type"] == "web_search_call"]
            assert calls and calls[0]["x_eugene_plexus"]["search_suggestions"] == SUGGESTIONS, calls
        done = [i for i in responses_stream["done_items"] if i["type"] == "web_search_call"]
        assert done and done[0]["x_eugene_plexus"]["search_suggestions"] == SUGGESTIONS, done
        for result in (messages, messages_stream):
            assert result["status"] == 200, result
            blocks = [b for b in result["content"] if b["type"] == "web_search_tool_result"]
            assert blocks and blocks[0]["x_eugene_plexus"]["search_suggestions"] == SUGGESTIONS, blocks
        ok("Responses (a web_search_call item, final and streamed) and Anthropic messages (a "
           "web_search_tool_result block, plain and streamed) each carry the Search Suggestions unmodified")

        # --- 5. a domain filter --------------------------------------------------
        filtered = by_sdk(key, [{"kind": "responses", "model": MODEL, "input": "How much is a Pi 5?",
                                 "tools": [{"type": "web_search",
                                            "filters": {"allowed_domains": ["raspberrypi.com"]}}]}])[0]
        assert filtered["status"] == 200, filtered
        said = _text(next(m for m in reversed(seen("model")[-1]["messages"]) if m.get("role") == "tool"))
        assert SOURCES[1] in said and SOURCES[0] not in said, said
        assert "Answer from the search provider" not in said, said
        assert "site:raspberrypi.com" in seen("google")[-1]["body"]["contents"][0]["parts"][0]["text"]
        ok("with allowed_domains, Google is asked with a site: hint, only the matching source reaches the "
           "model, and Google's own answer is left out (it may draw on the pages filtered away)")

        # --- 6. where the suggestions and the key never go ------------------------
        with sqlite3.connect(directory / "gateway" / "metrics.sqlite3") as db:
            dumped = "\n".join(db.iterdump())
        assert SUGGESTIONS_MARK not in dumped, "the suggestions HTML is in the metrics"
        logged = [p.name for p in directory.rglob("*.log")
                  if SUGGESTIONS_MARK in p.read_text(encoding="utf-8", errors="ignore")
                  or GOOGLE_KEY in p.read_text(encoding="utf-8", errors="ignore")]
        assert not logged, f"suggestions or the key in a process log: {logged}"
        assert stats()["key_in_url"] == 0, stats()
        ok("the Search Suggestions are in no metrics row and no log; the key rode x-goog-api-key, never a URL "
           "or a log")

        # --- 7. back to the default -------------------------------------------------
        call("gateway", "PATCH", "/v1/config", operator, json={"webSearchOrder": []}).raise_for_status()
        wait(lambda: order()[0] == ("brave", "default", True), "the default order again")
        ok("webSearchOrder [] returns to the default rule, as the routing view says")

        # --- 8. one real Google search ----------------------------------------------
        if live:
            proxy("google", "PATCH", "/v1/config", operator,
                  json={"baseUrl": None, "apiKey": _key("GEMINI_API_KEY")}).raise_for_status()
            call("gateway", "PATCH", "/v1/config", operator,
                 json={"webSearchOrder": ["google"]}).raise_for_status()
            wait(lambda: order()[0][:2] == ("google", "order"), "Google first for the live search")
            real = by_sdk(key, [{"kind": "chat", "model": MODEL, "web_search_options": {},
                                 "messages": [{"role": "user", "content": "How much is a Pi 5?"}]}])[0]
            assert real["status"] == 200, real
            html = (real["extra"] or {}).get("search_suggestions") or []
            assert html and "google.com/search" in html[0], real["extra"]
            said = _text(next(m for m in reversed(seen("model")[-1]["messages"]) if m.get("role") == "tool"))
            urls = re.findall(r"https?://\S+", said)
            assert urls and not any("grounding-api-redirect" in u for u in urls), said[:1500]
            print(f"INFO live: {len(urls)} sources, e.g. {urls[0]}", flush=True)
            ok("live: one real Google search through a Gemini key; real addresses reached the model and "
               "Google's Search Suggestions came back")

        (directory / "summary.json").write_text(json.dumps({"passed": passed}, indent=2), encoding="utf-8")
        print(f"{passed} PASS", flush=True)
    finally:
        for name in reversed(list(processes)):
            process = processes.pop(name)
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        client.close()
        for output in logs:
            output.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-google-search-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.live)
