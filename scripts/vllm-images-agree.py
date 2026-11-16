"""Row 42: release/manifest.json `vllmImages` and the agent's own pins agree.

The agent pulls what `engines/vllm_images.json` names; the release records
`vllmImages`. Run against an agent checkout: `python vllm-images-agree.py
<agent checkout>`. An agent from before row 42 has no pins file and passes
(the release pins then name images no agent pulls yet).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINS = Path("src/eugene_plexus_agent/engines/vllm_images.json")


def disagreements(manifest: dict, agent_pins: dict) -> list[str]:
    """What differs between the two, as sentences; empty when they agree."""
    released = manifest.get("vllmImages") or {}
    pinned = {k: v for k, v in agent_pins.items() if isinstance(v, dict)}
    out = []
    for variant in sorted(set(released) | set(pinned)):
        mine, theirs = released.get(variant), pinned.get(variant)
        if mine is None or theirs is None:
            out.append(f"{variant}: only in {'the agent' if mine is None else 'the manifest'}")
            continue
        for key in ("image", "version"):
            if mine.get(key) != theirs.get(key):
                out.append(f"{variant}.{key}: manifest {mine.get(key)!r}, agent {theirs.get(key)!r}")
    return out


def main(argv: list[str]) -> int:
    agent = Path(argv[1]) if len(argv) > 1 else ROOT.parent / "agent"
    pins = agent / PINS
    if not pins.is_file():
        print(f"PASS the agent at {agent} predates row 42: no vLLM image pins to compare")
        return 0
    manifest = json.loads((ROOT / "release" / "manifest.json").read_text(encoding="utf-8"))
    found = disagreements(manifest, json.loads(pins.read_text(encoding="utf-8")))
    if found:
        print("FAIL release/manifest.json vllmImages and the agent's pins differ:")
        for line in found:
            print(f"  {line}")
        return 1
    print("PASS release/manifest.json vllmImages equal the agent's engines/vllm_images.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
