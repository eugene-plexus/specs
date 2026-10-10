"""LS6 sabotage pass: each engine owns its fit model
(library-sources-and-engines.md §4.3, §6.1, §6.7). Only the code that changed.

Restores from a COPY, never `git checkout --`, and opens with a baseline per
gate. Each entry puts one rule of the slice back, or takes one check out, and
names the gate that must notice:

- `library`: the `reserved_share` arithmetic, the judge's per-engine fit and
  the level it feeds, the fit route's `fitModel`, the candidates' sizes;
- `agent`: each adapter's declaration, Strata's setup table, admission by the
  engine's own model, the library client, Run's context;
- `ui`: the judge's question and its older-Library fallback, the fit panel
  per engine, the popover's fit lines, Discover's version column (vitest,
  started from `D:`);
- `acceptance`: `ls6-fit-acceptance.py`, for what only real processes show.

Usage: python specs/scripts/ls6-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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
FIT = LIB + "fit.py"
ENGINE_FIT = LIB + "engine_fit.py"
JUDGE = LIB + "eligibility.py"
GUIDANCE = LIB + "routes/guidance.py"
MODELS_ROUTE = LIB + "routes/models.py"
CATALOGUE = LIB + "catalogue.py"
STARTER = LIB + "starter.py"
AG = "agent/src/eugene_plexus_agent/"
ADMISSION = AG + "admission.py"
STRATA = AG + "engines/strata.py"
SETUP = AG + "engines/strata_models.py"
VLLM = AG + "engines/vllm.py"
LLAMA = AG + "engines/llama_cpp.py"
RUNTIMES = AG + "runtimes.py"
WORKER = AG + "run_worker.py"
ELIGIBILITY = "ui/src/lib/eligibility.ts"
BUDGET = "ui/src/lib/nodeBudget.ts"
LIBRARY_PAGE = "ui/src/app/library/page.tsx"
DISCOVER = "ui/src/app/discover/page.tsx"
DOT = "ui/src/components/EligibilityDot.tsx"
ACCEPTANCE = "specs/scripts/ls6-fit-acceptance.py"

GATES: dict[str, tuple[str, list[str]]] = {
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_engine_fit.py", "tests/test_eligibility.py", "tests/test_catalogue_facts.py",
        "tests/test_catalogue_sources.py", "tests/test_guidance.py", "tests/test_one_fit_path.py",
    ]),
    "agent": ("agent", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_fit_per_engine.py", "tests/test_strata.py", "tests/test_admission.py",
        "tests/test_vllm.py", "tests/test_engines.py", "tests/test_run_worker.py",
    ]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/lib/eligibility.test.ts",
        "src/lib/nodeBudget.test.ts", "src/app/library/page.test.tsx",
        "src/app/discover/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the library: vLLM's share --------------------------------------------------------
    ("THE RULE: a share-taking engine spills to system memory", "library", FIT,
     "        if need_per_card > share_per_card:\n            verdict = FitVerdict.no",
     "        if need_per_card > share_per_card:\n            verdict = FitVerdict.split"),
    ("a share-taking engine starts with less than its share free", "library", FIT,
     "        elif free / cards < share_per_card:", "        elif False:"),
    ("the share is of free memory, not the total", "library", FIT,
     "    share = int(total * utilization)", "    share = int(free * utilization)"),
    ("the model is not split across the cards", "library", FIT,
     "        need_per_card = required / cards", "        need_per_card = required"),
    ("the longest context ignores the share", "library", FIT,
     "    room = int(total * utilization) - overhead_bytes * cards - weights_bytes - fixed",
     "    room = total - overhead_bytes * cards - weights_bytes - fixed"),
    ("a caller's total memory is ignored", "library", FIT,
     "        if vram_total_override is not None:", "        if False:"),
    # --- the library: the judge -----------------------------------------------------------
    ("THE RULE: a fit of `no` never counts against the level", "library", JUDGE,
     "        if engine_fit.counts_as_no(v.fit)", "        if False"),
    ("a fit not estimated counts as `no`", "library", ENGINE_FIT,
     "    return bool(answer and answer.estimated and answer.verdict is FitVerdict.no)",
     "    return bool(answer and (not answer.estimated or answer.verdict is FitVerdict.no))"),
    ("an engine with no fit model borrows llama.cpp's", "library", ENGINE_FIT,
     '    if declared is None:\n        return not_estimated("this engine has no fit estimate in Eugene yet")',
     "    if declared is None:\n        declared = EngineFitModel(kind=FitModelKind.spill)"),
    ("an engine's table is matched by case", "library", ENGINE_FIT,
     "    return next((row for row in table if row.file.lower() == wanted), None)",
     "    return next((row for row in table if row.file == file), None)"),
    ("a prepared model is looked up by its own file", "library", ENGINE_FIT,
     "        return Sizing(weights_bytes=None, file=_name(source.file if source else None))",
     "        return Sizing(weights_bytes=None, file=_name(model.path))"),
    ("a guessed candidate's fit is not marked approximate", "library", ENGINE_FIT,
     "        approximate=bool(candidate.approximate),", "        approximate=False,"),
    ("a read candidate's fit is marked approximate", "library", ENGINE_FIT,
     "        approximate=bool(candidate.approximate),", "        approximate=True,"),
    ("a spill engine under a caller's budget compares the total", "library", ENGINE_FIT,
     "            if question.budget.source is Source.override", "            if False"),
    ("an engine that does not load it is given a fit", "library", JUDGE,
     "                if verdict.verdict is EngineVerdictKind.no", "                if False"),
    ("the route never asks the fit question", "library", MODELS_ROUTE,
     "    question = await _fit_question(request, body.fit) if body.fit is not None else None",
     "    question = None"),
    ("a lone card's question counts no card", "library", ENGINE_FIT,
     "        cards = 1 if vram_total > 0 else 0", "        cards = 0"),
    ("the fit route ignores the engine's fit model", "library", GUIDANCE,
     "    if kind is FitModelKind.reserved_share:\n        assert gpuMemoryUtilization is not None",
     "    if False:\n        assert gpuMemoryUtilization is not None"),
    ("the fit route answers an engine's table with llama.cpp's", "library", GUIDANCE,
     "    if kind is FitModelKind.engine_table:", "    if False:"),
    ("a version's facts lose its size", "library", CATALOGUE,
     "            sizeBytes=group.size,\n        )\n    path = config_path(group)",
     "        )\n    path = config_path(group)"),
    ("an engine list's facts lose the size", "library", CATALOGUE,
     "                            sizeBytes=model.sizeBytes,\n", ""),
    ("the starter set's facts lose the size", "library", STARTER,
     "            sizeBytes=entry.size_bytes,\n", ""),
    # --- the agent: declarations ----------------------------------------------------------
    ("llama.cpp declares no fit model", "agent", LLAMA,
     "    fit_model = EngineFitModel(kind=FitModelKind.spill)", "    fit_model = None"),
    ("vLLM's default share is the old 0.9", "agent", VLLM,
     "DEFAULT_GPU_MEMORY_UTILIZATION = 0.92", "DEFAULT_GPU_MEMORY_UTILIZATION = 0.9"),
    ("an engine not installed reports no fit", "agent", RUNTIMES,
     "                    fit=fit,\n", ""),
    ("the table names its rows by list id", "agent", SETUP,
     "        file = PurePosixPath(model.source.file).name if model.source.file else model.id",
     "        file = model.id"),
    ("Strata's card may be one it cannot use", "agent", STRATA,
     "        if d.kind in STRATA_CARDS and not d.sharedMemory", "        if not d.sharedMemory"),
    # --- the agent: setup's rule ----------------------------------------------------------
    ("THE RULE: Strata's low-RAM mode is not setup's", "agent", SETUP,
     "    if low_ram_needed(choice, ram_gib) and low_ram_fits(choice, ram_gib, vram_gib):",
     "    if False:"),
    ("a few GB short is `no`, not setup's `tight`", "agent", SETUP,
     "    if ram_gib >= choice.ram_gb - TIGHT_GB:", "    if False:"),
    ("a RAM-budget model is sized like the rest", "agent", SETUP,
     "    if choice.budget:\n        if ram_gib >= choice.ram_gb:",
     "    if False:\n        if ram_gib >= choice.ram_gb:"),
    ("the RAM budget leaves nothing beside it", "agent", SETUP,
     "    gib = round(ram_gib) - UNSLOTH_RAM_LEFT_GB", "    gib = round(ram_gib)"),
    ("no card is answered as if there were one", "agent", SETUP,
     "    if vram_gib is None:\n        return SetupFit(",
     "    if vram_gib is None:\n        vram_gib = 0.0\n    if False:\n        return SetupFit("),
    # --- the agent: admission -------------------------------------------------------------
    ("THE RULE: Strata is admitted without its table", "agent", ADMISSION,
     "    if spec.engine is EngineKind.strata:\n        return strata_admission(",
     "    if False:\n        return strata_admission("),
    ("MLX and Kev are measured by llama.cpp's arithmetic", "agent", ADMISSION,
     "    if declared is None:\n        return Admission(", "    if False:\n        return Admission("),
    ("A4: an engine with no fit model is not told which device it runs on", "agent", ADMISSION,
     "            device=device,\n            devices=list(placement.devices) if placement.spread else None,\n            contextLength=context_length,",
     "            device=None,\n            devices=list(placement.devices) if placement.spread else None,\n            contextLength=context_length,"),
    ("vLLM is asked about llama.cpp's fit", "agent", ADMISSION,
     "            fit_model=declared.kind.value if shares else None,", "            fit_model=None,"),
    ("a launch's own share is ignored", "agent", ADMISSION,
     "        return float(asked)", "        return declared.gpuMemoryUtilization"),
    ("vLLM is measured at llama.cpp's flag", "agent", ADMISSION,
     "        context_length = model_length(flags)", "        pass"),
    ("vLLM holds only what the model needs", "agent", ADMISSION,
     "            required = max(required, taken)", "            pass"),
    ("vLLM's refusal says to set gpuLayers", "agent", ADMISSION,
     "        if shares:\n            # Nothing moves", "        if False:\n            # Nothing moves"),
    ("Strata ignores the RAM free now", "agent", ADMISSION,
     "        and available < experts", "        and False"),
    ("Strata holds nothing on its card", "agent", ADMISSION,
     "            requiredBytes=room if fit is not AdmissionFit.unknown else None,",
     "            requiredBytes=None,"),
    ("Strata's `tight` is admitted", "agent", ADMISSION,
     "    if fit in (AdmissionFit.fits, AdmissionFit.split):",
     "    if fit in (AdmissionFit.fits, AdmissionFit.split, AdmissionFit.tight):"),
    ("the library client never sends the fit model", "agent", ADMISSION,
     "            if fit_model is not None:", "            if False:"),
    ("Run suggests vLLM a flag it refuses", "agent", WORKER,
     "        if not takes_context_size(engine):", "        if False:"),
    # --- the console ----------------------------------------------------------------------
    ("THE RULE: a version's column quotes llama.cpp for every engine", "ui", DISCOVER,
     '            const spills = candidate.format === "gguf" && (!ownFit || ownFit.model === "spill");',
     "            const spills = true;"),
    ("the Library page never asks the fit question", "ui", LIBRARY_PAGE,
     "            fit: fitKey ? (JSON.parse(fitKey) as FitQuestion) : null,", "            fit: null,"),
    ("Discover's versions are judged without the fit question", "ui", DISCOVER,
     "    fitQuestion(budget, contextLength),\n  );\n  const answerFor",
     "    null,\n  );\n  const answerFor"),
    ("an older Library is not asked again", "ui", ELIGIBILITY,
     "    if (!isRefusal(err)) throw err;", "    throw err;"),
    ("the node's engines' fit models are not sent", "ui", ELIGIBILITY,
     "    ...(e.fit ? { fit: e.fit } : {}),\n", ""),
    ("an older agent's llama.cpp has no fit model", "ui", ELIGIBILITY,
     '  return engine.engine === "llama_cpp" ? { kind: "spill" } : null;', "  return null;"),
    ("the dot's engine ignores a fit of `no`", "ui", ELIGIBILITY,
     '    (v) => v.available && (v.verdict === "runs" || v.verdict === "may_run") && !fitsNot(v),',
     '    (v) => v.available && (v.verdict === "runs" || v.verdict === "may_run"),'),
    ("vLLM's panel is asked as llama.cpp's", "ui", LIBRARY_PAGE,
     "          share != null ? shareFitQuery(budget, share) : fitQuery(budget),",
     "          fitQuery(budget),"),
    ("vLLM's panel says what spills", "ui", LIBRARY_PAGE,
     "      {!resident && !shares && placementSentence(fit.fit) && (",
     "      {!resident && placementSentence(fit.fit) && ("),
    ("a prepared model's fit is not its engine's", "ui", LIBRARY_PAGE,
     "          fit={verdictFit(model.prepared?.engine)}", "          fit={null}"),
    ("an engine with no fit model gets llama.cpp's panel", "ui", LIBRARY_PAGE,
     '        (fitEngineModel?.kind === "spill" || fitEngineModel?.kind === "reserved_share" ? (',
     "        (true ? ("),
    ("the panel does not name its engine", "ui", LIBRARY_PAGE,
     "        {name}&rsquo;s estimate\n", "        The estimate\n"),
    ("the popover drops each engine's fit", "ui", DOT,
     "              const fit = fitLine(v, engineName);",
     "              const fit = null as string | null;"),
    ("a share-taking engine is asked without the total", "ui", BUDGET,
     "  if (budget?.gpu?.totalBytes != null) query.vramTotalBytes = String(budget.gpu.totalBytes);\n",
     ""),
    ("the judge's question leaves the total out", "ui", BUDGET,
     "  if (budget.gpu?.totalBytes != null) question.vramTotalBytes = budget.gpu.totalBytes;\n", ""),
    # --- real processes -------------------------------------------------------------------
    ("Strata reports no table on a real node", "acceptance", STRATA,
     "    def fit_model_here(self, devices: DevicesReader) -> EngineFitModel | None:\n        \"\"\"Setup's own",
     "    def _not_asked(self, devices: DevicesReader) -> EngineFitModel | None:\n        \"\"\"Setup's own"),
    ("the real judge never resolves the question", "acceptance", MODELS_ROUTE,
     "    question = await _fit_question(request, body.fit) if body.fit is not None else None",
     "    question = None"),
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
    backup = Path(tempfile.mkdtemp(prefix="ls6-sabotage-"))
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
