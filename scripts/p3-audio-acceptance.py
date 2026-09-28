"""P3: speech and transcription, at `/v1/audio/*`, through real signed processes.

A control root, an enrolled agent, a gateway and five inference-drivers, all
started here with isolated state and ports:

* `router` -- the real `openrouter` provider, its `baseUrl` a fixture playing
  OpenRouter: an account listing (`/v1/models/user`) with two speech models,
  two transcription models and one chat model; OpenRouter's
  `/v1/audio/speech`, which makes `mp3` and `pcm` only; and its
  `/v1/audio/transcriptions`, which answers `json` or `verbose_json` and
  refuses `text` (all measured 2026-09-28);
* `llama` -- a single-model `openai_compat_custom` driver against a fixture
  playing `llama-server` b11235 with Qwen3-ASR: `/props` says it hears, it
  answers `json` only, and its text carries the model's own preamble;
* `eleven`, `voiceless` and `scoped` -- the real `elevenlabs` provider, each
  with its own key, against a fixture playing ElevenLabs' API as measured on
  2026-09-28: `xi-api-key`, the voice in the path, `output_format` in the
  query, `text` and `model_id` in the body, and its error bodies word for
  word. `eleven`'s key reads models and voices; `voiceless`'s reads models
  only; `scoped`'s reads neither, like the key Troy was given.

The fixture streams its audio in six chunks, and 0.4 s apart when the text
carries `[slow]`, so a check can tell streamed bytes from buffered ones by
the clock. It counts every speech request per model and keeps each one, so
a check can say what reached an upstream and what did not.

**The OpenAI Python SDK makes the requests the done-when names**, unchanged,
from its own interpreter: this one if it has `openai`, else `$EP_SDK_PYTHON`.

No live service is touched unless `--live` is passed, which adds OpenRouter
(`hexgrad/kokoro-82m` speaks; `google/gemini-2.5-flash-lite` hears it back;
`openai/whisper-large-v3-turbo` transcribes), ElevenLabs (`eleven_flash_v2_5`
speaks, as WAV and streamed mp3) and an OpenAI account (`tts-1` speaks;
`whisper-1` and `gpt-4o-mini-transcribe` transcribe) with the keys in
`C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or `$EP_KEYS`).
Each key is handed to its driver only in the environment variable the engine
already falls back to (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`), and the last
check scans the run's state for both. The live run costs well under a cent.

`--llama-server DIR` adds a real `llama-server` on this machine: DIR holds
`llama/llama-server[.exe]`, `Qwen3-ASR-0.6B-Q8_0.gguf` and its
`mmproj-Qwen3-ASR-0.6B-Q8_0.gguf` (on this box, the scratchpad's `m4/`). It
runs on the CPU and transcribes the fox locally, which is the done-when.

Run in an environment containing all five Python components (on this box,
`agent/.venv`). Logs and state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
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

import httpx
import yaml
from fastapi import Request

NODE_NAME = "p3-agent"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))

#: OpenRouter's account listing, trimmed: two speech models, one of them
#: listing voices (most do) and one not (fish-audio's and bytedance's do not),
#: and a chat model.
OR_LISTING = {
    "acme/kokoro": {"output": ["speech"], "voices": ["af_heart", "af_bella"]},
    "acme/flux": {"output": ["speech"], "voices": None},
    "acme/chat": {"output": ["text"], "voices": None},
    # Transcription: audio in, and no parameters listed (measured).
    "acme/whisper": {"output": ["transcription"], "input": ["audio"], "voices": None},
    "acme/whisper-2": {"output": ["transcription"], "input": ["audio"], "voices": None},
}
#: What the transcription fixtures heard, and the file the SDK uploads.
FOX = Path(__file__).resolve().parent / "fixtures" / "p2-fox.mp3"
SAID = "The quick brown fox jumps over the lazy dog."
#: ElevenLabs' account list: the speech-to-speech model says it cannot do
#: text to speech and must not be offered.
EL_MODELS = [
    {"model_id": "eleven_flash_v2_5", "name": "Eleven Flash v2.5", "can_do_text_to_speech": True},
    {"model_id": "eleven_multilingual_v2", "name": "Eleven Multilingual v2", "can_do_text_to_speech": True},
    {"model_id": "eleven_multilingual_sts_v2", "name": "Eleven Multilingual v2 (STS)",
     "can_do_text_to_speech": False},
]
EL_VOICES = ["21m00Tcm4TlvDq8ikWAM", "EXAVITQu4vr4xnSDxMaL"]
#: The three fixture keys. `scoped` is the measured case: it can speak and
#: cannot list models or voices.
EL_KEYS = {"eleven": "fixture-el-full", "voiceless": "fixture-el-novoices", "scoped": "fixture-el-scoped"}
#: ElevenLabs' `output_format` -> (our format, its media type), measured.
EL_FORMATS = {"mp3_44100_128": ("mp3", "audio/mpeg"), "pcm_24000": ("pcm", "audio/pcm"),
              "opus_48000_64": ("opus", "audio/opus")}
#: What each format streams. `pcm` does not open with a RIFF header, so a WAV
#: in an answer can only be one this driver made.
AUDIO = {
    "mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes(range(256)) * 24,
    "pcm": bytes((i * 7) % 256 for i in range(6144)),
    "opus": b"OggS\x00\x02" + bytes(range(256)) * 24,
}
CHUNKS = 6
GAP = 0.4
#: The live models, measured on OpenRouter 2026-09-28.
LIVE_SPEAKS = "hexgrad/kokoro-82m"
LIVE_HEARS = "google/gemini-2.5-flash-lite"
#: Whisper, not qwen3-asr: on 2026-09-28 OpenRouter's `qwen/qwen3-asr-0.6b`
#: answered the fox in 0.6 s in the morning and hung past 90 s on every file
#: in the afternoon, while Whisper took our streaming WAV in 2.3 s.
LIVE_TRANSCRIBES = "openai/whisper-large-v3-turbo"
#: ElevenLabs' cheapest speech model, and an OpenAI account's speech and two
#: transcription models (the key Troy added 2026-09-28).
LIVE_EL = "eleven_flash_v2_5"
LIVE_OPENAI = ["tts-1", "whisper-1", "gpt-4o-mini-transcribe"]

#: Transcription through the SDK. Each job is `audio.transcriptions.create`
#: arguments with `file` a path, or `translate: true` for the other door; the
#: answer is reported as the SDK typed it.
SDK_TRANSCRIBE = """
import json, sys
import openai
args = json.loads(sys.argv[1])
client = openai.OpenAI(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=120)
out = []
for job in args["jobs"]:
    translate = job.pop("translate", False)
    door = client.audio.translations if translate else client.audio.transcriptions
    try:
        with open(job.pop("file"), "rb") as fh:
            answer = door.create(file=fh, **job)
    except openai.APIStatusError as e:
        out.append({"status": e.status_code, "error": e.message})
        continue
    if isinstance(answer, str):
        out.append({"status": 200, "kind": "str", "text": answer})
    else:
        out.append({"status": 200, "kind": type(answer).__name__, "body": answer.model_dump()})
print(json.dumps(out))
"""

#: What the SDK does, in its own interpreter. `jobs` are
#: `audio.speech.create` arguments; each is streamed and timed, and the first
#: is also made the ordinary way, as most code calls it.
SDK_SNIPPET = """
import hashlib, json, sys, time
import openai
args = json.loads(sys.argv[1])
client = openai.OpenAI(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=60)
out = []
for job in args["jobs"]:
    save = job.pop("save", None)
    started = time.perf_counter()
    arrivals, data = [], b""
    try:
        with client.audio.speech.with_streaming_response.create(**job) as response:
            status, kind = response.status_code, response.headers.get("content-type")
            for chunk in response.iter_bytes():
                arrivals.append(round(time.perf_counter() - started, 3))
                data += chunk
    except openai.APIStatusError as e:
        out.append({"status": e.status_code, "error": e.message})
        continue
    if save:
        open(save, "wb").write(data)
    out.append({"status": status, "type": kind, "sha": hashlib.sha256(data).hexdigest(),
                "length": len(data), "arrivals": arrivals})
first = dict(args["jobs"][0])
first.pop("save", None)
made = client.audio.speech.create(**first)
out.append({"sha": hashlib.sha256(made.content).hexdigest(), "length": len(made.content),
            "sdk": openai.__version__})
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


def wav_header(data: bytes) -> tuple:
    """The 44-byte header's fields: what a player reads before the samples."""
    riff, size, wave, fmt, length, pcm, channels, rate, byte_rate, block, bits, tag, data_size = struct.unpack(
        "<4sI4s4sIHHIIHH4sI", data[:44])
    return riff, size, wave, fmt, length, pcm, channels, rate, byte_rate, block, bits, tag, data_size


STREAMING_WAV = (b"RIFF", 0xFFFFFFFF, b"WAVE", b"fmt ", 16, 1, 1, 24000, 48000, 2, 16, b"data", 0xFFFFFFFF)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        counts: dict[str, int] = {}
        seen: dict[str, list[dict]] = {}
        #: Per upstream model: "ok", "busy" (a 429 before any audio) or
        #: "cut" (two chunks, then the connection drops).
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

        def audio(model, fmt, media, slow, *, whole=False):
            body = AUDIO[fmt]
            size = -(-len(body) // CHUNKS)
            pieces = [body[i:i + size] for i in range(0, len(body), size)]
            cut = modes.get(model) == "cut"

            async def stream():
                if whole:
                    # A route that answers once the audio is made.
                    if slow:
                        await asyncio.sleep(GAP * CHUNKS)
                    yield body
                    return
                for index, piece in enumerate(pieces):
                    if cut and index == 2:
                        raise ConnectionResetError("the fixture dropped the connection")
                    yield piece
                    if slow:
                        await asyncio.sleep(GAP)

            return StreamingResponse(stream(), media_type=media)

        # --- OpenRouter ---------------------------------------------------

        @app.get("/v1/models/user")
        async def or_listing():
            return {"data": [
                {
                    "id": model_id, "name": model_id, "context_length": 4096,
                    "architecture": {"input_modalities": entry.get("input", ["text"]),
                                     "output_modalities": entry["output"]},
                    # No speech or transcription model lists any parameter (measured).
                    "supported_parameters": [] if "text" not in entry["output"] else ["max_tokens"],
                    **({"supported_voices": entry["voices"]} if entry["voices"] else {}),
                }
                for model_id, entry in OR_LISTING.items()
            ]}

        @app.post("/v1/audio/speech")
        async def or_speech(request: Request):
            body = await request.json()
            model = body.get("model")
            record(model, {"body": body, "accept": request.headers.get("accept")})
            if "speech" not in OR_LISTING.get(model, {}).get("output", []):
                return JSONResponse({"error": {"message": f"No endpoints found for {model}.", "code": 404}},
                                    status_code=404)
            if modes.get(model) == "busy":
                return JSONResponse({"error": {"message": "Rate limit exceeded: free-models-per-min.",
                                               "code": 429}}, status_code=429, headers={"Retry-After": "1"})
            # OpenRouter's own default is pcm (measured), not OpenAI's mp3.
            fmt = body.get("response_format", "pcm")
            if fmt not in ("mp3", "pcm"):
                # A Zod 400 listing the two it takes (measured; wording trimmed).
                return JSONResponse({"error": {"message": f"Invalid option: expected one of \"mp3\"|\"pcm\" "
                                               f"at response_format (got {fmt!r})", "code": 400}}, status_code=400)
            return audio(model, fmt, {"mp3": "audio/mpeg", "pcm": "audio/pcm"}[fmt], "[slow]" in body.get("input", ""))

        async def heard(request, model_field="model"):
            """A transcription upload as it arrived, recorded under its model."""
            form = await request.form()
            upload = form.get("file")
            data = await upload.read() if upload is not None and not isinstance(upload, str) else b""
            fields = {k: form.getlist(k) if k.endswith("[]") else form.get(k) for k in form if k != "file"}
            model = form.get(model_field)
            record(model, {"fields": fields, "filename": getattr(upload, "filename", None),
                           "type": getattr(upload, "content_type", None), "size": len(data),
                           "sha": hashlib.sha256(data).hexdigest()})
            return model, fields

        @app.post("/v1/audio/transcriptions")
        async def or_transcribe(request: Request):
            model, fields = await heard(request)
            if "transcription" not in OR_LISTING.get(model, {}).get("output", []):
                return JSONResponse({"error": {"message": f"No endpoints found for {model}.", "code": 404}},
                                    status_code=404)
            if modes.get(model) == "busy":
                return JSONResponse({"error": {"message": "Rate limit exceeded: free-models-per-min.",
                                               "code": 429}}, status_code=429, headers={"Retry-After": "1"})
            fmt = fields.get("response_format") or "json"
            if fmt not in ("json", "verbose_json"):
                # `text` is a 400 naming the two it makes (measured).
                return JSONResponse({"error": {"message": "response_format must be json or verbose_json",
                                               "code": 400}}, status_code=400)
            usage = {"seconds": 3.5, "cost": 0.0001}
            if fmt == "json":
                return {"text": " " + SAID, "usage": usage}
            granular = fields.get("timestamp_granularities[]") or []
            return {"task": "transcribe", "language": "english", "duration": 3.5, "text": SAID,
                    "segments": [{"id": 0, "start": 0.0, "end": 3.5, "text": SAID}],
                    **({"words": [{"word": "The", "start": 0.1, "end": 0.3}]} if "word" in granular else {}),
                    "usage": usage}

        # --- llama-server, with Qwen3-ASR -------------------------------------

        @app.get("/llama/props")
        async def llama_props():
            return {"modalities": {"vision": False, "audio": True},
                    "default_generation_settings": {"n_ctx": 4096}}

        @app.get("/llama/v1/models")
        async def llama_models():
            return {"data": [{"id": "local-asr", "object": "model"}]}

        @app.post("/llama/v1/audio/transcriptions")
        async def llama_transcribe(request: Request):
            _, fields = await heard(request)
            if (fields.get("response_format") or "json") != "json":
                return JSONResponse({"error": {"code": 400, "type": "invalid_request_error",
                                               "message": "Only 'json' response_format is supported"}},
                                    status_code=400)
            return {"type": "transcript.text.done", "text": "language English<asr_text>" + SAID,
                    "usage": {"type": "tokens", "input_tokens": 61, "output_tokens": 14, "total_tokens": 75}}

        # --- ElevenLabs -----------------------------------------------------

        def el_refusal(status, detail):
            return JSONResponse({"detail": detail}, status_code=status)

        def el_key(request, *, permission=None):
            key = request.headers.get("xi-api-key")
            if key not in EL_KEYS.values():
                return el_refusal(401, {"status": "needs_authorization",
                                        "message": "Neither authorization header nor xi-api-key received, "
                                                   "please provide one."})
            lacking = {"fixture-el-novoices": {"voices_read"},
                       "fixture-el-scoped": {"models_read", "voices_read"}}.get(key, set())
            if permission in lacking:
                return el_refusal(401, {"type": "authentication_error", "code": "unauthorized",
                                        "message": f"The API key you used is missing the permission {permission} "
                                                   "to execute this operation.",
                                        "status": "missing_permissions"})
            return None

        @app.get("/el/v1/models")
        async def el_models(request: Request):
            return el_key(request, permission="models_read") or EL_MODELS

        @app.get("/el/v1/voices")
        async def el_voices(request: Request):
            return el_key(request, permission="voices_read") or {
                "voices": [{"voice_id": v, "name": v[:6]} for v in EL_VOICES]}

        @app.post("/el/v1/text-to-speech/{voice}")
        async def el_speech_whole(voice: str, request: Request):
            """ElevenLabs' other route, which answers once the audio is made:
            a driver using it works, and is caught by the clock."""
            return await el_speech(voice, request, whole=True)

        @app.post("/el/v1/text-to-speech/{voice}/stream")
        async def el_speech(voice: str, request: Request, whole: bool = False):
            body = await request.json()
            model = body.get("model_id")
            record(model, {"body": body, "voice": voice, "query": dict(request.query_params),
                           "key": request.headers.get("xi-api-key")})
            refused = el_key(request)
            if refused is not None:
                return refused
            if voice not in EL_VOICES:
                return el_refusal(404, {"type": "not_found", "code": "voice_not_found",
                                        "message": f"A voice with voice_id '{voice}' was not found.",
                                        "status": "voice_not_found"})
            if model not in {m["model_id"] for m in EL_MODELS if m["can_do_text_to_speech"]}:
                return el_refusal(400, {"status": "model_not_found",
                                        "message": f"A model with model ID {model} does not exist ..."})
            output = request.query_params.get("output_format", "mp3_44100_128")
            if output.startswith("wav"):
                return el_refusal(403, {"status": "output_format_not_allowed",
                                        "message": f"Output format '{output}' is only available on the Pro "
                                                   "tier and above"})
            if output not in EL_FORMATS:
                return el_refusal(400, {"status": "invalid_output_format", "message": f"Invalid {output}"})
            fmt, media = EL_FORMATS[output]
            return audio(model, fmt, media, "[slow]" in body.get("text", ""), whole=whole)

    elif kind in ("router", "eleven", "voiceless", "scoped", "llama", "asr", "openrouter", "el-live",
                  "oai-live"):
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


def exercise(directory: Path, *, live: bool, llama_dir: Path | None = None) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ["control", "agent", "gateway", "fixture", "router", "eleven", "voiceless", "scoped", "llama"]
    if live:
        names += ["openrouter", "el-live", "oai-live"]
    if llama_dir is not None:
        names += ["llama-server", "asr"]
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
    passed = 0
    sdk = sdk_python()
    # Three keys, each handed only to its own driver, in the variable its
    # engine falls back to: OpenRouter's and OpenAI's both as OPENAI_API_KEY.
    live_keys = {
        "openrouter": _key("OPENROUTER_API_KEY"),
        "elevenlabs": _key("ELEVENLABS_API_KEY"),
        "openai": _key("OPENAI_API_KEY"),
    } if live else {}

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
        env.pop("ELEVENLABS_API_KEY", None)
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

    def speak(token, model, *, voice="af_heart", text="Hello there.", stream=False, **extra):
        body = {"model": model, "input": text, "voice": voice, **extra}
        if not stream:
            return call("gateway", "POST", "/v1/audio/speech", token, json=body)
        started = time.perf_counter()
        arrivals, data = [], b""
        with client.stream("POST", url("gateway") + "/v1/audio/speech", json=body,
                           headers={"Authorization": "Bearer " + token}) as response:
            for chunk in response.iter_raw():
                arrivals.append(time.perf_counter() - started)
                data += chunk
        return response, data, arrivals

    def by_sdk(token, jobs):
        result = subprocess.run(
            [sdk, "-c", SDK_SNIPPET, json.dumps({"base": url("gateway") + "/v1", "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=180,
            env={k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")},
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    def transcribe_by_sdk(token, jobs):
        result = subprocess.run(
            [sdk, "-c", SDK_TRANSCRIBE, json.dumps({"base": url("gateway") + "/v1", "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=300,
            env={k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")},
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    def upload(token, model, *, data=None, content=None, **fields):
        return client.post(
            url("gateway") + "/v1/audio/transcriptions",
            headers={"Authorization": "Bearer " + token},
            data={"model": model, **fields},
            files={"file": ("fox.mp3", FOX.read_bytes() if content is None else content, "audio/mpeg")},
        )

    def streamed(arrivals, label):
        """Nothing buffered: the first byte arrives long before the last is
        sent. A buffering hop delivers every byte at once, at the end."""
        first, last = arrivals[0], arrivals[-1]
        assert last >= (CHUNKS - 1) * GAP * 0.9, (label, arrivals)
        assert first < last * 0.4 and last - first >= (CHUNKS - 2) * GAP, (label, arrivals)
        return f"first byte {first:.2f} s, last {last:.2f} s"

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
        for name, key in EL_KEYS.items():
            driver(name, {"provider": "elevenlabs", "baseUrl": url("fixture") + "/el"}, {"ELEVENLABS_API_KEY": key})
        driver("llama", {"provider": "openai_compat_custom", "baseUrl": url("fixture") + "/llama",
                         "modelId": "local-asr", "backendLocality": "local"}, {})
        slots = [
            {"model": "narrator", "targets": ["router/acme/kokoro", "eleven/eleven_flash_v2_5"]},
            {"model": "scribe", "targets": ["router/acme/chat", "router/acme/whisper", "router/acme/whisper-2"]},
        ]
        if llama_dir is not None:
            binary = llama_dir / "llama" / ("llama-server.exe" if os.name == "nt" else "llama-server")
            output = (directory / "llama-server.log").open("ab")
            logs.append(output)
            processes["llama-server"] = subprocess.Popen(
                [str(binary), "-m", str(llama_dir / "Qwen3-ASR-0.6B-Q8_0.gguf"),
                 "--mmproj", str(llama_dir / "mmproj-Qwen3-ASR-0.6B-Q8_0.gguf"),
                 "--alias", "qwen3-asr", "--host", "127.0.0.1", "--port", str(ports["llama-server"]),
                 "-c", "4096"],
                stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            wait(lambda: call("llama-server", "GET", "/health").status_code == 200, "llama-server", 120)
            driver("asr", {"provider": "openai_compat_custom", "baseUrl": url("llama-server"),
                           "modelId": "qwen3-asr", "backendLocality": "local"}, {})
        if live:
            driver("openrouter", {"provider": "openrouter",
                                  "catalogueInclude": [LIVE_SPEAKS, LIVE_HEARS, LIVE_TRANSCRIBES]},
                   {"OPENAI_API_KEY": live_keys["openrouter"]})
            driver("el-live", {"provider": "elevenlabs"}, {"ELEVENLABS_API_KEY": live_keys["elevenlabs"]})
            driver("oai-live", {"provider": "openai", "catalogueInclude": LIVE_OPENAI},
                   {"OPENAI_API_KEY": live_keys["openai"]})
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

        wanted = {"router/acme/kokoro", "router/acme/flux", "router/acme/chat", "eleven/eleven_flash_v2_5",
                  "eleven/eleven_multilingual_v2", "voiceless/eleven_flash_v2_5", "narrator",
                  "router/acme/whisper", "router/acme/whisper-2", "local-asr", "scribe"}
        wait(lambda: wanted <= set(models()), "the fixture accounts' models are routable")

        # --- 1. what each model is listed with ----------------------------
        listed = models()
        assert listed["router/acme/kokoro"]["surfaces"] == ["speech"], listed["router/acme/kokoro"]
        assert listed["router/acme/kokoro"]["voices"] == ["af_heart", "af_bella"]
        assert listed["router/acme/kokoro"]["speech_formats"] == ["mp3", "wav", "pcm"]
        assert listed["router/acme/flux"].get("voices") is None
        assert listed["router/acme/chat"]["surfaces"] == ["chat"]
        assert listed["eleven/eleven_flash_v2_5"]["voices"] == EL_VOICES
        assert listed["eleven/eleven_flash_v2_5"]["speech_formats"] == ["mp3", "opus", "wav", "pcm"]
        assert "eleven/eleven_multilingual_sts_v2" not in listed
        # A key that cannot read voices still speaks: none listed, which is
        # not "no voices".
        assert listed["voiceless/eleven_flash_v2_5"].get("voices") is None
        assert not [m for m in listed if m.startswith("scoped/")], sorted(listed)
        ok("GET /v1/models lists each speech model with the voices its provider names (none where it names "
           "none) and the formats it can be given in; ElevenLabs' speech-to-speech model is not offered")

        info = call("scoped", "GET", "/v1/info", operator).json()
        error = (info.get("catalogue") or {}).get("error") or ""
        assert info.get("models") in ([], None) and "models_read" in error, info
        ok(f"a key without models_read offers no model, and /v1/info says why in ElevenLabs' words: {error!r}")

        # --- 2. the OpenAI SDK, unchanged, and nothing buffers --------------
        before = counts()
        results = by_sdk(key, [
            {"model": "eleven/eleven_flash_v2_5", "voice": EL_VOICES[0], "input": "Hello [slow] there.",
             "response_format": "mp3"},
            {"model": "router/acme/kokoro", "voice": "af_heart", "input": "Hello [slow] there."},
        ])
        for got, label in zip(results[:2], ("ElevenLabs", "OpenRouter"), strict=True):
            assert got["status"] == 200 and got["type"] == "audio/mpeg", got
            assert got["sha"] == hashlib.sha256(AUDIO["mp3"]).hexdigest(), (label, got["length"])
            print(f"INFO SDK through the gateway to {label}: {streamed(got['arrivals'], label)}", flush=True)
        assert results[2]["sha"] == hashlib.sha256(AUDIO["mp3"]).hexdigest(), results[2]
        after = counts()
        assert after.get("eleven_flash_v2_5", 0) == before.get("eleven_flash_v2_5", 0) + 2, (before, after)
        assert after.get("acme/kokoro", 0) == before.get("acme/kokoro", 0) + 1, (before, after)
        ok(f"the OpenAI SDK {results[2]['sdk']}, unchanged, gets ElevenLabs' and OpenRouter's audio byte for "
           "byte, streamed: the first byte arrives while the upstream is still sending, by the clock")

        response, data, arrivals = speak(key, "eleven/eleven_flash_v2_5", voice=EL_VOICES[0],
                                         text="A [slow] sentence.", stream=True, response_format="pcm")
        assert response.status_code == 200 and data == AUDIO["pcm"], (response.status_code, len(data))
        print(f"INFO raw pcm through two hops: {streamed(arrivals, 'pcm')}", flush=True)
        ok("pcm streams through the driver and the gateway as it is made, not collected and sent at the end")

        # --- 3. what reached each upstream ---------------------------------
        sent = last_seen("eleven_flash_v2_5")
        assert sent["voice"] == EL_VOICES[0] and sent["query"] == {"output_format": "pcm_24000"}, sent
        assert sent["body"] == {"text": "A [slow] sentence.", "model_id": "eleven_flash_v2_5"}, sent["body"]
        assert sent["key"] == EL_KEYS["eleven"], "the driver's own key was not the one sent"
        response = speak(key, "eleven/eleven_flash_v2_5", voice=EL_VOICES[1], speed=1.25)
        assert response.status_code == 200 and response.content == AUDIO["mp3"], response.status_code
        sent = last_seen("eleven_flash_v2_5")
        assert sent["query"] == {"output_format": "mp3_44100_128"}, sent["query"]
        assert sent["body"]["voice_settings"] == {"speed": 1.25}, sent["body"]
        ok("ElevenLabs is asked in its own shape: the voice in the path, output_format in the query, text and "
           "model_id in the body, speed as voice_settings, the driver's key as xi-api-key; mp3 when no format "
           "is named")

        response = speak(key, "router/acme/kokoro", speed=0.9, instructions="warmly")
        assert response.status_code == 200 and response.content == AUDIO["mp3"], response.status_code
        sent = last_seen("acme/kokoro")
        assert sent["body"] == {"model": "acme/kokoro", "input": "Hello there.", "voice": "af_heart",
                                "response_format": "mp3", "speed": 0.9, "instructions": "warmly"}, sent["body"]
        ok("OpenRouter is asked with the format always sent (its own default is pcm, OpenAI's mp3), and speed "
           "and instructions carried")

        # --- 4. wav, made from pcm where the backend has no wav ----------------
        for model, upstream, voice in (("router/acme/kokoro", "acme/kokoro", "af_heart"),
                                       ("eleven/eleven_flash_v2_5", "eleven_flash_v2_5", EL_VOICES[0])):
            response = speak(key, model, voice=voice, response_format="wav")
            assert response.status_code == 200, response.text[:300]
            assert response.headers["content-type"] == "audio/wav", response.headers["content-type"]
            assert wav_header(response.content) == STREAMING_WAV, wav_header(response.content)
            assert response.content[44:] == AUDIO["pcm"], len(response.content)
            sent = last_seen(upstream)
            asked = sent["body"].get("response_format") or sent["query"].get("output_format")
            assert asked in ("pcm", "pcm_24000"), asked
        ok("wav from OpenRouter and ElevenLabs is their pcm with a streaming WAV header written first "
           "(24 kHz, 16-bit, mono, sizes 0xFFFFFFFF), since neither makes wav on these plans")

        # --- 5. what a model cannot make is refused before any network -------
        before = counts()
        for model, fmt, named in (("router/acme/kokoro", "opus", "mp3, wav, pcm"),
                                  ("eleven/eleven_flash_v2_5", "aac", "mp3, opus, wav, pcm")):
            response = speak(key, model, voice="x", response_format=fmt)
            assert response.status_code == 400 and error_of(response).get("param") == "response_format", response.text
            assert named in error_of(response)["message"], error_of(response)
        # The driver's own copy of the rule, asked directly: the gateway's
        # refusal above would hide its absence.
        response = call("eleven", "POST", "/v1/speak", operator, json={
            "model": "eleven_flash_v2_5", "input": "hi", "voice": EL_VOICES[0], "format": "aac"})
        assert response.status_code == 400, response.text[:300]
        assert response.json()["detail"]["type"].endswith("#speech-refused"), response.text[:300]
        response = speak(key, "eleven/eleven_flash_v2_5", voice=EL_VOICES[0], instructions="warmly")
        assert response.status_code == 400 and "instructions" in error_of(response).get("message", ""), response.text
        response = speak(key, "router/acme/kokoro", stream_format="sse")
        assert response.status_code == 400 and error_of(response).get("param") == "stream_format", response.text
        assert counts() == before, (before, counts())
        ok("a format a model cannot be given in (at the gateway, and at the driver asked directly), "
           "instructions to ElevenLabs (which would drop them) and stream_format sse are 400s naming the "
           "field and what would work; no upstream is called")

        # --- 6. voices pass through, and the provider's refusal names them ---
        before = counts()
        response = speak(key, "eleven/eleven_flash_v2_5", voice="alloy")
        assert response.status_code == 400, response.text[:300]
        message = error_of(response).get("message", "")
        assert "alloy" in message and "not found" in message, message
        assert counts().get("eleven_flash_v2_5", 0) == before.get("eleven_flash_v2_5", 0) + 1
        ok(f"the SDK's default voice alloy is passed to ElevenLabs, which does not know it, and its refusal is "
           f"relayed as the caller's 400: {message[:110]!r}")

        # --- 7. the wrong door ----------------------------------------------
        before = counts()
        response = speak(key, "router/acme/chat")
        assert response.status_code == 400 and "/v1/chat/completions" in error_of(response).get("message", ""), response.text
        response = call("gateway", "POST", "/v1/chat/completions", key, json={
            "model": "router/acme/kokoro", "messages": [{"role": "user", "content": "hi"}]})
        # The model's own door, not the one a chat caller's refusal once named for everything.
        told = error_of(response).get("message", "")
        assert response.status_code == 400 and "Send this request to /v1/audio/speech" in told, response.text
        assert counts() == before, (before, counts())
        ok("speech to a chat model and chat to a speech model are each told the right door; no upstream is called")

        # --- 8. a client key's limits hold at this door ------------------------
        before = counts()
        scoped = mint("Only flux", allowedModels=["router/acme/flux"])
        response = speak(scoped, "router/acme/kokoro")
        assert response.status_code in (403, 404), response.text[:300]
        assert "router/acme/kokoro" not in models(scoped)
        response = speak(scoped, "router/acme/flux")
        assert response.status_code == 200 and response.content == AUDIO["mp3"], response.text[:300]
        local = mint("Local only", localOnly=True)
        response = speak(local, "router/acme/flux")
        assert response.status_code == 403 and "local" in error_of(response).get("message", "").lower(), response.text
        after = counts()
        assert after.get("acme/kokoro", 0) == before.get("acme/kokoro", 0), (before, after)
        assert after.get("acme/flux", 0) == before.get("acme/flux", 0) + 1, (before, after)
        ok("a key allowed only acme/flux cannot speak through acme/kokoro (and is not shown it), and a "
           "local-only key cannot reach a hosted voice; neither reaches an upstream")

        # --- 9. a slot speaks with its first model, never its second -----------
        assert listed["narrator"]["voices"] == ["af_heart", "af_bella"], listed["narrator"]
        assert listed["narrator"]["speech_formats"] == ["mp3", "wav", "pcm"], listed["narrator"]
        before = counts()
        response = speak(key, "narrator")
        assert response.status_code == 200 and response.content == AUDIO["mp3"], response.text[:300]
        after = counts()
        assert after.get("acme/kokoro", 0) == before.get("acme/kokoro", 0) + 1, (before, after)
        assert after.get("eleven_flash_v2_5", 0) == before.get("eleven_flash_v2_5", 0), (before, after)
        def recorded(response):
            """The retained row for this response, found by its own request id
            once the recorder has written it -- never an older row."""
            wanted, found = response.headers["x-request-id"], []

            def written():
                rows = call("gateway", "GET", "/v1/metrics/requests", operator, params={"limit": 20}).json()
                found[:] = [r for r in rows["requests"] if r.get("requestId") == wanted]
                return bool(found)
            wait(written, f"the metrics row for request {wanted}", 10)
            return found[0]

        row = recorded(response)
        assert row["outcome"] == "served" and row["servedModel"] == "router/acme/kokoro", row
        assert row["tier"] == 1 and [t["served"] for t in row["tries"]] == [True], row
        assert (row["door"], row["characters"]) == ("speech", len("Hello there.")), row
        ok("narrator -> [router/acme/kokoro, eleven/eleven_flash_v2_5] speaks with kokoro, is listed with "
           "kokoro's voices and formats, and is retained in /v1/metrics as served by kokoro at tier 1, "
           "in characters")

        call("fixture", "POST", "/mode", params={"model": "acme/kokoro", "mode": "cut"}).raise_for_status()
        before = counts()
        response = speak(key, "narrator")
        assert response.status_code == 200 and response.content == AUDIO["mp3"][:2 * -(-len(AUDIO["mp3"]) // CHUNKS)], \
            (response.status_code, len(response.content))
        after = counts()
        assert after.get("acme/kokoro", 0) == before.get("acme/kokoro", 0) + 1, (before, after)
        assert after.get("eleven_flash_v2_5", 0) == before.get("eleven_flash_v2_5", 0), (before, after)
        ok(f"after the first byte a dropped upstream ends the audio at {len(response.content)} bytes: "
           "the other voice does not finish the sentence, and kokoro is not asked again")

        call("fixture", "POST", "/mode", params={"model": "acme/kokoro", "mode": "busy"}).raise_for_status()
        before = counts()
        response = speak(key, "narrator")
        assert response.status_code >= 400, (response.status_code, response.text[:300])
        after = counts()
        assert after.get("acme/kokoro", 0) == before.get("acme/kokoro", 0) + 1, (before, after)
        assert after.get("eleven_flash_v2_5", 0) == before.get("eleven_flash_v2_5", 0), (before, after)
        print(f"INFO narrator with kokoro rate-limited: {response.status_code} {response.text[:200]}", flush=True)
        row = recorded(response)
        assert row["outcome"] == "error" and len(row["tries"]) == 1, row
        ok(f"with kokoro refusing before its first byte (a 429, which chat would cascade past), narrator "
           f"answers {response.status_code} and ElevenLabs is never asked: a speech failover never changes voice")
        call("fixture", "POST", "/mode", params={"model": "acme/kokoro", "mode": "ok"}).raise_for_status()

        # --- 10. transcription -------------------------------------------------------
        fox = FOX.read_bytes()
        fox_sha = hashlib.sha256(fox).hexdigest()
        listed = models()
        assert listed["router/acme/whisper"]["surfaces"] == ["transcription"], listed["router/acme/whisper"]
        assert listed["local-asr"]["surfaces"] == ["chat", "transcription"], listed["local-asr"]
        assert "transcription" in listed["scribe"]["surfaces"], listed["scribe"]
        ok("an OpenRouter transcription model is listed as transcription, and a llama-server whose projector "
           "hears as chat and transcription")

        before = counts()
        results = transcribe_by_sdk(key, [
            {"model": "router/acme/whisper", "file": str(FOX), "language": "en", "prompt": "Foxes."},
            {"model": "router/acme/whisper", "file": str(FOX), "response_format": "text"},
            {"model": "router/acme/whisper", "file": str(FOX), "response_format": "verbose_json",
             "timestamp_granularities": ["word", "segment"]},
        ])
        plain, text, verbose = results
        assert plain["status"] == 200 and plain["body"]["text"] == " " + SAID, plain
        assert plain["body"]["usage"]["type"] == "duration" and plain["body"]["usage"]["seconds"] == 3.5, plain
        assert text == {"status": 200, "kind": "str", "text": " " + SAID}, text
        body = verbose["body"]
        assert verbose["status"] == 200 and (body["language"], body["duration"]) == ("english", 3.5), verbose
        assert body["segments"][0]["text"] == SAID and body["words"][0]["word"] == "The", verbose
        assert counts().get("acme/whisper", 0) == before.get("acme/whisper", 0) + 3
        seen = call("fixture", "GET", "/seen", params={"model": "acme/whisper"}).json()[-3:]
        assert all((e["filename"], e["size"], e["sha"]) == ("p2-fox.mp3", len(fox), fox_sha) for e in seen), seen
        assert seen[0]["fields"] == {"model": "acme/whisper", "language": "en", "prompt": "Foxes."}, seen[0]
        # `text` was asked of nobody: OpenRouter refuses it, so it is made here.
        assert "response_format" not in seen[1]["fields"], seen[1]
        assert seen[2]["fields"]["response_format"] == "verbose_json", seen[2]
        assert seen[2]["fields"]["timestamp_granularities[]"] == ["word", "segment"], seen[2]
        ok("the OpenAI SDK, unchanged, transcribes through OpenRouter: the file arrives byte for byte under "
           "its name, json and verbose_json are the backend's with each granularity, and text is rendered "
           "here from json, since OpenRouter refuses it")

        results = transcribe_by_sdk(key, [
            {"model": "local-asr", "file": str(FOX)},
            {"model": "local-asr", "file": str(FOX), "response_format": "verbose_json"},
        ])
        assert results[0]["status"] == 200 and results[0]["body"]["text"] == SAID, results[0]
        # The SDK's message is its repr of the body, so the quotes arrive escaped.
        assert results[1]["status"] == 400 and "response_format is supported" in results[1]["error"], results[1]
        seen = call("fixture", "GET", "/seen", params={"model": "local-asr"}).json()
        assert seen[0]["fields"] == {"model": "local-asr"} and seen[0]["sha"] == fox_sha, seen[0]
        ok("llama-server's answer comes back without Qwen3-ASR's preamble, and verbose_json asked of it is "
           "its own refusal, relayed with its words")

        before = counts()
        # Each with its own reason, not only the field: srt and chunking_strategy
        # would otherwise also fall to the generic "not a value / not a field".
        for fields, param, reason in (
            ({"response_format": "srt"}, "response_format", "srt and vtt are not made here"),
            ({"stream": "true"}, "stream", "not served"),
            ({"chunking_strategy": "auto"}, "chunking_strategy", "not carried"),
            ({"timestamp_granularities[]": "word"}, "timestamp_granularities", "verbose_json"),
        ):
            response = upload(key, "router/acme/whisper", **fields)
            assert response.status_code == 400 and error_of(response).get("param") == param, response.text
            assert reason in error_of(response)["message"], response.text
        # The driver's own copy of the surface rule, asked directly.
        response = call("router", "POST", "/v1/transcribe", operator, json={
            "model": "acme/chat", "audio": {"data": base64.b64encode(fox).decode(), "filename": "fox.mp3"}})
        assert response.status_code == 400, response.text[:300]
        assert response.json()["detail"]["type"].endswith("#transcription-unsupported"), response.text[:300]
        response = upload(key, "router/acme/whisper", content=b"\0" * (25 * 1024 * 1024 + 1))
        assert response.status_code == 413 and error_of(response).get("param") == "file", response.text[:300]
        response = upload(key, "router/acme/chat")
        assert response.status_code == 400 and "/v1/chat/completions" in error_of(response).get("message", ""), response.text
        results = transcribe_by_sdk(key, [{"model": "router/acme/whisper", "file": str(FOX), "translate": True}])
        assert results[0]["status"] == 400 and "No backend here translates" in results[0]["error"], results[0]
        assert counts() == before, (before, counts())
        ok("srt, stream, chunking_strategy and timestamps without verbose_json are 400s naming the field and "
           "why, a file over 25 MiB is a 413 naming it, a chat model is sent to the chat door (and refused by "
           "the driver asked directly), and translation says no backend here translates; nothing reaches an "
           "upstream")

        call("fixture", "POST", "/mode", params={"model": "acme/whisper", "mode": "busy"}).raise_for_status()
        before = counts()
        response = upload(key, "scribe")
        assert response.status_code == 200 and response.json()["text"] == " " + SAID, response.text
        after = counts()
        assert after.get("acme/whisper", 0) == before.get("acme/whisper", 0) + 1, (before, after)
        assert after.get("acme/whisper-2", 0) == before.get("acme/whisper-2", 0) + 1, (before, after)
        assert after.get("acme/chat", 0) == before.get("acme/chat", 0), (before, after)
        row = recorded(response)
        assert (row["servedModel"], row["tier"], row["outcome"]) == ("router/acme/whisper-2", 3, "served"), row
        assert [t["served"] for t in row["tries"]] == [False, True], row
        assert (row["door"], row["audioSeconds"], row["characters"]) == ("transcription", 3.5, None), row
        call("fixture", "POST", "/mode", params={"model": "acme/whisper", "mode": "ok"}).raise_for_status()
        ok("scribe -> [chat, whisper, whisper-2] skips the chat model, and with whisper rate-limited is answered "
           "by whisper-2 at tier 3, as chat cascades; the row counts 3.5 seconds of audio")

        before = counts()
        scoped = mint("Only flux, again", allowedModels=["router/acme/flux"])
        response = upload(scoped, "router/acme/whisper")
        assert response.status_code in (403, 404), response.text[:300]
        local = mint("Local only, again", localOnly=True)
        response = upload(local, "router/acme/whisper")
        assert response.status_code == 403, response.text[:300]
        response = upload(local, "local-asr")
        assert response.status_code == 200 and response.json()["text"] == SAID, response.text[:300]
        after = counts()
        assert after.get("acme/whisper", 0) == before.get("acme/whisper", 0), (before, after)
        assert after.get("local-asr", 0) == before.get("local-asr", 0) + 1, (before, after)
        ok("a key allowed only acme/flux cannot transcribe, and a local-only key is refused a hosted "
           "transcriber and served by the local llama-server")

        if llama_dir is not None:
            wait(lambda: "qwen3-asr" in models(), "the real llama-server is routable", 60)
            assert models()["qwen3-asr"]["surfaces"] == ["chat", "transcription"], models()["qwen3-asr"]
            started = time.perf_counter()
            [answer] = transcribe_by_sdk(key, [{"model": "qwen3-asr", "file": str(FOX)}])
            took = time.perf_counter() - started
            assert answer["status"] == 200, answer
            local_text = answer["body"]["text"]
            assert "quick brown fox" in local_text.lower() and "<asr_text>" not in local_text, local_text
            print(f"INFO local llama-server (CPU): {local_text!r} in {took:.2f} s through the SDK", flush=True)
            ok(f"llama-server transcribes locally, on this machine's CPU, through the OpenAI SDK unchanged: "
               f"{local_text!r}")

        # --- 11. the live half ---------------------------------------------------
        if live:
            speaks_live, hears_live = f"openrouter/{LIVE_SPEAKS}", f"openrouter/{LIVE_HEARS}"
            wait(lambda: {speaks_live, hears_live} <= set(models()), "OpenRouter's live models", 60)
            voices = models()[speaks_live].get("voices") or []
            voice = "af_heart" if "af_heart" in voices else voices[0]
            clip = directory / "live.wav"
            sentence = "The zebra is blue and the kettle is singing."
            results = by_sdk(key, [
                {"model": speaks_live, "voice": voice, "input": sentence, "response_format": "wav",
                 "save": str(clip)},
                {"model": speaks_live, "voice": voice, "response_format": "mp3",
                 "input": "This is a longer sentence, so that the audio has a chance to arrive in pieces "
                          "while the rest of it is still being spoken by the model."},
            ])
            assert results[0]["status"] == 200 and results[0]["type"] == "audio/wav", results[0]
            raw = clip.read_bytes()
            assert wav_header(raw) == STREAMING_WAV and len(raw) > 44 + 48000, (wav_header(raw), len(raw))
            got = results[1]
            assert got["status"] == 200 and got["type"] == "audio/mpeg" and got["length"] > 10_000, got
            print(f"INFO live {LIVE_SPEAKS} voice {voice}: wav {(len(raw) - 44) / 48000:.2f} s; mp3 "
                  f"{got['length']} bytes in {len(got['arrivals'])} reads, first {got['arrivals'][0]:.2f} s, "
                  f"last {got['arrivals'][-1]:.2f} s", flush=True)
            response = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": hears_live, "max_tokens": 80,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Transcribe this recording exactly. Reply with the transcript only."},
                    {"type": "input_audio", "input_audio": {"data": base64.b64encode(raw).decode(), "format": "wav"}},
                ]}],
            })
            assert response.status_code == 200, response.text[:400]
            heard = response.json()["choices"][0]["message"]["content"] or ""
            said = {w for w in sentence.lower().strip(".").split() if len(w) >= 4}
            words = {"".join(c for c in w if c.isalpha()) for w in heard.lower().split()}
            assert len(said & words) * 2 >= len(said), (heard, sorted(said))
            ok(f"live: the OpenAI SDK gets {LIVE_SPEAKS}'s speech through the gateway as a WAV made from its pcm, "
               f"and {LIVE_HEARS} hears it back as {heard.strip()!r}")

            transcribes_live = f"openrouter/{LIVE_TRANSCRIBES}"
            wait(lambda: transcribes_live in models(), "OpenRouter's live transcription model", 60)
            [answer] = transcribe_by_sdk(key, [{"model": transcribes_live, "file": str(clip)}])
            assert answer["status"] == 200, answer
            words = {"".join(c for c in w if c.isalpha()) for w in answer["body"]["text"].lower().split()}
            assert len(said & words) * 2 >= len(said), (answer, sorted(said))
            ok(f"live: {LIVE_TRANSCRIBES} transcribes that WAV through the SDK as {answer['body']['text'].strip()!r}")

            # ElevenLabs, with the key widened on 2026-09-28 (it reads models
            # and voices now; P3-2 said no model is offered until it can).
            el_model = f"el-live/{LIVE_EL}"
            wait(lambda: el_model in models(), "ElevenLabs' live models", 60)
            el_voices = models()[el_model].get("voices") or []
            assert el_voices, models()[el_model]
            assert not [m for m in models() if m.startswith("el-live/") and "sts" in m], sorted(models())
            el_clip = directory / "el-live.wav"
            el_said = "The quick brown fox jumps over the lazy dog near the river bank."
            results = by_sdk(key, [
                {"model": el_model, "voice": el_voices[0], "input": el_said, "response_format": "wav",
                 "save": str(el_clip)},
                {"model": el_model, "voice": el_voices[0], "response_format": "mp3",
                 "input": "This longer sentence gives the audio a chance to arrive in pieces while the rest "
                          "of it is still being spoken."},
            ])
            assert results[0]["status"] == 200 and results[0]["type"] == "audio/wav", results[0]
            el_raw = el_clip.read_bytes()
            assert wav_header(el_raw) == STREAMING_WAV and len(el_raw) > 44 + 48000, (wav_header(el_raw), len(el_raw))
            got = results[1]
            assert got["status"] == 200 and got["type"] == "audio/mpeg" and got["length"] > 10_000, got
            print(f"INFO live ElevenLabs {LIVE_EL} voice {el_voices[0]}: wav {(len(el_raw) - 44) / 48000:.2f} s; "
                  f"mp3 {got['length']} bytes in {len(got['arrivals'])} reads, first {got['arrivals'][0]:.2f} s, "
                  f"last {got['arrivals'][-1]:.2f} s", flush=True)
            ok(f"live: ElevenLabs speaks through the gateway from the OpenAI SDK unchanged, {len(el_voices)} "
               f"voices listed: a WAV made from its pcm, and mp3 streamed")

            # An OpenAI account: its own speech and transcription models.
            tts, whisper, mini = (f"oai-live/{m}" for m in LIVE_OPENAI)
            wait(lambda: {tts, whisper, mini} <= set(models()), "OpenAI's live models", 60)
            assert models()[tts]["surfaces"] == ["speech"] and models()[whisper]["surfaces"] == ["transcription"]
            oai_clip = directory / "oai-live.mp3"
            results = by_sdk(key, [
                {"model": tts, "voice": "alloy", "input": el_said, "response_format": "mp3", "save": str(oai_clip)},
                {"model": tts, "voice": "alloy", "input": "Short.", "response_format": "wav"},
            ])
            assert results[0]["status"] == 200 and results[0]["type"] == "audio/mpeg", results[0]
            assert results[1]["status"] == 200 and results[1]["type"] == "audio/wav", results[1]
            answers = transcribe_by_sdk(key, [
                {"model": whisper, "file": str(el_clip)},
                {"model": mini, "file": str(oai_clip)},
                {"model": whisper, "file": str(oai_clip), "response_format": "verbose_json",
                 "timestamp_granularities": ["word"]},
            ])
            said_words = {w for w in el_said.lower().strip(".").split() if len(w) >= 4}
            for answer in answers:
                assert answer["status"] == 200, answer
                heard = {"".join(c for c in w if c.isalpha()) for w in answer["body"]["text"].lower().split()}
                assert len(said_words & heard) * 2 >= len(said_words), (answer, sorted(said_words))
            verbose = answers[2]["body"]
            assert verbose.get("language") and verbose.get("duration") and verbose.get("words"), verbose
            print(f"INFO live OpenAI: whisper-1 heard ElevenLabs as {answers[0]['body']['text'].strip()!r}; "
                  f"gpt-4o-mini-transcribe heard tts-1 as {answers[1]['body']['text'].strip()!r}; "
                  f"{len(verbose['words'])} words timed", flush=True)
            ok("live: an OpenAI account speaks with tts-1 (mp3 and its own wav), whisper-1 transcribes the "
               "ElevenLabs clip, gpt-4o-mini-transcribe the tts-1 one, and whisper-1's verbose_json times each word")

            leaked = [str(p) for p in directory.rglob("*") if p.is_file()
                      and any(k.encode() in p.read_bytes() for k in live_keys.values())]
            assert not leaked, f"a live key was written to {len(leaked)} file(s) of the run's state"
            ok(f"none of the three live keys is in any of the {sum(1 for p in directory.rglob('*') if p.is_file())} files "
               "of the run's state and logs")

        # The fixture's ElevenLabs keys were handed over the same way.
        on_disk = [str(p) for p in directory.rglob("*") if p.is_file() and p.suffix in (".yaml", ".json")
                   and any(k.encode() in p.read_bytes() for k in EL_KEYS.values())]
        assert not on_disk, on_disk
        ok("the ElevenLabs keys reached their drivers in the environment only: no config file holds one")

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
    parser.add_argument("--llama-server", type=Path, dest="llama_dir")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-p3-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.live, llama_dir=args.llama_dir)
