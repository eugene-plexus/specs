"""A4: Eugene on a Mac, on a GitHub-hosted macOS runner.

The audience roadmap's A4 takes MLX out of experimental by testing **our
integration**, not MLX: that the installer and launchd bring the agent up,
that the agent installs, launches, proves and routes `mlx_lm.server`, and
that unified memory is scored from what the machine really allows. Whether
MLX generates good tokens is upstream's (Troy, 2026-09-30).

**The runner exposes Metal.** Measured 2026-09-30 on macos-14, macos-15 and
macos-26 (arm64): MLX reports `Apple Paravirtual device`, runs a matmul on
the GPU and generates from `mlx-community/Qwen3-0.6B-4bit` at ~95 tok/s. So
this run is the real engine on a real (virtual) Apple GPU, not a stub and
not a CPU fallback. What it cannot show is listed in the acceptance record,
docs/acceptance/a4-macos-runner-run.md.

Everything is stdlib, so the harness needs no environment of its own. It
installs from the checked-out `install.sh`, whose pins say what ships; set
EP_PIN_AGENT / EP_PIN_LIBRARY / EP_PIN_GATEWAY / EP_PIN_DRIVER / EP_PIN_CONTROL
(full SHAs) to try a candidate before pinning it.

    python3 scripts/a4-macos-acceptance.py [--report a4-report.json]

It refuses to run anywhere but macOS on Apple silicon, and it installs a
launchd agent under the invoking account, so it is for a disposable
machine: a CI runner, or a rented Mac that is wiped afterwards.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
UID = os.getuid()
LABEL = "com.eugeneplexus.agent"
PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PASSPHRASE = "a4-disposable-passphrase-on-a-runner"
MLX_ENV = HOME / "eugene-mlx"

# Two MLX models: one MLX-converted (the pinned known-compatible model), one
# vanilla HF safetensors (B1's open question 2). A tiny GGUF for llama.cpp.
MLX_REPO = "mlx-community/Qwen3-0.6B-4bit"
VANILLA_REPO = "HuggingFaceTB/SmolLM2-135M-Instruct"
GGUF_REPO = "unsloth/Qwen3-0.6B-GGUF"
GGUF_QUANT = "Q4_K_M"

RESULTS: list[dict] = []
FACTS: dict[str, object] = {}


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def check(number: str, claim: str, passed: bool, detail: object = "") -> bool:
    RESULTS.append({"check": number, "claim": claim, "passed": bool(passed), "detail": str(detail)})
    mark = "PASS" if passed else "FAIL"
    tail = f"  -- {detail}" if detail not in ("", None) else ""
    print(f"  {mark}  {number}. {claim}{tail}", flush=True)
    return bool(passed)


def fact(key: str, value: object) -> None:
    FACTS[key] = value
    print(f"  FACT  {key}: {value}", flush=True)


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


class Abort(Exception):
    """A check whose failure leaves nothing after it meaningful."""


def must(number: str, claim: str, passed: bool, detail: object = "") -> None:
    if not check(number, claim, passed, detail):
        raise Abort(f"{number}: {claim}")


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #


def run(argv, *, timeout: float = 600, env=None, input_text=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, env=env, input=input_text
    )


def sh(command: str, **kw) -> subprocess.CompletedProcess:
    return run(["/bin/sh", "-c", command], **kw)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(method: str, url: str, token: str | None = None, body=None, timeout: float = 60):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        status = e.code
    except (urllib.error.URLError, OSError) as e:
        return None, str(e)
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def stream(url: str, token: str, body: dict, *, stop_after: int | None = None, timeout=120):
    """Server-sent events from a chat completion: the parsed `data:` frames."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    request.add_header("content-type", "application/json")
    request.add_header("authorization", f"Bearer {token}")
    frames: list = []
    done = False
    with _OPENER.open(request, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                done = True
                break
            try:
                frames.append(json.loads(payload))
            except ValueError:
                frames.append(payload)
            if stop_after is not None and len(frames) >= stop_after:
                break
    return frames, done


def wait_for(predicate, seconds: float, interval: float = 1.0):
    deadline = time.perf_counter() + seconds
    last = None
    while time.perf_counter() < deadline:
        try:
            last = predicate()
        except Exception as e:  # noqa: BLE001 - a probe that raised is "not yet"
            last = e
        if last and not isinstance(last, Exception):
            return last
        time.sleep(interval)
    return None


def listener_pid(port: int) -> int | None:
    out = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], timeout=20).stdout.split()
    return int(out[0]) if out else None


def ppid_of(pid: int) -> int | None:
    out = run(["ps", "-o", "ppid=", "-p", str(pid)], timeout=20).stdout.strip()
    return int(out) if out.isdigit() else None


def command_of(pid: int) -> str:
    return run(["ps", "-o", "command=", "-p", str(pid)], timeout=20).stdout.strip()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pids_matching(pattern: str) -> list[int]:
    out = run(["pgrep", "-f", pattern], timeout=20).stdout.split()
    me = os.getpid()
    return [int(p) for p in out if p.isdigit() and int(p) != me]


def vm_available() -> int | None:
    out = run(["vm_stat"], timeout=20).stdout
    size = re.search(r"page size of (\d+) bytes", out)
    page = int(size.group(1)) if size else 4096
    pages = dict(re.findall(r"^(.*?):\s+(\d+)\.?$", out, flags=re.M))
    keys = ("Pages free", "Pages inactive", "Pages speculative")
    if not all(k in pages for k in keys):
        return None
    return sum(int(pages[k]) for k in keys) * page


def metal_device() -> dict | None:
    """Metal's own answer, read here independently of the product."""
    try:
        ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        metal = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
        objc = ctypes.CDLL(ctypes.util.find_library("objc"))
    except OSError:
        return None
    metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

    def send(obj, selector: bytes, restype):
        fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p)(address)
        return fn(obj, objc.sel_registerName(selector))

    device = metal.MTLCreateSystemDefaultDevice()
    if not device:
        return None
    name = send(send(device, b"name", ctypes.c_void_p), b"UTF8String", ctypes.c_char_p)
    return {
        "name": name.decode() if name else None,
        "recommendedMaxWorkingSetSize": int(
            send(device, b"recommendedMaxWorkingSetSize", ctypes.c_uint64)
        ),
        "hasUnifiedMemory": bool(send(device, b"hasUnifiedMemory", ctypes.c_bool)),
    }


class Log:
    """The agent's log file, read from a mark so a count is about one window."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def mark(self) -> int:
        return len(self.text())

    def since(self, mark: int) -> str:
        return self.text()[mark:]

    @staticmethod
    def engine_posts(text: str, runtime: str) -> int:
        pattern = re.compile(
            rf"\[engine: {re.escape(runtime)}\] .*\"POST /v1/chat/completions HTTP/1\.1\" 200"
        )
        return len(pattern.findall(text))


# --------------------------------------------------------------------------- #
# the install
# --------------------------------------------------------------------------- #


def installer_copy(workdir: Path) -> Path:
    """install.sh as checked out, with any candidate pin substituted."""
    text = (HERE / "install.sh").read_text(encoding="utf-8")
    for name in ("AGENT", "CONTROL", "GATEWAY", "DRIVER", "LIBRARY", "TOOL_DRIVER"):
        override = os.environ.get(f"EP_PIN_{name}", "").strip()
        if override:
            if not re.fullmatch(r"[0-9a-f]{40}", override):
                raise SystemExit(f"EP_PIN_{name} must be a full 40-character SHA")
            text, count = re.subn(rf"^PIN_{name}=[0-9a-f]{{40}}", f"PIN_{name}={override}", text, flags=re.M)
            assert count == 1, name
            fact(f"candidate pin {name.lower()}", override)
    copy = workdir / "install.sh"
    copy.write_text(text, encoding="utf-8")
    return copy


def phase_rosetta_install(installer: Path, workdir: Path) -> None:
    say("Rosetta: an install started from an x86_64 shell")
    prefix = workdir / "rosetta-prefix"
    if run(["arch", "-x86_64", "/usr/bin/true"], timeout=30).returncode != 0:
        check("R1", "Rosetta is present on this machine", False, "arch -x86_64 failed")
        return
    fact("rosetta", "present")
    out = run(
        ["arch", "-x86_64", "/bin/sh", str(installer), "--prefix", str(prefix),
         "--no-service", "--no-start"],
        timeout=900,
    )
    check("R1", "install.sh completes from a Rosetta shell", out.returncode == 0,
          (out.stdout + out.stderr)[-400:] if out.returncode else "")
    python = prefix / "venv" / "bin" / "python"
    if python.exists():
        machine = run([str(python), "-c", "import platform; print(platform.machine())"]).stdout.strip()
        check("R2", "...and its Python is native arm64, not x86_64", machine == "arm64", machine)
    else:
        check("R2", "...and its Python is native arm64, not x86_64", False, "no venv python")
    shutil.rmtree(prefix, ignore_errors=True)


def phase_install(installer: Path, prefix: Path, port: int) -> dict:
    say("install.sh and launchd")
    if prefix.exists():
        shutil.rmtree(prefix)
    check("1", "the prefix does not exist before the run", not prefix.exists(), prefix)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    if port != 8079:
        env["EUGENE_PLEXUS_AGENT_BIND_PORT"] = str(port)
    started = time.perf_counter()
    out = run(["/bin/sh", str(installer), "--prefix", str(prefix)], timeout=1200, env=env)
    fact("install seconds", round(time.perf_counter() - started, 1))
    text = out.stdout + out.stderr
    must("2", "install.sh completes and says the agent is running",
         out.returncode == 0 and "Eugene Plexus is running" in text, text[-800:])

    python = prefix / "venv" / "bin" / "python"
    probe = run([str(python), "-c",
                 "import platform, sys; print(platform.machine(), sys.version.split()[0])"]).stdout.split()
    check("3", "the install's Python is native arm64 CPython 3.12",
          len(probe) == 2 and probe[0] == "arm64" and probe[1].startswith("3.12"), " ".join(probe))
    check("4", "a LaunchAgent plist was written", PLIST.is_file(), PLIST)
    printed = run(["launchctl", "print", f"gui/{UID}/{LABEL}"], timeout=30).stdout
    state = re.search(r"^\s*state = (\S+)", printed, re.M)
    job_pid = re.search(r"^\s*pid = (\d+)", printed, re.M)
    check("5", "launchd has the job loaded and running",
          bool(state) and state.group(1) == "running", state.group(1) if state else printed[:300])
    agent_pid = listener_pid(port)
    check("6", "the process listening on the agent's port is launchd's job, a child of launchd",
          agent_pid is not None and job_pid is not None and int(job_pid.group(1)) == agent_pid
          and ppid_of(agent_pid) == 1,
          f"listener={agent_pid} job={job_pid.group(1) if job_pid else None} "
          f"ppid={ppid_of(agent_pid) if agent_pid else None}")
    base = f"http://127.0.0.1:{port}"
    status, health = api("GET", f"{base}/healthz")
    check("7", "the agent answers /healthz", status == 200, health)
    status, page = api("GET", f"{base}/")
    check("8", "the UI is served at /", status == 200 and isinstance(page, str) and "<!DOCTYPE html>" in page,
          str(page)[:120])
    declared = (prefix / "agent.yaml").read_text(encoding="utf-8") if (prefix / "agent.yaml").exists() else ""
    kinds = re.findall(r"^- kind: (\S+)", declared, re.M)
    check("9", "the agent declared control, gateway and library", sorted(kinds) == ["control", "gateway", "library"],
          kinds)
    return {"base": base, "agent_pid": agent_pid, "python": python, "log": Log(prefix / "logs" / "agent.log")}


def component_url(base: str, token: str, name: str) -> str | None:
    status, body = api("GET", f"{base}/v1/components", token)
    if status != 200:
        return None
    for component in body.get("components", []):
        if component.get("name") == name:
            return (component.get("url") or "").rstrip("/")
    return None


def phase_onboard(ctx: dict) -> None:
    say("onboarding through the API, as the wizard does")
    base = ctx["base"]

    def healthy(url):
        return lambda: api("GET", f"{url}/healthz")[0] == 200

    status, _ = api("GET", f"{base}/healthz")
    control = "http://127.0.0.1:8083"
    must("10", "the control root came up", bool(wait_for(healthy(control), 120)))
    status, _ = api("POST", f"{control}/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    must("11", "control initializes", status == 204, status)
    status, body = api("POST", f"{base}/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    must("12", "the agent initializes", status == 200 and bool(body.get("sessionToken")), body)
    wait_for(healthy(control), 120)
    status, body = api("POST", f"{control}/v1/auth/login", body={"passphrase": PASSPHRASE})
    control_token = body.get("sessionToken") if status == 200 else None
    status, body = api("POST", f"{control}/v1/nodes/join-token", control_token, {"nodeName": "a4-mac"})
    join = body.get("token") if status in (200, 201) else None
    must("13", "control mints a join token", bool(join), body)
    _, login = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    status, body = api("POST", f"{base}/v1/node/enroll", login.get("sessionToken"),
                       {"controlUrl": control, "token": join, "name": "a4-mac"}, timeout=120)
    must("14", "the agent enrolls with its own control root", status == 200, body)
    for url in (base, control, "http://127.0.0.1:8080", "http://127.0.0.1:8082"):
        wait_for(healthy(url), 120)
    time.sleep(2)
    status, body = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    must("15", "a fresh session after enrollment", status == 200, body)
    ctx["token"] = body["sessionToken"]
    ctx["gateway"] = component_url(base, ctx["token"], "gateway") or "http://127.0.0.1:8080"
    ctx["library"] = component_url(base, ctx["token"], "library") or "http://127.0.0.1:8082"
    status, node = api("GET", f"{base}/v1/node", ctx["token"])
    mechanism = ((node or {}).get("install") or {}).get("mechanism") if status == 200 else None
    check("16", "the agent knows launchd is what starts it", mechanism == "launchd", mechanism)
    restart = (((node or {}).get("reach") or {}).get("restart") or {}) if status == 200 else {}
    check("17", "...and says it can restart itself through launchd",
          restart.get("mechanism") == "launchd" and restart.get("canSelfRestart") is True
          and f"gui/{UID}/{LABEL}" in (restart.get("command") or ""), restart)
    ctx["node"] = node

    # What the wizard's first screen does: the keyring where this host has
    # one (S0), written to both, then the sign-in that also unlocks the root.
    _, auth = api("GET", f"{base}/v1/auth/status")
    keyring = bool((auth or {}).get("keyringAvailable"))
    fact("keyring available to the launchd agent", keyring)
    _, clogin = api("POST", f"{control}/v1/auth/login", body={"passphrase": PASSPHRASE})
    ctoken = (clogin or {}).get("sessionToken")
    if keyring:
        a, _ = api("PATCH", f"{base}/v1/config", ctx["token"], {"securityMode": "os_keyring"})
        c, _ = api("PATCH", f"{control}/v1/config", ctoken, {"securityMode": "os_keyring"})
        check("17b", "the keyring is chosen on both, as the wizard chooses it", a == 200 and c == 200,
              f"agent={a} control={c}")
        api("POST", f"{control}/v1/auth/login", body={"passphrase": PASSPHRASE})
    _, cstatus = api("GET", f"{control}/v1/auth/status")
    check("17c", "the control root is unlocked after sign-in", (cstatus or {}).get("unlocked") is True, cstatus)
    ctx["keyring"], ctx["control"] = keyring, control


# --------------------------------------------------------------------------- #
# unified memory
# --------------------------------------------------------------------------- #


def phase_unified_memory(ctx: dict) -> None:
    say("unified memory: what the machine allows, and what we report")
    metal = metal_device()
    ram = int(run(["sysctl", "-n", "hw.memsize"]).stdout.strip() or 0)
    fact("hw.memsize", ram)
    fact("metal (read by this harness)", metal)
    fact("iogpu.wired_limit_mb", run(["sysctl", "-n", "iogpu.wired_limit_mb"]).stdout.strip())
    if metal:
        fact("metal working set / RAM", round(metal["recommendedMaxWorkingSetSize"] / ram, 4))
    ctx["metal"] = metal
    devices = (ctx.get("node") or {}).get("devices") or []
    gpu = next((d for d in devices if d.get("kind") == "metal"), None)
    fact("agent metal device", gpu)
    check("18", "the agent reports a Metal device with shared memory",
          bool(gpu) and gpu.get("sharedMemory") is True, gpu)
    want = metal["recommendedMaxWorkingSetSize"] if metal else None
    check("19", "its budget is Metal's recommendedMaxWorkingSetSize, not a fixed share of RAM",
          bool(gpu) and want is not None and gpu.get("memoryTotalBytes") == want,
          f"agent={gpu.get('memoryTotalBytes') if gpu else None} metal={want}")
    check("20", "it is named for the device, not for platform.processor() ('arm')",
          bool(gpu) and gpu.get("name") not in (None, "", "arm"), gpu.get("name") if gpu else None)
    status, hardware = api("GET", f"{ctx['library']}/v1/hardware", ctx["token"])
    fact("library hardware", hardware)
    gpus = (hardware or {}).get("gpus") or [] if status == 200 else []
    check("21", "the library sees unified memory on this Mac",
          status == 200 and hardware.get("unifiedMemory") is True, status)
    check("22", "...and scores against the same Metal budget",
          len(gpus) == 1 and want is not None and gpus[0].get("vramTotalBytes") == want,
          f"library={gpus[0].get('vramTotalBytes') if gpus else None} metal={want}")


# --------------------------------------------------------------------------- #
# the MLX engine
# --------------------------------------------------------------------------- #


def engine(ctx: dict, name: str) -> dict:
    status, body = api("GET", f"{ctx['base']}/v1/engines", ctx["token"], timeout=120)
    if status != 200:
        return {}
    return next((e for e in body.get("engines", []) if e.get("engine") == name), {})


def phase_mlx_install(ctx: dict) -> None:
    say("installing MLX the way the agent tells the person to")
    if MLX_ENV.exists():
        shutil.rmtree(MLX_ENV)
    mlx = engine(ctx, "mlx")
    acquisition = mlx.get("acquisition") or {}
    manual = acquisition.get("manualInstall") or {}
    check("23", "the agent lists MLX as experimental, manual, not yet available",
          mlx.get("experimental") is True and acquisition.get("policy") == "manual"
          and mlx.get("available") is False, {k: mlx.get(k) for k in ("experimental", "available")})
    command = manual.get("command")
    fact("mlx install command", command)
    must("24", "on Apple silicon it offers a command", bool(command), manual)

    # Rosetta first, into a scratch HOME so `~` lands elsewhere: the recipe
    # must not be able to build an x86_64 environment from a Rosetta shell.
    scratch = Path(tempfile.mkdtemp(prefix="a4-rosetta-home-"))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env["HOME"] = str(scratch)
    out = run(["arch", "-x86_64", "/bin/sh", "-c", command], timeout=900, env=env)
    rosetta_python = scratch / "eugene-mlx" / "bin" / "python"
    machine = (run([str(rosetta_python), "-c", "import platform; print(platform.machine())"]).stdout.strip()
               if rosetta_python.exists() else f"(no env; exit {out.returncode}: {(out.stdout + out.stderr)[-300:]})")
    check("25", "the command, run verbatim from a Rosetta shell, still builds a native arm64 environment",
          machine == "arm64", machine)
    shutil.rmtree(scratch, ignore_errors=True)

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    started = time.perf_counter()
    out = run(["/bin/sh", "-c", command], timeout=900, env=env)
    fact("mlx install seconds", round(time.perf_counter() - started, 1))
    server = MLX_ENV / "bin" / "mlx_lm.server"
    must("26", "the command, run verbatim in the person's own shell, installs mlx_lm.server",
         out.returncode == 0 and server.exists(), (out.stdout + out.stderr)[-600:])
    info = run([str(MLX_ENV / "bin" / "python"), "-c",
                "import json, platform, importlib.metadata as m, mlx.core as mx; "
                "print(json.dumps({'machine': platform.machine(), 'mlx_lm': m.version('mlx-lm'), "
                "'mlx': m.version('mlx'), 'metal': mx.metal.is_available(), "
                "'device_info': mx.device_info()}))"]).stdout
    try:
        info = json.loads(info)
    except ValueError:
        info = {}
    fact("mlx environment", info)
    check("27", "the environment is native arm64 with the pinned mlx-lm, and MLX sees Metal",
          info.get("machine") == "arm64" and info.get("mlx_lm") == "0.31.3" and info.get("metal") is True, info)
    metal = ctx.get("metal") or {}
    check("28", "MLX's own working-set figure agrees with the one the agent reports",
          (info.get("device_info") or {}).get("max_recommended_working_set_size")
          == metal.get("recommendedMaxWorkingSetSize"), info.get("device_info"))

    status, body = api("PATCH", f"{ctx['base']}/v1/config", ctx["token"],
                       {"mlxBinary": "~/eugene-mlx/bin/mlx_lm.server"})
    check("29", "mlxBinary is set as the notes say, with a ~", status == 200, body if status != 200 else "")
    mlx = engine(ctx, "mlx")
    python = mlx.get("python") or {}
    check("30", "the agent now finds MLX, reads its version and names the environment's interpreter",
          mlx.get("available") is True and mlx.get("version") == "0.31.3"
          and str(MLX_ENV) in (python.get("interpreter") or ""),
          {k: mlx.get(k) for k in ("available", "version", "binaryPath", "error")} | {"python": python})

    flags = json.loads(run([str(ctx["python"]), "-c",
                            "import json; from eugene_plexus_agent.engines.mlx import _FLAG_CLI_NAMES as f; "
                            "print(json.dumps(f))"]).stdout or "{}")
    helptext = run([str(server), "--help"]).stdout
    missing = [cli for cli in flags.values() if cli not in helptext]
    check("31", "every curated flag the agent can render is an mlx_lm.server option",
          bool(flags) and not missing, missing or f"{len(flags)} flags")
    check("32", "mlx_lm.server has no --served-model-name (why upstreamModelId exists)",
          "--served-model-name" not in helptext and "--model" in helptext)


def library_model(ctx: dict, repo: str, pick=None) -> dict | None:
    """Download `repo` through the library, as Discover does; return the model entry."""
    status, detail = api("GET", f"{ctx['library']}/v1/catalogue/model?repo={repo}", ctx["token"], timeout=120)
    if status != 200:
        return {"harnessError": f"catalogue {status}: {str(detail)[:300]}"}
    candidates = detail.get("candidates") or []
    candidate = pick(candidates) if pick else (candidates[0] if candidates else None)
    if not candidate:
        return {"harnessError": f"no candidate in {[c.get('label') for c in candidates]}"}
    # Exactly the candidate's files, as Discover sends them: a safetensors
    # candidate must carry its own sidecars or the model will not load.
    files = [f.get("path") if isinstance(f, dict) else f for f in candidate.get("files") or []]
    status, record = api("POST", f"{ctx['library']}/v1/downloads", ctx["token"], {"repo": repo, "files": files})
    if status not in (200, 201, 202):
        return {"harnessError": f"download {status}: {str(record)[:300]}"}
    download = record["id"]

    def finished():
        _, current = api("GET", f"{ctx['library']}/v1/downloads/{download}", ctx["token"])
        state = (current or {}).get("state")
        return current if state in ("done", "failed", "cancelled") and (
            state != "done" or current.get("modelId")) else None

    record = wait_for(finished, 900, 2)
    if not record or record.get("state") != "done":
        return {"harnessError": f"download ended {record}"}
    status, model = api("GET", f"{ctx['library']}/v1/models/{record['modelId']}", ctx["token"])
    return model if status == 200 else {"harnessError": f"model {status}: {model}"}


def phase_models(ctx: dict) -> None:
    say("models through the library")
    root = HOME / "Eugene Models"
    status, body = api("PATCH", f"{ctx['library']}/v1/config", ctx["token"], {"modelRoots": [str(root)]})
    must("33", "the library takes a models folder", status == 200, body if status != 200 else "")
    started = time.perf_counter()
    qwen = library_model(ctx, MLX_REPO)
    fact("download seconds (mlx model)", round(time.perf_counter() - started, 1))
    must("34", f"{MLX_REPO} downloads through the library", bool(qwen) and "harnessError" not in qwen, qwen.get("harnessError") or qwen.get("path"))
    detail = qwen.get("safetensors") or {}
    check("35", "it is catalogued as safetensors with the MLX quantization marker",
          qwen.get("format") == "safetensors" and bool(detail.get("mlxQuantization")),
          {"format": qwen.get("format"), "mlxQuantization": detail.get("mlxQuantization")})
    smol = library_model(ctx, VANILLA_REPO)
    must("36", f"{VANILLA_REPO} (vanilla, not converted) downloads through the library",
         bool(smol) and "harnessError" not in smol, smol.get("harnessError") or smol.get("path"))
    check("37", "...and carries no MLX marker", not (smol.get("safetensors") or {}).get("mlxQuantization"),
          (smol.get("safetensors") or {}).get("mlxQuantization"))
    ctx["qwen"], ctx["smol"] = qwen, smol


def phase_upstream_claims(ctx: dict) -> None:
    """The v0.31.3 claims the adapter is built on, against the real server."""
    say("the upstream claims the adapter rests on (mlx_lm.server alone)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    started = time.perf_counter()
    proc = subprocess.Popen(
        [str(MLX_ENV / "bin" / "mlx_lm.server"), "--model", ctx["qwen"]["path"],
         "--host", "127.0.0.1", "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT,
    )
    first_health = first_token = None
    health_only = 0
    try:
        while time.perf_counter() - started < 180 and first_token is None:
            status, _ = api("GET", f"{base}/health", timeout=1)
            if status == 200:
                first_health = first_health or time.perf_counter() - started
                status, body = api("POST", f"{base}/v1/chat/completions", body={
                    "model": "default_model", "max_tokens": 1, "temperature": 0,
                    "messages": [{"role": "user", "content": "ok"}]}, timeout=0.3)
                if status == 200:
                    first_token = time.perf_counter() - started
                    ctx["raw_completion"] = body
                else:
                    health_only += 1
            time.sleep(0.02)
        fact("raw server: first /health, first token (s)",
             (round(first_health or -1, 2), round(first_token or -1, 2)))
        check("38", "mlx_lm.server answers /health before it can generate (why readiness asks for a token)",
              first_health is not None and first_token is not None and health_only >= 1,
              f"{health_only} polls with /health ok and no token")
        status, models = api("GET", f"{base}/v1/models")
        fact("raw /v1/models", (status, models))
        ids = [m.get("id") for m in (models or {}).get("data", [])] if isinstance(models, dict) else []
        log.flush()
        if status != 200 or not ids:
            fact("raw server log tail", Path(log.name).read_text(errors="replace")[-1500:])
        # Recorded, not required: nothing of ours reads this list, which is
        # the point -- whatever it says is not a name we chose.
        check("39", "its model list offers no name we chose, so nothing may route by it",
              "a4-public-alias" not in ids and "qwen3-0.6b-mlx" not in ids, f"status={status} ids={ids}")
        body = ctx.get("raw_completion") or {}
        check("40", "`default_model` resolves to --model, and nothing in the answer states a context length",
              body.get("model") == "default_model"
              and not re.search(r"context|n_ctx|max_model_len", json.dumps(body)), body)
        status, _ = api("POST", f"{base}/v1/chat/completions", body={
            "model": "a4-public-alias", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]})
        log.flush()
        hub = "api/models/a4-public-alias" in Path(log.name).read_text(errors="replace")
        check("41", "any other model id sends mlx_lm.server to the Hub (so the alias must never reach it)",
              status != 200 and hub, f"status={status} hub_fetch={hub}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


# --------------------------------------------------------------------------- #
# runtimes through the product
# --------------------------------------------------------------------------- #


def runtime(ctx: dict, name: str) -> dict:
    status, body = api("GET", f"{ctx['base']}/v1/runtimes/{name}", ctx["token"])
    return body if status == 200 else {}


def wait_status(ctx: dict, name: str, wanted: str, seconds: float) -> dict:
    return wait_for(lambda: (lambda r: r if r.get("status") == wanted else None)(runtime(ctx, name)),
                    seconds, 1) or runtime(ctx, name)


def gateway_models(ctx: dict) -> list[str]:
    status, body = api("GET", f"{ctx['gateway']}/v1/models", ctx["token"])
    return [m.get("id") for m in (body or {}).get("data", [])] if status == 200 else []


def complete(ctx: dict, alias: str, prompt: str = "Reply with one word: ok", tokens: int = 12):
    return api("POST", f"{ctx['gateway']}/v1/chat/completions", ctx["token"], {
        "model": alias, "max_tokens": tokens, "temperature": 0,
        "messages": [{"role": "user", "content": prompt}]}, timeout=180)


def phase_runtimes(ctx: dict) -> None:
    say("MLX runtimes, launched, proved and routed by the product")
    log: Log = ctx["log"]
    qwen_alias, smol_alias = "qwen3-0.6b-mlx", "smollm2-135m-mlx"
    spec = {"name": "qwen-mlx", "engine": "mlx", "modelPath": ctx["qwen"]["path"],
            "modelAlias": qwen_alias, "autoStart": True}
    status, admission = api("POST", f"{ctx['base']}/v1/runtimes/admission", ctx["token"], spec, timeout=120)
    fact("admission (mlx, qwen)", admission)
    check("42", "admission answers for an MLX runtime on the Metal device and does not refuse",
          status == 200 and admission.get("decision") != "refuse"
          and (admission.get("device") or {}).get("kind") == "metal", admission)

    mark = log.mark()
    started = time.perf_counter()
    status, body = api("POST", f"{ctx['base']}/v1/runtimes", ctx["token"], spec, timeout=120)
    must("43", "the runtime is declared", status in (200, 201), body)
    qwen = wait_status(ctx, "qwen-mlx", "ready", 240)
    fact("seconds to ready (qwen-mlx)", round(time.perf_counter() - started, 1))
    must("44", "it reaches ready", qwen.get("status") == "ready",
         {k: qwen.get(k) for k in ("status", "lastError", "argv")})
    binary = str(MLX_ENV / "bin" / "mlx_lm.server")
    expected = [binary, "--model", ctx["qwen"]["path"], "--host", "127.0.0.1", "--port", str(qwen.get("port"))]
    check("45", "the agent launched exactly `mlx_lm.server --model <path> --host --port`",
          qwen.get("argv") == expected, qwen.get("argv"))
    pid = qwen.get("pid")
    live = command_of(pid) if pid else ""
    # ps shows the console script's interpreter first (its shebang), then
    # the argv the agent built.
    check("46", "...and that is the command line of the live process",
          bool(pid) and live.endswith(" ".join(expected)), live)
    at_ready = Log.engine_posts(log.since(mark), "qwen-mlx")
    check("47", "readiness was proved with exactly one generated token", at_ready == 1, f"{at_ready} completions")
    time.sleep(20)
    later = Log.engine_posts(log.since(mark), "qwen-mlx")
    check("48", "...and never again while it stays up (20 s of polls later)", later == 1, f"{later} completions")
    check("49", "an MLX runtime reports no context length (MLX publishes none)",
          not ((qwen.get("capabilities") or {}).get("maxContextTokens")), qwen.get("capabilities"))

    ready_models = wait_for(lambda: (lambda ids: ids if qwen_alias in ids else None)(gateway_models(ctx)), 90, 2)
    ids = ready_models or gateway_models(ctx)
    check("50", "the gateway lists the public alias, and neither the sentinel nor a path",
          qwen_alias in ids and "default_model" not in ids and not any(str(i).startswith("/") for i in ids), ids)
    mark = log.mark()
    status, body = complete(ctx, qwen_alias)
    served = ((body or {}).get("x_eugene_plexus") or {}) if status == 200 else {}
    check("51", "a completion through the gateway answers under the alias, served by this runtime",
          status == 200 and body.get("model") == qwen_alias and served.get("runtime") == "qwen-mlx"
          and bool(((body.get("choices") or [{}])[0].get("message") or {}).get("content")),
          body if status != 200 else {"model": body.get("model"), "runtime": served.get("runtime")})
    frames, done = stream(f"{ctx['gateway']}/v1/chat/completions", ctx["token"], {
        "model": qwen_alias, "stream": True, "max_tokens": 48, "temperature": 0,
        "messages": [{"role": "user", "content": "Count to five."}]})
    # Qwen3 thinks first, and its thinking streams as reasoning, not content.
    content = [f for f in frames if isinstance(f, dict) and any(
        ((f.get("choices") or [{}])[0].get("delta") or {}).get(k)
        for k in ("content", "reasoning_content", "reasoning"))]
    models = {f.get("model") for f in frames if isinstance(f, dict) and f.get("model")}
    check("52", "a streamed completion arrives as many frames, every one under the alias, then [DONE]",
          len(content) >= 2 and models == {qwen_alias} and done, f"{len(content)} content frames, models={models}")
    hub = re.search(rf"\[engine: qwen-mlx\].*api/models/{re.escape(qwen_alias)}", log.since(mark))
    check("53", "the engine never saw the alias (no Hub lookup for it)", not hub, hub.group(0) if hub else "")

    # A vanilla model, with the curated flags a person could set.
    flags = {"maxTokens": 256, "promptCacheSize": 4, "promptCacheBytes": "512MB", "decodeConcurrency": 4,
             "promptConcurrency": 2, "prefillStepSize": 512, "trustRemoteCode": True,
             "draftModel": ctx["smol"]["path"], "numDraftTokens": 2}
    smol_spec = {"name": "smol-mlx", "engine": "mlx", "modelPath": ctx["smol"]["path"],
                 "modelAlias": smol_alias, "autoStart": True, "flags": flags}
    status, body = api("POST", f"{ctx['base']}/v1/runtimes", ctx["token"], smol_spec, timeout=120)
    smol = wait_status(ctx, "smol-mlx", "ready", 240) if status in (200, 201) else {}
    check("54", "a vanilla HF safetensors model reaches ready under MLX, with nine curated flags set",
          smol.get("status") == "ready", {k: smol.get(k) for k in ("status", "lastError")} or body)
    argv = " ".join(smol.get("argv") or [])
    rendered = ["--max-tokens 256", "--prompt-cache-size 4", "--prompt-cache-bytes 512MB",
                "--decode-concurrency 4", "--prompt-concurrency 2", "--prefill-step-size 512",
                "--trust-remote-code", "--draft-model", "--num-draft-tokens 2"]
    check("55", "...each rendered on its command line as upstream spells it",
          all(r in argv for r in rendered), [r for r in rendered if r not in argv])

    wait_for(lambda: smol_alias in gateway_models(ctx), 90, 2)
    mark = log.mark()
    answers = [complete(ctx, qwen_alias)[0] for _ in range(3)] + [complete(ctx, smol_alias)[0] for _ in range(2)]
    window = log.since(mark)
    counts = (Log.engine_posts(window, "qwen-mlx"), Log.engine_posts(window, "smol-mlx"))
    check("56", "two MLX runtimes behind one sentinel are two models: each alias reaches only its own engine",
          answers == [200] * 5 and counts == (3, 2), f"statuses={answers} engine posts (qwen, smol)={counts}")

    # Cancellation: close a long stream early; the gateway must let go of it.
    try:
        stream(f"{ctx['gateway']}/v1/chat/completions", ctx["token"], {
            "model": qwen_alias, "stream": True, "max_tokens": 1500,
            "messages": [{"role": "user", "content": "Count from 1 to 1000, one number per line."}]},
            stop_after=3)
    except Exception as e:  # noqa: BLE001
        fact("cancel stream error", e)

    def idle():
        status, table = api("GET", f"{ctx['gateway']}/v1/admin/routing", ctx["token"])
        backends = [b for s in (table or {}).get("slots", []) for t in s.get("tiers", [])
                    for b in t.get("backends", []) if b.get("runtime") == "qwen-mlx"]
        return backends and all((b.get("in_flight") or 0) == 0 for b in backends)

    check("57", "a stream the caller closed early leaves nothing in flight", bool(wait_for(idle, 20, 1)))
    status, _ = complete(ctx, qwen_alias)
    check("58", "...and the next request is served", status == 200, status)

    # Stop, start, and the agent's own restart under launchd.
    before = vm_available()
    old_pid = runtime(ctx, "qwen-mlx").get("pid")
    status, _ = api("POST", f"{ctx['base']}/v1/runtimes/qwen-mlx/stop", ctx["token"], {}, timeout=120)
    stopped = wait_status(ctx, "qwen-mlx", "stopped", 60)
    gone = wait_for(lambda: not alive(old_pid), 30, 1) if old_pid else None
    time.sleep(3)
    after = vm_available()
    fact("vm available bytes: running, after stop", (before, after))
    check("59", "stop ends the engine process", stopped.get("status") == "stopped" and bool(gone),
          {"status": stopped.get("status"), "pid": old_pid})
    mark = log.mark()
    api("POST", f"{ctx['base']}/v1/runtimes/qwen-mlx/start", ctx["token"], {}, timeout=120)
    restarted = wait_status(ctx, "qwen-mlx", "ready", 240)
    posts = Log.engine_posts(log.since(mark), "qwen-mlx")
    check("60", "start brings it back, and the new process pays its one proving token again",
          restarted.get("status") == "ready" and restarted.get("pid") != old_pid and posts == 1,
          f"status={restarted.get('status')} completions={posts}")

    engines_before = sorted(pids_matching("mlx_lm.server"))
    agent_before = ctx["agent_pid"]
    mark = log.mark()
    out = run(["launchctl", "kickstart", "-k", f"gui/{UID}/{LABEL}"], timeout=60)
    new_agent = wait_for(lambda: (lambda p: p if p and p != agent_before else None)(
        listener_pid(int(ctx["base"].rsplit(":", 1)[1]))), 60, 1)
    check("61", "`launchctl kickstart -k` restarts the agent under launchd",
          out.returncode == 0 and bool(new_agent) and ppid_of(new_agent) == 1,
          f"old={agent_before} new={new_agent} rc={out.returncode} {out.stderr.strip()}")
    ctx["agent_pid"] = new_agent or agent_before
    wait_for(lambda: api("GET", f"{ctx['base']}/healthz")[0] == 200, 120)
    # Nobody signs in: this is the restart nobody is watching.
    control = ctx["control"]
    wait_for(lambda: api("GET", f"{control}/healthz")[0] == 200, 120)
    _, cstatus = api("GET", f"{control}/v1/auth/status")
    unlocked = (cstatus or {}).get("unlocked")
    fact("control root after an unattended restart", cstatus)
    if ctx.get("keyring"):
        check("61b", "with the keyring chosen, the root comes back unlocked with nobody signing in",
              unlocked is True, cstatus)
    else:
        check("61b", "with no keyring, the root comes back sealed and says so", unlocked is False, cstatus)
    _, login = api("POST", f"{ctx['base']}/v1/auth/login", body={"passphrase": PASSPHRASE})
    ctx["token"] = (login or {}).get("sessionToken", ctx["token"])
    back = [wait_status(ctx, n, "ready", 300).get("status") for n in ("qwen-mlx", "smol-mlx")]
    window = log.since(mark)
    proofs = (Log.engine_posts(window, "qwen-mlx"), Log.engine_posts(window, "smol-mlx"))
    orphans = [p for p in engines_before if alive(p)]
    check("62", "both MLX runtimes come back after the agent restart, each proved once, none orphaned",
          back == ["ready", "ready"] and proofs == (1, 1) and not orphans,
          f"status={back} proofs={proofs} orphans={orphans}")
    wait_for(lambda: qwen_alias in gateway_models(ctx), 120, 2)
    status, _ = complete(ctx, qwen_alias)
    check("63", "...and the gateway serves the alias again", status == 200, status)
    for name in ("qwen-mlx", "smol-mlx"):
        api("POST", f"{ctx['base']}/v1/runtimes/{name}/stop", ctx["token"], {}, timeout=120)


# --------------------------------------------------------------------------- #
# llama.cpp on Metal, the other engine a Mac runs
# --------------------------------------------------------------------------- #


def phase_llama_cpp(ctx: dict) -> None:
    say("llama.cpp's macOS build, installed and run by the agent")
    llama = engine(ctx, "llama_cpp")
    acquisition = llama.get("acquisition") or {}
    check("64", "llama.cpp is installable here, as the macOS arm64 build",
          acquisition.get("installable") is True and "macos-arm64" in (acquisition.get("variant") or ""),
          {k: acquisition.get(k) for k in ("installable", "variant", "reason", "latestVersion")})
    status, body = api("POST", f"{ctx['base']}/v1/engines/llama_cpp/install", ctx["token"], {}, timeout=900)
    llama = wait_for(lambda: (lambda e: e if e.get("available") else None)(engine(ctx, "llama_cpp")), 600, 5) or {}
    must("65", "the agent installs it", llama.get("available") is True,
         {"install": status, "engine": {k: llama.get(k) for k in ("available", "version", "error")}})
    binary = Path(llama.get("binaryPath") or "")
    devices = run([str(binary), "--list-devices"], timeout=60)
    listed = devices.stdout + devices.stderr
    fact("llama-server --list-devices", listed.strip()[-400:])
    check("66", "the installed build lists the Metal device", "MTL" in listed or "Metal" in listed, "")
    gguf = library_model(ctx, GGUF_REPO, pick=lambda cs: next(
        (c for c in cs if GGUF_QUANT in (c.get("label") or "") and c.get("format") == "gguf"), None))
    must("67", f"{GGUF_REPO} {GGUF_QUANT} downloads through the library", bool(gguf) and "harnessError" not in gguf, gguf.get("harnessError") or gguf.get("path"))
    spec = {"name": "qwen-gguf", "engine": "llama_cpp", "modelPath": gguf["path"],
            "modelAlias": "qwen3-0.6b-gguf", "autoStart": True}
    status, body = api("POST", f"{ctx['base']}/v1/runtimes", ctx["token"], spec, timeout=120)
    ready = wait_status(ctx, "qwen-gguf", "ready", 240) if status in (200, 201) else {}
    check("68", "a llama.cpp runtime reaches ready on this Mac", ready.get("status") == "ready",
          {k: ready.get(k) for k in ("status", "lastError")} or body)
    wait_for(lambda: "qwen3-0.6b-gguf" in gateway_models(ctx), 90, 2)
    status, reply = complete(ctx, "qwen3-0.6b-gguf")
    check("69", "...and answers through the gateway", status == 200, reply if status != 200 else "")
    offload = (ready.get("flags") or {}).get("gpuLayers")
    fact("llama.cpp runtime flags", ready.get("flags"))
    api("POST", f"{ctx['base']}/v1/runtimes/qwen-gguf/stop", ctx["token"], {}, timeout=120)
    del offload


# --------------------------------------------------------------------------- #
# leaving
# --------------------------------------------------------------------------- #


def phase_uninstall(installer: Path, prefix: Path) -> None:
    say("uninstall")
    engines_before = pids_matching("mlx_lm.server") + pids_matching("llama-server")
    out = run(["/bin/sh", str(installer), "--prefix", str(prefix), "--uninstall"], timeout=300)
    kept = re.search(rf"{re.escape(str(prefix))}\.removed-\d+", out.stdout + out.stderr)
    check("70", "--uninstall removes the LaunchAgent and keeps the config",
          out.returncode == 0 and not PLIST.exists() and bool(kept) and (Path(kept.group(0)) / "agent.yaml").exists(),
          (out.stdout + out.stderr)[-300:])
    time.sleep(3)
    left = [p for p in pids_matching(str(prefix)) + engines_before if alive(p)]
    check("71", "nothing it started is still running, engines included", not left,
          [command_of(p)[:120] for p in left])
    loaded = run(["launchctl", "print", f"gui/{UID}/{LABEL}"], timeout=30).returncode == 0
    check("72", "launchd no longer knows the job", not loaded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", type=Path, default=HOME / "ep-a4")
    parser.add_argument("--port", type=int, default=8079)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--skip-llama", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        print("this run is for macOS on Apple silicon (a disposable one)", file=sys.stderr)
        return 2

    fact("macOS", run(["sw_vers", "-productVersion"]).stdout.strip())
    fact("chip", run(["sysctl", "-n", "machdep.cpu.brand_string"]).stdout.strip())
    fact("virtual machine", run(["sysctl", "-n", "kern.hv_vmm_present"]).stdout.strip() == "1")
    workdir = Path(tempfile.mkdtemp(prefix="a4-"))
    installer = installer_copy(workdir)
    ctx: dict = {}
    try:
        phase_rosetta_install(installer, workdir)
        ctx = phase_install(installer, args.prefix, args.port)
        phase_onboard(ctx)
        phase_unified_memory(ctx)
        phase_mlx_install(ctx)
        phase_models(ctx)
        phase_upstream_claims(ctx)
        phase_runtimes(ctx)
        if not args.skip_llama:
            phase_llama_cpp(ctx)
    except Abort as e:
        print(f"\n  ABORT  {e}", flush=True)
    except Exception:  # noqa: BLE001 - the report must still be written
        check("X", "the harness itself ran to the end", False, traceback.format_exc()[-1500:])
    finally:
        if ctx and ctx.get("log"):
            keep = (args.report.parent if args.report else workdir) / "agent-log-tail.txt"
            keep.write_text(ctx["log"].text()[-60000:], encoding="utf-8")
            print(f"\n(agent log tail kept at {keep})")
        try:
            phase_uninstall(installer, args.prefix)
        except Exception:  # noqa: BLE001
            check("X2", "uninstall ran", False, traceback.format_exc()[-800:])

    failed = [r for r in RESULTS if not r["passed"]]
    say("result")
    print(f"  {len(RESULTS)} checks, {len(failed)} failures")
    if args.report:
        args.report.write_text(json.dumps({"facts": FACTS, "checks": RESULTS}, indent=2, default=str),
                               encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"## A4 on {FACTS.get('chip')} / macOS {FACTS.get('macOS')}\n\n")
            out.write(f"**{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed.**\n\n")
            out.write("| # | Claim | Result |\n|---|---|---|\n")
            for r in RESULTS:
                out.write(f"| {r['check']} | {r['claim']} | {'PASS' if r['passed'] else 'FAIL: ' + r['detail'][:160].replace('|', '/')} |\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
