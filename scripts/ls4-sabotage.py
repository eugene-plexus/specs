"""LS4 sabotage pass: catalogue sources are a list, and engines publish what
they support (library-sources-and-engines.md §4.4). Only the code that
changed.

Restores from a COPY, never `git checkout --`, and opens with a baseline per
gate. Each entry puts one rule of the slice back, or takes one check out, and
names the gate that must notice:

- `library`: the Library's suites for sources, the judge, facts, settings and
  downloads;
- `agent`: Strata's list and the engine descriptor;
- `ui`: Discover, the sources editor and the eligibility helpers (vitest,
  started from `D:`).

Usage: python specs/scripts/ls4-sabotage.py [--gate NAME ...] [--label TEXT ...]
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
JUDGE = LIB + "eligibility.py"
CAT = LIB + "catalogue.py"
SOURCES = LIB + "catalogue_sources.py"
ROUTES = LIB + "routes/catalogue.py"
CONFIG = LIB + "config.py"
DOWNLOADS = LIB + "downloads.py"
STARTER = LIB + "starter.py"
REPO_REF = LIB + "repo_ref.py"
AG = "agent/src/eugene_plexus_agent/"
STRATA = AG + "engines/strata.py"
STRATA_MODELS = AG + "engines/strata_models.py"
RUNTIMES = AG + "runtimes.py"
DISCOVER = "ui/src/app/discover/page.tsx"
EDITOR = "ui/src/components/CatalogueSources.tsx"
UI_ELIG = "ui/src/lib/eligibility.ts"

GATES: dict[str, tuple[str, list[str]]] = {
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_catalogue_sources.py", "tests/test_eligibility.py",
        "tests/test_catalogue_facts.py", "tests/test_settings_truth.py",

    ]),
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_strata.py", "tests/test_engines.py",
    ]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/app/discover/page.test.tsx",
        "src/components/CatalogueSources.test.tsx", "src/lib/eligibility.test.ts",
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the judge: an engine that runs only the files it names ------------------------
    ("THE RULE: a file off the engine's list is prepared anyway", "library", JUDGE,
     "        elif not _named(facts.file, need.files):", "        elif False:"),
    ("a listed file in another case is refused", "library", JUDGE,
     "file.casefold() in {n.casefold() for n in names}", "file in set(names)"),
    ("a search row's unknown file is not said to be assumed", "library", JUDGE,
     "            assumed.append(_files_assumed(need.files))", "            pass"),
    ("a library model is judged with no file name", "library", JUDGE,
     "        file=PureWindowsPath(model.path).name if model.path else None,",
     "        file=None,"),
    ("a hub version's facts carry no file name", "library", CAT,
     "            file=PurePosixPath(first).name or None,", "            file=None,"),
    ("a starter entry's facts carry no file name", "library", STARTER,
     "            file=PurePosixPath(entry.file).name,", "            file=None,"),
    # --- the engines' lists as a source ---------------------------------------------------
    ("an engine list's entry carries no file name", "library", CAT,
     "                            file=file,\n                        )\n                    ],",
     "                            file=None,\n                        )\n                    ],"),
    ("an engine_list source naming one engine lists every engine's", "library", CAT,
     "        if engine is not None and listed.engine != engine:", "        if False:"),
    ("an engine's list ignores the query", "library", CAT,
     "            if not _words_match(query, haystack):", "            if False:"),
    ("an engine's list ignores the format filter", "library", CAT,
     "            if fmt is not None and model.format != fmt:", "            if False:"),
    # --- searching the sources together -------------------------------------------------
    ("a node whose engines publish no list is silent about it", "library", ROUTES,
     "            if not any(\n                source.engine is None or listed_by.engine",
     "            if False and not any(\n                source.engine is None or listed_by.engine"),
    ("a switched-off source is searched", "library", ROUTES,
     "        if not sources_mod.enabled(source):", "        if False:"),
    ("one hub down fails the whole search", "library", ROUTES,
     "        if isinstance(answer, HubError):", "        if False:"),
    ("a later page repeats the sources that had no more", "library", ROUTES,
     "        if cursors is not None and source.id not in cursors:", "        if False:"),
    ("the detail asks the default hub, whatever source is named", "library", ROUTES,
     '    architecture before anything is downloaded.\n    """\n'
     "    client = _client(request, source)",
     '    architecture before anything is downloaded.\n    """\n'
     "    client = _client(request)"),
    ("a pasted link is looked up on the default hub, whatever its host", "library", SOURCES,
     "                and urlsplit(address_of(source)).netloc.lower() == host.lower()",
     "                and False"),
    ("a pasted link's host is dropped", "library", REPO_REF,
     "certain=True, host=split.netloc.lower())", "certain=True)"),
    ("each hub gets the same token", "library", SOURCES,
     "            token=source.token or None,", "            token=self._sources()[0].token,"),
    ("a switched-off hub answers a call naming it", "library", SOURCES,
     "    if not enabled(found):", "    if False:"),
    ("the default hub is the first hub, switched off or not", "library", SOURCES,
     "s.kind is CatalogueSourceKind.hf_hub and enabled(s)), None)",
     "s.kind is CatalogueSourceKind.hf_hub), None)"),
    # --- the config: migration, the file, redaction -------------------------------------
    ("a hub's token is shown", "library", SOURCES,
     '            shown["token"] = None', '            shown["token"] = entry.get("token")'),
    # --- downloads ------------------------------------------------------------------------
    ("a download does not record its hub", "library", DOWNLOADS,
     "            repo=spec.repo,\n            source=source,\n            revision=revision,",
     "            repo=spec.repo,\n            revision=revision,"),
    ("a download's transfer asks the default hub", "library", DOWNLOADS,
     "            client=self._client_of(source),", "            client=self._client_of(None),"),
    # --- the agent: Strata's list ----------------------------------------------------------
    ("an engine not installed publishes no list", "agent", RUNTIMES,
     "                    accepts=list(adapter.accepts_for(None)),\n"
     "                    supportedModels=list(adapter.supported_models),\n",
     "                    accepts=list(adapter.accepts_for(None)),\n"),
    ("THE RULE: Strata prepares any qwen4exp GGUF", "agent", STRATA,
     "            files=list(STRATA_FILES),\n", ""),
    ("Strata's file names keep their folders", "agent", STRATA_MODELS,
     "    PurePosixPath(m.source.file).name for m in SUPPORTED_MODELS if m.source.file",
     "    m.source.file for m in SUPPORTED_MODELS if m.source.file"),
    ("a revision that is not upstream setup's", "agent", STRATA_MODELS,
     '    _QWEN: "ed59f92082b1e93c0e96d60a8b11aab089b52f09",',
     '    _QWEN: "0000000000000000000000000000000000000000",'),
    # --- the console -------------------------------------------------------------------------
    ("the search sends no engine list", "ui", DISCOVER,
     "            ...(lists ? { engines: lists } : {}),", ""),
    ("an older Library's 405 is an error, not the one hub", "ui", DISCOVER,
     "          if (!(err instanceof ApiError && err.status === 405)) throw err;",
     "          throw err;"),
    ("THE CALL: Discover opens on Everything where llama.cpp runs hub models", "ui", DISCOVER,
     '(runsHubModelsAsTheyAre(engines) ? "works_here" : "")', '""'),
    ("a chosen filter is not remembered", "ui", DISCOVER,
     "          ...(chosenLevel !== null ? { chosenLevel } : {}),", ""),
    ("the old stored default is read as a choice", "ui", DISCOVER,
     "        const chosen = prefs.chosenLevel;",
     "        const chosen = prefs.chosenLevel ?? (prefs as { level?: LevelFilter }).level;"),
    ("a hub row does not say which hub", "ui", DISCOVER,
     "{labels.get(result.source)}", "{null}"),
    ("a source that failed is not said", "ui", DISCOVER,
     ".filter((s) => s.searched && s.problem);", ".filter(() => false);"),
    ("the detail is asked of the default hub", "ui", DISCOVER,
     "          repo,\n          ...hubParam,\n          ...(pinned ? { revision: pinned } : {}),\n"
     "          contextLength: String(contextLength),",
     "          repo,\n          ...(pinned ? { revision: pinned } : {}),\n"
     "          contextLength: String(contextLength),"),
    ("an engine's entry opens at main, not its pinned revision", "ui", DISCOVER,
     "          ...hubParam,\n          ...(pinned ? { revision: pinned } : {}),\n"
     "          contextLength: String(contextLength),",
     "          ...hubParam,\n          contextLength: String(contextLength),"),
    ("a download is fetched from the default hub", "ui", DISCOVER,
     "        // than the sources list is never sent a field it refuses.\n        ...hubParam,\n",
     "        // than the sources list is never sent a field it refuses.\n"),
    ("no version is marked as on an engine's list", "ui", DISCOVER,
     "m.source.file === candidate.files[0]?.path", "false"),
    ("a rename sends a blank token, clearing the saved one", "ui", EDITOR,
     "      if (row.token !== null) out.token = row.token;", '      out.token = row.token ?? "";'),
    ("Strata alone opens on Works here now", "ui", UI_ELIG,
     '(need) => need.format !== "prepared" && need.preparation == null,',
     "(need) => need.preparation == null,"),
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
    args = parser.parse_args()
    chosen = [
        s
        for s in SABOTAGES
        if (not args.gate or s[1] in args.gate)
        and (not args.label or any(part in s[0] for part in args.label))
    ]
    gates = sorted({s[1] for s in chosen})
    backup = Path(tempfile.mkdtemp(prefix="ls4-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")
    missing = [
        (label, io.open(ROOT / relative, encoding="utf-8").read().count(old))
        for label, _gate, relative, old, _new in chosen
        if io.open(ROOT / relative, encoding="utf-8").read().count(old) != 1
    ]
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
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
