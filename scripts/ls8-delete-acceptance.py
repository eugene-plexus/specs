"""LS8 acceptance: Delete a model from the Library, any format.

library-sources-and-engines.md §6.11 (Troy: a Delete for every model). A
throwaway standalone agent on free loopback ports supervises its own Library
over one folder holding: a two-shard Flash-Next GGUF with two prepared models
made from it in `Strata-data` (each with its own pack, both sharing the MTP
helper); two quants of a small model sharing one projector; and a
safetensors folder. Nothing is started but the agent and its Library.

  D1  the plan for a prepared model lists its own files and keeps the MTP
      helper for the other, naming it; a stale token deletes nothing;
  D2  deleting it removes exactly those files and the model, the other
      prepared model and the source untouched, and a new scan does not
      bring it back;
  D3  a quant keeps the projector the other quant uses;
  D4  the GGUF names the prepared model made from it; deleting both takes
      the MTP helper too (its last user), leaving setup's own intermediates
      and the engine-files marker;
  D5  a safetensors folder goes whole, and the folders it leaves empty;
  D6  (Windows) a file held open is not deleted, and neither is anything
      else of that model.

Clears every ambient EUGENE_PLEXUS_* variable, so it is safe beside a live
install. Run with the agent and library installed (editable is fine).
"""

from __future__ import annotations

import importlib.util
import json
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


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ls3 = _load("ls3", "ls3-prepared-acceptance.py")

FAILURES: list[str] = []
REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
FIRST = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
SECOND = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf"


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _gguf(path: Path, kv: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ls3.write_gguf(path, kv)


def lay_out(models: Path) -> dict[str, Path]:
    kv = {
        "general.architecture": "qwen4exp",
        "general.name": "Flash Next",
        "qwen4exp.context_length": 8192,
        "general.file_type": 20,
        "split.count": 2,
    }
    _gguf(models / REPO / FIRST, kv)
    _write(models / REPO / SECOND, b"second shard" * 100)
    data = models / "Strata-data"
    _write(data / ".eugene-engine-files", b"Strata's own files.\n")
    _write(data / "mtp" / "rt" / "experts.bin", b"m" * 2048)
    _write(data / "mtp" / "tensors" / "intermediate.bin", b"t" * 8192)
    for tag in ("iq2a", "iq2b"):
        _write(data / "packs" / tag / "dense.bin", b"d" * 4096)
        (data / f"strata-{tag}.json").write_text(
            json.dumps({"args": ["--pack", f"packs/{tag}", "--mtp", "mtp/rt"]}), encoding="utf-8"
        )
        (data / f"flash-{tag}{ls3.SUFFIX}").write_text(
            json.dumps(
                {
                    "engine": "strata",
                    "entry": f"strata-{tag}.json",
                    "source": {"path": str(models / REPO / FIRST)},
                    "files": [
                        {"path": f"strata-{tag}.json"},
                        {"path": f"packs/{tag}/dense.bin"},
                        {"path": "mtp/rt/experts.bin", "shared": True},
                    ],
                }
            ),
            encoding="utf-8",
        )
    small = models / "small"
    llama = {"general.architecture": "llama", "general.name": "Small", "llama.context_length": 4096}
    _gguf(small / "small-Q4_K_M.gguf", llama | {"general.file_type": 15})
    _gguf(small / "small-Q8_0.gguf", llama | {"general.file_type": 7})
    _gguf(small / "mmproj-small-f16.gguf", {"general.architecture": "clip"})
    folder = models / "org" / "tiny"
    _write(folder / "config.json", json.dumps({"model_type": "llama", "architectures": ["LlamaForCausalLM"]}).encode())
    _write(folder / "model.safetensors", b"\x08\x00\x00\x00\x00\x00\x00\x00{}      ")
    _write(folder / "tokenizer.json", b"{}")
    _write(folder / "README.md", b"readme")
    return {"data": data, "small": small, "folder": folder}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory(prefix="ep-ls8-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw).resolve()
        agent_port, library_port = ls3.free_ports(2)
        models = directory / "share"
        models.mkdir()
        where = lay_out(models)
        data = where["data"]
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

            def listed() -> dict[str, dict[str, Any]]:
                client.post(f"{proxy}/v1/scan", json={"full": True})
                wait(
                    lambda: client.get(f"{proxy}/v1/scan").json()["state"] != "scanning",
                    "the scan finishes",
                )
                return {m["name"]: m for m in client.get(f"{proxy}/v1/models").json()["models"]}

            def plan_of(model: dict[str, Any]) -> dict[str, Any]:
                return client.get(f"{proxy}/v1/models/{model['id']}/deletion").json()

            def delete(model: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
                return client.post(f"{proxy}/v1/models/{model['id']}/delete", json=body)

            models_now = listed()

            # D1 -----------------------------------------------------------
            a = models_now["flash-iq2a"]
            plan = plan_of(a)
            own = {Path(f["path"]) for f in plan.get("files") or []}
            kept = [(Path(k["path"]), [u["name"] for u in k["usedBy"]]) for k in plan.get("kept") or []]
            stale = delete(a, {"token": "not-the-plan"})
            check(
                "D1 a prepared model's plan: its own files, the MTP helper kept for the other",
                own
                == {
                    data / f"flash-iq2a{ls3.SUFFIX}",
                    data / "strata-iq2a.json",
                    data / "packs" / "iq2a" / "dense.bin",
                }
                and kept == [(data / "mtp" / "rt" / "experts.bin", ["flash-iq2b"])]
                and plan.get("bytesFreed", 0) > 4096,
                plan,
            )
            check(
                "D1 a stale plan deletes nothing",
                stale.status_code == 409 and all(p.is_file() for p in own),
                stale.text[:300],
            )

            # D2 -----------------------------------------------------------
            done = delete(a, {"token": plan["token"]})
            after = listed()
            check(
                "D2 deleted: its files and the model gone, the other and the source kept, and a "
                "scan does not bring it back",
                done.status_code == 200
                and not any(p.exists() for p in own)
                and (data / "packs" / "iq2b" / "dense.bin").is_file()
                and (data / "mtp" / "rt" / "experts.bin").is_file()
                and (models / REPO / FIRST).is_file()
                and "flash-iq2a" not in after
                and "flash-iq2b" in after,
                (done.status_code, done.text[:300], sorted(after)),
            )

            # D3 -----------------------------------------------------------
            q4 = next(m for m in after.values() if m["path"].endswith("small-Q4_K_M.gguf"))
            q4_plan = plan_of(q4)
            projector = where["small"] / "mmproj-small-f16.gguf"
            q4_names = {Path(f["path"]) for f in q4_plan.get("files") or []}
            check(
                "D3 a quant keeps the projector the other quant uses",
                projector not in q4_names
                and any(Path(k["path"]) == projector for k in q4_plan.get("kept") or [])
                and where["small"] / "small-Q4_K_M.gguf" in q4_names,
                q4_plan,
            )

            # D4 -----------------------------------------------------------
            gguf = next(m for m in after.values() if m["path"].endswith(FIRST))
            g_plan = plan_of(gguf)
            dependents = [d["name"] for d in g_plan.get("preparedFrom") or []]
            b = after["flash-iq2b"]
            both = delete(gguf, {"token": g_plan.get("token"), "alsoDelete": [b["id"]]})
            gone = listed()
            check(
                "D4 the GGUF names what was prepared from it; both go, the MTP helper with its "
                "last user, setup's intermediates and the marker stay",
                dependents == ["flash-iq2b"]
                and both.status_code == 200
                and not (models / REPO / FIRST).exists()
                and not (models / REPO / SECOND).exists()
                and not (data / "mtp" / "rt" / "experts.bin").exists()
                and (data / "mtp" / "tensors" / "intermediate.bin").is_file()
                and (data / ".eugene-engine-files").is_file()
                and "flash-iq2b" not in gone
                and not any(m["path"].endswith(FIRST) for m in gone.values()),
                (dependents, both.status_code, both.text[:300]),
            )

            # D5 -----------------------------------------------------------
            tiny = next(m for m in gone.values() if m["format"] == "safetensors")
            t_plan = plan_of(tiny)
            t_done = delete(tiny, {"token": t_plan.get("token")})
            check(
                "D5 a safetensors folder goes whole, and the folders it leaves empty",
                t_done.status_code == 200
                and not where["folder"].exists()
                and not (models / "org").exists()
                and models.is_dir(),
                (t_done.status_code, t_done.text[:300]),
            )

            # D6 -----------------------------------------------------------
            if os.name == "nt":
                q8 = next(m for m in listed().values() if m["path"].endswith("small-Q8_0.gguf"))
                q8_plan = plan_of(q8)
                held = where["small"] / "small-Q8_0.gguf"
                with held.open("rb"):  # Python opens without FILE_SHARE_DELETE
                    refused = delete(q8, {"token": q8_plan.get("token")})
                check(
                    "D6 a file held open is not deleted, and neither is anything else of it",
                    refused.status_code == 409
                    and "in use" in refused.text
                    and held.is_file()
                    and not list(where["small"].glob(".eugene-deleting-*")),
                    (refused.status_code, refused.text[:300]),
                )
            else:
                print("SKIP  D6 (Windows only: a POSIX file can be moved while open)")
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
