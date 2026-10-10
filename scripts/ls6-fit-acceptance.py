"""LS6 acceptance: each engine owns its fit model.

library-sources-and-engines.md, slice LS6 (Troy's L11). A throwaway
standalone agent on free loopback ports supervises its own Library over a
folder of fixture models (headers only, no weights): a llama GGUF, a
Qwen3.8-Flash-Next GGUF by the name Strata's setup gives IQ2_XS's first
shard, an MLX-quantized safetensors folder, a plain one, and a prepared
Strata model made from IQ2_XS. No engine is installed, nothing is started.

  F1  the real agent's GET /v1/engines carries each engine's fit model:
      llama.cpp `spill`, vLLM `reserved_share` at vLLM's own default share,
      Strata `engine_table` with setup's answer for every model on its list
      on this node's RAM and card; MLX and Kev declare none;
  F2  the console's question through the agent's proxy, with the node's
      memory (POST /v1/eligibility with `fit`): every engine answers its own
      fit, Strata's is its table's row, an engine with none is *not
      estimated*, and a model that fits no engine that would run it is red;
  F3  GET /v1/models/{id}/fit asked by a share-taking engine's model: its
      share of the cards' total decides, and an engine's table is not
      answered there;
  F4  admission, the real agent's dry run: MLX and Kev are never measured
      by llama.cpp's arithmetic; Strata is measured by its setup's table;
      vLLM by its share at its own `maxModelLen` (on a node with a card).

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
GIB = 1024**3


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


#: IQ2_XS's first shard, by the name Strata's setup gives it (LS4).
FLASH = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002"
#: What the scan calls it: a split GGUF is named without its shard suffix.
FLASH_NAME = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS"


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
        f"{architecture}.block_count": 32,
        f"{architecture}.attention.head_count": 32,
        f"{architecture}.attention.head_count_kv": 8,
        f"{architecture}.embedding_length": 4096,
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


def write_prepared(models: Path) -> Path:
    """A Strata model made from IQ2_XS, as LS5's preparation writes one."""
    data = models / "Strata-data"
    data.mkdir()
    (data / ".eugene-engine-files").write_text("Strata's own files.\n", encoding="utf-8")
    (data / "strata-iq2_xs.json").write_text(json.dumps({"args": []}), encoding="utf-8")
    path = data / "qwen3.8-flash-next-iq2_xs.eugene-prepared.json"
    path.write_text(
        json.dumps(
            {
                "formatVersion": 1,
                "engine": "strata",
                "entry": "strata-iq2_xs.json",
                "recipe": "strata-prepare",
                "source": {
                    "repoId": "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF",
                    "file": f"IQ2_XS/{FLASH}.gguf",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def could_have_here(engine: dict[str, Any]) -> bool:
    """The console's `offeredOnThisNode`, for an engine not installed."""
    acquisition = engine.get("acquisition") or {}
    return (
        acquisition.get("policy") != "manual"
        or bool(acquisition.get("installable"))
        or bool((acquisition.get("manualInstall") or {}).get("command"))
    )


def as_console_sends(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`eligibilityEngines` in the console: since LS6 with each engine's fit."""
    out = []
    for e in engines:
        sent = {
            "engine": e["engine"],
            "available": bool(e["available"]),
            "installable": not e["available"] and could_have_here(e),
            "experimental": bool(e.get("experimental")),
            "accepts": e["accepts"],
        }
        if e.get("fit"):
            sent["fit"] = e["fit"]
        out.append(sent)
    return out


def node_memory(node: dict[str, Any]) -> tuple[int | None, int | None, bool]:
    """This node's RAM, the card Strata would use (setup: the most memory,
    NVIDIA or AMD), and whether it has any accelerator at all."""
    devices = node.get("devices") or []
    cpu = next((d for d in devices if d.get("kind") == "cpu"), {})
    cards = [
        d
        for d in devices
        if d.get("kind") in ("cuda", "rocm")
        and not d.get("sharedMemory")
        and (d.get("memoryTotalBytes") or 0) > 0
    ]
    card = max((d["memoryTotalBytes"] for d in cards), default=None)
    accelerated = any(d.get("kind") != "cpu" for d in devices)
    return cpu.get("memoryTotalBytes"), card, accelerated


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory(prefix="ep-ls6-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        agent_port, library_port = free_ports(2)
        models = directory / "models"
        models.mkdir()
        write_gguf(models / "small-llama-Q4_K_M.gguf", gguf_kv("Small Llama", "llama", 15))
        write_gguf(models / f"{FLASH}.gguf", gguf_kv("Flash Next", "qwen4exp", 20))
        write_hf_folder(models / "mlx-model", mlx=True)
        write_hf_folder(models / "plain-model", mlx=False)
        prepared_path = write_prepared(models)
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
                lambda: (lambda ms: ms if len(ms) == 5 else None)(
                    client.get(f"{proxy}/v1/models").json()["models"]
                ),
                "the five fixtures are catalogued",
            )
            ids = {m["name"]: m["id"] for m in listed}
            prepared_id = next(m["id"] for m in listed if m["format"] == "prepared")
            node = client.get("/v1/node").json()
            ram, card, accelerated = node_memory(node)
            print(
                f"agent :{agent_port}, library :{library_port}; RAM {ram}, Strata card {card}; "
                f"models {sorted(ids)}",
                flush=True,
            )

            # F1 -----------------------------------------------------------
            engines = client.get("/v1/engines").json()["engines"]
            by = {e["engine"]: e for e in engines}
            check(
                "F1 llama.cpp declares `spill`, vLLM `reserved_share` at vLLM's own 0.92",
                (by["llama_cpp"].get("fit") or {}).get("kind") == "spill"
                and (by["vllm"].get("fit") or {}).get("kind") == "reserved_share"
                and (by["vllm"].get("fit") or {}).get("gpuMemoryUtilization") == 0.92,
                {k: by[k].get("fit") for k in ("llama_cpp", "vllm")},
            )
            check(
                "F1 MLX and Kev declare no fit model",
                by["mlx"].get("fit") is None and by["kev"].get("fit") is None,
                {k: by[k].get("fit") for k in ("mlx", "kev")},
            )
            table = (by["strata"].get("fit") or {}).get("table") or []
            rows = {r["file"]: r for r in table}
            listed_files = {
                m["source"]["file"].rsplit("/", 1)[-1] for m in by["strata"]["supportedModels"]
            }
            check(
                "F1 Strata's table has setup's answer for every model on its list",
                (by["strata"].get("fit") or {}).get("kind") == "engine_table"
                and set(rows) == listed_files
                and len(rows) == 9,
                by["strata"].get("fit"),
            )
            iq2 = rows.get(f"{FLASH}.gguf", {}).get("fit") or {}
            if card is None:
                expected_iq2 = "unknown"
            elif ram is not None and ram / GIB >= 48:
                expected_iq2 = "fits"
            else:
                expected_iq2 = "not fits"
            check(
                f"F1 IQ2_XS on this node follows setup's rule ({expected_iq2}: needs 48 GB of RAM "
                "and a card it can use)",
                (iq2.get("verdict") == expected_iq2)
                if expected_iq2 != "not fits"
                else iq2.get("verdict") in ("split", "tight", "no"),
                iq2,
            )

            # F2 -----------------------------------------------------------
            sent = as_console_sends(engines)

            def judge(models: list[str], fit: dict[str, Any] | None) -> dict[str, Any]:
                body: dict[str, Any] = {"engines": sent, "models": models}
                if fit is not None:
                    body["fit"] = fit
                answer = client.post(f"{proxy}/v1/eligibility", json=body)
                if answer.status_code != 200:
                    raise AssertionError(f"{answer.status_code} {answer.text[:300]}")
                return {m["modelId"]: m for m in answer.json()["models"]}

            def engine(answer: dict[str, Any], kind: str) -> dict[str, Any]:
                return next(v for v in answer["engines"] if v["engine"] == kind)

            roomy = {
                "contextLength": 4096,
                "vramFreeBytes": 24 * GIB,
                "vramTotalBytes": 24 * GIB,
                "gpuCount": 1,
                "ramAvailableBytes": 64 * GIB,
                "ramTotalBytes": 64 * GIB,
            }
            judged = judge(list(ids.values()), roomy)
            llama = engine(judged[ids["small-llama-Q4_K_M"]], "llama_cpp")
            check(
                "F2 llama.cpp's own fit, by its metadata, on the node's memory",
                (llama.get("fit") or {}).get("estimated") is True
                and llama["fit"].get("verdict") == "fits"
                and llama["fit"].get("model") == "spill",
                llama,
            )
            strata_flash = engine(judged[ids[FLASH_NAME]], "strata")
            check(
                "F2 Strata's fit for its GGUF is its own table's row for that file",
                (strata_flash.get("fit") or {}).get("reason") == iq2.get("reason")
                and strata_flash["fit"].get("verdict") == iq2.get("verdict"),
                strata_flash,
            )
            strata_prepared = engine(judged[prepared_id], "strata")
            check(
                "F2 a prepared model is found in the table by what it was made from",
                (strata_prepared.get("fit") or {}).get("reason") == iq2.get("reason"),
                strata_prepared,
            )
            mlx = engine(judged[ids["mlx-model"]], "mlx")
            check(
                "F2 MLX's fit is not estimated, never llama.cpp's number",
                (mlx.get("fit") or {}).get("estimated") is False
                and (mlx.get("fit") or {}).get("verdict") is None
                and (mlx.get("fit") or {}).get("requiredBytes") is None,
                mlx,
            )
            vllm = engine(judged[ids["plain-model"]], "vllm")
            check(
                "F2 vLLM's fit is its share's",
                (vllm.get("fit") or {}).get("model") == "reserved_share"
                and vllm["fit"].get("verdict") == "fits"
                and (vllm["fit"].get("shareBytes") or 0) == int(24 * GIB * 0.92),
                vllm,
            )
            starved = judge(
                [ids["small-llama-Q4_K_M"]],
                {"vramFreeBytes": 0, "vramTotalBytes": 0, "gpuCount": 0, "ramAvailableBytes": 1},
            )[ids["small-llama-Q4_K_M"]]
            check(
                "F2 a model that fits no engine that would run it is red",
                starved["level"] == "not_here"
                and engine(starved, "llama_cpp")["fit"]["verdict"] == "no",
                starved,
            )
            unasked = judge([ids["small-llama-Q4_K_M"]], None)[ids["small-llama-Q4_K_M"]]
            check(
                "F2 without the question, no fit and the level as before LS6",
                all(v.get("fit") is None for v in unasked["engines"])
                and unasked["level"] == judged[ids["small-llama-Q4_K_M"]]["level"],
                unasked,
            )

            # F3 -----------------------------------------------------------
            fit_url = f"{proxy}/v1/models/{ids['plain-model']}/fit"
            share = {"fitModel": "reserved_share", "gpuMemoryUtilization": 0.92}
            busy = client.get(
                fit_url, params={**share, "vramBytes": 10 * GIB, "vramTotalBytes": 24 * GIB}
            ).json()
            idle = client.get(
                fit_url, params={**share, "vramBytes": 23 * GIB, "vramTotalBytes": 24 * GIB}
            ).json()
            check(
                "F3 a share-taking engine fits an idle card and is `tight` while less is free",
                idle["fit"]["verdict"] == "fits"
                and busy["fit"]["verdict"] == "tight"
                and busy["fit"]["model"] == "reserved_share",
                (idle["fit"], busy["fit"]),
            )
            refused = [
                client.get(fit_url, params={"fitModel": "reserved_share"}).status_code,
                client.get(fit_url, params={"fitModel": "engine_table"}).status_code,
            ]
            check(
                "F3 no share, or an engine's own table: not estimated here (422)",
                refused == [422, 422],
                refused,
            )

            # F4 -----------------------------------------------------------
            def admission(kind: str, path: Path, flags: dict[str, Any] | None = None):  # type: ignore[no-untyped-def]
                spec = {"name": f"ls6-{kind}", "engine": kind, "modelPath": str(path)}
                if flags:
                    spec["flags"] = flags
                answer = client.post("/v1/runtimes/admission", json=spec)
                if answer.status_code != 200:
                    raise AssertionError(f"{answer.status_code} {answer.text[:300]}")
                return answer.json()

            for kind in ("mlx", "kev"):
                got = admission(kind, models / "plain-model")
                check(
                    f"F4 {kind}: admitted on faith, never measured by another engine's arithmetic",
                    got["fit"] == "unknown"
                    and got["decision"] == "admit"
                    and "no memory estimate" in got["reason"],
                    got,
                )
            strata = admission("strata", prepared_path)
            want = {"fits": "fits", "split": "split", "tight": "tight", "no": "no"}.get(
                iq2.get("verdict", ""), "unknown"
            )
            check(
                f"F4 Strata is measured by its setup's table ({want} here)",
                strata["basis"] == "engine_table"
                and (
                    strata["fit"] == want
                    # Setup's figure met by the machine, short of what is free now.
                    or (want == "fits" and strata["fit"] == "tight")
                ),
                strata,
            )
            if accelerated:
                got = admission("vllm", models / "plain-model", {"maxModelLen": 4096})
                check(
                    "F4 vLLM is measured by its share, at its own maxModelLen",
                    "of the cards' total memory" in got["reason"] and got.get("contextLength") == 4096,
                    got,
                )
            else:
                print("SKIP  F4 vLLM: no accelerator here, so admission measures nothing", flush=True)
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
