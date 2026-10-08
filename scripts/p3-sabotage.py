"""Sabotage pass for p3-audio-acceptance.py.

Each sabotage puts back one way P3 could be wrong -- in the driver or the
gateway -- runs the fixture half of the acceptance, and requires it to FAIL.
The acceptance runs the editable installs, so a source edit is what runs.

Where the gateway and the driver each enforce the same rule (both refuse a
format the model cannot make), removing one copy alone is hidden by the
other; the pass says which it expects to escape and why, and removing BOTH
must be caught.

Restores are from byte copies taken before the first edit, never `git
checkout --`. Opens with a baseline assertion that the gate passes
unsabotaged, and refuses to start if any anchor is not found exactly once.

    python scripts/p3-sabotage.py <python with all five components> [label filter]

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
ACCEPTANCE = SPECS / "scripts" / "p3-audio-acceptance.py"
EL = DRIVER / "engines" / "elevenlabs_http.py"
COMPAT = DRIVER / "engines" / "openai_compat_http.py"
CATALOGUE = DRIVER / "engines" / "_catalogue.py"
SPEAK = DRIVER / "routes" / "speak.py"
TRANSCRIPTION = DRIVER / "transcription.py"
ROUTING = GATEWAY / "routing.py"
ROUTE = GATEWAY / "routes" / "inference.py"

_GATEWAY_FORMATS = "    if offered and fmt not in offered:\n"
_ELIGIBLE = (
    "            eligible = [\n"
    "                b for b in tier.eligible() if (b.translates if translate else b.transcribes)\n"
    "            ]\n"
)
TRANSCRIBE = DRIVER / "routes" / "transcribe.py"
CONTRACT = GATEWAY / "chat_contract.py"
_EL_FORMATS = "        refuse_format(asked, ELEVENLABS_FORMATS)\n"


@dataclass(frozen=True)
class Sabotage:
    label: str
    edits: tuple[tuple[Path, str, str], ...]
    #: Why it is expected to ESCAPE, when it is: another layer does the job.
    escapes: str | None = None


SABOTAGES: list[Sabotage] = [
    # --- the driver: what each account offers ------------------------------
    Sabotage(
        "ElevenLabs' speech-to-speech model is offered for text to speech",
        ((EL, '            if entry.get("can_do_text_to_speech") is False:\n',
          "            if False:\n"),),
    ),
    Sabotage(
        "ElevenLabs' voices are never read",
        ((EL, "        voices = await self._voices()\n", "        voices = None\n"),),
    ),
    Sabotage(
        "a key that cannot read voices is reported as having none",
        ((EL, "                    upstream_words(response),\n                )\n            return None\n",
          "                    upstream_words(response),\n                )\n            return []\n"),),
    ),
    Sabotage(
        "the driver sends ElevenLabs no key",
        ((EL, '        return {"xi-api-key": self._api_key} if self._api_key else {}\n',
          "        return {}\n"),),
    ),
    Sabotage(
        "OpenRouter's voices are not read from its listing",
        ((CATALOGUE, '        voices = entry.get("supported_voices")\n', "        voices = None\n"),),
    ),
    Sabotage(
        "OpenRouter's speech models are not sorted into speech",
        ((CATALOGUE, '        ("speech", "speech"),\n', ""),),
    ),
    Sabotage(
        "an OpenRouter speech model lists no formats",
        ((CATALOGUE,
          '                    speechFormats=list(OPENROUTER_FORMATS) if "speech" in surfaces else None,\n',
          "                    speechFormats=None,\n"),),
    ),
    # --- the driver: how each backend is asked -----------------------------------
    Sabotage(
        "ElevenLabs is asked for its Pro-tier wav instead of pcm",
        ((EL, '    SpeechFormat.wav: "pcm_24000",\n}', '    SpeechFormat.wav: "wav_44100",\n}'),),
    ),
    Sabotage(
        "ElevenLabs' pcm is sent as wav with no header",
        ((EL, "                header_sent = asked is not SpeechFormat.wav\n",
          "                header_sent = True\n"),),
    ),
    Sabotage(
        "instructions to ElevenLabs are dropped silently",
        ((EL, "        if request.instructions:\n            raise SpeechRefusal(\n",
          "        if False:\n            raise SpeechRefusal(\n"),),
    ),
    Sabotage(
        "speed is not carried to ElevenLabs",
        ((EL, '            body["voice_settings"] = {"speed": request.speed}\n', "            pass\n"),),
    ),
    Sabotage(
        "the driver uses ElevenLabs' route that answers once the audio is made",
        ((EL, "        path = f\"/v1/text-to-speech/{quote(request.voice, safe='')}/stream\"\n",
          "        path = f\"/v1/text-to-speech/{quote(request.voice, safe='')}\"\n"),),
    ),
    Sabotage(
        "OpenRouter is asked for wav, which it does not make",
        ((COMPAT, '        made_here = asked is SpeechFormat.wav and self._dialect.catalogue == "openrouter"\n',
          "        made_here = False\n"),),
    ),
    Sabotage(
        "the format is left to OpenRouter's default",
        ((COMPAT, '            "response_format": (SpeechFormat.pcm if made_here else asked).value,\n', ""),),
    ),
    Sabotage(
        "the driver reads OpenRouter's whole answer before sending any",
        ((COMPAT, "                header_sent = not made_here\n                async for chunk in response.aiter_raw():\n",
          "                header_sent = not made_here\n                for chunk in [await response.aread()]:\n"),),
    ),
    Sabotage(
        "the driver serves speech as octet-stream",
        ((SPEAK, "    return StreamingResponse(audio(), media_type=MEDIA_TYPES[fmt])\n",
          '    return StreamingResponse(audio(), media_type="application/octet-stream")\n'),),
    ),
    Sabotage(
        "a refused speech request is the driver's 500, not the caller's 400",
        ((SPEAK, '"speech-refused"\n        ) from None', '"speech-refused", code=500\n        ) from None'),),
    ),
    Sabotage(
        "the driver does not refuse a format ElevenLabs cannot make",
        ((EL, _EL_FORMATS, ""),),
    ),
    # --- the gateway ----------------------------------------------------------
    Sabotage(
        "speech walks a slot's tiers, as chat does",
        # Since gateway ea12c1a speech chooses from `Resolution.first_model()`.
        ((ROUTING,
          "        eligible = [b for b in resolution.first_model() if b.speaks]\n",
          "        tiers = [[b.client for b in t.eligible() if b.speaks]\n"
          "                 for t in resolution.tiers]\n"
          "        if any(tiers):\n"
          "            return TieredClient(name=resolution.model, tiers=[t for t in tiers if t], hooks=self)\n"
          "        eligible = [b for b in resolution.first_model() if b.speaks]\n"),),
    ),
    Sabotage(
        "a slot alias finds no speaker, because no backend is named after it",
        # The rule lives in `Resolution.first_model()` since gateway ea12c1a.
        ((ROUTING, "if b.public_id == first.target]\n", "if b.public_id == self.model]\n"),),
    ),
    Sabotage(
        "a slot is listed with the voices of every tier",
        ((ROUTING,
          "        for backend in resolution.tiers[0].backends if resolution.tiers else []:\n",
          "        for backend in resolution.backends():\n"),),
    ),
    Sabotage(
        "the gateway reads the driver's whole answer before sending any",
        ((GATEWAY / "driver_client.py",
          '            yield response.headers.get("content-type", "application/octet-stream")\n'
          "            async for chunk in response.aiter_raw():\n",
          '            yield response.headers.get("content-type", "application/octet-stream")\n'
          "            for chunk in [await response.aread()]:\n"),),
    ),
    Sabotage(
        "a served clip is left to the middleware's fallback row",
        ((ROUTE,
          "                await events.aclose()\n                _record(\n                    rec,\n",
          "                await events.aclose()\n                (lambda *a, **k: None)(\n                    rec,\n"),),
    ),
    Sabotage(
        "the speech door is not under client admission",
        ((GATEWAY / "admission.py", '        "/v1/audio/speech",\n        "/v1/audio/transcriptions",\n',
          '        "/v1/audio/transcriptions",\n'),),
    ),
    Sabotage(
        "stream_format sse is accepted",
        ((GATEWAY / "chat_contract.py",
          '    if parsed.stream_format is not None and parsed.stream_format.value == "sse":\n',
          "    if False:\n"),),
    ),
    Sabotage(
        "the gateway alone does not refuse a format a model cannot make",
        ((ROUTE, _GATEWAY_FORMATS, "    if False:\n"),),
    ),
    Sabotage(
        "speech to a chat model is not told the right door",
        ((ROUTE, '    if surfaces and "speech" not in surfaces:\n', "    if False:\n"),),
    ),
    # --- P3b: transcription, in the driver ------------------------------------
    Sabotage(
        "the driver always sends a response_format",
        ((COMPAT, '        if request.verbose:\n            fields["response_format"] = "verbose_json"\n',
          '        fields["response_format"] = "verbose_json" if request.verbose else "json"\n'),),
    ),
    Sabotage(
        "the driver drops the timestamp granularities",
        ((COMPAT,
          '            fields["timestamp_granularities[]"] = [g.value for g in request.timestampGranularities]\n',
          "            pass\n"),),
    ),
    Sabotage(
        "the driver drops the uploaded file's name",
        ((COMPAT, "            request.audio.filename,\n", '            "audio",\n'),),
    ),
    Sabotage(
        "Qwen3-ASR's preamble is left in the text",
        ((TRANSCRIPTION, '    language, text = split_preamble(body["text"])\n',
          '    language, text = None, body["text"]\n'),),
    ),
    Sabotage(
        "a backend's usage is not read",
        ((TRANSCRIPTION, "        usage=usage_from(body),\n", "        usage=None,\n"),),
    ),
    Sabotage(
        "a llama-server that hears is not said to transcribe",
        ((DRIVER / "routes" / "info.py", '            surfaces.append("transcription")\n', "            pass\n"),),
    ),
    Sabotage(
        "the driver transcribes with a model that does not",
        ((DRIVER / "routes" / "transcribe.py",
          "    if not body.translate and not await transcribes(engine, surfaces):\n",
          "    if False:\n"),),
    ),
    Sabotage(
        "the driver takes audio over 25 MiB",
        ((DRIVER / "routes" / "transcribe.py", "    if len(audio) > MAX_AUDIO_BYTES:\n", "    if False:\n"),),
        escapes="the gateway refuses the file first; the driver's copy is unit-tested (test_transcribe.py)",
    ),
    # --- P3b: transcription, in the gateway -------------------------------------
    Sabotage(
        "text is sent as JSON",
        ((ROUTE, "    if fmt == \"text\":\n        return PlainTextResponse(result.text, headers=headers)\n",
          "    if fmt == \"text\":\n        return JSONResponse(content={\"text\": result.text}, headers=headers)\n"),),
    ),
    Sabotage(
        "a transcription is handed to a model that only chats",
        ((ROUTING, _ELIGIBLE, "            eligible = list(tier.eligible())\n"),),
    ),
    Sabotage(
        "transcription keeps to the slot's first model, as speech does",
        ((ROUTING, "        for tier in resolution.tiers:\n" + _ELIGIBLE,
          "        for tier in resolution.tiers[:1]:\n" + _ELIGIBLE),),
    ),
    Sabotage(
        "srt is refused only as an unknown value",
        ((GATEWAY / "chat_contract.py", '    if fmt in ("srt", "vtt"):\n', "    if False:\n"),),
    ),
    Sabotage(
        "stream: true is accepted",
        ((GATEWAY / "chat_contract.py", '    if stream is not None and stream.lower() not in ("false", "0"):\n',
          "    if False:\n"),),
    ),
    Sabotage(
        "chunking_strategy is refused only as an unknown field",
        ((GATEWAY / "chat_contract.py",
          '    "chunking_strategy": "is not carried: the backend decides how to split the audio",\n', ""),),
    ),
    Sabotage(
        "timestamps are taken without verbose_json",
        ((GATEWAY / "chat_contract.py", '    if granularities and fmt != "verbose_json":\n', "    if False:\n"),),
    ),
    Sabotage(
        "the gateway takes a file over 25 MiB",
        ((GATEWAY / "chat_contract.py", "    if len(audio) > MAX_UPLOAD_BYTES:\n", "    if False:\n"),),
    ),
    Sabotage(
        "the translation door is not there",
        ((ROUTE, '@router.post("/v1/audio/translations", dependencies=_auth)\n',
          '@router.post("/v1/audio/translations-gone", dependencies=_auth)\n'),),
    ),
    Sabotage(
        "the transcription door is not under client admission",
        ((GATEWAY / "admission.py", '        "/v1/audio/transcriptions",\n        "/v1/audio/translations",\n',
          '        "/v1/audio/translations",\n'),),
    ),
    Sabotage(
        "a transcription row does not count its seconds",
        ((ROUTE, "                door=surface,\n                audio_seconds=seconds,\n",
          "                door=surface,\n                audio_seconds=None,\n"),),
    ),
    Sabotage(
        "a speech row does not count its characters",
        ((ROUTE, "                    characters=len(body.input),\n", "                    characters=None,\n"),),
    ),
    Sabotage(
        "a wrong door names one fixed door, not the model's own",
        ((ROUTE, "Send this request to {' or '.join(doors) or instead} instead. ",
          "Send this request to {instead} instead. "),),
    ),
    # --- P3-1: ElevenLabs transcribes ---------------------------------------------
    Sabotage(
        "ElevenLabs' speech-to-text models are never listed",
        ((EL, "            heard = await self._transcription_models()\n", "            heard = []\n"),),
    ),
    Sabotage(
        "scribe models are offered to a key that may not transcribe",
        ((EL, "        if not _refused_as_empty(allowed):\n", "        if False:\n"),),
    ),
    Sabotage(
        "ElevenLabs is left to tag audio events",
        ((EL, '            "tag_audio_events": "false",\n', ""),),
    ),
    Sabotage(
        "a prompt is sent to ElevenLabs, which would ignore it",
        ((EL, "        if request.prompt:\n", "        if False:\n"),),
    ),
    Sabotage(
        "segment timestamps are asked of ElevenLabs, which makes none",
        ((EL, "        if TimestampGranularity.segment in granularities:\n", "        if False:\n"),),
    ),
    Sabotage(
        "ElevenLabs' spacing and audio events are returned as words",
        ((EL, '                and w.get("type") == "word"\n', ""),),
    ),
    Sabotage(
        "ElevenLabs' audio seconds are not the usage",
        ((EL, "            usage=TranscriptionUsage(seconds=seconds) if seconds is not None else None,\n",
          "            usage=None,\n"),),
    ),
    # --- P3-4: translation, in the driver ------------------------------------------
    Sabotage(
        "OpenAI's whisper is not said to translate",
        ((COMPAT, '        return ["transcription", "translation"]\n', '        return ["transcription"]\n'),),
    ),
    Sabotage(
        "a translation is asked of the transcription door",
        ((COMPAT, '                f"/v1/audio/{what}s",\n', '                "/v1/audio/transcriptions",\n'),),
    ),
    Sabotage(
        "the driver translates with a model that does not",
        ((TRANSCRIBE, "    if body.translate and not await transcribes(engine, surfaces, translate=True):\n",
          "    if False:\n"),),
    ),
    Sabotage(
        "the driver alone lets a language through on a translation",
        ((TRANSCRIBE, "    if body.translate and (body.language or body.timestampGranularities):\n",
          "    if False:\n"),),
        escapes="the gateway's translation form refuses a language and timestamps first",
    ),
    Sabotage(
        "neither layer stops a language on a translation",
        ((TRANSCRIBE, "    if body.translate and (body.language or body.timestampGranularities):\n",
          "    if False:\n"),
         (CONTRACT, '    "language": "is not taken by a translation: the text is always English",\n', ""),
         (CONTRACT, '_TRANSLATION_CARRIED = {"file", "model", "prompt", "response_format", "temperature"}\n',
          '_TRANSLATION_CARRIED = {"file", "model", "prompt", "response_format", "temperature", "language"}\n')),
    ),
    # --- P3-4: translation, in the gateway -------------------------------------------
    Sabotage(
        "a model that translates is not listed as translating",
        ((ROUTING, '            + (["translation"] if any(b.translates for b in backends) else [])\n', ""),),
    ),
    Sabotage(
        "a translation is handed to a model that only transcribes",
        ((ROUTING, "(b.translates if translate else b.transcribes)", "b.transcribes"),),
    ),
    Sabotage(
        "a transcriber at the translation door is not sent to the transcription door",
        ((ROUTE, "    if surfaces and surface not in surfaces:\n        return _wrong_surface(\n"
                 "            ask.model, surfaces, wanted=surface,",
          '    if surfaces and "transcription" not in surfaces:\n        return _wrong_surface(\n'
          "            ask.model, surfaces, wanted=surface,"),),
    ),
    Sabotage(
        "the driver is not told to translate",
        ((ROUTE, "                        translate=translate,\n", ""),),
    ),
    Sabotage(
        "a verbose translation says task transcribe",
        ((ROUTE, '            "task": "translate" if translate else "transcribe",\n',
          '            "task": "transcribe",\n'),),
    ),
    Sabotage(
        "a language on a translation is refused only as an unknown field",
        ((CONTRACT, '    "language": "is not taken by a translation: the text is always English",\n', ""),),
    ),
    Sabotage(
        "a translation row is filed as a transcription",
        ((ROUTE, "                door=surface,\n", '                door="transcription",\n'),),
    ),
    Sabotage(
        "the translation door is not under client admission",
        ((GATEWAY / "admission.py", '        "/v1/audio/translations",\n', ""),),
    ),
    Sabotage(
        "the form is parsed without caching the body first",
        ((ROUTE, "        await request.body()\n        form = await request.form(max_files=1, max_fields=32)\n",
          "        form = await request.form(max_files=1, max_fields=32)\n"),),
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
