"""LS5 acceptance: preparation is a job on the engine's node.

library-sources-and-engines.md, slice LS5 (§4.6, calls B43-B56 in §6.6). A
throwaway standalone agent on free loopback ports supervises its own Library
over a folder holding both shards of the GGUF Strata's list names IQ2_XS
(headers only). Strata is a borrowed installation (`strataServer`) whose
`setup.py` is a stand-in taking upstream's arguments and writing what
upstream's writes, where it writes it: the pack, tokenizer and MTP helper
(itself a GGUF) into the data folder, `strata-<tag>.json` with absolute paths
and a start script into its own folder, `.done` marks beside the shards. Its
`serve/server.py` answers `/health` as Strata does and keeps the launch
configuration it was handed. Its `.venv` is a real, empty venv, and its
preparation tools (`third_party/llama.cpp`) are already there, so nothing
is downloaded. No real Strata, no model, no GPU.

  E1  the node's Strata publishes, per model on its list, the disk its setup
      needs on this node and the contexts it offers;
  P1  *Prepare for Strata* (a run operation asking for it, 32K context) goes
      checking -> preparing -> settings -> launching -> loading -> ready,
      and says where it is while it prepares, in setup's words;
  P2  setup ran non-interactively, with its own settings folder, the
      context asked for, text only;
  P3  on disk: `Strata-data` beside the GGUF's folder with the engine-files
      marker, Strata's configuration moved there with relative paths and no
      `cwd`, the expert profile copied beside the pack, nothing left in the
      engine's folder, the GGUF unchanged;
  P4  the Library lists the prepared model (and not the MTP helper, a GGUF),
      linked to the GGUF; the run went on with it: its profile is Strata's,
      its runtime names the provenance file, and Strata was handed the
      prepared files at 32K;
  P5  setup's warnings are kept on the operation;
  R1  preparing again with another context replaces its own configuration
      and provenance, one model of that name;
  U1  Strata cannot be uninstalled while it prepares;
  C1  cancelling the operation stops setup, and lists nothing;
  F1  a setup that stops fails the run at *prepare*, in setup's own words.

Clears every ambient EUGENE_PLEXUS_* variable, so it is safe beside a live
install. Run with the agent and library installed (editable is fine).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any

import httpx
import yaml

FAILURES: list[str] = []
SUFFIX = ".eugene-prepared.json"
REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
FIRST = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
SECOND = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf"
PREPARED = "qwen3.8-flash-next-iq2_xs"

# Upstream's setup, standing in: its arguments, its outputs where it puts
# them, its `[!]`/`[X]`/`=== Step` lines. A `SLOW` file in the data folder
# makes it wait (for C1 and U1), a `FAIL` file makes it stop (F1).
FAKE_SETUP = r'''
import argparse, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
for flag in ("--family", "--model", "--gguf-dir", "--data-dir", "--context", "--gpu", "--vision",
             "--experimental-speed-projection"):
    ap.add_argument(flag)
for flag in ("--no-browser", "--no-start", "--yes"):
    ap.add_argument(flag, action="store_true")
a = ap.parse_args()
data, gguf = Path(a.data_dir), Path(a.gguf_dir)
data.mkdir(parents=True, exist_ok=True)
calls = data / "setup-calls.jsonl"
with calls.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "pid": os.getpid(),
                        "appdata": os.environ.get("APPDATA"),
                        "xdg": os.environ.get("XDG_CONFIG_HOME")}) + "\n")
(Path(os.environ["APPDATA"]) / "Strata").mkdir(parents=True, exist_ok=True)
print("=== Step 1: checking your PC ===", flush=True)
print("  [!]  Windows' page file is 2.0 GB", flush=True)
if (data / "SLOW").exists():
    for _ in range(600):
        time.sleep(0.1)
if (data / "FAIL").exists():
    print("\n  [X]  not enough free disk space in " + str(gguf) + ": need ~44 GB", flush=True)
    print("       use --models-dir on a bigger drive", flush=True)
    sys.exit(1)
print("=== Step 6: preparing the model for Strata ===", flush=True)
time.sleep(6)  # long enough to be seen preparing: the worker reports every ~2 s
tag = ("" if a.family == "qwen" else a.family + "-") + a.model
tag = tag.lower()
pack = data / "packs" / tag
(pack / "tokenizer").mkdir(parents=True, exist_ok=True)
for name in ("vocab.json", "merges.txt", "token_type.json"):
    (pack / "tokenizer" / name).write_text("{}")
(pack / "native_experts.txt").write_text("x" * 4096)
rt = data / "mtp" / "rt"
rt.mkdir(parents=True, exist_ok=True)
(rt / "experts.bin").write_bytes(b"\0" * 65536)
# The MTP helper is itself a GGUF, as upstream's is.
head = b"GGUF" + (3).to_bytes(4, "little") + (0).to_bytes(8, "little") + (0).to_bytes(8, "little")
(data / "mtp" / "mtp-q2_0.gguf").write_bytes(head)
shards = sorted(gguf.glob("*IQ2_XS-*-of-*.gguf"))
for s in shards:
    s.with_name(s.name + ".done").write_text("whole")
args = ["--pack", str(pack), "--native", str(shards[0]), "--ple-gguf", str(shards[-1]),
        "--expert-profile", str(ROOT / "data" / "expert-profile.bin"), "--expert-cache", "auto",
        "--prefill", "auto", "--spec", "4", "--spec-min-p", "0.5", "--mtp", str(rt),
        "--max-context", str(a.context or 65536), "--kv", "int8"]
cfg = {"exe": str(ROOT / "engine" / "strata.exe"), "args": args, "cwd": str(ROOT),
       "tokenizer": str(pack / "tokenizer"), "model_name": "qwen3.8-flash-next-" + a.model.lower(),
       "log": str(ROOT / f"strata-{tag}.log"), "lib_dirs": [], "port": 8080, "draft_vocab": "cjk"}
(ROOT / f"strata-{tag}.json").write_text(json.dumps(cfg))
(ROOT / f"run-{tag}.bat").write_text("@echo off")
print("All set.", flush=True)
'''

# The stand-in for Strata's `serve/server.py`, as LS3's acceptance has it.
FAKE_SERVER = '''
import argparse, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
for flag in ("--engine", "--config", "--host"):
    parser.add_argument(flag)
parser.add_argument("--port", type=int)
args = parser.parse_args()
config = json.loads(Path(args.config).read_text(encoding="utf-8"))
(Path(__file__).parent / "seen" / (config["model_name"] + ".json")).write_text(
    json.dumps({"engine": args.engine, "config": config}), encoding="utf-8"
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = {"service": "strata", "loaded": True, "max_context": 32768}
        elif self.path == "/v1/models":
            body = {"object": "list", "data": [{"id": config["model_name"], "object": "model"}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass


ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
'''


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def free_ports(count: int) -> list[int]:
    socks = [socket.socket() for _ in range(count)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def _gguf_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def write_gguf(path: Path, kv: dict[str, Any]) -> None:
    body = bytearray(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0) + struct.pack("<Q", len(kv)))
    for key, value in kv.items():
        body += _gguf_string(key)
        if isinstance(value, str):
            body += struct.pack("<I", 8) + _gguf_string(value)
        else:
            body += struct.pack("<I", 4) + struct.pack("<I", value)
    path.write_bytes(bytes(body))


def fake_strata(root: Path) -> Path:
    """A borrowed Strata install: setup, server, engine, data, tools, venv."""
    server = root / "serve" / "server.py"
    server.parent.mkdir(parents=True)
    server.write_text(FAKE_SERVER, encoding="utf-8")
    (root / "serve" / "seen").mkdir()
    (root / "setup.py").write_text(FAKE_SETUP, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True
    )
    native = root / "engine" / ("strata.exe" if os.name == "nt" else "strata")
    native.parent.mkdir()
    native.touch()
    (root / "data").mkdir()
    (root / "data" / "expert-profile.bin").write_bytes(b"\1" * 256)
    llama = root / "third_party" / "llama.cpp"
    (llama / "ggml").mkdir(parents=True)
    (llama / "ggml" / "CMakeLists.txt").write_text("", encoding="utf-8")
    (llama / "gguf-py").mkdir()
    return server


def alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def same(given: str, expected: Path) -> bool:
    try:
        return Path(given).is_absolute() and os.path.samefile(given, expected)
    except OSError:
        return False


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ep-ls5-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        agent_port, library_port = free_ports(2)
        models = directory / "models"
        folder = models / REPO.replace("/", os.sep)
        folder.mkdir(parents=True)
        kv = {"general.architecture": "qwen4exp", "general.name": "Flash Next", "general.file_type": 20}
        write_gguf(folder / FIRST, kv)
        write_gguf(folder / SECOND, {"general.architecture": "qwen4exp"})
        original = (folder / FIRST).read_bytes()
        strata_root = directory / "strata"
        server = fake_strata(strata_root)
        data = models / "Strata-data"
        (directory / "engines").mkdir()
        (directory / "library.yaml").write_text(
            yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
        )
        (directory / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
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
        log_path = directory / "agent.log"
        log = log_path.open("wb")
        agent = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
            cwd=directory,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        client = httpx.Client(base_url=f"http://127.0.0.1:{agent_port}", timeout=60, trust_env=False)

        def wait(fn, label: str, seconds: float = 90):  # type: ignore[no-untyped-def]
            deadline = time.perf_counter() + seconds
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    got = fn()
                    if got:
                        return got
                except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as e:
                    last = e
                time.sleep(0.25)
            raise AssertionError(f"timed out: {label} ({last!r})")

        try:
            wait(lambda: client.get("/healthz").status_code == 200, "the agent answers")
            token = client.post(
                "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
            ).json()["sessionToken"]
            client.headers["Authorization"] = f"Bearer {token}"
            proxy = "/api/proxy/library"
            wait(lambda: client.get(f"{proxy}/healthz").status_code == 200, "the library answers")
            patched = client.patch("/v1/config", json={"strataServer": str(server)})
            if patched.status_code != 200:
                raise AssertionError(f"strataServer refused: {patched.text[:300]}")

            def scanned() -> dict[str, dict[str, Any]]:
                client.post(f"{proxy}/v1/scan", json={"full": True})
                wait(
                    lambda: client.get(f"{proxy}/v1/scan").json()["state"] != "scanning",
                    "the scan finishes",
                )
                return {m["name"]: m for m in client.get(f"{proxy}/v1/models").json()["models"]}

            gguf_name = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS"  # a split GGUF is named without its shard
            listed = wait(lambda: (lambda ms: ms if gguf_name in ms else None)(scanned()), "the GGUF is listed")
            gguf = listed[gguf_name]
            node = client.get("/v1/node").json().get("name")
            print(f"agent :{agent_port}, library :{library_port}, node {node!r}", flush=True)

            # E1 -----------------------------------------------------------
            engines = {e["engine"]: e for e in client.get("/v1/engines").json()["engines"]}
            strata = engines["strata"]
            entry = next((m for m in strata.get("supportedModels") or [] if m["id"] == "IQ2_XS"), {})
            preparation = entry.get("preparation") or {}
            check(
                "E1 Strata is available from its borrowed install and publishes each preparation's disk and contexts",
                strata["available"] is True
                and isinstance(preparation.get("diskBytes"), int)
                and preparation["diskBytes"] >= 8_000_000_000
                and 32768 in (preparation.get("contexts") or []),
                {"available": strata["available"], "preparation": preparation},
            )

            def submit(op: str, **preparation: Any) -> None:
                body = {"modelId": gguf["id"], "node": node, "preparation": {"engine": "strata", **preparation}}
                put = client.put(f"{proxy}/v1/run-operations/{op}", json=body)
                if put.status_code != 202:
                    raise AssertionError(f"run refused: {put.status_code} {put.text[:300]}")

            def record(op: str) -> dict[str, Any]:
                got: dict[str, Any] = client.get(f"{proxy}/v1/run-operations/{op}").json()
                return got

            def until(op: str, steps: tuple[str, ...], seconds: float = 180) -> dict[str, Any]:
                return wait(
                    lambda: (lambda r: r if r["step"] in steps else None)(record(op)),
                    f"run {op} reaches {steps}",
                    seconds,
                )

            # P1 -----------------------------------------------------------
            submit("ls5-prepare", contextSize=32768)
            preparing = until("ls5-prepare", ("preparing", "failed", "ready"), 120)
            seen_steps: set[str] = set()
            status: dict[str, Any] = {}
            deadline = time.perf_counter() + 120
            while time.perf_counter() < deadline:
                now = record("ls5-prepare")
                if now["step"] == "preparing" and now.get("preparation"):
                    status = now["preparation"]
                    seen_steps.add(status.get("step") or "")
                if now["step"] not in ("checking", "preparing"):
                    break
                time.sleep(0.2)
            check(
                "P1 the run prepares, saying where it is in setup's own words",
                preparing["step"] == "preparing"
                and any("preparing the model for Strata" in s for s in seen_steps)
                and status.get("bytesNeeded") == preparation.get("diskBytes"),
                {"steps": sorted(seen_steps), "status": status, "record": preparing.get("error")},
            )
            done = until("ls5-prepare", ("ready", "failed", "cancelled"))
            check(
                "P1 then settings, launch and load: ready, on Strata",
                done["step"] == "ready" and done.get("engine") == "strata",
                {k: done.get(k) for k in ("step", "engine", "error", "failedStep")},
            )

            # P2 -----------------------------------------------------------
            calls = [json.loads(line) for line in (data / "setup-calls.jsonl").read_text().splitlines()]
            argv = calls[0]["argv"] if calls else []
            pairs = dict(zip(argv[::2], argv[1::2]))
            check(
                "P2 setup ran non-interactively for IQ2_XS at 32K, text only, with its own settings folder",
                "--yes" in argv
                and "--no-start" in argv
                and pairs.get("--family") == "qwen"
                and pairs.get("--model") == "IQ2_XS"
                and argv[argv.index("--context") + 1] == "32768"
                and argv[argv.index("--vision") + 1] == "no"
                and argv[argv.index("--experimental-speed-projection") + 1] == "off"
                and calls[0]["appdata"] != os.environ.get("APPDATA")
                and not Path(calls[0]["appdata"]).exists(),
                calls[:1],
            )

            # P3 -----------------------------------------------------------
            config_path = data / "strata-iq2_xs.json"
            config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
            args = config.get("args") or []
            check(
                "P3 Strata-data has the marker and Strata's configuration, paths relative, no cwd",
                (data / ".eugene-engine-files").is_file()
                and "cwd" not in config
                and args[args.index("--pack") + 1] == "packs/iq2_xs"
                and args[args.index("--native") + 1] == f"../{REPO}/{FIRST}"
                and config.get("tokenizer") == "packs/iq2_xs/tokenizer",
                config,
            )
            check(
                "P3 the expert profile is copied beside the pack, nothing is left in the engine's folder",
                (data / "packs" / "iq2_xs" / "expert-profile.bin").read_bytes() == b"\1" * 256
                and args[args.index("--expert-profile") + 1] == "packs/iq2_xs/expert-profile.bin"
                and not list(strata_root.glob("strata-*.json"))
                and not list(strata_root.glob("run-*.bat")),
                sorted(p.name for p in strata_root.iterdir()),
            )
            check(
                "P3 the GGUF is unchanged (setup's .done marks beside it)",
                (folder / FIRST).read_bytes() == original and (folder / (FIRST + ".done")).is_file(),
            )

            # P4 -----------------------------------------------------------
            listed = scanned()
            prepared = listed.get(PREPARED) or {}
            provenance_path = data / f"{PREPARED}{SUFFIX}"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
            check(
                "P4 the Library lists the prepared model, linked to its GGUF; the MTP helper is not a model",
                prepared.get("format") == "prepared"
                and prepared.get("status") == "present"
                and (prepared.get("prepared") or {}).get("sourceModelId") == gguf["id"]
                and provenance.get("entry") == "strata-iq2_xs.json"
                and provenance.get("recipe") == "strata-prepare"
                and provenance.get("recipeVersion") == "v0.1.39"
                and (provenance.get("source") or {}).get("repoId") == REPO
                and "mtp-q2_0" not in listed,
                {"model": prepared, "provenance": provenance, "names": sorted(listed)},
            )
            check(
                "P4 the run went on with the prepared model, from the GGUF",
                (done.get("model") or {}).get("id") == prepared.get("id")
                and (done.get("preparedFrom") or {}).get("id") == gguf["id"],
                {k: done.get(k) for k in ("model", "preparedFrom")},
            )
            profiles = client.get(f"{proxy}/v1/models/{prepared.get('id')}/profiles").json()["profiles"]
            runtimes = {r["name"]: r for r in client.get("/v1/runtimes").json()["runtimes"]}
            runtime = runtimes.get(done.get("runtime") or "") or {}
            seen_file = server.parent / "seen" / f"{PREPARED}.json"
            seen = json.loads(seen_file.read_text(encoding="utf-8")) if seen_file.exists() else {}
            handed = (seen.get("config") or {}).get("args") or []
            check(
                "P4 its profile is Strata's, its runtime the provenance file, Strata handed the prepared files at 32K",
                [p["engine"] for p in profiles] == ["strata"]
                and Path(runtime.get("modelPath") or "") == provenance_path
                and runtime.get("status") == "ready"
                and same(handed[handed.index("--pack") + 1], data / "packs" / "iq2_xs")
                and same(handed[handed.index("--native") + 1], folder / FIRST)
                and handed[handed.index("--max-context") + 1] == "32768",
                {"profiles": profiles, "runtime": runtime, "handed": handed},
            )

            # P5 -----------------------------------------------------------
            check(
                "P5 setup's warnings are kept on the operation",
                "Windows' page file is 2.0 GB" in ((done.get("preparation") or {}).get("warnings") or []),
                done.get("preparation"),
            )

            # R1 -----------------------------------------------------------
            if done.get("runtime"):
                client.post(f"/v1/runtimes/{done['runtime']}/stop")
            submit("ls5-again", contextSize=8192)
            again = until("ls5-again", ("ready", "failed", "cancelled"))
            config = json.loads(config_path.read_text(encoding="utf-8"))
            args = config.get("args") or []
            listed = scanned()
            check(
                "R1 preparing again with another context replaces its own configuration and provenance",
                again["step"] == "ready"
                and args[args.index("--max-context") + 1] == "8192"
                and json.loads(provenance_path.read_text(encoding="utf-8")).get("recipe") == "strata-prepare"
                and [n for n in listed if n.startswith(PREPARED)] == [PREPARED],
                {k: again.get(k) for k in ("step", "error")},
            )
            if again.get("runtime"):
                client.post(f"/v1/runtimes/{again['runtime']}/stop")

            # U1 + C1 ------------------------------------------------------
            (data / "SLOW").write_text("", encoding="utf-8")
            calls_before = len((data / "setup-calls.jsonl").read_text().splitlines())
            submit("ls5-cancel")
            until("ls5-cancel", ("preparing",), 120)
            wait(
                lambda: len((data / "setup-calls.jsonl").read_text().splitlines()) > calls_before,
                "setup starts",
            )
            pid = json.loads((data / "setup-calls.jsonl").read_text().splitlines()[-1])["pid"]
            refused = client.post("/v1/engines/strata/uninstall")
            check(
                "U1 Strata cannot be uninstalled while it prepares",
                refused.status_code == 409 and "preparing a model" in refused.text,
                (refused.status_code, refused.text[:200]),
            )
            cancelled = client.post(f"{proxy}/v1/run-operations/ls5-cancel/cancel")
            stopped = wait(lambda: not alive(pid), "setup stops", 60) if cancelled.status_code == 200 else False
            check(
                "C1 cancelling the operation stops setup and what it started",
                cancelled.json().get("step") == "cancelled" and stopped is True,
                (cancelled.status_code, cancelled.text[:200]),
            )
            (data / "SLOW").unlink()

            # F1 -----------------------------------------------------------
            (data / "FAIL").write_text("", encoding="utf-8")
            submit("ls5-fail")
            failed = until("ls5-fail", ("ready", "failed", "cancelled"))
            check(
                "F1 a setup that stops fails the run at prepare, in setup's own words",
                failed["step"] == "failed"
                and failed.get("failedStep") == "prepare"
                and "Strata's setup stopped: not enough free disk space" in (failed.get("error") or ""),
                {k: failed.get(k) for k in ("step", "failedStep", "error")},
            )
            (data / "FAIL").unlink()
        finally:
            if os.name == "nt":
                agent.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                agent.terminate()
            try:
                agent.wait(timeout=60)
            except subprocess.TimeoutExpired:
                agent.kill()
                print("WARN  the agent did not stop in 60 s and was killed", flush=True)
            log.close()
            if FAILURES:
                print("--- agent log (last 80 lines) ---")
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
