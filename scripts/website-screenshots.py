"""Photograph the real console and Workbench for eugeneplexus.com (v0.2.0).

The website shows the product, and the pictures should be the product. This
builds one disposable install of real processes and drives Chrome through it:

* a control root, and two enrolled agents named `desk-pc` and `garage-nas`
  (the second only a machine on the list), on random free ports;
* on `desk-pc`: the real gateway and library, and four real CPU llama.cpp
  runtimes started by the agent (Qwen3-0.6B for the console, Gemma 4 E4B for
  Workbench, a Qwen3 embedder and reranker for saved documents);
* the console as the v0.2.0 release serves it (the `dist` commit pinned by
  `scripts/install.sh`, extracted by `git archive`, not the working tree);
* Workbench installed from the agent's own catalogue at its pinned archive,
  with the owner and the two people `Sam` and `Riley`;
* demo data written for the shots: a fictional community-garden handbook
  (PDF) and a watering schedule (CSV), three memory notes, a small MCP server
  over the demo folder, a client key named `laptop`, about twenty requests.

Nothing is intercepted or canned, and nothing touches an installed service:
no default port, no service, every ambient EUGENE_PLEXUS_* variable cleared
for every child, the prefix under `D:\\eugene-demo\\<run-id>` so no path on
screen names a person, and engines on the CPU only.

    agent/.venv/Scripts/python.exe specs/scripts/website-screenshots.py \\
        --output <new-dir> --engine <CPU llama-server.exe>

`--hold` brings the install up, writes `session.json` beside the output and
waits for a `stop` file, so the browser half can be iterated against it:
`node scripts/website-screenshots.mjs <session.json> <output>`.
Review every image before publishing it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import httpx
import yaml

HERE = Path(__file__).resolve().parent
SPECS = HERE.parent
ROOT = SPECS.parent
DEMO = Path(os.environ.get("EP_DEMO_ROOT", r"D:\eugene-demo"))
HOME = Path.home()
TEMP = Path(os.environ.get("TEMP", "."))
WB_PY = ROOT / "workbench" / ".venv" / "Scripts" / "python.exe"
PASSPHRASE = "demo-passphrase-for-screenshots"
OWNER = "owner"
PEOPLE = {"sam": "Sam", "riley": "Riley"}
FIRST, SECOND = "desk-pc", "garage-nas"
#: Where each model is found on this machine, and what it is called in the demo.
MODEL_SOURCES = {
    "Qwen3-0.6B-Q4_K_M.gguf": [HOME / ".eugene-plexus" / "acceptance-models"],
    "Qwen3-Embedding-0.6B-Q8_0.gguf": [HOME / ".eugene-plexus" / "acceptance-models"],
    "qwen3-reranker-0.6b-q8_0.gguf": [HOME / ".eugene-plexus" / "acceptance-models"],
    # Not run: the Library page of a model that is not running shows "Runs as" and Delete.
    "nomic-embed-text-v1.5.Q8_0.gguf": [HOME / ".eugene-plexus" / "acceptance-models"],
    "gemma-4-E4B-it-Q4_K_M.gguf": [
        TEMP / "ep-a4-models",
        HOME / ".eugene-plexus" / "acceptance-models",
    ],
}
#: The one setting the agent has no knob for: where it starts handing out
#: runtime and app ports. Both ranges sit where the live install draws its own
#: (8090-8189, 8190-8289), so each is moved to a base the OS chose.
LAUNCHER = (
    "import os\n"
    "import eugene_plexus_agent.state as state\n"
    "import eugene_plexus_agent.apps as apps\n"
    "state._RUNTIME_PORT_BASE = int(os.environ['WS_RUNTIME_PORT_BASE'])\n"
    "apps.APP_PORT_BASE = int(os.environ['WS_APP_PORT_BASE'])\n"
    "from eugene_plexus_agent.__main__ import main\n"
    "main()\n"
)
CONTROL = (
    "import sys, uvicorn\n"
    "from pathlib import Path\n"
    "from eugene_plexus_control.app import create_app\n"
    "from eugene_plexus_control.settings import Settings\n"
    "d = Path(sys.argv[1])\n"
    "uvicorn.run(create_app(Settings(config_file=d / 'control.yaml', state_dir=d / 'state')),\n"
    "            host='127.0.0.1', port=int(sys.argv[2]), log_level='error', access_log=False)\n"
)
#: Case-insensitive regular expressions that must not match any captured page; the OS host and user
#: names are added at run time. Key prefixes match only when a key follows (the demo machine
#: `desk-pc` contains "sk-"), and names match as words.
BANNED = [
    r"\btroy\b",
    r"\btroyc",
    r"\btcorbin",
    r"\bcorbin",
    r"\bamish",
    r"\bjessie",
    r"192\.168\.",
    r"C:\\Users",
    r"eugene-plexus-secrets",
    r"\bsk-[a-z0-9_-]{8,}",
    r"\baiza[0-9a-z_-]{20,}",
]
#: The ports the live install holds; nothing here may use one.
LIVE_PORTS = set(range(8079, 8084)) | set(range(8279, 8284))


def routable_address() -> str:
    """The address this host would use to reach another; no packet is sent."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


def info(text: str) -> None:
    print(f"   {text}", flush=True)


def free_ports(count: int) -> list[int]:
    held = [socket.socket() for _ in range(count)]
    try:
        for sock in held:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in held]
    finally:
        for sock in held:
            sock.close()
    assert not LIVE_PORTS & set(ports), "the OS handed out a live-install port"
    return ports


def wait_until(what: str, probe, seconds: float, every: float = 0.5) -> Any:
    deadline = time.perf_counter() + seconds
    last: Exception | None = None
    while time.perf_counter() < deadline:
        try:
            found = probe()
            if found:
                return found
        except (
            httpx.HTTPError,
            KeyError,
            ValueError,
            TypeError,
            IndexError,
            OSError,
        ) as exc:
            last = exc
        time.sleep(every)
    raise SystemExit(f"timed out waiting for {what} ({last!r})")


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Every ambient EUGENE_PLEXUS_* variable cleared (install.ps1 sets some for the whole account)."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith("EUGENE_PLEXUS_")
    }
    env.pop("OPENAI_API_KEY", None)
    env.update(
        {
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
        }
    )
    env.update(extra or {})
    return env


class WorkbenchSession:
    """A person's browser against Workbench's real sign-in page, over HTTP, to seed its data."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=60, trust_env=False)
        self.secret: str | None = None

    def sign_in(self, password: str) -> str:
        start = self.http.get(self.base + "/signin")
        assert start.status_code == 302, start.text[:200]
        page = self.http.get(start.headers["location"])
        assert page.status_code == 200, page.text[:200]
        import html as html_module

        fields = {
            m.group(1): html_module.unescape(m.group(2))
            for m in re.finditer(
                r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page.text
            )
        }
        form = {k: v for k, v in fields.items() if k not in ("name", "password")}
        form["password"] = password
        if 'name="name"' in page.text:
            form["name"] = "operator"
        posted = self.http.post(
            httpx.URL(start.headers["location"]).copy_with(query=None), data=form
        )
        assert posted.status_code in (302, 303), posted.text[:300]
        location = self.http.get(posted.headers["location"]).headers.get("location", "")
        if "#signin=" in location:
            self.secret = location.split("#signin=", 1)[1]
        return location

    def request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = {"Origin": self.base}
        if self.secret:
            headers["X-Workbench-Secret"] = self.secret
        return self.http.request(method, self.base + path, headers=headers, **kw)

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.request("POST", path, **kw)


def seed_chats(owner: "WorkbenchSession") -> dict[str, str]:
    """Two empty chats on Gemma, set up the way a person sets them: one searching the saved
    documents, one with the documents-folder tool. The questions are asked in the browser."""
    models = owner.get("/api/models").json()["models"]
    gemma = next(m["id"] for m in models if "gemma-4-e4b" in m["id"])
    out: dict[str, str] = {"model": gemma}
    plain = owner.post("/api/chats", json={"model": gemma}).json()["id"]
    brief = {
        "instructions": "Answer in one or two short sentences. Say which file the answer comes from."
    }
    owner.request("PATCH", f"/api/chats/{plain}", json={"settings": brief})
    docs = owner.post("/api/chats", json={"model": gemma}).json()["id"]
    changed = owner.request(
        "PATCH", f"/api/chats/{docs}", json={"settings": {"documents": "on", **brief}}
    )
    assert changed.status_code == 200, changed.text
    server = next(
        sv["id"]
        for sv in owner.get("/api/tools/servers").json()["servers"]
        if sv["name"] == "Documents folder"
    )
    tool = owner.post("/api/chats", json={"model": gemma}).json()["id"]
    changed = owner.request(
        "PATCH", f"/api/chats/{tool}", json={"settings": {"toolServers": [server]}}
    )
    assert changed.status_code == 200, changed.text
    out.update({"plain": plain, "docs": docs, "tool": tool})
    return out


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = args.run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.prefix = DEMO / self.run_id
        self.models = DEMO / "models"
        self.documents = DEMO / "documents"
        self.output: Path = args.output.resolve()
        self.processes: list[tuple[str, subprocess.Popen[bytes]]] = []
        self.client = httpx.Client(timeout=120, trust_env=False)
        self.url: dict[str, str] = {}
        self.owned_ports: list[int] = []
        self.root_token = ""
        self.tokens: dict[str, str] = {}

    # -- preparation ---------------------------------------------------------

    def prepare(self) -> None:
        say(f"preparing {self.prefix}")
        self.prefix.mkdir(parents=True, exist_ok=False)
        self.models.mkdir(parents=True, exist_ok=True)
        self.documents.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        for name, folders in MODEL_SOURCES.items():
            target = self.models / name
            source = next((f / name for f in folders if (f / name).is_file()), None)
            if source is None:
                raise SystemExit(
                    f"{name} is not on this machine (looked in {[str(f) for f in folders]})"
                )
            if target.is_file() and target.stat().st_size == source.stat().st_size:
                continue
            info(f"{name}: {source.stat().st_size / 1e6:.0f} MB")
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        self.engine_source = Path(self.args.engine).resolve().parent
        said = subprocess.run(
            [str(self.args.engine), "--version"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        built = re.search(r"build (\d+)", said.stdout + said.stderr)
        assert built, "cannot read the engine's build number"
        self.engine_build = "b" + built.group(1)
        info(f"engine: llama.cpp {self.engine_build} (CPU build)")
        self.py = self.release_install()
        self.write_demo_files()

    def release_install(self) -> Path:
        """The packages v0.2.0 ships, built the way install.sh builds them: one venv, the locked
        dependencies with their hashes, then the seven packages at the commits install.sh pins.
        Built once and kept under the demo root; the screenshots then show the released code
        (and a real commit stamp), not a development checkout."""
        manifest = json.loads(
            (SPECS / "release" / "manifest.json").read_text(encoding="utf-8")
        )
        key = (
            manifest["components"]["agent"][:8]
            + "-"
            + manifest["dependenciesSha256"][:8]
        )
        venv = DEMO / "release" / key
        python = venv / "Scripts" / "python.exe"
        marker = venv / "installed.ok"
        if marker.is_file():
            return python
        uv = str(Path(sys.executable).with_name("uv.exe"))
        say(f"building the v0.2.0 install in {venv} (once)")
        shutil.rmtree(venv, ignore_errors=True)
        env = clean_env()
        subprocess.run(
            [uv, "venv", "--python", manifest["python"], str(venv)], check=True, env=env
        )
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "--only-binary",
                ":all:",
                "-r",
                str(SPECS / "release" / "requirements.lock"),
            ],
            check=True,
            env=env,
        )
        names = {
            "agent": "agent",
            "control": "control",
            "gateway": "gateway",
            "library": "library",
            "tool-driver": "tool-driver",
            "ui": "ui",
            "inference-driver": "inference-driver",
        }
        archives = [
            f"eugene-plexus-{n} @ https://github.com/eugene-plexus/{n}/archive/{manifest['components'][c]}.tar.gz"
            for c, n in names.items()
        ]
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--no-build-isolation",
                *archives,
            ],
            check=True,
            env=env,
        )
        marker.write_text("ok", encoding="utf-8")
        return python

    def write_demo_files(self) -> None:
        (self.documents / "watering-schedule.csv").write_text(
            "plot,day,time,volunteer\n"
            "1-6,Tuesday,7:00,Marisol\n7-12,Thursday,7:00,Devon\n13-18,Saturday,7:00,Priya\n"
            "19-24,Saturday,8:00,Tomas\nHerb bed,Tuesday and Friday,18:00,Anneke\n",
            encoding="utf-8",
            newline="\n",
        )
        node = [
            "node",
            str(HERE / "website-screenshots.mjs"),
            "--make-data",
            str(self.documents),
        ]
        subprocess.run(node, check=True)
        assert (self.documents / "maple-street-garden-handbook.pdf").is_file()

    # -- processes -----------------------------------------------------------

    def spawn(
        self, name: str, command: list[str], env: dict[str, str], cwd: Path
    ) -> subprocess.Popen[bytes]:
        log = (self.prefix / f"{name}.log").open("wb")
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW,
        )
        self.processes.append((name, proc))
        return proc

    def call(
        self, name: str, method: str, path: str, token: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, self.url[name] + path, headers=headers, **kw)

    def start_control(self) -> None:
        say("a control root")
        (port,) = free_ports(1)
        self.owned_ports.append(port)
        directory = self.prefix / "control"
        directory.mkdir()
        (directory / "control.yaml").write_text("{}\n", encoding="utf-8")
        self.url["control"] = f"http://127.0.0.1:{port}"
        self.spawn(
            "control",
            [str(self.py), "-c", CONTROL, str(directory), str(port)],
            clean_env(),
            directory,
        )
        wait_until(
            "control",
            lambda: self.call("control", "GET", "/healthz").status_code == 200,
            90,
        )
        self.call(
            "control", "POST", "/v1/auth/initialize", json={"passphrase": PASSPHRASE}
        ).raise_for_status()
        self.root_token = self.call(
            "control", "POST", "/v1/auth/login", json={"passphrase": PASSPHRASE}
        ).json()["sessionToken"]
        for name, display in PEOPLE.items():
            made = self.call(
                "control",
                "POST",
                "/v1/people",
                self.root_token,
                json={
                    "name": name,
                    "displayName": display,
                    "password": f"{name}-demo-password-1",
                },
            )
            assert made.status_code == 201, made.text

    def start_agent(
        self, label: str, node_name: str, *, components: bool, host: str = "127.0.0.1"
    ) -> None:
        say(f"an agent: {node_name}")
        directory = self.prefix / label
        directory.mkdir()
        agent_port, library_port, gateway_port = free_ports(3)

        def range_base() -> int:
            """A hundred ports the agent may allocate from, clear of the live install and below 65000."""
            while True:
                base = free_ports(1)[0]
                if base + 100 < 65000 and not LIVE_PORTS & set(range(base, base + 100)):
                    return base

        runtime_base, app_base = range_base(), range_base()
        self.owned_ports += [agent_port, library_port, gateway_port]
        url = f"http://{host}:{agent_port}"
        self.url[label] = url
        config: dict[str, Any] = {
            "firstRunComplete": True,
            "updateChecks": True,
            "securityMode": "prompt_on_startup",
            "advertiseUrl": url,
            "runtimes": [],
            "uvBinary": str(Path(sys.executable).with_name("uv.exe")),
            "components": [],
        }
        if components:
            # The CPU build sits where the agent keeps an installed engine, so the console says
            # "installed" the way it does on a real install; no `binary` override is needed.
            installed = directory / "engines" / "llama_cpp" / self.engine_build
            shutil.copytree(self.engine_source, installed)
            (installed / "install.json").write_text(
                json.dumps(
                    {
                        "version": self.engine_build,
                        "variant": "win-cpu-x64",
                        "binary": "llama-server.exe",
                        "installedAt": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                        "sizeBytes": sum(
                            f.stat().st_size
                            for f in installed.rglob("*")
                            if f.is_file()
                        ),
                    }
                ),
                encoding="utf-8",
            )
            (directory / "library.yaml").write_text(
                yaml.safe_dump({"logLevel": "INFO", "modelRoots": [str(self.models)]}),
                encoding="utf-8",
            )
            (directory / "gateway.yaml").write_text(
                yaml.safe_dump(
                    {
                        "logLevel": "INFO",
                        "routingRefreshSeconds": 2,
                        "requestTimeoutSeconds": 600,
                    }
                ),
                encoding="utf-8",
            )
            config["components"] = [
                # The root runs as its own process here, and this agent holds it as its control component.
                {"name": "control", "kind": "control", "url": self.url["control"]},
                {
                    "name": "library",
                    "kind": "library",
                    "url": f"http://127.0.0.1:{library_port}",
                    "spawn": {"configFile": str(directory / "library.yaml")},
                },
                {
                    "name": "gateway",
                    "kind": "gateway",
                    "url": f"http://127.0.0.1:{gateway_port}",
                    "spawn": {"configFile": str(directory / "gateway.yaml")},
                },
            ]
        (directory / "agent.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        env = clean_env(
            {
                "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(directory / "agent.yaml"),
                "EUGENE_PLEXUS_AGENT_BIND_HOST": host,
                "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
                "EUGENE_PLEXUS_AGENT_ENGINE_ROOT": str(directory / "engines"),
                "EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY": "0",
                "WS_RUNTIME_PORT_BASE": str(runtime_base),
                "WS_APP_PORT_BASE": str(app_base),
            }
        )
        self.spawn(
            label, [str(self.py), "-c", LAUNCHER, "--unattended"], env, directory
        )
        wait_until(
            f"{label} answers",
            lambda: self.call(label, "GET", "/healthz").status_code == 200,
            120,
        )
        initial = self.call(
            label, "POST", "/v1/auth/initialize", json={"passphrase": PASSPHRASE}
        )
        initial.raise_for_status()
        join = self.call(
            "control",
            "POST",
            "/v1/nodes/join-token",
            self.root_token,
            json={
                "nodeName": node_name,
                **({"grants": ["gateway"]} if components else {}),
            },
        )
        enrolled = self.call(
            label,
            "POST",
            "/v1/node/enroll",
            initial.json()["sessionToken"],
            timeout=120,
            json={
                "controlUrl": self.url["control"],
                "token": join.json()["token"],
                "name": node_name,
            },
        )
        assert enrolled.status_code == 200, enrolled.text
        wait_until(
            f"{label} after enrolment",
            lambda: self.call(label, "GET", "/healthz").status_code == 200,
            90,
        )
        self.tokens[label] = self.call(
            label, "POST", "/v1/auth/login", json={"passphrase": PASSPHRASE}
        ).json()["sessionToken"]
        self.agent_ports = getattr(self, "agent_ports", {}) | {
            label: (runtime_base, app_base)
        }

    # -- the demo's models -------------------------------------------------------

    def declare(self, name: str, model: str, alias: str, **extra: Any) -> None:
        body = {
            "name": name,
            "engine": "llama_cpp",
            "modelPath": str(self.models / model),
            "modelAlias": alias,
            "env": {"CUDA_VISIBLE_DEVICES": "-1"},
            **extra,
        }
        made = self.call("desk", "POST", "/v1/runtimes", self.tokens["desk"], json=body)
        assert made.status_code == 201, f"{name}: {made.status_code} {made.text[:300]}"
        view = made.json()
        if isinstance(view.get("port"), int):
            self.owned_ports.append(view["port"])

    def runtimes(self) -> None:
        say("four CPU runtimes (llama.cpp, the agent starts each)")
        self.declare(
            "qwen3-0.6b",
            "Qwen3-0.6B-Q4_K_M.gguf",
            "qwen3-0.6b",
            flags={"contextSize": 4096},
        )
        self.declare(
            "gemma-4-e4b",
            "gemma-4-E4B-it-Q4_K_M.gguf",
            "gemma-4-e4b",
            flags={"contextSize": 8192},
        )
        self.declare("search-model", "Qwen3-Embedding-0.6B-Q8_0.gguf", "search-model")
        self.declare("result-sorter", "qwen3-reranker-0.6b-q8_0.gguf", "result-sorter")
        for name in ("qwen3-0.6b", "gemma-4-e4b", "search-model", "result-sorter"):
            wait_until(
                f"{name} running", lambda name=name: self.runtime_running(name), 600, 2
            )
        for name in ("qwen3-0.6b", "gemma-4-e4b"):
            driver = (
                self.call("desk", "GET", f"/v1/runtimes/{name}", self.tokens["desk"])
                .json()
                .get("driver")
            )
            if driver:
                got = self.call(
                    "desk",
                    "PATCH",
                    f"/api/proxy/{driver}/v1/config",
                    self.tokens["desk"],
                    json={"thinkingMode": "off"},
                )
                info(f"{name} driver {driver}: thinkingMode off -> {got.status_code}")
        key = self.call(
            "desk",
            "POST",
            "/v1/auth/client-keys",
            self.tokens["desk"],
            json={"name": "laptop", "ttlDays": 30},
        )
        assert key.status_code in (200, 201), key.text
        self.laptop_key = key.json()["token"]

    def runtime_running(self, name: str) -> bool:
        runtime = self.call(
            "desk", "GET", f"/v1/runtimes/{name}", self.tokens["desk"]
        ).json()
        if runtime["status"] == "crashed":
            raise SystemExit(f"{name} crashed: {runtime.get('lastError')}")
        return runtime["status"] in ("ready", "running")

    def requests(self) -> None:
        say("about twenty requests, so Metrics has data")
        gateway = f"{self.url['desk']}/api/proxy/gateway"
        wait_until(
            "the gateway lists the demo models",
            lambda: (
                {
                    m["id"]
                    for m in self.call(
                        "desk",
                        "GET",
                        "/api/proxy/gateway/v1/models",
                        self.tokens["desk"],
                    ).json()["data"]
                }
                >= {"qwen3-0.6b", "gemma-4-e4b"}
            ),
            120,
        )
        prompts = [
            "Name a quick snack.",
            "Give me a haiku about rain.",
            "What is 12 times 12?",
            "Suggest a name for a cat.",
            "One tip for sleeping well.",
            "Say hello in French.",
            "What colour is the sky at noon?",
            "Name two root vegetables.",
            "A word that rhymes with garden.",
            "Why is the sea salty? One sentence.",
            "Name a good houseplant.",
            "Spell 'tomato' backwards.",
            "Suggest a Saturday plan.",
            "Name three herbs.",
            "Describe a ladybird in five words.",
            "What do bees make?",
            "Give me a short riddle.",
            "Name a spring flower.",
            "Is a tomato a fruit?",
            "Say good morning to a neighbour.",
        ]
        for index, prompt in enumerate(prompts):
            done = self.call(
                "desk",
                "POST",
                "/api/proxy/gateway/v1/chat/completions",
                self.laptop_key,
                json={
                    "model": "qwen3-0.6b",
                    "max_tokens": 48,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=300,
            )
            if done.status_code != 200:
                info(f"request {index}: {done.status_code} {done.text[:160]}")
        del gateway
        # A few the gateway cannot serve, so the outcome bar is a real mix.
        for _ in range(3):
            self.call(
                "desk",
                "POST",
                "/api/proxy/gateway/v1/chat/completions",
                self.laptop_key,
                json={
                    "model": "a-model-nobody-runs",
                    "max_tokens": 8,
                    "messages": [{"role": "user", "content": "Hello?"}],
                },
                timeout=60,
            )

    def search_accounts(self) -> None:
        """Two web search accounts, so the order page has an order. Neither has a key."""
        say("two web search accounts (no keys)")
        token = self.tokens["desk"]
        for name, patch in (
            ("searxng", {"provider": "searxng", "baseUrl": "http://127.0.0.1:9"}),
            ("brave", {"provider": "brave"}),
        ):
            (port,) = free_ports(1)
            self.owned_ports.append(port)
            made = self.call(
                "desk",
                "POST",
                "/v1/components",
                token,
                json={
                    "name": name,
                    "kind": "tool-driver",
                    "url": f"http://127.0.0.1:{port}",
                    "spawn": {"configFile": f"{name}.yaml"},
                },
            )
            assert made.status_code == 201, made.text
            wait_until(
                f"{name} answers",
                lambda name=name: (
                    self.call(
                        "desk", "GET", f"/api/proxy/{name}/healthz", token
                    ).status_code
                    == 200
                ),
                90,
            )
            patched = self.call(
                "desk", "PATCH", f"/api/proxy/{name}/v1/config", token, json=patch
            )
            assert patched.status_code == 200, patched.text

    # -- Workbench ----------------------------------------------------------------

    def workbench(self) -> None:
        say("Workbench, installed from the agent's catalogue")
        token = self.tokens["desk"]
        entry = next(
            (
                e
                for e in self.call("desk", "GET", "/v1/app-catalogue", token).json()[
                    "apps"
                ]
                if e["manifest"]["id"] == "workbench"
            ),
            None,
        )
        assert entry, "the catalogue offers no Workbench"
        info(f"catalogue: Workbench {entry['manifest']['version'][:8]}")
        began = self.call("desk", "POST", "/v1/apps/workbench/install", token)
        assert began.status_code == 202, began.text

        def installed() -> bool:
            progress = self.call(
                "desk", "GET", "/v1/apps/workbench/install", token
            ).json()
            if progress["state"] == "failed":
                raise SystemExit(
                    "the install failed: " + str(progress.get("error"))[-1500:]
                )
            return progress["state"] == "done"

        wait_until("the Workbench install", installed, 900, 2)
        wait_until(
            "Workbench running",
            lambda: (
                self.call("desk", "GET", "/v1/apps/workbench", token).json()["status"]
                == "running"
            ),
            120,
        )
        app = self.call("desk", "GET", "/v1/apps/workbench", token).json()
        self.workbench_url = app["uiUrl"].rstrip("/")
        port = int(self.workbench_url.rsplit(":", 1)[1].split("/")[0])
        self.owned_ports.append(port)
        assert port not in LIVE_PORTS
        # The owner, signed in as a person's browser does it, to seed what the shots show.
        owner = WorkbenchSession(self.workbench_url)
        landed = owner.sign_in(PASSPHRASE)
        assert landed.startswith("/#signin="), landed
        for text, kind in (
            ("The garden's plots are 4 by 8 feet.", "fact"),
            ("My plot is number 14, next to the herb bed.", "fact"),
            ("I like short answers with the steps in a list.", "preference"),
        ):
            made = owner.post("/api/memory/notes", json={"text": text, "kind": kind})
            assert made.status_code in (200, 201), made.text
        files = [
            (
                "files",
                (
                    p.name,
                    p.read_bytes(),
                    "application/pdf" if p.suffix == ".pdf" else "text/csv",
                ),
            )
            for p in sorted(self.documents.iterdir())
            if p.suffix in (".pdf", ".csv")
        ]
        kept = owner.post("/api/documents", files=files)
        assert kept.status_code == 201, kept.text

        def read() -> bool:
            listing = owner.get("/api/documents").json()
            rows = listing.get("documents") or []
            info(
                "documents: "
                + ", ".join(f"{r.get('name')}={r.get('state')}" for r in rows)
            )
            return bool(rows) and all(r.get("state") == "ready" for r in rows)

        wait_until("the saved documents read", read, 300, 3)
        # A small MCP server over the demo folder: the tool whose call Workbench holds for approval.
        (mcp_port,) = free_ports(1)
        self.owned_ports.append(mcp_port)
        self.spawn(
            "documents-mcp",
            [
                str(WB_PY),
                str(HERE / "fixtures" / "website-demo-documents-mcp.py"),
                str(self.documents),
                str(mcp_port),
            ],
            clean_env(),
            self.prefix,
        )
        wait_until("the documents tool server", lambda: self.listening(mcp_port), 60)
        added = owner.post(
            "/api/tools/servers",
            json={
                "name": "Documents folder",
                "transport": "http",
                "url": f"http://127.0.0.1:{mcp_port}/mcp",
            },
        )
        assert added.status_code == 201, added.text
        self.mcp_name = "Documents folder"
        self.chats = seed_chats(owner)

    # -- teardown ----------------------------------------------------------------

    def stop(self) -> None:
        say("tearing down the install")
        for label in ("desk", "garage"):
            if label in self.url and label in self.tokens:
                try:
                    for runtime in (
                        self.call(label, "GET", "/v1/runtimes", self.tokens[label])
                        .json()
                        .get("runtimes", [])
                    ):
                        self.call(
                            label,
                            "DELETE",
                            f"/v1/runtimes/{runtime['name']}",
                            self.tokens[label],
                        )
                except (httpx.HTTPError, KeyError, ValueError):
                    pass
        for name, proc in reversed(self.processes):
            if proc.poll() is None:
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                    proc.wait(timeout=60 if name in ("desk", "garage") else 10)
                except (subprocess.TimeoutExpired, OSError):
                    pass
            if proc.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True
                )
        leaked = [p for p in self.owned_ports if self.listening(p)]
        info(
            "ports still listening after teardown: "
            + (str(leaked) if leaked else "none")
        )
        assert not LIVE_PORTS & set(self.owned_ports), "a live-install port was used"
        self.client.close()
        if not self.args.keep and not self.args.hold:
            logs = self.output / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            for log in self.prefix.glob("*.log"):
                shutil.copy2(log, logs / log.name)
            for _ in range(10):
                shutil.rmtree(self.prefix, ignore_errors=True)
                if not self.prefix.exists():
                    break
                time.sleep(2)
            info(
                f"install removed: {not self.prefix.exists()} (the models stay in {self.models})"
            )

    @staticmethod
    def listening(port: int) -> bool:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    def sessions(self) -> Path:
        path = self.prefix / "session.json"
        path.write_text(
            json.dumps(
                {
                    "url": self.url["desk"],
                    "token": self.tokens["desk"],
                    "passphrase": PASSPHRASE,
                    "owner": OWNER,
                    "shots": str(self.output),
                    "run": self.run_id,
                    "hostName": socket.gethostname(),
                    "userName": os.environ.get("USERNAME", ""),
                    "banned": BANNED,
                    "garage": self.url.get("garage"),
                    "documents": str(self.documents),
                    "workbench": getattr(self, "workbench_url", None),
                    "people": PEOPLE,
                    "chats": getattr(self, "chats", {}),
                    "playwright": str(ROOT / "ui"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="a new directory for the PNGs"
    )
    parser.add_argument(
        "--engine", type=Path, required=True, help="a CPU llama-server.exe build"
    )
    parser.add_argument("--run-id", help="the run's name (default: the time)")
    parser.add_argument(
        "--keep", action="store_true", help="leave the install directory after the run"
    )
    parser.add_argument(
        "--hold",
        action="store_true",
        help="stand the install up, then wait for a `stop` file",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    run = Run(args)
    try:  # noqa: SIM105
        run.prepare()
        run.start_control()
        run.start_agent("desk", FIRST, components=True)
        # A console will not hop to a loopback address, so the second machine listens on, and advertises,
        # this host's own address (its one port only); the pictures show it as a demo address.
        run.start_agent("garage", SECOND, components=False, host=routable_address())
        run.runtimes()
        run.requests()
        run.search_accounts()
        run.workbench()
        session = run.sessions()
        if args.hold:
            say(f"held: {session}")
            while not (run.prefix / "stop").exists():
                time.sleep(2)
            return 0
        subprocess.run(
            [
                "node",
                str(HERE / "website-screenshots.mjs"),
                str(session),
                str(run.output),
            ],
            check=True,
            env=clean_env(),
        )
        return 0
    except BaseException:
        traceback.print_exc()
        sys.stderr.flush()
        raise
    finally:
        run.stop()
        say(f"run time {time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    sys.exit(main())
