"""P6: moderations and `GET /v1/models/{model}`, through real signed processes.

A control root, an enrolled agent, a gateway and two inference-drivers, all
started here with isolated state and ports:

* `oai` -- the real `openai` provider against a fixture playing OpenAI's API
  as measured on 2026-09-28 (`provider-accounts-measurement.md` section 12):
  `omni-moderation-latest` and `omni-moderation-2024-09-26` listed beside a
  chat model; `/v1/moderations` taking a string, an array of strings (one
  result each) or an array of parts (one result), refusing a second image
  with OpenAI's words, and answering 429 when told to be busy.
* `router` -- the real `openrouter` provider, whose account lists no
  moderation model (OpenRouter has no moderation door: 404, measured), and
  whose ids carry slashes for `GET /v1/models/{model}`.

**The OpenAI SDK makes the requests**, unchanged
(`client.moderations.create`, `client.models.retrieve`, `client.models.list`),
from its own interpreter: this one if it has `openai`, else
`$EP_SDK_PYTHON`.

No live service is touched unless `--live` is passed, which adds an OpenAI
account with the key in `C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env`
(or `$EP_KEYS`): `omni-moderation-latest` flags a threat and reads an image.
Moderation is free.

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

NODE_NAME = "p6-agent"
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))

OAI_MODELS = ["omni-moderation-latest", "omni-moderation-2024-09-26", "gpt-4o"]
OR_LISTING = {"acme/chat": {"input": ["text"], "output": ["text"]}}
CATEGORIES = ["harassment", "harassment/threatening", "violence", "violence/graphic", "sexual"]

SDK_SNIPPET = """
import json, sys, warnings
warnings.simplefilter("ignore")
import openai
args = json.loads(sys.argv[1])
client = openai.OpenAI(base_url=args["base"], api_key=args["key"], max_retries=0, timeout=60)
out = []
for job in args["jobs"]:
    kind = job.pop("kind")
    try:
        if kind == "moderate":
            answer = client.moderations.create(**job)
            out.append({"status": 200, "kind": type(answer).__name__, "body": answer.model_dump()})
        elif kind == "retrieve":
            model = client.models.retrieve(job["model"])
            out.append({"status": 200, "kind": type(model).__name__, "body": model.model_dump()})
        elif kind == "list":
            out.append({"status": 200, "ids": [m.id for m in client.models.list()]})
    except openai.APIStatusError as e:
        out.append({"status": e.status_code, "error": e.message, "kind": type(e).__name__})
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
        from fastapi.responses import JSONResponse

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

        @app.get("/oai/v1/models")
        async def oai_models():
            return {"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "system", "shutdown_date": None} for m in OAI_MODELS
            ]}

        def verdict(text: str, image: bool) -> dict:
            threat = "hurt" in text.lower()
            kinds = ["text", "image"] if image else ["text"]
            return {
                "flagged": threat,
                "categories": {c: threat and c in ("violence", "harassment/threatening") for c in CATEGORIES},
                "category_scores": {c: (0.87 if threat and c == "violence" else 0.0001) for c in CATEGORIES},
                "category_applied_input_types": {c: kinds for c in CATEGORIES},
            }

        @app.post("/oai/v1/moderations")
        async def oai_moderate(request: Request):
            body = await request.json()
            model = body.get("model")
            given = body.get("input")
            counts[model] = counts.get(model, 0) + 1
            seen.setdefault(model, []).append({
                "model": model,
                "input": [{"type": p.get("type"), "text": p.get("text"),
                           "url_head": ((p.get("image_url") or {}).get("url") or "")[:22]}
                          if isinstance(p, dict) else p for p in (given if isinstance(given, list) else [given])],
                "keys": sorted(body),
            })
            if model not in OAI_MODELS[:2]:
                return JSONResponse({"error": {"message": f"Invalid value for 'model' = {model}.",
                                               "type": "invalid_request_error", "param": "model"}}, status_code=400)
            if modes.get(model) == "busy":
                return JSONResponse({"error": {"message": "Rate limit reached", "type": "requests"}},
                                    status_code=429, headers={"Retry-After": "1"})
            if isinstance(given, list) and given and all(isinstance(p, dict) for p in given):
                images = [p for p in given if p.get("type") == "image_url"]
                if len(images) > 1:
                    return JSONResponse({"error": {"message": f"Number of images ({len(images)}) exceeds maximum of 1",
                                                   "type": "invalid_request_error", "param": "input",
                                                   "code": "too_many_images"}}, status_code=400)
                text = " ".join(p.get("text") or "" for p in given if p.get("type") == "text")
                results = [verdict(text, bool(images))]
            else:
                texts = given if isinstance(given, list) else [given]
                results = [verdict(str(t), False) for t in texts]
            return {"id": f"modr-{counts[model]}", "model": model, "results": results}

        @app.get("/v1/models/user")
        async def or_listing():
            return {"data": [
                {"id": model_id, "name": model_id, "context_length": 4096,
                 "architecture": {"input_modalities": e["input"], "output_modalities": e["output"]},
                 "supported_parameters": ["max_tokens"]}
                for model_id, e in OR_LISTING.items()
            ]}

        @app.get("/v1/images/models")
        async def or_images():
            return {"data": []}

        @app.get("/v1/videos/models")
        async def or_videos():
            return {"data": []}

    elif kind in ("router", "oai", "oai-live"):
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
        names += ["oai-live"]
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
    live_key = _key("OPENAI_API_KEY") if live else None
    image = "data:image/png;base64," + base64.b64encode(solid_png(64, 64, (200, 30, 30))).decode()

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

    def seen(model):
        return call("fixture", "GET", "/seen", params={"model": model}).json()

    def by_sdk(token, jobs):
        result = subprocess.run(
            [sdk, "-c", SDK_SNIPPET, json.dumps({"base": url("gateway") + "/v1", "key": token, "jobs": jobs})],
            capture_output=True, text=True, timeout=300,
            env={k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENAI_BASE_URL")},
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return json.loads(result.stdout.strip().splitlines()[-1])

    def moderate(token, **body):
        return call("gateway", "POST", "/v1/moderations", token, json=body)

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
        # One moderation model to begin with: `model` left out names it (P6-1).
        driver("oai", {"provider": "openai", "baseUrl": url("fixture") + "/oai",
                       "catalogueInclude": ["omni-moderation-latest", "gpt-4o"]},
               {"OPENAI_API_KEY": "fixture-oai"})
        slots = [{"model": "verdicts", "targets": ["oai/omni-moderation-latest", "oai/omni-moderation-2024-09-26"]}]
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

        wanted = {"oai/omni-moderation-latest", "oai/gpt-4o", "router/acme/chat"}
        wait(lambda: wanted <= set(models()), "the fixture accounts' models are routable")

        def recorded(request_id):
            found = []

            def written():
                rows = call("gateway", "GET", "/v1/metrics/requests", operator, params={"limit": 30}).json()
                found[:] = [r for r in rows["requests"] if r.get("requestId") == request_id]
                return bool(found)
            wait(written, f"the metrics row for request {request_id}", 10)
            return found[0]

        # --- 1. listed, and one model by id ------------------------------------------
        listed = models()
        assert listed["oai/omni-moderation-latest"]["surfaces"] == ["moderation"], listed["oai/omni-moderation-latest"]
        assert "moderation" not in listed["router/acme/chat"]["surfaces"], listed["router/acme/chat"]
        results = by_sdk(key, [
            {"kind": "retrieve", "model": "oai/omni-moderation-latest"},
            {"kind": "retrieve", "model": "router/acme/chat"},
            {"kind": "retrieve", "model": "router/acme/nope"},
            {"kind": "list"},
        ])
        found, slashed, missing, all_ids, sdk_info = results
        assert found["status"] == 200 and found["kind"] == "Model", found
        assert found["body"]["id"] == "oai/omni-moderation-latest", found
        full = call("gateway", "GET", "/v1/models/oai/omni-moderation-latest", key).json()
        listed_entry = next(m for m in call("gateway", "GET", "/v1/models", key).json()["data"]
                            if m["id"] == "oai/omni-moderation-latest")
        assert full == listed_entry, (full, listed_entry)
        assert slashed["status"] == 200 and slashed["body"]["id"] == "router/acme/chat", slashed
        assert missing["status"] == 404 and missing["kind"] == "NotFoundError", missing
        assert "oai/omni-moderation-latest" in all_ids["ids"], all_ids
        ok(f"the OpenAI SDK {sdk_info['sdk']} retrieves one model by id, slashes included, as the list shows it "
           "(x_eugene_plexus and all); an unknown id is its NotFoundError; the moderation model is listed as such")

        # --- 2. the done-when: the SDK moderates, model left out -------------------------
        before = counts()
        results = by_sdk(key, [
            {"kind": "moderate", "input": "I will hurt you."},
            {"kind": "moderate", "model": "oai/omni-moderation-latest", "input": ["hello", "I will hurt you."]},
            {"kind": "moderate", "model": "oai/omni-moderation-latest", "input": [
                {"type": "text", "text": "a red square"}, {"type": "image_url", "image_url": {"url": image}}]},
        ])
        single, batch, multimodal = results[:3]
        assert single["status"] == 200 and single["kind"] == "ModerationCreateResponse", single
        assert single["body"]["model"] == "oai/omni-moderation-latest", single["body"]["model"]
        verdict = single["body"]["results"][0]
        assert verdict["flagged"] is True and verdict["categories"]["violence"] is True, verdict
        assert [r["flagged"] for r in batch["body"]["results"]] == [False, True], batch
        assert multimodal["status"] == 200, multimodal
        applied = multimodal["body"]["results"][0]["category_applied_input_types"]["violence"]
        assert applied == ["text", "image"], multimodal
        assert counts().get("omni-moderation-latest", 0) == before.get("omni-moderation-latest", 0) + 3
        sent = seen("omni-moderation-latest")[-3:]
        assert sent[0]["input"] == ["I will hurt you."] and sent[0]["keys"] == ["input", "model"], sent[0]
        assert sent[1]["input"] == ["hello", "I will hurt you."], sent[1]
        assert [p["type"] for p in sent[2]["input"]] == ["text", "image_url"], sent[2]
        assert sent[2]["input"][1]["url_head"].startswith("data:image/png"), sent[2]
        ok("the OpenAI SDK, unchanged, moderates with model left out (the one moderation model answers, P6-1), "
           "a batch gets one verdict each, and text with an image is one input with one verdict; OpenAI is asked "
           "in its own shape with its own model id")

        # --- 3. refused before anything is sent -------------------------------------------
        before = counts()
        refusals = [
            (moderate(key, input="hi", user="x"), "user", "not a field"),
            (moderate(key, input=["a", {"type": "text", "text": "b"}]), "input", "mixes strings and parts"),
            (moderate(key, input=[{"type": "image_url", "image_url": {"url": "https://example.com/x.png"}}]),
             "input[0].image_url.url", "URLs are not fetched"),
            (moderate(key, model="oai/gpt-4o", input="hi"), None, "/v1/chat/completions"),
        ]
        for response, param, said in refusals:
            assert response.status_code == 400, response.text[:300]
            assert said in error_of(response).get("message", ""), response.text[:300]
            if param is not None:
                assert error_of(response).get("param") == param, response.text[:300]
        # The driver's own copy of the surface rule, asked directly.
        response = call("oai", "POST", "/v1/moderate", operator, json={"model": "gpt-4o", "texts": ["hi"]})
        assert response.status_code == 400, response.text[:300]
        assert response.json()["detail"]["type"].endswith("#moderation-unsupported"), response.text[:300]
        assert counts() == before, (before, counts())
        response = moderate(key, model="oai/omni-moderation-latest", input=[
            {"type": "image_url", "image_url": {"url": image}}, {"type": "image_url", "image_url": {"url": image}}])
        assert response.status_code == 400 and "exceeds maximum of 1" in error_of(response).get("message", ""), \
            response.text[:300]
        ok("an unknown field, strings mixed with parts, a remote image (A4) and a chat model are 400s naming why, "
           "and the driver refuses a chat model too when asked directly; none reaches OpenAI. Its own limit of one "
           "image is relayed in its words")

        # --- 4. same model only, and the row ------------------------------------------------
        call("fixture", "POST", "/mode", params={"model": "omni-moderation-latest", "mode": "busy"}).raise_for_status()
        call("oai", "PATCH", "/v1/config", operator,
             json={"catalogueInclude": ["omni-moderation-latest", "omni-moderation-2024-09-26", "gpt-4o"]}
             ).raise_for_status()
        wait(lambda: "oai/omni-moderation-2024-09-26" in models(), "the second moderation model is routable", 60)
        before = counts()
        response = moderate(key, model="verdicts", input="hi")
        after = counts()
        assert response.status_code >= 400, response.text[:300]
        assert after.get("omni-moderation-latest", 0) == before.get("omni-moderation-latest", 0) + 1, (before, after)
        assert after.get("omni-moderation-2024-09-26", 0) == before.get("omni-moderation-2024-09-26", 0), \
            (before, after)
        print(f"INFO verdicts with its first model busy: {response.status_code} {response.text[:160]}", flush=True)
        call("fixture", "POST", "/mode", params={"model": "omni-moderation-latest", "mode": "ok"}).raise_for_status()
        # The 429 cooled the backend (its circuit), so the next request waits
        # that out rather than being served at once.
        served: list[httpx.Response] = []
        wait(lambda: served.append(moderate(key, model="verdicts", input="hi")) or served[-1].status_code == 200,
             "the first model served again after its cooldown", 60)
        response = served[-1]
        # A slot answers under the model that served it, as chat's does.
        assert response.json()["model"] == "oai/omni-moderation-latest", response.json()
        row = recorded(response.headers["x-request-id"])
        assert (row["door"], row["servedModel"], row["tier"], row["outcome"]) == (
            "moderation", "oai/omni-moderation-latest", 1, "served"), row
        several = moderate(key, input="hi")
        assert several.status_code == 400 and error_of(several).get("param") == "model", several.text[:300]
        assert "omni-moderation-2024-09-26" in error_of(several)["message"], several.text[:300]
        ok("verdicts -> [latest, 2024-09-26] never asks the second model when the first is busy (P6-2); served, "
           "its row says door moderation, tier 1; with two moderation models, model left out is a 400 naming both")

        # --- 5. a key's limits hold at both doors --------------------------------------------
        before = counts()
        scoped = mint("Only chat", allowedModels=["router/acme/chat"])
        response = moderate(scoped, input="hi")
        assert response.status_code == 400 and "no moderation model you may use" in error_of(response)["message"], \
            response.text[:300]
        response = moderate(scoped, model="oai/omni-moderation-latest", input="hi")
        assert response.status_code in (403, 404), response.text[:300]
        response = call("gateway", "GET", "/v1/models/oai/omni-moderation-latest", scoped)
        assert response.status_code == 404, response.text[:300]
        assert call("gateway", "GET", "/v1/models/router/acme/chat", scoped).status_code == 200
        local = mint("Local only", localOnly=True)
        response = moderate(local, model="oai/omni-moderation-latest", input="hi")
        assert response.status_code in (400, 403, 404), response.text[:300]
        assert counts() == before, (before, counts())
        ok("a key allowed only acme/chat has no moderation model to leave out, cannot name one, and is told a "
           "model it may not use does not exist (while its own is found); a local-only key reaches no hosted "
           "moderator; nothing reaches OpenAI")

        # --- 6. the live half ----------------------------------------------------------------
        if live:
            # Started only now: a second moderation model would make every
            # earlier `model` left out a 400 naming both, correctly.
            driver("oai-live", {"provider": "openai", "catalogueInclude": ["omni-moderation-latest"]},
                   {"OPENAI_API_KEY": live_key})
            model = "oai-live/omni-moderation-latest"
            wait(lambda: model in models(), "OpenAI's live moderation model", 60)
            photo = "data:image/png;base64," + base64.b64encode(solid_png(256, 256, (20, 120, 40))).decode()
            results = by_sdk(key, [
                {"kind": "moderate", "model": model, "input": "I will hurt you."},
                {"kind": "moderate", "model": model, "input": [
                    {"type": "text", "text": "a green square"}, {"type": "image_url", "image_url": {"url": photo}}]},
                {"kind": "retrieve", "model": model},
            ])
            threat, picture, retrieved = results[:3]
            assert threat["status"] == 200 and threat["body"]["results"][0]["flagged"] is True, threat
            assert threat["body"]["results"][0]["categories"]["violence"] is True, threat
            assert picture["status"] == 200, picture
            kinds = {k for v in picture["body"]["results"][0]["category_applied_input_types"].values() for k in v}
            assert "image" in kinds, picture
            assert retrieved["status"] == 200 and retrieved["body"]["id"] == model, retrieved
            scores = threat["body"]["results"][0]["category_scores"]
            print(f"INFO live omni-moderation-latest: violence {scores['violence']:.2f}, "
                  f"threatening {scores['harassment/threatening']:.2f}; image read as {sorted(kinds)}", flush=True)
            ok("live: OpenAI's omni-moderation-latest flags a threat and reads an image through the SDK, and is "
               "retrieved by id")
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
        directory = Path(tempfile.mkdtemp(prefix="ep-p6-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.live)
