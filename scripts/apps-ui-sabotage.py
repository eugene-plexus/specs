"""Apps UI sabotage pass: the console's half of apps-and-spokes.md.

Restores from a COPY, never `git checkout --`, and opens with a baseline
(memory: `sabotage-runs-restore-from-a-copy`). Each sabotage is a
plausible wrong wiring, and the gate is the vitest files that drive the
pages rather than the pure module -- a component test is not a wiring
test.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Upper-case drive letter: Vite on Windows resolves a lower-case `d:` cwd
# against upper-case module ids and collects no tests at all.
UI = Path("D:/py/eugene-plexus/ui")
PAGE = "src/app/apps/page.tsx"
SETTINGS = "src/app/apps/settings/page.tsx"
EDITOR = "src/components/ConfigEditor.tsx"
APPS = "src/lib/apps.ts"
TREE = "src/lib/resourceTree.ts"
TOPO = "src/components/ResourceTree.tsx"
FILES = (PAGE, SETTINGS, EDITOR, APPS, TREE, TOPO)
GATE = (
    "src/app/apps",
    "src/lib/apps.test.ts",
    "src/lib/resourceTree.test.ts",
    "src/components/ConfigEditor.test.tsx",
)

SABOTAGES: list[tuple[str, str, str, str]] = [
    (
        "installing on another machine goes to this machine's agent",
        APPS,
        "  if (!node || node === localNode) return \"agent\";\n  return `node:${node}`;",
        "  return \"agent\";",
    ),
    (
        "the settings page hands the editor no endpoints, so it edits the agent",
        SETTINGS,
        "<ConfigEditor target={target} label={app.name} endpoints={endpoints} />",
        "<ConfigEditor target={target} label={app.name} />",
    ),
    (
        "the editor ignores the endpoints it was given for a restart",
        EDITOR,
        "      const waiting = await ends.restart();",
        "      const waiting = await componentEndpoints(target).restart();",
    ),
    (
        "the Test button shows for an app that has no test endpoint",
        EDITOR,
        "          {ends.canTest && (",
        "          {true && (",
    ),
    (
        "an install is started and never watched",
        PAGE,
        "      void watch(id);",
        "      void id;",
    ),
    (
        "a node that cannot install still offers the button",
        PAGE,
        "              disabled={!installable || running}",
        "              disabled={running}",
    ),
    (
        "the Apps branch is drawn with nothing installed",
        TREE,
        "  if (apps.length === 0) return null;\n  const layer = layerOf(\"tools\");",
        "  const layer = layerOf(\"tools\");",
    ),
    (
        "an app selection does not parse",
        TREE,
        '  for (const type of ["driver", "app"] as const) {',
        '  for (const type of ["driver"] as const) {',
    ),
]


def run_gate() -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["npx", "vitest", "run", *GATE],
            cwd=UI,
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
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    backup = Path(tempfile.mkdtemp(prefix="apps-ui-sabotage-"))
    for relative in FILES:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(UI / relative, destination)
    print(f"copy in {backup}\n")

    code, out = run_gate()
    print(f"[baseline] {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1

    caught = escaped = 0
    for label, relative, old, new in SABOTAGES:
        path = UI / relative
        source = io.open(path, encoding="utf-8").read()
        if source.count(old) != 1:
            print(f"[SKIP   ] {label}: anchor matched {source.count(old)} times")
            escaped += 1
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            code, out = run_gate()
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
        if code != 0:
            print(f"[caught ] {label}")
            caught += 1
        else:
            print(f"[ESCAPED] {label}")
            escaped += 1

    print(f"\n{caught} caught, {escaped} escaped, {len(SABOTAGES)} sabotages")
    code, out = run_gate()
    print(f"[restored] {'PASS' if code == 0 else 'FAIL'}")
    if code != 0:
        print(out)
        return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
