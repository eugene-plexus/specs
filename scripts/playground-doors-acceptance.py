#!/usr/bin/env python3
"""The playground's other doors, driven by a real browser (U7 of
docs/design/playground-doors.md).

A throwaway signed install -- control root, agent, gateway -- with drivers
in front of the P2-P6 gates' own fixture backends, each started by its own
gate script (`--serve fixture`), so the backends are the ones those gates
already pin. The agent serves the UI; the system Chrome signs in and walks
every door with `ui/e2e/playground-doors.spec.ts`, which writes a results
file this script reads and prints.

Doors and the fixture behind each:

* Completions: P6's llama-server fixture (`coder`), with a suffix.
* Speech and Transcription: P3's OpenRouter-shaped fixture (`audio`), and
  its OpenAI-shaped `/oai` for a translation (`oai-audio/whisper-1`).
  Speech is tried through the agent's proxy and direct to the gateway, so
  the `x-eugene-plexus-*` headers are proved readable across origins.
* Images: P4's fixture (`pictures/acme/flux`), and an edit with a mask on
  its `/oai` (`oai-images/gpt-image-1`).
* Video: P5's fixture (`videos/acme/grok`), a job polled and fetched.
* Chat: P2's fixture (`media/acme/hears`, `reads`, `speaks`): a recording,
  a PDF, and a spoken reply.

Run from the agent's venv (it holds every component and the UI wheel):

    python scripts/playground-doors-acceptance.py [--build-ui]

`--build-ui` runs `npm run build:python` in ../ui first; without it the
script refuses to run against an export that has no doors in it, since a
green run against the previous build would prove nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

SPECS = Path(__file__).resolve().parent.parent
UI = SPECS.parent / "ui"
NODE_NAME = "doors-agent"
FOX = SPECS / "scripts" / "fixtures" / "p2-fox.mp3"
#: Which gate serves which fixture, by the name the drivers call it.
FIXTURES = {
    "fx-media": "p2-media-acceptance.py",
    "fx-audio": "p3-audio-acceptance.py",
    "fx-images": "p4-images-acceptance.py",
    "fx-videos": "p5-videos-acceptance.py",
    "fx-coder": "p6-acceptance.py",
}
#: The browser checks, in the order the spec runs them.
CHECKS = [
    "completion",
    "speech-proxy",
    "speech-direct",
    "transcription",
    "translation",
    "image-generate",
    "image-edit",
    "video",
    "chat-audio-in",
    "chat-pdf",
    "chat-spoken",
]


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(
            settings=Settings(config_file=directory / "agent.yaml", default_topology=False, bind_port=port)
        )
    elif kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(
            settings=Settings(
                config_file=directory / "gateway.yaml", metrics_file=directory / "metrics.sqlite3", **bootstrap
            )
        )
    else:
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(settings=Settings(config_file=directory / "driver.yaml", **bootstrap))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def served_export_has_doors() -> tuple[bool, str]:
    """Whether the UI the agent will serve is a build with the doors in it."""
    try:
        import eugene_plexus_ui
    except ImportError:
        return False, "eugene-plexus-ui is not installed in this environment"
    root = Path(eugene_plexus_ui.static_dir())
    if not root.is_dir():
        return False, f"{root} is not a directory"
    for chunk in root.rglob("*.js"):
        if "completion-door" in chunk.read_text(encoding="utf-8", errors="ignore"):
            return True, str(root)
    return False, f"no chunk under {root} mentions completion-door"


def exercise(directory: Path) -> int:
    from eugene_plexus_agent.node_identity import NodeIdentityStore
    from eugene_plexus_agent.trust import NodeTrust

    drivers = ["media", "audio", "oai-audio", "pictures", "oai-images", "videos", "coder"]
    names = ["control", "agent", "gateway", *FIXTURES, *drivers]
    sockets = [socket.socket() for _ in names]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = dict(zip(names, [sock.getsockname()[1] for sock in sockets], strict=True))
    for sock in sockets:
        sock.close()
    processes: dict[str, subprocess.Popen[bytes]] = {}
    logs = []
    client = httpx.Client(timeout=120, trust_env=False)
    passphrase = secrets.token_urlsafe(24)

    def url(name: str) -> str:
        return f"http://127.0.0.1:{ports[name]}"

    def call(name, method, path, token=None, **kwargs):
        return client.request(
            method, url(name) + path, headers={"Authorization": "Bearer " + token} if token else None, **kwargs
        )

    def write(name, filename, data):
        work = directory / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(
            json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data), encoding="utf-8"
        )

    def wait(check, label, seconds=45):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                last = e
            time.sleep(0.2)
        raise AssertionError(f"timed out: {label} ({last!r})")

    def start(name, extra_env=None, script: Path | None = None, kind: str | None = None):
        work = directory / name
        work.mkdir(exist_ok=True)
        output = (work / "process.log").open("ab")
        logs.append(output)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env.pop("OPENAI_API_KEY", None)
        env.pop("ELEVENLABS_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        env.update(extra_env or {})
        processes[name] = subprocess.Popen(
            [sys.executable, str(script or Path(__file__).resolve()), "--serve", kind or name,
             "--directory", str(work), "--port", str(ports[name])],
            cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        wait(lambda: call(name, "GET", "/healthz").status_code == 200, name)

    def login(name):
        response = call(name, "POST", "/v1/auth/login", json={"passphrase": passphrase})
        response.raise_for_status()
        return response.json()["sessionToken"]

    try:
        # --- a signed one-node install ------------------------------------------
        start("control")
        call("control", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        root_session = login("control")
        write("agent", "agent.yaml", {
            "firstRunComplete": True, "updateChecks": False,
            "advertiseUrl": url("agent"),
            "securityMode": "prompt_on_startup", "components": [],
        })
        start("agent")
        call("agent", "POST", "/v1/auth/initialize", json={"passphrase": passphrase}).raise_for_status()
        standalone = login("agent")
        join = call("control", "POST", "/v1/nodes/join-token", root_session, json={"grants": ["gateway"]})
        join.raise_for_status()
        call("agent", "POST", "/v1/node/enroll", standalone, json={
            "controlUrl": url("control"), "token": join.json()["token"], "name": NODE_NAME,
        }).raise_for_status()
        operator = login("agent")

        agent_dir = directory / "agent"
        store = NodeIdentityStore(agent_dir / "node.yaml")
        store.load()
        trust = NodeTrust(store, agent_dir / "trust_bundle.json")
        trust.load()

        def bootstrap(sub):
            token, _ = trust.mint_service(sub=sub, audience=trust.recipient)
            return {
                "agent_url": url("agent"),
                "trust_bundle_file": str(trust.bundle_path),
                "trust_authority": trust.authority,
                "auth_recipient": trust.recipient,
                "service_token": token,
            }

        def register(name, kind):
            call("agent", "POST", "/v1/components", operator, json={
                "name": name, "kind": kind, "url": url(name),
            }).raise_for_status()

        def driver(name, config, env):
            write(name, "bootstrap.json", bootstrap("inference-driver"))
            write(name, "driver.yaml", config)
            start(name, env)
            register(name, "inference-driver")

        for name, gate in FIXTURES.items():
            start(name, script=SPECS / "scripts" / gate, kind="fixture")
        or_key = {"OPENAI_API_KEY": "fixture-not-a-key"}
        driver("media", {"provider": "openrouter", "baseUrl": url("fx-media")}, or_key)
        driver("audio", {"provider": "openrouter", "baseUrl": url("fx-audio")}, or_key)
        driver("oai-audio", {"provider": "openai", "baseUrl": url("fx-audio") + "/oai"}, or_key)
        driver("pictures", {"provider": "openrouter", "baseUrl": url("fx-images")}, or_key)
        driver("oai-images", {"provider": "openai", "baseUrl": url("fx-images") + "/oai"},
               {"OPENAI_API_KEY": "fixture-oai"})
        driver("videos", {"provider": "openrouter", "baseUrl": url("fx-videos")}, or_key)
        driver("coder", {"provider": "openai_compat_custom", "baseUrl": url("fx-coder") + "/llama",
                         "modelId": "coder", "backendLocality": "local"}, {})
        write("gateway", "bootstrap.json", bootstrap("gateway"))
        write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2})
        start("gateway")
        # The browser reaches the gateway through the agent's proxy, which
        # finds it in the agent's topology.
        register("gateway", "gateway")

        wanted = {
            "coder", "audio/acme/kokoro", "audio/acme/whisper", "oai-audio/whisper-1", "pictures/acme/flux",
            "oai-images/gpt-image-1", "videos/acme/grok", "media/acme/hears", "media/acme/reads",
            "media/acme/speaks",
        }

        def routable():
            data = call("gateway", "GET", "/v1/models", operator).json().get("data", [])
            return wanted <= {m["id"] for m in data}

        wait(routable, "every door's model is routable", 90)
        print("INFO every door's model is routable through the gateway", flush=True)

        # --- the browser ----------------------------------------------------------
        results_file = directory / "browser-results.json"
        npx = "npx.cmd" if os.name == "nt" else "npx"
        run = subprocess.run(
            [npx, "playwright", "test", "e2e/playground-doors.spec.ts", "--reporter=line"],
            cwd=UI,
            env={
                **os.environ,
                "EP_UI_URL": url("agent"),
                "EP_PASSPHRASE": passphrase,
                "EP_GATEWAY_URL": url("gateway"),
                "EP_FOX": str(FOX),
                "EP_RESULTS_FILE": str(results_file),
            },
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
        )
        tail = (run.stdout + run.stderr).strip().splitlines()[-25:]
        results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
        passed = 0
        for check in CHECKS:
            found = results.get(check)
            if found is None:
                print(f"FAIL {check}: not reached", flush=True)
            elif found["ok"]:
                passed += 1
                print(f"PASS {check}: {found['detail']}", flush=True)
            else:
                print(f"FAIL {check}: {found['detail']}", flush=True)
        if run.returncode != 0 or passed != len(CHECKS):
            print("\n".join(tail), flush=True)
            print(f"{passed} of {len(CHECKS)} PASS; playwright exited {run.returncode}", flush=True)
            return 1
        print(f"{passed} PASS", flush=True)
        return 0
    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        for output in logs:
            output.close()


def main() -> None:
    # Playwright's line reporter prints characters a Windows console's code
    # page cannot, and a crash while printing them hid the results once.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--build-ui", action="store_true")
    parser.add_argument("--keep", action="store_true", help="keep the throwaway install's directory")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return
    if args.build_ui:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run([npm, "run", "build:python"], cwd=UI, check=True)
    ok, where = served_export_has_doors()
    if not ok:
        raise SystemExit(f"The UI this agent would serve has no doors in it ({where}). Run with --build-ui.")
    print(f"INFO the agent serves the UI export at {where}", flush=True)
    if args.keep:
        directory = Path(tempfile.mkdtemp(prefix="playground-doors-"))
        print(f"INFO keeping {directory}", flush=True)
        sys.exit(exercise(directory))
    directory = Path(tempfile.mkdtemp(prefix="playground-doors-"))
    try:
        code = exercise(directory)
    finally:
        remove_when_released(directory)
    sys.exit(code)


def remove_when_released(directory: Path, seconds: float = 15) -> None:
    """Delete the throwaway install once Windows lets go of its files.

    A process the agent started can outlive it by a moment and hold
    `agent/process.log`, so a single delete raced it and turned 11 PASS
    into a traceback (2026-09-29). Retry briefly; if the files are still
    held, say where they are rather than failing a run that passed.
    """
    deadline = time.perf_counter() + seconds
    while True:
        try:
            shutil.rmtree(directory)
            return
        except FileNotFoundError:
            return
        except OSError as e:
            if time.perf_counter() >= deadline:
                print(f"WARN could not remove {directory}: {e}", flush=True)
                return
            time.sleep(0.5)


if __name__ == "__main__":
    main()
