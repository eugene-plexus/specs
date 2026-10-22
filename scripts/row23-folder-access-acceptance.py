"""Row 23: real ACLs plus authenticated routes, on disposable Windows/Linux CI.

No service or account is created, and no elevation is requested. Permission
changes are confined to a new temporary tree and a current-user group or a
well-known SID. The installed service lifecycle remains a separate live run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


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


def linux(root: Path, specs: Path) -> None:
    module_spec = importlib.util.spec_from_file_location(
        "folder_helper", specs / "scripts/folder-access-helper.py"
    )
    helper = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(helper)
    folder = root / "shared"
    folder.mkdir()
    (folder / "read.txt").write_text("Project data", encoding="utf-8")
    (folder / "child").mkdir()
    group = str(os.getgid())
    # The operator-set entry is for this user's own UID. It must survive.
    subprocess.run(["setfacl", "-m", f"u:{os.getuid()}:r-x", str(folder)], check=True)
    with helper.opened(str(folder), parents_safe=False) as fd:
        before = helper.acl(fd)
        ledger = {}
        record = root / "ledger.json"
        assert helper.grant(
            fd, group, False, ledger, lambda r: helper.write_record(record, r)
        )
        saved = json.loads(record.read_text())
        assert saved["items"]
        assert helper.acl(fd)[f"group:{group}"] == "r-x"
        assert helper.acl(fd)[f"user:{os.getuid()}"] == before[f"user:{os.getuid()}"]
        # Already provisioned rights generate no new delta.
        existing = {}
        assert not helper.grant(fd, group, False, existing, lambda _: None)
        assert helper.revoke(fd, existing)
        assert helper.acl(fd)[f"group:{group}"] == "r-x"
        assert helper.revoke(fd, saved)
        assert helper.acl(fd) == before
        write = {}
        assert helper.grant(fd, group, True, write, lambda _: None)
        assert helper.acl(fd)[f"group:{group}"] == "rwx"
        assert helper.revoke(fd, write)
        assert helper.acl(fd) == before
        # A changed recorded ACL prevents removal; a manual entry survives.
        changed = {}
        helper.grant(fd, group, False, changed, lambda _: None)
        subprocess.run(["setfacl", "-m", f"g:{group}:rwx", str(folder)], check=True)
        assert not helper.revoke(fd, changed)
        helper.set_acl(fd, before)
        grown = {}
        helper.grant(fd, group, False, grown, lambda _: None)
        new_child = folder / "new-child.txt"
        new_child.write_text("New", encoding="utf-8")
        assert not helper.revoke(fd, grown)
        new_child.unlink()
        assert helper.revoke(fd, grown)
        assert helper.acl(fd) == before
        # A masked entry is refused before the first ACL changes.
        subprocess.run(
            ["setfacl", "-n", "-m", f"u:{os.getuid()}:rwx,m::r--", str(folder)],
            check=True,
        )
        masked = helper.acl(fd)
        try:
            helper.grant(fd, group, True, {}, lambda _: None)
        except ValueError as exc:
            assert "masked out" in str(exc)
        else:
            raise AssertionError("A masked ACL was widened")
        assert helper.acl(fd) == masked
        helper.set_acl(fd, before)


def windows(root: Path) -> None:
    import win32api
    import win32security as ws

    from eugene_plexus_agent.folder_access import Access, WindowsPermissions

    folder = root / "shared"
    folder.mkdir()
    # Authenticated Users is well known; a separate manual Everyone ACE stays.
    backend = WindowsPermissions("S-1-5-11", eugene=(), homes=())
    token = ws.OpenProcessToken(win32api.GetCurrentProcess(), ws.TOKEN_QUERY)
    try:
        own_sid = ws.GetTokenInformation(token, ws.TokenUser)[0]
    finally:
        token.Close()
    acl = ws.ACL()
    acl.AddAccessAllowedAceEx(ws.ACL_REVISION, 3, 0x1F01FF, own_sid)
    acl.AddAccessAllowedAceEx(
        ws.ACL_REVISION, 3, 0x1F01FF, ws.ConvertStringSidToSid("S-1-5-18")
    )
    acl.AddAccessAllowedAceEx(
        ws.ACL_REVISION, 0, 0x80, ws.ConvertStringSidToSid("S-1-1-0")
    )
    ws.SetNamedSecurityInfo(
        str(folder),
        ws.SE_FILE_OBJECT,
        4 | ws.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )
    before = ws.ConvertSecurityDescriptorToStringSecurityDescriptor(
        ws.GetFileSecurity(str(folder), 4), 1, 4
    )
    access = Access(root / "folder-access.json", backend)
    added = access.add("workbench", str(folder), "read", "acceptance")
    assert added.state == "ready", added.message
    assert not added.preexisting
    assert json.loads(access.file.read_text())[added.id]["delta"]["added"]
    reopened = Access(access.file, backend)
    assert reopened.listing("workbench")[0].id == added.id
    assert reopened.remove("workbench", added.id).state == "removed"
    assert (
        ws.ConvertSecurityDescriptorToStringSecurityDescriptor(
            ws.GetFileSecurity(str(folder), 4), 1, 4
        )
        == before
    )
    # Preexisting inheritable rights stay when their new record is removed.
    manual, _, _ = backend.grant(str(folder), "read", lambda _: None)
    existing = access.add("workbench", str(folder), "read", "acceptance")
    assert existing.preexisting
    assert access.remove("workbench", existing.id).state == "removed"
    assert backend.revoke(str(folder), manual)


def main() -> None:
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit(
            "Refused: folder-access acceptance runs only on disposable github-hosted runners."
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    specs = Path(__file__).resolve().parent.parent
    sources = specs.parent
    scratch = sources / ".codex-tmp"
    scratch.mkdir(exist_ok=True)
    # Agent HTTP stays in process. Workbench tests use ephemeral loopback ports.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_folder_access.py",
            "tests/test_folder_access_windows.py",
            "--basetemp",
            str(scratch / "row23-agent-tests"),
        ],
        cwd=sources / "agent",
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_folder_access.py",
            "--basetemp",
            str(scratch / "row23-workbench-tests"),
        ],
        cwd=sources / "workbench",
        check=True,
    )
    with tempfile.TemporaryDirectory(prefix="row23-", dir=scratch) as directory:
        root = Path(directory)
        refusals(root)
        if os.name == "nt":
            windows(root)
        elif sys.platform == "linux":
            linux(root, specs)
        else:
            raise SystemExit("This acceptance requires real Windows or Linux.")
    args.report.write_text(
        json.dumps(
            {
                "ok": True,
                "platform": sys.platform,
                "scope": "permission engines and authenticated routes",
                "remaining": "installed service, catalogue, UI browser and restart integration",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
