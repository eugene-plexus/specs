"""Sabotage pass for the A5 repair and A4's label change, against their unit tests.

Each sabotage puts one defect back into a component's working tree, runs
the tests that guard it, and requires them to FAIL. Restores are from byte
copies taken before the first edit, never `git checkout --`
(feedback: sabotage-runs-restore-from-a-copy), and the pass opens with a
baseline that must pass.

    python scripts/a5-sabotage.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "inference-driver"
UI = ROOT / "ui"
OCH = DRIVER / "src/eugene_plexus_inference_driver/engines/openai_compat_http.py"
COMPAT = UI / "src/lib/engineCompat.ts"


def python(repo: Path) -> Path:
    windows = repo / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else repo / ".venv" / "bin" / "python"


RUNNERS = {
    DRIVER: lambda: [str(python(DRIVER)), "-m", "pytest", "-q", "-p", "no:warnings", "-p",
                     "no:cacheprovider", "tests/test_named_tool_choice.py"],
    UI: lambda: ["npx", "vitest", "run", "src/lib/engineCompat.test.ts"],
}

SABOTAGES: list[tuple[str, Path, Path, str, str]] = [
    (
        "driver: a named choice is never recognised (passed through to be ignored)",
        DRIVER, OCH,
        "        if not isinstance(choice, NamedToolChoice) or not request.tools:\n",
        "        if True:\n",
    ),
    (
        "driver: the translation applies to every backend, not only llama-server",
        DRIVER, OCH,
        "        if tool is None or not await self._answers_as_llama_cpp():\n",
        "        if tool is None:\n",
    ),
    (
        "driver: the tools stay in the request beside the schema",
        DRIVER, OCH,
        '    for key in ("tools", "tool_choice", "parallel_tool_calls"):\n        payload.pop(key, None)\n',
        "",
    ),
    (
        "driver: a cut-off answer is turned into a call anyway",
        DRIVER, OCH,
        '    if finish == "length" or not isinstance(content, str):\n',
        "    if not isinstance(content, str):\n",
    ),
    (
        "driver: a streamed forced answer's arguments go out as text",
        DRIVER, OCH,
        "                        if forced is not None:\n                            held.append(text)\n"
        "                            continue\n",
        "",
    ),
    (
        "driver: a call with no id is named call_0 again",
        DRIVER, OCH,
        '    return f"call_{uuid.uuid4().hex[:24]}"\n',
        '    return "call_0"\n',
    ),
    (
        "ui: MLX is shown on every machine once the flag is gone",
        UI, COMPAT,
        '  if (acquisition?.policy !== "manual") return true;\n',
        "  return true;\n",
    ),
    (
        "ui: llama.cpp is hidden when GitHub refuses its release list",
        UI, COMPAT,
        '  if (acquisition?.policy !== "manual") return true;\n',
        "",
    ),
]


def run(repo: Path) -> int:
    result = subprocess.run(RUNNERS[repo](), cwd=repo, capture_output=True, text=True, timeout=900,
                            encoding="utf-8", errors="replace",
                            shell=sys.platform == "win32" and repo == UI)
    tail = (result.stdout + result.stderr).strip().splitlines()
    summary = next((line for line in reversed(tail) if "passed" in line or "failed" in line), "")
    print(f"    {repo.name}: exit={result.returncode}  {summary.strip()}")
    return result.returncode


def main() -> None:
    files = {path for _, _, path, _, _ in SABOTAGES}
    copies = {path: path.read_bytes() for path in files}
    caught, escaped = 0, []
    try:
        print("baseline: every guard passes unsabotaged")
        if any(run(repo) != 0 for repo in RUNNERS):
            raise SystemExit("BASELINE FAILED; fix that first")
        print("baseline PASS\n")
        for label, repo, path, old, new in SABOTAGES:
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            if source.count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once: {label}")
            print(f"sabotage: {label}")
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run(repo)
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n")
            else:
                escaped.append(label)
                print("    ESCAPED\n")
        print(f"{caught} of {len(SABOTAGES)} caught")
        for label in escaped:
            print(f"ESCAPED: {label}")
        if escaped:
            sys.exit(1)
    finally:
        for path, raw in copies.items():
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
