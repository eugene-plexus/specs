# Server-run tools (P8): web search first

**Status: P8a-P8e BUILT AND ACCEPTED 2026-09-29** (Troy: *"implement P8 as written… as long as we
don't code ourselves into a corner"*): web search through the new `tool-driver` component on all three
doors, the console's search-account page, a key's tool scope and the playground's search switch.
**P8e (`image_generation` on `/v1/responses`) is designed in §7 with four calls, built as
recommended.** §12 is the
implementation record, §13 the departures. All six calls in §9 TAKEN as recommended (Troy, 2026-09-29).
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

**Anthropic's tool is dated, so any date is accepted (Troy, 2026-09-29).**
Claude Code sends `web_search_20250305` today, and a newer client will send
a newer date. The door matches `web_search_` followed by eight digits, not
one literal, because refusing an unknown date would break WebSearch on the
day Claude Code updates (`output_config` 400'd every Claude Code request
once, the same way). A newer date may also carry settings whose meaning we
do not implement, so it is not assumed to mean the old one: the settings we
know (`max_uses`, `allowed_domains`, `blocked_domains`, `user_location`) are
honoured, any other is dropped **and named** on the ignored-settings header,
and the version seen is recorded on the execution's metrics row so a new
date is noticed rather than discovered.

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

## 7. `image_generation`, second (P8e)

Same loop, same framework; the tool calls Eugene's own images door (P4),
so no new provider account is needed. Written 2026-09-29 once P8a-P8d had
landed, as the build order said.

**Which door.** OpenAI defines `image_generation` for the Responses API
only; chat completions has no such tool and Anthropic's API has none. So
P8e is `/v1/responses` alone. Before it, the door refused the tool with a
400 naming its type (§0's table of other server tools).

**What runs.** The loop offers the model a function
`image_generation(prompt, size?)`; each call is routed exactly as a
`POST /v1/images/generations` would be (P4: the key's `allowedModels`, the
model's listed image settings, tiers) and answered in-process -- no second
HTTP hop, no second recording path. The model is told, in text, that an
image was made for its prompt and is shown to the person; the caller gets
the image as OpenAI returns it, an `image_generation_call` item whose
`result` is the base64 image, streamed as
`response.image_generation_call.in_progress` → `.generating` →
`.completed`. The tool's `size`, `quality`, `background`,
`output_format`, `output_compression` and `moderation` ride on the images
request; `partial_images`, `input_image_mask`, `input_fidelity` and an
`action` other than `generate`/`auto` are named as ignored. `size` is
offered to the model only when the tool left it unset: a size the caller
configured is the caller's, not the model's, to change.

**The limits are one budget.** `max_tool_calls` bounds every built-in tool
a response runs (OpenAI's own wording), so searches and images share it;
failover ends at the first execution of either.

| # | Call | Recommendation | Main tradeoff |
| --- | --- | --- | --- |
| P8e-1 | Which image model | **The tool's `model` when the install serves it; else the gateway's `imageToolModel` setting; else the one image model the install serves, when there is exactly one.** With none of those, the tool cannot run and the 400 says which to set. | An install with two image models and no setting must say which before the tool works. |
| P8e-2 | What the model is given | **Text only**: that an image was made, its prompt and size. The bytes go to the caller, never back into the prompt. | A model that could look at its own image cannot here; nothing in this gateway carries an image in a tool result. |
| P8e-3 | When it cannot run | **400 naming the reason**, as before P8 (no image model, the key's tool scope, a local-only key -- every image backend today is hosted). Not removed silently: a caller that offered image generation and got none would read the model's refusal as the model's. | Responses removes `web_search` when it cannot run and refuses this; the difference is Codex, which sends search on every request and never sends this. |
| P8e-4 | Handed-back items | **Become history**: an `image_generation_call` in `input` is a line of the assistant's turn naming the prompt. The base64 is not re-sent to the model. | A long conversation of images is not carried to the model as images. |

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

**All six taken as recommended, 2026-09-29 (Troy).**

| # | Call | Recommendation | Main tradeoff |
| --- | --- | --- | --- |
| 1 | Remote MCP in P8? | **No.** The hub would dial caller-supplied URLs with caller-supplied credentials. Revisit as its own slice. | OpenAI lists it as server-run, so a Responses caller using it is refused. |
| 2 | Codex's default `external_web_access: false` | **Strip it, as today.** Search runs when Codex's user turns on live search. | Codex users get no search until they change one Codex setting. |
| 3 | Local-only keys and web search | **Refuse**, naming the policy. | A LAN SearXNG feels local but still sends the query out. |
| 4 | First search provider(s) | **SearXNG** (self-hosted, no key, testable in CI) **and Brave** (the first keyed one). Tavily later. | SearXNG must have its JSON output enabled, which is off by default. |
| 5 | Default tool scope for a client key | **Allowed** when a search account exists, deniable per key. | A key minted before P8 gains search without anyone choosing it. |
| 6 | `max_tool_calls` default | **5** per request. | Deep-research style prompts want more; the caller can raise it. |

## 12. Implementation record (2026-09-29)

**Pinned:** specs `a9fc9b9` (contracts: `tool-driver.yaml`,
`ComponentKind.tool-driver`, `ClientKeyLimits.allowedTools`, "Server-run
tools" in `gateway.yaml`, `MetricToolExecution`), `e53a6d9`
(`ToolDriverInfo.billing`), `c4e2fe4` (P8e: `image_generation` on
`/v1/responses`, `MetricRequest.imageGenerations`). New repo
**`eugene-plexus/tool-driver`**.
Components: see the record's table,
[`../acceptance/server-tools-run.md`](../acceptance/server-tools-run.md).

**What was built, by slice.**

* **P8-0 (the owed half).** SearXNG's JSON answer measured against a real
  instance (`searxng/searxng@4e2c1ea` in WSL2): JSON switched off is a
  **403 with an HTML body**, there is no `number_of_results`, and engines
  can be down inside a 200 (`unresponsive_engines`). Codex's rendering of
  `web_search_call` items measured with a real Codex 0.130.0: it prints
  `web search: <action.query>` once for the added item and once for the
  done one -- and printed an empty line until the query rode on the added
  item too.
* **P8a.** As §2 says, with two departures in §13.
* **P8b, `tool-driver`.** SearXNG and Brave providers; settings read per
  search (no restart to fix an address); the Brave key sealed with the
  agent's master key; filters applied after the provider, always; health
  from the last search, with a free SearXNG also probed on a timer and a
  paid provider never. The agent spawns it with its own
  `EUGENE_PLEXUS_TOOL_DRIVER_` prefix and the master key; the agent's
  proxy reaches it by name; the control root's union view tolerates a kind
  it does not know; the installers install it as the seventh package; the
  update checker treats its pin as optional in a target (every release to
  alpha.5 predates it).
* **P8c, the loop.** `gateway/server_tools.py`: the plan, `why_not`, the
  runner with account fallback, `SearchingClient`. `TieredClient.pin`
  ends failover at the first search. Metrics schema v10.
* **P8d, the console.** *Backends → Add a search account*
  (`/backends/search`): create, configure, run the Test search, say what to
  change when it fails. Search accounts are leaves under Backends with a
  Settings page. A key's permissions gain *Let apps using this key search
  the web*. The playground gains *Search the web* on the chat door, the
  sources under the answer and the searches on the routing bar.
* **P8e, `image_generation`.** The loop grew a second tool rather than a
  second loop: `ImagePlan`, `image_model` (P8e-1) and `ImageRunner`, which
  routes each call through the images door's own `image_refusal` and
  `pick_image` in-process. `SearchingClient` runs a search, an image or
  both under one `max_tool_calls` budget; with an image asked for, no
  candidate is sent a search natively, because the image is made only
  here. The image backend's attempt rows are taken off the request's
  (they are the model's) and summarised on a `tool_execution` row, read
  back as `imageGenerations`. A new gateway setting, `imageToolModel`
  (*Image model for tools*), and `maxToolCalls` is relabelled *Web
  searches and images per request*. The UI needed no change: the setting
  lands in its topic by category, and no screen reads the Responses door.

**Found on the way, each fixed:**

1. `prepare_candidate` rebuilt every candidate's request from the caller's
   body, so the loop's appended turns were dropped whenever a profile
   default applied -- nearly every request. It copies the three defaults
   onto the request it is handed now.
2. The key's limits are read by `admission.authorize` inside `_prepare`;
   deciding whether a search may run before it read a local-only key and a
   key denied search as unrestricted. The decision moved into `_prepare`.
3. `ClientRequest` never read `allowedTools` at all -- a key denied search
   still searched. Caught by the first unit test of the rule.
4. Accounts were ordered by name, so with SearXNG and Brave both set up
   every search went to Brave. Hence `ToolDriverInfo.billing` and free
   first (the first acceptance run).
5. A schema default of 5 on `WebSearchRequest.maxResults` would have been
   filled in by every generated client, so the account's own setting could
   never apply (found generating the tool-driver's models).
6. An inline `outcome` enum generated as `Outcome1` (the S6 trap); named
   `MetricToolOutcome`.
7. The control root validated every placement strictly, so one component
   of a kind it did not know made `GET /v1/components` a 500 for the whole
   install.
8. The update checker required every pin, so a new agent would have found
   no release channel at all.
9. The Anthropic door's `_tools` returned `[]` rather than `None` for a
   request whose only tool is server-run, putting `tools` in
   `callerSettings` with nothing in it.
10. **Three checks could not fail, found by the sabotage pass.** Failover
    after a search was tested with a `RuntimeError`, which cascades nowhere
    whether or not the loop pins; a search called on the last turn (the one
    that offers no search tool) was never tested reaching the caller; and
    the tool-scope sabotage went into the agent's copy of
    `client_admission.py`, which an enrolled node never consults -- P1's
    measured finding again. Each has its check now: a `ConnectError` after
    the search, a stream test at `max_tool_calls: 1`, and the sabotage on
    the control root's copy against the acceptance run plus the agent's copy
    against its own unit test.

## 13. Departures

* **Port 8190, not the 8086 first drafted**: the UI hands added drivers
  8081-8089 and the agent hands companions 8090-8189.
* **`ToolDriverInfo.billing`** was not in §2; the first acceptance run
  showed an install with a free and a paid account paying for every search.
* **A search that cannot run on `/v1/messages` is a 400** (as §5 said)
  **decided after admission**, not at translation: the route cannot know a
  key's scope before `admission.authorize` has read it.
* **Search accounts sit under Backends in the tree** rather than a branch
  of their own: they answer requests the way a backend does, and one
  `driver:` selection reaches either through the proxy by name.
* **P8e: a local-only key is refused by the image routing, not by a rule of
  its own.** §7's table named "a local-only key" as a reason because every
  image backend today is hosted; `image_model` asks for an image model the
  key may use, local-only included, so the day a local image engine is
  served the tool runs for that key with no change here.
* **P8e: metrics gain `imageGenerations` beside `webSearches`** rather than
  putting images into a list named for searches. Same row schema; the
  `provider` of an image row is the image model that made it.
