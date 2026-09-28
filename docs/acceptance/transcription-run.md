# P3b: transcription at `/v1/audio/transcriptions` — record

**2026-09-28. Built, run and pinned in both installers** (inference-driver
`f578d1f`, gateway `46167da`). This completes P3. Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§9, calls P3-1 to P3-4. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §3 and
§8.

| Repo | Commit |
|---|---|
| specs (contract) | `aee2335`, `64ee670` |
| inference-driver | `f578d1f` |
| gateway | `b5114a6`, `46167da` |

- **`scripts/p3-audio-acceptance.py` is now P3's one gate** (it was
  `p3-speech-acceptance.py`): 21 fixture checks, in specs CI. `--llama-server
  DIR` adds a real `llama-server` on this machine, and `--live` adds four
  provider checks. **26 of 26 PASS with both.**
- **`scripts/p3-sabotage.py`: 48 of 48 caught across P3a and P3b**, and
  one declared escape: the driver's own 25 MiB check, which the gateway's
  check reaches first and the driver's unit tests cover. Every P3b
  sabotage failed on its own rule, not a neighbour's.
- **Unit suites:** inference-driver 779, gateway 894. Against the previous source, 9 of the
  driver's 10 new route tests fail (the 404 case passes either way), and so
  do all 19 of the gateway's transcription tests, the v6 migration test and
  the speech-unit assertion.

## The done-when: `llama-server` transcribes locally

`llama-server` b11235 with `ggml-org/Qwen3-ASR-0.6B-GGUF` Q8_0 and its
projector, on this machine's CPU, fronted by a single-model driver: the OpenAI
SDK sent the fox through the gateway and got back *"The quick brown fox jumps
over the lazy dog."* in 0.99 s, with the model's `language
English<asr_text>` preamble parsed away. `GET /v1/models` lists it as `chat`
and `transcription`, and a local-only key is served by it.

## What it does

- **OpenAI's multipart form, as the SDK sends it**: `file`, `model`, and
  `language`, `prompt`, `response_format`, `temperature` and
  `timestamp_granularities[]` when set. The audio goes to the driver as
  base64 in JSON, as attachments do, and on to the backend in the same
  multipart form, which OpenRouter and `llama-server` both take (measured).
- **Tiers, as chat** (§5, call #4): a fallback model's transcript is still a
  transcript. Each tier holds only backends that transcribe, so a slot
  `scribe → [chat, whisper, whisper-2]` skips the chat model, and with
  `whisper` rate-limited is answered by `whisper-2` at tier 3.
- **Formats:** `json` (the default) and `verbose_json` are the backend's.
  `text` is rendered by the gateway from `json`, because `llama-server`
  refuses `text` and OpenRouter does too (both measured). `srt` and `vtt` are
  refused. `response_format` is sent to the backend only for `verbose_json`,
  since `json` is everyone's default and `llama-server` refuses anything
  else.
- **Refused with a 400 naming the field and why:** `stream: true`,
  `chunking_strategy`, `include[]`, speaker labels, an unknown field, and
  timestamps without `verbose_json`. A file over 25 MiB is a 413 naming
  `file`.
- **Which backends transcribe:** an account says per model, from its
  listing. A single `llama-server` does when its projector hears, which the
  existing `/props` audio probe already reports, so its surfaces become
  `chat` and `transcription`.
- **Usage in the backend's own unit:** seconds for Whisper, tokens for
  `llama-server`. The gateway answers in OpenAI's two usage shapes,
  `{"type": "duration", "seconds"}` and `{"type": "tokens", ...}`.
- **`/v1/audio/translations` answers a 400** saying no backend here
  translates (P3-4), rather than a 404 that reads as a typo.
- **Metrics schema v7:** a request row carries its door, the characters
  spoken (speech) and the seconds of audio heard (transcription). A v6 store
  migrates in place.
- **Upload limits:** the gateway's body limit for the two doors is 26 MiB, a
  per-path limit beside the shared 16 MiB, and the route checks the file
  against 25 MiB exactly. The driver's `/v1/transcribe` limit is 36 MiB, for
  25 MiB of base64.

## Found on the way

- **An inline enum renamed nine others.** The first contract draft's
  `TranscriptionUsageOut.type` was generated as `Type` and renumbered the
  gateway's existing `Type`…`Type8` to `Type1`…`Type9`, which would have
  broken every reference to them. Found by regenerating before committing a
  consumer, S6's `Source1` trap again. Both P3b enums are named schemas now
  (`64ee670`).
- **`request.form()` consumes the stream without caching it**, and the
  gateway's disconnect watcher reads the body again, so the first route
  answered 500. The route caches the body first; the body limit has already
  buffered it.
- **OpenRouter's `qwen/qwen3-asr-0.6b` hung.** It transcribed the fox in
  0.6 s that morning and timed out after 90 s on every file that afternoon,
  called directly and through the product alike. Whisper took the same
  files, our streaming WAV included, in 1.2-2.3 s, so the live check uses
  Whisper.
- **Our streaming WAV is a valid upload.** Whisper transcribed the kokoro WAV
  whose size fields are `0xFFFFFFFF` as well as one with real sizes.
- **A wrong-door refusal named a fixed door.** Each door passed one, right
  with two surfaces and wrong with five: a speech model sent to chat was
  told to use `/v1/embeddings`. It now names the model's own doors
  (`46167da`), and the gate asserts it.
- **The routing table's `surfaces_for` had no caller** and knew no speech.
  Removed.

## Not done, named

- ~~**Agent, control and library still pin P2's specs.**~~ Re-pinned
  regen-only at P3's end (specs `02330fb`).
- **OpenAI's own API transcribes, live since 2026-09-28 (late)**: through an
  OpenAI account, `whisper-1` heard the ElevenLabs clip word for word and
  timed each word in `verbose_json`, and `gpt-4o-mini-transcribe` heard
  `tts-1`'s.
- **ElevenLabs' speech-to-text** is deferred (P3-1). Its reason, a key
  without `speech_to_text`, is gone since the key was widened.
- **Translation** is deferred (P3-4). Its reason, no OpenAI key, is gone
  too: `whisper-1` is on the account.
- **Streaming transcription** (`stream: true`, SSE deltas) is refused, not
  served. `llama-server` supports it (measured), OpenRouter ignores it.
- **No `ui` screen consumes P3.** The agent's browser proxy forwards raw
  request bytes (up to 32 MiB) and streams raw answers, so both audio doors
  should pass through it, but nothing has sent audio through it.
