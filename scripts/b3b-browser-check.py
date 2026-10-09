"""2b.3b in the browser (docs/design/job-sites-own-enrollment.md §3.3, 2b.3c's
*done when*, which 2b.3b took on): in a real Workbench page, a job site's
"allow" runs with no prompt, "ask" prompts, "deny" is never offered, a 40-call
search-and-read task finishes, and Stop ends it.

Real processes on free ports, one account (this one):

* **the root**: `control`, plain HTTP, `siteJoinUrl` its own address (the
  LAN-only install, J31). The public entry point is not under test here
  (`job-sites-acceptance.py` owns it);
* **an agent** enrolled with it that supervises a real **gateway** and a real
  **inference-driver**, whose engine is a scripted model in this process (it
  makes the tool calls each step needs, and records what it was offered);
* **the site**: the real site host, installed from the sibling checkout (or
  `--site-host-source`), joined as ada's site, with a worker beside it. With
  one account the worker is `job-sites-acceptance.py`'s stand-in (the real
  worker with its one account refusal removed); what the OS does between
  accounts is that script's and the Windows run's;
* **Workbench**, installed from an archive (`--workbench-source`, else the
  agent's catalogue pin) and run with the environment the agent gives an app,
  as `app:workbench@root` (the root serves job sites to no other client);
* **Chrome** (the system one, Playwright from `ui/node_modules`) signs in as
  ada on Eugene's own page and does every step in Workbench's page
  (`b3b-browser-check.mjs`). Only the machine's starter is played: ada's key
  is pinned in the links file, and what is held for it is approved at the
  machine through the site host's own `/v1/held`, as `job-sites-acceptance.py`
  does (passkeys in Chrome are `j14a3-browser-check.py`'s).

Run with the agent's venv, which holds every Python component:
`../agent/.venv/Scripts/python.exe scripts/b3b-browser-check.py
--workbench-source <dist archive URL or directory>`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPOS = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("job_sites", HERE / "job-sites-acceptance.py")
assert _spec and _spec.loader
js = importlib.util.module_from_spec(_spec)
sys.modules["job_sites"] = js
_spec.loader.exec_module(js)  # also clears every ambient EUGENE_PLEXUS_* variable

MODEL = "b3b-local"
NODE = "b3b-node"
FILES = 40

RESULTS: list[tuple[str, str, bool, str]] = []


def check(number: str, claim: str, passed: bool, detail: object = "") -> bool:
    RESULTS.append((number, claim, bool(passed), str(detail)))
    tail = f"  -- {detail}" if detail not in ("", None) else ""
    print(f"  {'PASS' if passed else 'FAIL'}  {number}. {claim}{tail}", flush=True)
    return bool(passed)


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


def wait(fn: Any, label: str, seconds: float = 60) -> Any:
    deadline = time.perf_counter() + seconds
    last: object = None
    while time.perf_counter() < deadline:
        try:
            value = fn()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001 - retried until the deadline
            last = exc
        time.sleep(0.25)
    raise SystemExit(f"timed out: {label} ({last!r})")


# --------------------------------------------------------------------------- #
# The scripted model: what each step's answer calls, by the step's tag
# --------------------------------------------------------------------------- #


class Script:
    """Shared by the model's handler, the browser (through `/stats`) and the
    harness. `seen` is every chat request: its step, its round and the tools
    it offered by their file-tool names."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seen: list[dict[str, Any]] = []
        self.write_function: str | None = None
        self.machine: Any = None  # set once the site is up: approve or reject at the machine


SCRIPT = Script()


def _text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def _tool(functions: list[dict[str, Any]], tool: str) -> str | None:
    """Workbench names a site's tool `"<site> · Files: <tool>. <description>"`."""
    return next((f["name"] for f in functions if f": {tool}." in f["description"]), None)


def plan(step: str, rounds: int, functions: list[dict[str, Any]]) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    """The calls this round makes (by tool), or the answer's last words."""
    by_name = {t: _tool(functions, t) for t in ("read_text", "write_text", "glob", "grep")}

    def call(tool: str, **arguments: Any) -> tuple[str, dict[str, Any]]:
        name = by_name[tool]
        if name is None:
            raise LookupError(tool)
        return name, {"folder": "Notes", **arguments}

    if step == "W1":
        return ([call("read_text", path="plan.txt")], None) if rounds == 0 else ([], "W1-DONE")
    if step in ("W2a", "W2b", "W2c"):
        if rounds:
            return [], f"{step}-DONE"
        path = {"W2a": "approved.txt", "W2b": "declined.txt", "W2c": "stopped.txt"}[step]
        made = call("write_text", path=path, text=f"written by {step}\n", expectedSha256="")
        SCRIPT.write_function = made[0]
        return [made], None
    if step == "W3":
        if rounds:
            return [], "W3-DONE"
        # The write tool Workbench offered before the rules said "never",
        # asked for again by a model that remembers it.
        return [(SCRIPT.write_function or "unknown", {"folder": "Notes", "path": "denied.txt",
                                                      "text": "never\n", "expectedSha256": ""})], None
    if step == "W4":
        if rounds == 0:
            return [call("glob", pattern="docs/*.txt"), call("grep", pattern="needle-7"),
                    call("read_text", path="docs/f01.txt"), call("read_text", path="docs/f02.txt")], None
        if rounds <= 9:
            first = 3 + 4 * (rounds - 1)
            return [call("read_text", path=f"docs/f{n:02}.txt") for n in range(first, first + 4)], None
        return [], "W4-DONE: searched twice and read 38 files"
    if step == "W5":
        time.sleep(0.3)
        return [call("read_text", path=f"docs/f{rounds % FILES + 1:02}.txt")], None
    return [], f"no step named {step!r}"


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        pass

    def send(self, body: object, content_type: str = "application/json", status: int = 200) -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/stats"):
            with SCRIPT.lock:
                self.send({"seen": SCRIPT.seen})
            return
        self.send({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if self.path.startswith("/machine/"):
            # The machine's starter, for the browser: approve (or turn down)
            # what is held for ada, through the site host's own /v1/held.
            action = self.path.rsplit("/", 1)[1]
            try:
                done = SCRIPT.machine(action)
                self.send({"done": done})
            except Exception as exc:  # noqa: BLE001 - reported to the browser
                self.send({"error": f"{type(exc).__name__}: {exc}"}, status=500)
            return
        body = json.loads(raw)
        if "messages" not in body:
            self.send_error(404)  # an engine probe, not a chat request
            return
        messages = body["messages"]
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        step = _text(messages[last_user]).split(":", 1)[0].strip()
        rounds = sum(1 for m in messages[last_user:] if m["role"] == "assistant" and m.get("tool_calls"))
        functions = [t["function"] for t in body.get("tools") or []]
        offered = sorted(f["description"].split(": ", 1)[1].split(".", 1)[0] for f in functions
                         if ": " in f["description"])
        results = sum(1 for m in messages[last_user:] if m["role"] == "tool")
        with SCRIPT.lock:
            SCRIPT.seen.append({"step": step, "round": rounds, "offered": offered, "results": results})
        try:
            calls, words = plan(step, rounds, functions)
        except LookupError as exc:
            calls, words = [], f"{step}: the tool {exc} was not offered"
        if calls:
            delta: dict[str, Any] = {"role": "assistant", "tool_calls": [
                {"index": i, "id": f"{step}-{rounds}-{i}-{secrets.token_hex(3)}", "type": "function",
                 "function": {"name": name, "arguments": json.dumps(arguments)}}
                for i, (name, arguments) in enumerate(calls)]}
            finish = "tool_calls"
        else:
            delta, finish = {"role": "assistant", "content": words}, "stop"

        def chunk(value: dict[str, Any], end: str | None) -> dict[str, Any]:
            return {"id": "b3b", "object": "chat.completion.chunk", "created": 1, "model": MODEL,
                    "choices": [{"index": 0, "delta": value, "finish_reason": end}]}

        frames = [chunk(delta, None), chunk({}, finish)]
        self.send(("".join("data: " + json.dumps(f) + "\n\n" for f in frames)
                   + "data: [DONE]\n\n").encode(), "text/event-stream")


# --------------------------------------------------------------------------- #
# Control and the agent, each its own process (this script with --serve)
# --------------------------------------------------------------------------- #


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app as create_agent
        from eugene_plexus_agent.settings import Settings as AgentSettings

        app = create_agent(settings=AgentSettings(config_file=directory / "agent.yaml",
                                                  default_topology=False, bind_port=port))
    else:
        raise SystemExit(f"unknown kind {kind!r}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def uv_binary() -> str:
    beside = Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv")
    found = str(beside) if beside.is_file() else shutil.which("uv")
    if not found:
        raise SystemExit("uv is needed: pip install uv into this interpreter")
    return found


def workbench_source(chosen: str | None) -> str:
    if chosen:
        path = Path(chosen)
        return str(path.resolve()) if path.exists() else chosen
    import yaml
    from eugene_plexus_agent import apps

    catalogue = yaml.safe_load((Path(apps.__file__).parent / "apps_catalogue.yaml").read_text(encoding="utf-8"))
    entries = catalogue if isinstance(catalogue, list) else catalogue.get("apps", [])
    return str(next(e for e in entries if e["id"] == "workbench")["source"])


def install_workbench(work: Path, source: str) -> Path:
    from eugene_plexus_agent.apps import venv_python

    uv = uv_binary()
    env_dir = work / "workbench-env"
    subprocess.run([uv, "venv", "--python", "3.12", str(env_dir)], check=True, capture_output=True,
                   stdin=subprocess.DEVNULL)
    python = Path(venv_python(env_dir))
    installed = subprocess.run([uv, "pip", "install", "--python", str(python), source],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if installed.returncode != 0:
        raise SystemExit("Workbench did not install:\n" + installed.stderr[-2000:])
    return python


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def run(args: argparse.Namespace) -> int:
    import httpx
    import yaml

    work = Path(tempfile.mkdtemp(prefix="ep-b3b-browser-"))
    names = ["control", "agent", "gateway", "model", "workbench"]
    ports = {n: js.free_port() for n in names}
    url = {n: f"http://127.0.0.1:{p}" for n, p in ports.items()}
    processes: list[subprocess.Popen[bytes]] = []
    hosts: list[Any] = []
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    fixture_url = f"http://127.0.0.1:{fixture.server_address[1]}"
    http = httpx.Client(trust_env=False, timeout=60)
    say(f"working in {work}")

    def start(name: str) -> None:
        directory = work / name
        directory.mkdir(exist_ok=True)
        env = js.clean_environment()
        env.pop("OPENAI_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        processes.append(subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name, "--directory",
             str(directory), "--port", str(ports[name])],
            cwd=directory, env=env, stdin=subprocess.DEVNULL,
            stdout=(directory / "process.log").open("ab"), stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ))
        wait(lambda: http.get(url[name] + "/healthz").status_code == 200, name)

    try:
        say("the root, its people and Workbench's sign-in")
        (work / "control").mkdir()
        start("control")
        control = url["control"]
        assert http.post(f"{control}/v1/auth/initialize", json={"passphrase": js.PASSPHRASE}).status_code == 204
        root = http.post(f"{control}/v1/auth/login", json={"passphrase": js.PASSPHRASE}).json()["sessionToken"]
        owner = {"Authorization": f"Bearer {root}"}
        client = http.post(f"{control}/v1/oidc/clients", headers=owner, json={
            "name": "Workbench", "owner": "app:workbench@root",
            "redirectUris": [f"{url['workbench']}/oidc/callback", js.CALLBACK]}).json()
        made = http.post(f"{control}/v1/people", headers=owner, json={
            "name": "ada", "password": js.PASSWORD, "apps": [client["client"]["clientId"]]})
        assert made.status_code == 201, made.text
        ada_id = made.json()["id"]
        assert http.patch(f"{control}/v1/config", headers=owner,
                          json={"siteJoinUrl": control}).status_code == 200

        say("an agent that supervises a gateway and a model whose engine is the script")
        agent_dir = work / "agent"
        agent_dir.mkdir()
        (agent_dir / "gateway.yaml").write_text(yaml.safe_dump({"routingRefreshSeconds": 2}), encoding="utf-8")
        (agent_dir / "model.yaml").write_text(yaml.safe_dump({
            "provider": "openai_compat_custom", "baseUrl": fixture_url, "modelId": MODEL,
            "backendLocality": "local"}), encoding="utf-8")
        (agent_dir / "agent.yaml").write_text(yaml.safe_dump({
            "firstRunComplete": True,
            "updateChecks": False,
            "advertiseUrl": url["agent"],
            "securityMode": "prompt_on_startup",
            "uvBinary": uv_binary(),
            "components": [
                {"name": "gateway", "kind": "gateway", "url": url["gateway"],
                 "spawn": {"configFile": str(agent_dir / "gateway.yaml")}},
                {"name": "model", "kind": "inference-driver", "url": url["model"],
                 "spawn": {"configFile": str(agent_dir / "model.yaml")}},
            ],
        }), encoding="utf-8")
        start("agent")
        agent = url["agent"]
        local = http.post(f"{agent}/v1/auth/initialize", json={"passphrase": js.PASSPHRASE}).json()["sessionToken"]
        join = http.post(f"{control}/v1/nodes/join-token", headers=owner,
                         json={"nodeName": NODE, "grants": ["gateway"]}).json()["token"]
        enrolled = http.post(f"{agent}/v1/node/enroll", headers={"Authorization": f"Bearer {local}"},
                             timeout=90, json={"controlUrl": control, "token": join, "name": NODE})
        assert enrolled.status_code == 200, enrolled.text[:400]
        wait(lambda: http.get(f"{agent}/healthz").status_code == 200, "the agent after enrolment")
        operator = http.post(f"{agent}/v1/auth/login", json={"passphrase": js.PASSPHRASE}).json()["sessionToken"]
        op = {"Authorization": f"Bearer {operator}"}

        def running(name: str) -> bool:
            listed = http.get(f"{agent}/v1/components", headers=op).json()["components"]
            return next(c for c in listed if c["name"] == name)["status"] == "running"

        for name in ("gateway", "model"):
            wait(lambda name=name: running(name), f"the agent runs {name}", 120)
        key = http.post(f"{agent}/v1/auth/client-keys", headers=op,
                        json={"name": "app:workbench@root", "limits": {"writeLogs": True}})
        assert key.status_code == 201, key.text[:400]
        app_key = key.json()["token"]
        wait(lambda: any(m["id"] == MODEL for m in http.get(
            f"{url['gateway']}/v1/models", headers={"Authorization": f"Bearer {app_key}"}).json()["data"]),
            "the gateway lists the scripted model", 90)

        say("ada's job site, its worker, her key and her folder")
        python = js.install_site_host(work, js.site_host_source(args.site_host_source))
        desk = js.SiteHost(python, work / "desk" / "data")
        hosts.append(desk)
        desk.protected = [str(desk.site_dir)]
        invited = http.post(f"{control}/v1/sites/invitations", headers=owner,
                            json={"owner": ada_id, "label": "desk"})
        assert invited.status_code == 201, invited.text
        joined = desk.join(control, invited.json()["token"], "ada", "desk", js.PASSWORD, None)
        assert joined.returncode == 0, joined.stdout + joined.stderr
        site_id = desk.record()["site"]
        desk.link(ada_id, "ada", desk.account, "harness")
        desk.add_worker("ada", desk.account, None, desk.protected)
        desk.write_links()
        desk.start()
        desk.start_workers()
        desk.wait_for(http, lambda h: h.get("lastContactAt") and h.get("reason") is None,
                      "the site host never reached its root")
        desk.pin(ada_id)
        folder = work / "notes"
        (folder / "docs").mkdir(parents=True)
        (folder / "plan.txt").write_text("ada's plan: ship 2b.3b\n", encoding="utf-8", newline="\n")
        for n in range(1, FILES + 1):
            (folder / "docs" / f"f{n:02}.txt").write_text(f"file {n}\nneedle-{n}\n", encoding="utf-8",
                                                           newline="\n")

        def machine(action: str) -> int:
            if action == "approve":
                return len(desk.approve(ada_id))
            if action == "reject":
                return desk.reject_all(ada_id)
            raise ValueError(action)

        SCRIPT.machine = machine

        say("Workbench, as the agent runs an app")
        wb_python = install_workbench(work, workbench_source(args.workbench_source))
        wb_dir = work / "workbench"
        wb_dir.mkdir(exist_ok=True)
        (wb_dir / "key").write_text(app_key + "\n", encoding="utf-8")
        (wb_dir / "oidc-secret").write_text(client["clientSecret"] + "\n", encoding="utf-8")
        wb_env = {**js.clean_environment(),
                  "EUGENE_PLEXUS_APP_ID": "workbench",
                  "EUGENE_PLEXUS_APP_BIND_PORT": str(ports["workbench"]),
                  "EUGENE_PLEXUS_APP_DATA_DIR": str(wb_dir / "data"),
                  "EUGENE_PLEXUS_APP_KEY_FILE": str(wb_dir / "key"),
                  "EUGENE_PLEXUS_APP_ADMIN_TOKEN": secrets.token_urlsafe(32),
                  "EUGENE_PLEXUS_APP_GATEWAY_URL": url["gateway"],
                  "EUGENE_PLEXUS_APP_OIDC_ISSUER": f"{control}/oidc",
                  "EUGENE_PLEXUS_APP_OIDC_CLIENT_ID": client["client"]["clientId"],
                  "EUGENE_PLEXUS_APP_OIDC_SECRET_FILE": str(wb_dir / "oidc-secret"),
                  "PYTHONUNBUFFERED": "1"}
        processes.append(subprocess.Popen(
            [str(wb_python), "-m", "eugene_plexus_workbench"], cwd=wb_dir, env=wb_env,
            stdin=subprocess.DEVNULL, stdout=(wb_dir / "process.log").open("ab"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ))
        wait(lambda: http.get(f"{url['workbench']}/healthz").status_code == 200, "Workbench", 90)

        say("Chrome drives Workbench")
        shots = work / "shots"
        shots.mkdir()
        cfg = work / "browser.json"
        cfg.write_text(json.dumps({
            "workbench": url["workbench"], "fixture": fixture_url, "password": js.PASSWORD,
            "folder": str(folder), "audit": str(desk.data / "audit.jsonl"), "site": site_id,
            "files": FILES, "shots": str(shots),
            "playwright": str(REPOS / "ui" / "node_modules" / "playwright-core"),
        }), encoding="utf-8")
        done = subprocess.run(["node", str(HERE / "b3b-browser-check.mjs"), str(cfg)],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
        try:
            out = json.loads(done.stdout)
        except ValueError:
            check("B0", "Chrome ran the page", False, (done.stdout + done.stderr)[-2000:])
            out = {"checks": [], "problems": []}
        for number, claim, passed, detail in out["checks"]:
            check(number, claim, passed, detail)
        for problem in out["problems"]:
            check("P", "the page reported no problem", False, problem)
        expected = {"W0", "W0b", "W1", "W1b", "W2a", "W2b", "W2c", "W3", "W3b", "W4", "W5"}
        missing = expected - {c[0] for c in out["checks"]}
        if missing:
            check("B99", "every step reported", False, sorted(missing))
        print(f"  screenshots in {shots}", flush=True)
    finally:
        for host in hosts:
            host.stop_workers()
            host.stop()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
        fixture.shutdown()
        if args.keep:
            print(f"kept {work}", flush=True)
        else:
            shutil.rmtree(work, ignore_errors=True)
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory")
    parser.add_argument("--port", type=int)
    parser.add_argument("--workbench-source", help="an archive URL or a directory to install from")
    parser.add_argument("--site-host-source")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, Path(args.directory), args.port)
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
