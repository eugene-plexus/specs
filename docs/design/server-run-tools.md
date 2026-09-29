# Server-run tools (P8): web search first

**Status: DESIGN, 2026-09-29. Nothing built. The calls in §9 are Troy's.**
Slice P8 of [`openai-inference-compatibility.md`](openai-inference-compatibility.md)
(§4 row P8, and call #8 there: *Eugene runs some tools itself, through a
modular framework, starting with `image_generation` and `web_search`*).
Troy set the order on 2026-09-28: **web search before image generation**,
and P7 (Realtime) after all of P8.

## 0. Measured, 2026-09-29

What a caller gets today when it asks for a search, read in the gateway at
`9d3dcd7`:

| Door | What the caller sends | What happens | Where |
| --- | --- | --- | --- |
| `/v1/responses` (Codex CLI) | `{"type": "web_search", "external_web_access": false}` on **every** request | Removed, named on the ignored-settings header. The model is never told a search exists. | `gateway/responses.py:351`; capture in `docs/acceptance/responses-measurement.md` §1 |
| `/v1/messages` (Claude Code) | A separate request offering one tool, `{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}` | **Refused with a 400** at the door: *"a server-side tool … which this gateway cannot execute"* | `gateway/anthropic.py:614`; capture in `docs/acceptance/server-tools-measurement.md` §1 |
| `/v1/chat/completions` | `web_search_options` | Routed only to a model whose listing names the field (P2c), and forwarded to it. A local model is never chosen. | `gateway/admission.py:210` |

So on a local model today: Codex silently loses search, and Claude Code's
WebSearch fails outright. That second one is the user-visible defect this
slice exists for.

**Captured the same day (P8-0, `docs/acceptance/server-tools-measurement.md`):**
Claude Code runs WebSearch as its **own request** with one server tool and
folds whatever text comes back into the main loop's tool result, so the
loop only has to produce an answer; Codex sends `external_web_access: false`
by default and for `"cached"`, `true` for `"live"`, and no tool for
`"disabled"`. **Still owed:** how Codex renders `web_search_call` items, and
SearXNG's JSON answer from a real instance.

## 1. The boundary (agreed with Troy, 2026-09-28)

- **In the hub:** tools OpenAI's and Anthropic's APIs define as
  *server-run* — `web_search` now, `image_generation` next, `file_search`
  later. They run in a new **tool driver** component, one per tool provider
  account, a sibling of the inference-driver. The gateway runs the loop.
- **Not in the hub:** anything that acts on the user's machine — files,
  shell, code execution, `apply_patch`, `computer`, and the user's own MCP
  servers. Those stay in apps (spokes) or in the client, which is where the
  files are. `apps-and-spokes.md` gains this line (§10 step 1).
- **Remote MCP is a call (§9 #1).** It is on OpenAI's server-run list, but
  running it means the hub dials a URL the caller supplies, with a
  credential the caller supplies, on the caller's behalf — closer to "the
  user's own MCP servers" than to a search. Recommended: out of P8.

**Why a component and not a plugin registry in the gateway:** the
generative rule (new responsibility = new component). A tool executor has
egress, secrets and failure modes of its own, and a search account is
configured, supervised and health-checked exactly like a provider account.
The gateway stays a router with a loop; it never holds a search API key.

## 2. The tool driver

A new repo, `eugene-plexus/tool-driver`, a new `ComponentKind`
(`tool-driver`, the fifth value — a contract change), and
`openapi/tool-driver.yaml`:

- `GET /v1/info` — the tools it runs (`["web_search"]`), and its
  **egress**: `internet` for every search provider, since even a SearXNG on
  the LAN sends the query on to public engines.
- `POST /v1/tools/web_search` — `{query, maxResults, allowedDomains,
  userLocation, contextSize}` → `{results: [{url, title, snippet,
  publishedAt}], provider, latencyMs}`. The driver owns the provider's
  quirks; the gateway sees one shape.
- The config trio, secrets sealed like an inference-driver's `apiKey`, and
  `/healthz` that actually queries.

Declared and supervised by the agent like any driver; added from the UI's
"Add an app you already run" flow as a new kind of account (§9 #4 picks the
first providers).

## 3. The loop, in the gateway

When a request asks for `web_search` and the routed backend does **not**
run it natively:

1. The gateway offers the model a function tool (named `web_search`, or a
   non-colliding name when the caller already declared one).
2. The model calls it; the gateway sends the call to a tool driver the
   caller's key may use, and appends the result as a tool message.
3. The model is called again, up to `max_tool_calls` (the caller's, else an
   install default, recommended 5). Past the limit the model is told no
   more searches are available and must answer.
4. The caller receives only the final answer plus the door's own record of
   what ran: `web_search_call` items on Responses, `server_tool_use` and
   `web_search_tool_result` blocks on messages, `url_citation` annotations
   on chat.

When the routed backend runs search natively (an OpenAI or OpenRouter model
whose listing names it), the request is **forwarded, not run twice**,
exactly as P2c routes `web_search_options` today.

**One declaration across three doors:** `tools[].type == "web_search"`
(Responses), `web_search_options` (chat) and Anthropic's `web_search_*`
server tool (messages) all become one internal request field, so the loop
is written once.

**Streaming:** each call is streamed as it runs (on Responses:
`response.web_search_call.in_progress` → `.searching` → `.completed`),
so a slow search reads as working, not hung.

## 4. Failover ends at the first search

A search Eugene has run is a side effect with a cost, and its result is now
in the conversation. So **the commit point moves from the first token to
the first tool execution**: after it, a backend failure is reported, never
retried on another backend — the same rule M10 set for tokens, for the same
reason (no seam the caller can see).

## 5. Keys, privacy and accounting

- **Local-only keys refuse web search**, with a reason naming the policy: a
  search query is derived from the prompt and leaves the machine whatever
  provider runs it (§9 #3).
- **A per-key tool scope** beside `allowedModels` (`allowedTools`), so a key
  handed to one app can be denied search (§9 #5 sets the default).
- **Metrics:** one row per execution — tool, driver, latency, outcome,
  result count, and the request it belonged to. **No query text is
  retained**, matching A5's rule that no prompt is kept.

## 6. Codex's `external_web_access: false`

Codex sends `false` by default and for `web_search = "cached"`, and `true`
only when its user sets `web_search = "live"` (measured, Codex 0.130.0). OpenAI reads `false` as cached results only, no live
fetch. We have no cache, so every search we run is live. §9 #2 decides
whether `false` means *strip it as today* (recommended: the user did not
ask for live web access, and a search sends their prompt out) or *run it
anyway*.

## 7. `image_generation`, second

Same loop, same framework; the tool calls Eugene's own images door (P4),
so no new provider account is needed. Its own small design section when P8a
lands, since the result is bytes in the conversation rather than text.

## 8. Build order

1. **P8-0, measurements:** Claude Code's WebSearch request and Codex's
   flag are captured (`docs/acceptance/server-tools-measurement.md`). Owed:
   Codex with `web_search_call` items back, and a SearXNG JSON answer.
2. **P8a, contracts:** `tool-driver.yaml`, `ComponentKind.tool-driver`,
   `allowedTools` on client keys, the tool-execution metrics row, and the
   three doors' tool items. Write the boundary into `apps-and-spokes.md`.
3. **P8b, the tool driver repo** with the first provider(s), and the agent
   supervising it.
4. **P8c, the loop** on `/v1/responses` first (Codex), then `/v1/messages`
   (Claude Code), then chat. Acceptance through the unchanged SDKs against a
   fixture search provider; sabotage pass.
5. **P8d, the UI:** add a search account, the per-key tool scope, and a
   Search door in the playground.
6. **P8e, `image_generation`.**

## 9. Calls for Troy

| # | Call | Recommendation | Main tradeoff |
| --- | --- | --- | --- |
| 1 | Remote MCP in P8? | **No.** The hub would dial caller-supplied URLs with caller-supplied credentials. Revisit as its own slice. | OpenAI lists it as server-run, so a Responses caller using it is refused. |
| 2 | Codex's default `external_web_access: false` | **Strip it, as today.** Search runs when Codex's user turns on live search. | Codex users get no search until they change one Codex setting. |
| 3 | Local-only keys and web search | **Refuse**, naming the policy. | A LAN SearXNG feels local but still sends the query out. |
| 4 | First search provider(s) | **SearXNG** (self-hosted, no key, testable in CI) **and Brave** (the first keyed one). Tavily later. | SearXNG must have its JSON output enabled, which is off by default. |
| 5 | Default tool scope for a client key | **Allowed** when a search account exists, deniable per key. | A key minted before P8 gains search without anyone choosing it. |
| 6 | `max_tool_calls` default | **5** per request. | Deep-research style prompts want more; the caller can raise it. |
