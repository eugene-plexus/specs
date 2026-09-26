# OpenAI inference compatibility, and one driver per provider account

**Status: design, 2026-09-26. Nothing here is built.** §0 is measured.
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

**In:** every operation in the 0.1 table apart from its stateful edges,
and every data type in 0.2.

**Out, and later:**

- The platform half: files, uploads, batches, vector stores, fine-tuning,
  evals, graders, containers, stored chat completions, stored responses
  and conversations, custom voices, video characters. **It is on the
  roadmap after this** (Troy, 2026-09-26).
- **`file_id` inputs** are refused until then, because they name a store
  Eugene does not have.

**Out, as not inference:** assistants and threads (deprecated upstream),
agents, skills, vaults, ChatKit, webhooks, organisation and project admin,
spend alerts, and content-provenance checks.

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
