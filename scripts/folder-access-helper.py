"""Root-owned Linux folder broker. Installed verbatim by write_app_units().

No imports from the agent or files it owns. All filesystem changes use held
file descriptors. The command line accepts identifiers, never paths or ACLs.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
from pathlib import Path

SYSTEM = tuple(
    "/" + n
    for n in "bin boot dev etc lib lib32 lib64 libx32 opt proc root run sbin snap sys tmp usr var".split()
)


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode:
        raise ValueError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"{args[0]} failed ({result.returncode})"
        )
    return result.stdout


def identity(fd):
    data = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    if (
        libc.statx(fd, b"", 0x1000, 0x1800, data)
        or struct.unpack_from("=I", data)[0] & 0x1800 != 0x1800
    ):
        raise ValueError(
            "The filesystem does not expose folder creation time and mount identity."
        )
    info = os.fstat(fd)
    seconds, nanos = struct.unpack_from("=qI", data, 80)
    return [
        info.st_dev,
        info.st_ino,
        seconds,
        nanos,
        struct.unpack_from("=Q", data, 144)[0],
    ]


def acl(fd):
    text = run("getfacl", "-cpn", "--", f"/proc/self/fd/{fd}", pass_fds=(fd,))
    return dict(
        (line.rsplit(":", 1)[0], line.rsplit(":", 1)[1].split()[0])
        for line in text.splitlines()
        if line and not line.startswith("#")
    )


def bits(value):
    return sum(bit for letter, bit in (("r", 4), ("w", 2), ("x", 1)) if letter in value)


def words(value):
    return "".join(
        letter if value & bit else "-" for letter, bit in (("r", 4), ("w", 2), ("x", 1))
    )


def plan(before, group, write, directory):
    """Preserve every existing entry; widening a masked entry is refused."""
    after = before.copy()
    for prefix in ("", "default:") if directory else ("",):
        mask = bits(before.get(prefix + "mask:", "rwx"))
        for key, rights in before.items():
            if (
                key.startswith(prefix)
                and (
                    key.startswith(prefix + "group:")
                    or (key.startswith(prefix + "user:") and key != prefix + "user:")
                )
                and bits(rights) & ~mask
            ):
                raise ValueError(
                    "A named or group ACL entry is masked out; changing the mask would widen its access."
                )
        if prefix and not any(key.startswith(prefix) for key in before):
            for key in ("user:", "group:", "other:"):
                after[prefix + key] = before[key]
        desired = 6 if write else 4
        if (
            directory
            or prefix
            or any(
                "x" in p for key, p in before.items() if not key.startswith("default:")
            )
        ):
            desired |= 1
        key = prefix + f"group:{group}"
        after[key] = words(bits(before.get(key, "---")) | desired)
        # An explicit mask preserves the effective rights of every older entry.
        after[prefix + "mask:"] = (
            words(mask | desired)
            if prefix + "mask:" in before
            else words(desired | bits(after[prefix + "group:"]))
        )
    return after


def set_acl(fd, entries):
    run(
        "setfacl",
        "--no-mask",
        "--set-file=-",
        "--",
        f"/proc/self/fd/{fd}",
        input="\n".join(k + ":" + v for k, v in entries.items()) + "\n",
        pass_fds=(fd,),
    )
    if stat.S_ISDIR(os.fstat(fd).st_mode) and not any(
        k.startswith("default:") for k in entries
    ):
        run("setfacl", "--remove-default", "--", f"/proc/self/fd/{fd}", pass_fds=(fd,))


def write_record(path, data):
    temp = path.with_suffix(".new")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def related(path, root):
    return (
        path == root
        or path.startswith(root.rstrip("/") + "/")
        or root.startswith(path.rstrip("/") + "/")
    )


def refuse(path, prefix):
    if any(ord(c) < 32 or ord(c) == 127 for c in path) or not path.startswith("/"):
        raise ValueError(
            "not_a_folder: Use an absolute path without control characters."
        )
    if path.startswith("//"):
        raise ValueError("network: Network folders are not supported.")
    if os.path.realpath(path, strict=True) != path:
        raise ValueError("link: Choose an existing folder, not a link or a path alias.")
    if not os.path.isdir(path):
        raise ValueError("not_a_folder: Choose an existing folder.")
    if os.path.ismount(path):
        raise ValueError("drive_root: Choose a folder inside the drive.")
    if related(path, prefix):
        raise ValueError("eugene: This is Eugene's own folder.")
    import pwd

    homes = ["/home"] + [
        p.pw_dir
        for p in pwd.getpwall()
        if p.pw_dir.startswith("/") and p.pw_dir not in ("/", "/nonexistent")
    ]
    if any(related(path, home) for home in homes):
        raise ValueError("home: Use a Job Site to work in your own folders.")
    if any(related(path, system) for system in SYSTEM) or Path(path).parts[
        1
    ].startswith("lib"):
        raise ValueError("system: Eugene does not give apps system folders.")


@contextlib.contextmanager
def opened(path, *, parents_safe=True):
    held = [os.open("/", os.O_RDONLY | os.O_DIRECTORY)]
    try:
        for name in Path(path).parts[1:]:
            parent = held[-1]
            info = os.fstat(parent)
            if parents_safe:
                permissions = acl(parent)
                mask = bits(permissions.get("mask:", "rwx"))
                foreign_write = any(
                    bits(rights)
                    & (mask if key.startswith(("group:", "user:")) else 7)
                    & 2
                    for key, rights in permissions.items()
                    if key not in ("user:", "user:0", "mask:")
                    and not key.startswith("default:")
                )
                if info.st_uid != 0 or foreign_write:
                    raise ValueError(
                        "A parent folder is writable by an account other than root."
                    )
            held.append(
                os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
            )
        yield held[-1]
    finally:
        for fd in reversed(held):
            os.close(fd)


def tree(fd, mount, names=()):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("A special file is inside this folder.")
        if info.st_nlink != 1:
            raise ValueError(
                "link: A file inside this folder has more than one hard link."
            )
    ident = identity(fd)
    if ident[-1] != mount:
        raise ValueError("drive_root: A mounted descendant is not supported.")
    yield names, fd, ident
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                continue
            if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                raise ValueError("A special file is inside this folder.")
            child = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
            )
            try:
                yield from tree(child, mount, (*names, name))
            finally:
                os.close(child)


def grant(fd, group, write, ledger, save):
    """Also called unprivileged on private temporary trees by acceptance tests."""
    # Preflight the entire tree before the first change (including masked entries).
    ledger["group"] = group
    ledger["seen"] = []
    for names, child, ident in tree(fd, identity(fd)[-1]):
        plan(acl(child), group, write, stat.S_ISDIR(os.fstat(child).st_mode))
        ledger["seen"].append([names, ident])
    ledger["items"] = []
    for names, child, ident in tree(fd, identity(fd)[-1]):
        before = acl(child)
        after = plan(before, group, write, stat.S_ISDIR(os.fstat(child).st_mode))
        if before == after:
            continue
        ledger["items"].append(
            dict(names=names, identity=ident, before=before, after=after)
        )
        save(ledger)  # write ahead: interrupted grants can still be released
        set_acl(child, after)
    return bool(ledger["items"])


def revoke(fd, ledger):
    # POSIX ACLs do not mark an entry as inherited. A new child with this
    # group's rights cannot be distinguished from a by-hand addition. Leave
    # everything in place and report changed_outside rather than claim removal.
    if ledger["items"]:
        known = {
            (tuple(names), tuple(ident)) for names, ident in ledger.get("seen", [])
        }
        for names, child, ident in tree(fd, identity(fd)[-1]):
            if (
                tuple(names),
                tuple(ident),
            ) not in known and f"group:{ledger['group']}" in acl(child):
                ledger["refusal"] = (
                    f"{'/'.join(names)} has group permissions whose origin is not recorded by Eugene."
                )
                return False
    # Verify every recorded item before touching any of them.
    with contextlib.ExitStack() as stack:
        changes = []
        for item in ledger["items"]:
            parent = fd
            for name in item["names"]:
                child = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                )
                stack.callback(os.close, child)
                parent = child
            if identity(parent) != item["identity"]:
                ledger["refusal"] = (
                    f"{'/'.join(item['names']) or 'The folder'} was replaced."
                )
                return False
            if acl(parent) != item["after"]:
                ledger["refusal"] = (
                    f"{'/'.join(item['names']) or 'The folder'} has permissions changed outside Eugene."
                )
                return False
            changes.append((parent, item["before"]))
        for child, before in changes:
            set_acl(child, before)
    return True


def dropin(app, group, records):
    directory = Path(f"/etc/systemd/system/eugene-plexus-app@{app}.service.d")
    directory.mkdir(mode=0o755, exist_ok=True)
    paths = [
        record["path"]
        for record in records
        if record.get("write") and not record.get("removed")
    ]
    # systemd's quoted string syntax, including literal percent specifiers.
    quoted = [json.dumps(p.replace("%", "%%"), ensure_ascii=True) for p in paths]
    (directory / "20-folders.conf").write_text(
        "[Service]\nSupplementaryGroups="
        + group
        + "\n"
        + ("ReadWritePaths=" + " ".join(quoted) + "\n" if paths else "")
    )
    run("systemctl", "daemon-reload")


def write_mount(path, mountinfo):
    """Read the effective namespace, not a reloaded unit's future settings."""
    matches = []
    for line in mountinfo.splitlines():
        fields = line.split()
        point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        if path == point or path.startswith(point.rstrip("/") + "/"):
            matches.append((len(point), "rw" in fields[5].split(",")))
    if not matches:
        return False
    longest = max(length for length, _ in matches)
    current = [writable for length, writable in matches if length == longest]
    if len(current) != 1:
        raise ValueError(
            "More than one mount describes this folder; its effective write access cannot be proved."
        )
    return current[0]


def running_access(app, group, path, write):
    pid = int(
        run(
            "systemctl",
            "show",
            f"eugene-plexus-app@{app}.service",
            "--property=MainPID",
            "--value",
        ).strip()
        or "0"
    )
    if not pid:
        return pid, write
    status = Path(f"/proc/{pid}/status").read_text()
    groups = next(
        (
            line.split()[1:]
            for line in status.splitlines()
            if line.startswith("Groups:")
        ),
        [],
    )
    if group not in groups:
        raise ValueError(
            "Workbench's running process does not have its file group. Restart Workbench in Eugene, then give access."
        )
    mounts = Path(f"/proc/{pid}/mountinfo").read_text()
    return pid, write and not write_mount(path, mounts)


def main():
    import grp

    prefix, account, verb, app, mode, ident = sys.argv[1:]
    if (
        not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", app)
        or not re.fullmatch(r"[0-9a-f]{32}", ident)
        or mode not in ("read", "write")
        or verb not in ("folder-grant", "folder-revoke")
    ):
        raise ValueError("Invalid folder permission request identifiers.")
    root = Path("/etc/eugene-plexus/folder-access")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory = root / app
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / (ident + ".json")
    group_name = "eapp-" + hashlib.sha256(app.encode()).hexdigest()[:12] + "-files"
    group = str(grp.getgrnam(group_name).gr_gid)
    if verb == "folder-grant":
        if target.exists():
            raise ValueError("This access record already exists.")
        path = run(
            "runuser",
            "-u",
            account,
            "--",
            "head",
            "-c",
            "4097",
            "--",
            str(Path(prefix) / "apps/ctl" / (ident + ".path")),
        )
        if not 0 < len(path) <= 4096:
            raise ValueError("Invalid folder path length.")
        refuse(path, prefix)
        process, restart_needed = running_access(app, group, path, mode == "write")
        with opened(path) as fd:
            expected = json.loads(
                run(
                    "runuser",
                    "-u",
                    account,
                    "--",
                    "head",
                    "-c",
                    "1024",
                    "--",
                    str(Path(prefix) / "apps/ctl" / (ident + ".identity")),
                )
            )
            if identity(fd) != expected:
                raise ValueError(
                    "The folder was replaced before the permission change."
                )
            # Network filesystems and bind mounts have their own mount id.
            mount = identity(fd)[-1]
            mounts = Path("/proc/self/mountinfo").read_text().splitlines()
            line = next(line for line in mounts if int(line.split()[0]) == mount)
            fs = line.split(" - ")[1].split()[0]
            if fs.startswith(("nfs", "cifs", "smb", "9p", "fuse.ssh")):
                raise ValueError("network: Network folders are not supported.")
            record = dict(
                path=path,
                identity=identity(fd),
                write=mode == "write",
                removed=False,
                items=[],
            )
            added = grant(
                fd, group, mode == "write", record, lambda r: write_record(target, r)
            )
            write_record(target, record)
            dropin(
                app,
                group_name,
                [json.loads(p.read_text()) for p in directory.glob("*.json")],
            )
            print(
                json.dumps(
                    dict(added=added, process=process, restartNeeded=restart_needed)
                )
            )
    else:
        if not target.is_file():
            print(json.dumps(dict(removed=True)))
            return
        record = json.loads(target.read_text())
        if record.get("removed"):
            print(json.dumps(dict(removed=True)))
            return
        with opened(record["path"]) as fd:
            removed = identity(fd) == record["identity"] and revoke(fd, record)
        if removed:
            record["removed"] = True
            write_record(target, record)
            dropin(
                app,
                group_name,
                [json.loads(p.read_text()) for p in directory.glob("*.json")],
            )
        print(
            json.dumps(
                dict(
                    removed=removed,
                    message=record.get("refusal", "The folder identity changed."),
                )
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        sys.exit(1)
