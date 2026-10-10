"""LS7b sabotage pass: the Library says what is known of a prepared model
(library-sources-and-engines.md §6.8 and §6.10: B22 replaced, B26, B30, the
source list's order). Only the code that changed. Restores from a COPY,
never `git checkout --`, and opens with a baseline per gate.

Usage: python specs/scripts/ls7b-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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
BASE = AG + "engines/base.py"
STRATA = AG + "engines/strata.py"
STRATA_MODELS = AG + "engines/strata_models.py"
PREPARE = AG + "engines/strata_prepare.py"
FACTS = AG + "prepared_facts.py"
WORKER = AG + "run_worker.py"
RUNTIMES = AG + "runtimes.py"
ROUTES = AG + "routes/runtimes.py"
LIB = "library/src/eugene_plexus_library/"
PREPARED = LIB + "prepared.py"
MODELS = LIB + "routes/models.py"
CATALOGUE = LIB + "routes/catalogue.py"
SOURCES = LIB + "catalogue_sources.py"
FORM = "ui/src/components/AddPreparedModel.tsx"
PREPARE_UI = "ui/src/components/PrepareModel.tsx"
SOURCES_UI = "ui/src/components/CatalogueSources.tsx"
PAGE = "ui/src/app/library/page.tsx"
ACCEPTANCE = "specs/scripts/ls7b-facts-acceptance.py"

GATES: dict[str, tuple[str, list[str]]] = {
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_ls7b_facts.py", "tests/test_strata_prepare.py",
        "tests/test_run_preparation.py", "tests/test_ls7_copies.py",
    ]),
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_prepared.py", "tests/test_catalogue_sources.py",
        "tests/test_settings_truth.py",
    ]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/components/AddPreparedModel.test.tsx",
        "src/components/PrepareModel.test.tsx", "src/components/CatalogueSources.test.tsx",
        "src/app/library/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the agent reads Strata's configuration back (B22 replaced, B26) ---
    ("THE RULE: the MTP helper is not marked shared", "agent", STRATA,
     'SHARED_ARGS = frozenset({"--mtp"})', "SHARED_ARGS: frozenset[str] = frozenset()"),
    ("the source model's shards are listed as the prepared model's own", "agent", STRATA,
     "        if flag in SOURCE_ARGS:\n            continue\n",
     "        if flag in SOURCE_ARGS:\n            pass\n"),
    ("the low-RAM resident mode reads as every expert in RAM", "agent", STRATA,
     '    if "--resident-experts" in args:\n        return "the low-RAM mode',
     '    if False:\n        return "the low-RAM mode'),
    ("the prepared context is not read", "agent", STRATA,
     "        context_length=context if context and context > 0 else None,",
     "        context_length=None,"),
    ("the list entry is never found for the source", "agent", STRATA,
     "    listed = choice_for_file(str(source)) if source is not None else None",
     "    listed = None"),
    ("a missing named file is passed over", "agent", STRATA,
     "        found = files_of(path)\n        if found is None:\n            raise PreparedInspectError(",
     "        found = files_of(path) or []\n        if False:\n            raise PreparedInspectError("),
    ("the source path keeps this node's spelling", "agent", FACTS,
     '            source["path"] = spelled', '            source["path"] = str(facts.source_file)'),
    ("a Windows-spelled Library entry is joined as a POSIX path", "agent", FACTS,
     "    if is_windows_shaped(entry_declared):\n        return ntpath.normpath(",
     "    if False:\n        return ntpath.normpath("),
    ("shared files are not marked in the provenance", "agent", FACTS,
     '        if shared:\n            item["shared"] = True', '        if False:\n            item["shared"] = True'),
    ("files are recorded without their sizes", "agent", FACTS,
     '            item["sizeBytes"] = path.stat().st_size', '            item["sizeBytes"] = 0'),
    ("a preparation records none of what Strata wrote", "agent", PREPARE,
     "            facts=facts,\n", ""),
    ("the worker drops the facts from the provenance it sends", "agent", WORKER,
     "                **result.facts,\n", ""),
    ("a file Strata did not write is a server error, not 422", "agent", ROUTES,
     '            code=status.HTTP_422_UNPROCESSABLE_ENTITY,\n            slug="prepared-unreadable",',
     '            code=500,\n            slug="prepared-unreadable",'),
    ("inspect reads a file outside the Library's folders", "acceptance", ROUTES,
     "    require_library_folder(request, body.entry)\n    local = Path(",
     "    local = Path("),
    # --- B30: the oldest engine an entry needs ---
    ("THE RULE: the installed version equal to the floor is too old", "agent", BASE,
     "and have is not None and need is not None and have < need:",
     "and have is not None and need is not None and have <= need:"),
    ("a version's suffix breaks the comparison", "agent", BASE,
     '        digits = "".join(itertools.takewhile(str.isdigit, piece))',
     "        digits = piece"),
    ("UD-IQ4_XS names no floor", "agent", STRATA_MODELS,
     '        min_engine="v0.1.38",', "        min_engine=None,"),
    ("the node's list loses each entry's floor", "agent", STRATA_MODELS,
     '        preparation = model.preparation.model_copy(update={"diskBytes": need})',
     '        preparation = PREPARATION.model_copy(update={"diskBytes": need})'),
    ("the node never judges its own install", "acceptance", RUNTIMES,
     "supportedModels=with_engine_version(adapter.supported_models_here(), found.version),",
     "supportedModels=list(adapter.supported_models_here()),"),
    # --- the Library says what is known, and names what is not ---
    ("THE RULE: a fact missing is not named", "library", PREPARED,
     "    if source is None or not (source.path or source.repoId or source.file):",
     "    if False:"),
    ("files not on disk still give a size", "library", PREPARED,
     "        if absent:\n            missing.append(", "        if False:\n            missing.append("),
    ("sizes come from the file, not the disk", "library", PREPARED,
     '        out.append(item.model_copy(update={"sizeBytes": size}))', "        out.append(item)"),
    ("no architecture inherited from the source", "library", PREPARED,
     '                    "architecture": model.architecture or source.architecture,',
     '                    "architecture": model.architecture,'),
    ("an inherited architecture is still named missing", "library", PREPARED,
     '                if inherited["architecture"] is not None and prepared.missing:',
     '                if False and prepared.missing:'),
    ("the title is not the model's name in lists", "library", PREPARED,
     "        displayName=provenance.title,\n        status=ModelStatus.present,",
     "        status=ModelStatus.present,"),
    ("its size is not its files'", "library", PREPARED,
     "        sizeBytes=about.diskBytes,", "        sizeBytes=None,"),
    ("files adopted elsewhere keep the entry folder's paths", "library", MODELS,
     "    provenance = prepared.rebased(body.provenance, entry, folder).model_copy(",
     "    provenance = body.provenance.model_copy("),
    # --- the source list's order ---
    ("THE RULE: the engines' lists always answer first", "library", CATALOGUE,
     "        results=[row for s in sources for row in by_source.get(s.id, [])],",
     "        results=[row for s in sorted(sources, key=lambda s: s.kind.value != \"engine_list\")"
     " for row in by_source.get(s.id, [])],"),
    ("the default list puts the hub first", "library", SOURCES,
     "    ]\n\n\ndef _hub_label", "    ][::-1]\n\n\ndef _hub_label"),
    ("an old file's hub lands on the engines' list", "library", SOURCES,
     '    hub = next(s for s in sources if s["kind"] == "hf_hub")', "    hub = sources[0]"),
    # --- the console ---
    ("the source the file names is not chosen", "ui", FORM,
     '  const chosenSource = source ?? named?.id ?? "";', '  const chosenSource = source ?? "";'),
    ("a file the engine refused can be added", "ui", FORM,
     "disabled={busy || folders === null || outside || reading || !!unread?.refused}",
     "disabled={busy || folders === null || outside || reading}"),
    ("what the engine read is not sent", "ui", FORM,
     "    const read = draft ? { ...draft } : {};", "    const read = {};"),
    ("a too-old engine still prepares", "ui", PREPARE_UI,
     "  const blocked = disabledReason ?? tooOld;", "  const blocked = disabledReason;"),
    ("moving a source does nothing", "ui", SOURCES_UI,
     "    [next[index], next[to]] = [next[to]!, next[index]!];", "    void next[to];"),
    ("the made-from reason shows twice", "ui", PAGE,
     '        .filter((m) => m.fact !== "source")', "        .filter(() => true)"),
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
    backup = Path(tempfile.mkdtemp(prefix="ls7b-sabotage-"))
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
