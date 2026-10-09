"""LS3 acceptance: prepared models are Library models.

library-sources-and-engines.md, slice LS3 (Troy's L6). A throwaway standalone
agent on free loopback ports supervises its own Library over a folder holding
a fake prepared Strata bundle: Strata's JSON configuration, a pack folder, a
tokenizer and the GGUF it was made from (a header only). Strata itself is a
borrowed installation (`strataServer`) whose `serve/server.py` is a stand-in
that answers `/health` as Strata does and records the launch configuration it
was handed; its `.venv` is a real, empty venv and `engine/strata` an empty
file nothing executes. No real Strata, no model, no GPU.

  A1  Add a prepared model, as the console does: the Library writes
      `<name>.eugene-prepared.json` beside Strata's configuration, entry
      relative, and lists a `prepared` model linked to its source GGUF;
  A2  the scan finds the same file again, and a provenance file written by
      hand, and says why one it cannot read is unreadable;
  E1  the real agent's Strata declares the models it prepared (and older
      consoles see `prepared`, never every GGUF);
  J1  the Library judges it: Strata runs it, llama.cpp does not, the dot is
      green; its source GGUF stays *after preparation*;
  F1  fit is not estimated for it;
  R1  Run, through the real agent's run worker: Strata is chosen, a profile
      is made on the prepared model, a runtime declared on its provenance
      file under the Library's name, and the stand-in reports ready;
  L1  what Strata was handed: the entry's assets as absolute paths, the
      model's name, the original configuration untouched;
  N1  a prepared model whose configuration names a missing file fails at
      Run, naming the file, before anything starts.

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

# The stand-in for Strata's `serve/server.py`: the argv the adapter builds,
# `/health` as Strata answers it, and the launch configuration it was handed
# kept beside it for L1.
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
            body = {"service": "strata", "loaded": True, "max_context": 8192}
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


def could_have_here(engine: dict[str, Any]) -> bool:
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


def prepared_bundle(
    folder: Path, *, gguf: str = "Flash-Next-IQ2_XS.gguf", extra: list[str] | None = None
) -> Path:
    """What Strata's setup leaves: its JSON configuration naming the GGUF it
    was made from, a pack and a tokenizer. Relative to its own folder."""
    folder.mkdir(parents=True)
    (folder / "pack").mkdir()
    write_gguf(
        folder / gguf,
        {
            "general.architecture": "qwen4exp",
            "general.name": "Flash Next",
            "qwen4exp.context_length": 8192,
            "general.file_type": 20,
        },
    )
    tokenizer = folder / "tokenizer"
    tokenizer.mkdir()
    for name in ("vocab.json", "merges.txt", "token_type.json"):
        (tokenizer / name).write_text("{}", encoding="utf-8")
    config = {
        "args": [
            "--pack",
            "pack",
            "--native",
            gguf,
            "--max-context",
            "8192",
            *(extra or []),
        ],
        "tokenizer": "tokenizer",
        "parallel": 1,
    }
    entry = folder / "strata-qwen.json"
    entry.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return entry


def fake_strata(root: Path) -> Path:
    server = root / "serve" / "server.py"
    server.parent.mkdir(parents=True)
    server.write_text(FAKE_SERVER, encoding="utf-8")
    (root / "serve" / "seen").mkdir()
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")], check=True
    )
    native = root / "engine" / ("strata.exe" if os.name == "nt" else "strata")
    native.parent.mkdir()
    native.touch()
    return server


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ep-ls3-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        agent_port, library_port = free_ports(2)
        models = directory / "models"
        models.mkdir()
        entry = prepared_bundle(models / "strata-bundle")
        source = entry.parent / "Flash-Next-IQ2_XS.gguf"
        broken_entry = prepared_bundle(
            models / "broken-bundle", gguf="Other-IQ2_XS.gguf", extra=["--mtp", "mtp-not-there"]
        )
        original = entry.read_bytes()
        server = fake_strata(directory / "strata")
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
            # The borrowed installation, set as the console's Settings page sets it.
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

            listed = wait(lambda: (lambda ms: ms if "Flash-Next-IQ2_XS" in ms else None)(scanned()), "the GGUF is listed")
            print(f"agent :{agent_port}, library :{library_port}, models {sorted(listed)}", flush=True)

            # A1 -----------------------------------------------------------
            added = client.post(
                f"{proxy}/v1/models/prepared",
                json={
                    "name": "qwen-flash",
                    "provenance": {
                        "engine": "strata",
                        "entry": str(entry),
                        "source": {"path": listed["Flash-Next-IQ2_XS"]["path"]},
                    },
                },
            )
            model = added.json() if added.status_code == 201 else {}
            written = entry.parent / f"qwen-flash{SUFFIX}"
            on_disk = json.loads(written.read_text(encoding="utf-8")) if written.exists() else {}
            check(
                "A1 the Library writes the provenance file beside Strata's configuration, entry relative",
                added.status_code == 201
                and on_disk.get("entry") == "strata-qwen.json"
                and on_disk.get("engine") == "strata"
                and on_disk.get("formatVersion") == 1,
                (added.status_code, added.text[:300], on_disk),
            )
            prepared = model.get("prepared") or {}
            check(
                "A1 it is listed at once as a prepared model, linked to the GGUF it was made from",
                model.get("format") == "prepared"
                and model.get("status") == "present"
                and model.get("path") == str(written)
                and model.get("sizeBytes") is None
                and prepared.get("entryFound") is True
                and prepared.get("sourceModelId") == listed["Flash-Next-IQ2_XS"]["id"],
                model,
            )
            again = client.post(
                f"{proxy}/v1/models/prepared",
                json={"name": "qwen-flash", "provenance": {"engine": "strata", "entry": str(entry)}},
            )
            check("A1 adopting the same name twice is refused, nothing replaced", again.status_code == 409, again.text[:200])

            # A2 -----------------------------------------------------------
            elsewhere = directory / "elsewhere" / "strata-other.json"
            (models / f"by-hand{SUFFIX}").write_text(
                json.dumps({"engine": "strata", "entry": str(elsewhere)}), encoding="utf-8"
            )
            (models / f"too-new{SUFFIX}").write_text(
                json.dumps({"formatVersion": 99, "engine": "strata", "entry": "x.json"}),
                encoding="utf-8",
            )
            broken_added = client.post(
                f"{proxy}/v1/models/prepared",
                json={"name": "broken", "provenance": {"engine": "strata", "entry": str(broken_entry)}},
            )
            listed = scanned()
            check(
                "A2 a full rescan keeps it, and finds a provenance file written by hand",
                (listed.get("qwen-flash") or {}).get("status") == "present"
                and (listed.get("by-hand") or {}).get("status") == "present"
                and ((listed.get("by-hand") or {}).get("prepared") or {}).get("entryFound") is False,
                {k: listed.get(k) for k in ("qwen-flash", "by-hand")},
            )
            check(
                "A2 one written by a newer Eugene is listed unreadable, and says so",
                (listed.get("too-new") or {}).get("status") == "unreadable"
                and "newer Eugene" in ((listed.get("too-new") or {}).get("error") or ""),
                listed.get("too-new"),
            )
            ids = {name: m["id"] for name, m in listed.items()}

            # E1 -----------------------------------------------------------
            engines = client.get("/v1/engines").json()["engines"]
            by = {e["engine"]: e for e in engines}
            strata = {r["format"]: r for r in by["strata"].get("accepts") or []}
            check(
                "E1 Strata declares the models it prepared, and is available from its borrowed install",
                (strata.get("prepared") or {}).get("preparedFor") == "strata"
                and by["strata"]["available"] is True,
                by["strata"],
            )
            check(
                "E1 older consoles see `prepared` for Strata, never every GGUF",
                by["strata"]["modelFormats"] == ["prepared"],
                by["strata"]["modelFormats"],
            )

            # J1 -----------------------------------------------------------
            answer = client.post(
                f"{proxy}/v1/eligibility",
                json={"engines": as_console_sends(engines), "models": [ids["qwen-flash"], ids["Flash-Next-IQ2_XS"]]},
            )
            judged = {m["modelId"]: m for m in answer.json().get("models", [])}

            def verdict(name: str, engine: str) -> dict[str, Any]:
                return next(v for v in judged[ids[name]]["engines"] if v["engine"] == engine)

            check(
                "J1 the prepared model: Strata runs it as it is, llama.cpp does not, the dot is green",
                answer.status_code == 200
                and verdict("qwen-flash", "strata")["verdict"] == "runs"
                and verdict("qwen-flash", "llama_cpp")["verdict"] == "no"
                and "prepared" in verdict("qwen-flash", "llama_cpp")["reason"]
                and judged[ids["qwen-flash"]]["level"] == "works_here",
                judged.get(ids["qwen-flash"]),
            )
            check(
                "J1 the GGUF it came from stays *after preparation* for Strata",
                verdict("Flash-Next-IQ2_XS", "strata")["verdict"] == "after_preparation",
                judged.get(ids["Flash-Next-IQ2_XS"]),
            )

            # F1 -----------------------------------------------------------
            fit = client.get(f"{proxy}/v1/models/{ids['qwen-flash']}/fit")
            check(
                "F1 fit is not estimated, never llama.cpp's arithmetic on a JSON file",
                fit.status_code == 422 and "Fit not estimated" in fit.text,
                (fit.status_code, fit.text[:200]),
            )

            # R1 -----------------------------------------------------------
            node = client.get("/v1/node").json().get("name")

            def run(model_id: str, op: str, until: tuple[str, ...]) -> dict[str, Any]:
                put = client.put(
                    f"{proxy}/v1/run-operations/{op}", json={"modelId": model_id, "node": node}
                )
                if put.status_code != 202:
                    raise AssertionError(f"run refused: {put.status_code} {put.text[:300]}")
                return wait(
                    lambda: (lambda r: r if r["step"] in until else None)(
                        client.get(f"{proxy}/v1/run-operations/{op}").json()
                    ),
                    f"run {op} reaches {until}",
                    180,
                )

            record = run(ids["qwen-flash"], "ls3-run", ("ready", "failed", "cancelled"))
            check(
                "R1 Run picks Strata, makes a profile, declares a runtime, and it reports ready",
                record["step"] == "ready" and record.get("engine") == "strata",
                record,
            )
            profiles = client.get(f"{proxy}/v1/models/{ids['qwen-flash']}/profiles").json()["profiles"]
            check(
                "R1 the profile is the prepared model's own, for Strata",
                [p["engine"] for p in profiles] == ["strata"],
                profiles,
            )
            runtimes = {r["name"]: r for r in client.get("/v1/runtimes").json()["runtimes"]}
            runtime = runtimes.get(record.get("runtime") or "") or {}
            check(
                "R1 the runtime names the provenance file and answers to the Library's name",
                Path(runtime.get("modelPath") or "") == written
                and runtime.get("modelAlias") in (None, "qwen-flash")
                and runtime.get("status") == "ready",
                runtime,
            )

            # L1 -----------------------------------------------------------
            seen_path = server.parent / "seen" / "qwen-flash.json"
            seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
            config = seen.get("config") or {}
            argv = config.get("args") or []

            def names(given: str, expected: Path) -> bool:
                # The same file, however spelled: on a Windows runner the temp
                # folder is `RUNNER~1` here and `runneradmin` once resolved.
                try:
                    return Path(given).is_absolute() and os.path.samefile(given, expected)
                except OSError:
                    return False

            check(
                "L1 Strata was handed the entry's assets as absolute paths, under the model's name",
                seen.get("engine") == "strata"
                and config.get("model_name") == "qwen-flash"
                and "--pack" in argv
                and names(argv[argv.index("--pack") + 1], entry.parent / "pack")
                and names(argv[argv.index("--native") + 1], source)
                and names(config.get("tokenizer") or "", entry.parent / "tokenizer"),
                seen,
            )
            check("L1 Strata's own configuration is untouched", entry.read_bytes() == original)
            if record.get("runtime"):
                client.post(f"/v1/runtimes/{record['runtime']}/stop")

            # N1 -----------------------------------------------------------
            if broken_added.status_code != 201:
                check("N1 the second prepared model is adopted", False, broken_added.text[:300])
            else:
                record = run(broken_added.json()["id"], "ls3-broken", ("ready", "failed", "cancelled"))
                check(
                    "N1 a configuration naming a missing file fails at Run, naming it, before Strata starts",
                    record["step"] == "failed"
                    and "mtp-not-there" in (record.get("error") or "")
                    and not (server.parent / "seen" / "broken.json").exists(),
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
                print("--- agent log (last 80 lines) ---")
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
