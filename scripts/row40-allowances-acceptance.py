"""Row 40 acceptance: usage and money allowances, counted across two gateways.

Real processes on OS-assigned loopback ports (never 8079-8083), with all state
in a temporary folder and no `EUGENE_PLEXUS_*` variable reaching a child: one
control root, one agent enrolled with the `gateway` grant, the a6 fixture
backend behind three drivers (`local` is local, `cloud` is external, `unknown`
is neither), and two gateways, A and B. Every answer uses 7 tokens in and 3
out. Linux and Windows. Do not run this against a live install.

1. A key with 100 tokens a day sends 10 requests, alternating A and B: all
   served. The 11th is refused on A and on B, as OpenAI's 429
   `insufficient_quota`, with the root's sentence and `Retry-After`; the
   root's total for the key is 100 tokens in 10 requests, as the fixture
   counted them.
2. A person in a group with $0.01 a month, through an app key and their own
   sign-in: the owner prices `cloud` at $500 a million tokens, so two
   requests spend the group's cent (one on A, one on B), and the third is
   refused naming the group, its $0.01 and its reset. `local` is still
   served (no price set: free); `unknown` has no price at all and is
   refused under the money limit. Once the owner gives `local` a rate, it
   is refused too.
3. The root's totals for the group and the person match the fixture's
   count of what was served.
4. Sabotage (`--sabotage`): gateway B is restarted from a copy of the
   gateway's `admission.py` that sends no usage with its releases, so the
   root counts only gateway A's. Step 1 run again must fail. The file is
   restored from the copy, and its hash checked against the one read before.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml

HERE = Path(__file__).resolve().parent
NODE = "tower"
APP_OWNER = f"app:workbench@{NODE}"
CALLBACK = "http://127.0.0.1:9/callback"
PASSWORD = "row40 member password"
VERIFIER = "v" * 50
#: The a6 fixture's usage for every answer.
TOKENS_PER_ANSWER = 10
#: $500 a million tokens: ten tokens cost $0.005, so two spend $0.01.
CLOUD_RATE = 500_000_000
#: What the sabotage removes: gateway B's releases then carry no usage.
SABOTAGE_FROM = 'if action == "release" and self.usage is not None:'
SABOTAGE_TO = 'if action == "release" and self.usage is not None and False:'
PASSES: list[str] = []


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def must_fail(label: str) -> Iterator[None]:
    """The block must raise `AssertionError`: the check the sabotage breaks."""
    try:
        yield
    except AssertionError as caught:
        ok(f"sabotage caught: {label} ({str(caught)[:200]})")
        return
    raise AssertionError(f"sabotage NOT caught: {label} passed with gateway B uncounted")


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class Install:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        names = (
            "control",
            "agent",
            "fixture",
            "local",
            "cloud",
            "unknown",
            "gateway-a",
            "gateway-b",
        )
        sockets = [socket.socket() for _ in names]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        self.ports = {n: s.getsockname()[1] for n, s in zip(names, sockets, strict=True)}
        for sock in sockets:
            sock.close()
        assert not set(self.ports.values()) & set(range(8079, 8084)), self.ports
        assert not set(self.ports.values()) & set(range(8279, 8284)), self.ports
        self.client = httpx.Client(timeout=30, trust_env=False, follow_redirects=False)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: list[Any] = []
        self.passphrase = secrets.token_urlsafe(24)

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def call(self, name: str, method: str, path: str, token: str | None = None, **kw: Any) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers.update(kw.pop("headers", {}) or {})
        return self.client.request(method, self.url(name) + path, headers=headers, **kw)

    def good(self, name: str, method: str, path: str, token: str | None = None, **kw: Any) -> Any:
        answer = self.call(name, method, path, token, **kw)
        assert answer.is_success, (name, path, answer.status_code, answer.text)
        return answer.json() if answer.content else {}

    def write(self, name: str, filename: str, data: Any) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith(".json") else yaml.safe_dump(data),
            encoding="utf-8",
        )

    def wait(self, check: Callable[[], Any], label: str, seconds: float = 30) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError):
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def start(self, name: str) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        self.logs.append(log)
        # Never an ambient EUGENE_PLEXUS_* variable: install.ps1 sets one for
        # the whole account on a machine with Eugene on it.
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        kind = "gateway" if name.startswith("gateway") else name
        self.processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--serve",
                kind,
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
        self.wait(lambda: self.call(name, "GET", "/healthz").status_code == 200, f"{name} up")

    def stop(self, name: str) -> None:
        process = self.processes.pop(name, None)
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def close(self) -> None:
        for name in list(self.processes):
            self.stop(name)
        for log in self.logs:
            log.close()
        self.client.close()

    def sign_in(self, app: dict[str, Any], person: str) -> str:
        """The Authorization Code flow with PKCE, as an app runs it; the access token."""
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
                "state": "row40",
                "nonce": secrets.token_urlsafe(8),
                "code_challenge": _challenge(VERIFIER),
                "code_challenge_method": "S256",
            },
        )
        assert page.status_code == 200, page.text
        found = re.search(r'name="request" value="([^"]+)"', page.text)
        assert found, page.text[:400]
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
        return str(exchanged.json()["access_token"])


def serve_fixture_or_component(kind: str, directory: Path, port: int) -> None:
    load("a6-local-only-acceptance.py").serve(kind, directory, port)


def exercise(directory: Path, sabotage: bool) -> None:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    for name in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
        del os.environ[name]
    install = Install(directory)
    try:
        # --- the install ---------------------------------------------------
        install.start("control")
        install.good(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
        )
        root = install.good(
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
        install.good(
            "agent", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
        )
        standalone = install.good(
            "agent", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )["sessionToken"]
        join = install.good(
            "control", "POST", "/v1/nodes/join-token", root, json={"grants": ["gateway"]}
        )
        install.good(
            "agent",
            "POST",
            "/v1/node/enroll",
            standalone,
            json={"controlUrl": install.url("control"), "token": join["token"], "name": NODE},
        )
        operator = install.good(
            "agent", "POST", "/v1/auth/login", json={"passphrase": install.passphrase}
        )["sessionToken"]
        store = NodeIdentityStore(directory / "agent" / "node.yaml")
        store.load()
        trust = NodeTrust(store, directory / "agent" / "trust_bundle.json")
        trust.load()

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
        for model, locality in (("local", "local"), ("cloud", "external"), ("unknown", "unknown")):
            install.write(model, "bootstrap.json", bootstrap("inference-driver"))
            install.write(
                model,
                "driver.yaml",
                {
                    "provider": "openai_compat_custom",
                    "modelId": model,
                    "baseUrl": install.url("fixture") + "/" + model,
                    "backendLocality": locality,
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

        def start_gateway(name: str) -> None:
            install.write(name, "bootstrap.json", bootstrap("gateway"))
            install.write(name, "gateway.yaml", {"routingRefreshSeconds": 1})
            install.start(name)

        for name in ("gateway-a", "gateway-b"):
            start_gateway(name)

        def mint(name: str, **limits: Any) -> str:
            made = install.good(
                "agent",
                "POST",
                "/v1/auth/client-keys",
                operator,
                json={"name": name, "limits": {"requestsPerMinute": 1000, **limits}},
            )
            return str(made["token"])

        def chat(gateway: str, token: str, model: str, person: str | None = None) -> Any:
            headers = {"X-Eugene-Person-Token": person} if person else {}
            return install.call(
                gateway,
                "POST",
                "/v1/chat/completions",
                token,
                headers=headers,
                json={
                    "model": model,
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "A6_PRIVATE row 40"}],
                },
            )

        def served() -> dict[str, int]:
            return dict(install.good("fixture", "GET", "/stats"))

        warm = mint("Warm-up")
        for gateway in ("gateway-a", "gateway-b"):
            install.wait(
                lambda g=gateway: (
                    {"local", "cloud", "unknown"}
                    <= {m["id"] for m in install.call(g, "GET", "/v1/models", warm).json()["data"]}
                ),
                f"{gateway} routes the three models",
                seconds=45,
            )

        def usage_of(kind: str, ident: str) -> dict[str, Any]:
            report = install.good("control", "GET", "/v1/usage", root)
            return next(s for s in report["subjects"] if s["kind"] == kind and s["id"] == ident)

        def key_id(name: str) -> str:
            keys = install.good("control", "GET", "/v1/auth/client-keys", root)["keys"]
            return str(next(k for k in keys if k["name"] == name)["id"])

        def two_gateway_day(name: str) -> None:
            """Step 1: 100 tokens a day, ten requests across A and B, the 11th refused."""
            token = mint(name, tokensPerDay=100)
            before = served()["local"]
            for n in range(10):
                answer = chat("gateway-a" if n % 2 == 0 else "gateway-b", token, "local")
                assert answer.status_code == 200, (n, answer.status_code, answer.text)
            # The release reaches the root as the answer's end goes out; a moment for it.
            install.wait(
                lambda: usage_of("key", key_id(name))["day"]["requests"] >= 10,
                "the root counted both gateways' requests",
                seconds=10,
            )
            for gateway in ("gateway-a", "gateway-b"):
                refused = chat(gateway, token, "local")
                assert refused.status_code == 429, (gateway, refused.status_code, refused.text)
                error = refused.json()["error"]
                assert error["type"] == "insufficient_quota" == error["code"], error
                assert error["message"].startswith("This key used 100 of its 100 tokens for "), (
                    error
                )
                assert "It resets at 00:00 UTC on" in error["message"], error
                assert int(refused.headers["Retry-After"]) >= 1
                assert refused.headers["X-Eugene-Refusal-Reason"] == "insufficient_quota"
            day = usage_of("key", key_id(name))["day"]
            assert (day["requests"], day["tokens"]) == (10, 10 * TOKENS_PER_ANSWER), day
            assert served()["local"] - before == 10, "the fixture served exactly ten"

        two_gateway_day("Daily")
        ok(
            "1. 100 tokens a day across two gateways: ten served, the 11th refused on A and B as insufficient_quota"
        )

        # --- 2: a group's cent, priced and unpriced models -----------------------
        app = install.good(
            "control",
            "POST",
            "/v1/oidc/clients",
            root,
            json={"name": "Workbench", "owner": APP_OWNER, "redirectUris": [CALLBACK]},
        )
        # The app's own key, made at the root as an app's install makes it.
        app_key = install.good(
            "control",
            "POST",
            "/v1/auth/client-keys",
            root,
            json={"name": APP_OWNER, "limits": {"requestsPerMinute": 1000}},
        )["token"]
        sales = install.good(
            "control",
            "POST",
            "/v1/permission-groups",
            root,
            json={
                "name": "Sales",
                "apps": [app["client"]["clientId"]],
                "policies": {"costPerMonthMicros": 10_000},
            },
        )
        assert sales["policies"]["costPerMonthMicros"] == 10_000, sales
        pat = install.good(
            "control",
            "POST",
            "/v1/people",
            root,
            json={"name": "Pat", "password": PASSWORD, "groups": [sales["id"]]},
        )
        person = install.sign_in(app, "Pat")
        install.good(
            "control",
            "PUT",
            "/v1/usage/prices",
            root,
            json={
                "model": "cloud",
                "price": {
                    "inputPerMillionMicros": CLOUD_RATE,
                    "outputPerMillionMicros": CLOUD_RATE,
                },
            },
        )
        # A model with no price at all is refused while the cent is unspent: its cost
        # cannot be counted. (Once the cent is spent, the spent allowance is the cause.)
        unpriced = chat("gateway-a", app_key, "unknown", person)
        assert unpriced.status_code == 429, unpriced.text
        assert unpriced.json()["error"]["message"].startswith(
            "No price is set for unknown, so a money limit cannot allow it."
        ), unpriced.text
        before = served()
        for gateway in ("gateway-a", "gateway-b"):
            answer = chat(gateway, app_key, "cloud", person)
            assert answer.status_code == 200, (gateway, answer.text)
        install.wait(
            lambda: usage_of("group", sales["id"])["month"]["requests"] >= 2,
            "the root counted the group's two requests",
            seconds=10,
        )
        refused = chat("gateway-a", app_key, "cloud", person)
        assert refused.status_code == 429, refused.text
        now = datetime.now(UTC)
        upcoming = calendar.month_name[now.month % 12 + 1]
        message = refused.json()["error"]["message"]
        assert message == (
            f"Your group Sales used $0.01 of its $0.01 for {calendar.month_name[now.month]}. "
            f"It resets on 1 {upcoming}."
        ), message
        assert refused.json()["error"]["code"] == "insufficient_quota"
        for gateway in ("gateway-b", "gateway-a"):
            free = chat(gateway, app_key, "local", person)
            assert free.status_code == 200, ("a local model with no price is free", free.text)
        install.good(
            "control",
            "PUT",
            "/v1/usage/prices",
            root,
            json={
                "model": "local",
                "price": {"inputPerMillionMicros": 1_000_000, "outputPerMillionMicros": 1_000_000},
            },
        )
        priced_local = chat("gateway-b", app_key, "local", person)
        assert priced_local.status_code == 429, (
            "local is refused once it has a rate",
            priced_local.text,
        )
        ok(
            "2. a group's $0.01: priced cloud refused after two, local free until it has a rate, unpriced refused"
        )

        # --- 3: the root's totals are the fixture's --------------------------------
        after = served()
        assert (after["cloud"] - before["cloud"], after["local"] - before["local"]) == (2, 2), (
            before,
            after,
        )
        assert after["unknown"] == before["unknown"], "the unpriced model was never asked"
        for kind, ident in (("group", sales["id"]), ("person", pat["id"])):
            month = usage_of(kind, ident)["month"]
            assert month["requests"] == 4 and month["tokens"] == 4 * TOKENS_PER_ANSWER, month
            assert month["costUsd"] == "0.010000000000", month
            by_model = {m["model"]: m for m in month["models"]}
            assert by_model["cloud"]["costUsd"] == "0.010000000000", by_model
            assert by_model["local"]["costUsd"] == "0.000000000000", by_model
        spent = usage_of("group", sales["id"])["allowances"][0]
        assert spent["kind"] == "costPerMonth" and spent["spent"] is True, spent
        ok("3. the root's totals for the group and the person are what the fixture served")

        # --- 4: sabotage ------------------------------------------------------------
        if sabotage:
            import eugene_plexus_gateway.admission as admission_module

            target = Path(admission_module.__file__)
            original = target.read_bytes()
            baseline = hashlib.sha256(original).hexdigest()
            assert original.count(SABOTAGE_FROM.encode()) == 1, "the sabotage no longer applies"
            backup = directory / "admission.py.copy"
            shutil.copyfile(target, backup)
            try:
                target.write_bytes(original.replace(SABOTAGE_FROM.encode(), SABOTAGE_TO.encode()))
                install.stop("gateway-b")
                start_gateway("gateway-b")
            finally:
                # Gateway B has read the broken copy; the file is restored at once.
                shutil.copyfile(backup, target)
            assert hashlib.sha256(target.read_bytes()).hexdigest() == baseline, "not restored"
            install.wait(
                lambda: (
                    "local"
                    in {
                        m["id"]
                        for m in install.call("gateway-b", "GET", "/v1/models", warm).json()["data"]
                    }
                ),
                "the sabotaged gateway-b routes local",
                seconds=45,
            )
            with must_fail("step 1 with gateway B's releases uncounted"):
                two_gateway_day("Daily, gateway B uncounted")
            ok("4. admission.py restored from its copy, hash as before")

        expected = 4 if sabotage else 3
        assert len(PASSES) == expected + (1 if sabotage else 0), PASSES
        print(f"ALL {len(PASSES)} CHECKS PASSED", flush=True)
    finally:
        install.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--sabotage", action="store_true")
    args, _ = parser.parse_known_args()
    if args.serve:
        serve_fixture_or_component(args.serve, args.directory, args.port)
        return 0
    root = HERE.parents[1] / ".codex-tmp"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="row40-", dir=root, ignore_cleanup_errors=True) as tmp:
        try:
            exercise(Path(tmp), args.sabotage)
        except BaseException:
            for log in sorted(Path(tmp).glob("*/process.log")):
                print(
                    f"--- {log.parent.name}",
                    log.read_text(encoding="utf-8", errors="replace")[-6000:],
                )
            raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
