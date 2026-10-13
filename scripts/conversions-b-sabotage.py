"""Data conversions, part B (2026-10-13): what v0.1 saved in the Library, the agent and Workbench is
converted once, and a failure degrades. Only the code that changed. Restores from a COPY, never
`git checkout --`, and opens with a baseline per gate.

    library   state v1 -> v2 with its profile document, flash attention true -> "on" and false
              dropped in the profile documents (and the builder's record), a config's bare-string
              `modelRoots` rewritten, the v1 read paths and the load-time bare string gone, two
              text fixes
    agent     `agent.yaml` runtime flags, converted once with a backup and `stateVersion: 2`; the
              checkbox read sites gone; the risk in four summaries and two "applies when" lines
    workbench a copy of the store before a migration, schema 2 as the oldest, a failed migration
              served as a degraded Workbench

Usage: python specs/scripts/conversions-b-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("D:/py/eugene-plexus")
TIMEOUT = 900


def python(repo: str) -> str:
    windows = ROOT / repo / ".venv" / "Scripts" / "python.exe"
    return str(windows if windows.exists() else ROOT / repo / ".venv" / "bin" / "python")


def pytest(repo: str, *tests: str) -> tuple[str, list[str]]:
    return repo, [
        python(repo), "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *tests,
    ]


GATES: dict[str, tuple[str, list[str]]] = {
    "library": pytest(
        "library", "tests/test_conversions.py", "tests/test_store.py",
        "tests/test_library_folders.py", "tests/test_config_descriptions.py",
    ),
    "agent": pytest(
        "agent", "tests/test_conversions.py", "tests/test_engines.py", "tests/test_benchmarks.py",
        "tests/test_profile_builds.py", "tests/test_config_descriptions.py", "tests/test_vllm.py",
    ),
    "workbench": pytest("workbench", "tests/test_conversions.py", "tests/test_store_schema.py"),
}

LIB = "library/src/eugene_plexus_library/"
AGENT = "agent/src/eugene_plexus_agent/"
WB = "workbench/src/eugene_plexus_workbench/"

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- library: the state and its profile document ---------------------------------------------
    ("THE RULE: false becomes off, which switches flash attention off in every profile before",
     "library", LIB + "conversions.py",
     '            del flags["flashAttention"]',
     '            flags["flashAttention"] = "off"'),
    ("true is left a checkbox", "library", LIB + "conversions.py",
     '            flags["flashAttention"] = "on"\n        elif value is False:',
     "            pass\n        elif value is False:"),
    ("the builder's record keeps its checkbox", "library", LIB + "conversions.py",
     '    for flags in (settings.get("flags"), built.get("flags") if isinstance(built, dict) else None):',
     '    for flags in (settings.get("flags"),):'),
    ("no copy of the state is kept", "library", LIB + "conversions.py",
     '    backup = keep_backup(path, data)\n    with _after_backup(path, backup):\n        embedded = raw.pop(',
     '    backup = path\n    with _after_backup(path, backup):\n        embedded = raw.pop('),
    ("the profiles never reach their document", "library", LIB + "conversions.py",
     "                profile_storage.write(profiles_file, records, models)",
     "                pass"),
    ("the state is not stamped version 2", "library", LIB + "conversions.py",
     '        raw["version"] = STATE_VERSION',
     '        raw["version"] = 1'),
    ("a converted state is converted again", "library", LIB + "conversions.py",
     "    if not _is_version(raw, 1):",
     "    if not isinstance(raw, dict):"),
    ("a copy that says something else is taken for the backup", "library", LIB + "conversions.py",
     "            if candidate.read_bytes() == data:\n                return candidate",
     "            candidate.read_bytes()\n            return candidate"),
    ("a document an earlier start made is replaced by what is embedded", "library",
     LIB + "conversions.py",
     "        if not profiles_file.exists():",
     "        if True:"),
    ("a failure is not named", "library", LIB + "conversions.py",
     '        raise _failed(path, f"{type(exc).__name__}: {exc}", None, _plain_cause(exc)) from exc',
     '        raise _failed(path, "failed") from exc'),
    ("a bare string stays in the config", "library", LIB + "conversions.py",
     '                folders.append({"path": item.strip(), "mounts": []})',
     "                folders.append(item)"),
    ("a config with no bare string is rewritten", "library", LIB + "conversions.py",
     "    if not isinstance(roots, list) or not any(isinstance(item, str) for item in roots):\n        return",
     "    if not isinstance(roots, list):\n        return"),
    ("a state of version 1 is read again", "library", LIB + "store.py",
     "                    if type(version) is not int or version != STATE_VERSION:",
     "                    if type(version) is not int or version not in (1, STATE_VERSION):"),
    ("the failed conversion is not why writes are refused", "library", LIB + "store.py",
     "            self._storage_error = blocked",
     "            self._storage_error = None"),
    ("a bare string in a loaded config is a folder again", "library", LIB + "folders.py",
     '        log.warning("modelRoots entry %d is malformed (%r); ignoring it", index, item)',
     '        out.append({"path": str(item), "mounts": []})'),
    ("a PATCH of bare strings is refused", "library", LIB + "config.py",
     "                    new_value = folders_from_body(new_value)",
     "                    pass"),
    ("the sources do not say that turning off search stops them", "library", LIB + "config.py",
     '            "Turning off Search and download models stops every source here."',
     '            "Sources can be reordered."'),
    ("the folders do not say what no mounts means", "library", LIB + "config.py",
     '"machines, or not at all. A node that mounts the share elsewhere sets an override "',
     '"machines. A node that mounts the share elsewhere sets an override "'),
    ("the config is not converted at start", "library", LIB + "app.py",
     "            conversions.convert_config(settings.config_file)\n",
     ""),
    ("the state is not converted at start", "library", LIB + "app.py",
     "        conversions.convert_state(settings.state_file)\n    except conversions.ConversionFailed as exc:",
     "        pass\n    except conversions.ConversionFailed as exc:"),
    ("a failed state conversion is not reported", "library", LIB + "app.py",
     "    state_store.load(blocked=blocked)",
     "    state_store.load()"),
    # --- agent -----------------------------------------------------------------------------------
    ("THE RULE: false becomes off, which switches flash attention off in every runtime before",
     "agent", AGENT + "conversions.py",
     '        del flags["flashAttention"]\n        return True',
     '        flags["flashAttention"] = "off"\n        return True'),
    ("true is left a checkbox", "agent", AGENT + "conversions.py",
     '        flags["flashAttention"] = "on"\n        return True',
     "        return True"),
    ("the rewrite does not carry the version", "agent", AGENT + "conversions.py",
     '        converted = {**raw, "stateVersion": STATE_VERSION}',
     "        converted = {**raw}"),
    ("a file that has the version is converted again", "agent", AGENT + "conversions.py",
     "    if type(stamp) is int and stamp >= STATE_VERSION:\n        return raw",
     "    if False:\n        return raw"),
    ("no copy of the old file is kept", "agent", AGENT + "conversions.py",
     "        backup = keep_backup(path, original)",
     "        backup = path"),
    ("a file with nothing to convert is rewritten", "agent", AGENT + "conversions.py",
     "    if not changed:\n        return raw",
     "    if False:\n        return raw"),
    ("a failure is not named", "agent", AGENT + "conversions.py",
     "        raise _failed(path, exc, backup) from exc",
     '        raise ConversionFailed("failed") from exc'),
    ("a copy that says something else is taken for the backup", "agent", AGENT + "conversions.py",
     "            if candidate.read_bytes() == data:\n                return candidate\n",
     "            candidate.read_bytes()\n            return candidate\n"),
    ("an ordinary write drops the version", "agent", AGENT + "state.py",
     '        out["stateVersion"] = conversions.STATE_VERSION\n',
     ""),
    ("the file is not converted when it is loaded", "agent", AGENT + "state.py",
     "                raw = conversions.convert(self._path, original, raw)\n",
     ""),
    ("a checkbox is read as a setting again", "agent", AGENT + "engines/llama_cpp.py",
     "    if choice is not None and choice not in FLASH_ATTENTION_CHOICES:",
     "    if False:"),
    ("a build takes a checkbox", "agent", AGENT + "profile_builds.py",
     "    if flags.get(FLASH_ATTENTION_KEY) not in (None, *FLASH_ATTENTION_CHOICES):",
     "    if False:"),
    ("allowCustomApps does not say in its line that an app runs code", "agent", AGENT + "state.py",
     '            "Expert override: apps from any archive or folder run their own code as the "\n'
     '            "agent\'s OS user.\\n\\n"',
     '            "Expert override: add apps from any archive or folder.\\n\\n"'),
    ("allowUnrestrictedEngineLaunch does not say in its line that it runs code", "agent",
     AGENT + "state.py",
     '            "Lets a runtime use any binary and raw extra arguments, which can run code "\n'
     '            "as the agent\'s OS user.\\n\\n"',
     '            "Lets a runtime use any binary and raw extra arguments.\\n\\n"'),
    ("allowedHosts does not say in its line that * lowers a protection", "agent",
     AGENT + "state.py",
     '            "Extra names a browser may use to reach Eugene; `*` allows every name and "\n'
     '            "switches off DNS-rebinding protection.\\n\\n"',
     '            "Extra names a browser may use to reach Eugene.\\n\\n"'),
    ("trustRemoteCode does not say in its line that it runs the model folder's code", "agent",
     AGENT + "engines/vllm.py",
     '            "Lets code shipped in the model folder run with the engine\'s privileges.\\n\\n"',
     '            "Allow the model directory\'s own code.\\n\\n"'),
    ("pathMappings does not say when a change applies", "agent", AGENT + "state.py",
     '            "save. Applies at the next launch."',
     '            "save."'),
    ("advertiseUrl does not say what keeps the old address", "agent", AGENT + "state.py",
     '            "at once. Components already running keep the old address until they restart."',
     '            "at once."'),
    # --- workbench -------------------------------------------------------------------------------
    ("no copy of the store is kept before a migration", "workbench", WB + "store.py",
     "        on_backup(_keep_backup(db, path, before))",
     "        pass"),
    ("the copy is a file copy, which misses the write-ahead log", "workbench", WB + "store.py",
     "            db.backup(copy)\n",
     "            copy.close()\n"
     '            __import__("shutil").copyfile(path, partial)\n'
     "            copy = sqlite3.connect(partial)\n"),
    ("a copy that is already there is replaced", "workbench", WB + "store.py",
     "        kept = _copy_name(path, version, copies[-1][0] + 1 if copies else 0)",
     "        kept = newest or _copy_name(path, version, 0)"),
    ("the copy keeps the log's journal mode", "workbench", WB + "store.py",
     '            copy.execute("PRAGMA journal_mode=DELETE")',
     "            pass"),
    ("a current store is copied on every start", "workbench", WB + "store.py",
     "    if before is not None and OLDEST_SCHEMA <= before < SCHEMA_VERSION:",
     "    if before is not None:"),
    ("a rollback with nothing to undo hides the cause", "workbench", WB + "store.py",
     '        with contextlib.suppress(sqlite3.Error):\n            db.execute("ROLLBACK")\n        raise',
     '        db.execute("ROLLBACK")\n        raise'),
    ("the oldest schema is 1 again", "workbench", WB + "store.py",
     "OLDEST_SCHEMA = 2\n",
     "OLDEST_SCHEMA = 1\n"),
    ("the copy's place is not remembered for the failure", "workbench", WB + "store.py",
     "    def _kept(self, backup: Path) -> None:\n        self.backup = backup",
     "    def _kept(self, backup: Path) -> None:\n        pass"),
    ("a store that cannot be opened stops the process", "workbench", WB + "app.py",
     "        except Exception as exc:\n            # Degraded, not dead. A store that cannot be opened",
     "        except ZeroDivisionError as exc:\n            # Degraded, not dead. A store that cannot be opened"),
    ("the cause is not named", "workbench", WB + "app.py",
     '    cause = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"',
     '    cause = "an error"'),
    ("a degraded Workbench is not marked", "workbench", WB + "app.py",
     "            app.state.degraded = why",
     "            pass"),
    ("a degraded Workbench says it is well", "workbench", WB + "web.py",
     '            response = JSONResponse({"status": "degraded", "reason": problem})',
     '            response = JSONResponse({"status": "ok"})'),
    ("an API address is answered by its route, which has no store", "workbench", WB + "web.py",
     '        elif path.startswith(_API_PREFIXES) or path == "/signin":',
     "        elif False:"),
    ("the cause is put in the page as markup", "workbench", WB + "web.py",
     '        f"<p>{html.escape(problem)}</p>"',
     '        f"<p>{problem}</p>"'),
]


def clean_environment() -> dict[str, str]:
    """Nothing of this machine's own install reaches a gate."""
    return {k: v for k, v in os.environ.items() if not k.startswith("EUGENE_PLEXUS_")}


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    try:
        done = subprocess.run(command, cwd=str(ROOT / repo), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, env=clean_environment())
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-6000:] + (done.stderr or "")[-500:]


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
    missing = []
    for label, _gate, relative, old, _new in chosen:
        text = io.open(ROOT / relative, encoding="utf-8", newline="").read().replace("\r\n", "\n")
        if text.count(old) != 1:
            missing.append((label, text.count(old)))
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
    if args.anchors:
        print(f"{len(chosen)} anchors, each matched once")
        return 0
    backup = Path(tempfile.mkdtemp(prefix="conversions-b-sabotage-"))
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
    caught = 0
    escaped: list[str] = []
    try:
        for label, gate, relative, old, new in chosen:
            path = ROOT / relative
            original = path.read_bytes()
            text = original.decode("utf-8")
            crlf = "\r\n" in text
            if crlf:
                text = text.replace("\r\n", "\n")
            try:
                changed = text.replace(old, new)
                path.write_bytes((changed.replace("\n", "\r\n") if crlf else changed).encode("utf-8"))
                code, out = run_gate(gate)
            finally:
                shutil.copy2(backup / relative, path)
            caught += code != 0
            print(f"{'CAUGHT ' if code != 0 else 'ESCAPED'} [{gate}] {label}")
            if code != 0:
                # By which test: a gate that fails for a broken edit is not a check that held.
                lines = out.splitlines()
                by = next((ln for ln in lines if ln.startswith("FAILED ")), "") or next(
                    (ln for ln in lines if ln.startswith(("ERROR ", "E  "))), ""
                )
                print(f"          {by[:150]}")
            if code == 0:
                escaped.append(label)
    finally:
        for _label, _gate, relative, _old, _new in chosen:
            shutil.copy2(backup / relative, ROOT / relative)
    for gate in gates:
        code, _out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}")
    print(f"\n{caught}/{len(chosen)} caught")
    for label in escaped:
        print(f"  escaped: {label}")
    return 0 if caught == len(chosen) else 1


if __name__ == "__main__":
    sys.exit(main())
