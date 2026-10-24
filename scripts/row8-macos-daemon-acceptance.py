"""Row 8: Eugene on a Mac as a LaunchDaemon in its own account.

Design: docs/design/rows/row-08.md, section 5. Runs on a GitHub-hosted macOS
runner, as the runner account, which has passwordless sudo. It installs for
real from the checked-out `install.sh` (its pins say what ships; EP_PIN_*
substitutes a candidate, as A4 does), so it is for a disposable machine: a
CI runner, or a rented Mac that is wiped afterwards.

Two phases.

**A, a fresh install** (the default on a Mac since row 8):
 1. `_eugeneplexus` exists, is hidden, has no login shell and no password,
    and shares a group of its own with the person (never `staff`), which
    owns ~/Eugene Models (2770) and may pass through the home (ACL `search`)
 2. the daemon plist is root:wheel 0644, lints, and names `_eugeneplexus`;
    there is no LaunchAgent
 3. launchd runs it; the agent's uid is the account's (never 0, never the
    runner's); its parent is pid 1
 4. the runner cannot read node.yaml, agent.yaml or the passphrase file
 5. health answers on the run's own port; nothing of the run listens on
    8079 or 8081, the agent's and the driver's defaults, which this harness
    holds. 8080 and 8082 are left to the gateway and the library: holding
    them makes the agent move control onto the gateway's new port
    (agent#31). 8083 is left to the install's machine port, the one door
    other machines use: every node opens it there, the installer has no
    setting for it, and the enrolment below must reach it (the root's join
    token pins it, agent#27)
 6. onboarding: agent and control use passphrase_file; the file is 0400 and
    the account's
 7. Reach says launchd, "starts at boot", can restart
 8. the runner's Keychain locked, then `sudo launchctl kickstart -k`: the
    root comes back unlocked with nobody signing in
 9. Reach's own restart gives a new pid under launchd within 30 s
10. in the daemon the agent reports Metal; a GGUF downloaded through the
    Library lands in ~/Eugene Models and answers through the gateway
A2. what Eugene's own account runs, on fixtures made here, offline, each
    checked whatever happened before it (part 8c): a program in the
    runner's folder waits for an owner's approval and does not run;
    approved through the API it runs; one byte changed, it asks again. A
    chain of links through the runner's home and a script whose
    interpreter the runner owns wait for approval too. Root's program with
    an ACL entry that lets the runner write, a `#!/usr/bin/env` script, a
    volume that ignores ownership and a folder its group can write are
    refused, naming the cause, and the API will not approve the last;
    /usr/bin/true and Eugene's own store run, a relative path as the
    absolute path that was checked; nothing refused or waiting ran
13. --user beside the daemon is refused
14. uninstall: plist gone, job unknown to launchd, no process left, account
    and group removed, config kept as root's

**B, the move from a LaunchAgent install** (`--user`, onboarded with the
Keychain where this runner has one, enrolled):
12. a `launchctl` stand-in that fails `bootstrap system`: the LaunchAgent
    serves again from the old prefix, and the message holds launchctl's words
11. the real move: words first; node name, key and port unchanged; Library
    state kept; the old prefix kept inside a folder root made and closed
    (root:wheel 0700, no ACL entry), so an ACL entry the person put on the
    old prefix beforehand opens nothing; the new prefix carries no ACL
    entry from the copy; sealed until one sign-in; then a kickstart unlocks
    by itself; 11g, no copied llama.cpp build is kept (one changed after
    download among them) and the daemon fetches it again, byte for byte;
    11h, a copied setting naming a folder of the person's is kept and said
    as "Eugene will ask before running it"; 11j, an approval planted in the
    per-user install does not cross, though it binds exactly what the
    owner's own approval of that program binds
14b. uninstall again, by root's own removal run by root alone (no
    --person): the home's ACL entry and the kept old prefix go too

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
MODELS_GROUP = "_eugeneplexusmodels"
PREFIX = Path("/usr/local/eugene-plexus")
DAEMON = Path("/Library/LaunchDaemons") / f"{LABEL}.plist"
RECEIPTS = Path("/usr/local/lib/eugene-plexus")
AGENT_PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
USER_PREFIX = HOME / ".local" / "share" / "eugene-plexus"
MODELS = HOME / "Eugene Models"
PORT = 18279
HELD = (8079, 8081)
#: The machine port (LT1): the root's control root is reached through it, in
#: plain HTTP from this machine as A4 does, and enrolment needs its TLS.
MACHINE = "http://127.0.0.1:8083"
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
    """One attribute's value. dscl writes `Key: value`, and an attribute it
    has no standard name for as `dsAttrTypeNative:Key: value`."""
    out = run(["dscl", ".", "-read", path, key], timeout=20)
    if out.returncode != 0:
        return None
    text = out.stdout.strip().removeprefix("dsAttrTypeNative:")
    return text.split(":", 1)[1].strip() if ":" in text else text


def plist_value(path: Path, key: str) -> str | None:
    out = run(["plutil", "-extract", key, "raw", "-o", "-", str(path)], timeout=20)
    # `raw` ends the value with a newline.
    return out.stdout.rstrip("\n") if out.returncode == 0 else None


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
    """Idle listeners on 8079 and 8081, so the install must keep off them."""
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


def onboard(base: str, read_agent_yaml, *, keyring: bool) -> dict:
    """What the wizard does: the passphrase on both, the unlock mode, and the
    machine enrolled with its own control root. Returns the session and URLs.

    `read_agent_yaml` reads the install's agent.yaml (as root for the
    daemon's); the topology is waited for, since the agent declares it as
    it starts. The control root is reached through the machine port, as A4
    reaches it, since its join token pins that port (agent#27)."""
    declared = wait_for(lambda: component_url(read_agent_yaml(), "control"), 90)
    fact("control declared at", declared)
    control = MACHINE
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
    def member(user: str, group: str) -> bool:
        return run(["dseditgroup", "-o", "checkmember", "-m", user, group], timeout=20).returncode == 0

    staff, admin = member(ACCOUNT, "staff"), member(ACCOUNT, "admin")
    models = member(ACCOUNT, MODELS_GROUP) and member(ME, MODELS_GROUP)
    fact("account", {"uid": uid, "shell": shell, "hidden": hidden, "auth": auth.stdout.strip()[:120]})
    check("1", "_eugeneplexus exists below 500, hidden, no login shell, no password, not in staff or admin; "
          "it and the person share the models group",
          uid is not None and 0 < uid < 500 and shell == "/usr/bin/false" and hidden == "1"
          and "ShadowHash" not in auth.stdout and not staff and not admin and models,
          {"uid": uid, "shell": shell, "hidden": hidden, "staff": staff, "admin": admin, "models group": models})
    folder = run(["stat", "-f", "%Su:%Sg %Sp", str(MODELS)], timeout=20).stdout.strip()
    acl = run(["ls", "-led", str(HOME)], timeout=20).stdout
    check("1b", "~/Eugene Models is the person's, the models group's, 2770; the home lets that group pass and no more",
          folder == f"{ME}:{MODELS_GROUP} drwxrws---" and f"group:{MODELS_GROUP} allow search" in acl
          and f"group:{MODELS_GROUP} allow list" not in acl,
          {"folder": folder, "home acl": acl.strip()[-300:]})

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
    check("5", "health answers on the run's port, and nothing of the run listens on 8079 or 8081",
          status == 200 and not any(others.values()), {"health": status, "others": others})

    agent_yaml = root_read(PREFIX / "agent.yaml")
    check("6a", "a fresh install unlocks from a passphrase file (agent.yaml)",
          re.search(r"^securityMode: passphrase_file$", agent_yaml, re.M) is not None,
          re.findall(r"^securityMode:.*$", agent_yaml, re.M))
    ctx = onboard(base, lambda: root_read(PREFIX / "agent.yaml"), keyring=False)
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


TRUST_ROOT = Path("/usr/local/row8-trust")
NOOWNERS_IMAGE = Path("/tmp/row8-noowners.dmg")
NOOWNERS_MOUNT = Path("/Volumes/row8noowners")


def _engine_said(ctx: dict, path: str) -> dict:
    """The daemon's word on `vllmBinary` = PATH: its vllm engine entry."""
    api("PATCH", f"{ctx['base']}/v1/config", ctx["token"], {"vllmBinary": path})
    _, engines = api("GET", f"{ctx['base']}/v1/engines", ctx["token"], timeout=120)
    return next((e for e in (engines or {}).get("engines", []) if e.get("engine") == "vllm"), {})


def phase_trust(ctx: dict) -> None:
    """A2: what Eugene's own account runs, on fixtures made here, offline,
    every one checked whatever happened before it (row 8 final review, part
    8c).

    Each fixture is named as `vllmBinary`, and the daemon's agent says, in
    `GET /v1/engines`, whether it would run it: `execTrust` says
    `needs_approval` (only the runner's account can change it) or `refused`
    (anyone else can), the error naming the cause; a program it runs is
    reported by the checked absolute path. A2a approves one through the
    API, and a changed byte makes it ask again."""
    say("A2. what Eugene's own account runs")
    STUB_DIR.mkdir(exist_ok=True)
    sudo("rm", "-rf", str(TRUST_ROOT), timeout=60)
    sudo("mkdir", "-p", str(TRUST_ROOT), timeout=60)

    def fixture(number: str, claim: str, path: str, *, expect: str, cause: str | None, setup) -> dict:
        try:
            setup()
            entry = _engine_said(ctx, path)
        except Exception:  # noqa: BLE001 - a fixture that cannot be made is a failure, never a skip
            check(number, claim, False, traceback.format_exc()[-600:])
            return {}
        error = entry.get("error") or ""
        trust = entry.get("execTrust") or {}
        if expect == "ok":
            check(number, claim, "Eugene's own account" not in error and not trust,
                  {"error": error[:300], "binaryPath": entry.get("binaryPath")})
        elif expect == "needs_approval":
            check(number, claim,
                  trust.get("kind") == "needs_approval" and trust.get("account") == ME
                  and bool(trust.get("sha256")) and "only once an owner approves it" in error
                  and (cause is None or cause in error),
                  {"error": error[:300], "execTrust": trust})
        else:
            check(number, claim,
                  trust.get("kind") == "refused" and "will not run" in error
                  and (cause is None or cause in error),
                  {"error": error[:300], "execTrust": trust})
        return entry

    # A2a: a program only the runner's account can change, whose interpreter
    # (the runner's too) leaves a mark when the daemon runs it to read the
    # program's environment: asked about and not run; approved through the
    # API, run; one byte changed, asked about again and not run.
    approved = STUB_DIR / "approve"
    approved_ran = Path("/tmp/row8-approved-ran")

    def runner_owned():
        approved.mkdir(exist_ok=True)
        python = approved / "python"
        python.write_text(f"#!/bin/sh\ntouch {approved_ran}\n", encoding="utf-8")
        python.chmod(0o755)
        (approved / "vllm").write_text(f"#!{python}\nimport vllm\n", encoding="utf-8")
        (approved / "vllm").chmod(0o755)
        sudo("rm", "-f", str(approved_ran), timeout=20)

    entry = fixture("A2a", "a program in a folder of the runner's waits for an owner's approval, naming that "
                    "account", str(approved / "vllm"), expect="needs_approval", cause=f"belongs to {ME}",
                    setup=runner_owned)
    trust = entry.get("execTrust") or {}
    check("A2a1", "...and it is not run, not even to read its environment", not approved_ran.exists(),
          "the stand-in's interpreter left its mark")
    try:
        status, body = api("POST", f"{ctx['base']}/v1/exec-approvals", ctx["token"],
                           {"path": trust.get("path"), "sha256": trust.get("sha256")})
        after = _engine_said(ctx, str(approved / "vllm"))
        check("A2a2", "approved through the API, it runs: listed as the engine at its path, its interpreter run",
              status == 201 and (body or {}).get("account") == ME and not (after.get("error") or "")
              and after.get("binaryPath") == str(approved / "vllm") and approved_ran.exists(),
              {"approve": [status, str(body)[:300]], "error": (after.get("error") or "")[:300],
               "binaryPath": after.get("binaryPath"), "ran": approved_ran.exists()})
        sudo("rm", "-f", str(approved_ran), timeout=20)
        (approved / "vllm").write_text(f"#!{approved / 'python'}\nimport vllx\n", encoding="utf-8")
        changed = _engine_said(ctx, str(approved / "vllm"))
        _, listed = api("GET", f"{ctx['base']}/v1/exec-approvals", ctx["token"])
        again = changed.get("execTrust") or {}
        check("A2a3", "one byte changed, it asks again: the approval is gone and the program is not run",
              again.get("kind") == "needs_approval" and again.get("sha256") not in (None, trust.get("sha256"))
              and not (listed or {}).get("approvals") and not approved_ran.exists(),
              {"execTrust": again, "approvals": listed, "ran": approved_ran.exists()})
    except Exception:  # noqa: BLE001
        check("A2a2", "approved through the API, it runs", False, traceback.format_exc()[-600:])

    def acl_write():
        sudo("cp", "/usr/bin/true", str(TRUST_ROOT / "acl-vllm"), timeout=30)
        sudo("chmod", "0755", str(TRUST_ROOT / "acl-vllm"), timeout=30)
        sudo("chmod", "+a", f"user:{ME} allow write", str(TRUST_ROOT / "acl-vllm"), timeout=30)

    fixture("A2b", "root's 0755 program with an ACL entry that lets the runner write is refused",
            str(TRUST_ROOT / "acl-vllm"), expect="refused", cause=f"ACL entry that lets user {ME} write",
            setup=acl_write)

    def chain():
        hop = HOME / "row8-hop"
        if hop.is_symlink() or hop.exists():
            hop.unlink()
        hop.symlink_to("/usr/bin/true")
        sudo("ln", "-sf", str(hop), str(TRUST_ROOT / "chain-vllm"), timeout=30)

    fixture("A2c", "a link of root's to a link in the runner's home (then to /usr/bin/true) waits for an "
            "approval, naming the runner", str(TRUST_ROOT / "chain-vllm"), expect="needs_approval",
            cause=f"which belongs to {ME}", setup=chain)

    def interpreter():
        python = STUB_DIR / "python"
        python.write_text(f"#!/bin/sh\ntouch {STUB_RAN}\n", encoding="utf-8")
        python.chmod(0o755)
        sudo("sh", "-c", f"printf '#!{python}\\nimport vllm\\n' > {TRUST_ROOT}/interp-vllm && chmod 0755 "
             f"{TRUST_ROOT}/interp-vllm", timeout=30)

    fixture("A2d", "root's script whose interpreter is in the runner's home waits for an approval",
            str(TRUST_ROOT / "interp-vllm"), expect="needs_approval", cause=f"belongs to {ME}",
            setup=interpreter)

    def env_shebang():
        sudo("sh", "-c", f"printf '#!/usr/bin/env python3\\nimport vllm\\n' > {TRUST_ROOT}/env-vllm && "
             f"chmod 0755 {TRUST_ROOT}/env-vllm", timeout=30)

    fixture("A2e", "a script that finds its interpreter on PATH (#!/usr/bin/env) is refused",
            str(TRUST_ROOT / "env-vllm"), expect="refused", cause="names its interpreter through PATH",
            setup=env_shebang)

    # A2k: root's program in a folder its group can change (part 8c): refused,
    # and the API will not approve it either.
    shared = TRUST_ROOT / "shared"

    def group_writable():
        sudo("mkdir", "-p", str(shared), timeout=30)
        sudo("chown", "root:staff", str(shared), timeout=30)
        sudo("chmod", "0775", str(shared), timeout=30)
        sudo("cp", "/usr/bin/true", str(shared / "vllm"), timeout=30)
        sudo("chmod", "0755", str(shared / "vllm"), timeout=30)

    fixture("A2k", "root's program in a folder its group (staff) can change is refused, naming who can",
            str(shared / "vllm"), expect="refused", cause="can be changed by others (mode 0775: its owner root "
            "and group staff)", setup=group_writable)
    status, body = api("POST", f"{ctx['base']}/v1/exec-approvals", ctx["token"],
                       {"path": str(shared / "vllm"),
                        "sha256": hashlib.sha256(Path("/usr/bin/true").read_bytes()).hexdigest()})
    check("A2k2", "...and the API refuses to approve it (409), naming the cause",
          status == 409 and "can be changed by others" in json.dumps(body), [status, str(body)[:300]])

    def noowners():
        sudo("hdiutil", "detach", str(NOOWNERS_MOUNT), "-force", timeout=60)
        NOOWNERS_IMAGE.unlink(missing_ok=True)
        made = run(["hdiutil", "create", "-size", "8m", "-fs", "HFS+", "-volname", "row8noowners",
                    str(NOOWNERS_IMAGE)], timeout=120)
        assert made.returncode == 0, made.stderr
        attached = sudo("hdiutil", "attach", "-owners", "off", "-nobrowse", "-mountpoint",
                        str(NOOWNERS_MOUNT), str(NOOWNERS_IMAGE), timeout=120)
        assert attached.returncode == 0, attached.stderr
        fact("the volume with ownership ignored", [line for line in run(["/sbin/mount"]).stdout.splitlines()
                                                   if str(NOOWNERS_MOUNT) in line])
        sudo("cp", "/usr/bin/true", str(NOOWNERS_MOUNT / "vllm"), timeout=30)

    fixture("A2f", "a program on a volume that ignores ownership is refused",
            str(NOOWNERS_MOUNT / "vllm"), expect="refused", cause="ignores ownership", setup=noowners)
    sudo("hdiutil", "detach", str(NOOWNERS_MOUNT), "-force", timeout=60)

    fixture("A2g", "a system program (/usr/bin/true, root's) is run",
            "/usr/bin/true", expect="ok", cause=None, setup=lambda: None)

    def own_store():
        sudo("-u", ACCOUNT, "sh", "-c", f"mkdir -p {PREFIX}/engines/row8-trust && "
             f"cp /usr/bin/true {PREFIX}/engines/row8-trust/vllm", timeout=30)

    fixture("A2h", "a program in Eugene's own store is run",
            str(PREFIX / "engines" / "row8-trust" / "vllm"), expect="ok", cause=None, setup=own_store)

    # A relative path names, at the time it runs, whatever is there from the
    # folder the program starts in: the agent runs the absolute path it
    # checked, from its own folder (the prefix).
    try:
        entry = _engine_said(ctx, "engines/row8-trust/vllm")
        check("A2i", "a relative path is run as the absolute path that was checked",
              entry.get("binaryPath") == str(PREFIX / "engines" / "row8-trust" / "vllm")
              and not (entry.get("error") or ""),
              {"binaryPath": entry.get("binaryPath"), "error": (entry.get("error") or "")[:300]})
    except Exception:  # noqa: BLE001
        check("A2i", "a relative path is run as the absolute path that was checked", False,
              traceback.format_exc()[-600:])
    check("A2j", "none of the programs refused or waiting for approval ran, not even for its version",
          not STUB_RAN.exists(), f"a stand-in left {STUB_RAN}")
    api("PATCH", f"{ctx['base']}/v1/config", ctx["token"], {"vllmBinary": None})
    _, listed = api("GET", f"{ctx['base']}/v1/exec-approvals", ctx["token"])
    for approval in (listed or {}).get("approvals") or []:
        api("DELETE", f"{ctx['base']}/v1/exec-approvals/{approval.get('id')}", ctx["token"])
    sudo("rm", "-rf", str(TRUST_ROOT), str(PREFIX / "engines" / "row8-trust"), str(approved_ran),
         timeout=60)


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
    """Where a component answers now, from the agent's own topology, once it
    does: after Reach's restart the components are starting again."""

    def answering():
        status, body = api("GET", f"{ctx['base']}/v1/components", ctx["token"])
        if status != 200:
            return None
        for component in (body or {}).get("components", []):
            if component.get("name") == name and component.get("url"):
                url = component["url"].rstrip("/")
                return url if api("GET", f"{url}/healthz")[0] == 200 else None
        return None

    return wait_for(answering, 120, 2) or f"http://127.0.0.1:{8082 if name == 'library' else 8080}"


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
        # Eugene's own account runs no program the runner can change (row 8,
        # exec_trust): the fallback build goes into a folder of root's first.
        roots_copy = Path("/usr/local/row8-llama-fallback")
        sudo("rm", "-rf", str(roots_copy), timeout=60)
        sudo("ditto", fallback, str(roots_copy), timeout=300)
        sudo("chown", "-R", "root:wheel", str(roots_copy), timeout=60)
        sudo("chmod", "-R", "go-w", str(roots_copy), timeout=60)
        api("PATCH", f"{base}/v1/config", ctx["token"], {"engineBinaryRoots": [str(roots_copy)]})
        spec["binary"] = str(roots_copy / "llama-server")
        fact("llama.cpp", f"GitHub refused the release list; using {fallback}, copied to {roots_copy} as root's")
    else:
        api("POST", f"{base}/v1/engines/llama_cpp/install", ctx["token"], {}, timeout=900)
        wait_for(lambda: (lambda e: e if e.get("available") else None)(next(
            (e for e in (api("GET", f"{base}/v1/engines", ctx["token"], timeout=120)[1] or {}).get("engines", [])
             if e.get("engine") == "llama_cpp"), {})), 600, 5)
    status, body = api("POST", f"{base}/v1/runtimes", ctx["token"], spec, timeout=120)
    ready = wait_for(lambda: (lambda r: r if r.get("status") == "ready" else None)(
        api("GET", f"{base}/v1/runtimes/row8-gguf", ctx["token"])[1] or {}), 300, 2) or {}
    gateway = library_url(ctx, "gateway")

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


def acl_entries(path: Path) -> list[str]:
    """The ACL entries `ls -le` lists under PATH's own line, read as root."""
    return [line.strip() for line in sudo("ls", "-led", str(path), timeout=20).stdout.splitlines()[1:]
            if line.strip()]


def kept_moves() -> list[Path]:
    return sorted(Path(p) for p in sudo("sh", "-c", f"ls -d {PREFIX}.moved-* 2>/dev/null", timeout=20).stdout.split())


def phase_uninstall(installer: Path, number: str, *, root_alone: bool = False) -> None:
    """Remove Eugene: by `install.sh --uninstall` as the runner, or with
    ROOT_ALONE by root's own removal run as root with no --person, as an
    administrator following the removal's own words would."""
    say(f"{number}. uninstall" + (" (root's removal, run by root alone)" if root_alone else ""))
    engines = run(["pgrep", "-f", "llama-server"], timeout=20).stdout.split()
    moves_before = kept_moves()
    if root_alone:
        out = run(["sudo", "-n", "/bin/sh", str(RECEIPTS / "remove.sh"), "--prefix", str(PREFIX)],
                  timeout=600, env=clean_env())
    else:
        out = run(["/bin/sh", str(installer), "--uninstall"], timeout=600, env=clean_env())
    text = out.stdout + out.stderr
    kept = re.search(r"(/usr/local/eugene-plexus\.removed-\d+)", text)
    kept_path = Path(kept.group(1)) if kept else None
    kept_ok = bool(kept_path) and sudo("test", "-f", str(kept_path / "agent.yaml")).returncode == 0
    kept_owner = sudo("stat", "-f", "%Su:%Sg %Lp", str(kept_path), timeout=20).stdout.strip() if kept_path else ""
    kept_acl = acl_entries(kept_path) if kept_path else ["(nothing kept)"]
    time.sleep(3)
    left = [line for line in sudo("ps", "-axo", "pid=,comm=", timeout=20).stdout.splitlines()
            if str(PREFIX) + "/" in line]
    left += [p for p in engines if run(["kill", "-0", p], timeout=10).returncode == 0
             or "Operation not permitted" in run(["kill", "-0", p], timeout=10).stderr]
    loaded = sudo("launchctl", "print", f"system/{LABEL}", timeout=30).returncode == 0
    models_group = dscl_read(f"/Groups/{MODELS_GROUP}", "PrimaryGroupID")
    home_acl = f"group:{MODELS_GROUP} allow" in run(["ls", "-led", str(HOME)], timeout=20).stdout
    moves_after = kept_moves()
    moves_said = all(f"Deleted the copy kept from before Eugene moved to its own account: {m}" in text
                     for m in moves_before)
    check(number, "plist gone, job unknown, no process left, account, its group and the models group "
          "removed, the home's ACL entry gone, config kept as root's with no ACL entry, the old prefix "
          "a move kept deleted and said",
          out.returncode == 0 and not DAEMON.exists() and not loaded and not left
          and account_uid() is None and dscl_read(f"/Groups/{ACCOUNT}", "PrimaryGroupID") is None
          and models_group is None and not home_acl
          and kept_ok and kept_owner == "root:wheel 700" and not kept_acl and not PREFIX.exists()
          and not (RECEIPTS / "account.txt").exists() and not moves_after and moves_said,
          {"rc": out.returncode, "plist": DAEMON.exists(), "loaded": loaded, "left": left,
           "account": account_uid(), "models group": models_group, "home acl entry": home_acl,
           "kept": str(kept_path), "kept owner": kept_owner, "kept acl": kept_acl,
           "moves before": [str(m) for m in moves_before], "moves after": [str(m) for m in moves_after],
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
    ctx = onboard(base, lambda: (USER_PREFIX / "agent.yaml").read_text(encoding="utf-8"), keyring=keyring)
    ctx.update(base=base, keyring=keyring)
    _, node = api("GET", f"{base}/v1/node", ctx["token"])
    ctx["name"] = (node or {}).get("name")
    ctx["node_yaml"] = (USER_PREFIX / "node.yaml").read_text(encoding="utf-8")
    ctx["state_files"] = sorted(p.name for p in USER_PREFIX.glob("library-state*.json"))
    fact("before the move", {"name": ctx["name"], "node.yaml": sha(ctx["node_yaml"]),
                             "state": ctx["state_files"], "securityMode": re.findall(r"^securityMode:.*$", (USER_PREFIX / "agent.yaml").read_text(encoding="utf-8"), re.M)})
    return ctx


def phase_engine_before_move(ctx: dict) -> None:
    """R8-ENGINES-COPY: a llama.cpp build in the per-user install, its
    llama-server changed after it was downloaded, as a program running as
    the person could change it before the move."""
    say("B1. a llama.cpp build in the per-user install, changed after download")
    base, token = ctx["base"], ctx["token"]
    status, body = api("POST", f"{base}/v1/engines/llama_cpp/install", token, {}, timeout=900)

    def finished():
        s, b = api("GET", f"{base}/v1/engines/llama_cpp/install", token, timeout=60)
        return b if s == 200 and isinstance(b, dict) and b.get("state") in ("done", "failed", "cancelled") else None

    done = wait_for(finished, 900, 5) or {}
    store = HOME / ".eugene-plexus" / "engines" / "llama_cpp"
    builds = []
    for build in store.iterdir() if store.is_dir() else []:
        record = build / "install.json"
        if record.is_file():
            meta = json.loads(record.read_text(encoding="utf-8"))
            builds.append((str(meta.get("installedAt") or ""), build, meta))
    if done.get("state") != "done" or not builds:
        ctx["engine"] = {"skip": f"no llama.cpp build to change: {status} {done.get('state')} {done.get('error')} {str(body)[:200]}"}
        fact("llama.cpp before the move", ctx["engine"])
        return
    _, build, meta = max(builds, key=lambda b: b[0])
    binary = build / str(meta["binary"])
    changed = binary.read_bytes() + b"\n# changed after it was downloaded\n"
    binary.write_bytes(changed)
    ctx["engine"] = {
        "version": str(meta["version"]),
        "binary": str(meta["binary"]),
        "recorded": (meta.get("files") or {}).get(Path(str(meta["binary"])).as_posix()),
        "changed": "sha256:" + hashlib.sha256(changed).hexdigest(),
    }
    fact("llama.cpp before the move", ctx["engine"])


STUB_DIR = HOME / "row8-bin"
STUB_RAN = Path("/tmp/row8-stub-ran")


def phase_setting_before_move(ctx: dict) -> None:
    """A setting the person's install holds that names a folder of the
    person's for engine binaries, with a stand-in `llama-server` in it that
    leaves a mark whenever it runs."""
    say("B2. a setting naming a folder of the person's for engine binaries")
    STUB_DIR.mkdir(exist_ok=True)
    stub = STUB_DIR / "llama-server"
    stub.write_text(f"#!/bin/sh\ntouch {STUB_RAN}\necho 'version: 1 (row8 stand-in)'\n", encoding="utf-8")
    stub.chmod(0o755)
    STUB_RAN.unlink(missing_ok=True)
    status, body = api("PATCH", f"{ctx['base']}/v1/config", ctx["token"], {"engineBinaryRoots": [str(STUB_DIR)]})
    fact("engineBinaryRoots set before the move", (status, str(body)[:200]))


def phase_plant_before_move(ctx: dict) -> None:
    """B3: what the review planted, in the per-user install, before the
    move -- offline, and checked whatever else happened (11i)."""
    say("B3. code planted in the per-user install before the move")
    store = HOME / ".eugene-plexus" / "engines" / "llama_cpp"
    try:
        # A build as downloaded, with its own record; and one whose record
        # is a link to valid metadata.
        pristine = store / "row8-pristine"
        pristine.mkdir(parents=True, exist_ok=True)
        shutil.copyfile("/usr/bin/true", pristine / "llama-server")
        (pristine / "llama-server").chmod(0o755)
        digest = hashlib.sha256((pristine / "llama-server").read_bytes()).hexdigest()
        record = {"version": "row8-pristine", "variant": "macos-arm64", "binary": "llama-server",
                  "installedAt": "2020-01-01T00:00:00+00:00", "files": {"llama-server": f"sha256:{digest}"},
                  "links": {}}
        (pristine / "install.json").write_text(json.dumps(record), encoding="utf-8")
        linked = store / "row8-linked"
        linked.mkdir(parents=True, exist_ok=True)
        shutil.copyfile("/usr/bin/true", linked / "llama-server")
        (linked / "llama-server").chmod(0o755)
        (store / "architectures").mkdir(parents=True, exist_ok=True)
        (store / "architectures" / "row8-receipt.json").write_text(
            json.dumps({**record, "version": "row8-linked"}), encoding="utf-8")
        receipt = linked / "install.json"
        if receipt.is_symlink() or receipt.exists():
            receipt.unlink()
        receipt.symlink_to("../architectures/row8-receipt.json")
        # A program in the old install, named by a setting.
        custom = USER_PREFIX / "custom"
        custom.mkdir(exist_ok=True)
        shutil.copyfile("/usr/bin/true", custom / "llama-server")
        (custom / "llama-server").chmod(0o755)
        status, body = api("PATCH", f"{ctx['base']}/v1/config", ctx["token"],
                           {"mlxBinary": str(custom / "llama-server")})
        fact("mlxBinary set before the move", (status, str(body)[:200]))
        # An app's environment beside its data; a module a component started
        # in the prefix would import; a link inside a folder that crosses.
        venv = USER_PREFIX / "apps" / "row8app" / "versions" / "v1" / "venv" / "bin"
        venv.mkdir(parents=True, exist_ok=True)
        shutil.copyfile("/usr/bin/true", venv / "python")
        (venv / "python").chmod(0o755)
        (USER_PREFIX / "apps" / "row8app" / "data").mkdir(parents=True, exist_ok=True)
        (USER_PREFIX / "apps" / "row8app" / "data" / "notes.txt").write_text("kept\n", encoding="utf-8")
        (USER_PREFIX / "yaml.py").write_text("raise SystemExit('planted')\n", encoding="utf-8")
        link = USER_PREFIX / "logs" / "row8-link"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(STUB_DIR)
        ctx["planted"] = True
    except Exception:  # noqa: BLE001 - checked as a failure in 11i, never skipped
        ctx["planted"] = traceback.format_exc()[-600:]
    try:
        ctx["forged"] = forge_approval()
    except Exception:  # noqa: BLE001 - checked as a failure in 11j, never skipped
        ctx["forged"] = {"error": traceback.format_exc()[-600:]}


FORGED = HOME / "row8-forged" / "vllm"
#: A spelling only the volume can tell from `exec-approvals.json` (8c
#: re-reviews): `ſ` (U+017F) folds to `s` on APFS, so carried, this would be
#: the daemon's file. The move clears the copy of the name by lookup; on a
#: volume that does not fold it, it crosses and nothing reads it.
FORGED_NAME = "exec-approval\u017f.json"


def forge_approval() -> dict:
    """8c review: what a program running as the person could write into the
    per-user install before the move -- an approval, for a program of the
    person's, binding exactly what an owner's own approval binds (the path,
    the account, the SHA-256 and every item the daemon's check walks).
    Carried, the daemon would run it with nobody's approval."""
    FORGED.parent.mkdir(exist_ok=True)
    shutil.copyfile("/usr/bin/true", FORGED)
    FORGED.chmod(0o755)
    chain = []
    current = Path("/")
    for part in FORGED.parts:
        current = current / part if part != "/" else current
        info = os.lstat(current)
        chain.append({"path": str(current), "uid": info.st_uid, "mode": info.st_mode})
    approval = {
        "id": "forged",
        "path": str(FORGED),
        "account": ME,
        "accountUid": UID,
        "sha256": hashlib.sha256(FORGED.read_bytes()).hexdigest(),
        "chain": chain,
        "approvedAt": "2026-10-23T00:00:00Z",
        "approvedBy": "nobody",
    }
    (USER_PREFIX / FORGED_NAME).write_text(json.dumps({"approvals": [approval]}),
                                                     encoding="utf-8")
    # Observed, not inferred: whether this volume takes the two as one.
    approval["folds"] = (USER_PREFIX / "exec-approvals.json").exists()
    fact("the volume takes exec-approval\u017f.json for exec-approvals.json", approval["folds"])
    return approval


def phase_forged_approval_after_move(ctx: dict, said: str) -> None:
    """11j: the planted approval did not cross. The daemon asks before it
    runs the program the approval named, and the owner's own approval of
    that program binds exactly what the planted one did -- so, carried, it
    would have been honoured."""
    forged = ctx.get("forged") or {}
    claim = ("an approval planted in the per-user install as exec-approval\u017f.json does not reach the "
             "daemon: the daemon asks before running the program it named, though it bound exactly what "
             "the owner's own approval binds")
    if "error" in forged or not forged:
        check("11j", claim, False, forged.get("error") or "nothing was planted")
        return
    # What the daemon would read, by its own spelling: on a volume that folds
    # the two, the move must have taken it out of the copy, and said so.
    kept = sudo("test", "-e", str(PREFIX / "exec-approvals.json"), timeout=20).returncode == 0
    folds = bool(forged.get("folds"))
    said_it = "did not carry exec-approvals.json (the old install held a name this volume takes" in said
    entry = _engine_said(ctx, str(FORGED))
    trust = entry.get("execTrust") or {}
    status, approval = api("POST", f"{ctx['base']}/v1/exec-approvals", ctx["token"],
                           {"path": trust.get("path"), "sha256": trust.get("sha256")})
    approval = approval if isinstance(approval, dict) else {}
    same = {key: approval.get(key) == forged.get(key)
            for key in ("path", "accountUid", "sha256", "chain")}
    check("11j", claim,
          not kept and (said_it or not folds)
          and trust.get("kind") == "needs_approval" and status == 201 and all(same.values()),
          {"daemon's file there": kept, "volume folds": folds, "said": said_it, "execTrust": trust,
           "approve": status, "same as planted": same,
           "words": [line for line in said.splitlines() if "exec-approval" in line.lower()][:2]})
    if approval.get("id"):
        api("DELETE", f"{ctx['base']}/v1/exec-approvals/{approval['id']}", ctx["token"])
    api("PATCH", f"{ctx['base']}/v1/config", ctx["token"], {"vllmBinary": None})


def phase_planted_after_move(ctx: dict, said: str) -> None:
    """11i: nothing that runs crossed the move."""
    agent_yaml = root_read(PREFIX / "agent.yaml")

    def there(flag: str, path: Path) -> bool:
        return sudo("test", flag, str(path), timeout=20).returncode == 0

    found = {
        "planted": ctx.get("planted"),
        "pristine build": there("-e", PREFIX / "engines" / "llama_cpp" / "row8-pristine"),
        "linked-receipt build": there("-e", PREFIX / "engines" / "llama_cpp" / "row8-linked"),
        "mlxBinary turned off": re.search(r"(?m)^mlxBinary: null$", agent_yaml) is not None
        and "turned off mlxBinary" in said,
        "custom program, executable": there("-x", PREFIX / "custom" / "llama-server"),
        "custom program, as data": there("-f", PREFIX / "custom" / "llama-server"),
        "app environment": there("-e", PREFIX / "apps" / "row8app" / "versions"),
        "app data": there("-f", PREFIX / "apps" / "row8app" / "data" / "notes.txt"),
        "app listed to be rebuilt": "row8app" in said,
        "module": there("-e", PREFIX / "yaml.py"),
        "module said": "did not carry yaml.py: code" in said,
        "link in a data folder": there("-L", PREFIX / "logs" / "row8-link"),
    }
    check("11i", "nothing that runs crossed the move: no engine build (one as downloaded, one behind a linked "
          "record), a setting naming a program in the old install turned off and the program carried as data "
          "only, an app's data without its environment, no module, no link",
          found["planted"] is True and not found["pristine build"] and not found["linked-receipt build"]
          and found["mlxBinary turned off"] and found["custom program, as data"]
          and not found["custom program, executable"] and not found["app environment"] and found["app data"]
          and found["app listed to be rebuilt"] and not found["module"] and found["module said"]
          and not found["link in a data folder"],
          found)


def phase_setting_after_move(ctx: dict, said: str) -> None:
    """11h: the move kept the setting and said, in its words and in root's
    receipt, that Eugene's own account asks before running what it names:
    only the person's account can change that folder (part 8c; a program
    there waits for an approval: A2)."""
    receipt = sudo("cat", str(RECEIPTS / "move-report.txt"), timeout=20).stdout
    agent_yaml = root_read(PREFIX / "agent.yaml")
    line = f"engineBinaryRoots names {STUB_DIR}: {ME} can change it. Eugene will ask before running it."
    check("11h", "a copied setting naming a folder of the person's is kept, and said as 'Eugene will ask "
          "before running it' in the move's words and in root's receipt",
          line in said and line in receipt and str(STUB_DIR) in agent_yaml
          and f"engineBinaryRoots names {STUB_DIR}: {ME} can change it. It will not run" not in said,
          {"said": [s for s in said.splitlines() if "names" in s][:4], "receipt": receipt[:300],
           "kept": str(STUB_DIR) in agent_yaml, "stand-in ran": STUB_RAN.exists()})


def phase_engine_after_move(ctx: dict, said: str) -> None:
    """11g: the changed build was not kept; the daemon fetched that version
    again from GitHub, and its llama-server is what was downloaded."""
    engine = ctx.get("engine") or {}
    if "skip" in engine or not engine:
        skip("11g", "a changed copied llama.cpp build is not kept, and is fetched again", engine.get("skip", "no build"))
        return
    version = engine["version"]
    build = PREFIX / "engines" / "llama_cpp" / version
    marker = PREFIX / "engines" / "refetch.json"

    def refetched():
        if sudo("test", "-f", str(marker)).returncode == 0:
            return None
        return True if sudo("test", "-f", str(build / "install.json")).returncode == 0 else None

    again = wait_for(refetched, 900, 5)
    out = sudo("shasum", "-a", "256", str(build / engine["binary"]), timeout=60).stdout.split()
    now = "sha256:" + out[0] if out else None
    reason = ""
    if not again:
        _, engines = api("GET", f"{ctx['base']}/v1/engines", ctx.get("token"), timeout=120)
        llama = next((e for e in (engines or {}).get("engines", []) if e.get("engine") == "llama_cpp"), {})
        reason = (llama.get("acquisition") or {}).get("reason") or ""
        if "limit of 60 requests an hour" in reason:
            skip("11g", "a changed copied llama.cpp build is not kept, and is fetched again",
                 f"GitHub refused the daemon's release list: {reason[:200]}")
            return
    # The move copies no engine build at all (the final review), and says
    # so on the line that lists the version to fetch again.
    check("11g", "no copied llama.cpp build is kept (this one was changed after download): the move says so, "
          "and the daemon fetches that version again, whose llama-server is what was downloaded",
          f"fetches llama_cpp {version} again" in said
          and "no engine build crosses the move" in said
          and bool(again) and now is not None and now != engine["changed"]
          and (engine["recorded"] is None or now == engine["recorded"]),
          {"engine": engine, "fetched again": bool(again), "llama-server now": now, "reason": reason[:200],
           "said": [line for line in said.splitlines() if "llama_cpp" in line][:4]})


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
    # The state the move copies and must not touch: the node's identity and
    # the root's settings. (Not every byte: the agent that comes back
    # rewrites its own run files and its announcement counter.)
    def state() -> dict[str, str]:
        found = {}
        if (USER_PREFIX / "node.yaml").is_file():
            found["node.yaml"] = sha("\n".join(identity_lines((USER_PREFIX / "node.yaml").read_text(encoding="utf-8"))))
        if (USER_PREFIX / "control.yaml").is_file():
            found["control.yaml"] = sha((USER_PREFIX / "control.yaml").read_text(encoding="utf-8"))
        return found

    before = state()
    # As `sudo sh install.sh` runs it, so root's launchctl is the stand-in.
    out = run(["sudo", "-n", "env", f"PATH={stubs}:{os.environ['PATH']}", f"SUDO_USER={ME}", f"HOME={HOME}",
               "/bin/sh", str(installer)], timeout=1500, env=clean_env())
    text = out.stdout + out.stderr
    fact("refused move said", text[-800:])
    back = wait_for(lambda: api("GET", f"{ctx['base']}/healthz")[0] == 200, 60)
    pid = listener_pid(PORT)
    command = ps_field(pid, "command") if pid else ""
    after = state() if USER_PREFIX.is_dir() else {}
    user = ps_field(pid, "user") if pid else ""
    said = "Bootstrap failed: 5: Input/output error" in text
    check("12", "launchctl's refusal is said, and the LaunchAgent serves again from the old prefix",
          out.returncode != 0 and said and AGENT_PLIST.is_file() and bool(back)
          and str(USER_PREFIX) in command and user == ME and not DAEMON.exists()
          and not PREFIX.exists() and account_uid() is None and "node.yaml" in before and after == before,
          {"rc": out.returncode, "said": said, "agent plist": AGENT_PLIST.is_file(), "serving": bool(back),
           "user": user, "me": ME, "command": command[:160], "daemon": DAEMON.exists(),
           "prefix": PREFIX.exists(), "account": account_uid(), "state before": before, "after": after})


def phase_move(installer: Path, ctx: dict) -> None:
    say("11. the move to the daemon")
    # What a program running as the person could leave behind beforehand
    # (row 8 re-review A and B): an ACL entry that lets the person search
    # the old prefix -- no numeric chmod removes one -- and one that lets
    # them read its node.yaml. Neither may open the keys after the move.
    planted = {
        str(USER_PREFIX): run(["chmod", "+a", f"user:{ME} allow list,search,readattr,readsecurity",
                               str(USER_PREFIX)], timeout=20).returncode,
        "node.yaml": run(["chmod", "+a", f"user:{ME} allow read,readattr,readsecurity",
                          str(USER_PREFIX / "node.yaml")], timeout=20).returncode,
    }
    fact("ACL entries planted before the move (0 = planted)", planted)
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
    # The one sign-in the move asks for, once the root behind the machine
    # port answers: a person whose first try meets a root still starting
    # signs in again (seen on macos-15, where the first try came too soon).
    wait_for(lambda: api("GET", f"{ctx['control']}/healthz")[0] == 200, 120)

    def signed_in():
        status, body = api("POST", f"{base}/v1/auth/login", body={"passphrase": PASSPHRASE})
        if status != 200:
            fact("sign-in after the move answered", (status, str(body)[:200]))
        return (body or {}).get("sessionToken") if status == 200 else None

    token = wait_for(signed_in, 120, 5)
    _, node = api("GET", f"{base}/v1/node", token)
    node_yaml = root_read(PREFIX / "node.yaml")
    state_files = sorted(Path(p).name for p in sudo("sh", "-c", f"ls {PREFIX}/library-state*.json", timeout=20).stdout.split())
    # The old folder holds the machine's keys in clear: kept inside a folder
    # root made beside the new prefix -- root's, 0700, no ACL entry -- so
    # the entries planted above open nothing, and nothing is left in the
    # home. The person is told where it is and how to delete it.
    in_home = sorted(USER_PREFIX.parent.glob(USER_PREFIX.name + ".moved-*"))
    moved = kept_moves()
    keep = moved[-1] if moved else None
    kept_old = keep / USER_PREFIX.name if keep else None
    moved_owner = sudo("stat", "-f", "%Su:%Sg %Lp", str(keep), timeout=20).stdout.strip() if keep else ""
    moved_acl = acl_entries(keep) if keep else ["(nothing kept)"]
    moved_keys = bool(keep) and sudo("test", "-f", str(kept_old / "node.yaml")).returncode == 0
    person_reads = bool(keep) and run(["cat", str(kept_old / "node.yaml")], timeout=20).returncode == 0
    person_lists = bool(keep) and run(["ls", str(kept_old)], timeout=20).returncode == 0
    same_node = bool(identity_lines(node_yaml)) and identity_lines(node_yaml) == identity_lines(ctx["node_yaml"])
    check("11c", "node name and keys unchanged, Library state kept, the old folder kept in root's closed "
          "folder, which the person's own ACL entries do not open, its deletion said; no LaunchAgent",
          (node or {}).get("name") == ctx["name"] and same_node
          and set(ctx["state_files"]) <= set(state_files) and not USER_PREFIX.exists() and not in_home
          and moved_owner == "root:wheel 700" and not moved_acl and moved_keys
          and not person_reads and not person_lists
          and bool(keep) and f"sudo rm -rf '{keep}'" in text
          and not AGENT_PLIST.exists(),
          {"name": (node or {}).get("name"), "same keys": same_node, "state": state_files,
           "kept in": str(keep), "owner": moved_owner, "acl": moved_acl,
           "left in home": [str(m) for m in in_home],
           "person reads its node.yaml": person_reads, "person lists it": person_lists})
    # Re-review B: the copy restores no ACL entry, attribute or mode from
    # what it read; the new prefix and its node.yaml carry no entry.
    prefix_acl = acl_entries(PREFIX)
    node_acl = acl_entries(PREFIX / "node.yaml")
    fact("node.yaml after the move", sudo("stat", "-f", "%Su %Lp", str(PREFIX / "node.yaml"), timeout=20).stdout.strip())
    check("11f", "the new prefix and its node.yaml carry no ACL entry from the copy, though the old "
          "node.yaml had one",
          planted["node.yaml"] == 0 and not prefix_acl and not node_acl,
          {"planted": planted, "prefix acl": prefix_acl, "node.yaml acl": node_acl})
    agent_yaml = root_read(PREFIX / "agent.yaml")
    # The Keychain move must be exercised, not assumed: an old install that
    # was never on os_keyring proves nothing about it.
    check("11d", "the moved settings name the new prefix, and the Keychain mode became the passphrase file",
          ctx["keyring"] and str(USER_PREFIX) not in agent_yaml and str(PREFIX) in agent_yaml
          and re.search(r"^securityMode: passphrase_file$", agent_yaml, re.M) is not None,
          {"keychain exercised": ctx["keyring"], "securityMode": re.findall(r"^securityMode:.*$", agent_yaml, re.M)})
    control = ctx["control"]
    _, croot = api("GET", f"{control}/v1/config", token)
    cmode = (croot or {}).get("securityMode") if isinstance(croot, dict) else None
    before = listener_pid(PORT)
    sudo("launchctl", "kickstart", "-k", f"system/{LABEL}", timeout=60)
    wait_for(lambda: (lambda p: p if p and p != before else None)(listener_pid(PORT)), 90)
    wait_for(lambda: api("GET", f"{base}/healthz")[0] == 200, 120)
    agent_ok = wait_for(lambda: unlocked(base), 60)
    control_ok = wait_for(lambda: unlocked(control), 90)
    check("11e", "that one sign-in moved the root off the Keychain, and a kickstart unlocks agent and root by itself",
          ctx["keyring"] and cmode == "passphrase_file" and agent_ok is True and control_ok is True,
          {"keychain exercised": ctx["keyring"], "root's mode after sign-in": cmode,
           "agent": agent_ok, "control": control_ok})
    ctx["token"] = token
    phase_engine_after_move(ctx, text)
    phase_setting_after_move(ctx, text)
    phase_planted_after_move(ctx, text)
    phase_forged_approval_after_move(ctx, text)


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
    # Eugene's account passes through the home by the ACL entry the install
    # adds for its models group, whatever the home's own mode is.
    fact("home folder mode", run(["stat", "-f", "%Sp", str(HOME)]).stdout.strip())
    held = hold_default_ports()
    fact("held by this harness", f"{', '.join(map(str, HELD))} (pid {os.getpid()})")
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
            phase_engine_before_move(ctx)
            phase_setting_before_move(ctx)
            phase_plant_before_move(ctx)
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
                    phase_uninstall(installer, "14b", root_alone=True)
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
            phase_trust(ctx)
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
