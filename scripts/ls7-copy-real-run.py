"""LS7a real-model run: Strata runs a prepared model from the node's own copy.

Troy, 2026-10-09: real models allowed tonight. A throwaway agent on free
loopback ports, with the Strata v0.1.39 install kept from LS5's real run as
its engine root, a Library folder standing in for the NAS (default
`D:\\ls7-share`, holding the IQ2_XS set as LS5 prepared it) and a copy folder
on C:'s SSD. Run copies the whole set, Strata loads it from the copy and
answers, and deleting the runtime takes its copy with it.

Usage: python specs/scripts/ls7-copy-real-run.py [--share D:\\ls7-share]
       [--engines C:\\ls5-strata\\engines] [--copies C:\\ls7-copies]
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
_spec = importlib.util.spec_from_file_location("ls3", HERE / "ls3-prepared-acceptance.py")
assert _spec is not None and _spec.loader is not None
ls3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls3)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--share", default="D:\\ls7-share")
    parser.add_argument("--engines", default="C:\\ls5-strata\\engines")
    parser.add_argument("--copies", default="C:\\ls7-copies")
    args = parser.parse_args()
    share, engines, copies = Path(args.share), Path(args.engines), Path(args.copies)
    with tempfile.TemporaryDirectory(prefix="ep-ls7-real-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        agent_port, library_port = ls3.free_ports(2)
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
        client = httpx.Client(base_url=f"http://127.0.0.1:{agent_port}", timeout=120, trust_env=False)

        def wait(fn, label: str, seconds: float = 120):  # type: ignore[no-untyped-def]
            deadline = time.perf_counter() + seconds
            last: object = None
            while time.perf_counter() < deadline:
                try:
                    got = fn()
                    if got:
                        return got
                except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as e:
                    last = e
                time.sleep(1.0)
            raise AssertionError(f"timed out: {label} ({last!r})")

        try:
            wait(lambda: client.get("/healthz").status_code == 200, "the agent answers")
            token = client.post(
                "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
            ).json()["sessionToken"]
            client.headers["Authorization"] = f"Bearer {token}"
            proxy = "/api/proxy/library"
            wait(lambda: client.get(f"{proxy}/healthz").status_code == 200, "the library answers")
            client.patch(
                "/v1/config",
                json={
                    "modelCopyEnabled": True,
                    "modelCopyDir": str(copies),
                    "modelCopyMinFreeGb": 50,
                },
            )
            schema = client.get("/v1/config/schema").json()
            status = next(f for f in schema["fields"] if f["key"] == "modelCopyDir").get("status")
            check("R0 Settings names the copy folder's drive (C:, an SSD)", (status or {}).get("text") == "On an SSD.", status)
            client.post(f"{proxy}/v1/scan", json={"full": True})
            models = wait(
                lambda: (
                    lambda ms: ms
                    if any(m["format"] == "prepared" and m["status"] == "present" for m in ms)
                    and client.get(f"{proxy}/v1/scan").json()["state"] != "scanning"
                    else None
                )(client.get(f"{proxy}/v1/models").json()["models"]),
                "the prepared IQ2_XS is listed",
                600,
            )
            prepared = next(m for m in models if m["format"] == "prepared" and m["status"] == "present")
            node = client.get("/v1/node").json().get("name")
            started = time.perf_counter()
            put = client.put(
                f"{proxy}/v1/run-operations/ls7-real", json={"modelId": prepared["id"], "node": node}
            )
            if put.status_code != 202:
                raise AssertionError(f"run refused: {put.status_code} {put.text[:300]}")
            seen_files: set[int] = set()
            record: dict[str, Any] = {}
            deadline = time.perf_counter() + 2400
            while time.perf_counter() < deadline:
                record = client.get(f"{proxy}/v1/run-operations/ls7-real").json()
                for runtime in client.get("/v1/runtimes").json()["runtimes"]:
                    progress = runtime.get("copyProgress") or {}
                    if progress.get("files"):
                        seen_files.add(int(progress["files"]))
                if record.get("step") in ("ready", "failed", "cancelled"):
                    break
                time.sleep(2.0)
            took = time.perf_counter() - started
            check(f"R1 download-free Run reaches ready from the copy ({took / 60:.1f} min)", record.get("step") == "ready", record)
            if not seen_files and any(p.is_file() for p in copies.rglob("*")):
                print("SKIP  R1 the copy was already current from an earlier run: nothing to copy", flush=True)
            else:
                check("R1 the copy reported the set's files while it ran", any(n > 1 for n in seen_files), seen_files)
            runtimes = client.get("/v1/runtimes").json()["runtimes"]
            strata = next((r for r in runtimes if r.get("engine") == "strata"), {})
            check(
                "R1 Strata opens the copy on C:",
                strata.get("localPathSource") == "copy" and str(strata.get("localPath", "")).startswith(str(copies)),
                {k: strata.get(k) for k in ("localPath", "localPathSource", "localPathNote", "status")},
            )
            copied = [p for p in copies.rglob("*") if p.is_file()]
            gb = sum(p.stat().st_size for p in copied) / 1e9
            print(f"INFO  {len(copied)} files, {gb:.1f} GB in {copies}", flush=True)
            port = strata.get("port")
            # A wait waits for its subject: Strata's own answer. Any early
            # refusal after the agent said ready is recorded, as evidence.
            early: list[str] = []
            answer = None
            until = time.perf_counter() + 600
            while time.perf_counter() < until:
                try:
                    answer = httpx.post(
                        f"http://127.0.0.1:{port}/v1/chat/completions",
                        json={
                            "model": strata.get("modelAlias"),
                            "messages": [{"role": "user", "content": "Reply with one word: ready"}],
                            "max_tokens": 256,
                        },
                        timeout=600,
                        trust_env=False,
                    )
                except httpx.HTTPError as exc:
                    early.append(type(exc).__name__)
                    time.sleep(5)
                    continue
                if answer.status_code == 200:
                    break
                early.append(str(answer.status_code))
                time.sleep(5)
            print(f"INFO  refusals after ready, before the first answer: {early or 'none'}", flush=True)
            text = ""
            if answer is not None and answer.status_code == 200:
                # A reasoning model may spend its tokens thinking: either is
                # the engine answering from the copy.
                message = answer.json()["choices"][0]["message"]
                text = (message.get("content") or "") + (message.get("reasoning_content") or "")
            check("R2 Strata answers from the copy", bool(text.strip()), answer.text[:300] if answer is not None else early)
            client.delete(f"/v1/runtimes/{strata.get('name')}")
            gone = wait(lambda: not any(p.is_file() for p in copies.rglob("*")), "the copy goes with the runtime", 300)
            check("R3 deleting the runtime takes its copy with it", bool(gone))
        finally:
            if os.name == "nt":
                agent.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                agent.terminate()
            try:
                agent.wait(timeout=120)
            except subprocess.TimeoutExpired:
                agent.kill()
                print("WARN  the agent did not stop in 120 s and was killed", flush=True)
            log.close()
            if FAILURES:
                print("--- agent log (last 80 lines) ---")
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
