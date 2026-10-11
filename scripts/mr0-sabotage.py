"""Sabotage pass: the embeddings door names `dimensions` and `user` as ignored (MR0,
2026-10-11). Only the code that changed.

Restores from a COPY, never `git checkout --`, and opens with a baseline on every
gate it is about to use, so a "caught" is a gate that was green and went red.

Gates:

- `unit`: the gateway's `tests/test_embeddings.py` and `tests/test_client_disconnect.py`;
- `acceptance`: `mr0-embeddings-honest-acceptance.py` over a fixture engine, through a
  real gateway and a real inference-driver;
- `acceptance-real`: the same, with a real `llama-server` on `nomic-embed-text-v1.5`
  (CPU only), which is the one that can see a real engine's own width.

What this change invites, and what the pass breaks (each once):

* the header never sent (the bug), or sent for one setting only, or in another order;
* the header on every answer, or for an explicit null;
* the opposite fix, quietly honouring `dimensions` by truncating the vector;
* the header on a refusal too.

An escape means the checks cannot tell the fix from its opposite.

Usage: python specs/scripts/mr0-sabotage.py [--gate NAME ...] [--label TEXT ...] [--anchors]
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

INFERENCE = "gateway/src/eugene_plexus_gateway/routes/inference.py"
GATEWAY_PY = str(ROOT / "gateway" / ".venv" / "Scripts" / "python.exe")
ACCEPTANCE = "scripts/mr0-embeddings-honest-acceptance.py"
REAL = [
    "--llama-server",
    "C:/Users/troyc/.eugene-plexus/engines/llama_cpp/b10948/llama-server.exe",
    "--embedding-model",
    "C:/Users/troyc/.eugene-plexus/acceptance-models/nomic-embed-text-v1.5.Q8_0.gguf",
]

GATES: dict[str, tuple[str, list[str]]] = {
    "unit": (
        "gateway",
        [
            GATEWAY_PY, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider",
            "tests/test_embeddings.py", "tests/test_client_disconnect.py",
        ],
    ),
    "acceptance": ("specs", [sys.executable, ACCEPTANCE]),
    "acceptance-real": ("specs", [sys.executable, ACCEPTANCE, *REAL]),
}

HEADER_LINE = '        response.headers["x-eugene-plexus-ignored-settings"] = ", ".join(ignored)\n'
IGNORED_TUPLE = '_EMBEDDING_IGNORED = ("dimensions", "user")\n'
IS_SENT = "if getattr(body, name, None) is not None]\n"
ENCODE = "embedding=_encode_embedding(v, fmt))"
REFUSAL = (
    "        return _no_such_model(body.model, table).as_openai()\n\n"
    "    surfaces = resolution.surfaces()\n"
    '    if surfaces and "embeddings" not in surfaces:\n'
)

# (label, gates, file, old, new)
SABOTAGES: list[tuple[str, tuple[str, ...], str, str, str]] = [
    (
        "THE BUG: the header is never sent",
        ("unit", "acceptance", "acceptance-real"),
        INFERENCE,
        HEADER_LINE,
        "        pass\n",
    ),
    (
        "`user` is not named",
        ("unit", "acceptance"),
        INFERENCE,
        IGNORED_TUPLE,
        '_EMBEDDING_IGNORED = ("dimensions",)\n',
    ),
    (
        "`dimensions` is not named",
        ("unit", "acceptance"),
        INFERENCE,
        IGNORED_TUPLE,
        '_EMBEDDING_IGNORED = ("user",)\n',
    ),
    (
        "both are named in the other order",
        ("unit", "acceptance"),
        INFERENCE,
        IGNORED_TUPLE,
        '_EMBEDDING_IGNORED = ("user", "dimensions")\n',
    ),
    (
        "a setting that was not sent is named",
        ("unit", "acceptance"),
        INFERENCE,
        IS_SENT,
        "if True]\n",
    ),
    (
        "an explicit null is named",
        ("unit", "acceptance"),
        INFERENCE,
        IS_SENT,
        "if name in body.model_fields_set]\n",
    ),
    (
        "THE OPPOSITE FIX: dimensions honoured by truncating the vector",
        ("unit", "acceptance", "acceptance-real"),
        INFERENCE,
        ENCODE,
        "embedding=_encode_embedding(v[: body.dimensions] if body.dimensions else v, fmt))",
    ),
    (
        "a refusal names the settings too",
        ("unit",),
        INFERENCE,
        REFUSAL,
        "        refusal = _no_such_model(body.model, table).as_openai()\n"
        '        refusal.headers["x-eugene-plexus-ignored-settings"] = "dimensions, user"\n'
        "        return refusal\n\n"
        "    surfaces = resolution.surfaces()\n"
        '    if surfaces and "embeddings" not in surfaces:\n',
    ),
]


def run_gate(name: str) -> tuple[int, str]:
    where, command = GATES[name]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("EUGENE_PLEXUS_")}
    try:
        done = subprocess.run(
            command,
            cwd=str(ROOT / where),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, "the gate never returned (hung)"
    return done.returncode, (done.stdout or "")[-1800:] + (done.stderr or "")[-500:]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", action="append", choices=sorted(GATES))
    parser.add_argument("--label", action="append", help="run only entries whose label has this")
    parser.add_argument("--anchors", action="store_true", help="check every anchor, run nothing")
    args = parser.parse_args()
    chosen = [
        (label, [g for g in gates if not args.gate or g in args.gate], relative, old, new)
        for label, gates, relative, old, new in SABOTAGES
        if not args.label or any(part in label for part in args.label)
    ]
    chosen = [entry for entry in chosen if entry[1]]
    gates_used = sorted({g for _label, gates, *_rest in chosen for g in gates})

    missing = []
    for label, _gates, relative, old, _new in chosen:
        count = io.open(ROOT / relative, encoding="utf-8").read().count(old)
        if count != 1:
            missing.append((label, count))
    if missing:
        for label, count in missing:
            print(f"[ANCHOR ] {label}: matched {count} times")
        return 1
    if args.anchors:
        print(f"{len(chosen)} anchors, each matched once")
        return 0

    backup = Path(tempfile.mkdtemp(prefix="mr0-sabotage-"))
    for _label, _gates, relative, _old, _new in chosen:
        destination = backup / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
    print(f"copy in {backup}\n")

    for gate in gates_used:
        code, out = run_gate(gate)
        print(f"[baseline] {gate}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        if code != 0:
            print(out)
            return 1
    print()

    caught = escaped = runs = 0
    for label, gates, relative, old, new in chosen:
        path = ROOT / relative
        source = io.open(path, encoding="utf-8").read()
        io.open(path, "w", encoding="utf-8", newline="\n").write(source.replace(old, new, 1))
        try:
            for gate in gates:
                runs += 1
                code, out = run_gate(gate)
                if code != 0:
                    print(f"[caught ] ({gate}) {label}", flush=True)
                    caught += 1
                else:
                    print(f"[ESCAPED] ({gate}) {label}", flush=True)
                    escaped += 1
        finally:
            shutil.copy2(backup / relative, path)  # restore FROM THE COPY
    print(f"\n{caught} caught, {escaped} escaped, {runs} sabotage runs over {len(chosen)} breaks")

    for gate in gates_used:
        code, out = run_gate(gate)
        print(f"[restored] {gate}: {'PASS' if code == 0 else 'FAIL'}", flush=True)
        if code != 0:
            print(out)
            return 1
    return 0 if escaped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
