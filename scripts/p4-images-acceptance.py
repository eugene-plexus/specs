"""P4: images, at `/v1/images/*`, through real signed processes.

A control root, an enrolled agent, a gateway and two inference-drivers, all
started here with isolated state and ports:

* `router` -- the real `openrouter` provider, its `baseUrl` a fixture playing
  OpenRouter as measured on 2026-09-28 (`provider-accounts-measurement.md`
  section 9): an account listing whose image models' `supported_parameters`
  are chat-style and useless, `GET /images/models` with the typed descriptors
  that are the only real ones, and `/images/generations`, which enforces a
  listed setting with its own 400, silently ignores an unlisted one and a
  `mask`, takes reference images only as `input_references` OBJECTS, answers
  `created: 0` from flux, streams bare `data:` frames between `: ` keepalives
  for the one model that streams, and answers plain JSON to a model that
  cannot stream;
* `oai` -- the real `openai` provider against a fixture playing OpenAI's image
  API from its spec (`openai-openapi` d983890): `/v1/images/generations`,
  whose `dall-e-*` answers a URL unless asked for `b64_json`, and
  `/v1/images/edits`, multipart, with `image[]` and `mask`, streaming named
  `image_edit.*` events.

**The OpenAI Python SDK makes the requests the done-when names**, unchanged,
from its own interpreter: this one if it has `openai`, else `$EP_SDK_PYTHON`.
The same `client.images.generate(...)` call goes to OpenRouter's model and to
OpenAI's; a URL input is refused.

The fixture's streamed image sends its partial render, then waits 1.2 s
before the final one, so a check can tell a relayed stream from a buffered
one by the clock. It keeps every request per model, so a check can say what
reached an upstream and what did not.

No live service is touched unless `--live` is passed, which adds OpenRouter
and an OpenAI account with the keys in
`C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or `$EP_KEYS`), each
handed only to its own driver as `OPENAI_API_KEY`. On OpenRouter,
flux.2-klein-4b makes a 512x512 image through the SDK and then edits it, and
gpt-image-2.5-flare streams one at low quality. On OpenAI's own API,
gpt-image-2.5-flare generates, edits the result with a mask (the one setting
only OpenAI honours), and streams. The live run cost about five cents with
gpt-image-1-mini, which OpenAI retires on 2026-12-01; GPT Image 2.5's image
output tokens are listed at $30 a million against mini's $8, so expect more.

Run in an environment containing all five Python components (on this box,
`agent/.venv`). Logs and state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib

import httpx
import yaml
from fastapi import Request

NODE_NAME = "p4-agent"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + bytes(range(256)) * 4
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + bytes(64)

#: OpenRouter's account listing: what the main listing says about image
#: models, which is chat-style and nothing to route on (measured).
OR_LISTING = {
    "acme/flux": {"input": ["text", "image"], "output": ["image"], "params": ["seed"]},
    "acme/mini": {"input": ["text", "image"], "output": ["image"], "params": ["temperature"]},
    "acme/gemini-image": {"input": ["image", "text"], "output": ["image", "text"], "params": ["max_tokens"]},
    "acme/styles": {"input": ["text", "image"], "output": ["image"], "params": []},
    "acme/chat": {"input": ["text"], "output": ["text"], "params": ["max_tokens"]},
}
#: `GET /images/models`: the settings, as typed descriptors (measured shapes).
OR_IMAGES = {
    "acme/flux": {
        "supported_parameters": {
            "aspect_ratio": {"type": "enum", "values": ["1:1", "16:9", "auto"]},
            "output_format": {"type": "enum", "values": ["png", "jpeg"]},
            "n": {"type": "range", "min": 1, "max": 1},
            "input_references": {"type": "range", "min": 0, "max": 4},
            "seed": {"type": "boolean"},
        },
        "supports_streaming": False,
    },
    "acme/mini": {
        "supported_parameters": {
            "quality": {"type": "enum", "values": ["auto", "low", "medium", "high"]},
            "background": {"type": "enum", "values": ["auto", "transparent", "opaque"]},
            "n": {"type": "range", "min": 1, "max": 10},
            "input_references": {"type": "range", "min": 0, "max": 16},
        },
        "supports_streaming": True,
    },
    "acme/gemini-image": {
        "supported_parameters": {
            "n": {"type": "range", "min": 1, "max": 1},
            "input_references": {"type": "range", "min": 0, "max": 14},
        },
        "supports_streaming": False,
    },
    "acme/styles": {
        "supported_parameters": {
            "n": {"type": "range", "min": 1, "max": 1},
            "input_references": {"type": "range", "min": 1, "max": 1},
        },
        "supports_streaming": False,
    },
}
#: What each fixture model answers with. flux answers JPEG with `created: 0`;
#: mini answers PNG whatever format is asked, so the label is the bytes'.
ANSWERS = {"acme/flux": JPEG, "acme/mini": PNG, "acme/gemini-image": JPEG, "acme/styles": PNG,
           "gpt-image-1": PNG, "dall-e-3": PNG}
OAI_MODELS = ["gpt-image-1", "dall-e-3", "gpt-4o"]
GAP = 1.2

#: The live models, measured on OpenRouter 2026-09-28. The streaming one was
#: gpt-image-1-mini until 2026-10-03: OpenAI shuts it down on 2026-12-01 and
#: names gpt-image-2.5-sunburst or gpt-image-2.5-flare instead (its
#: deprecations page, read 2026-10-03). Flare is the speed tier. OpenRouter's
#: /images/models lists it with `supports_streaming: true` and `low` among its
#: qualities, which is what this run asks for. Not yet run live.
LIVE_MAKES = "black-forest-labs/flux.2-klein-4b"
LIVE_STREAMS = "openai/gpt-image-2.5-flare"
#: The same model on OpenAI's own API, through an OpenAI account. OpenAI's
#: image guide documents Image API streaming (`partial_images`) and masked
#: edits for it; the driver files any `gpt-image-*` as an image model.
LIVE_OPENAI = "gpt-image-2.5-flare"


def rgba_png(width: int, height: int, clear: tuple[int, int, int, int]) -> bytes:
    """A mask for OpenAI's edit: opaque white, fully transparent inside
    `clear` (x0, y0, x1, y1), which is where the edit may change the image."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    x0, y0, x1, y1 = clear
    opaque, hole = b"\xff\xff\xff\xff", b"\x00\x00\x00\x00"
    solid = b"\x00" + opaque * width
    holed = b"\x00" + opaque * x0 + hole * (x1 - x0) + opaque * (width - x1)
    raw = b"".join(holed if y0 <= y < y1 else solid for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

#: What the SDK does, in its own interpreter. Each job is `images.generate`,
#: `images.edit` or `images.create_variation` arguments, with image paths
#: opened here; a streamed job is iterated and each event timed.
SDK_SNIPPET = """
import json, sys, time
import openai
args = json.loads(sys.argv[1])
client = openai.OpenAI(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=180)
out = []
for job in args["jobs"]:
    kind = job.pop("kind", "generate")
    handles = []
    for field in ("image", "mask"):
        value = job.get(field)
        if isinstance(value, list):
            handles += [open(p, "rb") for p in value]
            job[field] = handles[-len(value):]
        elif isinstance(value, str):
            handles.append(open(value, "rb"))
            job[field] = handles[-1]
    started = time.perf_counter()
    try:
        if kind == "edit":
            answer = client.images.edit(**job)
        elif kind == "variation":
            answer = client.images.create_variation(**job)
        else:
            answer = client.images.generate(**job)
        if job.get("stream"):
            events = []
            for event in answer:
                events.append({"type": event.type, "at": round(time.perf_counter() - started, 3),
                               "b64": event.b64_json, "output_format": event.output_format,
                               "size": getattr(event, "size", None),
                               "usage": event.usage.model_dump() if getattr(event, "usage", None) else None})
            out.append({"status": 200, "events": events})
        else:
            out.append({"status": 200, "created": answer.created, "output_format": answer.output_format,
                        "data": [{"b64": d.b64_json, "url": d.url} for d in answer.data],
                        "usage": answer.usage.model_dump() if answer.usage else None})
    except openai.APIStatusError as e:
        out.append({"status": e.status_code, "error": e.message})
    finally:
        for handle in handles:
            handle.close()
out.append({"sdk": openai.__version__})
print(json.dumps(out))
"""


def _key(name: str) -> str:
    for line in KEYS_FILE.read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise SystemExit(f"no {name} in {KEYS_FILE}")


def sdk_python() -> str:
    if importlib.util.find_spec("openai") is not None:
        return sys.executable
    path = os.environ.get("EP_SDK_PYTHON")
    if path:
        return path
    raise SystemExit(
        "The OpenAI Python SDK is needed: pip install openai==3.20.0 here, or set "
        "EP_SDK_PYTHON to an interpreter that has it."
    )


def kind_of(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return "other"


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        counts: dict[str, int] = {}
        seen: dict[str, list[dict]] = {}
        modes: dict[str, str] = {}

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return counts

        @app.get("/seen")
        async def seen_requests(model: str):
            return seen.get(model, [])

        @app.post("/mode")
        async def set_mode(model: str, mode: str):
            modes[model] = mode
            return {}

        def record(model, entry):
            counts[model] = counts.get(model, 0) + 1
            seen.setdefault(model, []).append(entry)

        def b64(model):
            return base64.b64encode(ANSWERS[model]).decode()

        # --- OpenRouter ---------------------------------------------------

        @app.get("/v1/models/user")
        async def or_listing():
            return {"data": [
                {
                    "id": model_id, "name": model_id, "context_length": 4096,
                    "architecture": {"input_modalities": e["input"], "output_modalities": e["output"]},
                    "supported_parameters": e["params"],
                }
                for model_id, e in OR_LISTING.items()
            ]}

        @app.get("/v1/images/models")
        async def or_images():
            return {"data": [{"id": model_id, **entry} for model_id, entry in OR_IMAGES.items()]}

        def no_provider(model, what):
            # OpenRouter's own 400 for a listed setting out of range (measured).
            return JSONResponse({"error": {
                "message": f"No provider for {model} supports the requested parameter(s): {what}.",
                "code": 400, "metadata": {"failed_routing_step": "Filter by Image Capabilities"}}},
                status_code=400)

        @app.post("/v1/images/generations")
        async def or_generate(request: Request):
            body = await request.json()
            model = body.get("model")
            refs = body.get("input_references") or []
            record(model, {"body": {k: v for k, v in body.items() if k != "input_references"},
                           "references": [
                               r if isinstance(r, str) else {"type": r.get("type"),
                                                             "url": (r.get("image_url") or {}).get("url")}
                               for r in refs]})
            listed = OR_IMAGES.get(model)
            if listed is None:
                return JSONResponse({"error": {"message": f"No endpoints found for {model}.", "code": 404}},
                                    status_code=404)
            if any(isinstance(r, str) for r in refs):
                # The strings OpenRouter's guide shows are its Zod 400 (measured).
                return JSONResponse({"success": False, "error": {"name": "ZodError", "message":
                                     "input_references.0: Invalid input: expected object, received string"}},
                                    status_code=400)
            if modes.get(model) == "busy":
                return JSONResponse({"error": {"message": "Rate limit exceeded", "code": 429}},
                                    status_code=429, headers={"Retry-After": "1"})
            if "[filter]" in body.get("prompt", ""):
                return JSONResponse({"error": {"message": "Black Forest Labs refused this prompt for "
                                               "graphic violence", "code": 400}}, status_code=400)
            params = listed["supported_parameters"]
            n = body.get("n", 1)
            if n > params.get("n", {"max": 1})["max"]:
                return no_provider(model, f'n "{n}"')
            low, high = params["input_references"]["min"], params["input_references"]["max"]
            if not low <= len(refs) <= high:
                return no_provider(model, f"input_references ({len(refs)} items)")
            for name in ("quality", "background", "output_format"):
                if name in body and name in params and body[name] not in params[name]["values"]:
                    return no_provider(model, f'{name} "{body[name]}"')
            # Unlisted settings, `mask` and `response_format` are ignored.
            created = 0 if model in ("acme/flux", "acme/gemini-image") else int(time.time())
            usage = {"prompt_tokens": 6, "completion_tokens": 4096, "total_tokens": 4102, "cost": 0.014}
            if body.get("stream") and listed["supports_streaming"]:
                async def frames():
                    yield ": \n\n"
                    yield "data: " + json.dumps({"type": "image_generation.partial_image",
                                                 "b64_json": base64.b64encode(PNG).decode(),
                                                 "partial_image_index": 0}) + "\n\n"
                    await asyncio.sleep(GAP / 2)
                    yield ": \n\n"
                    await asyncio.sleep(GAP / 2)
                    for _ in range(n):
                        yield "data: " + json.dumps({"type": "image_generation.completed", "b64_json": b64(model),
                                                     "created": created, "media_type": "image/png",
                                                     "usage": usage}) + "\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(frames(), media_type="text/event-stream")
            # A model that cannot stream answers JSON although asked (measured).
            return {"created": created, "usage": usage,
                    "data": [{"b64_json": b64(model), "media_type": "image/jpeg"} for _ in range(n)]}

        # --- OpenAI -------------------------------------------------------

        @app.get("/oai/v1/models")
        async def oai_models():
            return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "openai"}
                                               for m in OAI_MODELS]}

        @app.post("/oai/v1/images/generations")
        async def oai_generate(request: Request):
            body = await request.json()
            model = body.get("model")
            record(model, {"body": body})
            if model.startswith("dall-e") and body.get("response_format") != "b64_json":
                # dall-e answers a URL by default (OpenAI's spec).
                return {"created": int(time.time()), "data": [{"url": "https://oaidalle.example/x.png"}]}
            if not model.startswith("dall-e") and "response_format" in body:
                return JSONResponse({"error": {"message": "Unknown parameter: 'response_format'.",
                                               "type": "invalid_request_error"}}, status_code=400)
            return {"created": int(time.time()), "data": [{"b64_json": b64(model)}], "output_format": "png",
                    "usage": {"input_tokens": 9, "output_tokens": 272, "total_tokens": 281,
                              "input_tokens_details": {"text_tokens": 9, "image_tokens": 0}}}

        @app.post("/oai/v1/images/edits")
        async def oai_edit(request: Request):
            form = await request.form()
            model = form.get("model")
            parts = []
            for name in ("image", "image[]", "mask"):
                for item in form.getlist(name):
                    data = await item.read()
                    parts.append({"name": name, "filename": item.filename, "type": item.content_type,
                                  "kind": kind_of(data)})
            fields = {k: form.get(k) for k in form if k not in ("image", "image[]", "mask")}
            record(model, {"fields": fields, "parts": parts})
            common = {"created_at": int(time.time()), "size": "1024x1024", "quality": "low",
                      "background": "opaque", "output_format": "png"}
            if fields.get("stream") == "true":
                async def frames():
                    partial = {"type": "image_edit.partial_image", "b64_json": b64(model),
                               "partial_image_index": 0, **common}
                    yield f"event: {partial['type']}\ndata: {json.dumps(partial)}\n\n"
                    await asyncio.sleep(GAP)
                    done = {"type": "image_edit.completed", "b64_json": b64(model), **common,
                            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}
                    yield f"event: {done['type']}\ndata: {json.dumps(done)}\n\n"
                return StreamingResponse(frames(), media_type="text/event-stream")
            return {"created": int(time.time()), "data": [{"b64_json": b64(model)}]}

    elif kind in ("router", "oai", "openrouter", "oai-live"):
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


def exercise(directory: Path, *, live: bool) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ["control", "agent", "gateway", "fixture", "router", "oai"]
    if live:
        names += ["openrouter", "oai-live"]
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
    live_key = _key("OPENROUTER_API_KEY") if live else None
    openai_key = _key("OPENAI_API_KEY") if live else None
    files = directory / "images"
    files.mkdir()
    png_file, jpeg_file, pdf_file = files / "square.png", files / "photo.jpg", files / "not-an-image.png"
    png_file.write_bytes(PNG)
    jpeg_file.write_bytes(JPEG)
    pdf_file.write_bytes(b"%PDF-1.7 this is not an image")

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

    def wait(check, label, seconds=30):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                last = e
            time.sleep(0.1)
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

    def stop(name):
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        response.raise_for_status()
        return response.json()["sessionToken"]

    def counts():
        return call("fixture", "GET", "/stats").json()

    def last_seen(model):
        entries = call("fixture", "GET", "/seen", params={"model": model}).json()
        assert entries, f"nothing reached the upstream as {model}"
        return entries[-1]

    def by_sdk(token, jobs):
        result = subprocess.run(
            [sdk, "-c", SDK_SNIPPET, json.dumps({"base": url("gateway") + "/v1", "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=300,
            env={k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")},
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    def image(entry, index=0):
        return base64.b64decode(entry["data"][index]["b64"])

    def error_of(response):
        return response.json().get("error") or {}

    try:
        # --- a signed one-node install -----------------------------------
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
        driver("router", {"provider": "openrouter", "baseUrl": url("fixture")}, {"OPENAI_API_KEY": "fixture-not-a-key"})
        driver("oai", {"provider": "openai", "baseUrl": url("fixture") + "/oai"}, {"OPENAI_API_KEY": "fixture-oai"})
        if live:
            driver("openrouter", {"provider": "openrouter", "catalogueInclude": [LIVE_MAKES, LIVE_STREAMS]},
                   {"OPENAI_API_KEY": live_key})
            driver("oai-live", {"provider": "openai", "catalogueInclude": [LIVE_OPENAI]},
                   {"OPENAI_API_KEY": openai_key})
        slots = [{"model": "pictures", "targets": ["router/acme/flux", "router/acme/mini"]}]
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2, "modelSlots": slots})
        start("gateway")

        def mint(name, **limits):
            response = call("agent", "POST", "/v1/auth/client-keys", operator, json={
                "name": name, "limits": {"allowedModels": None, "requestsPerMinute": 1000, **limits},
            })
            response.raise_for_status()
            return response.json()["token"]

        key = mint("Everything")

        def models(token=key):
            return {
                m["id"]: m.get("x_eugene_plexus") or {}
                for m in call("gateway", "GET", "/v1/models", token).json().get("data", [])
            }

        wanted = {"router/acme/flux", "router/acme/mini", "router/acme/gemini-image", "router/acme/styles",
                  "router/acme/chat", "oai/gpt-image-1", "oai/dall-e-3", "pictures"}
        wait(lambda: wanted <= set(models()), "the fixture accounts' image models are routable")

        def recorded(response_or_id):
            wanted_id = response_or_id if isinstance(response_or_id, str) else response_or_id.headers["x-request-id"]
            found = []

            def written():
                rows = call("gateway", "GET", "/v1/metrics/requests", operator, params={"limit": 30}).json()
                found[:] = [r for r in rows["requests"] if r.get("requestId") == wanted_id]
                return bool(found)
            wait(written, f"the metrics row for request {wanted_id}", 10)
            return found[0]

        # --- 1. what each model is listed with -----------------------------
        listed = models()
        flux, mini, gem = listed["router/acme/flux"], listed["router/acme/mini"], listed["router/acme/gemini-image"]
        assert flux["surfaces"] == ["image"] and flux["image_edits"] is True, flux
        assert flux["image_streaming"] is False and flux["image_mask"] is False, flux
        assert mini["image_streaming"] is True, mini
        assert gem["surfaces"] == ["chat", "image"], gem
        assert listed["oai/gpt-image-1"]["surfaces"] == ["image"] and listed["oai/gpt-image-1"]["image_mask"], listed
        assert listed["router/acme/chat"]["surfaces"] == ["chat"], listed["router/acme/chat"]
        assert "oai/gpt-4o" in listed and listed["oai/gpt-4o"]["surfaces"] == ["chat"], listed.get("oai/gpt-4o")
        ok("the images listing, not the chat-style main listing, decides which models make images and what "
           "each takes: flux edits and does not stream, mini streams, Gemini's image+text model answers both "
           "doors, OpenAI's gpt-image-1 takes a mask")

        # --- 2. the done-when: one SDK call, OpenRouter and OpenAI -----------
        results = by_sdk(key, [
            {"model": "router/acme/flux", "prompt": "a blue square", "size": "1536x1024"},
            {"model": "oai/gpt-image-1", "prompt": "a blue square", "size": "1536x1024"},
        ])
        router_answer, oai_answer, sdk_info = results
        assert router_answer["status"] == 200 and image(router_answer) == JPEG, router_answer.get("error")
        assert router_answer["output_format"] == "jpeg" and router_answer["created"] > 0, router_answer
        assert router_answer["usage"]["output_tokens"] == 4096, router_answer["usage"]
        assert oai_answer["status"] == 200 and image(oai_answer) == PNG, oai_answer.get("error")
        sent = last_seen("acme/flux")["body"]
        assert sent == {"model": "acme/flux", "prompt": "a blue square", "size": "1536x1024"}, sent
        assert "response_format" not in last_seen("gpt-image-1")["body"], last_seen("gpt-image-1")
        ok(f"the same client.images.generate call (openai {sdk_info['sdk']}) is answered through OpenRouter's "
           "flux and OpenAI's gpt-image-1, as b64_json the SDK decodes; flux's created 0 is replaced by a "
           "real time and its JPEG is labelled jpeg")

        [dall_e] = by_sdk(key, [{"model": "oai/dall-e-3", "prompt": "a blue square", "response_format": "url",
                                 "style": "vivid"}])[:1]
        assert dall_e["status"] == 200 and image(dall_e) == PNG and dall_e["data"][0]["url"] is None, dall_e
        sent = last_seen("dall-e-3")["body"]
        assert sent["response_format"] == "b64_json" and sent["style"] == "vivid", sent
        ok("response_format url is accepted and answered as b64_json (P4-1): dall-e-3, which answers a URL "
           "unless told otherwise, was asked for b64_json, and style reached it")

        # --- 3. edits: multipart as the SDK sends it -------------------------
        before = counts()
        results = by_sdk(key, [
            {"kind": "edit", "model": "router/acme/flux", "prompt": "make it red",
             "image": [str(png_file), str(jpeg_file)]},
            {"kind": "edit", "model": "oai/gpt-image-1", "prompt": "make it red",
             "image": [str(png_file), str(jpeg_file)], "mask": str(png_file), "input_fidelity": "high"},
        ])
        assert all(r["status"] == 200 for r in results[:2]), results
        refs = last_seen("acme/flux")["references"]
        assert refs == [
            {"type": "image_url", "url": "data:image/png;base64," + base64.b64encode(PNG).decode()},
            {"type": "image_url", "url": "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()},
        ], refs
        edit = last_seen("gpt-image-1")
        assert [(p["name"], p["kind"]) for p in edit["parts"]] == [
            ("image[]", "png"), ("image[]", "jpeg"), ("mask", "png")], edit["parts"]
        assert edit["fields"]["input_fidelity"] == "high" and "response_format" not in edit["fields"], edit
        assert counts().get("acme/flux", 0) == before.get("acme/flux", 0) + 1
        ok("an SDK edit of two images reaches OpenRouter as input_references objects with data: URLs (its only "
           "edit route) and OpenAI as its own multipart form, image[] twice and the mask, typed by their bytes")

        # --- 4. the done-when: a URL input is refused ------------------------
        before = counts()
        data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()

        def edit_json(image_ref, model="router/acme/flux"):
            return call("gateway", "POST", "/v1/images/edits", key,
                        json={"model": model, "prompt": "make it red", "images": [image_ref]})

        by_url = edit_json({"image_url": "https://example.com/cat.png"})
        by_file = edit_json({"file_id": "file-abc123"})
        assert by_url.status_code == 400 and error_of(by_url)["param"] == "images[0].image_url", by_url.text
        assert "not fetched" in error_of(by_url)["message"], by_url.text
        assert by_file.status_code == 400 and error_of(by_file)["param"] == "images[0].file_id", by_file.text
        assert counts() == before, (before, counts())
        inline = edit_json({"image_url": data_url})
        assert inline.status_code == 200, inline.text
        ok("a URL input is refused naming images[0].image_url, and a file_id naming images[0].file_id; "
           "nothing reached an upstream; the same edit with a data: URL is served")

        before = counts()
        results = by_sdk(key, [{"kind": "edit", "model": "router/acme/flux", "prompt": "x",
                                "image": str(pdf_file)}])
        assert results[0]["status"] == 400 and "PNG, JPEG, WebP or GIF" in results[0]["error"], results[0]
        assert counts() == before
        ok("a file named .png that is a PDF is refused by its bytes, unsent")

        # --- 5. settings route by each model's own listing -------------------
        # One setting per request: n alone also rules flux out, and a check
        # sending both could not tell whether quality was read at all (the
        # sabotage pass's one escape).
        for setting in ({"quality": "high"}, {"n": 2}):
            before = counts()
            response = call("gateway", "POST", "/v1/images/generations", key,
                            json={"model": "pictures", "prompt": "a cat", **setting})
            assert response.status_code == 200, (setting, response.text)
            after = counts()
            assert after.get("acme/flux", 0) == before.get("acme/flux", 0), (setting, before, after)
            assert after.get("acme/mini", 0) == before.get("acme/mini", 0) + 1, (setting, before, after)
        assert len(response.json()["data"]) == 2, response.text
        row = recorded(response)
        assert (row["servedModel"], row["tier"], row["door"], row["images"]) == (
            "router/acme/mini", 2, "images", 2), row
        assert (row["promptTokens"], row["completionTokens"]) == (6, 4096), row
        ok("pictures -> [flux, mini] with quality high, and again with n 2, never asks flux, whose listing takes "
           "neither, and is answered by mini at tier 2; the row counts two images beside the tokens")

        before = counts()
        refused = {}
        for field, value in (("background", "transparent"), ("output_format", "webp"), ("n", 2)):
            response = call("gateway", "POST", "/v1/images/generations", key,
                            json={"model": "router/acme/flux", "prompt": "a cat", field: value})
            assert response.status_code == 400 and error_of(response)["param"] == field, response.text
            refused[field] = error_of(response)["message"]
        assert counts() == before, (before, counts())
        assert "Nothing was sent" in refused["background"] and "png, jpeg" in refused["output_format"], refused
        ok("background transparent, output_format webp and n 2 to flux alone are 400s naming the field, "
           "before anything is sent: flux would have ignored the background with a 200 (measured)")

        response = call("gateway", "POST", "/v1/images/generations", key,
                        json={"model": "router/acme/mini", "prompt": "a cat", "output_format": "webp"})
        assert response.status_code == 200 and response.json()["output_format"] == "png", response.text
        assert last_seen("acme/mini")["body"]["output_format"] == "webp"
        ok("an output_format mini's listing does not name is carried (gpt-image-1-mini honours it, measured) "
           "and the answer is labelled by its bytes: png")

        before = counts()
        masked = call("gateway", "POST", "/v1/images/edits", key, json={
            "model": "router/acme/flux", "prompt": "x", "images": [{"image_url": data_url}],
            "mask": {"image_url": data_url}})
        assert masked.status_code == 400 and error_of(masked)["param"] == "mask", masked.text
        edits_only = call("gateway", "POST", "/v1/images/generations", key,
                          json={"model": "router/acme/styles", "prompt": "x"})
        assert edits_only.status_code == 400 and error_of(edits_only)["param"] == "image", edits_only.text
        extra = call("gateway", "POST", "/v1/images/generations", key,
                     json={"model": "router/acme/flux", "prompt": "x", "aspect_ratio": "16:9"})
        assert extra.status_code == 400 and error_of(extra)["param"] == "aspect_ratio", extra.text
        assert "size" in error_of(extra)["message"]
        assert counts() == before, (before, counts())
        styled = edit_json({"image_url": data_url}, model="router/acme/styles")
        assert styled.status_code == 200, styled.text
        ok("a mask to OpenRouter (which ignores one) is refused naming mask; the edit-only model makes no "
           "generation and does edit; OpenRouter's own aspect_ratio is refused by name, pointing at size (P4-4)")

        # --- 6. streaming (P4-3) ---------------------------------------------
        before = counts()
        results = by_sdk(key, [
            {"model": "router/acme/mini", "prompt": "a star", "stream": True, "partial_images": 1,
             "quality": "low"},
            {"model": "router/acme/flux", "prompt": "a star", "stream": True},
            {"model": "pictures", "prompt": "a star", "stream": True},
        ])
        streamed, flux_stream, slot_stream = results[:3]
        assert streamed["status"] == 200, streamed
        kinds = [e["type"] for e in streamed["events"]]
        assert kinds == ["image_generation.partial_image", "image_generation.completed"], kinds
        first_at, last_at = streamed["events"][0]["at"], streamed["events"][-1]["at"]
        assert last_at - first_at >= GAP * 0.8, streamed["events"]
        final = streamed["events"][-1]
        assert base64.b64decode(final["b64"]) == PNG and final["output_format"] == "png", final
        assert final["size"] == "auto" and final["usage"]["output_tokens"] == 4096, final
        assert flux_stream["status"] == 400 and "image_streaming" in flux_stream["error"], flux_stream
        asked = call("fixture", "GET", "/seen", params={"model": "acme/mini"}).json()
        assert any(e["body"].get("stream") is True and e["body"].get("partial_images") == 1 for e in asked), asked
        assert slot_stream["status"] == 200 and slot_stream["events"][-1]["type"] == "image_generation.completed"
        after = counts()
        assert after.get("acme/flux", 0) == before.get("acme/flux", 0), (before, after)
        ok(f"the SDK streams mini's partial render at {first_at:.2f} s and the image at {last_at:.2f} s, relayed "
           f"not buffered, with every field OpenAI's events require; a stream to flux is a 400 naming "
           f"image_streaming, and pictures streams from mini without asking flux (P4-3)")

        with client.stream("POST", url("gateway") + "/v1/images/generations", json={
                "model": "pictures", "prompt": "a moon", "stream": True},
                headers={"Authorization": "Bearer " + key}) as response:
            assert response.status_code == 200, response.read()
            request_id = response.headers["x-request-id"]
            body = response.read().decode()
        assert body.count("image_generation.completed") >= 1, body[:300]
        row = recorded(request_id)
        assert (row["outcome"], row["streamed"], row["servedModel"], row["images"]) == (
            "served", True, "router/acme/mini", 1), row
        ok("a streamed image is retained as served, streamed, with its count: the route reads past the final "
           "event, or the tiered client would never mark its attempt served")

        results = by_sdk(key, [{"kind": "edit", "model": "oai/gpt-image-1", "prompt": "red",
                                "image": str(png_file), "stream": True}])
        kinds = [e["type"] for e in results[0]["events"]]
        assert kinds == ["image_edit.partial_image", "image_edit.completed"], results[0]
        ok("a streamed edit through OpenAI's named-event stream reaches the SDK as image_edit events")

        # --- 7. failover, and a refusal that does not cascade ----------------
        # Before the rate limit: a 429 cools flux's circuit, and a cooling model
        # is skipped, which would send this prompt to mini instead.
        before = counts()
        response = call("gateway", "POST", "/v1/images/generations", key,
                        json={"model": "pictures", "prompt": "a red circle [filter]"})
        assert response.status_code == 400 and "graphic violence" in error_of(response)["message"], response.text
        after = counts()
        assert after.get("acme/flux", 0) == before.get("acme/flux", 0) + 1, (before, after)
        assert after.get("acme/mini", 0) == before.get("acme/mini", 0), (before, after)
        call("fixture", "POST", "/mode", params={"model": "acme/flux", "mode": "busy"}).raise_for_status()
        before = counts()
        response = call("gateway", "POST", "/v1/images/generations", key,
                        json={"model": "pictures", "prompt": "a dog"})
        assert response.status_code == 200, response.text
        row = recorded(response)
        assert (row["servedModel"], row["tier"]) == ("router/acme/mini", 2), row
        assert [t["served"] for t in row["tries"]] == [False, True], row
        call("fixture", "POST", "/mode", params={"model": "acme/flux", "mode": "ok"}).raise_for_status()
        ok("with flux rate-limited, pictures is answered by mini at tier 2, as chat cascades; a provider's "
           "content filter is relayed with its words and does not cascade")

        # --- 8. variations, keys ---------------------------------------------
        results = by_sdk(key, [{"kind": "variation", "image": str(png_file), "n": 1, "size": "256x256"}])
        assert results[0]["status"] == 400 and "variations" in results[0]["error"], results[0]
        scoped = mint("Only mini", allowedModels=["router/acme/mini"])
        response = call("gateway", "POST", "/v1/images/generations", scoped,
                        json={"model": "router/acme/flux", "prompt": "x"})
        assert response.status_code in (403, 404), response.text[:300]
        local = mint("Local only", localOnly=True)
        response = call("gateway", "POST", "/v1/images/generations", local,
                        json={"model": "router/acme/flux", "prompt": "x"})
        assert response.status_code == 403, response.text[:300]
        ok("variations say no backend here makes them (P4-2); a key allowed only mini cannot reach flux, and a "
           "local-only key is refused a hosted image model")

        # --- 9. the live half --------------------------------------------------
        if live:
            makes, streams = f"openrouter/{LIVE_MAKES}", f"openrouter/{LIVE_STREAMS}"
            wait(lambda: {makes, streams} <= set(models()), "OpenRouter's live image models", 60)
            [made] = by_sdk(key, [{"model": makes, "prompt": "a plain blue square on a white background",
                                   "size": "512x512"}])[:1]
            assert made["status"] == 200, made
            raw = image(made)
            assert kind_of(raw) in ("jpeg", "png"), raw[:8]
            live_file = files / f"live.{kind_of(raw)}"
            live_file.write_bytes(raw)
            [edited] = by_sdk(key, [{"kind": "edit", "model": makes, "prompt": "make the square green",
                                     "image": str(live_file), "size": "512x512"}])[:1]
            assert edited["status"] == 200 and kind_of(image(edited)) in ("jpeg", "png"), edited
            [flowed] = by_sdk(key, [{"model": streams, "prompt": "a yellow star", "quality": "low",
                                     "stream": True, "partial_images": 1}])[:1]
            assert flowed["status"] == 200, flowed
            kinds = [e["type"] for e in flowed["events"]]
            assert kinds[-1] == "image_generation.completed" and kinds.count("image_generation.completed") == 1
            print(f"INFO live {LIVE_MAKES}: {kind_of(raw)} {len(raw)} bytes; edit {len(image(edited))} bytes; "
                  f"{LIVE_STREAMS} stream {kinds} at {[e['at'] for e in flowed['events']]}", flush=True)
            ok(f"live: the SDK makes an image with {LIVE_MAKES}, edits it through input_references, and streams "
               f"one from {LIVE_STREAMS}, all through the gateway")

            # OpenAI's own API: the same SDK calls, and the masked edit only it honours.
            oai = f"oai-live/{LIVE_OPENAI}"
            wait(lambda: oai in models(), "the OpenAI account's image model", 60)
            listed_oai = models()[oai]
            assert listed_oai["surfaces"] == ["image"] and listed_oai["image_mask"] is True, listed_oai
            [made] = by_sdk(key, [{"model": oai, "prompt": "a plain blue square on a white background",
                                   "size": "1024x1024", "quality": "low"}])[:1]
            assert made["status"] == 200 and kind_of(image(made)) == "png", made.get("error")
            source = files / "oai-live.png"
            source.write_bytes(image(made))
            mask = files / "oai-mask.png"
            mask.write_bytes(rgba_png(1024, 1024, (256, 256, 768, 768)))
            [edited] = by_sdk(key, [{"kind": "edit", "model": oai, "prompt": "make the square bright red",
                                     "image": str(source), "mask": str(mask), "size": "1024x1024",
                                     "quality": "low"}])[:1]
            assert edited["status"] == 200 and kind_of(image(edited)) == "png", edited.get("error")
            [flowed_oai] = by_sdk(key, [{"model": oai, "prompt": "a yellow star", "quality": "low",
                                         "size": "1024x1024", "stream": True, "partial_images": 1}])[:1]
            assert flowed_oai["status"] == 200, flowed_oai
            kinds = [e["type"] for e in flowed_oai["events"]]
            assert kinds[-1] == "image_generation.completed", kinds
            print(f"INFO live OpenAI {LIVE_OPENAI}: generation {len(image(made))} bytes, usage {made['usage']}; "
                  f"masked edit {len(image(edited))} bytes; stream {kinds} at "
                  f"{[e['at'] for e in flowed_oai['events']]}", flush=True)
            ok(f"live: the same SDK calls reach OpenAI's own API through an OpenAI account: {LIVE_OPENAI} makes an "
               f"image, edits it through the multipart form with a mask, and streams one")

            keys = [live_key, openai_key]
            leaked = [str(p) for p in directory.rglob("*")
                      if p.is_file() and any(k.encode() in p.read_bytes() for k in keys)]
            assert not leaked, f"a live key was written to {len(leaked)} file(s) of the run's state"
            ok("neither live key is in the run's state and logs")

        (directory / "summary.json").write_text(json.dumps({"passed": passed}, indent=2), encoding="utf-8")
        print(f"{passed} PASS", flush=True)
    finally:
        for name in reversed(list(processes)):
            stop(name)
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
        directory = Path(tempfile.mkdtemp(prefix="ep-p4-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.live)
