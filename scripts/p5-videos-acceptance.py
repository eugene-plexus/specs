"""P5: videos at `/v1/videos`, as signed jobs, through real signed processes.

A control root, an enrolled agent, a gateway and two inference-drivers, all
started here with isolated state and ports:

* `router` -- the real `openrouter` provider against a fixture playing
  OpenRouter's video API as measured on 2026-09-28
  (`provider-accounts-measurement.md` section 10): `GET /videos/models` with
  each model's durations, sizes and first-frame support; `POST /videos`
  taking `duration` as an integer, a listed `size` (another is its 400) and
  `frame_images`, answering 202 `pending`; `GET /videos/{id}` moving to
  `completed` with `unsigned_urls` and `usage.cost` (or `failed` with a string
  `error`); `/content` streaming the MP4 chunked, ignoring `variant`; an
  unknown job 404; no list, delete or remix route.
* `oai` -- the real `openai` provider against a fixture of OpenAI's model
  list, where both Sora models carry the 2026-09-24 `shutdown_date`.

**The OpenAI SDK makes the requests the done-when names**, unchanged
(`client.videos.create`, which always sends multipart, `create_and_poll`,
`retrieve`, `download_content`), from its own interpreter: this one if it has
`openai`, else `$EP_SDK_PYTHON`. **The gateway is restarted between a submit
and its poll**, and the poll and download work.

No live service is touched unless `--live` is passed, which adds OpenRouter
with the key in `C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or
`$EP_KEYS`): `x-ai/grok-imagine-video` makes one second at 480p from text and
one from a first frame, with a gateway restart in the middle. About eleven
cents.

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

NODE_NAME = "p5-agent"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))

MP4 = b"\x00\x00\x00 ftypisom" + bytes(range(256)) * 64
#: OpenRouter's account listing, trimmed; the video settings are only on
#: `/videos/models` (measured).
OR_LISTING = {
    "acme/grok": {"input": ["text", "image"], "output": ["video"]},
    "acme/wide": {"input": ["text"], "output": ["video"]},
    "acme/chat": {"input": ["text"], "output": ["text"]},
}
OR_VIDEOS = {
    "acme/grok": {"supported_durations": [1, 2, 3, 4, 5], "supported_sizes": ["854x480", "1280x720"],
                  "supported_frame_images": ["first_frame"]},
    "acme/wide": {"supported_durations": list(range(1, 16)), "supported_sizes": None,
                  "supported_frame_images": None},
}
#: The fixture's job takes this long to complete, and streams its MP4 in two
#: halves this far apart, so a relayed download is told from a buffered one.
MAKING = 1.0
GAP = 0.6
LIVE_MODEL = "x-ai/grok-imagine-video"

#: What the SDK does, in its own interpreter.
SDK_SNIPPET = """
import json, sys, time, warnings
warnings.simplefilter("ignore")
import openai
args = json.loads(sys.argv[1])
client = openai.OpenAI(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=300)
out = []
for job in args["jobs"]:
    kind = job.pop("kind")
    started = time.perf_counter()
    try:
        if kind in ("create", "create_and_poll"):
            path = job.pop("input_reference", None)
            handle = open(path, "rb") if path else None
            if handle:
                job["input_reference"] = handle
            try:
                if kind == "create_and_poll":
                    video = client.videos.create_and_poll(poll_interval_ms=job.pop("poll_ms", 500), **job)
                else:
                    video = client.videos.create(**job)
            finally:
                if handle:
                    handle.close()
            out.append({"status": 200, "video": video.model_dump(), "took": round(time.perf_counter() - started, 2)})
        elif kind == "retrieve":
            out.append({"status": 200, "video": client.videos.retrieve(job["id"]).model_dump()})
        elif kind == "download":
            arrivals, data = [], b""
            with client.videos.with_streaming_response.download_content(job["id"], **job.get("extra", {})) as r:
                for chunk in r.iter_bytes():
                    arrivals.append(round(time.perf_counter() - started, 3))
                    data += chunk
            if job.get("save"):
                open(job["save"], "wb").write(data)
            out.append({"status": 200, "length": len(data), "head": data[:12].hex(), "arrivals": arrivals,
                        "type": r.headers.get("content-type")})
        elif kind == "remix":
            out.append({"status": 200, "video": client.videos.remix(job["id"], prompt="x").model_dump()})
        elif kind == "list":
            out.append({"status": 200, "page": [v.id for v in client.videos.list()]})
    except openai.APIStatusError as e:
        out.append({"status": e.status_code, "error": e.message})
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


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A plain PNG, at least 8 pixels a side (OpenRouter refuses a 1x1 first
    frame, measured)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        counts: dict[str, int] = {}
        seen: dict[str, list[dict]] = {}
        jobs: dict[str, dict] = {}
        modes: dict[str, str] = {}
        content_asks: list[dict] = []

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return {"submits": counts, "content": content_asks}

        @app.get("/seen")
        async def seen_requests(model: str):
            return seen.get(model, [])

        @app.post("/mode")
        async def set_mode(model: str, mode: str):
            modes[model] = mode
            return {}

        @app.get("/v1/models/user")
        async def or_listing():
            return {"data": [
                {"id": model_id, "name": model_id, "context_length": 4096,
                 "architecture": {"input_modalities": e["input"], "output_modalities": e["output"]},
                 "supported_parameters": [] if "text" not in e["output"] else ["max_tokens"]}
                for model_id, e in OR_LISTING.items()
            ]}

        @app.get("/v1/images/models")
        async def or_images():
            return {"data": []}

        @app.get("/v1/videos/models")
        async def or_videos():
            return {"data": [{"id": model_id, **entry} for model_id, entry in OR_VIDEOS.items()]}

        @app.post("/v1/videos")
        async def or_submit(request: Request):
            body = await request.json()
            model = body.get("model")
            frames = body.get("frame_images") or []
            counts[model] = counts.get(model, 0) + 1
            seen.setdefault(model, []).append({
                "body": {k: v for k, v in body.items() if k != "frame_images"},
                "frames": [{"type": f.get("type"), "frame_type": f.get("frame_type"),
                            "url_head": ((f.get("image_url") or {}).get("url") or "")[:30]} for f in frames]})
            listed = OR_VIDEOS.get(model)
            if listed is None:
                return JSONResponse({"error": {"message": f"No endpoints found for {model}.", "code": 404}},
                                    status_code=404)
            if modes.get(model) == "busy":
                return JSONResponse({"error": {"message": "Rate limit exceeded", "code": 429}},
                                    status_code=429, headers={"Retry-After": "1"})
            size = body.get("size")
            if size is not None and listed["supported_sizes"] is not None and size not in listed["supported_sizes"]:
                return JSONResponse({"error": {"message": f'Unsupported size "{size}".', "code": 400}},
                                    status_code=400)
            if not isinstance(body.get("duration", 1), int):
                return JSONResponse({"success": False, "error": {"name": "ZodError",
                                     "message": "duration: expected number"}}, status_code=400)
            job_id = f"gen-vid-{model.split('/')[-1]}-{len(jobs)}"
            jobs[job_id] = {"at": time.perf_counter(), "fail": "[fail]" in body.get("prompt", ""),
                            "model": model}
            return JSONResponse({"id": job_id, "polling_url": f"/v1/videos/{job_id}", "status": "pending"},
                                status_code=202)

        @app.get("/v1/videos/{job_id}")
        async def or_poll(job_id: str):
            job = jobs.get(job_id)
            if job is None:
                return JSONResponse({"error": {"message": f"Job {job_id} not found", "code": 404}},
                                    status_code=404)
            if time.perf_counter() - job["at"] < MAKING:
                return {"id": job_id, "generation_id": job_id, "status": "pending"}
            if job["fail"]:
                return {"id": job_id, "status": "failed",
                        "error": "Image dimensions 1x1 are too small. [WKE=invalid_image]"}
            return {"id": job_id, "generation_id": job_id, "status": "completed",
                    "unsigned_urls": [f"/v1/videos/{job_id}/content?index=0"],
                    "usage": {"cost": 0.05, "is_byok": False}}

        @app.get("/v1/videos/{job_id}/content")
        async def or_content(job_id: str, request: Request):
            content_asks.append({"job": job_id, "query": dict(request.query_params)})
            if job_id not in jobs:
                return JSONResponse({"error": {"message": f"Job {job_id} not found", "code": 404}},
                                    status_code=404)

            async def halves():
                yield MP4[: len(MP4) // 2]
                await asyncio.sleep(GAP)
                yield MP4[len(MP4) // 2 :]

            # `variant` is ignored: the MP4 whatever is asked (measured).
            return StreamingResponse(halves(), media_type="video/mp4")

        @app.get("/oai/v1/models")
        async def oai_models():
            return {"object": "list", "data": [
                {"id": "sora-2", "object": "model", "owned_by": "system", "shutdown_date": "2026-09-24"},
                {"id": "sora-2-pro", "object": "model", "owned_by": "system", "shutdown_date": "2026-09-24"},
                {"id": "gpt-4o", "object": "model", "owned_by": "system", "shutdown_date": None},
            ]}

    elif kind in ("router", "oai", "openrouter"):
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
        names += ["openrouter"]
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
    files = directory / "files"
    files.mkdir()
    frame_file = files / "frame.png"
    frame_file.write_bytes(solid_png(64, 64, (40, 90, 200)))
    url_file = files / "not-an-image.png"
    url_file.write_bytes(b"%PDF-1.7 not an image")

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

    def fixture_stats():
        return call("fixture", "GET", "/stats").json()

    def seen(model):
        return call("fixture", "GET", "/seen", params={"model": model}).json()

    def by_sdk(token, jobs):
        result = subprocess.run(
            [sdk, "-c", SDK_SNIPPET, json.dumps({"base": url("gateway") + "/v1", "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=600,
            env={k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")},
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    def error_of(response):
        return response.json().get("error") or {}

    def form(**fields):
        """Multipart, as the SDK sends every create (captured): httpx's
        `data=` alone would send a urlencoded form, which OpenAI takes no
        more than this door does."""
        return {"files": {k: (None, str(v)) for k, v in fields.items()}}

    try:
        # --- a signed one-node install -----------------------------------
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        root_session = login("control")
        write("agent", "agent.yaml", {
            "firstRunComplete": True, "updateChecks": False,
            "advertiseUrl": url("agent"),
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
            driver("openrouter", {"provider": "openrouter", "catalogueInclude": [LIVE_MODEL]},
                   {"OPENAI_API_KEY": live_key})
        slots = [{"model": "clips", "targets": ["router/acme/grok", "router/acme/wide"]}]
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
        other_key = mint("Someone else")

        def models(token=key):
            return {
                m["id"]: m.get("x_eugene_plexus") or {}
                for m in call("gateway", "GET", "/v1/models", token).json().get("data", [])
            }

        wanted = {"router/acme/grok", "router/acme/wide", "router/acme/chat", "clips", "oai/gpt-4o"}
        wait(lambda: wanted <= set(models()), "the fixture accounts' models are routable")

        def recorded(request_id):
            found = []

            def written():
                rows = call("gateway", "GET", "/v1/metrics/requests", operator, params={"limit": 30}).json()
                found[:] = [r for r in rows["requests"] if r.get("requestId") == request_id]
                return bool(found)
            wait(written, f"the metrics row for request {request_id}", 10)
            return found[0]

        # --- 1. listed -----------------------------------------------------------
        listed = models()
        grok = listed["router/acme/grok"]
        assert grok["surfaces"] == ["video"] and grok["video_durations"] == [1, 2, 3, 4, 5], grok
        assert grok["video_sizes"] == ["1280x720", "854x480"] and grok["video_first_frame"] is True, grok
        assert listed["router/acme/wide"]["video_first_frame"] is False, listed["router/acme/wide"]
        assert not [m for m in listed if m.startswith("oai/sora")], sorted(listed)
        ok("the video listing decides what each model takes (grok: 1-5 s, two sizes, a first frame); an OpenAI "
           "account lists neither Sora model, both past their 2026-09-24 shutdown_date")

        # --- 2. the done-when: submitted, polled, downloaded through one gateway -
        results = by_sdk(key, [
            {"kind": "create_and_poll", "model": "router/acme/grok", "prompt": "a red ball bouncing",
             "seconds": "4", "size": "1280x720", "poll_ms": 200},
        ])
        made, sdk_info = results[0], results[-1]
        assert made["status"] == 200, made
        video = made["video"]
        assert video["id"].startswith("video_") and video["status"] == "completed", video
        assert (video["progress"], video["seconds"], video["size"]) == (100, "4", "1280x720"), video
        submitted = seen("acme/grok")[-1]["body"]
        assert submitted == {"model": "acme/grok", "prompt": "a red ball bouncing", "duration": 4,
                             "size": "1280x720"}, submitted
        [got] = by_sdk(key, [{"kind": "download", "id": video["id"], "save": str(files / "grok.mp4")}])[:1]
        assert got["status"] == 200 and got["type"] == "video/mp4" and got["length"] == len(MP4), got
        assert (files / "grok.mp4").read_bytes() == MP4
        first, last = got["arrivals"][0], got["arrivals"][-1]
        assert last - first >= GAP * 0.8, got["arrivals"]
        ok(f"the SDK's create_and_poll (openai {sdk_info['sdk']}) submits through the gateway, which asks "
           f"OpenRouter in its own shape (duration 4 as a number), polls to completed, and download_content "
           f"streams the MP4 back relayed, not buffered (first half at {first:.2f} s, last at {last:.2f} s)")

        # --- 3. a restart loses nothing ------------------------------------------
        [queued] = by_sdk(key, [{"kind": "create", "model": "router/acme/grok", "prompt": "a blue cube",
                                 "seconds": "1"}])[:1]
        assert queued["status"] == 200 and queued["video"]["status"] == "queued", queued
        handle = queued["video"]["id"]
        stop("gateway")
        start("gateway")
        wait(lambda: "router/acme/grok" in models(), "the restarted gateway's routes")
        time.sleep(MAKING)
        after = by_sdk(key, [{"kind": "retrieve", "id": handle}, {"kind": "download", "id": handle}])
        assert after[0]["status"] == 200 and after[0]["video"]["status"] == "completed", after[0]
        assert after[1]["status"] == 200 and after[1]["length"] == len(MP4), after[1]
        assert (directory / "gateway" / "video-handles.key").exists()
        ok("a job submitted before a gateway restart is polled to completed and downloaded after it: the "
           "handle carries the job, and the gateway's own secret, kept beside its config, still verifies it")

        # --- 4. another key's poll is refused ---------------------------------
        theirs = by_sdk(other_key, [{"kind": "retrieve", "id": handle}, {"kind": "download", "id": handle}])
        assert [r["status"] for r in theirs[:2]] == [404, 404], theirs
        forged = call("gateway", "GET", f"/v1/videos/{handle[:-3]}AAA", key)
        assert forged.status_code == 404, forged.text
        mine = call("gateway", "GET", f"/v1/videos/{handle}", key)
        assert mine.status_code == 200, mine.text
        ok("another key's retrieve and download of the same handle are 404s, and so is a tampered handle; "
           "the key that made the job still reads it")

        # --- 5. settings route by the model's listing --------------------------
        before = fixture_stats()["submits"]
        refused = {}
        for field, value, model in (("seconds", "12", "router/acme/grok"), ("size", "720x1280", "router/acme/grok")):
            response = call("gateway", "POST", "/v1/videos", key,
                            **form(model=model, prompt="x", **{field: value}))
            assert response.status_code == 400 and error_of(response)["param"] == field, response.text
            refused[field] = error_of(response)["message"]
        results = by_sdk(key, [
            {"kind": "create", "model": "router/acme/wide", "prompt": "x", "input_reference": str(frame_file)},
            {"kind": "create", "model": "router/acme/grok", "prompt": "x", "input_reference": str(url_file)},
        ])
        assert results[0]["status"] == 400 and "first frame" in results[0]["error"], results[0]
        assert results[1]["status"] == 400 and "PNG, JPEG" in results[1]["error"], results[1]
        by_url = call("gateway", "POST", "/v1/videos", key, json={
            "model": "router/acme/grok", "prompt": "x", "input_reference": {"image_url": "https://example.com/a.png"}})
        assert by_url.status_code == 400 and error_of(by_url)["param"] == "input_reference.image_url", by_url.text
        assert fixture_stats()["submits"] == before, (before, fixture_stats()["submits"])
        assert "1, 2, 3, 4, 5" in refused["seconds"] and "854x480" in refused["size"], refused
        ok("12 s and 720x1280 to grok are 400s naming seconds and size with what it makes; a first frame to a "
           "model that takes none, a PDF named .png, and a URL reference are refused; nothing reached OpenRouter")

        before = fixture_stats()["submits"]
        results = by_sdk(key, [
            {"kind": "create", "model": "clips", "prompt": "a long pan", "seconds": "10"},
            {"kind": "create", "model": "router/acme/grok", "prompt": "the square turns", "seconds": "1",
             "input_reference": str(frame_file)},
        ])
        assert all(r["status"] == 200 for r in results[:2]), results
        after = fixture_stats()["submits"]
        assert after.get("acme/grok", 0) == before.get("acme/grok", 0) + 1, (before, after)
        assert after.get("acme/wide", 0) == before.get("acme/wide", 0) + 1, (before, after)
        frame = seen("acme/grok")[-1]["frames"]
        assert frame == [{"type": "image_url", "frame_type": "first_frame",
                          "url_head": "data:image/png;base64,iVBORw0K"}], frame
        ok("clips -> [grok, wide] with 10 s never asks grok (1-5 s) and is taken by wide; an SDK file upload "
           "reaches OpenRouter as frame_images with frame_type first_frame")

        # --- 6. failover at submit only ------------------------------------------
        call("fixture", "POST", "/mode", params={"model": "acme/grok", "mode": "busy"}).raise_for_status()
        response = call("gateway", "POST", "/v1/videos", key, **form(model="clips", prompt="a dog", seconds=2))
        assert response.status_code == 200, response.text
        job = response.json()
        assert job["x_eugene_plexus"]["tier"] == 2 and job["x_eugene_plexus"]["attempts"] == 2, job
        call("fixture", "POST", "/mode", params={"model": "acme/grok", "mode": "ok"}).raise_for_status()
        time.sleep(MAKING)
        polled = call("gateway", "GET", f"/v1/videos/{job['id']}", key).json()
        assert polled["status"] == "completed" and polled["model"] == "router/acme/wide", polled
        row = recorded(response.headers["x-request-id"])
        assert (row["door"], row["videoSeconds"], row["servedModel"], row["tier"]) == (
            "videos", 2, "router/acme/wide", 2), row
        assert [t["served"] for t in row["tries"]] == [False, True], row
        ok("with grok rate-limited at submit, clips is accepted by wide at tier 2; the job is wide's for life "
           "(grok recovering changes nothing), and the row counts 2 seconds of video")

        # --- 7. what the door refuses ---------------------------------------------
        [failed] = by_sdk(key, [{"kind": "create_and_poll", "model": "router/acme/grok",
                                 "prompt": "a dot [fail]", "poll_ms": 200}])[:1]
        assert failed["video"]["status"] == "failed", failed
        assert failed["video"]["error"]["code"] == "video_generation_failed", failed
        assert "too small" in failed["video"]["error"]["message"], failed
        asked_before = len(fixture_stats()["content"])
        results = by_sdk(key, [
            {"kind": "download", "id": video["id"], "extra": {"variant": "thumbnail"}},
            {"kind": "list"},
            {"kind": "remix", "id": video["id"]},
        ])
        assert results[0]["status"] == 400 and "only video" in results[0]["error"], results[0]
        assert results[1]["status"] == 400 and "no store" in results[1]["error"], results[1]
        assert results[2]["status"] == 404, results[2]
        assert len(fixture_stats()["content"]) == asked_before
        local = mint("Local only", localOnly=True)
        refused_local = call("gateway", "POST", "/v1/videos", local,
                             **form(model="router/acme/grok", prompt="x"))
        assert refused_local.status_code == 403, refused_local.text
        ok("a failed job reads failed with the provider's reason as {code, message}; a thumbnail is refused "
           "rather than answered with the MP4, the list says there is no store, remix is not routed (P5-2), "
           "and a local-only key is refused a hosted video model")

        # --- 8. the live half ----------------------------------------------------
        if live:
            model = f"openrouter/{LIVE_MODEL}"
            wait(lambda: model in models(), "OpenRouter's live video model", 60)
            listed_live = models()[model]
            assert 1 in (listed_live.get("video_durations") or []) and listed_live.get("video_first_frame"), listed_live
            live_frame = files / "live-frame.png"
            live_frame.write_bytes(solid_png(640, 480, (230, 120, 30)))
            submitted_live = by_sdk(key, [
                {"kind": "create", "model": model, "prompt": "a red ball bouncing on a wooden floor",
                 "seconds": "1", "size": "854x480"},
                {"kind": "create", "model": model, "prompt": "the orange square slowly zooms out",
                 "seconds": "1", "size": "854x480", "input_reference": str(live_frame)},
            ])
            assert all(r["status"] == 200 for r in submitted_live[:2]), submitted_live
            handles = [r["video"]["id"] for r in submitted_live[:2]]
            stop("gateway")
            start("gateway")
            wait(lambda: model in models(), "the restarted gateway's live route", 60)
            deadline = time.perf_counter() + 300
            states: list[str] = []
            while time.perf_counter() < deadline:
                states = [call("gateway", "GET", f"/v1/videos/{h}", key).json()["status"] for h in handles]
                if all(s in ("completed", "failed") for s in states):
                    break
                time.sleep(5)
            assert states == ["completed", "completed"], states
            downloads = by_sdk(key, [{"kind": "download", "id": h, "save": str(files / f"live-{i}.mp4")}
                                     for i, h in enumerate(handles)])
            for d in downloads[:2]:
                assert d["status"] == 200 and d["type"] == "video/mp4", d
                assert bytes.fromhex(d["head"])[4:8] == b"ftyp" and d["length"] > 10_000, d
            print(f"INFO live {LIVE_MODEL}: text-to-video {downloads[0]['length']} bytes, image-to-video "
                  f"{downloads[1]['length']} bytes, both polled after a gateway restart", flush=True)
            ok(f"live: {LIVE_MODEL} makes one second from text and one from a first frame through the SDK; "
               "both are polled to completed after a gateway restart and downloaded as MP4s")
            leaked = [str(p) for p in directory.rglob("*") if p.is_file() and live_key.encode() in p.read_bytes()]
            assert not leaked, f"the live key was written to {len(leaked)} file(s) of the run's state"
            ok("the live key is in none of the run's state and logs")

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
        directory = Path(tempfile.mkdtemp(prefix="ep-p5-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.live)
