# API compatibility

This describes development builds after A4 implementation, not the frozen `v0.1.0-alpha.1`.
Compatibility means the features below, not every feature of a provider API.

| Surface or feature | Status | Boundary |
| --- | --- | --- |
| `GET /v1/models` | Supported | Eugene's discovered models and routing aliases. |
| `GET /v1/models/{model}` | Supported (P6, since 2026-09-28) | One model as the list shows it to this caller; the id takes the rest of the path, slashes included. A model the key may not use is a 404. |
| `POST /v1/moderations` | Supported (P6, since 2026-09-28) | OpenAI's shape through an OpenAI account's `omni-moderation-*`. `model` may be left out when the key can use exactly one moderation model. Same model only. See [moderations](#moderations). |
| `POST /v1/chat/completions` | Supported | Text messages, tools, structured-output forwarding, batch responses and SSE. Images, audio and PDFs as content parts (see [attachments](#attachments)). A spoken answer with `modalities` and `audio` (see [audio output](#audio-output)). |
| `POST /v1/messages` | Supported subset | Anthropic text, image, document and tool translation; measured Claude Code 2.1.207 shapes remain covered. |
| `POST /v1/embeddings` | Supported | Text inputs; requires an embedding-capable backend. |
| `POST /v1/audio/speech` | Supported (P3a, since 2026-09-28) | Text in, audio bytes out, streamed as made, through OpenRouter's speech models and ElevenLabs. Voices are the provider's own ids. See [speech](#speech). |
| `POST /v1/systemone` | Experimental (B2, not in alpha.2) | TypeSafe System One typed decisions against decision-only backends. See [typed decisions](#typed-decisions-b2). |
| `POST /v1/responses` | Supported subset (since 2026-09-23) | Stateless: text, images, inline PDFs and audio (since 2026-09-28), and function tools, streamed or not. `/v1/responses/input_tokens` counts (P2c). Other tool types (`custom`, `shell`, `local_shell`, `apply_patch`, `computer`) are refused by name. No stored responses (`store`, `previous_response_id`), no server-run tools. See [responses and completions](design/responses-and-completions.md). |
| Provider accounts (P1, 2026-09-27) | Supported | An OpenAI-compatible connection with no model set serves every model its provider lists (OpenRouter, OpenAI, xAI, Ollama, LM Studio, a custom URL), each named `<connection>/<model id>`. A model whose only use has no door here yet (rerank, completion) is not listed on `GET /v1/models`, nor is a model past its provider's `shutdown_date`. See [the design](design/openai-inference-compatibility.md). |
| Client-key model patterns | Supported | `allowedModels` entries may use `*`, which matches anything including `/`: `openrouter/*` allows one connection's models. |
| `POST /v1/audio/transcriptions` | Supported (P3b, since 2026-09-28) | OpenAI's multipart form, through OpenRouter's transcription models, OpenAI's, ElevenLabs' `scribe_*` (P3-1) and a `llama-server` whose projector hears. Tiers as chat. See [transcription](#transcription). |
| `POST /v1/audio/translations` | Supported (P3-4, since 2026-09-28) | The SDK's five fields, through OpenAI's `whisper-*`, the only model that translates. Tiers, holding only translators. See [transcription](#transcription). |
| `POST /v1/images/generations`, `POST /v1/images/edits` | Supported (P4, since 2026-09-28) | OpenAI's shapes, streamed or not, through OpenRouter's image models and OpenAI's. Edits as multipart or JSON with `data:` URLs; a URL or `file_id` input is refused. Every answer is `b64_json`. See [images](#images). |
| `POST /v1/images/variations` | Refused | A 400: only OpenAI's `dall-e-2` makes variations, and this door is deferred (P4-2). |
| `POST /v1/videos`, `GET /v1/videos/{video_id}` and `/content` | Supported (P5, since 2026-09-28) | OpenAI's shape, as jobs, through OpenRouter's video models (OpenAI's own video API shut down on 2026-09-24). The job id is a signed handle: no store, another key cannot read it, a restart loses nothing. See [videos](#videos). |
| Uploaded files, batches, provider storage; video remix, edits, extensions and delete | Not implemented | The platform half of [the design](design/openai-inference-compatibility.md). The video operations only OpenAI's shut-down API served are not routed (P5-2). |
| Content-part input: images, audio, PDFs | Supported subset | Ordered text plus inline PNG/JPEG, WAV/MP3 and PDF on user messages, sent only to backends that confirm that input. See [attachments](#attachments). |
| Tools and `response_format` | Forwarded | Definitions, JSON Schema and `strict` survive the wire. Backend support and schema enforcement vary; Eugene does not execute tools or post-validate output. |
| Reasoning output | Supported | A model's separately reported reasoning (llama.cpp `reasoning_content`, vLLM `reasoning`) is returned as `reasoning_content` on the OpenAI door and as `thinking` blocks on the Anthropic door when the request enabled thinking. See [reasoning](#reasoning). |
| `frequency_penalty`, `presence_penalty`, `top_k`, `min_p`, `parallel_tool_calls`, the `developer` role | Carried | Refused with 400 before 2026-09-23. Backends that cannot take one are routed around; see [chat settings](#chat-settings). |
| `logprobs`, `logit_bias`, `reasoning_effort`, `verbosity`, `prediction`, `web_search_options` | Carried (P2c, since 2026-09-28) | Routed only to a backend whose model lists the setting; with none, a 400 naming it. Log probabilities and web citations come back. See [chat settings](#chat-settings). |
| The deprecated `functions` / `function_call` | Translated (P2c) | Carried as tools and answered in the old shape. |
| `POST /v1/responses/input_tokens` | Supported (P2c) | Counted by a local `llama-server`'s own tokenizer; a hosted provider cannot count and says so. |
| Unknown fields | Rejected | 400 naming the field, including unknown nested message/tool/format fields. |
| All clients, providers and reasoning-token accounting | Unverified | Captured requests test transport semantics; they do not demonstrate every model's behavior. |

## Client authentication

Use a client key from Home's **Use it from your apps** card. Enrolled agents
manage one install-wide registry; all accepting gateways enforce its revocations.
Policy refresh is 15 seconds by default, with a 60-second maximum cache age
(plus up to five seconds clock tolerance). Stale or unavailable policy returns
client-only 503; operator repair access remains available. See
[client keys](client-keys.md) for migration and outage behavior.

## Chat settings

Use either `max_tokens` or `max_completion_tokens` with a positive JSON integer.
Both may be supplied only when their non-null values are equal. A conflict returns
400 naming `max_completion_tokens`; neither spelling overrides the other. Strings,
booleans, fractional numbers, integral floats, zero and negatives are rejected.
Null means unspecified. Normalization happens before routing/profile defaults.
Each fallback attempt retains the explicit limit; omitted limits use that
candidate's model profile, then the gateway's `defaultMaxTokens` (initially 2,048).

`temperature`, `top_p`, `seed`, up to four `stop` strings (or one string), `tools`,
`tool_choice`, `response_format`, `frequency_penalty`, `presence_penalty`,
`parallel_tool_calls` and the local-engine extensions `top_k` and `min_p` are
carried to the driver. Explicit controls are identified separately from inherited
defaults, allowing an adapter to reject a control it knows it cannot honor before
starting work — and a backend that does not advertise one is skipped when choosing
where to send the request. None of the five newer fields has a profile or install
default; an absent one stays absent, and `parallel_tool_calls` most of all, since
llama.cpp assumes false and OpenAI true. Streaming failures after HTTP headers
have been sent use an error frame; clients must inspect it.

A `developer` message is delivered to the backend as `system`, in place.
`reasoning_content` is accepted on an `assistant` message and handed back to the
backend (see [reasoning](#reasoning)); on any other role it is a 400.

`n: 1` and `store: false` are accepted neutral defaults; other non-null values
are refused. `user` and string-valued `metadata` are ignored annotations,
neither stored nor forwarded nor used as authenticated identity. Unknown fields
are refused even when null.

**Since P2c (2026-09-28)**, six more settings are carried, each routed only to
a backend whose model is known to take it: `logprobs` (with `top_logprobs`, up
to 20), `logit_bias`, `reasoning_effort`, `verbosity`, `prediction` and
`web_search_options`.

- An OpenRouter model takes the ones its listing names. On 2026-09-28 that was
  186 models for `reasoning_effort`, 149 for `logprobs`, 141 for `logit_bias`
  and far fewer for the rest.
- OpenAI's own API takes all six. A local engine takes none yet: llama.cpp and
  vLLM document `logprobs` and `logit_bias`, but they are not measured here.
- With no backend that takes one, the answer is a 400 naming it; nothing is
  sent. `logprobs: false` asks for nothing.
- **Listed is not promised.** A provider can still refuse a listed setting
  (OpenAI refuses `web_search_options` for `gpt-4o-mini`), and that is the
  caller's 400 with the provider's words.
- What comes back is OpenAI's shape: `choices[].logprobs`, on each streamed
  frame's choice as well, and `message.annotations` (`delta.annotations` when
  streamed) for a web search's `url_citation`s.

`prompt_cache_key`, `prompt_cache_retention`, `service_tier` and
`safety_identifier` are hints. They are carried to OpenAI's own API and dropped
for every other backend, and never restrict routing.

The deprecated `functions`, `function_call` and `function` role are carried as
tools and answered in the old shape (`message.function_call`,
`finish_reason: function_call`). They are refused together with `tools` or
`tool_choice`. `parallel_tool_calls` is not sent for them, since that would
route only to the few models that list it. If a model makes more than one call,
the first is given.
The gateway does not include prompt content or invalid values in validation errors.

With `stream: true`, `stream_options.include_usage: true` produces a final
usage-only chunk when the driver reports usage. False omits usage. Omitting
`stream_options` preserves Eugene's older final choice chunk containing usage.
This option does not change retained metrics. Token counts are not invented when
a backend supplies none.

## Engines and token accounting

| Adapter/backend | Limit behavior | Other controls |
| --- | --- | --- |
| `openai_compat_http`, local llama.cpp/vLLM or other compatible servers | Sends normalized `maxTokens` as upstream `max_tokens`. | Forwards sampling (including `top_k`, `min_p`, both penalties), stop, tools, `parallel_tool_calls` and response format, and an assistant turn's reasoning as `reasoning_content`. The server validates and enforces what it supports. Measured on llama.cpp b10948; vLLM from its 0.29 source; Ollama's handling of `top_k`/`min_p` unverified. |
| `openai_compat_http`, configured OpenAI endpoint | Sends upstream `max_completion_tokens`. | Explicit `top_k`/`min_p` are refused (OpenAI rejects them); the fixed-temperature model rule also refuses explicit temperature/top-p and both penalties; inherited defaults are omitted. History reasoning is not sent. Other supported fields are forwarded. |
| `claude_code_cli`, `codex_cli` | An explicit limit is refused; these harnesses do not expose this knob through Eugene's adapter. | Explicit sampling (all of it), stop, `parallel_tool_calls` and response-format controls are also refused. Calls without explicit controls retain harness/profile-default behavior; no deterministic sampling or token cap is promised. No reasoning is returned. |

The two public limit spellings express one Eugene generation limit, not two
different budgets. OpenAI documents its completion limit as including reasoning
tokens as well as visible output. That does not establish identical accounting
in local engines or CLI harnesses. No universal visible-output or reasoning-token
cap has been measured here. [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

## Anthropic compatibility concessions

`/v1/messages` requires a positive integer `max_tokens`. It carries text, tool
definitions/results, temperature, top-p, `top_k`, stop sequences and
`tool_choice.disable_parallel_tool_use` into the same routing path. Images
(since 2026-09-23) and `document` blocks (since 2026-09-28: a base64 PDF, or
plain text) are carried to backends that confirm them, including from inside a
`tool_result`. A document by URL or file id, `citations` enabled, hosted tools,
`mcp_servers`, any `output_config` key other than `effort` (structured output's
`format` included) and unknown top-level settings receive explicit refusals. The measured Claude Code request includes `thinking`,
`context_management`, `output_config.effort` and cache hints even when pointed at
local models. `context_management`, `output_config.effort` and cache hints remain
accepted, but **are not enforced**;
`thinking` decides whether reasoning is returned (below), but a `budget_tokens` is
not enforced and `disabled` hides reasoning without stopping the model thinking.
Both streaming and ordinary responses list controls that were not honoured in
`x-eugene-plexus-ignored-settings`. Metadata remains an ignored annotation.
`stop_sequence` names the matched sequence when the backend reports it (vLLM
does; llama.cpp does not, so behind llama.cpp `stop_reason` reads `end_turn`).
When the backend reports cached prompt tokens, they are `cache_read_input_tokens`
and `input_tokens` is the remainder, so the three input fields sum to the prompt.
This is not native Anthropic reasoning, caching or context editing; consumers
requiring those guarantees should not use this compatibility subset. Historical
measurements remain in [the Claude Code capture](acceptance/anthropic-messages-measurement.md).

## Reasoning

A reasoning model's thinking, when its backend reports it apart from the answer
(llama.cpp's default `reasoning_content`, vLLM's `reasoning` with a reasoning
parser), is returned to the caller. Before 2026-09-23 it was discarded, so a model
that thought until `max_tokens` answered with an empty `content`.

- **OpenAI door:** `message.reasoning_content` on a batch response,
  `delta.reasoning_content` frames ahead of the answer on a stream. Absent when
  there was none. Send the assistant message back unchanged and the reasoning goes
  back to the backend, which llama.cpp renders into the prompt for templates that
  keep it (Qwen3, gpt-oss).
- **Anthropic door:** a `thinking` block ahead of the answer, streamed as
  `thinking_delta`, **only** when the request's `thinking` is non-null and not
  `disabled`. `display: "omitted"` — which Claude Code sends on every request —
  returns the block with empty text and the reasoning carried in `signature` as
  `eugene-plexus-reasoning-v1:<base64>`; echoing the block back returns it to the
  model. That signature is Eugene's, not Anthropic's. `redacted_thinking` and
  foreign signatures are ignored.
- **Either door:** reasoning is output, so its first fragment is the streaming
  commit point — no failover after the caller has seen the model think. A driver
  whose `thinkingMode` is `off` returns none. Usage carries
  `completion_tokens_details.reasoning_tokens` only where the backend counts it
  (vLLM); llama.cpp does not, and Eugene does not estimate it.

Update gateway and inference-driver together when adopting A2. Older drivers do
not understand caller-setting provenance. Contract/unit checks and isolated HTTP
acceptance establish forwarding and refusals; live provider enforcement and newer
client versions remain unverified.


## Image input (A4)

Use OpenAI chat user content parts of type `text` and `image_url`, with an
inline `data:image/png;base64,...` or `data:image/jpeg;base64,...` URL. The gateway
never fetches remote URLs, local paths or file IDs. Images on system, assistant
or tool messages, animation, other formats, and explicit `detail: high/low` are
refused. Omitted detail and `auto` are accepted. Text-only arrays are joined in
order; arrays containing images remain structured through every routing attempt.

Limits cover the entire conversation, including images in earlier turns:

- `maxImagesPerRequest` images per request (12 by default, at most 64), each at
  most 5 MiB decoded; 10 MiB decoded total.
- Audio clips and PDFs at most 10 MiB decoded each, and every attachment
  together at most 11 MiB decoded (see [attachments](#attachments)).
- At most 16 million pixels per image and 8192 pixels along either dimension.
- At most 16 MiB for the JSON body, including text and base64 overhead.

The gateway and direct driver validate the file type and image bounds. Invalid
images return a field-specific refusal; oversized HTTP bodies return 413 before
JSON parsing. Image payloads are excluded from driver debug logs and upstream
error excerpts.

`x_eugene_plexus.image_input` on `GET /v1/models` means at least one candidate
confirms vision support. Image requests use only those candidates; text-only
fallbacks are skipped. The driver rechecks the loaded model before forwarding.

## Attachments

Since 2026-09-28 (P2a), chat user messages also take:

- `input_audio`: `{"data": <base64, no data: prefix>, "format": "wav" | "mp3"}`.
  The bytes must match the format (a WAV header, or an ID3 tag or MPEG frame).
- `file`: `{"filename": ..., "file_data": "data:application/pdf;base64,..."}`.
  PDF only. Bare base64 is accepted and sent on as that data URL, because
  OpenRouter refuses anything else. `file_id` is refused: this install has no
  file store.

Each is at most 10 MiB decoded, and all attachments in a request, images
included, at most 11 MiB decoded. That is what fits in the 16 MiB body once
base64 has grown it by a third. `/v1/responses` takes `input_file` and
`input_audio` the same way, and `/v1/messages` takes `document` blocks.

A request is routed only to a backend that confirms every kind of attachment in
it, fallback tiers included. `x_eugene_plexus.audio_input` and `file_input` on
`GET /v1/models` say which models do. An OpenRouter account's models confirm
what OpenRouter's listing says they take. A `llama-server` confirms audio from
its `/props`. No local engine confirms PDFs yet, and neither CLI backend
confirms either. With no confirming backend the request is refused before
anything is sent or woken. `count_tokens` cannot count a request with an
attachment and says so.

Verified live through the gateway on 2026-09-28 against OpenRouter: an MP3
transcribed and a PDF read through chat, a `document` block read through
`/v1/messages`, and a slot whose first tier cannot hear answered from its
second ([record](acceptance/media-inputs-run.md)).
Initially verified capability discovery is the single-model llama.cpp server's
`/props` vision modality plus matching `/v1/models` identity. Other engines and
multi-model endpoints do not yet advertise image input, even if they could
support it outside Eugene. Unknown capability is not a promise.

See [application setup](application-workflows.md) for the named client paths.

## Audio output

Since 2026-09-28 (P2b), `modalities: ["text", "audio"]` with
`audio: {"voice": ..., "format": ...}` asks for a spoken answer. It is
`message.audio` on the answer (`delta.audio` when streamed): `data` is
base64, `transcript` is what it says, and `format` is what the bytes are.
The answer's text is the transcript, and `content` is null.

- **Routed only to a model that speaks:** `x_eugene_plexus.audio_output` on
  `GET /v1/models`, from `audio` in an OpenRouter model's output modalities.
  Fallback tiers included; with none it is a 400 naming that field. No local
  engine or CLI speaks.
- **Formats.** Every audio-output model behind an account answers audio only
  on a stream and only as 16-bit, 24 kHz mono `pcm16` (measured), so that is
  what the backend is asked for. A non-streamed answer takes `wav` (that
  stream with a header) or `pcm16`. A streamed answer takes `pcm16` only, as
  OpenAI's does. `mp3`, `flac`, `opus` and `aac` are refused with a 400
  naming the two that work; nothing transcodes.
- **Labelled truthfully.** Lyria answers MP3 whatever it is asked, and its
  audio comes back with `format: "mp3"`, not as the WAV that was asked for.
  `format` is not an OpenAI field on `message.audio`; it is there because
  OpenAI's shape cannot say this.
- **Nothing stores it.** An assistant message sent back with `audio: {id}`
  is refused; send the transcript as `content`.
- `audio` without `"audio"` in `modalities`, and the reverse, are refused.
- Not on `/v1/messages` or `/v1/responses`.

Verified live on 2026-09-28 against OpenRouter: `openai/gpt-audio-mini`
answered as a WAV that `google/gemini-2.5-flash-lite` then transcribed word
for word, and `google/lyria-3-clip-preview` returned music, labelled `mp3`
([record](acceptance/audio-output-run.md)).

## Speech

Since 2026-09-28 (P3a), `POST /v1/audio/speech` takes OpenAI's body
(`model`, `input`, `voice`, and optionally `response_format`, `speed`,
`instructions`) and answers with the audio as raw bytes, streamed as the
backend makes them. The OpenAI SDKs work unchanged, including
`with_streaming_response`.

- **Backends:** OpenRouter's speech models, through an OpenRouter connection,
  ElevenLabs, through an ElevenLabs connection (a new provider), and OpenAI's
  own API (`tts-1` verified). No local engine speaks yet.
- **ElevenLabs needs a key that can read models** (`models_read`). A key
  without it offers no model, and the connection's `/v1/info` says which
  permission is missing, in ElevenLabs' own words. A key that cannot read
  voices still speaks.
- **Voices are the provider's own ids** and are passed through as sent.
  `x_eugene_plexus.voices` on `GET /v1/models` lists them where the provider
  does, and is absent where it does not, which is not "no voices". A voice the
  provider does not know is its refusal, relayed as a 400 that names it. So
  OpenAI's `alloy` reaches ElevenLabs and is refused there.
- **Formats:** `x_eugene_plexus.speech_formats` lists what each model can be
  given in. OpenRouter makes `mp3` and `pcm`, ElevenLabs `mp3`, `opus` and
  `pcm` on its lower plans, and `wav` is their `pcm` with a streaming header
  written here (24 kHz, 16-bit, mono). Anything else is a 400 naming what
  would work; nothing transcodes. **`mp3` is always asked for when no format
  is named**, since OpenRouter's own default is `pcm`.
- **Refused with a 400 naming the field:** `stream_format: "sse"` (the audio
  itself is streamed), `instructions` to ElevenLabs (which would drop them),
  and speech to a chat model or chat to a speech model.
- **The same model, always.** A slot alias speaks with its first model, and
  its later tiers are never used for speech: a failover would change the
  voice mid-conversation. A replica of the same model (the same connection
  name on another machine) is a failover. After the first byte a failure ends
  the audio.
- **Client keys** apply here as at every other door: allowed models,
  local-only, rate and concurrency limits.

Verified live on 2026-09-28: the OpenAI Python SDK 3.20.0 got
`hexgrad/kokoro-82m`'s speech through the gateway as a WAV, and
`google/gemini-2.5-flash-lite` heard it back. The ElevenLabs key available
cannot read models, so ElevenLabs speaking through the product is proven
against a fixture playing its measured API
([record](acceptance/speech-run.md)).

## Transcription

Since 2026-09-28 (P3b), `POST /v1/audio/transcriptions` takes OpenAI's
multipart form (`file`, `model`, and optionally `language`, `prompt`,
`response_format`, `temperature`, `timestamp_granularities[]`). The OpenAI
SDKs work unchanged.

- **Backends:** OpenRouter's transcription models, and a `llama-server`
  whose projector hears (`/props` reports audio), which is then listed with
  both `chat` and `transcription` surfaces, OpenAI's own API (`whisper-1`
  and `gpt-4o-mini-transcribe` verified), and ElevenLabs' `scribe_*` models
  (P3-1), offered only to a key with the `speech_to_text` permission.
- **ElevenLabs** is asked for no audio-event tags, so its text reads as
  OpenAI's does. It takes no `prompt` and would ignore one, so a prompt is
  refused; it makes no segments, so `segment` timestamps are refused. Its
  words come back as OpenAI's `{word, start, end}`, its language as it names
  it (`eng`), and its audio seconds as the usage.
- **Tiers, as chat.** A slot's fallback tiers are used, holding only
  backends that transcribe. Unlike speech, a transcript from another model is
  still a transcript.
- **Formats:** `json` (the default) and `verbose_json` come from the
  backend; `llama-server` makes `json` only and refuses the other, and that
  refusal is relayed. `text` is rendered here from `json`. `srt` and `vtt`
  are refused.
- **The file is at most 25 MiB**, OpenAI's limit; over it is a 413 naming
  `file`.
- **Refused with a 400 naming the field:** `stream: true` (the answer is one
  JSON document), `chunking_strategy`, `include[]`, speaker labels, unknown
  fields, and `timestamp_granularities[]` without `verbose_json`.
- **`llama-server`'s Qwen3-ASR preamble** (`language English<asr_text>...`)
  is parsed away: the text is the transcript, as it is from OpenRouter.
- **Usage** is OpenAI's: `{"type": "duration", "seconds"}` where the backend
  counts audio, `{"type": "tokens", ...}` where it counts tokens.
- **Metrics:** each row says its door, with characters for speech and audio
  seconds for transcription.

**`POST /v1/audio/translations`** (P3-4, since 2026-09-28) gives the text in
English, whatever was spoken. It takes the OpenAI SDK's five fields (`file`,
`model`, `prompt`, `response_format`, `temperature`); a `language` or
`timestamp_granularities[]` is refused naming it. Only OpenAI's `whisper-*`
translates (its `gpt-4o-*-transcribe` models, OpenRouter and `llama-server`
answer this door 404, measured), so a model with the `translation` surface is
required, and a slot's tiers hold only translators: a model that only
transcribes would answer in the language spoken, with a 200. `verbose_json`
says `task: translate`. Verified live: `whisper-1` translated `tts-1`'s French
as *"The fast brown fox jumps over the lazy dog."*

Verified on 2026-09-28: a real `llama-server` b11235 with Qwen3-ASR 0.6B
transcribed the fox on this machine's CPU in 0.99 s through the OpenAI SDK,
and `openai/whisper-large-v3-turbo` on OpenRouter transcribed speech
`hexgrad/kokoro-82m` had made through the same gateway
([record](acceptance/transcription-run.md)).

## Images

Since 2026-09-28 (P4), `POST /v1/images/generations` takes OpenAI's JSON body
and `POST /v1/images/edits` takes OpenAI's multipart form (`image` for one
image, `image[]` for several, `mask`) or its JSON form (`images[].image_url`,
`mask.image_url`). The OpenAI SDKs work unchanged, `stream=True` included.

- **Backends:** OpenRouter's image models (Gemini's image+text models answer
  here as well as on chat) and OpenAI's `gpt-image-*` and `dall-e-*`.
  OpenRouter has no edit route: an edit reaches it as a generation with the
  images as `input_references`. OpenAI's own API is verified with
  `gpt-image-1-mini`, a masked edit included; `dall-e-*` is not.
- **Tiers, as chat,** each holding only models whose listing takes the
  request. `x_eugene_plexus.image_streaming`, `image_edits` and `image_mask`
  on `GET /v1/models` say what each model does.
- **Settings route by the model's own listing:** a listed `n`, `quality`,
  `background` or `output_format` goes only to a model that takes that value;
  with none in the slot, a 400 names the setting. `auto` asks for nothing. An
  `output_format` a listing does not mention is carried, and the answer's
  `output_format` is what the image is.
- **`stream: true`** goes only to a model that streams partial images (on
  OpenRouter, OpenAI's eight); otherwise a 400 names `stream`. The first
  event is the commit point.
- **`mask`** goes only to OpenAI's own API, which alone honours it.
- **Inputs are inline bytes only:** an `image_url` that is not a `data:` URL,
  and a `file_id`, are refused. An image's type is read from its bytes (PNG,
  JPEG, WebP, GIF). At most 16 images and 25 MiB in all; over it is a 413.
- **Every answer is `b64_json`.** `response_format: url` is accepted and
  ignored: there is nothing here to serve a URL from.
- **Refused with a 400 naming the field:** OpenRouter's own `aspect_ratio`,
  `resolution` and `seed` (use `size`, which reaches every backend), and any
  unknown field.
- **Metrics:** each row counts its images beside the tokens.

`POST /v1/images/variations` answers a 400 saying no backend here makes
variations.

Verified on 2026-09-28 against OpenRouter: `black-forest-labs/flux.2-klein-4b`
made an image through the OpenAI SDK and edited it, and
`openai/gpt-image-1-mini` streamed one ([record](acceptance/images-run.md)).

## Videos

Since 2026-09-28 (P5), `POST /v1/videos` takes OpenAI's body (the SDK sends
multipart; JSON works too) and answers a job; `GET /v1/videos/{video_id}`
polls it and `GET /v1/videos/{video_id}/content` streams the MP4. The OpenAI
SDK's `client.videos.create`, `create_and_poll`, `retrieve` and
`download_content` work unchanged.

- **Backends:** OpenRouter's video models. OpenAI's own video API shut down
  on 2026-09-24; an OpenAI connection no longer lists Sora.
- **The job id is a signed handle.** It names the backend and the key that
  made the job, so a poll reaches that backend, another key's poll is a 404,
  and a gateway restart loses nothing. Nothing is stored; the id is the job.
- **Status is OpenAI's:** `queued`, `in_progress`, `completed`, `failed`,
  with `progress` 0 until the job ends and 100 when it completes. A failure
  carries the provider's reason.
- **Settings route by the model's listing:** `seconds` (any whole number
  the model lists, not only OpenAI's 4, 8 and 12), `size`, and
  `input_reference` (an image file or `data:` URL) only to a model that takes
  a first frame. `x_eugene_plexus.video_durations`, `video_sizes` and
  `video_first_frame` on `GET /v1/models` say what each takes.
- **Failover happens at submit only**; an accepted job stays with its
  backend.
- **Refused:** `variant` other than `video`, `GET /v1/videos` (no store to
  list from), a URL or `file_id` reference. Remix, edits, extensions and
  delete are not routed.
- **Metrics:** each submit's row counts the seconds asked for.

Verified on 2026-09-28: `x-ai/grok-imagine-video` made one second at 480p
from text and one from a first frame through the OpenAI SDK, both polled to
completion after a gateway restart ([record](acceptance/videos-run.md)).

## Moderations

Since 2026-09-28 (P6), `POST /v1/moderations` takes OpenAI's request: the
OpenAI SDK's `client.moderations.create` works unchanged.

- **Backends:** an OpenAI account's `omni-moderation-latest` and
  `omni-moderation-2024-09-26`. OpenRouter has no moderation door (404,
  measured), and no local engine moderates.
- **`model` may be left out**, as the SDK does: the one moderation model the
  key may use answers. With none or several, a 400 names the choices. A slot
  alias does not count as another model.
- **Same model only.** A slot's other targets are never used, since a
  verdict is its model's own categories and thresholds; replicas of the one
  model balance and fail over.
- **`input`** is a string, an array of strings (one result each), or an
  array of parts, `text` and `image_url` (one result). Images are inline
  `data:` URLs, as everywhere (A4); OpenAI moderates at most one per request
  and its refusal of more is relayed. Unknown fields are refused naming them.
- **The answer** is OpenAI's `{id, model, results}`, each result carrying
  `flagged`, `categories`, `category_scores` and
  `category_applied_input_types`. `model` is the public id of the model that
  answered. Each request is retained with `door: moderation`.

Verified live on 2026-09-28: `omni-moderation-latest` flagged *"I will hurt
you."* (violence 0.87) and read an image beside text.

## Typed decisions (B2)

`POST /v1/systemone` accepts the TypeSafe System One request as pinned on
2026-09-22: `model` (an Eugene alias), `state` (string, object or array) and
`questions`, a map of names to `noul`, `choice` or `score` questions. Answers use
TypeSafe's field names, keyed by your question names; `usage` reports
`input_tokens`/`output_tokens` only when the backend reports them. A TypeSafe
client changes its base URL and nothing else. Client keys, revocation, model
scopes, local-only policy and per-key limits apply as on the other doors.
[Design and pins](design/decision-models.md)

Refused before any backend work: more than `decisionMaxQuestions` questions
(gateway config, default 32), a `choice` with other than 1-255 options, a
`score` with other than 2-10 levels, a question field the protocol does not
define, and the shared body-size limit. Malformed questions return 422, as
TypeSafe does.

A backend answer is checked before it is returned: every question answered once
with its own type, choices drawn from the request's options, distributions of
finite numbers in [0, 1] summing to 1, scores inside the scale. Anything else is a
502 naming the defect. Eugene never repairs a decision or substitutes a chat
model prompted for JSON. Probabilities and `confidence` are the provider's own
calibration, not comparable across models.

Non-streaming only. Decision models refuse chat and embeddings with a 400 naming
`/v1/systemone`; chat models refuse decisions with a 400 naming
`/v1/chat/completions`. A deadline that fires is a 504 with an uncertain outcome:
the same decision is **not** re-sent to another backend. A backend that holds one
request at a time answers 503 while busy rather than queueing, and a client that
disconnects does not free it until its work finishes. Disable automatic retries
in any SDK you use; a retried decision is a second decision.

| Backend | Status |
| --- | --- |
| Kev (`jaredpalmer/kev-0.8b`), supervised by the agent | **Measured** on WSL2 CPU ([run](acceptance/decision-run.md)); CUDA, ROCm, Metal unverified |
| Another System One server (`systemone_custom`) | Supported when it passes the answer checks above; see [the recipe](application-workflows.md#register-another-system-one-server) |
| Hosted Jev (`typesafe`) | **Measured** through OpenRouter's System One endpoint, 2026-09-28 ([run](acceptance/decision-run.md#hosted-jev-through-openrouter-2026-09-28), [recipe](application-workflows.md#hosted-jev)); TypeSafe's own endpoint unverified. Always external, refused to local-only keys, never a fallback for a local model |
| Vercel `/v1/evaluate`, AI SDK evaluation | Not implemented — a different dialect |

Decision requests are not yet rows in `GET /v1/metrics`.
