"""CX6: removing a machine from the install, live (control `DELETE /v1/nodes/{name}`).

Proves, with real processes from the installed packages (a control root, agent A
on the root's machine and agent "cx6-worker"), loopback ports the OS picks and
no `EUGENE_PLEXUS_*` variable from the calling shell:

1. The root refuses to remove its own machine (409, "This root's own machine");
   the roster and the log index (`appliedIndex`) are unchanged.
2. Without a session the removal is refused (401 or 403) and the worker stays.
3. The worker is made the standby and its agent starts the standby.
4. With the worker's agent stopped, the operator's removal answers 202 with
   `TrustChange.revokedNode == "cx6-worker"`, in under 30 s (it never hangs on
   a machine that does not answer).
5. The roster and `/v1/components` no longer list the worker.
6. A standby token the worker minted before removal is refused by the root.
7. The worker's agent, started again with its old enrollment, stops its
   standby and deletes `standby-state/` within 3 minutes (the trust pull is
   about once a minute): "a removed standby deletes its copy".
8. Re-joining: the worker leaves its old enrollment (`POST /v1/node/unenroll`,
   `notifyControl: false`), enrolls with a new join token and is listed again.

Waits poll the real endpoint or directory. A check that cannot run is recorded
as "not checked", never as a pass. Reuses the process helpers of
`standby-acceptance.py` (`serve`, `free_ports`, `node_signer`).

Writes `result.json` and `result.md` into --output (a new directory).

Never run this on default ports on Amish_Station: it picks its own free
loopback ports, clears every ambient `EUGENE_PLEXUS_*` variable, and is meant
for a disposable install at the end of a pass.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx
import yaml

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "standby-acceptance.py"
ROOT_NODE = "cx6-root"
WORKER = "cx6-worker"
REMOVE_BOUND_SECONDS = 30.0
REJOIN_BOUND_SECONDS = 180.0
REPLICATION_LOG = "/v1/control/log?after=0"

# Same as the script it reuses: nothing from the calling shell reaches a process.
for _key in [k for k in os.environ if k.upper().startswith("EUGENE_PLEXUS_")]:
    del os.environ[_key]

_spec = importlib.util.spec_from_file_location("standby_acceptance", SCRIPT)
assert _spec and _spec.loader
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)


class Record:
    """Each check's result and what was observed, in order."""

    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, status: str, **observed: object) -> None:
        self.checks.append({"check": name, "status": status, "observed": observed})
        print(f"{status.upper():12} {name} {json.dumps(observed, default=str)}", flush=True)

    def markdown(self) -> str:
        lines = [
            "# CX6 remove-machine acceptance",
            "",
            "| Check | Result | Observed |",
            "|---|---|---|",
        ]
        for row in self.checks:
            observed = json.dumps(row["observed"], default=str).replace("|", "/")
            lines.append(f"| {row['check']} | {row['status']} | `{observed}` |")
        return "\n".join(lines) + "\n"


def exercise(root: Path, record: Record) -> None:
    ports = sb.free_ports()
    dirs = {"control": root / "root", "agent-a": root / "a", "agent-b": root / "b"}
    for directory in dirs.values():
        directory.mkdir()
    dir_b = dirs["agent-b"]
    passphrase = secrets.token_urlsafe(24)

    def base(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    for name, components in (
        ("agent-a", [{"name": "control", "kind": "control", "url": base("control")}]),
        ("agent-b", []),
    ):
        (dirs[name] / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "advertiseUrl": base(name),
                    "securityMode": "prompt_on_startup",
                    "components": components,
                }
            ),
            encoding="utf-8",
        )

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    processes: dict[str, subprocess.Popen] = {}
    logs: dict[str, object] = {}

    def start(name: str) -> None:
        directory = dirs[name]
        (directory / "stop").unlink(missing_ok=True)
        logs[name] = (root / f"{name}.log").open("a", encoding="utf-8")
        argv = [
            sys.executable,
            str(SCRIPT),
            "--serve",
            "control" if name == "control" else "agent",
            "--directory",
            str(directory),
            "--port",
            str(ports[name]),
        ]
        if name == "agent-b":
            argv += ["--standby-port", str(ports["standby"])]
        processes[name] = subprocess.Popen(
            argv,
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=logs[name],
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def stop(name: str) -> None:
        proc = processes.pop(name)
        (dirs[name] / "stop").touch()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                proc.kill()
            proc.wait(timeout=10)
            raise AssertionError(f"{name} did not shut down its owned processes") from None
        finally:
            logs.pop(name).close()

    with httpx.Client(trust_env=False, timeout=45) as client:

        def call(name: str, method: str, path: str, token: str | None = None, **kwargs):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return client.request(method, base(name) + path, headers=headers, **kwargs)

        def wait_for(check, label: str, timeout: float = 45.0) -> float:
            started = time.perf_counter()
            deadline = started + timeout
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    last = check()
                    if last:
                        return time.perf_counter() - started
                except httpx.HTTPError as exc:
                    last = exc
                time.sleep(0.25)
            raise AssertionError(f"timed out after {timeout:.0f} s waiting for {label} ({last!r})")

        def healthy(name: str) -> None:
            def up() -> bool:
                assert processes[name].poll() is None, f"{name} exited"
                return call(name, "GET", "/healthz").status_code == 200

            wait_for(up, f"{name} health")

        def login(name: str) -> str | None:
            response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
            return response.json()["sessionToken"] if response.status_code == 200 else None

        def roster(session: str) -> dict[str, dict]:
            listed = call("control", "GET", "/v1/nodes", session)
            assert listed.status_code == 200, f"/v1/nodes: {listed.status_code} {listed.text}"
            return {n["name"]: n for n in listed.json()["nodes"]}

        def applied_index(session: str) -> int:
            status = call("control", "GET", "/v1/control/status", session)
            assert status.status_code == 200, f"status: {status.status_code}"
            return status.json()["appliedIndex"]

        def join_token(session: str) -> str:
            minted = call("control", "POST", "/v1/nodes/join-token", session, json={})
            assert minted.status_code == 201, f"join token: {minted.status_code} {minted.text}"
            return minted.json()["token"]

        def worker_standby() -> dict | None | str:
            """The worker's own report; "unknown" when it will not sign us in."""
            session = login("agent-b")
            if session is None:
                return "unknown"
            response = call("agent-b", "GET", "/v1/node", session)
            return response.json().get("standby") if response.status_code == 200 else "unknown"

        def enroll_worker(session_root: str) -> None:
            response = call(
                "agent-b", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}
            )
            token = (
                response.json().get("sessionToken")
                if response.status_code == 200
                else login("agent-b")
            )
            assert token, f"worker initialize/login: {response.status_code} {response.text}"
            enrolled = call(
                "agent-b",
                "POST",
                "/v1/node/enroll",
                token,
                json={
                    "controlUrl": base("control"),
                    "token": join_token(session_root),
                    "name": WORKER,
                },
            )
            assert enrolled.status_code == 200, f"enroll: {enrolled.status_code} {enrolled.text}"

        def mint_standby_token() -> str:
            from eugene_plexus_agent import tokens

            token, _ = sb.node_signer(dir_b).mint(
                typ=tokens.TYP_SERVICE,
                sub="standby",
                aud=[tokens.RECIPIENT_CONTROL],
                ttl_seconds=900,
            )
            return token

        try:
            # ---- setup: a root, A on its machine, the worker -----------------------
            start("control")
            healthy("control")
            init = call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
            assert init.status_code == 204, f"root initialize: {init.status_code}"
            session_root = login("control")
            assert session_root, "root login"
            patched = call(
                "control", "PATCH", "/v1/config", session_root, json={"nodePollIntervalSeconds": 2}
            )
            assert patched.json().get("applied") == ["nodePollIntervalSeconds"], patched.text
            for name in ("agent-a", "agent-b"):
                start(name)
                healthy(name)
            call("agent-a", "POST", "/v1/auth/initialize", json={"passphrase": passphrase})
            session_a = login("agent-a")
            assert session_a, "agent A login"
            enrolled = call(
                "agent-a",
                "POST",
                "/v1/node/enroll",
                session_a,
                json={
                    "controlUrl": base("control"),
                    "token": join_token(session_root),
                    "name": ROOT_NODE,
                },
            )
            assert enrolled.status_code == 200, f"A enroll: {enrolled.status_code} {enrolled.text}"
            enroll_worker(session_root)
            session_root = login("control")
            assert session_root, "root login after enrollment"

            def both_reachable() -> bool:
                nodes = roster(session_root)
                return set(nodes) == {ROOT_NODE, WORKER} and all(
                    n.get("reachable") for n in nodes.values()
                )

            took = wait_for(both_reachable, "both nodes listed reachable", 90)
            record.add(
                "setup: worker enrolled and listed reachable", "pass", seconds=round(took, 1)
            )

            components_before = call("control", "GET", "/v1/components", session_root)
            assert components_before.status_code == 200, components_before.text
            worker_components_before = [
                c for c in components_before.json().get("components", []) if c.get("node") == WORKER
            ]

            # ---- 1. the root's own machine is refused ------------------------------
            index_before = applied_index(session_root)
            own = call("control", "DELETE", f"/v1/nodes/{ROOT_NODE}", session_root)
            assert own.status_code == 409, f"{own.status_code} {own.text}"
            assert "This root's own machine" in own.text, own.text
            assert ROOT_NODE in roster(session_root), "the root's machine left the roster"
            index_after = applied_index(session_root)
            assert index_after == index_before, f"log index moved {index_before} -> {index_after}"
            record.add(
                "1 root's own machine refused, roster and log index unchanged",
                "pass",
                httpStatus=own.status_code,
                body=own.text[:200],
                appliedIndex=index_after,
            )

            # ---- 2. no session ------------------------------------------------------
            anonymous = call("control", "DELETE", f"/v1/nodes/{WORKER}")
            assert anonymous.status_code in (401, 403), f"{anonymous.status_code} {anonymous.text}"
            assert WORKER in roster(session_root), "the worker left the roster without a session"
            record.add("2 removal without a session refused", "pass", httpStatus=anonymous.status_code)

            # ---- 3. the worker becomes the standby ---------------------------------
            made = call("control", "PUT", f"/v1/nodes/{WORKER}/standby", session_root)
            assert made.status_code == 202, f"{made.status_code} {made.text}"
            took = wait_for(
                lambda: (lambda s: isinstance(s, dict) and s.get("status") == "running")(
                    worker_standby()
                ),
                "the worker's agent to start the standby",
                80.0,
            )
            copy = dir_b / "standby-state"
            assert copy.is_dir(), f"no standby copy at {copy}"
            standby_token = mint_standby_token()
            before = call("control", "GET", REPLICATION_LOG, standby_token).status_code
            record.add(
                "3 worker made standby and running",
                "pass",
                seconds=round(took, 1),
                standbyState=str(copy),
                standbyTokenAtLogBeforeRemoval=before,
            )

            # ---- 4. stop the worker, then remove it --------------------------------
            stop("agent-b")
            started = time.perf_counter()
            removed = call("control", "DELETE", f"/v1/nodes/{WORKER}", session_root)
            elapsed = time.perf_counter() - started
            assert removed.status_code == 202, f"{removed.status_code} {removed.text}"
            assert removed.json().get("revokedNode") == WORKER, removed.text
            assert elapsed < REMOVE_BOUND_SECONDS, f"removal took {elapsed:.1f} s"
            record.add(
                "4 removal of a down worker answers 202 with revokedNode, not hanging",
                "pass",
                httpStatus=removed.status_code,
                seconds=round(elapsed, 2),
                body=removed.json(),
            )

            # ---- 5. gone from the roster and the component list --------------------
            assert WORKER not in roster(session_root), "the worker is still listed"
            components = call("control", "GET", "/v1/components", session_root)
            assert components.status_code == 200, components.text
            left = [c for c in components.json().get("components", []) if c.get("node") == WORKER]
            assert not left, f"components still listed on the worker: {left}"
            record.add("5a worker no longer in /v1/nodes", "pass")
            if worker_components_before:
                record.add(
                    "5b worker's components no longer in /v1/components",
                    "pass",
                    before=len(worker_components_before),
                    after=0,
                )
            else:
                record.add(
                    "5b worker's components no longer in /v1/components",
                    "not checked",
                    note="the worker declared no components before removal",
                )

            # ---- 6. a token it minted before is refused ----------------------------
            if before == 200:
                after = call("control", "GET", REPLICATION_LOG, standby_token).status_code
                assert after == 401, f"the worker's old token answered {after}"
                record.add(
                    "6 worker's pre-removal standby token refused",
                    "pass",
                    before=before,
                    after=after,
                )
            else:
                record.add(
                    "6 worker's pre-removal standby token refused",
                    "not checked",
                    note="not checked: the token was not accepted before removal",
                    before=before,
                )

            # ---- 7. started again, a removed standby deletes its copy --------------
            start("agent-b")
            healthy("agent-b")
            seen: list[object] = []

            def standby_gone() -> bool:
                state = worker_standby()
                if not seen or seen[-1] != state:
                    seen.append(state)
                return not copy.exists() and state in (None, "unknown")

            try:
                took = wait_for(
                    standby_gone,
                    "the removed worker's agent to stop its standby and delete its copy",
                    REJOIN_BOUND_SECONDS,
                )
            except AssertionError as exc:
                raise AssertionError(
                    f"{exc}; standby copy still at {copy} (exists={copy.exists()}); "
                    f"standby states seen: {seen}"
                ) from None
            record.add(
                "7 removed standby stopped and deleted its copy",
                "pass",
                seconds=round(took, 1),
                directory=str(copy),
                standbyStatesSeen=seen,
            )

            # ---- 8. re-join ----------------------------------------------------------
            session_b = login("agent-b")
            assert session_b, "the worker would not sign in to leave its old enrollment"
            left = call(
                "agent-b", "POST", "/v1/node/unenroll", session_b, json={"notifyControl": False}
            )
            assert left.status_code == 200, f"unenroll: {left.status_code} {left.text}"
            enroll_worker(session_root)
            session_root = login("control")
            assert session_root, "root login after re-join"

            def listed_once() -> bool:
                nodes = roster(session_root)
                return WORKER in nodes and nodes[WORKER].get("reachable") is True

            took = wait_for(listed_once, "the worker listed reachable again", 90)
            names = [n for n in roster(session_root) if n == WORKER]
            assert len(names) == 1, names
            record.add("8 worker re-joined and is listed once", "pass", seconds=round(took, 1))
        except BaseException:
            for name in ("control", "agent-a", "agent-b"):
                handle = logs.get(name)
                if handle is not None:
                    handle.flush()
                path = root / f"{name}.log"
                if path.exists():
                    tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                    print(f"{name} log tail:\n" + "\n".join(tail), file=sys.stderr)
            raise
        finally:
            for name in ("agent-b", "agent-a", "control"):
                if name in processes:
                    try:
                        stop(name)
                    except AssertionError as exc:
                        print(str(exc), file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    record = Record()
    failure: str | None = None
    try:
        exercise(output, record)
    except BaseException as exc:  # noqa: BLE001 - recorded, then reported by exit status
        failure = f"{type(exc).__name__}: {exc}"
        record.add("failed", "fail", error=failure)
    unchecked = [c["check"] for c in record.checks if c["status"] == "not checked"]
    result = {
        "passed": failure is None,
        "notChecked": unchecked,
        "checks": record.checks,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (output / "result.md").write_text(record.markdown(), encoding="utf-8", newline="\n")
    if failure is not None:
        sys.exit(f"CX6 acceptance failed: {failure}")
    print(f"CX6 acceptance passed ({len(unchecked)} not checked); record in {output}", flush=True)


if __name__ == "__main__":
    main()
