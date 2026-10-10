"""Sabotage pass: what an answer being written is doing, and which cap stopped it
(2026-10-10, Troy). Only the code that changed.

Workbench said "Waiting for the model" through minutes of Strata's reasoning,
then stopped the answer at the install's 4,096-token cap and told Troy to raise
his chat's own setting. Restores from a COPY, never `git checkout --`, and
opens with a baseline per gate. Gates:

- `driver`: llama.cpp's running count (`timings_per_token`);
- `gateway`: the count relayed, and `output_cap` with its source;
- `workbench`: the cap kept with the answer (pytest);
- `wbweb`: Workbench's working line, the count across pieces, the length note
  (vitest, started from `D:`);
- `ui`: the Playground's working line and length badge (vitest);
- `acceptance`: `progress-acceptance.py` on real processes (llama.cpp b10948).

Usage: python specs/scripts/writing-progress-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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
LLAMA = Path.home() / ".eugene-plexus" / "engines" / "llama_cpp" / "b10948" / "llama-server.exe"

DRIVER = "inference-driver/src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
GATEWAY = "gateway/src/eugene_plexus_gateway/routes/inference.py"
ANSWERS = "workbench/src/eugene_plexus_workbench/answers.py"
WORDS = "workbench/web/src/lib/words.ts"
USECHAT = "workbench/web/src/lib/useChat.ts"
WORKING = "ui/src/lib/workingState.ts"
PLAYGROUND = "ui/src/app/playground/page.tsx"


def _py(repo: str, *tests: str) -> tuple[str, list[str]]:
    return repo, [
        str(ROOT / repo / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", *tests,
    ]


GATES: dict[str, tuple[str, list[str]]] = {
    "driver": _py("inference-driver", "tests/test_stream_progress.py"),
    "gateway": _py("gateway", "tests/test_output_cap.py", "tests/test_stream_progress.py"),
    "workbench": _py("workbench", "tests/test_output_cap.py"),
    "wbweb": ("workbench/web", ["cmd", "/c", "npx", "vitest", "run", "src/lib/lib.test.ts"]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/lib/outputCap.test.ts",
        "src/lib/workingState.test.ts", "src/app/playground/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "gateway" / ".venv" / "Scripts" / "python.exe"),
        "scripts/progress-acceptance.py",
    ]),
}

INSTALL_CAP = "            return OutputCap(tokens=installed, source=OutputCapSource.install)"
ASKS_FOR_COUNT = '            payload["timings_per_token"] = True\n'

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    # --- the driver ----------------------------------------------------------------------
    ("THE GAP: llama.cpp is not asked for its running count", "driver", DRIVER,
     ASKS_FOR_COUNT, ""),
    ("a frame's count is never read", "driver", DRIVER,
     "    if not isinstance(written, int) or isinstance(written, bool) or written <= 0:",
     "    if True:"),
    ("every frame's count is forwarded", "driver", DRIVER,
     "_GENERATING_PROGRESS_SECONDS = 0.5", "_GENERATING_PROGRESS_SECONDS = 0.0"),
    ("a count that did not rise is said again", "driver", DRIVER,
     "                                and (writing.generatedTokens or 0) > generated",
     "                                and True"),
    # --- the gateway ---------------------------------------------------------------------
    ("the count does not cross the gateway", "gateway", GATEWAY,
     '                "generated_tokens": raw.get("generatedTokens"),\n', ""),
    ("THE BUG: the install's cap is sent and not said", "gateway", GATEWAY,
     INSTALL_CAP, "            return None"),
    ("a profile's cap is called the install's", "gateway", GATEWAY,
     "        return OutputCap(tokens=profiled, source=OutputCapSource.profile)",
     "        return OutputCap(tokens=profiled, source=OutputCapSource.install)"),
    ("a fallback reports the cap the primary would have had", "gateway", GATEWAY,
     "        return caps.get(key, base_cap)", "        return base_cap"),
    ("a stream's final frame has no cap", "gateway", GATEWAY,
     "                    output_cap=output_cap(client),", "                    output_cap=None,"),
    ("a whole answer has no cap", "gateway", GATEWAY,
     "            output_cap=prepared.output_cap(client),", "            output_cap=None,"),
    # --- Workbench's server ----------------------------------------------------------------
    ("the cap is not kept past a restart", "workbench", ANSWERS,
     "                output_cap=m.output_cap,\n", ""),
    ("the cap is not read off the final frame", "workbench", ANSWERS,
     '            cap = extension.get("output_cap")', "            cap = None"),
    ("a cap in another shape is kept", "workbench", ANSWERS,
     '''                if isinstance(cap, dict)
                and isinstance(cap.get("tokens"), int)
                and cap.get("source") in ("request", "profile", "install")''',
     '''                if isinstance(cap, dict)'''),
    # --- Workbench's page ------------------------------------------------------------------
    ("TROY'S REPORT: thinking reads as waiting for the model", "wbweb", WORDS,
     '  const doing = message.content ? "Writing the answer" : message.reasoning ? "Thinking" : null;',
     "  const doing = null as string | null;"),
    ("the backend's count is not shown", "wbweb", WORDS,
     '  const written = progress?.stage === "generating" ? progress.generated_tokens : undefined;',
     "  const written = undefined as number | undefined;"),
    ("the length note blames the chat whatever capped it", "wbweb", WORDS,
     '      return message.finish === "length" ? lengthLimitNote(message) : null;',
     '      return message.finish === "length"\n'
     '        ? lengthLimitNote({ outputCap: { tokens: 1, source: "request" } })\n'
     "        : null;"),
    ("each piece of text clears the count", "wbweb", USECHAT,
     '      return previous?.stage === "generating" ? undefined : null;', "      return null;"),
    # --- the Playground ------------------------------------------------------------------
    ("the Playground ignores the count", "ui", WORKING,
     '  if (progress?.stage === "generating" && progress.generated_tokens) {', "  if (false) {"),
    ("the Playground says still working over a moving count", "ui", WORKING,
     '  return stage !== "prompt" && stage !== "tool" && stage !== "generating";',
     '  return stage !== "prompt" && stage !== "tool";'),
    ("the Playground's badge ignores the cap", "ui", PLAYGROUND,
     "          {lengthStopWords(info.output_cap).badge}", "          {lengthStopWords(null).badge}"),
    # --- only real processes show ------------------------------------------------------
    ("ACCEPTANCE: llama.cpp is not asked for its running count", "acceptance", DRIVER,
     ASKS_FOR_COUNT, ""),
    ("ACCEPTANCE: the install's cap is sent and not said", "acceptance", GATEWAY,
     INSTALL_CAP, "            return None"),
]


def run_gate(name: str) -> tuple[int, str]:
    repo, command = GATES[name]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    env["EP_LLAMA_SERVER"] = str(LLAMA)
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
    backup = Path(tempfile.mkdtemp(prefix="writing-progress-sabotage-"))
    for _label, _gate, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")
    for gate in gates:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
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
