"""C5b: catalogue Workbench, real service account, sign-in, model and stdio tools.

Disposable GitHub runners only. Reuses C1's installation and account probes,
C4's public model registration, and C3's browser client. No live developer
install is touched. The model is a deterministic fixture, not an LLM benchmark.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


c4 = load("c4", "c4-open-webui-acceptance.py")
c1 = c4.c1
c3 = load("c3", "c3-workbench-acceptance.py")
api, check, must, fact, wait_for = c1.api, c1.check, c1.must, c1.fact, c1.wait_for
MODEL = "c5-local"
REQUESTS: list[dict] = []


def alive(pid: int) -> bool:
    if c1.WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return (
                bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                and code.value == 259
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(")", 1)[1].split()[0] == "Z")


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def send(self, body: object, content_type: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.send({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "messages" not in body:
            # Engine capability/tokenization probes are not chat requests.
            self.send_error(404)
            return
        REQUESTS.append(body)
        results = [m for m in body["messages"] if m["role"] == "tool"]
        if body.get("tools") and not results:
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "c5-call",
                        "type": "function",
                        "function": {
                            "name": body["tools"][0]["function"]["name"],
                            "arguments": "{}",
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            delta, finish = {"role": "assistant", "content": "C5 complete."}, "stop"

        def chunk(value, end):
            return {
                "id": "c5-answer",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": MODEL,
                "choices": [{"index": 0, "delta": value, "finish_reason": end}],
            }

        frames = [chunk(delta, None), chunk({}, finish)]
        self.send(
            (
                "".join("data: " + json.dumps(f) + "\n\n" for f in frames)
                + "data: [DONE]\n\n"
            ).encode(),
            "text/event-stream",
        )


def install(token: str) -> dict:
    _, catalogue = api("GET", c1.AGENT + "/v1/app-catalogue", token)
    entry = next(
        a["manifest"] for a in catalogue["apps"] if a["manifest"]["id"] == "workbench"
    )
    must(
        "30",
        "catalogue requires an app account for Workbench",
        entry["localActions"] is True,
    )
    fact("Workbench dist", entry["version"])
    status, body = api("POST", c1.AGENT + "/v1/apps/workbench/install", token)
    must("31", "Workbench install starts", status in (200, 202), body)

    def finished():
        _, progress = api("GET", c1.AGENT + "/v1/apps/workbench/install", token)
        return (
            progress
            if progress.get("state") in {"done", "failed", "cancelled"}
            else None
        )

    progress = wait_for(finished, 900, 3) or {}
    must(
        "32",
        "the published Workbench archive installs",
        progress.get("state") == "done",
        progress,
    )

    def running():
        _, app = api("GET", c1.AGENT + "/v1/apps/workbench", token)
        return app if app.get("status") == "running" else None

    app = wait_for(running, 180, 2) or {}
    must(
        "33",
        "Workbench runs in its own OS account",
        app.get("isolation") == "own_account",
        app.get("status"),
    )
    return app


def provision(app: dict) -> tuple[str, list[str]]:
    # The operator installs code outside people's private home directories.
    target = Path(r"C:\ep-c5b-tools") if c1.WINDOWS else Path("/opt/ep-c5b-tools")
    copies = [
        (HERE / "fixtures/c5-local-mcp.py", "server.py"),
        (c1.FIXTURE / "eugene_plexus_app_fixture/__main__.py", "app_probe.py"),
    ]
    if c1.WINDOWS:
        target.mkdir(exist_ok=True)
        for source, name in copies:
            shutil.copyfile(source, target / name)
    else:
        subprocess.run(["sudo", "mkdir", "-p", str(target)], check=True)
        for source, name in copies:
            subprocess.run(
                ["sudo", "install", "-m", "644", str(source), str(target / name)],
                check=True,
            )
    venv = c1.PREFIX / "apps/workbench/versions" / app["version"] / "venv"
    python = venv / ("Scripts/python.exe" if c1.WINDOWS else "bin/python")
    return str(python), [str(target / "server.py"), str(c1.PREFIX)]


def exercise(app: dict, token: str) -> None:
    base = f"http://127.0.0.1:{app['port']}"
    browser = c3.Browser(base)
    must(
        "40",
        "owner signs in through Eugene",
        browser.sign_in(c1.PASSPHRASE).startswith("/#signin="),
    )
    tools = browser.get("/api/tools/servers").json()
    must(
        "41",
        "real launcher enables local tools",
        tools["localProcesses"]["available"],
        tools["localProcesses"],
    )
    command, args = provision(app)
    created = browser.post(
        "/api/tools/servers",
        json={
            "name": "OS access probe",
            "transport": "stdio",
            "command": command,
            "args": args,
            "environment": {"C5_MARKER": "configured-for-this-server"},
        },
    )
    must("42", "owner saves a local command", created.status_code == 201, created.text)
    server = created.json()["id"]
    discovery = browser.post(f"/api/tools/servers/{server}/check")
    must(
        "43",
        "the app account can start and discover the provisioned program",
        discovery.status_code == 200,
        discovery.text,
    )
    chat = browser.post("/api/chats", json={"model": MODEL}).json()["id"]
    selected = browser.patch(
        f"/api/chats/{chat}", json={"settings": {"toolServers": [server]}}
    )
    must(
        "44",
        "owner selects the local server",
        selected.status_code == 200,
        selected.text,
    )
    sent = browser.post(
        f"/api/chats/{chat}/messages", json={"content": "Inspect the account."}
    )
    must(
        "45",
        "a model turn starts through the public gateway",
        sent.status_code == 201,
        sent.text,
    )

    def pending():
        messages = browser.get(f"/api/chats/{chat}").json()["messages"]
        message = messages[-1]
        return (
            message
            if message.get("toolRounds") or message["status"] != "running"
            else None
        )

    message = wait_for(pending, 60, 0.2) or {}
    calls = (message.get("toolRounds") or [{}])[0].get("calls") or []
    must(
        "46",
        "the exact call waits for approval",
        bool(calls) and calls[0]["status"] == "pending",
        calls or message,
    )
    approved = browser.post(
        f"/api/chats/{chat}/messages/{message['id']}/tools/decision",
        json={"callId": calls[0]["id"], "approve": True},
    )
    must("47", "the owner approves", approved.status_code == 204, approved.text)
    done = browser.answer(chat, seconds=120)
    call = done["toolRounds"][0]["calls"][0]
    must(
        "48",
        "the tool runs and the model continues",
        done["status"] == "done" and call["status"] == "done",
        done,
    )
    result, _ = json.JSONDecoder().raw_decode(call["result"])
    pids = [int(result["serverPid"]), int(result["childPid"])]
    check(
        "48a",
        "the completed answer leaves no server or ordinary child process",
        bool(wait_for(lambda: all(not alive(pid) for pid in pids), 15, 0.2)),
        pids,
    )
    fact("local tool account", result["user"])
    expected_account = str(app["account"]).split(" (", 1)[0].lower()
    check(
        "49",
        "tool inherits Workbench's account",
        str(result["user"]).lower().startswith(expected_account),
        app["account"],
    )
    readable = result["readable"]
    check(
        "50",
        "local tool cannot read Eugene or another app's private files",
        not [
            p
            for p in readable
            if not p.startswith("apps/workbench/") and not p.startswith(c1.SHARED_TREES)
        ],
        readable[:20],
    )
    check(
        "51",
        "no Eugene credential environment reaches the local tool",
        result["eugeneEnvironment"] == [],
        result["eugeneEnvironment"],
    )
    check(
        "52",
        "the server receives its explicit value and own working home",
        result["explicitValue"] and result["cwd"] == result["home"],
    )
    _, login = api(
        "POST", c1.CONTROL + "/v1/auth/login", body={"passphrase": c1.PASSPHRASE}
    )
    status, person = api(
        "POST",
        c1.CONTROL + "/v1/people",
        login["sessionToken"],
        {"name": "ada", "password": "c5-person-password"},
    )
    must("53", "owner adds a person", status == 201, person)
    member = c3.Browser(base)
    must(
        "54",
        "member signs in",
        member.sign_in("c5-person-password", "ada").startswith("/#signin="),
    )
    check(
        "55",
        "member cannot list or launch the owner's local command",
        member.get("/api/tools/servers").json()["servers"] == []
        and member.post(f"/api/tools/servers/{server}/check").status_code == 403,
    )
    _, before = api("GET", c1.AGENT + "/v1/apps/workbench", token)
    must("56a", "Workbench has a service PID before restart", bool(before.get("pid")))
    status, restarted = api("POST", c1.AGENT + "/v1/apps/workbench/restart", token)
    must("56b", "the agent accepts the restart", status == 200, restarted)

    def ready_again():
        _, current = api("GET", c1.AGENT + "/v1/apps/workbench", token)
        return (
            current.get("status") == "running"
            and current.get("pid")
            and current["pid"] != before["pid"]
            and c1.healthy(base)()
        )

    must(
        "56",
        "a new Workbench process answers its health check",
        bool(wait_for(ready_again, 90, 2)),
    )
    browser = c3.Browser(base)
    must(
        "57",
        "owner signs in after restart",
        browser.sign_in(c1.PASSPHRASE, "operator").startswith("/#signin="),
    )
    saved = browser.get(f"/api/chats/{chat}").json()["messages"][-1]
    check(
        "58",
        "completed tool result survives restart",
        saved["toolRounds"] == done["toolRounds"],
    )
    check(
        "59",
        "the owner can remove the server",
        browser.http.delete(
            base + f"/api/tools/servers/{server}", headers=browser._headers()
        ).status_code
        == 204,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise SystemExit(
            "This installs machine services. Run only on a disposable GitHub runner."
        )
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    c4.MODEL, c4.FIXTURE_PORT = MODEL, fixture.server_address[1]
    try:
        work = Path(tempfile.mkdtemp(prefix="ep-c5b-"))
        c1.phase_install(c1.installer_copy(work))
        token = c1.phase_onboard()
        other_apps = c1.phase_apps(token, c1.fixture_source(work))
        c1.phase_probe(other_apps)
        c4.add_model(token)
        app = install(token)
        exercise(app, token)
    except Exception as exc:
        check("aborted", "acceptance completes", False, f"{type(exc).__name__}: {exc}")
    finally:
        fixture.shutdown()
        args.report.write_text(
            json.dumps({"facts": c1.FACTS, "results": c1.RESULTS}, indent=2),
            encoding="utf-8",
        )
    failed = [r for r in c1.RESULTS if not r["passed"]]
    print(f"{len(c1.RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
