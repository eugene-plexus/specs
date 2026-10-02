"""Sabotage pass for what Troy's first profile build found (2026-10-01).

The first profile a person built crashed at launch: the builder saved
`flashAttention: true`, Launch wrote a bare `--flash-attn`, and
llama-server read the next flag as its value. A test had required that
bare shape. On the Inference screen, the crashed runtime and the one
before it could not be told apart (the runtime's name is cut to 60
characters and lost the profile's), and its companion driver, unable to
report its runtime, stood on a row of its own as an "external backend".
The builder's slider said words and pages where Troy wanted tokens and
tok/s.

Each sabotage puts one of those back, or over-corrects it, and requires
the guards to FAIL. Restores are from byte copies, never
`git checkout --`, and the pass opens with a baseline that must pass.

    python scripts/builder-launch-sabotage.py [words in a label]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
UI = ROOT / "ui"
LLAMA = AGENT / "src/eugene_plexus_agent/engines/llama_cpp.py"
RUNTIMES = AGENT / "src/eugene_plexus_agent/runtimes.py"
ROWS = UI / "src/lib/inferenceRows.ts"
LAUNCH = UI / "src/lib/launchSpec.ts"
PAGE = UI / "src/app/inference/page.tsx"
BUILD = UI / "src/lib/profileBuild.ts"


def python(repo: Path) -> Path:
    windows = repo / ".venv" / "Scripts" / "python.exe"
    return windows if windows.exists() else repo / ".venv" / "bin" / "python"


RUNNERS = {
    AGENT: lambda: [str(python(AGENT)), "-m", "pytest", "-q", "-p", "no:warnings", "-p",
                    "no:cacheprovider", "tests/test_engines.py", "tests/test_runtimes.py"],
    UI: lambda: ["npx", "vitest", "run", "src/lib/inferenceRows.test.ts",
                 "src/lib/launchSpec.test.ts", "src/app/inference/page.test.tsx",
                 "src/lib/profileBuild.test.ts", "src/components/ProfileBuilder.test.tsx",
                 "src/lib/oneClickRun.test.ts"],
}

SABOTAGES: list[tuple[str, Path, Path, str, str]] = [
    (
        "flash attention is a bare switch again",
        AGENT, LLAMA,
        "                if value:\n                    argv += [cli, \"on\"]\n",
        "                if value:\n                    argv.append(cli)\n",
    ),
    (
        "an unticked flash attention is sent as off, overriding the engine's auto",
        AGENT, LLAMA,
        "                if value:\n                    argv += [cli, \"on\"]\n",
        "                argv += [cli, \"on\" if value else \"off\"]\n",
    ),
    (
        "the agent does not report the profile a runtime came from",
        AGENT, RUNTIMES,
        "            profile=spec.profile,\n",
        "            profile=None,\n",
    ),
    (
        "Launch does not record the profile",
        UI, LAUNCH,
        "    profile: { id: profile.id, name: profile.name },\n",
        "",
    ),
    (
        "the Inference screen does not say which profile",
        UI, PAGE,
        "            {own?.profile?.name && (\n",
        "            {false && own?.profile?.name && (\n",
    ),
    (
        "a crashed companion is shown as an external backend again",
        UI, ROWS,
        "?? companionOf(d.name, placedNode);",
        "?? null;",
    ),
    (
        "a driver is joined to another machine's runtime of the same name",
        UI, ROWS,
        "    return runtimeByNode.has(onNode(node, name)) ? name : null;\n",
        "    return runtimes.some((r) => r.name === name) ? name : null;\n",
    ),
    (
        "the slider says words a second again",
        UI, BUILD,
        "`${Math.round(speed)} tok/s`;\n  return",
        "`About ${Math.round(speed * 0.75)} words a second`;\n  return",
    ),
    (
        "the slider says pages again",
        UI, BUILD,
        "  return `${said} · ${candidate.contextSize.toLocaleString()} tokens of context`;\n",
        "  return `${said} · holds about ${Math.round(candidate.contextSize / 650)} pages`;\n",
    ),
    (
        "a built profile's row says pages again",
        UI, BUILD,
        "      ? `${context.toLocaleString()} tokens of context`\n",
        "      ? `room for about ${Math.round(context / 650)} pages`\n",
    ),
]

TIMEOUT = 300


def run(repo: Path) -> int:
    try:
        result = subprocess.run(RUNNERS[repo](), cwd=repo, capture_output=True, text=True,
                                timeout=TIMEOUT, encoding="utf-8", errors="replace",
                                shell=sys.platform == "win32" and repo == UI)
    except subprocess.TimeoutExpired:
        print(f"    {repo.name}: did not finish in {TIMEOUT} s", flush=True)
        return 124
    tail = (result.stdout + result.stderr).strip().splitlines()
    summary = next((line for line in reversed(tail) if "passed" in line or "failed" in line), "")
    print(f"    {repo.name}: exit={result.returncode}  {summary.strip()}", flush=True)
    return result.returncode


def main() -> None:
    only = " ".join(sys.argv[1:]).lower()
    chosen = [s for s in SABOTAGES if only in s[0].lower()]
    files = {path for _, _, path, _, _ in SABOTAGES}
    copies = {path: path.read_bytes() for path in files}
    for label, _, path, old, _ in SABOTAGES:
        if copies[path].decode("utf-8").replace("\r\n", "\n").count(old) != 1:
            raise SystemExit(f"sabotage anchor not found exactly once: {label}")
    caught, escaped = 0, []
    try:
        print("baseline: every guard passes unsabotaged", flush=True)
        if any(run(repo) != 0 for repo in RUNNERS):
            raise SystemExit("BASELINE FAILED; fix that first")
        print("baseline PASS\n", flush=True)
        for label, repo, path, old, new in chosen:
            source = copies[path].decode("utf-8").replace("\r\n", "\n")
            print(f"sabotage: {label}", flush=True)
            path.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            try:
                code = run(repo)
            finally:
                path.write_bytes(copies[path])
            if code != 0:
                caught += 1
                print("    CAUGHT\n", flush=True)
            else:
                escaped.append(label)
                print("    ESCAPED\n", flush=True)
        print(f"{caught} of {len(chosen)} caught")
        for label in escaped:
            print(f"ESCAPED: {label}")
        if escaped:
            sys.exit(1)
    finally:
        for path, raw in copies.items():
            path.write_bytes(raw)


if __name__ == "__main__":
    main()
