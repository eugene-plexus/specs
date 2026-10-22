"""Row 43, CI Linux: real agent, stub NVML and nvidia-smi, fixture engine.

No inference or hardware measurements. Every listener uses an allocated port,
all install variables are removed, and fixtures/logs stay under .codex-tmp.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
import yaml

NVML = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int cards(void) {
    FILE *f = fopen(getenv("ROW43_CARDS_FILE"), "r");
    int n = 2; if (f) { fscanf(f, "%d", &n); fclose(f); } return n;
}
int nvmlInit_v2(void) { return 0; }
int nvmlShutdown(void) { return 0; }
const char *nvmlErrorString(int n) { return "fixture unsupported"; }
int nvmlDeviceGetHandleByIndex_v2(unsigned i, void **h) {
    if (i >= cards()) return 6; *h = (void *)(uintptr_t)(cards() == 1 ? 2 : i+1); return 0;
}
int nvmlDeviceGetUUID(void *h, char *s, unsigned n) {
    snprintf(s, n, "GPU-%c", (uintptr_t)h == 1 ? 'a' : 'b'); return 0;
}
typedef struct { char legacy[16]; unsigned domain,bus,device,id,subsystem; char busId[32]; } Pci;
int nvmlDeviceGetPciInfo_v3(void *h, Pci *p) { snprintf(p->busId, 32, "00000000:0%lu:00.0", (unsigned long)(uintptr_t)h); return 0; }
#define NUMBER(name, value) int name(void *h, unsigned *out) { *out = value; return 0; }
NUMBER(nvmlDeviceGetCurrPcieLinkGeneration, 4)
NUMBER(nvmlDeviceGetCurrPcieLinkWidth, 4)
NUMBER(nvmlDeviceGetMaxPcieLinkGeneration, 4)
NUMBER(nvmlDeviceGetMaxPcieLinkWidth, 16)
NUMBER(nvmlDeviceGetEnforcedPowerLimit, 300000)
NUMBER(nvmlDeviceGetPowerManagementDefaultLimit, 450000)
NUMBER(nvmlDeviceGetPowerUsage, 150000)
int nvmlDeviceGetTemperature(void *h, unsigned sensor, unsigned *out) { *out = 61; return 0; }
int nvmlDeviceGetUtilizationRates(void *h, unsigned *out) { out[0] = 70; out[1] = 20; return 0; }
int nvmlDeviceGetMemoryInfo(void *h, uint64_t *out) { out[0] = 24ULL<<30; out[1] = 20ULL<<30; out[2] = 4ULL<<30; return 0; }
int nvmlDeviceGetCurrentClocksThrottleReasons(void *h, uint64_t *out) { *out = 4; return 0; }
int nvmlDeviceGetEccMode(void *h, unsigned *current, unsigned *pending) { *current = *pending = 1; return 0; }
int nvmlDeviceGetTotalEccErrors(void *h, unsigned type, unsigned counter, uint64_t *out) { *out = 0; return 0; }
int nvmlDeviceGetP2PStatus(void *h, void *other, unsigned cap, unsigned *status) { *status = 0; return 0; }
"""

SMI = r"""
import os, sys
from pathlib import Path
count = int(Path(os.environ["ROW43_CARDS_FILE"]).read_text())
fields = next((v.split("=", 1)[1].split(",") for v in sys.argv if v.startswith("--query-gpu=")), ["index", "name", "memory.total", "memory.free"])
for index in range(count):
    uuid = "GPU-b" if count == 1 or index == 1 else "GPU-a"
    row = {"index": str(index), "name": "Fixture RTX", "memory.total": "24576", "memory.free": "20480",
           "uuid": uuid, "driver_version": "555.0", "compute_cap": "8.6"}
    print(", ".join(row.get(field, "0") for field in fields))
"""

ENGINE = r"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
if "--version" in sys.argv:
    print("version: 11719 (fixture)"); raise SystemExit
if "--help" in sys.argv:
    print("--model --ctx-size --n-gpu-layers --fit --cache-ram --cache-reuse --cache-type-k --cache-type-v"); raise SystemExit
argv = sys.argv[1:]
def flag(name, default):
    return argv[argv.index(name) + 1] if name in argv else default
Path(os.environ["ROW43_RECORD"]).write_text(json.dumps({"argv": argv, "cuda": os.environ.get("CUDA_VISIBLE_DEVICES")}))
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {"n_ctx": int(flag("--ctx-size", 8192)), "total_slots": 1} if self.path == "/props" else {"status": "ok"}
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *_): pass
ThreadingHTTPServer(("127.0.0.1", int(flag("--port", 0))), Handler).serve_forever()
"""


def isolated_env(root: Path, port: int, source=None):
    assert port not in range(8079, 8084), "default ports are forbidden"
    env = {
        k: v
        for k, v in (os.environ if source is None else source).items()
        if not k.upper().startswith("EUGENE_PLEXUS_")
    }
    env.update(
        EUGENE_PLEXUS_AGENT_CONFIG_FILE=str(root / "agent.yaml"),
        EUGENE_PLEXUS_AGENT_BIND_HOST="127.0.0.1",
        EUGENE_PLEXUS_AGENT_BIND_PORT=str(port),
        EUGENE_PLEXUS_AGENT_MACHINE_PORT=str(free_port()),
        EUGENE_PLEXUS_AGENT_ENGINE_ROOT=str(root / "engines"),
        LD_LIBRARY_PATH=str(root) + os.pathsep + env.get("LD_LIBRARY_PATH", ""),
        PATH=str(root) + os.pathsep + env.get("PATH", ""),
        ROW43_CARDS_FILE=str(root / "cards"),
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONUNBUFFERED="1",
    )
    return env


def free_port():
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in range(8079, 8084):
            return port


def wait(predicate, label, seconds=40):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            if result := predicate():
                return result
        except (httpx.HTTPError, OSError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"Timed out: {label}")


def assert_launch(runtime, record, uuids, context, missing):
    assert runtime["status"] == "ready", runtime
    assert runtime["lastDevices"] == uuids, runtime
    assert record["cuda"].split(",") == uuids, record
    assert record["argv"][record["argv"].index("--ctx-size") + 1] == str(context), (
        record
    )
    report = runtime.get("startedOnFewerCards")
    assert ([d["uuid"] for d in report["missing"]] if report else []) == missing, (
        runtime
    )
    if report:
        assert report["missing"][0]["lastIndex"] == 0, report
        assert "16384" in " ".join(report["changes"]), report


def main():
    if not sys.platform.startswith("linux"):
        raise SystemExit("This stub-NVML acceptance runs on Linux in CI.")
    root = Path.cwd() / ".codex-tmp" / f"row43-{secrets.token_hex(6)}"
    root.mkdir(parents=True)
    print(f"Fixtures and logs: {root}", flush=True)
    (root / "cards").write_text("2")
    (root / "nvml.c").write_text(NVML)
    subprocess.run(
        [
            "cc",
            "-shared",
            "-fPIC",
            str(root / "nvml.c"),
            "-o",
            str(root / "libnvidia-ml.so.1"),
        ],
        check=True,
    )
    for name, source in (("nvidia-smi", SMI), ("llama-server", ENGINE)):
        executable = root / name
        executable.write_text(f"#!{sys.executable}\n" + source)
        executable.chmod(0o700)
    model = root / "model.gguf"
    model.write_bytes(b"GGUF-fixture")

    class Library(BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import parse_qs, urlparse

            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/v1/folders":
                self.send_error(503, "Fixture has no folder catalogue")
                return
            if url.path == "/v1/models":
                body = {
                    "models": [
                        {
                            "id": "fixture",
                            "sizeBytes": model.stat().st_size,
                            "fileCount": 1,
                            "contextLength": 32768,
                        }
                    ]
                }
            else:
                context = int(query.get("contextLength", [32768])[0])
                budget = int(query.get("vramBytes", [0])[0])
                required = (
                    36 if budget > 30 * 1024**3 else 25 if context > 16384 else 18
                ) * 1024**3
                body = {
                    "fit": {
                        "requiredBytes": required,
                        "contextLength": context,
                        "verdict": "fits" if required <= budget else "tight",
                    },
                    "maxContextLength": 16384 if required > budget else context,
                }
                with (root / "fit-queries.jsonl").open("a") as out:
                    out.write(json.dumps(query) + "\n")
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    library = ThreadingHTTPServer(("127.0.0.1", free_port()), Library)
    Thread(target=library.serve_forever, daemon=True).start()
    config = root / "agent.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "firstRunComplete": True,
                "updateChecks": False,
                "securityMode": "prompt_on_startup",
                "allowUnrestrictedEngineLaunch": True,
                "components": [
                    {
                        "name": "library",
                        "kind": "library",
                        "url": f"http://127.0.0.1:{library.server_port}",
                    }
                ],
                "runtimes": [],
            }
        )
    )
    port = free_port()
    with (root / "agent.log").open("wb") as log:
        agent = subprocess.Popen(
            [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
            cwd=root,
            env=isolated_env(root, port),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=20
            ) as client:
                wait(lambda: client.get("/healthz").is_success, "agent")
                response = client.post(
                    "/v1/auth/initialize",
                    json={"passphrase": secrets.token_urlsafe(24)},
                )
                response.raise_for_status()
                client.headers["Authorization"] = (
                    "Bearer " + response.json()["sessionToken"]
                )
                cards = client.get("/v1/node").json()["devices"][:2]
                assert [d["uuid"] for d in cards] == ["GPU-a", "GPU-b"], cards
                assert cards[0]["pcieLink"]["width"] == 4, cards
                assert cards[0]["powerLimitWatts"] == 300, cards
                assert cards[0]["peers"] == ["GPU-b"], cards
                pinned = {
                    "name": "pin",
                    "engine": "llama_cpp",
                    "modelPath": str(model),
                    "binary": str(root / "llama-server"),
                    "port": free_port(),
                    "autoDriver": False,
                    "flags": {"contextSize": 8192},
                    "env": {
                        "CUDA_VISIBLE_DEVICES": "1",
                        "ROW43_RECORD": str(root / "pin.json"),
                    },
                }
                # Its smaller budget is deliberate; this probe tests UUID argv,
                # while the spread runtime below tests the measured refit.
                response = client.post("/v1/runtimes", json=pinned)
                response.raise_for_status()
                wait(lambda: (root / "pin.json").exists(), "pinned launch")
                assert json.loads((root / "pin.json").read_text())["cuda"] == "GPU-b"
                client.post("/v1/runtimes/pin/stop", json={}).raise_for_status()
                spread = {
                    **pinned,
                    "name": "spread",
                    "port": free_port(),
                    "flags": {
                        "gpuLayers": 99,
                        "contextSize": 32768,
                        "tensorSplit": "1,1",
                    },
                    "env": {"ROW43_RECORD": str(root / "spread.json")},
                }
                client.post("/v1/runtimes", json=spread).raise_for_status()
                route = "/v1/runtimes/spread"

                def ready(uuids, context, missing):
                    runtime = client.get(route).json()
                    record = json.loads((root / "spread.json").read_text())
                    try:
                        assert_launch(runtime, record, uuids, context, missing)
                    except AssertionError:
                        return None
                    return runtime

                wait(lambda: ready(["GPU-a", "GPU-b"], 32768, []), "two-card launch")
                saved = config.read_bytes()
                (root / "cards").write_text("1")
                assert client.get("/v1/node").json()["devices"][0]["uuid"] == "GPU-b"
                client.post(route + "/restart", json={}).raise_for_status()
                reduced = wait(
                    lambda: ready(["GPU-b"], 16384, ["GPU-a"]), "refit after card loss"
                )
                assert reduced["flags"]["contextSize"] == 16384, reduced
                assert config.read_bytes() == saved
                (root / "cards").write_text("2")
                client.post(route + "/restart", json={}).raise_for_status()
                wait(lambda: ready(["GPU-a", "GPU-b"], 32768, []), "card restored")
                assert config.read_bytes() == saved
                # The same preflight runs on a crash respawn, without an HTTP start.
                resident = client.get(route).json()
                (root / "cards").write_text("1")
                os.kill(resident["pid"], signal.SIGKILL)
                wait(
                    lambda: ready(["GPU-b"], 16384, ["GPU-a"]),
                    "crash respawn card check",
                )
                assert config.read_bytes() == saved
                # Device identity survives the agent too. Boot uses the saved
                # profile and clears the warning when both cards are back.
                agent.terminate()
                agent.wait(timeout=40)
                (root / "cards").write_text("2")
                agent = subprocess.Popen(
                    [sys.executable, "-m", "eugene_plexus_agent", "--unattended"],
                    cwd=root,
                    env=isolated_env(root, port),
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                )
                wait(lambda: ready(["GPU-a", "GPU-b"], 32768, []), "boot card check")
                assert config.read_bytes() == saved
                queries = [
                    json.loads(line)
                    for line in (root / "fit-queries.jsonl").read_text().splitlines()
                ]
                assert any(q.get("gpuCount") == ["2"] for q in queries), queries
                assert any(
                    q.get("vramBytes") == [str(20 * 1024**3)] for q in queries
                ), queries
        except BaseException:
            print((root / "agent.log").read_text(errors="replace"), flush=True)
            raise
        finally:
            agent.terminate()
            agent.wait(timeout=40)
            library.shutdown()
            library.server_close()
    print(
        "PASS: readout, UUID pins, renumbering, refit, unchanged profile, and restored cards."
    )


if __name__ == "__main__":
    main()
