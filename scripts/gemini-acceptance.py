"""Gemini: a Google account of the user's own, through real signed processes.

A control root, an enrolled agent, a gateway and an inference-driver with
`provider: gemini` (`docs/design/gemini-provider.md`), all started here with
isolated state and ports. The driver's `baseUrl` points at a fixture playing
Google's native Gemini API as its documentation described it on 2026-10-09:

* `GET /v1beta/models` in two pages (`nextPageToken`), each model with
  `supportedGenerationMethods`, `inputTokenLimit` and `thinking`; an Imagen
  model (`predict`) and `aqa` (`generateAnswer`) that Eugene does not route;
* `:generateContent` and `:streamGenerateContent?alt=sse` for chat (thought
  parts, a `functionCall` carrying a `thoughtSignature`, which the next turn
  must send back or the fixture refuses it as Google does), speech (PCM in
  `inlineData`), images and transcription;
* `:batchEmbedContents`, and Veo's `:predictLongRunning` with an operation
  polled until `done`, its video served by a redirect to storage;
* every request must carry the key in `x-goog-api-key`; a key in a URL is
  counted, and must never happen.

**The OpenAI SDK makes the requests**, unchanged, from its own interpreter:
this one if it has `openai`, else `$EP_SDK_PYTHON`. The driver is restarted
between a tool call and its result, to show what a lost signature costs.

No live service is touched unless `--live` is passed, which adds the real
Gemini API with `GEMINI_API_KEY` from
`C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or `$EP_KEYS`),
handed to its driver in the environment the engine falls back to, so it is
never written to a config file, a log or this script's output. The live run
makes: a tool round trip on a thinking model (plain and streamed),
embeddings, one image, one speech clip transcribed back, and one 4-second
720p video on Veo's lite model (`--live-no-video` leaves the video out).

Run in an environment containing all five Python components (on this box,
`agent/.venv`). Logs and state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
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

NODE_NAME = "gemini-agent"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))

CHAT = "gemini-3.5-flash"
EMBED = "gemini-embedding-001"
TTS = "gemini-3.8-flash-tts"
IMAGE = "gemini-3.1-flash-image"
VEO = "veo-3.1-lite-generate-preview"
TRANSCRIBE = "gemini-3.5-transcribe"
ROUTED = (CHAT, EMBED, TTS, IMAGE, VEO, TRANSCRIBE)

#: Google's listing, trimmed, in two pages: methods, windows and `thinking`
#: as the documentation shows them; no input modalities (Google lists none).
PAGES = [
    [
        {"name": f"models/{CHAT}", "displayName": "Gemini 3.5 Flash", "inputTokenLimit": 1048576,
         "outputTokenLimit": 65536, "thinking": True,
         "supportedGenerationMethods": ["generateContent", "countTokens", "createCachedContent"]},
        {"name": f"models/{EMBED}", "displayName": "Gemini Embedding 001", "inputTokenLimit": 2048,
         "supportedGenerationMethods": ["embedContent", "batchEmbedContents"]},
        {"name": "models/imagen-4.0-generate-001", "displayName": "Imagen 4",
         "supportedGenerationMethods": ["predict"]},
    ],
    [
        {"name": f"models/{TTS}", "displayName": "Gemini 3.8 Flash TTS", "inputTokenLimit": 8192,
         "supportedGenerationMethods": ["generateContent"]},
        {"name": f"models/{IMAGE}", "displayName": "Gemini 3.1 Flash Image", "inputTokenLimit": 32768,
         "supportedGenerationMethods": ["generateContent"]},
        {"name": f"models/{VEO}", "displayName": "Veo 3.1 Lite",
         "supportedGenerationMethods": ["predictLongRunning"]},
        {"name": f"models/{TRANSCRIBE}", "displayName": "Gemini 3.5 Transcribe", "inputTokenLimit": 65536,
         "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/aqa", "displayName": "AQA", "supportedGenerationMethods": ["generateAnswer"]},
    ],
]
USAGE = {"promptTokenCount": 7, "candidatesTokenCount": 2, "thoughtsTokenCount": 5,
         "cachedContentTokenCount": 3, "totalTokenCount": 14}
PCM = bytes(range(256)) * 19  # 4,864 bytes: about a tenth of a second at 24 kHz
MP4 = b"\x00\x00\x00 ftypisom" + bytes(range(256)) * 64
#: The fixture's video is done after this many polls.
POLLS_TO_FINISH = 2
MISSING_SIGNATURE = (
    "Function call is missing a thought_signature in functionCall parts. This is required "
    "for tools to work correctly, and missing thought_signature may lead to degraded model "
    "performance."
)

#: What the SDK does, in its own interpreter. Each job names its `kind`;
#: errors come back as the status and message the SDK raised.
SDK_SNIPPET = r"""
import base64, json, sys, time, warnings
warnings.simplefilter("ignore")
import openai
args = json.loads(sys.argv[1])
client = openai.OpenAI(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=900)
TOOLS = [{"type": "function", "function": {
    "name": "get_weather", "description": "The weather now in a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]


def chat(job):
    job = dict(job)
    if not job.pop("stream", False):
        answer = client.chat.completions.create(**job)
        choice = answer.choices[0]
        return {"status": 200, "message": choice.message.model_dump(exclude_none=True),
                "finish": choice.finish_reason, "model": answer.model,
                "usage": answer.usage.model_dump(exclude_none=True) if answer.usage else None}
    text, reasoning, calls, finish, usage = "", "", {}, None, None
    for chunk in client.chat.completions.create(
        stream=True, stream_options={"include_usage": True}, **job
    ):
        if chunk.usage:
            usage = chunk.usage.model_dump(exclude_none=True)
        for choice in chunk.choices:
            delta = choice.delta
            text += delta.content or ""
            reasoning += (delta.model_extra or {}).get("reasoning_content") or ""
            for call in delta.tool_calls or []:
                slot = calls.setdefault(call.index, {"id": None, "type": "function",
                                                     "function": {"name": "", "arguments": ""}})
                if call.id:
                    slot["id"] = call.id
                if call.function and call.function.name:
                    slot["function"]["name"] += call.function.name
                if call.function and call.function.arguments:
                    slot["function"]["arguments"] += call.function.arguments
            if choice.finish_reason:
                finish = choice.finish_reason
    message = {"role": "assistant", "content": text or None}
    if reasoning:
        message["reasoning_content"] = reasoning
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"status": 200, "message": message, "finish": finish, "usage": usage}


def round_trip(job):
    # A tool call, then its result, as an OpenAI client sends them: the
    # assistant turn carries only what the OpenAI shape has (no signature).
    messages = [{"role": "user", "content": job.pop("ask")}]
    first = chat({**job, "messages": messages, "tools": TOOLS})
    calls = first["message"].get("tool_calls") or []
    if not calls:
        return {"status": 200, "first": first, "second": None, "messages": messages}
    messages.append({"role": "assistant", "content": first["message"].get("content"),
                     "tool_calls": [{"id": c["id"], "type": "function",
                                     "function": {"name": c["function"]["name"],
                                                  "arguments": c["function"]["arguments"]}}
                                    for c in calls]})
    for c in calls:
        messages.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps({"sky": "sunny", "celsius": 21})})
    second = chat({**job, "messages": messages, "tools": TOOLS})
    return {"status": 200, "first": first, "second": second, "messages": messages}


out = []
for job in args["jobs"]:
    kind = job.pop("kind")
    started = time.perf_counter()
    try:
        if kind == "chat":
            if job.pop("with_tools", False):
                job["tools"] = TOOLS
            result = chat(job)
        elif kind == "round_trip":
            result = round_trip(job)
        elif kind == "embed":
            answer = client.embeddings.create(encoding_format="float", **job)
            result = {"status": 200, "vectors": [d.embedding for d in answer.data],
                      "usage": answer.usage.model_dump() if answer.usage else None}
        elif kind == "image":
            answer = client.images.generate(**job)
            result = {"status": 200, "b64": [d.b64_json for d in answer.data],
                      "usage": answer.usage.model_dump() if answer.usage else None}
        elif kind == "speech":
            save = job.pop("save", None)
            data = b""
            with client.audio.speech.with_streaming_response.create(**job) as response:
                kind_header = response.headers.get("content-type")
                for chunk in response.iter_bytes():
                    data += chunk
            if save:
                open(save, "wb").write(data)
            result = {"status": 200, "type": kind_header, "length": len(data), "head": data[:12].hex()}
        elif kind == "transcribe":
            with open(job.pop("file"), "rb") as fh:
                answer = client.audio.transcriptions.create(file=fh, **job)
            result = {"status": 200, "text": answer.text}
        elif kind == "video":
            video = client.videos.create_and_poll(poll_interval_ms=job.pop("poll_ms", 500), **job)
            result = {"status": 200, "video": video.model_dump()}
            if video.status == "completed":
                data = b""
                with client.videos.with_streaming_response.download_content(video.id) as response:
                    result["type"] = response.headers.get("content-type")
                    for chunk in response.iter_bytes():
                        data += chunk
                result.update(length=len(data), head=data[:12].hex())
        else:
            result = {"status": 0, "error": f"unknown job {kind}"}
    except openai.APIStatusError as e:
        result = {"status": e.status_code, "error": e.message}
    result["took"] = round(time.perf_counter() - started, 2)
    out.append(result)
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
        "The OpenAI Python SDK is needed: pip install openai here, or set "
        "EP_SDK_PYTHON to an interpreter that has it."
    )


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def wav(pcm: bytes, rate: int = 24_000) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, Response, StreamingResponse

        app = FastAPI()
        expected = os.environ["EP_FIXTURE_KEY"]
        seen: dict[str, list[dict]] = {}
        stats = {"lists": 0, "key_in_url": 0, "signed_ok": 0, "unsigned": 0,
                 "storage_with_key": 0, "storage": 0}
        issued: set[str] = set()
        operations: dict[str, int] = {}

        def error(code: int, status: str, message: str, details: list | None = None) -> JSONResponse:
            body = {"error": {"code": code, "message": message, "status": status}}
            if details:
                body["error"]["details"] = details
            return JSONResponse(body, status_code=code)

        def refused_key(request: Request) -> JSONResponse | None:
            if expected in str(request.url):
                stats["key_in_url"] += 1
            if request.headers.get("x-goog-api-key") != expected:
                return error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                             [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                               "reason": "API_KEY_INVALID"}])
            return None

        def answer(parts: list[dict], finish: str = "STOP", usage: dict | None = None) -> dict:
            return {"candidates": [{"content": {"role": "model", "parts": parts},
                                    "finishReason": finish, "index": 0}],
                    "usageMetadata": usage or USAGE, "modelVersion": CHAT}

        def sse(frames: list[dict]) -> StreamingResponse:
            async def body():
                for frame in frames:
                    yield "data: " + json.dumps(frame) + "\r\n\r\n"

            return StreamingResponse(body(), media_type="text/event-stream")

        def chat(body: dict, stream: bool):
            contents = body.get("contents") or []
            last = contents[-1] if contents else {"parts": []}
            text = "".join(p.get("text", "") for p in last.get("parts", []))
            if any("functionResponse" in p for p in last.get("parts", [])):
                prior = contents[-2] if len(contents) > 1 else {"parts": []}
                calls = [p for p in prior.get("parts", []) if "functionCall" in p]
                if not calls or any(p.get("thoughtSignature") not in issued for p in calls):
                    stats["unsigned"] += 1
                    return error(400, "INVALID_ARGUMENT", MISSING_SIGNATURE)
                stats["signed_ok"] += 1
                parts = [{"text": "It is sunny in Paris, 21 degrees."}]
            elif body.get("tools"):
                signature = base64.b64encode(secrets.token_bytes(24)).decode()
                issued.add(signature)
                parts = [{"text": "The weather tool answers this.", "thought": True},
                         {"functionCall": {"name": "get_weather", "args": {"city": "Paris"}},
                          "thoughtSignature": signature}]
            elif text == "unsafe":
                frame = {"candidates": [{"finishReason": "SAFETY", "index": 0,
                                         "safetyRatings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                                                            "probability": "HIGH", "blocked": True}]}],
                         "usageMetadata": {"promptTokenCount": 3, "totalTokenCount": 3}}
                return sse([frame]) if stream else frame
            elif text == "echo-key":
                # Google's errors can quote the request; the key must not come
                # back. Quoted bare, not as `key=...`, which a second pattern
                # also catches: this is the check on the key itself.
                return error(400, "INVALID_ARGUMENT", f"Invalid value {expected!r} in the request")
            else:
                parts = [{"text": "Thinking it over.", "thought": True}, {"text": "pong"}]
            if not stream:
                return answer(parts)
            frames = [{"candidates": [{"content": {"role": "model", "parts": [p]}, "index": 0}]}
                      for p in parts[:-1]]
            frames.append({**answer(parts[-1:]), "usageMetadata": USAGE})
            return sse(frames)

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def get_stats():
            return stats

        @app.get("/seen")
        async def get_seen(model: str):
            return seen.get(model, [])

        @app.get("/v1beta/models")
        async def listing(request: Request, pageToken: str | None = None):
            if refused := refused_key(request):
                return refused
            stats["lists"] += 1
            if pageToken == "page-2":
                return {"models": PAGES[1]}
            return {"models": PAGES[0], "nextPageToken": "page-2"}

        @app.get("/v1beta/models/{model}/operations/{operation}")
        async def poll(model: str, operation: str, request: Request):
            if refused := refused_key(request):
                return refused
            name = f"models/{model}/operations/{operation}"
            if name not in operations:
                return error(404, "NOT_FOUND", "Operation not found")
            operations[name] += 1
            if operations[name] < POLLS_TO_FINISH:
                return {"name": name}
            uri = f"http://127.0.0.1:{port}/v1beta/files/{operation}:download?alt=media"
            return {"name": name, "done": True, "response": {
                "@type": "type.googleapis.com/google.ai.generativelanguage.v1beta.PredictLongRunningResponse",
                "generateVideoResponse": {"generatedSamples": [{"video": {"uri": uri}}]}}}

        @app.get("/v1beta/files/{name}")
        async def download(name: str, request: Request):
            if refused := refused_key(request):
                return refused
            file_id = name.split(":", 1)[0]
            return Response(status_code=302,
                            headers={"location": f"http://127.0.0.1:{port}/storage/{file_id}.mp4"})

        @app.get("/storage/{name}")
        async def storage(name: str, request: Request):
            stats["storage"] += 1
            if "x-goog-api-key" in request.headers:
                stats["storage_with_key"] += 1
            return Response(MP4, media_type="video/mp4")

        @app.post("/v1beta/models/{call}")
        async def model_call(call: str, request: Request):
            if refused := refused_key(request):
                return refused
            model, _, method = call.partition(":")
            body = await request.json()
            seen.setdefault(model, []).append({"method": method, "query": dict(request.query_params),
                                               "body": body})
            if method == "batchEmbedContents":
                if model != EMBED:
                    return error(400, "INVALID_ARGUMENT", f"{model} does not embed")
                return {"embeddings": [{"values": [float(i), float(len(r["content"]["parts"][0]["text"])), 0.5]}
                                       for i, r in enumerate(body["requests"])]}
            if method == "predictLongRunning":
                name = f"models/{model}/operations/op{len(operations) + 1}"
                operations[name] = 0
                return {"name": name}
            stream = method == "streamGenerateContent"
            if method not in ("generateContent", "streamGenerateContent"):
                return error(404, "NOT_FOUND", f"no method {method}")
            if stream and request.query_params.get("alt") != "sse":
                return error(400, "INVALID_ARGUMENT", "this fixture streams SSE only")
            if model == TTS:
                return answer([{"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000",
                                               "data": base64.b64encode(PCM).decode()}}])
            if model == IMAGE:
                png = solid_png(16, 16, (40, 120, 200))
                return answer([{"text": "Here is the picture."},
                               {"inlineData": {"mimeType": "image/png",
                                               "data": base64.b64encode(png).decode()}}])
            if model == TRANSCRIBE:
                return answer([{"text": "Eugene Plexus says hello.\n"}])
            if model == CHAT:
                return chat(body, stream)
            return error(404, "NOT_FOUND", f"models/{model} is not found")

    elif kind in ("gem", "live"):
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


def exercise(directory: Path, *, live: bool, live_video: bool) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ["control", "agent", "gateway", "fixture", "gem"] + (["live"] if live else [])
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(zip(names, [sock.getsockname()[1] for sock in sockets], strict=True))
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs = []
    client = httpx.Client(timeout=60, trust_env=False)
    passphrase = secrets.token_urlsafe(24)
    fake_key = "AIzaFixture-" + secrets.token_urlsafe(18)
    sdk_exe = sdk_python()
    passed = 0

    def ok(message: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {message}", flush=True)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(method, url(name) + path,
                              headers={"Authorization": "Bearer " + token} if token else {}, **kwargs)

    def write(name, filename, data):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data), encoding="utf-8")

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
        for inherited in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
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

    def sdk(token: str, jobs: list[dict], timeout: float = 300) -> list[dict]:
        done = subprocess.run(
            [sdk_exe, "-c", SDK_SNIPPET,
             json.dumps({"base": url("gateway") + "/v1", "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=timeout,
        )
        if done.returncode != 0:
            raise AssertionError(f"the SDK failed: {done.stderr[-3000:]}")
        return json.loads(done.stdout.strip().splitlines()[-1])

    def seen(model: str) -> list[dict]:
        return call("fixture", "GET", f"/seen?model={model}").json()

    def stats() -> dict:
        return call("fixture", "GET", "/stats").json()

    try:
        # --- a signed one-node install -------------------------------------
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

        def declare(name):
            call("agent", "POST", "/v1/components", operator, json={
                "name": name, "kind": "inference-driver", "url": url(name)}).raise_for_status()

        start("fixture", {"EP_FIXTURE_KEY": fake_key})
        write("gem", "bootstrap.json", bootstrap("inference-driver"))
        # An account (no modelId); the key only in the environment it falls back to.
        write("gem", "driver.yaml", {"provider": "gemini", "baseUrl": url("fixture") + "/v1beta"})
        start("gem", {"GEMINI_API_KEY": fake_key})
        declare("gem")
        if live:
            write("live", "bootstrap.json", bootstrap("inference-driver"))
            write("live", "driver.yaml", {"provider": "gemini"})
            start("live", {"GEMINI_API_KEY": _key("GEMINI_API_KEY")})
            declare("live")
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2})
        start("gateway")
        response = call("agent", "POST", "/v1/auth/client-keys", operator, json={
            "name": "Everything", "limits": {"allowedModels": None, "requestsPerMinute": 1000}})
        response.raise_for_status()
        token = response.json()["token"]

        def listing() -> dict[str, dict]:
            return {m["id"]: m.get("x_eugene_plexus") or {}
                    for m in call("gateway", "GET", "/v1/models", token).json().get("data", [])}

        wanted = {f"gem/{m}" for m in ROUTED}
        wait(lambda: wanted <= set(listing()), "the account's models are routable", 40)

        # --- 1. the listing ------------------------------------------------------
        models = listing()
        gem = sorted(i for i in models if i.startswith("gem/"))
        assert gem == sorted(wanted), gem
        info = call("gem", "GET", "/v1/info", operator).json()
        assert info["backend"] == "gemini_api" and "modelId" not in info, info
        assert info["catalogue"]["source"] == "gemini" and info["catalogue"]["exposed"] == 6, info["catalogue"]
        assert stats()["lists"] >= 2, stats()
        assert models[f"gem/{CHAT}"]["context_length"] == 1048576, models[f"gem/{CHAT}"]
        assert "chat" in models[f"gem/{CHAT}"]["surfaces"], models[f"gem/{CHAT}"]
        assert models[f"gem/{TTS}"]["surfaces"] == ["speech"], models[f"gem/{TTS}"]
        assert models[f"gem/{TTS}"]["speech_formats"] == ["wav", "pcm"], models[f"gem/{TTS}"]
        assert "Kore" in models[f"gem/{TTS}"]["voices"], models[f"gem/{TTS}"]
        assert models[f"gem/{EMBED}"]["surfaces"] == ["embeddings"], models[f"gem/{EMBED}"]
        assert models[f"gem/{VEO}"]["surfaces"] == ["video"], models[f"gem/{VEO}"]
        assert models[f"gem/{IMAGE}"]["surfaces"] == ["image"], models[f"gem/{IMAGE}"]
        ok("a Gemini account read in two pages: six models published as gem/<id> with Google's window, "
           "each on its own surface; Imagen (predict) and aqa are not routed")

        # --- 2. chat, both ways --------------------------------------------------
        plain, streamed = sdk(token, [
            {"kind": "chat", "model": f"gem/{CHAT}", "reasoning_effort": "low",
             "messages": [{"role": "system", "content": "Answer in one word."},
                          {"role": "user", "content": "ping"}]},
            {"kind": "chat", "model": f"gem/{CHAT}", "stream": True,
             "messages": [{"role": "user", "content": "ping"}]},
        ])[:2]
        for result in (plain, streamed):
            assert result["status"] == 200, result
            assert result["message"]["content"] == "pong" and result["finish"] == "stop", result
            assert result["message"].get("reasoning_content") == "Thinking it over.", result
            usage = result["usage"]
            assert (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]) == (7, 7, 14), usage
            assert usage["completion_tokens_details"]["reasoning_tokens"] == 5, usage
            assert usage["prompt_tokens_details"]["cached_tokens"] == 3, usage
        sent = [s for s in seen(CHAT) if s["method"] == "generateContent"][-1]["body"]
        assert sent["systemInstruction"] == {"parts": [{"text": "Answer in one word."}]}, sent
        assert sent["contents"] == [{"role": "user", "parts": [{"text": "ping"}]}], sent
        assert sent["generationConfig"]["thinkingConfig"] == {"includeThoughts": True, "thinkingLevel": "low"}, sent
        streamed_call = [s for s in seen(CHAT) if s["method"] == "streamGenerateContent"][-1]
        assert streamed_call["query"].get("alt") == "sse", streamed_call["query"]
        ok("chat through the unchanged OpenAI SDK, plain and streamed: the system prompt as systemInstruction, "
           "reasoning_effort as thinkingLevel, thoughts back as reasoning, usage with thoughts and cache")

        # --- 3. a tool round trip keeps the thought signature ------------------------
        trips = sdk(token, [
            {"kind": "round_trip", "model": f"gem/{CHAT}", "ask": "What is the weather in Paris?"},
            {"kind": "round_trip", "model": f"gem/{CHAT}", "ask": "What is the weather in Paris?",
             "stream": True},
        ])[:2]
        for trip in trips:
            assert trip["status"] == 200 and trip["second"], trip
            first, second = trip["first"], trip["second"]
            assert first["finish"] == "tool_calls", first
            calls = first["message"]["tool_calls"]
            assert [c["function"]["name"] for c in calls] == ["get_weather"], calls
            assert json.loads(calls[0]["function"]["arguments"]) == {"city": "Paris"}, calls
            assert second["status"] == 200 and second["message"]["content"].startswith("It is sunny"), second
        assert stats()["signed_ok"] == 2 and stats()["unsigned"] == 0, stats()
        returned = [s for s in seen(CHAT) if any(
            "functionResponse" in p for c in s["body"]["contents"] for p in c["parts"])][-1]["body"]
        assert returned["contents"][-1]["parts"][0]["functionResponse"]["name"] == "get_weather", returned
        assert returned["contents"][-1]["parts"][0]["functionResponse"]["response"] == {"sky": "sunny", "celsius": 21}
        declared = returned["tools"][0]["functionDeclarations"][0]
        assert declared["name"] == "get_weather" and "parametersJsonSchema" in declared, declared
        ok("a tool call and its result, plain and streamed, from a client that cannot carry Gemini's thought "
           "signature: the driver put it back, and Google's check passed both times (G2)")

        # --- 4. a driver restart loses it, and says so -----------------------------
        stop("gem")
        start("gem", {"GEMINI_API_KEY": fake_key})
        wait(lambda: call("gem", "GET", "/v1/info", operator).json()["catalogue"].get("exposed") == 6,
             "the restarted driver lists its models")
        replay = sdk(token, [{"kind": "chat", "model": f"gem/{CHAT}", "with_tools": True,
                              "messages": trips[0]["messages"]}])[0]
        assert replay["status"] == 400, replay
        assert "before the driver restarted" in replay["error"] and "thought" in replay["error"], replay
        assert stats()["unsigned"] == 1, stats()
        ok("after a driver restart the same conversation is refused by Google, and the answer says the "
           "signature was lost with the restart, not that the request was malformed")

        # --- 5. what Gemini cannot honour, and what it stopped ------------------------
        before = len(seen(CHAT))
        refused, stopped, echoed = sdk(token, [
            {"kind": "chat", "model": f"gem/{CHAT}", "logit_bias": {"50256": -100},
             "messages": [{"role": "user", "content": "ping"}]},
            {"kind": "chat", "model": f"gem/{CHAT}", "messages": [{"role": "user", "content": "unsafe"}]},
            {"kind": "chat", "model": f"gem/{CHAT}", "messages": [{"role": "user", "content": "echo-key"}]},
        ])[:3]
        assert refused["status"] == 400 and "logit_bias" in refused["error"], refused
        assert len(seen(CHAT)) == before + 2, "logit_bias reached Google"
        assert stopped["status"] == 200 and stopped["finish"] == "content_filter", stopped
        assert "finishReason=SAFETY" in stopped["message"]["content"], stopped
        assert echoed["status"] == 400 and fake_key not in json.dumps(echoed), "the key came back"
        assert "<redacted>" in echoed["error"], echoed
        ok("logit_bias is refused naming it and never sent; an answer Google stopped is content_filter with "
           "its reason; an error quoting the key comes back with the key redacted")

        # --- 6. embeddings, an image, speech, transcription ------------------------
        clip = directory / "fixture-clip.wav"
        clip.write_bytes(wav(PCM))
        spoken = directory / "spoken.wav"
        embedded, image, speech, named_mp3, heard = sdk(token, [
            {"kind": "embed", "model": f"gem/{EMBED}", "input": ["one", "three", "seven"]},
            {"kind": "image", "model": f"gem/{IMAGE}", "prompt": "a blue square"},
            {"kind": "speech", "model": f"gem/{TTS}", "voice": "Kore", "input": "Hello.", "save": str(spoken)},
            {"kind": "speech", "model": f"gem/{TTS}", "voice": "Kore", "input": "Hello.", "response_format": "mp3"},
            {"kind": "transcribe", "model": f"gem/{TRANSCRIBE}", "file": str(clip)},
        ])[:5]
        assert embedded["status"] == 200, embedded
        assert embedded["vectors"] == [[0.0, 3.0, 0.5], [1.0, 5.0, 0.5], [2.0, 5.0, 0.5]], embedded
        assert image["status"] == 200 and base64.b64decode(image["b64"][0])[:8] == b"\x89PNG\r\n\x1a\n", image
        assert seen(IMAGE)[-1]["body"]["generationConfig"] == {"responseModalities": ["TEXT", "IMAGE"]}
        assert speech["status"] == 200 and speech["type"] == "audio/wav", speech
        made = spoken.read_bytes()
        assert made[:4] == b"RIFF" and made[8:12] == b"WAVE" and made[44:] == PCM, made[:44]
        assert struct.unpack("<I", made[24:28])[0] == 24000, made[:44]
        voice = seen(TTS)[0]["body"]["generationConfig"]
        assert voice["responseModalities"] == ["AUDIO"], voice
        assert voice["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore", voice
        assert named_mp3["status"] == 400 and "wav, pcm" in named_mp3["error"], named_mp3
        assert len(seen(TTS)) == 1, "mp3 reached Google"
        assert heard["status"] == 200 and heard["text"] == "Eugene Plexus says hello.", heard
        audio_part = seen(TRANSCRIBE)[-1]["body"]["contents"][0]["parts"][0]["inlineData"]
        assert audio_part["mimeType"] == "audio/wav", audio_part
        ok("embeddings in order, an image, speech (no format named: a whole WAV around Google's 24 kHz PCM; "
           "mp3 named: refused, naming wav and pcm) and a transcription, each through the SDK")

        # --- 7. a Veo video, polled and fetched --------------------------------------
        video = sdk(token, [{"kind": "video", "model": f"gem/{VEO}", "prompt": "a red ball rolling",
                             "seconds": "4", "size": "1280x720", "poll_ms": 300}])[0]
        assert video["status"] == 200 and video["video"]["status"] == "completed", video
        assert video["length"] == len(MP4) and bytes.fromhex(video["head"]) == MP4[:12], video
        submitted = [s for s in seen(VEO) if s["method"] == "predictLongRunning"][-1]["body"]
        assert submitted["instances"] == [{"prompt": "a red ball rolling"}], submitted
        assert submitted["parameters"]["aspectRatio"] == "16:9" and submitted["parameters"]["resolution"] == "720p"
        assert str(submitted["parameters"]["durationSeconds"]) == "4", submitted
        assert stats()["storage"] == 1 and stats()["storage_with_key"] == 0, stats()
        ok("a 4-second 720p Veo video as a polled job, downloaded through a redirect to storage that was "
           "followed without the key")

        assert stats()["key_in_url"] == 0, stats()
        ok("the key rode x-goog-api-key on every request and never a URL")

        # --- 8. the live Gemini API ----------------------------------------------------
        if live:
            run_live(call, wait, listing, sdk, operator, token, directory, ok, live_video=live_video)

        (directory / "summary.json").write_text(json.dumps({"passed": passed}, indent=2), encoding="utf-8")
        print(f"{passed} PASS", flush=True)
    finally:
        for name in reversed(list(processes)):
            stop(name)
        client.close()
        for output in logs:
            output.close()


def _pick(ids: list[str], *preferences: str, contains: str | None = None) -> str | None:
    for wanted in preferences:
        if wanted in ids:
            return wanted
    if contains:
        found = sorted(i for i in ids if contains in i)
        return found[0] if found else None
    return None


def run_live(call, wait, listing, sdk, operator, token, directory, ok, *, live_video: bool) -> None:
    wait(lambda: any(i.startswith("live/") for i in listing()), "the live account's models", 90)
    catalogue = call("live", "GET", "/v1/info", operator).json()
    by_surface: dict[str, list[str]] = {}
    for model in catalogue["models"]:
        for surface in model.get("surfaces") or []:
            by_surface.setdefault(surface, []).append(model["id"])
    thinking = sorted(m["id"] for m in catalogue["models"]
                      if "reasoningEffort" in ((m.get("capabilities") or {}).get("supportedSettings") or []))
    print("INFO live listing: " + ", ".join(f"{s} {len(v)}" for s, v in sorted(by_surface.items())), flush=True)
    chat = _pick(thinking, "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash", contains="flash")
    embed = _pick(by_surface.get("embeddings", []), "gemini-embedding-001", contains="embedding")
    image = _pick(by_surface.get("image", []), "gemini-3.1-flash-image", contains="image")
    tts = _pick(by_surface.get("speech", []), "gemini-3.8-flash-tts", contains="tts")
    hear = _pick(by_surface.get("transcription", []), "gemini-3.5-transcribe", contains="transcribe") or chat
    veo = _pick(by_surface.get("video", []), "veo-3.1-lite-generate-preview", contains="lite")
    print(f"INFO live picks: chat {chat}, embeddings {embed}, image {image}, speech {tts}, "
          f"transcription {hear}, video {veo}", flush=True)
    assert chat and embed and image and tts and hear, "the live listing lacks a surface"

    trips = sdk(token, [
        {"kind": "round_trip", "model": f"live/{chat}", "reasoning_effort": "low",
         "ask": "What is the weather in Paris right now? Use the tool, then answer in one sentence."},
        {"kind": "round_trip", "model": f"live/{chat}", "stream": True,
         "ask": "What is the weather in Paris right now? Use the tool, then answer in one sentence."},
    ], timeout=600)[:2]
    for trip in trips:
        assert trip["status"] == 200, trip
        assert trip["first"]["finish"] == "tool_calls", trip["first"]
        assert trip["second"] and trip["second"]["status"] == 200, trip
        assert (trip["second"]["message"].get("content") or "").strip(), trip["second"]
        print(f"INFO live round trip: {trip['second']['message']['content'][:120]!r} "
              f"usage {trip['first']['usage']} then {trip['second']['usage']}", flush=True)
    ok(f"live: a tool round trip on {chat}, plain and streamed, with the thought signature put back")

    spoken = directory / "live-spoken.wav"
    embedded, speech = sdk(token, [
        {"kind": "embed", "model": f"live/{embed}", "input": ["Eugene Plexus", "a local control plane"]},
        {"kind": "speech", "model": f"live/{tts}", "voice": "Kore",
         "input": "Hello from Eugene Plexus.", "save": str(spoken)},
    ], timeout=600)[:2]
    assert embedded["status"] == 200 and len(embedded["vectors"]) == 2, embedded
    assert len(embedded["vectors"][0]) == len(embedded["vectors"][1]) > 0, "vectors differ"
    assert speech["status"] == 200 and speech["type"] == "audio/wav", speech
    assert spoken.read_bytes()[:4] == b"RIFF" and len(spoken.read_bytes()) > 10_000, speech
    heard = sdk(token, [{"kind": "transcribe", "model": f"live/{hear}", "file": str(spoken)}], timeout=300)[0]
    assert heard["status"] == 200 and "hello" in heard["text"].lower(), heard
    print(f"INFO live: embeddings of {len(embedded['vectors'][0])} dimensions; speech "
          f"{speech['length']} bytes; heard {heard['text']!r}", flush=True)
    ok(f"live: embeddings ({embed}), speech ({tts}) and it heard back ({hear})")

    def no_quota(result: dict) -> bool:
        # A key on Google's free tier may have no quota for paid-only models:
        # Google's own refusal, reported as not run rather than passed.
        return result.get("status") == 429 and "quota" in str(result.get("error", "")).lower()

    picture = sdk(token, [{"kind": "image", "model": f"live/{image}",
                           "prompt": "A small flat icon of a blue gear, white background."}], timeout=600)[0]
    if no_quota(picture):
        print(f"NOT RUN live image on {image}: {picture['error'][:300]}", flush=True)
    else:
        assert picture["status"] == 200 and picture["b64"] and picture["b64"][0], picture
        head = base64.b64decode(picture["b64"][0])[:12]
        assert head[:8] == b"\x89PNG\r\n\x1a\n" or head[:3] == b"\xff\xd8\xff" or head[8:12] == b"WEBP", head
        print(f"INFO live image: usage {picture['usage']}", flush=True)
        ok(f"live: an image on {image}")

    if live_video and veo:
        made = sdk(token, [{"kind": "video", "model": f"live/{veo}", "seconds": "4", "size": "1280x720",
                            "prompt": "A slow pan across a tidy workbench with hand tools.",
                            "poll_ms": 5000}], timeout=900)[0]
        if no_quota(made):
            print(f"NOT RUN live video on {veo}: {made['error'][:300]}", flush=True)
        else:
            assert made["status"] == 200 and made["video"]["status"] == "completed", made
            assert made["length"] > 10_000 and bytes.fromhex(made["head"])[4:8] == b"ftyp", made
            print(f"INFO live video: {made['length']} bytes in {made['took']}s", flush=True)
            ok(f"live: a 4-second 720p video on {veo}, polled and downloaded")
    elif live_video:
        print("INFO live: no Veo lite model is listed for this key; the video was not made", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--live-no-video", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-gemini-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.live, live_video=not args.live_no_video)
