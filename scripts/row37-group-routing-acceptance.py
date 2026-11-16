"""Row 37 acceptance: routing by role and models per permission group.

Real processes on OS-assigned loopback ports (never 8079-8083 or 8279-8283)
with temporary state, and every ambient `EUGENE_PLEXUS_*` variable cleared:
one control root, one agent enrolled with the `gateway` grant, three real
inference drivers (m1, m2, m3) in front of one counting OpenAI-compatible
fixture, and the gateway. No model, engine, installed service or provider.

The install routes `role:chat` and `role:agentic` to m3, then m1. Two groups:
G1 (models m1, m2; chat -> m2, m1) and G2 (no model list; chat -> m1). Person A
is in [G1]; person B is in [G2, G1], so B works from G2 until B chooses G1, and
G1's model list limits B whichever group B works from (call R37-SELF, Choice
3, default built). Each person signs in to an app (`app:workbench@<node>`) and
sends its key and their token, as Workbench does.

1. A asks `role:chat`: m2 answers. A's `/v1/models` lists m1, m2 and the
   roles A can use, not m3. A asks m3: 403 `model_not_allowed` naming G1.
   A asks `role:agentic`, which G1 does not route: the install's list is m3,
   m1; m3 is dropped, not tried, and m1 answers.
2. Sabotage: a second gateway whose resolution skips the person's model list
   (patched in that process before its app starts; no file is changed, so
   nothing needs restoring). Asked through it with A's token, step 1's
   `role:agentic` must be served by m3, and m3's count must rise.
3. B asks `role:chat`: m1 answers (G2's routing, the first of B's groups). B
   asks m3: 403 naming G1, though B works from G2, which sets no list. B
   chooses G1 at `/oidc/active-group`, through the agent's `/oidc` as an app
   reaches it: B's `role:chat` is m2, and m3 is still refused naming G1. A
   second change within a minute is a 429 with `Retry-After`. A person cannot
   choose a group they are not in.
4. A key with no person: the install's routing (`role:chat` is m3), and m3
   is reachable.
5. m2's driver stops: A's `role:chat` fails over to m1, inside G1's list.
6. The owner takes m1 out of G1 (and out of its chat route, which may name
   only G1's own models): A's next request for m1 is refused, with no token
   refresh, and m1 is not called.
7. The owner takes B out of G1: B's next request for m3 is served, since G2
   sets no model list (leaving a group widens at the next request).

Run with a Python that has agent, control, gateway and inference-driver
installed (CI's cross-component job has them).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml

# At module level: the fixture's routes annotate `request` with it, and with
# postponed annotations FastAPI resolves the name in this module's globals; an
# import inside the factory left it unresolved, so `request` read as a query
# parameter (a 422 for every answer).
from fastapi import Request

NODE_NAME = "r37-agent"
APP_OWNER = f"app:workbench@{NODE_NAME}"
CALLBACK = "http://127.0.0.1:9/callback"
PASSWORD = "row37 member password"
VERIFIER = "v" * 50
MODELS = ("m1", "m2", "m3")
#: The marker that tells a person's request from a driver's capability probe.
MARKER = "R37_PRIVATE_PROMPT"
#: The install's ports and the live root's (+200): never used here.
FORBIDDEN_PORTS = set(range(8079, 8084)) | set(range(8279, 8284))
PASSES: list[str] = []


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def _sabotage_gateway() -> None:
    """The sabotage: a resolution that skips the person's model list, so a
    role's list keeps models outside the person's group."""
    from eugene_plexus_gateway import routing
    from eugene_plexus_gateway.model_patterns import ModelScope

    original = routing.Resolution.restricted

    def skipped(self: Any, allowed: Any, *, local_only: bool = False) -> Any:
        if isinstance(allowed, ModelScope):
            allowed = ModelScope(allowed.key, [])
        return original(self, allowed, local_only=local_only)

    routing.Resolution.restricted = skipped  # type: ignore[method-assign]


def fixture_app() -> Any:
    from fastapi import FastAPI

    app = FastAPI()
    counts = dict.fromkeys(MODELS, 0)

    @app.get("/healthz")
    async def health() -> Any:
        return {}

    @app.get("/stats")
    async def stats() -> Any:
        return counts

    @app.get("/{model}/v1/models")
    async def models(model: str) -> Any:
        return {"data": [{"id": model, "object": "model"}]}

    @app.get("/{model}/props")
    async def props(model: str) -> Any:
        return {"default_generation_settings": {"n_ctx": 4096}}

    @app.post("/{model}/v1/{operation:path}")
    async def inference(model: str, operation: str, request: Request) -> Any:
        body = await request.json()
        if MARKER in json.dumps(body):
            counts[model] += 1
        return {
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"{model}-answered"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }

    return app


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "fixture":
        app = fixture_app()
    elif kind in MODELS:
        from eugene_plexus_inference_driver.app import create_app as driver_app
        from eugene_plexus_inference_driver.settings import Settings as DriverSettings

        bootstrap = json.loads(
            (directory / "bootstrap.json").read_text(encoding="utf-8")
        )
        app = driver_app(
            settings=DriverSettings(config_file=directory / "driver.yaml", **bootstrap)
        )
    elif kind == "control":
        from eugene_plexus_control.app import create_app as control_app
        from eugene_plexus_control.settings import Settings as ControlSettings

        app = control_app(
            ControlSettings(
                config_file=directory / "control.yaml", state_dir=directory / "state"
            )
        )
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app as agent_app
        from eugene_plexus_agent.settings import Settings as AgentSettings

        app = agent_app(
            settings=AgentSettings(
                config_file=directory / "agent.yaml",
                default_topology=False,
                bind_port=port,
            )
        )
    elif kind in ("gateway", "gateway-sabotaged"):
        if kind == "gateway-sabotaged":
            _sabotage_gateway()
        from eugene_plexus_gateway.app import create_app as gateway_app
        from eugene_plexus_gateway.settings import Settings as GatewaySettings

        bootstrap = json.loads(
            (directory / "bootstrap.json").read_text(encoding="utf-8")
        )
        app = gateway_app(
            settings=GatewaySettings(
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


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class Install:
    """The processes, their ports and one HTTP client."""

    NAMES = ("control", "agent", "fixture", *MODELS, "gateway", "gateway-sabotaged")

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.client = httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: list[Any] = []
        self.passphrase = secrets.token_urlsafe(24)
        self.ports: dict[str, int] = {}
        while len(self.ports) < len(self.NAMES):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            if port not in FORBIDDEN_PORTS and port not in self.ports.values():
                self.ports[self.NAMES[len(self.ports)]] = port
        assert not set(self.ports.values()) & FORBIDDEN_PORTS, self.ports

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def call(
        self, name: str, method: str, path: str, token: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers.update(kw.pop("headers", {}) or {})
        return self.client.request(method, self.url(name) + path, headers=headers, **kw)

    def good(
        self, name: str, method: str, path: str, token: str | None = None, **kw: Any
    ) -> Any:
        answer = self.call(name, method, path, token, **kw)
        assert answer.is_success, (name, path, answer.status_code, answer.text)
        return answer.json() if answer.content else {}

    def wait(self, check: Callable[[], bool], label: str, seconds: float = 30) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError, AssertionError):
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def write(self, name: str, filename: str, body: Any) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(body) if filename.endswith(".json") else yaml.safe_dump(body),
            encoding="utf-8",
        )

    def start(self, name: str) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        self.logs.append(log)
        # Never an ambient EUGENE_PLEXUS_* variable: install.ps1 sets one for
        # the whole account on a machine with Eugene on it.
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().startswith("EUGENE_PLEXUS_")
        }
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env["PYTHONUNBUFFERED"] = "1"
        self.processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                name,
                "--directory",
                str(work),
                "--port",
                str(self.ports[name]),
            ],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.wait(
            lambda: self.call(name, "GET", "/healthz").status_code == 200, f"{name} up"
        )

    def stop(self, name: str) -> None:
        process = self.processes.pop(name, None)
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def close(self) -> None:
        for name in reversed(list(self.processes)):
            self.stop(name)
        for log in self.logs:
            log.close()
        self.client.close()

    # --- signing in -------------------------------------------------------

    def sign_in(self, app: dict[str, Any], person: str) -> dict[str, Any]:
        """The Authorization Code flow with PKCE, as an app runs it."""
        client_id = app["client"]["clientId"]
        page = self.call(
            "control",
            "GET",
            "/oidc/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "scope": "openid profile offline_access",
                "state": "row37",
                "nonce": secrets.token_urlsafe(8),
                "code_challenge": _challenge(VERIFIER),
                "code_challenge_method": "S256",
            },
        )
        assert page.status_code == 200, page.text
        found = re.search(r'name="request" value="([^"]+)"', page.text)
        assert found, page.text
        approved = self.call(
            "control",
            "POST",
            "/oidc/authorize",
            data={"request": found.group(1), "name": person, "password": PASSWORD},
        )
        assert approved.status_code == 302, approved.text
        code = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
        exchanged = self.client.post(
            self.url("control") + "/oidc/token",
            auth=(client_id, app["clientSecret"]),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": CALLBACK,
            },
        )
        assert exchanged.status_code == 200, exchanged.text
        return dict(exchanged.json())


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def chat(
    install: Install, gateway: str, key: str, model: str, proof: str | None
) -> httpx.Response:
    headers = {"X-Eugene-Person-Token": proof} if proof else {}
    return install.call(
        gateway,
        "POST",
        "/v1/chat/completions",
        key,
        json={"model": model, "messages": [{"role": "user", "content": MARKER}]},
        headers=headers,
    )


def answered_by(answer: httpx.Response) -> str:
    assert answer.status_code == 200, (answer.status_code, answer.text)
    content = answer.json()["choices"][0]["message"]["content"]
    return str(content).removesuffix("-answered")


def refused_naming(answer: httpx.Response, model: str, group: str) -> None:
    assert answer.status_code == 403, (answer.status_code, answer.text)
    error = answer.json()["error"]
    assert error.get("code") == "model_not_allowed", error
    assert error["message"] == (
        f"Your group {group} does not include {model}. Ask the owner, or choose another model."
    ), error


def agentic_for_a(
    install: Install, gateway: str, key: str, proof: str
) -> tuple[int, str, int]:
    """Step 1's last request: `(status, the model that answered, how many
    times m3 was called for it)`."""
    before = install.good("fixture", "GET", "/stats")
    answer = chat(install, gateway, key, "role:agentic", proof)
    after = install.good("fixture", "GET", "/stats")
    who = answered_by(answer) if answer.status_code == 200 else ""
    return answer.status_code, who, after["m3"] - before["m3"]


def listed(install: Install, gateway: str, key: str, proof: str | None) -> set[str]:
    headers = {"X-Eugene-Person-Token": proof} if proof else {}
    answer = install.call(gateway, "GET", "/v1/models", key, headers=headers)
    assert answer.status_code == 200, answer.text
    return {m["id"] for m in answer.json()["data"]}


def exercise(directory: Path) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    install = Install(directory)
    try:
        # ---------------------------------------------------------------- #
        # The install: a root, an enrolled agent, three drivers, the gateway
        # ---------------------------------------------------------------- #
        install.start("control")
        install.good(
            "control",
            "POST",
            "/v1/auth/initialize",
            json={"passphrase": install.passphrase},
        )
        owner = install.good(
            "control", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )["sessionToken"]
        install.write(
            "agent",
            "agent.yaml",
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "advertiseUrl": install.url("agent"),
                "securityMode": "prompt_on_startup",
                "components": [],
            },
        )
        install.start("agent")
        standalone = install.good(
            "agent",
            "POST",
            "/v1/auth/initialize",
            json={"passphrase": install.passphrase},
        )["sessionToken"]
        join = install.good(
            "control",
            "POST",
            "/v1/nodes/join-token",
            owner,
            json={"grants": ["gateway"]},
        )
        install.good(
            "agent",
            "POST",
            "/v1/node/enroll",
            standalone,
            json={
                "controlUrl": install.url("control"),
                "token": join["token"],
                "name": NODE_NAME,
            },
        )
        operator = install.good(
            "agent", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )["sessionToken"]
        store = NodeIdentityStore(directory / "agent" / "node.yaml")
        store.load()
        trust = NodeTrust(store, directory / "agent" / "trust_bundle.json")
        trust.load()
        assert trust.enrolled, "the agent did not enroll"

        def bootstrap(sub: str) -> dict[str, Any]:
            token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
            return {
                "agent_url": install.url("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        install.start("fixture")
        for model in MODELS:
            install.write(model, "bootstrap.json", bootstrap("inference-driver"))
            install.write(
                model,
                "driver.yaml",
                {
                    "provider": "openai_compat_custom",
                    "modelId": model,
                    "baseUrl": install.url("fixture") + "/" + model,
                    "backendLocality": "local",
                },
            )
            install.start(model)
            install.good(
                "agent",
                "POST",
                "/v1/components",
                operator,
                json={
                    "name": f"{model}-driver",
                    "kind": "inference-driver",
                    "url": install.url(model),
                },
            )
        slots = [
            {"model": "role:chat", "targets": ["m3", "m1"]},
            {"model": "role:agentic", "targets": ["m3", "m1"]},
        ]
        for gateway in ("gateway", "gateway-sabotaged"):
            install.write(gateway, "bootstrap.json", bootstrap("gateway"))
            install.write(
                gateway,
                "gateway.yaml",
                {"routingRefreshSeconds": 3600, "modelSlots": slots},
            )
        install.start("gateway")

        # The app, its key, a key with no person, two groups and two people.
        app = install.call(
            "control",
            "POST",
            "/v1/oidc/clients",
            owner,
            json={"name": "Workbench", "owner": APP_OWNER, "redirectUris": [CALLBACK]},
        )
        assert app.status_code == 201, app.text
        app_json = app.json()
        client_id = app_json["client"]["clientId"]
        key = install.good(
            "control",
            "POST",
            "/v1/auth/client-keys",
            owner,
            json={"name": APP_OWNER, "limits": {"requestsPerMinute": 1000}},
        )["token"]
        plain = install.good(
            "control",
            "POST",
            "/v1/auth/client-keys",
            owner,
            json={"name": "Open WebUI", "limits": {"requestsPerMinute": 1000}},
        )["token"]
        groups: dict[str, dict[str, Any]] = {}
        for name, models, chat_list in (
            ("G1", ["m1", "m2"], ["m2", "m1"]),
            ("G2", None, ["m1"]),
        ):
            made = install.call(
                "control",
                "POST",
                "/v1/permission-groups",
                owner,
                json={
                    "name": name,
                    "apps": [client_id],
                    "policies": {
                        "allowedModels": models,
                        "roleRouting": {"chat": chat_list},
                    },
                },
            )
            assert made.status_code == 201, made.text
            assert made.json()["policies"]["allowedModels"] == models, made.text
            groups[name] = made.json()
        g1, g2 = groups["G1"]["id"], groups["G2"]["id"]
        people: dict[str, dict[str, Any]] = {}
        for name, member_of in (("A", [g1]), ("B", [g2, g1])):
            made = install.call(
                "control",
                "POST",
                "/v1/people",
                owner,
                json={"name": name, "password": PASSWORD, "groups": member_of},
            )
            assert made.status_code == 201, made.text
            people[name] = made.json()
        assert people["B"]["policiesInEffect"]["activeGroup"] == g2, people["B"]
        signed = {name: install.sign_in(app_json, name) for name in ("A", "B")}
        proof_a, proof_b = signed["A"]["access_token"], signed["B"]["access_token"]
        install.wait(
            lambda: {"m1", "m2", "m3"} <= listed(install, "gateway", plain, None),
            "the gateway knows the keys and routes m1, m2 and m3",
        )
        ok(
            "install: root, enrolled agent, drivers m1-m3, gateway; G1, G2; A in G1, B in G2 then G1"
        )

        # ---------------------------------------------------------------- #
        # 1. Person A, in G1
        # ---------------------------------------------------------------- #
        assert answered_by(chat(install, "gateway", key, "role:chat", proof_a)) == "m2"
        ok("step 1: A's role:chat follows G1's routing: m2 answers")
        mine = listed(install, "gateway", key, proof_a)
        assert mine == {"m1", "m2", "role:chat", "role:agentic"}, mine
        ok("step 1: A's /v1/models lists m1, m2 and the roles A can use, not m3")
        before = install.good("fixture", "GET", "/stats")
        refused_naming(chat(install, "gateway", key, "m3", proof_a), "m3", "G1")
        assert install.good("fixture", "GET", "/stats")["m3"] == before["m3"]
        ok(
            "step 1: A asking m3 is refused 403 model_not_allowed, naming G1; m3 is not called"
        )
        assert agentic_for_a(install, "gateway", key, proof_a) == (200, "m1", 0)
        ok(
            "step 1: A's role:agentic (not routed by G1) uses the install's m3, m1: m3 dropped, m1 answers"
        )

        # ---------------------------------------------------------------- #
        # 2. Sabotage: a gateway that skips the person's model list
        # ---------------------------------------------------------------- #
        install.start("gateway-sabotaged")
        # Ready for a person's request, as the sabotaged one is: A's key and
        # token, and the role A asks for.
        install.wait(
            lambda: (
                "role:agentic" in listed(install, "gateway-sabotaged", key, proof_a)
            ),
            "the sabotaged gateway serves A's role:agentic",
        )
        sabotaged = agentic_for_a(install, "gateway-sabotaged", key, proof_a)
        assert sabotaged == (200, "m3", 1), (
            f"sabotage NOT caught as expected: {sabotaged}, not (200, 'm3', 1)"
        )
        ok(
            "sabotage caught: a gateway that skips G1's models serves A's role:agentic from m3"
        )
        install.stop("gateway-sabotaged")

        # ---------------------------------------------------------------- #
        # 3. Person B, in G2 then G1
        # ---------------------------------------------------------------- #
        assert answered_by(chat(install, "gateway", key, "role:chat", proof_b)) == "m1"
        refused_naming(chat(install, "gateway", key, "m3", proof_b), "m3", "G1")
        ok(
            "step 3: B works from G2: role:chat is m1 (G2's route); m3 is refused naming G1,"
            " whose list applies though B works from G2 (R37-SELF)"
        )
        through_agent = install.call(
            "agent", "POST", "/oidc/active-group", proof_b, json={"group": g1}
        )
        assert through_agent.status_code == 200, through_agent.text
        assert through_agent.json()["inEffect"] == g1, through_agent.text
        assert answered_by(chat(install, "gateway", key, "role:chat", proof_b)) == "m2"
        refused_naming(chat(install, "gateway", key, "m3", proof_b), "m3", "G1")
        ok(
            "step 3: B chooses G1 through the agent's /oidc: role:chat is m2, m3 is refused naming G1"
        )
        again = install.call(
            "agent", "POST", "/oidc/active-group", proof_b, json={"group": g2}
        )
        assert again.status_code == 429, again.text
        assert 1 <= int(again.headers["Retry-After"]) <= 60, again.headers
        ok("step 3: a second change within a minute is refused 429 with Retry-After")
        elsewhere = install.good(
            "control",
            "POST",
            "/v1/permission-groups",
            owner,
            json={"name": "Elsewhere"},
        )
        not_mine = install.call(
            "agent",
            "POST",
            "/oidc/active-group",
            proof_b,
            json={"group": elsewhere["id"]},
        )
        assert not_mine.status_code == 403, not_mine.text
        assert not_mine.json()["error"] == "not_a_member", not_mine.text
        assert answered_by(chat(install, "gateway", key, "role:chat", proof_b)) == "m2"
        ok("step 3: B cannot choose a group B is not in; B still works from G1")

        # ---------------------------------------------------------------- #
        # 4. A key with no person
        # ---------------------------------------------------------------- #
        assert answered_by(chat(install, "gateway", plain, "role:chat", None)) == "m3"
        assert answered_by(chat(install, "gateway", plain, "m3", None)) == "m3"
        assert {"m1", "m2", "m3"} <= listed(install, "gateway", plain, None)
        ok(
            "step 4: a key with no person keeps the install's routing (m3) and reaches m3"
        )

        # ---------------------------------------------------------------- #
        # 5. m2 stops: A fails over inside G1's list
        # ---------------------------------------------------------------- #
        install.stop("m2")
        before = install.good("fixture", "GET", "/stats")
        assert answered_by(chat(install, "gateway", key, "role:chat", proof_a)) == "m1"
        assert install.good("fixture", "GET", "/stats")["m3"] == before["m3"]
        ok(
            "step 5: with m2's driver stopped, A's role:chat fails over to m1, never to m3"
        )

        # ---------------------------------------------------------------- #
        # 6. The owner takes m1 out of G1
        # ---------------------------------------------------------------- #
        edited = install.call(
            "control",
            "PUT",
            f"/v1/permission-groups/{g1}",
            owner,
            json={
                "name": "G1",
                "apps": [client_id],
                "policies": {"allowedModels": ["m2"], "roleRouting": {"chat": ["m2"]}},
            },
        )
        assert edited.status_code == 200, edited.text
        before = install.good("fixture", "GET", "/stats")
        refused_naming(chat(install, "gateway", key, "m1", proof_a), "m1", "G1")
        assert install.good("fixture", "GET", "/stats")["m1"] == before["m1"]
        assert "m1" not in listed(install, "gateway", key, proof_a)
        ok(
            "step 6: m1 taken out of G1 is refused at A's next request, with no token refresh"
        )

        # ---------------------------------------------------------------- #
        # 7. B leaves G1: G2 sets no list, so m3 is B's at the next request
        # ---------------------------------------------------------------- #
        refused_naming(chat(install, "gateway", key, "m3", proof_b), "m3", "G1")
        left = install.call(
            "control",
            "PATCH",
            f"/v1/people/{people['B']['id']}",
            owner,
            json={"groups": [g2]},
        )
        assert left.status_code == 200, left.text
        assert answered_by(chat(install, "gateway", key, "m3", proof_b)) == "m3"
        ok("step 7: B taken out of G1 reaches m3 at the next request (G2 sets no list)")
    finally:
        install.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return 0
    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    with tempfile.TemporaryDirectory(
        prefix="ep-row37-", ignore_cleanup_errors=True
    ) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory)
        except BaseException:
            for log in sorted(directory.glob("**/process.log")):
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[
                    -30:
                ]
                print(f"--- {log.parent.name} ---", *tail, sep="\n")
            raise
    print(f"{len(PASSES)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
