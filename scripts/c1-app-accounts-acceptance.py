#!/usr/bin/env python3
"""C1 (workbench.md §2): an app cannot read the install's keys.

Runs on a GitHub runner, never on a developer's box: it installs Eugene the
way a person does, as the machine's service -- `install.ps1` elevated on
Windows (LocalSystem, %ProgramData%), `sudo install.sh` on Linux (the
`eugene-plexus` account, /var/lib/eugene-plexus) -- onboards it through the
API, installs two copies of the app fixture as custom apps, and asks each
one, from inside its own process, what it can open.

The claim is about files and accounts, so the evidence is the app's own
answer: who it runs as, and which files under the install's prefix it could
open (names only; `GET /probe` never returns a byte of their contents), plus
on Windows which of its account's stored credentials mention Eugene.

**Before C1 this run fails, and that is the point**: an app runs as the
agent's own account and reads `node.yaml`, `agent.yaml`, the control root's
files, the other app's key and the keyring. After C1 each of those is
refused and the app still has its own directory and its key.

Try a candidate before pinning it: EP_PIN_AGENT (and the other EP_PIN_*)
take a full SHA, substituted into a copy of the installer.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "app-fixture"
PASSPHRASE = "c1-disposable-passphrase-on-a-runner"
WINDOWS = sys.platform == "win32"
PREFIX = (
    Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "EugenePlexus"
    if WINDOWS
    else Path("/var/lib/eugene-plexus")
)
AGENT = "http://127.0.0.1:8079"
CONTROL = "http://127.0.0.1:8083"
#: The account the agent runs as on each service install. An app in this
#: account is the defect.
AGENT_ACCOUNT = "nt authority\\system" if WINDOWS else "eugene-plexus"
APPS = ("probe-a", "probe-b")
#: Trees an app is meant to read: interpreters and code, nothing secret.
SHARED_TREES = ("venv/", "pythons/", "bin/", "ui/", "apps/pythons/", "apps/launcher/")

PINS_SH = {
    "AGENT": "AGENT",
    "CONTROL": "CONTROL",
    "GATEWAY": "GATEWAY",
    "DRIVER": "DRIVER",
    "LIBRARY": "LIBRARY",
    "TOOL_DRIVER": "TOOL_DRIVER",
}
PINS_PS1 = {
    "AGENT": "agent",
    "CONTROL": "control",
    "GATEWAY": "gateway",
    "DRIVER": "inference-driver",
    "LIBRARY": "library",
    "TOOL_DRIVER": "tool-driver",
}

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


def fact(key: str, value: object) -> None:
    FACTS[key] = value
    print(f"  FACT  {key}: {value}", flush=True)


def say(text: str) -> None:
    print(f"\n== {text}", flush=True)


class Abort(Exception):
    pass


def must(number: str, claim: str, passed: bool, detail: object = "") -> None:
    if not check(number, claim, passed, detail):
        raise Abort(f"{number}: {claim}")


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #

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
            raw, status = response.read().decode("utf-8", errors="replace"), response.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode("utf-8", errors="replace"), e.code
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
            value = predicate()
        except Exception:  # noqa: BLE001 - a probe that raised is "not yet"
            value = None
        if value:
            return value
        time.sleep(interval)
    return None


def healthy(url: str):
    return lambda: api("GET", f"{url}/healthz")[0] == 200


# --------------------------------------------------------------------------- #
# the install
# --------------------------------------------------------------------------- #


def installer_copy(workdir: Path) -> Path:
    """The installer as checked out, with any candidate pin substituted."""
    name = "install.ps1" if WINDOWS else "install.sh"
    text = (HERE / name).read_text(encoding="utf-8")
    for env_name, key in (PINS_PS1 if WINDOWS else PINS_SH).items():
        override = os.environ.get(f"EP_PIN_{env_name}", "").strip()
        if not override:
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", override):
            raise SystemExit(f"EP_PIN_{env_name} must be a full 40-character SHA")
        if WINDOWS:
            pattern = rf'^(\s*"{re.escape(key)}"\s*=\s*")[0-9a-f]{{40}}"'
            text, count = re.subn(pattern, rf'\g<1>{override}"', text, flags=re.M)
        else:
            text, count = re.subn(rf"^PIN_{key}=[0-9a-f]{{40}}", f"PIN_{key}={override}", text, flags=re.M)
        assert count == 1, env_name
        fact(f"candidate pin {env_name.lower()}", override)
    copy = workdir / name
    # PowerShell 5.1 reads a BOM-less script as the ANSI code page.
    copy.write_text(text, encoding="utf-8-sig" if WINDOWS else "utf-8")
    return copy


def phase_install(installer: Path) -> None:
    say("the service install, as a person runs it")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    if WINDOWS:
        # A runner step's shell is PowerShell 7, whose PSModulePath names
        # its own modules first. Left as it is on purpose: install.ps1
        # drops 7's folders itself, and this run is what proves it.
        argv = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer), "-NoTray"]
    else:
        argv = ["sudo", "-E", "sh", str(installer)]
    started = time.perf_counter()
    out = subprocess.run(argv, capture_output=True, text=True, timeout=1800, env=env)
    fact("install seconds", round(time.perf_counter() - started, 1))
    text = out.stdout + out.stderr
    ok = out.returncode == 0 and "Eugene Plexus is running" in text
    if not ok:
        fact("installer exit code", out.returncode)
        print(text[-4000:], flush=True)
        # install.ps1 keeps a transcript of every run; it holds what the
        # console capture can lose when a child script exits the host.
        logs = sorted(Path(tempfile.gettempdir()).glob("eugene-plexus-install-*.log"),
                      key=lambda p: p.stat().st_mtime)
        if logs:
            print(f"--- {logs[-1]} (tail)", flush=True)
            print(logs[-1].read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
    must("1", "the installer completes and says Eugene is running", ok, text[-1200:])
    must("2", "the agent answers on 8079", bool(wait_for(healthy(AGENT), 120)))


def phase_onboard() -> str:
    say("onboarding through the API, as the wizard does")
    must("3", "the control root came up", bool(wait_for(healthy(CONTROL), 180)))
    status, _ = api("POST", f"{CONTROL}/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    must("4", "control initializes", status == 204, status)
    status, body = api("POST", f"{AGENT}/v1/auth/initialize", body={"passphrase": PASSPHRASE})
    must("5", "the agent initializes", status == 200 and bool((body or {}).get("sessionToken")), body)
    wait_for(healthy(CONTROL), 120)
    _, body = api("POST", f"{CONTROL}/v1/auth/login", body={"passphrase": PASSPHRASE})
    ctoken = (body or {}).get("sessionToken")
    status, body = api("POST", f"{CONTROL}/v1/nodes/join-token", ctoken,
                       {"nodeName": "c1-node", "grants": ["gateway"]})
    join = (body or {}).get("token") if status in (200, 201) else None
    must("6", "control mints a join token", bool(join), body)
    _, login = api("POST", f"{AGENT}/v1/auth/login", body={"passphrase": PASSPHRASE})
    status, body = api("POST", f"{AGENT}/v1/node/enroll", (login or {}).get("sessionToken"),
                       {"controlUrl": CONTROL, "token": join, "name": "c1-node"}, timeout=120)
    must("7", "the agent enrolls with its own control root", status == 200, body)
    for url in (AGENT, CONTROL):
        wait_for(healthy(url), 120)
    time.sleep(2)
    status, body = api("POST", f"{AGENT}/v1/auth/login", body={"passphrase": PASSPHRASE})
    must("8", "a session after enrollment", status == 200, body)
    token = body["sessionToken"]

    # The wizard's keyring choice where this host has one, so the keyring
    # holds what it holds on a real install.
    _, auth = api("GET", f"{AGENT}/v1/auth/status")
    keyring = bool((auth or {}).get("keyringAvailable"))
    fact("keyring available to the service", keyring)
    fact("agent securityMode", (auth or {}).get("securityMode"))
    if keyring:
        _, clogin = api("POST", f"{CONTROL}/v1/auth/login", body={"passphrase": PASSPHRASE})
        api("PATCH", f"{AGENT}/v1/config", token, {"securityMode": "os_keyring"})
        api("PATCH", f"{CONTROL}/v1/config", (clogin or {}).get("sessionToken"), {"securityMode": "os_keyring"})
        api("POST", f"{CONTROL}/v1/auth/login", body={"passphrase": PASSPHRASE})
        _, login = api("POST", f"{AGENT}/v1/auth/login", body={"passphrase": PASSPHRASE})
        token = (login or {}).get("sessionToken") or token
    return token


def fixture_source(workdir: Path) -> Path:
    """A copy of the fixture the service's account can read."""
    target = (Path(r"C:\ep-c1") if WINDOWS else Path("/tmp/ep-c1")) / "app-fixture"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(FIXTURE, target, ignore=shutil.ignore_patterns("__pycache__"))
    if not WINDOWS:
        subprocess.run(["chmod", "-R", "a+rX", str(target.parent)], check=False)
    return target


def phase_apps(token: str, source: Path) -> dict[str, dict]:
    say("two apps, installed as custom entries")
    status, _ = api("PATCH", f"{AGENT}/v1/config", token, {"allowCustomApps": True})
    must("9", "custom apps allowed", status == 200, status)
    found: dict[str, dict] = {}
    for app_id in APPS:
        manifest = {
            "id": app_id,
            "name": f"Probe {app_id[-1].upper()}",
            "source": str(source),
            "version": "dev-1",
            "package": "eugene-plexus-app-fixture",
            "entry": "eugene_plexus_app_fixture",
            "uses": ["inference"],
        }
        status, body = api("POST", f"{AGENT}/v1/app-catalogue/custom", token, manifest)
        must(f"10{app_id[-1]}", f"{app_id} added", status == 201, body)
        status, body = api("POST", f"{AGENT}/v1/apps/{app_id}/install", token)
        must(f"11{app_id[-1]}", f"{app_id}'s install starts", status in (200, 202), body)

        def finished(app_id=app_id):
            _, state = api("GET", f"{AGENT}/v1/apps/{app_id}/install", token)
            return state if (state or {}).get("state") in ("done", "failed", "cancelled") else None

        state = wait_for(finished, 900, 3) or {}
        must(f"12{app_id[-1]}", f"{app_id} installs", state.get("state") == "done", state)

        def running(app_id=app_id):
            _, app = api("GET", f"{AGENT}/v1/apps/{app_id}", token)
            return app if (app or {}).get("status") == "running" else None

        app = wait_for(running, 120, 2)
        must(f"13{app_id[-1]}", f"{app_id} is running and answers /healthz", bool(app),
             api("GET", f"{AGENT}/v1/apps/{app_id}", token)[1])
        found[app_id] = app
    return found


def probe(app: dict) -> dict:
    status, body = api("GET", f"http://127.0.0.1:{app['port']}/probe?root={PREFIX}", timeout=120)
    if status != 200 or not isinstance(body, dict):
        raise Abort(f"probe of {app['id']} answered {status}: {body}")
    return body


def phase_probe(apps: dict[str, dict]) -> None:
    say("what each app can open, asked from inside it")
    users = {app_id: str(probe(app)["user"]).lower() for app_id, app in apps.items()}
    # One account each: two apps in one account can reach each other's
    # processes, whatever the files say (C1's first Linux run shared a uid).
    check("28", "the two apps run as two different accounts", len(set(users.values())) == len(users), users)
    for app_id, app in apps.items():
        other = next(a for a in APPS if a != app_id)
        found = probe(app)
        readable: list[str] = found["readable"]
        user = str(found["user"]).lower()
        fact(f"{app_id} runs as", found["user"])
        fact(f"{app_id} walked", f"{found['walkedFiles']} files; unlistable {len(found['unlistable'])}")
        n = app_id[-1]
        check(f"20{n}", f"{app_id} does not run as the agent's account ({AGENT_ACCOUNT})",
              user != AGENT_ACCOUNT and not user.startswith(AGENT_ACCOUNT + " "), found["user"])
        check(f"21{n}", f"{app_id} cannot read node.yaml", "node.yaml" not in readable)
        check(f"22{n}", f"{app_id} cannot read agent.yaml", "agent.yaml" not in readable)
        if WINDOWS:
            creds = found.get("credentials") or []
            check(f"23{n}", f"{app_id} sees none of the install's keyring entries", not creds, creds)
        else:
            check(f"23{n}", f"{app_id} cannot read the passphrase file", "passphrase" not in readable)
        control = [p for p in readable if p.startswith("control")]
        check(f"24{n}", f"{app_id} cannot read the control root's files", not control, control[:10])
        theirs = [p for p in readable if p.startswith(f"apps/{other}/")]
        check(f"25{n}", f"{app_id} cannot read {other}'s directory, key included", not theirs, theirs[:10])
        own = f"apps/{app_id}/"
        leaks = [p for p in readable if not p.startswith(own) and not p.startswith(SHARED_TREES)]
        check(f"26{n}", f"{app_id} can read nothing else in the install", not leaks,
              f"{len(leaks)}: {leaks[:15]}")
        check(f"27{n}", f"{app_id} can still read its own key", found.get("keyFileReadable") is True,
              [p for p in readable if p.startswith(own)][:10])


def phase_service(token: str, apps: dict[str, dict]) -> None:
    say("what the install says about it, and the ingress")
    _, catalogue = api("GET", f"{AGENT}/v1/app-catalogue", token)
    check("30", "the catalogue says this install gives apps their own accounts",
          (catalogue or {}).get("ownAccounts") is True, (catalogue or {}).get("ownAccountsReason"))
    for app_id in apps:
        _, app = api("GET", f"{AGENT}/v1/apps/{app_id}", token)
        fact(f"{app_id} account (as the agent reports it)", (app or {}).get("account"))
        check(f"31{app_id[-1]}", f"{app_id} reports isolation own_account",
              (app or {}).get("isolation") == "own_account", (app or {}).get("isolation"))

    # The fixture prints one line at start; it reaches the Logs page only
    # through the launcher and POST /v1/logs, under the app's own name.
    def logged(app_id: str):
        status, page = api("GET", f"{AGENT}/v1/logs?source=app:%20{app_id}&tail=50", token)
        lines = (page or {}).get("lines") or [] if status == 200 else []
        return lines if any("fixture app on" in str(l.get("text")) for l in lines) else None

    for app_id in apps:
        found = wait_for(lambda app_id=app_id: logged(app_id), 60, 2)
        check(f"32{app_id[-1]}", f"what {app_id} printed is on the Logs page, as source 'app: {app_id}'",
              bool(found), api("GET", f"{AGENT}/v1/logs?contains=fixture&tail=20", token)[1])

    say("stop and start through the service manager")
    app_id = APPS[0]
    status, app = api("POST", f"{AGENT}/v1/apps/{app_id}/stop", token, timeout=120)
    gone = wait_for(lambda: api("GET", f"http://127.0.0.1:{apps[app_id]['port']}/healthz", timeout=3)[0] is None, 60, 2)
    check("33", f"stopping {app_id} stops its process", status == 200 and bool(gone), app)
    status, _ = api("POST", f"{AGENT}/v1/apps/{app_id}/start", token, timeout=120)

    def running():
        _, app = api("GET", f"{AGENT}/v1/apps/{app_id}", token)
        return app if (app or {}).get("status") == "running" else None

    check("34", f"starting {app_id} again brings it back", status == 200 and bool(wait_for(running, 120, 2)))

    say("uninstall removes the app's service")
    other = APPS[1]
    status, _ = api("DELETE", f"{AGENT}/v1/apps/{other}?purge=true", token, timeout=120)
    if WINDOWS:
        out = subprocess.run(["sc.exe", "query", f"EugenePlexusApp-{other}"], capture_output=True, text=True)
        removed = "1060" in (out.stdout + out.stderr)
        detail = (out.stdout + out.stderr).strip()[-200:]
    else:
        out = subprocess.run(["systemctl", "show", f"eugene-plexus-app@{other}.service", "--property=ActiveState"],
                             capture_output=True, text=True)
        removed = "ActiveState=active" not in out.stdout
        detail = out.stdout.strip()
    check("35", f"uninstalling {other} leaves no service running it", status == 204 and removed, detail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    fact("platform", f"{platform.system()} {platform.release()} {platform.machine()}")
    fact("prefix", PREFIX)
    workdir = Path(tempfile.mkdtemp(prefix="ep-c1-"))
    token: str | None = None
    try:
        phase_install(installer_copy(workdir))
        token = phase_onboard()
        apps = phase_apps(token, fixture_source(workdir))
        phase_probe(apps)
        phase_service(token, apps)
    except Abort as exc:
        print(f"\nABORTED at {exc}", flush=True)
    failed = [r for r in RESULTS if r["passed"] is False]
    if failed and token:
        # The agent's own words, read the way an operator would.
        _, page = api("GET", f"{AGENT}/v1/logs?tail=150", token)
        print("\n--- the agent's log (tail)", flush=True)
        for line in (page or {}).get("lines") or []:
            if "/healthz" in str(line.get("text")):
                continue  # the health polls drown everything else
            print(f"  {line.get('time')} [{line.get('source')}] {line.get('text')}", flush=True)
    if failed and not WINDOWS:
        # The root helper that starts and stops apps, which the agent's log
        # can only see from the outside.
        for argv in (
            ["sudo", "systemctl", "status", "--no-pager", "eugene-plexus-apps-ctl.path",
             "eugene-plexus-apps-ctl.service"],
            ["sudo", "journalctl", "--no-pager", "-n", "60", "-u", "eugene-plexus-apps-ctl.service",
             "-u", "eugene-plexus-apps-ctl.path"],
        ):
            out = subprocess.run(argv, capture_output=True, text=True, check=False)
            print(f"\n--- {' '.join(argv[1:])}\n{out.stdout}{out.stderr}", flush=True)
    passed = [r for r in RESULTS if r["passed"]]
    print(f"\n{len(passed)} passed, {len(failed)} failed", flush=True)
    if args.report:
        args.report.write_text(json.dumps({"facts": {k: str(v) for k, v in FACTS.items()},
                                           "results": RESULTS}, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
