# A Gemini API door: the first measurement

**Status:** CLI measured 2026-10-20; Python SDK measured 2026-10-22.
Row 58's contract is prepared; the gateway implementation follows its specs pin.
**Issue:** gateway#5.

gateway#5 asked for a measurement before any code: does a client built on Google's SDK accept
another base URL, and what does it send? The CLI measurement is below;
section 4 adds the Python SDK capture required by row 58a.

## 1. What was measured

- **Client:** Gemini CLI **0.64.0** (`npm i @google/gemini-cli`). It uses `google-genai-sdk/1.30.0`.
- **Where it ran:** Windows, a throwaway home folder, and a fake key.
- **Its settings:** API-key auth, with usage statistics off. A headless run also needs
  `GEMINI_CLI_TRUST_WORKSPACE=true`.
- **What it was pointed at:** a capture listener (`scratchpad/gemini-cli/capture.py`, not kept).
  The listener records each request and answers as Gemini's API does.

```
GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8553 GEMINI_API_KEY=... gemini -p "Say hi"
```

## 2. What it found

- **The base URL can be changed:** `GOOGLE_GEMINI_BASE_URL` sends every model request to it. So
  the door has a client on day one. The answer from the capture ("Hi from the capture.") was
  printed as Gemini's.
- **The key arrives as a header, `x-goog-api-key`**, never as `?key=`. The paths are under
  `/v1beta`.
- **One prompt made six requests:**
  1. **A routing classifier**, `POST /v1beta/models/gemini-3.5-flash-lite:generateContent`. It is a
     structured-output call: `generationConfig.responseMimeType: application/json` with a
     `responseJsonSchema` (`complexity_score`, `complexity_reasoning`). The capture's plain text
     did not parse, so the CLI tried five times, then went on with its default model. A door
     must answer structured output, or the CLI pays five calls a prompt.
  2. **The turn itself**, `POST /v1beta/models/gemini-3.1-pro-preview:streamGenerateContent?alt=sse`:
     - `contents` (text parts) and `systemInstruction`, about 30,000 characters;
     - `tools: [{functionDeclarations: [...]}]` with 8 functions, each with
       `parametersJsonSchema`, not `parameters`. One of them is its own `google_web_search`;
     - `generationConfig`: `temperature 1`, `topP 0.95`, `topK 64`, and
       `thinkingConfig {includeThoughts: true, thinkingLevel: "HIGH"}`;
     - no `toolConfig` and no `safetySettings`.
- **No `models` listing, `countTokens` or `embedContent`** in this run. The model ids are in the
  path, the CLI's own names. A door would map them to Eugene's model ids, or the person names an
  Eugene id with `--model`.
- **Not seen by the capture:** anything the CLI sends to Google's own addresses outside the base
  URL, such as telemetry (it was off here).

## 3. What a design would have to answer (for Troy, when scheduled)

- **Model names.** Gemini CLI asks for `gemini-3.1-pro-preview` and `gemini-3.5-flash-lite` by
  name. Either a mapping from those to Eugene's models, or the person passes `--model <eugene id>`.
- **Structured output** (`responseJsonSchema`) through the door, onto the chat path's
  `response_format`.
- **`thinkingConfig.thinkingLevel`** onto `reasoning_effort`, and `includeThoughts` onto
  returning reasoning.
- **`functionDeclarations` with `parametersJsonSchema`** onto tools, and function-call and
  function-response parts onto tool calls and their results.
- **Streaming as SSE** in Gemini's shape (`?alt=sse`), with `usageMetadata` and `finishReason` in
  its words, as gateway#5's proposed shape says.

## 4. Python SDK capture (row 58a, 2026-10-22)

**Measured, not inferred from Google's reference.** Python **3.12.10**, Windows,
`google-genai` **2.31.0**, installed from a locally cached wheel into
`.codex-tmp/genai-venv/`. The throwaway `ThreadingHTTPServer` listened on
**127.0.0.1:18558**, used a fake key, recorded requests, and served fixture
JSON/SSE. It was shut down after the capture. No gateway, agent, engine,
Google service or real hardware inference ran. The temporary listener and
sanitized capture are `.codex-tmp/capture-genai.py` and
`.codex-tmp/google-genai-capture.json` in the row's workspace, outside the repos.

The SDK accepts a custom origin through `http_options.base_url`:

```python
from google import genai
from google.genai import types

with genai.Client(
    api_key="row58-sdk-capture-fake-key",
    http_options=types.HttpOptions(
        base_url="http://127.0.0.1:18558",
        timeout=5000,
        client_args={"trust_env": False},
    ),
) as client:
    reply = client.models.generate_content(model="fixture/chat", contents="Say hi")
    print(reply.text)
```

The listener's text printed as **"Hi from the Python capture."** The origin
has no `/v1beta` suffix: the SDK adds it by default. Setting
`types.HttpOptions(api_version="v1", ...)` changes every path below to `/v1`;
the same operations passed there. Slashes in `fixture/chat` were preserved
as path segments, so the door must capture the whole model id before the
method suffix.

Every captured request carried **`x-goog-api-key`**, with neither a bearer
header nor a `key` query parameter. Both `user-agent` and
`x-goog-api-client` were `google-genai-sdk/2.31.0 gl-python/3.12.10`.
`timeout=5000` also sent `X-Server-Timeout: 5`. These are observations of this
SDK version; query-key authentication remains part of the door's contract
for other clients, with redaction required on every logging and metrics path.

| SDK operation | Captured request | Fixture result parsed by SDK |
|---|---|---|
| `models.generate_content` | `POST /v1beta/models/fixture/chat:generateContent` | text, usage and actual `modelVersion` |
| `models.generate_content_stream` | `POST /v1beta/models/fixture/chat:streamGenerateContent?alt=sse` | two data-only SSE frames joined to "Hi from the stream." |
| `models.count_tokens` | `POST /v1beta/models/fixture/chat:countTokens` | `total_tokens == 7` |
| `models.list(config={"page_size": 1})` | `GET /v1beta/models?pageSize=1`, then `&pageToken=capture-page-2` | two model names, iteration stops when `nextPageToken` is absent |
| `models.get(model="fixture/chat")` | `GET /v1beta/models/fixture/chat` | `name == "models/fixture/chat"` |

Plain generation, streaming and counting each sent this body:

```json
{"contents":[{"parts":[{"text":"Say hi"}],"role":"user"}]}
```

Structured output and thinking sent the following `generationConfig`.
Both dictionary config and explicitly constructed `GenerateContentConfig`
and `ThinkingConfig` objects produced these same spellings:

```json
{
  "responseMimeType": "application/json",
  "responseJsonSchema": {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"]
  },
  "thinkingConfig": {"include_thoughts": true, "thinking_level": "HIGH"}
}
```

The SDK parsed the fixture's `{"answer":"hi"}` response. Unlike the recorded
CLI's camelCase nested fields, this Python SDK version sent **snake_case
inside `thinkingConfig`**. Its function declarations likewise used
**`parameters_json_schema`** inside camelCase `functionDeclarations`, for
both dictionaries and typed `Tool`/`FunctionDeclaration` objects:

```json
{"tools":[{"functionDeclarations":[{
  "name":"weather",
  "parameters_json_schema":{
    "type":"object",
    "properties":{"city":{"type":"string"}},
    "required":["city"]
  }
}]}],"generationConfig":{}}
```

With automatic function calling disabled, the fixture's function call
parsed as `id="call-capture"`, `name="weather"`, `args={"city":"Eugene"}`.
The next request carried that `functionCall` in a `role:"model"` turn, and
`{"functionResponse":{"name":"weather","response":{"temperature":18}}}`
in a `role:"user"` turn. The SDK helper omitted the response id, so matching
by the preceding call's name is needed. The final fixture text parsed.

**Counting limitation observed in the client:** adding `system_instruction`
and tools through `CountTokensConfig` raised `ValueError` before any HTTP
request: `system_instruction parameter is only supported in Gemini
Enterprise Agent Platform mode, not in Gemini Developer API mode.` This
happened with both API versions. It does not establish a server limitation:
the door contract also accepts raw `generateContentRequest` for counting
the complete translated prompt, including system instructions and tools.

The fixture's first SSE frame had no `finishReason` or `usageMetadata`;
the second carried `STOP` and usage. There were no `event:` lines and no
`[DONE]` sentinel. The SDK accepted these partial frames, so their contract
does not require complete-response fields on every frame.

## 5. Defaults built into the row 58 contract

- **R58-NAMES, default built:** known Eugene ids resolve directly;
  configured Gemini names resolve to their selected model or role;
  otherwise both CLI calls use `role:chat`. `geminiModelNames`, labelled
  **Gemini model names**, is live and editable in the GUI using the existing
  model-slot renderer. `modelVersion` and envelope headers identify what
  actually answered. Model/tool scope and locality limits still apply.
- **The `/v1/models` overlap:** retain OpenAI's `object`/`data` and model
  `id`, adding the Gemini `models` projection and model `name`/metadata.
  Both projections describe the same caller-visible page. Gemini-key
  requests receive Google's error shape; bearer-only catalogue errors
  retain the existing OpenAI shape. `/v1beta/models` always uses Gemini's
  shape. This avoids changing the existing OpenAI discovery response.
- **Thinking budgets:** map to effort as specified in the contract; name
  `thinkingConfig.thinkingBudget` in ignored settings when an exact
  positive budget is reduced to effort. Omitted `includeThoughts` is false.
- **Wire compatibility:** accept both the CLI's camelCase and the Python
  capture's nested snake_case fields. Conflicting spellings are refused
  naming the field; a supported setting must not disappear silently.

These captures establish the client's wire behavior and response parsing.
Phase 2 still needs gateway/driver behavior tests and the row's fixture
acceptance, including query-key redaction. A live run with an actual
provider key and real speech encoders on the target platforms remains
Troy's measurement; these captures do not establish Google's acceptance,
model availability, audio fidelity or hardware performance.
