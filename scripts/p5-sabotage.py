"""Sabotage pass for p5-videos-acceptance.py.

Each sabotage puts back one way P5 could be wrong -- in the driver or the
gateway -- runs the fixture half of the acceptance, and requires it to FAIL.
The acceptance runs the editable installs, so a source edit is what runs.

Where the gateway and the driver each enforce the same rule (a first frame
only to a model that takes one), removing one copy alone is hidden by the
other; the pass says it expects that to escape and why, and removing BOTH
must be caught.

Restores are from byte copies taken before the first edit, never `git
checkout --`. Opens with a baseline assertion that the gate passes
unsabotaged, and refuses to start if any anchor is not found exactly once.

    python scripts/p5-sabotage.py <python with all five components> [label filter]

The acceptance's SDK half needs `openai` in that python or `$EP_SDK_PYTHON`.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SPECS = Path(__file__).resolve().parents[1]
ROOT = SPECS.parent
DRIVER = ROOT / "inference-driver" / "src" / "eugene_plexus_inference_driver"
GATEWAY = ROOT / "gateway" / "src" / "eugene_plexus_gateway"
ACCEPTANCE = SPECS / "scripts" / "p5-videos-acceptance.py"
COMPAT = DRIVER / "engines" / "openai_compat_http.py"
CATALOGUE = DRIVER / "engines" / "_catalogue.py"
VIDEOS_OUT = DRIVER / "videos_out.py"
DOORS = GATEWAY / "video_doors.py"
ROUTING = GATEWAY / "routing.py"
ROUTE = GATEWAY / "routes" / "inference.py"

_GATEWAY_FRAME = "    if ask.reference is not None and not c.firstFrame:\n"
_DRIVER_FRAME = "            and (caps is None or not caps.firstFrame)\n"


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- the driver ----------------------------------------------------------
    Sabotage(
        "OpenRouter's video listing is never read",
        ((COMPAT, "                models = with_openrouter_videos(models, videos)\n",
          "                pass\n"),),
    ),
    Sabotage(
        "an OpenAI account lists models past their shutdown date",
        ((CATALOGUE, "        if shut_down(entry):\n", "        if False:\n"),),
    ),
    Sabotage(
        "OpenRouter is sent OpenAI's `seconds` string instead of an integer duration",
        ((COMPAT, '            payload["duration"] = request.seconds\n',
          '            payload["seconds"] = str(request.seconds)\n'),),
    ),
    Sabotage(
        "the first frame is sent without its frame_type",
        ((COMPAT, '                    "frame_type": "first_frame",\n', ""),),
    ),
    Sabotage(
        "OpenRouter's pending is read as completed",
        ((VIDEOS_OUT, '    "pending": VideoJobStatus.queued,\n', '    "pending": VideoJobStatus.completed,\n'),),
    ),
    Sabotage(
        "the driver alone lets a first frame through to a model that takes none",
        ((COMPAT, _DRIVER_FRAME, "            and False\n"),),
        escapes="the gateway routes a first frame only to a model whose listing takes one",
    ),
    # --- the gateway: the handle ---------------------------------------------
    Sabotage(
        "a handle's signature is not checked",
        ((DOORS, "        if not hmac.compare_digest(given, expected):\n", "        if False:\n"),),
    ),
    Sabotage(
        "a job's owner is not checked",
        ((ROUTE, '    if payload is None or payload.get("o") != _owner():\n', "    if payload is None:\n"),),
    ),
    Sabotage(
        "the handle secret is made anew by every gateway process",
        ((DOORS, "            if self._path.exists():\n", "            if False:\n"),),
    ),
    Sabotage(
        "the poll paths are not under client admission",
        ((GATEWAY / "admission.py", '        "/v1/videos/{video_id}",\n', ""),),
    ),
    # --- the gateway: routing --------------------------------------------------
    Sabotage(
        "a duration is not checked against the model's listing",
        ((DOORS, "    if ask.seconds is not None and c.durations is not None and ask.seconds not in c.durations:\n",
          "    if False:\n"),),
    ),
    Sabotage(
        "a size is not checked against the model's listing",
        ((DOORS, "    if ask.size is not None and c.sizes is not None and ask.size not in c.sizes:\n",
          "    if False:\n"),),
    ),
    Sabotage(
        "the gateway alone lets a first frame through",
        ((DOORS, _GATEWAY_FRAME, "    if False:\n"),),
        escapes="the driver refuses a first frame for a model that takes none, naming it",
    ),
    Sabotage(
        "neither layer stops a first frame reaching a model that takes none",
        ((DOORS, _GATEWAY_FRAME, "    if False:\n"), (COMPAT, _DRIVER_FRAME, "            and False\n")),
    ),
    Sabotage(
        "the submit tiers are not filtered by what each model takes",
        ((ROUTING, "                if b.makes_videos and video_doors.rules_out(b.video_caps, ask) is None\n",
          "                if b.makes_videos\n"),),
    ),
    Sabotage(
        "a slot where nothing could take the request is not refused naming the setting",
        ((ROUTING, "            ruled = video_doors.rules_out(backend.video_caps, ask)\n",
          "            ruled = None\n"),),
    ),
    # --- the gateway: answering -------------------------------------------------
    Sabotage(
        "a thumbnail is answered with the video",
        ((ROUTE, '    if variant not in (None, "video"):\n', "    if False:\n"),),
    ),
    Sabotage(
        "the list is answered as not found instead of refused",
        ((ROUTE, '    return _error(\n        code=400,\n        message=(\n            "Videos are not listed here',
          '    return _error(\n        code=404,\n        message=(\n            "Videos are not listed here'),),
    ),
    Sabotage(
        "a completed job reports no progress",
        ((DOORS, '    progress = 100 if status == "completed" else',
          '    progress = 0 if status == "completed" else'),),
    ),
    Sabotage(
        "a failed job's error lacks OpenAI's code",
        ((DOORS, '            "code": "video_generation_failed",\n', ""),),
    ),
    Sabotage(
        "a submit's row does not count its seconds",
        ((ROUTE, "                video_seconds=ask.seconds,\n", "                video_seconds=None,\n"),),
    ),
]


def run_acceptance(python: str) -> int:
    result = subprocess.run(
        [python, str(ACCEPTANCE)],
        capture_output=True,
        text=True,
        timeout=600,
        stdin=subprocess.DEVNULL,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    print(f"    exit={result.returncode}  {lines[-1] if lines else ''}", flush=True)
    return result.returncode


def main() -> None:
    python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    only = sys.argv[2] if len(sys.argv) > 2 else None
    chosen = [s for s in SABOTAGES if only is None or only in s.label]
    files = {path for s in chosen for path, _, _ in s.edits}
    copies = {path: path.read_bytes() for path in files}
    for sabotage in chosen:
        for path, old, _ in sabotage.edits:
            if copies[path].decode("utf-8").replace("\r\n", "\n").count(old) != 1:
                raise SystemExit(f"sabotage anchor not found exactly once in {path.name}: {sabotage.label}")
    caught = 0
    expected_escapes: list[str] = []
    surprises: list[str] = []
    try:
        print("baseline: the gate must pass unsabotaged", flush=True)
        if run_acceptance(python) != 0:
            raise SystemExit("BASELINE FAILED: the gate does not pass unsabotaged; fix that first")
        print("baseline PASS\n", flush=True)
        for sabotage in chosen:
            print(f"sabotage: {sabotage.label}", flush=True)
            sources: dict[Path, str] = {}
            for path, old, new in sabotage.edits:
                source = sources.get(path, copies[path].decode("utf-8").replace("\r\n", "\n"))
                sources[path] = source.replace(old, new)
            for path, source in sources.items():
                path.write_text(source, encoding="utf-8", newline="\n")
            try:
                code = run_acceptance(python)
            finally:
                for path in sources:
                    path.write_bytes(copies[path])
            if code != 0 and sabotage.escapes is None:
                caught += 1
                print("    CAUGHT\n", flush=True)
            elif code == 0 and sabotage.escapes is not None:
                expected_escapes.append(sabotage.label)
                print(f"    ESCAPED, as expected: {sabotage.escapes}\n", flush=True)
            else:
                surprises.append(sabotage.label)
                print("    ESCAPED\n" if code == 0 else "    CAUGHT, BUT EXPECTED TO ESCAPE\n", flush=True)
        must = [s for s in chosen if s.escapes is None]
        print(f"{caught} of {len(must)} caught; {len(expected_escapes)} escaped as expected", flush=True)
        for label in surprises:
            print(f"SURPRISE: {label}", flush=True)
        if surprises:
            sys.exit(1)
    finally:
        for path, data in copies.items():
            path.write_bytes(data)


if __name__ == "__main__":
    main()
