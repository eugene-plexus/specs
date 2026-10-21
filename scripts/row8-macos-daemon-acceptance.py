"""Row 8: Eugene on a Mac as a LaunchDaemon in its own account.

Design: docs/design/rows/row-08.md, section 5. Runs on a GitHub-hosted macOS
runner, as the runner account, which has passwordless sudo. It installs for
real from the checked-out `install.sh` (its pins say what ships; EP_PIN_*
substitutes a candidate, as A4 does), so it is for a disposable machine: a
CI runner, or a rented Mac that is wiped afterwards.

Two phases.

**A, a fresh install** (the default on a Mac since row 8):
 1. `_eugeneplexus` exists, is hidden, has no login shell and no password,
    and is in `staff`
 2. the daemon plist is root:wheel 0644, lints, and names `_eugeneplexus`;
    there is no LaunchAgent
 3. launchd runs it; the agent's uid is the account's (never 0, never the
    runner's); its parent is pid 1
 4. the runner cannot read node.yaml, agent.yaml or the passphrase file
 5. health answers; nothing of the run listens on 8079-8083 (this harness
    holds them, so the install must walk off them)
 6. onboarding: agent and control use passphrase_file; the file is 0400 and
    the account's
 7. Reach says launchd, "starts at boot", can restart
 8. the runner's Keychain locked, then `sudo launchctl kickstart -k`: the
    root comes back unlocked with nobody signing in
 9. Reach's own restart gives a new pid under launchd within 30 s
10. in the daemon the agent reports Metal; a GGUF downloaded through the
    Library lands in ~/Eugene Models and answers through the gateway
13. --user beside the daemon is refused
14. uninstall: plist gone, job unknown to launchd, no process left, account
    and group removed, config kept as root's

**B, the move from a LaunchAgent install** (`--user`, onboarded with the
Keychain where this runner has one, enrolled):
12. a `launchctl` stand-in that fails `bootstrap system`: the LaunchAgent
    serves again from the old prefix, and the message holds launchctl's words
11. the real move: words first; node name, key and port unchanged; Library
    state kept; the old prefix moved aside; sealed until one sign-in; then a
    kickstart unlocks by itself
14b. uninstall again

Not here (row-08.md section 5): a reboot and a sign-in on a real Mac,
bare-metal Metal, and macOS privacy prompts, which runner images may
pre-grant.

    python3 scripts/row8-macos-daemon-acceptance.py [--report row8-report.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
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
ME = os.environ.get("USER") or subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
LABEL = "com.eugeneplexus.agent"
ACCOUNT = "_eugeneplexus"
PREFIX = Path("/usr/local/eugene-plexus")
DAEMON = Path("/Library/LaunchDaemons") / f"{LABEL}.plist"
RECEIPTS = Path("/usr/local/lib/eugene-plexus")
AGENT_PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
USER_PREFIX = HOME / ".local" / "share" / "eugene-plexus"
MODELS = HOME / "Eugene Models"
PORT = 18279
HELD = range(8079, 8084)
PASSPHRASE = "row8-disposable-passphrase-on-a-runner"
GGUF_REPO = "unsloth/Qwen3-0.6B-GGUF"
GGUF_QUANT = "Q4_K_M"

RESULTS: list[dict] = []
FACTS: dict[str, object] = {}


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def check(number: str, claim: str, passed: bool, detail: object = "") -> bool:
    RESULTS.append({"check": number, "claim": claim, "passed": bool(passed), "detail": str(detail)})
    tail = f"  -- {detail}" if detail not in ("", None) else ""
    print(f"  {'PASS' if passed else 'FAIL'}  {number}. {claim}{tail}", flush=True)
    return bool(passed)


def skip(number: str, claim: str, reason: str) -> None:
    RESULTS.append({"check": number, "claim": claim, "passed": None, "detail": reason})
    print(f"  SKIP  {number}. {claim}  -- {reason}", flush=True)


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
        [str(a) for a in argv], capture_output=True, text=True, timeout=timeout, env=env,
        input=input_text,
    )


def sudo(*argv, timeout: float = 120) -> subprocess.CompletedProcess:
    return run(["sudo", "-n", *argv], timeout=timeout)


def as_account(*argv, timeout: float = 120) -> subprocess.CompletedProcess:
    return run(["sudo", "-n", "-u", ACCOUNT, *argv], timeout=timeout)


def clean_env(**extra: str) -> dict[str, str]:
    """This environment without a single EUGENE_PLEXUS_* variable, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env.update(extra)
    return env


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


def wait_for(predicate, seconds: float, interval: float = 1.0):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            got = predicate()
        except Exception:  # noqa: BLE001 - a probe that raised is "not yet"
            got = None
        if got:
            return got
        time.sleep(interval)
    return None


def listener_pids(port: int) -> list[int]:
    """Every process listening on `port`, whoever owns it."""
    out = sudo("lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t", timeout=30).stdout.split()
    return sorted({int(p) for p in out if p.isdigit()})


def listener_pid(port: int) -> int | None:
    pids = listener_pids(port)
    return pids[0] if pids else None


def ps_field(pid: int, field: str) -> str:
    return sudo("ps", "-o", f"{field}=", "-p", str(pid), timeout=20).stdout.strip()


def account_uid() -> int | None:
    out = run(["id", "-u", ACCOUNT], timeout=20)
    return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip().isdigit() else None


def dscl_read(path: str, key: str) -> str | None:
    out = run(["dscl", ".", "-read", path, key], timeout=20)
    if out.returncode != 0:
        return None
    text = out.stdout.strip()
    return text.split(":", 1)[1].strip() if ":" in text else text


def plist_value(path: Path, key: str) -> str | None:
    out = run(["plutil", "-extract", key, "raw", "-o", "-", str(path)], timeout=20)
    return out.stdout if out.returncode == 0 else None


def root_read(path: Path) -> str:
    out = sudo("cat", str(path), timeout=20)
    return out.stdout if out.returncode == 0 else ""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def job_pid(domain: str) -> int | None:
    printed = sudo("launchctl", "print", domain, timeout=30).stdout
    match = re.search(r"^\s*pid = (\d+)", printed, re.M)
    return int(match.group(1)) if match else None


def hold_default_ports() -> list[socket.socket]:
    """Idle listeners on 8079-8083, so the install must keep off them."""
    held = []
    for port in HELD:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(1)
            held.append(sock)
        except OSError as e:
            sock.close()
            raise SystemExit(f"port {port} is already taken on this machine ({e}); refusing to run")
    return held


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
    copy.chmod(0o755)
    return copy


def component_url(agent_yaml: str, name: str) -> str | None:
    """A declared component's URL, read from agent.yaml's topology.

    Stdlib only, so the list items are cut out by their shape: an item is a
    `- key: value` line, and its other keys are the lines two spaces further
    in, up to the next line at or left of its dash."""
    lines = agent_yaml.splitlines()
    for index, line in enumerate(lines):
        start = re.match(r"^( *)- ([A-Za-z]+:.*)$", line)
        if not start:
            continue
        base = len(start.group(1))
        fields = [start.group(2)]
        for follow in lines[index + 1:]:
            if not follow.strip():
                continue
            indent = len(follow) - len(follow.lstrip(" "))
            if indent <= base:
                break
            if indent == base + 2:
                fields.append(follow.strip())
        keys = {}
        for field in fields:
            pair = re.match(r"^([A-Za-z]+):\s*'?([^']*?)'?\s*$", field)
            if pair:
                keys[pair.group(1)] = pair.group(2)
        if keys.get("name") == name and keys.get("url", "").startswith("http"):
            return keys["url"].rstrip("/")
    return None


def identity_lines(node_yaml: str) -> list[str]:
    """What makes a node the same node: its name and its public keys."""
    return sorted(
        line for line in node_yaml.splitlines()
        if re.match(r"^(name|publicKey|signingPublicKey|controlPublicKey):", line)
    )


def onboard(base: str, agent_yaml: str, *, keyring: bool) -> dict:
    """What the wizard does: the passphrase on both, the unlock mode, and the
    machine enrolled with its own control root. Returns the session and URLs."""
    control = component_url(agent_yaml, "control")
    if not control:
        raise Abort(f"no control root declared in agent.yaml: {agent_yaml[:400]}")
    wait_for(lambda: api("GET", f"{control}/healthz")[0] == 200, 120)
    status, _ = api("POST", f"{control}/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    must("ob1", "control initializes", status == 204, status)
    status, body = api("POST", f"{base}/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    must("ob2", "the agent initializes", status == 200 and bool((body or {}).get("sessionToken")), body)
    wait_for(lambda: api("GET", f"{control}/healthz")[0] == 200, 120)
    _, clogin = api("POST", f"{control}/v1/auth/login", body={"passphrase": PASSPHRASE})
    ctoken = (clogin or {}).get("sessionToken")
    _, agent_status = api("GET", f"{base}/v1/auth/status")
    mode = "os_keyring" if keyring else ("passphrase_file" if (agent_status or {}).get("passphraseFile") else None)
    if mode:
        _, alogin = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
        a, _ = api("PATCH", f"{base}/v1/config", (alogin or {}).get("sessionToken"), {"securityMode": mode})
        c, _ = api("PATCH", f"{control}/v1/config", ctoken, {"securityMode": mode})
        check("ob3", f"{mode} is chosen on both, as the wizard chooses it", a == 200 and c == 200,
              f"agent={a} control={c}")
    status, body = api("POST", f"{control}/v1/nodes/join-token", ctoken, {"nodeName": "row8-mac"})
    join = (body or {}).get("token") if status in (200, 201) else None
    must("ob4", "control mints a join token", bool(join), body)
    _, login = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    status, body = api("POST", f"{base}/v1/node/enroll", (login or {}).get("sessionToken"),
                       {"controlUrl": control, "token": join, "name": "row8-mac"}, timeout=120)
    must("ob5", "the agent enrolls with its own control root", status == 200, body)
    wait_for(lambda: api("GET", f"{base}/healthz")[0] == 200, 120)
    wait_for(lambda: api("GET", f"{control}/healthz")[0] == 200, 120)
    time.sleep(2)
    # A fresh sign-in after enrolment, which also writes the passphrase file
    # on an install that keeps one.
    status, body = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    must("ob6", "a fresh session after enrolment", status == 200, body)
    api("POST", f"{control}/v1/auth/login", body={"passphrase": PASSPHRASE})
    return {"token": body["sessionToken"], "control": control}


def unlocked(url: str) -> bool | None:
    _, body = api("GET", f"{url}/v1/auth/status")
    return (body or {}).get("unlocked") if isinstance(body, dict) else None


# --------------------------------------------------------------------------- #
# phase A: a fresh install
# --------------------------------------------------------------------------- #


def phase_fresh(installer: Path) -> dict:
    say("A. a fresh install: Eugene as a LaunchDaemon in its own account")
    here = [str(p) for p in (PREFIX, DAEMON, AGENT_PLIST, USER_PREFIX) if p.exists()]
    must("A-", "nothing of Eugene is on this machine before the fresh install", not here, here)
    started = time.perf_counter()
    out = run(["/bin/sh", str(installer)], timeout=1500,
              env=clean_env(EUGENE_PLEXUS_AGENT_BIND_PORT=str(PORT)))
    fact("install seconds", round(time.perf_counter() - started, 1))
    text = out.stdout + out.stderr
    must("A0", "install.sh completes and says the agent is running",
         out.returncode == 0 and "Eugene Plexus is running" in text, text[-1500:])
    check("A0b", "...without the per-user warning", "any program you run as you" not in text)

    uid = account_uid()
    shell = dscl_read(f"/Users/{ACCOUNT}", "UserShell")
    hidden = dscl_read(f"/Users/{ACCOUNT}", "IsHidden")
    auth = run(["dscl", ".", "-read", f"/Users/{ACCOUNT}", "AuthenticationAuthority"], timeout=20)
    staff = run(["dseditgroup", "-o", "checkmember", "-m", ACCOUNT, "staff"], timeout=20).returncode == 0
    admin = run(["dseditgroup", "-o", "checkmember", "-m", ACCOUNT, "admin"], timeout=20).returncode == 0
    fact("account", {"uid": uid, "shell": shell, "hidden": hidden, "auth": auth.stdout.strip()[:120]})
    check("1", "_eugeneplexus exists below 500, hidden, no login shell, no password, in staff, not admin",
          uid is not None and 0 < uid < 500 and shell == "/usr/bin/false" and hidden == "1"
          and "ShadowHash" not in auth.stdout and staff and not admin,
          {"uid": uid, "shell": shell, "hidden": hidden, "staff": staff, "admin": admin})

    owner = run(["stat", "-f", "%Su:%Sg %Lp", str(DAEMON)], timeout=20).stdout.strip()
    lint = run(["plutil", "-lint", str(DAEMON)], timeout=20)
    check("2", "the daemon plist is root:wheel 0644, lints, names _eugeneplexus; no LaunchAgent",
          owner == "root:wheel 644" and lint.returncode == 0
          and plist_value(DAEMON, "UserName") == ACCOUNT and plist_value(DAEMON, "GroupName") == ACCOUNT
          and not AGENT_PLIST.exists(),
          {"owner": owner, "lint": lint.stdout.strip(), "user": plist_value(DAEMON, "UserName"),
           "agent plist": AGENT_PLIST.exists()})

    pid = wait_for(lambda: job_pid(f"system/{LABEL}"), 30)
    listener = listener_pid(PORT)
    proc_uid = ps_field(listener, "uid") if listener else ""
    check("3", "launchd runs it, as the account (never 0, never the runner), child of pid 1",
          bool(pid) and pid == listener and proc_uid == str(uid) and proc_uid not in ("0", str(UID))
          and ps_field(listener, "ppid") == "1",
          {"job": pid, "listener": listener, "uid": proc_uid, "ppid": ps_field(listener, "ppid") if listener else None})

    base = f"http://127.0.0.1:{PORT}"
    status, _ = api("GET", f"{base}/healthz")
    ours = os.getpid()
    others = {port: [p for p in listener_pids(port) if p != ours] for port in HELD}
    check("5", "health answers, and nothing of the run listens on 8079-8083",
          status == 200 and not any(others.values()), {"health": status, "others": others})

    agent_yaml = root_read(PREFIX / "agent.yaml")
    check("6a", "a fresh install unlocks from a passphrase file (agent.yaml)",
          re.search(r"^securityMode: passphrase_file$", agent_yaml, re.M) is not None,
          re.findall(r"^securityMode:.*$", agent_yaml, re.M))
    ctx = onboard(base, agent_yaml, keyring=False)
    ctx["base"] = base
    got = sudo("stat", "-f", "%Su %Lp", str(PREFIX / "passphrase"), timeout=20).stdout.strip()
    _, cconfig = api("GET", f"{ctx['control']}/v1/config", ctx["token"])
    cmode = None
    if isinstance(cconfig, dict):
        values = cconfig.get("values") if isinstance(cconfig.get("values"), dict) else cconfig
        cmode = values.get("securityMode")
    check("6", "agent and control use passphrase_file; the file is the account's, 0400",
          got == f"{ACCOUNT} 400" and cmode == "passphrase_file", {"file": got, "control": cmode})

    denied = {}
    for name in ("node.yaml", "agent.yaml", "passphrase"):
        attempt = run(["cat", str(PREFIX / name)], timeout=20)
        denied[name] = attempt.returncode != 0 and "Permission denied" in attempt.stderr
    check("4", "the runner cannot read node.yaml, agent.yaml or the passphrase file", all(denied.values()), denied)

    status, node = api("GET", f"{base}/v1/node", ctx["token"])
    restart = (((node or {}).get("reach") or {}).get("restart") or {}) if status == 200 else {}
    mechanism = ((node or {}).get("install") or {}).get("mechanism") if status == 200 else None
    check("7", "Reach says launchd, starts at boot, can restart",
          restart.get("mechanism") == "launchd" and "starts at boot" in (restart.get("detail") or "")
          and restart.get("canSelfRestart") is True and mechanism == "launchd"
          and f"system/{LABEL}" in (restart.get("command") or ""),
          {"restart": restart, "install": mechanism})
    ctx["node"] = node
    return ctx


def phase_unattended(ctx: dict) -> None:
    say("8-9. restarts nobody is watching")
    base = ctx["base"]
    locked = run(["security", "lock-keychain"], timeout=30)
    fact("security lock-keychain", (locked.returncode, locked.stderr.strip()[:120]))
    before = listener_pid(PORT)
    kick = sudo("launchctl", "kickstart", "-k", f"system/{LABEL}", timeout=60)
    after = wait_for(lambda: (lambda p: p if p and p != before else None)(listener_pid(PORT)), 90)
    wait_for(lambda: api("GET", f"{base}/healthz")[0] == 200, 120)
    wait_for(lambda: unlocked(ctx["control"]) is not None, 120)
    agent_unlocked = wait_for(lambda: unlocked(base), 60)
    control_unlocked = wait_for(lambda: unlocked(ctx["control"]), 60)
    check("8", "Keychain locked, kickstart -k: agent and root come back unlocked, nobody signing in",
          kick.returncode == 0 and bool(after) and agent_unlocked is True and control_unlocked is True,
          {"old": before, "new": after, "agent": agent_unlocked, "control": control_unlocked,
           "kickstart": kick.stderr.strip()[:200]})

    _, login = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    token = (login or {}).get("sessionToken")
    before = listener_pid(PORT)
    status, body = api("POST", f"{base}/v1/node/reach", token, {"enabled": False, "restartAgent": True})
    started = time.perf_counter()
    after = wait_for(lambda: (lambda p: p if p and p != before else None)(listener_pid(PORT)), 30, 0.5)
    seconds = round(time.perf_counter() - started, 1)
    check("9", "Reach's own restart: a new pid under launchd within 30 s",
          status == 200 and (body or {}).get("restarted") is True and bool(after)
          and ps_field(after, "ppid") == "1",
          {"status": status, "restarted": (body or {}).get("restarted"), "old": before, "new": after,
           "seconds": seconds, "steps": (body or {}).get("steps")})
    wait_for(lambda: api("GET", f"{base}/healthz")[0] == 200, 120)
    wait_for(lambda: unlocked(base), 60)
    _, login = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    ctx["token"] = (login or {}).get("sessionToken", ctx["token"])


def library_url(ctx: dict, name: str = "library") -> str:
    url = component_url(root_read(PREFIX / "agent.yaml"), name)
    return url or "http://127.0.0.1:8082"


def library_model(ctx: dict, library: str, repo: str, pick) -> dict:
    status, detail = api("GET", f"{library}/v1/catalogue/model?repo={repo}", ctx["token"], timeout=120)
    if status != 200:
        return {"harnessError": f"catalogue {status}: {str(detail)[:300]}"}
    candidate = pick(detail.get("candidates") or [])
    if not candidate:
        return {"harnessError": "no candidate"}
    files = [f.get("path") if isinstance(f, dict) else f for f in candidate.get("files") or []]
    status, record = api("POST", f"{library}/v1/downloads", ctx["token"], {"repo": repo, "files": files})
    if status not in (200, 201, 202):
        return {"harnessError": f"download {status}: {str(record)[:300]}"}

    def finished():
        _, current = api("GET", f"{library}/v1/downloads/{record['id']}", ctx["token"])
        state = (current or {}).get("state")
        return current if state in ("done", "failed", "cancelled") and (state != "done" or current.get("modelId")) else None

    done = wait_for(finished, 900, 2)
    if not done or done.get("state") != "done":
        return {"harnessError": f"download ended {done}"}
    status, model = api("GET", f"{library}/v1/models/{done['modelId']}", ctx["token"])
    return model if status == 200 else {"harnessError": f"model {status}: {model}"}


def phase_metal(ctx: dict) -> None:
    say("10. Metal and a model, in the daemon")
    base = ctx["base"]
    _, node = api("GET", f"{base}/v1/node", ctx["token"])
    gpu = next((d for d in (node or {}).get("devices") or [] if d.get("kind") == "metal"), None)
    fact("agent metal device", gpu)
    check("10a", "in the daemon, the agent reports a Metal device with shared memory",
          bool(gpu) and gpu.get("sharedMemory") is True, gpu)
    library = library_url(ctx)
    status, body = api("PATCH", f"{library}/v1/config", ctx["token"], {"modelRoots": [str(MODELS)]})
    check("10b", "the library takes ~/Eugene Models", status == 200, body if status != 200 else "")
    gguf = library_model(ctx, library, GGUF_REPO, lambda cs: next(
        (c for c in cs if GGUF_QUANT in (c.get("label") or "") and c.get("format") == "gguf"), None))
    path = Path(gguf.get("path") or "") if "harnessError" not in gguf else None
    owner = run(["stat", "-f", "%Su", str(path)], timeout=20).stdout.strip() if path else ""
    check("10c", "a download lands in ~/Eugene Models, written by the account, readable by the person",
          bool(path) and str(path).startswith(str(MODELS) + "/") and owner == ACCOUNT
          and os.access(path, os.R_OK),
          gguf.get("harnessError") or {"path": str(path), "owner": owner})
    if not path:
        return
    engine = {}
    status, engines = api("GET", f"{base}/v1/engines", ctx["token"], timeout=120)
    if status == 200:
        engine = next((e for e in engines.get("engines", []) if e.get("engine") == "llama_cpp"), {})
    acquisition = engine.get("acquisition") or {}
    spec = {"name": "row8-gguf", "engine": "llama_cpp", "modelPath": str(path),
            "modelAlias": "row8-gguf", "autoStart": True}
    if acquisition.get("installable") is not True and "limit of 60 requests an hour" in (acquisition.get("reason") or ""):
        fallback = os.environ.get("EP_LLAMA_FALLBACK_DIR", "")
        if not fallback:
            skip("10d", "a GGUF answers through the gateway", "GitHub refused the agent and no fallback build was given")
            return
        api("PATCH", f"{base}/v1/config", ctx["token"], {"engineBinaryRoots": [fallback]})
        spec["binary"] = str(Path(fallback) / "llama-server")
        fact("llama.cpp", f"GitHub refused the release list; using {fallback}")
    else:
        api("POST", f"{base}/v1/engines/llama_cpp/install", ctx["token"], {}, timeout=900)
        wait_for(lambda: (lambda e: e if e.get("available") else None)(next(
            (e for e in (api("GET", f"{base}/v1/engines", ctx["token"], timeout=120)[1] or {}).get("engines", [])
             if e.get("engine") == "llama_cpp"), {})), 600, 5)
    status, body = api("POST", f"{base}/v1/runtimes", ctx["token"], spec, timeout=120)
    ready = wait_for(lambda: (lambda r: r if r.get("status") == "ready" else None)(
        api("GET", f"{base}/v1/runtimes/row8-gguf", ctx["token"])[1] or {}), 300, 2) or {}
    gateway = component_url(root_read(PREFIX / "agent.yaml"), "gateway") or "http://127.0.0.1:8080"

    def answered():
        s, reply = api("POST", f"{gateway}/v1/chat/completions", ctx["token"], {
            "model": "row8-gguf", "max_tokens": 8, "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with one word: ok"}]}, timeout=180)
        return (s, reply) if s == 200 else None

    reply = wait_for(answered, 120, 3)
    check("10d", "a GGUF in ~/Eugene Models answers through the gateway, from the daemon",
          ready.get("status") == "ready" and bool(reply),
          {"runtime": {k: ready.get(k) for k in ("status", "lastError")}, "declared": status})
    api("POST", f"{base}/v1/runtimes/row8-gguf/stop", ctx["token"], {}, timeout=120)


def phase_user_beside(installer: Path) -> None:
    say("13. --user beside the daemon")
    out = run(["/bin/sh", str(installer), "--user", "--no-start"], timeout=300, env=clean_env())
    text = out.stdout + out.stderr
    check("13", "--user beside the daemon is refused, and writes no LaunchAgent",
          out.returncode != 0 and "This Mac already starts Eugene at boot. Re-run without --user to update it." in text
          and not AGENT_PLIST.exists(), text[-400:])


def phase_uninstall(installer: Path, number: str) -> None:
    say(f"{number}. uninstall")
    engines = run(["pgrep", "-f", "llama-server"], timeout=20).stdout.split()
    out = run(["/bin/sh", str(installer), "--uninstall"], timeout=600, env=clean_env())
    text = out.stdout + out.stderr
    kept = re.search(r"(/usr/local/eugene-plexus\.removed-\d+)", text)
    kept_path = Path(kept.group(1)) if kept else None
    kept_ok = bool(kept_path) and sudo("test", "-f", str(kept_path / "agent.yaml")).returncode == 0
    kept_owner = sudo("stat", "-f", "%Su:%Sg %Lp", str(kept_path), timeout=20).stdout.strip() if kept_path else ""
    time.sleep(3)
    left = [line for line in sudo("ps", "-axo", "pid=,comm=", timeout=20).stdout.splitlines()
            if str(PREFIX) + "/" in line]
    left += [p for p in engines if run(["kill", "-0", p], timeout=10).returncode == 0
             or "Operation not permitted" in run(["kill", "-0", p], timeout=10).stderr]
    loaded = sudo("launchctl", "print", f"system/{LABEL}", timeout=30).returncode == 0
    check(number, "plist gone, job unknown, no process left, account and group removed, config kept as root's",
          out.returncode == 0 and not DAEMON.exists() and not loaded and not left
          and account_uid() is None and dscl_read(f"/Groups/{ACCOUNT}", "PrimaryGroupID") is None
          and kept_ok and kept_owner == "root:wheel 700" and not PREFIX.exists()
          and not (RECEIPTS / "account.txt").exists(),
          {"rc": out.returncode, "plist": DAEMON.exists(), "loaded": loaded, "left": left,
           "account": account_uid(), "kept": str(kept_path), "kept owner": kept_owner,
           "said": text[-500:]})


# --------------------------------------------------------------------------- #
# phase B: the move from a LaunchAgent install
# --------------------------------------------------------------------------- #


def phase_user_install(installer: Path) -> dict:
    say("B. a per-user install, as the old Mac layout made it")
    out = run(["/bin/sh", str(installer), "--user"], timeout=1500,
              env=clean_env(EUGENE_PLEXUS_AGENT_BIND_PORT=str(PORT)))
    text = out.stdout + out.stderr
    must("B0", "install.sh --user completes with a LaunchAgent on the run's port",
         out.returncode == 0 and AGENT_PLIST.is_file() and "Eugene Plexus is running" in text, text[-1200:])
    base = f"http://127.0.0.1:{PORT}"
    _, status = api("GET", f"{base}/v1/auth/status")
    keyring = bool((status or {}).get("keyringAvailable"))
    fact("keyring available to the LaunchAgent", keyring)
    agent_yaml = (USER_PREFIX / "agent.yaml").read_text(encoding="utf-8")
    ctx = onboard(base, agent_yaml, keyring=keyring)
    ctx.update(base=base, keyring=keyring)
    _, node = api("GET", f"{base}/v1/node", ctx["token"])
    ctx["name"] = (node or {}).get("name")
    ctx["node_yaml"] = (USER_PREFIX / "node.yaml").read_text(encoding="utf-8")
    ctx["state_files"] = sorted(p.name for p in USER_PREFIX.glob("library-state*.json"))
    fact("before the move", {"name": ctx["name"], "node.yaml": sha(ctx["node_yaml"]),
                             "state": ctx["state_files"], "securityMode": re.findall(r"^securityMode:.*$", (USER_PREFIX / "agent.yaml").read_text(encoding="utf-8"), re.M)})
    return ctx


def phase_refused_move(installer: Path, ctx: dict, workdir: Path) -> None:
    say("12. launchd refuses the daemon: the LaunchAgent comes back")
    stubs = workdir / "launchctl-stand-in"
    stubs.mkdir(exist_ok=True)
    stand_in = stubs / "launchctl"
    stand_in.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = bootstrap ] && [ "$2" = system ]; then\n'
        '  echo "Bootstrap failed: 5: Input/output error" >&2\n'
        "  exit 5\n"
        "fi\n"
        'exec /bin/launchctl "$@"\n',
        encoding="utf-8",
    )
    stand_in.chmod(0o755)
    before = {p.relative_to(USER_PREFIX).as_posix(): p.stat().st_size for p in USER_PREFIX.rglob("*")
              if p.is_file() and "venv" not in p.parts and "logs" not in p.parts and "pythons" not in p.parts}
    # As `sudo sh install.sh` runs it, so root's launchctl is the stand-in.
    out = run(["sudo", "-n", "env", f"PATH={stubs}:{os.environ['PATH']}", f"SUDO_USER={ME}", f"HOME={HOME}",
               "/bin/sh", str(installer)], timeout=1500, env=clean_env())
    text = out.stdout + out.stderr
    fact("refused move said", text[-800:])
    back = wait_for(lambda: api("GET", f"{ctx['base']}/healthz")[0] == 200, 60)
    pid = listener_pid(PORT)
    command = ps_field(pid, "command") if pid else ""
    after = {p.relative_to(USER_PREFIX).as_posix(): p.stat().st_size for p in USER_PREFIX.rglob("*")
             if p.is_file() and "venv" not in p.parts and "logs" not in p.parts and "pythons" not in p.parts}
    check("12", "launchctl's refusal is said, and the LaunchAgent serves again from the old prefix",
          out.returncode != 0 and "Bootstrap failed: 5: Input/output error" in text
          and AGENT_PLIST.is_file() and bool(back) and str(USER_PREFIX) in command
          and ps_field(pid, "user") == ME and not DAEMON.exists() and not PREFIX.exists()
          and account_uid() is None and set(after) >= set(before),
          {"rc": out.returncode, "serving": bool(back), "command": command[:160],
           "daemon": DAEMON.exists(), "prefix": PREFIX.exists(), "account": account_uid()})


def phase_move(installer: Path, ctx: dict) -> None:
    say("11. the move to the daemon")
    out = run(["/bin/sh", str(installer)], timeout=1500, env=clean_env())
    text = out.stdout + out.stderr
    words = text.find("Eugene will start when this Mac starts, before anyone signs in")
    copying = text.find("copying its identity")
    check("11a", "the words come first, then the move, and it finishes",
          out.returncode == 0 and 0 <= words < copying and "sign in to Eugene once" in text, text[-1200:])
    base = ctx["base"]
    pid = wait_for(lambda: listener_pid(PORT), 60)
    _, status = api("GET", f"{base}/v1/auth/status")
    check("11b", "the daemon answers on the same port, as the account, sealed until one sign-in",
          bool(pid) and ps_field(pid, "user") == ACCOUNT and isinstance(status, dict)
          and status.get("initialized") is True and status.get("unlocked") is False,
          {"pid": pid, "user": ps_field(pid, "user") if pid else None, "status": status})
    _, login = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
    token = (login or {}).get("sessionToken")
    _, node = api("GET", f"{base}/v1/node", token)
    node_yaml = root_read(PREFIX / "node.yaml")
    state_files = sorted(Path(p).name for p in sudo("sh", "-c", f"ls {PREFIX}/library-state*.json", timeout=20).stdout.split())
    moved = sorted(USER_PREFIX.parent.glob(USER_PREFIX.name + ".moved-*"))
    same_node = bool(identity_lines(node_yaml)) and identity_lines(node_yaml) == identity_lines(ctx["node_yaml"])
    check("11c", "node name and keys unchanged, Library state kept, the old prefix moved aside, no LaunchAgent",
          (node or {}).get("name") == ctx["name"] and same_node
          and set(ctx["state_files"]) <= set(state_files) and bool(moved) and not USER_PREFIX.exists()
          and not AGENT_PLIST.exists() and bool(moved) and (moved[-1] / "node.yaml").is_file(),
          {"name": (node or {}).get("name"), "same keys": same_node, "state": state_files,
           "moved": [str(m) for m in moved]})
    agent_yaml = root_read(PREFIX / "agent.yaml")
    check("11d", "the moved settings name the new prefix and unlock from the passphrase file",
          str(USER_PREFIX) not in agent_yaml and str(PREFIX) in agent_yaml
          and (not ctx["keyring"] or re.search(r"^securityMode: passphrase_file$", agent_yaml, re.M) is not None),
          re.findall(r"^securityMode:.*$", agent_yaml, re.M))
    control = component_url(agent_yaml, "control") or ctx["control"]
    if unlocked(control) is not True:
        api("POST", f"{control}/v1/auth/login", body={"passphrase": PASSPHRASE})
    before = listener_pid(PORT)
    sudo("launchctl", "kickstart", "-k", f"system/{LABEL}", timeout=60)
    wait_for(lambda: (lambda p: p if p and p != before else None)(listener_pid(PORT)), 90)
    wait_for(lambda: api("GET", f"{base}/healthz")[0] == 200, 120)
    agent_ok = wait_for(lambda: unlocked(base), 60)
    control_ok = wait_for(lambda: unlocked(control), 90)
    if ctx["keyring"]:
        check("11e", "after that one sign-in, a kickstart unlocks agent and root by itself",
              agent_ok is True and control_ok is True, {"agent": agent_ok, "control": control_ok})
    else:
        skip("11e", "after one sign-in, a kickstart unlocks by itself",
             "this runner's LaunchAgent had no Keychain, so the old install kept prompt_on_startup")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("this run is for macOS (a disposable one)", file=sys.stderr)
        return 2
    if run(["sudo", "-n", "true"], timeout=20).returncode != 0:
        print("this run needs passwordless sudo, as a GitHub macOS runner has", file=sys.stderr)
        return 2
    fact("macOS", run(["sw_vers", "-productVersion"]).stdout.strip())
    fact("machine", platform.machine())
    # A Mac's home is 0750 person:staff, which is how Eugene's account (in
    # staff) reaches ~/Eugene Models. Said, and made so if a runner image
    # differs, because the install only warns about it.
    mode = run(["stat", "-f", "%Sp", str(HOME)]).stdout.strip()
    fact("home folder mode", mode)
    if len(mode) > 6 and mode[6] not in "xs":
        run(["chmod", "g+x", str(HOME)])
        fact("home folder mode, as a Mac makes it", run(["stat", "-f", "%Sp", str(HOME)]).stdout.strip())
    held = hold_default_ports()
    fact("held by this harness", f"{HELD.start}-{HELD.stop - 1} (pid {os.getpid()})")
    workdir = Path(tempfile.mkdtemp(prefix="row8-"))
    os.chmod(workdir, 0o755)
    installer = installer_copy(workdir)
    try:
        # B first: A locks the runner's Keychain (check 8), which B's
        # LaunchAgent needs to unlock from.
        for path in (PREFIX, DAEMON, AGENT_PLIST, USER_PREFIX):
            if path.exists():
                raise SystemExit(f"{path} exists before the run; this harness is for a machine with no Eugene")
        try:
            ctx = phase_user_install(installer)
            phase_refused_move(installer, ctx, workdir)
            phase_move(installer, ctx)
        except Abort as e:
            print(f"\n  ABORT  {e}", flush=True)
        except Exception:  # noqa: BLE001 - the report must still be written
            check("XB", "phase B ran to the end", False, traceback.format_exc()[-1500:])
        finally:
            log = root_read(PREFIX / "logs" / "agent.log") or (
                (USER_PREFIX / "logs" / "agent.log").read_text(encoding="utf-8", errors="replace")
                if (USER_PREFIX / "logs" / "agent.log").exists() else "")
            if log:
                (workdir / "agent-log-tail-b.txt").write_text(log[-60000:], encoding="utf-8")
            if DAEMON.exists() or PREFIX.exists():
                try:
                    phase_uninstall(installer, "14b")
                except Exception:  # noqa: BLE001
                    check("X14b", "uninstall ran", False, traceback.format_exc()[-800:])
            # What B left of the per-user layout, so A starts from nothing.
            if AGENT_PLIST.exists():
                run(["launchctl", "bootout", f"gui/{UID}/{LABEL}"], timeout=60)
                AGENT_PLIST.unlink()
            if USER_PREFIX.exists():
                USER_PREFIX.rename(USER_PREFIX.with_name(USER_PREFIX.name + ".row8-b"))
        try:
            ctx = phase_fresh(installer)
            phase_unattended(ctx)
            phase_metal(ctx)
            phase_user_beside(installer)
        except Abort as e:
            print(f"\n  ABORT  {e}", flush=True)
        except Exception:  # noqa: BLE001
            check("XA", "phase A ran to the end", False, traceback.format_exc()[-1500:])
        finally:
            log = root_read(PREFIX / "logs" / "agent.log")
            if log:
                (workdir / "agent-log-tail-a.txt").write_text(log[-60000:], encoding="utf-8")
            try:
                phase_uninstall(installer, "14")
            except Exception:  # noqa: BLE001
                check("X14", "uninstall ran", False, traceback.format_exc()[-800:])
    finally:
        for sock in held:
            sock.close()
        if args.report:
            for name in ("agent-log-tail-a.txt", "agent-log-tail-b.txt"):
                if (workdir / name).exists():
                    shutil.copyfile(workdir / name, args.report.parent / name)

    failed = [r for r in RESULTS if r["passed"] is False]
    skipped = [r for r in RESULTS if r["passed"] is None]
    ran = len(RESULTS) - len(skipped)
    say("result")
    print(f"  {ran} checks, {len(failed)} failures, {len(skipped)} skipped")
    if args.report:
        args.report.write_text(json.dumps({"facts": FACTS, "checks": RESULTS}, indent=2, default=str),
                               encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"## Row 8 on macOS {FACTS.get('macOS')}\n\n")
            out.write(f"**{ran - len(failed)} of {ran} checks passed, {len(skipped)} skipped.**\n\n")
            out.write("| # | Claim | Result |\n|---|---|---|\n")
            for r in RESULTS:
                verdict = {True: "PASS", False: "FAIL: ", None: "SKIP: "}[r["passed"]]
                said = "" if r["passed"] else r["detail"][:160].replace("|", "/")
                out.write(f"| {r['check']} | {r['claim']} | {verdict}{said} |\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
