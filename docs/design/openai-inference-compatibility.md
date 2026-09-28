# OpenAI inference compatibility, and one driver per provider account

**Status: P1 built 2026-09-27** (one driver per provider account; record
[`provider-accounts-run.md`](../acceptance/provider-accounts-run.md)).
**P2a, attachments in, is built and pinned in both installers 2026-09-28**
(record [`media-inputs-run.md`](../acceptance/media-inputs-run.md): 9 fixture
checks and 5 live OpenRouter checks, 21 of 21 sabotages caught).
**P2b, audio out, is built and pinned 2026-09-28** (record
[`audio-output-run.md`](../acceptance/audio-output-run.md): 5 fixture and 3
live checks, 19 of 19 new sabotages caught). **P2c, the missing fields, is built and pinned 2026-09-28** (record
[`chat-fields-run.md`](../acceptance/chat-fields-run.md)), which completes P2:
its done-when is met, and both installers pin all five Python components at
P2's end. **P3a, speech, is built and pinned 2026-09-28** (record
[`speech-run.md`](../acceptance/speech-run.md): 15 fixture and 3 live
checks, the OpenAI SDK unchanged). **P3b, transcription, is built and pinned
2026-09-28** (record [`transcription-run.md`](../acceptance/transcription-run.md):
`llama-server` transcribes locally), which completes P3. **P4, images, is
built and pinned 2026-09-28** (record [`images-run.md`](../acceptance/images-run.md):
15 fixture and 2 live checks, the OpenAI SDK unchanged). **P5, videos, is
built and pinned 2026-09-28** (record [`videos-run.md`](../acceptance/videos-run.md):
8 fixture and 2 live checks; OpenAI's own video API had shut down, so
OpenRouter is the backend). **P6-P8 are not built.** §0 is measured, and §6's authenticated measurements
are in [`provider-accounts-measurement.md`](../acceptance/provider-accounts-measurement.md).
**All nine calls in §5 were taken by Troy the same day.** Seven went as
recommended; #3 (replace `modelId`) and #8 (Eugene runs some
server-side tools itself) did not.

**Direction, set by Troy on 2026-09-26:**

- **One inference-driver per provider account, not per model.**
- **Full compatibility with OpenAI's *inference* API comes first,** for
  every data type it supports.
- **Then survey the landscape** for shapes nothing standard covers.
  Eugene does not invent a door ahead of a standard, because an invented
  door has to change when an official shape appears.
- **A per-key spend limit is deferred.**
- **A passthrough door is deferred.**
- **OpenAI's stateful *platform* half is on the future roadmap and comes
  after this.** That half is files, batches, vector stores, fine-tuning,
  and stored responses and conversations.

**What prompted it:** a work job, run outside Eugene. Claude Code with
Opus 5.5 was given OpenRouter and ElevenLabs keys and made a 45-second
video with music, sound effects and a voice-over, keeping to a spend limit
stated in the prompt. That job should be doable through Eugene, with the
harness holding one revocable client key instead of two raw provider keys.

## 0. Measured, 2026-09-26

### 0.1 OpenAI's API

Source: `openai/openai-openapi` at `d983890` (committed 2026-09-26
07:45Z), `info.version` 2.3.0, OpenAPI 3.1. It has **353 operations**.

The **inference** half is below; everything else is platform state,
product surfaces or organisation admin (§1).

| Operation | Request | Response | Eugene today |
|---|---|---|---|
| `POST /chat/completions` | JSON, 37 fields | JSON or SSE | **Built.** 24 fields; see 0.2 |
| `POST /responses` | JSON, 32 fields | JSON or SSE | **Built** (2026-09-23). 29 fields; see 0.2 |
| `POST /responses/input_tokens` | JSON | JSON | Not built |
| `POST /responses/compact` | JSON | JSON | Not built |
| `POST /embeddings` | JSON, 5 fields | JSON | **Built**, all 5 fields |
| `POST /completions` (legacy, and fill-in-the-middle via `suffix`) | JSON, 18 fields | JSON or SSE | Not built. Its own open call: [`responses-and-completions.md`](responses-and-completions.md) §2 |
| `GET /models`, `GET /models/{model}` | — | JSON | List **built**; single model not built |
| `POST /audio/speech` | JSON: `model input voice instructions response_format speed stream_format` | **binary** audio, or SSE | Not built |
| `POST /audio/transcriptions` | **multipart**: `file`, `model`, 12 more | JSON, text, SRT/VTT, or SSE | Not built |
| `POST /audio/translations` | multipart, 5 fields | JSON or text | Not built |
| `POST /images/generations` | JSON, 14 fields | JSON (`b64_json` or `url`), or SSE of partial images | Not built |
| `POST /images/edits` | **multipart or JSON** (image, optional mask) | as above | Not built |
| `POST /images/variations` | multipart | JSON | Not built |
| `POST /videos`, `GET /videos/{id}`, `GET /videos/{id}/content`, `/remix`, `/edits`, `/extensions`, `GET` and `DELETE` the list | JSON or multipart, then **polled**; content is `video/mp4` | JSON job objects, then bytes | Not built. **An asynchronous job**, which no door here has been |
| `POST /moderations` | JSON: `input`, `model` | JSON | Not built |
| Realtime (`/realtime/*` REST plus the WebSocket; `/realtime/calls` speaks SDP) and `/live/sessions/*` | WebSocket, WebRTC, SIP | events | Not built. **A different transport** |

**Stateful edges inside the inference half:**

- `store: true` on chat, and `GET/POST/DELETE /chat/completions/{id}`.
- Retrieval, delete and `input_items` on responses.
- `/audio/voices` and `/audio/voice_consents` (custom voices).
- `/videos/characters`.

These belong to the platform half. They are refused with a 400 until it
exists, as stored responses are today.

### 0.2 Data types inside the doors we already have

**Chat completions.**

- **Content parts:** OpenAI's user content parts are `text`, `image_url`,
  `input_audio` (base64 `wav`/`mp3`) and `file` (`file_data` base64 with a
  `filename`, or a `file_id`). Eugene carries `text` and `image_url` only,
  and `common.yaml` `MessageContentPart` is exactly those two.
- **Output:** the response message carries `audio` as well as text when
  the request sets `modalities: ["text","audio"]` and `audio: {voice, format}`.
  Eugene carries text.
- **Missing fields, fifteen of them:** `audio`, `modalities`,
  `logit_bias`, `top_logprobs`, `reasoning_effort`, `verbosity`,
  `prediction`, `web_search_options`, `moderation`, `service_tier`,
  `prompt_cache_key`, `prompt_cache_options`, `prompt_cache_retention`,
  and the deprecated `functions`/`function_call`.
- **Eugene's own extras:** `top_k`, `min_p`.

**Responses.**

- **Input content:** `input_text`, `input_image` and `input_file`. There
  is **no `input_audio`** in the current spec, although `gateway.yaml`
  names it among its refusals.
- **Missing fields:** `access_programs`, `context_management`,
  `moderation`, `prompt_cache_options`.
- **Refused today:** `input_file`, and `tool_choice` naming anything but
  a function.
- **Tools:** OpenAI's union has sixteen tool types, in two kinds.
  - **Run by OpenAI's servers:** `web_search`, `file_search`,
    `code_interpreter`, `image_generation`, remote `mcp`.
  - **Declared and run by the client:** `function`, `custom`, `shell`,
    `local_shell`, `apply_patch`, `computer`.
  - **Eugene today** maps `function`, accepts and strips `web_search`,
    and refuses every other type.

**Anthropic messages** refuses `document` blocks (PDFs) and images
(`gateway.yaml:3667`).

**Stale on the way:** `docs/api-compatibility.md` row 13 still says
`/v1/responses` is *not implemented*. That was false from 2026-09-23.

### 0.3 OpenRouter, read live and unauthenticated

**628 models.** The default `GET /api/v1/models` lists only the **458**
whose output includes text. The rest appear only under
`?output_modalities=`:

| Output | Models | In the default list |
|---|---|---|
| image | 57 | 11 (the image+text chat models) |
| audio | 4 | 4: `google/lyria-3-pro-preview`, `google/lyria-3-clip-preview` (**music**), and `openai/gpt-audio`, `openai/gpt-audio-mini` |
| video | 29 | 0 (also listed at `GET /api/v1/videos/models`) |
| speech | 21 | 0 |
| transcription | 24 | 0 |
| embeddings | 37 | 0 |

So **an account driver that reads only `/models` misses 170 models**.
`?output_modalities=all` returns all 628.

**Per-model metadata**, which is what per-model capabilities come from:

- `architecture.input_modalities` / `output_modalities`: text, image,
  file, audio, video.
- `supported_parameters`: for example `tools` on 390 of 458,
  `response_format` 391, `logprobs` 150, `logit_bias` 141, `min_p` 114.
- `context_length`, `pricing`, `per_request_limits` and
  `supported_voices`.
- Video models add `supported_durations`, `supported_resolutions`,
  `supported_aspect_ratios` and `generate_audio`.

**Routes**, probed by an unauthenticated POST of `{}`. A 401 or a
schema-validation 400 means the route exists; 404 means it does not.

| Route | Answer |
|---|---|
| `chat/completions`, `completions`, `responses`, `messages`, `embeddings`, `audio/transcriptions` | 401 |
| `audio/speech`, `images/generations`, `videos` | 400: Zod validation, naming `model` and `input` / `prompt` |
| `moderations` | **404** |

**The finding that matters for the video job:** OpenRouter's **music**
models (Lyria 3) and its image+text models sit **on chat completions**,
with audio or images in the output. Music therefore already has an
OpenAI-shaped path: chat completions' audio output. It does not need a
door of its own.

### 0.4 ElevenLabs

Source: `api.elevenlabs.io/openapi.json`, 306 paths.

- **The key rides in `xi-api-key`**, not `Authorization`.
- **Nothing is OpenAI-shaped.**
  - Speech is `POST /v1/text-to-speech/{voice_id}`: the voice is in the
    path, the output format is a **query** parameter, and the body is
    `text`, `model_id`, `voice_settings`, `seed`, and so on.
  - Speech-to-text is `POST /v1/speech-to-text`.
  - Voices are listed at `GET /v1/voices`.
- **Sound effects** (`/v1/sound-generation`: `text`, `duration_seconds`,
  `loop`, `prompt_influence`) and **music** (`/v1/music`: `prompt`,
  `lyrics_text`, `composition_plan`, `music_length_ms`, …) are close to
  one shape, a prompt and a duration in and audio out. **No OpenAI door
  covers either.**

### 0.5 Local engines

`llama-server-impl.dll` of the supervised llama.cpp **b11076** contains
the route **`/v1/audio/transcriptions`**, alongside chat, completions,
embeddings, rerank, messages and responses. It has **no speech and no
image route**.

- **Found by reading the binary, not by a request.** Which models it
  transcribes with is unmeasured.
- **Unmeasured:** local speech engines (speaches, Kokoro-FastAPI) and
  local image servers (stable-diffusion.cpp).

### 0.6 Eugene's own constraint

**A driver serves exactly one model.**

- `/v1/info` reports one `modelId`, which needs a restart to change.
- `GenerateRequest` has **no `model` field**. `openai_compat_http.py:625`
  always sends the configured `upstreamModelId`.
- The gateway's `by_model` is keyed by that one id (`routing.py:917-947`).

**What already exists:**

- `list_models()`, which the driver uses to fill the UI's model dropdown,
  with a chat-name heuristic (`filter_models`).
- Client-key `allowedModels`, matched as exact members (`admission.py:60`).
- Per-key concurrency and rate limits (A5).

## 1. Scope

**This is short-term scope only.** Nothing below is ruled out for Eugene.
Long term, the aim is to be as open, flexible and capable as possible
(Troy, 2026-09-26), so every choice here should keep what comes later
possible.

**In this design:** every operation in the 0.1 table apart from its
stateful edges, and every data type in 0.2.

**Later, on the roadmap:**

- The platform half: files, uploads, batches, vector stores, fine-tuning,
  evals, graders, containers, stored chat completions, stored responses
  and conversations, custom voices, video characters. **It is on the
  roadmap after this** (Troy, 2026-09-26).
- **`file_id` inputs** are refused until then, because they name a store
  Eugene does not have.

**Not in this design, because they are not inference, and not ruled
out:** assistants and threads (deprecated upstream), agents, skills,
vaults, ChatKit, webhooks, organisation and project admin, spend alerts,
and content-provenance checks.

**Phase 2**, after the survey (§3): shapes with no OpenAI standard.

## 2. The shape

### 2.1 A provider account is one driver serving many models

**The contract** (`inference-driver.yaml`):

- **`InferenceDriverInfo.models[]`**, one entry per model this driver
  serves. Each entry has:
  - `id`, public and routed on;
  - `upstreamId`, diagnostic, as today;
  - `surfaces[]`: chat, embeddings, speech, transcription, image, video,
    moderation, completion;
  - `inputModalities` and `outputModalities`;
  - `capabilities`: tool calling, context window, supported settings,
    image input and the rest, today's `capabilities` object per model;
  - optional `voices`.
- **`models[]` replaces `modelId`** (call #3). A companion driver
  reports a one-entry list with its bare alias.
  - P1 therefore moves `inference-driver`, `gateway` and `ui` in one pin
    bump, with both installers re-pinned together.
  - The cost that remains is mixed pins **across machines**: a worker
    whose drivers are older than the gateway cannot be routed to until
    that worker is upgraded.
  - So the gateway must name such a driver and its node, as an Issue
    with "upgrade this machine" as the fix. It must never be silently
    absent.
- **Every request gains `model`**: `GenerateRequest`, `EmbedRequest`, and
  the media requests of 2.2. The driver refuses a model it does not list.

**The driver:**

- It reads its upstream catalogue at startup and on an interval.
  **For OpenRouter that means `output_modalities=all`, not the default
  listing (0.3).**
- It maps metadata into `models[]` per provider:
  - OpenRouter: `architecture`, `supported_parameters`, `context_length`.
  - OpenAI: its `/models` carries none of this, so per-model facts come
    from a probe or a table.
  - Ollama and LM Studio: every model the operator pulled.
- It gains `include` / `exclude` glob patterns in config. **By default
  an aggregator account exposes everything** (call #2), and a client
  key's scope narrows what each app sees.

**Model ids** are `<account>/<upstream id>`, where the account is the
driver's operator-chosen name. So `openrouter/anthropic/claude-opus-5.5`
and `ollama/qwen3:8b`.

- Two accounts can never collide.
- One upstream model through two accounts is **two ids, not a replica
  pair**. Putting both in a tier is the operator's explicit act, which is
  what a model slot already is. That matters because the same model
  through a different provider is not the same backend: price, limits
  and retention all differ.
- Companion drivers, one per supervised runtime, keep their bare alias.
  Nothing about M6 changes.
- A friendly name for a harness is a model slot, as today. For example,
  Claude Code's `claude-opus-5-5` → `openrouter/anthropic/claude-opus-5.5`.

**The gateway:**

- Every `models[]` entry becomes a routing candidate keyed by
  `(node, driver, model)`, the R1.6 key with one more member.
- The balancer, eligibility, tiers, metrics and client-key admission
  treat it exactly as a single-model driver today.
- `allowedModels` gains **glob entries** (`openrouter/*`), which is a
  change to `agent.yaml`'s key schema. Without it, a key scoped to one
  account means typing out hundreds of names.

**The UI:**

- Adding an aggregator account skips `PickModel` and shows the count and
  the filter.
- The Routing page's pickers need search.
- Scoped-key editing needs the glob.

**What it unlocks beyond OpenRouter:** an Ollama, LM Studio or
router-mode `llama-server` with twenty models exposes twenty, where today
it exposes one per driver process.

### 2.2 Phase 1 doors

**Driver-internal contract: normalised** (call #9). The gateway speaks
OpenAI on the outside and something like `GenerateRequest` to the
driver, and the driver translates to its backend, as it does for chat
today. That is what lets `/v1/audio/speech` front ElevenLabs.

**Chat completions:**

- `input_audio` and inline `file` parts. PDF and other files arrive as
  `file_data`; a `file_id` is refused.
- `modalities` and `audio`, for audio output.
- The fifteen missing fields, each **carried to a backend that
  advertises it and routed around one that does not**. That is A2's
  caller-settings mechanism, unchanged, fed by per-model
  `supported_parameters`.
- Routing extends A4's rule: a request with audio or a file routes only
  to a model whose `inputModalities` confirm it, and a request for audio
  output only to one whose `outputModalities` do.
- **This slice is what brings Lyria's music in (0.3).**

**Responses:**

- `input_file` inline, the four missing fields, `input_tokens`, and
  `compact`.
- `/v1/responses/input_tokens` is in b11076's route list (0.5), so a
  local answer exists.
- **Client-run tool types** (`custom`, `shell`, `local_shell`,
  `apply_patch`, `computer`) are carried to any backend that accepts
  them. The model emits the call and the harness runs it, so nothing
  executes inside Eugene. Where a backend only takes `function`, the
  request is routed around it, which is A2's mechanism again.
- **Server-run tools** (call #8):
  - **Forwarded** to a backend that runs them natively.
  - **Run by Eugene itself** for a model whose backend cannot, once the
    tool framework (P8) exists.
  - **Refused** until then.

**Anthropic messages:** `document` blocks, translated to the file part.

**Audio:**

- **`/v1/audio/speech`:** backends are OpenAI, OpenRouter's 21 speech
  models, ElevenLabs through a new `elevenlabs_http` engine, and any local
  OpenAI-shaped speech server. The response is **binary**, streamed.
- **`/v1/audio/transcriptions`** and **`/translations`:** **multipart
  upload**. Backends are OpenAI, OpenRouter's 24, ElevenLabs
  speech-to-text, and `llama-server`.
- **Voices** are listed on `GET /v1/models` as `x_eugene_plexus.voices`
  for each speech model, not on an invented endpoint. OpenAI has no
  voice-list endpoint, and `Model` already carries our extension object.

**Images:** `/v1/images/generations`, `/edits` (JSON or multipart) and
`/variations`. Backends are OpenAI and OpenRouter's 57 models. A partial
image in an SSE stream is the commit point, as a token is for chat.

**Videos** (call #5):

- `POST /v1/videos` submits a job; `GET` polls it; `/content` streams
  the bytes back.
- The job id Eugene returns **encodes the backend and the calling key**,
  signed, so a poll reaches the backend that owns the job and no other
  key can read it. **There is no new store**, so `GET /v1/videos`, which
  lists a key's jobs, is refused until the platform half supplies one
  (§5, #5).
- Backends: OpenAI, and OpenRouter's 29 video models.

**Small ones:** `/v1/moderations` (an OpenAI account; OpenRouter answers
404), `GET /v1/models/{model}`, and `/v1/completions` (call #6).

**Realtime:** its own design (call #7).

**Carried across every new door:**

- **Transport.** Gateway → driver is JSON and SSE today. The new doors
  need multipart request bodies and streamed binary responses, with
  per-door size limits: the 16 MiB JSON limit stands, and audio uploads
  need their own. The agent's browser proxy needs the same for the
  playground. Buffering is measured by a clock, not a frame count, which
  is the M10 and proxy-move lesson.
- **The failover rule per door** (call #4):
  - **Speech: same model only.** A voice-over whose voice changes
    between two clips is embeddings' noise problem in another form.
  - Transcription and images: tiers, as chat.
  - Video: at submit only.
- **URLs are never fetched,** which is A4's rule extended. `file_url`,
  image URLs on edits and a video `input_reference` by URL are refused;
  inline bytes only.
- **Metrics units per door:** characters, audio seconds, image count and
  video seconds beside tokens. This means gateway metrics schema v6, and
  it is the same plumbing a spend limit will read later.
- **Surfaces.** `ModelRoutingInfo.surfaces` grows the new surfaces, and
  `/v1/models` says which door each model answers on.

## 3. Phase 2: the survey, afterwards

**The survey, taken after phase 1 lands:**

- **ElevenLabs:** sound effects, music with composition plans, dialogue,
  stem separation.
- **OpenRouter's extensions past OpenAI's shape:** video input parts, and
  image output on chat.
- **Whatever local engines serve by then.**

**Troy's rule governs it:** where a standard shape has appeared, use it.
Where none has, decide then between a translated door, a passthrough, or
waiting. Music and sound effects are one shape, so they are one decision,
not two.

**For the video job:**

- **Phase 1 carries** the voice-over (speech), music (Lyria through
  chat), stills (images), clips (videos), and the harness's own model
  (`/v1/messages` through an OpenRouter account).
- **Only the sound effects wait for phase 2.**

## 4. Slices, in order

Each slice opens with a check that fails before the change and passes
after it.

| Slice | Content | Done when |
|---|---|---|
| **P1** | Account driver: contract (`models[]` replacing `modelId`, `model` on requests), driver catalogue and filters, gateway `(node, driver, model)` routing, glob `allowedModels`, the add-account UI, the older-driver Issue | One OpenRouter driver process serves completions from two different models. A key scoped `openrouter/*` sees those and nothing else. An Ollama account lists every pulled model. A pre-P1 driver on another node is named in Issues with its node, and is not silently absent. |
| **P2** | Chat, responses and messages data types: audio in and out, inline files and documents, the missing fields, modality-aware routing, `input_tokens`, `compact` | An audio question and a PDF question are answered through chat. Lyria returns music through chat. A text-only backend is routed around, not sent the audio. |
| **P3** | Speech, transcription and translation; the `elevenlabs_http` engine; multipart and binary transport; metrics units; the same-model rule for speech | ElevenLabs speaks through `/v1/audio/speech` from the OpenAI SDK unchanged. `llama-server` transcribes locally. Nothing buffers, measured by clock. A speech failover never changes voice. |
| **P4** | Images: generations, edits, variations | The same SDK call works against OpenAI and OpenRouter; a URL input is refused. |
| **P5** | Videos, with signed job handles | A job submitted through one gateway is polled and downloaded through it. Another key's poll is refused. A restart loses nothing. |
| **P6** | Moderations, `GET /v1/models/{model}`, `/v1/completions` | As each door's contract says. |
| **P7** | Realtime | Its own design first. |
| **P8** | Server-run tools, as a **modular framework**, starting with `image_generation` and `web_search`. May start once P4 lands; it is independent of P5–P7. | Its own design first (below). Then a local model on `/v1/responses` asks for a search and an image, Eugene runs both, and the model answers with them. The same model with `web_search` on an OpenAI account is forwarded, not run twice. |

**P8 needs its own design before code.** Troy's brief: start with image
generation and web search, and stay open to every future kind of tool.
The questions it must answer:

- **Where tools live.** The generative rule (new responsibility = new
  component) points to a **tool driver** per tool provider, a sibling of
  the inference-driver, with the gateway running the loop. The
  alternative is a plugin registry inside the gateway. The design's
  first call.
- **One declaration per tool across three doors.** For example, web
  search is `web_search` on Responses, `web_search_options` on chat, and
  Anthropic's server `web_search` tool on messages.
- **Side effects end failover.** A tool Eugene has executed is a side
  effect, so the commit point moves to the first execution.
- **Local-only keys** must refuse a tool whose execution leaves the
  machine. A search query is derived from the prompt.
- **Permissions and accounting.** A per-key tool scope beside
  `allowedModels`, per-execution metrics rows, and `max_tool_calls`
  enforced.
- **Streamed tool items.** The stream carries each call as it runs, for
  example `web_search_call` in Responses events.
- **The search provider** is a new kind of account (SearXNG, Brave,
  Tavily, …). **`image_generation`** calls Eugene's own images door.

## 5. Calls for Troy

**Taken 2026-09-26 (Troy):** #1, #2, #4, #5, as recommended.

**#1 carries three rules that come with the prefix:**

- **An account's name is fixed once it exposes models.** Renaming it
  would rename every model id, and with them every client config, slot,
  `allowedModels` entry and metrics series. So a rename is a new account
  and says so.
- **Existing single-model drivers keep their bare ids.** Only a driver
  that reports `models[]` is prefixed, so no installed client's model
  name changes under it.
- **Model ids contain slashes.** `GET /v1/models/{model}` and every
  route that takes an id in its path must accept them, as OpenRouter's
  own routes do.

The same `provider/vendor/model` form is what OpenClaw and other
multi-provider clients already use.

**#5's consequence:** with no store, `GET /v1/videos` (list my jobs)
cannot be answered per key. The upstream account's list is every key's
jobs together. The list is refused until the platform half supplies a
store. Create, poll, download, remix and delete all work from the handle
alone.

| # | Question | Recommendation | Against it |
|---|---|---|---|
| 1 | Model ids from an account: `<account>/<upstream id>`, or bare upstream ids? | **TAKEN: prefix.** Collisions become impossible, and one model through two providers stays two backends, which it is. | Longer ids. A client with a hardcoded name needs a slot to alias it, which is what slots are for. |
| 2 | What an aggregator account exposes by default | **TAKEN: everything** (all 628 on OpenRouter). The operator added the account to use it, and a client key's scope already narrows what each app sees. | 628 entries in `/v1/models` and in every picker until filtered; search is required, not optional. |
| 3 | Keep `modelId` beside `models[]`? | Recommended keeping it. **TAKEN: replace it.** P1 moves driver, gateway and UI in one bump, and an older driver on another node is named as an Issue (§2.1). | Old drivers on not-yet-upgraded machines stop routing until upgraded. |
| 4 | Failover for speech | **TAKEN: same model only**, like embeddings. | An outage of one TTS model is an outage, not a fallback. |
| 5 | Video job state | **TAKEN: a signed handle, no store**: it survives a gateway restart and needs no database. | A handle is opaque and long, and revoking a key cannot recall one already issued, only refuse its next poll. |
| 6 | `/v1/completions` | **TAKEN: in phase 1 (P6)**, under the new direction. This supersedes `responses-and-completions.md` §2's *not yet*. The capture of a real IDE client doing fill-in-the-middle is still owed before P6 starts. | Legacy upstream; OpenAI lists three models for it. |
| 7 | Realtime | **TAKEN: its own design, after P5.** It is WebSocket, WebRTC and SIP, and no gateway path here carries any of them. | The voice-agent use case waits longest. |
| 8 | Server-run tools on responses (`web_search`, `file_search`, `code_interpreter`, `image_generation`, remote `mcp`) | Recommended forwarding only. **TAKEN: Eugene runs some itself**, through a modular framework, starting with `image_generation` and `web_search`, and open to every future kind of tool. Still forwarded where the backend runs one natively. This is slice P8, with its own design. | A tool executor inside the install is a new responsibility with side effects, egress and permissions of its own. |
| 9 | Driver-internal contract for media | **TAKEN: normalised**, with the driver translating. | More contract than mirroring OpenAI, but mirroring cannot front ElevenLabs. |

## 6. Measurements owed before building

**Taken 2026-09-27** except the video job and the local engines:
[`provider-accounts-measurement.md`](../acceptance/provider-accounts-measurement.md).
The ones that change this design: a driver reads
`/models/user?output_modalities=all` (the account's own 625), not
`/models`; an alias answers with its target's id; OpenRouter has no
`GET /models/{id}`; Lyria's music needs `stream: true` and arrives as one
~1 MB SSE event; image output on chat is an OpenRouter-only
`message.images[]`; and speech defaults to `pcm`, not `mp3`.

- **OpenRouter, authenticated** (needs Troy's key; pennies):
  - the speech response format;
  - the video job lifecycle, and whether `/content` redirects to a CDN,
    which matters to a proxy;
  - Lyria's audio-output shape in chat;
  - the image+text output shape.
- **A real client per new door, captured the way R4 captured Claude
  Code.** The OpenAI SDK for each; Open WebUI's voice mode for speech and
  transcription is a candidate, unverified.
- **Local speech and image engines:** which ones speak OpenAI's shapes
  (speaches, Kokoro-FastAPI, stable-diffusion.cpp), installed and
  captured.
- **`llama-server` b11076's `/v1/audio/transcriptions`:** exercised, and
  with which models. §0.5 found the route string, not a response.

## 7. P1's own calls, 2026-09-27

Building P1 raised four questions the design had not answered. **Troy took
all four as recommended:**

| # | Question | Taken |
|---|---|---|
| P1-1 | Who applies the `<account>/` prefix? | **The gateway**, from the driver's name as it was added (its component name). A driver stays unaware of its own name. Names cannot be renamed, so "fixed once it exposes models" holds without a rule. **The same name on two machines is one account served from both**, a replica per model, as same-named local models already are. |
| P1-2 | How a driver becomes an account, and which backends | **An OpenAI-compatible driver with no model set is an account** and exposes its catalogue, prefixed. A driver with a model set works exactly as before, with its bare id. In P1 for every OpenAI-compatible provider: OpenRouter, OpenAI, xAI, Ollama, LM Studio and custom (which covers `llama-server`'s router mode). The Claude and Codex subscriptions and System One stay single-model **for now**. |
| P1-3 | Per-model capabilities where a provider's list says nothing | **The provider's own listing where it says it** (OpenRouter's catalogue; Ollama's and LM Studio's native model information). **Elsewhere each model inherits the driver-wide answer given today**, and image input stays re-checked per request. No shipped table, no per-model probes. |
| P1-4 | Models whose only use has no door yet | **Listed on `GET /v1/models` once a door serves them.** Chat, embeddings and decision models appear now; speech, image, video and transcription models appear as P3-P5 add their doors. The driver reports them all, so no id changes later. |

**Taken without a separate call, because each follows from a rule already
held:**

- **An older driver** (one reporting the single `modelId`) is listed with its
  machine in the gateway's routing view, and an Issue says to update that
  machine. The gateway never sends `model` to it: an older driver ignores
  unknown fields and would answer with its one model.
- **The catalogue** is read at start and then hourly (configurable). A failed
  read keeps the last good list, saved beside the driver's config so a
  restart with the upstream down still serves it, and the reason is on
  `/v1/info` (R2.1's lesson).
- **A model that leaves the catalogue** is deleted from nothing: slot tiers
  and key scopes keep it, it reads *nothing serves this* as an unlaunched
  model does, and an Issue names it.
- **Cooldown is per model**, not per account.
- **Globs in `allowedModels`:** `*` is the only wildcard and matches across
  `/`. One matcher, in the gateway, the agent and the control root.
- **Metrics:** each attempt records its model (schema v6).
- **OpenRouter's `provider.require_parameters: true`** is sent whenever a
  request carries settings, because §0.3's per-model parameter list is a
  union over providers, and A2 forbids a setting being silently dropped.
- **A new `string_list` config value type** carries the include/exclude
  patterns, rather than a comma-separated string.

## 8. P2's own calls, 2026-09-28

Troy took all three as recommended.

| # | Question | Taken |
|---|---|---|
| P2-1 | A non-streamed answer asks for mp3, opus, flac or aac audio, but the backend streams audio only as pcm16 (every OpenRouter audio model, measured) | **Refused**, with a 400 naming `wav` and `pcm16`, which are served by streaming pcm16 upstream and wrapping a WAV header when `wav` was asked. No transcoder is added now; one can come with P3's speech door. |
| P2-2 | Lyria answers mp3 whatever format was asked | **Returned, and labelled truthfully**: `message.audio` gains `format`, read from the audio's own header, so mp3 bytes are never presented as wav. |
| P2-3 | Responses tool types other than `function` (`custom`, `shell`, `local_shell`, `apply_patch`, `computer`) | **Deferred together.** They need a driver that speaks the Responses API upstream, which becomes its own slice. P2 keeps refusing them by name. |

**Taken without a separate call, because each follows a held rule:**

- **Consequential settings route around a model that does not list them** (A2):
  `logit_bias`, `logprobs`/`top_logprobs`, `reasoning_effort`, `verbosity`,
  `prediction` and `web_search_options`. **`modalities`/`audio` were on this
  list and came off it when measured (2026-09-28):** no audio-output model on
  OpenRouter lists either as a parameter, so this rule would route them
  nowhere. P2b routes them by `output_modalities` instead.
- **Hints are carried where the backend takes them and dropped elsewhere**, as
  `metadata` and `safety_identifier` already are on chat: `prompt_cache_key`,
  `prompt_cache_retention`, `prompt_cache_options`, `safety_identifier` and
  `service_tier`.
- **`functions`/`function_call`** are translated to tools and back again,
  because a client that sends the deprecated shape reads the deprecated answer.
- **Inline media stays inside the 16 MiB body:** at most 10 MiB for one audio
  clip or file, and 11 MiB across all attachments, decoded. (Written as 12
  here first; 12 MiB grows to 16 MiB in base64, which no body could carry
  alongside its JSON, so the limit could never have bound.) A `file_id`, a URL
  and an assistant turn's `audio: {id}` are refused, since each names a store
  Eugene does not have.
- **`/v1/responses/input_tokens`** is counted by the backend, the way
  `/v1/messages/count_tokens` already is. **`/v1/responses/compact` is
  deferred:** OpenAI's compaction returns an item no other backend can read back.

**P2 is built in three parts**, each landing on its own:

| Part | Content | State |
|---|---|---|
| **P2a** | Attachments in: `input_audio` and `file` on chat, `input_file`/`input_audio` on Responses, `document` on Messages; routing by `audioInput`/`fileInput` | **Built 2026-09-28** (specs `6ac2761`, driver `e231aaf`, gateway `de7a65f`). Acceptance, live OpenRouter run and sabotage pass done; both installers pin driver `934d824` and gateway `ba25538`. |
| **P2b** | Audio out: `modalities` and `audio` on chat; streamed pcm16 assembled for a batch answer, WAV-wrapped when `wav` was asked (P2-1); Lyria's mp3 labelled by its header (P2-2); routing by `outputModalities` | **Built 2026-09-28** (specs `060f516`, driver `429d0d0`, gateway `e44b88b`). Acceptance, live OpenRouter run and sabotage pass done; both installers pin driver `429d0d0` and gateway `e44b88b`. Routing keys on `output_modalities` because no audio model lists `modalities` or `audio` as a parameter (measured). |
| **P2c** | The missing fields (the list above) and `/v1/responses/input_tokens` | **Built 2026-09-28** (specs `8ee10cf` and `eca5391`, driver `8390004`, gateway `2977f8b` and `fa81fca`). Acceptance, live OpenRouter run and sabotage pass done. The acceptance run found that sending `parallel_tool_calls: false` for the old `functions` routed them to 12 of 455 models; it is not sent. |

## 9. P3's own calls, 2026-09-28

Measured first:
[`provider-accounts-measurement.md`](../acceptance/provider-accounts-measurement.md)
§3 and §8. Troy took two of four as recommended.

| # | Question | Taken |
|---|---|---|
| P3-1 | The ElevenLabs key speaks but lacks `speech_to_text`, `models_read` and `voices_read` | **ElevenLabs transcription is deferred.** In P3, ElevenLabs is speech only; transcription goes to OpenRouter and `llama-server`. |
| P3-2 | What an ElevenLabs driver offers when its key cannot list models or voices | **Require the permission** (not as recommended, which was a built-in model list). No model is offered until the key can read `/v1/models`, and `/v1/info` names `models_read` as the reason. Voices are listed when `voices_read` allows and are passed through either way (P3-3). |
| P3-3 | A client sending OpenAI's default voice (`alloy`) to a backend that does not know it | **Pass voices through**, as recommended. The voice is the provider's own id. `x_eugene_plexus.voices` lists each model's voices where the provider says, and an unknown voice is the provider's 400, relayed naming it. |
| P3-4 | `/v1/audio/translations`, which only OpenAI's own API serves, with no OpenAI key to verify it | **Deferred** (not as recommended, which was to build it unverified). The door answers 400 saying no backend here translates. |

**Consequence of P3-2 for the done-when:** "ElevenLabs speaks through
`/v1/audio/speech` from the OpenAI SDK unchanged" can be run live only with a
key that has `models_read`. Until then that half is proven against a fixture
playing ElevenLabs' measured API.

**Taken without a separate call, because each follows a held rule or a
measurement:**

- **Speech failover is same-model only** (§5, #4), as embeddings' is. A slot's
  other targets are never used for speech.
- **Speech formats:** each backend is asked for what it can make.
  - OpenRouter makes `mp3` and `pcm` (measured). ElevenLabs makes mp3, pcm and
    opus on this plan. OpenAI's API makes all six.
  - `wav` is `pcm` with a header wherever `pcm` exists, as P2b does.
  - Anything else is a 400 naming what that model can make, never a transcode.
- **The default format is `mp3` and is always sent**, because OpenRouter's own
  default is `pcm` (measured) where OpenAI's is `mp3`. A client that relies on
  the default gets what OpenAI promised it.
- **`stream_format: "sse"` is refused**; the body is streamed raw bytes, and a
  first byte is the commit point.
- **Transcription formats:**
  - `json` everywhere.
  - `text` rendered by the gateway from the JSON, since llama-server refuses
    `text` (measured).
  - `verbose_json` carried to a backend that makes it; a backend's refusal is
    relayed.
  - `srt` and `vtt` refused.
- **`llama-server`'s Qwen3-ASR preamble** (`language English<asr_text>…`) is
  parsed by the driver into `language` and the text. The same model on
  OpenRouter answers without it (measured), so the prefix is llama.cpp not
  parsing its own output.
- **Uploads are at most 25 MiB**, OpenAI's limit, on the multipart doors only.
  The 16 MiB JSON limit stands everywhere else.
- **Metrics units:** characters for speech, audio seconds for transcription
  where the backend reports them.

**P3 is built in two parts:**

| Part | Content | State |
|---|---|---|
| **P3a** | `/v1/audio/speech`: OpenAI-shaped speech through accounts (OpenRouter's 21 models, OpenAI) and the new `elevenlabs_http` engine; binary streamed; voices on `/v1/models`; same-model failover | **Built and pinned 2026-09-28** ([record](../acceptance/speech-run.md)). ElevenLabs live waits on a key with `models_read` |
| **P3b** | `/v1/audio/transcriptions`: multipart, through OpenRouter's 24 models and `llama-server`; `/v1/audio/translations` refused (P3-4); metrics units | **Built and pinned 2026-09-28** ([record](../acceptance/transcription-run.md)) |

## 10. P4's own calls, 2026-09-28

Measured first:
[`provider-accounts-measurement.md`](../acceptance/provider-accounts-measurement.md)
§9. Troy took two of four as recommended.

| # | Question | Taken |
|---|---|---|
| P4-1 | `response_format: "url"`, with no store to host a URL | **Ignored, answered `b64_json`** (not as recommended, which was a 400). OpenRouter does the same, and OpenAI's GPT image models always answer base64. |
| P4-2 | `/v1/images/variations`, which only OpenAI's `dall-e-2` serves, with no OpenAI key to verify it | **Refused**, as recommended and as translations are (P3-4): the door answers 400 saying no backend here makes variations. |
| P4-3 | `stream: true` for a model that cannot stream (47 of OpenRouter's 55, which silently answer JSON) | **Routed only to a model that streams** (not as recommended, which was a single `completed` event built from the batch answer). A streamed request is A2's setting: the 8 that stream take it, and where none can, the 400 names `stream`. |
| P4-4 | OpenRouter's own `aspect_ratio`, `resolution` and `seed` | **Not in P4**, as recommended; §3's survey decides extensions. OpenAI's `size` already reaches OpenRouter's models, which translate it (measured). |

**Taken without a separate call, because each follows a held rule or a
measurement:**

- **An edit is a generation with reference images.** The driver-internal
  contract is one `ImageRequest` (call #9, normalised) with `references` and
  `mask`. OpenRouter is asked on `/images/generations` with
  `input_references` objects (its only edit route, measured); OpenAI on
  `/images/edits` in the multipart form its SDK uses.
- **The door takes OpenAI's two edit forms:** multipart (`image`, `image[]`,
  `mask`, which is all the SDK sends) and JSON (`images[].image_url`,
  `mask.image_url`). **A URL is refused** (A4's rule), and so is a
  `file_id`, which names a store Eugene does not have; a `data:` URL is
  inline bytes and is taken.
- **An image's type is read from its bytes** (PNG, JPEG, WebP, GIF), never
  from its part header: the SDK labels a `BytesIO` `application/octet-stream`
  (measured). Anything else is a 400 before any backend is asked.
- **Settings are routed by the model's own listing, and the listing is read
  where it exists** (OpenRouter's `/images/models`; the main listing says
  nothing about images, measured):
  - A setting the listing names is **enforced**: `n`, `quality`,
    `background`, `output_format`, the number of reference images, and
    `stream` (P4-3). A model whose listing names none of `quality` or
    `background` does not take them: flux answered an opaque JPEG for
    `background: transparent` with a 200 (measured), which is the silent
    drop A2 forbids.
  - **`output_format` where the listing does not name it is carried**,
    because gpt-image-1-mini honours it unlisted (measured), and **the
    answer is labelled by its bytes**, P2-2's rule: `output_format` in the
    answer is what the image is.
  - **`mask` routes only to OpenAI's own API**; OpenRouter ignores it
    (measured).
  - `size` is carried everywhere: no model lists it and OpenRouter translates
    it.
  - Hints are carried and dropped where not taken: `output_compression`,
    `moderation`, `style`, `input_fidelity`, `partial_images`, `user`.
  - **An OpenAI account's image models have no listing**; its API checks
    its own fields, so they are carried and its refusal is relayed (P1-3's
    inherited answer). Only `stream` is known per id: OpenAI streams GPT
    image models, not `dall-e-*`.
- **Five OpenRouter models require a reference image** (`min: 1`); a
  generation routes around them.
- **Image+text models answer on the images door too** (gemini flash-lite
  image returned one image, measured), so they carry `image` beside `chat`.
- **Failover: tiers, as chat** (§5, #4). **A streamed request's first event
  is the commit point.**
- **Uploads are at most 25 MiB decoded across all images**, the transcription
  door's limit, and 16 images, OpenAI's.
- **The answer is OpenAI's shape** whatever the backend: `created` is the
  gateway's clock where the backend says 0 (flux and gemini, measured);
  usage is `input_tokens`/`output_tokens`; stream events carry every field
  OpenAI's schema requires, which OpenRouter's omit.
- **Metrics units:** the image count beside tokens (schema v8).

**P4 is built in one part** (specs `8455ff2`, driver `e484972`, gateway
`6be3f0a` and `3e54fbb`), pinned in both installers; record
[`images-run.md`](../acceptance/images-run.md).

## 11. P5's own calls, 2026-09-28

Measured first, with Troy's $10 for test videos ($0.102 spent):
[`provider-accounts-measurement.md`](../acceptance/provider-accounts-measurement.md)
§10. **OpenAI shut its video API down on 2026-09-24** (`sora-2` and
`sora-2-pro` carry that `shutdown_date`; `/v1/videos` answers an empty 404),
so OpenRouter is the only live video backend. OpenAI's shape is still the
standard the SDK's `client.videos` speaks, so the door is OpenAI's and the
driver translates to OpenRouter's. Troy took three of four as recommended.

| # | Question | Taken |
|---|---|---|
| P5-1 | OpenAI's `seconds` is Sora's `4`/`8`/`12`; OpenRouter's models each list their own (grok 1-15) | **Any whole number of seconds a model lists**, as recommended: routed by the model's listing (A2), a 400 naming `seconds` otherwise. |
| P5-2 | Remix, edits, extensions and delete, which only OpenAI's shut-down API served (OpenRouter has none) | **Not routed** (not as recommended, which was a 400 saying why): they answer as any unknown path does. |
| P5-3 | Who may poll a job an operator session made, when sessions rotate at every sign-in | **Any operator session of the install**, as recommended. A client key's job is readable only with that key. |
| P5-4 | What signs the job handle | **The gateway's own secret file**, as recommended: made once, owner-only, kept beside its config. A restart keeps it; a reinstall makes a new one and older handles read as not found. |

**Taken without a separate call, because each follows a held rule or a
measurement:**

- **The handle is the job** (call #5): `video_` and a signed payload naming
  the driver, its node, the model, the upstream job, the owner, and the
  `seconds` and `size` asked for. OpenRouter's poll carries none of those
  last two and OpenAI's `VideoResource` requires them. `prompt` is not kept,
  and is `null` on a poll, as OpenAI's schema allows.
- **`GET /v1/videos` is refused** with a 400: with no store, one key's jobs
  cannot be told from another's (call #5).
- **Failover at submit only** (§5, #4): a submit walks the slot's tiers; an
  accepted job is bound to its backend for life.
- **Settings route by the model's listing**, which on OpenRouter is only
  `GET /videos/models` (the images rule, P4): `seconds`, `size`, and an
  `input_reference` only to a model that takes a first frame. The listing is
  supplementary: a failed read of it must not unroute the account.
- **`input_reference` is inline only** (A4): a file upload or a `data:` URL;
  another URL and a `file_id` are refused. It becomes OpenRouter's
  `frame_images` first frame.
- **`variant` other than `video` is refused**: OpenRouter ignores it and
  answers the MP4 (measured), which a caller asking for a thumbnail would
  save as one.
- **Status is OpenAI's words**: OpenRouter's `pending` is `queued`.
  `progress` is 0 until the job ends and 100 when it completes, since
  OpenRouter reports none. A failure's `error` is OpenAI's
  `{code, message}`, with the provider's own words.
- **An OpenAI account stops listing a model past its `shutdown_date`** (the
  two Sora models today): it can serve nothing.
- **Metrics units:** the seconds of video asked for, on the submit's row
  (schema v9).

**P5 is built in one part** (specs `c09b264`, driver `c9e0dcb`, gateway
`ccfaa7c`), pinned in both installers; record
[`videos-run.md`](../acceptance/videos-run.md).
