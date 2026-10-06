#!/usr/bin/env python3
"""PB2 acceptance: a browser builds, saves and launches a profile (profile-builder.md §8).

A throwaway standalone agent on free ports supervises its own library, with
a CPU-only llama.cpp build (`--engine DIR`, a managed build directory with its
install.json, holding llama-server, llama-bench, llama-fit-params and
llama-perplexity) and one small GGUF
(`--model FILE`) copied into the library's folder. The managed engine store
is pointed at an empty directory, so nothing reaches the live install's
engines, and a CPU build never touches the graphics card.

The system Chrome signs in and runs `ui/e2e/profile-builder.spec.ts`: open
the builder on the model's page, start a Max build, wait for the result,
save it, launch it. Then this script checks, against the agent's and the
library's own APIs, that the launched runtime's flags are the saved
profile's flags and that the profile carries the build's record.

Run from the agent's venv (it holds every component and the UI, editable):

    python scripts/pb2-browser-acceptance.py --engine DIR --model FILE [--build-ui] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
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
CHECKS = ["open", "preflight", "start", "result", "save", "measured", "launch", "running", "phone"]
MARKER = "Build settings for this machine"
TOOLS = ("llama-server", "llama-bench", "llama-fit-params", "llama-perplexity")


def say(verdict: str, message: str) -> None:
    print(f"{verdict} {message}", flush=True)


def served_export_has_builder() -> tuple[bool, str]:
    """Whether the UI the agent will serve is a build with the builder in it."""
    try:
        import eugene_plexus_ui
    except ImportError:
        return False, "eugene-plexus-ui is not installed in this environment"
    root = Path(eugene_plexus_ui.static_dir())
    if not root.is_dir():
        return False, f"{root} is not a directory"
    for chunk in root.rglob("*.js"):
        if MARKER in chunk.read_text(encoding="utf-8", errors="ignore"):
            return True, str(root)
    return False, f"no chunk under {root} carries {MARKER!r}"


def free_ports(count: int) -> list[int]:
    sockets = [socket.socket() for _ in range(count)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    ports = [sock.getsockname()[1] for sock in sockets]
    for sock in sockets:
        sock.close()
    return ports


def exercise(directory: Path, engine: Path, model: Path) -> int:
    agent_port, library_port = free_ports(2)
    agent_url = f"http://127.0.0.1:{agent_port}"
    passphrase = secrets.token_urlsafe(24)
    failures = 0

    # The engine and the model, as this run's own copies. The build goes
    # into this run's managed engine store (`<root>/llama_cpp/<version>/`
    # with its install.json), which is how an install finds llama.cpp;
    # engineBinaryRoots only says which paths a runtime may name.
    meta = json.loads((engine / "install.json").read_text(encoding="utf-8"))
    engine_dir = directory / "engines" / "llama_cpp" / str(meta["version"])
    shutil.copytree(engine, engine_dir)
    if meta.get("variant") != "win-cpu-x64" and "cpu" not in str(meta.get("variant")):
        raise SystemExit(f"{engine} is a {meta.get('variant')} build, not a CPU-only one")
    models = directory / "models"
    models.mkdir()
    shutil.copy2(model, models / model.name)

    (directory / "library.yaml").write_text(
        yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
    )
    (directory / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "securityMode": "prompt_on_startup",
                "components": [
                    {
                        "name": "library",
                        "kind": "library",
                        "url": f"http://127.0.0.1:{library_port}",
                        "spawn": {"configFile": str(directory / "library.yaml")},
                    }
                ],
                "runtimes": [],
            }
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(
        {
            "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(directory / "agent.yaml"),
            "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
            "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
            "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(directory / "engines"),
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "PYTHONUNBUFFERED": "1",
        }
    )
    env.pop("OPENAI_API_KEY", None)
    log = (directory / "agent.log").open("wb")
    agent = subprocess.Popen(
        [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
        cwd=directory,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    client = httpx.Client(base_url=agent_url, timeout=60, trust_env=False)

    def wait(check, label: str, seconds: float = 90):  # type: ignore[no-untyped-def]
        deadline = time.perf_counter() + seconds
        last: object = None
        while time.perf_counter() < deadline:
            try:
                got = check()
                if got:
                    return got
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                last = e
            time.sleep(0.5)
        raise AssertionError(f"timed out: {label} ({last!r})")

    try:
        wait(lambda: client.get("/healthz").status_code == 200, "the agent answers")
        token = client.post("/v1/auth/initialize", json={"passphrase": passphrase}).json()[
            "sessionToken"
        ]
        client.headers["Authorization"] = f"Bearer {token}"
        library = httpx.Client(
            base_url=f"http://127.0.0.1:{library_port}",
            timeout=60,
            trust_env=False,
            headers={"Authorization": f"Bearer {token}"},
        )
        wait(lambda: library.get("/healthz").status_code == 200, "the library answers")
        library.post("/v1/scan")
        found = wait(
            lambda: [m for m in library.get("/v1/models").json()["models"] if m["name"] == model.stem],
            "the model is catalogued",
        )
        model_id = found[0]["id"]
        say("PASS", f"agent :{agent_port}, library :{library_port}, {model.name} catalogued as {model_id}")
        engines = client.get("/v1/engines").json()["engines"]
        llama = next(e for e in engines if e["engine"] == "llama_cpp")
        assert llama["available"], llama
        say("PASS", f"llama.cpp available from this run's own CPU build ({llama.get('version')})")

        results_file = directory / "browser-results.json"
        npx = "npx.cmd" if os.name == "nt" else "npx"
        run = subprocess.run(
            [npx, "playwright", "test", "e2e/profile-builder.spec.ts", "--reporter=line"],
            cwd=UI,
            env={
                **os.environ,
                "EP_UI_URL": agent_url,
                "EP_PASSPHRASE": passphrase,
                "EP_MODEL_ID": model_id,
                "EP_RESULTS_FILE": str(results_file),
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=40 * 60,
        )
        results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}
        for check in CHECKS:
            found_check = results.get(check)
            if found_check is None:
                failures += 1
                say("FAIL", f"browser {check}: not reached")
            elif found_check["ok"]:
                say("PASS", f"browser {check}: {found_check['detail']}")
            else:
                failures += 1
                say("FAIL", f"browser {check}: {found_check['detail']}")
        if run.returncode != 0:
            print("\n".join((run.stdout + run.stderr).strip().splitlines()[-30:]), flush=True)

        # --- the API side of "the launched row matches what was saved" -------
        profiles = library.get(f"/v1/models/{model_id}/profiles").json()["profiles"]
        built = [p for p in profiles if p.get("builtBy")]
        if len(built) != 1:
            failures += 1
            say("FAIL", f"one built profile in the library, found {len(built)}")
        else:
            profile = built[0]
            record = profile["builtBy"]
            builds = client.get("/v1/profile-builds").json()["builds"]
            build = next((b for b in builds if b["id"] == record["buildId"]), None)
            checks = {
                "the record names a build this node ran": build is not None,
                "the build completed": bool(build) and build["state"] == "completed",
                "the record's flags are the profile's builder flags": all(
                    profile["flags"].get(k) == v for k, v in record["flags"].items()
                ),
                "no gpuLayers: placement is llama.cpp's": "gpuLayers" not in profile["flags"],
                "Max chose the full-precision cache": record["flags"].get("cacheType") == "f16",
            }
            for label, passed in checks.items():
                failures += 0 if passed else 1
                say("PASS" if passed else "FAIL", f"{label} ({json.dumps(record['flags'])})")
            runtimes = client.get("/v1/runtimes").json()["runtimes"]
            launched = [r for r in runtimes if r.get("modelPath", "").endswith(model.name)]
            if not launched:
                failures += 1
                say("FAIL", "a runtime was declared for the model")
            else:
                runtime = launched[0]
                same = runtime.get("flags") == profile["flags"]
                failures += 0 if same else 1
                say(
                    "PASS" if same else "FAIL",
                    f"the launched runtime's flags are the saved profile's: {json.dumps(runtime.get('flags'))}",
                )
                ready = runtime.get("status") == "ready"
                failures += 0 if ready else 1
                say("PASS" if ready else "FAIL", f"the runtime is {runtime.get('status')}")
                base = str(runtime.get("url") or "").rstrip("/")
                answer = (
                    httpx.post(
                        f"{base}/completion",
                        json={"prompt": "def add(a, b):", "n_predict": 8},
                        timeout=60,
                        trust_env=False,
                    )
                    if base
                    else None
                )
                served = answer is not None and answer.status_code == 200
                failures += 0 if served else 1
                say("PASS" if served else "FAIL", "the launched engine answers a completion")
        passed = len(CHECKS) - sum(1 for c in CHECKS if not results.get(c, {}).get("ok"))
        say("INFO", f"browser {passed} of {len(CHECKS)}; {failures} failure(s) in all")
        return 0 if failures == 0 else 1
    finally:
        # Asked to stop, not killed: a hard kill on Windows skips the
        # agent's shutdown and orphans the library and the engine it
        # supervises, which then hold their ports (install-paths §12).
        if os.name == "nt":
            agent.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            agent.terminate()
        try:
            agent.wait(timeout=60)
        except subprocess.TimeoutExpired:
            agent.kill()
            say("WARN", "the agent did not stop in 60 s and was killed")
        log.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True, help="a CPU-only llama.cpp build")
    parser.add_argument("--model", type=Path, required=True, help="a small GGUF")
    parser.add_argument("--build-ui", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    missing = [t for t in TOOLS if not any(args.engine.glob(f"{t}*"))]
    if missing:
        raise SystemExit(f"{args.engine} lacks {', '.join(missing)}")
    if not (args.engine / "install.json").is_file():
        raise SystemExit(f"{args.engine} is not a managed build (no install.json)")
    if args.build_ui:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run([npm, "run", "build:python"], cwd=UI, check=True)
    ok, where = served_export_has_builder()
    if not ok:
        raise SystemExit(f"The UI this agent would serve has no builder in it ({where}). Run with --build-ui.")
    say("INFO", f"the agent serves the UI export at {where}")
    directory = Path(tempfile.mkdtemp(prefix="ep-pb2-"))
    try:
        code = exercise(directory, args.engine.resolve(), args.model.resolve())
    finally:
        if args.keep:
            say("INFO", f"kept {directory}")
        else:
            shutil.rmtree(directory, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
