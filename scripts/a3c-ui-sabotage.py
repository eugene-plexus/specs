"""A3c UI sabotage pass: break each rule of the fit words and the experts offer; a test must fail.

The words for a split (experts in RAM, partial offload, needs RAM too), the
placement sentence, the experts-in-RAM context on the starter rows, Home and
the Library's panel, and the profile prefill that starts a MoE model on a
small card at that context rather than at llama.cpp's 4,096 floor.

Restores from a copy taken first and opens with a baseline that must pass.

    python a3c-ui-sabotage.py [--ui DIR]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORDS = "src/lib/fitWords.ts"
SUGGEST = "src/lib/contextSuggestion.ts"
BADGE = "src/components/FitBadge.tsx"
STARTER = "src/components/StarterSetPanel.tsx"
LIBRARY = "src/app/library/page.tsx"
HOME = "src/components/home/FirstModelCard.tsx"
EDITOR = "src/components/ProfileEditor.tsx"
RUN = "src/lib/oneClickRun.ts"
STOPPED = "src/lib/runningModel.ts"

GATE = [
    "src/lib/fitWords.test.ts",
    "src/lib/starter.test.ts",
    "src/lib/oneClickRun.test.ts",
    "src/lib/runningModel.test.ts",
    "src/components/FitBadge.offload.test.tsx",
    "src/components/StarterSetPanel.test.tsx",
    "src/components/ProfileEditor.test.tsx",
    "src/app/library/page.test.tsx",
    "src/app/page.test.tsx",
]

SABOTAGES = [
    # --- the words ---------------------------------------------------------
    (
        "a split with its experts in RAM is called a dense spill (the defect)",
        WORDS,
        'if (fit.offload === "experts") return "experts in RAM";',
        'if (fit.offload === "experts") return "partial offload";',
    ),
    (
        "a split of unknown kind is guessed to be a dense spill",
        WORDS,
        '  return "needs RAM too";\n}',
        '  return "partial offload";\n}',
    ),
    (
        "the experts meaning predicts a speed",
        WORDS,
        "Its experts sit in system memory and the rest runs on the graphics card.",
        "Its experts sit in system memory and the rest runs on the graphics card, "
        "so it runs more slowly.",
    ),
    # --- what sits where ---------------------------------------------------
    (
        "the card is said to hold the experts too",
        WORDS,
        'return { kind: "experts", cardBytes: required - experts, expertBytes: experts };',
        'return { kind: "experts", cardBytes: required, expertBytes: experts };',
    ),
    (
        "a tight verdict is not described",
        WORDS,
        'if (fit.verdict !== "tight" && fit.verdict !== "split") return null;',
        'if (fit.verdict !== "split") return null;',
    ),
    (
        "an experts placement is built with no expert share",
        WORDS,
        "if (experts <= 0 || required <= experts) return null;",
        "if (required <= experts) return null;",
    ),
    (
        "every expert is said to move, not up to that many",
        WORDS,
        "Up to ${formatMemory(where.expertBytes)} of experts go to system memory.",
        "All ${formatMemory(where.expertBytes)} of experts go to system memory.",
    ),
    (
        "a dense spill's size is not worked out from the budget",
        WORDS,
        "systemBytes: free > 0 && required > free ? required - free : null",
        "systemBytes: null",
    ),
    (
        "a zero context is offered",
        WORDS,
        'if (typeof tokens !== "number" || tokens <= 0) return null;',
        'if (typeof tokens !== "number") return null;',
    ),
    # --- the badge ---------------------------------------------------------
    (
        "the badge keeps its own old word table",
        BADGE,
        "  const word = verdictWord(fit);",
        '  const word = fit.verdict === "split" ? "partial offload" : verdictWord(fit);',
    ),
    (
        "the badge's numbers offer the experts context for a dense spill",
        BADGE,
        'const longest = fit.offload === "experts" ? expertsContextSentence(expertsContext) : null;',
        "const longest = expertsContextSentence(expertsContext);",
    ),
    (
        "the badge's numbers never say what sits where",
        BADGE,
        "const where = withPlacement ? placementSentence(fit) : null;",
        "const where = null;",
    ),
    # --- the starter rows --------------------------------------------------
    (
        "a dense row offers a stray experts number",
        STARTER,
        '{model.fit?.offload === "experts" && model.maxContextExpertsInRam != null && (',
        "{model.maxContextExpertsInRam != null && (",
    ),
    (
        "a MoE row never offers its experts context",
        STARTER,
        '{model.fit?.offload === "experts" && model.maxContextExpertsInRam != null && (',
        '{false && model.fit?.offload === "experts" && model.maxContextExpertsInRam != null && (',
    ),
    # --- the Library's panel -----------------------------------------------
    (
        "the Library calls experts in RAM a partial CPU offload",
        LIBRARY,
        '? "Runs with its experts in system memory"',
        '? "Needs partial CPU offload"',
    ),
    (
        "the Library guesses a dense spill for a file read without its tensor table",
        LIBRARY,
        ': "Needs system memory as well")}',
        ': "Needs partial CPU offload")}',
    ),
    (
        "the Library never says what sits where",
        LIBRARY,
        "{!resident && placementSentence(fit.fit) && (",
        "{false && placementSentence(fit.fit) && (",
    ),
    (
        "the Library offers an experts context on a dense model",
        LIBRARY,
        '{fit.fit.offload === "experts" && expertsContextSentence(fit.maxContextExpertsInRam) && (',
        "{expertsContextSentence(fit.maxContextExpertsInRam) && (",
    ),
    # --- Home --------------------------------------------------------------
    (
        "Home shows the library's long reason for an experts pick",
        HOME,
        "      {expertsWhere ? (",
        "      {false ? (",
    ),
    (
        "Home drops the experts-in-RAM context",
        HOME,
        "{expertsContext && <> {expertsContext}</>}",
        "",
    ),
    # --- the offer: a new profile's context --------------------------------
    (
        "the experts context is never asked for (profile starts empty, fit floors it at 4,096)",
        SUGGEST,
        "  return expertsInRamContext(model, target);",
        "  return null;",
    ),
    (
        "the experts context is capped like a whole-card number (left unset at the model's own)",
        SUGGEST,
        "const tokens = model.contextLength != null ? Math.min(longest, model.contextLength) : longest;",
        "const tokens = contextPrefill(longest, model.contextLength) ?? 0;\n"
        "    if (tokens <= 0) return null;",
    ),
    (
        "a dense layer spill is given the experts context",
        SUGGEST,
        'if (fit.fit?.offload !== "experts") return null;',
        "",
    ),
    (
        "an engine whose fit does not move experts is asked anyway",
        SUGGEST,
        "if (engine !== EXPERTS_MOVE_ON) return null;",
        "",
    ),
    (
        "a node with no devices is scored against the library's own host",
        SUGGEST,
        "if (!budget) return null;",
        "",
    ),
    (
        "a whole file on the card asks for the experts number too",
        SUGGEST,
        'if (answer.fit === "fits" || answer.fit === "unknown") return null;',
        "",
    ),
    (
        "the experts number wins over a whole-card one",
        SUGGEST,
        '  if (whole !== null) return { tokens: whole, way: "whole" };',
        "",
    ),
    (
        "the experts path is asked of this browser's machine, not the run's",
        SUGGEST,
        'const identity = await api.get<NodeIdentity>(target, "/v1/node");',
        'const identity = await api.get<NodeIdentity>("agent", "/v1/node");',
    ),
    (
        "Run ignores the suggestion",
        RUN,
        'defaultProfileSpec(engine as ModelProfile["engine"], suggestion?.tokens ?? null);',
        'defaultProfileSpec(engine as ModelProfile["engine"], null);',
    ),
    (
        "the profile form calls an experts prefill a whole-card one",
        EDITOR,
        'suggestedWay={prefillContext?.way ?? "whole"}',
        'suggestedWay="whole"',
    ),
    (
        "the profile form ignores the suggestion",
        EDITOR,
        "suggestedContext={prefillContext?.tokens ?? null}",
        "suggestedContext={null}",
    ),
    # --- PB1's stop reason, which the re-pin brought -----------------------
    (
        "a runtime a test paused is described as stopped by someone",
        STOPPED,
        'measurement: "a test of this machine paused it, and it starts again when the test ends",',
        'measurement: "someone stopped it",',
    ),
]


def run_gate(ui: Path) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["npx", "vitest", "run", *GATE],
            cwd=ui,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            shell=True,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1500:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", type=Path, default=Path(__file__).resolve().parents[2] / "ui")
    ui = parser.parse_args().ui.resolve()
    files = sorted({f for _, f, _, _ in SABOTAGES})
    with tempfile.TemporaryDirectory(prefix="a3c-ui-sabotage-") as tmp:
        backup = Path(tmp)
        for f in files:
            (backup / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ui / f, backup / f)

        def restore() -> None:
            for f in files:
                shutil.copy2(backup / f, ui / f)

        try:
            code, tail = run_gate(ui)
            if code != 0:
                print("BASELINE FAILED: the gate does not pass unsabotaged")
                print(tail)
                return 2
            print("baseline passes")
            caught = escaped = 0
            for name, f, original, sabotaged in SABOTAGES:
                text = (backup / f).read_bytes().decode("utf-8")
                if text.count(original) != 1:
                    print(f"NOT APPLIED ({text.count(original)} matches): {name}")
                    escaped += 1
                    continue
                (ui / f).write_bytes(text.replace(original, sabotaged).encode("utf-8"))
                try:
                    code, _ = run_gate(ui)
                    if code == 0:
                        print(f"ESCAPED: {name}")
                        escaped += 1
                    else:
                        print(f"caught: {name}")
                        caught += 1
                finally:
                    restore()
            print(f"{caught} of {len(SABOTAGES)} caught, {escaped} escaped or not applied")
            return 0 if escaped == 0 else 1
        finally:
            restore()


if __name__ == "__main__":
    sys.exit(main())
