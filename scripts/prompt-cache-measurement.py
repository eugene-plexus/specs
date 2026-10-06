#!/usr/bin/env python3
"""How much of each prompt does the engine read again, direct and through Eugene?

An instrument for the prompt-cache measurement (2026-10-02), not a gate.
It replays real client sessions captured by `prompt-cache-capture.py` --
Claude Code on the Anthropic door, Codex on the Responses door -- at real
llama-server processes, both directly and through a real one-node Eugene
install (control root, enrolled agent, gateway, one driver per replica), and
reads the engine's own counter, `llamacpp:prompt_tokens_total`, before and
after every request. Its delta is the number of prompt tokens the engine
actually computed; everything else in the prompt came from its cache. No
response field is trusted for the headline number.

Experiments, each on freshly started engines so no cache carries over:

    single        one replica; sessions one after another; direct vs Eugene
    normalized    as single through Eugene, with Claude Code's per-prompt
                  billing-header suffix replaced by a constant
    interleaved1  one replica; four sessions taking turns, through Eugene
    interleaved2  two replicas; four sessions taking turns, through Eugene
                  (the gateway balances), then pinned per session directly
    concurrent    2-4 replicas; many sessions at once, each a closed loop of
                  turns with seeded think times, through Eugene, once per
                  balancing policy (see `ConcurrentBench`; added 2026-10-02
                  for cache-aware balancing v2)

    python prompt-cache-measurement.py --llama-dir <dir with llama-server>
        --model <gguf> --sessions <dir of claude-N.jsonl, codex-N.jsonl>
        --out results.jsonl [--experiments single,interleaved2]

    python prompt-cache-measurement.py ... --experiments concurrent \\
        --replicas 3 --claude 12 --codex 12 --concurrency 12 \\
        --policies eugene:least_busy,eugene:round_robin,eugene:conversation \\
        --modes default,pinned

Every port is chosen by the OS, and none may fall in 8079-8290 (the live
install on the measuring box).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

NODE_NAME = "pc-agent"
MODEL = "probe"
LIVE_PORTS = range(8079, 8291)


def serve(kind: str, directory: Path, port: int) -> None:
    import uvicorn

    if kind == "control":
        from eugene_plexus_control.app import create_app
        from eugene_plexus_control.settings import Settings

        app = create_app(Settings(config_file=directory / "control.yaml", state_dir=directory / "state"))
    elif kind == "agent":
        from eugene_plexus_agent.app import create_app
        from eugene_plexus_agent.settings import Settings

        app = create_app(settings=Settings(config_file=directory / "agent.yaml", default_topology=False,
                                           bind_port=port))
    elif kind == "gateway":
        from eugene_plexus_gateway.app import create_app
        from eugene_plexus_gateway.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        slots = bootstrap.pop("bench_parallel_slots", None)
        if slots:
            # **The bench's one change to the gateway, and only to where a
            # number comes from.** A real install's drivers front runtimes the
            # agent supervises, and the gateway reads each runtime's slots
            # from the agent (`/props` `total_slots`). The bench's drivers
            # front engines it started itself, so there is no runtime to join
            # and every replica would read as ONE slot -- which makes PC4
            # move a conversation whenever its replica has anything in flight.
            # The bench starts every engine with `--parallel slots`, so this
            # is the number the agent would have reported.
            from eugene_plexus_gateway import routing

            routing._Backend.parallel_slots = property(lambda self: int(slots))
        pool = bootstrap.pop("bench_context_pool", None)
        if pool:
            # The same change for CB3's budget: the agent would report each
            # runtime's shared pool (`contextPoolTokens`, the engine's `-c`
            # under `--kv-unified`), and both of a replica's drivers front
            # one engine, `llama-<x>`, whose pool they share.
            from eugene_plexus_gateway import routing

            routing._Backend.context_pool = property(lambda self: int(pool))
            routing._Backend.pool_key = property(
                lambda self: (None, "llama-" + self.name.rsplit("-", 1)[-1]))
        app = create_app(settings=Settings(config_file=directory / "gateway.yaml",
                                           metrics_file=directory / "metrics.sqlite3", **bootstrap))
    elif kind.startswith("proxy"):
        app = proxy_app(json.loads((directory / "proxy.json").read_text(encoding="utf-8")))
    elif kind.startswith("driver"):
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(settings=Settings(config_file=directory / "driver.yaml", **bootstrap))
    else:
        raise SystemExit(f"unknown process kind {kind!r}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


def conversation_key(payload: dict) -> str:
    """The conversation a chat payload belongs to, as the engine sees it:
    its first system message and its first user message (the gateway's
    fingerprint, one layer down)."""
    system = user = None
    for m in payload.get("messages") or []:
        if m.get("role") in ("system", "developer") and system is None and user is None:
            system = json.dumps(m.get("content"), sort_keys=True)
        elif m.get("role") == "user":
            user = json.dumps(m.get("content"), sort_keys=True)
            break
    return hashlib.sha256(json.dumps([system, user]).encode()).hexdigest()[:16]


class SlotPins:
    """Conversation -> engine slot, least recently used first out.

    llama-server's own choice (b11211) sends every conversation that shares a
    prefix to the one most similar idle slot, so a replica keeps one
    conversation per prompt family warm however many slots it has (measured
    2026-10-02; upstream #22083). Pinning by `id_slot` keeps one per slot,
    and needs `--no-cache-idle-slots`, or every new task clears the idle
    slots it would come back to (upstream #28139).

    `acquire` is the safe form: it never names a slot that is busy. A request
    whose slot is busy, or a new conversation when no slot is idle, waits
    here, not in the engine -- because pinning to a busy slot is what
    preceded every wedged llama-server (cache-aware-balancing-measurement.md §4).
    """

    def __init__(self, slots: int) -> None:
        self.n = slots
        self.lock = threading.Lock()
        self.cond: "asyncio.Condition | None" = None
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.owner: list[str | None] = [None] * self.n
            self.last = [0.0] * self.n
            self.busy = [0] * self.n
            self.of: dict[str, int] = {}

    def assign(self, key: str) -> int:
        with self.lock:
            slot = self.of.get(key)
            if slot is None:
                free = [s for s in range(self.n) if self.owner[s] is None]
                idle = [s for s in range(self.n) if self.busy[s] == 0]
                slot = free[0] if free else min(idle or range(self.n), key=lambda s: self.last[s])
                old = self.owner[slot]
                if old is not None:
                    self.of.pop(old, None)
                self.owner[slot] = key
                self.of[key] = slot
            self.busy[slot] += 1
            return slot

    def _choose(self, key: str) -> int | None:
        own = self.of.get(key)
        if own is not None:
            return own if self.busy[own] == 0 else None
        idle = [s for s in range(self.n) if self.busy[s] == 0]
        if not idle:
            return None
        free = [s for s in idle if self.owner[s] is None]
        return free[0] if free else min(idle, key=lambda s: self.last[s])

    async def acquire(self, key: str) -> int:
        if self.cond is None:
            self.cond = asyncio.Condition()
        async with self.cond:
            while True:
                with self.lock:
                    slot = self._choose(key)
                    if slot is not None:
                        old = self.owner[slot]
                        if old is not None and old != key:
                            self.of.pop(old, None)
                        self.owner[slot] = key
                        self.of[key] = slot
                        self.busy[slot] += 1
                        return slot
                await self.cond.wait()

    def release(self, slot: int | None) -> None:
        if slot is None:
            return
        with self.lock:
            self.busy[slot] -= 1
            self.last[slot] = time.perf_counter()
        if self.cond is not None:
            asyncio.get_running_loop().create_task(self._wake())

    async def _wake(self) -> None:
        async with self.cond:
            self.cond.notify_all()


def proxy_app(config: dict):
    """A recording proxy in front of one engine (bench only).

    It writes one line per chat request -- the gateway's `X-Request-ID`, the
    conversation, the slot, and the engine's own `timings` (`prompt_n` read,
    `cache_n` reused) -- so a concurrent run can say which replica served each
    request and what it read, which the engine's global counter cannot. With
    `pin_slots` it also pins each conversation to a slot (`SlotPins`).
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response, StreamingResponse
    from starlette.routing import Route

    client = httpx.AsyncClient(base_url=config["upstream"], timeout=1800, trust_env=False,
                               limits=httpx.Limits(max_connections=256, max_keepalive_connections=64))
    pins = SlotPins(int(config.get("pin_slots") or 0)) if config.get("pin_slots") else None
    state = {"record": open(config["record"], "a", encoding="utf-8"), "pin": pins is not None}
    lock = threading.Lock()

    def write(row: dict) -> None:
        with lock:
            state["record"].write(json.dumps(row) + "\n")
            state["record"].flush()

    hop = {"host", "content-length", "transfer-encoding", "connection"}

    async def control(request: Request):
        body = await request.json() if request.method == "POST" else {}
        if "record" in body:
            with lock:
                state["record"].close()
                state["record"] = open(body["record"], "a", encoding="utf-8")
        if "pin" in body:
            state["pin"] = body["pin"] if pins is not None else False
        if pins is not None:
            pins.reset()
        return JSONResponse({"pin": state["pin"], "slots": pins.n if pins else 0})

    async def forward(request: Request):
        path = request.url.path
        raw = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in hop}
        if request.method != "POST" or not path.endswith("/chat/completions"):
            r = await client.request(request.method, path, params=request.query_params, content=raw,
                                     headers=headers)
            return Response(r.content, status_code=r.status_code,
                            headers={k: v for k, v in r.headers.items() if k.lower() not in hop})
        payload = json.loads(raw)
        if payload.get("tools"):
            # The replay generates real tokens, so a slot is busy for as long
            # as a turn really takes; a small model's tool call is often
            # malformed, and llama-server's parser then drops the stream
            # mid-answer. `tool_choice: none` returns the same text as plain
            # content and leaves the prompt byte-identical (measured on
            # Llama 3.x: the next request reuses all but the last token).
            payload["tool_choice"] = "none"
        key = conversation_key(payload)
        slot = (await pins.acquire(key) if state["pin"] == "safe" else pins.assign(key)) if state["pin"] else None
        if slot is not None:
            payload["id_slot"] = slot
        # The slot the request names, whoever named it: this proxy, or (in
        # `driverpin`) Eugene's own driver.
        row = {"rid": request.headers.get("x-request-id"), "key": key, "slot": payload.get("id_slot"),
               "messages": len(payload.get("messages") or []), "stream": bool(payload.get("stream")),
               "t_arrive": time.time()}
        started = time.perf_counter()
        headers.pop("content-type", None)
        req = client.build_request("POST", path, json=payload, headers=headers)
        try:
            upstream = await client.send(req, stream=True)
        except BaseException:
            # Cancelled (the caller gave up) or refused before a response:
            # the slot must not stay counted as busy.
            if slot is not None:
                pins.release(slot)
            raise
        row["status"] = upstream.status_code

        def absorb(obj: dict) -> None:
            if isinstance(obj.get("timings"), dict):
                t = obj["timings"]
                row.update(prompt_n=t.get("prompt_n"), cache_n=t.get("cache_n"),
                           predicted_n=t.get("predicted_n"), prompt_ms=t.get("prompt_ms"))
            usage = obj.get("usage")
            if isinstance(usage, dict) and usage.get("prompt_tokens") is not None:
                row["prompt_tokens"] = usage["prompt_tokens"]

        if not row["stream"]:
            data = await upstream.aread()
            await upstream.aclose()
            if slot is not None:
                pins.release(slot)
            try:
                absorb(json.loads(data))
            except ValueError:
                row["error"] = data[:300].decode(errors="replace")
            row["seconds"] = round(time.perf_counter() - started, 4)
            write(row)
            return Response(data, status_code=upstream.status_code,
                            headers={k: v for k, v in upstream.headers.items() if k.lower() not in hop})

        async def stream():
            buf = b""
            try:
                async for chunk in upstream.aiter_raw():
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.startswith(b"data:") or line.strip() == b"data: [DONE]":
                            continue
                        try:
                            obj = json.loads(line[5:])
                        except ValueError:
                            continue
                        if "ttft" not in row:
                            delta = ((obj.get("choices") or [{}])[0] or {}).get("delta") or {}
                            if delta.get("content") or delta.get("tool_calls") or delta.get("reasoning_content"):
                                row["ttft"] = round(time.perf_counter() - started, 4)
                        absorb(obj)
                    yield chunk
            finally:
                await upstream.aclose()
                if slot is not None:
                    pins.release(slot)
                row["seconds"] = round(time.perf_counter() - started, 4)
                write(row)

        return StreamingResponse(stream(), status_code=upstream.status_code,
                                 headers={k: v for k, v in upstream.headers.items() if k.lower() not in hop})

    async def healthz(request: Request):
        return JSONResponse({"status": "ok"})

    return Starlette(routes=[Route("/_bench", control, methods=["GET", "POST"]),
                             Route("/healthz", healthz, methods=["GET"]),
                             Route("/{path:path}", forward, methods=["GET", "POST", "PUT", "DELETE"])])


def free_ports(names: list[str]) -> dict[str, int]:
    while True:
        sockets = [socket.socket() for _ in names]
        for s in sockets:
            s.bind(("127.0.0.1", 0))
        ports = {n: s.getsockname()[1] for n, s in zip(names, sockets, strict=True)}
        for s in sockets:
            s.close()
        if not any(p in LIVE_PORTS for p in ports.values()):
            return ports


def load_sessions(directory: Path, client: str) -> list[list[dict]]:
    sessions = []
    for path in sorted(directory.glob(f"{client}-*.jsonl")):
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        rows = [r for r in rows if r.get("body") and r["body"].get("tools")
                and "count_tokens" not in r["path"]]
        sessions.append(rows)
    return sessions


_BILLING = re.compile(r"(cc_version=[0-9.]+\.)[0-9a-f]{3}")


def normalize_billing(body: dict) -> dict:
    system = body.get("system")
    if isinstance(system, list) and system and isinstance(system[0].get("text"), str):
        body = dict(body)
        first = dict(system[0])
        first["text"] = _BILLING.sub(r"\g<1>000", first["text"])
        body["system"] = [first, *system[1:]]
    return body


def fold_system(body: dict) -> dict:
    """Claude Code's in-conversation `system` messages as user turns, in place.

    Qwen 3.x chat templates raise "System message must be at the beginning"
    on them (measured 2026-10-02). Moving them to the top would change the
    prompt's start every turn; keeping their position as user text keeps it.
    """
    messages = []
    for m in body.get("messages") or []:
        if m.get("role") == "system":
            content = m.get("content")
            text = content if isinstance(content, str) else "\n".join(
                p.get("text", "") for p in content or [] if isinstance(p, dict))
            m = {"role": "user", "content": f"<system-reminder>\n{text}\n</system-reminder>"}
        messages.append(m)
    return dict(body, messages=messages)


class Bench:
    def __init__(self, args: argparse.Namespace, directory: Path) -> None:
        self.args = args
        self.dir = directory
        self.ports = free_ports(["control", "agent", "gateway", "driver-a", "driver-b", "llama-a", "llama-b"])
        self.procs: dict[str, subprocess.Popen] = {}
        self.logs: list = []
        self.http = httpx.Client(timeout=1800, trust_env=False)
        self.passphrase = secrets.token_urlsafe(24)
        self.out = args.out.open("a", encoding="utf-8")

    # ---------------------------------------------------------------- plumbing

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def call(self, name, method, path, token=None, **kw):
        headers = {"Authorization": "Bearer " + token} if token else None
        return self.http.request(method, self.url(name) + path, headers=headers, **kw)

    def wait(self, check, label, seconds=120):
        deadline = time.perf_counter() + seconds
        last = None
        while time.perf_counter() < deadline:
            try:
                if check():
                    return
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                last = e
            time.sleep(0.2)
        raise AssertionError(f"timed out: {label} ({last!r})")

    def write(self, name, filename, data):
        work = self.dir / name
        work.mkdir(exist_ok=True)
        (work / filename).write_text(json.dumps(data) if filename.endswith("json") else yaml.safe_dump(data),
                                     encoding="utf-8")

    def start(self, name):
        work = self.dir / name
        work.mkdir(exist_ok=True)
        log = (work / "process.log").open("ab")
        self.logs.append(log)
        env = {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}
        env.pop("OPENAI_API_KEY", None)
        env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        self.procs[name] = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", name, "--directory", str(work),
             "--port", str(self.ports[name])],
            cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.wait(lambda: self.call(name, "GET", "/healthz").status_code == 200, name)

    def stop(self, name):
        proc = self.procs.pop(name, None)
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def login(self, name):
        r = self.call(name, "POST", "/v1/auth/login", json={"passphrase": self.passphrase})
        r.raise_for_status()
        return r.json()["sessionToken"]

    # ------------------------------------------------------------- the engine

    def start_llama(self, name: str, extra: list[str] | None = None) -> None:
        self.stop(name)
        binary = self.args.llama_dir / ("llama-server.exe" if os.name == "nt" else "llama-server")
        logs = self.args.engine_logs or self.dir
        logs.mkdir(parents=True, exist_ok=True)
        log = (logs / f"{name}.log").open("ab")
        self.logs.append(log)
        argv = [str(binary), "-m", str(self.args.model), "--alias", MODEL, "--host", "127.0.0.1",
                "--port", str(self.ports[name]), "--metrics", "--jinja", "-c", str(self.args.ctx),
                *self.args.engine_args, *(extra or [])]
        log.write((" ".join(argv) + "\n").encode())
        log.flush()
        self.procs[name] = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.wait(lambda: self.call(name, "GET", "/health").status_code == 200, name, 300)

    def processed(self, name: str) -> float:
        text = self.call(name, "GET", "/metrics").text
        m = re.search(r"^llamacpp:prompt_tokens_total (\S+)", text, re.M)
        return float(m.group(1)) if m else 0.0

    # ------------------------------------------------------------ the install

    def install(self) -> None:
        from eugene_plexus_agent.node_identity import NodeIdentityStore
        from eugene_plexus_agent.trust import NodeTrust

        self.start("control")
        self.call("control", "POST", "/v1/auth/initialize", json={"passphrase": self.passphrase}).raise_for_status()
        root = self.login("control")
        self.write("agent", "agent.yaml", {"firstRunComplete": True, "advertiseUrl": self.url("agent"),
                                           "securityMode": "prompt_on_startup", "components": []})
        self.start("agent")
        self.call("agent", "POST", "/v1/auth/initialize", json={"passphrase": self.passphrase}).raise_for_status()
        standalone = self.login("agent")
        join = self.call("control", "POST", "/v1/nodes/join-token", root, json={"grants": ["gateway"]})
        join.raise_for_status()
        self.call("agent", "POST", "/v1/node/enroll", standalone, json={
            "controlUrl": self.url("control"), "token": join.json()["token"], "name": NODE_NAME,
        }).raise_for_status()
        self.operator = self.login("agent")
        store = NodeIdentityStore(self.dir / "agent" / "node.yaml")
        store.load()
        self.trust = NodeTrust(store, self.dir / "agent" / "trust_bundle.json")
        self.trust.load()
        self.write("gateway", "bootstrap.json", self.bootstrap("gateway"))
        gateway_config = {"routingRefreshSeconds": 2, "loadBalancing": self.args.balancing}
        for item in self.args.gateway_set:
            key, _, value = item.partition("=")
            gateway_config[key] = yaml.safe_load(value)
        self.write("gateway", "gateway.yaml", gateway_config)
        self.start("gateway")
        r = self.call("agent", "POST", "/v1/auth/client-keys", self.operator, json={
            "name": "measure", "limits": {"allowedModels": None, "requestsPerMinute": 1000}})
        r.raise_for_status()
        self.key = r.json()["token"]

    def bootstrap(self, sub: str) -> dict:
        token, _ = self.trust.mint_service(sub=sub, audience=self.trust.recipient)
        return {"agent_url": self.url("agent"), "trust_bundle_file": str(self.trust.bundle_path),
                "trust_authority": self.trust.authority, "auth_recipient": self.trust.recipient,
                "service_token": token}

    def add_driver(self, name: str, llama: str) -> None:
        self.write(name, "bootstrap.json", self.bootstrap("inference-driver"))
        self.write(name, "driver.yaml", {"provider": "openai_compat_custom", "baseUrl": self.url(llama),
                                         "modelId": MODEL, "backendLocality": "local"})
        self.start(name)
        self.call("agent", "POST", "/v1/components", self.operator, json={
            "name": name, "kind": "inference-driver", "url": self.url(name)}).raise_for_status()

    def remove_driver(self, name: str) -> None:
        self.call("agent", "DELETE", f"/v1/components/{name}", self.operator)
        self.stop(name)

    def routable(self, drivers: int) -> None:
        def ready():
            view = self.call("gateway", "GET", "/v1/admin/drivers", self.operator).json()
            healthy = [d for d in view.get("drivers", []) if d.get("reachable") and MODEL in json.dumps(d)]
            return len(healthy) == drivers
        self.wait(ready, f"{drivers} driver(s) reachable for {MODEL}")
        self.wait(lambda: MODEL in json.dumps(self.call("gateway", "GET", "/v1/models", self.key).json()),
                  "the model is routable")

    # --------------------------------------------------------------- requests

    def send(self, client: str, body: dict, target: str) -> tuple[int, dict]:
        body = dict(body)
        body["model"] = MODEL
        body["stream"] = False
        if client == "claude":
            body["max_tokens"] = 1
            body.pop("thinking", None)
            path = "/v1/messages"
        else:
            body["max_output_tokens"] = 16
            path = "/v1/responses"
        if target == "eugene":
            r = self.call("gateway", "POST", path, self.key, json=body)
        else:
            r = self.call(target, "POST", path, json=body)
        try:
            data = r.json()
        except ValueError:
            data = {"text": r.text[:300]}
        return r.status_code, data

    def replay(self, experiment: str, client: str, order: list[tuple[int, int, dict]], route) -> None:
        """`order` is (session, turn, body); `route(session)` names the target."""
        engines = [n for n in ("llama-a", "llama-b") if n in self.procs]
        if not experiment.startswith("family"):
            experiment += getattr(self, "suffix", "")
        for session, turn, body in order:
            target = route(session)
            before = {n: self.processed(n) for n in engines}
            t = time.perf_counter()
            status, data = self.send(client, body, target)
            took = time.perf_counter() - t
            after = {n: self.processed(n) for n in engines}
            delta = {n: after[n] - before[n] for n in engines}
            usage = data.get("usage") if isinstance(data, dict) else None
            served = max(delta, key=delta.get) if any(delta.values()) else None
            row = {"experiment": experiment, "model": self.args.model.stem,
                   "engine_args": " ".join(self.args.engine_args),
                   "client": client, "session": session, "turn": turn,
                   "target": target, "status": status, "seconds": round(took, 3),
                   "processed": sum(delta.values()), "served_by": served, "per_engine": delta,
                   "usage": usage, "error": None if status == 200 else json.dumps(data)[:300]}
            self.out.write(json.dumps(row) + "\n")
            self.out.flush()
            print(f"{experiment:<13} {client:<6} s{session} t{turn} -> {target:<7} {status} "
                  f"{took:7.2f}s processed={row['processed']:>7.0f} on={served} usage={usage}", flush=True)

    # ------------------------------------------------------------ experiments

    def sequential(self, sessions):
        return [(s, t, body["body"]) for s, rows in enumerate(sessions, 1) for t, body in enumerate(rows, 1)]

    def interleaved(self, sessions):
        order = []
        for t in range(max(len(rows) for rows in sessions)):
            for s, rows in enumerate(sessions, 1):
                if t < len(rows):
                    order.append((s, t + 1, rows[t]["body"]))
        return order

    def run(self) -> None:
        claude = load_sessions(self.args.sessions, "claude")[: self.args.max_sessions]
        codex = load_sessions(self.args.sessions, "codex")[: self.args.max_sessions]
        # Transforms of Claude Code's bodies, applied to every experiment so a
        # direct and an Eugene path are compared on the same prompt.
        for rows in claude:
            for row in rows:
                if self.args.normalize:
                    row["body"] = normalize_billing(row["body"])
                if self.args.fold_system:
                    row["body"] = fold_system(row["body"])
        suffix = ("-normalized" if self.args.normalize else "") + ("-folded" if self.args.fold_system else "")
        self.suffix = suffix
        experiments = self.args.experiments.split(",")
        if experiments == ["family"]:
            # The engine alone, per model family: no install, sessions one
            # after another, the engine's own log kept for its checkpoint lines.
            label = f"family-{self.args.model.stem}{suffix}"
            for client, sessions in (("claude", claude), ("codex", codex)):
                if client == "codex" and suffix:
                    continue
                self.start_llama("llama-a")
                self.replay(label, client, self.sequential(sessions), lambda s: "llama-a")
            return
        self.install()
        self.start_llama("llama-a")
        self.add_driver("driver-a", "llama-a")
        self.routable(1)
        if "single" in experiments:
            for client, sessions in (("claude", claude), ("codex", codex)):
                for target in ("llama-a", "eugene"):
                    if client == "codex" and target != "eugene":
                        status, _ = self.send("codex", sessions[0][0]["body"], "llama-a")
                        if status == 404:
                            continue
                    self.start_llama("llama-a")
                    self.routable(1)
                    self.replay("single", client, self.sequential(sessions), lambda s, t=target: t)
        if "normalized" in experiments:
            self.start_llama("llama-a")
            self.routable(1)
            order = [(s, t, normalize_billing(b)) for s, t, b in self.sequential(claude)]
            self.replay("normalized", "claude", order, lambda s: "eugene")
        if "interleaved1" in experiments:
            for client, sessions in (("claude", claude), ("codex", codex)):
                self.start_llama("llama-a")
                self.routable(1)
                self.replay("interleaved1", client, self.interleaved(sessions), lambda s: "eugene")
        if "interleaved2" in experiments:
            self.start_llama("llama-b")
            self.add_driver("driver-b", "llama-b")
            for client, sessions in (("claude", claude), ("codex", codex)):
                for mode in ("eugene", "pinned"):
                    if client == "codex" and mode == "pinned":
                        status, _ = self.send("codex", sessions[0][0]["body"], "llama-a")
                        if status == 404:
                            continue
                    self.start_llama("llama-a")
                    self.start_llama("llama-b")
                    self.routable(2)
                    route = (lambda s: "eugene") if mode == "eugene" else (
                        lambda s: "llama-a" if s % 2 else "llama-b")
                    self.replay(f"interleaved2-{mode}", client, self.interleaved(sessions), route)

    def close(self) -> None:
        for name in list(self.procs):
            self.stop(name)
        for log in self.logs:
            log.close()
        self.out.close()


# --------------------------------------------------------------------------- #
# Many sessions at once (2026-10-02, late): the measurement behind balancing v2
# --------------------------------------------------------------------------- #

REPLICAS = "abcdefgh"
#: The events that mean the backend has started answering, per door.
FIRST_OUTPUT = {"content_block_start", "content_block_delta", "response.output_item.added",
                "response.output_text.delta", "response.function_call_arguments.delta"}


class Router:
    """Harness-side placement for policies the gateway does not have (yet).

    The request still goes through the real gateway, addressed to one
    replica's own model id, so the prompt each engine sees is exactly what
    the gateway's balanced path would send; only the choice is made here.
    `conversation` re-implements PC4 so its run validates the rest against
    the gateway's own `conversation`.

        least_busy     the gateway's rotation, then in-flight per slot
        conversation   PC4: back to the replica that served the key, unless
                       it is saturated and another has a free slot
        spread         as conversation, but a NEW conversation goes to the
                       replica holding the fewest conversations, not the
                       fewest requests in flight
        prefix         as spread, preferring a replica that served the same
                       prompt family (system text + tool names) while it
                       holds fewer than `slots` conversations
        hrw            rendezvous hashing with bounded load (1.25 x mean):
                       stateless, the same answer from any gateway
        spread_fit     spread, and a turn is held until its replica's pool
                       has room for every prompt in flight there (an
                       estimate from the request's size), because a unified
                       pool shared by its slots refuses a prompt that does
                       not fit ("Context size has been exceeded")

    `@2` runs two independent routers, each request through a random one
    (two gateways behind one name); `~reset` clears the router's state at
    `--reset-at` seconds (a gateway restart: the affinity table is memory).
    """

    def __init__(self, policy: str, replicas: list[str], slots: int, pool: int = 0) -> None:
        self.policy = policy
        self.replicas = replicas
        self.slots = slots
        self.pool = pool
        self.lock = threading.Lock()
        self.room = threading.Condition(self.lock)
        self.inflight = dict.fromkeys(replicas, 0)
        self.tokens = dict.fromkeys(replicas, 0)
        self.cursor = 0
        self.affinity: dict[str, str] = {}
        self.resident: dict[str, OrderedDict] = {r: OrderedDict() for r in replicas}
        self.warm: dict[str, set] = {r: set() for r in replicas}

    def reset(self) -> None:
        with self.lock:
            self.affinity.clear()
            for r in self.replicas:
                self.resident[r].clear()
                self.warm[r].clear()

    def _free(self, r: str) -> bool:
        return self.inflight[r] < self.slots

    def _hrw(self, key: str) -> str:
        order = sorted(self.replicas, key=lambda r: hashlib.sha256(f"{key}|{r}".encode()).digest(),
                       reverse=True)
        held = {r: sum(1 for k in self.resident[r] if k != key) for r in self.replicas}
        bound = max(1, -(-int(1.25 * (sum(held.values()) + 1)) // len(self.replicas)))
        return next((r for r in order if held[r] < bound), order[0])

    def _fits(self, r: str, est: int) -> bool:
        return self.tokens[r] == 0 or self.tokens[r] + est <= self.pool

    def _choose_fit(self, key: str, est: int) -> tuple[str, str]:
        pinned = self.affinity.get(key)
        while True:
            if pinned is not None:
                if self._fits(pinned, est):
                    return pinned, "hit"
            else:
                n = len(self.replicas)
                rotated = self.replicas[self.cursor % n:] + self.replicas[:self.cursor % n]
                room = [r for r in rotated if self._fits(r, est)]
                if room:
                    self.cursor += 1
                    return min(room, key=lambda r: (sum(1 for k in self.resident[r] if k != key),
                                                    self.inflight[r])), "new"
            self.room.wait()

    def choose(self, key: str, family: str, est: int = 0) -> tuple[str, str]:
        if self.policy == "spread_fit":
            with self.lock:
                chosen, outcome = self._choose_fit(key, est)
                self.inflight[chosen] += 1
                self.tokens[chosen] += est
                self.affinity[key] = chosen
                return chosen, outcome
        with self.lock:
            n = len(self.replicas)
            rotated = self.replicas[self.cursor % n:] + self.replicas[:self.cursor % n]
            self.cursor += 1
            by_busy = sorted(rotated, key=lambda r: self.inflight[r] / self.slots)
            outcome = "new"
            if self.policy == "least_busy":
                chosen = by_busy[0]
            elif self.policy == "hrw":
                chosen = self._hrw(key)
                outcome = "hit" if self.affinity.get(key) == chosen else (
                    "moved" if key in self.affinity else "new")
            else:
                pinned = self.affinity.get(key)
                if pinned is not None and (self._free(pinned) or not any(map(self._free, self.replicas))):
                    chosen, outcome = pinned, "hit"
                else:
                    outcome = "moved" if pinned is not None else "new"
                    if self.policy == "conversation":
                        chosen = by_busy[0]
                    else:
                        def held(r: str) -> int:
                            return sum(1 for k in self.resident[r] if k != key)

                        chosen = min(rotated, key=lambda r: (held(r), self.inflight[r]))
                        if self.policy == "prefix":
                            warm = [r for r in rotated if family in self.warm[r] and held(r) < self.slots]
                            if warm:
                                chosen = min(warm, key=lambda r: (held(r), self.inflight[r]))
            self.inflight[chosen] += 1
            self.affinity[key] = chosen
            return chosen, outcome

    def done(self, replica: str, key: str, family: str, est: int = 0) -> None:
        with self.lock:
            self.inflight[replica] -= 1
            if self.policy == "spread_fit":
                self.tokens[replica] -= est
                self.room.notify_all()
            for r in self.replicas:
                self.resident[r].pop(key, None)
            self.resident[replica][key] = time.perf_counter()
            self.warm[replica].add(family)


class ConcurrentBench(Bench):
    """2-4 replicas, many sessions at once, one balancing policy per run.

    Each session is a closed loop: a turn is sent when the previous one has
    answered and its think time (seeded, the same for every policy) has
    passed. `--concurrency` sessions run at once; the next starts when one
    finishes. Every engine sits behind a recording proxy (`proxy_app`), and
    every run starts on fresh engines and a fresh gateway, so nothing
    carries over. The headline is still the engines' own counters.

    Modes: `default` is llama-server as the agent launches it today
    (`--parallel` slots, its own slot choice); `pinned` adds
    `--no-cache-idle-slots` and the proxy pins each conversation to a slot;
    `pinned0` pins with `--cache-ram 0` instead; `pinsafe` is `pinned` that
    never names a busy slot (`SlotPins.acquire`); `driverpin` (CB4) is the
    product's own pinning: the engines get `--no-cache-idle-slots`, every
    driver `slotPinning: true`, the gateway hands each driver the
    conversation, and the proxy pins nothing. Drivers read the setting at
    start, so `driverpin` cannot share an invocation with another mode.
    """

    def __init__(self, args: argparse.Namespace, directory: Path) -> None:
        super().__init__(args, directory)
        self.names = list(REPLICAS[: args.replicas])
        self.ports = free_ports(["control", "agent", "gateway"]
                                + [f"{p}-{x}" for x in self.names for p in ("llama", "proxy", "driver", "driverx")])
        self.http = httpx.Client(timeout=1800, trust_env=False,
                                 limits=httpx.Limits(max_connections=256, max_keepalive_connections=128))
        claude = load_sessions(args.sessions, "claude")[: args.claude]
        codex = load_sessions(args.sessions, "codex")[: args.codex]
        for rows in claude:
            for row in rows:
                row["body"] = fold_system(normalize_billing(row["body"]))
        # Families interleaved, so a run that takes the first N sessions mixes them.
        mixed = []
        for i in range(max(len(claude), len(codex))):
            mixed += [("claude", s) for s in claude[i:i + 1]] + [("codex", s) for s in codex[i:i + 1]]
        self.sessions = [(client, n, rows) for n, (client, rows) in enumerate(mixed, 1)]
        rng = random.Random(args.seed)
        self.think = {n: [rng.expovariate(1 / args.think_mean) for _ in rows] for _, n, rows in self.sessions}

    def family(self, client: str, body: dict) -> str:
        system = body.get("system") if client == "claude" else body.get("instructions")
        tools = sorted(str(t.get("name")) for t in body.get("tools") or [] if isinstance(t, dict))
        return hashlib.sha256(json.dumps([client, system, tools], default=str).encode()).hexdigest()[:12]

    def key_of(self, client: str, body: dict, n: int) -> str:
        # The key the gateway's PC4 reads: Claude Code's session id inside
        # metadata.user_id, Codex's prompt_cache_key -- both one per session.
        return f"{client}-{n}"

    # ----------------------------------------------------------- plumbing

    def start_engines(self, mode: str) -> None:
        # `--kv-unified` as well: an explicit `--parallel` turns the shared
        # pool off and gives each slot ctx/slots, while the agent's default
        # (parallelSlots unset) is llama-server's auto, 4 slots sharing one pool.
        extra = ["--parallel", str(self.args.parallel), "--kv-unified"]
        if mode in ("pinned", "pinsafe", "driverpin"):
            extra.append("--no-cache-idle-slots")
        elif mode == "pinned0":
            # No RAM prompt cache at all (and so no idle-slot caching, which
            # needs it). Pinned with the RAM cache on, llama-server b11211
            # intermittently wedged a slot (cache-aware-balancing-measurement.md §4); this tells the two apart.
            extra += ["--cache-ram", "0"]
        for x in self.names:
            self.start_llama(f"llama-{x}", extra)
        for x in self.names:
            self.call(f"proxy-{x}", "POST", "/_bench", json={
                "pin": "safe" if mode == "pinsafe" else mode.startswith("pinned"),  # driverpin: no
                "record": str(self.dir / f"proxy-{self.run_id}-{x}.jsonl")}).raise_for_status()

    def start_gateway(self, balancing: str) -> None:
        self.stop("gateway")
        bootstrap = self.bootstrap("gateway")
        bootstrap["bench_parallel_slots"] = self.args.parallel
        bootstrap["bench_context_pool"] = self.args.ctx
        self.write("gateway", "bootstrap.json", bootstrap)
        self.write("gateway", "gateway.yaml", {"routingRefreshSeconds": 2, "loadBalancing": balancing,
                                               "metricsEnabled": True})
        self.start("gateway")

        def ready():
            view = self.call("gateway", "GET", "/v1/admin/drivers", self.operator).json()
            healthy = [d for d in view.get("drivers", []) if d.get("reachable")]
            models = json.dumps(self.call("gateway", "GET", "/v1/models", self.key).json())
            return len(healthy) == 2 * len(self.names) and all(f'"{MODEL}-{x}"' in models for x in self.names)
        self.wait(ready, "every replica routable, balanced and by name")

    @property
    def driver_pins(self) -> bool:
        modes = self.args.modes.split(",")
        if "driverpin" in modes and len(modes) > 1:
            raise SystemExit("driverpin cannot share an invocation with another mode")
        return modes == ["driverpin"]

    def setup(self) -> None:
        self.install()
        # One key per session, as dozens of users would each have their own:
        # a key admits `maxConcurrentRequests` at once (default 2), so one
        # shared key would turn the run into a test of that limit.
        self.keys = {}
        for _, n, _ in self.sessions:
            r = self.call("agent", "POST", "/v1/auth/client-keys", self.operator, json={
                "name": f"session-{n}", "limits": {"allowedModels": None, "maxConcurrentRequests": 4,
                                                   "requestsPerMinute": 1000}})
            r.raise_for_status()
            self.keys[n] = r.json()["token"]
        self.stop("gateway")
        self.run_id = "setup"
        for x in self.names:
            self.start_llama(f"llama-{x}", ["--parallel", str(self.args.parallel), "--kv-unified"])
            self.write(f"proxy-{x}", "proxy.json", {"upstream": self.url(f"llama-{x}"),
                                                    "record": str(self.dir / "proxy-setup.jsonl"),
                                                    "pin_slots": self.args.parallel})
            self.start(f"proxy-{x}")
            for kind, model in (("driver", MODEL), ("driverx", f"{MODEL}-{x}")):
                name = f"{kind}-{x}"
                self.write(name, "bootstrap.json", self.bootstrap("inference-driver"))
                self.write(name, "driver.yaml", {"provider": "openai_compat_custom",
                                                 "baseUrl": self.url(f"proxy-{x}"),
                                                 "modelId": model, "backendLocality": "local",
                                                 "slotPinning": self.driver_pins})
                self.start(name)
                self.call("agent", "POST", "/v1/components", self.operator, json={
                    "name": name, "kind": "inference-driver", "url": self.url(name)}).raise_for_status()

    # ------------------------------------------------------------ one turn

    def stream_turn(self, client: str, body: dict, model: str, key: str) -> dict:
        body = dict(body)
        body.update(model=model, stream=True)
        if client == "claude":
            body["max_tokens"] = self.args.gen_tokens
            body.pop("thinking", None)
            path = "/v1/messages"
        else:
            body["max_output_tokens"] = max(16, self.args.gen_tokens)
            path = "/v1/responses"
        out = {"status": None, "rid": None, "ttft": None, "usage": {}}
        started = time.perf_counter()
        try:
            with self.http.stream("POST", self.url("gateway") + path, json=body,
                                  headers={"Authorization": "Bearer " + key}) as r:
                out["status"] = r.status_code
                out["rid"] = r.headers.get("x-request-id")
                if r.status_code != 200:
                    out["error"] = r.read()[:300].decode(errors="replace")
                else:
                    for line in r.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            obj = json.loads(line[5:])
                        except ValueError:
                            continue
                        kind = obj.get("type")
                        if out["ttft"] is None and kind in FIRST_OUTPUT:
                            out["ttft"] = round(time.perf_counter() - started, 4)
                        usage = (obj.get("message") or {}).get("usage") or obj.get("usage") or (
                            (obj.get("response") or {}).get("usage") if kind == "response.completed" else None)
                        if isinstance(usage, dict):
                            out["usage"].update({k: v for k, v in usage.items() if v is not None})
                        if kind in ("error", "response.failed"):
                            out["error"] = json.dumps(obj)[:300]
        except httpx.HTTPError as e:
            out["error"] = repr(e)
        out["seconds"] = round(time.perf_counter() - started, 4)
        return out

    # ------------------------------------------------------------- one run

    def run_policy(self, mode: str, policy: str) -> None:
        self.run_id = f"{mode}-{policy.replace(':', '-').replace('@', '-').replace('~', '-')}"
        where, _, name = policy.partition(":")
        name, _, reset = name.partition("~")
        name, _, gateways = name.partition("@")
        self.start_gateway(name if where == "eugene" else "least_busy")
        self.start_engines(mode)
        routers = ([Router(name, [f"llama-{x}" for x in self.names], self.args.parallel, self.args.ctx)
                    for _ in range(int(gateways or 1))] if where == "route" else [])
        pick = random.Random(self.args.seed + 1)
        engines = [f"llama-{x}" for x in self.names]
        before = {e: self.processed(e) for e in engines}
        queue = list(self.sessions)
        lock = threading.Lock()
        rows: list[dict] = []

        def worker(index: int) -> None:
            time.sleep(index * self.args.stagger)
            while True:
                with lock:
                    if not queue:
                        return
                    client, n, turns = queue.pop(0)
                    router = routers[pick.randrange(len(routers))] if len(routers) > 1 else (
                        routers[0] if routers else None)
                for t, row in enumerate(turns):
                    if t:
                        time.sleep(self.think[n][t])
                    body = row["body"]
                    family = self.family(client, body)
                    key = self.key_of(client, body, n)
                    if router is not None:
                        if len(routers) > 1:
                            router = routers[pick.randrange(len(routers))]
                        # What the gateway could estimate too: the request's
                        # size (~3.5 characters a token here) and the answer.
                        est = len(json.dumps(body)) * 2 // 7 + self.args.gen_tokens
                        replica, outcome = router.choose(key, family, est)
                        model = f"{MODEL}-{replica.removeprefix('llama-')}"
                    else:
                        replica = outcome = None
                        model = MODEL
                    result = self.stream_turn(client, body, model, self.keys[n])
                    if router is not None:
                        router.done(replica, key, family, est)
                    result.update(client=client, session=n, turn=t + 1, routed_to=replica,
                                  harness_affinity=outcome, family=family, t_end=time.time())
                    with lock:
                        rows.append(result)
                    print(f"{self.run_id:<34} {client:<6} s{n:<2} t{t + 1} {result['status']} "
                          f"ttft={result['ttft']} {result['seconds']:.2f}s", flush=True)

        started = time.perf_counter()
        if reset and routers:
            def clear() -> None:
                for router in routers:
                    router.reset()
                print(f"{self.run_id}: router state cleared at {time.perf_counter() - started:.1f}s", flush=True)
            threading.Timer(self.args.reset_at, clear).start()
        with ThreadPoolExecutor(self.args.concurrency) as pool:
            list(pool.map(worker, range(self.args.concurrency)))
        wall = time.perf_counter() - started
        after = {e: self.processed(e) for e in engines}
        self.report(mode, policy, rows, {e: after[e] - before[e] for e in engines}, wall)

    def report(self, mode: str, policy: str, rows: list[dict], read: dict, wall: float) -> None:
        proxied: dict[str, dict] = {}
        for x in self.names:
            path = self.dir / f"proxy-{self.run_id}-{x}.jsonl"
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    rec = json.loads(line)
                    if rec.get("rid"):
                        proxied[rec["rid"]] = dict(rec, replica=f"llama-{x}")
        served = self.served_by()
        joined = 0
        for row in rows:
            rec = proxied.get(row.get("rid") or "")
            if rec:
                joined += 1
                row.update(prompt_n=rec.get("prompt_n"), cache_n=rec.get("cache_n"), slot=rec.get("slot"),
                           engine_ttft=rec.get("ttft"), predicted_n=rec.get("predicted_n"),
                           replica=rec["replica"])
            row["served_by"] = served.get(row.get("rid") or "", {}).get("driver")
            row["gateway_affinity"] = served.get(row.get("rid") or "", {}).get("affinity")
        rows.sort(key=lambda r: (r["session"], r["turn"]))
        evicted = moved = resident = 0
        last: dict[int, dict] = {}
        for row in rows:
            prev = last.get(row["session"])
            if prev and prev.get("prompt_n") is not None and row.get("cache_n") is not None:
                held = row["cache_n"] >= (prev["prompt_n"] + prev["cache_n"]) - 64
                same = row.get("replica") == prev.get("replica")
                row["history"] = "held" if held else ("evicted" if same else "moved")
                resident += held
                evicted += (not held) and same
                moved += (not held) and not same
            last[row["session"]] = row
            self.out.write(json.dumps({"experiment": "concurrent", "run": self.run_id, "mode": mode,
                                       "policy": policy, **row}) + "\n")
        total = sum((r.get("prompt_n") or 0) + (r.get("cache_n") or 0) for r in rows)
        engine_read = sum(read.values())
        ttft = sorted(r["ttft"] for r in rows if r.get("ttft") is not None)
        later = sorted(r["ttft"] for r in rows if r.get("ttft") is not None and r["turn"] > 1)

        def pct(xs: list[float], p: float) -> float | None:
            return round(xs[min(len(xs) - 1, int(p * len(xs)))], 3) if xs else None

        summary = {
            "experiment": "concurrent-summary", "run": self.run_id, "mode": mode, "policy": policy,
            "model": self.args.model.stem, "replicas": len(self.names), "slots": self.args.parallel,
            "ctx": self.args.ctx, "sessions": len(self.sessions), "concurrency": self.args.concurrency,
            "think_mean": self.args.think_mean, "gen_tokens": self.args.gen_tokens,
            "requests": len(rows), "errors": sum(1 for r in rows if r.get("status") != 200 or r.get("error")),
            "joined": joined, "prompt_tokens": total, "engine_read": engine_read,
            "proxy_read": sum(r.get("prompt_n") or 0 for r in rows),
            "reused_pct": round(100 * (1 - engine_read / total), 1) if total else None,
            "ttft_p50": pct(ttft, 0.5), "ttft_p90": pct(ttft, 0.9),
            "ttft_p50_later": pct(later, 0.5), "ttft_p90_later": pct(later, 0.9),
            "history_held": resident, "history_evicted": evicted, "history_moved": moved,
            "per_engine_read": read, "wall_seconds": round(wall, 1),
        }
        self.out.write(json.dumps(summary) + "\n")
        self.out.flush()
        print(json.dumps(summary), flush=True)

    def served_by(self) -> dict[str, dict]:
        """The gateway's own record of every request: rid -> served driver, affinity."""
        import sqlite3

        path = self.dir / "gateway" / "metrics.sqlite3"
        out: dict[str, dict] = {}
        for _ in range(50):
            try:
                db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                for rid, driver, affinity in db.execute(
                        "SELECT r.correlation_id, a.driver, r.affinity FROM request r "
                        "JOIN attempt a ON a.request_id = r.id AND a.served = 1"):
                    if rid:
                        out[rid] = {"driver": driver, "affinity": affinity}
                db.close()
                return out
            except sqlite3.Error:
                time.sleep(0.2)
        return out

    def run(self) -> None:
        self.setup()
        for mode in self.args.modes.split(","):
            for policy in self.args.policies.split(","):
                self.run_policy(mode, policy)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serve")
    ap.add_argument("--directory", type=Path)
    ap.add_argument("--port", type=int)
    ap.add_argument("--llama-dir", type=Path)
    ap.add_argument("--model", type=Path)
    ap.add_argument("--sessions", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--ctx", type=int, default=40960)
    ap.add_argument("--balancing", default="least_busy")
    ap.add_argument("--max-sessions", type=int, default=4)
    ap.add_argument("--gateway-set", action="append", default=[],
                    help="KEY=VALUE into the gateway's config file, repeatable")
    ap.add_argument("--fold-system", action="store_true",
                    help="family: Claude Code's in-conversation system messages as user turns")
    ap.add_argument("--normalize", action="store_true",
                    help="family: replace Claude Code's per-prompt billing-header suffix first")
    ap.add_argument("--engine-logs", type=Path, help="keep each llama-server log here, not in the temp dir")
    ap.add_argument("--experiments", default="single,normalized,interleaved1,interleaved2")
    ap.add_argument("--keep-dir", type=Path, help="work here and keep it (proxy records, metrics), not a temp dir")
    ap.add_argument("--engine-arg", dest="engine_args", action="append", default=[],
                    help="an argument for every llama-server, repeatable (e.g. --engine-arg=--threads)")
    concurrent = ap.add_argument_group("concurrent")
    concurrent.add_argument("--replicas", type=int, default=3, help="2-8 llama-server replicas")
    concurrent.add_argument("--parallel", type=int, default=4, help="slots per replica (--parallel)")
    concurrent.add_argument("--claude", type=int, default=12, help="Claude Code sessions")
    concurrent.add_argument("--codex", type=int, default=12, help="Codex sessions")
    concurrent.add_argument("--concurrency", type=int, default=12, help="sessions running at once")
    concurrent.add_argument("--think-mean", type=float, default=2.0,
                            help="seconds between a turn's answer and the next turn, exponential")
    concurrent.add_argument("--stagger", type=float, default=0.5, help="seconds between session starts")
    concurrent.add_argument("--gen-tokens", type=int, default=64, help="max output tokens per turn")
    concurrent.add_argument("--seed", type=int, default=20261002)
    concurrent.add_argument("--policies", default="eugene:least_busy,eugene:round_robin,eugene:conversation",
                            help="eugene:<loadBalancing> or route:<Router policy>[@<gateways>], comma-separated")
    concurrent.add_argument("--modes", default="default",
                            help="default, pinned, pinned0, pinsafe and/or driverpin (alone), comma-separated")
    concurrent.add_argument("--reset-at", type=float, default=20.0,
                            help="seconds into a run when a `~reset` policy clears its router's state")
    args = ap.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return
    with tempfile.TemporaryDirectory(prefix="ep-prompt-cache-") as tmp:
        if args.keep_dir:
            tmp = str(args.keep_dir)
            Path(tmp).mkdir(parents=True, exist_ok=True)
        bench = (ConcurrentBench if args.experiments == "concurrent" else Bench)(args, Path(tmp))
        try:
            bench.run()
        finally:
            bench.close()


if __name__ == "__main__":
    main()
