"""LS1 acceptance: engines declare what they accept; the Library judges.

library-sources-and-engines.md, slice LS1. A throwaway standalone agent on
free loopback ports supervises its own Library over a folder of four fixture
models (headers only, no weights): a llama GGUF, a Qwen3.8-Flash-Next GGUF
(architecture qwen4exp), an MLX-quantized safetensors folder and a plain one.
No engine is installed in its engine root, and nothing is ever started.

  E1  the real agent's GET /v1/engines carries each engine's `accepts`;
  E2  the console's question, through the agent's own proxy as the browser
      sends it: POST /api/proxy/library/v1/eligibility with that node's
      engines, answered with a verdict per engine and Troy's level per model;
  E3  Run, through the real agent's run worker: a GGUF reaches *install
      llama.cpp?* on llama.cpp's verdict, and an MLX folder on a machine that
      cannot have MLX fails naming vLLM's reason, which only the Library writes.

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


# --- fixtures: headers a scanner reads, nothing an engine could load -------


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


def gguf_kv(name: str, architecture: str, file_type: int) -> dict[str, Any]:
    return {
        "general.architecture": architecture,
        "general.name": name,
        f"{architecture}.context_length": 4096,
        "general.file_type": file_type,
    }


def write_hf_folder(directory: Path, *, mlx: bool) -> None:
    directory.mkdir(parents=True)
    config: dict[str, Any] = {
        "architectures": ["LlamaForCausalLM"],
        "model_type": "llama",
        "max_position_embeddings": 2048,
        "hidden_size": 32,
    }
    if mlx:
        config["quantization"] = {"bits": 4, "group_size": 64}
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    header = json.dumps(
        {"weight": {"dtype": "F32", "shape": [1024], "data_offsets": [0, 4096]}}
    ).encode("utf-8")
    (directory / "model.safetensors").write_bytes(
        struct.pack("<Q", len(header)) + header + bytes(4096)
    )
    (directory / "tokenizer.json").write_text("{}", encoding="utf-8")


def could_have_here(engine: dict[str, Any]) -> bool:
    """The console's `offeredOnThisNode`, for an engine not installed."""
    acquisition = engine.get("acquisition") or {}
    return (
        acquisition.get("policy") != "manual"
        or bool(acquisition.get("installable"))
        or bool((acquisition.get("manualInstall") or {}).get("command"))
    )


def as_console_sends(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "engine": e["engine"],
            "available": bool(e["available"]),
            "installable": not e["available"] and could_have_here(e),
            "experimental": bool(e.get("experimental")),
            "accepts": e["accepts"],
        }
        for e in engines
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ep-ls1-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        agent_port, library_port = free_ports(2)
        models = directory / "models"
        models.mkdir()
        write_gguf(models / "small-llama-Q4_K_M.gguf", gguf_kv("Small Llama", "llama", 15))
        write_gguf(models / "flash-next-IQ2_XS.gguf", gguf_kv("Flash Next", "qwen4exp", 20))
        write_hf_folder(models / "mlx-model", mlx=True)
        write_hf_folder(models / "plain-model", mlx=False)
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
                time.sleep(0.5)
            raise AssertionError(f"timed out: {label} ({last!r})")

        try:
            wait(lambda: client.get("/healthz").status_code == 200, "the agent answers")
            token = client.post(
                "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
            ).json()["sessionToken"]
            client.headers["Authorization"] = f"Bearer {token}"
            proxy = "/api/proxy/library"
            wait(lambda: client.get(f"{proxy}/healthz").status_code == 200, "the library answers")
            client.post(f"{proxy}/v1/scan")
            listed = wait(
                lambda: (lambda ms: ms if len(ms) == 4 else None)(
                    client.get(f"{proxy}/v1/models").json()["models"]
                ),
                "the four fixtures are catalogued",
            )
            ids = {m["name"]: m["id"] for m in listed}
            print(f"agent :{agent_port}, library :{library_port}, models {sorted(ids)}", flush=True)

            # E1 -----------------------------------------------------------
            engines = client.get("/v1/engines").json()["engines"]
            by = {e["engine"]: e for e in engines}
            check(
                "E1 every engine on /v1/engines declares what it accepts",
                all(e.get("accepts") for e in engines),
                [e["engine"] for e in engines if not e.get("accepts")],
            )
            strata = (by.get("strata") or {}).get("accepts") or [{}]
            check(
                "E1 Strata accepts a qwen4exp GGUF after preparation, and old consoles see no format",
                strata[0].get("architectures") == ["qwen4exp"]
                and bool(strata[0].get("preparation"))
                and by["strata"]["modelFormats"] == [],
                by.get("strata"),
            )
            vllm = (by.get("vllm") or {}).get("accepts") or [{}]
            check(
                "E1 vLLM never takes an MLX-quantized folder, and leaves the architecture to itself",
                vllm[0].get("mlxQuantization") == "forbidden" and vllm[0].get("authority") == "engine",
                by.get("vllm"),
            )

            # E2 -----------------------------------------------------------
            answer = client.post(
                f"{proxy}/v1/eligibility",
                json={"engines": as_console_sends(engines), "models": list(ids.values()) + ["gone"]},
            )
            judged = {m["modelId"]: m for m in answer.json().get("models", [])}
            check(
                "E2 the Library answers through the agent's proxy, leaving out an unknown id",
                answer.status_code == 200 and set(judged) == set(ids.values()),
                answer.text[:300],
            )

            def verdict(name: str, engine: str) -> dict[str, Any]:
                return next(v for v in judged[ids[name]]["engines"] if v["engine"] == engine)

            llama = verdict("small-llama-Q4_K_M", "llama_cpp")
            check(
                "E2 a llama GGUF: llama.cpp runs it; Strata names the architecture it needs",
                llama["verdict"] == "runs"
                and verdict("small-llama-Q4_K_M", "strata")["verdict"] == "no"
                and "qwen4exp" in verdict("small-llama-Q4_K_M", "strata")["reason"],
                judged[ids["small-llama-Q4_K_M"]],
            )
            expected = "works_here" if by["llama_cpp"]["available"] else "other_engine"
            check(
                f"E2 its level follows llama.cpp being installed here or not ({expected})",
                judged[ids["small-llama-Q4_K_M"]]["level"] == expected,
                judged[ids["small-llama-Q4_K_M"]]["level"],
            )
            check(
                "E2 a Flash-Next GGUF: Strata runs it after preparation, llama.cpp as it is",
                verdict("flash-next-IQ2_XS", "strata")["verdict"] == "after_preparation"
                and verdict("flash-next-IQ2_XS", "llama_cpp")["verdict"] == "runs",
                judged[ids["flash-next-IQ2_XS"]],
            )
            check(
                "E2 an MLX folder: MLX runs it, vLLM cannot load its weights",
                verdict("mlx-model", "mlx")["verdict"] == "runs"
                and verdict("mlx-model", "vllm")["verdict"] == "no"
                and "MLX-quantized" in verdict("mlx-model", "vllm")["reason"],
                judged[ids["mlx-model"]],
            )
            check(
                "E2 a plain folder: vLLM and MLX may run it, in vLLM's own words",
                verdict("plain-model", "vllm")["verdict"] == "may_run"
                and verdict("plain-model", "mlx")["verdict"] == "may_run"
                and "vLLM checks the architecture" in verdict("plain-model", "vllm")["reason"],
                judged[ids["plain-model"]],
            )

            # E3 -----------------------------------------------------------
            # The node this agent's tokens name. Unjoined, that is `local`,
            # while the console sends `null`, which the Library never hands to
            # anyone (library#7, found by this run): named here so E3
            # tests the judge, not that.
            node = client.get("/v1/node").json().get("name") or "local"

            def run(name: str, op: str) -> dict[str, Any]:
                put = client.put(
                    f"{proxy}/v1/run-operations/{op}", json={"modelId": ids[name], "node": node}
                )
                if put.status_code != 202:
                    raise AssertionError(f"run refused: {put.status_code} {put.text[:300]}")
                return wait(
                    lambda: (lambda r: r if r["step"] not in ("checking",) else None)(
                        client.get(f"{proxy}/v1/run-operations/{op}").json()
                    ),
                    f"{name} leaves checking",
                    60,
                )

            if by["llama_cpp"]["available"]:
                print("SKIP  E3 llama.cpp is installed here, so Run would start it", flush=True)
            else:
                record = run("small-llama-Q4_K_M", "ls1-gguf")
                check(
                    "E3 Run takes llama.cpp's verdict and asks before installing it",
                    record["step"] == "awaiting-install" and record.get("engine") == "llama_cpp",
                    record,
                )
                client.post(f"{proxy}/v1/run-operations/ls1-gguf/cancel")
            if by["mlx"]["available"] or by["mlx"]["accepts"] and could_have_here(by["mlx"]):
                print("SKIP  E3 this machine can have MLX", flush=True)
            else:
                record = run("mlx-model", "ls1-mlx")
                check(
                    "E3 Run on an MLX folder here fails naming vLLM's reason from the Library",
                    record["step"] == "failed"
                    and "cannot load MLX-quantized weights" in (record.get("error") or ""),
                    record,
                )
        finally:
            # Asked to stop, not killed: a hard kill on Windows skips the
            # agent's shutdown and orphans the library it supervises.
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
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
