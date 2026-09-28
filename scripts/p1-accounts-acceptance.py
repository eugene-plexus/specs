"""P1: one driver serving many models, through real signed processes.

A control root, an enrolled agent, a gateway and three inference-driver
processes, all started here with isolated state and ports:

* `acct` -- a provider ACCOUNT (an OpenAI-compatible driver with no model
  set) over a counting upstream fixture that lists two models;
* `solo` -- a single-model driver over the same fixture, which must keep
  its bare id;
* `legacy` -- a stub answering `/v1/info` in the shape from before P1.

No live service, model or provider is touched unless `--openrouter-live` is
passed, which adds a real OpenRouter account read with the key in
`C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env` (or `$EP_KEYS`).
That key is handed to its driver process in the `OPENAI_API_KEY`
environment variable the engine already falls back to, so it is never
written to a config file, a log or this script's output. It costs a few
hundred-thousandths of a dollar.

Run in an environment containing all five Python components. Logs and
state stay in a temporary tree.
"""

from __future__ import annotations

import argparse
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

NODE_NAME = "p1-agent"
ACCOUNT_MODELS = ("alpha/model-a", "beta/model-b:free")
#: Different per model, as vLLM's listing reports them, so a candidate that
#: carried another model's facts is visible on `GET /v1/models`.
WINDOWS = {"alpha/model-a": 8192, "beta/model-b:free": 32768}
KEYS_FILE = Path(os.environ.get("EP_KEYS", "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"))


def _openrouter_key() -> str:
    for line in KEYS_FILE.read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "OPENROUTER_API_KEY":
            return value.strip().strip('"').strip("'")
    raise SystemExit(f"no OPENROUTER_API_KEY in {KEYS_FILE}")


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse, StreamingResponse

        app = FastAPI()
        # Counted by the model the upstream was ASKED for, which is the
        # whole of what P1 changes on the wire.
        counts: dict[str, int] = {}
        state = {"list_fails": False}

        @app.get("/healthz")
        async def health():
            return {}

        @app.get("/stats")
        async def stats():
            return counts

        @app.post("/list-fails")
        async def list_fails(request: Request):
            state["list_fails"] = (await request.json())["enabled"]
            return {}

        @app.get("/{scope}/v1/models")
        async def models(scope: str):
            if state["list_fails"]:
                return JSONResponse({"error": {"message": "listing is down"}}, status_code=503)
            ids = ACCOUNT_MODELS if scope == "acct" else ("solo",)
            return {
                "data": [
                    {"id": i, "object": "model", **({"max_model_len": WINDOWS[i]} if i in WINDOWS else {})}
                    for i in ids
                ]
            }

        @app.get("/{scope}/props")
        async def props(scope: str):
            return JSONResponse({}, status_code=404)

        @app.post("/{scope}/v1/chat/completions")
        async def chat(scope: str, request: Request):
            body = await request.json()
            model = body.get("model")
            counts[model] = counts.get(model, 0) + 1
            text = f"answer from {model}"
            usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
            if body.get("stream"):

                async def stream():
                    for piece in (text[:6], text[6:]):
                        yield "data: " + json.dumps(
                            {
                                "model": model,
                                "choices": [
                                    {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                                ],
                            }
                        ) + "\n\n"
                    yield "data: " + json.dumps(
                        {
                            "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": usage,
                        }
                    ) + "\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(stream(), media_type="text/event-stream")
            return {
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }

    elif kind == "legacy":
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/healthz")
        async def legacy_health():
            return {"status": "ok"}

        @app.get("/v1/info")
        async def legacy_info():
            # The shape every driver answered with before P1.
            return {
                "backend": "openai_compat_http",
                "modelId": "legacy-model",
                "version": "0.9.0",
                "capabilities": {"streaming": True},
            }

    elif kind in ("acct", "solo", "openrouter"):
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
                client_key_refresh_seconds=0.15,
                client_key_max_age_seconds=3.5,
                client_key_timeout_seconds=0.4,
                client_key_retry_seconds=0.1,
                **bootstrap,
            )
        )
    else:
        raise SystemExit(f"unknown process kind {kind!r}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path, *, live: bool) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    names = ["control", "agent", "gateway", "fixture", "acct", "solo", "legacy"]
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
    client = httpx.Client(timeout=30, trust_env=False)
    passphrase = secrets.token_urlsafe(24)
    passed = 0

    def ok(message: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {message}", flush=True)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": "Bearer " + token} if token else {},
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
        write("acct", "bootstrap.json", bootstrap("inference-driver"))
        # No modelId: a provider ACCOUNT (P1-2).
        write("acct", "driver.yaml", {
            "provider": "openai_compat_custom", "baseUrl": url("fixture") + "/acct",
            "backendLocality": "local",
        })
        write("solo", "bootstrap.json", bootstrap("inference-driver"))
        write("solo", "driver.yaml", {
            "provider": "openai_compat_custom", "baseUrl": url("fixture") + "/solo",
            "modelId": "solo", "backendLocality": "local",
        })
        for name in ("acct", "solo", "legacy"):
            start(name)
            declare(name)
        if live:
            write("openrouter", "bootstrap.json", bootstrap("inference-driver"))
            write("openrouter", "driver.yaml", {"provider": "openrouter", "catalogueInclude": ["*"]})
            start("openrouter", {"OPENAI_API_KEY": _openrouter_key()})
            declare("openrouter")
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2})
        start("gateway")

        def mint(name, allowed):
            response = call("agent", "POST", "/v1/auth/client-keys", operator, json={
                "name": name, "limits": {"allowedModels": allowed, "requestsPerMinute": 1000},
            })
            response.raise_for_status()
            return response.json()["token"]

        everything = mint("Everything", None)
        acct_only = mint("Account only", ["acct/*"])
        one_model = mint("One model", ["acct/alpha/*"])

        def listed(token):
            return [m["id"] for m in call("gateway", "GET", "/v1/models", token).json().get("data", [])]

        wanted = {"acct/alpha/model-a", "acct/beta/model-b:free", "solo"}
        wait(lambda: wanted <= set(listed(everything)), "the account's models are routable")

        # --- 1. ids ---------------------------------------------------------
        ids = listed(everything)
        assert "acct/alpha/model-a" in ids and "acct/beta/model-b:free" in ids, ids
        assert "solo" in ids and "legacy-model" not in ids, ids
        info = call("acct", "GET", "/v1/info", operator).json()
        assert "modelId" not in info and sorted(m["id"] for m in info["models"]) == list(ACCOUNT_MODELS), info
        assert info["catalogue"]["source"] == "openai" and info["catalogue"]["exposed"] == 2, info["catalogue"]
        windows = {
            m["id"]: (m.get("x_eugene_plexus") or {}).get("context_length")
            for m in call("gateway", "GET", "/v1/models", everything).json()["data"]
        }
        # Each candidate carries its own model's facts, not its driver's
        # first model's: the two windows differ upstream and must here.
        assert windows["acct/alpha/model-a"] == 8192, windows
        assert windows["acct/beta/model-b:free"] == 32768, windows
        ok("one account driver lists two models, published as acct/<id>, each with its own facts; a single-model driver keeps its bare id")

        # --- 2. the wire ----------------------------------------------------
        before = call("fixture", "GET", "/stats").json()
        for model, stream in (("acct/alpha/model-a", False), ("acct/beta/model-b:free", True)):
            response = call("gateway", "POST", "/v1/chat/completions", everything, json={
                "model": model, "stream": stream,
                "messages": [{"role": "user", "content": "hi"}],
            })
            assert response.status_code == 200, response.text
            upstream = model.split("/", 1)[1]
            if stream:
                frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
                text = "".join(
                    (c.get("delta") or {}).get("content") or ""
                    for f in frames for c in f.get("choices") or []
                )
                assert text == f"answer from {upstream}", text
                assert {f.get("model") for f in frames} == {model}, {f.get("model") for f in frames}
            else:
                body = response.json()
                assert body["choices"][0]["message"]["content"] == f"answer from {upstream}", body
                assert body["model"] == model, body["model"]
        after = call("fixture", "GET", "/stats").json()
        for model in ACCOUNT_MODELS:
            assert after.get(model, 0) == before.get(model, 0) + 1, (model, before, after)
        ok("each request reached the upstream as the model it named, unprefixed; answers came back under the public id, streamed and not")

        # --- 3. keys scoped by pattern ---------------------------------------
        assert sorted(listed(acct_only)) == ["acct/alpha/model-a", "acct/beta/model-b:free"], listed(acct_only)
        assert listed(one_model) == ["acct/alpha/model-a"], listed(one_model)
        # Refused by the key's authority, the agent, before routing: the
        # same * rule runs there as in the gateway's model list.
        refused = call("gateway", "POST", "/v1/chat/completions", acct_only, json={
            "model": "solo", "messages": [{"role": "user", "content": "hi"}]})
        assert refused.status_code == 403, refused.text
        refused = call("gateway", "POST", "/v1/chat/completions", one_model, json={
            "model": "acct/beta/model-b:free", "messages": [{"role": "user", "content": "hi"}]})
        assert refused.status_code == 403, refused.text
        allowed = call("gateway", "POST", "/v1/chat/completions", acct_only, json={
            "model": "acct/beta/model-b:free", "messages": [{"role": "user", "content": "hi"}]})
        assert allowed.status_code == 200, allowed.text
        ok("a key scoped acct/* sees and uses the account's models and nothing else; acct/alpha/* narrows it")

        # --- 4. the driver that was not updated --------------------------------
        view = call("gateway", "GET", "/v1/admin/routing", operator).json()
        outdated = view.get("outdated_drivers") or []
        assert [(d["name"], d["node"], d.get("modelId")) for d in outdated] == [("legacy", NODE_NAME, "legacy-model")], outdated
        health = {d["name"]: d for d in call("gateway", "GET", "/v1/admin/drivers", operator).json()["drivers"]}
        assert health["legacy"]["outdated"] is True and health["legacy"]["node"] == NODE_NAME, health["legacy"]
        assert health["acct"]["account"] is True and health["acct"]["modelCount"] == 2, health["acct"]
        assert health["solo"]["modelId"] == "solo" and health["solo"]["outdated"] is False, health["solo"]
        refused = call("gateway", "POST", "/v1/chat/completions", everything, json={
            "model": "legacy-model", "messages": [{"role": "user", "content": "hi"}]})
        assert refused.status_code == 404, refused.text
        ok("a driver still reporting one modelId is routed nothing and named with its machine as outdated")

        # --- 5. attempts record their model ----------------------------------
        def attempts():
            rows = call("gateway", "GET", "/v1/metrics/requests", operator).json().get("requests", [])
            return [a.get("model") for r in rows for a in r.get("tries", [])]

        wait(lambda: "acct/alpha/model-a" in attempts(), "metrics record the attempt's model", 15)
        ok("each metrics attempt records the published model it asked for (schema v6)")

        # --- 6. patterns apply live ------------------------------------------
        patched = call("acct", "PATCH", "/v1/config", operator, json={"catalogueExclude": ["beta/*"]}).json()
        assert patched.get("requiresRestart") is False, patched
        wait(lambda: "acct/beta/model-b:free" not in listed(everything), "the excluded model left the list", 20)
        before = call("fixture", "GET", "/stats").json().get("beta/model-b:free", 0)
        direct = call("acct", "POST", "/v1/generate", operator, json={
            "model": "beta/model-b:free", "messages": [{"role": "user", "content": "hi"}]})
        assert direct.status_code == 404 and direct.json()["detail"]["type"].endswith("#model-not-served"), direct.text
        assert call("fixture", "GET", "/stats").json().get("beta/model-b:free", 0) == before
        call("acct", "PATCH", "/v1/config", operator, json={"catalogueExclude": []}).raise_for_status()
        ok("an exclude pattern takes effect without a restart; the excluded model is 404 at the driver and never reaches the upstream")

        # --- 7. a restart with the upstream's list down ------------------------
        stop("acct")
        call("fixture", "POST", "/list-fails", json={"enabled": True}).raise_for_status()
        start("acct")
        wait(lambda: call("acct", "GET", "/v1/info", operator).json()["catalogue"].get("error"), "the failed read is reported")
        info = call("acct", "GET", "/v1/info", operator).json()
        assert sorted(m["id"] for m in info["models"]) == list(ACCOUNT_MODELS), info
        assert "503" in info["catalogue"]["error"] and info["catalogue"]["refreshedAt"], info["catalogue"]
        response = call("gateway", "POST", "/v1/chat/completions", everything, json={
            "model": "acct/alpha/model-a", "messages": [{"role": "user", "content": "hi"}]})
        assert response.status_code == 200, response.text
        call("fixture", "POST", "/list-fails", json={"enabled": False}).raise_for_status()
        ok("restarted while its upstream's list is down, the account still serves the last good list and says why")

        # --- 8. live OpenRouter -----------------------------------------------
        if live:
            wait(lambda: any(i.startswith("openrouter/") for i in listed(everything)), "OpenRouter's models", 60)
            routes = [i for i in listed(everything) if i.startswith("openrouter/")]
            info = call("openrouter", "GET", "/v1/info?models=false", operator).json()["catalogue"]
            # P1-4: speech, image and video models are on the driver and not
            # on /v1/models until their doors exist.
            assert info["source"] == "openrouter" and info["exposed"] > len(routes) > 100, (info, len(routes))
            assert "openrouter/hexgrad/kokoro-82m" not in routes
            live_key = mint("OpenRouter only", ["openrouter/*"])
            answers = {}
            for model in ("openrouter/mistralai/mistral-nemo", "openrouter/~z-ai/glm-flash-latest"):
                response = call("gateway", "POST", "/v1/chat/completions", live_key, json={
                    "model": model, "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Reply with exactly: pong"}]})
                assert response.status_code == 200, response.text[:400]
                answers[model] = response.json()
                # The alias answers under its target upstream; the caller
                # still sees the id it asked for.
                assert answers[model]["model"] == model, answers[model]["model"]
            assert listed(live_key) == routes
            print(f"INFO openrouter: {info['total']} listed, {info['exposed']} exposed, {len(routes)} on /v1/models", flush=True)
            ok("a real OpenRouter account: two models over one driver and one key, the alias reported as asked")

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
        directory = Path(tempfile.mkdtemp(prefix="ep-p1-acceptance-"))
        print(f"Isolated state and process logs: {directory}", flush=True)
        exercise(directory, live=args.openrouter_live)
