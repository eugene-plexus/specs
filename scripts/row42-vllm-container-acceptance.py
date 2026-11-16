"""Row 42: vLLM from its official container image, run for real with Docker.

`docs/design/rows/row-42.md` section 5. GitHub's Linux runners have Docker and
no GPU, so this builds a small CPU fixture image (an OpenAI-compatible server
behind a `vllm` entrypoint that answers `/health`, `/version`, `/v1/models`,
`/load` and a chat completion), sets it as the agent's `vllmContainerImage`
(by its image ID, `sha256:...`), and checks Eugene's side of the contract on a
real, isolated agent (quiet ports, its own data folder, no EUGENE_PLEXUS_*
from the environment):

1. The agent detects Docker (GPUs: false here) and reports it.
2. The image installs as an engine build (already on the machine: no pull).
3. A vLLM runtime in container mode starts: the container carries this agent's
   labels, the model folder is mounted read only (a write from inside fails),
   the compile cache is the runtime's own, the port is published on loopback
   only, the profile's variable reaches the container by name and its value is
   in no command line, and the engine answers a chat.
4. Stop: the container is gone within 30 s.
5. A bad image reference: the pull fails naming the registry's answer, and the
   image in use stays.
6. Kill the agent with its whole process tree (systemd's final SIGKILL): the
   container is left running; at the agent's next start it is removed, and the
   log says so.

Not run here: a real vLLM on a GPU (no GPU on the runner), and a chat routed
through a gateway (the engine is reached on its own port; routing to a runtime
does not depend on how the runtime was started).
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import psutil
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance_logs import quiet_ports  # noqa: E402

FIXTURE_VLLM = r'''#!/usr/bin/env python3
"""A stand-in for `vllm serve`: answers what Eugene reads, on CPU, in seconds."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

args = sys.argv[1:]
if args[:1] != ["serve"]:
    sys.exit("fixture: only `serve` is known")
if "--help=all" in args:
    print("--host --port --served-model-name --enable-prompt-tokens-details --max-model-len")
    sys.exit(0)
model = args[1]
def opt(name, default):
    return args[args.index(name) + 1] if name in args else default
host, port = opt("--host", "127.0.0.1"), int(opt("--port", "8000"))
served = opt("--served-model-name", model)
try:
    with open(os.path.join(model, "written-from-inside"), "w") as f:
        f.write("x")
    writable = True
except OSError as e:
    writable = False
    print(f"fixture: the model folder refused a write: {e}", flush=True)

class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
        elif self.path == "/version":
            self._json(200, {"version": "0.0.0-fixture"})
        elif self.path == "/load":
            self._json(200, {"server_load": 0})
        elif self.path == "/v1/models":
            self._json(200, {"data": [{"id": served, "max_model_len": 2048}]})
        elif self.path == "/fixture":
            self._json(200, {"modelWritable": writable, "model": model,
                             "secret": os.environ.get("FIXTURE_SECRET"),
                             "offline": os.environ.get("HF_HUB_OFFLINE")})
        else:
            self._json(404, {"error": "not found"})
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/v1/chat/completions":
            self._json(200, {"id": "x", "object": "chat.completion", "model": served,
                             "choices": [{"index": 0, "finish_reason": "stop",
                                          "message": {"role": "assistant",
                                                      "content": "hello from the container"}}],
                             "usage": {"prompt_tokens": 1, "completion_tokens": 4, "total_tokens": 5}})
        else:
            self._json(404, {"error": "not found"})
    def log_message(self, *a):
        pass

import signal
# PID 1 in a container ignores a signal it has no handler for; vLLM has one.
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
print(f"fixture: serving {served} on {host}:{port}", flush=True)
ThreadingHTTPServer((host, port), Handler).serve_forever()
'''

DOCKERFILE = """FROM python:3.12-slim
COPY vllm /usr/local/bin/vllm
RUN chmod 0755 /usr/local/bin/vllm
"""

PASSED: list[str] = []


def ok(text: str) -> None:
    PASSED.append(text)
    print(f"PASS {text}", flush=True)


def wait(predicate, label, seconds=60.0, step=0.25):
    deadline = time.perf_counter() + seconds
    last: object = None
    while time.perf_counter() < deadline:
        try:
            result = predicate()
            if result:
                return result
            last = result
        except (httpx.HTTPError, KeyError, ValueError, OSError) as exc:
            last = exc
        time.sleep(step)
    raise AssertionError(f"timed out after {seconds:g} s: {label} (last: {last!r})")


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    answer = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if check and answer.returncode != 0:
        raise AssertionError(f"docker {' '.join(args)}: {answer.stderr.strip()}")
    return answer


def containers_named(name: str) -> list[str]:
    listed = docker("ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}")
    return [line for line in listed.stdout.splitlines() if line.strip()]


class Agent:
    def __init__(self, directory: Path, port: int, machine_port: int) -> None:
        self.directory = directory
        self.port = port
        self.machine_port = machine_port
        self.process: subprocess.Popen[bytes] | None = None
        self.log = directory / "agent.log"
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=60
        )

    def start(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
        env.update(
            EUGENE_PLEXUS_AGENT_CONFIG_FILE=str(self.directory / "agent.yaml"),
            EUGENE_PLEXUS_AGENT_BIND_HOST="127.0.0.1",
            EUGENE_PLEXUS_AGENT_BIND_PORT=str(self.port),
            EUGENE_PLEXUS_AGENT_MACHINE_PORT=str(self.machine_port),
            EUGENE_PLEXUS_AGENT_ENGINE_ROOT=str(self.directory / "engines"),
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
            PYTHONUNBUFFERED="1",
        )
        with self.log.open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
                cwd=self.directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        wait(lambda: self.client.get("/healthz").status_code == 200, "agent up", 60)

    def kill_tree(self) -> None:
        """SIGKILL the agent and every process under it, as systemd's final
        SIGKILL of a service's control group does: no stop runs, and the
        `docker run` CLI forwards nothing. (Killing the agent alone is not an
        orphan on Linux: the CLI gets SIGTERM on its parent's death,
        `orphan_kill`, and forwards it to the container.) The agent is frozen
        first, so it sees none of it."""
        assert self.process is not None
        agent = psutil.Process(self.process.pid)
        agent.suspend()
        for child in agent.children(recursive=True):
            child.kill()
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=30)

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=30)


def main() -> int:
    if shutil.which("docker") is None:
        print("SKIP: no docker on this machine", flush=True)
        return 0
    if os.name == "nt":
        print("SKIP: the container path runs on Linux runners (Docker without a VM)", flush=True)
        return 0
    directory = Path(tempfile.mkdtemp(prefix="ep-row42-"))
    print(f"isolated tree: {directory}", flush=True)

    # The fixture image, named by its image ID: a digest nobody can move.
    build = directory / "image"
    build.mkdir()
    (build / "vllm").write_text(FIXTURE_VLLM, encoding="utf-8", newline="\n")
    (build / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8", newline="\n")
    image_id = docker("build", "-q", str(build)).stdout.strip().splitlines()[-1]
    assert image_id.startswith("sha256:") and len(image_id) == 71, image_id
    print(f"fixture image: {image_id}", flush=True)

    model = directory / "library" / "Fixture-1B"
    model.mkdir(parents=True)
    (model / "config.json").write_text(
        json.dumps({"architectures": ["LlamaForCausalLM"], "num_attention_heads": 8}),
        encoding="utf-8",
    )
    (model / "model.safetensors").write_bytes(b"\0" * 1024)

    agent_port, machine_port, runtime_port = quiet_ports(3)
    (directory / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "vllmContainerImage": image_id,
                "components": [],
                "runtimes": [],
            }
        ),
        encoding="utf-8",
    )
    agent = Agent(directory, agent_port, machine_port)
    name = None
    try:
        agent.start()
        token = agent.client.post(
            "/v1/auth/initialize", json={"passphrase": secrets.token_urlsafe(24)}
        ).json()["sessionToken"]
        agent.client.headers["Authorization"] = f"Bearer {token}"

        # 1. Docker is detected and reported.
        listed = agent.client.get("/v1/engines").json()
        found = listed["containerRuntime"]
        assert found["kind"] == "docker" and found["usable"] is True, found
        assert found["gpus"] is False, found  # a GPU-less runner
        vllm = next(e for e in listed["engines"] if e["engine"] == "vllm")
        assert vllm["container"]["installable"] is True, vllm["container"]
        assert vllm["container"]["image"] == image_id
        assert vllm["container"]["source"] == "configured"
        ok(f"Docker {found['version']} is detected and reported, GPUs: false")

        # 2. The image installs as an engine build.
        started = agent.client.post("/v1/engines/vllm/install", json={"variant": "container"})
        assert started.status_code == 202, started.text
        done = wait(
            lambda: (
                s
                if (s := agent.client.get("/v1/engines/vllm/install").json())["state"]
                in ("done", "failed")
                else None
            ),
            "image install",
        )
        assert done["state"] == "done", done
        vllm = next(
            e for e in agent.client.get("/v1/engines").json()["engines"] if e["engine"] == "vllm"
        )
        assert vllm["available"] is True and vllm["container"]["pulled"]["digest"] == image_id
        ok("the image is an installed engine build, recorded by its digest")

        # 3. A runtime in container mode.
        created = agent.client.post(
            "/v1/runtimes",
            json={
                "name": "fixture",
                "engine": "vllm",
                "modelPath": str(model),
                "port": runtime_port,
                "autoStart": False,
                "autoDriver": False,
                "env": {"FIXTURE_SECRET": "s3cret-value"},
                "flags": {"source": "container", "reuseRepeatedText": False},
            },
        )
        assert created.status_code in (200, 201), created.text
        assert agent.client.post("/v1/runtimes/fixture/start").is_success
        ready = wait(
            lambda: (
                r
                if (r := agent.client.get("/v1/runtimes/fixture").json())["status"]
                in ("ready", "crashed")
                else None
            ),
            "runtime ready",
            120,
        )
        assert ready["status"] == "ready", ready
        container = ready["container"]
        name = container["name"]
        assert container["image"] == image_id, container
        inspected = json.loads(docker("inspect", name).stdout)[0]
        labels = inspected["Config"]["Labels"]
        assert labels.get("eugene-plexus.runtime") == "fixture", labels
        assert labels.get("eugene-plexus.agent") and name.endswith("-fixture"), labels
        ok(f"the runtime runs in container {name}, labelled with its agent and runtime")

        mounts = {m["Destination"]: m for m in inspected["Mounts"]}
        assert set(mounts) == {"/models/Fixture-1B", "/root/.cache/vllm"}, mounts
        assert mounts["/models/Fixture-1B"]["RW"] is False, mounts
        assert mounts["/root/.cache/vllm"]["RW"] is True
        assert Path(mounts["/root/.cache/vllm"]["Source"]).is_relative_to(directory)
        refused = docker("exec", name, "sh", "-c", "touch /models/Fixture-1B/x", check=False)
        assert refused.returncode != 0, "a write into the model folder succeeded"
        assert "Read-only" in refused.stderr or "read-only" in refused.stderr.lower(), refused
        assert not (model / "written-from-inside").exists()
        ok("the model folder is mounted read only: a write from inside fails")

        bindings = inspected["HostConfig"]["PortBindings"]["8000/tcp"]
        assert bindings == [{"HostIp": "127.0.0.1", "HostPort": str(runtime_port)}], bindings
        assert not inspected["HostConfig"].get("Privileged")
        assert inspected["HostConfig"].get("IpcMode") != "host"
        assert "no-new-privileges" in (inspected["HostConfig"].get("SecurityOpt") or [])
        ok(f"the port is published on loopback only (127.0.0.1:{runtime_port})")

        argv = " ".join(ready.get("argv") or [])
        assert "FIXTURE_SECRET" in argv and "s3cret-value" not in argv, argv
        assert "FIXTURE_SECRET=s3cret-value" in inspected["Config"]["Env"]
        engine = httpx.Client(base_url=f"http://127.0.0.1:{runtime_port}", trust_env=False)
        seen = engine.get("/fixture").json()
        assert seen["secret"] == "s3cret-value" and seen["offline"] == "1", seen
        assert seen["modelWritable"] is False, seen
        answer = engine.post(
            "/v1/chat/completions",
            json={"model": "Fixture-1B", "messages": [{"role": "user", "content": "hi"}]},
        ).json()
        assert answer["choices"][0]["message"]["content"] == "hello from the container"
        assert ready["modelAlias"] == "Fixture-1B"
        ok("the profile's variable reaches the container by name only; the engine answers a chat")

        # 4. Stop.
        began = time.perf_counter()
        stopped = agent.client.post("/v1/runtimes/fixture/stop")
        assert stopped.is_success, stopped.text
        wait(lambda: not containers_named(name), "container gone after stop", 30)
        ok(f"Stop removes the container ({time.perf_counter() - began:.1f} s)")

        # 5. A bad image reference: the pull names the registry's answer, and the
        # image in use stays.
        bad = "ghcr.io/eugene-plexus/no-such-vllm-image@sha256:" + "0" * 64
        assert agent.client.patch("/v1/config", json={"vllmContainerImage": bad}).is_success
        started = agent.client.post("/v1/engines/vllm/install", json={"variant": "container"})
        assert started.status_code == 202, started.text
        failed = wait(
            lambda: (
                s
                if (s := agent.client.get("/v1/engines/vllm/install").json())["state"]
                in ("done", "failed")
                else None
            ),
            "bad pull ends",
            120,
        )
        assert failed["state"] == "failed", failed
        error = failed.get("error") or ""
        assert error.startswith(f"Pulling {bad} failed: "), error
        words = error.split("failed: ", 1)[1].lower()
        assert any(w in words for w in ("denied", "not found", "unknown", "unauthorized")), error
        vllm = next(
            e for e in agent.client.get("/v1/engines").json()["engines"] if e["engine"] == "vllm"
        )
        assert vllm["container"]["pulled"]["digest"] == image_id, vllm["container"]
        assert agent.client.patch("/v1/config", json={"vllmContainerImage": image_id}).is_success
        ok(f"a bad image's pull fails in the registry's words ({error.split(': ', 1)[1][:80]})")

        # 6. Kill the agent with the runtime running: an orphan, removed at the next start.
        assert agent.client.post("/v1/runtimes/fixture/start").is_success
        wait(
            lambda: agent.client.get("/v1/runtimes/fixture").json()["status"] == "ready",
            "runtime ready again",
            120,
        )
        agent.kill_tree()
        time.sleep(2)
        assert containers_named(name), "the container went with the agent; nothing to sweep"
        agent.start()
        wait(lambda: not containers_named(name), "orphan removed at the next start", 60)
        assert "an earlier run of this agent left running" in agent.log.read_text(
            encoding="utf-8", errors="replace"
        )
        ok(
            "an agent killed with its whole tree leaves its container running; its next "
            "start removes it, and the log says so"
        )
    except BaseException:
        print("---- agent log (tail) ----", flush=True)
        if agent.log.exists():
            print(agent.log.read_text(encoding="utf-8", errors="replace")[-8000:], flush=True)
        raise
    finally:
        if name:
            docker("rm", "-f", name, check=False)
        agent.stop()
        docker("image", "rm", "-f", image_id, check=False)
    print(f"ALL PASS: {len(PASSED)} checks; tree retained for logs at {directory}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
