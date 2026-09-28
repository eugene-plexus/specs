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
