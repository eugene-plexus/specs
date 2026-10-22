"""The privilege acceptance must run on both real operating systems."""

import importlib.util
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


def test_installed_helper_is_exactly_the_reviewed_source():
    source = (ROOT / "scripts/folder-access-helper.py").read_text("utf-8").rstrip()
    installed = (
        (ROOT / "scripts/install.sh")
        .read_text("utf-8")
        .split("<<'FOLDER_HELPER'\n", 1)[1]
        .split("\nFOLDER_HELPER", 1)[0]
    )
    assert installed == source


def test_masked_acl_entry_is_refused_without_widening():
    h = helper()
    before = {
        "user:": "rwx",
        "group:": "r--",
        "other:": "---",
        "user:1000": "rwx",
        "mask:": "r--",
    }
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


def test_revoke_leaves_unrecorded_inherited_rights_as_changed_outside(monkeypatch):
    h = helper()
    monkeypatch.setattr(h, "identity", lambda _: [1, 2, 3, 4, 5])
    monkeypatch.setattr(
        h,
        "tree",
        lambda *_: iter([((), 10, [1, 2, 3, 4, 5]), (("new",), 11, [1, 3, 4, 5, 6])]),
    )
    monkeypatch.setattr(h, "acl", lambda _: {"group:1000": "r-x"})
    changed = []
    monkeypatch.setattr(h, "set_acl", lambda *args: changed.append(args))
    record = {
        "group": "1000",
        "seen": [[[], [1, 2, 3, 4, 5]]],
        "items": [
            {
                "names": [],
                "identity": [1, 2, 3, 4, 5],
                "before": {},
                "after": {"group:1000": "r-x"},
            }
        ],
    }
    assert not h.revoke(10, record)
    assert changed == []


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
