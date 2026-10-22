# Row 58: a Gemini API door, and the small Gemini items

Lane GW. Low risk (a new door onto the existing path). Sources: gateway#5
("A Gemini API door: generateContent, for clients on Google's SDK"),
inference-driver#7 (Gemini speech in mp3 and opus), `gemini-provider.md`
(calls G1-G6; GEM-x), MRC23 (`dimensions`: "pass it where a driver can
later"), the Anthropic door's R4 measurement as the model for 58a.

## 58a. What clients send (measured; one more, S)

Gemini CLI 0.64.0 was measured on 2026-10-20 (`gemini-door.md`):
`GOOGLE_GEMINI_BASE_URL` redirects it; the key arrives in
`x-goog-api-key`; paths are under `/v1beta`; one prompt makes a
structured-output routing call to `gemini-3.5-flash-lite`
(`responseMimeType: application/json` with `responseJsonSchema`, retried
five times if the answer does not parse) and a streamed turn to
`gemini-3.1-pro-preview` with `functionDeclarations` using
`parametersJsonSchema`, and `thinkingConfig {includeThoughts, thinkingLevel}`.
This row adds the Python `google-genai` SDK's capture (its base URL
option, `?key=` or header, `countTokens`, `models`) to that record.

### Model names (call R58-NAMES)

Gemini CLI asks for Google's model names. The door maps any model name it
does not know to an install role: by default `role:chat` for both the
turn and the routing call, so Gemini CLI works on day one; the response's
`modelVersion` and the envelope headers name the model that answered. The
owner can map names to other models or roles on the gateway's settings
("Gemini model names"). A name that is an Eugene model id is used as it
is (`gemini --model <id>`).

## 58b. The door (M)

- **Paths** (`gateway.yaml`): `POST /v1beta/models/{model}:generateContent`,
  `POST /v1beta/models/{model}:streamGenerateContent` (`alt=sse`), `POST
  /v1beta/models/{model}:countTokens`, `GET /v1beta/models`,
  `GET /v1beta/models/{model}`, and the same under `/v1/`.
- **Keys:** an Eugene client key in `x-goog-api-key` or `?key=` is checked
  like a bearer key on the other doors (a `?key=` is removed from every
  log line and metric).
- **Translated onto the shared path** the other three doors use, so keys,
  routing, model roles, failover, metrics and server-run web search are the
  same:

  | Gemini | Shared path |
  |---|---|
  | `contents[].parts` text, `inlineData` (images, audio, PDF) | messages and content parts, within today's attachment limits |
  | `functionCall`, `functionResponse` | tool calls and tool results |
  | `systemInstruction` | the system message |
  | `tools.functionDeclarations` (`parameters` or `parametersJsonSchema`), `toolConfig.functionCallingConfig` (AUTO, ANY, NONE, `allowedFunctionNames`) | tools and `tool_choice` |
  | `tools.googleSearch` | the hub's web search (as `web_search_options`) |
  | `generationConfig` temperature, topP, topK, maxOutputTokens, stopSequences, seed | the same settings |
  | `responseMimeType: application/json` + `responseSchema` or `responseJsonSchema` | structured output (JSON schema) |
  | `thinkingConfig.thinkingLevel` (LOW, MEDIUM, HIGH) or `thinkingBudget`, `includeThoughts` | reasoning effort, and reasoning returned as `thought` parts |
  | `candidateCount` > 1 | refused, naming it |
  | `safetySettings` | accepted, named in `x-eugene-plexus-ignored-settings` (no safety filter runs locally) |

- **Answers in Gemini's words:** `candidates[0].content.parts`,
  `finishReason` (STOP, MAX_TOKENS, SAFETY never invented), `usageMetadata`
  (prompt, candidates, thoughts, cached tokens), `modelVersion` as the
  model that answered; Eugene's envelope on response headers, as on the
  Anthropic door.
- **Refusals** in Google's error shape (`error.code`, `message`, `status`),
  each naming the field.

## 58c. The small Gemini items (S each)

- **Speech in mp3 and opus** (inference-driver#7): the driver converts
  Gemini's PCM with PyAV (wheels that bundle the encoders on Windows,
  macOS and Linux, x86 and arm), so every format the OpenAI speech door
  names works on Gemini; call G5 is then closed.
- **`countTokens`:** the Gemini provider answers token counts with
  Gemini's own `countTokens` (for the Anthropic door's `count_tokens`, the
  Responses door's `input_tokens`, and the new Gemini door) instead of
  saying the backend cannot count.
- **`dimensions`:** passed to Gemini embeddings as
  `outputDimensionality`; the header stops calling it ignored for Gemini
  (MRC23's "pass it where a driver can").

## Repositories

gateway (the door, translations), inference-driver (58c), specs
(`gateway.yaml` the door's paths and schemas, the measurement record,
acceptance).

## Tests that fail before

- gateway `test_gemini_door.py::test_generate_content_round_trips_text_and_usage`,
  `test_function_calling_round_trip`, `test_stream_is_sse_of_responses`,
  `test_key_in_query_is_checked_and_never_logged`,
  `test_candidate_count_two_is_refused_naming_it`.
- inference-driver `test_gemini_speech.py::test_mp3_and_opus_are_encoded`
  (today: refused naming wav and pcm), `test_gemini_count_tokens.py`,
  `test_gemini_embeddings.py::test_dimensions_reach_gemini`.

## Acceptance (CI, Linux, about 3 minutes)

`specs/scripts/row58-gemini-door-acceptance.py` on row 2's harness with
the fixture backend: the real `google-genai` Python SDK, pointed at the
gateway, runs a chat, a streamed chat, a function-calling round trip,
structured output and `count_tokens`; Gemini CLI's two recorded requests
(the routing call and the streamed turn, from `gemini-door.md`) are
replayed and answered in Gemini's shape, the routing call's JSON parsing
on the first try; a request with `?key=` leaves no key in the gateway's
log or metrics.

## Size and risks

M in total, about 3 days. Risks:
- **Gemini CLI's routing call** retries five times when structured output
  fails to parse; the acceptance runs Gemini CLI's own request shapes from
  the record, so that path is tested.
- **Thinking and safety fields have no exact match locally;** each is
  mapped or named as ignored, never dropped silently.

**Calls:** R58-NAMES (unknown Gemini model names go to the install's Chat
role by default).
