"""Row 23 privilege acceptance. Disposable GitHub runners only.

Linux installs the reviewed installer function, shell broker and root helper.
Windows registers a service the way the agent registers an app
(`app_accounts.WindowsServiceRunner`): a virtual account of its own
(`NT SERVICE\\<name>`), the base interpreter with `-I -u`, a ctypes service
host, and access to its own folders only. An app process proves effective
read/write before grant, after grant/restart, and after removal. No success
report is written until every assertion passes.

Each step is printed when it starts, unbuffered, and every wait is bounded,
so a run that stalls names the step it stalled in.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def step(message: str) -> None:
    print(f"row23 {time.strftime('%H:%M:%S')} {message}", flush=True)


def run(*args: str, timeout: float = 300, **kwargs) -> str:
    try:
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=timeout, **kwargs
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{args[0]} did not finish in {timeout:g} seconds: {' '.join(map(str, args))}\n"
            f"{exc.stdout or ''}{exc.stderr or ''}"
        ) from None
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} failed ({result.returncode}): {result.stderr or result.stdout}"
        )
    return result.stdout


def stream(*args: str, timeout: float, **kwargs) -> None:
    """Run with output straight to the job log, so its progress shows as it happens."""
    print(end="", flush=True)
    try:
        result = subprocess.run(args, check=False, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"{args[0]} did not finish in {timeout:g} seconds: {' '.join(map(str, args))}"
        ) from None
    if result.returncode:
        raise RuntimeError(f"{' '.join(map(str, args[:3]))} ... failed ({result.returncode})")


def wait_for(check, seconds=30, what="the app or the installed broker", detail=None):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    extra = ""
    if detail is not None:
        try:
            extra = "\n" + str(detail())
        except Exception as exc:  # diagnostics never hide the timeout itself
            extra = f"\n(no diagnostics: {exc})"
    raise AssertionError(f"{what} did not answer within {seconds} seconds{extra}")


def replace(source: Path, target: Path) -> None:
    """os.replace, retried while the other side holds the file open (Windows)."""
    for attempt in range(100):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.05)


PROBE = r"""
import json, os, sys, time, traceback
from pathlib import Path

IO = Path(sys.argv[1])

def log(text):
    try:
        with open(IO / 'probe.log', 'a', encoding='utf-8') as stream:
            stream.write(time.strftime('%H:%M:%S ') + text + '\n')
    except OSError:
        pass

def replace(source, target):
    for attempt in range(100):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.05)

def identity():
    if os.name != 'nt':
        return {'uid': os.getuid(), 'groups': os.getgroups()}
    import win32api, win32security as ws
    token = ws.OpenProcessToken(win32api.GetCurrentProcess(), ws.TOKEN_QUERY)
    try:
        # A virtual account's own SID is the token's user, not one of its groups.
        user = ws.GetTokenInformation(token, ws.TokenUser)[0]
        groups = [sid for sid, _ in ws.GetTokenInformation(token, ws.TokenGroups)]
        return {'sids': [ws.ConvertSidToStringSid(sid) for sid in (user, *groups)]}
    finally:
        token.Close()

def answer(request):
    reply = {'id': request['id'], 'pid': os.getpid()}
    reply.update(identity())
    reply['writtenFile'] = 'app-created-' + request['id'] + '.txt'
    folder = Path(request['path'])
    if request.get('protect'):
        # What the app's own account may do to a folder it made: close it to
        # inheritance, which turns inherited entries into explicit copies.
        import subprocess
        made = folder / request['protect']
        try:
            made.mkdir(exist_ok=True)
            (made / 'secret.txt').write_text('app secret')
            subprocess.run(['icacls', str(made), '/inheritance:d'], check=True,
                           capture_output=True, timeout=60)
            reply['protected'] = True
        except (OSError, subprocess.SubprocessError) as exc:
            reply['protected'] = False
            reply['protectError'] = str(exc)
    for name, action in [('read', lambda: (folder / request.get('readFile', 'seed.txt')).read_text()),
                         ('write', lambda: (folder / reply['writtenFile']).write_text('app data'))]:
        try:
            action()
            reply[name] = True
        except OSError as exc:
            reply[name] = False
            reply[name + 'Error'] = str(exc)
    return reply

def serve(stopping):
    log('serving as pid %d' % os.getpid())
    last = None
    while not stopping():
        try:
            request = json.loads((IO / 'command.json').read_text('utf-8'))
        except (OSError, ValueError):
            time.sleep(0.1)
            continue
        if request.get('id') == last:
            time.sleep(0.1)
            continue
        last = request.get('id')
        try:
            reply = answer(request)
        except Exception:
            reply = {'id': last, 'error': traceback.format_exc()}
            log(reply['error'])
        temp = IO / 'result.new'
        temp.write_text(json.dumps(reply), encoding='utf-8')
        replace(temp, IO / 'result.json')

def windows_service(name):
    # The agent's app launcher hosts its service with ctypes alone
    # (app_launcher._windows_service); so does this probe.
    import ctypes, threading
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)

    class Status(ctypes.Structure):
        _fields_ = [(field, wintypes.DWORD) for field in
                    ('type', 'state', 'accepted', 'win32', 'specific', 'checkpoint', 'hint')]

    main_type = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
    handler_type = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.LPVOID)

    class Entry(ctypes.Structure):
        _fields_ = [('name', wintypes.LPWSTR), ('main', main_type)]

    advapi.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
    advapi.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, handler_type, wintypes.LPVOID]
    advapi.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(Status)]
    stopping = threading.Event()
    handle = {}

    def report(state):
        status = Status(0x10, state, 1 if state == 4 else 0, 0, 0, 0, 0)
        advapi.SetServiceStatus(handle['value'], ctypes.byref(status))

    def handler(control, _event, _data, _context):
        if control in (1, 5):  # stop, shutdown
            report(3)
            stopping.set()
        return 0

    handler_ref = handler_type(handler)

    def service_main(_argc, _argv):
        handle['value'] = advapi.RegisterServiceCtrlHandlerExW(name, handler_ref, None)
        report(4)
        try:
            serve(stopping.is_set)
        except Exception:
            log(traceback.format_exc())
        report(1)

    main_ref = main_type(service_main)
    table = (Entry * 2)(Entry(name, main_ref), Entry(None, main_type()))
    if not advapi.StartServiceCtrlDispatcherW(table):
        log('StartServiceCtrlDispatcherW failed: %d' % ctypes.get_last_error())
        sys.exit(1)

if __name__ == '__main__':
    log('started: %s' % sys.executable)
    if os.name == 'nt':
        windows_service(sys.argv[2])
    else:
        serve(lambda: False)
"""


def probe_log(directory: Path) -> str:
    log = directory / "probe.log"
    try:
        return "probe.log:\n" + log.read_text("utf-8")[-4000:]
    except FileNotFoundError:
        return "The probe wrote no log, so its interpreter never ran its first line."


def probe(directory: Path, path: Path, read_file: str = "seed.txt", **extra) -> dict:
    ident = uuid.uuid4().hex
    temp = directory / "command.new"
    temp.write_text(
        json.dumps({"id": ident, "path": str(path), "readFile": read_file, **extra}),
        encoding="utf-8",
    )
    replace(temp, directory / "command.json")

    def result():
        try:
            value = json.loads((directory / "result.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return value if value.get("id") == ident else None

    answer = wait_for(
        result, what=f"The app probe (asked about {path})", detail=lambda: probe_log(directory)
    )
    assert "error" not in answer, answer["error"]
    return answer


def assert_app_revoked(io, folder, created):
    for file in ("seed.txt", created.name):
        observed = probe(io, folder, file)
        assert not observed["read"] and not observed["write"], (file, observed)


def root_refusals(ctl, broker, link, owner, extra=()):
    """Bypass the unprivileged agent: the installed root broker must refuse."""
    for path, cause in (("/etc", "system:"), (str(link), "link:"), *extra):
        ident = uuid.uuid4().hex
        request = ctl / (ident + ".path")
        request.write_text(path)
        owner(request)
        try:
            answer = broker(
                f"folder-grant workbench read {ident}", expect_success=False
            )
            assert answer["code"] != 0 and cause in answer["output"], answer
        finally:
            request.unlink(missing_ok=True)


def check_refusals(access, cases) -> None:
    """Each path is refused with its cause, and no refusal writes a record."""
    from eugene_plexus_agent.folder_access import Refused

    before = access._read()
    for path, cause in cases:
        try:
            access.add("workbench", path, "read", "acceptance")
        except Refused as exc:
            assert exc.cause == cause, (path, exc.cause, cause, str(exc))
            assert str(exc)
        else:
            raise AssertionError(f"{cause} was not refused for {path}")
    assert access._read() == before, "A refusal must not create an access record"


def swapped_folder(add, remove, folder, target, acl, link):
    before = acl(target)
    content = (target / "seed.txt").read_bytes()
    grant = add(str(folder))
    assert grant["state"] == "ready", grant
    moved = folder.with_name(folder.name + "-original")
    folder.rename(moved)
    link(folder, target)
    try:
        outcome = remove(grant["id"])
        assert outcome["state"] == "changed_outside", outcome
        assert acl(target) == before
        assert (target / "seed.txt").read_bytes() == content
    finally:
        if folder.is_symlink():
            folder.unlink()
        else:
            folder.rmdir()  # A Windows junction is a directory entry.
        moved.rename(folder)
    assert remove(grant["id"])["state"] == "removed"


def check_release(client, key, path, ident, foreign, listing):
    headers = {"Authorization": "Bearer " + key}
    route = "/v1/apps/workbench/folder-access/release"
    before = listing()
    lookup = client.post(route, json={"path": str(path)}, headers=headers)
    assert lookup.status_code == 200, lookup.text
    assert listing() == before, "A path lookup must not release any access"
    released = client.post(route, json={"id": ident}, headers=headers)
    assert released.status_code == 200, released.text
    assert released.json()["grants"][0]["state"] == "removed", released.text
    expected = {**before, ident: "removed"}
    assert listing() == expected, "An id release must remove exactly one record"
    denied = client.post(route, json={"id": foreign}, headers=headers)
    assert denied.status_code == 404, denied.text
    assert listing() == expected, "Another app's record must stay in place"


def release_http(root, access, paths):
    """Real HTTP routing, signature verification and key standing; real ACL backend."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from eugene_plexus_agent import tokens
    from eugene_plexus_agent.app import create_app
    from eugene_plexus_agent.routes import directories
    from eugene_plexus_agent.settings import Settings

    app = create_app(Settings(config_file=root / "agent.yaml", default_topology=False))
    with TestClient(app) as client:
        initialized = client.post(
            "/v1/auth/initialize", json={"passphrase": "disposable row 23 acceptance"}
        )
        assert initialized.status_code == 200, initialized.text
        client.headers["Authorization"] = "Bearer " + initialized.json()["sessionToken"]
        minted = client.post(
            "/v1/auth/client-keys", json={"name": "app:workbench@this-node"}
        )
        assert minted.status_code == 201, minted.text
        key = minted.json()["token"]
        claims = app.state.auth_state.trust.verify(key, classes=(tokens.TYP_CLIENT,))
        # Wire the app's installed key and this acceptance's durable access service.
        app.state.apps = SimpleNamespace(
            node_name=lambda: None,
            store=SimpleNamespace(
                get=lambda _: object(), key=lambda _: SimpleNamespace(key_id=claims.jti)
            ),
        )
        grants = [
            access.add(name, str(path), "read", "acceptance")
            for name, path in zip(("workbench", "workbench", "other"), paths)
        ]
        assert all(g.state == "ready" for g in grants), grants
        with patch.object(directories, "_access", lambda *_: access):
            check_release(
                client,
                key,
                paths[0],
                grants[0].id,
                grants[2].id,
                lambda: {ident: row["state"] for ident, row in access._read().items()},
            )
        for grant in grants[1:]:
            assert access.remove(grant.app, grant.id).state == "removed"


def refusals(root: Path) -> None:
    """Windows: the agent's own checks. Linux's go through the root broker in linux()."""
    from eugene_plexus_agent.folder_access import Access, WindowsPermissions

    own = root / "eugene"
    own.mkdir()
    target = root / "target"
    (target / "sub").mkdir(parents=True)
    link = root / "link"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    backend = WindowsPermissions("S-1-5-11", eugene=(str(own),))
    access = Access(root / "refusals.json", backend)
    check_refusals(
        access,
        [
            (root.anchor, "drive_root"),
            (os.environ["SystemRoot"], "system"),
            (str(own), "eugene"),
            (str(Path.home()), "home"),
            (str(link), "link"),
            # A junction part-way along the path is refused too.
            (str(link / "sub"), "link"),
            (r"\\unreachable.invalid\share", "network"),
            (str(root / "missing"), "not_a_folder"),
        ],
    )
    assert not access.file.exists(), "A refusal must not create an access record"


AGENT_CLI = """\
from pathlib import Path
import json, runpy, subprocess, sys
from eugene_plexus_agent.folder_access import Access, LinuxPermissions, Refused
prefix = Path(sys.argv[1])
a = Access(
    prefix / 'folder-access.json',
    LinuxPermissions('workbench', prefix / 'apps', eugene=(str(prefix),)),
    process=lambda: int(subprocess.check_output(
        ['systemctl', 'show', 'eugene-plexus-app@workbench.service', '--property=MainPID', '--value'])),
)
verb = sys.argv[2]
if verb in ('http', 'refusals'):
    module = runpy.run_path(sys.argv[3])
    if verb == 'http':
        module['release_http'](prefix / 'http', a, [Path(p) for p in sys.argv[4:]])
    else:
        module['check_refusals'](a, json.loads(sys.argv[4]))
    print(json.dumps({'ok': True}))
    sys.exit(0)
try:
    if verb == 'add':
        r = a.add('workbench', sys.argv[3], sys.argv[4], 'acceptance')
    elif verb == 'remove':
        r = a.remove('workbench', sys.argv[3])
    else:
        r = next(x for x in a.listing('workbench') if x.state == 'ready')
except Refused as exc:
    print(json.dumps({'refused': exc.cause, 'message': str(exc)}))
    sys.exit(0)
print(r.model_dump_json())
"""


def linux(specs: Path) -> None:
    import grp
    import hashlib
    import pwd

    assert os.geteuid() == 0, (
        "The Linux acceptance must install and execute the helper as root"
    )
    root = Path("/srv/ep-r23")
    assert not root.exists(), "Refuse to reuse any existing /srv/ep-r23 tree"
    root.mkdir(mode=0o755)
    account = os.environ["SUDO_USER"]
    assert account != "root"
    prefix = root / "install"
    prefix.mkdir()
    runner = pwd.getpwnam(account)
    os.chown(prefix, runner.pw_uid, runner.pw_gid)
    source = (specs / "scripts/install.sh").read_text("utf-8")
    function = source.split("write_app_units() {", 1)[1].split("\n}\n", 1)[0]
    # This is the exact production install function, including its shell
    # broker and systemd path watcher; root never loads agent-owned code.
    setup = root / "install-units.sh"
    setup.write_text(
        'set -eu\nas_root() { "$@"; }\nin_prefix() { runuser -u "$SYSTEM_ACCOUNT" -- "$@"; }\nwarn() { echo "$*" >&2; }\n'
        + "PREFIX="
        + str(prefix)
        + "\nSYSTEM_ACCOUNT="
        + account
        + "\nSERVICE_LABEL=ep-r23\n"
        + "APPS_HELPER=/usr/local/lib/eugene-plexus/apps-ctl\n"
        + "APPS_TEMPLATE=/etc/systemd/system/eugene-plexus-app@.service\n"
        + "APPS_CTL_SERVICE=/etc/systemd/system/eugene-plexus-apps-ctl.service\n"
        + "APPS_CTL_PATH=/etc/systemd/system/eugene-plexus-apps-ctl.path\n"
        + "write_app_units() {"
        + function
        + "\n}\nwrite_app_units\n",
        encoding="utf-8",
    )
    unit = "eugene-plexus-app@workbench.service"
    drop = Path("/etc/systemd/system/" + unit + ".d")
    io = Path("/var/lib/eugene-plexus-apps/workbench")
    alias = root / "etc-alias"
    other = "ep-r23-other"
    try:
        step("Linux: install the units, the shell broker and the root helper")
        run("bash", str(setup))
        installed = Path("/usr/local/lib/eugene-plexus/folder-access.py")
        assert (
            installed.read_bytes()
            == (specs / "scripts/folder-access-helper.py").read_bytes()
        )
        assert installed.stat().st_uid == 0 and installed.stat().st_mode & 0o022 == 0
        for directory in ("apps/pythons", "apps/launcher", "apps/workbench/data"):
            (prefix / directory).mkdir(parents=True, exist_ok=True)
        for file in (
            "apps/workbench/data/client_key",
            "apps/workbench/data/oidc_secret",
            "apps/workbench/admin_token",
        ):
            (prefix / file).write_text("disposable")
        (root / "service_probe.py").write_text(PROBE, encoding="utf-8")
        drop.mkdir(exist_ok=True)
        (drop / "05-acceptance.conf").write_text(
            "[Service]\nExecStart=\nExecStart=/usr/bin/python3 -u "
            + str(root / "service_probe.py")
            + " "
            + str(io)
            + "\n"
        )
        run("systemctl", "daemon-reload")
        ctl = prefix / "apps/ctl"

        def broker(verb, *, expect_success=True):
            request = ctl / (uuid.uuid4().hex + ".req")
            request.write_text(verb + ("" if " " in verb else " workbench") + "\n")
            os.chown(request, runner.pw_uid, runner.pw_gid)
            result = request.with_suffix(".res")
            wait_for(
                result.exists,
                seconds=90,
                what=f"The installed broker (asked to {verb})",
                detail=lambda: run(
                    "journalctl", "-n", "40", "--no-pager", "-u",
                    "eugene-plexus-apps-ctl.service", "-u", "eugene-plexus-apps-ctl.path",
                ),
            )
            answer = json.loads(result.read_text())
            result.unlink()
            if expect_success:
                assert answer["code"] == 0, answer
            return answer

        step("Linux: start Workbench's unit through the broker")
        broker("start")
        wait_for(io.is_dir, what="Workbench's state directory")
        link = root / "root-refusal-link"
        link.symlink_to("/etc", target_is_directory=True)
        # Review blocker: a bind mount gives /etc a second name that realpath
        # keeps. Read-only, so nothing can write through it into /etc.
        alias.mkdir()
        run("mount", "--bind", "/etc", str(alias))
        run("mount", "-o", "remount,bind,ro", str(alias))
        step("Linux: the root broker itself refuses /etc, a link to it and a bind mount of it")
        root_refusals(
            ctl,
            broker,
            link,
            lambda p: os.chown(p, runner.pw_uid, runner.pw_gid),
            extra=[(str(alias / "systemd"), "system:")],
        )
        group_name = (
            "eapp-" + hashlib.sha256(b"workbench").hexdigest()[:12] + "-files"
        )
        group = str(grp.getgrnam(group_name).gr_gid)
        cli = root / "agent_cli.py"
        cli.write_text(AGENT_CLI, encoding="utf-8")

        def agent(*args):
            return json.loads(
                run(
                    "runuser",
                    "-u",
                    account,
                    "--",
                    sys.executable,
                    str(cli),
                    str(prefix),
                    *args,
                    timeout=180,
                )
            )

        step("Linux: the agent refuses each kind of folder through the root helper")
        refusal_target = root / "refusal-target"
        refusal_target.mkdir(mode=0o700)
        refusal_link = root / "refusal-link"
        refusal_link.symlink_to(refusal_target, target_is_directory=True)
        # Inside Eugene's prefix and inside a home, every parent below the
        # account's own folder is "unsafe"; the folder's own rule is named.
        in_home = specs.parent
        assert in_home.is_relative_to(runner.pw_dir) and in_home != Path(runner.pw_dir)
        assert agent(
            "refusals",
            str(Path(__file__).resolve()),
            json.dumps(
                [
                    ("/", "drive_root"),
                    ("/etc", "system"),
                    (str(prefix), "eugene"),
                    (str(prefix / "apps"), "eugene"),
                    (runner.pw_dir, "home"),
                    (str(in_home), "home"),
                    (str(refusal_link), "link"),
                    (str(link), "link"),
                    (str(alias / "systemd"), "system"),
                    ("//unreachable.invalid/share", "network"),
                    (str(root / "missing"), "not_a_folder"),
                ]
            ),
        )["ok"]
        run("umount", str(alias))
        assert not os.path.ismount(alias)
        folder = root / "f\u00fc project %data"
        folder.mkdir(mode=0o700)
        (folder / "seed.txt").write_text("project data")
        (folder / "seed.txt").chmod(0o600)
        run("setfacl", "-m", "u:65534:r-x", str(folder))
        # Negative controls: an unrelated account, and a folder beside it.
        run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", other)
        outside = root / "outside"
        outside.mkdir(mode=0o700)
        (outside / "seed.txt").write_text("outside")
        (outside / "seed.txt").chmod(0o600)

        def unrelated(path):
            """What the unrelated account can do: (read, write)."""
            reads = subprocess.run(
                ["runuser", "-u", other, "--", "cat", str(path / "seed.txt")],
                capture_output=True,
                timeout=60,
            )
            writes = subprocess.run(
                ["runuser", "-u", other, "--", "sh", "-c", 'echo x > "$1"', "sh",
                 str(path / "unrelated.txt")],
                capture_output=True,
                timeout=60,
            )
            return reads.returncode == 0, writes.returncode == 0

        def acls(path):
            return [run("getfacl", "-cpnE", str(p)) for p in (path, path / "seed.txt")]

        step("Linux: Workbench cannot read the folder before a grant")
        before = probe(io, folder)
        assert not before["read"] and not before["write"]
        untouched = acls(folder)
        step("Linux: a read grant lets Workbench read, not write; nobody else gains")
        read = agent("add", str(folder), "read")
        assert read["state"] == "ready", read
        observed = probe(io, folder)
        assert observed["read"] and not observed["write"], observed
        assert int(group) in observed["groups"] and observed["uid"] != runner.pw_uid
        assert unrelated(folder) == (False, False)
        beside = probe(io, outside)
        assert not beside["read"] and not beside["write"], beside
        step("Linux: removing the read grant restores the folder's ACLs exactly")
        assert agent("remove", read["id"])["state"] == "removed"
        assert not probe(io, folder)["read"]
        assert acls(folder) == untouched
        step("Linux: a write grant needs a restart, then Workbench writes; nobody else gains")
        write = agent("add", str(folder), "write")
        assert write["state"] == "ready" and write["restartNeeded"], write
        assert not probe(io, folder)["write"]
        config = (drop / "20-folders.conf").read_text("utf-8")
        assert '-"/srv/ep-r23/f\u00fc project %%data"' in config
        broker("restart")
        observed = probe(io, folder)
        assert observed["read"] and observed["write"], observed
        created = folder / observed["writtenFile"]
        assert not agent("list")["restartNeeded"]
        assert unrelated(folder) == (False, False)
        beside = probe(io, outside)
        assert not beside["read"] and not beside["write"], beside
        # Reopen the agent's durable record; chmod and new inherited files
        # must not prevent revocation, or undo another principal's entry.
        step("Linux: removing the write grant closes the folder and the app's file")
        folder.chmod(0o750)
        assert agent("remove", write["id"])["state"] == "removed"
        revoked = probe(io, folder)
        assert not revoked["read"] and not revoked["write"], revoked
        assert_app_revoked(io, folder, created)
        assert created.read_text() == "app data"
        acl = run("getfacl", "-cpnE", str(folder))
        assert "user:65534:r-x" in acl and "group:" + group + ":" not in acl
        assert "group:" + group + ":" not in run("getfacl", "-cpnE", str(created))
        step("Linux: a folder swapped for a link is left alone, and so is the target")
        swap, target = root / "swap", root / "swap-target"
        swap.mkdir(mode=0o700)
        target.mkdir(mode=0o700)
        (target / "seed.txt").write_text("private")
        swapped_folder(
            lambda p: agent("add", p, "read"),
            lambda ident: agent("remove", ident),
            swap,
            target,
            lambda p: run("getfacl", "-cpnE", str(p), str(p / "seed.txt")),
            lambda p, destination: p.symlink_to(destination, target_is_directory=True),
        )
        step("Linux: the app's own key releases one grant over HTTP, never another app's")
        http_paths = [root / ("http-" + name) for name in ("one", "two", "foreign")]
        for path in http_paths:
            path.mkdir(mode=0o700)
        assert agent(
            "http", str(Path(__file__).resolve()), *(str(p) for p in http_paths)
        )["ok"]
        step("Linux: removing a child's write grant keeps the parent's read grant")
        parent = root / "overlap"
        child = parent / "child"
        parent.mkdir(mode=0o700)
        child.mkdir(mode=0o700)
        (child / "seed.txt").write_text("parent read must survive")
        (child / "seed.txt").chmod(0o600)
        parent_read = agent("add", str(parent), "read")
        assert parent_read["state"] == "ready", parent_read
        child_write = agent("add", str(child), "write")
        assert child_write["state"] == "ready", child_write
        broker("restart")
        observed = probe(io, child)
        assert observed["read"] and observed["write"], observed
        assert agent("remove", child_write["id"])["state"] == "removed"
        observed = probe(io, child)
        assert observed["read"] and not observed["write"], observed
        assert agent("list")["id"] == parent_read["id"]
        assert agent("remove", parent_read["id"])["state"] == "removed"
        assert not probe(io, child)["read"]
        # Review: removal deleted a by-hand entry for Eugene's own group.
        step("Linux: an entry for Eugene's group made by hand stays after a removal")
        manual = root / "manual"
        manual.mkdir(mode=0o700)
        (manual / "seed.txt").write_text("by hand")
        (manual / "seed.txt").chmod(0o600)
        run("setfacl", "-m", f"g:{group}:r--", str(manual / "seed.txt"))
        by_hand = run("getfacl", "-cpnE", str(manual / "seed.txt"))
        grant = agent("add", str(manual), "read")
        assert grant["state"] == "ready", grant
        assert probe(io, manual)["read"]
        assert agent("remove", grant["id"])["state"] == "removed"
        assert run("getfacl", "-cpnE", str(manual / "seed.txt")) == by_hand
        assert not probe(io, manual)["read"]
        # Real parser, masked named user AND owning group, unchanged on failure.
        step("Linux: a masked ACL entry is refused and left unchanged")
        for entry in ("u:65534:rwx", "g::rwx"):
            run("setfacl", "-n", "-m", entry + ",m::r--", str(folder))
            before_acl = run("getfacl", "-cpnE", str(folder))
            refused = agent("add", str(folder), "write")
            assert (
                refused["state"] == "failed" and "masked out" in refused["message"]
            ), refused
            assert run("getfacl", "-cpnE", str(folder)) == before_acl
            assert agent("remove", refused["id"])["state"] == "removed"
        step("Linux: a granted folder deleted later never stops Workbench starting")
        deleted = root / "deleted"
        deleted.mkdir(mode=0o700)
        gone = agent("add", str(deleted), "write")
        assert gone["state"] == "ready", gone
        shutil.rmtree(deleted)
        broker("restart")  # Missing optional ReadWritePaths cannot cause 226/NAMESPACE.
        assert run("systemctl", "is-active", unit).strip() == "active"
        assert agent("remove", gone["id"])["state"] == "removed"
        assert str(deleted) not in (drop / "20-folders.conf").read_text("utf-8")
        # The installed main() and opened() must refuse an unsafe parent.
        step("Linux: a folder under a parent other accounts can change is refused")
        unsafe = root / "unsafe"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        child = unsafe / "child"
        child.mkdir()
        denied = agent("add", str(child), "read")
        assert denied.get("refused") == "unsafe_parent", denied
        assert str(unsafe) + " can be changed by other accounts" in denied["message"], denied
    finally:
        step("Linux: clean up")
        subprocess.run(
            [
                "systemctl",
                "stop",
                unit,
                "eugene-plexus-apps-ctl.path",
                "eugene-plexus-apps-ctl.service",
            ],
            check=False,
            timeout=120,
        )
        subprocess.run(["umount", str(alias)], check=False, capture_output=True, timeout=60)
        subprocess.run(["userdel", other], check=False, capture_output=True, timeout=60)
        # Dedicated paths created above on an explicitly disposable runner.
        # Never delete through a mount: the bind mount above shows /etc.
        mounted = [
            line.split()[4]
            for line in Path("/proc/self/mountinfo").read_text().splitlines()
            if line.split()[4].startswith(str(root) + "/")
        ]
        for target in (drop, Path("/etc/eugene-plexus/folder-access/workbench"), root):
            if target == root and mounted:
                step(f"Linux: {root} still holds mounts {mounted}; it stays on this runner")
                continue
            if target.exists():
                shutil.rmtree(target)
        run("systemctl", "daemon-reload")


def create_service(name: str, account: str, command: str) -> None:
    """The agent's `WindowsServiceRunner.prepare`, for a probe instead of an app."""
    import win32service

    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        handle = win32service.CreateService(
            manager,
            name,
            "Eugene row 23 disposable acceptance",
            win32service.SERVICE_ALL_ACCESS,
            win32service.SERVICE_WIN32_OWN_PROCESS,
            win32service.SERVICE_DEMAND_START,
            win32service.SERVICE_ERROR_NORMAL,
            command,
            None,
            0,
            None,
            account,
            None,
        )
        win32service.CloseServiceHandle(handle)
    finally:
        win32service.CloseServiceHandle(manager)


def service_diagnostics(name: str, io: Path) -> str:
    parts = []
    for args in (
        ("sc.exe", "qc", name),
        ("sc.exe", "queryex", name),
        (
            "wevtutil",
            "qe",
            "System",
            "/q:*[System[Provider[@Name='Service Control Manager']]]",
            "/c:6",
            "/rd:true",
            "/f:text",
        ),
    ):
        try:
            parts.append(run(*args, timeout=60))
        except RuntimeError as exc:
            parts.append(str(exc))
    parts.append(probe_log(io))
    return "\n".join(parts)


def remove_service(name: str) -> None:
    """Best effort: a cleanup failure must never hide the check that failed."""
    import win32service
    import win32serviceutil

    try:
        win32serviceutil.ControlService(name, win32service.SERVICE_CONTROL_STOP)
    except Exception as exc:
        step(f"Windows: stop {name}: {exc}")
    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline:
        try:
            if win32serviceutil.QueryServiceStatus(name)[1] == win32service.SERVICE_STOPPED:
                break
        except Exception:
            break
        time.sleep(0.5)
    try:
        win32serviceutil.RemoveService(name)
    except Exception as exc:
        step(f"Windows: remove {name}: {exc}")


def windows(root: Path) -> None:
    import ctypes
    import win32security as ws
    import win32serviceutil

    from eugene_plexus_agent.folder_access import Access, WindowsPermissions

    assert ctypes.windll.shell32.IsUserAnAdmin(), (
        "The runner must already be admin; never request elevation"
    )
    name = "EpR23Probe"
    account = "NT SERVICE\\" + name
    # The probe's own folder, like an app's: only the probe's account is
    # given it. `root` came from mkdtemp, which on Python 3.12.4 and later
    # gives SYSTEM, Administrators and the owner alone; nothing inherited
    # from it lets a service account read its script.
    home = root / "probe"
    home.mkdir()
    script = home / "service_probe.py"
    script.write_text(PROBE, encoding="utf-8")
    io = root / "probe-io"
    io.mkdir()
    folder = root / "shared"
    folder.mkdir()
    (folder / "seed.txt").write_text("project data")

    def private(path):
        own = ws.GetFileSecurity(str(path), 1).GetSecurityDescriptorOwner()
        acl = ws.ACL()
        for sid in (own, ws.ConvertStringSidToSid("S-1-5-18")):
            acl.AddAccessAllowedAceEx(2, 3, 0x1F01FF, sid)
        ws.SetNamedSecurityInfo(
            str(path),
            1,
            4 | ws.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            acl,
            None,
        )

    private(folder)
    closed = folder / "closed"
    closed.mkdir()
    (closed / "seed.txt").write_text("keep closed")
    private(closed)
    # Negative controls: a folder beside the granted one, and an unrelated
    # service account that is never given anything.
    outside = root / "outside"
    outside.mkdir()
    (outside / "seed.txt").write_text("outside")
    private(outside)
    other = "EpR23Other"
    other_account = "NT SERVICE\\" + other
    other_io = root / "other-io"
    other_io.mkdir()
    # The base interpreter, as `app_accounts.base_interpreter` picks it:
    # a service must be the process the service manager started.
    python = getattr(sys, "_base_executable", None) or sys.executable
    step(f"Windows: register {account} and {other_account} the way the agent registers an app")
    create_service(name, account, f'"{python}" -I -u "{script}" "{io}" {name}')
    create_service(other, other_account, f'"{python}" -I -u "{script}" "{other_io}" {other}')

    def holders(tree):
        """Every item under `tree` whose DACL names the probe's account."""
        found = []
        for item in [tree, *tree.rglob("*")]:
            acl = ws.GetFileSecurity(str(item), 4).GetSecurityDescriptorDacl()
            if acl is not None and any(
                ws.ConvertSidToStringSid(acl.GetAce(i)[-1]) == sid_text
                for i in range(acl.GetAceCount())
            ):
                found.append(str(item))
        return found

    def dacls(path):
        return [
            ws.ConvertSecurityDescriptorToStringSecurityDescriptor(
                ws.GetFileSecurity(str(p), 4), 1, 4
            )
            for p in (path, path / "seed.txt")
        ]

    try:
        for account_name, own_io in ((account, io), (other_account, other_io)):
            run("icacls", str(home), "/grant", account_name + ":(OI)(CI)(RX)")
            run("icacls", str(own_io), "/grant:r", account_name + ":(OI)(CI)(M)")
        sid_text = ws.ConvertSidToStringSid(ws.LookupAccountName(None, account)[0])
        step("Windows: start the probe services")
        for service, service_io in ((name, io), (other, other_io)):
            try:
                win32serviceutil.StartService(service)
            except Exception as exc:
                raise AssertionError(
                    f"The probe service {service} did not start: {exc}\n"
                    f"{service_diagnostics(service, service_io)}"
                ) from exc
        step("Windows: the service's account cannot open the folder before a grant")
        before = probe(io, folder)
        assert sid_text in before["sids"], before
        assert not before["read"] and not before["write"], before
        untouched = dacls(folder)
        backend = WindowsPermissions(account, eugene=(), homes=())
        access = Access(root / "folder-access.json", backend)
        step("Windows: a read grant lets the service read, not write; nobody else gains")
        read = access.add("workbench", str(folder), "read", "acceptance")
        assert read.state == "ready", read.message
        assert read.notInheriting == 1
        denied = probe(io, closed)
        assert not denied["read"] and not denied["write"], denied
        observed = probe(io, folder)
        assert observed["read"] and not observed["write"], observed
        unrelated = probe(other_io, folder)
        assert not unrelated["read"] and not unrelated["write"], unrelated
        beside = probe(io, outside)
        assert not beside["read"] and not beside["write"], beside
        step("Windows: the record survives a reopen, and its release restores the DACLs")
        reopened = Access(access.file, backend)
        assert reopened.listing("workbench")[0].id == read.id
        assert reopened.release("workbench", read.id)[0].state == "removed"
        assert not probe(io, folder)["read"]
        assert holders(folder) == []
        assert dacls(folder) == untouched
        step("Windows: a write grant lets the service write; nobody else gains")
        write = access.add("workbench", str(folder), "write", "acceptance")
        assert write.state == "ready", write.message
        observed = probe(io, folder)
        assert observed["read"] and observed["write"], observed
        created = folder / observed["writtenFile"]
        unrelated = probe(other_io, folder)
        assert not unrelated["read"] and not unrelated["write"], unrelated
        beside = probe(io, outside)
        assert not beside["read"] and not beside["write"], beside
        # Review blocker: the app closes a folder it made to inheritance, so
        # Eugene's inherited entry becomes an explicit copy in that folder.
        step("Windows: the app protects a folder it made; removal still takes its access")
        protected = probe(io, folder, protect="keep")
        assert protected.get("protected"), protected
        keep = folder / "keep"
        assert str(keep) in holders(folder)
        step("Windows: removing the write grant closes the folder and the app's files")
        assert access.remove("workbench", write.id).state == "removed"
        revoked = probe(io, folder)
        assert not revoked["read"] and not revoked["write"], revoked
        assert_app_revoked(io, folder, created)
        assert created.read_text() == "app data"
        locked = probe(io, keep, "secret.txt")
        assert not locked["read"] and not locked["write"], locked
        assert holders(folder) == []
        step("Windows: an entry made outside Eugene stays after a removal")
        manual, _, _ = backend.grant(str(folder), "read", lambda _: None)
        existing = access.add("workbench", str(folder), "read", "acceptance")
        assert existing.preexisting
        assert access.remove("workbench", existing.id).state == "removed"
        assert probe(io, folder)["read"]
        assert backend.revoke(str(folder), manual)
        assert holders(folder) == []
        step("Windows: a grant inside another grant is refused, naming the outer one")
        sub = folder / "sub"
        sub.mkdir()
        outer = access.add("workbench", str(folder), "read", "acceptance")
        assert outer.state == "ready", outer.message
        try:
            access.add("workbench", str(sub), "write", "acceptance")
        except ValueError as exc:
            assert "is inside" in str(exc) and str(folder).lower() in str(exc).lower(), exc
        else:
            raise AssertionError("A grant inside another grant was accepted")
        assert access.remove("workbench", outer.id).state == "removed"
        assert holders(folder) == []
        step("Windows: a folder swapped for a junction is left alone, and so is the target")
        swap, target = root / "swap", root / "swap-target"
        swap.mkdir()
        target.mkdir()
        private(swap)
        private(target)
        (target / "seed.txt").write_text("private")

        def junction(path, destination):
            run("cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(destination))

        def acl(path):
            return [
                ws.ConvertSecurityDescriptorToStringSecurityDescriptor(
                    ws.GetFileSecurity(str(p), 4), 1, 4
                )
                for p in (path, path / "seed.txt")
            ]

        swapped_folder(
            lambda p: access.add("workbench", p, "read", "acceptance").model_dump(),
            lambda ident: access.remove("workbench", ident).model_dump(),
            swap,
            target,
            acl,
            junction,
        )
        step("Windows: the app's own key releases one grant over HTTP, never another app's")
        http_paths = [root / ("http-" + name) for name in ("one", "two", "foreign")]
        for path in http_paths:
            path.mkdir()
            private(path)
        release_http(root / "http-config", access, http_paths)
    finally:
        step("Windows: clean up")
        remove_service(name)
        remove_service(other)


def main() -> None:
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit(
            "Refused: folder-access acceptance runs only on disposable github-hosted runners."
        )
    for name in list(os.environ):
        if name.startswith("EUGENE_PLEXUS_"):
            del os.environ[name]
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--linux-root", action="store_true")
    args = parser.parse_args()
    specs = Path(__file__).resolve().parent.parent
    if args.linux_root:
        linux(specs)
        args.report.write_text(
            json.dumps(
                {
                    "ok": True,
                    "platform": "linux",
                    "proved": [
                        "root installer",
                        "shell broker",
                        "helper main and parent checks",
                        "direct root broker system/link refusals",
                        "agent refusals through the root helper",
                        "symlink swap leaves target untouched",
                        "HTTP app-key lookup, id release, foreign id refusal",
                        "parent read survives child write revoke",
                        "systemd drop-in",
                        "app read/write and restart",
                        "masked ACL refusal",
                        "growth/chmod revoke",
                        "deleted folder restart",
                        "unsafe parent refusal",
                        "bind mount alias of /etc refused by the broker and the agent",
                        "by-hand entry for Eugene's group kept",
                        "read grant removal restores the exact ACLs",
                        "unrelated account and outside folder gain nothing",
                    ],
                }
            ),
            encoding="utf-8",
        )
        step("Linux: every check passed")
        return
    scratch = specs.parent / ".codex-tmp"
    scratch.mkdir(exist_ok=True)
    for component, tests in [
        (
            "agent",
            ["tests/test_folder_access.py", "tests/test_folder_access_windows.py"],
        ),
        ("workbench", ["tests/test_folder_access.py"]),
    ]:
        step(f"Run {component}'s folder access tests")
        stream(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *tests,
            "--basetemp",
            str(scratch / ("row23-" + component)),
            cwd=specs.parent / component,
            timeout=600,
        )
    if os.name == "nt":
        with tempfile.TemporaryDirectory(prefix="row23-", dir=scratch) as directory:
            root = Path(directory)
            step("Windows: the agent refuses each kind of folder")
            refusals(root)
            windows(root)
            args.report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "platform": "win32",
                        "proved": [
                            "real virtual account service, registered as the agent registers an app",
                            "app read/write",
                            "persisted access",
                            "revocation",
                            "revocation of app-created file",
                            "junction swap leaves target untouched",
                            "HTTP app-key lookup, id release, foreign id refusal",
                            "preexisting ACL preservation",
                            "refusals and authenticated routes",
                            "folder protected by the app after a grant loses the access",
                            "grant inside another grant refused",
                            "read grant removal restores the exact DACLs",
                            "unrelated service account and outside folder gain nothing",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            step("Windows: every check passed")
    else:
        step("Linux: continue as root")
        stream(
            "sudo",
            "--preserve-env=RUNNER_ENVIRONMENT",
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--linux-root",
            "--report",
            str(args.report.resolve()),
            timeout=660,
        )


if __name__ == "__main__":
    main()
