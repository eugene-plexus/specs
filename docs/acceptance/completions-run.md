# P6b: `/v1/completions`, raw continuation and fill-in-the-middle — record

**2026-09-28 (late). Built, run and pinned in both installers**
(inference-driver `89770ea`, gateway `9ecd3c9`). Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§12, calls P6-3 (no capture: the clients were read in their source) and P6-4
(local engines first). Measured and read first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §12
and §12a.

| Repo | Commit |
|---|---|
| specs (contract) | `8657f60` |
| inference-driver | `89770ea` |
| gateway | `e7cdb07`, pinned at `9ecd3c9` (a flaky test fixed; same code) |

- **`scripts/p6-acceptance.py`** is P6's one gate: 9 fixture checks in specs
  CI. `--llama-server DIR --fim-model FILE` adds a real `llama-server`, and
  `--live` the OpenAI moderation checks. **12 of 12 PASS with both.**
- **`scripts/p6-sabotage.py`: 38 of 38 caught across P6**, plus one
  declared escape from P6a (a remote image, which the gateway refuses
  first). **The first full pass let one through:** with `generate.completion`
  never set, the gate still passed, because a request rebuilt with profile
  defaults sets the prompt again, and every completion in the gate left a
  sampling field out. Check 7 now sends `max_tokens`, `temperature` and
  `top_p` together, so the request the route built is the one sent, and a
  new sabotage removes the second site.
- **Unit suites:** inference-driver 844 (11 new), gateway 977 (9 new).
- **Every acceptance script specs CI runs passed locally before this pin.**

## The done-when

**The OpenAI SDK's `client.completions.create` fills in the middle on a local
engine.** A real `llama-server` b11235 with Qwen2.5-Coder 0.5B, on this
machine's CPU, answered `" a + b"` for `def add(a, b):\n    return` before
`\n\nprint(add(1, 2))\n` three ways through the gateway: a prompt Continue
would render itself, the `suffix` field (sent to its `/infill`), and a
stream. Three completions took 0.83 s.

## What it does

- **A translation at the edge**, as `/v1/messages` and `/v1/responses` are:
  the sampling fields become a chat-shaped request, so the shared path serves
  it unchanged (tiers, wake, the commit point at the first token, the row),
  and the prompt reaches the driver as `GenerateRequest.completion`, with
  `messages` empty. No chat template is ever applied.
- **The `completion` surface** is reported by a local `llama-server` (it
  answers `/props`), a local vLLM (`/version`), and an Ollama account's
  models with its `completion` capability. A hosted endpoint is not offered,
  nor any account over a hosted API: OpenRouter's completions answer a prompt
  as a chat turn (measured). **A completion is routed only to a model with the
  surface, in every tier**, so a slot `[a chat model, coder]` is served by the
  coder.
- **Each engine is asked the way it continues raw text:** `llama-server` and
  vLLM at `/v1/completions`; Ollama at `/api/generate` with `raw: true`, since
  its `/v1/completions` applies the chat template (read).
- **`suffix` routes like an attachment**, only to a model whose
  `x_eugene_plexus.fill_in_middle` is true: a `llama-server` whose `/infill`
  answers (a zero-token probe at `/v1/info`), or an Ollama model listing
  `insert`. **It is never dropped:** `llama-server`'s `/v1/completions` would
  drop it (measured), so its driver sends a suffix to `/infill`; vLLM refuses
  one for all but DeepSeek V4, so it is never sent there. With no model that
  fills, a 400 naming `suffix`.
- **The answer is OpenAI's** `text_completion`, `finish_reason` `stop` or
  `length`; a stream is chunks, a last chunk with the finish reason, a usage
  chunk when `include_usage` asked, then `[DONE]`. A stream that stops without
  its engine's terminator is an error, never a short completion.
- **Refused in P6, naming the field:** `n` and `best_of` above 1, `echo`
  (`llama-server` ignores it, measured), `logprobs`, a `prompt` of several
  strings or of token ids, unknown fields. The drivers refuse a setting a raw
  completion would drop (Ollama has no logit bias).
- **Metrics:** a completion's row says `door: completion`, with its tokens.

## Found on the way

- **`llama-server`'s own `/v1/completions` drops `suffix`**, so passing
  OpenAI's field through would have silently ignored everything after the
  cursor.
- **Ollama's `/v1/completions` is templated**, so a raw prompt sent there
  becomes a chat turn; its native route is the only raw one.
- **Continue sends model ids starting `gpt` or `o` to chat**, so an
  `ollama/...` or `openrouter/...` id never reaches `/v1/completions` from it
  (read, not measured).
- **Every local `llama-server` now lists the `completion` surface**, a
  speech-recognition model included, since it answers `/props`: the P3 gate
  expected `["chat", "transcription"]` and was widened to match. Running
  every CI acceptance script before the pin is what found it.
- **The gateway fills the install's default temperature** into a completion
  the caller left it out of, as it does for chat: the gateway owns every
  output setting.

## Not done, named

- **No real IDE client was captured** (P6-3): Continue and llama.vscode are
  read in source, and the gate plays what they send.
- **vLLM and Ollama are built from their source and unverified here**: neither
  runs on this box today.
- **llama.vscode's default route, `/infill`, has no door**: it reaches
  `llama-server` directly, or completes through this door in its experimental
  OpenAI mode.
- **`logprobs`, `echo`, `n` above 1 and several prompts** are refused, not
  carried.
- **No `ui` screen consumes P6.**
