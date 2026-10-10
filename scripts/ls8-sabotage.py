"""LS8 sabotage pass: Delete a model from the Library, any format
(library-sources-and-engines.md §6.11). Only the code that changed. Restores
from a COPY, never `git checkout --`, and opens with a baseline per gate.

Usage: python specs/scripts/ls8-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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
DELETION = LIB + "deletion.py"
MODELS = LIB + "routes/models.py"
DELETE_UI = "ui/src/components/DeleteModel.tsx"
PAGE = "ui/src/app/library/page.tsx"
ACCEPTANCE = "specs/scripts/ls8-delete-acceptance.py"

GATES: dict[str, tuple[str, list[str]]] = {
    "library": ("library", [
        str(ROOT / "library" / ".venv" / "Scripts" / "python.exe"),
        "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
        "tests/test_deletion.py",
    ]),
    "ui": ("ui", [
        "cmd", "/c", "npx", "vitest", "run", "src/components/DeleteModel.test.tsx",
        "src/app/library/page.test.tsx",
    ]),
    "acceptance": ("specs", [
        str(ROOT / "agent" / ".venv" / "Scripts" / "python.exe"), ACCEPTANCE.removeprefix("specs/"),
    ]),
}

# (label, gate, file, old, new)
SABOTAGES: list[tuple[str, str, str, str, str]] = [
    ("THE RULE: a file another model uses is deleted anyway", "library", DELETION,
     "        others = users.get(_key(f.path))", "        others = None"),
    ("models deleted together still keep each other's shared files", "library", DELETION,
     "    skip = {model.id, *also}", "    skip = {model.id}"),
    ("what was prepared from a GGUF is not named", "library", DELETION,
     "if m.id != model.id and m.prepared is not None and m.prepared.sourceModelId == model.id",
     "if m.id != model.id and m.prepared is not None and False"),
    ("a download writing into it does not refuse", "library", DELETION,
     "        if download.state not in WRITING:", "        if True:"),
    ("a run working on it does not refuse", "library", DELETION,
     '        if record.get("step") in FINISHED_STEPS:', "        if True:"),
    ("a safetensors folder's other files are left", "library", DELETION,
     "    if model.format is ModelFormat.safetensors and os.path.isdir(model.path):",
     "    if False:"),
    ("THE RULE: a file that cannot be moved leaves the rest deleted", "library", DELETION,
     "            for original, hidden in reversed(moved):",
     "            for original, hidden in []:"),
    ("files are removed in place, with no step aside", "library", DELETION,
     "            os.replace(path, aside)", "            os.remove(path)"),
    ("folders left empty stay", "library", DELETION,
     "            current.rmdir()  # only when empty", "            return"),
    ("a stale plan deletes anyway", "library", MODELS,
     "        if shown.token != body.token:", "        if False:"),
    ("a refusal does not hold at delete time", "library", MODELS,
     "        if shown.refusal:", "        if False:"),
    ("the model stays listed after its files go", "library", MODELS,
     "            store.forget_model(p.model.id)", "            pass"),
    ("models deleted together are planned apart", "library", MODELS,
     "        together = {model.id, *also}", "        together = {model.id}"),
    ("THE RULE: a node running it does not block", "ui", DELETE_UI,
     "  const refusal = plan?.refusal ?? blocked;", "  const refusal = plan?.refusal ?? null;"),
    ("a running runtime does not count as running", "ui", DELETE_UI,
     'runtime.status !== "stopped" && runtime.status !== "exited" && runtime.status !== "crashed"',
     "false"),
    ("a node that cannot be asked does not block", "ui", DELETE_UI,
     "  if (unread.length > 0) {", "  if (false) {"),
    ("runtimes naming it are left pointing at nothing", "ui", DELETE_UI,
     "      for (const { node, r } of declared) {", "      for (const { node, r } of [] as typeof declared) {"),
    ("the ticked prepared models are not sent", "ui", DELETE_UI,
     "{ token: plan.token, ...(also.length ? { alsoDelete: also } : {}) },", "{ token: plan.token },"),
    ("Delete is not offered on the model page", "ui", PAGE,
     "        <DeleteModel model={model} nodes={nodes} onDeleted={onDeleted} />", "        null"),
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
    backup = Path(tempfile.mkdtemp(prefix="ls8-sabotage-"))
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
