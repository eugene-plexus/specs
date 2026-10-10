"""LS7a sabotage pass: a node runs a prepared model from its own copy of the
Library's files (library-sources-and-engines.md §6.8-§6.9). Only the code
that changed. Restores from a COPY, never `git checkout --`, and opens with a
baseline per gate.

Usage: python specs/scripts/ls7-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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
TIMEOUT = 900

AG = "agent/src/eugene_plexus_agent/"
COPIES = AG + "model_copies.py"
RUNTIMES = AG + "runtimes.py"
ROUTES = AG + "routes/runtimes.py"
STRATA = AG + "engines/strata.py"
PREPARE = AG + "engines/strata_prepare.py"
INSTALL = AG + "engines/strata_install.py"
ACQ = AG + "engines/acquisition.py"
DRIVES = AG + "drives.py"
CONFIG = AG + "routes/config.py"
ADMISSION = AG + "admission.py"
LIB = "library/src/eugene_plexus_library/"
PREPARED = LIB + "prepared.py"
MODELS = LIB + "routes/models.py"
FORM = "ui/src/components/AddPreparedModel.tsx"
ISSUES = "ui/src/lib/issues.ts"
ACCEPTANCE = "specs/scripts/ls7-copy-acceptance.py"

GATES: dict[str, tuple[str, list[str]]] = {
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_ls7_copies.py", "tests/test_model_copies.py", "tests/test_strata_prepare.py",
        "tests/test_strata.py", "tests/test_fit_per_engine.py",
    ]),
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_prepared.py",
    ]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/lib/issues.test.ts",
        "src/app/library/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    ("THE RULE: a model's copy is its first file alone", "agent", COPIES,
     "        members=tuple(members) if len(members) > 1 else (),", "        members=(),"),
    ("a split GGUF is one file", "agent", COPIES,
     "    if found is None:\n        return (path,)\n    total = int(found.group(\"total\"))",
     "    if True:\n        return (path,)\n    total = int(found.group(\"total\"))"),
    ("a GGUF missing a shard is copied half", "agent", COPIES,
     "    if len(files) > 1 and not all(os.path.isfile(f) for f in files):", "    if False:"),
    ("a prepared model is never copied", "agent", COPIES,
     "    if lowered.endswith(PREPARED_SUFFIX):\n        return _prepared_members(source)",
     "    if lowered.endswith(PREPARED_SUFFIX):\n        return None"),
    ("a file outside the Library folder is copied anyway", "agent", COPIES,
     "        if os.path.isabs(inside) or inside == \"..\" or inside.startswith(\"..\" + os.sep):",
     "        if False:"),
    ("one current file makes the set current", "agent", COPIES,
     "    return all(member_is_current(m, mtime_tolerance=mtime_tolerance) for m in plan.files)",
     "    return any(member_is_current(m, mtime_tolerance=mtime_tolerance) for m in plan.files)"),
    ("a copy stopped halfway starts again from nothing", "agent", COPIES,
     "        if member_is_current(member):\n            st = _stat(member.destination)",
     "        if False:\n            st = _stat(member.destination)"),
    ("the files copied are not counted", "agent", COPIES,
     "        copied = _copy_one(member, settings, state, copied, should_cancel)\n        state.files_copied += 1",
     "        copied = _copy_one(member, settings, state, copied, should_cancel)"),
    ("reconciling keeps only the first file", "agent", RUNTIMES,
     "            for destination in plan.destinations\n        ]",
     "            for destination in plan.destinations[:1]\n        ]"),
    ("Strata names no tokenizer", "agent", STRATA,
     "        if isinstance(tokenizer, str):\n            named.append(tokenizer)",
     "        if False:\n            named.append(tokenizer)"),
    ("Strata's set misses a GGUF's other shards", "agent", STRATA,
     "                files += [Path(s) for s in shards_of(str(path))]",
     "                files += [path]"),
    ("a missing named file still makes a set", "agent", STRATA,
     "            else:\n                return None\n        seen: set[str] = set()",
     "            else:\n                continue\n        seen: set[str] = set()"),
    ("the stored configuration keeps the node's paths", "agent", PREPARE,
     "        for key in (*OWNED_KEYS, *SETUP_KEYS, \"open_browser\"):\n            cfg.pop(key, None)",
     "        for key in ():\n            cfg.pop(key, None)"),
    ("a preparation runs without its tools", "agent", PREPARE,
     "    if not tools_installed(root):", "    if False:"),
    ("the install leaves the tools out", "agent", INSTALL,
     "(SOURCE, NATIVE, LLAMA_CPP), \"server.py\")",
     "(SOURCE, NATIVE), \"server.py\")"),
    ("the install unpacks all of llama.cpp", "agent", INSTALL,
     "                if info.is_dir() or not rest.startswith(LLAMA_CPP_PARTS):",
     "                if info.is_dir():"),
    ("a spinning copy folder says nothing", "agent", DRIVES,
     "    if kind == \"hdd\":\n        return (", "    if False:\n        return ("),
    ("a share is a local drive", "agent", DRIVES,
     "    if path.startswith((\"\\\\\\\\\", \"//\")):\n        return \"network\"\n    target",
     "    if False:\n        return \"network\"\n    target"),
    ("Strata's install never warns", "agent", DRIVES,
     "    kind = drive_kind(copy_folder)\n    if not slow(kind):\n        return None",
     "    kind = drive_kind(copy_folder)\n    if True:\n        return None"),
    ("Strata's start never warns", "agent", DRIVES,
     "    kind = drive_kind(path)\n    if not slow(kind):\n        return None\n    drive",
     "    kind = drive_kind(path)\n    if True:\n        return None\n    drive"),
    ("THE RULE: an entry outside the Library is adopted", "library", MODELS,
     "    if prepared.is_absolute(written) and not is_within(written, root):", "    if False:"),
    ("one written by hand outside is listed", "library", PREPARED,
     "    if is_absolute(entry) and not is_within(resolved, root):", "    if False:"),
    ("the form sends an entry from outside", "ui", FORM,
     "          disabled={busy || folders === null || outside}",
     "          disabled={busy || folders === null}"),
    ("copying says nothing of its files", "ui", ISSUES,
     "  if (typeof progress.files === \"number\" && progress.files > 1) {",
     "  if (false) {"),
    ("Settings never names the copy folder's drive", "acceptance", CONFIG,
     "            found = drives.copy_folder_status(str(live[\"copy_dir\"]))",
     "            found = None"),
    ("the launch opens the share, not the copy", "acceptance", COPIES,
     "    if plan is not None and copy_is_current(plan):\n        return LocalPath(path=plan.destination, source=\"copy\")",
     "    if False:\n        return LocalPath(path=plan.destination, source=\"copy\")"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    where = str(ROOT / repo)
    try:
        done = subprocess.run(command, cwd=where, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    parser.add_argument("--anchors", action="store_true", help="check every anchor, run nothing")
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    missing = [
        (label, io.open(ROOT / relative, encoding="utf-8").read().count(old))
        for label, _gate, relative, old, _new in chosen
        if io.open(ROOT / relative, encoding="utf-8").read().count(old) != 1
    ]
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
    if args.anchors:
        print(f"{len(chosen)} anchors, each matched once")
        return 0
    backup = Path(tempfile.mkdtemp(prefix="ls7-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
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
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
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
