"""Row 23 privilege acceptance. Disposable GitHub runners only.

Linux installs the reviewed installer function, shell broker and root helper.
Windows creates a LocalService process with an unrestricted service SID.
An app process proves effective read/write before grant, after grant/restart,
and after removal. No success report is written until every assertion passes.
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


def run(*args: str, **kwargs) -> str:
    result = subprocess.run(args, check=False, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} failed ({result.returncode}): {result.stderr or result.stdout}"
        )
    return result.stdout


def wait_for(check, seconds=30):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("The app or installed broker did not answer within 30 seconds")


PROBE = r"""
import json, os, time
from pathlib import Path

def serve(directory):
    directory = Path(directory)
    last = None
    while True:
        try:
            request = json.loads((directory / 'command.json').read_text('utf-8'))
        except (FileNotFoundError, ValueError):
            time.sleep(0.1)
            continue
        if request['id'] == last:
            time.sleep(0.1)
            continue
        last = request['id']
        answer = {'id': last, 'pid': os.getpid()}
        answer['writtenFile'] = 'app-created-' + last + '.txt'
        if os.name == 'nt':
            import win32api, win32security as ws
            token = ws.OpenProcessToken(win32api.GetCurrentProcess(), ws.TOKEN_QUERY)
            answer['sids'] = [ws.ConvertSidToStringSid(sid) for sid, flags in ws.GetTokenInformation(token, ws.TokenGroups)]
            token.Close()
        else:
            answer['uid'], answer['groups'] = os.getuid(), os.getgroups()
        for name, action in [('read', lambda: (Path(request['path']) / 'seed.txt').read_text()),
                             ('write', lambda: (Path(request['path']) / answer['writtenFile']).write_text('app data'))]:
            try:
                action()
                answer[name] = True
            except OSError as exc:
                answer[name] = False
                answer[name + 'Error'] = str(exc)
        temp = directory / 'result.new'
        temp.write_text(json.dumps(answer), encoding='utf-8')
        os.replace(temp, directory / 'result.json')

if os.name == 'nt':
    import win32serviceutil, win32service
    class ServiceProbe(win32serviceutil.ServiceFramework):
        _svc_name_ = 'EpR23Probe'
        _svc_display_name_ = 'Eugene row 23 disposable acceptance'
        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            os._exit(0)
        def SvcDoRun(self):
            serve(Path(__file__).parent / 'probe-io')
    if __name__ == '__main__':
        import servicemanager
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ServiceProbe)
        servicemanager.StartServiceCtrlDispatcher()
else:
    if __name__ == '__main__':
        import sys
        serve(sys.argv[1])
"""


def probe(directory: Path, path: Path) -> dict:
    ident = uuid.uuid4().hex
    temp = directory / "command.new"
    temp.write_text(json.dumps({"id": ident, "path": str(path)}), encoding="utf-8")
    os.replace(temp, directory / "command.json")

    def result():
        try:
            value = json.loads((directory / "result.json").read_text("utf-8"))
            return value if value["id"] == ident else None
        except (FileNotFoundError, ValueError):
            return None

    return wait_for(result)


def refusals(root: Path) -> None:
    from eugene_plexus_agent.folder_access import (
        Access,
        LinuxPermissions,
        Refused,
        WindowsPermissions,
    )

    own = root / "eugene"
    own.mkdir()
    target = root / "target"
    target.mkdir()
    link = root / "link"
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
        backend = WindowsPermissions("S-1-5-11", eugene=(str(own),))
        drive = root.anchor
        system = os.environ["SystemRoot"]
        home = str(Path.home())
        network = r"\\unreachable.invalid\share"
    else:
        link.symlink_to(target, target_is_directory=True)
        backend = LinuxPermissions("workbench", root / "apps", eugene=(str(own),))
        drive, system, home, network = (
            "/",
            "/etc",
            str(Path.home()),
            "//unreachable.invalid/share",
        )
    access = Access(root / "refusals.json", backend)
    for path, cause in [
        (drive, "drive_root"),
        (system, "system"),
        (str(own), "eugene"),
        (home, "home"),
        (str(link), "link"),
        (network, "network"),
        (str(root / "missing"), "not_a_folder"),
    ]:
        try:
            access.add("workbench", path, "read", "acceptance")
        except Refused as exc:
            assert exc.cause == cause, (path, exc.cause, cause)
            assert str(exc)
        else:
            raise AssertionError(f"{cause} was not refused for {path}")
    assert not access.file.exists(), "A refusal must not create an access record"


def linux(specs: Path) -> None:
    import grp
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
    try:
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
        io = Path("/var/lib/eugene-plexus-apps/workbench")
        (drop / "05-acceptance.conf").write_text(
            "[Service]\nExecStart=\nExecStart=/usr/bin/python3 -u "
            + str(root / "service_probe.py")
            + " "
            + str(io)
            + "\n"
        )
        run("systemctl", "daemon-reload")
        ctl = prefix / "apps/ctl"

        def broker(verb):
            request = ctl / (uuid.uuid4().hex + ".req")
            request.write_text(verb + " workbench\n")
            os.chown(request, runner.pw_uid, runner.pw_gid)
            result = request.with_suffix(".res")
            wait_for(result.exists)
            answer = json.loads(result.read_text())
            result.unlink()
            assert answer["code"] == 0, answer

        broker("start")
        wait_for(io.is_dir)
        group_name = (
            "eapp-"
            + __import__("hashlib").sha256(b"workbench").hexdigest()[:12]
            + "-files"
        )
        group = str(grp.getgrnam(group_name).gr_gid)
        folder = root / "f\u00fc project %data"
        folder.mkdir(mode=0o700)
        (folder / "seed.txt").write_text("project data")
        (folder / "seed.txt").chmod(0o600)
        run("setfacl", "-m", "u:65534:r-x", str(folder))
        cli = root / "agent_cli.py"
        cli.write_text(
            "from pathlib import Path\nimport json,sys,subprocess\nfrom eugene_plexus_agent.folder_access import Access,LinuxPermissions\nprefix=Path(sys.argv[1])\na=Access(prefix/'folder-access.json',LinuxPermissions('workbench',prefix/'apps',eugene=(str(prefix),)),process=lambda: int(subprocess.check_output(['systemctl','show','eugene-plexus-app@workbench.service','--property=MainPID','--value'])))\nverb=sys.argv[2]\nif verb=='add': r=a.add('workbench',sys.argv[3],sys.argv[4],'acceptance')\nelif verb=='remove': r=a.remove('workbench',sys.argv[3])\nelse: r=next(x for x in a.listing('workbench') if x.state=='ready')\nprint(r.model_dump_json())\n"
        )

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
                )
            )

        before = probe(io, folder)
        assert not before["read"] and not before["write"]
        read = agent("add", str(folder), "read")
        assert read["state"] == "ready", read
        observed = probe(io, folder)
        assert observed["read"] and not observed["write"], observed
        assert int(group) in observed["groups"] and observed["uid"] != runner.pw_uid
        assert agent("remove", read["id"])["state"] == "removed"
        assert not probe(io, folder)["read"]
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
        # Reopen the agent's durable record; chmod and new inherited files
        # must not prevent revocation, or undo another principal's entry.
        folder.chmod(0o750)
        assert agent("remove", write["id"])["state"] == "removed"
        revoked = probe(io, folder)
        assert not revoked["read"] and not revoked["write"], revoked
        assert created.read_text() == "app data"
        acl = run("getfacl", "-cpnE", str(folder))
        assert "user:65534:r-x" in acl and "group:" + group + ":" not in acl
        assert "group:" + group + ":" not in run("getfacl", "-cpnE", str(created))
        # Real parser, masked named user AND owning group, unchanged on failure.
        for entry in ("u:65534:rwx", "g::rwx"):
            run("setfacl", "-n", "-m", entry + ",m::r--", str(folder))
            before_acl = run("getfacl", "-cpnE", str(folder))
            refused = agent("add", str(folder), "write")
            assert (
                refused["state"] == "failed" and "masked out" in refused["message"]
            ), refused
            assert run("getfacl", "-cpnE", str(folder)) == before_acl
            assert agent("remove", refused["id"])["state"] == "removed"
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
        unsafe = root / "unsafe"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        child = unsafe / "child"
        child.mkdir()
        denied = agent("add", str(child), "read")
        assert denied["state"] == "failed" and "parent folder" in denied["message"], (
            denied
        )
    finally:
        subprocess.run(
            [
                "systemctl",
                "stop",
                unit,
                "eugene-plexus-apps-ctl.path",
                "eugene-plexus-apps-ctl.service",
            ],
            check=False,
        )
        # Dedicated paths created above on an explicitly disposable runner.
        for target in (drop, Path("/etc/eugene-plexus/folder-access/workbench"), root):
            if target.exists():
                shutil.rmtree(target)
        run("systemctl", "daemon-reload")


def windows(root: Path) -> None:
    import ctypes
    import win32security as ws
    import win32serviceutil

    from eugene_plexus_agent.folder_access import Access, WindowsPermissions

    assert ctypes.windll.shell32.IsUserAnAdmin(), (
        "The runner must already be admin; never request elevation"
    )
    name = "EpR23Probe"
    (root / "service_probe.py").write_text(PROBE, encoding="utf-8")
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
    win32serviceutil.InstallService(
        None,
        name,
        "Eugene row 23 disposable acceptance",
        startType=3,
        exeName=sys.executable,
        exeArgs='"' + str(root / "service_probe.py") + '"',
        userName="NT AUTHORITY\\LocalService",
    )
    try:
        run("sc.exe", "sidtype", name, "unrestricted")
        sid = ws.LookupAccountName(None, "NT SERVICE\\" + name)[0]
        sid_text = ws.ConvertSidToStringSid(sid)
        # Let only this service write its command/result directory.
        acl = ws.GetFileSecurity(str(io), 4).GetSecurityDescriptorDacl()
        acl.AddAccessAllowedAceEx(2, 3, 0x1F01FF, sid)
        ws.SetNamedSecurityInfo(str(io), 1, 4, None, None, acl, None)
        win32serviceutil.StartService(name)
        before = probe(io, folder)
        assert sid_text in before["sids"], before
        assert not before["read"] and not before["write"], before
        backend = WindowsPermissions("NT SERVICE\\" + name, eugene=(), homes=())
        access = Access(root / "folder-access.json", backend)
        read = access.add("workbench", str(folder), "read", "acceptance")
        assert read.state == "ready", read.message
        assert read.notInheriting == 1
        denied = probe(io, closed)
        assert not denied["read"] and not denied["write"], denied
        observed = probe(io, folder)
        assert observed["read"] and not observed["write"], observed
        reopened = Access(access.file, backend)
        assert reopened.listing("workbench")[0].id == read.id
        assert reopened.release("workbench", read.id)[0].state == "removed"
        assert not probe(io, folder)["read"]
        write = access.add("workbench", str(folder), "write", "acceptance")
        assert write.state == "ready", write.message
        observed = probe(io, folder)
        assert observed["read"] and observed["write"], observed
        created = folder / observed["writtenFile"]
        assert access.remove("workbench", write.id).state == "removed"
        revoked = probe(io, folder)
        assert not revoked["read"] and not revoked["write"], revoked
        assert created.read_text() == "app data"
        manual, _, _ = backend.grant(str(folder), "read", lambda _: None)
        existing = access.add("workbench", str(folder), "read", "acceptance")
        assert existing.preexisting
        assert access.remove("workbench", existing.id).state == "removed"
        assert probe(io, folder)["read"]
        assert backend.revoke(str(folder), manual)
    finally:
        subprocess.run(["sc.exe", "stop", name], check=False, capture_output=True)
        wait_for(lambda: win32serviceutil.QueryServiceStatus(name)[1] == 1)
        win32serviceutil.RemoveService(name)


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
    scratch = specs.parent / ".codex-tmp"
    scratch.mkdir(exist_ok=True)
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
                        "systemd drop-in",
                        "app read/write and restart",
                        "masked ACL refusal",
                        "growth/chmod revoke",
                        "deleted folder restart",
                    ],
                }
            ),
            encoding="utf-8",
        )
        return
    for component, tests in [
        (
            "agent",
            ["tests/test_folder_access.py", "tests/test_folder_access_windows.py"],
        ),
        ("workbench", ["tests/test_folder_access.py"]),
    ]:
        run(
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *tests,
            "--basetemp",
            str(scratch / ("row23-" + component)),
            cwd=specs.parent / component,
        )
    with tempfile.TemporaryDirectory(prefix="row23-", dir=scratch) as directory:
        root = Path(directory)
        refusals(root)
        if os.name == "nt":
            windows(root)
            args.report.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "platform": "win32",
                        "proved": [
                            "real LocalService and NT SERVICE SID token",
                            "app read/write",
                            "persisted access",
                            "revocation",
                            "preexisting ACL preservation",
                            "refusals and authenticated routes",
                        ],
                    }
                ),
                encoding="utf-8",
            )
        else:
            run(
                "sudo",
                "--preserve-env=RUNNER_ENVIRONMENT",
                sys.executable,
                str(Path(__file__).resolve()),
                "--linux-root",
                "--report",
                str(args.report.resolve()),
            )


if __name__ == "__main__":
    main()
