"""Sabotage pass for p6-acceptance.py.

Each sabotage puts back one way P6a could be wrong -- in the driver or the
gateway -- runs the fixture half of the acceptance, and requires it to FAIL.
The acceptance runs the editable installs, so a source edit is what runs.

Where the gateway and the driver each enforce the same rule (a remote image
is never forwarded), removing one copy alone is hidden by the other; the pass
says it expects that to escape and why.

Restores are from byte copies taken before the first edit, never `git
checkout --`. Opens with a baseline assertion that the gate passes
unsabotaged, and refuses to start if any anchor is not found exactly once.

    python scripts/p6-sabotage.py <python with all five components> [label filter]

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
ACCEPTANCE = SPECS / "scripts" / "p6-acceptance.py"
COMPAT = DRIVER / "engines" / "openai_compat_http.py"
MODERATE = DRIVER / "routes" / "moderate.py"
DOOR = GATEWAY / "moderation_door.py"
ROUTING = GATEWAY / "routing.py"
ROUTE = GATEWAY / "routes" / "inference.py"
ADMISSION = GATEWAY / "admission.py"
RAW = DRIVER / "raw_completion.py"
CATALOGUE = DRIVER / "engines" / "_catalogue.py"
COMPLETION_DOOR = GATEWAY / "completion_door.py"

_RETRIEVE_ALLOWED = (
    "    listed = (\n        table.as_model_list(\n"
    "            context.allowed_models if context else None, local_only=admission.local_only()\n"
)


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- the driver --------------------------------------------------------------
    Sabotage(
        "an OpenAI moderation model is not sorted into moderation",
        ((COMPAT, '    if "moderation" in lowered:\n', "    if False:\n"),),
    ),
    Sabotage(
        "the driver moderates with a model that does not",
        ((MODERATE, "    if not moderates:\n", "    if False:\n"),),
    ),
    Sabotage(
        "an image part is sent to OpenAI as text",
        ((COMPAT, "                if part.type is ModerationPartType.image\n",
          "                if False\n"),),
    ),
    Sabotage(
        "texts are sent as the generated wrappers, not strings",
        ((COMPAT, '            wire = [getattr(text, "root", text) for text in request.texts or []]\n',
          "            wire = list(request.texts or [])\n"),),
    ),
    Sabotage(
        "the driver alone forwards a remote image",
        ((MODERATE, '        if part.type is ModerationPartType.image and not (part.image or "").startswith("data:"):\n',
          "        if False:\n"),),
        escapes="the gateway refuses a remote image first (A4); the driver's copy is unit-tested",
    ),
    # --- the gateway: the door ------------------------------------------------------
    Sabotage(
        "an unknown field is taken",
        ((DOOR, "    for key in body:\n", "    for key in ():\n"),),
    ),
    Sabotage(
        "a remote image is forwarded",
        ((DOOR, '                budget.admit(url, f"{field}.image_url.url")\n', "                pass\n"),),
    ),
    Sabotage(
        "strings mixed with parts are taken as parts",
        ((DOOR, "    if not all(isinstance(item, dict) for item in raw):\n", "    if False:\n"),),
    ),
    # --- the gateway: routing ----------------------------------------------------------
    Sabotage(
        "a model that moderates is not listed as moderating",
        ((ROUTING, '            + (["moderation"] if any(b.moderates for b in backends) else [])\n', ""),),
    ),
    Sabotage(
        "a moderation walks the slot's tiers, as chat does",
        ((ROUTING,
          "        eligible = [b for b in resolution.first_model() if b.moderates]\n",
          "        tiers = [[b.client for b in t.eligible() if b.moderates] for t in resolution.tiers]\n"
          "        if any(tiers):\n"
          "            return TieredClient(name=resolution.model, tiers=[t for t in tiers if t], hooks=self)\n"
          "        eligible = [b for b in resolution.first_model() if b.moderates]\n"),),
    ),
    Sabotage(
        "model left out takes the first of several",
        ((ROUTE, "    if len(choices) == 1:\n", "    if choices:\n"),),
    ),
    Sabotage(
        "a slot alias counts as another moderation model",
        ((ROUTE, "        if table.serves(m.id)\n        and m.x_eugene_plexus is not None\n",
          "        if m.x_eugene_plexus is not None\n"),),
    ),
    Sabotage(
        "a slot answers under its own name, not the model that served",
        ((ROUTE, '            "model": getattr(client, "served_model", None) or model,\n',
          '            "model": model,\n'),),
    ),
    Sabotage(
        "a moderation row is filed with no door",
        ((ROUTE, '                door="moderation",\n', "                door=None,\n"),),
    ),
    Sabotage(
        "the moderation door is not under client admission",
        ((ADMISSION, '        "/v1/moderations",\n', ""),),
    ),
    # --- the gateway: GET /v1/models/{model} -----------------------------------------
    Sabotage(
        "one model is looked up without the key's limits",
        ((ROUTE, _RETRIEVE_ALLOWED,
          "    listed = (\n        table.as_model_list(\n"
          "            None, local_only=admission.local_only()\n"),),
    ),
    Sabotage(
        "the model lookup is not under client admission",
        ((ADMISSION, '        "/v1/models/{model:path}",\n', ""),),
    ),
    Sabotage(
        "a path template does not take the rest of the path",
        ((GATEWAY / "door_paths.py", '        if template[-1].endswith(":path}"):\n', "        if False:\n"),),
    ),
    Sabotage(
        "one model is serialised differently from the list",
        ((ROUTE, '    return JSONResponse(content=found.model_dump(mode="json"))\n',
          '    return JSONResponse(content=found.model_dump(mode="json", exclude_none=True))\n'),),
    ),
    # --- P6b: the driver ------------------------------------------------------------
    Sabotage(
        "a suffix is sent to llama-server's /v1/completions, which drops it",
        ((COMPAT, "        if completion.suffix is not None:\n", "        if False:\n"),),
    ),
    Sabotage(
        "the suffix is not carried to /infill",
        ((RAW, '        "input_suffix": request.completion.suffix or "",\n', '        "input_suffix": "",\n'),),
    ),
    Sabotage(
        "Ollama is asked without raw, so its template wraps the prompt",
        ((RAW, '        payload["raw"] = True\n', "        pass\n"),),
    ),
    Sabotage(
        "a llama-server that fills in the middle is not said to",
        ((COMPAT, "                self._completion_caps = (True, infill.status_code == 200)\n",
          "                self._completion_caps = (True, False)\n"),),
    ),
    Sabotage(
        "vLLM is not recognised as continuing raw text",
        ((COMPAT, '            if isinstance(body, dict) and isinstance(body.get("version"), str):\n',
          "            if False:\n"),),
    ),
    Sabotage(
        "a hosted endpoint is offered raw completion",
        ((COMPAT, '        if getattr(self, "routing_locality", None) != "local":\n', "        if False:\n"),),
    ),
    Sabotage(
        "Ollama's models are not said to continue raw text",
        ((CATALOGUE, '            surfaces.append("completion")\n', "            pass\n"),),
    ),
    Sabotage(
        "the driver completes with a model that does not continue raw text",
        ((DRIVER / "routes" / "generate.py", "    if completes:\n", "    if True:\n"),),
    ),
    # --- P6b: the gateway -------------------------------------------------------------
    Sabotage(
        "a completion may reach a model that only chats",
        ((ROUTING, "                if takes(b.caps, needs) and (surface is None or surface in b.surfaces)\n",
          "                if takes(b.caps, needs)\n"),),
    ),
    Sabotage(
        "a suffix is not routed as a need for fill-in-the-middle",
        ((ROUTE,
          '        needs = frozenset({"fill_in_middle"}) if completion.suffix is not None else frozenset()\n',
          "        needs = frozenset()\n"),),
    ),
    Sabotage(
        "the prompt is sent as the chat stand-in, not as a completion",
        ((ROUTE, "        generate.completion = completion\n", "        pass\n"),),
    ),
    Sabotage(
        "a request rebuilt with profile defaults loses its prompt",
        ((ROUTE, "                prepared.completion = completion\n", "                pass\n"),),
    ),
    Sabotage(
        "n above 1 is dropped rather than refused",
        ((COMPLETION_DOOR, '    for field in ("n", "best_of"):\n', "    for field in ():\n"),),
    ),
    Sabotage(
        "echo is dropped rather than refused",
        ((COMPLETION_DOOR, "    if raw.get(\"echo\") not in (None, False):\n", "    if False:\n"),),
    ),
    Sabotage(
        "a suffix no model can fill is refused under the wrong field",
        ((ROUTE, '        param="suffix" if missing[0] == "fill_in_middle" else "messages",\n',
          '        param="messages",\n'),),
    ),
    Sabotage(
        "a completion row is filed with no door",
        ((ROUTE, '            backend_ms=response.latencyMs,\n            door="completion",\n        )\n    content:',
          '            backend_ms=response.latencyMs,\n            door=None,\n        )\n    content:'),),
    ),
    Sabotage(
        "a stream's last frame carries no finish reason",
        ((ROUTE,
          '                        "logprobs": None,\n'
          '                        "finish_reason": _completion_finish(response.finishReason),\n'
          '                    }\n                ],\n            )\n        )\n',
          '                        "logprobs": None,\n'
          '                        "finish_reason": None,\n'
          '                    }\n                ],\n            )\n        )\n'),),
    ),
    Sabotage(
        "a stream asked for its usage sends none",
        ((ROUTE, "        if include_usage and usage is not None:\n", "        if False:\n"),),
    ),
    Sabotage(
        "a model that fills in the middle is not listed so",
        ((ROUTING, "                        fill_in_middle=any(takes(b.caps, _FILLS) for b in backends),\n", ""),),
    ),
    Sabotage(
        "the completions door is not under client admission",
        ((ADMISSION, '        "/v1/completions",\n', ""),),
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
