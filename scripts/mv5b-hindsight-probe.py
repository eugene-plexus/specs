#!/usr/bin/env python3
"""MV5b feasibility probe: Hindsight 1.0.0 as a local memory server (workbench-memory-v2.md 52).

No product code. A throwaway stack, every port owned by this run, torn down by pid:

* `llama-server` three times on the GPU: the chat model under test, Qwen3-Embedding-0.6B
  (`--embedding`) and bge-reranker-v2-m3 (`--reranking`);
* one inference-driver per server (`openai_compat_custom`), a stub agent that lists them, and a
  real gateway, so Hindsight reaches every model through Eugene's own doors (`/v1`,
  `/v1/embeddings`, `/v1/rerank` as Cohere);
* `hindsight-api` from a scratch venv (`--hindsight-venv`, with `hindsight-all==1.0.0` and
  `psutil`), on embedded `pg0`, its LLM, embedder and reranker all pointed at that gateway.

Steps (the numbers are section 52's):

  1. Hindsight starts on embedded pg0: how long, peak RAM of its process tree, disk (venv and
     pg0 data). `--linux` runs only this step, with a stub model server, for WSL.
  2. Every socket of its process tree is sampled every 0.2 s for the whole run; anything not on
     loopback is listed (connections and listening sockets).
  3. A labelled person (36 sessions: facts, preferences, projects, events, five superseded
     facts and distractors) is retained session by session, each as Workbench sends it under
     Standard (the person's own words, `context` "A Workbench chat"), timed. Then 21 questions
     are recalled with Workbench's budget (`max_tokens` 1000), and the same questions are put to
     two stand-ins for Workbench's past-chats search over the same sessions: the embedder's
     cosine top 5 and BM25 top 5. A question is answered when a result in the top 5 matches its
     label; a superseded fact is stale when the old value ranks above the new.
  4. Its MCP (`/mcp/{bank}/`, its auth token) through Workbench's own adapter
     (`memory_servers.Servers`, `memoryServers: any`): the verbs found, recall timed against the
     2 s turn limit, retain, forget, list and purge.

Results go to stdout and to `--out` as JSON.

  # Windows, one model a run
  HS/venv/Scripts/python.exe specs/scripts/mv5b-hindsight-probe.py \
      --hindsight-venv HS/venv --llama-server C:/sd1-acceptance/engine/b11719/llama-server.exe \
      --model C:/mr8-models/gemma-4-12b/gemma-4-12b-it-Q4_K_M.gguf --name gemma-4-12b \
      --out docs/acceptance/mv5b-data/gemma-4-12b.json

  # Linux (WSL), step 1 only
  python specs/scripts/mv5b-hindsight-probe.py --linux --hindsight-venv ~/hs-venv --out ...
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re

import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import psutil

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
WINDOWS = os.name == "nt"
PORTS = dict(
    zip(
        (
            "chat",
            "embed",
            "rerank",
            "d_chat",
            "d_embed",
            "d_rerank",
            "agent",
            "gateway",
            "hs",
            "stub",
        ),
        range(8520, 8530),
        strict=True,
    )
)
CHAT, EMBED, RERANK = "probe-chat", "probe-embed", "probe-rerank"
BANK = "probe"
MCP_TOKEN = "mv5b-probe-mcp-token"
BUDGET = 1000  # Workbench: relevant budget 3,200 at a 32k window, a third to the server
TOP = 5
LOOPBACK = ("127.", "::1", "0:0:0:0:0:0:0:1", "::ffff:127.")

# --- the labelled person ------------------------------------------------------
# (id, day of October 2026, the person's words). Built from Workbench's MV3 sets
# (`memory_measure.SETS`), as one person: the five `update` priors come first.
SESSIONS: list[tuple[str, int, str]] = [
    ("vim", 1, "I use Vim as my editor. How do I search and replace across a file?"),
    (
        "denver",
        1,
        "I live in Denver. Where can I see the aspens change colour this week?",
    ),
    (
        "teacher",
        2,
        "I work as a teacher. How do I keep a class of 30 quiet during a test?",
    ),
    (
        "vegetarian",
        2,
        "I'm vegetarian. What can I make with chickpeas and spinach tonight?",
    ),
    ("iphone", 3, "I use an iPhone. How do I turn off the keyboard clicks?"),
    (
        "arch",
        3,
        "I run Arch Linux on my laptop. How do I list installed packages by size?",
    ),
    (
        "rust",
        4,
        "I code mostly in Rust these days, coming from C++. Why does the borrow checker "
        "reject a second mutable borrow?",
    ),
    (
        "two_kids",
        4,
        "I have two kids, 6 and 9, and we're trying to cut screen time. Any board "
        "games for that age?",
    ),
    (
        "proxmox",
        5,
        "Our homelab runs Proxmox on three old Dell Optiplexes. Is Ceph worth it at "
        "that size?",
    ),
    (
        "japanese",
        5,
        "I'm learning Japanese, currently around JLPT N4. Can you explain the "
        "difference between wa and ga?",
    ),
    (
        "left_handed",
        6,
        "I'm left-handed and I've just started calligraphy. Which pen nibs work best?",
    ),
    (
        "gpu",
        6,
        "I'm on Windows 11 with an RTX 5090. Which CUDA version should I install for "
        "llama.cpp?",
    ),
    (
        "short",
        7,
        "Please keep answers short. Bullet points are fine. How do I rename a git branch?",
    ),
    (
        "british",
        7,
        "I prefer British spelling in anything you write for me. Draft a two-line "
        "thank-you note to my landlord.",
    ),
    (
        "unraid",
        8,
        "I'm building a home NAS on Unraid with 6 drives. Which parity setup should I use?",
    ),
    (
        "novel",
        8,
        "I'm writing a fantasy novel set in a desert city; I'm on chapter 12. Help me "
        "name a spice merchant.",
    ),
    (
        "marathon",
        9,
        "I'm training for my first marathon in April. How many long runs a week "
        "should I do?",
    ),
    (
        "tokyo",
        9,
        "I'm flying to Tokyo on November 3rd for two weeks. What should I pack for that "
        "weather?",
    ),
    (
        "interview",
        10,
        "I have a job interview on Thursday for a data analyst role. What questions "
        "should I prepare?",
    ),
    (
        "pihole",
        10,
        "How do I set up a cron job?\nIt's for my Raspberry Pi that runs Pi-hole for "
        "the whole house.\nEvery night at 2am.",
    ),
    # distractors (MV3's `nothing` and `transient` sets)
    ("d_math", 11, "What's 15% of 240?"),
    ("d_tcp", 11, "Explain the difference between TCP and UDP."),
    (
        "d_sam",
        12,
        "My friend Sam is vegan and allergic to nuts; what can I bake for her birthday?",
    ),
    ("d_dentist", 12, "If I were a dentist, how much would I make in Canada?"),
    (
        "d_ill",
        13,
        "I'm ill today so keep answers short just for today. What's 12 squared?",
    ),
    (
        "d_oslo",
        13,
        "I used to live in Oslo years ago. What's the best season to visit now?",
    ),
    (
        "d_pottery",
        14,
        "I might take up pottery someday, who knows. Is it an expensive hobby?",
    ),
    (
        "d_boss",
        14,
        "My boss likes reports in bullet points. Turn this into bullets: sales rose 4% "
        "and costs fell.",
    ),
    (
        "d_spanish",
        15,
        "For this answer only, use Spanish: what's Madrid like in winter?",
    ),
    # the updates
    (
        "helix",
        16,
        "I've switched from Vim to Helix as my editor. How do I select a whole line?",
    ),
    (
        "portland",
        17,
        "We moved from Denver to Portland last month. What's a good weekend hike "
        "near Portland?",
    ),
    (
        "tester",
        18,
        "I'm no longer a teacher, I work as a software tester now. How do I write a "
        "good bug report?",
    ),
    (
        "pescatarian",
        19,
        "I'm not vegetarian any more, I eat fish now. Any quick salmon recipes?",
    ),
    (
        "pixel",
        20,
        "I switched from an iPhone to a Pixel 9. How do I move my WhatsApp chats over?",
    ),
    (
        "tokyo_cancel",
        21,
        "I was going to Tokyo in November but I cancelled the trip. Can I change "
        "yen back to dollars at a bank?",
    ),
    ("d_lol", 22, "lol ok thanks"),
]

# (question, label that answers it, label of the superseded value or None). Labels as
# `memory_measure.matches`: `|` alternatives, `&` all of, each starting a word.
QUESTIONS: list[tuple[str, str, str | None]] = [
    ("What operating system is on my laptop?", "arch", None),
    ("Which programming language do I mostly use?", "rust", None),
    (
        "How many children do I have?",
        "two kids|two children|kids|children|6 and 9",
        None,
    ),
    ("What runs in my homelab?", "proxmox", None),
    ("Which language am I learning?", "japanese", None),
    ("Am I left-handed or right-handed?", "left", None),
    ("What GPU do I have?", "5090", None),
    ("How do I like my answers formatted?", "short|brief|bullet|concise", None),
    ("Which spelling should you use for me?", "british", None),
    ("What NAS am I building?", "unraid", None),
    ("What am I writing at the moment?", "novel|fantasy", None),
    ("What race am I training for?", "marathon", None),
    ("What job am I interviewing for?", "data analyst|analyst", None),
    ("What does my Raspberry Pi run?", "pi-hole|pihole", None),
    ("Which text editor do I use?", "helix", "vim"),
    ("Which city do I live in?", "portland", "denver|oslo"),
    ("What do I do for work?", "tester|testing", "teacher"),
    ("Do I eat fish?", "fish|pescatar", "vegetarian"),
    ("What phone do I have?", "pixel", "iphone"),
    ("Am I still going to Tokyo in November?", "cancel", None),
    (
        "What should I cook for my own dinner, given my diet?",
        "fish|pescatar|salmon",
        "vegetarian",
    ),
]


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def matches(label: str, text: str) -> bool:
    folded = _norm(text)
    return all(
        any(
            re.search(r"(?<![^\W_])" + re.escape(alt.strip()), folded)
            for alt in group.split("|")
        )
        for group in label.split("&")
    )


def judge(texts: list[str], label: str, stale: str | None) -> dict[str, Any]:
    top = texts[:TOP]
    hit = next((i for i, t in enumerate(top) if matches(label, t)), None)
    old = None
    if stale:
        old = next(
            (
                i
                for i, t in enumerate(top)
                if matches(stale, t) and not matches(label, t)
            ),
            None,
        )
    return {
        "answered": hit is not None,
        "rank": hit,
        "stale_first": stale is not None
        and old is not None
        and (hit is None or old < hit),
    }


# --- small helpers ------------------------------------------------------------


def say(text: str) -> None:
    print(text, flush=True)


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def until(probe: Any, seconds: float, every: float = 1.0) -> Any:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        try:
            got = probe()
        except Exception:
            got = None
        if got:
            return got
        time.sleep(every)
    return None


def size_of(path: Path) -> int:
    total = 0
    for dirpath, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                pass
    return total


def gib(n: float) -> str:
    return f"{n / 2**30:.2f} GiB"


class Procs:
    def __init__(self, logs: Path) -> None:
        self.logs = logs
        self.procs: dict[str, subprocess.Popen[bytes]] = {}

    def start(
        self, name: str, argv: list[str], env: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        handle = open(self.logs / f"{name}.log", "ab")  # noqa: SIM115
        extra: dict[str, Any] = {}
        if WINDOWS:
            extra["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            extra["start_new_session"] = True
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT, env=env,
            **extra,
        )  # fmt: skip
        self.procs[name] = proc
        return proc

    def kill(self, name: str) -> None:
        proc = self.procs.pop(name, None)
        if proc is None:
            return
        try:
            tree = [
                psutil.Process(proc.pid),
                *psutil.Process(proc.pid).children(recursive=True),
            ]
        except psutil.Error:
            tree = []
        if not WINDOWS:
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(15)
            except Exception:
                pass
        for p in reversed(tree):
            try:
                p.kill()
            except psutil.Error:
                pass

    def kill_all(self) -> None:
        for name in list(self.procs)[::-1]:
            self.kill(name)


class Watch(threading.Thread):
    """Every socket of a process tree, every 0.2 s: what is not on loopback, and peak RSS."""

    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.stop = threading.Event()
        self.outside: Counter[str] = Counter()
        self.listen_outside: set[str] = set()
        self.names: set[str] = set()
        self.peak_rss = 0
        self.samples = 0

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                root = psutil.Process(self.pid)
                tree = [root, *root.children(recursive=True)]
            except psutil.Error:
                tree = []
            rss = 0
            for p in tree:
                try:
                    self.names.add(p.name())
                    rss += p.memory_info().rss
                    for c in p.net_connections(kind="inet"):
                        if c.status == psutil.CONN_LISTEN:
                            if c.laddr and not str(c.laddr.ip).startswith(LOOPBACK):
                                self.listen_outside.add(
                                    f"{p.name()} {c.laddr.ip}:{c.laddr.port}"
                                )
                        elif c.raddr and not str(c.raddr.ip).startswith(LOOPBACK):
                            self.outside[
                                f"{p.name()} -> {c.raddr.ip}:{c.raddr.port}"
                            ] += 1
                except psutil.Error:
                    continue
            self.peak_rss = max(self.peak_rss, rss)
            self.samples += 1
            self.stop.wait(0.2)


def clean_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("EUGENE_PLEXUS_", "HINDSIGHT_"))
    }
    for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        env.pop(proxy, None)
        env.pop(proxy.lower(), None)
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "COHERE_API_KEY",
        "GEMINI_API_KEY",
        "HF_TOKEN",
    ):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def pg0_dirs() -> list[Path]:
    home = Path.home()
    found = [home / ".pg0"]
    if WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        found += [local / "pg0", Path(os.environ.get("APPDATA", home)) / "pg0"]
    else:
        found += [home / ".local" / "share" / "pg0"]
    return [p for p in found if p.exists()]


# --- the stub model (Linux step 1 only) ---------------------------------------


class StubModel(BaseHTTPRequestHandler):
    """Answers embeddings with a fixed vector and chat with an empty JSON object."""

    def log_message(self, *args: Any) -> None:
        pass

    def _json(self, body: Any) -> None:
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._json({"data": [{"id": "stub", "object": "model"}]})

    def do_POST(self) -> None:
        body = json.loads(
            self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}"
        )
        if self.path.endswith("/embeddings"):
            inputs = body.get("input")
            inputs = inputs if isinstance(inputs, list) else [inputs]
            data = [
                {
                    "object": "embedding",
                    "index": i,
                    "embedding": [((i + j) % 7) / 7 for j in range(384)],
                }
                for i in range(len(inputs))
            ]
            return self._json({"object": "list", "data": data, "model": "stub"})
        if self.path.endswith("/rerank"):
            docs = body.get("documents") or []
            return self._json(
                {
                    "results": [
                        {"index": i, "relevance_score": 1 / (i + 1)}
                        for i in range(len(docs))
                    ]
                }
            )
        self._json(
            {
                "id": "x",
                "object": "chat.completion",
                "model": "stub",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )


# --- the Eugene stack (Windows) ----------------------------------------------


class Agent(BaseHTTPRequestHandler):
    """Topology only: the three drivers."""

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        body: Any = {"status": "ok"}
        if path == "/v1/components":
            body = {
                "components": [
                    {
                        "name": f"probe-{n}",
                        "kind": "inference-driver",
                        "url": f"http://127.0.0.1:{PORTS['d_' + n]}/",
                        "status": "running",
                    }
                    for n in ("chat", "embed", "rerank")
                ]
            }
        elif path == "/v1/runtimes":
            body = {"runtimes": []}
        elif path == "/v1/node":
            body = {"name": "mv5b-node", "enrolled": False}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(handler: type[BaseHTTPRequestHandler], port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_eugene(
    args: argparse.Namespace, procs: Procs, work: Path, env: dict[str, str]
) -> str:
    server = str(args.llama_server)
    common = ["--host", "127.0.0.1", "-ngl", "99", "--no-webui"]
    procs.start(
        "llama-chat",
        [server, "-m", str(args.model), "--port", str(PORTS["chat"]), "-c", str(args.ctx),
         "-np", str(args.parallel), "--jinja", *common],
        env,
    )  # fmt: skip
    procs.start(
        "llama-embed",
        [server, "-m", str(args.embed_model), "--port", str(PORTS["embed"]), "--embedding",
         "--pooling", "last", "-c", "8192", "-np", "4", "-ub", "2048", *common],
        env,
    )  # fmt: skip
    procs.start(
        "llama-rerank",
        [server, "-m", str(args.rerank_model), "--port", str(PORTS["rerank"]), "--reranking",
         "-c", "8192", "-np", "4", "-ub", "2048", *common],
        env,
    )  # fmt: skip
    # A driver learns what its engine serves once, at start: the models must be loaded first.
    for name in ("chat", "embed", "rerank"):
        url = f"http://127.0.0.1:{PORTS[name]}/health"
        if not until(
            lambda u=url: httpx.get(u, timeout=3, trust_env=False).status_code == 200,
            900,
        ):
            raise SystemExit(
                f"llama-{name} never loaded its model; logs in {procs.logs}"
            )
    for name in ("chat", "embed", "rerank"):
        model = {"chat": CHAT, "embed": EMBED, "rerank": RERANK}[name]
        cfg = work / f"driver-{name}.yaml"
        cfg.write_text(
            f"provider: openai_compat_custom\nbaseUrl: http://127.0.0.1:{PORTS[name]}\n"
            f"modelId: {model}\nbackendLocality: local\nrequestTimeoutSeconds: 600\n",
            encoding="utf-8",
            newline="\n",
        )
        procs.start(
            f"driver-{name}",
            [str(args.driver_python), "-m", "eugene_plexus_inference_driver"],
            {
                **env,
                "EUGENE_PLEXUS_DRIVER_CONFIG_FILE": str(cfg),
                "EUGENE_PLEXUS_DRIVER_BIND_HOST": "127.0.0.1",
                "EUGENE_PLEXUS_DRIVER_BIND_PORT": str(PORTS[f"d_{name}"]),
            },
        )
    serve(Agent, PORTS["agent"])
    (work / "gateway.yaml").write_text(
        "routingRefreshSeconds: 3\n", encoding="utf-8", newline="\n"
    )
    procs.start(
        "gateway",
        [str(args.gateway_python), "-m", "eugene_plexus_gateway"],
        {
            **env,
            "EUGENE_PLEXUS_GATEWAY_CONFIG_FILE": str(work / "gateway.yaml"),
            "EUGENE_PLEXUS_GATEWAY_METRICS_FILE": str(work / "metrics.sqlite3"),
            "EUGENE_PLEXUS_GATEWAY_BIND_HOST": "127.0.0.1",
            "EUGENE_PLEXUS_GATEWAY_BIND_PORT": str(PORTS["gateway"]),
            "EUGENE_PLEXUS_GATEWAY_AGENT_URL": f"http://127.0.0.1:{PORTS['agent']}",
        },
    )
    gw = f"http://127.0.0.1:{PORTS['gateway']}"

    def listed() -> bool:
        got = httpx.get(f"{gw}/v1/models", timeout=5, trust_env=False).json()
        ids = {
            x["id"]
            for x in got.get("data") or []
            if (x.get("x_eugene_plexus") or {}).get("ready_backends", 1)
        }
        return {CHAT, EMBED, RERANK} <= ids

    if not until(listed, 600, 2.0):
        raise SystemExit(
            f"the gateway never listed all three models; logs in {procs.logs}"
        )
    return gw


def preflight(gw: str, out: dict[str, Any]) -> None:
    """The three doors Hindsight will use, called as Hindsight calls them (any bearer)."""
    h = {"Authorization": "Bearer unused"}
    with httpx.Client(trust_env=False, timeout=300, headers=h) as c:
        r = c.post(
            f"{gw}/v1/chat/completions",
            json={"model": CHAT, "messages": [{"role": "user", "content": "Say OK."}],
                  "max_completion_tokens": 64, "reasoning_effort": "none"},
        )  # fmt: skip
        out["preflight_chat"] = [r.status_code, r.text[:300]]
        r = c.post(f"{gw}/v1/embeddings", json={"model": EMBED, "input": ["hello"]})
        dims = len(r.json()["data"][0]["embedding"]) if r.status_code == 200 else None
        out["preflight_embed"] = [r.status_code, dims]
        r = c.post(
            f"{gw}/v1/rerank",
            json={
                "model": RERANK,
                "query": "pets",
                "documents": ["a dog", "a tax form"],
            },
        )
        out["preflight_rerank"] = [r.status_code, r.text[:300]]
    say(f"  preflight: chat {out['preflight_chat'][0]}, embed {out['preflight_embed']}, "
        f"rerank {out['preflight_rerank'][0]}")  # fmt: skip
    if any(
        out[k][0] != 200
        for k in ("preflight_chat", "preflight_embed", "preflight_rerank")
    ):
        raise SystemExit(
            f"a door refused the preflight: {json.dumps(out, indent=1)[:1500]}"
        )


def hindsight_env(
    base: dict[str, str], url: str, args: argparse.Namespace, linux: bool
) -> dict[str, str]:
    env = {
        **base,
        "HINDSIGHT_API_HOST": "127.0.0.1",
        "HINDSIGHT_API_PORT": str(PORTS["hs"]),
        "HINDSIGHT_API_DATABASE_URL": f"pg0://{args.instance}",
        "HINDSIGHT_API_LLM_PROVIDER": "openai",
        "HINDSIGHT_API_LLM_BASE_URL": f"{url}/v1",
        "HINDSIGHT_API_LLM_API_KEY": "unused",
        "HINDSIGHT_API_LLM_MODEL": CHAT if not linux else "stub",
        "HINDSIGHT_API_LLM_MAX_CONCURRENT": str(args.parallel),
        "HINDSIGHT_API_LLM_TIMEOUT": "600",
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "openai",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL": f"{url}/v1",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": "unused",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL": EMBED if not linux else "stub",
        "HINDSIGHT_API_RERANKER_PROVIDER": "cohere",
        # Posted to as given: a Cohere-compatible host's whole rerank path
        "HINDSIGHT_API_RERANKER_COHERE_BASE_URL": f"{url}/v1/rerank",
        "HINDSIGHT_API_RERANKER_COHERE_API_KEY": "unused",
        "HINDSIGHT_API_RERANKER_COHERE_MODEL": RERANK if not linux else "stub",
        "HINDSIGHT_API_MCP_ENABLED": "true",
        "HINDSIGHT_API_MCP_AUTH_TOKEN": MCP_TOKEN,
        "HINDSIGHT_API_OTEL_TRACES_ENABLED": "false",
    }
    if args.reasoning_effort:
        env["HINDSIGHT_API_LLM_REASONING_EFFORT"] = args.reasoning_effort
    if linux:
        env["HINDSIGHT_API_LLM_PROVIDER"] = "none"
        env["HINDSIGHT_API_SKIP_LLM_VERIFICATION"] = "true"
    return env


def start_hindsight(
    args: argparse.Namespace, procs: Procs, env: dict[str, str], out: dict[str, Any]
) -> Watch:
    bindir = args.hindsight_venv / ("Scripts" if WINDOWS else "bin")
    exe = bindir / ("hindsight-api.exe" if WINDOWS else "hindsight-api")
    t0 = time.perf_counter()
    proc = procs.start("hindsight", [str(exe)], env)
    watch = Watch(proc.pid)
    watch.start()
    hs = f"http://127.0.0.1:{PORTS['hs']}"

    def ready() -> bool:
        if proc.poll() is not None:
            raise SystemExit(
                f"hindsight-api exited {proc.returncode}; see {procs.logs / 'hindsight.log'}"
            )
        return httpx.get(f"{hs}/health", timeout=3, trust_env=False).status_code == 200

    try:
        ok = until(ready, args.start_seconds, 1.0)
    except SystemExit as exc:
        out["start"] = {"ok": False, "why": str(exc)}
        raise
    out["start"] = {"ok": bool(ok), "seconds": round(time.perf_counter() - t0, 1),
                    "rss_at_ready": gib(watch.peak_rss)}  # fmt: skip
    say(f"1. hindsight ready: {out['start']}")
    if not ok:
        raise SystemExit(
            f"hindsight never answered /health; see {procs.logs / 'hindsight.log'}"
        )
    return watch


# --- step 3: retain and recall -----------------------------------------------


def iso(day: int) -> str:
    return f"2026-10-{day:02d}T12:00:00Z"


def retain_all(hs: str, out: dict[str, Any]) -> None:
    times: list[float] = []
    failures: list[str] = []
    with httpx.Client(trust_env=False, timeout=1800) as c:
        for ident, day, words in SESSIONS:
            t = time.perf_counter()
            r = c.post(
                f"{hs}/v1/default/banks/{BANK}/memories",
                json={"items": [{"content": words, "timestamp": iso(day),
                                 "context": "A Workbench chat", "document_id": f"chat-{ident}:1"}],
                      "async": False},
            )  # fmt: skip
            took = time.perf_counter() - t
            times.append(took)
            if r.status_code >= 300:
                failures.append(f"{ident}: {r.status_code} {r.text[:200]}")
            say(f"  retain {ident}: {r.status_code} in {took:.1f} s")
        r = c.post(f"{hs}/v1/default/banks/{BANK}/memories/list", json={"limit": 500})
        if r.status_code >= 400:
            r = c.get(
                f"{hs}/v1/default/banks/{BANK}/memories/list", params={"limit": 500}
            )
        kept: list[str] = []
        if r.status_code == 200:
            body = r.json()
            items = (
                body.get("items") or body.get("memories") or body.get("results") or []
            )
            kept = [str(i.get("text") or i.get("content") or i) for i in items]
    times.sort()
    out["retain"] = {
        "sessions": len(SESSIONS),
        "total_seconds": round(sum(times), 1),
        "median_seconds": round(times[len(times) // 2], 1),
        "max_seconds": round(times[-1], 1),
        "failures": failures,
        "memories_listed": len(kept),
        "memories": kept[:200],
    }
    say(f"3a. retained {len(SESSIONS)} sessions in {sum(times):.0f} s "
        f"(median {times[len(times) // 2]:.1f} s), {len(failures)} failed, {len(kept)} memories")  # fmt: skip


def recall_texts(body: Any) -> list[str]:
    items = body.get("results") if isinstance(body, dict) else body
    return [str(i.get("text") or "") for i in items or [] if isinstance(i, dict)]


def bm25(query: str, docs: list[str]) -> list[int]:
    tok = [re.findall(r"\w+", _norm(d)) for d in docs]
    q = re.findall(r"\w+", _norm(query))
    n = len(docs)
    avg = sum(map(len, tok)) / n
    df = Counter(w for t in tok for w in set(t))
    scores = []
    for t in tok:
        tf = Counter(t)
        s = 0.0
        for w in q:
            if w in tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(t) / avg))
        scores.append(s)
    return sorted(range(n), key=lambda i: -scores[i])


def recall_all(hs: str, gw: str, out: dict[str, Any]) -> None:
    docs = [w for _, _, w in SESSIONS]
    with httpx.Client(trust_env=False, timeout=300) as c:
        e = c.post(f"{gw}/v1/embeddings", json={"model": EMBED, "input": docs}).json()[
            "data"
        ]
        vecs = [x["embedding"] for x in sorted(e, key=lambda x: x["index"])]

        def cosine_top(q: str) -> list[int]:
            v = c.post(
                f"{gw}/v1/embeddings", json={"model": EMBED, "input": [q]}
            ).json()["data"][0]["embedding"]
            nv = math.sqrt(sum(x * x for x in v))
            sims = [
                sum(a * b for a, b in zip(v, d, strict=True))
                / (nv * math.sqrt(sum(x * x for x in d)))
                for d in vecs
            ]
            return sorted(range(len(docs)), key=lambda i: -sims[i])

        rows = []
        latencies = []
        for q, label, stale in QUESTIONS:
            t = time.perf_counter()
            r = c.post(f"{hs}/v1/default/banks/{BANK}/memories/recall",
                       json={"query": q, "max_tokens": BUDGET})  # fmt: skip
            took = time.perf_counter() - t
            latencies.append(took)
            texts = recall_texts(r.json()) if r.status_code == 200 else []
            row = {
                "question": q,
                "seconds": round(took, 2),
                "hindsight": judge(texts, label, stale),
                "hindsight_top": texts[:TOP],
                "cosine": judge([docs[i] for i in cosine_top(q)], label, stale),
                "bm25": judge([docs[i] for i in bm25(q, docs)], label, stale),
            }
            if r.status_code != 200:
                row["error"] = [r.status_code, r.text[:200]]
            rows.append(row)
            say(f"  {q} -> hindsight {row['hindsight']['answered']} "
                f"(stale {row['hindsight']['stale_first']}), cosine {row['cosine']['answered']}, "
                f"bm25 {row['bm25']['answered']}, {took:.2f} s")  # fmt: skip
    latencies.sort()

    def tally(key: str) -> dict[str, int]:
        return {
            "answered": sum(r[key]["answered"] for r in rows),
            "stale_first": sum(r[key]["stale_first"] for r in rows),
            "of": len(rows),
        }

    out["recall"] = {
        "rows": rows,
        "hindsight": tally("hindsight"),
        "cosine": tally("cosine"),
        "bm25": tally("bm25"),
        "median_seconds": round(latencies[len(latencies) // 2], 2),
        "max_seconds": round(latencies[-1], 2),
        "over_2s": sum(x > 2.0 for x in latencies),
    }
    say(f"3b. answered of {len(rows)}: hindsight {out['recall']['hindsight']}, "
        f"cosine {out['recall']['cosine']}, bm25 {out['recall']['bm25']}; recall median "
        f"{out['recall']['median_seconds']} s, max {out['recall']['max_seconds']} s")  # fmt: skip


# --- step 4: Workbench's adapter ---------------------------------------------

ADAPTER = r"""
import asyncio, json, sys, time
sys.path.insert(0, sys.argv[1])
from eugene_plexus_workbench import memory_servers as ms

class Store:
    async def memory_server_reached(self, owner, reason):
        pass

async def main(url, token):
    out = {}
    servers = ms.Servers(Store())
    t = time.perf_counter()
    name, verbs = await servers.discover(url, token, "any")
    out["discover"] = {"name": name, "verbs": {k: v.get("tool") for k, v in verbs.items()},
                       "seconds": round(time.perf_counter() - t, 2)}
    server = {"owner": "probe", "url": url, "token": token, "verbs": verbs}
    async def call(verb, wanted, seconds=ms.CALL_SECONDS):
        t = time.perf_counter()
        try:
            items = await servers.call(server, "any", verb, wanted, seconds)
            return {"ok": True, "items": [i.text[:160] for i in items][:5], "n": len(items),
                    "seconds": round(time.perf_counter() - t, 2)}
        except ms.ServerProblem as exc:
            return {"ok": False, "why": exc.message, "seconds": round(time.perf_counter() - t, 2)}
    turns = []
    for q in ["Which text editor do I use?", "What GPU do I have?", "Which city do I live in?"]:
        turns.append({"query": q, **await call("recall", {"query": q, "max_tokens": 1000},
                                                ms.RECALL_SECONDS)})
    out["recall_in_turn"] = turns
    out["retain"] = await call("retain", {"content": "I keep bees in my back garden.",
                                          "document_id": "chat-bees:1",
                                          "timestamp": "2026-10-23T12:00:00Z",
                                          "context": "A Workbench chat"})
    out["recall_bees"] = await call("recall", {"query": "Do I have any hobbies with animals?",
                                               "max_tokens": 1000})
    if "forget" in verbs:
        out["forget"] = await call("forget", {"document_id": "chat-bees:1"})
        out["recall_after_forget"] = await call("recall", {"query": "bees", "max_tokens": 1000})
    if "list" in verbs:
        out["list"] = await call("list", {"limit": 100, "offset": 0})
    if "purge" in verbs:
        out["purge"] = await call("purge", {})
        if "list" in verbs:
            out["list_after_purge"] = await call("list", {"limit": 100, "offset": 0})
    print(json.dumps(out))

asyncio.run(main(sys.argv[2], sys.argv[3]))
"""


def adapter(
    args: argparse.Namespace, work: Path, env: dict[str, str], out: dict[str, Any]
) -> None:
    script = work / "adapter.py"
    script.write_text(ADAPTER, encoding="utf-8", newline="\n")
    url = f"http://127.0.0.1:{PORTS['hs']}/mcp/{BANK}/"
    r = subprocess.run(
        [str(args.workbench_python), str(script), str(ROOT / "workbench" / "src"), url, MCP_TOKEN],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=900,
    )  # fmt: skip
    try:
        out["adapter"] = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out["adapter"] = {
            "error": r.returncode,
            "stderr": r.stderr[-2000:],
            "stdout": r.stdout[-500:],
        }
    say(f"4. adapter: {json.dumps(out['adapter'])[:1500]}")


# --- main ----------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--hindsight-venv", type=Path, required=True)
    p.add_argument(
        "--linux", action="store_true", help="step 1 only, with a stub model"
    )
    p.add_argument("--llama-server", type=Path)
    p.add_argument("--model", type=Path)
    p.add_argument("--name", default="model")
    p.add_argument(
        "--embed-model",
        type=Path,
        default=Path.home()
        / ".eugene-plexus/acceptance-models/Qwen3-Embedding-0.6B-Q8_0.gguf",
    )
    p.add_argument(
        "--rerank-model",
        type=Path,
        default=Path.home()
        / ".eugene-plexus/acceptance-models/bge-reranker-v2-m3-Q8_0.gguf",
    )
    p.add_argument("--ctx", type=int, default=65536)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument(
        "--reasoning-effort",
        default="none",
        help="sent by Hindsight on every LLM call ('' to send none)",
    )
    p.add_argument("--instance", default="mv5b-probe", help="the pg0 instance name")
    p.add_argument("--start-seconds", type=float, default=600)
    p.add_argument(
        "--gateway-python", type=Path, default=ROOT / "gateway/.venv/Scripts/python.exe"
    )
    p.add_argument(
        "--driver-python",
        type=Path,
        default=ROOT / "inference-driver/.venv/Scripts/python.exe",
    )
    p.add_argument(
        "--workbench-python",
        type=Path,
        default=ROOT / "workbench/.venv/Scripts/python.exe",
    )
    p.add_argument("--skip-adapter", action="store_true")
    p.add_argument(
        "--keep", action="store_true", help="leave the stack up (Enter to stop)"
    )
    p.add_argument("--out", type=Path)
    args = p.parse_args()

    taken = [port for port in PORTS.values() if listening(port)]
    if taken:
        print(
            f"ports {taken} are taken; this run owns {min(PORTS.values())}-{max(PORTS.values())}"
        )
        return 1
    work = Path(tempfile.mkdtemp(prefix="ep-mv5b-"))
    (work / "logs").mkdir()
    procs = Procs(work / "logs")
    env = clean_env()
    out: dict[str, Any] = {
        "name": "linux" if args.linux else args.name,
        "model": str(args.model) if args.model else None,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "work": str(work),
        "venv_bytes": size_of(args.hindsight_venv),
        "pg0_dirs_before": [str(d) for d in pg0_dirs()],
    }
    say(f"0. work in {work}; hindsight venv {gib(out['venv_bytes'])}")
    watch: Watch | None = None
    code = 1
    try:
        if args.linux:
            serve(StubModel, PORTS["stub"])
            url = f"http://127.0.0.1:{PORTS['stub']}"
        else:
            if not (args.llama_server and args.model):
                print("--llama-server and --model are required on Windows")
                return 1
            url = start_eugene(args, procs, work, env)
            preflight(url, out)
        watch = start_hindsight(
            args, procs, hindsight_env(env, url, args, args.linux), out
        )
        hs = f"http://127.0.0.1:{PORTS['hs']}"
        if args.linux:
            r = httpx.post(
                f"{hs}/v1/default/banks/{BANK}/memories",
                json={"items": [{"content": "I keep bees.", "document_id": "x"}], "async": False},
                timeout=300, trust_env=False,
            )  # fmt: skip
            out["linux_retain"] = [r.status_code, r.text[:300]]
            r = httpx.post(f"{hs}/v1/default/banks/{BANK}/memories/recall",
                           json={"query": "bees", "max_tokens": 500}, timeout=120, trust_env=False)  # fmt: skip
            out["linux_recall"] = [r.status_code, r.text[:300]]
            say(
                f"1. linux retain {out['linux_retain'][0]}, recall {out['linux_recall'][0]}"
            )
        else:
            retain_all(hs, out)
            recall_all(hs, url, out)
            if not args.skip_adapter:
                adapter(args, work, env, out)
        if args.keep:
            input("stack up; Enter to stop ")
        code = 0
    except SystemExit as exc:
        out["stopped"] = str(exc)
        say(f"STOPPED: {exc}")
    finally:
        if watch is not None:
            watch.stop.set()
            watch.join(2)
            out["sockets"] = {
                "samples": watch.samples,
                "outside": dict(watch.outside),
                "listening_outside": sorted(watch.listen_outside),
                "processes": sorted(watch.names),
            }
            out["peak_rss"] = gib(watch.peak_rss)
            say(f"2. sockets: {watch.samples} samples; outside {dict(watch.outside) or 'none'}; "
                f"listening off loopback {sorted(watch.listen_outside) or 'none'}; "
                f"peak RSS {gib(watch.peak_rss)}; processes {sorted(watch.names)}")  # fmt: skip
        procs.kill_all()
        # pg_ctl starts postgres outside hindsight's tree: killing the tree leaves it running.
        for pg0 in args.hindsight_venv.glob("**/site-packages/pg0/bin/pg0*"):
            r = subprocess.run([str(pg0), "stop", "--name", args.instance, "--timeout", "30"],
                               capture_output=True, text=True, timeout=90, env=env)  # fmt: skip
            out["pg0_stop"] = [r.returncode, (r.stdout + r.stderr)[-300:]]
            say(f"   pg0 stop {args.instance}: {r.returncode}")
            break
        out["pg0_dirs_after"] = {str(d): gib(size_of(d)) for d in pg0_dirs()}
        say(f"   pg0 data: {out['pg0_dirs_after']}")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(out, indent=1, ensure_ascii=False),
                encoding="utf-8",
                newline="\n",
            )
            say(f"   written {args.out}")
        still = [port for port in PORTS.values() if listening(port)]
        if still:
            say(f"   ports still listening after teardown: {still}")
    return code


if __name__ == "__main__":
    sys.exit(main())
