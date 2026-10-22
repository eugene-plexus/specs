"""The privilege acceptance must run on both real operating systems."""

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def helper():
    spec = importlib.util.spec_from_file_location(
        "folder_helper", ROOT / "scripts/folder-access-helper.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
    source = (ROOT / "scripts/folder-access-helper.py").read_text("utf-8").rstrip()
    installed = (
        (ROOT / "scripts/install.sh")
        .read_text("utf-8")
        .split("<<'FOLDER_HELPER'\n", 1)[1]
        .split("\nFOLDER_HELPER", 1)[0]
    )
    assert installed == source


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
