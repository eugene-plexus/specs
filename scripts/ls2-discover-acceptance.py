"""LS2 acceptance: Discover shows which engines can run what, before download.

library-sources-and-engines.md, slice LS2. A throwaway standalone agent on
free loopback ports supervises its own Library, whose catalogue points at a
fake hub on loopback (never huggingface.co). The engine root holds a
stand-in llama.cpp build `b1` (a receipt and an empty file, never started)
whose own architecture list is already kept beside it: every name in the
list the agent ships, except `qwen4exp`. Nothing is downloaded or started.

  D1  the agent's GET /v1/engines declares llama.cpp's architectures as the
      installed build's own list, not the shipped one and with no *may run*;
  D2  a search, through the agent's proxy as the browser sends it: the hub is
      asked for its GGUF block, and every row carries approximate facts
      (architecture from that block, the MLX marker from tags);
  D3  the console's question on those rows: a llama GGUF works here; a
      Flash-Next GGUF is refused by the installed llama.cpp, naming the
      architecture, and Strata would prepare it; the levels follow;
  D4  an MLX folder's detail reads its remote config.json with one ranged
      read, so MLX is told from vLLM before anything is downloaded;
  D5  a plain folder's detail: vLLM may run it, and its SentencePiece
      tokenizer comes with the download (design doc section 7);
  D6  the starter set carries facts, and the installed build runs it.

Clears every ambient EUGENE_PLEXUS_* variable, so it is safe beside a live
install. Run with the agent and library installed (editable is fine).
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml

FAILURES: list[str] = []
HUB_REQUESTS: list[tuple[str, dict[str, list[str]], str | None]] = []

MLX_CONFIG = {
    "architectures": ["Qwen3ForCausalLM"],
    "model_type": "qwen3",
    "quantization": {"bits": 4, "group_size": 64},
}
PLAIN_CONFIG = {"architectures": ["LlamaForCausalLM"], "model_type": "llama"}

SEARCH = [
    {"id": "org/Small-GGUF", "author": "org", "downloads": 40, "tags": ["gguf"],
     "library_name": "gguf", "gguf": {"architecture": "llama", "total": 1_000_000_000}},
    {"id": "org/FlashNext-GGUF", "author": "org", "downloads": 30, "tags": ["gguf"],
     "library_name": "gguf", "gguf": {"architecture": "qwen4exp", "total": 125_000_000_000}},
    {"id": "mlx-community/Tiny-4bit", "author": "mlx-community", "downloads": 20,
     "tags": ["mlx", "safetensors"], "library_name": "mlx"},
    {"id": "org/Plain", "author": "org", "downloads": 10, "tags": ["safetensors"],
     "library_name": "transformers"},
]


def _file(path: str, size: int, *, lfs: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "file", "path": path, "size": size, "oid": "1" * 40}
    if lfs:
        entry["lfs"] = {"oid": "a" * 64, "size": size}
    return entry


TREES = {
    "mlx-community/Tiny-4bit": [
        _file("config.json", len(json.dumps(MLX_CONFIG))),
        _file("model.safetensors", 400_000_000, lfs=True),
        _file("tokenizer.json", 9_000),
    ],
    "org/Plain": [
        _file("config.json", len(json.dumps(PLAIN_CONFIG))),
        _file("model.safetensors", 2_000_000_000, lfs=True),
        _file("tokenizer.model", 500_000),
        _file("tokenizer_config.json", 2_000),
    ],
}
CONFIGS = {"mlx-community/Tiny-4bit": MLX_CONFIG, "org/Plain": PLAIN_CONFIG}


class FakeHub(BaseHTTPRequestHandler):
    """Just the hub endpoints the catalogue calls, shaped like the real ones."""

    def log_message(self, *_: object) -> None:
        pass

    def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        HUB_REQUESTS.append((parts.path, parse_qs(parts.query), self.headers.get("Range")))
        if parts.path == "/api/models":
            self._send(200, json.dumps(SEARCH).encode())
            return
        if parts.path.startswith("/api/models/"):
            rest = parts.path[len("/api/models/"):]
            if "/tree/" in rest:
                repo = rest.split("/tree/")[0]
                self._send(200, json.dumps(TREES.get(repo, [])).encode())
                return
            row = next((r for r in SEARCH if r["id"] == rest), None)
            if row is None:
                self._send(404, b'{"error": "Repository not found"}')
                return
            self._send(200, json.dumps({**row, "sha": "c0ffee"}).encode())
            return
        for repo, config in CONFIGS.items():
            if parts.path == f"/{repo}/resolve/main/config.json":
                body = json.dumps(config).encode()
                wanted = self.headers.get("Range", "")
                if wanted.startswith("bytes=0-"):
                    last = min(int(wanted.split("-")[1]), len(body) - 1)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes 0-{last}/{len(body)}")
                    self.send_header("Content-Length", str(last + 1))
                    self.end_headers()
                    self.wfile.write(body[: last + 1])
                    return
                self._send(200, body)
                return
        self._send(404, b'{"error": "Entry not found"}')


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


def shipped_architectures() -> list[str]:
    from eugene_plexus_agent.engines import llama_architectures

    return list(llama_architectures.shipped().names)


def stand_in_llama_build(root: Path, names: list[str]) -> None:
    """A managed build the agent recognises by its receipt, and its kept list.
    The binary is an empty file: nothing in this run starts an engine."""
    build = root / "llama_cpp" / "b1"
    build.mkdir(parents=True)
    binary = build / ("llama-server.exe" if os.name == "nt" else "llama-server")
    binary.write_bytes(b"")
    (build / "install.json").write_text(
        json.dumps(
            {"version": "b1", "variant": "stand-in", "binary": binary.name,
             "installedAt": "2026-10-09T00:00:00+00:00", "sizeBytes": 0}
        ),
        encoding="utf-8",
    )
    kept = root / "llama_cpp" / "architectures"
    kept.mkdir(parents=True)
    (kept / "b1.json").write_text(json.dumps({"tag": "b1", "architectures": names}), encoding="utf-8")


def main() -> int:
    build_names = [n for n in shipped_architectures() if n != "qwen4exp"]
    hub_port, agent_port, library_port = free_ports(3)
    hub = ThreadingHTTPServer(("127.0.0.1", hub_port), FakeHub)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix="ep-ls2-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        models = directory / "models"
        models.mkdir()
        engines_root = directory / "engines"
        stand_in_llama_build(engines_root, build_names)
        (directory / "library.yaml").write_text(
            yaml.safe_dump(
                {
                    "logLevel": "INFO",
                    "modelRoots": [str(models)],
                    "catalogueBaseUrl": f"http://127.0.0.1:{hub_port}",
                }
            ),
            encoding="utf-8",
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
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(engines_root),
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "PYTHONUNBUFFERED": "1",
                # The fake hub is on loopback; no proxy may stand between.
                "NO_PROXY": "127.0.0.1,localhost",
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
            print(f"agent :{agent_port}, library :{library_port}, hub :{hub_port}", flush=True)

            # D1 -----------------------------------------------------------
            engines = client.get("/v1/engines").json()["engines"]
            by = {e["engine"]: e for e in engines}
            llama = by["llama_cpp"]
            check(
                "D1 the installed llama.cpp declares its own build's architectures, nothing else",
                llama["available"] is True
                and llama.get("version") == "b1"
                and [r.get("architectures") for r in llama["accepts"]] == [build_names]
                and all(r.get("authority") in (None, "eugene") for r in llama["accepts"]),
                {k: llama.get(k) for k in ("available", "version")},
            )
            sent = as_console_sends(engines)

            # D2 -----------------------------------------------------------
            page = client.get(f"{proxy}/v1/catalogue/search", params={"q": "x"}).json()
            rows = {r["repo"]: r for r in page["results"]}
            searches = [q for path, q, _ in HUB_REQUESTS if path == "/api/models"]
            check(
                "D2 the hub is asked for its GGUF block on a search, with every field a row shows",
                bool(searches)
                and "gguf" in searches[-1].get("expand[]", [])
                and "downloads" in searches[-1].get("expand[]", []),
                searches[-1:] or "no search reached the hub",
            )
            facts = {r: (rows[r].get("facts") or []) for r in rows}
            check(
                "D2 rows carry approximate facts: GGUF architecture from the hub, MLX from tags",
                set(rows) == {s["id"] for s in SEARCH}
                and facts["org/FlashNext-GGUF"][0].get("architecture") == "qwen4exp"
                and facts["mlx-community/Tiny-4bit"][0].get("mlxQuantized") is True
                and facts["org/Plain"][0].get("mlxQuantized") is False
                and all(f.get("approximate") for fs in facts.values() for f in fs),
                facts,
            )

            # D3 -----------------------------------------------------------
            every = [f for fs in facts.values() for f in fs]
            answer = client.post(
                f"{proxy}/v1/eligibility", json={"candidates": every, "engines": sent}
            )
            judged = {m["modelId"]: m for m in answer.json().get("models", [])}

            def of(repo: str) -> dict[str, Any]:
                return judged[facts[repo][0]["id"]]

            def verdict(repo: str, engine: str) -> dict[str, Any]:
                return next(v for v in of(repo)["engines"] if v["engine"] == engine)

            check(
                "D3 the Library judges every row, through the agent's proxy",
                answer.status_code == 200 and set(judged) == {f["id"] for f in every},
                answer.text[:300],
            )
            check(
                "D3 a llama GGUF row works here, on the installed build, marked approximate",
                of("org/Small-GGUF")["level"] == "works_here"
                and verdict("org/Small-GGUF", "llama_cpp")["verdict"] == "runs"
                and of("org/Small-GGUF")["approximate"] is True,
                of("org/Small-GGUF"),
            )
            flash = of("org/FlashNext-GGUF")
            strata_here = by["strata"]["available"] or could_have_here(by["strata"])
            expected = "other_engine" if strata_here else "not_here"
            check(
                f"D3 a Flash-Next row: this llama.cpp build does not know qwen4exp, Strata "
                f"would prepare it ({expected})",
                verdict("org/FlashNext-GGUF", "llama_cpp")["verdict"] == "no"
                and "qwen4exp is not one of them"
                in verdict("org/FlashNext-GGUF", "llama_cpp")["reason"]
                and verdict("org/FlashNext-GGUF", "strata")["verdict"] == "after_preparation"
                and flash["level"] == expected,
                flash,
            )

            # D4 -----------------------------------------------------------
            before = len(HUB_REQUESTS)
            detail = client.get(
                f"{proxy}/v1/catalogue/model", params={"repo": "mlx-community/Tiny-4bit"}
            ).json()
            reads = [
                rng for path, _, rng in HUB_REQUESTS[before:]
                if path.endswith("/resolve/main/config.json")
            ]
            mlx_facts = detail["candidates"][0].get("facts") or {}
            check(
                "D4 an MLX folder's detail reads its remote config.json, one ranged read",
                len(reads) == 1
                and (reads[0] or "").startswith("bytes=0-")
                and mlx_facts.get("mlxQuantized") is True
                and mlx_facts.get("architecture") == "Qwen3ForCausalLM"
                and not mlx_facts.get("approximate"),
                {"reads": reads, "facts": mlx_facts},
            )
            one = client.post(
                f"{proxy}/v1/eligibility", json={"candidates": [mlx_facts], "engines": sent}
            ).json()["models"][0]
            vllm = next(v for v in one["engines"] if v["engine"] == "vllm")
            mlx = next(v for v in one["engines"] if v["engine"] == "mlx")
            check(
                "D4 so MLX runs it and vLLM says why not, before anything is downloaded",
                mlx["verdict"] == "runs"
                and vllm["verdict"] == "no"
                and "MLX-quantized" in vllm["reason"]
                and not any(models.iterdir()),
                one,
            )

            # D5 -----------------------------------------------------------
            plain = client.get(f"{proxy}/v1/catalogue/model", params={"repo": "org/Plain"}).json()
            candidate = plain["candidates"][0]
            judged_plain = client.post(
                f"{proxy}/v1/eligibility",
                json={"candidates": [candidate["facts"]], "engines": sent},
            ).json()["models"][0]
            plain_vllm = next(v for v in judged_plain["engines"] if v["engine"] == "vllm")
            check(
                "D5 a plain folder: vLLM may run it, in its own words, and nothing was guessed",
                candidate["facts"].get("mlxQuantized") is False
                and plain_vllm["verdict"] == "may_run"
                and "vLLM checks the architecture" in plain_vllm["reason"]
                and judged_plain["approximate"] is False,
                judged_plain,
            )
            check(
                "D5 its SentencePiece tokenizer comes with the download (section 7)",
                "tokenizer.model" in [f["path"] for f in candidate["files"]],
                [f["path"] for f in candidate["files"]],
            )

            # D6 -----------------------------------------------------------
            starter = client.get(f"{proxy}/v1/catalogue/starter").json()["models"]
            starter_facts = [m.get("facts") for m in starter]
            starter_judged = client.post(
                f"{proxy}/v1/eligibility",
                json={"candidates": [f for f in starter_facts if f], "engines": sent},
            ).json()["models"]
            check(
                "D6 every starter entry carries facts, and the installed build runs each",
                bool(starter)
                and all(f and f.get("architecture") for f in starter_facts)
                and len(starter_judged) == len(starter)
                and all(m["level"] == "works_here" for m in starter_judged),
                [(m["modelId"], m["level"]) for m in starter_judged],
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
            hub.shutdown()
            if FAILURES:
                print("--- agent log (last 60 lines) ---")
                print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))
    print(f"{'FAILED' if FAILURES else 'PASSED'}: {len(FAILURES)} failing check(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
