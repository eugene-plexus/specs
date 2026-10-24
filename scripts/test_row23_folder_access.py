"""The privilege acceptance must run on both real operating systems."""

import importlib.util
import contextlib
import json
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


MOUNT_ROOT = "1 0 8:1 / / rw,relatime - ext4 /dev/sda1 rw\n"


def helper():
    spec = importlib.util.spec_from_file_location(
        "folder_helper", ROOT / "scripts/folder-access-helper.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # One root filesystem; a test that is about mounts sets its own table.
    module.mount_table = lambda: MOUNT_ROOT
    return module


def test_row23_acceptance_runs_on_real_windows_and_linux():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["folder-access"]
    assert set(job["strategy"]["matrix"]["os"]) == {"windows-latest", "ubuntu-24.04"}
    assert job["defaults"]["run"]["shell"] == "bash"
    assert any(
        "row23-folder-access-acceptance.py" in s.get("run", "") for s in job["steps"]
    )
    assert (ROOT / "scripts/row23-folder-access-acceptance.py").is_file()


def test_acceptance_refuses_privileged_work_on_a_developer_machine(tmp_path):
    import os
    import sys

    env = {k: v for k, v in os.environ.items() if k != "RUNNER_ENVIRONMENT"}
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/row23-folder-access-acceptance.py"),
            "--linux-root",
            "--report",
            str(report),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "disposable github-hosted" in result.stderr
    assert not report.exists()


def test_linux_acceptance_dispatches_to_root_before_reporting_ok(tmp_path, monkeypatch):
    import sys

    spec = importlib.util.spec_from_file_location(
        "acceptance", ROOT / "scripts/row23-folder-access-acceptance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["acceptance", "--report", str(report)])
    monkeypatch.setattr(
        module,
        "os",
        SimpleNamespace(name="posix", environ={"RUNNER_ENVIRONMENT": "github-hosted"}),
    )
    monkeypatch.setattr(
        module,
        "sys",
        SimpleNamespace(
            executable=sys.executable,
            argv=["acceptance", "--report", str(report)],
            platform="linux",
        ),
    )
    monkeypatch.setattr(module, "refusals", lambda _: None)

    def unelevated(*args):
        pytest.fail("Linux privilege acceptance must execute via sudo")

    monkeypatch.setattr(module, "linux", unelevated)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(module.subprocess, "run", run)
    module.main()
    assert any(args[0] == "sudo" and "--linux-root" in args for args in calls)
    assert not report.exists(), "Only the privileged child may report success"


def test_identity_does_not_require_mount_id_or_device_number(tmp_path, monkeypatch):
    import os
    import struct

    h = helper()
    calls = []

    def statx(fd, path, flags, mask, data):
        calls.append(mask)
        struct.pack_into("=I", data, 0, 0x800)
        struct.pack_into("=qI", data, 80, 123, 456)
        return 0

    monkeypatch.setattr(h.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace(statx=statx))
    file = tmp_path / "identity"
    file.touch()
    fd = os.open(file, os.O_RDONLY)
    try:
        actual = os.fstat(fd)
        assert h.identity(fd) == [actual.st_ino, 123, 456]
        assert calls == [0x800]
    finally:
        os.close(fd)


def test_installed_helper_is_exactly_the_reviewed_source():
    # A Windows checkout may hold both files with CRLF line ends.
    source = (ROOT / "scripts/folder-access-helper.py").read_bytes().replace(b"\r\n", b"\n")
    installed = (
        (ROOT / "scripts/install.sh")
        .read_bytes()
        .replace(b"\r\n", b"\n")
        .split(b"<<'FOLDER_HELPER'\n", 1)[1]
        .split(b"FOLDER_HELPER\n", 1)[0]
    )
    assert installed == source


def test_root_inspection_checks_path_and_returns_held_identity(monkeypatch):
    h = helper()
    calls = []
    monkeypatch.setattr(h, "refuse", lambda *args: calls.append(args))

    @contextlib.contextmanager
    def opened(path, *, parents_safe=True, allow_mount_root=False):
        assert calls == [(path, "/srv/install")]
        assert parents_safe
        assert allow_mount_root
        yield 10

    monkeypatch.setattr(h, "opened", opened)
    monkeypatch.setattr(h, "identity", lambda fd: [fd, 123, 456])
    assert h.inspect_folder("/srv/closed/child", "/srv/install") == {
        "facts": {"path": "/srv/closed/child"},
        "identity": [10, 123, 456],
    }


@pytest.mark.parametrize(
    ("error", "facts"),
    [
        (FileNotFoundError(), {"is_dir": False}),
        (NotADirectoryError(), {"is_dir": False}),
        (ValueError("link: A path component is a link."), {"link": True}),
        (ValueError("not_a_folder: Choose a folder."), {"is_dir": False}),
        (ValueError("network: No network folders."), {"network": True}),
    ],
)
def test_root_inspection_reports_refusals_without_opening(monkeypatch, error, facts):
    h = helper()

    def refuse(*_):
        raise error

    monkeypatch.setattr(h, "refuse", refuse)
    monkeypatch.setattr(
        h, "opened", lambda *a, **kw: pytest.fail("Refused path opened")
    )
    assert h.inspect_folder("/srv/refused", "/srv/install") == {
        "facts": {"path": "/srv/refused", **facts},
        "identity": [],
    }


@pytest.mark.parametrize(
    ("cause", "facts"),
    [
        ("drive_root", {"mount_root": True}),
        ("system", {"system": ["/srv/shared"]}),
        ("eugene", {"eugene": ["/srv/shared"]}),
        ("home", {"homes": ["/srv/shared"]}),
    ],
)
def test_root_inspection_keeps_identity_for_new_grant_policy_refusals(
    monkeypatch, cause, facts
):
    h = helper()

    def refuse(*_):
        raise ValueError(cause + ": New grants are refused.")

    @contextlib.contextmanager
    def opened(path, *, parents_safe=True, allow_mount_root=False):
        assert parents_safe and allow_mount_root
        yield 10

    monkeypatch.setattr(h, "refuse", refuse)
    monkeypatch.setattr(h, "opened", opened)
    monkeypatch.setattr(h, "identity", lambda fd: [fd, 1, 2])
    assert h.inspect_folder("/srv/shared", "/srv/install") == {
        "facts": {"path": "/srv/shared", **facts},
        "identity": [10, 1, 2],
    }


@pytest.mark.parametrize("foreign_owner", [False, True])
def test_root_inspection_stops_before_opening_below_an_unsafe_parent(
    monkeypatch, foreign_owner
):
    from pathlib import PurePosixPath

    h = helper()
    paths, closed, identified = [], [], []

    def open_folder(path, flags, **kwargs):
        paths.append(path)
        assert path != "secret", "Inspection traversed the unsafe parent"
        return len(paths)

    monkeypatch.setattr(h, "Path", PurePosixPath)
    monkeypatch.setattr(h, "refuse", lambda *args: None)
    monkeypatch.setattr(
        h,
        "os",
        SimpleNamespace(
            open=open_folder,
            close=closed.append,
            fstat=lambda fd: SimpleNamespace(
                st_uid=1000 if fd == 2 and foreign_owner else 0
            ),
            O_RDONLY=0,
            O_DIRECTORY=1,
            O_NOFOLLOW=2,
        ),
    )
    monkeypatch.setattr(
        h,
        "acl",
        lambda fd: {
            "user:": "rwx",
            "group:": "---",
            "other:": "rwx" if fd == 2 and not foreign_owner else "---",
        },
    )
    monkeypatch.setattr(h, "identity", lambda fd: identified.append(fd))
    assert h.inspect_folder("/srv/secret/shared", "/srv/install") == {
        "facts": {"path": "/srv/secret/shared", "unsafe_parent": "/srv"},
        "identity": [],
    }
    assert paths == ["/", "srv"]
    assert closed == [2, 1]
    assert not identified


def test_inspect_verb_reads_request_as_agent_without_creating_a_ledger(
    monkeypatch, capsys
):
    import sys
    from pathlib import PurePosixPath

    h = helper()
    ident = "a" * 32
    monkeypatch.setattr(
        h,
        "sys",
        SimpleNamespace(
            version_info=(3, 12),
            argv=[
                "helper",
                "/srv/install",
                "agent",
                "folder-inspect",
                "workbench",
                "read",
                ident,
            ],
        ),
    )
    monkeypatch.setitem(sys.modules, "grp", SimpleNamespace())
    calls = []

    def run(*args):
        calls.append(args)
        return "/srv/closed/child"

    monkeypatch.setattr(h, "run", run)
    monkeypatch.setattr(h, "Path", PurePosixPath)
    result = {"facts": {"path": "/srv/closed/child"}, "identity": [1, 2, 3]}

    def inspect(path, prefix):
        assert path == "/srv/closed/child" and prefix == "/srv/install"
        return result

    monkeypatch.setattr(h, "inspect_folder", inspect)
    h.main()
    assert json.loads(capsys.readouterr().out) == result
    assert calls == [
        (
            "runuser",
            "-u",
            "agent",
            "--",
            "head",
            "-c",
            "4097",
            "--",
            f"/srv/install/apps/ctl/{ident}.path",
        )
    ]


@pytest.mark.parametrize("entry", ["user:1000", "group:"])
def test_masked_acl_entry_is_refused_without_widening(monkeypatch, entry):
    h = helper()

    def getfacl(*args, **kwargs):
        comment = "" if "-cpnE" in args else "\t#effective:r--"
        owning_group = f"rwx{comment}" if entry == "group:" else "r--"
        named = "" if entry == "group:" else f"{entry}:rwx{comment}\n"
        return f"user::rwx\ngroup::{owning_group}\nother::---\n{named}mask::r--\n"

    monkeypatch.setattr(h, "run", getfacl)
    before = h.acl(10)
    with pytest.raises(ValueError, match="masked out"):
        h.plan(before, "1001", True, True)
    assert before["mask:"] == "r--"


def test_existing_complete_acl_is_not_added_again():
    h = helper()
    before = {
        "user:": "rwx",
        "group:": "---",
        "other:": "---",
        "group:1000": "r-x",
        "mask:": "r-x",
    }
    before.update({"default:" + k: v for k, v in list(before.items())})
    assert h.plan(before, "1000", False, True) == before


def test_helper_refuses_control_characters_before_reading_a_path():
    with pytest.raises(ValueError, match="control characters"):
        helper().refuse("/srv/project\n[Service]", "/var/lib/eugene-plexus")


@pytest.mark.parametrize(
    ("path", "prefix", "home", "cause"),
    [
        ("/home/runner", "/home/runner/ep", "/home/runner", "home"),
        ("/home", "/home/runner/ep", "/home/runner", "home"),
        ("/home/runner/shared", "/home/runner/ep", "/home/runner", "home"),
        ("/home/runner/ep", "/home/runner/ep", "/home/runner", "eugene"),
        ("/home/runner/ep/apps", "/home/runner/ep", "/home/runner", "eugene"),
        ("/opt", "/opt/ep", "/opt/service", "system"),
        ("/opt/ep", "/opt/ep", "/opt/service", "eugene"),
        ("/var", "/var/lib/ep", "/var/lib/service", "system"),
        ("/var/lib/ep/apps", "/var/lib/ep", "/var/lib/service", "eugene"),
        ("/srv/people", "/srv/people/person/ep", "/srv/people/person", "home"),
        ("/srv/install", "/srv/install/ep", "/home/runner", "eugene"),
    ],
)
def test_helper_refusal_precedence(monkeypatch, path, prefix, home, cause):
    import sys
    from pathlib import PurePosixPath

    h = helper()
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwall=lambda: [SimpleNamespace(pw_dir=home)]),
    )
    monkeypatch.setattr(h, "Path", PurePosixPath)
    monkeypatch.setattr(h.os.path, "realpath", lambda path, **kw: path)
    monkeypatch.setattr(h.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(h.os.path, "ismount", lambda path: False)
    with pytest.raises(ValueError, match=f"^{cause}:"):
        h.refuse(path, prefix)


@pytest.mark.parametrize(
    ("mounts", "path", "cause"),
    [
        # Review blocker: `mount --bind /etc /srv/etc-alias`; realpath keeps the alias.
        (
            "2 1 8:1 /etc /srv/etc-alias rw - ext4 /dev/sda1 rw\n",
            "/srv/etc-alias/ssh",
            "system",
        ),
        (
            "2 1 8:1 /etc /srv/with\\040space rw - ext4 /dev/sda1 rw\n",
            "/srv/with space/ssh",
            "system",
        ),
        # A home on its own disk, bound into /srv.
        (
            "3 1 8:17 / /home rw - ext4 /dev/sdb1 rw\n"
            "4 1 8:17 /person /srv/person rw - ext4 /dev/sdb1 rw\n",
            "/srv/person/projects",
            "home",
        ),
        # The system disk mounted a second time shows Eugene's own folder.
        (
            "5 1 8:1 / /mnt/system rw - ext4 /dev/sda1 rw\n",
            "/mnt/system/srv/install/apps",
            "eugene",
        ),
        # A data disk bound into /srv is an ordinary shared folder.
        (
            "6 1 8:33 / /data rw - ext4 /dev/sdc1 rw\n"
            "7 1 8:33 /projects /srv/projects rw - ext4 /dev/sdc1 rw\n",
            "/srv/projects/acme",
            None,
        ),
        ("", "/srv/projects/acme", None),
    ],
)
def test_helper_refuses_a_mount_alias_of_a_protected_folder(
    monkeypatch, mounts, path, cause
):
    import re
    import sys
    from pathlib import PurePosixPath

    h = helper()
    h.mount_table = lambda: MOUNT_ROOT + mounts
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwall=lambda: [SimpleNamespace(pw_dir="/home/person")]),
    )
    monkeypatch.setattr(h, "Path", PurePosixPath)
    monkeypatch.setattr(h.os.path, "realpath", lambda path, **kw: path)
    monkeypatch.setattr(h.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(h.os.path, "ismount", lambda path: False)
    if cause is None:
        h.refuse(path, "/srv/install")
    else:
        with pytest.raises(ValueError, match=f"^{cause}: {re.escape(path)} is /"):
            h.refuse(path, "/srv/install")


def test_helper_fails_closed_without_the_mount_table(monkeypatch):
    import sys
    from pathlib import PurePosixPath

    h = helper()

    def unreadable():
        raise PermissionError("mountinfo")

    h.mount_table = unreadable
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwall=lambda: []))
    monkeypatch.setattr(h, "Path", PurePosixPath)
    monkeypatch.setattr(h.os.path, "realpath", lambda path, **kw: path)
    monkeypatch.setattr(h.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(h.os.path, "ismount", lambda path: False)
    with pytest.raises(PermissionError):
        h.refuse("/srv/projects/acme", "/srv/install")


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="Linux ACL tools")
def test_revoke_removes_owned_group_after_growth_and_chmod(tmp_path):
    h = helper()
    import os

    folder = tmp_path / "shared"
    folder.mkdir()
    group = str(os.getgid())
    with h.opened(str(folder), parents_safe=False) as fd:
        record = {}
        h.grant(fd, group, True, record, lambda _: None)
        (folder / "new").write_text("data")
        h.run("setfacl", "-m", f"u:{os.getuid()}:r--", str(folder / "new"))
        folder.chmod(0o750)
        assert h.revoke(fd, record)
        assert f"group:{group}" not in h.acl(fd)
    text = h.run("getfacl", "-cpnE", str(folder / "new"))
    assert f"group:{group}:" not in text
    assert f"user:{os.getuid()}:r--" in text


def test_dropin_ignores_missing_paths_and_keeps_utf8(tmp_path, monkeypatch):
    h = helper()
    monkeypatch.setattr(h, "Path", lambda _: tmp_path)
    monkeypatch.setattr(h, "run", lambda *_: "")
    h.dropin("workbench", "files", [{"path": "/srv/fü %oo", "write": True}])
    assert 'ReadWritePaths=-"/srv/fü %%oo"' in (tmp_path / "20-folders.conf").read_text(
        "utf-8"
    )


def test_helper_names_its_python_requirement(monkeypatch):
    h = helper()
    monkeypatch.setattr(h.sys, "version_info", (3, 6, 0))
    with pytest.raises(ValueError, match="Folder access needs Python 3.10 or newer"):
        h.main()
    import ast

    ast.parse(
        (ROOT / "scripts/folder-access-helper.py").read_text("utf-8"),
        feature_version=(3, 6),
    )


def test_missing_acl_tools_names_the_package(monkeypatch):
    h = helper()

    def missing(*args, **kwargs):
        raise FileNotFoundError("getfacl")

    monkeypatch.setattr(h.subprocess, "run", missing)
    with pytest.raises(ValueError, match="acl package is missing"):
        h.acl(1)


def test_acl_install_failure_warns_and_continues(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not installed")
    source = (ROOT / "scripts/install.sh").read_text("utf-8")
    preamble = source.split("write_app_units() {\n", 1)[1].split(
        "    as_root install", 1
    )[0]
    script = tmp_path / "install-acl.sh"
    script.write_text(
        "set -eu\ncommand() { case \"$*\" in '-v apt-get') return 0;; *) return 1;; esac; }\nas_root() { return 1; }\nwarn() { printf '%s\\n' \"$*\"; }\ndie() { exit 99; }\n"
        + preamble
        + "printf 'resumed\\n'\n",
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run([bash, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "acl package" in result.stdout and "resumed" in result.stdout


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="Linux ACL tools")
def test_linux_plan_is_saved_once_and_setfacl_is_batched(tmp_path, monkeypatch):
    h = helper()
    import os

    for i in range(140):
        (tmp_path / str(i)).write_text("data")
    saves, calls = [], []
    original = h.run

    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(h, "run", counted)
    with h.opened(str(tmp_path), parents_safe=False) as fd:
        h.grant(fd, str(os.getgid()), True, {}, lambda r: saves.append(len(r["items"])))
    assert saves == [141]
    assert len([c for c in calls if c[0] == "setfacl"]) <= 3


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/srv/acme", True),
        ("/srv/other", False),
        ("/srv/acme-extra", False),
        ("/srv/with space", True),
    ],
)
def test_write_state_comes_from_the_running_mount_namespace(path, expected):
    mounts = "1 0 8:1 / / ro - ext4 /dev/sda ro\n2 1 8:1 /srv/acme /srv/acme rw - ext4 /dev/sda rw\n3 1 8:1 /srv/with\\040space /srv/with\\040space rw - ext4 /dev/sda rw\n"
    assert helper().write_mount(path, mounts) is expected


@pytest.mark.parametrize(("groups", "writable"), [("1000 1001", False), ("1000", True)])
def test_running_access_checks_process_groups_and_the_effective_namespace(
    monkeypatch, groups, writable
):
    h = helper()
    monkeypatch.setattr(h, "run", lambda *_: "123\n")
    files = {
        "/proc/123/status": f"Groups:\t{groups}\n",
        "/proc/123/mountinfo": f"1 0 8:1 / / {'rw' if writable else 'ro'} - ext4 /dev/sda rw\n",
    }
    monkeypatch.setattr(
        h, "Path", lambda name: SimpleNamespace(read_text=lambda: files[name])
    )
    assert h.running_access("workbench", "1000", "/srv/acme", True) == (
        123,
        not writable,
    )
    with pytest.raises(ValueError, match="does not have its file group"):
        h.running_access("workbench", "1002", "/srv/acme", True)


def test_stopped_app_waits_for_its_start_without_probe_or_restart_guess(monkeypatch):
    h = helper()
    monkeypatch.setattr(h, "run", lambda *_: "0\n")
    assert h.running_access("workbench", "1000", "/srv/acme", True) == (0, True)
    assert h.running_access("workbench", "1000", "/srv/acme", False) == (0, False)


def test_overlapping_mounts_do_not_guess_that_write_is_effective():
    mounts = "1 0 8:1 / / ro - ext4 /dev/sda ro\n2 1 8:1 /srv/acme /srv/acme rw - ext4 /dev/sda rw\n3 2 8:1 /srv/acme /srv/acme ro - ext4 /dev/sda ro\n"
    with pytest.raises(ValueError, match="More than one mount"):
        helper().write_mount("/srv/acme", mounts)


@pytest.fixture
def fake_tree(monkeypatch):
    """Exercise the real walk and ACL mutations without Linux ACLs on Windows."""
    h = helper()
    nodes = {10: ((), stat.S_IFDIR | 0o700, 1, 1)}
    permissions = {10: {"user:": "rwx", "group:": "---", "other:": "---"}}
    missing = {}
    calls = []

    def add(name, mode=stat.S_IFREG | 0o600, links=1, mount=1):
        fd = max(nodes) + 1
        nodes[fd] = ((name,), mode, links, mount)
        permissions[fd] = {"user:": "rw-", "group:": "---", "other:": "---"}
        return fd

    def info(fd):
        _, mode, links, _ = nodes[fd]
        return SimpleNamespace(st_mode=mode, st_nlink=links, st_dev=7, st_ino=fd)

    def lookup(name, parent, stage):
        if missing.get(name) == stage:
            raise FileNotFoundError(name)
        return next(
            fd for fd, item in nodes.items() if item[0] == (*nodes[parent][0], name)
        )

    def open_child(name, flags, *, dir_fd):
        child = lookup(name, dir_fd, "open")
        if stat.S_ISSOCK(nodes[child][1]) and not flags & 0x200000:
            raise OSError("Cannot open socket for data")
        return child

    fake_os = SimpleNamespace(
        fstat=info,
        stat=lambda name, *, dir_fd, follow_symlinks: info(
            lookup(name, dir_fd, "stat")
        ),
        listdir=lambda fd: [
            item[0][-1]
            for item in nodes.values()
            if item[0][:-1] == nodes[fd][0] and item[0]
        ],
        open=open_child,
        close=lambda fd: None,
        dup=lambda fd: fd,
        O_RDONLY=0,
        O_NOFOLLOW=0x20000,
        O_NONBLOCK=0x800,
        O_PATH=0x200000,
    )
    monkeypatch.setattr(h, "os", fake_os)
    monkeypatch.setattr(h, "identity", lambda fd: [fd, 1, 2])
    monkeypatch.setattr(h, "mount_id", lambda fd: nodes[fd][3], raising=False)
    monkeypatch.setattr(h, "acl", lambda fd: permissions[fd].copy())
    monkeypatch.setattr(h, "acls", lambda fds: [h.acl(fd) for fd in fds])
    monkeypatch.setattr(
        h, "set_acl", lambda fd, entries: permissions.__setitem__(fd, entries.copy())
    )

    def run(*args, **kwargs):
        calls.append(args)
        fds = kwargs.get("pass_fds", ())
        if "-x" in args:
            key = (
                args[args.index("-x") + 1]
                .replace("d:g:", "default:group:")
                .replace("g:", "group:")
            )
            for fd in fds:
                permissions[fd].pop(key, None)
        if "-k" in args or "--remove-default" in args:
            for fd in fds:
                permissions[fd] = {
                    k: v
                    for k, v in permissions[fd].items()
                    if not k.startswith("default:")
                }
        if "--restore=-" in args:
            for block in kwargs["input"].strip().split("\n\n"):
                header, body = block.split("\n", 1)
                permissions[int(header.rsplit("/", 1)[1])] = h.parse_acl(body)
        return ""

    monkeypatch.setattr(h, "run", run)
    return SimpleNamespace(
        h=h, nodes=nodes, acl=permissions, add=add, missing=missing, calls=calls
    )


def test_revoke_keeps_an_entry_the_group_had_before_the_grant(fake_tree):
    """Review: removal deleted a by-hand entry for Eugene's own group."""
    f = fake_tree
    seed = f.add("seed.txt")
    f.acl[seed].update({"group:1001": "r--", "mask:": "r--"})
    by_hand = f.acl[seed].copy()
    record = {}
    f.h.grant(10, "1001", False, record, lambda _: None)
    assert f.h.revoke(10, record)
    assert f.acl[seed] == by_hand


def test_revoke_restores_an_entry_the_grant_widened(fake_tree):
    f = fake_tree
    sub = f.add("sub", stat.S_IFDIR | 0o700)
    f.acl[sub] = {
        "user:": "rwx",
        "group:": "---",
        "other:": "---",
        "group:1001": "r-x",
        "mask:": "r-x",
    }
    before = f.acl[sub].copy()
    record = {}
    f.h.grant(10, "1001", True, record, lambda _: None)
    assert f.acl[sub]["group:1001"] == "rwx"
    assert f.h.revoke(10, record)
    assert f.acl[sub] == before


def test_revoke_restores_the_exact_acl_of_an_item_nobody_changed(fake_tree):
    """No mask or default entry is left behind where nothing else changed."""
    f = fake_tree
    seed = f.add("seed.txt")
    before = {fd: f.acl[fd].copy() for fd in (10, seed)}
    record = {}
    f.h.grant(10, "1001", False, record, lambda _: None)
    assert "mask:" in f.acl[seed] and "default:mask:" in f.acl[10]
    assert f.h.revoke(10, record)
    assert {fd: f.acl[fd] for fd in (10, seed)} == before


def test_revoke_keeps_a_by_hand_entry_on_a_file_renamed_after_the_grant(fake_tree):
    """Re-review: provenance was keyed by path, so a rename lost it."""
    f = fake_tree
    seed = f.add("seed.txt")
    f.acl[seed].update({"group:1001": "r--", "mask:": "r--"})
    by_hand = f.acl[seed].copy()
    record = {}
    f.h.grant(10, "1001", False, record, lambda _: None)
    f.nodes[seed] = (("moved.txt",), *f.nodes[seed][1:])  # the same inode, a new name
    assert f.h.revoke(10, record)
    assert f.acl[seed] == by_hand


def test_revoke_restores_a_file_renamed_after_the_grant(fake_tree):
    f = fake_tree
    seed = f.add("seed.txt")
    before = f.acl[seed].copy()
    record = {}
    f.h.grant(10, "1001", False, record, lambda _: None)
    f.nodes[seed] = (("moved.txt",), *f.nodes[seed][1:])
    assert f.h.revoke(10, record)
    assert f.acl[seed] == before


def test_grant_checks_again_just_before_it_saves_and_applies(fake_tree):
    f = fake_tree
    f.add("seed.txt")
    before = {fd: acl.copy() for fd, acl in f.acl.items()}
    saved = []

    def gained_a_name():
        raise ValueError("system: /srv/shared is /etc/ep-alias through a mount.")

    with pytest.raises(ValueError, match="^system:"):
        f.h.grant(10, "1001", False, {}, saved.append, check=gained_a_name)
    assert saved == []
    assert f.acl == before


def test_folder_grant_runs_the_refusals_again_right_before_applying(
    fake_tree, monkeypatch, tmp_path
):
    """Re-review: a bind made between the check and the grant gave the folder a
    forbidden name that nothing looked at again."""
    import sys

    f = fake_tree
    f.add("seed.txt")
    before = {fd: acl.copy() for fd, acl in f.acl.items()}
    checked = []

    def refuse(path, prefix):
        checked.append(path)
        if len(checked) == 2:
            raise ValueError("system: /srv/shared is /etc/ep-alias through a mount.")

    ident = "c" * 32
    monkeypatch.setattr(f.h, "refuse", refuse)
    monkeypatch.setitem(
        sys.modules,
        "grp",
        SimpleNamespace(getgrnam=lambda _: SimpleNamespace(gr_gid=1001)),
    )
    monkeypatch.setattr(
        f.h,
        "sys",
        SimpleNamespace(
            version_info=(3, 12),
            argv=["helper", "/srv/install", "agent", "folder-grant", "workbench", "read", ident],
        ),
    )
    monkeypatch.setattr(
        f.h,
        "Path",
        lambda p: SimpleNamespace(read_text=lambda: MOUNT_ROOT)
        if p == "/proc/self/mountinfo"
        else tmp_path,
    )
    fake_run = f.h.run

    def run(*args, **kwargs):
        if args[0] == "runuser":
            return "/srv/shared" if "4097" in args else json.dumps([10, 1, 2])
        return fake_run(*args, **kwargs)

    monkeypatch.setattr(f.h, "run", run)
    monkeypatch.setattr(f.h, "running_access", lambda *args: (0, False))
    monkeypatch.setattr(
        f.h, "write_record", lambda path, data: path.write_text(json.dumps(data))
    )
    monkeypatch.setattr(f.h, "dropin", lambda *args: None)

    @contextlib.contextmanager
    def opened(path, **kwargs):
        yield 10

    monkeypatch.setattr(f.h, "opened", opened)
    with pytest.raises(ValueError, match="^system:"):
        f.h.main()
    assert checked == ["/srv/shared", "/srv/shared"]
    assert f.acl == before
    assert not (tmp_path / "workbench" / (ident + ".json")).exists()


@pytest.mark.parametrize("stage", ["stat", "open"])
def test_revoke_continues_after_a_child_vanishes(fake_tree, stage):
    f = fake_tree
    f.add("vanishing")
    last = f.add("last")
    record = {}
    f.h.grant(10, "1001", True, record, lambda _: None)
    f.missing["vanishing"] = stage
    assert f.h.revoke(10, record)
    assert "group:1001" not in f.acl[last]


def test_revoke_does_not_hide_an_unexpected_missing_file(
    fake_tree, monkeypatch, tmp_path
):
    f = fake_tree
    record = {"path": "/srv/shared", "identity": [10, 1, 2], "items": [{}]}
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)

    def missing(*args):
        raise FileNotFoundError("Unexpected ACL tool failure")

    monkeypatch.setattr(f.h, "revoke", missing)
    with pytest.raises(FileNotFoundError, match="Unexpected ACL"):
        f.h.main()
    assert not json.loads(target.read_text()).get("removed")


def configure_revoke_main(f, monkeypatch, tmp_path, record):
    import sys

    directory = tmp_path / "workbench"
    directory.mkdir(exist_ok=True)
    ident = "a" * 32
    target = directory / (ident + ".json")
    target.write_text(json.dumps(record))
    monkeypatch.setitem(
        sys.modules,
        "grp",
        SimpleNamespace(getgrnam=lambda _: SimpleNamespace(gr_gid=1001)),
    )
    monkeypatch.setattr(
        f.h,
        "sys",
        SimpleNamespace(
            version_info=(3, 12),
            argv=[
                "helper",
                "/srv/install",
                "agent",
                "folder-revoke",
                "workbench",
                "read",
                ident,
            ],
        ),
    )
    monkeypatch.setattr(f.h, "Path", lambda _: tmp_path)
    monkeypatch.setattr(
        f.h, "write_record", lambda path, data: path.write_text(json.dumps(data))
    )
    monkeypatch.setattr(f.h, "dropin", lambda *args: None)

    @contextlib.contextmanager
    def opened(path, **kwargs):
        yield 10

    monkeypatch.setattr(f.h, "opened", opened)
    return target


def test_grant_then_home_policy_still_inspects_and_revokes(
    fake_tree, monkeypatch, tmp_path, capsys
):
    import sys
    from pathlib import PurePosixPath

    f = fake_tree
    homes = []
    monkeypatch.setitem(
        sys.modules,
        "pwd",
        SimpleNamespace(getpwall=lambda: [SimpleNamespace(pw_dir=p) for p in homes]),
    )
    monkeypatch.setattr(f.h, "Path", PurePosixPath)
    f.h.os.path = SimpleNamespace(
        realpath=lambda path, **kw: path,
        isdir=lambda path: True,
        ismount=lambda path: False,
    )

    @contextlib.contextmanager
    def opened(path, **kwargs):
        yield 10

    monkeypatch.setattr(f.h, "opened", opened)
    before = f.h.inspect_folder("/srv/shared", "/srv/install")
    original = f.acl[10].copy()
    record = {"path": "/srv/shared", "identity": before["identity"]}
    assert f.h.grant(10, "1001", False, record, lambda _: None)
    homes.append("/srv/shared/person")
    after = f.h.inspect_folder("/srv/shared", "/srv/install")
    assert after["facts"]["homes"] == ["/srv/shared"]
    assert after["identity"] == before["identity"] == [10, 1, 2]
    with pytest.raises(ValueError, match="^home:"):
        f.h.refuse("/srv/shared", "/srv/install")
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    f.h.main()
    assert json.loads(capsys.readouterr().out)["removed"]
    assert json.loads(target.read_text())["removed"]
    assert any(call[0] == "setfacl" for call in f.calls)
    assert f.acl[10] == original


@pytest.mark.parametrize("replaced", [False, True])
def test_revoke_under_now_unsafe_parent_uses_only_ledger_identity(
    fake_tree, monkeypatch, tmp_path, capsys, replaced
):
    f = fake_tree
    record = {"path": "/srv/shared", "identity": [10, 1, 2]}
    assert f.h.grant(10, "1001", True, record, lambda _: None)
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)

    @contextlib.contextmanager
    def opened(path, *, parents_safe=True, allow_mount_root=False):
        assert path == record["path"]
        if parents_safe:
            raise ValueError("/srv can be changed by other accounts.")
        assert allow_mount_root  # A later drive-root policy must not block revoke.
        yield 10

    monkeypatch.setattr(f.h, "opened", opened)
    monkeypatch.setattr(
        f.h, "refuse", lambda *args: pytest.fail("Revoke checked new-grant policy")
    )
    if replaced:
        monkeypatch.setattr(f.h, "identity", lambda fd: [fd, 9, 9])
    f.h.main()
    assert json.loads(capsys.readouterr().out)["removed"] is (not replaced)
    assert bool(json.loads(target.read_text()).get("removed")) is (not replaced)
    assert ("group:1001" in f.acl[10]) is replaced


@pytest.mark.parametrize("kind", ["hardlink", "fifo", "socket"])
def test_revoke_removes_group_from_new_unusual_items(fake_tree, kind):
    f = fake_tree
    record = {}
    f.h.grant(10, "1001", True, record, lambda _: None)
    mode = {"hardlink": stat.S_IFREG, "fifo": stat.S_IFIFO, "socket": stat.S_IFSOCK}[
        kind
    ]
    child = f.add(kind, mode | 0o600, links=2 if kind == "hardlink" else 1)
    f.acl[child]["group:1001"] = "rw-"
    assert f.h.revoke(10, record)
    assert "group:1001" not in f.acl[child]


def test_revoke_reports_unsupported_special_acl_and_finishes_other_items(
    fake_tree, monkeypatch
):
    f = fake_tree
    record = {}
    f.h.grant(10, "1001", True, record, lambda _: None)
    special = f.add("socket", stat.S_IFSOCK | 0o600)
    last = f.add("last")
    f.acl[last]["group:1001"] = "r--"
    original = f.h.acl

    def unsupported(fd):
        if fd == special:
            raise ValueError("Operation not supported")
        return original(fd)

    monkeypatch.setattr(f.h, "acl", unsupported)
    assert not f.h.revoke(10, record)
    assert "group:1001" not in f.acl[last]
    assert (
        "socket" in record["refusal"] and "Operation not supported" in record["refusal"]
    )


def test_same_device_bind_mount_is_refused_on_grant_and_skipped_on_revoke(fake_tree):
    f = fake_tree
    mounted = f.add("bind", stat.S_IFDIR | 0o700, mount=2)
    f.nodes[15] = (("bind", "private"), stat.S_IFREG | 0o600, 1, 2)
    f.acl[15] = {"user:": "rw-", "group:": "---", "other:": "---", "group:1001": "rw-"}
    private = f.acl[15].copy()
    f.acl[mounted]["group:1001"] = "rwx"
    with pytest.raises(ValueError, match="mounted descendant"):
        f.h.grant(10, "1001", False, {}, lambda _: None)
    last = f.add("last")
    f.acl[last]["group:1001"] = "r--"
    record = {"group": "1001", "items": [{}]}
    assert not f.h.revoke(10, record)
    assert f.acl[15] == private
    assert "group:1001" not in f.acl[last]
    assert "mounted descendant" in record["refusal"]


@pytest.mark.parametrize("named", ["group:", "user:42"])
def test_masked_execute_does_not_make_a_readable_file_executable(named):
    before = {
        "user:": "rw-",
        "group:": "r-x",
        "other:": "---",
        "mask:": "r--",
        named: "r-x",
    }
    after = helper().plan(before, "1001", False, False)
    assert after["group:1001"] == "r--"
    assert after["mask:"] == "r--"


def test_bind_mounted_root_is_refused_by_the_held_mount_ids(monkeypatch):
    from pathlib import PurePosixPath

    h = helper()
    fds = iter((1, 2, 3))
    closed = []
    monkeypatch.setattr(h, "Path", PurePosixPath)
    monkeypatch.setattr(
        h,
        "os",
        SimpleNamespace(
            open=lambda *args, **kwargs: next(fds),
            close=closed.append,
            fstat=lambda fd: SimpleNamespace(st_uid=0),
            O_RDONLY=0,
            O_DIRECTORY=1,
            O_NOFOLLOW=2,
        ),
    )
    monkeypatch.setattr(
        h, "acl", lambda fd: {"user:": "rwx", "group:": "r-x", "other:": "---"}
    )
    monkeypatch.setattr(h, "mount_id", lambda fd: 2 if fd == 3 else 1)
    with pytest.raises(ValueError, match="mounted drive"):
        with h.opened("/srv/bind"):
            pytest.fail("A bind mount root must never be yielded")
    assert closed == [3, 2, 1]


def test_mount_id_is_read_from_the_held_descriptor(monkeypatch):
    h = helper()
    paths = []

    def path(name):
        paths.append(name)
        return SimpleNamespace(read_text=lambda: "pos:\t0\nmnt_id:\t1234\nino:\t99\n")

    monkeypatch.setattr(h, "Path", path)
    assert h.mount_id(12) == 1234
    assert paths == ["/proc/self/fdinfo/12"]


@pytest.mark.parametrize("existing_default", [False, True])
def test_revoke_removes_only_defaults_it_created(fake_tree, existing_default):
    f = fake_tree
    if existing_default:
        f.acl[10].update({"default:" + k: v for k, v in list(f.acl[10].items())})
    before = f.acl[10].copy()
    record = {}
    f.h.grant(10, "1001", True, record, lambda _: None)
    assert f.h.revoke(10, record)
    assert any(k.startswith("default:") for k in f.acl[10]) is existing_default
    if existing_default:
        assert f.acl[10]["default:group:"] == before["default:group:"]


@pytest.mark.parametrize("key", ["user:", "group:", "other:", "mask:"])
def test_revoke_preserves_edited_default_values(fake_tree, key):
    f = fake_tree
    record = {}
    f.h.grant(10, "1001", True, record, lambda _: None)
    f.acl[10]["default:" + key] = "r--"
    expected = {
        k: v
        for k, v in f.acl[10].items()
        if k.startswith("default:") and k != "default:group:1001"
    }
    assert f.h.revoke(10, record)
    assert {k: v for k, v in f.acl[10].items() if k.startswith("default:")} == expected


@pytest.mark.parametrize("kind", ["hardlink", "fifo", "socket", "device"])
def test_reapply_skips_unsafe_items_and_restores_accepted_items(
    fake_tree, monkeypatch, tmp_path, capsys, kind
):
    f = fake_tree
    child = f.add("child", stat.S_IFDIR | 0o700)
    parent = {"path": "/srv/shared", "identity": [10, 1, 2], "write": False}
    f.h.grant(10, "1001", False, parent, lambda _: None)
    record = {"path": "/srv/shared/child", "identity": [child, 1, 2], "write": True}
    f.h.grant(child, "1001", True, record, lambda _: None)
    mode = {
        "hardlink": stat.S_IFREG,
        "fifo": stat.S_IFIFO,
        "socket": stat.S_IFSOCK,
        "device": stat.S_IFCHR,
    }[kind]
    unsafe = f.add(kind, mode | 0o600, links=2 if kind == "hardlink" else 1)
    f.nodes[unsafe] = (("child", kind), *f.nodes[unsafe][1:])
    untouched = f.acl[unsafe].copy()
    last = f.add("last")
    f.nodes[last] = (("child", "last"), *f.nodes[last][1:])
    f.acl[last]["group:1001"] = "rw-"
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    (target.parent / ("b" * 32 + ".json")).write_text(json.dumps(parent))

    @contextlib.contextmanager
    def opened(path, **kwargs):
        yield child if path.endswith("/child") else 10

    monkeypatch.setattr(f.h, "opened", opened)
    original = f.h.acl

    def readable(fd):
        # Removal may inspect unusual objects, but reapply must skip them
        # before asking for their ACL or adding rights to an outside inode.
        if fd == unsafe and any("-x" in call for call in f.calls):
            pytest.fail("Reapply read an ACL it must never restore")
        return original(fd)

    monkeypatch.setattr(f.h, "acl", readable)
    f.h.main()
    outcome = json.loads(capsys.readouterr().out)
    assert not outcome["removed"]
    assert f"/srv/shared/child/{kind}" in outcome["message"]
    assert ("hard link" if kind == "hardlink" else "special file") in outcome["message"]
    assert f.acl[unsafe] == untouched
    assert f.acl[last]["group:1001"] == "r--"
    assert f.acl[child]["group:1001"] == "r-x"


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("The folder cannot be opened"),
        ValueError("A parent folder is writable by an account other than root"),
    ],
)
@pytest.mark.parametrize("healthy", [False, True])
def test_reapply_reports_unavailable_related_record_and_continues(
    fake_tree, monkeypatch, tmp_path, capsys, error, healthy
):
    f = fake_tree
    record = {"path": "/srv/shared", "identity": [10, 1, 2], "write": True}
    f.h.grant(10, "1001", True, record, lambda _: None)
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    unavailable = dict(record, path="/srv/shared/unavailable")
    (target.parent / ("b" * 32 + ".json")).write_text(json.dumps(unavailable))
    if healthy:
        (target.parent / ("c" * 32 + ".json")).write_text(
            json.dumps(dict(record, write=False))
        )

    @contextlib.contextmanager
    def opened(path, **kwargs):
        if path.endswith("/unavailable"):
            raise error
        yield 10

    monkeypatch.setattr(f.h, "opened", opened)
    f.h.main()
    outcome = json.loads(capsys.readouterr().out)
    assert not outcome["removed"]
    assert unavailable["path"] in outcome["message"]
    assert str(error) in outcome["message"]
    assert f.acl[10].get("group:1001") == ("r-x" if healthy else None)


@pytest.mark.parametrize("error", [FileNotFoundError, NotADirectoryError])
def test_revoke_parent_completes_after_a_granted_subfolder_is_deleted(
    fake_tree, monkeypatch, tmp_path, capsys, error
):
    f = fake_tree
    child = f.add("sub", stat.S_IFDIR | 0o700)
    parent = {"path": "/x", "identity": [10, 1, 2], "write": False}
    f.h.grant(10, "1001", False, parent, lambda _: None)
    record = {"path": "/x/sub", "identity": [child, 1, 2], "write": True}
    f.h.grant(child, "1001", True, record, lambda _: None)
    target = configure_revoke_main(f, monkeypatch, tmp_path, parent)
    (target.parent / ("b" * 32 + ".json")).write_text(json.dumps(record))
    del f.nodes[child]
    del f.acl[child]

    @contextlib.contextmanager
    def opened(path, **kwargs):
        if path == "/x/sub":
            raise error("The folder no longer exists")
        yield 10

    monkeypatch.setattr(f.h, "opened", opened)
    f.h.main()
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["removed"]
    assert outcome["message"] == ""
    assert json.loads(target.read_text())["removed"]
    assert "group:1001" not in f.acl[10]


@pytest.mark.parametrize("unsafe", [False, True])
def test_revoke_reports_reapplied_additions_to_a_preexisting_parent(
    fake_tree, monkeypatch, tmp_path, capsys, unsafe
):
    f = fake_tree
    f.acl[10] = f.h.plan(f.acl[10], "1001", False, True)
    parent = {"path": "/x", "identity": [10, 1, 2], "write": False}
    assert not f.h.grant(10, "1001", False, parent, lambda _: None)
    assert parent["items"] == []
    child = f.add("sub", stat.S_IFDIR | 0o700)
    record = {"path": "/x/sub", "identity": [child, 1, 2], "write": True}
    assert f.h.grant(child, "1001", True, record, lambda _: None)
    if unsafe:
        special = f.add("socket", stat.S_IFSOCK | 0o600)
        f.nodes[special] = (("sub", "socket"), *f.nodes[special][1:])
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    parent_file = target.parent / ("b" * 32 + ".json")
    parent_file.write_text(json.dumps(parent))

    @contextlib.contextmanager
    def opened(path, **kwargs):
        yield child if path == "/x/sub" else 10

    monkeypatch.setattr(f.h, "opened", opened)
    f.h.main()
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["removed"] is (not unsafe)
    saved = json.loads(parent_file.read_text())
    assert saved["items"][0]["names"] == ["sub"]
    assert f.acl[child]["group:1001"] == "r-x"
    assert outcome["reapplied"] == [parent_file.stem]


@pytest.mark.parametrize("existing_item", [False, True])
def test_reapply_records_default_additions_before_changing_them(
    fake_tree, monkeypatch, tmp_path, capsys, existing_item
):
    f = fake_tree
    parent = {"path": "/srv/shared", "identity": [10, 1, 2], "write": False}
    f.h.grant(10, "1001", False, parent, lambda _: None)
    record = {"path": "/srv/shared", "identity": [10, 1, 2], "write": True}
    f.h.grant(10, "1001", True, record, lambda _: None)
    child = f.add("new", stat.S_IFDIR | 0o700)
    if existing_item:
        parent["items"].append(
            dict(names=["new"], identity=[child, 0, 0], before={}, after={})
        )
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    parent_file = target.parent / ("b" * 32 + ".json")
    parent_file.write_text(json.dumps(parent))
    original = f.h.set_acl

    def recorded(fd, after):
        if fd == child:
            saved = json.loads(parent_file.read_text())
            assert any(
                item["names"] == ["new"] and item["identity"] == [child, 1, 2]
                for item in saved["items"]
            ), "Reapply must save ownership before adding defaults"
        original(fd, after)

    monkeypatch.setattr(f.h, "set_acl", recorded)
    f.h.main()
    assert json.loads(capsys.readouterr().out)["removed"]
    assert f.acl[child]["default:group:1001"] == "r-x"
    parent = json.loads(parent_file.read_text())
    assert f.h.revoke(10, parent)
    assert not any(k.startswith("default:") for k in f.acl[child])


@pytest.mark.parametrize("unsafe_parent", [False, True])
def test_revoking_child_write_reapplies_parent_read(
    fake_tree, monkeypatch, tmp_path, unsafe_parent
):
    f = fake_tree
    child = f.add("child", stat.S_IFDIR | 0o700)
    file = f.add("temporary")
    f.nodes[file] = (("child", "file"), stat.S_IFREG | 0o600, 1, 1)
    parent = {"path": "/srv/shared", "identity": [10, 1, 2], "write": False}
    f.h.grant(10, "1001", False, parent, lambda _: None)
    record = {"path": "/srv/shared/child", "identity": [child, 1, 2], "write": True}
    f.h.grant(child, "1001", True, record, lambda _: None)
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    (target.parent / ("b" * 32 + ".json")).write_text(json.dumps(parent))

    @contextlib.contextmanager
    def opened(path, *, parents_safe=True, allow_mount_root=False):
        if unsafe_parent and parents_safe:
            raise ValueError("/srv can be changed by other accounts.")
        yield child if path.endswith("/child") else 10

    monkeypatch.setattr(f.h, "opened", opened)
    f.h.main()
    assert json.loads(target.read_text())["removed"]
    assert f.acl[file]["group:1001"] == "r--"
    assert f.acl[child]["group:1001"] == "r-x"


def test_overlap_restoration_continues_past_an_unsupported_special_acl(
    fake_tree, monkeypatch, tmp_path, capsys
):
    f = fake_tree
    parent = {"path": "/srv/shared", "identity": [10, 1, 2], "write": False}
    f.h.grant(10, "1001", False, parent, lambda _: None)
    record = {"path": "/srv/shared", "identity": [10, 1, 2], "write": True}
    f.h.grant(10, "1001", True, record, lambda _: None)
    special = f.add("socket", stat.S_IFSOCK | 0o600)
    last = f.add("last")
    f.acl[last]["group:1001"] = "rw-"
    target = configure_revoke_main(f, monkeypatch, tmp_path, record)
    (target.parent / ("b" * 32 + ".json")).write_text(json.dumps(parent))
    original = f.h.acl

    def unsupported(fd):
        if fd == special:
            raise ValueError("Operation not supported")
        return original(fd)

    monkeypatch.setattr(f.h, "acl", unsupported)
    f.h.main()
    assert not json.loads(capsys.readouterr().out)["removed"]
    assert not json.loads(target.read_text()).get("removed")
    assert f.acl[last]["group:1001"] == "r--"


def acceptance():
    spec = importlib.util.spec_from_file_location(
        "acceptance", ROOT / "scripts/row23-folder-access-acceptance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_checks_apps_read_of_its_created_file(tmp_path, monkeypatch):
    module = acceptance()
    calls = []

    def probe(io, folder, read_file="seed.txt"):
        calls.append(read_file)
        return {"read": read_file != "seed.txt", "write": False}

    monkeypatch.setattr(module, "probe", probe)
    with pytest.raises(AssertionError):
        module.assert_app_revoked(tmp_path, tmp_path, tmp_path / "created.txt")
    assert calls == ["seed.txt", "created.txt"]


@pytest.mark.parametrize("bad_cause", [None, "home:"])
def test_acceptance_sends_unsafe_paths_directly_to_root_broker(tmp_path, bad_cause):
    module = acceptance()
    seen = []
    link = tmp_path / "link"

    def broker(verb, *, expect_success=True):
        assert not expect_success
        ident = verb.split()[-1]
        path = (tmp_path / (ident + ".path")).read_text()
        seen.append(path)
        return {
            "code": 1,
            "output": bad_cause or ("system:" if path == "/etc" else "link:"),
        }

    if bad_cause:
        with pytest.raises(AssertionError):
            module.root_refusals(tmp_path, broker, link, lambda _: None)
    else:
        module.root_refusals(tmp_path, broker, link, lambda _: None)
        assert seen == ["/etc", str(link)]


def test_acceptance_swap_proves_target_acl_and_content_unchanged(tmp_path):
    module = acceptance()
    folder, target = tmp_path / "folder", tmp_path / "target"
    folder.mkdir()
    target.mkdir()
    (target / "seed.txt").write_text("private")
    touched = []

    def link(path, destination):
        path.mkdir()  # Fake the link on hosts without symlink privileges.

    def remove(ident):
        touched.append(ident)
        return {"state": "changed_outside" if len(touched) == 1 else "removed"}

    module.swapped_folder(
        lambda path: {"id": "grant", "state": "ready"},
        remove,
        folder,
        target,
        lambda path: b"private ACL",
        link,
    )
    assert touched == ["grant", "grant"]
    assert (target / "seed.txt").read_text() == "private"


def test_acceptance_release_checks_lookup_one_id_and_foreign_id():
    module = acceptance()
    states = {"one": "ready", "two": "ready", "foreign": "ready"}
    calls = []

    def post(url, *, json, headers):
        assert headers == {"Authorization": "Bearer app-key"}
        assert url == "/v1/apps/workbench/folder-access/release"
        calls.append(json)
        if json.get("id") == "foreign":
            return SimpleNamespace(status_code=404, text="not found")
        if "id" in json:
            states[json["id"]] = "removed"
        return SimpleNamespace(
            status_code=200,
            text="ok",
            json=lambda: {"grants": [{"id": "one", "state": states["one"]}]},
        )

    module.check_release(
        SimpleNamespace(post=post),
        "app-key",
        "/srv/one",
        "one",
        "foreign",
        lambda: states.copy(),
    )
    assert calls == [{"path": "/srv/one"}, {"id": "one"}, {"id": "foreign"}]


def test_linux_unprivileged_part_never_asks_a_broker_it_has_not_installed(
    tmp_path, monkeypatch
):
    """Linux inspection goes through the root broker, which the root part installs.

    Asking it before then waited forever: 13 silent minutes, then the job limit.
    """
    import sys

    module = acceptance()
    report = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["acceptance", "--report", str(report)])
    monkeypatch.setattr(
        module,
        "os",
        SimpleNamespace(name="posix", environ={"RUNNER_ENVIRONMENT": "github-hosted"}),
    )

    def too_early(_):
        pytest.fail("Linux refusals need the root broker, which is not installed yet")

    monkeypatch.setattr(module, "refusals", too_early)
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    module.main()
    assert calls[-1][0] == "sudo" and "--linux-root" in calls[-1]
    assert "-u" in calls[-1], "The root part must print each step as it happens"


def test_every_command_is_bounded_and_names_itself_when_it_stalls():
    import sys

    module = acceptance()
    with pytest.raises(RuntimeError, match="did not finish in 0.5 seconds"):
        module.run(sys.executable, "-c", "import time; time.sleep(30)", timeout=0.5)
    with pytest.raises(AssertionError, match="The broker did not answer.*\nbroker log"):
        module.wait_for(
            lambda: False, seconds=0.2, what="The broker", detail=lambda: "broker log"
        )


@pytest.mark.skipif(
    __import__("os").name != "nt", reason="Windows service registration"
)
def test_windows_probe_service_is_registered_like_an_app_and_can_read_its_script(
    tmp_path, monkeypatch
):
    """The 1053 rounds: the service could not read a script inside a mkdtemp folder."""
    import ctypes

    import win32security
    import win32serviceutil

    module = acceptance()
    events = []
    monkeypatch.setattr(ctypes.windll.shell32, "IsUserAnAdmin", lambda: 1)
    monkeypatch.setattr(
        module, "create_service", lambda *args: events.append(("create", *args))
    )
    monkeypatch.setattr(
        module, "run", lambda *args, **kwargs: events.append(args) or ""
    )
    monkeypatch.setattr(
        win32security,
        "LookupAccountName",
        lambda *_: (win32security.ConvertStringSidToSid("S-1-5-80-1-2-3-4-5"), "", 5),
    )

    def start(name):
        events.append(("start", name))
        raise RuntimeError("1053")

    monkeypatch.setattr(win32serviceutil, "StartService", start)
    monkeypatch.setattr(module, "service_diagnostics", lambda *_: "diagnostics")
    monkeypatch.setattr(
        module, "remove_service", lambda n: events.append(("remove", n))
    )
    with pytest.raises(AssertionError, match="did not start: 1053\ndiagnostics"):
        module.windows(tmp_path)
    created = [event for event in events if event[0] == "create"]
    assert [event[1] for event in created] == ["EpR23Probe", "EpR23Other"]
    script = tmp_path / "probe" / "service_probe.py"
    assert script.is_file()
    grants = {
        (args[1], args[3])
        for args in events
        if args[0] == "icacls" and args[2] in ("/grant", "/grant:r")
    }
    for _, name, account, command in created:
        assert account == "NT SERVICE\\" + name
        own_io = tmp_path / ("probe-io" if name == "EpR23Probe" else "other-io")
        assert f' -I -u "{script}" "{own_io}" {name}' in command
        assert (str(script.parent), account + ":(OI)(CI)(RX)") in grants
        assert (str(own_io), account + ":(OI)(CI)(M)") in grants
    last_grant = max(i for i, args in enumerate(events) if args[0] == "icacls")
    assert events.index(("start", "EpR23Probe")) > last_grant
    assert events[-2:] == [("remove", "EpR23Probe"), ("remove", "EpR23Other")]
