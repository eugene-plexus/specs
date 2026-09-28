"""Sabotage pass for p4-images-acceptance.py.

Each sabotage puts back one way P4 could be wrong -- in the driver or the
gateway -- runs the fixture half of the acceptance, and requires it to FAIL.
The acceptance runs the editable installs, so a source edit is what runs.

Where the gateway and the driver each enforce the same rule (a mask only
where it is honoured, a stream only from a model that streams), removing the
driver's copy alone is hidden by the gateway's; the pass says it expects that
to escape and why, and removing BOTH must be caught.

Restores are from byte copies taken before the first edit, never `git
checkout --`. Opens with a baseline assertion that the gate passes
unsabotaged, and refuses to start if any anchor is not found exactly once.

    python scripts/p4-sabotage.py <python with all five components> [label filter]

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
ACCEPTANCE = SPECS / "scripts" / "p4-images-acceptance.py"
COMPAT = DRIVER / "engines" / "openai_compat_http.py"
CATALOGUE = DRIVER / "engines" / "_catalogue.py"
IMAGES_OUT = DRIVER / "images_out.py"
DOORS = GATEWAY / "image_doors.py"
ROUTING = GATEWAY / "routing.py"
ROUTE = GATEWAY / "routes" / "inference.py"

_GATEWAY_MASK = "    if ask.mask is not None and not c.mask:\n"
_DRIVER_MASK = "        if mask is not None and caps is not None and not caps.mask:\n"
_GATEWAY_STREAM = "    if ask.stream and not c.streaming:\n"
_DRIVER_STREAM = "        if caps is not None and not caps.streaming:\n"


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- the driver: what each account offers ----------------------------
    Sabotage(
        "OpenRouter's images listing is never read",
        ((COMPAT, '            models = with_openrouter_images(models, await read("/v1/images/models"))\n',
          ""),),
    ),
    Sabotage(
        "an image+text model is not given the image surface",
        ((CATALOGUE, '            surfaces.append("image")\n', '            surfaces.append("image") if "chat" not in surfaces else None\n'),),
    ),
    Sabotage(
        "an unlisted quality is reported as the backend's to check, not as not taken",
        ((IMAGES_OUT, '        qualities=_enum(params, "quality") or [],\n',
          '        qualities=_enum(params, "quality"),\n'),),
    ),
    Sabotage(
        "an unlisted output_format is reported as not taken, not carried",
        ((IMAGES_OUT, '        outputFormats=_enum(params, "output_format"),\n',
          '        outputFormats=_enum(params, "output_format") or [],\n'),),
    ),
    Sabotage(
        "every OpenRouter image model is said to stream",
        ((IMAGES_OUT, '        streaming=entry.get("supports_streaming") is True,\n',
          "        streaming=True,\n"),),
    ),
    # --- the driver: how each backend is asked ----------------------------
    Sabotage(
        "OpenRouter is sent input_references as the strings its guide shows",
        ((COMPAT,
          '                    {\n                        "type": "image_url",\n'
          '                        "image_url": {"url": f"data:{ref.mediaType};base64,{ref.data}"},\n'
          "                    }\n",
          '                    f"data:{ref.mediaType};base64,{ref.data}"\n'),),
    ),
    Sabotage(
        "an edit on OpenAI's API is sent as a generation",
        ((COMPAT, '        if self._catalogue_source == "openrouter" or not request.references:\n',
          "        if True:\n"),),
    ),
    Sabotage(
        "dall-e is not asked for b64_json",
        ((COMPAT, '        dall_e = target.upstream.lower().startswith("dall-e-")\n', "        dall_e = False\n"),),
    ),
    Sabotage(
        "a GPT image model is sent response_format, which it refuses",
        ((COMPAT, '        dall_e = target.upstream.lower().startswith("dall-e-")\n', "        dall_e = True\n"),),
    ),
    Sabotage(
        "partial_images is not carried on a stream",
        ((COMPAT, '            settings.append(("partial_images", request.partialImages))\n', ""),),
    ),
    Sabotage(
        "partial renders are dropped from the stream",
        ((COMPAT, '                        if kind == "partial":\n', '                        if kind == "never":\n'),),
    ),
    Sabotage(
        "an answer's media type is assumed, not read from its bytes",
        ((IMAGES_OUT, "        mediaType=media,\n", '        mediaType="image/png",\n'),),
    ),
    Sabotage(
        "OpenRouter's chat-style usage is not read",
        ((IMAGES_OUT, '        inputTokens=whole("input_tokens", "prompt_tokens"),\n',
          '        inputTokens=whole("input_tokens"),\n'),),
    ),
    Sabotage(
        "the driver alone lets a mask through to a backend that ignores it",
        ((COMPAT, _DRIVER_MASK, "        if False:\n"),),
        escapes="the gateway routes a mask only to a model whose listing honours one",
    ),
    Sabotage(
        "the driver alone lets a stream through to a model that cannot stream",
        ((COMPAT, _DRIVER_STREAM, "        if False:\n"),),
        escapes="the gateway routes a stream only to a model that streams",
    ),
    # --- the gateway: reading the request ---------------------------------
    Sabotage(
        "a URL input is taken as if it were inline",
        ((DOORS, '    if not url.startswith("data:"):\n', "    if False:\n"),),
    ),
    Sabotage(
        "a file_id is not refused as naming a store",
        ((DOORS, "    if ref.file_id is not None:\n", "    if False:\n"),),
    ),
    Sabotage(
        "an upload's type is trusted rather than read from its bytes",
        ((DOORS, "    media = sniff(raw)\n", '    media = "image/png"\n'),),
    ),
    Sabotage(
        "the SDK's image[] parts are not read",
        ((DOORS, '    files = [*form.getlist("image"), *form.getlist("image[]")]\n',
          '    files = [*form.getlist("image")]\n'),),
    ),
    # --- the gateway: routing ----------------------------------------------
    Sabotage(
        "the gateway alone lets a mask through",
        ((DOORS, _GATEWAY_MASK, "    if False:\n"),),
    ),
    Sabotage(
        "neither layer stops a mask reaching a backend that ignores it",
        ((DOORS, _GATEWAY_MASK, "    if False:\n"), (COMPAT, _DRIVER_MASK, "        if False:\n")),
    ),
    Sabotage(
        "the gateway alone lets a stream through to a model that cannot",
        ((DOORS, _GATEWAY_STREAM, "    if False:\n"),),
    ),
    Sabotage(
        "neither layer stops a stream to a model that cannot",
        ((DOORS, _GATEWAY_STREAM, "    if False:\n"), (COMPAT, _DRIVER_STREAM, "        if False:\n")),
    ),
    Sabotage(
        "an edit-only model is offered generations",
        ((DOORS, "    if refs < (c.minReferences or 0):\n", "    if False:\n"),),
    ),
    Sabotage(
        "a listed setting is not checked against the model's values",
        ((DOORS, '        if value is None or value == "auto" or allowed is None or value in allowed:\n',
          "        if True:\n"),),
    ),
    Sabotage(
        "the tiers are not filtered by what each model takes",
        ((ROUTING, "                if b.makes_images and rules_out(b.image_caps, ask) is None\n",
          "                if b.makes_images\n"),),
    ),
    Sabotage(
        "a slot where nothing could take the request is not refused naming the setting",
        ((ROUTING, "            ruled = rules_out(backend.image_caps, ask)\n",
          "            ruled = None\n"),),
    ),
    # --- the gateway: answering ----------------------------------------------
    Sabotage(
        "a backend's created 0 is passed on",
        ((DOORS, '        "created": result.created or int(time.time()),\n', '        "created": result.created or 0,\n'),),
    ),
    Sabotage(
        "a stream event lacks a field OpenAI's schema requires",
        ((DOORS, '        "size": ask.size or "auto",\n', ""),),
    ),
    Sabotage(
        "the streamed route stops reading at the final event",
        ((ROUTE,
          "                                if i == last\n                                else None,\n"
          "                            )\n                    # Read on past",
          "                                if i == last\n                                else None,\n"
          "                            )\n                        break\n                    # Read on past"),),
    ),
    Sabotage(
        "an image row does not count its images",
        ((ROUTE, "        images=len(result.images) if result else None,\n", "        images=None,\n"),),
    ),
    Sabotage(
        "the generations door is not under client admission",
        ((GATEWAY / "admission.py", '        "/v1/images/generations",\n', ""),),
    ),
    Sabotage(
        "variations answer a 404 that reads as a typo",
        ((ROUTE,
          '    return _error(\n        code=400,\n        message=(\n'
          '            "No backend here makes image variations',
          '    return _error(\n        code=404,\n        message=(\n'
          '            "No backend here makes image variations'),),
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
