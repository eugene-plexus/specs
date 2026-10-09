"""LS5 sabotage pass: preparation is a job on the engine's node
(library-sources-and-engines.md §4.6, §6.6). Only the code that changed.

Restores from a COPY, never `git checkout --`, and opens with a baseline per
gate. Each entry puts one rule of the slice back, or takes one check out, and
names the gate that must notice:

- `library`: the run operation's preparing step, `/prepared`, the provenance
  file and the scan's engine folders;
- `agent`: Strata's recipe, the preparation jobs, the run worker's steps and
  the uninstall guard;
- `ui`: the run store, *Prepare* and *Download and prepare*, the install
  question (vitest, started from `D:`);
- `acceptance`: `ls5-preparation-acceptance.py`, for what only real processes
  show (a venv's python.exe is a launcher).

Usage: python specs/scripts/ls5-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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

LIB = "library/src/eugene_plexus_library/"
RUNOPS = LIB + "run_operations.py"
RUNOPS_ROUTES = LIB + "routes/run_operations.py"
PREPARED = LIB + "prepared.py"
SCANNER = LIB + "scanner.py"
AG = "agent/src/eugene_plexus_agent/"
WORKER = AG + "run_worker.py"
JOBS = AG + "preparation.py"
RECIPE = AG + "engines/strata_prepare.py"
MODELS = AG + "engines/strata_models.py"
ROUTES = AG + "routes/runtimes.py"
STORE = "ui/src/lib/oneClickRun.ts"
CONTROL = "ui/src/components/PrepareModel.tsx"
DIALOG = "ui/src/components/RunDialog.tsx"
LIBRARY_PAGE = "ui/src/app/library/page.tsx"
DISCOVER = "ui/src/app/discover/page.tsx"
ACCEPTANCE = "specs/scripts/ls5-preparation-acceptance.py"

GATES: dict[str, tuple[str, list[str]]] = {
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_run_preparation.py", "tests/test_run_operations.py",
        "tests/test_prepared.py", "tests/test_catalogue_sources.py",
    ]),
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_strata_prepare.py", "tests/test_run_preparation.py",
        "tests/test_engines.py", "tests/test_run_worker.py",
    ]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/components/PrepareModel.test.tsx",
        "src/lib/oneClickRun.prepare.test.ts", "src/components/RunDialog.test.tsx",
        "src/app/library/page.test.tsx", "src/app/discover/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the library: the operation goes on with the prepared model ---------------------
    ("THE RULE: a preparation run goes on with the original model", "library", RUNOPS,
     '                and record.get("preparedFrom") is None', "                and False"),
    ("skip is an answer to a preparation", "library", RUNOPS_ROUTES,
     '        if body.answer == "skip" and record["intent"].get("preparation"):',
     "        if False:"),
    ("a run that is not preparing lists a prepared model", "library", RUNOPS_ROUTES,
     '    if record["step"] != "preparing" or not preparation:\n        raise HTTPException(409, "Run is not preparing a model")\n    if body',
     '    if not preparation:\n        raise HTTPException(409, "Run is not preparing a model")\n    if body'),
    ("a run prepared for one engine lists another's", "library", RUNOPS_ROUTES,
     '    if body.provenance.engine.value != preparation["engine"]:', "    if False:"),
    ("an entry outside every Library folder is written", "library", RUNOPS_ROUTES,
     "    root = next((r for r in roots if prepared.is_absolute(entry) and is_within(entry, r)), None)",
     "    root = next(iter(roots), None)"),
    ("a missing entry is listed", "library", RUNOPS_ROUTES,
     "    if not os.path.isfile(prepared.entry_path(target, written)):", "    if False:"),
    ("someone else's provenance file is replaced", "library", RUNOPS_ROUTES,
     "    if replace and not prepared.replaces(target, provenance, written):", "    if False:"),
    ("any recipe's file counts as the preparation's own", "library", PREPARED,
     "        and found.recipe == provenance.recipe\n", "        and True\n"),
    ("the operation's model stays the original", "library", RUNOPS_ROUTES,
     '        record["model"] = listed', "        pass"),
    ("/prepared needs no lease before it writes", "library", RUNOPS_ROUTES,
     '    jobs.verify_lease(record, node, body.lease)\n    preparation = record["intent"].get("preparation")',
     '    preparation = record["intent"].get("preparation")'),
    ("the scan reads inside an engine's folder", "library", SCANNER,
     "            if (current / prepared.ENGINE_FILES_MARKER).is_file():", "            if False:"),
    ("the scan lists loose files beside the marker", "library", SCANNER,
     "        if prepared.ENGINE_FILES_MARKER in names:", "        if False:"),
    ("LS4, found on the live install: a search asks for the least downloaded first",
     "library", LIB + "routes/catalogue.py",
     '    descending = CatalogueSortDirection(body.direction or "desc") is CatalogueSortDirection.desc',
     "    descending = (body.direction or CatalogueSortDirection.desc) is CatalogueSortDirection.desc"),
    # --- the agent: the run worker ------------------------------------------------------
    ("THE RULE: a run asking for a preparation is run as it is", "agent", WORKER,
     "            if preparation:\n                return _prepare_route(",
     "            if False:\n                return _prepare_route("),
    ("an engine prepares what it does not prepare", "agent", WORKER,
     '    if verdict["verdict"] != "after_preparation":', "    if False:"),
    ("after installing, a preparation skips preparing", "agent", WORKER,
     '            after = "preparing" if (job.get("intent") or {}).get("preparation") else "settings"',
     '            after = "settings"'),
    ("a lost checkpoint prepares again", "agent", WORKER,
     '        if job.get("preparedFrom") is not None:', "        if False:"),
    ("a failed preparation goes on", "agent", WORKER,
     '        if progress.state != "done" or progress.result is None:',
     "        if progress.result is None and False:"),
    ("the library's refusal to list it is swallowed", "agent", WORKER,
     '            raise ValueError(\n                f"The library could not list the prepared model: {detail or exc}"\n            ) from exc',
     "            pass"),
    ("an entry outside the Library folder is sent", "agent", WORKER,
     '        if inside.parts[:1] == ("..",) or inside.is_absolute():', "        if False:"),
    ("the entry is sent as this node spells it", "agent", WORKER,
     "        entry = join_local(root, inside.parts)", "        entry = str(result.entry)"),
    ("a Library folder this node cannot reach is not named", "agent", WORKER,
     "        if not await asyncio.to_thread(Path(folder).is_dir):", "        if False:"),
    ("a cancelled operation's preparation goes on", "agent", WORKER,
     "        self.actions.preparations.cancel_except(", "        (lambda keep: None)("),
    ("Strata is uninstalled while it prepares", "agent", ROUTES,
     "    if isinstance(preparations, PreparationJobs) and preparations.busy_for(kind.value):",
     "    if False:"),
    # --- the agent: jobs ---------------------------------------------------------------
    ("two preparations run at once", "agent", JOBS,
     "                if self._running():\n", "                if False:\n"),
    ("a cancel never reaches the job", "agent", JOBS,
     "                job.progress.cancelled.set()", "                pass"),
    ("a recipe's failure is reported done", "agent", JOBS,
     '        except PreparationError as exc:\n            progress.error = str(exc)\n            progress.state = "failed"',
     '        except PreparationError as exc:\n            progress.error = str(exc)\n            progress.state = "done"'),
    ("a cancel does not stop the tool", "agent", JOBS,
     "                progress.check_cancelled()\n                time.sleep(0.2)",
     "                time.sleep(0.2)"),
    # Not here: dropping `/T` from the cancel's taskkill. CPython's venv launcher
    # puts its child in a kill-on-close job, so ending the launcher alone ends
    # setup too, and no check can tell the two apart (it escaped, 2026-10-09).
    # --- the agent: Strata's recipe ----------------------------------------------------
    ("setup is asked questions", "agent", RECIPE, '            "--yes",\n', ""),
    ("setup gets the person's own settings folder", "agent", RECIPE,
     '                "APPDATA": str(settings),\n', ""),
    ("Strata's configuration keeps its cwd", "agent", RECIPE,
     '        cfg.pop("cwd", None)', "        pass"),
    ("its paths stay absolute", "agent", RECIPE,
     "                args[i + 1] = self._relative(args[i + 1])", "                pass"),
    ("the expert profile stays in the engine's folder", "agent", RECIPE,
     "                if profile.is_file() and profile.is_relative_to(self.root):",
     "                if False:"),
    ("setup's start script is left behind", "agent", RECIPE,
     "        for leftover in self._produced():\n            leftover.unlink(missing_ok=True)\n        try:",
     "        try:"),
    ("a configuration Eugene cannot launch is listed", "agent", RECIPE,
     "            prepared_config(target, alias=self.choice.model_name, root=self.root)",
     "            pass"),
    ("the engine-files marker is not written", "agent", RECIPE,
     '            marker.write_text(MARKER_TEXT, encoding="utf-8", newline="\\n")', "            pass"),
    ("a Windows line's warning is lost", "agent", RECIPE,
     '            line = raw.rstrip("\\r").split("\\r")[-1].rstrip()',
     '            line = raw.split("\\r")[-1].rstrip()'),
    ("setup's hint under its failure is dropped", "agent", RECIPE,
     "                self._failure.append(text_only)", "                pass"),
    ("a file off the list is planned", "agent", RECIPE,
     "    if found is None:\n        raise PreparationError(", "    if False:\n        raise PreparationError("),
    ("a missing shard is not named", "agent", RECIPE,
     "    missing = [s.name for s in shards_of(gguf) if not s.is_file()]", "    missing = []"),
    ("too little disk starts anyway", "agent", RECIPE,
     "    if free is not None and free < need:", "    if False:"),
    ("any context goes", "agent", RECIPE,
     "    if context is not None and context not in CONTEXTS:", "    if False:"),
    ("the whole llama.cpp archive is unpacked", "agent", RECIPE,
     "                if info.is_dir() or not rest.startswith(LLAMA_CPP_PARTS):",
     "                if info.is_dir():"),
    ("unverified tools are kept", "agent", RECIPE,
     "        _verify(LLAMA_CPP, archive)", "        pass"),
    ("the tools are fetched every time", "agent", RECIPE,
     '    if (llama / "ggml" / "CMakeLists.txt").is_file() and (llama / "gguf-py").is_dir():',
     "    if False:"),
    ("several cards pick the first", "agent", RECIPE,
     "    return min(cards, key=lambda c: (-round(c[1] / 1024), c[0]))[0]", "    return cards[0][0]"),
    ("one card is named with --gpu", "agent", RECIPE,
     "    if len(cards) < 2:\n        return None", "    if not cards:\n        return None"),
    # --- the agent: the list as this node reports it -----------------------------------
    ("disk ignores the low-RAM file", "agent", MODELS,
     "        if ram_gib < choice.arena_gb + LOW_RAM_HEADROOM_GB:", "        if False:"),
    ("a RAM-budget model counts the low-RAM file", "agent", MODELS,
     "    elif not choice.budget:", "    else:"),
    ("the node reports no disk", "agent", MODELS,
     '        preparation = PREPARATION.model_copy(update={"diskBytes": need})',
     "        preparation = PREPARATION"),
    ("Strata offers no contexts", "agent", MODELS,
     "    contexts=[Context(c) for c in SETUP_CONTEXTS],", "    contexts=None,"),
    ("a listed file in another case is not on the list", "agent", MODELS,
     "PurePosixPath(model.source.file).name.lower() == wanted",
     "PurePosixPath(model.source.file).name == wanted"),
    # --- the console -------------------------------------------------------------------
    ("Run finds the preparation as its own run", "ui", STORE,
     "      (r.preparing === null || r.preparedFrom !== null),", "      true,"),
    ("the context chosen is not sent", "ui", STORE,
     "      modelId: model.id,\n      preparation: {\n        engine: preparation.engine,\n        ...(preparation.contextSize ? { contextSize: preparation.contextSize } : {}),",
     "      modelId: model.id,\n      preparation: {\n        engine: preparation.engine,"),
    ("preparing says nothing of where it is", "ui", STORE,
     '    case "preparing":\n      return describePreparation(task);',
     '    case "preparing":\n      return { detail: "preparing" };'),
    ("a failed preparation is named for llama.cpp", "ui", STORE,
     'function stepWord(task: RunTask): string {\n  const label = engineLabel(task.engine ?? task.preparing?.engine ?? "llama_cpp");',
     'function stepWord(task: RunTask): string {\n  const label = engineLabel(task.engine ?? "llama_cpp");'),
    ("download and prepare loses the pinned revision", "ui", DISCOVER,
     "            revision,\n            source,\n            label: entry.title,",
     "            revision: null,\n            source,\n            label: entry.title,"),
    ("Prepare is offered for every engine's verdict", "ui", LIBRARY_PAGE,
     '          .filter((v) => v.verdict === "after_preparation")', "          .filter(() => true)"),
    ("the disk shown is not the node's", "ui", CONTROL,
     "{formatBytes(preparation.diskBytes)}", "{formatBytes(8_000_000_000)}"),
    ("the entry is matched by case", "ui", CONTROL,
     '(m.source.file ?? "").split("/").pop()?.toLowerCase() === wanted',
     '(m.source.file ?? "").split("/").pop() === wanted'),
    ("Skip is offered to a preparation", "ui", DIALOG,
     "          {!task.preparing && (\n            <button", "          {(\n            <button"),
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
    backup = Path(tempfile.mkdtemp(prefix="ls5-sabotage-"))
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
