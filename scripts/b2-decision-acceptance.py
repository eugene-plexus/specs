"""B2: typed decisions, end to end, with a REAL Kev under real supervision.

The whole chain, nothing faked in the middle: a real control root, a
real enrolled agent that SPAWNS `python -m kev.serve` on the pinned
checkpoint (`jaredpalmer/kev-0.8b` @ 54f4f877) and declares its
companion driver, a real gateway routing `POST /v1/systemone` to it, and
real `curl` as the first client. The kev process is the only model
backend that is real; two additional System One backends are counting
fixtures (labeled simulated) for the checks a real model cannot produce
deterministically — a second distinguishable alias, controlled
misbehavior, a held request for the timeout and concurrency gates.

Designed to run INSIDE WSL from one venv holding all four components
(see docs/acceptance/decision-run.md for the environment), on CPU only —
`CUDA_VISIBLE_DEVICES=""` rides the runtime's own env so the owner's GPU
is never touched. Ephemeral ports, ambient EUGENE_PLEXUS_* cleared,
teardown by pid.

Credentials (per-node token keys, 2026-09-25). `agent-a` is the control
host's agent and joins with the `gateway` grant, as the wizard joins it,
because the gateway on its machine reads the control root. The kev
runtime and its companion driver are the agent's own children and get
their credentials from it; the two stub drivers and the gateway, which
this script starts itself, are given exactly what `agent-a` hands a child:
its `trust_bundle.json`, the `controlPublicKey` from its `node.yaml`,
`node:agent-a`, and a service token `agent-a`'s own key signs for its
machine. The operator signs in on `agent-a`, whose session the root
mints for `agent-a` and the root; every call here lands on that machine.
Client keys are the root's, forwarded by `agent-a`. No check was removed;
the install signing key the old harness read out of `node.yaml` to derive
a verify key and mint the gateway's token no longer exists, so those two
derivations are gone rather than any assertion.

Last run, 2026-09-25, inside WSL2 Ubuntu from the B2 venv (`~/b2/ep-venv`,
the four components editable from the current local repos under /mnt/d;
a dry-run reinstall showed nothing to change), CPU only:
    cd /mnt/d/py/eugene-plexus/specs/scripts && \\
        ~/b2/ep-venv/bin/python b2-decision-acceptance.py --directory /tmp/ep-b2-row3
-> ALL 13 CHECKS PASSED, first execution: cold start 9.4 s, offline
restart 6.0 s, p50 239 ms / p95 252 ms, peak RSS 5627392 kB, routing
fidelity 5/5, proxy overhead 37 ms median.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import yaml

from fastapi import Request  # noqa: E402 — module-level so handler annotations resolve

KEV_PYTHON = os.path.expanduser("~/b2/kev/.venv/bin/python")
KEV_CHECKPOINT = os.path.expanduser(
    "~/.cache/huggingface/hub/models--jaredpalmer--kev-0.8b/snapshots/"
    "54f4f8777356cd5bbbb6c6919c657f26e6f2f6d8"
)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(
            Settings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(
                config_file=directory / "agent.yaml",
                default_topology=False,
                bind_port=port,
            )
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
    elif kind == "driver":
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(Settings(config_file=directory / "driver.yaml", **bootstrap))
    elif kind == "sostub":
        # A simulated System One server: answers only its expected model
        # name, with derivable answers, plus scripted misbehavior for the
        # checks a real model cannot produce on demand.
        import asyncio

        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI()
        expected = (directory / "expected.txt").read_text(encoding="utf-8").strip()
        stats = {"served": 0, "finished": 0, "violations": 0}
        modes: dict[str, object] = {"hold": 0.0, "break": None}

        @app.get("/healthz")
        async def harness_health():
            return {}

        @app.get("/stats")
        async def stub_stats():
            return stats

        @app.post("/mode")
        async def set_mode(request: Request):
            modes.update(await request.json())
            return modes

        @app.get("/v1/models")
        async def models():
            return {"models": [{"id": expected, "device": "stub"}]}

        @app.post("/v1/systemone")
        async def systemone(request: Request):
            body = await request.json()
            if body.get("model") != expected:
                stats["violations"] += 1
                return JSONResponse({"detail": "unknown model"}, status_code=422)
            stats["served"] += 1
            hold = float(modes.get("hold") or 0)
            if hold:
                await asyncio.sleep(hold)
            answers = {}
            for name, question in (body.get("questions") or {}).items():
                kind_ = question.get("type")
                if kind_ == "noul":
                    answers[name] = {"type": "noul", "noul": 0.25}
                elif kind_ == "choice":
                    options = list(question.get("criteria") or {})
                    answers[name] = {
                        "type": "choice",
                        "choice": options[-1],
                        "probabilities": {
                            o: (1.0 if o == options[-1] else 0.0) for o in options
                        },
                        "confidence": 0.5,
                    }
                else:
                    levels = question.get("criteria") or []
                    answers[name] = {
                        "type": "score",
                        "score": 0.0,
                        "legend": {str(i): lv for i, lv in enumerate(levels)},
                        "probabilities": {
                            str(i): (1.0 if i == 0 else 0.0) for i in range(len(levels))
                        },
                        "confidence": 0.5,
                    }
            if modes.get("break") == "missing_answer" and answers:
                answers.pop(sorted(answers)[0])
            if modes.get("break") == "wrong_type" and answers:
                first = sorted(answers)[0]
                answers[first] = {"type": "noul", "noul": 2.5}
            stats["finished"] += 1
            return {
                "model": body.get("model"),
                "answers": answers,
                "usage": {"input_tokens": 11, "output_tokens": 7},
                "latency_ms": 1.0,
            }
    else:
        raise SystemExit(f"unknown serve kind {kind!r}")

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def child_environment(agent_dir: Path, sub: str, agent_url: str) -> dict:
    """What `agent_dir`'s agent hands a child it spawns (supervisor.py).

    The bundle path, the authority pinned at enrollment, this machine's
    recipient name and a token this node's own key signs for this machine
    only -- never a key. `sub` is the child's kind, as the agent mints it.
    """
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(agent_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, agent_dir / BUNDLE_FILE)
    trust.load()
    assert trust.enrolled and trust.bundle is not None, f"{agent_dir.name} holds no bundle"
    token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
    return {
        "trust_bundle_file": str(trust.bundle_path),
        "trust_authority": trust.authority,
        "auth_recipient": trust.recipient,
        "service_token": token,
        "agent_url": agent_url,
    }


def exercise(directory: Path) -> None:
    import jwt

    passed = 0

    def ok(label: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {passed:02d} {label}", flush=True)

    names = ("control", "agent-a", "gateway", "driver-inv", "driver-ext", "stub-inv", "stub-ext")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets)}
    for sock in sockets:
        sock.close()

    processes: dict[str, subprocess.Popen] = {}
    logs = []
    client = httpx.Client(timeout=30, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
        return client.request(
            method,
            url(name) + path,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            **kwargs,
        )

    def wait(check, label: str, seconds: float = 30) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise AssertionError("timed out: " + label)

    def start(name: str, kind: str) -> None:
        work = directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
            ],
            cwd=work,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name + " healthz")

    def stop(name: str) -> None:
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def login(name: str) -> str:
        """A session from `name`'s sign-in. An enrolled agent forwards it to
        the root and answers 503 while the root is unreachable, so wait."""
        deadline = time.perf_counter() + 20
        while True:
            response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
            if response.status_code != 503 or time.perf_counter() > deadline:
                break
            time.sleep(0.25)
        assert response.status_code == 200, (name, response.text)
        return response.json()["sessionToken"]

    def decide(token: str, model: str, questions: dict, state: object = "x", **kwargs):
        return call(
            "gateway",
            "POST",
            "/v1/systemone",
            token,
            json={"model": model, "state": state, "questions": questions, **kwargs},
        )

    TICKET = (
        "Customer: I was charged twice for order A-1 and I want my money back. "
        "Agent: I found the duplicate charge and issued a full refund just now."
    )
    MIXED = {
        "refunded": {"type": "noul", "instructions": "Was a refund issued?"},
        "route": {
            "type": "choice",
            "instructions": "Route this ticket.",
            "criteria": {"billing": "payments", "shipping": "delivery", "technical": "bugs"},
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent is this ticket now?",
            "criteria": ["low", "medium", "high"],
        },
    }

    try:
        assert Path(KEV_PYTHON).is_file(), f"no kev interpreter at {KEV_PYTHON}"
        assert Path(KEV_CHECKPOINT).is_dir(), f"no pinned checkpoint at {KEV_CHECKPOINT}"

        # --- the install ---------------------------------------------------
        start("control", "control")
        assert (
            call(
                "control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
            ).status_code
            == 204
        )
        root_session = login("control")
        work = directory / "agent-a"
        work.mkdir(exist_ok=True)
        (work / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "advertiseUrl": url("agent-a"),
                    "securityMode": "prompt_on_startup",
                    "components": [],
                }
            ),
            encoding="utf-8",
        )
        start("agent-a", "agent")
        assert (
            call(
                "agent-a", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
            ).status_code
            == 200
        )
        local_operator = login("agent-a")
        # The control host's join: with the gateway grant, as the wizard
        # mints it, because the gateway on this machine reads the root.
        join = call(
            "control", "POST", "/v1/nodes/join-token", root_session, json={"grants": ["gateway"]}
        )
        assert join.status_code in (200, 201), join.text
        enrolled = call(
            "agent-a",
            "POST",
            "/v1/node/enroll",
            local_operator,
            json={"controlUrl": url("control"), "token": join.json()["token"], "name": "agent-a"},
        )
        assert enrolled.status_code == 200, enrolled.text

        # The operator's session for everything on agent-a's machine: the
        # root mints it on agent-a's sign-in, addressed to agent-a and it.
        operator = login("agent-a")
        aud = jwt.decode(operator, options={"verify_signature": False})["aud"]
        assert aud == ["node:agent-a", "control"], aud

        # --- the REAL kev runtime, supervised by the agent ----------------
        # The launch policy refused the first two shapes, correctly, and
        # the second refusal is a finding worth keeping: a uv venv's
        # python is a SYMLINK to the shared uv-managed CPython, so
        # `engineBinaryRoots` can never whitelist it by directory — the
        # guard resolves the link and the venv's bin never contains the
        # real file (S5's `sys.prefix` lesson, one guard over). The
        # by-design path is the engine's own config key: a binary equal
        # to the CONFIGURED interpreter is trusted, resolving both sides.
        assert (
            call(
                "agent-a",
                "PATCH",
                "/v1/config",
                operator,
                json={"kevPython": KEV_PYTHON},
            ).status_code
            == 200
        )
        started_launch = time.perf_counter()
        declared = call(
            "agent-a",
            "POST",
            "/v1/runtimes",
            operator,
            json={
                "name": "tickets",
                "engine": "kev",
                "modelPath": KEV_CHECKPOINT,
                "modelAlias": "tickets",
                # The owner's GPU is not this run's to take (CUDA torch is
                # installed in the kev venv); CPU is the measured target.
                "env": {"CUDA_VISIBLE_DEVICES": ""},
            },
        )
        assert declared.status_code == 201, declared.text
        assert declared.json().get("driver") == "tickets-driver", declared.text

        def runtime_status() -> str:
            body = call("agent-a", "GET", "/v1/runtimes", operator).json()
            for runtime in body.get("runtimes", []):
                if runtime.get("name") == "tickets":
                    return str(runtime.get("status"))
            return "absent"

        wait(lambda: runtime_status() == "ready", "kev loads on CPU", seconds=300)
        cold_start_s = time.perf_counter() - started_launch
        ok(
            f"the agent spawned the pinned kev-0.8b and proved it ready in "
            f"{cold_start_s:.1f}s (cold, CPU)"
        )

        # --- the two simulated backends and the gateway --------------------
        for stub, expected in (("stub-inv", "invoices"), ("stub-ext", "cloudy")):
            work = directory / stub
            work.mkdir(exist_ok=True)
            (work / "expected.txt").write_text(expected, encoding="utf-8")
            start(stub, "sostub")

        def driver_dir(name: str, stub: str, alias: str, locality: str, extra: dict) -> None:
            work = directory / name
            work.mkdir(exist_ok=True)
            config = {
                "provider": "systemone_custom",
                "baseUrl": url(stub),
                "modelId": alias,
                "backendLocality": locality,
            }
            config.update(extra)
            (work / "driver.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
            (work / "bootstrap.json").write_text(
                json.dumps(
                    child_environment(directory / "agent-a", "inference-driver", url("agent-a"))
                ),
                encoding="utf-8",
            )
            start(name, "driver")
            assert (
                call(
                    "agent-a",
                    "POST",
                    "/v1/components",
                    operator,
                    json={"name": name, "kind": "inference-driver", "url": url(name)},
                ).status_code
                == 201
            )

        driver_dir("driver-inv", "stub-inv", "invoices", "local", {"decisionMaxConcurrent": 1})
        driver_dir("driver-ext", "stub-ext", "cloudy", "external", {})

        work = directory / "gateway"
        work.mkdir(exist_ok=True)
        (work / "bootstrap.json").write_text(
            json.dumps(child_environment(directory / "agent-a", "gateway", url("agent-a"))),
            encoding="utf-8",
        )
        (work / "gateway.yaml").write_text(
            yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8"
        )
        start("gateway", "gateway")

        def model_entry(model: str) -> dict | None:
            listing = call("gateway", "GET", "/v1/models", operator).json()
            for entry in listing.get("data", []):
                if entry.get("id") == model:
                    return entry
            return None

        wait(
            lambda: all(model_entry(m) is not None for m in ("tickets", "invoices", "cloudy")),
            "three decision models routable",
            seconds=45,
        )
        entry = model_entry("tickets")
        assert entry is not None
        assert entry["x_eugene_plexus"]["surfaces"] == ["decisions"], entry
        ok("the supervised kev model is discoverable and marked decisions-only")

        # --- 3: real curl, the first client --------------------------------
        request_body = json.dumps({"model": "tickets", "state": TICKET, "questions": MIXED})
        curl = subprocess.run(
            [
                "curl",
                "-s",
                url("gateway") + "/v1/systemone",
                "-H",
                f"Authorization: Bearer {operator}",
                "-H",
                "Content-Type: application/json",
                "-d",
                request_body,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert curl.returncode == 0, curl.stderr
        body = json.loads(curl.stdout)
        assert body["model"] == "tickets", body
        answers = body["answers"]
        assert answers["refunded"]["type"] == "noul"
        # The real model's judgment on an unambiguous refund transcript.
        assert answers["refunded"]["noul"] > 0.5, answers["refunded"]
        assert answers["route"]["choice"] == "billing", answers["route"]
        assert set(answers["route"]["probabilities"]) == {"billing", "shipping", "technical"}
        assert abs(sum(answers["route"]["probabilities"].values()) - 1.0) < 0.06
        assert answers["urgency"]["type"] == "score"
        assert body["usage"]["input_tokens"] > 0
        ok(
            "real curl -> real gateway -> real driver -> real kev: the refund is a "
            f"{answers['refunded']['noul']:.2f} yes routed to billing"
        )

        # --- 4: state shapes and question independence ---------------------
        for state in (
            TICKET,
            {"order": {"id": "A-1", "status": "refunded"}, "agent": "bot-7"},
            [{"role": "customer", "text": "charged twice"}, {"role": "agent", "text": "refunded"}],
        ):
            response = decide(
                operator,
                "tickets",
                {"refunded": {"type": "noul", "instructions": "Was a refund issued?"}},
                state=state,
            )
            assert response.status_code == 200, response.text
        # The same question name in separate requests is a fresh question.
        first = decide(
            operator, "tickets", {"q": {"type": "noul", "instructions": "Was a refund issued?"}},
            state=TICKET,
        ).json()["answers"]["q"]["noul"]
        second = decide(
            operator,
            "tickets",
            {"q": {"type": "noul", "instructions": "Is the customer asking about shipping?"}},
            state=TICKET,
        ).json()["answers"]["q"]["noul"]
        assert first > 0.5 and second < 0.5, (first, second)
        ok("string, object and array states all serve; a reused question id is independent")

        # --- 5: two aliases, distinguishable backends ----------------------
        response = decide(operator, "invoices", MIXED, state=TICKET)
        assert response.status_code == 200, response.text
        stub_answers = response.json()["answers"]
        # The fixture picks the LAST option where kev picked billing.
        assert stub_answers["route"]["choice"] == "technical"
        assert json.loads(call("stub-inv", "GET", "/stats").text)["served"] >= 1
        ok("a second public alias reaches its own backend, distinguishably")

        # --- 6: the doors refuse each other's models -----------------------
        chat = call(
            "gateway",
            "POST",
            "/v1/chat/completions",
            operator,
            json={"model": "tickets", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert chat.status_code == 400 and "/v1/systemone" in chat.text
        ok("a chat request naming the decision model is refused with the door's name")

        # --- 7: scopes and local-only ---------------------------------------
        scoped = call(
            "agent-a",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={"name": "B2 scoped", "limits": {"allowedModels": ["tickets"]}},
        )
        assert scoped.status_code == 201, scoped.text
        key = scoped.json()["token"]
        wait(
            lambda: decide(key, "tickets", MIXED, state=TICKET).status_code == 200,
            "scoped key admitted",
            seconds=30,
        )
        refused = decide(key, "invoices", MIXED)
        assert refused.status_code == 403, refused.text

        local_only = call(
            "agent-a",
            "POST",
            "/v1/auth/client-keys",
            operator,
            json={"name": "B2 local", "limits": {"localOnly": True}},
        )
        assert local_only.status_code == 201, local_only.text
        local_key = local_only.json()["token"]
        before = json.loads(call("stub-ext", "GET", "/stats").text)["served"]
        wait(
            lambda: decide(
                local_key,
                "tickets",
                {"q": {"type": "noul", "instructions": "?"}},
                state="x",
            ).status_code
            == 200,
            "local-only key serves the supervised local model",
            seconds=30,
        )
        denied = decide(local_key, "cloudy", {"q": {"type": "noul", "instructions": "?"}})
        assert denied.status_code == 403, denied.text
        after = json.loads(call("stub-ext", "GET", "/stats").text)["served"]
        assert after == before, "state left the machine on a local-only denial"
        ok(
            "a scoped key is refused the other model; a local-only key serves the "
            "supervised kev and is denied the external backend with zero requests to it"
        )

        # --- 8: negatives through the real chain ---------------------------
        bad = decide(
            operator,
            "tickets",
            {"q": {"type": "noul", "instructions": "?", "temperature": 1}},
        )
        assert bad.status_code == 422 and "temperature" in bad.text
        too_many = decide(
            operator,
            "invoices",
            {
                "a": {
                    "type": "choice",
                    "instructions": "?",
                    "criteria": {str(i): None for i in range(256)},
                }
            },
        )
        assert too_many.status_code == 422 and "255" in too_many.text

        def induced_502(mode: str, fragment: str) -> None:
            """One induced backend failure, circuit-breaker aware.

            The first execution of this check tripped over the gateway
            doing its job: an indeterminate 502 opens the backend's
            circuit, and the NEXT induced failure answered 503 "cooling
            down" instead of reaching the backend at all. So each
            sabotage loops until the circuit lets a request through
            (503-cooling tolerated, bounded), asserts the 502 names the
            defect, then restores health and waits for a clean 200 so
            the next sabotage starts from a closed circuit.
            """
            call("stub-inv", "POST", "/mode", json={"break": mode}).raise_for_status()
            deadline = time.perf_counter() + 30
            while True:
                response = decide(operator, "invoices", MIXED)
                if response.status_code == 502:
                    assert fragment in response.text, (fragment, response.text[:400])
                    break
                assert response.status_code == 503, (response.status_code, response.text[:400])
                assert time.perf_counter() < deadline, "circuit never let the request through"
                time.sleep(1)
            call("stub-inv", "POST", "/mode", json={"break": None}).raise_for_status()
            wait(
                lambda: decide(operator, "invoices", MIXED).status_code == 200,
                "circuit closes after health returns",
                seconds=45,
            )

        induced_502("missing_answer", "unanswered")
        induced_502("wrong_type", "malformed")
        ok(
            "protocol violations are 422 before work; a backend that leaves a question "
            "unanswered or answers out of range is a 502, never an invented decision"
        )

        # --- 9: the ambiguous timeout, and bounded work --------------------
        # The deadline binds when the routing table builds its driver
        # clients (measured in this run's sixth execution: a live PATCH
        # left the built client on its old budget and a 5 s hold answered
        # 200 in 5033 ms under a supposed 2 s limit), so the harness
        # restarts the gateway to apply it — which is also the honest
        # operator flow for this knob.
        # 5, not lower: the field's own minimum is 5, and the first
        # attempt PATCHed 2 — which the config surface rejected PER
        # FIELD inside a 200 the harness never read, leaving the file
        # without the key and the check green-looking for the wrong
        # reason. A config PATCH's status is not its verdict.
        patched = call(
            "gateway", "PATCH", "/v1/config", operator, json={"requestTimeoutSeconds": 5}
        )
        assert patched.status_code == 200, patched.text
        assert not patched.json().get("rejected"), patched.text
        stop("gateway")
        start("gateway", "gateway")
        wait(
            lambda: decide(
                operator, "invoices", {"q": {"type": "noul", "instructions": "?"}}
            ).status_code
            == 200,
            "gateway back with the short deadline",
            seconds=45,
        )
        call("stub-inv", "POST", "/mode", json={"hold": 9}).raise_for_status()
        stats_before = json.loads(call("stub-inv", "GET", "/stats").text)
        # Circuit-tolerant like the induced failures above: the breaker
        # may still be cooling from them, and a cooling 503 never reaches
        # the backend — so at most ONE attempt ever does, and it is the
        # one that times out.
        deadline = time.perf_counter() + 45
        while True:
            timed_out = decide(operator, "invoices", {"q": {"type": "noul", "instructions": "?"}})
            if timed_out.status_code == 504:
                break
            assert timed_out.status_code == 503, (timed_out.status_code, timed_out.text[:300])
            assert time.perf_counter() < deadline, "circuit never let the timeout attempt through"
            time.sleep(1)
        # Two honest 504 bodies exist and either may win the race at the
        # deadline: the decision route's own ("the outcome is uncertain
        # rather than failed") and the shared total-request-deadline
        # machinery's A6b wording ("No automatic replay ... a remote
        # provider may still have acted"). Both say the same thing —
        # nothing is silently re-decided — and the run's ninth execution
        # measured the shared one firing first.
        assert (
            "uncertain" in timed_out.text or "No automatic replay" in timed_out.text
        ), timed_out.text[:500]
        # The backend was asked ONCE — a fired deadline is never re-decided —
        # and its work runs to completion after the caller is gone.
        wait(
            lambda: json.loads(call("stub-inv", "GET", "/stats").text)["finished"]
            == stats_before["finished"] + 1,
            "the abandoned decision still finishes",
            seconds=20,
        )
        stats_after = json.loads(call("stub-inv", "GET", "/stats").text)
        assert stats_after["served"] == stats_before["served"] + 1
        call("stub-inv", "POST", "/mode", json={"hold": 0}).raise_for_status()
        assert (
            call(
                "gateway", "PATCH", "/v1/config", operator, json={"requestTimeoutSeconds": 600}
            ).status_code
            == 200
        )
        stop("gateway")
        start("gateway", "gateway")
        wait(
            lambda: decide(
                operator, "invoices", {"q": {"type": "noul", "instructions": "?"}}
            ).status_code
            == 200,
            "capacity is free again once the work actually ended",
            seconds=45,
        )
        ok(
            "a fired deadline is a 504 with an uncertain outcome, asked of exactly one "
            "backend, whose work runs to completion and only then frees capacity"
        )

        # --- 10: the single-slot ceiling ------------------------------------
        call("stub-inv", "POST", "/mode", json={"hold": 3}).raise_for_status()
        results: dict[str, httpx.Response] = {}
        # Read the counter at the LAST moment: the waits above answered
        # more requests since `stats_after`, and a stale baseline would
        # let this wait pass before the held request ever arrived — a
        # check that can pass while broken.
        held_before = json.loads(call("stub-inv", "GET", "/stats").text)["served"]

        def first_call() -> None:
            results["first"] = decide(
                operator, "invoices", {"q": {"type": "noul", "instructions": "?"}}
            )

        worker = threading.Thread(target=first_call)
        worker.start()
        wait(
            lambda: json.loads(call("stub-inv", "GET", "/stats").text)["served"] > held_before,
            "first decision reaches the held backend",
        )
        second = decide(operator, "invoices", {"q": {"type": "noul", "instructions": "?"}})
        worker.join(timeout=30)
        call("stub-inv", "POST", "/mode", json={"hold": 0}).raise_for_status()
        assert second.status_code == 503 and "concurrency ceiling" in second.text, second.text
        assert results["first"].status_code == 200
        ok("a single-slot backend is 503-not-queued while its one request is in flight")

        # --- 11: direct vs proxied on a frozen labeled set ------------------
        kev_port = None
        for runtime in call("agent-a", "GET", "/v1/runtimes", operator).json()["runtimes"]:
            if runtime["name"] == "tickets":
                kev_port = runtime.get("port")
                kev_pid = runtime.get("pid")
        assert kev_port, "runtime carries no port"
        labeled = [
            ("refund yes", TICKET, {"q": MIXED["refunded"]}, ("q", "noul", lambda v: v > 0.5)),
            (
                "refund no",
                "Customer: how do I change my shipping address?",
                {"q": MIXED["refunded"]},
                ("q", "noul", lambda v: v < 0.5),
            ),
            ("route billing", TICKET, {"q": MIXED["route"]}, ("q", "choice", "billing")),
            (
                "route billing, options reordered",
                TICKET,
                {
                    "q": {
                        "type": "choice",
                        "instructions": "Route this ticket.",
                        "criteria": {
                            "technical": "bugs",
                            "shipping": "delivery",
                            "billing": "payments",
                        },
                    }
                },
                ("q", "choice", "billing"),
            ),
            (
                "missing evidence stays uncertain",
                "Customer: hello?",
                {"q": MIXED["refunded"]},
                ("q", "noul", lambda v: 0.02 < v < 0.98),
            ),
        ]
        agreements = 0
        label_hits = 0
        direct_ms: list[float] = []
        proxied_ms: list[float] = []
        for label, state, questions, (qname, field, expect) in labeled:
            t0 = time.perf_counter()
            direct = client.post(
                f"http://127.0.0.1:{kev_port}/v1/systemone",
                json={"model": "tickets", "state": state, "questions": questions},
            ).json()["answers"][qname]
            direct_ms.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            via = decide(operator, "tickets", questions, state=state).json()["answers"][qname]
            proxied_ms.append((time.perf_counter() - t0) * 1000)
            direct_value = direct.get(field)
            via_value = via.get(field)
            same = (
                abs(direct_value - via_value) < 1e-9
                if isinstance(direct_value, float)
                else direct_value == via_value
            )
            agreements += int(same)
            hit = expect(via_value) if callable(expect) else via_value == expect
            label_hits += int(hit)
            print(
                f"     [{label}] direct={direct_value!r} via_gateway={via_value!r} "
                f"{'AGREE' if same else 'DISAGREE'} {'HIT' if hit else 'MISS'}",
                flush=True,
            )
        assert agreements == len(labeled), "the gateway changed an answer"
        ok(
            f"routing fidelity: {agreements}/{len(labeled)} identical answers direct vs "
            f"proxied; model accuracy on the frozen set {label_hits}/{len(labeled)} "
            f"(recorded, not gated); proxy overhead "
            f"{statistics.median(proxied_ms) - statistics.median(direct_ms):.0f}ms median"
        )

        # --- 12: p50/p95 and observed memory --------------------------------
        latencies = []
        for _ in range(8):
            t0 = time.perf_counter()
            assert (
                decide(
                    operator,
                    "tickets",
                    {"q": {"type": "noul", "instructions": "Was a refund issued?"}},
                    state=TICKET,
                ).status_code
                == 200
            )
            latencies.append((time.perf_counter() - t0) * 1000)
        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(len(latencies) * 0.95) - 1]
        peak = "unknown"
        if kev_pid:
            status = Path(f"/proc/{kev_pid}/status")
            if status.exists():
                for line in status.read_text().splitlines():
                    if line.startswith("VmHWM"):
                        peak = line.split(":", 1)[1].strip()
        ok(
            f"single-question p50 {p50:.0f}ms / p95 {p95:.0f}ms over 8 sequential "
            f"requests on CPU; kev peak RSS {peak}"
        )

        # --- 13: lifecycle and the offline second launch --------------------
        # Lifecycle verbs are 202 Accepted: the stop is asynchronous and
        # the status poll below is the truth.
        assert (
            call("agent-a", "POST", "/v1/runtimes/tickets/stop", operator).status_code == 202
        )
        wait(lambda: runtime_status() == "stopped", "kev stops", seconds=60)
        # PATCH takes the FULL spec, not a delta — a partial body is a
        # 422 from the schema before any handler runs.
        patched = call(
            "agent-a",
            "PATCH",
            "/v1/runtimes/tickets",
            operator,
            json={
                "name": "tickets",
                "engine": "kev",
                "modelPath": KEV_CHECKPOINT,
                "modelAlias": "tickets",
                "env": {
                    "CUDA_VISIBLE_DEVICES": "",
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                },
            },
        )
        assert patched.status_code == 200, patched.text
        relaunch = time.perf_counter()
        assert (
            call("agent-a", "POST", "/v1/runtimes/tickets/start", operator).status_code == 202
        )
        wait(lambda: runtime_status() == "ready", "offline second launch", seconds=300)
        warm_start_s = time.perf_counter() - relaunch
        wait(
            lambda: decide(
                operator,
                "tickets",
                {"q": {"type": "noul", "instructions": "Was a refund issued?"}},
                state=TICKET,
            ).status_code
            == 200,
            "routable again after the offline relaunch",
            seconds=60,
        )
        ok(
            f"stop, then a second launch with outbound access disabled "
            f"(HF_HUB_OFFLINE=1): ready from pinned local artifacts in {warm_start_s:.1f}s"
        )

        print(f"\nALL {passed} CHECKS PASSED", flush=True)
        print(
            f"measured: cold start {cold_start_s:.1f}s, offline restart {warm_start_s:.1f}s, "
            f"p50 {p50:.0f}ms, p95 {p95:.0f}ms, peak RSS {peak}",
            flush=True,
        )
    finally:
        # Stop the agent FIRST so it takes its supervised children (the
        # kev process, the companion driver) down with it.
        for name in ("agent-a", "gateway", "driver-inv", "driver-ext", "control"):
            stop(name)
        for name in list(processes):
            stop(name)
        for log in logs:
            log.close()
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, Path(args.directory), args.port)
        return
    if args.directory:
        work = Path(args.directory)
        work.mkdir(parents=True, exist_ok=True)
        exercise(work)
        return
    with tempfile.TemporaryDirectory(prefix="ep-b2-") as tmp:
        exercise(Path(tmp))


if __name__ == "__main__":
    main()
