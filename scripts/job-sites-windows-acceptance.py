"""Job Sites, slice 2b.2 on Windows (docs/design/job-sites-own-enrollment.md §2.2,
§2.4, §2.4.1, §3.2): each person's calls run as their own Windows account.

Run on a Windows 11 machine with two people signed in, from an **elevated**
shell (it makes a service and runs things as LocalSystem):

    python scripts/job-sites-windows-acceptance.py --person-account jessie
        --person-windows-password-file <unused> (not needed)

Before starting, `--person-account` (default `jessie`), a local standard
account, must be signed in (Switch user, sign in, switch back): on Windows a
person's worker runs only while they are signed in (J25 as revised). The
account running this script is the site's owner.

**What runs, all of it real and all of it throwaway:**
- a control root, in this process, on a free loopback port;
- an agent from this checkout, **as LocalSystem** (a one-shot scheduled task),
  in its own folder under `%ProgramData%`, on a free port, told it is a
  service install (`EUGENE_PLEXUS_AGENT_ACCEPTANCE_MECHANISM`) so it gives its
  site host an account of its own and plays the machine's starter;
- the site host, installed by that agent from the sibling checkout as the
  C1 service `EugenePlexusApp-site-host`, running as its virtual account;
- each person's worker, started by that agent into their own session with
  their own session token.

It never touches an installed Eugene: a machine's own `EugenePlexusAgent`
and its apps are checked unchanged before and after, and the run refuses to
start if `EugenePlexusApp-site-host` already exists. Everything it made is
removed at the end (`--keep` leaves the folder).

**Who a call ran as is read from the file it wrote**: Windows makes a new
file's owner the user of the token that made it (a filtered token's user,
not Administrators), so the owner's SID is the account the call ran as.

Checks (the done-when of §3, 2b.2):
1. The owner's link is made at the join, from the account that ran it; the
   site host runs as its own virtual account; the links file is not the site
   host's to write.
2. The owner's calls run as the owner's own account, unelevated.
3. A second person links **at the machine**, through the agent's `/link` page,
   from a program running in their own session; their worker starts as them.
4. Their calls run as them: their file is theirs; a file only the owner may
   read is refused to them, and one only they may read is refused to the
   owner. Nothing was granted by hand.
5. Someone with no link runs as the owner, inside the folder they were given
   (J27), and is refused anything else.
6. A worker started for an account it does not run as refuses to serve.
7. The second person removes their link from Workbench (root → agent): their
   worker stops; their calls run as the owner; their account is refused on
   the channel.
8. Neither the root nor the site host can make a link: no route makes one,
   and the site host's account may only read the links.
9. Signed out, a person's calls are refused, saying so (J25). This signs the
   second person out, so it runs last.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

SPECS = Path(__file__).resolve().parents[1]
REPOS = SPECS.parent
PASSPHRASE = "a long passphrase for job sites on windows"
PASSWORDS = {
    "troy": "troy's own long password",
    "jessie": "jessie's own long password",
    "bo": "bo's own long password",
}
CALLBACK = "http://127.0.0.1:9/callback"
SITE_HOST_SERVICE = "EugenePlexusApp-site-host"
PASSES: list[str] = []


def ok(message: str) -> None:
    PASSES.append(message)
    print(f"PASS {len(PASSES)}. {message}", flush=True)


def say(message: str) -> None:
    print(f"... {message}", flush=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def clean_environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


for _name in [n for n in os.environ if n.startswith("EUGENE_PLEXUS_")]:
    os.environ.pop(_name)


def wait_for(what: str, check: Any, seconds: float = 60.0, every: float = 0.5) -> Any:
    deadline = time.perf_counter() + seconds
    last: Any = None
    while time.perf_counter() < deadline:
        try:
            last = check()
        except Exception as exc:  # noqa: BLE001 - reported below
            last = exc
        if last and not isinstance(last, Exception):
            return last
        time.sleep(every)
    raise AssertionError(f"{what} (last: {last!r})")


# --------------------------------------------------------------------------- #
# Windows: accounts, sessions, files, services, LocalSystem
# --------------------------------------------------------------------------- #


def sid_of(name: str) -> str:
    import win32security

    sid, _domain, _kind = win32security.LookupAccountName(None, name)
    return str(win32security.ConvertSidToStringSid(sid))


def own_sid() -> str:
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    return str(win32security.ConvertSidToStringSid(user))


def sessions() -> dict[str, int]:
    """Each signed-in account's SID and a session of theirs."""
    import win32security
    import win32ts

    found: dict[str, int] = {}
    for session in win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE):
        if session["State"] not in (win32ts.WTSActive, win32ts.WTSDisconnected):
            continue
        user = win32ts.WTSQuerySessionInformation(
            None, session["SessionId"], win32ts.WTSUserName
        )
        domain = win32ts.WTSQuerySessionInformation(
            None, session["SessionId"], win32ts.WTSDomainName
        )
        if not user:
            continue
        try:
            sid, _, _ = win32security.LookupAccountName(None, f"{domain}\\{user}")
        except Exception:  # noqa: BLE001
            continue
        found.setdefault(str(win32security.ConvertSidToStringSid(sid)), int(session["SessionId"]))
    return found


def file_owner(path: Path) -> str:
    import win32security

    sd = win32security.GetFileSecurity(str(path), win32security.OWNER_SECURITY_INFORMATION)
    return str(win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()))


def icacls(path: Path, *args: str) -> None:
    done = subprocess.run(["icacls", str(path), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def service_state() -> dict[str, str]:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Service -Filter \"Name like 'EugenePlexus%'\" | "
         "Select-Object Name,State,StartName,PathName | ConvertTo-Json -Compress"],
        capture_output=True, text=True,
    )
    raw = json.loads(done.stdout or "[]")
    rows = raw if isinstance(raw, list) else [raw]
    return {r["Name"]: f"{r['State']}|{r['StartName']}|{r['PathName']}" for r in rows}


def processes(pattern: str) -> list[dict[str, Any]]:
    """Processes whose command line contains `pattern`, with their owners."""
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
        "$_.CommandLine -like '*"
        + pattern
        + "*' } | ForEach-Object { $o = Invoke-CimMethod -InputObject $_ -MethodName GetOwnerSid; "
        "[pscustomobject]@{Pid=$_.ProcessId; Sid=$o.Sid; Session=$_.SessionId; "
        "Line=$_.CommandLine} } | ConvertTo-Json -Compress"
    )
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True)
    raw = json.loads(done.stdout or "[]")
    return raw if isinstance(raw, list) else [raw]


class System:
    """One-shot scheduled tasks run as LocalSystem, each a Python script."""

    def __init__(self, work: Path, python: Path) -> None:
        import win32com.client

        self.work, self.python = work, python
        self.svc = win32com.client.Dispatch("Schedule.Service")
        self.svc.Connect()
        self.folder = self.svc.GetFolder("\\")
        self.names: list[str] = []

    def start(self, name: str, *args: str, limit: str = "PT0S") -> None:
        task = self.svc.NewTask(0)
        task.Principal.UserId = "NT AUTHORITY\\SYSTEM"
        task.Principal.LogonType = 5  # TASK_LOGON_SERVICE_ACCOUNT
        task.Principal.RunLevel = 1
        task.Settings.ExecutionTimeLimit = limit
        task.Settings.DisallowStartIfOnBatteries = False
        task.Settings.StopIfGoingOnBatteries = False
        action = task.Actions.Create(0)
        action.Path = str(self.python)
        action.Arguments = subprocess.list2cmdline([str(a) for a in args])
        action.WorkingDirectory = str(self.work)
        self.folder.RegisterTaskDefinition(name, task, 6, "NT AUTHORITY\\SYSTEM", None, 5)
        self.names.append(name)
        self.folder.GetTask(name).Run(None)

    def run(self, name: str, script: Path, *args: str, seconds: float = 120) -> dict[str, Any]:
        out = self.work / "results" / f"{name}.json"
        out.unlink(missing_ok=True)
        self.start(name, str(script), str(out), *args, limit="PT10M")
        found = wait_for(f"{name} never finished", lambda: out.exists() and out.stat().st_size,
                         seconds)
        assert found
        time.sleep(0.2)
        return json.loads(out.read_text(encoding="utf-8"))

    def close(self) -> None:
        for name in self.names:
            try:
                self.folder.GetTask(name).Stop(0)
                self.folder.DeleteTask(name, 0)
            except Exception:  # noqa: BLE001 - already gone
                pass


# Scripts a LocalSystem task runs, and one a person's session runs.

AGENT_LAUNCHER = r'''
import os, sys, json
spec = json.load(open(sys.argv[2], encoding="utf-8"))
os.environ.update(spec["env"])
log = open(spec["log"], "a", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr = log
sys.argv = ["eugene-plexus-agent", "--unattended"]
from eugene_plexus_agent.__main__ import main
main(["--unattended"])
'''

IN_SESSION = r'''
"""As LocalSystem: run a command in a signed-in account's own session, with
its own session token, and wait for it (what the agent's starter does)."""
import json, subprocess, sys
import win32con, win32event, win32process, win32profile, win32security, win32ts
out, sid, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]
result = {}
try:
    session = None
    for s in win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE):
        try:
            token = win32ts.WTSQueryUserToken(s["SessionId"])
        except Exception:
            continue
        user = win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(token, win32security.TokenUser)[0])
        if user == sid:
            session = token
            break
    if session is None:
        raise RuntimeError("no session for " + sid)
    env = win32profile.CreateEnvironmentBlock(session, False)
    si = win32process.STARTUPINFO()
    si.lpDesktop = "winsta0\\default"
    si.dwFlags = win32con.STARTF_USESHOWWINDOW
    si.wShowWindow = win32con.SW_HIDE
    hp, ht, pid, _ = win32process.CreateProcessAsUser(
        session, None, subprocess.list2cmdline(cmd), None, None, False,
        win32process.CREATE_NO_WINDOW | win32con.CREATE_UNICODE_ENVIRONMENT,
        env, env.get("USERPROFILE"), si)
    win32event.WaitForSingleObject(hp, 120000)
    result = {"code": win32process.GetExitCodeProcess(hp), "pid": pid}
except Exception as exc:
    result = {"error": repr(exc)}
json.dump(result, open(out, "w", encoding="utf-8"))
'''

LINK_CLIENT = r'''
"""In a person's own session: open the link page, sign in, confirm."""
import http.cookiejar, json, re, sys, urllib.error, urllib.parse, urllib.request
base, name, password_file, out = sys.argv[1:5]
password = open(password_file, encoding="utf-8").read().strip()
jar = http.cookiejar.CookieJar()
class Stop(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
plain = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
held = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar), Stop)
def where(url, data=None):
    try:
        held.open(url, data=data)
    except urllib.error.HTTPError as exc:
        if exc.code in (302, 303):
            return exc.headers["Location"]
        raise
    raise RuntimeError("no redirect from " + url)
result = {}
try:
    first = plain.open(base + "/link").read().decode()
    result["page"] = re.sub(r"<[^>]+>", " ", first)
    authorize = where(base + "/link/start")
    page = plain.open(base + authorize).read().decode()
    request = re.search(r'name="request" value="([^"]+)"', page).group(1)
    form = urllib.parse.urlencode({"request": request, "name": name, "password": password}).encode()
    callback = where(base + "/oidc/authorize", form)
    confirm = plain.open(callback).read().decode()
    result["confirm"] = re.sub(r"<[^>]+>", " ", confirm)
    csrf = re.search(r"name=csrf value='([^']+)'", confirm).group(1)
    done = plain.open(base + "/link/confirm", urllib.parse.urlencode({"csrf": csrf}).encode()).read().decode()
    result["done"] = re.sub(r"<[^>]+>", " ", done)
except Exception as exc:
    result["error"] = repr(exc)
json.dump(result, open(out, "w", encoding="utf-8"))
'''

RAW_CLIENT = r'''
"""In a person's own session: connect to the site host's channel directly."""
import asyncio, json, sys
from eugene_plexus_site_host import local_channel
channel, host, out = sys.argv[1:4]
async def go():
    conn = await local_channel.connect(channel, host, {"protocol": 1})
    first = await asyncio.wait_for(conn.receive(), 10)
    second = await asyncio.wait_for(conn.receive(), 10)
    return {"first": first, "then": second}
try:
    result = asyncio.run(go())
except Exception as exc:
    result = {"error": repr(exc)}
json.dump(result, open(out, "w", encoding="utf-8"))
'''


# --------------------------------------------------------------------------- #
# The root, in this process, and Workbench played by its own credentials
# --------------------------------------------------------------------------- #


def start_root(state: Path, port: int) -> Any:
    import uvicorn
    from eugene_plexus_control.app import create_app
    from eugene_plexus_control.settings import Settings

    app = create_app(Settings(config_file=state / "control.yaml", state_dir=state / "state"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for("the root did not start", lambda: socket.create_connection(("127.0.0.1", port), 1))
    return server, thread


def sign_in(http: Any, control: str, client: dict[str, Any], name: str, password: str) -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    page = http.get(f"{control}/oidc/authorize", params={
        "response_type": "code", "client_id": client["client"]["clientId"],
        "redirect_uri": CALLBACK, "scope": "openid profile", "state": "s", "nonce": "n",
        "code_challenge": challenge.rstrip(b"=").decode(), "code_challenge_method": "S256"})
    request = re.search(r'name="request" value="([^"]+)"', page.text)
    assert request, page.text[:300]
    answer = http.post(f"{control}/oidc/authorize", follow_redirects=False,
                       data={"request": request.group(1), "name": name, "password": password})
    assert answer.status_code == 302, answer.text[:300]
    code = re.search(r"code=([^&]+)", answer.headers["location"])
    assert code
    tokens = http.post(f"{control}/oidc/token",
                       auth=(client["client"]["clientId"], client["clientSecret"]),
                       data={"grant_type": "authorization_code", "code": code.group(1),
                             "code_verifier": verifier, "redirect_uri": CALLBACK})
    assert tokens.status_code == 200, tokens.text
    return str(tokens.json()["refresh_token"])


def rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": secrets.token_hex(4), "method": method, "params": {
        **(params or {}), "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                    "io.modelcontextprotocol/clientCapabilities": {}}}}


class Workbench:
    def __init__(self, http: Any, control: str, client: dict[str, Any]) -> None:
        self.http, self.control, self.client = http, control, client

    def call(self, route: str, token: str, /, **body: Any) -> Any:
        return self.http.post(f"{self.control}/oidc/{route}", timeout=60,
                              auth=(self.client["client"]["clientId"], self.client["clientSecret"]),
                              json={"refreshToken": token, **body})

    def tool(self, token: str, site: str, name: str, **arguments: Any) -> dict[str, Any]:
        answer = self.call("sites/mcp", token, site=site, server="files",
                           request=rpc("tools/call", {"name": name, "arguments": arguments}))
        assert answer.status_code in (200, 422, 503), answer.text
        return dict(answer.json())


def text_of(answer: dict[str, Any]) -> str:
    return json.dumps(answer.get("response") or {}) + str(answer.get("message") or "")


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def run(args: argparse.Namespace) -> None:
    import httpx

    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise SystemExit("run this from an elevated shell: it makes a service and uses LocalSystem")
    person_sid = sid_of(args.person_account)
    owner_sid = own_sid()
    signed_in = sessions()
    if person_sid not in signed_in:
        raise SystemExit(
            f"{args.person_account} is not signed in. Switch user, sign in as "
            f"{args.person_account}, switch back, and run this again (J25)."
        )
    if owner_sid not in signed_in:
        raise SystemExit("the account running this must be signed in at the machine")
    before = service_state()
    if SITE_HOST_SERVICE in before:
        raise SystemExit(f"{SITE_HOST_SERVICE} exists already: this run would collide with it")

    tag = secrets.token_hex(4)
    work = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / f"EugenePlexusAcceptance-{tag}"
    for name in ("agent", "root", "results", "scripts", "shared"):
        (work / name).mkdir(parents=True)
    icacls(work / "results", "/grant", "*S-1-5-32-545:(OI)(CI)M")
    icacls(work / "scripts", "/grant", "*S-1-5-32-545:(OI)(CI)RX")
    icacls(work / "shared", "/grant", "*S-1-5-32-545:(OI)(CI)M")
    scripts = work / "scripts"
    for name, text in (("agent_launcher.py", AGENT_LAUNCHER), ("in_session.py", IN_SESSION),
                       ("link_client.py", LINK_CLIENT), ("raw_client.py", RAW_CLIENT)):
        (scripts / name).write_text(text, encoding="utf-8")
    python = Path(sys.executable)
    system = System(work, python)
    root_port, agent_port = free_port(), free_port()
    control = f"http://127.0.0.1:{root_port}"
    agent_url = f"http://127.0.0.1:{agent_port}"
    config_file = work / "agent" / "agent.yaml"
    server, thread = start_root(work / "root", root_port)
    say(f"working in {work}; root {control}; agent {agent_url}")
    try:
        http = httpx.Client(trust_env=False, timeout=60)
        assert http.post(f"{control}/v1/auth/initialize", json={"passphrase": PASSPHRASE}).status_code == 204
        session = http.post(f"{control}/v1/auth/login", json={"passphrase": PASSPHRASE}).json()
        http.headers["Authorization"] = "Bearer " + session["sessionToken"]
        client = http.post(f"{control}/v1/oidc/clients", json={
            "name": "Workbench", "owner": "app:workbench@root", "redirectUris": [CALLBACK]}).json()
        for name, password in PASSWORDS.items():
            made = http.post(f"{control}/v1/people", json={
                "name": name, "password": password, "apps": [client["client"]["clientId"]]})
            assert made.status_code == 201, made.text
        people = {p["name"]: p["id"] for p in http.get(f"{control}/v1/people").json()["people"]}
        assert http.patch(f"{control}/v1/config", json={"siteJoinUrl": control}).status_code == 200
        plain = httpx.Client(trust_env=False, timeout=60)
        bench = Workbench(plain, control, client)
        token = {name: sign_in(plain, control, client, name, pw) for name, pw in PASSWORDS.items()}

        # ---- the node: joined here, then run as LocalSystem -------------------
        env = {**clean_environment(),
               "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(config_file),
               "EUGENE_PLEXUS_AGENT_BIND_PORT": str(agent_port),
               "EUGENE_PLEXUS_AGENT_ACCEPTANCE_MECHANISM": "windows_service",
               "EUGENE_PLEXUS_AGENT_SITE_HOST_SOURCE": str(REPOS / "site-host"),
               "PATH": str(python.parent) + os.pathsep + os.environ.get("PATH", "")}
        join_token = http.post(f"{control}/v1/nodes/join-token", json={}).json()["token"]
        joined = subprocess.run(
            [str(python), "-m", "eugene_plexus_agent", "join", "--control", control,
             "--token", join_token, "--name", f"acceptance-{tag}"],
            env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        assert joined.returncode == 0, joined.stdout + joined.stderr
        spec = work / "agent" / "launch.json"
        spec.write_text(json.dumps({"env": env, "log": str(work / "agent" / "agent.log")}),
                        encoding="utf-8")
        system.start(f"EugenePlexusAcceptance-agent-{tag}", str(scripts / "agent_launcher.py"),
                     "-", str(spec))
        wait_for("the agent did not answer", lambda: http.get(f"{agent_url}/healthz").status_code == 200,
                 90)
        say("the agent runs as LocalSystem")

        # ---- 1. the owner's join, and the link it makes -----------------------
        invited = http.post(f"{control}/v1/sites/invitations",
                            json={"owner": people["troy"], "label": f"acceptance-{tag}"})
        assert invited.status_code == 201, invited.text
        site_join = subprocess.run(
            [str(python), "-m", "eugene_plexus_agent", "site", "join", "--url", control,
             "--token", invited.json()["token"], "--owner", "troy", "--label",
             f"acceptance-{tag}", "--password-stdin"],
            env=env, input=PASSWORDS["troy"] + "\n", capture_output=True, text=True, timeout=1200)
        assert site_join.returncode == 0, site_join.stdout + site_join.stderr
        links_file = work / "agent" / "site" / "links.json"
        links = json.loads(links_file.read_text(encoding="utf-8"))["links"]
        assert [(link["subject"], link["account"]) for link in links] == [(people["troy"], owner_sid)], links
        site_id = json.loads((work / "agent" / "apps" / "site-host" / "data" / "site.json")
                             .read_text(encoding="utf-8"))["site"]
        state = service_state()
        assert SITE_HOST_SERVICE in state and "NT SERVICE\\EugenePlexusApp-site-host" in state[SITE_HOST_SERVICE], state
        host_sid = sid_of("NT SERVICE\\EugenePlexusApp-site-host")

        def site_view() -> dict[str, Any]:
            sites = bench.call("job-sites", token["troy"]).json()["sites"]
            return next(s for s in sites if s["id"] == site_id)

        wait_for("the owner's worker never connected", lambda: any(
            x["available"] for x in site_view().get("links") or []), 180)
        import win32security

        dacl = win32security.GetFileSecurity(
            str(links_file), win32security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
        writes = 0x2 | 0x4 | 0x10 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000
        for index in range(dacl.GetAceCount()):
            (kind, _flags), mask, sid = dacl.GetAce(index)
            who = win32security.ConvertSidToStringSid(sid)
            if kind == 0 and mask & writes:
                assert who in ("S-1-5-18", "S-1-5-32-544"), (who, hex(mask))
            if who == host_sid:
                assert not mask & writes, hex(mask)
        ok("the owner's link is made at the join, from the account that ran it; the site host "
           "runs as its own virtual account; the links file is SYSTEM's and Administrators' to "
           "write, and the site host's account may only read it")

        # ---- 2. the owner's calls run as the owner ----------------------------
        shared = work / "shared"
        (shared / "for-everyone.txt").write_text("hello", encoding="utf-8")
        owner_only = shared / "owner-only.txt"
        owner_only.write_text("the owner's alone", encoding="utf-8")
        icacls(owner_only, "/inheritance:r", "/grant:r", f"*{owner_sid}:F", "*S-1-5-18:F")
        added = bench.call(f"job-sites/{site_id}/folders", token["troy"], name="Shared",
                           path=str(shared), writable=True)
        assert added.status_code == 201, added.text
        folder_id = added.json()["id"]
        granted = bench.call(f"job-sites/{site_id}/folders/{folder_id}/people", token["troy"],
                             people=[{"name": n, "writable": True} for n in PASSWORDS])
        assert granted.status_code == 200, granted.text
        wait_for("the grant never reported", lambda: len(site_view()["folders"][0]["people"]) == 3)
        wrote = bench.tool(token["troy"], site_id, "write_text", folder="Shared",
                           path="by-troy.txt", text="troy", expectedSha256="")
        assert wrote["status"] == "done", wrote
        assert file_owner(shared / "by-troy.txt") == owner_sid
        workers = processes("eugene_plexus_site_host.worker")
        assert any(w["Sid"] == owner_sid for w in workers), workers
        ok("the owner's calls run as the owner's own account: the file their call wrote is "
           "theirs (a filtered token's user, not Administrators)")

        # ---- 3. a second person links at the machine --------------------------
        password_file = scripts / "person-password.txt"
        password_file.write_text(PASSWORDS["jessie"], encoding="utf-8")
        site_python = next((work / "agent" / "apps" / "site-host" / "versions").glob("*/venv/Scripts/python.exe"))
        out = work / "results" / "link.json"
        result = system.run(f"EugenePlexusAcceptance-link-{tag}", scripts / "in_session.py",
                            person_sid, str(site_python), "-I", str(scripts / "link_client.py"),
                            agent_url, "jessie", str(password_file), str(out))
        assert result.get("code") == 0, result
        linking = json.loads(out.read_text(encoding="utf-8"))
        assert "error" not in linking, linking
        assert args.person_account.lower() in linking["page"].lower(), linking["page"]
        assert "Link Eugene person" in linking["confirm"] and "Done." in linking["done"], linking
        links = json.loads(links_file.read_text(encoding="utf-8"))["links"]
        assert {(x["subject"], x["account"]) for x in links} == {
            (people["troy"], owner_sid), (people["jessie"], person_sid)}, links
        wait_for("her worker never started as her", lambda: any(
            w["Sid"] == person_sid for w in processes("eugene_plexus_site_host.worker")), 60)
        wait_for("her worker never connected", lambda: sum(
            1 for x in site_view().get("links") or [] if x["available"]) == 2, 60)
        ok("a second person links at the machine, through the agent's own page, from a program "
           "in her own session signed in to Eugene as herself; her worker starts as her")

        # ---- 4. her calls run as her ------------------------------------------
        wrote = bench.tool(token["jessie"], site_id, "write_text", folder="Shared",
                           path="by-jessie.txt", text="jessie", expectedSha256="")
        assert wrote["status"] == "done", wrote
        assert file_owner(shared / "by-jessie.txt") == person_sid
        refused = bench.tool(token["jessie"], site_id, "read_text", folder="Shared",
                             path="owner-only.txt")
        assert "owner's alone" not in text_of(refused), refused
        hers = shared / "hers-only.txt"
        hers.write_text("hers alone", encoding="utf-8")
        icacls(hers, "/inheritance:r", "/grant:r", f"*{person_sid}:F", "*S-1-5-18:F")
        theirs = bench.tool(token["troy"], site_id, "read_text", folder="Shared",
                            path="hers-only.txt")
        assert "hers alone" not in text_of(theirs), theirs
        read = bench.tool(token["jessie"], site_id, "read_text", folder="Shared",
                          path="hers-only.txt")
        assert "hers alone" in text_of(read), read
        ok("her calls run as her: her file is hers, the owner's private file is refused to "
           "her and hers to the owner, by Windows; nothing was granted by hand")

        # ---- 5. no link: the owner's worker, inside the folder ----------------
        wrote = bench.tool(token["bo"], site_id, "write_text", folder="Shared",
                           path="by-bo.txt", text="bo", expectedSha256="")
        assert wrote["status"] == "done", wrote
        assert file_owner(shared / "by-bo.txt") == owner_sid
        outside = bench.tool(token["bo"], site_id, "read_text", folder="Shared",
                             path="..\\agent\\agent.yaml")
        assert outside["status"] == "failed" or "error" in text_of(outside).lower(), outside
        ok("someone with no link runs as the owner, inside the folder the owner gave them, and "
           "cannot leave it (J27)")

        # ---- 6. a worker as the wrong account ---------------------------------
        wrong = subprocess.run(
            [str(site_python), "-I", "-m", "eugene_plexus_site_host.worker", "--account",
             person_sid, "--channel", "\\\\.\\pipe\\nowhere", "--host", host_sid],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        assert wrong.returncode != 0 and "not the account it was started for" in wrong.stderr, (
            wrong.returncode, wrong.stderr)
        ok("a worker started for an account it does not run as refuses to serve")

        # ---- 7. she removes her link from Workbench ----------------------------
        removed = bench.call("sites/link/remove", token["jessie"], site=site_id)
        assert removed.status_code == 204, removed.text
        links = json.loads(links_file.read_text(encoding="utf-8"))["links"]
        assert [x["account"] for x in links] == [owner_sid], links
        wait_for("her worker never stopped", lambda: not any(
            w["Sid"] == person_sid for w in processes("eugene_plexus_site_host.worker")), 60)
        wrote = bench.tool(token["jessie"], site_id, "write_text", folder="Shared",
                           path="jessie-unlinked.txt", text="as the owner", expectedSha256="")
        assert wrote["status"] == "done", wrote
        assert file_owner(shared / "jessie-unlinked.txt") == owner_sid
        from eugene_plexus_agent.site_host import channel_name as name_of

        channel_name = name_of(config_file.parent)
        raw_out = work / "results" / "raw.json"
        result = system.run(f"EugenePlexusAcceptance-raw-{tag}", scripts / "in_session.py",
                            person_sid, str(site_python), "-I", str(scripts / "raw_client.py"),
                            channel_name, host_sid, str(raw_out))
        raw = json.loads(raw_out.read_text(encoding="utf-8"))
        assert raw.get("first", {}).get("t") == "refused", raw
        ok("she removes her link from Workbench: the root asks the agent, her worker stops, her "
           "calls run as the owner, and her account is refused on the site host's channel")

        # ---- 8. no link can be made from the root or the site host ------------
        for method, path in (("POST", "/v1/site/links"), ("PUT", "/v1/site/links/x"),
                             ("POST", "/v1/site/links/x")):
            answer = http.request(method, f"{agent_url}{path}", json={})
            assert answer.status_code in (404, 405), (method, path, answer.status_code)
        root_paths = {getattr(r, "path", "") for r in server.config.app.routes}
        assert {p for p in root_paths if "link" in p} == {
            "/v1/sites/links/check", "/oidc/sites/link/remove"}, root_paths
        ok("no route makes a link: the agent's only one removes, the root has none, and the "
           "site host's account may only read the links file (check 1)")

        # ---- 9. signed out, refused -------------------------------------------
        relinked = system.run(f"EugenePlexusAcceptance-relink-{tag}", scripts / "in_session.py",
                              person_sid, str(site_python), "-I", str(scripts / "link_client.py"),
                              agent_url, "jessie", str(password_file), str(out))
        assert relinked.get("code") == 0, relinked
        wait_for("her worker never came back", lambda: any(
            w["Sid"] == person_sid for w in processes("eugene_plexus_site_host.worker")), 60)
        session_id = sessions()[person_sid]
        subprocess.run(["logoff", str(session_id)], check=False)
        wait_for("her session never ended", lambda: person_sid not in sessions(), 60)
        wait_for("her worker never ended", lambda: not any(
            w["Sid"] == person_sid for w in processes("eugene_plexus_site_host.worker")), 60)
        signed_out = wait_for("her call was never refused for being signed out", lambda: (
            lambda a: a if a["status"] == "failed" and "not signed in" in a["message"] else None)(
                bench.tool(token["jessie"], site_id, "read_text", folder="Shared",
                           path="for-everyone.txt")), 60)
        assert signed_out
        ok("signed out, her calls are refused saying she is not signed in there (J25)")
    finally:
        say("tearing down")
        try:
            subprocess.run([str(python), "-m", "eugene_plexus_agent", "site", "leave"],
                           env={**clean_environment(), "EUGENE_PLEXUS_AGENT_CONFIG_FILE": str(config_file)},
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            pass
        system.close()
        for line in subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout.splitlines():
            if f"127.0.0.1:{agent_port} " in line and "LISTENING" in line:
                subprocess.run(["taskkill", "/F", "/T", "/PID", line.split()[-1]],
                               capture_output=True)
        subprocess.run(["sc.exe", "stop", SITE_HOST_SERVICE], capture_output=True)
        time.sleep(2)
        subprocess.run(["sc.exe", "delete", SITE_HOST_SERVICE], capture_output=True)
        server.should_exit = True
        thread.join(timeout=10)
        after = service_state()
        assert {k: v for k, v in after.items() if k != SITE_HOST_SERVICE} == before, (before, after)
        # The files the run made one account's alone refuse even an
        # administrator's delete: take them back first.
        shared_dir = work / "shared"
        subprocess.run(["takeown", "/f", str(shared_dir), "/r", "/d", "y"], capture_output=True)
        subprocess.run(["icacls", str(shared_dir), "/reset", "/t", "/q"], capture_output=True)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"kept {work}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--person-account", default="jessie")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("this run is Windows only; job-sites-acceptance.py covers Linux")
    run(args)
    print(f"{len(PASSES)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
