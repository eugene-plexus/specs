"""LS5's real-environment run: Strata, a real model, a real GPU (operator-run, not CI).

library-sources-and-engines.md §5: LS5's acceptance is Strata's owed real-model
validation (strata-engine-run.md, "Still required"). It needs about 135 GB
on the chosen drive and downloads about 126 GB (Qwen3.8-Flash-Next IQ2_XS and
the Coder IQ1_M, at the revisions Strata pins) plus Strata's MTP helper
(~5 GB) and its tools; Troy's go, 2026-10-09: C:, with a second model.

A throwaway standalone agent on free loopback ports supervises its own
Library, whose one folder is `<folder>/models` on the drive chosen, with
engines installed into `<folder>/engines`. The live install is not touched.

  I1  Strata installs through the agent (the real recipe, from upstream);
  D1  *Download and prepare* (one run operation) downloads both shards at the
      pinned revision, prepares them with Strata's setup, and loads the model;
  G1  answers through the engine: a short answer, a long streamed answer
      (tokens/s), a cancelled stream followed by a prompt answer, what
      `/v1/status` says about speculative decoding (MTP);
  S1  a second real model (the Coder IQ1_M, about 58 GB more), downloaded
      and prepared beside the first, and switching between the two and back;
  F1  a prepared model whose pack is empty fails to load and says why;
  X1  stopping it ends the server and the native engine, and frees the VRAM;
  U1  uninstall is refused while it runs; after a stop, uninstall keeps the
      prepared files, a reinstall runs the same prepared model again.

Every measurement goes to `<folder>/ls5-report.json` as it is taken.

Usage: python specs/scripts/ls5-strata-real-run.py --folder D:\\ls5-strata [--keep-agent]
Clears every ambient EUGENE_PLEXUS_* variable for the agent it starts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any

import httpx
import yaml

REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
REVISION = "ed59f92082b1e93c0e96d60a8b11aab089b52f09"
FILES = [
    "IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf",
    "IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf",
]
PREPARED = "qwen3.8-flash-next-iq2_xs"
CODER_REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF"
CODER_REVISION = "5348543e0147355ac9cbcb031184a3546350988e"
CODER_FILES = [
    "IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf",
    "IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf",
]
REPORT: dict[str, Any] = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
FAILURES: list[str] = []


def note(key: str, value: Any, folder: Path) -> None:
    REPORT[key] = value
    (folder / "ls5-report.json").write_text(json.dumps(REPORT, indent=2, default=str), encoding="utf-8")


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def say(text: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def free_ports(count: int) -> list[int]:
    socks = [socket.socket() for _ in range(count)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def vram_used_mib() -> list[int]:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=False,
    ).stdout
    return [int(x) for x in out.split() if x.strip().isdigit()]


def ram_available_gib() -> float | None:
    if os.name != "nt":
        return None
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                    ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]

    status = Status()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return round(status.avail / 2**30, 1)


def process_tree(pid: int) -> dict[int, str]:
    """`pid` and every process under it, by name (Windows)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId) $($_.Name)\" }"],
        capture_output=True, text=True, check=False,
    ).stdout
    rows = [line.split(" ", 2) for line in out.splitlines() if line.count(" ") >= 2]
    children: dict[int, list[tuple[int, str]]] = {}
    names: dict[int, str] = {}
    for p, parent, name in rows:
        if p.isdigit() and parent.isdigit():
            children.setdefault(int(parent), []).append((int(p), name))
            names[int(p)] = name
    found = {pid: names.get(pid, "?")} if pid in names else {}
    stack = [pid]
    while stack:
        for child, name in children.get(stack.pop(), []):
            found[child] = name
            stack.append(child)
    return found


def alive(pids: list[int]) -> list[int]:
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False).stdout
    running = {int(m) for m in re.findall(r'^"[^"]*","(\d+)"', out, re.MULTILINE)}
    return [p for p in pids if p in running]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, help="where the throwaway stack and the model live")
    parser.add_argument("--keep-agent", action="store_true", help="leave the agent running at the end")
    args = parser.parse_args()
    folder = Path(args.folder).resolve()
    models = folder / "models"
    engines = folder / "engines"
    for d in (models, engines):
        d.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    say(f"{folder}: {free / 1e9:.0f} GB free; RAM available {ram_available_gib()} GiB; VRAM used {vram_used_mib()} MiB")
    note("folder", str(folder), folder)
    note("before", {"freeBytes": free, "ramAvailableGiB": ram_available_gib(), "vramUsedMiB": vram_used_mib()}, folder)

    agent_port, library_port = free_ports(2)
    (folder / "library.yaml").write_text(
        yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
    )
    (folder / "agent.yaml").write_text(
        yaml.safe_dump({
            "firstRunComplete": True,
            "updateChecks": False,
            "securityMode": "prompt_on_startup",
            "components": [{
                "name": "library", "kind": "library", "url": f"http://127.0.0.1:{library_port}",
                "spawn": {"configFile": str(folder / "library.yaml")},
            }],
            "runtimes": [],
        }),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update({
        "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(folder / "agent.yaml"),
        "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
        "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
        "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(engines),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "PYTHONUNBUFFERED": "1",
    })
    log = (folder / "agent.log").open("ab")
    agent = subprocess.Popen(
        [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
        cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{agent_port}", timeout=120, trust_env=False)
    proxy = "/api/proxy/library"

    def wait(fn, label: str, seconds: float):  # type: ignore[no-untyped-def]
        deadline = time.perf_counter() + seconds
        last: object = None
        while time.perf_counter() < deadline:
            try:
                got = fn()
                if got:
                    return got
            except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as e:
                last = e
            time.sleep(1)
        raise AssertionError(f"timed out: {label} ({last!r})")

    def runtime(name: str) -> dict[str, Any]:
        got: dict[str, Any] = client.get(f"/v1/runtimes/{name}").json()
        return got

    def until_status(name: str, wanted: tuple[str, ...], seconds: float) -> dict[str, Any]:
        return wait(lambda: (lambda r: r if r.get("status") in wanted else None)(runtime(name)),
                    f"{name} reaches {wanted}", seconds)

    try:
        wait(lambda: client.get("/healthz").status_code == 200, "the agent answers", 120)
        token = client.post("/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}).json()["sessionToken"]
        client.headers["Authorization"] = f"Bearer {token}"
        wait(lambda: client.get(f"{proxy}/healthz").status_code == 200, "the library answers", 120)
        node = client.get("/v1/node").json().get("name")
        say(f"agent :{agent_port}, library :{library_port}")

        # I1 --------------------------------------------------------------
        t0 = time.perf_counter()
        started = client.post("/v1/engines/strata/install")
        say(f"install: {started.status_code} {started.text[:200]}")
        done = wait(lambda: (lambda r: r if r["state"] in ("done", "failed", "cancelled") else None)(
            client.get("/v1/engines/strata/install").json()), "Strata installs", 1800)
        engines_now = {e["engine"]: e for e in client.get("/v1/engines").json()["engines"]}
        note("install", {"seconds": round(time.perf_counter() - t0), "record": done,
                         "descriptor": engines_now["strata"]}, folder)
        check("I1 Strata installs through the agent", done["state"] == "done" and engines_now["strata"]["available"], done)
        entry = next(m for m in engines_now["strata"]["supportedModels"] if m["id"] == "IQ2_XS")
        note("entry", entry, folder)

        # D1 --------------------------------------------------------------
        def download_and_prepare(op: str, repo: str, files: list[str], revision: str) -> dict[str, Any]:
            put = client.put(f"{proxy}/v1/run-operations/{op}", json={
                "node": node,
                "download": {"repo": repo, "files": files, "revision": revision},
                "preparation": {"engine": "strata"},
            })
            check(f"D1 Download and prepare is accepted ({op})", put.status_code == 202, put.text[:300])
            phases: dict[str, float] = {}
            last_line = ""
            t0 = time.perf_counter()
            while True:
                record: dict[str, Any] = client.get(f"{proxy}/v1/run-operations/{op}").json()
                step = record["step"]
                phases.setdefault(step, round(time.perf_counter() - t0))
                line = step
                if step == "downloading" and record.get("download"):
                    d = record["download"]
                    line += f" {(d.get('bytesDownloaded') or 0) / 1e9:.1f}/{(d.get('bytesTotal') or 0) / 1e9:.1f} GB"
                if step == "preparing" and record.get("preparation"):
                    p = record["preparation"]
                    line += f" {p.get('step')} · {(p.get('bytesWritten') or 0) / 1e9:.1f}/{(p.get('bytesNeeded') or 0) / 1e9:.0f} GB · {p.get('message')}"
                if line != last_line:
                    say(line)
                    last_line = line
                if step in ("ready", "failed", "cancelled", "skipped"):
                    break
                time.sleep(5)
            note(op, {"phasesStartedAtSeconds": phases, "record": record}, folder)
            check(f"D1 downloaded, prepared and loaded: ready on Strata ({op})",
                  record["step"] == "ready" and record.get("engine") == "strata",
                  {k: record.get(k) for k in ("step", "failedStep", "error")})
            return record

        record = download_and_prepare("ls5-real", REPO, FILES, REVISION)
        if record["step"] != "ready":
            return 1
        name = record["runtime"]
        a = runtime(name)
        tree = process_tree(int(a["pid"])) if a.get("pid") else {}
        note("loaded", {"runtime": a, "processes": tree, "vramUsedMiB": vram_used_mib(),
                        "ramAvailableGiB": ram_available_gib()}, folder)
        check("D1 the server and the native engine run", any("strata" in n.lower() for n in tree.values()), tree)
        base = str(a["url"]).rstrip("/")
        engine = httpx.Client(base_url=base, timeout=600, trust_env=False)

        # G1 --------------------------------------------------------------
        status_before = engine.get("/v1/status").json()
        t1 = time.perf_counter()
        short = engine.post("/v1/chat/completions", json={
            "model": PREPARED, "max_tokens": 64, "temperature": 0,
            "messages": [{"role": "user", "content": "What is 17 times 23? Reply with the number only."}],
        }).json()
        short_seconds = time.perf_counter() - t1
        answer = ((short.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        check("G1 a short answer is right", "391" in answer, short)
        first_token = None
        pieces: list[str] = []
        t1 = time.perf_counter()
        with engine.stream("POST", "/v1/chat/completions", json={
            "model": PREPARED, "max_tokens": 1500, "stream": True,
            "messages": [{"role": "user", "content": "Write a detailed, 1000-word explanation of how a refrigerator works."}],
        }) as stream:
            for raw in stream.iter_lines():
                if not raw.startswith("data: ") or raw == "data: [DONE]":
                    continue
                delta = (json.loads(raw[6:]).get("choices") or [{}])[0].get("delta") or {}
                text = (delta.get("content") or "") + (delta.get("reasoning_content") or "")
                if text:
                    first_token = first_token or time.perf_counter() - t1
                    pieces.append(text)
        long_seconds = time.perf_counter() - t1
        words = "".join(pieces).split()
        grams = [" ".join(words[i:i + 8]) for i in range(max(0, len(words) - 8))]
        repeated = 1 - len(set(grams)) / len(grams) if grams else 0.0
        status_after = engine.get("/v1/status").json()
        note("answers", {"shortSeconds": round(short_seconds, 2), "short": short,
                         "long": {"chunks": len(pieces), "words": len(words), "seconds": round(long_seconds, 1),
                                  "firstTokenSeconds": round(first_token or -1, 2),
                                  "chunksPerSecond": round(len(pieces) / max(0.001, long_seconds - (first_token or 0)), 1),
                                  "repeated8gramShare": round(repeated, 3)},
                         "statusBefore": status_before, "statusAfter": status_after}, folder)
        check("G1 a long answer streams to its end without repeating itself",
              len(words) > 300 and repeated < 0.2, {"words": len(words), "repeated": repeated})
        t1 = time.perf_counter()
        with engine.stream("POST", "/v1/chat/completions", json={
            "model": PREPARED, "max_tokens": 2000, "stream": True,
            "messages": [{"role": "user", "content": "Count from 1 to 2000, one number per line."}],
        }) as stream:
            seen = 0
            for raw in stream.iter_lines():
                if raw.startswith("data: "):
                    seen += 1
                if seen >= 40:
                    break  # the client goes away mid-answer
        t2 = time.perf_counter()
        after = engine.post("/v1/chat/completions", json={
            "model": PREPARED, "max_tokens": 16, "temperature": 0,
            "messages": [{"role": "user", "content": "Say OK."}],
        })
        note("cancel", {"answeredAfterCancelSeconds": round(time.perf_counter() - t2, 2),
                        "status": after.status_code, "body": after.text[:500]}, folder)
        check("G1 after a cancelled stream the next prompt is answered", after.status_code == 200, after.text[:300])

        # S1 --------------------------------------------------------------
        # A second real model (Troy, 2026-10-09): the Coder, its own files,
        # prepared beside the first in the same Strata-data (the MTP helper
        # is shared), then switched to and back with the agent's stop/start.
        data = models / "Strata-data"
        own = json.loads((data / "strata-iq2_xs.json").read_text(encoding="utf-8"))
        a_tree = list(process_tree(int(runtime(name)["pid"])))
        client.post(f"/v1/runtimes/{name}/stop")
        until_status(name, ("stopped",), 300)
        check("S1 stopping the first ends its processes", not alive(a_tree), alive(a_tree))
        coder = download_and_prepare("ls5-real-coder", CODER_REPO, CODER_FILES, CODER_REVISION)
        if coder["step"] != "ready":
            return 1
        second = coder["runtime"]
        b = runtime(second)
        b_health = httpx.get(str(b["url"]).rstrip("/") + "/health", timeout=30, trust_env=False).json()
        b_engine = httpx.Client(base_url=str(b["url"]).rstrip("/"), timeout=600, trust_env=False)
        coded = b_engine.post("/v1/chat/completions", json={
            "model": "coder", "max_tokens": 200, "temperature": 0,
            "messages": [{"role": "user", "content": "Write a Python function that returns the n-th Fibonacci number."}],
        })
        note("coder", {"runtime": b, "health": b_health, "status": coded.status_code,
                       "answer": coded.text[:2000], "vramUsedMiB": vram_used_mib(),
                       "ramAvailableGiB": ram_available_gib(),
                       "prepared": sorted(p.name for p in data.glob("*.eugene-prepared.json"))}, folder)
        check("S1 the Coder, prepared beside the first, loads and answers",
              b.get("status") == "ready" and coded.status_code == 200 and "def " in coded.text,
              {"status": b.get("status"), "answer": coded.text[:300]})
        timings: dict[str, float] = {}
        b_tree = list(process_tree(int(b["pid"])))
        client.post(f"/v1/runtimes/{second}/stop")
        until_status(second, ("stopped",), 300)
        t1 = time.perf_counter()
        client.post(f"/v1/runtimes/{name}/start")
        back = until_status(name, ("ready", "crashed"), 1800)
        timings["toFirstSeconds"] = round(time.perf_counter() - t1)
        check("S1 switching back to the first: the Coder is gone, the first ready",
              back.get("status") == "ready" and not alive(b_tree), back.get("lastError"))
        a_tree = list(process_tree(int(back["pid"])))
        client.post(f"/v1/runtimes/{name}/stop")
        until_status(name, ("stopped",), 300)
        t1 = time.perf_counter()
        client.post(f"/v1/runtimes/{second}/start")
        again = until_status(second, ("ready", "crashed"), 1800)
        timings["toCoderSeconds"] = round(time.perf_counter() - t1)
        note("switch", timings, folder)
        check("S1 and to the Coder again: the first is gone, the Coder ready",
              again.get("status") == "ready" and not alive(a_tree), again.get("lastError"))
        client.post(f"/v1/runtimes/{second}/stop")
        until_status(second, ("stopped",), 300)
        client.post(f"/v1/runtimes/{name}/start")
        until_status(name, ("ready", "crashed"), 1800)

        # F1 --------------------------------------------------------------
        (data / "empty-pack").mkdir(exist_ok=True)
        broken = dict(own, args=list(own["args"]))
        broken["args"][broken["args"].index("--pack") + 1] = "empty-pack"
        (data / "strata-broken.json").write_text(json.dumps(broken, indent=1), encoding="utf-8")
        bad = client.post(f"{proxy}/v1/models/prepared", json={
            "name": "qwen-broken", "provenance": {"engine": "strata", "entry": str(data / "strata-broken.json")}})
        client.post("/v1/runtimes", json={"name": "strata-broken", "engine": "strata",
                                         "modelPath": bad.json().get("path"), "autoStart": False})
        client.post(f"/v1/runtimes/{name}/stop")
        until_status(name, ("stopped",), 300)
        client.post("/v1/runtimes/strata-broken/start")
        failed = until_status("strata-broken", ("crashed", "ready", "stopped"), 900)
        note("failedLoad", failed, folder)
        check("F1 a prepared model with an empty pack fails to load and says why",
              failed.get("status") != "ready" and bool(failed.get("lastError")), failed)
        client.post("/v1/runtimes/strata-broken/stop")

        # X1 + U1 ---------------------------------------------------------
        client.post(f"/v1/runtimes/{name}/start")
        up = until_status(name, ("ready", "crashed"), 1800)
        tree = process_tree(int(up["pid"])) if up.get("pid") else {}
        vram_up = vram_used_mib()
        refused = client.post("/v1/engines/strata/uninstall")
        check("U1 uninstall is refused while it runs", refused.status_code == 409, refused.text[:200])
        client.post(f"/v1/runtimes/{name}/stop")
        until_status(name, ("stopped",), 300)
        time.sleep(5)
        gone = not alive(list(tree))
        vram_down = vram_used_mib()
        note("stop", {"processes": tree, "stillAlive": alive(list(tree)), "vramUpMiB": vram_up,
                      "vramDownMiB": vram_down, "before": REPORT["before"]["vramUsedMiB"]}, folder)
        check("X1 stopping ends the server and the native engine", gone, alive(list(tree)))
        check("X1 and frees its VRAM", bool(vram_down) and sum(vram_down) <= sum(REPORT["before"]["vramUsedMiB"]) + 512,
              {"up": vram_up, "down": vram_down})
        removed = client.post("/v1/engines/strata/uninstall")
        kept = (data / "strata-iq2_xs.json").is_file() and (data / "packs" / "iq2_xs").is_dir()
        check("U1 after a stop, uninstall removes the engine and keeps the prepared files",
              removed.status_code == 204 and kept, removed.text[:200])
        client.post("/v1/engines/strata/install")
        again = wait(lambda: (lambda r: r if r["state"] in ("done", "failed", "cancelled") else None)(
            client.get("/v1/engines/strata/install").json()), "Strata reinstalls", 1800)
        client.post(f"/v1/runtimes/{name}/start")
        last = until_status(name, ("ready", "crashed"), 1800)
        check("U1 a reinstall runs the same prepared model again",
              again["state"] == "done" and last.get("status") == "ready", last.get("lastError"))
        client.post(f"/v1/runtimes/{name}/stop")
    finally:
        note("finished", time.strftime("%Y-%m-%d %H:%M:%S"), folder)
        note("failures", FAILURES, folder)
        if not args.keep_agent:
            if os.name == "nt":
                agent.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                agent.terminate()
            try:
                agent.wait(timeout=120)
            except subprocess.TimeoutExpired:
                agent.kill()
        log.close()
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s); report {folder / 'ls5-report.json'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
