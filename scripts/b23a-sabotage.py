"""2b.3a sabotage pass: the workspace tools, and only the code they changed.

`job-sites-own-enrollment.md` §3.3. Restores from a COPY, never
`git checkout --`, and opens with a baseline per gate. Each entry puts one
rule of the slice back, or takes one check out, and names the gate that must
notice:

- `site`: the site host's suites for the changed files, on Windows (the
  junction, the directory listing's attributes, write times);
- `linux`: the same in WSL2's Linux, where `folder_linux.py` and Landlock
  are the code under test. It uses the editable Linux venv at
  `~/venvs/site-host-linux` (`uv pip install -e site-host[dev]`).

A pattern that never finishes, with its timeout taken away, hangs its gate:
that is caught by the gate's own time limit.

Usage: python specs/scripts/b23a-sabotage.py [--gate NAME ...] [--label TEXT ...]
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 300

SH = "site-host"
WT = "src/eugene_plexus_site_host/workspace_tools.py"
FS = "src/eugene_plexus_site_host/file_server.py"
HOST = "src/eugene_plexus_site_host/host.py"
FIO = "src/eugene_plexus_site_host/folder_io.py"
WIN = "src/eugene_plexus_site_host/folder_windows.py"
LIN = "src/eugene_plexus_site_host/folder_linux.py"
TESTS = (
    "tests/test_workspace_tools.py",
    "tests/test_folder_scope.py",
    "tests/test_host.py",
    "tests/test_routing.py",
    "tests/test_worker.py",
)

GATES: dict[str, list[str]] = {
    "site": [
        str(ROOT / SH / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *TESTS,
    ],
    "linux": [
        "wsl", "-e", "bash", "-lc",
        "cd /mnt/d/py/eugene-plexus/site-host && ~/venvs/site-host-linux/bin/python -m pytest "
        "-q -x --no-header -p no:cacheprovider " + " ".join(TESTS),
    ],
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- read_text -----------------------------------------------------------------
    ("a read's hash covers only the lines shown", "site", WT,
     '"sha256": digest,', '"sha256": hashlib.sha256("".join(shown[:k]).encode()).hexdigest(),'),
    ("THE FINDING: an answer is not cut to fit what the site carries", "site", WT,
     "    if answer_bytes(whole) <= ANSWER_BUDGET:", "    if True:"),
    ("the budget counts the result once, not as text and structured content", "site", WT,
     "    return len(json.dumps(inner, ensure_ascii=False).encode()) + len(inner.encode())",
     "    return len(inner.encode())"),
    ("a long line is shown whole", "site", WT,
     "        if len(body) > LONG_LINE:", "        if False:"),
    ("a read past the end answers nothing instead of saying so", "site", WT,
     "    if offset > max(total, 1):", "    if False:"),
    ("a read takes a file of any size", "site", WT,
     'read_all(fd, MAX_FILE, "read_text reads files of at most 16 MiB.")',
     'read_all(fd, 1 << 40, "read_text reads files of at most 16 MiB.")'),
    # --- edit_text -----------------------------------------------------------------
    ("THE FINDING: an edit does not check the hash the person read", "site", WT,
     '        if hashlib.sha256(data).hexdigest() != arguments["expectedSha256"]:',
     "        if False:"),
    ("an ambiguous passage replaces its first copy", "site", WT,
     "        if count > 1 and not every:", "        if False:"),
    ("replaceAll replaces one copy", "site", WT,
     "        changed = text.replace(old, new) if every else text.replace(old, new, 1)",
     "        changed = text.replace(old, new, 1)"),
    ("a CRLF file does not take a passage written with \\n", "site", WT,
     r'        if not count and "\r\n" in text and "\n" in old and "\r\n" not in old:',
     "        if False:"),
    ("an edit may grow a file past 1 MiB", "site", WT,
     "        if len(out) > MAX_EDIT:", "        if False:"),
    ("an edit may write a binary character", "site", WT,
     "        text_of(out)\n", "\n"),
    ("a write stops short of truncating: a shorter file keeps its old tail", "site", FIO,
     "        os.ftruncate(fd, len(data))", "        pass"),
    # --- the walk ------------------------------------------------------------------
    ("THE FINDING (Windows): a junction is listed as a folder", "site", WIN,
     '                                    kind = "link"', '                                    kind = "dir"'),
    ("THE FINDING (Linux): a symlink is listed as a folder", "linux", LIN,
     '                    out.append(Entry(entry.name, "link", 0, 0))',
     '                    out.append(Entry(entry.name, "dir", 0, 0))'),
    ("a link is not counted as passed over", "site", WT,
     '            if entry.kind == "link":\n                state.skip("links")',
     '            if entry.kind == "link":\n                pass'),
    (".git is searched", "site", WT,
     '                if entry.name == ".git":', '                if False:'),
    ("a .gitignore'd folder is entered", "site", WT,
     "                if ignore and ignores.ignored(path, True):", "                if False:"),
    ("a deeper .gitignore is not read", "site", WT,
     "            ignores.load(folder, directory)", "            pass"),
    ("a .gitignore above where the search starts is not read", "site", WT,
     "        for depth in range(len(start) + 1):", "        for depth in range(len(start), len(start) + 1):"),
    ("a deeper .gitignore's ! does not override a shallower one", "site", WT,
     "            if include is not None:\n                decision = include",
     "            if include is not None and decision is None:\n                decision = include"),
    ("Windows write times are not read", "site", WIN,
     "                                mtime = (written - 116_444_736_000_000_000) * 100",
     "                                mtime = 0"),
    # --- glob ----------------------------------------------------------------------
    ("a negated class matches the separator", "site", WT,
     'out.append(f"[^/{chars}]" if negate else f"[{chars}]")',
     'out.append(f"[^{chars}]" if negate else f"[{chars}]")'),
    ("glob's matches are not newest first", "site", WT,
     "    found.sort(key=lambda f: (-f[0], f[1]))", "    found.sort(key=lambda f: f[1])"),
    # --- grep ----------------------------------------------------------------------
    ("THE FINDING (J74): a pattern runs without a timeout", "site", WT,
     "    for match in pattern.finditer(text, timeout=seconds):",
     "    for match in pattern.finditer(text):"),
    ("binary files are searched", "site", WT,
     '            if _BINARY.search(data):\n                state.skip("binary")',
     '            if False:\n                state.skip("binary")'),
    ("a glob without / matches the whole path, not the name", "site", WT,
     '                relative = path[-1] if only.names_only else "/".join(path[len(names) :])',
     '                relative = "/".join(path[len(names) :])'),
    ("context lines are not shown", "site", WT,
     "low, high = max(0, hit - context), min(len(lines) - 1, hit + context)",
     "low, high = hit, hit"),
    ("Windows: a file given as the path is walked as a folder", "site", WIN,
     "                # Python raises ERROR_DIRECTORY (267) as this.\n                return False",
     "                # Python raises ERROR_DIRECTORY (267) as this.\n                raise"),
    ("Linux: a file given as the path is walked as a folder", "linux", LIN,
     "        except NotADirectoryError:\n            return False",
     "        except NotADirectoryError:\n            raise"),
    # --- the server, the worker and the host -----------------------------------------
    ("THE FINDING: the worker takes arguments unchecked", "site", FS,
     "    check_arguments(tool, arguments)\n", "\n"),
    ("a reader is offered the tools that change files", "site", FS,
     "        names = writable if name in DESTRUCTIVE else readable", "        names = readable"),
    ("the worker edits a folder the host says is read only", "site", FS,
     "        if folder is None or (params.name in DESTRUCTIVE and name not in writable):",
     "        if folder is None:"),
    ("the host lets a reader edit", "site", HOST,
     "        if writes and name not in target.writable:", "        if False:"),
    ("a search that ran out of time reads as 'it may have acted'", "site", HOST,
     "            reads = target.folders is not None and tool in file_server.READ_ONLY",
     "            reads = False"),
    ("readers are not given glob and grep", "site", HOST,
     "READING = {name: False for name in sorted(file_server.READ_ONLY)}",
     'READING = {"list_directory": False, "read_text": False}'),
]


def run_gate(name: str) -> tuple[int, str]:
    where = str(ROOT / SH)
    try:
        done = subprocess.run(GATES[name], cwd=where, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    backup = Path(tempfile.mkdtemp(prefix="b23a-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / SH / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    print()
    caught = escaped = 0
    for label, gate, relative, old, new in chosen:
        path = ROOT / SH / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, _out = run_gate(gate)
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] ({gate}) {label}")
            caught += 1
        else:
            print(f"[ESCAPED] ({gate}) {label}")
            escaped += 1
    print(f"\n{caught} caught, {escaped} escaped, {len(chosen)} sabotages")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
