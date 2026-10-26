"""Row 70 acceptance: policies per permission group.

Real processes on ephemeral loopback ports with temporary state, never the
default ports, and every ambient `EUGENE_PLEXUS_*` variable cleared: one
control root, and one agent enrolled with the `gateway` grant the way the
wizard joins the control host. No model, no engine, no installed service.

1. Two people, A and B, and two groups: G1 (background, 70%) and G2
   (interactive, 85%). A is in G1; B is in G1 and G2.
2. With an app's client key and each person's sign-in token, the root's
   admission check says `background` for A and `interactive` for B; asked
   through the agent, as the gateway asks, it says the same. A key with no
   person carries no band, and a caller cannot name its own band.
3. Signing in to the app, the ID token and /oidc/userinfo carry
   `eugene_groups` and the effective values (70% for A, 85% for B).
   Workbench reading those claims is `row70c-workbench-groups-acceptance.py`.
4. Workbench's group memory servers: `row70c-workbench-groups-acceptance.py`,
   which installs Workbench at the commit under test.
5. B is taken out of G2: after a token refresh, B's band is `background`
   and B's percent is 70.
6. Sabotage: a second root whose `effective_policies` takes the first
   group's value instead of the most generous. Step 2 for B must fail there.
   The sabotage is made in that root's process only (the function is
   replaced before the app starts); no file is changed, so nothing needs
   restoring.

Run with a Python that has agent and control installed (CI's cross-component
job has them).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml

PASSES: list[str] = []
CALLBACK = "http://127.0.0.1:9/callback"
APP_OWNER = "app:workbench@agent-a"
PASSWORD = "row70 member password"
VERIFIER = "v" * 50
#: The ports this script must never use (the install's defaults).
DEFAULT_PORTS = range(8079, 8084)


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


# --------------------------------------------------------------------------- #
# The processes
# --------------------------------------------------------------------------- #


def _first_group_only(state: Any, person: dict[str, Any]) -> dict[str, Any]:
    """The sabotage: each policy from the first of the person's groups that
    sets it, not the most generous of all of them."""
    groups = [
        state.permission_groups[g]
        for g in person.get("groups") or []
        if g in state.permission_groups
    ]
    found: dict[str, Any] = {}
    for policy in ("queueBand", "summaryContextPercent"):
        for group in groups:
            value = (group.get("policies") or {}).get(policy)
            if value is not None:
                found[policy] = value
                break
    return found


def serve(kind: str, directory: Path, port: int, sabotage: bool) -> None:
    import uvicorn

    if kind.startswith("control"):
        from eugene_plexus_control import permissions
        from eugene_plexus_control.app import create_app as control_app
        from eugene_plexus_control.settings import Settings as ControlSettings

        if sabotage:
            permissions.effective_policies = _first_group_only
        app = control_app(
            ControlSettings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    elif kind.startswith("agent"):
        from eugene_plexus_agent.app import create_app as agent_app
        from eugene_plexus_agent.settings import Settings as AgentSettings

        app = agent_app(
            settings=AgentSettings(
                config_file=directory / "agent.yaml", default_topology=False, bind_port=port
            )
        )
    else:
        raise SystemExit(f"unknown kind {kind}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def gateway_token(agent_dir: Path) -> str:
    """The service token an agent hands its gateway at spawn."""
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import BUNDLE_FILE, NodeTrust

    store = NodeIdentityStore(agent_dir / "node.yaml")
    store.load()
    trust = NodeTrust(store, agent_dir / BUNDLE_FILE)
    trust.load()
    token, _ = trust.mint_service(sub="gateway", audience=trust.recipient)
    return str(token)


def claims_of(token: str) -> dict[str, Any]:
    import jwt

    return dict(jwt.decode(token, options={"verify_signature": False}))


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@contextmanager
def must_fail(label: str) -> Iterator[None]:
    """The block must raise `AssertionError`: a check the sabotage breaks."""
    try:
        yield
    except AssertionError as caught:
        ok(f"sabotage caught: {label} ({caught})")
        return
    raise AssertionError(f"sabotage NOT caught: {label} passed against a broken rule")


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


class Install:
    """One root (and, for the main run, one enrolled agent) and its client."""

    def __init__(self, directory: Path, names: tuple[str, ...]) -> None:
        self.directory = directory
        self.client = httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.logs: list[Any] = []
        self.passphrase = secrets.token_urlsafe(24)
        sockets = [socket.socket() for _ in names]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        self.ports = {
            name: sock.getsockname()[1] for name, sock in zip(names, sockets, strict=True)
        }
        for sock in sockets:
            sock.close()
        assert not set(self.ports.values()) & set(DEFAULT_PORTS), self.ports

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def call(
        self, name: str, method: str, path: str, token: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers.update(kw.pop("headers", {}))
        return self.client.request(method, self.url(name) + path, headers=headers, **kw)

    def wait(self, check: Callable[[], bool], label: str, seconds: float = 30) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, PermissionError):
                pass
            time.sleep(0.1)
        raise AssertionError("timed out: " + label)

    def start(self, name: str, *, sabotage: bool = False) -> None:
        work = self.directory / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        self.logs.append(log)
        # Never an ambient EUGENE_PLEXUS_* variable: install.ps1 sets one for
        # the whole account on a machine with Eugene on it.
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--serve",
            name,
            "--directory",
            str(work),
            "--port",
            str(self.ports[name]),
        ]
        if sabotage:
            command.append("--sabotage")
        self.processes[name] = subprocess.Popen(
            command,
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.wait(lambda: self.call(name, "GET", "/healthz").status_code == 200, f"{name} healthy")

    def close(self) -> None:
        for process in self.processes.values():
            process.terminate()
        for process in self.processes.values():
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in self.logs:
            log.close()
        self.client.close()

    # --- the root -------------------------------------------------------

    def open_root(self, name: str) -> str:
        initialized = self.call(
            name, "POST", "/v1/auth/initialize", json={"passphrase": self.passphrase}
        )
        assert initialized.status_code == 204, initialized.text
        login = self.call(name, "POST", "/v1/auth/login", json={"passphrase": self.passphrase})
        assert login.status_code == 200, login.text
        return str(login.json()["sessionToken"])

    def sign_in(self, root: str, app: dict[str, Any], person: str) -> dict[str, Any]:
        """The Authorization Code flow with PKCE, as an app runs it."""
        client_id = app["client"]["clientId"]
        page = self.call(
            root,
            "GET",
            "/oidc/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": CALLBACK,
                "scope": "openid profile offline_access",
                "state": "row70",
                "nonce": secrets.token_urlsafe(8),
                "code_challenge": _challenge(VERIFIER),
                "code_challenge_method": "S256",
            },
        )
        assert page.status_code == 200, page.text
        found = re.search(r'name="request" value="([^"]+)"', page.text)
        assert found, page.text
        approved = self.call(
            root,
            "POST",
            "/oidc/authorize",
            data={"request": found.group(1), "name": person, "password": PASSWORD},
        )
        assert approved.status_code == 302, approved.text
        code = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
        exchanged = self.client.post(
            self.url(root) + "/oidc/token",
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

    def refresh(self, root: str, app: dict[str, Any], signed: dict[str, Any]) -> dict[str, Any]:
        answer = self.client.post(
            self.url(root) + "/oidc/token",
            auth=(app["client"]["clientId"], app["clientSecret"]),
            data={"grant_type": "refresh_token", "refresh_token": signed["refresh_token"]},
        )
        assert answer.status_code == 200, answer.text
        return {**dict(answer.json()), "refresh_token": signed["refresh_token"]}

    def userinfo(self, root: str, signed: dict[str, Any]) -> dict[str, Any]:
        answer = self.call(root, "GET", "/oidc/userinfo", signed["access_token"])
        assert answer.status_code == 200, answer.text
        return dict(answer.json())


def build(install: Install, root: str, session: str) -> dict[str, Any]:
    """Step 1: the app, its key, two groups and two people."""
    app = install.call(
        root,
        "POST",
        "/v1/oidc/clients",
        session,
        json={"name": "Workbench", "owner": APP_OWNER, "redirectUris": [CALLBACK]},
    )
    assert app.status_code == 201, app.text
    client_id = app.json()["client"]["clientId"]
    key = install.call(
        root,
        "POST",
        "/v1/auth/client-keys",
        session,
        json={"name": APP_OWNER, "limits": {"allowedModels": ["row70-model"]}},
    )
    assert key.status_code == 201, key.text
    groups = {}
    for name, band, percent in (("G1", "background", 70), ("G2", "interactive", 85)):
        made = install.call(
            root,
            "POST",
            "/v1/permission-groups",
            session,
            json={
                "name": name,
                "apps": [client_id],
                "policies": {"queueBand": band, "summaryContextPercent": percent},
            },
        )
        assert made.status_code == 201, made.text
        assert made.json()["policies"] == {"queueBand": band, "summaryContextPercent": percent}
        groups[name] = made.json()["id"]
    people = {}
    for name, member_of in (("A", ["G1"]), ("B", ["G1", "G2"])):
        made = install.call(
            root,
            "POST",
            "/v1/people",
            session,
            json={"name": name, "password": PASSWORD, "groups": [groups[g] for g in member_of]},
        )
        assert made.status_code == 201, made.text
        people[name] = made.json()
    return {
        "app": app.json(),
        "key": key.json()["key"]["id"],
        "groups": groups,
        "people": people,
    }


def band_at_root(
    install: Install, root: str, session: str, key: str, token: str | None, action: str = "check"
) -> httpx.Response:
    body: dict[str, Any] = {"keyId": key, "requestId": secrets.token_hex(6), "action": action}
    if token is not None:
        body["personToken"] = token
    if action == "acquire":
        body["model"] = "row70-model"
    return install.call(root, "POST", "/v1/auth/client-keys/admission", session, json=body)


def check_bands(observed: dict[str, str | None]) -> None:
    """Step 2's assertion, kept apart so the sabotage run can expect it to fail."""
    assert observed["A"] == "background", f"A's band is {observed['A']!r}, not background"
    assert observed["B"] == "interactive", f"B's band is {observed['B']!r}, not interactive"


def observe_bands(
    install: Install, root: str, session: str, built: dict[str, Any], signed: dict[str, Any]
) -> dict[str, str | None]:
    observed: dict[str, str | None] = {}
    for name in ("A", "B"):
        answer = band_at_root(install, root, session, built["key"], signed[name]["access_token"])
        assert answer.status_code == 200, answer.text
        assert answer.json()["personId"] == built["people"][name]["id"], answer.text
        observed[name] = answer.json().get("queueBand")
    return observed


def exercise(directory: Path) -> None:
    install = Install(directory, ("control", "agent-a"))
    try:
        # ---------------------------------------------------------------- #
        # 1. A root, an agent with the gateway grant, two groups, two people
        # ---------------------------------------------------------------- #
        install.start("control")
        session = install.open_root("control")
        built = build(install, "control", session)
        work = directory / "agent-a"
        work.mkdir(exist_ok=True)
        (work / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": install.url("agent-a"),
                    "securityMode": "prompt_on_startup",
                    "components": [],
                }
            ),
            encoding="utf-8",
        )
        install.start("agent-a")
        initialized = install.call(
            "agent-a", "POST", "/v1/auth/initialize", json={"passphrase": install.passphrase}
        )
        assert initialized.status_code == 200, initialized.text
        join = install.call(
            "control", "POST", "/v1/nodes/join-token", session, json={"grants": ["gateway"]}
        )
        assert join.status_code in (200, 201), join.text
        enrolled = install.call(
            "agent-a",
            "POST",
            "/v1/node/enroll",
            initialized.json()["sessionToken"],
            json={
                "controlUrl": install.url("control"),
                "token": join.json()["token"],
                "name": "agent-a",
            },
        )
        assert enrolled.status_code == 200, enrolled.text
        ok("step 1: G1 background + 70%, G2 interactive + 85%; A in G1, B in G1 and G2")

        listed = {
            p["name"]: p
            for p in install.call("control", "GET", "/v1/people", session).json()["people"]
        }
        assert listed["A"]["policiesInEffect"]["queueBand"] == "background"
        assert listed["B"]["policiesInEffect"] == {
            "queueBand": "interactive",
            "summaryContextPercent": 85,
            "setBy": {
                "queueBand": [built["groups"]["G2"]],
                "summaryContextPercent": [built["groups"]["G2"]],
            },
        }
        ok("step 1: the People list shows each person's policies in effect and who set them")

        # ---------------------------------------------------------------- #
        # 2. The admission check carries each verified person's band
        # ---------------------------------------------------------------- #
        signed = {name: install.sign_in("control", built["app"], name) for name in ("A", "B")}
        bands = observe_bands(install, "control", session, built, signed)
        check_bands(bands)
        ok("step 2: the root's admission check says background for A and interactive for B")

        acquired = band_at_root(
            install, "control", session, built["key"], signed["B"]["access_token"], "acquire"
        )
        assert acquired.status_code == 200, acquired.text
        assert acquired.json()["queueBand"] == "interactive"
        ok("step 2: an acquisition for B carries interactive too")

        install.wait(lambda: (work / "trust_bundle.json").is_file(), "agent-a holds the bundle")
        gateway = gateway_token(work)
        forwarded = {}
        for name in ("A", "B"):
            answer = install.call(
                "agent-a",
                "POST",
                "/v1/auth/client-keys/admission",
                gateway,
                json={
                    "keyId": built["key"],
                    "requestId": secrets.token_hex(6),
                    "action": "check",
                    "personToken": signed[name]["access_token"],
                },
            )
            assert answer.status_code == 200, answer.text
            forwarded[name] = answer.json().get("queueBand")
        check_bands(forwarded)
        ok("step 2: asked through the agent with the gateway's token, the bands are the same")

        plain_key = install.call(
            "control", "POST", "/v1/auth/client-keys", session, json={"name": "Open WebUI"}
        )
        assert plain_key.status_code == 201, plain_key.text
        no_person = band_at_root(install, "control", session, plain_key.json()["key"]["id"], None)
        assert no_person.status_code == 200, no_person.text
        assert "queueBand" not in no_person.json() and "personId" not in no_person.json()
        forged = install.call(
            "control",
            "POST",
            "/v1/auth/client-keys/admission",
            session,
            json={
                "keyId": built["key"],
                "requestId": "forged",
                "action": "check",
                "personToken": signed["A"]["access_token"],
                "queueBand": "interactive",
            },
        )
        assert forged.status_code == 422, forged.text
        ok("step 2: a key with no person carries no band; a caller cannot name its own band")

        # ---------------------------------------------------------------- #
        # 3. The sign-in claims carry the groups and the effective values
        # ---------------------------------------------------------------- #
        g1, g2 = built["groups"]["G1"], built["groups"]["G2"]
        expected = {
            "A": ([{"id": g1, "name": "G1"}], "background", 70),
            "B": ([{"id": g1, "name": "G1"}, {"id": g2, "name": "G2"}], "interactive", 85),
        }
        for name, (groups, band, percent) in expected.items():
            for claims in (
                claims_of(signed[name]["id_token"]),
                install.userinfo("control", signed[name]),
            ):
                assert claims["eugene_groups"] == groups, (name, claims)
                assert claims["eugene_policies"]["queueBand"] == band, (name, claims)
                assert claims["eugene_policies"]["summaryContextPercent"] == percent, (name, claims)
        ok("step 3: the ID token and userinfo carry the groups, and 70% for A and 85% for B")
        # Workbench reading them: row70c-workbench-groups-acceptance.py, step 2.

        # ---------------------------------------------------------------- #
        # 4. A group memory server in Workbench Settings: row70c-workbench-groups-
        # acceptance.py, step 3, which installs Workbench at the commit under test.
        # ---------------------------------------------------------------- #

        # ---------------------------------------------------------------- #
        # 5. Taken out of G2: after a refresh, B is background and 70%
        # ---------------------------------------------------------------- #
        moved = install.call(
            "control",
            "PATCH",
            f"/v1/people/{built['people']['B']['id']}",
            session,
            json={"groups": [g1]},
        )
        assert moved.status_code == 200, moved.text
        refreshed = install.refresh("control", built["app"], signed["B"])
        claims = claims_of(refreshed["id_token"])
        assert claims["eugene_groups"] == [{"id": g1, "name": "G1"}], claims
        assert claims["eugene_policies"]["summaryContextPercent"] == 70, claims
        assert (
            install.userinfo("control", refreshed)["eugene_policies"]["queueBand"] == "background"
        )
        for token in (refreshed["access_token"], signed["B"]["access_token"]):
            answer = band_at_root(install, "control", session, built["key"], token)
            assert answer.status_code == 200, answer.text
            assert answer.json()["queueBand"] == "background", answer.text
        ok("step 5: B taken out of G2: after a refresh B's band is background and percent 70")
    finally:
        install.close()

    # -------------------------------------------------------------------- #
    # 6. Sabotage: a root that takes the first group's value
    # -------------------------------------------------------------------- #
    sabotaged = Install(directory / "sabotage", ("control-sabotaged",))
    (directory / "sabotage").mkdir(exist_ok=True)
    try:
        sabotaged.start("control-sabotaged", sabotage=True)
        session = sabotaged.open_root("control-sabotaged")
        built = build(sabotaged, "control-sabotaged", session)
        signed = {
            name: sabotaged.sign_in("control-sabotaged", built["app"], name) for name in ("A", "B")
        }
        observed = observe_bands(sabotaged, "control-sabotaged", session, built, signed)
        with must_fail("step 2 for B against effective_policies that takes the first group"):
            check_bands(observed)
    finally:
        sabotaged.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--sabotage", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port, args.sabotage)
        return 0
    with tempfile.TemporaryDirectory(prefix="ep-row70-", ignore_cleanup_errors=True) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory)
        except BaseException:
            for log in sorted(directory.glob("**/process.log")):
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                print(f"--- {log.parent.name} ---", *tail, sep="\n")
            raise
    print(f"{len(PASSES)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
