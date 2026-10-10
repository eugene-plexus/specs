"""LS10 sabotage pass: the Library writes a preparation's files
(library-sources-and-engines.md §6.13). Only the code that changed.

Restores from a COPY, never `git checkout --`, and opens with a baseline per
gate. Each entry puts one rule of the slice back, or takes one check out, and
names the gate that must notice:

- `library`: where the Library writes a sent file and how it arrives
  (`prepared_uploads.py`, the three file routes);
- `agent`: the node's folder for a preparation, the links to the shards, what
  is sent and discarded, the sender, the failed log, the uninstall guard, the
  run-work client's headers;
- `acceptance`: `ls5-preparation-acceptance.py`, whose GGUF folder this
  account cannot write in (L1-L5), for what only real processes show.

Usage: python specs/scripts/ls10-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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

LIB = "library/src/eugene_plexus_library/"
UPLOADS = LIB + "prepared_uploads.py"
RUNOPS_ROUTES = LIB + "routes/run_operations.py"
AG = "agent/src/eugene_plexus_agent/"
WORKER = AG + "run_worker.py"
JOBS = AG + "preparation.py"
SEND = AG + "preparation_send.py"
RECIPE = AG + "engines/strata_prepare.py"
ROUTES = AG + "routes/runtimes.py"
ADMISSION = AG + "admission.py"
ACCEPTANCE = "specs/scripts/ls5-preparation-acceptance.py"

GATES: dict[str, tuple[str, list[str]]] = {
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_prepared_uploads.py", "tests/test_run_preparation.py",
    ]),
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_strata_prepare.py", "tests/test_run_preparation.py",
        "tests/test_admission.py",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the library: where it writes (B105) -------------------------------------------
    ("THE RULE: a preparation writes outside an engine's own folder", "library", UPLOADS,
     "    if len(parts) < 2 or not ENGINE_FOLDER.match(parts[0]):", "    if len(parts) < 1:"),
    ("a '..' part is written", "library", UPLOADS,
     '        if part in ("", ".", "..") or part != part.strip() or len(part) > 255:',
     '        if part in ("", ".") or part != part.strip() or len(part) > 255:'),
    ("a provenance file can be sent", "library", UPLOADS,
     "    if last.endswith(prepared.SUFFIX):", "    if False:"),
    ("a folder of that name the person made is written in", "library", UPLOADS,
     "        if not own.is_dir() or not (own / prepared.ENGINE_FILES_MARKER).is_file():",
     "        if not own.is_dir():"),
    ("a write follows a link out of the engine's folder", "library", UPLOADS,
     "        if _linked(here):\n", "        if False:\n"),
    ("a file is written under its own name as it arrives", "library", UPLOADS,
     "        return self.path.with_name(self.path.name + PARTIAL_SUFFIX)",
     "        return self.path"),
    ("a chunk at another offset is taken", "library", UPLOADS,
     "    if offset not in (0, have):", "    if False:"),
    ("a short file is put in place", "library", UPLOADS,
     "    if have != size:", "    if False:"),
    ("a damaged file is put in place", "library", UPLOADS,
     "    if sha256_of(partial) != sha256:", "    if False:"),
    ("files are written for a run that is not preparing", "library", RUNOPS_ROUTES,
     '    if record["step"] != "preparing" or not record["intent"].get("preparation"):',
     '    if not record["intent"].get("preparation"):'),
    ("files are written without the run's lease", "library", RUNOPS_ROUTES,
     '    jobs.verify_lease(record, node, lease)\n    if record["step"] != "preparing" or not record',
     '    if record["step"] != "preparing" or not record'),
    ("files go into whichever Library folder comes first", "library", RUNOPS_ROUTES,
     "    folder = next((r for r in roots if root and normalize(r) == normalize(root)), None)",
     "    folder = next(iter(roots), None)"),
    ("a chunk sent without its length is not counted", "library", RUNOPS_ROUTES,
     "        if total > limit:\n            raise too_large", "        if False:\n            raise too_large"),
    # --- the agent: the node's folder and the shards (B101, B102) -------------------------
    ("THE RULE: setup writes Strata-data into the Library folder", "agent", RECIPE,
     "        return self.work / DATA_FOLDER", "        return self.folder / DATA_FOLDER"),
    ("setup is given the GGUF's own folder", "agent", RECIPE,
     "            str(self._gguf_dir or self.view),", "            str(self.gguf.parent),"),
    ("the shards are not placed in the node's folder", "agent", RECIPE,
     "                    _place(make, shard, view / shard.name)\n", "                    pass\n"),
    ("a path outside the model's files is listed", "agent", RECIPE,
     "        if not _under(path, self.work):", "        if False:"),
    ("a shard outside the Library folder is prepared", "agent", RECIPE,
     '    if inside.parts[:1] == ("..",) or inside.is_absolute():\n        raise PreparationError(f"{gguf} is not inside',
     '    if False:\n        raise PreparationError(f"{gguf} is not inside'),
    # --- what is sent and what the node keeps (B103, B107) ------------------------------
    ("the GGUF and setup's records are sent", "agent", RECIPE,
     "            if key in seen or path.is_symlink() or not path.is_relative_to(self.data_dir):",
     "            if key in seen:"),
    ("the MTP helper is discarded from the node", "agent", RECIPE,
     '                *(f for f in files if not f.is_relative_to(self.data_dir / "mtp")),',
     "                *files,"),
    ("a copy of the shards is kept after listing", "agent", RECIPE,
     "                *self._copies,\n", ""),
    ("what was sent is kept on the node", "agent", WORKER,
     "        await asyncio.to_thread(_discard, progress.result.discard)\n", ""),
    # --- the sender (B104) ------------------------------------------------------------
    ("a done preparation is listed without its files", "agent", WORKER,
     '            sent = await sender.send(library, base, params, job["lease"])',
     "            sent = True"),
    ("a file the library holds is sent again", "agent", SEND,
     '                if held["sizeBytes"] == current.size and held["sha256"] == current.sha256:',
     "                if False:"),
    ("a send starts again from 0", "agent", SEND,
     "                current.offset = received if 0 < received <= current.size else 0",
     "                current.offset = 0"),
    ("a file that arrived damaged is not sent again", "agent", SEND,
     "                if current.resends >= RESENDS:", "                if True:"),
    ("one tick sends every chunk", "agent", SEND,
     "                if moved and time.perf_counter() - started > budget:\n                    return False",
     "                if False:\n                    return False"),
    ("a caller's header replaces the credential", "agent", ADMISSION,
     '        headers = {**(kwargs.pop("headers", None) or {}), **self._headers}',
     '        headers = {**self._headers, **(kwargs.pop("headers", None) or {})}'),
    # --- a failure, and the engine's uninstall (B106, B107) -----------------------------
    ("a failed setup's log is not sent", "agent", WORKER,
     "            where = await self._send_log(library, base, job, params, progress)",
     "            where = None"),
    ("the log's place is not kept", "agent", RECIPE,
     "        progress.log_name = self.log_path.relative_to(self.work).as_posix()",
     "        progress.log_name = None"),
    ("Strata is uninstalled while its files are sent", "agent", JOBS,
     ' or j.progress.state == "done")', ")"),
    # --- only real processes show -------------------------------------------------------
    ("ACCEPTANCE: Strata-data is written by the node into the Library folder", "acceptance", RECIPE,
     "        return self.work / DATA_FOLDER", "        return self.folder / DATA_FOLDER"),
    ("ACCEPTANCE: setup's marks go beside the Library's shards", "acceptance", RECIPE,
     "            str(self._gguf_dir or self.view),", "            str(self.gguf.parent),"),
    ("ACCEPTANCE: the failure names the node's own log", "acceptance", WORKER,
     "            where = await self._send_log(library, base, job, params, progress)",
     "            where = str(progress.log_file)"),
    ("ACCEPTANCE: uninstalling leaves the node's preparation folders", "acceptance", ROUTES,
     '        shutil.rmtree(engine_root() / "preparing" / kind.value, ignore_errors=True)\n', ""),
    ("ACCEPTANCE: the run-work client sends no chunk's type", "acceptance", ADMISSION,
     '        headers = {**(kwargs.pop("headers", None) or {}), **self._headers}\n        response = await self._client().request(\n            method, f"{self._base}{path}", headers=headers, **kwargs',
     '        response = await self._client().request(\n            method, f"{self._base}{path}", headers=self._headers, **kwargs'),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    # Safe beside a live install: no ambient EUGENE_PLEXUS_* reaches a gate.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    try:
        done = subprocess.run(command, cwd=str(ROOT / repo), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, env=env)
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
    backup = Path(tempfile.mkdtemp(prefix="ls10-sabotage-"))
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
            print(f"[caught ] ({gate}) {label}", flush=True)
            caught += 1
        else:
            print(f"[ESCAPED] ({gate}) {label}", flush=True)
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
