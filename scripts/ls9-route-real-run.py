"""LS9 real run: what the console's best-route rule reads, on this machine.

Troy's B54 change (library-sources-and-engines.md §6.8, §6.12): when the
preparing engine suits the machine better, Run recommends preparing and
chooses it. The rule is the console's (`betterAfterPreparing` in
ui/src/lib/eligibility.ts, unit-tested there); this run checks its inputs on
real hardware and real files: a throwaway agent on free loopback ports,
installing llama.cpp itself as a person's Backends page would, beside the
Strata v0.1.39 install kept from LS5's real run, over a Library folder
holding the real Qwen3.8-Flash-Next IQ2_XS GGUF (about 68 GB, two shards).

  R1  the Library lists the GGUF;
  R2  llama.cpp is installed here by the agent, and Strata is installed;
  R3  the Library's judge, asked as the console asks (each engine's fit model
      and this node's memory): llama.cpp runs it as it is but its own fit
      says part of it runs from system memory (or it does not fit); Strata
      runs it after preparing it and its own fit (setup's table) says it
      fits, or runs in its low-RAM mode;
  R4  so the console's rule recommends preparing for Strata here (the same
      rule, mirrored here line for line).

Usage: python specs/scripts/ls9-route-real-run.py [--share D:\\ls7-share]
       [--strata C:\\ls5-strata\\engines\\strata] [--engines C:\\ls9-engines]
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("ls6", HERE / "ls6-fit-acceptance.py")
assert _spec is not None and _spec.loader is not None
ls6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls6)

FAILURES: list[str] = []
FIRST = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def better_after_preparing(verdicts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """`betterAfterPreparing` in ui/src/lib/eligibility.ts, mirrored."""
    as_is = next(
        (v for v in verdicts if v.get("available") and v.get("verdict") in ("runs", "may_run")),
        None,
    )
    fit = (as_is or {}).get("fit") or {}
    if not fit.get("estimated") or fit.get("verdict") not in ("split", "no"):
        return None
    prepare = next(
        (
            v
            for v in verdicts
            if v.get("available")
            and v.get("verdict") == "after_preparation"
            and (v.get("fit") or {}).get("estimated") is True
            and (v.get("fit") or {}).get("verdict") in ("fits", "split")
        ),
        None,
    )
    return {"asIs": as_is, "prepare": prepare} if prepare else None


def budget(node: dict[str, Any]) -> dict[str, Any]:
    """`fitQuestion(budgetFromNode(node))` in the console."""
    devices = node.get("devices") or []
    cards = [d for d in devices if d.get("kind") != "cpu"]
    cpu = next((d for d in devices if d.get("kind") == "cpu"), None)

    def free(d: dict[str, Any]) -> int:
        return d.get("memoryFreeBytes") or d.get("memoryTotalBytes") or 0

    question: dict[str, Any] = {"vramFreeBytes": sum(free(d) for d in cards), "gpuCount": len(cards)}
    totals = [d.get("memoryTotalBytes") for d in cards]
    if cards and all(t is not None for t in totals):
        question["vramTotalBytes"] = sum(totals)
    if cpu is not None:
        question["ramAvailableBytes"] = free(cpu)
        if cpu.get("memoryTotalBytes") is not None:
            question["ramTotalBytes"] = cpu["memoryTotalBytes"]
    return question


def junction(link: Path, target: Path) -> None:
    if link.exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True,
                   capture_output=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--share", default="D:\\ls7-share")
    parser.add_argument("--strata", default="C:\\ls5-strata\\engines\\strata")
    parser.add_argument("--engines", default="C:\\ls9-engines")
    args = parser.parse_args()
    share, engines = Path(args.share), Path(args.engines)
    # Strata as LS5 installed it; llama.cpp installed below, by the agent.
    junction(engines / "strata", Path(args.strata))
    with tempfile.TemporaryDirectory(prefix="ep-ls9-real-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw).resolve()
        agent_port, library_port = ls6.free_ports(2)
        (directory / "library.yaml").write_text(
            yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(share)]}), encoding="utf-8"
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
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(engines),
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
                time.sleep(1)
            raise AssertionError(f"timed out: {label} ({last!r})")

        try:
            wait(lambda: client.get("/healthz").status_code == 200, "the agent answers")
            token = client.post(
                "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
            ).json()["sessionToken"]
            client.headers["Authorization"] = f"Bearer {token}"
            proxy = "/api/proxy/library"
            wait(lambda: client.get(f"{proxy}/healthz").status_code == 200, "the library answers")
            client.post(f"{proxy}/v1/scan", json={"full": True})
            wait(
                lambda: client.get(f"{proxy}/v1/scan").json()["state"] != "scanning",
                "the scan finishes",
                300,
            )
            models = client.get(f"{proxy}/v1/models").json()["models"]
            gguf = next((m for m in models if m["path"].endswith(FIRST)), None)
            check(
                "R1 the Library lists the real IQ2_XS GGUF",
                gguf is not None and gguf["status"] == "present",
                [m["path"] for m in models],
            )

            def by_engine() -> dict[str, dict[str, Any]]:
                return {e["engine"]: e for e in client.get("/v1/engines").json()["engines"]}

            if not by_engine()["llama_cpp"]["available"]:
                started = client.post("/v1/engines/llama_cpp/install", json={}, timeout=120)
                print(f"installing llama.cpp: {started.status_code}", flush=True)
                wait(lambda: by_engine()["llama_cpp"]["available"], "llama.cpp installs", 1200)
            found = by_engine()
            check(
                "R2 llama.cpp installed here by the agent, and Strata installed",
                found["llama_cpp"]["available"] and found["strata"]["available"],
                {k: {f: found[k].get(f) for f in ("available", "version", "error")}
                 for k in ("llama_cpp", "strata")},
            )
            node = client.get("/v1/node").json()
            question = budget(node)
            body = {
                "engines": ls6.as_console_sends(list(found.values())),
                "models": [gguf["id"]] if gguf else [],
                "fit": question,
            }
            answer = client.post(f"{proxy}/v1/eligibility", json=body)
            verdicts = (answer.json()["models"][0]["engines"]
                        if answer.status_code == 200 and answer.json()["models"] else [])
            by = {v["engine"]: v for v in verdicts}
            llama = by.get("llama_cpp", {})
            strata = by.get("strata", {})
            print(f"this node: {question}", flush=True)
            for v in (llama, strata):
                print(f"  {v.get('engine')}: {v.get('verdict')}; fit {v.get('fit')}", flush=True)
            check(
                "R3 llama.cpp runs it as it is, and its own fit says part of it runs from "
                "system memory here (or it does not fit)",
                llama.get("verdict") in ("runs", "may_run")
                and (llama.get("fit") or {}).get("estimated") is True
                and (llama.get("fit") or {}).get("verdict") in ("split", "no"),
                llama,
            )
            check(
                "R3 Strata runs it after preparing it, and setup's own table says it fits here "
                "(or its low-RAM mode)",
                strata.get("verdict") == "after_preparation"
                and (strata.get("fit") or {}).get("estimated") is True
                and (strata.get("fit") or {}).get("verdict") in ("fits", "split"),
                strata,
            )
            route = better_after_preparing(verdicts)
            check(
                "R4 so the console recommends preparing for Strata on this machine",
                route is not None and route["prepare"]["engine"] == "strata",
                route,
            )
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
                print("--- agent log (last 60 lines) ---")
                print(
                    "\n".join(
                        log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
                    )
                )
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
