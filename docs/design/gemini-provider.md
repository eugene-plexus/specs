# A Gemini provider: a Google account of the user's own

**Status:** designed and taken 2026-10-09 (Troy, G1-G4); built and pinned
2026-10-09 against a fixture (`docs/acceptance/gemini-provider-run.md`);
the live run waits for a key. G8, G11 and G13 confirmed by Troy; G5-G7, G9, G10, G12, G14 and G15 are building's calls, for him.
**Issue:** inference-driver#4. The Gemini *door* on the gateway (gateway#5) is
separate. **OpenRouter's Gemini models keep working as they do.**

## 1. What measuring found (2026-10-09, Google's docs)

- **Two APIs.** The native one (`https://generativelanguage.googleapis.com/v1beta`,
  header `x-goog-api-key`, streaming `:streamGenerateContent?alt=sse`) and an
  OpenAI-compatible one (`.../v1beta/openai/`), which Google calls beta and
  which **silently ignores any parameter it does not list**.
- **The model listing** (`GET /v1beta/models`, pages of up to 1,000) gives
  `inputTokenLimit`, `outputTokenLimit`, `supportedGenerationMethods` and
  `thinking`, **but no input modalities**: those come from our own table.
- **Thought signatures.** A Gemini 3 thinking model returns an encrypted
  `thoughtSignature` on its parts; a multi-turn tool conversation must send it
  back on the `functionCall` part, or Google refuses the turn (community
  reports and Google staff; the docs page now redirects). Most apps drop
  unknown fields, so they cannot carry it.
- **Models now:** `gemini-3.5/3.6/3.7/3.8-flash`, `gemini-3.5-flash-lite`,
  `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`; 2.5 is for existing
  users only. Images `gemini-3.1-flash-image` and kin; video
  `veo-3.1(-lite)-generate-preview`; speech `gemini-3.8-flash(-lite)-tts`;
  transcription `gemini-3.5-transcribe`; embeddings `gemini-embedding-001`,
  `gemini-embedding-2-preview`.
- **Limits** are per Google project (RPM, input TPM, RPD), by tier; responses
  do not say the tier. Implicit caching is on for 2.5 and later (at least
  4,096 tokens on 3.x).

## 2. Troy's calls (2026-10-09)

| # | Call | Taken |
|---|---|---|
| G1 | Which API | **The native API**, a new engine (`gemini_api`): everything Gemini offers and no silently ignored setting. (Recommended was the OpenAI-compatible endpoint.) |
| G2 | Thought signatures | **The driver remembers them**: bounded, in memory, by tool-call id, put back when the conversation returns. Lost on a driver restart: Google refuses that one turn, and the driver says why |
| G3 | The first slice | **Everything**: chat (tools, structured output, reasoning, image/audio/PDF/video input), embeddings, image generation, Veo video, text-to-speech, transcription |
| G4 | The free tier's data use | **Say nothing**, as for the other providers |

## 3. The shape

- **One driver per Google account** (P1): `provider: gemini`, engine
  `gemini_api`, an API key sealed in the driver's config like the others;
  every model the key may use, as `<driver>/<model>`.
- **Capabilities from Google's listing**, plus our table for what it does not
  say: methods give the surfaces (`generateContent` → chat, image or speech
  by family; `embedContent`/`batchEmbedContents` → embeddings;
  `predictLongRunning` → video); `inputTokenLimit` → context; `thinking` →
  reasoning effort offered; input modalities by family.
- **Chat**, translated both ways: OpenAI messages to `contents` with
  `systemInstruction`; tools to `functionDeclarations`, `tool_choice` to
  `toolConfig`; `response_format` to `responseMimeType`/`responseSchema`;
  `reasoning_effort` to `thinkingConfig`, thoughts returned as reasoning;
  `usageMetadata` to usage (cached and thought tokens included). A setting
  Gemini cannot honour is refused by the driver, never sent and ignored.
- **Signatures** (G2) on `functionCall` parts are kept by call id and put
  back; a text part's signature is kept with that turn's text where it can
  be.
- **A refusal names its cause:** a blocked prompt or answer gives Google's
  `blockReason`/`finishReason`; 401/403 is the credential; 429 carries
  `Retry-After`; a region refusal says so.
- **Media:** images through `generateContent` with an image response; video
  as the work order the driver already runs (`predictLongRunning`, polled);
  speech through `generateContent` with an audio response (PCM, served as
  WAV); transcription through `generateContent` with audio input.

## 4. Calls building makes (for Troy to confirm)

- **G5:** speech is offered as `wav` (and raw `pcm`) only, Gemini's PCM
  wrapped; other formats are refused rather than converted.
- **G6:** Google Search grounding and code execution are not offered in this
  slice; the gateway's own web search stays the one search.
- **G7:** the signature cache keeps 4,096 calls for 24 hours.
- **G8 (confirmed by Troy, 2026-10-09):** `reasoning_effort` maps to Gemini 3's `thinkingLevel` (`none` →
  `minimal`, the lowest Gemini 3 takes; `xhigh`/`max` → `high`) and to
  2.5's `thinkingBudget` (`none` 0, `low` 1,024, `medium` 8,192, `high`
  24,576, or 32,768 on Pro). Offered only where the listing says
  `thinking`. Thoughts are always asked for, so they come back as reasoning.
- **G9:** an answer Google stops with no text (`SAFETY` and kin) is
  `finish_reason: content_filter`, with Google's reason as the content; a
  blocked prompt is a 400 naming its `blockReason`.
- **G10:** a region refusal ("User location is not supported") is the
  account's, as a refused key is: nothing was done, so the request may go
  to another backend.
- **G11 (confirmed by Troy, 2026-10-09):** an OpenAI `/v1/audio/speech` request that names no format gets
  mp3 where the model makes mp3, and otherwise the model's first format
  (wav for Gemini); one that *names* mp3 on Gemini is refused, naming wav
  and pcm (gateway).
- **G12:** speech `instructions` and `speed` are refused (Gemini takes style
  only inside the text). Image `size`, `quality`, `n` > 1, masks and the
  other OpenAI image settings are refused. Up to 14 reference images.
- **G13 (confirmed by Troy, 2026-10-09):** every Gemini chat model is also offered for transcription (it
  hears audio); Gemma gets no tools or attachments, and its system prompt
  goes in front of the first user turn.
- **G14:** carried: `temperature`, `top_p`, `top_k`, `seed`, `stop`, the
  two penalties, tools and `tool_choice`, `response_format` (as
  `responseJsonSchema`). Refused: `min_p`, `logprobs`, `logit_bias`,
  `verbosity`, `prediction`, `web_search_options`, and an explicit
  `parallel_tool_calls: false`.
- **G15:** a Veo job's id is the base64url of Google's operation name; the
  video is fetched with the key only from Google's API host, and a
  redirect (to its storage) is followed without the key.

**Left for later:** `countTokens` (the driver's token count answers 501),
embedding `dimensions` (the contract carries none), a video part in chat
(the contract has none), signatures on text parts (Google does not enforce
them), Imagen (`:predict`).

## 5. What building found

- **The gateway refused every Gemini speech request that named no
  format.** It always sends OpenAI's default, mp3, and Gemini makes none;
  hence G11.
- **A region refusal read as "outcome unknown".** Google answers it with
  400 `FAILED_PRECONDITION` and no word the taxonomy knew; it is now the
  account's, like a refused key (G10).
- **The video fetch insisted on https**, so the fixture could not serve it;
  the rule is now "the base URL's own scheme, host and port", which is
  what keeps the key with Google.
- **Not confirmed in Google's documentation of 2026-10-09** (pages had
  moved to its Interactions API), so the live run checks them: which
  `thinkingLevel` values each Gemini 3 model takes; whether
  `responseJsonSchema` and `parametersJsonSchema` are accepted everywhere;
  whether the penalties are; the speech request and its
  `audio/L16;rate=24000` answer; Veo's `durationSeconds` type, its
  `image.inlineData` first frame and its answer's fields; the video
  redirect; whether `batchEmbedContents` reports usage; Google's exact
  words for a missing signature.

## 6. Proof

Unit tests against a fixture shaped from the docs; then one live run with
Troy's key (chat with a tool round trip on a thinking model, embeddings, one
image, one short video, one speech clip, one transcription), its cost stated.
