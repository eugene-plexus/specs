"""Sabotage pass for p2-media-acceptance.py.

Each sabotage puts back one way P2a could be wrong -- in the driver or the
gateway -- runs the fixture half of the acceptance, and requires it to FAIL.
The acceptance runs the editable installs, so a source edit is what runs.

A sabotage may edit several files at once. Where the gateway and the driver
each enforce the same rule (both check an attachment's bytes, both send a
bare-base64 PDF on as a data URL), removing one copy alone is hidden by the
other, and the pass says which of those it expects to escape and why rather
than calling the escape a weak check. Removing BOTH copies must be caught.

Restores are from byte copies taken before the first edit, never `git
checkout --`, which reverts uncommitted work and once turned a sabotage
run into one that tested nothing. Opens with a baseline assertion that the
gate passes unsabotaged.

    python scripts/p2-sabotage.py <python with all five components> [label filter]
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
ACCEPTANCE = SPECS / "scripts" / "p2-media-acceptance.py"

_AUDIO_BYTES = (
    "    if not matches:\n"
    '        raise ImageRefusal(field, f"audio does not match its declared {fmt} format")\n'
)
_NO_AUDIO_BYTES = (
    "    if False:\n"
    '        raise ImageRefusal(field, f"audio does not match its declared {fmt} format")\n'
)
_GATEWAY_REWRITE = (
    '                if url != part["file"].get("file_data") and typed is not None:\n'
    "                    typed[part_index].file.file_data = url\n"
)
_NO_GATEWAY_REWRITE = (
    "                if False:\n"
    "                    typed[part_index].file.file_data = url\n"
)
_DRIVER_DATA_URL = "    return _PDF_DATA_URL + encoded, len(raw)\n"
_DRIVER_AS_SENT = "    return data, len(raw)\n"


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- the driver: what each model takes -----------------------------------
    Sabotage(
        "the driver reads no audio input from OpenRouter's listing",
        ((DRIVER / "engines" / "_catalogue.py",
          '                    audioInput="audio" in inputs,\n',
          "                    audioInput=False,\n"),),
    ),
    Sabotage(
        "the driver says every listed model reads files",
        ((DRIVER / "engines" / "_catalogue.py",
          '                    fileInput="file" in inputs,\n',
          "                    fileInput=True,\n"),),
    ),
    # --- the driver: its own copy of the rules ---------------------------------
    Sabotage(
        "the driver sends an attachment to a model its listing does not confirm",
        ((DRIVER / "routes" / "generate.py",
          "        if not confirmed:\n            raise HTTPException(\n",
          "        if False:\n            raise HTTPException(\n"),),
    ),
    Sabotage(
        "the driver does not check an audio clip's bytes",
        ((DRIVER / "images.py", _AUDIO_BYTES, _NO_AUDIO_BYTES),),
    ),
    Sabotage(
        "the driver sends a bare-base64 PDF on as it arrived",
        ((DRIVER / "images.py", _DRIVER_DATA_URL, _DRIVER_AS_SENT),),
    ),
    Sabotage(
        "the driver normalises the PDF but never writes it back",
        ((DRIVER / "images.py",
          "def _write_file_data(part: Any, url: str) -> None:\n",
          "def _write_file_data(part: Any, url: str) -> None:\n    return\n"),),
    ),
    # --- the gateway: routing -------------------------------------------------
    Sabotage(
        "the gateway's capability test says every backend takes every attachment",
        ((GATEWAY / "routing.py", "    return not needs or (\n", "    return True or (\n"),),
    ),
    Sabotage(
        "pick() ignores what the request needs",
        ((GATEWAY / "routing.py",
          "            eligible = [b for b in tier.eligible() if takes(b.caps, needs)]\n",
          "            eligible = list(tier.eligible())\n"),),
    ),
    Sabotage(
        "the chat door never works out what the request carries",
        ((GATEWAY / "routes" / "inference.py",
          "    needs = attachment_kinds(body.messages)\n",
          "    needs = frozenset()\n"),),
    ),
    Sabotage(
        "GET /v1/models reports no audio input",
        ((GATEWAY / "routing.py",
          "                        audio_input=any(takes(b.caps, _AUDIO) for b in backends),\n",
          "                        audio_input=False,\n"),),
    ),
    Sabotage(
        "GET /v1/models reports file input from the audio flag",
        ((GATEWAY / "routing.py",
          "                        file_input=any(takes(b.caps, _FILE) for b in backends),\n",
          "                        file_input=any(takes(b.caps, _AUDIO) for b in backends),\n"),),
    ),
    Sabotage(
        "kinds confirmed by different backends are reported as one kind missing",
        ((GATEWAY / "routes" / "inference.py",
          "    if not missing:\n",
          "    if False:\n"),),
    ),
    # --- the gateway: the doors' own checks -------------------------------------
    Sabotage(
        "the gateway does not check an audio clip's bytes",
        ((GATEWAY / "images.py", _AUDIO_BYTES, _NO_AUDIO_BYTES),),
    ),
    Sabotage(
        "the gateway accepts a file_id",
        ((GATEWAY / "images.py",
          '    if file.get("file_id"):\n        raise ImageRefusal(\n',
          '    if False:\n        raise ImageRefusal(\n'),),
    ),
    Sabotage(
        "neither layer checks an audio clip's bytes",
        ((GATEWAY / "images.py", _AUDIO_BYTES, _NO_AUDIO_BYTES),
         (DRIVER / "images.py", _AUDIO_BYTES, _NO_AUDIO_BYTES)),
    ),
    Sabotage(
        "the chat door forwards a bare-base64 PDF as it arrived",
        ((GATEWAY / "images.py", _GATEWAY_REWRITE, _NO_GATEWAY_REWRITE),),
        escapes="the driver sends every PDF on as a data URL itself, and only a driver that "
        "confirms fileInput is ever routed one, so the gateway's rewrite cannot be seen "
        "through any door; its unit test is the check for it",
    ),
    Sabotage(
        "neither layer turns a bare-base64 PDF into a data URL",
        ((GATEWAY / "images.py", _GATEWAY_REWRITE, _NO_GATEWAY_REWRITE),
         (DRIVER / "images.py", _DRIVER_DATA_URL, _DRIVER_AS_SENT)),
    ),
    # --- the Anthropic door ---------------------------------------------------------
    Sabotage(
        "the Anthropic door refuses a base64 PDF document again",
        ((GATEWAY / "anthropic.py",
          '    if kind == "base64" and source.get("media_type") == "application/pdf":\n',
          "    if False:\n"),),
    ),
    Sabotage(
        "a document's title is not its filename",
        ((GATEWAY / "anthropic.py",
          "                    filename=title[:255] if isinstance(title, str) and title else None,\n",
          "                    filename=None,\n"),),
    ),
    Sabotage(
        "a document inside a tool_result is dropped",
        ((GATEWAY / "anthropic.py",
          '        elif kind == "document":\n            document = _document_part(inner, at, budget)\n',
          '        elif False:\n            document = _document_part(inner, at, budget)\n'),),
    ),
    Sabotage(
        "the tool message does not say its document moved",
        ((GATEWAY / "anthropic.py",
          '                    text = f"{text}\\n{note}" if text else note\n',
          "                    pass\n"),),
    ),
    # --- the Responses door -----------------------------------------------------------
    Sabotage(
        "the Responses door sends every clip on as wav",
        ((GATEWAY / "responses.py",
          "input_audio=InputAudio(data=data, format=InputAudioFormat(fmt))",
          'input_audio=InputAudio(data=data, format=InputAudioFormat("wav"))'),),
    ),
    # --- P2b, the driver: audio out ---------------------------------------------------
    Sabotage(
        "the driver reads no audio output from the listing",
        ((DRIVER / "engines" / "_catalogue.py",
          '                    audioOutput="audio" in output,\n',
          "                    audioOutput=False,\n"),),
    ),
    Sabotage(
        "the backend is asked for the caller's format instead of pcm16",
        ((DRIVER / "engines" / "openai_compat_http.py",
          '"format": "pcm16"}',
          '"format": request.audioOutput.format.value}'),),
    ),
    Sabotage(
        "a non-streamed spoken answer is asked for without a stream",
        ((DRIVER / "engines" / "openai_compat_http.py",
          "            return await self._assembled(request)\n",
          "            pass\n"),),
    ),
    Sabotage(
        "a pcm16 stream asked for as wav gets no header",
        ((DRIVER / "audio_out.py",
          "        if fmt is AudioOutputFormat.pcm16 and asked is AudioOutputFormat.wav:\n",
          "        if False:\n"),),
    ),
    Sabotage(
        "the clip is labelled with the format asked, not the one it is",
        ((DRIVER / "audio_out.py",
          "        fmt = self.format or AudioOutputFormat.pcm16\n",
          "        fmt = asked\n"),),
    ),
    Sabotage(
        "a lone frame sync is taken for an MP3",
        ((DRIVER / "audio_out.py",
          "    if length is not None and _mp3_frame_length(raw, length) is not None:\n",
          "    if length is not None:\n"),),
    ),
    Sabotage(
        "the driver's stream never frames an audio fragment",
        ((DRIVER / "routes" / "generate.py",
          '    audio = getattr(chunk, "audio", None)\n    if audio is not None:\n',
          '    audio = getattr(chunk, "audio", None)\n    if False:\n'),),
    ),
    Sabotage(
        "the driver asks a model that does not speak to",
        ((DRIVER / "routes" / "generate.py",
          "    if not confirmed:\n        raise HTTPException(\n",
          "    if False:\n        raise HTTPException(\n"),),
    ),
    Sabotage(
        "the driver takes any audio format",
        ((DRIVER / "routes" / "generate.py",
          "    if asked.format not in formats:\n",
          "    if False:\n"),),
    ),
    # --- P2b, the gateway: audio out ----------------------------------------------------
    Sabotage(
        "a spoken request is routed like a text one",
        ((GATEWAY / "routes" / "inference.py",
          '        needs = needs | {"audio_output"}\n',
          "        pass\n"),),
    ),
    Sabotage(
        "GET /v1/models reports no audio output",
        ((GATEWAY / "routing.py",
          "                        audio_output=any(takes(b.caps, _SPEAKS) for b in backends),\n",
          "                        audio_output=False,\n"),),
    ),
    Sabotage(
        "the gateway takes any non-streamed audio format",
        ((GATEWAY / "chat_contract.py",
          '    if not parsed.stream and fmt not in ("wav", "pcm16"):\n',
          "    if False:\n"),),
    ),
    Sabotage(
        "the gateway takes any streamed audio format",
        ((GATEWAY / "chat_contract.py",
          '    if parsed.stream and fmt != "pcm16":\n',
          "    if False:\n"),),
    ),
    Sabotage(
        "audio without modalities is ignored rather than refused",
        ((GATEWAY / "chat_contract.py",
          "    if parsed.audio is not None and not asked:\n",
          "    if False:\n"),),
    ),
    Sabotage(
        "an assistant's audio {id} is not told why",
        ((GATEWAY / "chat_contract.py",
          '        if isinstance(message, dict) and "audio" in message:\n',
          "        if False:\n"),),
    ),
    Sabotage(
        "the driver is never asked for audio",
        ((GATEWAY / "routes" / "inference.py",
          "        if body.audio is not None and chat_contract.wants_audio(body)\n",
          "        if False\n"),),
    ),
    Sabotage(
        "a non-streamed answer drops its audio",
        ((GATEWAY / "routes" / "inference.py",
          "                    audio=_to_openai_audio(response),\n",
          "                    audio=None,\n"),),
    ),
    Sabotage(
        "a streamed audio fragment is not forwarded as delta.audio",
        ((GATEWAY / "routes" / "inference.py",
          "                if event.audio:\n",
          "                if False:\n"),),
    ),
    Sabotage(
        "the gateway reads no audio off the driver's stream",
        ((GATEWAY / "driver_client.py",
          "                if isinstance(audio, dict) and audio:\n",
          "                if False:\n"),),
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
