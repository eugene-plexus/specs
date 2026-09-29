# Provider accounts: the authenticated measurements

**2026-09-27.** The measurements owed by
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§6, taken with Troy's OpenRouter and ElevenLabs keys. The keys were read at
run time from a file outside every repository, and never printed or written
anywhere. **OpenRouter spend for the whole run: $0.116.** ElevenLabs: 8
characters.

Nothing here is Eugene code. It is what the upstreams did, measured, so that
P1-P5 are built against real shapes.

## 1. For P1: the catalogue

- **The authenticated listing is the anonymous listing.** Both
  `GET /models?output_modalities=all` read 628; both default listings read
  458. The key changes nothing about `/models`.
- **`GET /models/user` is the listing a driver wants.** It applies the
  account's own provider and privacy settings: 455 by default and **625**
  with `output_modalities=all`. The three it drops
  (`meta/muse-spark-1.2-contributor`, `meta/muse-spark-1.3-contributor`,
  `sakana/sakana-namazu`) are models this account cannot call. So an
  account driver reads `/models/user?output_modalities=all`, not `/models`.
- **Every model entry carries the same keys:** `id`, `canonical_slug`,
  `hugging_face_id`, `name`, `created`, `description`, `context_length`,
  `architecture` (`modality`, `input_modalities`, `output_modalities`,
  `tokenizer`, `instruct_type`), `pricing`, `top_provider`
  (`context_length`, `max_completion_tokens`, `is_moderated`),
  `per_request_limits`, `supported_parameters`, `default_parameters`,
  `supported_voices`, `knowledge_cutoff`, `expiration_date`, `links`.
  Optional: `reasoning` (328), `benchmarks` (261), `alias_target` (19).
- **Output modalities, as combinations:** text 443, image 46, embeddings
  37, video 29, transcription 24, speech 21, image+text 11, **rerank 7**,
  **decisions 6**, audio+text 4. Rerank and decisions are two surfaces the
  design's list did not name.
- **Input modalities:** text 604, image 365, file 183, video 97, audio 82.
- **`supported_parameters` counts:** `max_tokens` 480, `response_format`
  409, `temperature` 394, `tools` 390, `tool_choice` 383, `seed` 382,
  `structured_outputs` 378, `top_p` 372, `reasoning` 328, `stop` 317,
  `frequency_penalty` 262, `presence_penalty` 253, `top_k` 219,
  `reasoning_effort` 191, `logprobs` 160, `logit_bias` 147, `min_p` 114,
  `max_completion_tokens` 72, `verbosity` 23, `web_search_options` 19,
  `parallel_tool_calls` 12, `prediction` 12, `top_a` 12.
- **The model-level `supported_parameters` is a union over providers.**
  `openai/gpt-oss-20b` has 12 provider endpoints. One accepts `tools` but
  not `response_format`, another the reverse. So a model-level parameter is
  not a promise that the provider actually chosen will honour it. The
  per-provider lists are at `GET /models/{author}/{slug}/endpoints`.
- **Ids:** no upstream id has more than one slash. **100 carry a `:`
  variant** (`:free`, `:batch`), and **aliases start with `~`**
  (`~openai/gpt-sol-latest` → `openai/gpt-6-sol`). The longest id is 56
  characters. With the account prefix, an id has two slashes:
  `openrouter/anthropic/claude-opus-5.5`.
- **`supported_voices`** is filled on 14 of 21 speech models (for example
  `hexgrad/kokoro-82m`: `af_alloy`, `af_aoede`, …) and `null` on the rest.

## 2. For P1: two models over one key

| Requested | Status | Response `model` | Provider | Content |
|---|---|---|---|---|
| `mistralai/mistral-nemo` | 200, 0.58 s | `mistralai/mistral-nemo` | DeepInfra | `Pong` |
| `openai/gpt-oss-20b` | 200, 2.71 s | `openai/gpt-oss-20b` | DekaLLM | `null`: all 20 tokens were reasoning |
| `~z-ai/glm-flash-latest` | 200, 0.48 s | **`z-ai/glm-5.3-flash`** | Wafer | `pong` |

- **One key, three models, no configuration between them.** The model is
  just the request's `model` field.
- **An alias answers with its target's id.** A driver must put the public
  id back on the response, as B1's `upstreamModelId` already does.
- **`usage.cost` is on every response**, in dollars, with a
  `cost_details` breakdown. It is what a spend limit will read later.
- **Routes that take an id:** `GET /models/{author}/{slug}/endpoints`
  answers with a literal slash and **404s with `%2F`**. There is **no
  `GET /models/{id}`**; both spellings answer 404. So Eugene's own
  `GET /v1/models/{model}` (P6) cannot be forwarded upstream as-is; it
  has to be answered from the driver's catalogue.

## 3. For P3: speech and transcription

**Speech** (`POST /audio/speech`, OpenAI's request shape):

- **`response_format` is `mp3` or `pcm` only.** `wav` and `opus` are a
  400 Zod error listing the two. **The default is `pcm`**
  (`audio/pcm;rate=24000;channels=1`), where OpenAI's default is `mp3`.
- **The body is binary, chunked.** kokoro mp3: headers at 4.39 s, then 26
  chunks in 0.1 s (it synthesises first, then sends). Deepgram's free
  model: first bytes at 0.35 s, then 94 chunks over 1.2 s, a real stream.
- **`stream_format: "sse"` is ignored:** raw pcm comes back.
- **The voice is required for some providers:** *"An explicit voice is
  required for this TTS provider."* An unknown voice is a bare *"Provider
  returned 400"*.
- **`speed` and `instructions`** were accepted without error.
- **Two error shapes on one route:** `{"success":false,"error":{"name":"ZodError",…}}`
  for validation and `{"error":{"message","code"}}` for the rest.

**Transcription** (`POST /audio/transcriptions`):

- **OpenAI's multipart form works:** `file` plus `model` gave
  `{"text": " The quick brown fox jumps over the lazy dog."}` from a
  kokoro-made mp3, in 2.1 s.
- **A JSON body also works:** `{"model", "input_audio": {"data", "format"}}`.
- **`response_format` is `json` or `verbose_json`.** `text` is a 400
  naming both. verbose_json adds `task`, `language`, `duration` and
  Whisper-style `segments`.
- **`stream: true` is ignored:** JSON comes back.
- **Usage differs by model:** `{"seconds": 3.5, "cost"}` for Whisper,
  tokens for `gpt-4o-mini-transcribe`.
- **`/audio/translations` answers 404.**

**ElevenLabs** (`xi-api-key`):

- **The key given is scoped.** `voices_read`, `models_read` and
  `user_read` are all refused with *"missing the permission …"*. So a
  driver cannot assume it can list voices or models; it must say which
  permission is missing, not "invalid key".
- **TTS works:** `POST /v1/text-to-speech/{voice_id}?output_format=mp3_44100_128`
  with the premade voice `21m00Tcm4TlvDq8ikWAM` gave `audio/mpeg` with a
  `character-cost` header (5). `/stream` gave a chunked body, headers at
  0.19 s.
- **`Authorization: Bearer` is refused** (*"Provided authorization header
  was invalid"*). Only `xi-api-key` works for this key.

## 4. For P2 and P4: music and images

**Lyria 3 (music) through chat completions:**

- **Audio output needs `stream: true`.** Without it: 400 *"Audio output
  requires stream: true"*.
- **The music arrives in ONE SSE event:** `delta.audio.data`, a 992,812
  character base64 string, which is an mp3 (`ID3`, 744,607 bytes). There
  is no `id`, `format`, `transcript` or `expires_at`, all of which
  OpenAI's `delta.audio` has. `delta.content` was `<instrumental>`.
- **So any SSE reader on the path must accept a ~1 MB line.**
- **$0.04 per clip**, 9.7 s to `[DONE]`, first frame at 2.2 s.

**Speech output through chat** (`openai/gpt-audio-mini`, measured 2026-09-28
for P2b; about $0.0003 in all):

- **The listing names no `modalities` or `audio` parameter** for any of the
  four audio-output models (`gpt-audio`, `gpt-audio-mini`, both Lyria 3s).
  Their `supported_parameters` are the ordinary sampling ones. So a request
  asking for audio cannot be routed by the A2 setting list; it must be routed
  by `architecture.output_modalities` containing `audio`, which all four have.
- **Not streamed, it is refused:** 400 *"Audio output requires stream: true"*,
  with `provider_name: null`, so OpenRouter refuses it before any provider.
- **Streamed with `audio.format: "pcm16"` it works.** 17 frames, 15 carrying
  `delta.audio`. The first has `id` and `transcript` only; later ones carry
  `data` too, plus `expires_at`. `delta.content` is `""`. The spoken text is
  only in `delta.audio.transcript`.
  - The audio is raw little-endian 16-bit samples with no header. It came in
    19,200-byte chunks (0.4 s each at OpenAI's documented 24 kHz mono; the rate
    is not measured here). Each chunk's base64 decodes on its own.
  - 108,000 bytes for a 60-token answer, with the first audio at 0.57 s.
  - Usage arrives on a frame of its own after the last audio, with `cost`.
- **Streamed with `wav` or `mp3` it is refused by OpenAI itself**, relayed as a
  400: *"'audio.format' does not support 'wav' when stream=true. Supported
  values are: 'pcm16'."* The same for `mp3`.

So P2-1 holds as measured: a caller wanting a non-streamed answer gets it
only by our streaming `pcm16` upstream and assembling it. `wav` is that plus
a header; any other format would need a transcoder.

**Lyria asked the way P2b asks** (`google/lyria-3-clip-preview`, streamed,
2026-09-28, $0.04 per clip):

- **Plain, with `modalities: ["text","audio"]`, and with `audio: {voice,
  format: "pcm16"}` as well, all three answer the same way:** one
  `delta.audio` carrying only `data`, an MP3 (`ID3`) of 653-745 KB, and
  `finish_reason: stop`, in 9-11 s. **Asked for `pcm16`, it still sends
  MP3**, which is P2-2's case.
- `delta.content` carries timestamped lyrics (`[4.0:6.0] SUN IS SHINING IN
  THE SKY`) where the 2026-09-27 run saw `<instrumental>`.
- **The first call of the three failed** with a Google 500 relayed as
  OpenRouter's 502 (*"Internal error encountered."*). The identical request
  succeeded minutes later, after the two lighter shapes had, so it was
  transient and not the parameters.

**Image output through chat** (`google/gemini-3.1-flash-lite-image`,
`modalities: ["image","text"]`):

- **The image is `message.images[]`**, an OpenRouter extension:
  `[{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,…"}}]`
  with `content: null`. OpenAI's chat has no such field.
- **The message also carried a 1,066,912 character reasoning
  `signature`** in `reasoning_details`.
- $0.034.

**`POST /images/generations`** (`black-forest-labs/flux.2-klein-4b`):

- **Always `b64_json`**, with an extra `media_type: "image/jpeg"` and
  `created: 0`. `response_format: "url"` and `stream: true` are both
  ignored. `size: "512x512"` reduced the token count (1,024 against 4,096).
- **A provider's content filter is a 400** naming the provider: *"a small
  red circle on a white background"* was refused by Black Forest Labs *"for
  graphic violence"*. A blue square was not.
- $0.014 per image.

## 5. For P5: videos

- **`GET /videos/models` lists 29**, each with `supported_durations`,
  `supported_resolutions`, `supported_aspect_ratios`, `supported_sizes`,
  `generate_audio`, `seed`, `allowed_passthrough_parameters` and
  **`pricing_skus`**. The SKUs come in at least four units: cents per
  second, dollars per second by resolution, per video token, and per
  megapixel-second.
- **The cheapest job** is `x-ai/grok-imagine-video` at 480p for 1 second:
  5 cents.
- **`GET /videos/{id}` and `/videos/{id}/content` for an unknown job are
  404** `"Job … not found"`. **`GET /videos` is a plain 404**: there is no
  list route, which matches call #5.
- **Not measured: a submitted job.** Its lifecycle, and whether
  `/content` redirects to a CDN, need one paid job, which waits for Troy's
  approval.

## 6. Found on the way

- **OpenRouter serves `/api/v1/systemone`**, B2's TypeSafe shape, and
  lists `typesafe/jev-1.13` (TypeSafe as its provider, $0.000000042 per
  prompt token), `jaredpalmer/kev-4b` and Respan's `span-01` family as
  `decisions` models. B2's owed *hosted Jev* check could be taken through
  an OpenRouter account. Not tried here.
- **`/rerank` and `/completions` exist on OpenRouter; `/moderations`,
  `/responses/input_tokens`, `/responses/compact` and
  `/messages/count_tokens` do not.**
- **`openrouter/auto` is itself a model**, a router whose pricing reads
  `-1`. Prefixed, it becomes `openrouter/openrouter/auto`.

## 7. For P2c: the missing fields (2026-09-28)

Read from the account listing (455 text-output models of 626) and then sent
to the cheapest model listing each, about $0.012 in all.

**How many models list each parameter** in `supported_parameters`:

| Parameter | Models | Sent to | Result |
|---|---|---|---|
| `reasoning_effort` | 186 (and `reasoning` 323) | `openai/gpt-oss-20b` | Honoured: 17 reasoning tokens at `low`, 275 at `high`. The answer carries `reasoning` and `reasoning_details` |
| `logprobs`, `top_logprobs` | 149 each | `mistralai/mistral-nemo` | Honoured; shapes below |
| `logit_bias` | 141 | `mistralai/mistral-nemo` | Accepted (200). Its effect is not visible without the model's token ids |
| `verbosity` | 23, mostly Anthropic | `anthropic/claude-sonnet-5` | Accepted (200) |
| `web_search_options` | 18 | `openai/gpt-4o-mini`, then `perplexity/sonar` | **Refused by OpenAI although listed**; answered by Sonar, shapes below |
| `prediction` | 12 | `openai/gpt-4o-mini` | Accepted (200); usage names no accepted or rejected prediction tokens |
| `service_tier`, `prompt_cache_key` | **0** | — | Not listed anywhere |

- **`logprobs`, not streamed:** `choices[0].logprobs` is `{"content": [{"token",
  "bytes", "logprob", "top_logprobs": [{"token", "bytes", "logprob"}]}],
  "refusal": null}`, OpenAI's shape. **Streamed:** the same object on the
  frame's choice beside `delta`, not inside it, on the frames that carry
  tokens (1 of 3 here).
- **One call of ten came back with `logprobs: null`** though it asked for
  them. It was not reproduced in eight more, with `provider.require_parameters`
  and without. The driver already sends `require_parameters` whenever a caller
  set a setting explicitly.
- **A listed parameter is not a promise.** OpenRouter lists
  `web_search_options` for `gpt-4o-mini`, and OpenAI answers 400 *"Web search
  options not supported with this model."* (relayed with `provider_name`, and
  Azure's identical refusal in `previous_errors`). The listing is a filter to
  route by, and the provider's own refusal is still the caller's 400.
- **Web search, not streamed:** `message.annotations` is `[{"type":
  "url_citation", "url_citation": {"url", "title", "start_index",
  "end_index"}}]`, and `content` carries `[2][3]`-style markers. Sonar's
  indices were all 0. **Streamed:** `delta.annotations` on 20 of 34 frames,
  one citation per frame. $0.005 per request, almost all of it the search.

## 8. For P3: the OpenAI SDK, ElevenLabs and llama-server (2026-09-28)

**What the OpenAI Python SDK sends** (openai 3.20.0, against a capture
listener):

- **Speech** is `POST /v1/audio/speech` with a JSON body `{model, voice,
  input}` plus `response_format`, `speed` and `instructions` when set, and
  `Accept: application/octet-stream`. **The SDK passes any `voice` string
  through**, an ElevenLabs voice id included. `with_streaming_response` is the
  same request, and the answer is read as raw bytes.
- **Transcription** is `POST /v1/audio/transcriptions`, multipart: `model`,
  `file` (with its filename and `Content-Type`), and `language`, `prompt`,
  `response_format`, `temperature` and `timestamp_granularities[]` when set.
  With `response_format: text` the SDK takes a plain-text body as the answer.
  Translation is the same form at `/v1/audio/translations`.

**ElevenLabs, with the key Troy gave** (`xi-api-key`):

- **Speech works.** `eleven_flash_v2_5` and `eleven_multilingual_v2` answered in
  0.17 s and 0.86 s, with a `character-cost` header (5 and 10 for 23
  characters). `mp3_44100_128` is `audio/mpeg`, `pcm_24000` is `audio/pcm`
  (16-bit mono), and `opus_48000_64` is `audio/opus` (an Ogg stream).
  Streamed at `/stream`: headers at 0.18 s, then 62 chunks, chunked transfer.
- **Its published formats are mp3, pcm (8-48 kHz), opus, μ-law and A-law.**
  `wav_44100` exists but is refused on this plan: 403 *"Output format
  'wav_44100' is only available on the Pro tier and above"*. There is no AAC
  or FLAC.
- **The key is scoped, and missing four permissions:** `models_read`,
  `voices_read`, `user_read`, and **`speech_to_text`**. Each is a 401 with
  `status: missing_permissions` and a message naming the permission. So this
  key can speak but cannot list models or voices, and cannot transcribe.
- **The errors name their cause:** an unknown voice is 400 `invalid_uid`, an
  unknown model is 400 `model_not_found`, and no key is 401
  `needs_authorization`.

**`llama-server` b11235 (published 2026-09-28) with
`ggml-org/Qwen3-ASR-0.6B-GGUF` Q8_0 and its projector, on the CPU:**

- `/props` reports `modalities: {audio: true}`. The route answers only when an
  audio projector is loaded; otherwise *"The current model does not support
  audio input."*
- `/v1/audio/transcriptions`, OpenAI's multipart form: the fox in 0.3-0.4 s.
  The answer is `{"type": "transcript.text.done", "text", "usage": {"type":
  "tokens", …}}`.
- **The text carries the model's own preamble**: `"language
  English<asr_text>The quick brown fox jumps over the lazy dog."`. The same
  model on OpenRouter answers `"The quick brown fox jumps over the lazy dog."`
  with `usage.seconds: 3.5`. So the prefix is llama.cpp not parsing the
  model's output, not the model's normal answer.
- **Only `response_format: json`**: `text` and `verbose_json` are 400 *"Only
  'json' response_format is supported"*. `stream: true` gives
  `transcript.text.delta` SSE events. A request with no file is a 500 JSON
  parse error.

**OpenRouter's listing for the new doors:** 21 speech models and 24
transcription models. Most speech models carry `supported_voices`, from 2 to
90 each; `fish-audio`'s and `bytedance`'s carry none. **No speech or
transcription model lists any `supported_parameters`.** `hexgrad/kokoro-82m`
and the free `deepgram/flux-tts:free` are the cheapest to speak with.
`openai/whisper-large-v3-turbo` transcribed the fox in 6.2 s, and
`qwen/qwen3-asr-0.6b` in 0.6 s.

## 9. For P4: images (2026-09-28)

OpenRouter spend: **$0.139** (flux.2-klein-4b at $0.014 a megapixel,
gpt-image-1-mini at low quality, one gemini flash-lite image).

**What the OpenAI Python SDK sends** (openai 3.20.0, capture listener):

- **Generation** is `POST /v1/images/generations`, JSON: `{prompt, model}`
  plus whatever was set. **`Accept: application/json` even with `stream:
  true`**; the SDK reads SSE whatever it asked for.
- **An edit is always multipart**, never the JSON form OpenAI's spec also
  allows. One image is a part named `image`; several are parts named
  **`image[]`**; the mask is `mask`. **A `BytesIO` arrives as `filename:
  upload`, `Content-Type: application/octet-stream`**, so an image's type
  must be read from its bytes, not its part header.
- **A variation** is multipart: `image`, `n`, `size`.
- **The streamed answers the SDK parses** are `data:` lines typed
  `image_generation.partial_image` / `.completed` (edits: `image_edit.*`).

**OpenAI's own contract** (`openai-openapi` at `d983890`): generations take
14 fields (`prompt` required; `n` 1-10; `size`; `quality`; `response_format`
`url|b64_json`, dall-e only; `output_format`; `output_compression`;
`background`; `moderation`; `style`, dall-e-3 only; `stream`;
`partial_images`; `user`). Edits take `image` (one or up to 16), `mask`,
`input_fidelity` and most of the same. Variations are **dall-e-2 only**. The
answer is `{created, data: [{b64_json | url, revised_prompt}], background,
output_format, size, quality, usage: {input_tokens, output_tokens,
total_tokens, input_tokens_details}}`. A partial-image event requires
`created_at`, `size`, `quality`, `background`, `output_format` and
`partial_image_index`.

**OpenRouter's routes:** `POST /images/generations` and its alias `POST
/images` (the same answer). **`/images/edits` and `/images/variations` are
404.** An edit is a generation with **`input_references`**, and those must be
**objects** `{"type": "image_url", "image_url": {"url": "data:..."}}`; the
plain strings its guide shows are a 400 (Zod: *expected object, received
string*).

**`GET /images/models`** (unauthenticated) lists **55**, the same set as the
main listing's image-output models less `openrouter/auto`. **The main
listing's `supported_parameters` for these is chat-style and says nothing
about images**; only `/images/models` carries the image settings, as typed
descriptors:

- `input_references` on 53 (range, max 1-16). **Five require at least one**
  (`recraft-v4-styles*`, `ming-image-...-design-layer`): they edit, they do
  not generate.
- `aspect_ratio` 52, `n` 51 (max 1 on 23, 6 on 18, 10 on 9), `resolution`
  19, `output_format` 14 (six models are **svg only**), `seed` 12,
  `background` 10, `quality` 9, `output_compression` 8. **No model lists
  `size`.**
- `supports_streaming` on **8**, every one OpenAI's (`gpt-image-*`,
  `gpt-5*-image*`).
- Per-provider records at each model's `endpoints` add
  `allowed_passthrough_parameters` (`moderation` on OpenAI's; `steps`,
  `guidance`, `safety_tolerance` on Black Forest Labs') and pricing by
  billable unit (per output megapixel, per output-image token).

**What OpenRouter does with each field:**

- **`size` is translated**, although no model lists it: `1536x1024` gave a
  1536×1024 JPEG from flux and `1024x1536` a 1024×1536 PNG from
  gpt-image-1-mini.
- **A listed setting outside its range is OpenRouter's own 400**, before any
  provider (`failed_routing_step: "Filter by Image Capabilities"`): `n: 2` on
  flux (max 1), `output_format: webp` on flux (png, jpeg), five references
  on flux (max 4).
- **An unlisted setting is silently ignored, or silently honoured.** flux
  given `quality: high` or `background: transparent` answered an ordinary
  opaque JPEG with a 200. gpt-image-1-mini, whose listing has no
  `output_format`, gave the `webp` and `jpeg` asked for. So the listing is
  exact where it names a setting and says nothing reliable where it does
  not.
- **`mask` and `response_format: url` are ignored**: a 200 with `b64_json`.
  Every answer is `b64_json` with an extra `media_type`.
- **The answer:** `{created, data: [{b64_json, media_type}], usage}`, where
  `usage` is chat-shaped (`prompt_tokens`, `completion_tokens` with
  `image_tokens`, `cost`), not OpenAI's `ImagesUsage`. **`created` is 0**
  from flux and gemini and a real time from OpenAI's models. `n: 2` gives two
  `data` items.
- **gemini-3.1-flash-lite-image**, an image+text chat model, answers on this
  route too: one 1408×768 JPEG, no text.

**Streaming** (gpt-image-1-mini, `partial_images: 1`): `text/event-stream`,
a **`: ` comment every ~0.42 s** as keepalive, then `data:` lines with **no
`event:` line**. The partial event carries only `type`, `b64_json` and
`partial_image_index` (none of the fields OpenAI's schema requires besides
those). The completed event carries `type`, `b64_json`, `created`,
`media_type` and chat-shaped `usage`. Partial at 3.6 s, completed at 6.2 s,
then `[DONE]`. **flux, which does not stream, asked to stream answers plain
`application/json`**: the flag is dropped, not refused.

## 10. For P5: videos (2026-09-28)

Troy cleared test videos with a $10 budget. **Spent: $0.102** on OpenRouter
(two 1-second 480p jobs); OpenAI's calls were refused before any work.

**OpenAI's video API is shut down.** `sora-2` and `sora-2-pro` both carry
`"shutdown_date": "2026-09-24"` on `GET /v1/models`, and `GET` and `POST
/v1/videos` answer an empty 404 with no request id, although `openai-openapi`
of 2026-09-26 still describes them. **OpenRouter is the only live video
backend.** It still lists `openai/sora-2-pro` among its 29, untried. OpenAI's
list carries `shutdown_date` on 56 of its 134 models (future dates too:
`gpt-image-1-mini` says 2026-12-01).

**The OpenAI SDK's `client.videos`** (3.20.0) has `create`, `create_and_poll`,
`poll`, `retrieve`, `list`, `delete`, `download_content` (with `variant`:
`video`, `thumbnail`, `spritesheet`), `remix`, `edit`, `extend` and the
character calls. OpenAI's contract: `POST /videos` takes `prompt`, `model`,
`seconds` (a string, `4`/`8`/`12`), `size` (four sizes) and `input_reference`
(an image, multipart or JSON `{image_url | file_id}`); the job is a
`VideoResource` with `status` `queued|in_progress|completed|failed`,
`progress`, `created_at`, `completed_at`, `expires_at`, `prompt`, `size`,
`seconds` and `error`, every one required.

**OpenRouter's video API is its own shape** (`POST /api/v1/videos`):
`duration` is an **integer**, `resolution` and `aspect_ratio` or an exact
`size` (one or the other), `frame_images` for image-to-video
(`{"type": "image_url", "image_url": {"url"}, "frame_type": "first_frame"}`),
`input_references`, `generate_audio`, `seed`. **A `size` it does not list is a
400** (*"Unsupported size \"848x480\""*); `GET /videos/models` lists each
model's `supported_durations`, `supported_sizes`, `supported_resolutions`,
`supported_aspect_ratios`, `supported_frame_images` and `pricing_skus`
(`x-ai/grok-imagine-video`: 1-15 s, 14 sizes, first frame only, 5¢ a second
at 480p).

**The lifecycle, measured** (`x-ai/grok-imagine-video`, 1 s, 480p):

- **Submit is a 202** in 1.7-3.8 s: `{id: "gen-vid-...", polling_url, status:
  "pending"}`.
- **Poll** (`GET /videos/{id}`): `pending`, then `completed` at 24 s (47 s
  with a first frame). **No `in_progress` was seen and there is no
  `progress` field.** Completed adds `unsigned_urls` and `usage: {cost}`
  ($0.05, $0.052).
- **Content** (`GET /videos/{id}/content?index=0`, the same bearer): 200
  `video/mp4`, chunked with **no length, and `Range` is ignored** (a full 200).
  No CDN redirect. `index=1` is a 400 naming the count. **`variant=thumbnail`
  is ignored: it returns the MP4.**
- **A bad input is accepted and fails later**: a 1×1 first frame was a 202,
  then `failed` 17 s on with `error` a string (*"Image dimensions 1x1 are too
  small. Both width and height must be at least 8 pixels.
  [WKE=invalid_image]"*) and no `usage`.
- **An unknown job is a 404** naming it. **There is no list, delete or remix
  route** (`GET /videos`, `DELETE /videos/{id}`, `POST .../remix`: plain 404s).

**What the OpenAI SDK sends for videos** (3.20.0, capture listener): **every
`videos.create` is multipart**, with or without a file (`prompt`, `model`,
`seconds`, `size`, and `input_reference` as a file part). A dict
`input_reference` (`{"image_url": ...}`) is refused by the SDK itself before
sending. `create_and_poll` polls `GET /videos/{id}`; `download_content` is
`GET /videos/{id}/content`, with `?variant=` when one is asked for. **The SDK
warns on every video call** that *"The Sora API is scheduled to permanently
shut down on September 24, 2026."*

## 11. For P3-1 and P3-4: ElevenLabs' speech-to-text, and who translates (2026-09-28, late)

Troy widened the ElevenLabs key and added an OpenAI key, which removed both
deferrals' reasons, and took both. Measured with those keys; the spend was a
few seconds of ElevenLabs transcription, one `tts-1` sentence and a handful of
`whisper-1` calls, under a cent.

**ElevenLabs' `/v1/models` lists text-to-speech models only**: nine with
`can_do_text_to_speech: true`, two speech-to-speech. No scribe model, and its
`ModelResponseModel` has no speech-to-text flag. **What names them is its own
refusal of an unknown model id**: *"'x' is not a valid model_id. Available
models: 'scribe_v1', 'scribe_v1_experimental', 'scribe_v2',
'scribe_v2_medical'"*, a 400 with `code: unsupported_model` and
`param: model_id`. It is given with no file, costs nothing (no
`character-cost` header), and **is given even to a wrong key**, so it is
ElevenLabs' list, not the account's.

**The key's permission is answered by an empty file**: a valid model with a
0-byte file is a 400 `status: empty_file` for a key that may transcribe, and a
401 naming `speech_to_text` for one that may not (the second measured before
the key was widened). Neither costs anything.

**`POST /v1/speech-to-text`** is multipart: `model_id` (required), `file`,
`language_code` (ISO-639-1 or -3), `tag_audio_events` (default **true**: the
text carries *(laughter)*), `timestamps_granularity` (`none`, `word` default,
`character`), `temperature` (0-2), `seed`, `keyterms`, diarization and more.
**There is no `prompt`, and an unknown field is ignored** (a `prompt` was a
200). The answer: `language_code` (`eng`, ISO-639-3), `language_probability`,
`text`, `words` (each with `text`, `start`, `end`, `type` of `word`, `spacing`
or `audio_event`, and `logprob`), `audio_duration_secs` and
`transcription_id`. **No segments.** `character-cost: 1` for four seconds of
audio. `scribe_v1` and `scribe_v2` answered the fox identically.

**Only OpenAI's `whisper-1` translates.** `POST /v1/audio/translations`
through an OpenAI account: `whisper-1` made *"The fast brown fox jumps over
the lazy dog."* of `tts-1`'s French in `json`, `text`, `verbose_json`
(`task: translate`, `language: english`, `duration`, segments) and `srt`.
`gpt-4o-mini-transcribe` and `gpt-4o-transcribe` answer this door **404
"Invalid URL"**. A `language` other than `en` is a 400 (*"Input should be
'en'"*); `timestamp_granularities[]` is accepted and ignored (no words
return); `prompt` and `temperature` are taken. No usage is returned.

**Nothing else here translates.** OpenRouter answers `/audio/translations`
404, and `task=translate` on its transcriptions door is ignored (the French
came back French). `llama-server` b11235 answers `/v1/audio/translations` 404
and transcribes French as French, with its preamble (`language
French<asr_text>...`).

## 12. For P6: moderations, one model by id, and completions (2026-09-28, late)

Measured with the OpenAI and OpenRouter keys; moderation is free, and the
completions calls cost well under a cent.

**Moderations: an OpenAI account only.** OpenAI lists
`omni-moderation-latest` and `omni-moderation-2024-09-26`; the
`text-moderation-*` models are gone (a 400 *"Invalid value for 'model'"*),
and a chat model is refused the same way. `model` left out answers as
`omni-moderation-latest`. `input` is a string, an array of strings (one
result each) or an array of parts (`text`, `image_url`), which is one input
with one result; each result has `flagged`, `categories`, `category_scores`
and `category_applied_input_types` (`["text"]`, or `["text", "image"]` when
an image was read). **At most one image per request** (a 400
`too_many_images`, *"Number of images (2) exceeds maximum of 1"*). A remote
`https` image is fetched by OpenAI. An unknown field (`user`) is ignored. No
usage is returned. **OpenRouter answers `/moderations` 404.**

**One model by id.** OpenAI's `GET /v1/models/{model}` answers `{id,
object, created, owned_by, shutdown_date}`, and an unknown id is a 404
`code: model_not_found`, *"The model 'x' does not exist"*. **OpenRouter has
no such route**: `GET /v1/models/openai/gpt-4o-mini` is a 404.

**Completions: OpenAI's legacy models are gone.** `gpt-3.5-turbo-instruct`,
`davinci-002` and `babbage-002` are listed and answer `/v1/completions` 404
*"has been deprecated"*. **The door answers `gpt-4o-mini` and
`gpt-4.1-nano`** as raw continuations (`object: "completion"`, not
`text_completion`), streams them, and takes `n`; it refuses `gpt-5-nano`
(*"This is a chat model and not supported"*), refuses `suffix` (*"Unrecognized
request argument supplied: suffix"*), and answers `echo` with `logprobs`, and
an array `prompt`, with a 500.

**OpenRouter's completions are chat in disguise.** `/v1/completions` with a
code prompt to `mistralai/codestral-2508` and
`qwen/qwen-2.5-coder-32b-instruct` answered *"It looks like you've started
defining a..."*, a chat reply to the prompt as a user turn, and **`suffix`
was silently ignored**: the answers with and without it were identical. No
OpenRouter model lists `suffix` among its parameters.
