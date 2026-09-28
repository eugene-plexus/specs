# P3a: speech at `/v1/audio/speech` — record

**2026-09-28. Built, run and pinned in both installers** (inference-driver
`13f2664`, gateway `5b82a68`). Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§9, calls P3-1 to P3-4. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §8.

| Repo | Commit |
|---|---|
| specs (contract) | `171b16c`, `849c348` |
| inference-driver | `ad039d8`, `13f2664` |
| gateway | `afff7f7`, `829ca38`, `e12e14a`, `8dab0ea`, `5b82a68` |

- **`scripts/p3-audio-acceptance.py`: 15 checks with fixtures, 18 with
  `--live`, all PASS.** Five processes plus four drivers, signed and enrolled,
  as P2's run is. The requests the done-when names are made by **the OpenAI
  Python SDK 3.20.0, unchanged**, from its own interpreter.
- **`scripts/p3-sabotage.py`: 27 of 27 caught**, with no declared escape.
  The full pass ran once. The five sabotages whose source then moved (the
  two format rules and the three routing ones) were re-run after the fixes
  below, and the metrics one was added with its fix. Each was caught for its
  own reason.
- **Unit suites:** inference-driver 753, gateway 872.
- **The specs CI acceptance set** (13 steps, this one among them) passes
  locally against the pinned heads, with the gateway at `8dab0ea`. This
  step re-ran at `5b82a68`, whose only change is the speech route's
  metrics row. ruff, format and mypy
  are clean on both.

## The done-when, part by part

- **ElevenLabs speaks through `/v1/audio/speech` from the OpenAI SDK
  unchanged:** proven against a fixture playing ElevenLabs' API as measured
  (the voice in the path, `output_format` in the query, `xi-api-key`, its
  error bodies word for word). **And live, since 2026-09-28 (late)**, once
  Troy widened the key: its 11 models are read (the 2 speech-to-speech ones
  not offered) with 22 voices, and `eleven_flash_v2_5` spoke through the
  unmodified SDK, a WAV made from its pcm and an mp3 streamed from 0.19 s,
  which OpenAI's `whisper-1` then transcribed word for word. No code changed:
  the check was added to `--live`, as this record said it would be.
- **Nothing buffers, measured by clock.** The fixture sends six chunks 0.4 s
  apart. Through the driver and the gateway, the SDK's first byte arrived at
  0.02-0.06 s and the last at 2.05-2.09 s, for both engines, and raw `pcm`
  the same. A hop that collected the audio would deliver all of it at about
  2 s.
- **A speech failover never changes voice.** A slot
  `narrator → [router/acme/kokoro, eleven/eleven_flash_v2_5]` speaks with
  kokoro. With kokoro refusing before its first byte with a 429, which chat
  would cascade past, the answer is a 502 and ElevenLabs is never asked. With
  kokoro dropping the connection after two chunks, the audio ends there, and
  neither voice is asked again.
- **`llama-server` transcribes locally** is P3b.

## What the run checks

1. `GET /v1/models` lists each speech model with its voices where the
   provider names them, none where it does not (a key without `voices_read`,
   or OpenRouter models without `supported_voices`), and its formats.
   ElevenLabs' speech-to-speech model is not offered.
2. A key without `models_read` offers no model, and `/v1/info` gives
   ElevenLabs' reason.
3. The SDK gets both engines' audio byte for byte, streamed, and the ordinary
   `create` call gets the same bytes.
4. `pcm` streams through two hops as it is made.
5. ElevenLabs is asked in its own shape, with the driver's own key, and speed
   as `voice_settings`. `mp3` is asked for when no format is named.
6. OpenRouter is asked with the format always sent (its own default is `pcm`),
   and speed and instructions carried.
7. `wav` from both is their `pcm` with a streaming WAV header written first.
8. A format a model cannot make (at the gateway, and at the driver asked
   directly), `instructions` to ElevenLabs, and `stream_format: "sse"` are
   400s naming the field, with no upstream call.
9. OpenAI's `alloy` is passed to ElevenLabs, and its refusal is relayed as a
   400 naming the voice.
10. Speech to a chat model and chat to a speech model name the right door.
11. A key allowed only one model cannot speak through another, and a
    local-only key cannot reach a hosted voice. Neither reaches an upstream.
12. A slot alias speaks with its first model, is listed with its voices, and
    is retained in `/v1/metrics` as served by that model at tier 1.
13. After the first byte, a dropped upstream ends the audio.
14. A 429 before the first byte does not move a slot to its second voice,
    and the request is retained as an error with its one attempt.
15. The ElevenLabs keys reach their drivers in the environment only.

Live, on 2026-09-28:

- **`hexgrad/kokoro-82m` (voice `af_heart`)**, through the SDK: 2.73 s of WAV
  made from its `pcm`, which `google/gemini-2.5-flash-lite` heard back as
  *"The zebra is blue and the kettle is singing"*, with `kettle` as `cattle`.
  An MP3 of a longer sentence came in 18 reads between 0.47 s and 0.56 s:
  OpenRouter sends it almost whole, which is the provider's pace, not ours.
- **ElevenLabs:** no model offered, and the reason given as *"The API key you
  used is missing the permission models_read to execute this operation."*
- Neither key is in any of the run's 39 files.

## Found on the way

- **The speech door shipped with no client admission, for one commit.**
  `/v1/audio/speech` accepted client keys at `afff7f7` but was in none of the
  gateway's three path lists. So a scoped key could speak through any model,
  a local-only key could reach a hosted voice, no rate or concurrency limit
  applied, a body of any size was read, and a browser's preflight was
  refused. This is what happened to `/v1/systemone` at B2. Fixed at
  `e12e14a`, with `test_front_door_paths.py`, which reads the routes instead
  of a list. Every route that takes a client key must now be under client
  admission and CORS, and every such POST under the body limit. The driver's
  `/v1/speak` was also missing from its body limit (`13f2664`).
  `/v1/systemone` is the one named exception for CORS, which B2 left
  undecided.
- **A slot alias could not speak** at `afff7f7`: speech looked for a backend
  named after the alias and answered 503 "not ready". The same-model rule now
  means the slot's first model: its replicas, never its next tier
  (`829ca38`).
- **Every served clip was retained as an error.** The speech route recorded
  nothing, so the admission middleware's fallback row, which knows only
  embeddings, marked each clip `error` with no served model. It became
  reachable at `e12e14a`, when speech joined the middleware's paths. The
  route records its own row now (`5b82a68`). Metrics units (characters) are
  P3b.
- **Two copies of one rule, and the sabotage pass found both.**
  - `pick_speech` filtered by format as well as the route. With the route's
    check removed, the copy answered a 503 "not ready" instead of a 400
    naming the formats. The copy is gone (`8dab0ea`).
  - The driver's own format refusal was hidden by the gateway's, so its
    removal escaped. The run now also asks the driver directly, and the
    sabotage is caught.
- **Embeddings have the slot-alias defect speech had.** `pick_embedding`
  still requires a backend named after the requested model, so embeddings
  to a slot alias answer 503 "not ready". Found reading, not fixed here.
- **ElevenLabs' `/stream` route answers an unknown voice with a 404**
  `voice_not_found`, not the 400 `invalid_uid` its other route gives
  (measured). The driver relays either as the caller's 400.

## Not done, named

- **A replica failover through real processes.** Replicas of one speech model
  are two connections with the same name on two machines, and this run is one
  machine. Failover between replicas, and the commit point after the first
  byte, are unit-tested in the gateway (`tests/test_speech.py`).
- **OpenAI's own API speaks, live since 2026-09-28 (late)**: an OpenAI
  account's `tts-1` gave mp3 and its own wav through the SDK. The other four
  formats are asked of it and unmeasured.
- **No local engine speaks.** A single-model driver is chat, embeddings or
  decisions; a local OpenAI-shaped speech server is not yet a speech backend.
- **Metrics units** (characters for speech) came with P3b's schema v7
  ([record](transcription-run.md)).
