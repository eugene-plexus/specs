"""P2: audio and PDFs in, audio out, and the missing chat fields, through real
signed processes.

A control root, an enrolled agent, a gateway and an OpenRouter-shaped
inference-driver, all started here with isolated state and ports. The driver
is a real `openrouter` provider whose `baseUrl` points at a fixture upstream
playing OpenRouter's account listing (`/v1/models/user`), so the driver's own
listing reader decides what each model takes. The fixture lists three models:

* `acme/text-only` -- text in;
* `acme/hears` -- text and audio in;
* `acme/reads` -- text and PDFs in;
* `acme/speaks` -- audio out, streamed as `pcm16` the way `gpt-audio` is;
* `acme/sings` -- audio out as one MP3, the way Lyria is;
* `acme/thinks` -- lists every setting P2c carries (logprobs, logit_bias,
  reasoning_effort, verbosity, prediction, web_search_options), answers with
  logprobs and citations, and calls a tool when one is forced.

A second fixture driver, `llama`, is a single-model `llama-server` (the
fixture's `/llama` prefix), the one kind of backend that counts a prompt
without generating (`/apply-template`, `/tokenize`).

Like OpenRouter with `provider.require_parameters`, the fixture refuses a
setting a model does not list with a 404.

Like OpenRouter, the fixture refuses an attachment its listing does not
confirm with a 404 *"No endpoints found that support input ..."*, a
non-streamed audio answer with a 400 *"Audio output requires stream: true"*
and a streamed one in any format but `pcm16` with OpenAI's 400, and it
counts every request per model and keeps the bodies it was sent, so a check
can say what reached the upstream and what did not.

No live service, model or provider is touched unless `--openrouter-live` is
passed, which adds a real OpenRouter account read with the key in
`C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or `$EP_KEYS`).
That key is handed to its driver process only in `OPENAI_API_KEY`, which
the engine already falls back to, so it is never written to a config file,
a log or this script's output; the last live check scans the run's state
for it. The live run costs about five cents, four of them Lyria's clip.

Run in an environment containing all five Python components (on this box,
`agent/.venv`). Logs and state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import yaml
from fastapi import Request

NODE_NAME = "p2-agent"
FOX = Path(__file__).resolve().parent / "fixtures" / "p2-fox.mp3"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))
PDF_PREFIX = "data:application/pdf;base64,"

#: What each fixture model takes, in OpenRouter's own listing words.
LISTING = {
    "acme/text-only": ["text"],
    "acme/hears": ["text", "audio"],
    "acme/reads": ["text", "file"],
    "acme/speaks": ["text"],
    "acme/sings": ["text"],
    "acme/thinks": ["text"],
}
#: The fixture models that give audio back (`output_modalities`).
SPEAKERS = {"acme/speaks", "acme/sings"}
#: Every model lists these (`supported_parameters`); `acme/thinks` lists P2C too.
BASE_PARAMS = ["max_tokens", "temperature", "tools", "tool_choice"]
P2C = ["logprobs", "top_logprobs", "logit_bias", "reasoning_effort", "verbosity", "prediction",
       "web_search_options"]
#: What the OpenRouter-shaped fixture answers a web search with: one citation,
#: and OpenRouter's own `file` note, which is not a citation.
CITATION = {"type": "url_citation", "url_citation": {"url": "https://example.org/canberra",
                                                     "title": "Canberra", "start_index": 0, "end_index": 0}}
FILE_NOTE = {"type": "file", "file": {"hash": "h", "name": "a.pdf", "content": []}}
#: What `acme/speaks` streams, in two fragments, and `acme/sings` sends whole.
#: The samples open with `FF FB 90 00`, a valid MPEG-1 Layer III header, and
#: no second header where it says the frame ends -- so they are `pcm16`, and
#: only a format check that trusts a lone frame sync would call them MP3.
PCM = b"\xff\xfb\x90\x00" + bytes(range(256)) * 150
SONG = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(256)) * 8
#: The two models the live run uses, both measured against OpenRouter
#: directly on 2026-09-28: the first answers the fox and the zebra, the
#: second is refused audio by OpenRouter itself.
#: LIVE_HEARS was google/gemini-2.5-flash-lite until 2026-10-03, which
#: OpenRouter retires on 2026-10-20 (its listing's `expiration_date`). Its
#: replacement's listing, read 2026-10-03: input text, audio and file (this
#: run asserts both), `tools`, no `logprobs` -- so `live-careful` still
#: routes past it -- and no `expiration_date`. Not yet run live.
LIVE_HEARS = "mistralai/voxtral-small-24b-2507"
LIVE_TEXT = "mistralai/mistral-nemo"
#: Audio out, measured 2026-09-28: `pcm16` streams only, and Lyria's MP3.
#: OpenAI retires gpt-audio-mini on 2027-01-20 (its deprecations page, read
#: 2026-10-03), naming gpt-audio-1.5, which OpenRouter does not list yet;
#: its other audio-out models are openai/gpt-audio, retiring the same day,
#: and Lyria. Kept until a replacement is listed.
LIVE_SPEAKS = "openai/gpt-audio-mini"
LIVE_SINGS = "google/lyria-3-clip-preview"
#: P2c: the listing names `reasoning_effort` for the first and
#: `web_search_options` for the second (measured 2026-09-28).
LIVE_THINKS = "openai/gpt-oss-20b"
LIVE_SEARCHES = "perplexity/sonar"
#: Forcing a named function: mistral-nemo lists `tool_choice` and its
#: providers refuse a named one (measured 2026-09-28), so gpt-4o-mini.
LIVE_CALLS = "openai/gpt-4o-mini"


def _openrouter_key() -> str:
    for line in KEYS_FILE.read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OPENROUTER_API_KEY":
            return value.strip().strip('"').strip("'")
    raise SystemExit(f"no OPENROUTER_API_KEY in {KEYS_FILE}")


def one_page_pdf(text: str) -> bytes:
    """A valid one-page PDF whose only content is `text` in Helvetica."""
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        # Per model the upstream was ASKED for: how many requests, and
        # every body, so a check can read the parts that arrived.
        counts: dict[str, int] = {}
        seen: dict[str, list[dict]] = {}

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return counts

        @app.get("/seen")
        async def seen_bodies(model: str):
            return seen.get(model, [])

        @app.get("/v1/models/user")
        async def listing():
            # OpenRouter's account listing, trimmed to the fields the
            # driver reads.
            return {
                "data": [
                    {
                        "id": model_id,
                        "name": model_id,
                        "context_length": 32768,
                        "architecture": {
                            "input_modalities": inputs,
                            "output_modalities": ["text", "audio"] if model_id in SPEAKERS else ["text"],
                        },
                        "supported_parameters": BASE_PARAMS + (P2C if model_id == "acme/thinks" else []),
                    }
                    for model_id, inputs in LISTING.items()
                ]
            }

        def spoken(model, body):
            """An audio answer, refused and shaped as measured 2026-09-28."""
            if model not in SPEAKERS:
                return JSONResponse(
                    {"error": {"message": "No endpoints found that support output audio", "code": 404}},
                    status_code=404,
                )
            if not body.get("stream"):
                return JSONResponse(
                    {"error": {"message": "Audio output requires stream: true", "code": 400}},
                    status_code=400,
                )
            fmt = (body.get("audio") or {}).get("format")
            if model == "acme/speaks" and fmt != "pcm16":
                return JSONResponse(
                    {"error": {"message": f"'audio.format' does not support '{fmt}' when stream=true. "
                               "Supported values are: 'pcm16'.", "code": 400}},
                    status_code=400,
                )
            if model == "acme/speaks":
                half = len(PCM) // 2
                deltas = [
                    {"role": "assistant", "content": ""},
                    {"audio": {"id": "audio_fixture", "transcript": "Hello"}},
                    {"audio": {"transcript": " there", "data": base64.b64encode(PCM[:half]).decode(),
                               "expires_at": 1790609721}},
                    {"audio": {"data": base64.b64encode(PCM[half:]).decode()}},
                ]
            else:
                deltas = [{"content": "[0.0:2.0] LA LA"}, {"audio": {"data": base64.b64encode(SONG).decode()}}]

            async def stream():
                for delta in deltas:
                    yield "data: " + json.dumps(
                        {"model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                    ) + "\n\n"
                yield "data: " + json.dumps(
                    {"model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                ) + "\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(stream(), media_type="text/event-stream")

        @app.get("/llama/v1/models")
        async def llama_models():
            return {"data": [{"id": "local-llama", "object": "model"}]}

        @app.post("/llama/apply-template")
        async def llama_template(request: Request):
            body = await request.json()
            return {"prompt": " ".join(str(m.get("content")) for m in body.get("messages") or [])}

        @app.post("/llama/tokenize")
        async def llama_tokenize(request: Request):
            body = await request.json()
            return {"tokens": list(range(len(str(body.get("content") or "").split())))}

        @app.post("/llama/v1/chat/completions")
        async def llama_chat(request: Request):
            return await chat(request)

        def logprobs_for(words, top):
            return {"content": [
                {"token": w, "logprob": -0.25, "bytes": list(w.encode()),
                 "top_logprobs": [{"token": w, "logprob": -0.25, "bytes": list(w.encode())}][:top]}
                for w in words
            ], "refusal": None}

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            model = body.get("model")
            counts[model] = counts.get(model, 0) + 1
            seen.setdefault(model, []).append(body)
            kinds = {
                {"input_audio": "audio", "file": "file", "image_url": "image"}[part["type"]]
                for message in body.get("messages") or []
                if isinstance(message.get("content"), list)
                for part in message["content"]
                if part.get("type") in ("input_audio", "file", "image_url")
            }
            refused = sorted(kinds - set(LISTING.get(model, [])))
            if refused:
                # OpenRouter's own answer, measured 2026-09-28 for audio.
                return JSONResponse(
                    {"error": {"message": f"No endpoints found that support input {refused[0]}", "code": 404}},
                    status_code=404,
                )
            if "audio" in (body.get("modalities") or []):
                return spoken(model, body)
            listed = BASE_PARAMS + (P2C if model == "acme/thinks" else [])
            unlisted = sorted(k for k in P2C if k in body and k not in listed)
            if unlisted and (body.get("provider") or {}).get("require_parameters"):
                # OpenRouter's answer when no provider takes every parameter.
                return JSONResponse(
                    {"error": {"message": "No endpoints found that can handle the requested parameters.",
                               "code": 404}},
                    status_code=404,
                )
            choice_of = body.get("tool_choice")
            if body.get("tools") and isinstance(choice_of, dict):
                call = {"id": "call_fixture", "type": "function",
                        "function": {"name": choice_of["function"]["name"], "arguments": '{"city": "Oslo"}'}}
                if body.get("stream"):

                    async def called():
                        for fragment in ({**call, "index": 0, "function": {**call["function"], "arguments": '{"city": '}},
                                         {"index": 0, "function": {"arguments": '"Oslo"}'}}):
                            yield "data: " + json.dumps(
                                {"model": model, "choices": [{"index": 0, "delta": {"tool_calls": [fragment]},
                                                              "finish_reason": None}]}) + "\n\n"
                        yield "data: " + json.dumps(
                            {"model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}
                        ) + "\n\n"
                        yield "data: [DONE]\n\n"

                    return StreamingResponse(called(), media_type="text/event-stream")
                return {"model": model, "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [call]}}]}
            text = f"answer from {model} with {'+'.join(sorted(kinds)) or 'text'}"
            usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
            top = int(body.get("top_logprobs") or 0)
            cites = [CITATION, FILE_NOTE] if "web_search_options" in body else None
            if body.get("stream"):

                async def stream():
                    for piece in (text[:6], text[6:]):
                        choice = {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                        if body.get("logprobs"):
                            choice["logprobs"] = logprobs_for([piece], top)
                        yield "data: " + json.dumps({"model": model, "choices": [choice]}) + "\n\n"
                    if cites:
                        for cite in cites:
                            yield "data: " + json.dumps({"model": model, "choices": [
                                {"index": 0, "delta": {"annotations": [cite]}, "finish_reason": None}]}) + "\n\n"
                    yield "data: " + json.dumps(
                        {"model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}
                    ) + "\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(stream(), media_type="text/event-stream")
            message = {"role": "assistant", "content": text}
            if cites:
                message["annotations"] = cites
            choice = {"index": 0, "message": message, "finish_reason": "stop"}
            if body.get("logprobs"):
                choice["logprobs"] = logprobs_for(text.split(), top)
            return {"model": model, "choices": [choice], "usage": usage}

    elif kind in ("router", "openrouter", "llama"):
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

    names = ["control", "agent", "gateway", "fixture", "router", "llama"]
    if live:
        names.append("openrouter")
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
    live_key = _openrouter_key() if live else None

    fox = base64.b64encode(FOX.read_bytes()).decode("ascii")
    zebra = base64.b64encode(one_page_pdf("The secret word is zebra.")).decode("ascii")

    def ok(message: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {message}", flush=True)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, headers=None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={**(headers or {}), **({"Authorization": "Bearer " + token} if token else {})},
            **kwargs,
        )

    def write(name, filename, data):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data),
            encoding="utf-8",
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
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
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
        bodies = call("fixture", "GET", "/seen", params={"model": model}).json()
        assert bodies, f"nothing reached the upstream as {model}"
        return bodies[-1]

    def parts_of(body, kind):
        return [
            part
            for message in body.get("messages") or []
            if isinstance(message.get("content"), list)
            for part in message["content"]
            if part.get("type") == kind
        ]

    def audio_part(fmt="mp3", data=None):
        return {"type": "input_audio", "input_audio": {"data": fox if data is None else data, "format": fmt}}

    def chat(token, model, content, *, stream=False, **extra):
        return call("gateway", "POST", "/v1/chat/completions", token, json={
            "model": model, "stream": stream, "max_tokens": 64,
            "messages": [{"role": "user", "content": content}], **extra,
        })

    def streamed(response):
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
        text = "".join(
            (c.get("delta") or {}).get("content") or "" for f in frames for c in f.get("choices") or []
        )
        envelope = next((f["x_eugene_plexus"] for f in reversed(frames) if f.get("x_eugene_plexus")), {})
        return text, envelope

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

        def declare(name):
            call("agent", "POST", "/v1/components", operator, json={
                "name": name, "kind": "inference-driver", "url": url(name),
            }).raise_for_status()

        start("fixture")
        write("router", "bootstrap.json", bootstrap("inference-driver"))
        # The real OpenRouter provider, pointed at the fixture: the
        # driver's own listing reader decides what each model takes.
        write("router", "driver.yaml", {"provider": "openrouter", "baseUrl": url("fixture")})
        start("router", {"OPENAI_API_KEY": "fixture-not-a-key"})
        declare("router")
        write("llama", "bootstrap.json", bootstrap("inference-driver"))
        write("llama", "driver.yaml", {
            "provider": "openai_compat_custom", "baseUrl": url("fixture") + "/llama",
            "modelId": "local-llama", "backendLocality": "local",
        })
        start("llama")
        declare("llama")
        slots = [
            {"model": "assistant", "targets": ["router/acme/text-only", "router/acme/hears"]},
            {"model": "mixed", "targets": ["router/acme/hears", "router/acme/reads"]},
            {"model": "speaker", "targets": ["router/acme/text-only", "router/acme/speaks"]},
            {"model": "careful", "targets": ["router/acme/text-only", "router/acme/thinks"]},
        ]
        if live:
            write("openrouter", "bootstrap.json", bootstrap("inference-driver"))
            write("openrouter", "driver.yaml", {
                "provider": "openrouter",
                "catalogueInclude": [LIVE_HEARS, LIVE_TEXT, LIVE_SPEAKS, LIVE_SINGS, LIVE_THINKS, LIVE_SEARCHES, LIVE_CALLS],
            })
            start("openrouter", {"OPENAI_API_KEY": live_key})
            declare("openrouter")
            slots.append({
                "model": "live-assistant",
                "targets": [f"openrouter/{LIVE_TEXT}", f"openrouter/{LIVE_HEARS}"],
            })
            slots.append({
                "model": "live-speaker",
                "targets": [f"openrouter/{LIVE_TEXT}", f"openrouter/{LIVE_SPEAKS}"],
            })
            slots.append({
                "model": "live-careful",
                "targets": [f"openrouter/{LIVE_HEARS}", f"openrouter/{LIVE_TEXT}"],
            })
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2, "modelSlots": slots})
        start("gateway")

        response = call("agent", "POST", "/v1/auth/client-keys", operator, json={
            "name": "Everything", "limits": {"allowedModels": None, "requestsPerMinute": 1000},
        })
        response.raise_for_status()
        key = response.json()["token"]

        def models():
            return {
                m["id"]: m.get("x_eugene_plexus") or {}
                for m in call("gateway", "GET", "/v1/models", key).json().get("data", [])
            }

        wanted = {f"router/{m}" for m in LISTING} | {"assistant", "mixed", "speaker", "careful", "local-llama"}
        wait(lambda: wanted <= set(models()), "the fixture account's models are routable")

        # --- 1. what each model takes, from the listing -----------------------
        info = {m["id"]: m["capabilities"] for m in call("router", "GET", "/v1/info", operator).json()["models"]}
        takes = {m: (c.get("audioInput"), c.get("fileInput")) for m, c in info.items()}
        assert takes == {
            "acme/text-only": (False, False), "acme/hears": (True, False), "acme/reads": (False, True),
            "acme/speaks": (False, False), "acme/sings": (False, False), "acme/thinks": (False, False),
        }, takes
        listed = models()
        reported = {m: (listed[f"router/{m}"].get("audio_input"), listed[f"router/{m}"].get("file_input")) for m in LISTING}
        assert reported == takes, reported
        # A slot reports what ANY of its backends takes.
        assert listed["assistant"].get("audio_input") is True and listed["assistant"].get("file_input") is False, listed["assistant"]
        ok("the driver reads audio and file input per model from OpenRouter's listing, and GET /v1/models reports each")

        # --- 2. a slot's tier 2 answers the audio -------------------------------
        before = counts()
        plain = chat(key, "assistant", "hello")
        assert plain.status_code == 200, plain.text
        assert plain.json()["x_eugene_plexus"]["tier"] == 1, plain.json()["x_eugene_plexus"]
        assert counts().get("acme/text-only", 0) == before.get("acme/text-only", 0) + 1
        ok("a text request to the slot is answered by its first tier, so tier 1 is live and preferred")

        for stream in (False, True):
            before = counts()
            response = chat(key, "assistant", [
                {"type": "text", "text": "What does the speaker say?"}, audio_part(),
            ], stream=stream)
            assert response.status_code == 200, response.text
            if stream:
                text, envelope = streamed(response)
            else:
                text, envelope = response.json()["choices"][0]["message"]["content"], response.json()["x_eugene_plexus"]
            assert text == "answer from acme/hears with audio", text
            assert envelope.get("tier") == 2 and envelope.get("attempts") == 1, envelope
            after = counts()
            assert after.get("acme/text-only", 0) == before.get("acme/text-only", 0), (before, after)
            assert after.get("acme/hears", 0) == before.get("acme/hears", 0) + 1, (before, after)
            sent = parts_of(last_seen("acme/hears"), "input_audio")
            assert sent == [audio_part()], [p.get("input_audio", {}).get("format") for p in sent]
        ok("an audio request to assistant -> [text-only, hears] is answered by tier 2 in one attempt, streamed and not; "
           "the text model's upstream count does not move and the clip arrives byte for byte")

        # --- 3. nothing confirms it: a 400 naming the field, nothing sent ------
        before = counts()
        refused = chat(key, "router/acme/text-only", [{"type": "text", "text": "hi"}, audio_part()])
        assert refused.status_code == 400 and "x_eugene_plexus.audio_input" in refused.text, refused.text
        refused = chat(key, "router/acme/hears", [
            {"type": "text", "text": "hi"}, {"type": "file", "file": {"filename": "z.pdf", "file_data": zebra}},
        ])
        assert refused.status_code == 400 and "x_eugene_plexus.file_input" in refused.text, refused.text
        both = chat(key, "mixed", [
            {"type": "text", "text": "hi"}, audio_part(),
            {"type": "file", "file": {"filename": "z.pdf", "file_data": zebra}},
        ])
        assert both.status_code == 400 and "together" in both.text, both.text
        assert counts() == before, (before, counts())
        ok("with no backend confirming the attachment it is a 400 naming audio_input or file_input; "
           "audio and a PDF confirmed by different backends is refused as 'together'; nothing reaches the upstream")

        # --- 4. checked by bytes at the door -------------------------------------
        # `param` is the exact field only when the GATEWAY refused: the
        # driver checks the same bytes, and its 400 relayed through the
        # gateway carries no such param. So this is the gateway's own check,
        # not the driver's standing in for it.
        before = counts()
        for content, param, words in (
            ([{"type": "text", "text": "hi"}, audio_part(fmt="wav")],
             "messages[0].content[1].input_audio", "declared wav"),
            ([{"type": "text", "text": "hi"}, {"type": "file", "file": {"file_id": "file-abc123"}}],
             "messages[0].content[1].file.file_id", "no file store"),
            ([{"type": "text", "text": "hi"}, {"type": "file", "file": {"filename": "z.pdf", "file_data": fox}}],
             "messages[0].content[1].file.file_data", "not a PDF"),
        ):
            model = "router/acme/hears" if content[1]["type"] == "input_audio" else "router/acme/reads"
            refused = chat(key, model, content)
            assert refused.status_code == 400, refused.text
            error = refused.json()["error"]
            assert error.get("param") == param and words in error["message"], error
        assert counts() == before, (before, counts())
        ok("MP3 bytes declared wav, a file_id and an MP3 sent as a PDF are each refused by the gateway itself, naming the field")

        # --- 5. a bare-base64 PDF arrives as the data URL -----------------------
        for data in (zebra, PDF_PREFIX + zebra):
            response = chat(key, "router/acme/reads", [
                {"type": "text", "text": "What is the secret word?"},
                {"type": "file", "file": {"filename": "zebra.pdf", "file_data": data}},
            ])
            assert response.status_code == 200, response.text
            assert response.json()["choices"][0]["message"]["content"] == "answer from acme/reads with file"
            sent = parts_of(last_seen("acme/reads"), "file")
            assert sent == [{"type": "file", "file": {"filename": "zebra.pdf", "file_data": PDF_PREFIX + zebra}}], (
                [p["file"].get("file_data", "")[:40] for p in sent]
            )
        ok("a PDF sent as bare base64 arrives upstream as the data URL OpenRouter requires; a data URL arrives unchanged")

        # --- 6. the Anthropic door: document blocks ------------------------------
        document = {
            "type": "document", "title": "zebra.pdf",
            "source": {"type": "base64", "media_type": "application/pdf", "data": zebra},
        }
        response = call("gateway", "POST", "/v1/messages", key, headers={"anthropic-version": "2023-06-01"}, json={
            "model": "router/acme/reads", "max_tokens": 64,
            "messages": [{"role": "user", "content": [document, {"type": "text", "text": "The secret word?"}]}],
        })
        assert response.status_code == 200, response.text
        answer = "".join(b.get("text", "") for b in response.json()["content"])
        assert answer == "answer from acme/reads with file", answer
        sent = parts_of(last_seen("acme/reads"), "file")
        assert sent == [{"type": "file", "file": {"filename": "zebra.pdf", "file_data": PDF_PREFIX + zebra}}], sent

        # Claude Code's Read of a PDF: a tool_result holding a document.
        response = call("gateway", "POST", "/v1/messages", key, headers={"anthropic-version": "2023-06-01"}, json={
            "model": "router/acme/reads", "max_tokens": 64,
            "tools": [{"name": "Read", "description": "Read a file.",
                       "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}}}],
            "messages": [
                {"role": "user", "content": "Read zebra.pdf and tell me the secret word."},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "toolu_p2_0001", "name": "Read", "input": {"file_path": "zebra.pdf"}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_p2_0001", "content": [
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": zebra}},
                    ]},
                ]},
            ],
        })
        assert response.status_code == 200, response.text
        body = last_seen("acme/reads")
        tool = [m for m in body["messages"] if m.get("role") == "tool"]
        assert tool and "attached to the next user message" in json.dumps(tool), tool
        after_tool = body["messages"][body["messages"].index(tool[-1]) + 1:]
        moved = [p for m in after_tool if m.get("role") == "user" and isinstance(m.get("content"), list)
                 for p in m["content"] if p.get("type") == "file"]
        assert [p["file"]["file_data"] for p in moved] == [PDF_PREFIX + zebra], moved
        ok("Anthropic document blocks arrive upstream as file parts -- top-level with its title as the filename, "
           "and from a tool_result moved to the next user message with the tool message saying so")

        # --- 7. the Responses door: input_file and input_audio -------------------
        def respond(model, content):
            return call("gateway", "POST", "/v1/responses", key, json={
                "model": model, "stream": False, "store": False,
                "input": [{"type": "message", "role": "user", "content": content}],
            })

        def output_text(response):
            return "".join(
                part.get("text", "")
                for item in response.json().get("output") or []
                if item.get("type") == "message"
                for part in item.get("content") or []
            )

        response = respond("router/acme/reads", [
            {"type": "input_text", "text": "The secret word?"},
            {"type": "input_file", "filename": "zebra.pdf", "file_data": PDF_PREFIX + zebra},
        ])
        assert response.status_code == 200, response.text
        assert output_text(response) == "answer from acme/reads with file", response.text[:400]
        sent = parts_of(last_seen("acme/reads"), "file")
        assert sent == [{"type": "file", "file": {"filename": "zebra.pdf", "file_data": PDF_PREFIX + zebra}}], sent
        response = respond("assistant", [
            {"type": "input_text", "text": "What does the speaker say?"}, audio_part(),
        ])
        assert response.status_code == 200, response.text
        assert output_text(response) == "answer from acme/hears with audio", response.text[:400]
        assert parts_of(last_seen("acme/hears"), "input_audio") == [audio_part()]
        ok("the Responses door's input_file arrives as a file part and its input_audio as input_audio, "
           "the audio routed past the slot's text-only tier")

        # --- 8. the driver's own copy of the rules --------------------------------
        # Called directly, as anything but this gateway might: the driver
        # does not rely on its caller having routed or normalised.
        def generate(model, content):
            return call("router", "POST", "/v1/generate", operator, json={
                "model": model, "maxTokens": 64, "messages": [{"role": "user", "content": content}],
            })

        before = counts()
        refused = generate("acme/text-only", [{"type": "text", "text": "hi"}, audio_part()])
        assert refused.status_code == 400 and "Audio input not supported" in refused.text, refused.text
        refused = generate("acme/hears", [
            {"type": "text", "text": "hi"}, {"type": "file", "file": {"filename": "z.pdf", "file_data": zebra}},
        ])
        assert refused.status_code == 400 and "File input not supported" in refused.text, refused.text
        refused = generate("acme/hears", [{"type": "text", "text": "hi"}, audio_part(fmt="wav")])
        assert refused.status_code == 400 and "declared wav" in refused.text, refused.text
        assert counts() == before, (before, counts())
        response = generate("acme/reads", [
            {"type": "text", "text": "The secret word?"},
            {"type": "file", "file": {"filename": "zebra.pdf", "file_data": zebra}},
        ])
        assert response.status_code == 200, response.text
        sent = parts_of(last_seen("acme/reads"), "file")
        assert sent == [{"type": "file", "file": {"filename": "zebra.pdf", "file_data": PDF_PREFIX + zebra}}], sent
        ok("the driver called directly refuses audio or a PDF its model's listing does not confirm and MP3 bytes "
           "declared wav, sending nothing upstream, and sends a bare-base64 PDF on as the data URL")

        # --- P2b. audio out ------------------------------------------------------
        def speak(model, fmt="wav", *, stream=False, **extra):
            return call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": model, "stream": stream, "max_tokens": 64,
                "messages": [{"role": "user", "content": "Say hello."}],
                "modalities": ["text", "audio"], "audio": {"voice": "alloy", "format": fmt}, **extra,
            })

        def wav_parts(raw):
            """(sample rate, data) of a WAV, or fail."""
            assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE", raw[:12]
            rate = int.from_bytes(raw[24:28], "little")
            assert raw[36:40] == b"data", raw[36:40]
            return rate, raw[44:44 + int.from_bytes(raw[40:44], "little")]

        info = {m["id"]: m["capabilities"] for m in call("router", "GET", "/v1/info", operator).json()["models"]}
        speaks = {m for m, c in info.items() if c.get("audioOutput")}
        assert speaks == SPEAKERS, speaks
        listed = models()
        assert {m for m in LISTING if listed[f"router/{m}"].get("audio_output")} == SPEAKERS, listed
        assert listed["speaker"].get("audio_output") is True, listed["speaker"]
        ok("audio output is read per model from what the listing says it gives back, and GET /v1/models reports it")

        for fmt in ("wav", "pcm16"):
            before = counts()
            response = speak("speaker", fmt)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["x_eugene_plexus"]["tier"] == 2 and body["x_eugene_plexus"]["attempts"] == 1, body["x_eugene_plexus"]
            after = counts()
            assert after.get("acme/text-only", 0) == before.get("acme/text-only", 0), (before, after)
            assert after.get("acme/speaks", 0) == before.get("acme/speaks", 0) + 1, (before, after)
            upstream = last_seen("acme/speaks")
            assert upstream["stream"] is True and upstream["modalities"] == ["text", "audio"], upstream.get("modalities")
            assert upstream["audio"] == {"voice": "alloy", "format": "pcm16"}, upstream["audio"]
            message = body["choices"][0]["message"]
            audio = message["audio"]
            raw = base64.b64decode(audio["data"])
            assert audio["format"] == fmt and audio["transcript"] == "Hello there", {k: audio[k] for k in ("format", "transcript")}
            assert audio["id"] == "audio_fixture" and audio["expires_at"] == 1790609721
            assert message["content"] is None, message["content"]
            if fmt == "wav":
                assert wav_parts(raw) == (24000, PCM)
            else:
                assert raw == PCM
        ok("a spoken answer to speaker -> [text-only, speaks] comes from tier 2 in one attempt, the text model never "
           "asked; the backend is asked for a pcm16 stream and the answer is WAV (24 kHz header) or the samples")

        response = speak("speaker", "pcm16", stream=True)
        assert response.status_code == 200, response.text
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
        fragments = [c["delta"]["audio"] for f in frames for c in f.get("choices") or [] if "audio" in (c.get("delta") or {})]
        assert fragments[0] == {"id": "audio_fixture", "transcript": "Hello"}, fragments[0]
        assert fragments[1].get("format") == "pcm16", fragments[1]
        assert b"".join(base64.b64decode(f["data"]) for f in fragments if "data" in f) == PCM
        assert "".join(f.get("transcript", "") for f in fragments) == "Hello there"
        ok("streamed, each audio fragment arrives as delta.audio and they reassemble to the samples sent")

        response = speak("router/acme/sings", "wav")
        assert response.status_code == 200, response.text
        message = response.json()["choices"][0]["message"]
        assert message["audio"]["format"] == "mp3", message["audio"]["format"]
        assert base64.b64decode(message["audio"]["data"]) == SONG
        assert message["content"] == "[0.0:2.0] LA LA", message["content"]
        ok("a Lyria-shaped model asked for WAV answers MP3, and it is returned as sent and labelled mp3")

        before = counts()
        hello = [{"role": "user", "content": "Say hello."}]
        wav = {"voice": "alloy", "format": "wav"}
        for body, param, words in (
            ({"messages": hello, "modalities": ["text", "audio"], "audio": {"voice": "alloy", "format": "mp3"}},
             "audio.format", "wav or pcm16"),
            ({"messages": hello, "modalities": ["text", "audio"], "audio": wav, "stream": True},
             "audio.format", "pcm16"),
            ({"messages": hello, "modalities": ["text"], "audio": wav}, "audio", "modalities"),
            ({"messages": [*hello, {"role": "assistant", "audio": {"id": "audio_x"}},
                           {"role": "user", "content": "again"}]}, "messages[1].audio", "keeps none"),
        ):
            refused = call("gateway", "POST", "/v1/chat/completions", key, json={"model": "speaker", **body})
            assert refused.status_code == 400, refused.text
            error = refused.json()["error"]
            assert error.get("param") == param and words in error["message"], error
        refused = speak("router/acme/text-only")
        assert refused.status_code == 400 and "x_eugene_plexus.audio_output" in refused.text, refused.text
        direct = call("router", "POST", "/v1/generate", operator, json={
            "model": "acme/text-only", "messages": [{"role": "user", "content": "hi"}],
            "audioOutput": {"voice": "alloy", "format": "wav"},
        })
        assert direct.status_code == 400 and "Audio output not supported" in direct.text, direct.text
        direct = call("router", "POST", "/v1/generate", operator, json={
            "model": "acme/speaks", "messages": [{"role": "user", "content": "hi"}],
            "audioOutput": {"voice": "alloy", "format": "mp3"},
        })
        assert direct.status_code == 400 and "#audio-format-unsupported" in direct.text, direct.text
        assert counts() == before, (before, counts())
        ok("MP3 asked non-streamed, WAV asked streamed, audio without modalities and an assistant's audio {id} are "
           "refused by the gateway naming the field; a model that does not speak is a 400 naming audio_output; "
           "the driver refuses both on its own; nothing reaches the upstream")

        # --- P2c. the missing chat fields ---------------------------------------
        settings = {"logprobs": True, "top_logprobs": 1, "logit_bias": {"50256": -100},
                    "reasoning_effort": "low", "verbosity": "low",
                    "prediction": {"type": "content", "content": "answer"},
                    "web_search_options": {"search_context_size": "low"}}
        claimed = {m: set(c.get("supportedSettings") or [])
                   for m, c in ((m["id"], m["capabilities"]) for m in call("router", "GET", "/v1/info", operator).json()["models"])}
        mine = {"logprobs", "logitBias", "reasoningEffort", "verbosity", "prediction", "webSearchOptions"}
        assert mine <= claimed["acme/thinks"] and not mine & claimed["acme/text-only"], claimed
        local = call("llama", "GET", "/v1/info", operator).json()["models"][0]["capabilities"]
        assert not mine & set(local.get("supportedSettings") or []), local.get("supportedSettings")
        before = counts()
        for stream in (False, True):
            response = chat(key, "careful", "Name a colour.", stream=stream, **settings)
            assert response.status_code == 200, response.text
            if stream:
                frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
                choices = [c for f in frames for c in f.get("choices") or []]
                tokens = [t["token"] for c in choices if c.get("logprobs") for t in c["logprobs"]["content"]]
                cited = [a for c in choices for a in (c.get("delta") or {}).get("annotations") or []]
                envelope = next(f["x_eugene_plexus"] for f in reversed(frames) if f.get("x_eugene_plexus"))
            else:
                body = response.json()
                tokens = [t["token"] for t in body["choices"][0]["logprobs"]["content"]]
                cited = body["choices"][0]["message"].get("annotations") or []
                envelope = body["x_eugene_plexus"]
            assert envelope["tier"] == 2 and envelope["attempts"] == 1, envelope
            assert "".join(tokens).replace(" ", "") == "answerfromacme/thinkswithtext", tokens
            assert cited == [CITATION], cited
        after = counts()
        assert after.get("acme/text-only", 0) == before.get("acme/text-only", 0), (before, after)
        upstream = last_seen("acme/thinks")
        for key_name in ("logprobs", "top_logprobs", "logit_bias", "reasoning_effort", "verbosity",
                         "prediction", "web_search_options"):
            assert upstream.get(key_name) == settings[key_name], (key_name, upstream.get(key_name))
        assert upstream["provider"] == {"require_parameters": True}, upstream.get("provider")
        ok("every P2c setting routes past a tier that does not list it to one that does, in OpenAI's names; "
           "logprobs and citations come back streamed and not, OpenRouter's file note left out; the "
           "text model never asked; a local engine and an unlisting model are claimed for none of them")

        before = counts()
        for name, value in (("logit_bias", {"1": 5}), ("reasoning_effort", "high"),
                            ("web_search_options", {}), ("logprobs", True)):
            refused = chat(key, "router/acme/text-only", "hi", **{name: value})
            assert refused.status_code == 400, refused.text
            error = refused.json()["error"]
            assert error.get("param") == name and name in error["message"], error
        refused = chat(key, "router/acme/thinks", "hi", top_logprobs=2)
        assert refused.status_code == 400 and refused.json()["error"]["param"] == "top_logprobs", refused.text
        assert counts() == before, (before, counts())
        hints = {"prompt_cache_key": "k", "service_tier": "flex", "safety_identifier": "u",
                 "prompt_cache_retention": "24h"}
        response = chat(key, "router/acme/text-only", "hi", **hints)
        assert response.status_code == 200, response.text
        assert not set(hints) & set(last_seen("acme/text-only")), sorted(last_seen("acme/text-only"))
        ok("a setting no backend lists is refused naming it and nothing is sent; top_logprobs needs logprobs; "
           "hints never restrict routing and are dropped for a backend that does not take them")

        weather = {"name": "get_weather", "description": "Weather.",
                   "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}
        for stream in (False, True):
            response = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": "router/acme/thinks", "stream": stream, "max_tokens": 32,
                "messages": [{"role": "user", "content": "Weather in Oslo?"}],
                "functions": [weather], "function_call": {"name": "get_weather"},
            })
            assert response.status_code == 200, response.text
            upstream = last_seen("acme/thinks")
            assert upstream["tools"] == [{"type": "function", "function": weather}], upstream["tools"]
            assert upstream["tool_choice"] == {"type": "function", "function": {"name": "get_weather"}}
            # Not sent: it would route only to the 12 of 455 models listing it.
            assert "parallel_tool_calls" not in upstream, upstream.get("parallel_tool_calls")
            if stream:
                frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
                choices = [c for f in frames for c in f.get("choices") or []]
                fragments = [c["delta"]["function_call"] for c in choices if (c.get("delta") or {}).get("function_call")]
                assert fragments[0]["name"] == "get_weather", fragments
                assert "".join(f.get("arguments") or "" for f in fragments) == '{"city": "Oslo"}', fragments
                assert not any((c.get("delta") or {}).get("tool_calls") for c in choices)
                assert choices[-1]["finish_reason"] == "function_call", choices[-1]
            else:
                choice = response.json()["choices"][0]
                assert choice["finish_reason"] == "function_call", choice["finish_reason"]
                assert choice["message"]["function_call"] == {"name": "get_weather", "arguments": '{"city": "Oslo"}'}
                assert not choice["message"].get("tool_calls")
        response = call("gateway", "POST", "/v1/chat/completions", key, json={
            "model": "router/acme/thinks", "max_tokens": 32, "functions": [weather],
            "messages": [
                {"role": "user", "content": "Weather in Oslo?"},
                {"role": "assistant", "content": None,
                 "function_call": {"name": "get_weather", "arguments": '{"city": "Oslo"}'}},
                {"role": "function", "name": "get_weather", "content": '{"temp": -3}'},
            ],
        })
        assert response.status_code == 200, response.text
        history = last_seen("acme/thinks")["messages"]
        assert history[1]["tool_calls"][0]["id"] == history[2]["tool_call_id"], history
        assert history[2]["role"] == "tool" and history[2]["content"] == '{"temp": -3}', history[2]
        ok("the deprecated functions reach the backend as tools with the call forced and parallel_tool_calls unsent, "
           "and come back as message.function_call and function_call fragments; a function history is "
           "carried as a tool call and its result")

        counted = call("gateway", "POST", "/v1/responses/input_tokens", key, json={
            "model": "local-llama", "input": "one two three four"})
        assert counted.status_code == 200, counted.text
        assert counted.json() == {"object": "response.input_tokens", "input_tokens": 4}, counted.json()
        cannot = call("gateway", "POST", "/v1/responses/input_tokens", key, json={
            "model": "router/acme/thinks", "input": "one two"})
        assert cannot.status_code == 400 and "without generating" in cannot.json()["error"]["message"], cannot.text
        ok("/v1/responses/input_tokens is counted by the llama.cpp-like backend's own template and tokenizer, "
           "and an OpenRouter model, which cannot count without generating, is a 400 saying so")

        # --- 9. live OpenRouter ---------------------------------------------------
        if live:
            hears, text_only = f"openrouter/{LIVE_HEARS}", f"openrouter/{LIVE_TEXT}"
            wait(lambda: {hears, text_only, "live-assistant"} <= set(models()), "OpenRouter's two models", 60)
            listed = models()
            assert listed[hears].get("audio_input") is True and listed[hears].get("file_input") is True, listed[hears]
            assert listed[text_only].get("audio_input") is False and listed[text_only].get("file_input") is False, listed[text_only]
            ok(f"a real OpenRouter listing: {LIVE_HEARS} takes audio and files, {LIVE_TEXT} neither")

            def words(response):
                assert response.status_code == 200, response.text[:400]
                answer = response.json()["choices"][0]["message"]["content"] or ""
                return "".join(c for c in answer.lower() if c.isalpha() or c.isspace()).split(), answer

            heard, answer = words(chat(key, hears, [
                {"type": "text", "text": "Transcribe this recording exactly. Reply with the transcript only."},
                audio_part(),
            ]))
            assert "quick" in heard and "fox" in heard and "lazy" in heard and "dog" in heard, answer
            print(f"INFO fox: {answer.strip()!r}", flush=True)
            read, answer = words(chat(key, hears, [
                {"type": "text", "text": "What is the secret word in this document? Reply with the word only."},
                {"type": "file", "file": {"filename": "secret.pdf", "file_data": zebra}},
            ]))
            assert "zebra" in read, answer
            print(f"INFO zebra (chat, bare base64): {answer.strip()!r}", flush=True)
            ok(f"through chat, {LIVE_HEARS} transcribes the fox mp3 and reads 'zebra' from a bare-base64 PDF")

            response = call("gateway", "POST", "/v1/messages", key, headers={"anthropic-version": "2023-06-01"}, json={
                "model": hears, "max_tokens": 32,
                "messages": [{"role": "user", "content": [
                    {"type": "document", "title": "secret.pdf",
                     "source": {"type": "base64", "media_type": "application/pdf", "data": zebra}},
                    {"type": "text", "text": "What is the secret word in this document? Reply with the word only."},
                ]}],
            })
            assert response.status_code == 200, response.text[:400]
            answer = "".join(b.get("text", "") for b in response.json()["content"])
            assert "zebra" in answer.lower(), answer
            print(f"INFO zebra (Anthropic document): {answer.strip()!r}", flush=True)
            ok("through the Anthropic door, a document block reaches OpenRouter as a file and is read")

            plain = chat(key, "live-assistant", "Reply with exactly: pong")
            assert plain.status_code == 200, plain.text[:400]
            assert plain.json()["x_eugene_plexus"]["tier"] == 1, plain.json()["x_eugene_plexus"]
            response = chat(key, "live-assistant", [
                {"type": "text", "text": "Transcribe this recording exactly. Reply with the transcript only."},
                audio_part(),
            ])
            heard, answer = words(response)
            envelope = response.json()["x_eugene_plexus"]
            assert envelope.get("tier") == 2 and envelope.get("attempts") == 1, envelope
            assert "fox" in heard, answer
            ok(f"the slot live-assistant -> [{LIVE_TEXT}, {LIVE_HEARS}] answers text from tier 1 and the fox from "
               "tier 2 in one attempt: the model OpenRouter refuses audio for is never sent it")

            speaks_live, sings_live = f"openrouter/{LIVE_SPEAKS}", f"openrouter/{LIVE_SINGS}"
            wait(lambda: {speaks_live, sings_live, "live-speaker"} <= set(models()), "OpenRouter's audio models", 60)
            listed = models()
            assert listed[speaks_live].get("audio_output") is True and listed[sings_live].get("audio_output") is True
            assert listed[text_only].get("audio_output") is False, listed[text_only]

            response = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": speaks_live, "max_tokens": 80,
                "messages": [
                    {"role": "system", "content": "Repeat the user's sentence aloud, word for word, and nothing else."},
                    {"role": "user", "content": "The zebra is blue and the kettle is singing."},
                ],
                "modalities": ["text", "audio"], "audio": {"voice": "alloy", "format": "wav"},
            })
            assert response.status_code == 200, response.text[:400]
            audio = response.json()["choices"][0]["message"]["audio"]
            raw = base64.b64decode(audio["data"])
            rate, samples = wav_parts(raw)
            assert audio["format"] == "wav" and rate == 24000 and len(samples) > 24000, (audio["format"], rate, len(samples))
            said = {w for w in "".join(c for c in (audio.get("transcript") or "").lower() if c.isalpha() or c.isspace()).split() if len(w) >= 4}
            assert said, audio.get("transcript")
            print(f"INFO speech: {len(samples) / 48000:.2f} s, transcript {audio.get('transcript')!r}", flush=True)
            # The round trip: the WAV this gateway built, heard by another
            # model. Whatever gpt-audio chose to say, a WAV with a wrong
            # header plays at the wrong speed or not at all, and is not
            # heard back as the same words.
            heard, answer = words(chat(key, hears, [
                {"type": "text", "text": "Transcribe this recording exactly. Reply with the transcript only."},
                {"type": "input_audio", "input_audio": {"data": audio["data"], "format": "wav"}},
            ]))
            shared = said & set(heard)
            assert len(shared) * 2 >= len(said), (sorted(said), answer)
            print(f"INFO speech heard back by {LIVE_HEARS}: {answer.strip()!r} ({len(shared)} of {len(said)} words)", flush=True)
            ok(f"through chat, {LIVE_SPEAKS} answers as a WAV this gateway assembled from its pcm16 stream, and "
               f"{LIVE_HEARS} transcribes that WAV back, so the header is right")

            response = speak("live-speaker", "pcm16")
            assert response.status_code == 200, response.text[:400]
            envelope = response.json()["x_eugene_plexus"]
            assert envelope.get("tier") == 2 and envelope.get("attempts") == 1, envelope
            ok(f"the slot live-speaker -> [{LIVE_TEXT}, {LIVE_SPEAKS}] answers a spoken request from tier 2 in one attempt")

            response = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": sings_live,
                "messages": [{"role": "user", "content": "A five second cheerful ukulele jingle."}],
                "modalities": ["text", "audio"], "audio": {"voice": "alloy", "format": "wav"},
            }, timeout=120)
            assert response.status_code == 200, response.text[:400]
            audio = response.json()["choices"][0]["message"]["audio"]
            raw = base64.b64decode(audio["data"])
            assert audio["format"] == "mp3" and raw[:3] == b"ID3" and len(raw) > 100_000, (audio["format"], raw[:4], len(raw))
            print(f"INFO music: {len(raw)} bytes of MP3 asked for as WAV", flush=True)
            ok(f"through chat, {LIVE_SINGS} returns music: asked for WAV, it sent MP3, labelled mp3")

            thinks, searches = f"openrouter/{LIVE_THINKS}", f"openrouter/{LIVE_SEARCHES}"
            wait(lambda: {thinks, searches, f"openrouter/{LIVE_CALLS}", "live-careful"} <= set(models()),
                 "OpenRouter's P2c models", 60)
            response = chat(key, "live-careful", "Name one primary colour. One word.", logprobs=True, top_logprobs=2)
            assert response.status_code == 200, response.text[:400]
            body = response.json()
            assert body["x_eugene_plexus"]["tier"] == 2 and body["x_eugene_plexus"]["attempts"] == 1, body["x_eugene_plexus"]
            entries = (body["choices"][0].get("logprobs") or {}).get("content") or []
            assert entries and all("logprob" in e and len(e.get("top_logprobs") or []) == 2 for e in entries), entries[:2]
            print(f"INFO logprobs: {[(e['token'], round(e['logprob'], 3)) for e in entries]}", flush=True)
            ok(f"the slot live-careful -> [{LIVE_HEARS}, {LIVE_TEXT}] answers logprobs from tier 2, "
               "the model that does not list them never asked, with two alternatives per token")

            spent = {}
            for effort in ("low", "high"):
                response = chat(key, thinks, "Name one primary colour. One word.", max_tokens=600,
                                reasoning_effort=effort)
                assert response.status_code == 200, response.text[:400]
                usage = response.json().get("usage") or {}
                spent[effort] = ((usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                                 or len(response.json()["choices"][0]["message"].get("reasoning_content") or ""))
            assert spent["high"] > spent["low"], spent
            print(f"INFO reasoning_effort: {spent}", flush=True)
            response = chat(key, searches, "What is the capital of Australia? One sentence.",
                            web_search_options={"search_context_size": "low"})
            assert response.status_code == 200, response.text[:400]
            cited = response.json()["choices"][0]["message"].get("annotations") or []
            assert cited and all(a["type"] == "url_citation" and a["url_citation"]["url"].startswith("http")
                                 for a in cited), cited
            print(f"INFO web search: {len(cited)} citations, first {cited[0]['url_citation']['url']}", flush=True)
            response = call("gateway", "POST", "/v1/chat/completions", key, json={
                "model": f"openrouter/{LIVE_CALLS}", "max_tokens": 64,
                "messages": [{"role": "user", "content": "What is the weather in Oslo?"}],
                "functions": [{"name": "get_weather", "description": "The current weather in a city.",
                               "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                              "required": ["city"]}}],
                "function_call": {"name": "get_weather"},
            })
            assert response.status_code == 200, response.text[:400]
            choice = response.json()["choices"][0]
            assert choice["finish_reason"] == "function_call" and choice["message"]["function_call"]["name"] == "get_weather", choice
            print(f"INFO function_call: {choice['message']['function_call']}", flush=True)
            ok(f"live: {LIVE_THINKS} thinks more at reasoning_effort high than low, {LIVE_SEARCHES} cites the web, "
               f"and {LIVE_CALLS} answers the deprecated functions as a function_call")

            # The key reached its driver in the environment only.
            leaked = [
                str(p) for p in directory.rglob("*")
                if p.is_file() and live_key.encode() in p.read_bytes()
            ]
            assert not leaked, f"the OpenRouter key was written to {len(leaked)} file(s) of the run's state"
            ok(f"the OpenRouter key is in none of the {sum(1 for p in directory.rglob('*') if p.is_file())} files of the run's state and logs")

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
    parser.add_argument("--openrouter-live", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
    else:
        directory = Path(tempfile.mkdtemp(prefix="ep-p2-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.openrouter_live)
