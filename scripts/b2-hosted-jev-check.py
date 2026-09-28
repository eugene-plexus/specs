"""B2 hosted Jev: the driver's `typesafe` provider against a REAL hosted Jev.

B2 shipped hosted Jev fixture-only, "pending TypeSafe credentials". Since
then OpenRouter serves Jev at `https://openrouter.ai/api/v1/systemone`,
the same pinned protocol, with an OpenRouter key — so the provider can be
exercised for real by pointing its `baseUrl` at OpenRouter. Nothing else
in the chain changes: a real control root, an enrolled agent, a real
gateway routing `POST /v1/systemone`, and two drivers on the `typesafe`
provider — one with the key, one with a deliberately invalid key, to see
what a real provider's 401 looks like at the gateway.

The key is read from `EP_KEYS` (default: the provider-keys file this
machine keeps) and written only into the throwaway driver's own config,
which is where the provider reads `apiKey`; the directory is deleted at
teardown. It is never printed, and check 9 scans every process log and
every response body for it.

Run it from a venv holding all four components (B2's is `~/b2/ep-venv`
in WSL, editable from the local repos):

    cd /mnt/d/py/eugene-plexus/specs/scripts && ~/b2/ep-venv/bin/python b2-hosted-jev-check.py

Ephemeral ports, ambient EUGENE_PLEXUS_* cleared, teardown by pid.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / "b2-decision-acceptance.py"  # its `--serve <kind>` starts each process
UPSTREAM_MODEL = os.environ.get("EP_JEV_MODEL", "typesafe/jev-1.13")
KEY_FILES = [os.environ.get("EP_KEYS", ""), "/mnt/c/Users/troyc/.eugene-plexus-secrets/provider-keys.env",
             "C:/Users/troyc/.eugene-plexus-secrets/provider-keys.env"]

TICKET = (
    "Customer: I was charged twice for order A-1 and I want my money back. "
    "Agent: I found the duplicate charge and issued a full refund just now."
)
MIXED = {
    "refunded": {"type": "noul", "instructions": "Was a refund issued?",
                 "criteria": {"true": "The agent says a refund was issued.", "false": "No refund was issued."}},
    "route": {"type": "choice", "instructions": "Route this ticket.",
              "criteria": {"billing": "payments", "shipping": "delivery", "technical": "bugs"}},
    "urgency": {"type": "score", "instructions": "How urgent is this ticket now?",
                "criteria": ["It can wait.", "Someone should look this week.", "A customer is blocked now."]},
}


def openrouter_key() -> str:
    for f in KEY_FILES:
        if f and Path(f).is_file():
            for line in Path(f).read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if k.strip() == "OPENROUTER_API_KEY" and v.strip():
                    return v.strip().strip('"').strip("'")
    raise SystemExit(f"no OPENROUTER_API_KEY in any of {[f for f in KEY_FILES if f]}")


def child_environment(agent_dir: Path, sub: str, agent_url: str) -> dict:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(agent_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, agent_dir / BUNDLE_FILE)
    trust.load()
    assert trust.enrolled and trust.bundle is not None, f"{agent_dir.name} holds no bundle"
    token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
    return {"trust_bundle_file": str(trust.bundle_path), "trust_authority": trust.authority,
            "auth_recipient": trust.recipient, "service_token": token, "agent_url": agent_url}


def exercise(directory: Path) -> None:
    key = openrouter_key()
    passed = 0
    responses: list[str] = []

    def ok(label: str) -> None:
        nonlocal passed
        passed += 1
        print(f"PASS {passed:02d} {label}", flush=True)

    names = ("control", "agent-a", "gateway", "driver-jev", "driver-badkey", "driver-badchat")
    socks = [socket.socket() for _ in names]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = {n: s.getsockname()[1] for n, s in zip(names, socks)}
    for s in socks:
        s.close()
    processes: dict[str, subprocess.Popen] = {}
    logs = []
    client = httpx.Client(timeout=60, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name: str, method: str, path: str, token: str | None = None, **kw):
        r = client.request(method, url(name) + path,
                           headers={"Authorization": f"Bearer {token}"} if token else {}, **kw)
        responses.append(r.text)
        return r

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
            [sys.executable, str(LAUNCHER), "--serve", kind, "--directory", str(work), "--port", str(ports[name])],
            cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name + " healthz")

    def login(name: str) -> str:
        deadline = time.perf_counter() + 20
        while True:
            r = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
            if r.status_code != 503 or time.perf_counter() > deadline:
                break
            time.sleep(0.25)
        assert r.status_code == 200, (name, r.text)
        return r.json()["sessionToken"]

    def decide(token: str, model: str, questions: dict, state: object = TICKET):
        return call("gateway", "POST", "/v1/systemone", token,
                    json={"model": model, "state": state, "questions": questions})

    try:
        # --- the install: a root, an enrolled agent -----------------------
        start("control", "control")
        assert call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).status_code == 204
        root = login("control")
        work = directory / "agent-a"
        work.mkdir(exist_ok=True)
        (work / "agent.yaml").write_text(yaml.safe_dump(
            {"firstRunComplete": True, "advertiseUrl": url("agent-a"),
             "securityMode": "prompt_on_startup", "components": []}), encoding="utf-8")
        start("agent-a", "agent")
        assert call("agent-a", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).status_code == 200
        local_op = login("agent-a")
        join = call("control", "POST", "/v1/nodes/join-token", root, json={"grants": ["gateway"]})
        assert join.status_code in (200, 201), join.text
        enrolled = call("agent-a", "POST", "/v1/node/enroll", local_op,
                        json={"controlUrl": url("control"), "token": join.json()["token"], "name": "agent-a"})
        assert enrolled.status_code == 200, enrolled.text
        operator = login("agent-a")

        # --- two drivers on the `typesafe` provider -------------------------
        def driver(name: str, alias: str, api_key: str, provider: str = "typesafe",
                   upstream: str = UPSTREAM_MODEL) -> None:
            w = directory / name
            w.mkdir(exist_ok=True)
            (w / "driver.yaml").write_text(yaml.safe_dump({
                "provider": provider, "baseUrl": "https://openrouter.ai/api", "apiKey": api_key,
                "modelId": alias, "upstreamModelId": upstream}), encoding="utf-8")
            (w / "bootstrap.json").write_text(json.dumps(
                child_environment(directory / "agent-a", "inference-driver", url("agent-a"))), encoding="utf-8")
            start(name, "driver")
            assert call("agent-a", "POST", "/v1/components", operator,
                        json={"name": name, "kind": "inference-driver", "url": url(name)}).status_code == 201

        driver("driver-jev", "jev", key)
        driver("driver-badkey", "jev-badkey", "sk-or-v1-" + "0" * 64)
        # The chat door with the same kind of bad key: the commoner case.
        driver("driver-badchat", "badchat", "sk-or-v1-" + "1" * 64, provider="openrouter",
               upstream="openai/gpt-4o-mini")
        info = call("driver-jev", "GET", "/v1/info", operator).json()
        (model,) = info["models"]  # since P1, capabilities are per model
        assert info["provider"] == "typesafe" and info["locality"] == "external", info
        assert model["id"] == "jev" and model["upstreamId"] == UPSTREAM_MODEL, model
        assert model["surfaces"] == ["decisions"], model
        kinds = model["capabilities"]["decision"]["kinds"]
        assert set(kinds) == {"noul", "choice", "score"}, model
        ok(f"the typesafe provider starts against OpenRouter: locality external, `jev` -> "
           f"{model['upstreamId']}, decisions only ({', '.join(kinds)})")

        w = directory / "gateway"
        w.mkdir(exist_ok=True)
        (w / "bootstrap.json").write_text(json.dumps(
            child_environment(directory / "agent-a", "gateway", url("agent-a"))), encoding="utf-8")
        (w / "gateway.yaml").write_text(yaml.safe_dump({"routingRefreshSeconds": 1}), encoding="utf-8")
        start("gateway", "gateway")

        def entry(model: str) -> dict | None:
            for e in call("gateway", "GET", "/v1/models", operator).json().get("data", []):
                if e.get("id") == model:
                    return e
            return None

        wait(lambda: all(entry(m) is not None for m in ("jev", "jev-badkey", "badchat")), "all routable", 45)
        e = entry("jev")
        assert e["x_eugene_plexus"]["surfaces"] == ["decisions"], e
        ok(f"the gateway lists `jev` as decisions-only ({json.dumps(e['x_eugene_plexus'])[:160]})")

        # --- 3: a real hosted decision through the whole chain -------------
        r = decide(operator, "jev", MIXED)
        assert r.status_code == 200, r.text
        body = r.json()
        a = body["answers"]
        assert body["model"] == "jev", body
        assert a["refunded"]["type"] == "noul" and a["refunded"]["noul"] > 0.5, a
        assert a["route"]["choice"] == "billing", a
        assert abs(sum(a["route"]["probabilities"].values()) - 1.0) < 0.06, a
        assert 0 <= a["urgency"]["score"] <= 2, a
        assert body["usage"]["input_tokens"] > 0, body
        ok(f"real hosted Jev through gateway and driver: refund {a['refunded']['noul']:.2f} yes, routed "
           f"{a['route']['choice']}, urgency {a['urgency']['score']:.2f}, "
           f"{body['usage']['input_tokens']} input tokens")
        # gateway.yaml (SystemOneResponse.model) says the backend's revision
        # is "surfaced in `x_eugene_plexus`". The driver records it
        # (`reportedModel`); the gateway drops it. Reported, not asserted,
        # until the contract gains the field or the sentence is changed.
        provenance = json.dumps(body.get("x_eugene_plexus") or {})
        if "jev-1.13" not in provenance:
            print(f"     FINDING: x_eugene_plexus carries no upstream revision: {provenance}", flush=True)

        # --- 4: the three state shapes, and latency -------------------------
        lat = []
        for state in (TICKET, {"order": {"id": "A-1", "status": "refunded"}, "agent": "bot-7"},
                      [{"role": "customer", "text": "charged twice"}, {"role": "agent", "text": "refunded"}]):
            for _ in range(2):
                t0 = time.perf_counter()
                r = decide(operator, "jev", {"refunded": MIXED["refunded"]}, state=state)
                lat.append((time.perf_counter() - t0) * 1000)
                assert r.status_code == 200, r.text
                assert r.json()["answers"]["refunded"]["noul"] > 0.5, r.text
        ok(f"string, object and array states all decided; end-to-end p50 {statistics.median(lat):.0f} ms, "
           f"max {max(lat):.0f} ms over {len(lat)} calls")

        # --- 5: the doors refuse each other's models -------------------------
        chat = call("gateway", "POST", "/v1/chat/completions", operator,
                    json={"model": "jev", "messages": [{"role": "user", "content": "hi"}]})
        assert chat.status_code == 400 and "/v1/systemone" in chat.text, chat.text
        ok("a chat request naming hosted Jev is refused with the decision door's name")

        # --- 6: client keys: an ordinary one decides, a local-only one is refused
        normal = call("agent-a", "POST", "/v1/auth/client-keys", operator, json={"name": "hosted jev"})
        assert normal.status_code == 201, normal.text
        nk = normal.json()["token"]
        wait(lambda: decide(nk, "jev", {"refunded": MIXED["refunded"]}).status_code == 200, "client key admitted", 30)
        local = call("agent-a", "POST", "/v1/auth/client-keys", operator,
                     json={"name": "local only", "limits": {"localOnly": True}})
        assert local.status_code == 201, local.text
        lk = local.json()["token"]
        denied = None
        deadline = time.perf_counter() + 30
        while time.perf_counter() < deadline:
            denied = decide(lk, "jev", {"refunded": MIXED["refunded"]})
            if denied.status_code != 401:
                break
            time.sleep(0.5)
        assert denied is not None and denied.status_code == 403, denied.text
        ok("a client key decides on hosted Jev; a local-only key is refused (403), since the provider is external")

        # --- 7: malformed questions never reach the provider ----------------
        bad = decide(operator, "jev", {"q": {"type": "noul", "instructions": "?", "temperature": 1}})
        assert bad.status_code == 422 and "temperature" in bad.text, bad.text
        ok("an unknown question field is a 422 at the gateway")

        # --- 8 and 9: a key the provider refuses, on both doors -------------
        # FOUND by this script's first run (2026-09-28): the refusal reached
        # the caller as a 400 `invalid_request_error`, the caller's fault
        # for a key only the operator holds. Fixed the same day (driver
        # `#backend-credential-refused`, gateway `upstream_auth_error`).
        def refused_as_ours(r: httpx.Response, driver_name: str) -> str:
            assert r.status_code == 502, r.text
            error = r.json()["error"]
            assert error["type"] == "upstream_auth_error", error
            assert driver_name in error["message"] and f"Config -> {driver_name}" in error["message"], error
            assert "401" in error["message"] and "Nothing is wrong with the request" in error["message"], error
            return error["message"]

        message = refused_as_ours(decide(operator, "jev-badkey", {"refunded": MIXED["refunded"]}), "driver-badkey")
        print(f"     ({message[:230]})", flush=True)
        ok("the decision door: a key OpenRouter refuses is our 502 upstream_auth_error, naming the driver")
        chat = call("gateway", "POST", "/v1/chat/completions", operator,
                    json={"model": "badchat", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8})
        refused_as_ours(chat, "driver-badchat")
        ok("the chat door: the same, for an OpenRouter chat driver with a bad key")

        # --- 10: the key never left the driver's config ----------------------
        for f in logs:
            f.flush()
        leaks = sum(p.read_text(encoding="utf-8", errors="replace").count(key)
                    for p in directory.glob("*/process.log"))
        leaks += sum(t.count(key) for t in responses)
        assert leaks == 0, f"the key appears {leaks} times in logs or responses"
        ok(f"the key appears in no process log and no response ({len(responses)} responses scanned)")
        print(f"ALL {passed} CHECKS PASSED", flush=True)
    finally:
        for name in list(processes):
            p = processes.pop(name)
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        for f in logs:
            f.close()


def main() -> None:
    # `--directory D` keeps the work (and the key in D/driver-*/driver.yaml)
    # for debugging; delete D afterwards. The default is a temp directory.
    if sys.argv[1:2] == ["--directory"]:
        work = Path(sys.argv[2])
        work.mkdir(parents=True, exist_ok=True)
        exercise(work)
        return
    with tempfile.TemporaryDirectory(prefix="ep-b2-hosted-") as tmp:
        exercise(Path(tmp))


if __name__ == "__main__":
    main()
