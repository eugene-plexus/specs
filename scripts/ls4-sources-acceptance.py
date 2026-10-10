"""LS4 acceptance: catalogue sources are a list; engines publish what they support.

library-sources-and-engines.md, slice LS4. A throwaway standalone agent on
free loopback ports supervises its own Library. Two fake hubs on loopback
(never huggingface.co) stand for the public hub and a company's own hub.
The Library starts from a config file written before LS4: one hub address
and one token, the keys LS4 replaced. Nothing is started but the agent and
its Library; one 2 KiB file is downloaded from the second fake hub.

  S1  the old file's hub address and token become the first hub, the
      token kept and never shown, and the file keeps the old keys beside the
      list for an older Library;
  S2  the agent's GET /v1/engines publishes Strata's own list: upstream
      setup's nine choices, each a named first shard at a pinned revision,
      and Strata's GGUF requirement names exactly those files;
  S3  a second hub is added through the agent's proxy as the console saves
      it, with its own token;
  S4  one POST search, the node's lists sent as the console sends them,
      answers from every source together, each result naming its source;
      each hub was asked with its own token and never the other's;
  S5  the judge: a list entry is *after preparation* for Strata, exactly; a
      Flash-Next K-quant from another publisher is *no* for Strata, naming
      its list, once its file is known;
  S6  a list entry opens its repo at the revision it pins, on the default
      hub, and that version is the one Strata names;
  S7  a repo on the second hub is opened and downloaded from that hub, with
      its token; the record names its source;
  S8  the second hub down: the search still answers, and says why that hub
      gave nothing;
  S9  a hub switched off is not asked and says so; its token survives the
      round trip that switched it off; an older console's GET still searches
      the one default hub.

Clears every ambient EUGENE_PLEXUS_* variable, so it is safe beside a live
install. Run with the agent and library installed (editable is fine).
"""

from __future__ import annotations

import hashlib
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
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import yaml

FAILURES: list[str] = []

FLASH_REPO = "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF"
FLASH_REV = "ed59f92082b1e93c0e96d60a8b11aab089b52f09"
FLASH_FIRST = "IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
OTHER_REPO = "other/FlashNext-K-GGUF"
CORP_REPO = "corp/Inside-GGUF"
CORP_FILE = "inside-Q4_K_M.gguf"
CORP_BYTES = bytes(range(256)) * 8
CORP_SHA = hashlib.sha256(CORP_BYTES).hexdigest()

STRATA_IDS = [
    "Q2_0",
    "IQ2_XS",
    "IQ3_XXS",
    "IQ3_S",
    "swift-IQ2_XS",
    "swift-IQ3_XXS",
    "coder-IQ1_M",
    "unsloth-UD-IQ4_XS",
    "unsloth-UD-Q4_K_XL",
]


def _file(path: str, size: int, sha: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "file", "path": path, "size": size, "oid": "1" * 40}
    if sha is not None:
        entry["lfs"] = {"oid": sha, "size": size}
    return entry


HUBS: dict[str, dict[str, Any]] = {
    "public": {
        "search": [
            {"id": "org/Small-GGUF", "author": "org", "downloads": 40, "tags": ["gguf"],
             "library_name": "gguf", "gguf": {"architecture": "llama"}},
            {"id": OTHER_REPO, "author": "other", "downloads": 30, "tags": ["gguf"],
             "library_name": "gguf", "gguf": {"architecture": "qwen4exp"}},
        ],
        "repos": {
            OTHER_REPO: {
                "info": {"author": "other", "tags": ["gguf"], "gguf": {"architecture": "qwen4exp"}},
                "tree": [
                    _file("FlashNext-UD-Q2_K_XL-00001-of-00002.gguf", 4_000, "a" * 64),
                    _file("FlashNext-UD-Q2_K_XL-00002-of-00002.gguf", 4_000, "b" * 64),
                ],
            },
            FLASH_REPO: {
                "info": {"author": "ISTA-DASLab", "tags": ["gguf"],
                         "gguf": {"architecture": "qwen4exp"}},
                "tree": [
                    _file(FLASH_FIRST, 39_225, "c" * 64),
                    _file(FLASH_FIRST.replace("00001-of", "00002-of"), 28_800, "d" * 64),
                    _file("IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf", 54_817,
                          "e" * 64),
                    _file("IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf", 28_800,
                          "f" * 64),
                ],
            },
        },
    },
    "corp": {
        "search": [
            {"id": CORP_REPO, "author": "corp", "downloads": 3, "tags": ["gguf"],
             "library_name": "gguf", "gguf": {"architecture": "llama"}},
        ],
        "repos": {
            CORP_REPO: {
                "info": {"author": "corp", "tags": ["gguf"], "gguf": {"architecture": "llama"}},
                "tree": [_file(CORP_FILE, len(CORP_BYTES), CORP_SHA)],
            },
        },
    },
}
# Every request each hub saw: (method, path, query, Authorization).
SEEN: dict[str, list[tuple[str, str, dict[str, list[str]], str | None]]] = {
    "public": [],
    "corp": [],
}


def hub_handler(name: str) -> type[BaseHTTPRequestHandler]:
    hub = HUBS[name]

    class FakeHub(BaseHTTPRequestHandler):
        """Only the hub endpoints the Library calls, shaped like the real ones."""

        def log_message(self, *_: object) -> None:
            pass

        def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _route(self) -> None:
            parts = urlsplit(self.path)
            SEEN[name].append(
                (self.command, parts.path, parse_qs(parts.query), self.headers.get("Authorization"))
            )
            path = parts.path
            if path == "/api/models":
                self._send(200, json.dumps(hub["search"]).encode())
                return
            if path.startswith("/api/models/"):
                rest = path[len("/api/models/"):]
                for repo, data in hub["repos"].items():
                    if rest.startswith(f"{repo}/tree/"):
                        self._send(200, json.dumps(data["tree"]).encode())
                        return
                    if rest == repo or rest.startswith(f"{repo}/revision/"):
                        body = {"id": repo, **data["info"], "sha": "c0ffee" * 6 + "c0ff"}
                        self._send(200, json.dumps(body).encode())
                        return
                self._send(404, b'{"error": "Repository not found"}',
                           {"X-Error-Code": "RepoNotFound"})
                return
            if name == "corp" and path == f"/{CORP_REPO}/resolve/{'c0ffee' * 6 + 'c0ff'}/{CORP_FILE}":
                headers = {
                    "X-Linked-Size": str(len(CORP_BYTES)),
                    "X-Linked-ETag": f'"{CORP_SHA}"',
                    "X-Repo-Commit": "c0ffee" * 6 + "c0ff",
                    "Accept-Ranges": "bytes",
                }
                if self.command == "HEAD":
                    self._send(200, CORP_BYTES, headers)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(CORP_BYTES)))
                self.end_headers()
                self.wfile.write(CORP_BYTES)
                return
            if "/resolve/" in path and name == "corp":
                # `main` before the commit is pinned.
                if path == f"/{CORP_REPO}/resolve/main/{CORP_FILE}":
                    self._send(200, b"", {
                        "X-Linked-Size": str(len(CORP_BYTES)),
                        "X-Linked-ETag": f'"{CORP_SHA}"',
                        "X-Repo-Commit": "c0ffee" * 6 + "c0ff",
                    })
                    return
            self._send(404, b'{"error": "Entry not found"}', {"X-Error-Code": "EntryNotFound"})

        def do_GET(self) -> None:  # noqa: N802
            self._route()

        def do_HEAD(self) -> None:  # noqa: N802
            self._route()

    return FakeHub


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


def as_console_judges(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def as_console_lists(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The console's `engineLists`: what the node's engines publish."""
    return [
        {"engine": e["engine"], "models": e["supportedModels"]}
        for e in engines
        if e.get("supportedModels")
    ]


def hosts_seen(name: str, *, path_prefix: str = "") -> list[str | None]:
    return [auth for _, path, _, auth in SEEN[name] if path.startswith(path_prefix)]


def main() -> int:
    public_port, corp_port, agent_port, library_port = free_ports(4)
    hubs = {
        "public": ThreadingHTTPServer(("127.0.0.1", public_port), hub_handler("public")),
        "corp": ThreadingHTTPServer(("127.0.0.1", corp_port), hub_handler("corp")),
    }
    for server in hubs.values():
        threading.Thread(target=server.serve_forever, daemon=True).start()
    public = f"http://127.0.0.1:{public_port}"
    corp = f"http://127.0.0.1:{corp_port}"
    with tempfile.TemporaryDirectory(prefix="ep-ls4-", ignore_cleanup_errors=True) as raw:
        directory = Path(raw)
        models = directory / "models"
        models.mkdir()
        library_yaml = directory / "library.yaml"
        # Written before LS4: one hub, one token.
        library_yaml.write_text(
            yaml.safe_dump(
                {
                    "logLevel": "INFO",
                    "modelRoots": [str(models)],
                    "catalogueBaseUrl": public,
                    "hfToken": "tok-public",
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
                            "spawn": {"configFile": str(library_yaml)},
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
                # The fake hubs are on loopback; no proxy may stand between.
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
            print(
                f"agent :{agent_port}, library :{library_port}, hubs :{public_port} :{corp_port}",
                flush=True,
            )

            # S1 -----------------------------------------------------------
            config = client.get(f"{proxy}/v1/config").json()
            sources = config.get("catalogueSources") or []
            first = next((s for s in sources if s.get("kind") == "hf_hub"), {})
            check(
                "S1a the old file's hub and token are the first hub, the token never shown; "
                "the engines' lists ahead of it, as the default list has them (LS7)",
                first.get("id") == "huggingface"
                and first.get("kind") == "hf_hub"
                and first.get("address") == public
                and first.get("token") is None
                and first.get("hasToken") is True
                and [s.get("kind") for s in sources] == ["engine_list", "hf_hub"]
                and "hfToken" not in config
                and "tok-public" not in json.dumps(config),
                sources,
            )

            # S2 -----------------------------------------------------------
            engines = client.get("/v1/engines").json()["engines"]
            by = {e["engine"]: e for e in engines}
            strata = by["strata"]
            listed = strata.get("supportedModels") or []
            gguf_need = next(
                (r for r in strata["accepts"] if r["format"] == "gguf"), {}
            )
            firsts = [PurePosixPath(m["source"]["file"]).name for m in listed]
            check(
                "S2 Strata publishes upstream setup's nine choices, and prepares those files only",
                [m["id"] for m in listed] == STRATA_IDS
                and all(
                    len(m["source"].get("revision") or "") == 40 and m["source"].get("repoId")
                    for m in listed
                )
                and strata["available"] is False
                and gguf_need.get("files") == firsts
                and not by["llama_cpp"].get("supportedModels"),
                (len(listed), gguf_need.get("files")),
            )

            # S3 -----------------------------------------------------------
            saved = [
                *sources,
                {
                    "id": "corp",
                    "kind": "hf_hub",
                    "label": "Corp hub",
                    "address": corp,
                    "token": "tok-corp",
                },
            ]
            patched = client.patch(f"{proxy}/v1/config", json={"catalogueSources": saved}).json()
            after = client.get(f"{proxy}/v1/config").json()["catalogueSources"]
            on_disk = yaml.safe_load(library_yaml.read_text(encoding="utf-8"))
            check(
                "S3 a second hub is saved with its own token; both tokens stay hidden",
                patched.get("applied") == ["catalogueSources"]
                and [(s["id"], s.get("hasToken")) for s in after]
                == [("engines", None), ("huggingface", True), ("corp", True)]
                and "tok-corp" not in json.dumps(after),
                (patched, after),
            )
            check(
                "S1b the file keeps the old keys beside the list, for an older Library",
                on_disk.get("catalogueBaseUrl") == public
                and bool(on_disk.get("hfToken"))
                # Sealed alike, or plain alike when the Library holds no key.
                and type(on_disk.get("hfToken")) is type(on_disk["catalogueSources"][1]["token"])
                and "hasToken" not in on_disk["catalogueSources"][1],
                {k: on_disk.get(k) for k in ("catalogueBaseUrl", "hfToken")},
            )

            # S4 -----------------------------------------------------------
            for seen in SEEN.values():
                seen.clear()
            lists = as_console_lists(engines)
            page = client.post(
                f"{proxy}/v1/catalogue/search", json={"limit": 30, "engines": lists}
            ).json()
            results = page.get("results") or []
            order = [(r.get("source"), r.get("repo")) for r in results]
            statuses = {s["id"]: s for s in page.get("sources") or []}
            check(
                "S4a every source answers together in the list's order (the engines' lists "
                "first, as this list has them), each result naming its source",
                order[:9] == [("engines", m["source"]["repoId"]) for m in listed]
                and order[9:] == [("huggingface", "org/Small-GGUF"), ("huggingface", OTHER_REPO),
                                  ("corp", CORP_REPO)]
                and all(r.get("engine") == "strata" for r in results[:9])
                and [s["results"] for s in statuses.values()] == [9, 2, 1],
                (order, statuses),
            )
            check(
                "S4b each hub was asked with its own token and never the other's",
                hosts_seen("public", path_prefix="/api/models") == ["Bearer tok-public"]
                and hosts_seen("corp", path_prefix="/api/models") == ["Bearer tok-corp"],
                {k: hosts_seen(k) for k in SEEN},
            )

            # S5 -----------------------------------------------------------
            judges = as_console_judges(engines)
            row_facts = [f for r in results for f in r.get("facts") or []]
            judged = {
                m["modelId"]: m
                for m in client.post(
                    f"{proxy}/v1/eligibility", json={"candidates": row_facts, "engines": judges}
                ).json()["models"]
            }

            def strata_verdict(answer: dict[str, Any]) -> tuple[str, str]:
                v = next(e for e in answer["engines"] if e["engine"] == "strata")
                return v["verdict"], v["reason"]

            listed_answers = [judged[r["facts"][0]["id"]] for r in results[:9]]
            other_row = judged[next(r for r in results if r["repo"] == OTHER_REPO)["facts"][0]["id"]]
            other = client.get(
                f"{proxy}/v1/catalogue/model", params={"repo": OTHER_REPO, "source": "huggingface"}
            ).json()
            version = other["candidates"][0]["facts"]
            version_answer = client.post(
                f"{proxy}/v1/eligibility", json={"candidates": [version], "engines": judges}
            ).json()["models"][0]
            check(
                "S5 a list entry runs on Strata after preparation, exactly; another publisher's "
                "Flash-Next is no for Strata once its file is known",
                all(
                    strata_verdict(a)[0] == "after_preparation" and a["approximate"] is False
                    for a in listed_answers
                )
                and strata_verdict(other_row)[0] == "after_preparation"
                and other_row["approximate"] is True
                and version.get("file") == "FlashNext-UD-Q2_K_XL-00001-of-00002.gguf"
                and strata_verdict(version_answer)
                == ("no", "runs only the 9 files on its own list, and "
                          "FlashNext-UD-Q2_K_XL-00001-of-00002.gguf is not one"),
                (strata_verdict(other_row), strata_verdict(version_answer)),
            )

            # S6 -----------------------------------------------------------
            for seen in SEEN.values():
                seen.clear()
            iq2 = next(r for r in results if (r.get("supported") or {}).get("id") == "IQ2_XS")
            opened = client.get(
                f"{proxy}/v1/catalogue/model",
                params={
                    "repo": iq2["repo"],
                    "source": iq2["hubSource"],
                    "revision": iq2["supported"]["source"]["revision"],
                },
            ).json()
            candidate = next(
                (c for c in opened.get("candidates") or []
                 if c["files"][0]["path"] == iq2["supported"]["source"]["file"]),
                None,
            )
            opened_answer = client.post(
                f"{proxy}/v1/eligibility",
                json={"candidates": [candidate["facts"]] if candidate else [], "engines": judges},
            ).json()["models"]
            check(
                "S6 a list entry opens its repo at the pinned revision on the default hub, and "
                "that version is Strata's",
                iq2["hubSource"] == "huggingface"
                and candidate is not None
                and len(candidate["files"]) == 2
                and any(p == f"/api/models/{FLASH_REPO}/revision/{FLASH_REV}"
                        for _, p, _, _ in SEEN["public"])
                and any(p == f"/api/models/{FLASH_REPO}/tree/{FLASH_REV}"
                        for _, p, _, _ in SEEN["public"])
                and not SEEN["corp"]
                and bool(opened_answer)
                and strata_verdict(opened_answer[0])[0] == "after_preparation",
                (candidate, opened_answer),
            )

            # S7 -----------------------------------------------------------
            for seen in SEEN.values():
                seen.clear()
            detail = client.get(
                f"{proxy}/v1/catalogue/model", params={"repo": CORP_REPO, "source": "corp"}
            )
            started = client.post(
                f"{proxy}/v1/downloads",
                json={"repo": CORP_REPO, "source": "corp", "files": [CORP_FILE]},
            )
            record = started.json()
            done = wait(
                lambda: (
                    lambda r: r if r.get("state") in ("done", "failed") else None
                )(client.get(f"{proxy}/v1/downloads/{record['id']}").json()),
                "the download finishes",
            ) if started.status_code == 202 else {}
            landed = Path(record.get("destinationDirectory") or directory) / CORP_FILE
            check(
                "S7 a repo on the second hub is opened and downloaded from that hub, with its "
                "token, and the record names it",
                detail.status_code == 200
                and started.status_code == 202
                and record.get("source") == "corp"
                and done.get("state") == "done"
                and landed.is_file()
                and landed.read_bytes() == CORP_BYTES
                and not SEEN["public"]
                and {a for a in hosts_seen("corp")} == {"Bearer tok-corp"},
                (detail.status_code, record, done, [(m, p) for m, p, _, _ in SEEN["public"]]),
            )

            # S8 -----------------------------------------------------------
            hubs["corp"].shutdown()
            hubs["corp"].server_close()
            # A query of its own: the Library keeps a search for 60 s, and an
            # answer from that is not the dead hub's.
            down = client.post(
                f"{proxy}/v1/catalogue/search", json={"q": "gguf", "limit": 30, "engines": lists}
            )
            down_page = down.json()
            down_status = {s["id"]: s for s in down_page.get("sources") or []}
            check(
                "S8 one hub down: the search still answers, and says why that hub gave nothing",
                down.status_code == 200
                and {r["source"] for r in down_page["results"]} == {"engines", "huggingface"}
                and down_status["corp"]["results"] == 0
                and "Could not reach" in (down_status["corp"].get("problem") or ""),
                down_status.get("corp"),
            )

            # S9 -----------------------------------------------------------
            for seen in SEEN.values():
                seen.clear()
            shown = client.get(f"{proxy}/v1/config").json()["catalogueSources"]
            for source in shown:
                if source["id"] == "corp":
                    source["enabled"] = False
            client.patch(f"{proxy}/v1/config", json={"catalogueSources": shown})
            off_page = client.post(
                f"{proxy}/v1/catalogue/search", json={"limit": 30, "engines": lists}
            ).json()
            off_status = {s["id"]: s for s in off_page.get("sources") or []}
            kept = {s["id"]: s for s in client.get(f"{proxy}/v1/config").json()["catalogueSources"]}
            older = client.get(f"{proxy}/v1/catalogue/search", params={"limit": 30}).json()
            check(
                "S9 a hub switched off is not asked and says so; its token survives; an older "
                "console's GET still searches the default hub",
                off_status["corp"]["searched"] is False
                and "switched off" in (off_status["corp"].get("problem") or "")
                and kept["corp"].get("hasToken") is True
                and kept["corp"].get("enabled") is False
                and [r["repo"] for r in older.get("results") or []]
                == ["org/Small-GGUF", OTHER_REPO]
                and all(r.get("source") is None for r in older.get("results") or []),
                (off_status.get("corp"), kept.get("corp"), older.get("results")),
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
            hubs["public"].shutdown()
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
