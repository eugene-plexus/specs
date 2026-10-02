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

    python prompt-cache-measurement.py --llama-dir <dir with llama-server>
        --model <gguf> --sessions <dir of claude-N.jsonl, codex-N.jsonl>
        --out results.jsonl [--experiments single,interleaved2]

Every port is chosen by the OS, and none may fall in 8079-8290 (the live
install on the measuring box).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
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
        app = create_app(settings=Settings(config_file=directory / "gateway.yaml",
                                           metrics_file=directory / "metrics.sqlite3", **bootstrap))
    elif kind.startswith("driver"):
        from eugene_plexus_inference_driver.app import create_app
        from eugene_plexus_inference_driver.settings import Settings

        bootstrap = json.loads((directory / "bootstrap.json").read_text(encoding="utf-8"))
        app = create_app(settings=Settings(config_file=directory / "driver.yaml", **bootstrap))
    else:
        raise SystemExit(f"unknown process kind {kind!r}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


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
            cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
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
        self.procs[name] = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
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
    ap.add_argument("--engine-arg", dest="engine_args", action="append", default=[],
                    help="an argument for every llama-server, repeatable (e.g. --engine-arg=--threads)")
    args = ap.parse_args()
    if args.serve:
        serve(args.serve, args.directory, args.port)
        return
    with tempfile.TemporaryDirectory(prefix="ep-prompt-cache-") as tmp:
        bench = Bench(args, Path(tmp))
        try:
            bench.run()
        finally:
            bench.close()


if __name__ == "__main__":
    main()
