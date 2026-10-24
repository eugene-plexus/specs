"""Root-owned Linux folder broker. Installed verbatim by write_app_units().

No imports from the agent or files it owns. All filesystem changes use held
file descriptors. The command line accepts identifiers, never paths or ACLs.
"""

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
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, **kwargs
        )
    except FileNotFoundError:
        if args[0] in ("getfacl", "setfacl"):
            raise ValueError(
                "The acl package is missing. Folder access needs getfacl and setfacl."
            ) from None
        raise
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
        libc.statx(fd, b"", 0x1000, 0x800, data)
        or struct.unpack_from("=I", data)[0] & 0x800 != 0x800
    ):
        raise ValueError(
            "The kernel or filesystem does not expose folder creation time."
        )
    info = os.fstat(fd)
    seconds, nanos = struct.unpack_from("=qI", data, 80)
    return [
        info.st_ino,
        seconds,
        nanos,
    ]


def same_identity(observed, expected):
    return observed == (expected[1:4] if len(expected) == 5 else expected)


def mount_id(fd):
    # Mount IDs belong to this operation's namespace, never the saved identity.
    for line in Path(f"/proc/self/fdinfo/{fd}").read_text().splitlines():
        if line.startswith("mnt_id:"):
            return int(line.split()[1])
    raise ValueError("The kernel does not expose this item's mount id.")


def acl(fd):
    text = run("getfacl", "-cpnE", "--", f"/proc/self/fd/{fd}", pass_fds=(fd,))
    return parse_acl(text)


def parse_acl(text):
    return dict(
        (line.rsplit(":", 1)[0], line.rsplit(":", 1)[1].split()[0])
        for line in text.splitlines()
        if line and not line.startswith("#")
    )


def acls(fds):
    text = run(
        "getfacl",
        "-cpnE",
        "--",
        *("/proc/self/fd/" + str(fd) for fd in fds),
        pass_fds=tuple(fds),
    )
    blocks = text.strip().split("\n\n")
    if len(blocks) != len(fds):
        raise ValueError("getfacl returned an incomplete folder permission plan.")
    return [parse_acl(block) for block in blocks]


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
        desired = 6 if write else 4
        if directory or any(
            bits(rights)
            & (mask if key.startswith(("group:", "user:")) and key != "user:" else 7)
            & 1
            for key, rights in before.items()
            if not key.startswith("default:") and key != "mask:"
        ):
            desired |= 1
        new_mask = (
            mask | desired
            if prefix + "mask:" in before
            else desired | bits(before.get(prefix + "group:", before["group:"]))
        )
        for key, rights in before.items():
            if (
                key.startswith(prefix)
                and (
                    key.startswith(prefix + "group:")
                    or (key.startswith(prefix + "user:") and key != prefix + "user:")
                )
                and bits(rights) & (new_mask & ~mask)
            ):
                raise ValueError(
                    "A named or group ACL entry is masked out; changing the mask would widen its access."
                )
        if prefix and not any(key.startswith(prefix) for key in before):
            for key in ("user:", "group:", "other:"):
                after[prefix + key] = before[key]
        key = prefix + f"group:{group}"
        after[key] = words(bits(before.get(key, "---")) | desired)
        # An explicit mask preserves the effective rights of every older entry.
        after[prefix + "mask:"] = words(new_mask)
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


def mount_table():
    return Path("/proc/self/mountinfo").read_text()


def unescape(field):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), field)


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def names_of(path):
    """Every name a folder has through the mounts that show its filesystem.

    `mount --bind /etc /srv/etc-alias` makes /srv/etc-alias/ssh the same
    folder as /etc/ssh, and realpath keeps the alias. A filesystem mounted
    twice, or a home's disk bound elsewhere, does the same. The deepest
    mount holding the path gives its place on that filesystem (the mount's
    root field); each mount of the same filesystem that shows that place
    gives another name. An unreadable table fails the request.
    """
    mounts = []
    for line in mount_table().splitlines():
        fields = line.split()
        mounts.append((unescape(fields[4]), unescape(fields[3]), fields[2]))
    holding = [m for m in mounts if inside(path, m[0])]
    if not holding:
        return [path]
    deepest = max(len(m[0]) for m in holding)
    point, root, device = [m for m in holding if len(m[0]) == deepest][-1]
    place = "/" + "/".join(
        p for p in (root + "/" + path[len(point) :]).split("/") if p
    )
    names = {path}
    for other_point, other_root, other_device in mounts:
        if other_device == device and inside(place, other_root):
            rest = place[len(other_root.rstrip("/")) :]
            names.add("/" + "/".join(p for p in (other_point + rest).split("/") if p))
    return sorted(names)


def refuse(path, prefix):
    """Match the agent: own prefix, system, home, then other install ancestors."""
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
    import pwd

    homes = ["/home"] + [
        p.pw_dir
        for p in pwd.getpwall()
        if p.pw_dir.startswith("/") and p.pw_dir not in ("/", "/nonexistent")
    ]
    policy(path, prefix, homes)
    for name in names_of(path):
        if name == path:
            continue
        try:
            policy(name, prefix, homes)
        except ValueError as exc:
            cause, words = str(exc).split(":", 1)
            raise ValueError(f"{cause}: {path} is {name} through a mount.{words}") from None


def policy(path, prefix, homes):
    if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
        raise ValueError("eugene: This is Eugene's own folder.")
    parts = Path(path).parts
    if any(related(path, system) for system in SYSTEM) or (
        len(parts) > 1 and parts[1].startswith("lib")
    ):
        raise ValueError("system: Eugene does not give apps system folders.")
    if any(related(path, home) for home in homes):
        raise ValueError("home: Use a Job Site to work in your own folders.")
    if related(path, prefix):
        raise ValueError("eugene: This is Eugene's own folder.")


class UnsafeParent(ValueError):
    def __init__(self, path):
        self.path = path
        super().__init__(path + " can be changed by other accounts.")


@contextlib.contextmanager
def opened(path, *, parents_safe=True, allow_mount_root=False):
    held = [os.open("/", os.O_RDONLY | os.O_DIRECTORY)]
    try:
        parts = Path(path).parts[1:]
        for index, name in enumerate(parts):
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
                    raise UnsafeParent(str(Path(path).parents[len(parts) - index - 1]))
            held.append(
                os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
            )
            if (
                not allow_mount_root
                and index == len(parts) - 1
                and mount_id(held[-1]) != mount_id(parent)
            ):
                raise ValueError(
                    "drive_root: Choose a folder inside the mounted drive."
                )
        yield held[-1]
    finally:
        for fd in reversed(held):
            os.close(fd)


def inspect_folder(path, prefix):
    """Inspect as root; the agent may not traverse any part of this path."""
    facts = dict(path=path)
    try:
        refuse(path, prefix)
    except (FileNotFoundError, NotADirectoryError):
        facts["is_dir"] = False
    except ValueError as exc:
        cause = str(exc).split(":", 1)[0]
        refused = {
            "not_a_folder": dict(is_dir=False),
            "link": dict(link=True),
            "network": dict(network=True),
            "drive_root": dict(mount_root=True),
            "system": dict(system=[path]),
            "eugene": dict(eugene=[path]),
            "home": dict(homes=[path]),
        }
        if cause not in refused:
            raise
        facts.update(refused[cause])
    if not (facts.get("link") or facts.get("network") or facts.get("is_dir") is False):
        try:
            # Grant policy is separate from identity. Only inspect through safe
            # parents; revoke uses its private ledger if a parent is now unsafe.
            with opened(path, allow_mount_root=True) as fd:
                return dict(facts=facts, identity=identity(fd))
        except UnsafeParent as exc:
            facts["unsafe_parent"] = exc.path
        except FileNotFoundError:
            facts["is_dir"] = False
        except NotADirectoryError:
            facts["link"] = True
    return dict(facts=facts, identity=[])


def tree(fd, mount, names=(), *, revoke=False, skipped=None):
    info = os.fstat(fd)
    if stat.S_ISLNK(info.st_mode):
        return
    if mount_id(fd) != mount:
        cause = "drive_root: A mounted descendant is not supported."
        if not revoke:
            raise ValueError(cause)
        skipped.append("/".join(names) + ": " + cause)
        return
    if not revoke and not stat.S_ISDIR(info.st_mode):
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("A special file is inside this folder.")
        if info.st_nlink != 1:
            raise ValueError(
                "link: A file inside this folder has more than one hard link."
            )
    ident = (
        identity(fd) if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) else []
    )
    yield names, fd, ident
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        for name in os.listdir(fd):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    continue
                special = not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(
                    info.st_mode
                )
                if special and not revoke:
                    raise ValueError("A special file is inside this folder.")
                # O_PATH avoids opening devices, blocking FIFOs, or connecting
                # sockets. ACL tools reach the held object through procfs.
                flags = os.O_PATH if special else os.O_RDONLY | os.O_NONBLOCK
                child = os.open(name, flags | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not revoke:
                    raise
                continue
            except OSError as exc:
                if not revoke:
                    raise
                skipped.append("/".join((*names, name)) + ": " + str(exc))
                continue
            try:
                yield from tree(
                    child, mount, (*names, name), revoke=revoke, skipped=skipped
                )
            finally:
                os.close(child)


def batches(fd, size=128, *, revoke=False, skipped=None):
    """Bound retained descriptors and subprocess argument size."""
    pending = []
    try:
        for names, child, ident in tree(
            fd, mount_id(fd), revoke=revoke, skipped=skipped
        ):
            pending.append((names, os.dup(child), ident))
            if len(pending) == size:
                yield pending
                for _, held, _ in pending:
                    os.close(held)
                pending = []
        if pending:
            yield pending
    finally:
        for _, held, _ in pending:
            os.close(held)


def grant(fd, group, write, ledger, save, check=None):
    """Preflight and save a complete plan before the first ACL change.

    `check` runs after the preflight and before the plan is saved: the last
    look at the folder's names before anything changes.
    """
    ledger["group"] = group
    ledger["items"] = []
    # Entries for the group that a grant leaves as they are: removal keeps them.
    ledger["kept"] = []
    keys = ("group:" + group, "default:group:" + group)
    for batch in batches(fd):
        for (names, child, ident), before in zip(batch, acls([c for _, c, _ in batch])):
            after = plan(before, group, write, stat.S_ISDIR(os.fstat(child).st_mode))
            if before != after:
                ledger["items"].append(
                    dict(names=names, identity=ident, before=before, after=after)
                )
            elif any(key in before for key in keys):
                ledger["kept"].append(dict(names=names, identity=ident))
    if check is not None:
        check()
    save(ledger)
    plans = {tuple(item["names"]): item for item in ledger["items"]}
    for batch in batches(fd):
        content, held = [], []
        for names, child, ident in batch:
            item = plans.get(names)
            if item is None:
                continue
            if not same_identity(ident, item["identity"]):
                raise ValueError(
                    "A folder item was replaced before its permission change."
                )
            held.append(child)
            content.append(
                "# file: /proc/self/fd/"
                + str(child)
                + "\n"
                + "\n".join(k + ":" + v for k, v in item["after"].items())
                + "\n\n"
            )
        if held:
            run("setfacl", "--restore=-", input="".join(content), pass_fds=tuple(held))
    return bool(plans)


def revoke(fd, ledger):
    # Revoke the group's entries throughout the current tree, including
    # children created since the grant, and every other principal's ACL
    # (including later chmod changes). An item nobody changed since the grant
    # gets its recorded ACL back; an entry the group held before stays.
    if not ledger["items"]:
        return True
    group = ledger["group"]
    skipped = []
    plans = index(item for item in ledger["items"] if "names" in item)
    kept = index(ledger.get("kept", []))
    for batch in batches(fd, revoke=True, skipped=skipped):
        normal = [item for item in batch if item[2]]
        entries = list(zip(normal, acls([c for _, c, _ in normal]))) if normal else []
        for item in batch:
            if item[2]:
                continue
            try:
                current = acl(item[1])
                remove_entries([(item, current)], group, plans, kept)
            except (OSError, ValueError) as exc:
                skipped.append("/".join(item[0]) + ": " + str(exc))
        remove_entries(entries, group, plans, kept)
    ledger["refusal"] = "; ".join(skipped)
    return not skipped


def index(items):
    """Records by identity, which a rename keeps, and by path for the rest."""
    found = {}
    for item in items:
        found[tuple(item["names"])] = item
        if item.get("identity"):
            found[("identity", *identity_key(item["identity"]))] = item
    return found


def identity_key(value):
    return tuple(value[1:4] if len(value) == 5 else value)


def recorded(records, names, ident):
    """The record for this item: by identity first, then by path."""
    if ident and ("identity", *identity_key(ident)) in records:
        return records[("identity", *identity_key(ident))]
    return records.get(tuple(names))


def remove_entries(entries, group, plans, kept=None):
    kept = kept or {}
    keys = ("group:" + group, "default:group:" + group)
    restore, removable = [], []
    for (names, child, ident), current in entries:
        item = recorded(plans, names, ident)
        planned = item is not None and same_identity(ident, item["identity"])
        prior = recorded(kept, names, ident)
        if planned and current == item["after"]:
            if current != item["before"]:
                restore.append((child, item["before"]))
            continue
        if prior is not None and same_identity(ident, prior["identity"]):
            continue  # The group's own entries from before the grant.
        if planned and any(key in item["before"] for key in keys):
            # Changed since, but the grant widened an older entry: put that
            # entry back as it was and keep everything else.
            wanted = {k: v for k, v in current.items() if k not in keys}
            wanted.update({k: item["before"][k] for k in keys if k in item["before"]})
            restore.append((child, wanted))
            continue
        removable.append(((names, child, ident), current))
    if restore:
        run(
            "setfacl",
            "--restore=-",
            input="".join(
                "# file: /proc/self/fd/"
                + str(child)
                + "\n"
                + "\n".join(k + ":" + v for k, v in wanted.items())
                + "\n\n"
                for child, wanted in restore
            ),
            pass_fds=tuple(child for child, _ in restore),
        )
    everything, entries = entries, removable
    for default in (False, True):
        key = ("default:" if default else "") + "group:" + group
        held = [child for (_, child, _), current in entries if key in current]
        if held:
            run(
                "setfacl",
                "-n",
                "-x",
                ("d:" if default else "") + "g:" + group,
                "--",
                *("/proc/self/fd/" + str(child) for child in held),
                pass_fds=tuple(held),
            )
    clear = []
    base = {"default:user:", "default:group:", "default:other:", "default:mask:"}
    # Default ACLs the grant created go; setfacl --restore leaves them.
    for (names, child, ident), current in everything:
        item = recorded(plans, names, ident)
        defaults = {k for k in current if k.startswith("default:")}
        defaults.discard("default:group:" + group)
        if (
            item is not None
            and same_identity(ident, item["identity"])
            and not any(k.startswith("default:") for k in item["before"])
            and defaults == base
            and all(current[k] == item["after"].get(k) for k in base)
        ):
            clear.append(child)
    if clear:
        run(
            "setfacl",
            "-k",
            "--",
            *(f"/proc/self/fd/{c}" for c in clear),
            pass_fds=tuple(clear),
        )


def reapply(fd, record, records):
    """Restore remaining overlapping grants before completing this revoke."""
    active = []
    skipped = []
    reapplied = set()
    for target, other in records.items():
        if (
            other.get("removed")
            or other == record
            or not related(other["path"], record["path"])
        ):
            continue
        try:
            # These are existing root-owned grants too. Validate identity
            # without applying policy for a new grant during removal.
            with opened(
                other["path"], parents_safe=False, allow_mount_root=True
            ) as held:
                if same_identity(identity(held), other["identity"]):
                    active.append((target, other))
        except (FileNotFoundError, NotADirectoryError):
            continue  # A missing related folder covers no items.
        except (OSError, ValueError) as exc:
            skipped.append(other["path"] + ": " + str(exc))
    if not active:
        record["refusal"] = "; ".join(filter(None, [record.get("refusal"), *skipped]))
        return not skipped, []
    plans = {
        target: {tuple(item["names"]): item for item in other["items"]}
        for target, other in active
    }
    for batch in batches(fd, revoke=True, skipped=skipped):
        changes = {}
        for names, child, ident in batch:
            path = record["path"].rstrip("/") + ("/" + "/".join(names) if names else "")
            covering = [
                (target, r)
                for target, r in active
                if path == r["path"] or path.startswith(r["path"].rstrip("/") + "/")
            ]
            if not covering:
                continue
            try:
                info = os.fstat(child)
                directory = stat.S_ISDIR(info.st_mode)
                if not directory:
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError("A special file is inside this folder.")
                    if info.st_nlink != 1:
                        raise ValueError("A file has more than one hard link.")
                before = acl(child)
                target, owner = max(
                    covering, key=lambda pair: bool(pair[1].get("write"))
                )
                after = plan(
                    before,
                    record["group"],
                    owner.get("write", False),
                    directory,
                )
                if before != after:
                    relative = path[len(owner["path"]) :].strip("/")
                    owned_names = tuple(relative.split("/")) if relative else ()
                    item = plans[target].get(owned_names)
                    if item is None or not same_identity(ident, item["identity"]):
                        if item is not None:
                            owner["items"].remove(item)
                        item = dict(
                            names=owned_names,
                            identity=ident,
                            before=before,
                            after=after,
                        )
                        owner["items"].append(item)
                        plans[target][owned_names] = item
                    changes.setdefault(target, []).append((path, child, after))
            except (OSError, ValueError) as exc:
                skipped.append(path + ": " + str(exc))
        for target, additions in changes.items():
            try:
                # Save each covering grant once per batch, before its additions.
                # Keep an existing item's original before/after values so an
                # owner's later default-ACL edits remain detectable on revoke.
                write_record(target, records[target])
                reapplied.add(target.stem)
            except (OSError, ValueError) as exc:
                skipped.extend(path + ": " + str(exc) for path, _, _ in additions)
                continue
            for path, child, after in additions:
                try:
                    set_acl(child, after)
                except (OSError, ValueError) as exc:
                    skipped.append(path + ": " + str(exc))
    if skipped:
        record["refusal"] = "; ".join(filter(None, [record.get("refusal"), *skipped]))
    return not skipped, sorted(reapplied)


def dropin(app, group, records):
    directory = Path(f"/etc/systemd/system/eugene-plexus-app@{app}.service.d")
    directory.mkdir(mode=0o755, exist_ok=True)
    paths = [
        record["path"]
        for record in records
        if record.get("write") and not record.get("removed")
    ]
    # systemd's quoted string syntax, including literal percent specifiers.
    quoted = ["-" + json.dumps(p.replace("%", "%%"), ensure_ascii=False) for p in paths]
    (directory / "20-folders.conf").write_text(
        "[Service]\nSupplementaryGroups="
        + group
        + "\n"
        + ("ReadWritePaths=" + " ".join(quoted) + "\n" if paths else ""),
        encoding="utf-8",
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
    if sys.version_info < (3, 10):
        raise ValueError(
            "Folder access needs Python 3.10 or newer at /usr/bin/python3."
        )
    import grp

    prefix, account, verb, app, mode, ident = sys.argv[1:]
    if (
        not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", app)
        or not re.fullmatch(r"[0-9a-f]{32}", ident)
        or mode not in ("read", "write")
        or verb not in ("folder-inspect", "folder-grant", "folder-revoke")
    ):
        raise ValueError("Invalid folder permission request identifiers.")
    if verb in ("folder-inspect", "folder-grant"):
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
        if verb == "folder-inspect":
            print(json.dumps(inspect_folder(path, prefix)))
            return
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
            if not same_identity(identity(fd), expected):
                raise ValueError(
                    "The folder was replaced before the permission change."
                )
            # Mount IDs are transient; use the longest containing mount
            # only to reject remote filesystems, never as persistent identity.
            mounts = []
            for line in mount_table().splitlines():
                point = re.sub(
                    r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]
                )
                if path == point or path.startswith(point.rstrip("/") + "/"):
                    mounts.append((len(point), line.split(" - ")[1].split()[0]))
            fs = max(mounts)[1]
            if fs.startswith(("nfs", "cifs", "smb", "9p", "fuse.ssh")):
                raise ValueError("network: Network folders are not supported.")
            record = dict(
                path=path,
                identity=identity(fd),
                write=mode == "write",
                removed=False,
                items=[],
            )
            # A mount made since the first check can give the folder a
            # forbidden name without changing its identity: look again.
            added = grant(
                fd,
                group,
                mode == "write",
                record,
                lambda r: write_record(target, r),
                check=lambda: refuse(path, prefix),
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
        reapplied = []
        with contextlib.ExitStack() as held:
            try:
                # This path and identity come only from the root-owned ledger.
                # Hold every component without following links, then compare the
                # saved identity before changing ACLs. New-grant policy cannot
                # prevent releasing an unchanged grant.
                fd = held.enter_context(
                    opened(record["path"], parents_safe=False, allow_mount_root=True)
                )
            except FileNotFoundError:
                removed = True  # Also remove a deleted folder's namespace allowance.
            except NotADirectoryError:
                removed = False  # A replacement link must never reach its target.
            else:
                removed = same_identity(identity(fd), record["identity"])
                if removed:
                    complete = revoke(fd, record)
                    records = {
                        p: json.loads(p.read_text())
                        for p in directory.glob("*.json")
                        if p != target
                    }
                    restored, reapplied = reapply(fd, record, records)
                    removed = complete and restored
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
                    message=record.get("refusal") or "",
                    reapplied=reapplied,
                )
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        sys.exit(1)
