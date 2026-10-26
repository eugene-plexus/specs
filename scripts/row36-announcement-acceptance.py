"""Row 36 acceptance: Machines says why a machine's address was refused.

Real processes on ephemeral loopback ports with temporary state: one control
root and one enrolled agent, `agent-a`. Every `EUGENE_PLEXUS_*` variable is
cleared. The agent's retry timers are shortened in the agent's own process
(a 15-minute wait is not a test).

1. The agent's configured address becomes one on the open internet (a name
   that never resolves, so no packet leaves): the root refuses it, and
   `GET /v1/nodes` shows `open_internet`, in the root's words, naming both
   addresses.
2. A second machine record holds an address; the agent announces it:
   `anothers_address`, naming that machine.
3. An announcement with a signature that does not verify: the count rises,
   no refusal changes, and nothing it carried is shown.
4. Re-enrollment is the way to confirm the move (R36-ACCEPT, Troy
   2026-10-22; there is no accept call): the refusal is cleared, and the
   agent's next attempts are "unchanged" and append nothing to the root's log.
5. A refusal never grows the root's log, and a root restart forgets it: the
   agent says again, and the refusal is back within one agent retry.

Run with a Python that has agent and control installed (CI's cross-component
job has both).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

# Nothing from the calling shell reaches a process.
for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]

PASSES: list[str] = []

#: An address on the open internet that never resolves (RFC 6761): the root
#: classes a hostname as public, and no packet leaves the runner.
PUBLIC_NAME = "agent-a.invalid"
#: Another machine's address, in the documentation range: private, never dialled
#: for a purpose here.
OTHER_ADDRESS = "http://192.0.2.50:59079"


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {message}", flush=True)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app as control_app
        from eugene_plexus_control.settings import Settings as ControlSettings

        app = control_app(
            ControlSettings(config_file=directory / "control.yaml", state_dir=directory / "state")
        )
    else:
        from eugene_plexus_agent import enrollment
        from eugene_plexus_agent.app import create_app as agent_app
        from eugene_plexus_agent.settings import Settings as AgentSettings

        # The agent's own timers, shortened in its own process: a refused
        # address is tried again every 3 s, not every 15 minutes, and a
        # refusal that may work later (a 409) every second or two.
        enrollment.REFUSED_RETRY_SECONDS = 3.0
        enrollment.ADDRESS_RECHECK_SECONDS = 1.0
        enrollment.ANNOUNCE_RETRY_FIRST_SECONDS = 1.0
        enrollment.ANNOUNCE_RETRY_MAX_SECONDS = 3.0
        app = agent_app(
            settings=AgentSettings(
                config_file=directory / "agent.yaml", default_topology=False, bind_port=port
            )
        )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def exercise(directory: Path) -> None:
    names = ("control", "agent-a")
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = {name: sock.getsockname()[1] for name, sock in zip(names, sockets, strict=True)}
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs: list[Any] = []
    client = httpx.Client(timeout=15, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name: str, method: str, path: str, token: str | None = None, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return client.request(method, url(name) + path, headers=headers, **kw)

    def wait(check: Any, label: str, seconds: float = 45) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, PermissionError, KeyError):
                pass
            time.sleep(0.2)
        raise AssertionError("timed out: " + label)

    def start(name: str) -> None:
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
                name,
                "--directory",
                str(work),
                "--port",
                str(ports[name]),
            ],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, f"{name} healthy")

    def stop(name: str) -> None:
        process = processes.pop(name)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def login_root() -> str:
        token: list[str] = []

        def attempt() -> bool:
            response = call("control", "POST", "/v1/auth/login", json={"passphrase": passphrase})
            if response.status_code != 200:
                return False
            token.append(str(response.json()["sessionToken"]))
            return True

        wait(attempt, "the root signs the operator in")
        return token[0]

    def write_agent_config(advertise: str) -> None:
        (directory / "agent-a" / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": advertise,
                    "securityMode": "prompt_on_startup",
                    "components": [],
                }
            ),
            encoding="utf-8",
        )

    def agent_identity() -> dict[str, Any]:
        loaded = yaml.safe_load((directory / "agent-a" / "node.yaml").read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        return loaded

    def agent_sequence() -> int:
        return int(agent_identity().get("advertiseSequence") or 0)

    def node(session: str, name: str = "agent-a") -> dict[str, Any]:
        response = call("control", "GET", f"/v1/nodes/{name}", session)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def applied_index(session: str) -> int:
        response = call("control", "GET", "/v1/control/status", session)
        assert response.status_code == 200, response.text
        return int(response.json()["appliedIndex"])

    def refusal_is(session: str, reason: str) -> bool:
        shown = node(session)["announcementRefused"]
        return bool(shown) and shown["reason"] == reason

    def join_secret(session: str) -> str:
        response = call("control", "POST", "/v1/nodes/join-token", session, json={})
        assert response.status_code in (200, 201), response.text
        return str(response.json()["token"]).partition(".")[0]

    agent_address = f"http://127.0.0.1:{ports['agent-a']}"
    public_address = f"http://{PUBLIC_NAME}:{ports['agent-a']}"

    try:
        # ---------------------------------------------------------------- #
        # An install: a root and an enrolled agent, at a loopback address
        # ---------------------------------------------------------------- #
        start("control")
        initialized = call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        assert initialized.status_code == 204, initialized.text
        root = login_root()

        write_agent_config(agent_address)
        start("agent-a")
        first = call("agent-a", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
        assert first.status_code == 200, first.text
        enrolled = call(
            "agent-a",
            "POST",
            "/v1/node/enroll",
            str(first.json()["sessionToken"]),
            json={
                "controlUrl": url("control"),
                "token": str(
                    call("control", "POST", "/v1/nodes/join-token", root, json={}).json()["token"]
                ),
                "name": "agent-a",
            },
        )
        assert enrolled.status_code == 200, enrolled.text
        recorded = node(root)
        assert recorded["url"].rstrip("/") == agent_address, recorded["url"]
        assert recorded["announcementRefused"] is None
        assert recorded["unverifiedAnnouncements"] is None
        ok("agent-a is enrolled at a loopback address and nothing has been refused")

        # ---------------------------------------------------------------- #
        # 1. A move onto the open internet
        # ---------------------------------------------------------------- #
        stop("agent-a")
        write_agent_config(public_address)
        start("agent-a")
        wait(lambda: refusal_is(root, "open_internet"), "the root says it refused the move")
        shown = node(root)["announcementRefused"]
        assert shown["title"] == "Address puts this node on the open internet", shown
        assert agent_address in shown["detail"] and PUBLIC_NAME in shown["detail"], shown
        assert "re-enroll" in shown["detail"].lower(), shown
        assert PUBLIC_NAME in shown["announcedUrl"], shown
        assert node(root)["url"].rstrip("/") == agent_address
        listed = {n["name"]: n for n in call("control", "GET", "/v1/nodes", root).json()["nodes"]}
        assert listed["agent-a"]["announcementRefused"] == shown
        ok("a move onto the open internet is shown as open_internet, naming both addresses")

        # ---------------------------------------------------------------- #
        # 2. Another machine's address
        # ---------------------------------------------------------------- #
        other = call(
            "control",
            "POST",
            "/v1/nodes/enroll",
            json={
                "token": join_secret(root),
                "name": "other",
                "publicKey": base64.b64encode(os.urandom(32)).decode("ascii"),
                "signingPublicKey": base64.b64encode(os.urandom(32)).decode("ascii"),
                "tokenPublicKey": base64.b64encode(os.urandom(32)).decode("ascii"),
                "url": OTHER_ADDRESS,
            },
        )
        assert other.status_code == 201, other.text
        stop("agent-a")
        write_agent_config(OTHER_ADDRESS)
        start("agent-a")
        wait(lambda: refusal_is(root, "anothers_address"), "the root says whose address it is")
        shown = node(root)["announcementRefused"]
        assert "other" in shown["detail"] and "192.0.2.50" in shown["detail"], shown
        assert node(root)["url"].rstrip("/") == agent_address
        ok("an address another machine holds is shown as anothers_address, naming that machine")

        # ---------------------------------------------------------------- #
        # 3. A signature that does not verify
        # ---------------------------------------------------------------- #
        before = node(root)
        assert before["unverifiedAnnouncements"] is None, before
        forged = call(
            "control",
            "PATCH",
            "/v1/nodes/agent-a",
            json={
                "url": "http://forged.invalid:1/SECRET-WORDS",
                "sequence": 999999,
                "signature": base64.b64encode(bytes(64)).decode("ascii"),
            },
        )
        assert forged.status_code == 401, forged.text
        after = node(root)
        assert after["unverifiedAnnouncements"]["count"] == 1, after["unverifiedAnnouncements"]
        assert after["unverifiedAnnouncements"]["lastAt"]
        assert after["announcementRefused"]["reason"] == "anothers_address"
        assert after["url"] == before["url"]
        assert "SECRET-WORDS" not in json.dumps(after)
        assert "SECRET-WORDS" not in call("control", "GET", "/v1/nodes", root).text
        ok("a forged announcement raises the count and changes nothing else; its text is not shown")

        # ---------------------------------------------------------------- #
        # 5 (first half). A refusal is an observation, not a log entry
        # ---------------------------------------------------------------- #
        index = applied_index(root)
        start_sequence = agent_sequence()
        wait(lambda: agent_sequence() >= start_sequence + 3, "the agent announced three more times")
        assert applied_index(root) == index, "a refusal appended to the replicated log"
        assert refusal_is(root, "anothers_address")
        ok("the agent asks again and again, and the root's log does not move")

        # ---------------------------------------------------------------- #
        # 4. Re-enrollment confirms a move onto the open internet
        # ---------------------------------------------------------------- #
        stop("agent-a")
        write_agent_config(public_address)
        start("agent-a")
        wait(lambda: refusal_is(root, "open_internet"), "the open-internet refusal is back")
        identity = agent_identity()
        current = node(root)
        machine = {}
        if current.get("machineUrl") and current.get("tlsPins"):
            machine = {"machineUrl": current["machineUrl"], "tlsPin": current["tlsPins"][0]}
        reenrolled = call(
            "control",
            "POST",
            "/v1/nodes/enroll",
            json={
                "token": join_secret(root),
                "name": "agent-a",
                "publicKey": identity["publicKey"],
                "signingPublicKey": identity["signingPublicKey"],
                "tokenPublicKey": _token_public(identity["tokenPrivateKey"]),
                "url": public_address,
                **machine,
            },
        )
        assert reenrolled.status_code == 201, reenrolled.text
        confirmed = node(root)
        assert confirmed["url"].rstrip("/") == public_address, confirmed["url"]
        assert confirmed["announcementRefused"] is None, confirmed["announcementRefused"]
        assert confirmed["unverifiedAnnouncements"] is None
        ok("re-enrolling the machine at that address confirms the move and clears what was refused")

        # The agent's next attempts are "unchanged": nothing is refused again
        # and nothing is appended.
        base_sequence = agent_sequence()
        wait(lambda: agent_sequence() >= base_sequence + 1, "the agent announced after enrollment")
        settled_index = applied_index(root)
        wait(lambda: agent_sequence() >= base_sequence + 4, "the agent announced three times more")
        assert applied_index(root) == settled_index, "an announcement changed the record"
        final = node(root)
        assert final["announcementRefused"] is None, final["announcementRefused"]
        assert final["url"].rstrip("/") == public_address
        ok("the agent's next attempts after re-enrollment are unchanged: no refusal, no log entry")

        # ---------------------------------------------------------------- #
        # 5 (second half). A root restart forgets, and the agent says again
        # ---------------------------------------------------------------- #
        stop("agent-a")
        write_agent_config(OTHER_ADDRESS)
        start("agent-a")
        wait(lambda: refusal_is(root, "anothers_address"), "the refusal is there before the restart")
        stop("agent-a")
        stop("control")
        start("control")
        root = login_root()
        assert node(root)["announcementRefused"] is None, "a refusal survived a root restart"
        assert node(root)["unverifiedAnnouncements"] is None
        ok("a root restart forgets what it refused: it was never in the log")

        start("agent-a")
        wait(
            lambda: refusal_is(root, "anothers_address"),
            "the refusal is back within one agent retry",
            seconds=30,
        )
        ok("the agent says again, and the refusal is back within one retry")
    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()
        client.close()


def _token_public(private: str) -> str:
    from eugene_plexus_agent import tokens

    return tokens.public_b64(tokens.load_private(private))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return 0
    with tempfile.TemporaryDirectory(prefix="ep-row36-", ignore_cleanup_errors=True) as tmp:
        directory = Path(tmp)
        try:
            exercise(directory)
        except BaseException:
            for log in sorted(directory.glob("*/process.log")):
                tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                print(f"--- {log.parent.name} ---", *tail, sep="\n")
            raise
    print(f"{len(PASSES)} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
