# `/v1/responses` and `/v1/completions` + FIM — two calls for Troy

**Written 2026-09-23, after measuring; nothing here is built.** Slice 4 of the
API-parity work. Each section is the evidence, the options, and a
recommendation. Decide either, both, or neither.

## 1. `/v1/responses` — OpenAI's Responses API

### What was measured

Codex CLI **0.130.0** (installed here), isolated `CODEX_HOME`, a custom provider
pointed at a capture listener:

- **`wire_api = "chat"` is refused at startup**: *"`wire_api = "chat"` is no
  longer supported. How to fix: set `wire_api = "responses"`"*. **So Codex
  cannot use this gateway at all today** — not badly, not at all, the same shape
  as tool calling before step 6 and the Anthropic door before R4.
- With `wire_api = "responses"` it sends `POST /v1/responses`, `stream: true`,
  **`store: false`**, `instructions` (21 KB), `input` as items
  (`message` with role `developer` or `user`, content `input_text`), ten
  function tools with `strict`, **plus a server-side `{"type": "web_search"}`
  tool on every request**, `tool_choice: "auto"`, `parallel_tool_calls: false`,
  `reasoning: null`, `include: []`, `prompt_cache_key`, `client_metadata`.
- Answered with a `function_call`, its next request **resent the entire
  history**: our `function_call` item (`call_id`, `name`, `arguments` string)
  followed by a `function_call_output` (`call_id`, `output` string). **No
  `previous_response_id`.** The conversation lives in the client.

The OpenAI Agents SDK also defaults to Responses (not installed here; not
measured). It can be switched to Chat Completions with one call, so it is
usable today; Codex is not.

### What it would take

The Anthropic door's shape exactly: a **stateless translation at the edge** onto
the shared path, so routing, failover, profiles, admission, metrics and the
image path are inherited rather than rebuilt.

- `instructions` → system; `developer` → system in place (already done for the
  OpenAI door); `input_text` / `input_image` → text and image parts;
  `function_call` / `function_call_output` → assistant `tool_calls` and `tool`
  messages; function tools → tools.
- **`web_search` accepted and disclosed, not refused** — it is on every Codex
  request, and refusing it is the `output_config` mistake again (a 400 on turn
  one of every session). Any other server-side tool is refused, as on the
  Anthropic door.
- `reasoning` items: returned when the model reasons, carried back through
  `encrypted_content` the way the Anthropic door's omitted `thinking` uses the
  signature — Codex sends reasoning items back when `store` is false.
- `previous_response_id` refused with a 400 naming it (we keep no conversation
  store); `store` accepted and disclosed.
- The Responses event stream (`response.created`, `output_item.added`,
  `output_text.delta`, `function_call_arguments.delta`, `output_item.done`,
  `response.completed` with usage). Like the Anthropic stream, the real work is
  numbering items statefully over our un-numbered internal stream.
- Contract: `gateway.yaml` only. The driver already carries everything
  (tools, reasoning, images, samplers).

Size: about R4's — two slices (request/response + tools, then streaming), a
capture-first step, and a live run with a **real Codex CLI** doing a shell tool
loop against llama.cpp.

### Recommendation: build it, next

It is the only door a current, major, open-source coding agent can use, and it
is absent. The measured statelessness removes the expensive half (no response
store, no retrieval endpoints). Counter-argument: Codex is also a *backend* here
(`codex_cli`, the subscription path), and a user with a Codex subscription may
prefer that route; but that is Codex using OpenAI, not Codex using a local
model, which is what this door is for.

## 2. `/v1/completions` and fill-in-the-middle

### What was measured

Against llama.cpp b10948, straight at the engine:

| Model | `/v1/completions` with `suffix` | `/infill` |
| --- | --- | --- |
| Gemma 4 E4B (no FIM tokens) | 200, **byte-identical to the same request without `suffix`** | **501** *"Infill is not supported by this model: prefix token is missing…"* |
| Qwen3-0.6B (has FIM tokens) | 200, output differs from the no-suffix one | 200 (an instruct model: the infill is junk) |

So **`suffix` is silently ignored on a model that cannot do FIM** — the exact
drop this project refuses elsewhere. An editor would get completions that
ignore everything after the cursor, with nothing to say so.

Not measured: which IDE clients send what. None is installed here. From their
documentation (unverified): Continue sends `/v1/completions` with `suffix` for
an OpenAI-compatible provider or builds the FIM template itself, and `/infill`
for its llama.cpp provider; `llama.vscode` sends `/infill`.

### What it would take

- `/v1/completions` passed through the shared path (the driver has no
  completions call today — a driver contract change), `prompt` + `suffix`.
- **`suffix` routed only to a backend whose model has FIM tokens**, refused with
  a 400 otherwise, never dropped. The library already reads GGUF metadata; the
  FIM token ids are there, or the driver can probe `/infill`.
- Optionally `/infill` passed through for `llama.vscode`.
- Latency is the real product question: autocomplete wants a few hundred
  milliseconds per keystroke pause, from a small dedicated FIM model kept
  resident — a different operating point from anything the gateway serves now
  (idle unload, wake on demand, cascade).

### Recommendation: not yet — capture a real IDE client first

Build only after one real client (Continue or `llama.vscode`) has been captured,
and only if IDE autocomplete is an audience you want: it pulls toward a
resident small model and per-keystroke latency, which is its own design. If
yes, the `suffix`-routing rule above is the part that must not be skipped.

## 3. The calls

| # | Call | Recommendation | Troy, 2026-09-23 |
| --- | --- | --- | --- |
| 1 | Build `/v1/responses` (stateless, Codex-first)? | **Yes, next** — Codex 0.130 cannot reach us at all | **Build it now.** Built the same day: `docs/acceptance/responses-run.md` |
| 2 | Build `/v1/completions` + FIM now? | **No** — capture an IDE client first, then decide whether autocomplete is an audience | **Not yet** |
| 3 | The four-image limit counts the whole conversation, so a session that read five screenshots is refused until it compacts | (was left open) | **Make it configurable, default 12.** The gateway's `maxImagesPerRequest` (1-64); the driver's own cap is now a ceiling of 64 |

Two things the build measured that this document did not know, both in
`docs/acceptance/responses-measurement.md`: Codex regenerates an answer
that ends `incomplete` five times, so the install's `defaultMaxTokens` is
not applied on this door; and Codex's five-minute idle timeout runs before
the first event, so the stream opens early and sends `response.in_progress`
every ten seconds.
