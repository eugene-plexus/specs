"""LS7a acceptance: a node runs a prepared model from its own copy of the Library's files.

library-sources-and-engines.md §6.8-§6.9 (Troy's principle: the Library is
the home of every model file and config; a node only ever holds a copy). A
throwaway standalone agent on free loopback ports supervises its own Library
over one folder laid out as LS5's preparation leaves it: a two-shard
Flash-Next GGUF in its publisher's folder, and `Strata-data` beside it with a
prepared model (provenance file, Strata's configuration, pack, tokenizer, the
MTP helper's runtime folder, and setup's intermediates it does not name). A
stand-in Strata server (LS3's) records the configuration it was started with.

  C1  copying on, Run copies the whole set to the node's copy folder, keeping
      its layout, and leaves setup's unnamed intermediates; the runtime opens
      the copy, and Strata was handed paths inside it;
  C3  Settings says which drive the copy folder is on (a share warns);
  C4  the Library refuses adopting an engine's files from outside its folders,
      and lists one written by hand that points outside as unreadable.

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
_spec = importlib.util.spec_from_file_location("ls3", HERE / "ls3-prepared-acceptance.py")
assert _spec is not None and _spec.loader is not None
ls3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls3)

FAILURES: list[str] = []
REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
FIRST = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
SECOND = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf"
LLAMA_FIRST = "small-llama-Q4_K_M-00001-of-00002.gguf"
LLAMA_SECOND = "small-llama-Q4_K_M-00002-of-00002.gguf"


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  -- {detail}"), flush=True)
    if not ok:
        FAILURES.append(label)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def lay_out(models: Path) -> Path:
    """The Library folder as LS5's preparation leaves it; returns the
    provenance file."""
    kv = {
        "general.architecture": "qwen4exp",
        "general.name": "Flash Next",
        "qwen4exp.context_length": 8192,
        "general.file_type": 20,
        "split.count": 2,
    }
    (models / REPO).mkdir(parents=True, exist_ok=True)
    ls3.write_gguf(models / REPO / FIRST, kv)
    _write(models / REPO / SECOND, b"second shard" * 100)
    data = models / "Strata-data"
    _write(data / ".eugene-engine-files", b"Strata's own files.\n")
    _write(data / "packs" / "iq2_xs" / "dense.bin", b"d" * 4096)
    _write(data / "packs" / "iq2_xs" / "expert-profile.bin", b"p" * 64)
    for name in ("vocab.json", "merges.txt", "token_type.json"):
        _write(data / "packs" / "iq2_xs" / "tokenizer" / name, b"{}")
    _write(data / "mtp" / "rt" / "experts.bin", b"m" * 2048)
    _write(data / "mtp" / "tensors" / "intermediate.bin", b"t" * 8192)
    config = {
        "args": [
            "--pack",
            "packs/iq2_xs",
            "--native",
            f"../{REPO}/{FIRST}",
            "--ple-gguf",
            f"../{REPO}/{SECOND}",
            "--expert-profile",
            "packs/iq2_xs/expert-profile.bin",
            "--mtp",
            "mtp/rt",
            "--max-context",
            "8192",
        ],
        "tokenizer": "packs/iq2_xs/tokenizer",
        "parallel": 1,
    }
    (data / "strata-iq2_xs.json").write_text(json.dumps(config, indent=1), encoding="utf-8")
    provenance = data / f"qwen3.8-flash-next-iq2_xs{ls3.SUFFIX}"
    provenance.write_text(
        json.dumps(
            {
                "formatVersion": 1,
                "engine": "strata",
                "entry": "strata-iq2_xs.json",
                "recipe": "strata-prepare",
                "source": {"repoId": REPO, "file": f"IQ2_XS/{FIRST}"},
            }
        ),
        encoding="utf-8",
    )
    llama_kv = {
        "general.architecture": "llama",
        "general.name": "Small Llama",
        "llama.context_length": 4096,
        "general.file_type": 15,
        "split.count": 2,
    }
    (models / "small").mkdir(parents=True, exist_ok=True)
    ls3.write_gguf(models / "small" / LLAMA_FIRST, llama_kv)
    _write(models / "small" / LLAMA_SECOND, b"llama second" * 100)
    return provenance


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory(prefix="ep-ls7-", ignore_cleanup_errors=True) as raw:
        # Long names: a CI runner's temp folder is its 8.3 short name
        # (RUNNER~1), which the agent spells long once it resolves a path.
        directory = Path(raw).resolve()
        agent_port, library_port = ls3.free_ports(2)
        models = directory / "share"
        models.mkdir()
        provenance = lay_out(models)
        copies = directory / "copies"
        server = ls3.fake_strata(directory / "strata")
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
            patched = client.patch(
                "/v1/config",
                json={
                    "strataServer": str(server),
                    "modelCopyEnabled": True,
                    "modelCopyDir": str(copies),
                    "modelCopyMinFreeGb": 0,
                },
            )
            if patched.status_code != 200:
                raise AssertionError(f"config refused: {patched.text[:300]}")
            client.post(f"{proxy}/v1/scan", json={"full": True})
            listed = wait(
                lambda: (
                    lambda ms: {m["name"]: m for m in ms}
                    if any(m["format"] == "prepared" for m in ms)
                    and client.get(f"{proxy}/v1/scan").json()["state"] != "scanning"
                    else None
                )(client.get(f"{proxy}/v1/models").json()["models"]),
                "the prepared model is listed",
            )
            prepared = next(m for m in listed.values() if m["format"] == "prepared")
            node = client.get("/v1/node").json().get("name")

            # C1 -----------------------------------------------------------
            put = client.put(
                f"{proxy}/v1/run-operations/ls7-run",
                json={"modelId": prepared["id"], "node": node},
            )
            if put.status_code != 202:
                raise AssertionError(f"run refused: {put.status_code} {put.text[:300]}")
            record = wait(
                lambda: (lambda r: r if r["step"] in ("ready", "failed", "cancelled") else None)(
                    client.get(f"{proxy}/v1/run-operations/ls7-run").json()
                ),
                "Run reaches ready",
                240,
            )
            check("C1 Run reaches ready on Strata", record["step"] == "ready", record)
            on_disk = sorted(
                p.relative_to(copies).as_posix() for p in copies.rglob("*") if p.is_file()
            )
            wanted = {
                f"Strata-data/{provenance.name}",
                "Strata-data/strata-iq2_xs.json",
                "Strata-data/packs/iq2_xs/dense.bin",
                "Strata-data/packs/iq2_xs/expert-profile.bin",
                "Strata-data/packs/iq2_xs/tokenizer/vocab.json",
                "Strata-data/mtp/rt/experts.bin",
                f"{REPO}/{FIRST}",
                f"{REPO}/{SECOND}",
            }
            # A standalone agent has no Library-folder rule, so a copy keeps the
            # model's whole path under the copy folder; the layout is what counts.
            check(
                "C1 the whole set is copied, layout kept, both GGUF shards with it (agent#10), "
                "and setup's unnamed intermediates are not",
                all(any(p.endswith(w) for p in on_disk) for w in wanted)
                and not any("tensors" in p for p in on_disk),
                on_disk,
            )
            runtimes = client.get("/v1/runtimes").json()["runtimes"]
            strata = next((r for r in runtimes if r.get("engine") == "strata"), {})
            opened = str(strata.get("localPath") or "")
            check(
                "C1 the runtime opens the copy",
                strata.get("localPathSource") == "copy" and opened.startswith(str(copies)),
                {k: strata.get(k) for k in ("localPath", "localPathSource", "localPathNote")},
            )
            seen = list((server.parent / "seen").glob("*.json"))
            handed = json.loads(seen[0].read_text(encoding="utf-8"))["config"] if seen else {}
            args = handed.get("args") or []
            native = args[args.index("--native") + 1] if "--native" in args else ""
            check(
                "C1 Strata was handed the GGUF and pack inside the copy",
                str(native).startswith(str(copies))
                and str(args[args.index("--pack") + 1]).startswith(str(copies)),
                args,
            )

            # C3 -----------------------------------------------------------
            def copy_status(folder: str) -> dict[str, Any]:
                client.patch("/v1/config", json={"modelCopyDir": folder})
                schema = client.get("/v1/config/schema").json()
                field = next(f for f in schema["fields"] if f["key"] == "modelCopyDir")
                return field.get("status") or {}

            share = copy_status("\\\\nas.invalid\\copies")
            check(
                "C3 a copy folder on a network share is warned about, in Settings",
                share.get("level") == "warning" and "network share" in (share.get("text") or ""),
                share,
            )
            local = copy_status(str(copies))
            check(
                "C3 the copy folder's own drive is named, or nothing claimed when unknown",
                local == {}
                or (local.get("level") in ("info", "warning") and "On " in (local.get("text") or "")),
                local,
            )

            # C4 -----------------------------------------------------------
            outside = directory / "elsewhere" / "strata-other.json"
            _write(outside, b"{}")
            refused = client.post(
                f"{proxy}/v1/models/prepared",
                json={"name": "outside", "provenance": {"engine": "strata", "entry": str(outside)}},
            )
            (models / f"by-hand{ls3.SUFFIX}").write_text(
                json.dumps({"engine": "strata", "entry": str(outside)}), encoding="utf-8"
            )
            client.post(f"{proxy}/v1/scan", json={"full": True})
            wait(lambda: client.get(f"{proxy}/v1/scan").json()["state"] != "scanning", "rescan")
            hand = next(
                (m for m in client.get(f"{proxy}/v1/models").json()["models"] if m["name"] == "by-hand"),
                {},
            )
            check(
                "C4 adopting from outside the Library is refused, nothing written",
                refused.status_code == 400
                and "outside the Library" in refused.text
                and not (models / f"outside{ls3.SUFFIX}").exists(),
                refused.text[:300],
            )
            check(
                "C4 one written by hand pointing outside is unreadable, saying why",
                hand.get("status") == "unreadable" and "outside the Library folder" in (hand.get("error") or ""),
                hand,
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
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
