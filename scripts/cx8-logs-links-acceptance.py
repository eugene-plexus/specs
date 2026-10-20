"""CX8: a failure links to the log lines about it, and Routing says what is true.

A fresh isolated install from this checkout's installer (the pinned UI wheel),
on claimed ports with every ambient `EUGENE_PLEXUS_*` variable cleared, set up
with no model and left with its gateway running. Beside the gateway the agent
supervises two real inference-drivers (`cx8-primary`, `cx8-backup`) whose
backend is a stand-in HTTP server in this process: it answers `/v1/models`
and `/props` for both, refuses every completion for `cx8-primary` with a 503,
and answers for `cx8-backup`. No model is downloaded.

Over HTTP, once the browser half has set the install up:
1. `PATCH gateway /v1/config` puts the routing list `cx8-alias -> cx8-primary,
   cx8-backup` in force, as the Routing page does. One chat request for
   `cx8-alias` goes through the agent's proxy: the primary refuses it, the
   backup answers (both stand-in counters are read).
2. The request is read in `GET gateway /v1/metrics/requests` (more than one
   attempt, one not served), and the agent's `GET /v1/logs?contains=<requestId>`
   returns the gateway's `failover[...]` WARNING ending "(request <id>)": the
   same id Metrics shows.

The browser half (`cx8-logs-links-browser.mjs`) then checks:
3. Metrics shows "Logs →" on that request (href `/logs?q=<id>`); a click opens
   Logs with the box holding the id and at least one line, one of them the id's.
4. `/logs?q=<text that matches nothing>` shows "No line contains “…”." and
   Clear, and Clear brings the lines back.
5. Routing: moving a target and pressing Save reads "Saved. The gateway uses
   these lists now" (and not the old "next routing refresh"), and the saved
   order is the gateway's.

Hand-off between the halves: the browser writes `ready.flag` when the gateway
runs, this script writes `http.json` when step 1-2 are done (or have failed),
and the browser waits for it.

Not checked, and recorded as such in `result.json` under `notChecked`: the
"Logs →" links on a down machine (Machines), a silent machine (Hosts), an
app's last error and a failed app install (one machine here, and no app is
installed or failed); and the "(driver: <word>)" suffix on "x of y ready" (every
backend here is ready).

Shares its install steps with the CX2 harness. Windows only. Never run on
the default ports on Amish_Station: it claims its own.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import httpx
import yaml

HERE = Path(__file__).resolve().parent
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PASSPHRASE = "cx8-disposable-passphrase"
ALIAS = "cx8-alias"

_spec = importlib.util.spec_from_file_location("cx2", HERE / "cx2-setup-resume-acceptance.py")
assert _spec and _spec.loader
cx2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cx2)

CHECKS = (
    "failoverHappened",
    "failoverLineCarriesId",
    "metricsLinkShown",
    "metricsLinkHref",
    "linkOpensLogsWithId",
    "linkedLogsShowLines",
    "noMatchMessage",
    "noMatchClear",
    "clearBringsLinesBack",
    "routingSavedLine",
    "routingOldWordingGone",
    "routingOrderSaved",
)

NOT_CHECKED = [
    "Machines: 'Logs →' on a down machine (one machine here; none is stopped)",
    "Hosts: 'Logs →' on a silent machine (no second machine is enrolled)",
    "an app's lastError 'Logs →' and a failed install's 'Logs →' (no app is installed or made to fail)",
    "the '(driver: <word>)' suffix on 'x of y ready' (every backend here is ready; the word is a unit test)",
]


class Standin:
    """The backend behind both drivers: `primary` refuses completions, `backup` answers."""

    def __init__(self, port: int) -> None:
        self.calls = {"primary": 0, "backup": 0}
        calls = self.calls

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def _send(self, status: int, body: dict) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                parts = self.path.split("?")[0].strip("/").split("/")
                name = parts[0]
                if self.path.endswith("/v1/models"):
                    self._send(200, {"data": [{"id": name}]})
                elif self.path.endswith("/props"):
                    self._send(200, {"default_generation_settings": {"n_ctx": 4096}})
                else:
                    self._send(200, {})

            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                name = self.path.strip("/").split("/")[0]
                if name in calls:
                    calls[name] += 1
                if name == "primary":
                    self._send(503, {"error": {"message": "cx8 stand-in refuses"}})
                    return
                self._send(200, {
                    "model": name,
                    "choices": [{"message": {"role": "assistant", "content": "backup-only"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                })

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def poll(check, seconds: float, what: str):
    until = time.perf_counter() + seconds
    while time.perf_counter() < until:
        try:
            value = check()
            if value:
                return value
        except httpx.HTTPError:
            pass
        time.sleep(.5)
    raise AssertionError(f"timed out: {what}")


def failover(client: httpx.Client, url: str, standin: Standin) -> dict:
    """Steps 1 and 2: make a failover happen and find its line by the request's id."""
    seen: dict = {}
    login = client.post(url + "/v1/auth/login", json={"passphrase": PASSPHRASE})
    assert login.status_code == 200, login.text[:300]
    auth = {"Authorization": f"Bearer {login.json()['sessionToken']}"}
    proxy = url + "/api/proxy/gateway"
    slots = [{"model": ALIAS, "targets": ["cx8-primary", "cx8-backup"]}]
    patched = client.patch(proxy + "/v1/config", headers=auth, json={"modelSlots": slots})
    assert patched.status_code == 200 and not patched.json().get("rejected"), patched.text[:300]

    def routed():
        table = client.get(proxy + "/v1/admin/routing", headers=auth)
        if table.status_code != 200:
            return False
        tiers = {
            tier["target"]: any(b.get("eligible") for b in tier.get("backends", []))
            for slot in table.json().get("slots", []) if slot.get("model") == ALIAS
            for tier in slot.get("tiers", [])
        }
        return tiers.get("cx8-primary") and tiers.get("cx8-backup")

    poll(routed, 240, "the gateway routes cx8-alias to both stand-in drivers")
    chat = client.post(proxy + "/v1/chat/completions", headers=auth, timeout=60, json={
        "model": ALIAS, "max_tokens": 8, "messages": [{"role": "user", "content": "hello"}]})
    seen["chatStatus"] = chat.status_code
    seen["standinCalls"] = dict(standin.calls)
    assert chat.status_code == 200 and "backup-only" in chat.text, chat.text[:300]
    assert standin.calls["primary"] >= 1 and standin.calls["backup"] >= 1, standin.calls

    def row():
        page = client.get(proxy + "/v1/metrics/requests?limit=50", headers=auth)
        rows = [r for r in page.json().get("requests", []) if r.get("requestedModel") == ALIAS and r.get("requestId")]
        return rows[0] if rows else None

    request = poll(row, 60, "the request in Metrics")
    request_id = request["requestId"]
    seen.update({"requestId": request_id, "attempts": request.get("attempts"),
                 "triesServed": [t.get("served") for t in request.get("tries", [])]})
    seen["failoverHappened"] = (request.get("attempts") or 0) > 1 and any(
        not t.get("served") for t in request.get("tries", []))

    def line():
        page = client.get(url + "/v1/logs", headers=auth, params={"contains": request_id, "tail": 200})
        lines = page.json().get("lines", []) if page.status_code == 200 else []
        tail = f"(request {request_id})"
        return [ln for ln in lines if "failover[" in ln["text"] and ln["text"].rstrip().endswith(tail)]

    try:
        found = poll(line, 45, "the failover line in the agent's log")
    except AssertionError:
        found = []
    seen["failoverLines"] = found
    seen["failoverLineCarriesId"] = bool(found)
    return seen


def run(root: Path) -> None:
    assert sys.platform == "win32", "Windows only"
    root.mkdir(parents=True, exist_ok=False)
    prefix = root / "install"
    before = cx2.snapshot_windows()
    base = cx2.claim_ports()
    agent_port = base + 1
    standin_port = base + 7
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update({"NO_PROXY": "localhost,127.0.0.1,::1", "PYTHONUTF8": "1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port)})
    result: dict = {"ports": {"agent": agent_port, "standin": standin_port}, "checks": {},
                    "notChecked": list(NOT_CHECKED)}
    agent = None
    standin = None
    logs = []
    try:
        standin = Standin(standin_port)
        wrapper = root / "install-wrapper.ps1"
        wrapper.write_text("& '" + str(HERE / "install.ps1").replace("'", "''") + "' -Prefix '" +
                           str(prefix).replace("'", "''") + "' -NoService -NoStart -Isolated\n",
                           encoding="utf-8")
        with (root / "installer.log").open("w", encoding="utf-8") as log:
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                           env=env, cwd=root, stdout=log, stderr=log, check=True, timeout=900)
        python = prefix / "venv/Scripts/python.exe"
        drivers = (("cx8-primary", 5, "primary"), ("cx8-backup", 6, "backup"))
        for name, _, path in drivers:
            (prefix / f"{name}.yaml").write_text(yaml.safe_dump({
                "provider": "openai_compat_custom", "modelId": name,
                "baseUrl": f"http://127.0.0.1:{standin_port}/{path}", "backendLocality": "local"}),
                encoding="utf-8")
        (prefix / "agent.yaml").write_text(yaml.safe_dump({"components": [
            {"name": name, "kind": kind, "url": f"http://127.0.0.1:{base + offset}",
             "spawn": {"configFile": str(prefix / f"{name}.yaml")}}
            for name, kind, offset in (
                ("control", "control", 2), ("gateway", "gateway", 3), ("library", "library", 4),
                ("cx8-primary", "inference-driver", 5), ("cx8-backup", "inference-driver", 6))]}),
            encoding="utf-8")
        env.update({"HOME": str(prefix), "USERPROFILE": str(prefix),
                    "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(prefix / "engines"),
                    "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(prefix / "agent.yaml"),
                    "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1"})
        log = (root / "agent.log").open("w", encoding="utf-8")
        logs.append(log)
        agent = subprocess.Popen([str(python), str(HERE / "s8-ui-acceptance.py"), "--serve", str(prefix),
                                  "--port", str(agent_port)], cwd=prefix, env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=FLAGS)
        url = f"http://127.0.0.1:{agent_port}"
        with httpx.Client(trust_env=False, timeout=10) as client:
            for _ in range(300):
                try:
                    if client.get(url + "/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert agent.poll() is None, "agent exited"
                time.sleep(.2)
            settings = root / "browser-settings.json"
            settings.write_text(json.dumps({"url": url, "output": str(root), "passphrase": PASSPHRASE,
                                            "alias": ALIAS}), encoding="utf-8")
            with (root / "browser.log").open("w", encoding="utf-8") as blog:
                browser = subprocess.Popen(["node", str(HERE / "cx8-logs-links-browser.mjs"), str(settings)],
                                           stdout=blog, stderr=blog)
                try:
                    # The browser sets the install up, then waits for the failover.
                    until = time.perf_counter() + 900
                    while not (root / "ready.flag").exists():
                        assert browser.poll() is None, "browser exited before the install was ready"
                        assert time.perf_counter() < until, "the install was not ready in 15 minutes"
                        time.sleep(.5)
                    try:
                        handoff = failover(client, url, standin)
                    except Exception as error:
                        handoff = {"error": repr(error)}
                    (root / "http.json").write_text(json.dumps(handoff), encoding="utf-8")
                    result["failover"] = handoff
                    browser.wait(timeout=1800)
                finally:
                    if browser.poll() is None:
                        browser.kill()
            report = root / "browser.json"
            if report.exists():
                result["browser"] = json.loads(report.read_text(encoding="utf-8"))
            assert "error" not in handoff, f"the failover could not be made: {handoff['error']}"
            assert browser.returncode == 0, "browser failed; see browser.log and failure.png"
            seen = result["browser"]
            opened = seen.get("opened") or {}
            nomatch = seen.get("nomatch") or {}
            routing = seen.get("routing") or {}
            checks = result["checks"]
            checks["failoverHappened"] = handoff.get("failoverHappened") is True
            checks["failoverLineCarriesId"] = handoff.get("failoverLineCarriesId") is True
            checks["metricsLinkShown"] = seen.get("linkShown") is True and seen.get("linkText") == "Logs →"
            checks["metricsLinkHref"] = seen.get("linkHrefOk") is True
            checks["linkOpensLogsWithId"] = opened.get("boxHoldsId") is True and opened.get("onLogs") is True
            checks["linkedLogsShowLines"] = (opened.get("lines") or 0) >= 1 and opened.get("someLineHasId") is True
            checks["noMatchMessage"] = nomatch.get("messageOk") is True
            checks["noMatchClear"] = nomatch.get("clearShown") is True
            checks["clearBringsLinesBack"] = nomatch.get("linesAfterClear", 0) >= 1
            checks["routingSavedLine"] = routing.get("savedLineOk") is True
            checks["routingOldWordingGone"] = routing.get("oldWordingGone") is True
            checks["routingOrderSaved"] = routing.get("orderSaved") is True
        result["passed"] = all(result["checks"].values()) and set(result["checks"]) == set(CHECKS)
    finally:
        try:
            if agent:
                (prefix / "stop").touch()
                agent.wait(timeout=45)
        finally:
            for log in logs:
                log.close()
            if standin:
                standin.stop()
            result["liveInstallUnchanged"] = cx2.snapshot_windows() == before
            (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            lines = ["# CX8 acceptance", "", f"Passed: {result.get('passed', False)}", "", "## Checks", ""]
            lines += [f"- {name}: {value}" for name, value in result["checks"].items()]
            lines += ["", "## Not checked", ""] + [f"- {item}" for item in result["notChecked"]]
            (root / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["liveInstallUnchanged"], "live service/account environment changed"
    assert result["passed"], "a CX8 check failed; see result.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True, help="A new disposable directory")
    run(parser.parse_args().output.resolve())
