# A Gemini API door: the first measurement

**Status:** measured 2026-10-20. Not designed, and not scheduled.
**Issue:** gateway#5.

gateway#5 asked for a measurement before any code: does a client built on Google's SDK accept
another base URL, and what does it send? This is that measurement, for Gemini CLI.

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
