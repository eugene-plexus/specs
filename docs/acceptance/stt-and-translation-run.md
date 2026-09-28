# P3-1 and P3-4: ElevenLabs transcribes, and `/v1/audio/translations` — record

**2026-09-28 (late). Built, run and pinned in both installers**
(inference-driver `5172b59`, gateway `0987cce`). Both were deferred in
P3 for want of a key ([design](../design/openai-inference-compatibility.md)
§9). Troy widened the ElevenLabs key and added an OpenAI key, then took both
the same evening. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §11.

| Repo | Commit |
|---|---|
| specs (contract) | `da19213` |
| inference-driver | `5172b59` |
| gateway | `0987cce` |

- **`scripts/p3-audio-acceptance.py`**, P3's one gate, grew from 21 to 27
  fixture checks (in specs CI). With `--live --llama-server`: **35 of 35 PASS**.
- **`scripts/p3-sabotage.py`: 67 of 67 caught across P3, with two declared
  escapes**: the driver's own 25 MiB check and its refusal of a language on a
  translation, each reached first by the gateway (removing both copies of the
  second is caught).
- **Unit suites:** inference-driver 828 (12 new), gateway 957 (10 new, one
  replaced: it asserted the old refusal).
- **Every acceptance script specs CI runs passed locally before this pin**
  (15 scripts).

## The done-when

**ElevenLabs transcribes through `/v1/audio/transcriptions` from the OpenAI
SDK unchanged.** Live, `scribe_v2` heard ElevenLabs' own `eleven_flash_v2_5`
clip as *"The quick brown fox jumps over the lazy dog near the riverbank"*,
timed 12 words in OpenAI's `{word, start, end}` shape, and reported 3.58 s as
the usage.

**The OpenAI SDK's `client.audio.translations` translates.** Live, `tts-1`
spoke *"Le renard brun rapide saute par-dessus le chien paresseux."* and
`whisper-1` translated it through the gateway as *"The fast brown fox jumps
over the lazy dog."*, in `json` and `verbose_json`. The same file sent to
`/v1/audio/transcriptions` came back French, so the door translated, not the
model.

## What it does

- **ElevenLabs' scribe models are listed from its own refusal.** Its
  `/v1/models` lists text-to-speech only. What names `scribe_v1`,
  `scribe_v1_experimental`, `scribe_v2` and `scribe_v2_medical` is its 400 for
  a model id it does not know: free, given before any audio, and given even to
  a wrong key. The engine sends one such probe per catalogue read.
- **Offered only to a key that may use them**, as P3-2 offers speech models
  only to a key that may list them: an empty file is refused as empty when the
  key has `speech_to_text` and 401 when it does not. A key without it keeps
  its speech models and offers no scribe, and the driver log says why, once.
  **A failure here never costs the speech models.**
- **ElevenLabs in OpenAI's words.** `tag_audio_events=false`, since its
  default puts *(laughter)* in the text. `timestamps_granularity` is `word`
  when word timestamps are asked and `none` otherwise. `language` becomes
  `language_code`, `temperature` is carried, and the key rides in
  `xi-api-key`. Its words (without the `spacing` and `audio_event` entries)
  become OpenAI's words, `audio_duration_secs` the usage seconds and, for
  `verbose_json`, the duration. Its language is named as it names it (`eng`).
- **Refused before any audio leaves:** a `prompt`, which ElevenLabs has no
  field for and would ignore (measured: a 200), and `segment` timestamps,
  which it does not make.
- **Translation is the transcription path with `translate` set.** The driver
  asks the backend's `/v1/audio/translations` in the same multipart form,
  minus `language` and timestamps. The gateway door takes the SDK's five
  fields and refuses `language` ("always English"), `timestamp_granularities[]`
  and `stream`, naming each.
- **A new `translation` surface**, which an OpenAI account's `whisper-*` models
  carry beside `transcription`. Nothing else translates: OpenAI's
  `gpt-4o-*-transcribe`, OpenRouter and `llama-server` all answer the door 404
  (measured). A transcriber sent to the translation door is told to use
  `/v1/audio/transcriptions`.
- **Tiers hold only translators.** A model that only transcribes would answer
  in the language spoken, with a 200, so `english -> [whisper-large,
  whisper-1]` translates at tier 2 and never asks the first.
- **Metrics:** a translation's row says `door: translation`.

## Found on the way

- **ElevenLabs ignores an unknown field**, so a prompt sent to it would have
  been dropped with a 200. That is why it is refused rather than passed.
- **OpenAI answers `/v1/audio/translations` 404 "Invalid URL" for its gpt-4o
  transcribe models**: the model, not the account, decides whether the door
  exists.
- **The P3 sabotage pass had two dead anchors** since gateway `ea12c1a` moved
  the slot rule into `Resolution.first_model()`. The pass refuses to start on
  one, so it had not run since. Both sabotages now target the new code.

## Not done, named

- **OpenRouter's speech-to-text models do not translate**, and nothing here
  translates locally. A local Whisper server behind `openai_compat_custom`
  would be told it does not translate, since a single-model driver has no
  listing to say so.
- **ElevenLabs' `keyterms`, diarization and `character` timestamps** are not
  reachable from OpenAI's form, which has no field for them.
- **No `ui` screen consumes P3.**
