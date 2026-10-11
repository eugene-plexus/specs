#!/usr/bin/env python3
"""MR3 acceptance: search models, started the way llama-server needs, by the agent itself.

2026-10-11. An embedding GGUF started by the agent answered neither /v1/embeddings (501)
nor chat (500) and was listed as a chat model, because the adapter never passed
--embeddings, --pooling or --reranking. The agent now reads the file's own header (or the
runtime's `mode`) and starts a search model as one. This is the whole of it, through the
agent's REAL launch path, on a stack of its own:

* a real agent (its own `main()`, `--unattended`) on free ports, supervising a real library
  (over a folder of real GGUF files), a real gateway, and the real companion inference-driver
  it keeps for each runtime. The one thing moved is where the agent starts handing out runtime
  and driver ports: it has no setting for it and starts at 8090, where the live install
  draws its own;
* real `llama-server` processes (a CPU build: the live install holds the GPU), started by
  the agent with `POST /v1/runtimes`, their argv read back from `GET /v1/runtimes`;
* a client key minted by the agent, the gateway called with it as an app would.

What it asserts, in order (the letters are the ones printed beside each result):

  L  the library says what each file is, from its header bytes: a search model, a result
     sorter, a chat model; and that a reranker is not also an "embedding" model;
  A  the agent's command line for each: an embedder gets --embeddings, its four defaults
     (4,096 tokens over 4 requests, 2,048-token batches) and no --pooling when the header
     names one; a chat model started on the same stack gets exactly the command line a chat
     model always had;
  C  what the agent says about what is running: capabilities.embeddings / reranking, the
     window a request gets, no idle timeout for a search model, the declared timeout kept
     for chat;
  I  the idle control: the same 20-second timeout is declared on a chat model and an
     embedder; the gateway unloads the chat model, and the embedder, sent nothing, is still
     ready three timeouts on, with the process it started with;
  G  through the gateway: the embedder is listed as `embeddings` and not `chat`, a
     16-input batch returns unit vectors of the model's width in order, chat to an embedder
     is refused naming the door to use;
  W  an input longer than a request's window (1,024 tokens under the defaults) is refused
     with the limit named, and the same file declared with the person's own contextSize
     (the curated flag wins, the other defaults stay) takes about 1,600 tokens;
  O  the override: `mode: chat` on an embedding file is the command line a chat model has,
     and `mode: embedding` on a chat file adds --pooling last, the one case it is added;
  F  a runtime edited to start as something else (embedding, then chat, then embedding
     again): its engine restarts and so does its driver, and the gateway lists it as what it
     now is each time, not as what it was;
  R  the reranker, started by the agent with --reranking, scores the relevant passage
     higher, and is never listed as an embedder;
  S  what the agent logged, and that its teardown leaves no owned port listening.

Safe beside a live install: every ambient EUGENE_PLEXUS_* variable is dropped (install.ps1
sets them for the whole account), every port is chosen by the OS, the engines run on the
CPU from a build that is not the install's, and nothing outside its own temporary
directory is written. The models are hard-linked into it, so they are not touched.

Run with the agent's interpreter (it has httpx and pyyaml and every component):

    agent/.venv/Scripts/python.exe specs/scripts/mr3-search-models-acceptance.py \\
        --llama-server PATH/llama-server.exe --embedding-model nomic-embed-text-v1.5.Q8_0.gguf \\
        --qwen3-embedding Qwen3-Embedding-0.6B-Q8_0.gguf --chat-model Qwen3-0.6B-Q4_K_M.gguf \\
        --reranker qwen3-reranker-0.6b-q8_0.gguf

At least one embedder is needed; a check that needs a model that was not given is SKIP.
`--skip I,W,O,F,R` leaves phases out (a sabotage pass runs only the ones a break can reach).
`--keep` keeps the temporary directory.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import yaml

RESULTS: list[tuple[str, bool, str]] = []
SKIPPED: list[str] = []

#: The command-line spelling llama-server accepts for what an embedder is started with.
DEFAULT_FLAGS = ["--ctx-size", "4096", "--parallel", "4", "--batch-size", "2048", "--ubatch-size", "2048"]
#: How long the idle control waits before the gateway may unload a runtime, shortened from
#: the minutes a person would set.
IDLE_SECONDS = 20
#: The agent's own entry point, run after the one setting it has no knob for is moved: the
#: first port it hands to a runtime or to the driver it keeps for it. That range starts at
#: 8090, where the live install draws its own, so this run starts it well away. Nothing else
#: about the agent is changed.
LAUNCHER = (
    "import os\n"
    "import eugene_plexus_agent.state as state\n"
    "state._RUNTIME_PORT_BASE = int(os.environ['MR3_PORT_BASE'])\n"
    "from eugene_plexus_agent.__main__ import main\n"
    "main()\n"
)


def check(name: str, ok: bool, detail: object = "") -> bool:
    RESULTS.append((name, bool(ok), str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {len(RESULTS):>2}. {name}" + (f"  -- {detail}" if detail != "" else ""), flush=True)
    return bool(ok)


def skip(name: str, why: str) -> None:
    SKIPPED.append(name)
    print(f"SKIP  --. {name}  -- {why}", flush=True)


def info(text: str) -> None:
    print(f"INFO  {text}", flush=True)


def free_ports(count: int) -> list[int]:
    held = [socket.socket() for _ in range(count)]
    try:
        for sock in held:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in held]
    finally:
        for sock in held:
            sock.close()


def listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_until(what: str, probe: Any, seconds: float, every: float = 1.0) -> Any:
    """Wait for the subject itself: `probe()` answers something truthy, or the time runs out."""
    deadline = time.perf_counter() + seconds
    last: Any = None
    while time.perf_counter() < deadline:
        try:
            last = probe()
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError, OSError):
            last = None
        if last:
            return last
        time.sleep(every)
    info(f"never saw: {what}")
    return None


def norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def show(argv: list[str]) -> str:
    """A command line as the record prints it: the engine and the model by name."""
    words = [Path(argv[0]).name, *argv[1:]]
    if "--model" in words:
        words[words.index("--model") + 1] = Path(words[words.index("--model") + 1]).name
    return " ".join(words)


def said(status: int, body: Any) -> str:
    """What a declaration answered: its status, and its words only when it was refused."""
    return f"HTTP {status}" if status == 201 else f"HTTP {status} {str(body)[:300]}"


def link(source: Path, destination: Path) -> None:
    """Hard link when the volume allows, a copy otherwise: the original is never touched."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Stack:
    """One agent, with the library and the gateway under it, and everything about them."""

    def __init__(self, work: Path, args: argparse.Namespace) -> None:
        self.work = work
        self.args = args
        ports = free_ports(3)
        self.agent_port, self.library_port, self.gateway_port = ports
        self.agent = f"http://127.0.0.1:{self.agent_port}"
        self.gateway = f"http://127.0.0.1:{self.gateway_port}"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path = work / "agent.log"
        self.client = httpx.Client(base_url=self.agent, timeout=120, trust_env=False)
        self.app = httpx.Client(timeout=300, trust_env=False)
        #: Every port this run's processes were given, learned as they are declared, so that
        #: teardown can say none is still listening.
        self.owned_ports = list(ports)
        #: Where the agent starts handing out runtime and driver ports (a hundred of them).
        base = free_ports(1)[0]
        self.port_base = base if base + 100 < 65000 else base - 1000

    # -- bring up --------------------------------------------------------------------

    def write_config(self, models: Path) -> None:
        (self.work / "library.yaml").write_text(
            yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(models)]}), encoding="utf-8"
        )
        # `idleCheckSeconds` is the gateway's sweep for runtimes past their idle timeout, at
        # its minimum; `routingRefreshSeconds` is how soon it learns what the agent runs.
        (self.work / "gateway.yaml").write_text(
            yaml.safe_dump(
                {
                    "logLevel": "INFO",
                    "routingRefreshSeconds": 2,
                    "idleCheckSeconds": 2,
                    "requestTimeoutSeconds": 120,
                }
            ),
            encoding="utf-8",
        )
        (self.work / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "firstRunComplete": True,
                    "updateChecks": False,
                    "securityMode": "prompt_on_startup",
                    # A build that is not the install's, outside the managed store: the one
                    # directory the agent is told it may run an engine from.
                    "engineBinaryRoots": [str(Path(self.args.llama_server).resolve().parent)],
                    "components": [
                        {
                            "name": "library",
                            "kind": "library",
                            "url": f"http://127.0.0.1:{self.library_port}",
                            "spawn": {"configFile": str(self.work / "library.yaml")},
                        },
                        {
                            "name": "gateway",
                            "kind": "gateway",
                            "url": f"http://127.0.0.1:{self.gateway_port}",
                            "spawn": {"configFile": str(self.work / "gateway.yaml")},
                        },
                    ],
                    "runtimes": [],
                }
            ),
            encoding="utf-8",
        )

    def child_environment(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env.update(
            {
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(self.work / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": "127.0.0.1",
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(self.agent_port),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(self.work / "engines"),
                # The one case the agent cannot detect for itself; declared so no default
                # component (8080, 8082, 8083) is ever started beside the live install.
                "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "0",
                "MR3_PORT_BASE": str(self.port_base),
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                "PYTHONUNBUFFERED": "1",
                "PYTHONUTF8": "1",
            }
        )
        return env

    def start(self) -> None:
        log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, "-c", LAUNCHER, "--unattended"],
            cwd=self.work,
            env=self.child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        # Each runtime goes first, by the agent's own API (its driver goes with it), so the
        # engines are stopped by the agent and not by this script.
        try:
            for runtime in self.client.get("/v1/runtimes").json().get("runtimes", []):
                self.note_ports(runtime)
                self.client.delete(f"/v1/runtimes/{runtime['name']}")
        except (httpx.HTTPError, KeyError, ValueError):
            pass
        if os.name == "nt":
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            self.process.terminate()
        try:
            self.process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.process.kill()
            info("the agent did not stop in 120 s and was killed")

    # -- calls -----------------------------------------------------------------------

    def runtime(self, name: str) -> dict[str, Any]:
        response = self.client.get(f"/v1/runtimes/{name}")
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    def note_ports(self, runtime: dict[str, Any]) -> None:
        """Remember the ports a runtime and its driver were given, for the teardown check."""
        if isinstance(runtime.get("port"), int):
            self.owned_ports.append(runtime["port"])
        driver = runtime.get("driver")
        if driver:
            got = self.client.get(f"/v1/components/{driver}")
            if got.status_code == 200:
                self.owned_ports.append(int(str(got.json()["url"]).rsplit(":", 1)[1].rstrip("/")))

    def declare(self, body: dict[str, Any]) -> tuple[int, Any]:
        """Declare a runtime as a console does: the agent allocates its port, and keeps a
        companion driver for it (`autoDriver` is on unless said otherwise)."""
        response = self.client.post("/v1/runtimes", json=body)
        try:
            answer: Any = response.json()
        except ValueError:
            answer = response.text
        if response.status_code == 201 and isinstance(answer, dict):
            self.note_ports(answer)
        return response.status_code, answer

    def remove(self, name: str) -> None:
        """Take a runtime away, as a console's Remove does; its driver goes with it."""
        self.client.delete(f"/v1/runtimes/{name}")

    def status_of(self, name: str, wanted: str, seconds: float = 180) -> dict[str, Any] | None:
        def probe() -> dict[str, Any] | None:
            runtime = self.runtime(name)
            if runtime["status"] == "crashed":
                raise SystemExit(f"{name} crashed: {runtime.get('lastError')}")
            return runtime if runtime["status"] == wanted else None

        found: dict[str, Any] | None = wait_until(f"{name} {wanted}", probe, seconds, 1.0)
        return found

    def gateway_call(self, method: str, path: str, body: Any = None, key: str = "") -> httpx.Response:
        return self.app.request(
            method,
            f"{self.gateway}{path}",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
        )


def runtime_body(
    stack: Stack, name: str, model: Path, **overrides: Any
) -> dict[str, Any]:
    """The declaration a console makes for a model, CPU only: the pin keeps admission and the
    engine off the card the live install holds, and the build is the one the agent was told
    it may run."""
    body: dict[str, Any] = {
        "name": name,
        "engine": "llama_cpp",
        "modelPath": str(model),
        "modelAlias": name,
        "binary": str(Path(stack.args.llama_server).resolve()),
        "env": {"CUDA_VISIBLE_DEVICES": "-1"},
    }
    body.update(overrides)
    return body


def expected_argv(stack: Stack, view: dict[str, Any], model: Path, alias: str, tail: list[str]) -> list[str]:
    return [
        norm(Path(stack.args.llama_server).resolve()),
        "--model",
        norm(model),
        "--host",
        "127.0.0.1",
        "--port",
        str(view["port"]),
        "--alias",
        alias,
        *tail,
    ]


def normalised(argv: list[str]) -> list[str]:
    """The argv with its two paths compared as paths: the agent spells them its way."""
    out = list(argv)
    out[0] = norm(out[0])
    if "--model" in out:
        out[out.index("--model") + 1] = norm(out[out.index("--model") + 1])
    return out


def vectors(body: Any) -> list[list[float]]:
    return [row["embedding"] for row in sorted(body["data"], key=lambda r: r["index"])]


def length(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


BATCH = [
    "The cat sat on the mat.",
    "A cat is sitting on a mat.",
    "Quarterly tax filing deadlines for small businesses.",
    "How do I reset the password on my router?",
    "Photosynthesis converts light into chemical energy.",
    "The 2026 budget allocates funds to the second GPU.",
    "Rust's borrow checker prevents data races.",
    "Where is the nearest pharmacy open on Sunday?",
    "Mitochondria are the powerhouse of the cell.",
    "She plays the violin in a string quartet.",
    "Restart the service after editing its configuration file.",
    "The recipe calls for two cups of flour and an egg.",
    "Glaciers carve valleys over thousands of years.",
    "Invoice 4471 is overdue by thirty days.",
    "Use a semicolon to join two related clauses.",
    "The satellite entered a polar orbit at dawn.",
]

LONG_WORDS = 1600


def provenance(llama_server: Path, linked: dict[str, Path]) -> None:
    """What this run used, so a record of it can be compared with the publishers' own numbers
    (the SHA-256 Hugging Face lists for each file, the digest GitHub lists for the build)."""
    try:
        done = subprocess.run(
            [str(llama_server), "--version"], capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
        )
        words = [ln.strip() for ln in (done.stdout + done.stderr).splitlines() if ln.startswith("version:")]
    except (OSError, subprocess.TimeoutExpired):
        words = []
    info(f"engine {llama_server.name}: {words[0] if words else 'version not readable'}")
    for label, path in linked.items():
        info(f"model {path.name} ({label}): {path.stat().st_size} bytes, sha256 {sha256(path)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--llama-server", type=Path, default=os.environ.get("EP_LLAMA_SERVER"),
                        help="a CPU llama-server build (not the install's)")
    parser.add_argument("--embedding-model", type=Path, help="nomic-embed-text-v1.5 Q8_0 (768-d)")
    parser.add_argument("--qwen3-embedding", type=Path, help="Qwen3-Embedding-0.6B Q8_0 (1024-d)")
    parser.add_argument("--chat-model", type=Path, help="a small chat GGUF, the control (Qwen3-0.6B)")
    parser.add_argument("--reranker", type=Path, help="the ggml-org Qwen3-Reranker-0.6B Q8_0")
    parser.add_argument(
        "--skip", default="",
        help="phases to leave out, comma separated: I (the idle wait, over a minute), W, O, F, R",
    )
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args()
    if args.llama_server is None or not Path(args.llama_server).is_file():
        print("--llama-server must name a CPU build of llama-server (or set EP_LLAMA_SERVER)")
        return 2
    files = {
        "nomic": args.embedding_model,
        "qwen3-embedding": args.qwen3_embedding,
        "chat": args.chat_model,
        "reranker": args.reranker,
    }
    for label, path in files.items():
        if path is not None and not Path(path).is_file():
            print(f"--{label}: {path} is not a file")
            return 2
    if not (args.embedding_model or args.qwen3_embedding):
        print("at least one embedding model is needed (--embedding-model or --qwen3-embedding)")
        return 2
    args.skipped = {part.strip().upper() for part in args.skip.split(",") if part.strip()}
    if args.skipped - {"I", "W", "O", "F", "R"}:
        print(f"--skip takes I, W, O, F or R, not {sorted(args.skipped - {'I', 'W', 'O', 'F', 'R'})}")
        return 2

    work = Path(tempfile.mkdtemp(prefix="mr3-search-"))
    models = work / "models"
    models.mkdir()
    linked: dict[str, Path] = {}
    for label, path in files.items():
        if path is not None:
            linked[label] = models / Path(path).name
            link(Path(path), linked[label])
    stack = Stack(work, args)
    stack.write_config(models)
    print(f"work {work}\nports: agent {stack.agent_port}, library {stack.library_port}, "
          f"gateway {stack.gateway_port}", flush=True)
    provenance(Path(args.llama_server), linked)

    try:
        return run(stack, linked)
    except SystemExit as exit_:
        print(f"STOPPED: {exit_}")
        return 1
    finally:
        stack.stop()
        stack.client.close()
        stack.app.close()
        leaked = [p for p in stack.owned_ports if listening(p)]
        check("teardown by the agent leaves no owned port listening", not leaked, leaked or "")
        mine = sorted(set(stack.owned_ports))
        live = [p for p in mine if 8079 <= p <= 8190]
        check("none of the ports this run was given is one the live install uses (8079-8190)",
              not live, live or f"{len(mine)} ports, {mine[0]}-{mine[-1]}")
        failed = [r for r in RESULTS if not r[1]]
        print(f"\n{len(RESULTS) - len(failed)} PASS, {len(failed)} FAIL, {len(SKIPPED)} SKIP  (work {work})")
        if args.keep:
            info(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def run(stack: Stack, linked: dict[str, Path]) -> int:
    args = stack.args
    skipped: set[str] = args.skipped
    leaked_env = sorted(k for k in stack.child_environment() if k.upper().startswith("EUGENE_PLEXUS_"))
    check(
        "the agent is given only its own EUGENE_PLEXUS_* variables, none from the live install",
        set(leaked_env) == {
            "EUGENE_PLEXUS_AGENT_CONFIG_FILE", "EUGENE_PLEXUS_AGENT_BIND_HOST",
            "EUGENE_PLEXUS_AGENT_BIND_PORT", "EUGENE_PLEXUS_AGENT_ENGINE_ROOT",
            "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY",
        } and 8079 not in stack.owned_ports,
        leaked_env,
    )
    stack.start()
    if not wait_until("the agent answers", lambda: stack.client.get("/healthz").status_code == 200, 90):
        raise SystemExit("the agent never became healthy")
    initialised = stack.client.post("/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)})
    stack.client.headers["Authorization"] = f"Bearer {initialised.json()['sessionToken']}"
    library = "/api/proxy/library"
    gateway_proxy = "/api/proxy/gateway"
    check(
        "the library and the gateway are up under the agent",
        bool(wait_until("library", lambda: stack.client.get(f"{library}/healthz").status_code == 200, 90))
        and bool(wait_until("gateway", lambda: stack.client.get(f"{gateway_proxy}/healthz").status_code == 200, 90)),
    )
    key_response = stack.client.post("/v1/auth/client-keys", json={"name": "mr3-acceptance", "ttlDays": 1})
    key = key_response.json().get("token", "") if key_response.status_code in (200, 201) else ""
    check("the agent mints a client key, as an app is given one", bool(key), key_response.status_code)

    # ---- L: the library, from header bytes -------------------------------------------
    stack.client.post(f"{library}/v1/scan", json={"full": True})

    def scanned() -> dict[str, Any] | None:
        """Every file this run linked, listed, and the walk over: the subject, not a state
        the Library was in before it began."""
        if stack.client.get(f"{library}/v1/scan").json()["state"] == "scanning":
            return None
        found = {Path(m["path"]).name: m for m in stack.client.get(f"{library}/v1/models").json()["models"]}
        return found if all(p.name in found for p in linked.values()) else None

    listed: dict[str, Any] = wait_until("every linked model listed by the Library", scanned, 180) or {}

    def kinds(label: str) -> tuple[Any, ...] | None:
        if label not in linked:
            return None
        caps = (listed.get(linked[label].name) or {}).get("capabilities") or {}
        return (bool(caps.get("chat")), bool(caps.get("embedding")), bool(caps.get("rerank")))

    expectations = {
        "nomic": (False, True, False),
        "qwen3-embedding": (False, True, False),
        "chat": (True, False, False),
        "reranker": (False, False, True),
    }
    for label, expected in expectations.items():
        if label not in linked:
            skip(f"the library reads {label} from its header", f"no --{label} model given")
            continue
        check(
            f"the library says what {linked[label].name} is, from its header: "
            f"(chat, embedding, rerank) = {expected}",
            kinds(label) == expected,
            kinds(label),
        )

    # ---- A, C: declared with an idle timeout, started by the agent ----------------------
    search_label = "qwen3-embedding" if "qwen3-embedding" in linked else "nomic"
    search = linked[search_label]
    width = 1024 if search_label == "qwen3-embedding" else 768
    search_alias = "embedder"
    declared_idle = {"idleUnloadSeconds": IDLE_SECONDS}

    status, body = stack.declare(runtime_body(stack, "embedder", search, **declared_idle))
    check("the agent declares the embedder (no mode, an idle timeout of "
          f"{IDLE_SECONDS} s, as an old declaration might)", status == 201, said(status, body))
    if "chat" in linked:
        status, body = stack.declare(
            runtime_body(stack, "chat-control", linked["chat"], flags={"contextSize": 2048}, **declared_idle)
        )
        check("the agent declares a chat model on the same stack, with the same timeout and "
              "a curated flag", status == 201, said(status, body))
    else:
        skip("the chat control", "no --chat-model given")
    if "nomic" in linked and search_label != "nomic":
        stack.declare(runtime_body(stack, "embedder-light", linked["nomic"]))

    embedder = stack.status_of("embedder", "ready")
    chat_control = stack.status_of("chat-control", "ready") if "chat" in linked else None
    check("the embedder reaches ready, started by the agent", embedder is not None,
          (embedder or {}).get("lastError") or "")
    if embedder is None:
        raise SystemExit("the embedder did not start")
    ready_at = time.perf_counter()
    light = stack.status_of("embedder-light", "ready") if "nomic" in linked and search_label != "nomic" else None

    # -- A: the argv --
    default_tail = [*DEFAULT_FLAGS, "--embeddings"]
    check(
        "A1 the embedder's command line: the model, host, port and alias, its four defaults and "
        "--embeddings, and no --pooling (its header names one)",
        normalised(embedder["argv"]) == expected_argv(stack, embedder, search, search_alias, default_tail),
        show(embedder["argv"]),
    )
    if light is not None:
        check(
            "A2 the lighter embedder (nomic, an encoder that names mean pooling) gets the same, "
            "and no --pooling either",
            normalised(light["argv"]) == expected_argv(stack, light, linked["nomic"], "embedder-light", default_tail),
            show(light["argv"]),
        )
    if chat_control is not None:
        chat_alias = "chat-control"
        check(
            "A3 the chat model started on the same stack gets exactly the command line a chat "
            "model always had: its own curated flag, and nothing about search",
            normalised(chat_control["argv"])
            == expected_argv(stack, chat_control, linked["chat"], chat_alias, ["--ctx-size", "2048"]),
            show(chat_control["argv"]),
        )
        check("A4 and no flag of the search kind appears on it",
              not ({"--embeddings", "--embedding", "--reranking", "--rerank", "--pooling"} & set(chat_control["argv"])))

    # -- C: what the agent says about what runs --
    caps = embedder.get("capabilities") or {}
    check("C1 the embedder says it embeds and does not rerank (read off the command line it was "
          "started with: llama-server's /props says nothing of it)",
          caps.get("embeddings") is True and caps.get("reranking") is False, caps)
    check("C2 its window is the one its argv gave it: 1,024 tokens a request, 4 requests",
          caps.get("contextLength") == 1024 and caps.get("parallelSlots") == 4, caps)
    check("C3 it reports no idle timeout and no start-on-demand, whatever was declared: "
          "that is what the gateway reads", embedder.get("idleUnloadSeconds") is None
          and embedder.get("startOnDemand") is None,
          {k: embedder.get(k) for k in ("idleUnloadSeconds", "startOnDemand")})
    if chat_control is not None:
        ccaps = chat_control.get("capabilities") or {}
        check("C4 the chat model reports it does not embed, and keeps the idle timeout it declared",
              ccaps.get("embeddings") is False and ccaps.get("reranking") is False
              and chat_control.get("idleUnloadSeconds") == IDLE_SECONDS,
              {"capabilities": ccaps, "idle": chat_control.get("idleUnloadSeconds")})

    # ---- I: the idle control ------------------------------------------------------------
    if "I" in skipped:
        skip("I the idle control", "--skip I")
    elif chat_control is not None:
        info(f"waiting for the gateway to unload the chat model (idle {IDLE_SECONDS} s, swept every 2 s); "
             "nothing is sent to either runtime meanwhile")

        def unloaded() -> dict[str, Any] | None:
            view = stack.runtime("chat-control")
            return view if view["status"] == "stopped" and view.get("stopReason") == "idle" else None

        gone = wait_until("the chat control unloaded for being idle", unloaded, IDLE_SECONDS + 90, 1.0)
        waited = time.perf_counter() - ready_at
        check(f"I1 the control: the gateway unloads the idle chat model ({waited:.0f} s after ready), "
              "so the machinery is live in this run", gone is not None,
              {k: (gone or {}).get(k) for k in ("status", "stopReason")})
        # The sweep runs every 2 s, so the embedder would have gone with the chat model if its
        # timeout counted. Wait out three timeouts all the same before looking at it, and send it
        # nothing: a request would reset the clock it is being tested against.
        time.sleep(max(0.0, 3 * IDLE_SECONDS - (time.perf_counter() - ready_at)))
        waited = time.perf_counter() - ready_at
        still = stack.runtime("embedder")
        check(f"I2 the embedder, declared with the same timeout, is still ready {waited:.0f} s on, "
              f"three times the {IDLE_SECONDS} s it would have gone at, having been sent nothing",
              still["status"] == "ready" and waited >= 3 * IDLE_SECONDS, f"{still['status']}")
        check("I3 and nothing stopped it: no stop reason, its process is the one it started with",
              still.get("stopReason") is None and still.get("pid") == embedder.get("pid"),
              {k: still.get(k) for k in ("pid", "stopReason")})
    else:
        skip("I the idle control", "no --chat-model given")

    # ---- G: through the gateway ------------------------------------------------------------
    def in_gateway(
        *names: str, surfaces: Callable[[list[str]], bool] | None = None, seconds: float = 90
    ) -> dict[str, Any]:
        """Each named model in the gateway's list with a backend ready, and, when `surfaces` is
        given, listed as what it asks for. The list names a model whose runtime is still starting
        (so that a client can wake it), and says what a model is from what its driver has learned
        by trying the engine: the entry alone is not the thing to wait for. Returns the last look
        it had, matching or not, so that a failure shows what the gateway said."""
        seen: dict[str, Any] = {}

        def probe() -> bool | None:
            response = stack.gateway_call("GET", "/v1/models", key=key)
            if response.status_code != 200:
                return None
            found = {m["id"]: m for m in response.json()["data"]}
            seen.clear()
            seen.update({n: found[n] for n in names if n in found})
            ok = all(
                n in found
                and ((found[n].get("x_eugene_plexus") or {}).get("ready_backends") or 0) >= 1
                and (surfaces is None or surfaces((found[n].get("x_eugene_plexus") or {}).get("surfaces") or []))
                for n in names
            )
            return True if ok else None

        wait_until(f"{', '.join(names)} ready in the gateway's list", probe, seconds, 1.0)
        return dict(seen)

    def embeds(listed: list[str]) -> bool:
        return listed == ["embeddings"]

    def chats(listed: list[str]) -> bool:
        return "chat" in listed and "embeddings" not in listed

    models_seen = in_gateway(
        search_alias, *(["embedder-light"] if light is not None else []), surfaces=embeds
    )
    entry = models_seen.get(search_alias) or {}
    surfaces = (entry.get("x_eugene_plexus") or {}).get("surfaces")
    check("G1 GET /v1/models lists the embedder as embeddings and not chat",
          surfaces == ["embeddings"], surfaces)
    check("G2 and says what one request may hold: 1,024 tokens",
          (entry.get("x_eugene_plexus") or {}).get("context_length") == 1024,
          (entry.get("x_eugene_plexus") or {}).get("context_length"))
    if light is not None:
        light_surfaces = ((models_seen.get("embedder-light") or {}).get("x_eugene_plexus") or {}).get("surfaces")
        check("G3 the lighter embedder is listed as embeddings too", light_surfaces == ["embeddings"], light_surfaces)

    started = time.perf_counter()
    response = stack.gateway_call("POST", "/v1/embeddings", {"model": search_alias, "input": BATCH}, key)
    took = time.perf_counter() - started
    rows = vectors(response.json()) if response.status_code == 200 else []
    check(f"G4 a 16-input batch returns 16 vectors of the model's width ({width}) in {took:.1f} s",
          response.status_code == 200 and len(rows) == 16 and all(len(v) == width for v in rows),
          f"HTTP {response.status_code}, {len(rows)} vectors, widths {sorted({len(v) for v in rows})}")
    lengths = [length(v) for v in rows]
    check("G5 every vector is a unit vector (the engine normalises)",
          bool(lengths) and all(abs(n - 1.0) < 1e-3 for n in lengths),
          f"norms {min(lengths, default=0):.5f}..{max(lengths, default=0):.5f}")
    ordered = len(rows) == 16 and dot(rows[0], rows[1]) > dot(rows[0], rows[2]) + 0.05
    check("G6 they are in the order sent, and they mean something: the cat sentence is nearer its "
          "paraphrase than the tax one",
          ordered, f"{dot(rows[0], rows[1]):.3f} against {dot(rows[0], rows[2]):.3f}" if len(rows) > 2 else "")
    again = stack.gateway_call("POST", "/v1/embeddings", {"model": search_alias, "input": BATCH[:1]}, key)
    same = again.status_code == 200 and rows and max(
        abs(a - b) for a, b in zip(vectors(again.json())[0], rows[0], strict=True)) < 1e-3
    check("G7 the same sentence alone gives the vector it gave in the batch", bool(same))
    if light is not None:
        nomic_response = stack.gateway_call(
            "POST", "/v1/embeddings", {"model": "embedder-light", "input": BATCH}, key)
        nomic_rows = vectors(nomic_response.json()) if nomic_response.status_code == 200 else []
        check("G8 the lighter embedder's batch: 16 unit vectors of 768",
              len(nomic_rows) == 16 and all(len(v) == 768 for v in nomic_rows)
              and all(abs(length(v) - 1.0) < 1e-3 for v in nomic_rows),
              f"HTTP {nomic_response.status_code}")
    # The chat door refuses an embedder by name, as it always has.
    refused = stack.gateway_call("POST", "/v1/chat/completions",
                                 {"model": search_alias, "messages": [{"role": "user", "content": "hi"}]}, key)
    check("G9 chat to an embedder is refused naming the door to use, not answered with nonsense",
          refused.status_code == 400 and "embeddings" in refused.text, f"{refused.status_code} {refused.text[:120]}")

    # ---- W: a request's window ---------------------------------------------------------------
    if "W" in skipped:
        skip("W a request's window", "--skip W")
    else:
        long_text = " ".join(["alpha"] * LONG_WORDS)
        too_long = stack.gateway_call("POST", "/v1/embeddings", {"model": search_alias, "input": long_text}, key)
        text = too_long.text
        check("W1 an input longer than a request's 1,024-token window is refused, with the limit "
              "named and not as a server fault",
              too_long.status_code in (400, 413, 422) and "1024" in text and "context" in text.lower(),
              f"HTTP {too_long.status_code} {text[:420]}")
        wide = runtime_body(stack, "embedder-wide", search, modelAlias="embedder-wide", flags={"contextSize": 8192})
        status, body = stack.declare(wide)
        check("W2 the same file declared with the person's own contextSize (8192)", status == 201, said(status, body))
        wide_view = stack.status_of("embedder-wide", "ready")
        if wide_view is not None:
            wide_tail = ["--ctx-size", "8192", "--parallel", "4", "--batch-size", "2048", "--ubatch-size", "2048", "--embeddings"]
            check("W3 curated flags win: --ctx-size 8192 once, the other three defaults kept",
                  normalised(wide_view["argv"]) == expected_argv(stack, wide_view, search, "embedder-wide", wide_tail),
                  show(wide_view["argv"]))
            in_gateway("embedder-wide", surfaces=embeds)
            long_ok = stack.gateway_call("POST", "/v1/embeddings", {"model": "embedder-wide", "input": long_text}, key)
            usage = (long_ok.json().get("usage") or {}) if long_ok.status_code == 200 else {}
            rows_long = vectors(long_ok.json()) if long_ok.status_code == 200 else []
            check(f"W4 and then a ~1,600-token input works ({usage.get('prompt_tokens')} tokens counted): "
                  f"one unit vector of {width}",
                  long_ok.status_code == 200 and len(rows_long) == 1 and len(rows_long[0]) == width
                  and abs(length(rows_long[0]) - 1.0) < 1e-3 and (usage.get("prompt_tokens") or 0) >= 1500,
                  f"HTTP {long_ok.status_code} {long_ok.text[:160] if long_ok.status_code != 200 else ''}")
            stack.remove("embedder-wide")

    # ---- the override: auto against an explicit chat ---------------------------------------
    if "O" in skipped:
        skip("O the override", "--skip O")
    else:
        over = runtime_body(stack, "as-chat", search, modelAlias="as-chat", mode="chat")
        status, body = stack.declare(over)
        check("O1 the embedding file declared with mode chat", status == 201, said(status, body))
        as_chat = stack.status_of("as-chat", "ready")
        if as_chat is not None:
            check("O2 mode chat beats the header: the command line is exactly a chat model's, nothing "
                  "of the search kind", normalised(as_chat["argv"]) == expected_argv(stack, as_chat, search, "as-chat", []),
                  show(as_chat["argv"]))
            check("O3 and it reports what it runs as: mode chat, not an embedder",
                  as_chat.get("mode") == "chat" and (as_chat.get("capabilities") or {}).get("embeddings") is False,
                  {"mode": as_chat.get("mode"), "caps": as_chat.get("capabilities")})
            stack.remove("as-chat")

        # A chat file declared as an embedder: its header names no pooling, so --pooling is the
        # one flag the agent has to supply, and a decoder is pooled on its last token.
        if "chat" in linked:
            status, body = stack.declare(
                runtime_body(stack, "chat-as-embedder", linked["chat"], mode="embedding")
            )
            check("O4 the chat file declared with mode embedding", status == 201, said(status, body))
            chat_embedder = stack.status_of("chat-as-embedder", "ready")
            if chat_embedder is not None:
                check("O5 its header names no pooling, so --pooling last is added after --embeddings: "
                      "the one case it is",
                      normalised(chat_embedder["argv"]) == expected_argv(
                          stack, chat_embedder, linked["chat"], "chat-as-embedder",
                          [*DEFAULT_FLAGS, "--embeddings", "--pooling", "last"]),
                      show(chat_embedder["argv"]))
                in_gateway("chat-as-embedder", surfaces=embeds)
                made = stack.gateway_call(
                    "POST", "/v1/embeddings", {"model": "chat-as-embedder", "input": BATCH[:3]}, key)
                made_rows = vectors(made.json()) if made.status_code == 200 else []
                widths = sorted({len(v) for v in made_rows})
                check("O6 and it embeds: 3 unit vectors, all of one width",
                      len(made_rows) == 3 and len(widths) == 1 and widths[0] >= 256
                      and all(abs(length(v) - 1.0) < 1e-3 for v in made_rows),
                      f"HTTP {made.status_code}, widths {widths}")
                stack.remove("chat-as-embedder")

    # ---- F: a runtime edited to start as something else --------------------------------------
    # A driver learns whether its engine embeds by trying it, and keeps the answer. The runtime
    # below is edited the way the Inference page edits one (a PATCH of the whole declaration):
    # embedder, then chat, then embedder again. Each time its engine restarts and the agent
    # restarts its driver, and the gateway has to list it as what it now is.
    if "F" in skipped:
        skip("F a runtime edited to start as something else", "--skip F")
    else:
        flip = runtime_body(stack, "flip", search, mode="embedding")
        status, body = stack.declare(flip)
        check("F1 the embedding file declared as an embedder", status == 201, said(status, body))
        now = stack.status_of("flip", "ready")
        seen = in_gateway("flip", surfaces=embeds)
        check("F2 the gateway lists it as embeddings",
              embeds(((seen.get("flip") or {}).get("x_eugene_plexus") or {}).get("surfaces") or []),
              ((seen.get("flip") or {}).get("x_eugene_plexus") or {}).get("surfaces"))
        for step, (mode, expected_surfaces, name) in enumerate(
            (("chat", chats, "chat"), ("embedding", embeds, "embeddings")), start=3
        ):
            old_pid = (now or {}).get("pid")
            edited_at = time.perf_counter()
            patched = stack.client.patch("/v1/runtimes/flip", json={**flip, "mode": mode})
            check(f"F{step}a it is edited to mode {mode}: accepted, and the engine restarts",
                  patched.status_code == 200, f"HTTP {patched.status_code} {patched.text[:200]}")

            def restarted(old_pid: Any = old_pid) -> dict[str, Any] | None:
                view = stack.runtime("flip")
                return view if view["status"] == "ready" and view.get("pid") != old_pid else None

            now = wait_until("flip ready again on a new process", restarted, 180, 1.0)
            seen = in_gateway("flip", surfaces=expected_surfaces)
            surfaces_now = ((seen.get("flip") or {}).get("x_eugene_plexus") or {}).get("surfaces") or []
            check(f"F{step}b the gateway lists it as {name} within {time.perf_counter() - edited_at:.0f} s of the edit, "
                  "not as what it was",
                  now is not None and expected_surfaces(surfaces_now), surfaces_now)
            if mode == "chat":
                chatted = stack.gateway_call(
                    "POST", "/v1/chat/completions",
                    {"model": "flip", "messages": [{"role": "user", "content": "Say hi."}], "max_tokens": 4}, key)
                check("F3c and chat to it is routed to it, not refused as an embedder",
                      chatted.status_code == 200 and bool(chatted.json().get("choices")),
                      f"HTTP {chatted.status_code} {chatted.text[:160] if chatted.status_code != 200 else ''}")
            else:
                made = stack.gateway_call("POST", "/v1/embeddings", {"model": "flip", "input": BATCH[:2]}, key)
                got = vectors(made.json()) if made.status_code == 200 else []
                check(f"F4c and it embeds again: 2 unit vectors of {width}",
                      len(got) == 2 and all(len(v) == width and abs(length(v) - 1.0) < 1e-3 for v in got),
                      f"HTTP {made.status_code}")
        stack.remove("flip")

    # ---- R: the reranker ----------------------------------------------------------------------
    if "R" in skipped:
        skip("R the reranker", "--skip R")
    else:
        if "reranker" in linked:
            status, body = stack.declare(runtime_body(stack, "reranker", linked["reranker"]))
            check("R1 the reranker declared with no mode", status == 201, said(status, body))
            ranker = stack.status_of("reranker", "ready")
            if ranker is not None:
                rerank_tail = [*DEFAULT_FLAGS, "--reranking"]
                check("R2 its header names rank pooling and labels, so the agent adds --reranking and the "
                      "defaults, and neither --embeddings nor --pooling",
                      normalised(ranker["argv"]) == expected_argv(stack, ranker, linked["reranker"], "reranker", rerank_tail),
                      show(ranker["argv"]))
                rcaps = ranker.get("capabilities") or {}
                check("R3 it reports that it reranks and not that it embeds, and has no idle timeout",
                      rcaps.get("reranking") is True and rcaps.get("embeddings") is False
                      and ranker.get("idleUnloadSeconds") is None, rcaps)
                answered = httpx.post(
                    f"{str(ranker['url']).rstrip('/')}/v1/rerank", trust_env=False, timeout=120,
                    json={"query": "What is the giant panda?",
                          "documents": ["The giant panda is a bear native to central China.",
                                        "Quarterly invoices are due on the first of the month.",
                                        "A fast sports car with a V8 engine."]},
                )
                scored = {r["index"]: r["relevance_score"] for r in answered.json()["results"]} if answered.status_code == 200 else {}
                check("R4 the engine reranks: the relevant passage scores above the others",
                      scored.get(0, 0) > max(scored.get(1, 0), scored.get(2, 0)),
                      scored or answered.text[:200])
                reranker_alias = "reranker"
                listed_rerank = in_gateway(reranker_alias).get(reranker_alias) or {}
                rerank_surfaces = (listed_rerank.get("x_eugene_plexus") or {}).get("surfaces") or []
                check("R5 the reranker is never listed as an embedder, so no client indexes with it "
                      "(it is listed as chat until the rerank door of MR6: recorded, not gated)",
                      "embeddings" not in rerank_surfaces, rerank_surfaces)
                as_embedder = stack.gateway_call("POST", "/v1/embeddings", {"model": reranker_alias, "input": "x"}, key)
                check("R6 and an embeddings request for it is refused, not answered with zeros",
                      as_embedder.status_code == 400, f"{as_embedder.status_code} {as_embedder.text[:120]}")
                # The driver polls what it fronts every couple of seconds. Twenty seconds is about
                # ten looks at a reranker: more than enough for the first one that would have
                # killed it (llama-server --reranking has died answering /v1/embeddings).
                time.sleep(20)
                soaked = stack.runtime("reranker")
                check("R7 and it is still up, on the process it started with, after 20 s of its "
                      "driver polling it",
                      soaked["status"] == "ready" and soaked.get("pid") == ranker.get("pid"),
                      {k: soaked.get(k) for k in ("status", "pid", "lastError")})
        else:
            skip("R the reranker", "no --reranker model given")
    return finish(stack, skipped, "reranker" in linked)


def finish(stack: Stack, skipped: set[str], reranked: bool) -> int:
    # ---- the agent's own words about it ---------------------------------------------------------
    log = stack.log_path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in log.splitlines() if "starts as" in line]
    check("S1 the agent logged what each search model starts as, and why (settings never lie)",
          any("embedder starts as an embedding model: its header names pooling type" in line for line in lines),
          lines[:3])
    check("S2 and warned that the idle timeout declared on the embedder is not acted on",
          any("embedder is a search model, so its idleUnloadSeconds and startOnDemand are not acted on" in line
              for line in log.splitlines()))
    check("S3 and said nothing of the kind about the chat model",
          not any("chat-control starts as" in line for line in log.splitlines()))
    if "F" not in skipped:
        restarts = [line for line in log.splitlines()
                    if "runtime flip will start as something else; restarting its driver to ask again" in line]
        check("S4 and said, once for each edit that changed what the runtime starts as, that it "
              "restarted the driver", len(restarts) == 2, f"{len(restarts)} lines")
    if "R" not in skipped and reranked:
        # The driver logs every request it makes (httpx, at INFO), and the agent mirrors the log.
        theirs = [line for line in log.splitlines()
                  if line.startswith("[driver: reranker-driver]") and "HTTP Request: POST" in line]
        embedded = [line for line in theirs if "/v1/embeddings" in line]
        reranked_at = [line for line in theirs if "/v1/rerank" in line]
        check("S5 the reranker's driver asked it to rerank and never to embed (its own request log: "
              "llama-server --reranking answers an embeddings request with numbers it never "
              "computed, and has died answering it)",
              bool(reranked_at) and not embedded,
              f"{len(reranked_at)} rerank requests, {len(embedded)} embeddings requests")
    return 0 if all(ok for _name, ok, _detail in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
