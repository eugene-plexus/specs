# The playground as a diagnostic instrument (design)

**Status:** designed 2026-09-13. Install-paths
[§9 step 8](install-paths-and-distribution.md); the call it builds on is
[`agent-clients-and-tool-calling.md`](agent-clients-and-tool-calling.md)
§7 (decided 2026-09-11): the playground is a reference client and a
diagnostic, not a product. Every claim marked *measured* was checked
against a file, a live process or a live install on the day of writing;
everything else is reasoning and marked as such. §11 is the
implementation record, appended as the work lands.

**What it is.** A way for someone whose agent harness is misbehaving to
ask *"is it my harness or is it the control plane"* and get an answer
they can act on. §7.1's rule is the whole design constraint: **a
reference client that shares its path with the thing it tests, tests
nothing.** So the playground gains a second way to reach the gateway —
the same one OpenCode or the OpenAI SDK uses: a base URL, a bearer
token, `POST /v1/chat/completions`, no proxy, no privileges — plus the
three things a harness sends that the playground cannot today (tool
definitions, tool results, file contents), and a report of what each
request did on the wire.

**What it is not.** Not a chat product. No personas, no prompt library,
no saved conversations, no tool execution. Every feature below is
justified by one test: *does it prove something about the backend, or
isolate a fault?* Anything that fails that test belongs to the clients
this project exists to serve.

---

## Decisions

| #     | The call                                                                                  | §    | Recommendation                                                              | Status |
| ----- | ----------------------------------------------------------------------------------------- | ---- | --------------------------------------------------------------------------- | ------ |
| **1** | The gateway answers CORS on its OpenAI-compatible paths                                    | §3   | Yes; any origin by default; the three front-door paths only; expert narrows | taken as recommended (unattended) |
| **2** | Direct is a *mode* beside the proxy path, not a replacement                               | §2   | A mode. Same request, two paths, is the instrument                          | taken as recommended |
| **3** | Attachments are text, inlined into the message                                            | §5   | Yes. The contract has no content parts; images are a separate decision      | taken as recommended |
| **4** | The playground never executes a tool; the operator types the result                       | §4   | Yes. The human is the tool runtime, which is what the loop needs proven     | taken as recommended |
| **5** | The "API key" shown is the operator's session token; no new credential is minted           | §2.3 | Yes, and say its lifetime. Long-lived client keys are a separate slice      | taken as recommended |

Every call here was taken as recommended because the build was
unattended. **#1's default (any origin) is the one Troy might overturn**
— §3.2 has the argument and the override.

---

## 0. What measuring the current playground found

Six things, checked on 2026-09-13 against `ui@44096f9`,
`gateway@687f770` and the live two-machine install.

1. **The playground has never touched the public surface.** *Measured.*
   Its two gateway calls — `listModels` and `streamChatCompletion` in
   `ui/src/lib/completions.ts` — go to `/api/proxy/gateway/...`, which
   the **agent** serves and forwards to the gateway's *topology URL*
   over its own `httpx` client. On the live install that URL is
   `http://127.0.0.1:8080/` inside a container that publishes the port
   as **8280** (recorded in the cross-node console run). The browser
   never learns the gateway's address, never dials it, and never
   presents the bearer to it — the proxy forwards the header. A gateway
   bound to loopback, a host firewall, a port remap or a stale
   `advertiseUrl` is therefore **invisible from the playground**, and
   those are the four most common reasons a harness on another machine
   cannot connect. The playground says "fine"; the harness says
   "connection refused"; the bisection is already wrong.

2. **The gateway does not speak CORS.** *Measured, live.* The exact
   preflight Chrome sends before a `fetch` with `Authorization` and a
   JSON body, against the live gateway:

   ```
   $ curl -i -X OPTIONS http://192.168.16.252:8280/v1/chat/completions \
       -H 'Origin: http://192.168.16.75:8079' \
       -H 'Access-Control-Request-Method: POST' \
       -H 'Access-Control-Request-Headers: authorization,content-type'
   HTTP/1.1 405 Method Not Allowed
   allow: POST
   ```

   No `access-control-*` header on that or on a `GET /v1/models` with
   an `Origin`. The gateway source has no CORS middleware (grep across
   the repo: zero hits), and `agent.yaml`'s proxy description states it
   as a design property — *"One origin for the whole install: no CORS
   configuration on any component."* That was the right rule for a UI
   that only ever talked through the proxy. It also means **no
   browser-based client can use the front door at all** — not the
   playground in a direct mode, not Open WebUI in a tab, not a web app
   someone builds against the OpenAI SDK with `dangerouslyAllowBrowser`.
   `llama-server` answers CORS by default and Ollama has
   `OLLAMA_ORIGINS`; we answer 405. This is the one finding here that
   is a product gap rather than a playground gap.

3. **The stream parser drops tool calls.** *Measured, by reading.*
   `streamChatCompletion` reads `choice.delta?.content` and nothing
   else from a frame. A streamed tool-call-only turn — the step 6
   headline, `finish_reason: tool_calls` with `content: null` — arrives
   as a stream of frames whose deltas carry `tool_calls`, every one of
   which is discarded. `finish_reason` is captured, so the assembled
   response says `tool_calls` with an assistant message that has no
   `tool_calls` field. The transcript shows an empty bubble, which is
   also exactly what "the model chose not to call anything" looks like.
   **Step 6 refused to let the driver produce that ambiguity, and the
   reference client produces it.**

4. **Nothing can send `tools`, `tool_choice` or `response_format`.**
   *Measured.* `CompletionOptions` has `model`, `messages`,
   `temperature`, `maxTokens` and `timeoutMs`. `ChatLog`'s own comment
   says a tool-call turn "shows as an empty bubble rather than as a
   crash … a placeholder for the tool-call rendering the diagnostic
   will want." The contract carries all three fields since `95dfa8f`
   and the generated TypeScript already has `Tool`, `ToolCall` and
   `ToolCallDelta`; no codegen is needed on the UI side.

5. **The credential a harness uses is the operator's session token,
   and nothing shows it to anyone.** *Measured.* The gateway's front
   door accepts an operator-audience *or* any `service:*` token
   (`dependencies.require_authorized`); the agent issues operator
   tokens with a **14-day** TTL (`_DEFAULT_SESSION_TTL_SECONDS`); there
   is no API-key surface on any component (`/v1/auth/*` on the agent is
   `status`, `initialize`, `login`, `sessions/current`). Every
   acceptance script since M0 uses a session token as the harness's
   bearer, and the live install's first cross-host tool call did too.
   So "connect OpenCode" today means: `curl -X POST /v1/auth/login`,
   copy the JWT out of the JSON, paste it as an API key, and know that
   it expires in two weeks. The UI holds that exact token in
   `sessionStorage` and shows it nowhere.

6. **The report is half there.** *Measured.* `RoutingBar` renders the
   `x_eugene_plexus` envelope — driver, runtime, backend, latency,
   tokens, context length, `attempts > 1`, `prompt_truncated`. What it
   cannot show, because the proxy path never sees it: which URL was
   dialled, the HTTP status, time to first byte, the frame count, and
   the request body as sent. A bug report needs both halves.

Also checked: `ChatCompletionMessage.content` is `string | null` — the
contract has no content-parts array, so an image attachment has no wire
shape and is out of scope until it does (§7). And a supervised
`llama.cpp` runtime's companion driver reports `toolCalling: true`
(`openai_compat_http.supports_tool_calling = True`), so the tools panel
is meaningful against a local engine, not only Ollama.

## 1. What the instrument is

The claim a user makes when they open the playground is *"the control
plane works"*. The claim they need, when a harness is failing, is *"the
control plane works **from where the harness stands**"*. Those differ by
exactly the path in §0.1, and the instrument is the ability to run the
same request down both and compare.

The bisection ladder, top to bottom, each rung a different fix:

| Works through the proxy | Works direct | Works in the harness | The fault is in                                                    |
| ----------------------- | ------------ | -------------------- | ------------------------------------------------------------------ |
| no                      | —            | —                    | the control plane itself; the routing bar and `/inference` say where |
| yes                     | no           | —                    | reachability: address, port, bind host, firewall, CORS, token       |
| yes                     | yes          | no                   | the harness — its base URL, its key, or a request shape we should see |
| yes                     | yes          | yes                  | nothing; the report is the evidence                                 |

Row two is what §0.1 could never distinguish from row one, and row
three is what §7's quote is about — *"the playground uses the tool
fine, so maybe my problem is with OpenCode."* For row three to mean
anything the playground has to send what a harness sends: tool
definitions, tool results and file contents. That is why tools and
attachments are in and personas are out — they are the difference
between a client that resembles a harness and one that does not.

## 2. Direct mode — the second path

A toggle on the playground: **Through the agent** (today's path, the
default) and **Direct to the gateway**. In direct mode the browser
itself does what a harness does:

```
fetch(`${baseUrl}/v1/chat/completions`, {
  method: "POST",
  headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
  body: JSON.stringify(request),
})
```

No `/api/proxy`, no `lib/api.ts`, no session handling, no 401 redirect.
`listModels` in direct mode goes to `${baseUrl}/v1/models` the same way.
The code that builds the request is shared between the two modes so the
*only* difference is the transport — otherwise "works direct, fails via
proxy" could be a difference in what was sent.

### 2.1 The base URL is a guess, and says so

The browser knows nothing about where the gateway is (§0.1). The default
is derived the way an operator would derive it by hand: the page's own
scheme and host, plus the gateway's **port** from the agent's topology
(`GET /v1/components`, the `gateway` entry's `url`, or `advertiseUrl`
when set). On a one-box install that yields `http://127.0.0.1:8080`,
which is right. On the live install it yields
`http://192.168.16.252:8080` — **wrong**, because the container publishes
8280 and nothing inside it can know that (the cross-node console record
established this is unfixable by rewriting). That is fine: the field is
editable, persisted per browser in `localStorage`, and the *first*
failure it produces is the honest one — connection refused at the port
the topology names — which is precisely the failure a harness meets when
handed the same guess. The instrument's job is to reproduce that, not
hide it.

Two hints the panel gives, because the failure they cause is opaque in a
browser (`TypeError: Failed to fetch`, no status, no body):

- **A loopback base URL from a non-loopback page.** A harness on another
  machine cannot use `127.0.0.1` either, so the guess is wrong for the
  same reason the harness config would be. Chrome additionally gates
  page-to-loopback requests from a LAN origin behind its local-network
  permission, so the failure can be a permission prompt nobody saw.
- **`https:` page, `http:` base URL.** Mixed content; the browser blocks
  it before any request leaves. A tailnet serving the UI over HTTPS
  needs the gateway over HTTPS too.

### 2.2 What a failure looks like

The report (§6) records the URL, the method, the status or the thrown
error, and elapsed time, for every attempt in either mode. A CORS
refusal, a connection refusal and a 401 are three different rows with
three different next actions, and the panel names them:

- `Failed to fetch` with a base URL the proxy path can reach → the
  gateway is not answering **this browser**: CORS disabled (§3), or a
  port that is published differently than the topology says, or a bind
  host of `127.0.0.1` on a machine you are not on. Each is spelled out
  with where to change it.
- `401` → the key. Either expired (14 days) or from a different install.
- `404` on `/v1/chat/completions` → this is not a gateway (the agent's
  port, most often).

### 2.3 The key

Prefilled with the operator's session token, masked, with reveal and
copy. Editable, so an expert can paste a service token or a token minted
on another node. Beside it, one sentence: *this is the token an OpenAI
client uses as its API key; it was issued when you signed in and expires
after 14 days.* That sentence is the whole of the "connect a client"
story today, and it is honest about the limitation.

**Not built here: a long-lived client key.** It is the obvious next
thing — `POST /v1/auth/keys` on the agent, `aud: client`, revocable,
listed — and it touches the trust root's auth model, the gateway's
accept-set, and the tailnet doc's *"three auth surfaces"* section. That
is its own slice with its own §0. Showing the session token now costs
nothing and removes the `curl` step; minting keys later replaces the
prefill and nothing else.

## 3. CORS on the gateway

### 3.1 What changes

The gateway answers CORS for exactly the paths an OpenAI client uses:
`/v1/models`, `/v1/chat/completions`, `/v1/embeddings`. A preflight
(`OPTIONS` with `Origin` and `Access-Control-Request-Method`) is answered
`204` with `Access-Control-Allow-Origin`, `-Methods` (`GET, POST`),
`-Headers` (what the request asked for, so `authorization` and
`content-type` and whatever else an SDK adds) and a `Max-Age`. Every
actual response on those paths carries `Access-Control-Allow-Origin`.
`Vary: Origin` whenever the allowed origin is echoed rather than `*`.

**No other path.** `/v1/config`, `/v1/admin/*`, `/v1/metrics` stay
same-origin-only. A browser client needs the front door and nothing
else; widening the operator surface would buy a browser-based console
nobody asked for, at the price of every operator route being callable
from any page holding a token.

**As a pure ASGI middleware, not `BaseHTTPMiddleware`.** The front door
streams, and M10 recorded what a buffering layer does to a stream: every
frame still arrives, framing stays correct, every "is it streaming"
check passes, and the tokens land all at once at the end. Starlette's
`BaseHTTPMiddleware` has had exactly that failure class. The middleware
here touches only the `http.response.start` message to add headers and
passes body messages through untouched; the unit test for it is the
sabotage-checked kind — it fails when the implementation buffers.

**Preflights are answered before auth.** A preflight carries no
`Authorization` by definition, so a CORS layer inside the auth dependency
would 401 every browser before it could send the real request. The
middleware wraps the app, so preflights never reach a route.

### 3.2 The default, and the override

Two fields on the gateway's config trio, both **live** (read per request
from the store, `requiresRestart: false`, and true in fact — the
`controlUrl` lesson):

- **`corsEnabled`** (boolean, default `true`). Off refuses browsers
  entirely: no preflight answer, no headers. The playground's direct
  mode then fails and says why.
- **`corsAllowedOrigins`** (`url_list`, default `[]`). **Empty means any
  origin.** Listing origins narrows it to those, matched exactly against
  the `Origin` header.

**Why "any origin" is the safe default here, and not a convenience.**
CORS exists to stop a page from spending credentials the *browser*
attaches on its own — cookies, HTTP auth, client certificates. The front
door has none of those: it authenticates by a bearer that the page must
hold and send explicitly, and a page that does not have the token gets
the same 401 a `curl` without one gets. `Access-Control-Allow-Origin: *`
with no `Allow-Credentials` is the shape both `llama-server` and OpenAI's
own API ship. What the default *does* expose is that the gateway exists
— a page can learn that a URL answers 401 with our `Problem` body — which
it could learn from the same origin's timing already. The narrowing is
for an operator who wants only their own UI's origin to be able to hit
the door from a browser, and that is what the list is for.

**Why not "the UI's own origin by default."** The agent that serves the
UI does not know the address a browser uses to reach it (§0.1 again —
the container case), so the gateway cannot compute that origin either.
A wrong default here is a direct mode that never works, and the failure
is `Failed to fetch` with no explanation. Any-origin works everywhere;
the expert narrows.

### 3.3 The contract

No schema changes. `gateway.yaml`'s front-door description gains a
paragraph saying these three paths answer CORS and how it is configured;
`agent.yaml`'s proxy description loses its absolute *"no CORS
configuration on any component"* in favour of *"none needed for the
UI's own calls; the gateway's front door answers CORS separately for
browser-based OpenAI clients."* Radius: `gateway` re-pins because it
implements the described behaviour; nobody else regenerates anything
different. Measured by regenerating, not assumed.

## 4. Tools

### 4.1 Definitions

A **Tools** panel, collapsed by default, holding the `tools` array as a
JSON editor with one example preloaded — the `get_weather` definition
the tool-calling acceptance run uses, so what the playground sends is
the thing already proven to make a real model call a tool. Invalid JSON
disables Send and says where. `tool_choice` is a select (`auto`,
`none`, `required`, or a named function from the definitions).
`response_format` (`text` / `json_object`) sits beside it, because it
is on the same request and harnesses use it; it is one select and
proves the backend honours the field.

When the panel is on, every request carries `tools`. When the selected
model reports `tool_calling: false` on `/v1/models`, the panel says so
before Send rather than after the 400 — that field exists so a caller
can know in advance, and the playground is a caller.

### 4.2 Calls

An assistant turn carrying `tool_calls` renders each call as a card:
the function name, the `arguments` string, and whether it parses as
JSON (a model can emit malformed arguments, and that is a model fault
worth seeing as such). Streamed, the card fills in as fragments arrive,
accumulated by `index` the way the contract says — `id` and `name`
once, `arguments` concatenated. The parser fix for §0.3 lives in
`streamChatCompletion`, which now returns `tool_calls` on the assembled
message; a pure function `accumulateToolCallDeltas` carries the rule and
is tested against fragmentation (OpenAI's shape) and against whole-call
deltas (Ollama's), because step 6 found those differ and a client must
handle both.

### 4.3 Results — the operator is the tool runtime

Under each call card, a textarea for the result and one **Send results**
button for the turn. For the preloaded example the textarea is prefilled
with `{"tempC": -3, "sky": "snow"}`, the same result the acceptance run
hands back, so the loop can be closed in two clicks. Sending appends one
`tool` message per call (`tool_call_id` set, `content` the typed string)
and runs the next turn with the full transcript, which is exactly the
sequence a harness performs.

**The playground executes nothing.** It has no tools of its own, no
sandbox, no filesystem. That is deliberate and not a shortcut: the claim
under test is *"the loop closes through the control plane"* — the call
arrives, the result goes back, the model uses it — and a human typing
the result proves that claim as well as a real function would while
adding nothing that could be the fault instead.

## 5. Attachments

A paperclip on the composer accepts text files. Each is read in the
browser and **inlined into the user message**:

```
<the typed text>

--- attached: notes.md (2,134 bytes) ---
<file contents>
--- end notes.md ---
```

This is the wire shape because it is the only one the contract has
(`content` is a string) and because it is what a coding harness does
when it pastes a file into the conversation. The message the transcript
shows is the message sent — no client-side metadata, no separate
attachment object — so what the operator reads is what the model got.
Long user messages collapse past a few dozen lines with a control to
expand, because a 60 KB attachment otherwise makes the transcript
unreadable, and collapsing the *display* changes nothing on the wire.

The reason this is a diagnostic feature and not a convenience: **it is
the step 7 reproduction.** Attach a file larger than the backend's
window, send, and watch the report — `prompt_tokens` versus the
characters sent, and the `input truncated` badge that already exists.
Files over a soft limit (1 MB) are refused with the size, because
nothing useful happens past that and the browser would spend seconds
serializing it.

Binary files are refused (a UTF-8 decode that produces replacement
characters), and images are out of scope until the contract has content
parts (§7).

## 6. The report

A **Request report** below the routing bar, one per turn, collapsed to a
summary line and expandable:

| Group      | Fields                                                                                                         |
| ---------- | -------------------------------------------------------------------------------------------------------------- |
| Path       | mode (`proxy` / `direct`), URL dialled, method                                                                 |
| Outcome    | HTTP status or the thrown error, elapsed ms, time to first frame, frames, content deltas, tool-call deltas      |
| Envelope   | everything `RoutingBar` shows today, plus `finish_reason`, `usage`, `context_length`, `prompt_truncated`        |
| Request    | the JSON body as sent, with `messages` collapsed                                                                |
| Reproduce  | a `curl` command equivalent to the request, key redacted unless revealed, with a copy button                    |

The `curl` line is the deliverable for row three of §1's table: it is
the request the browser just made, spelled so a shell or a bug report
can replay it — the same JSON document the browser sent, with every
character outside ASCII written as a `\uXXXX` escape. *(Corrected after
the first run: this said "byte for byte". A model answered `-3°C`, and
Git Bash on Windows handed curl one byte for the degree sign, because
the argument crosses the Windows command line through the ANSI code
page; the gateway could not parse the body. Same value, ASCII-safe.)* It uses the direct-mode URL whether or not direct mode is
on — a `curl` against `/api/proxy/gateway` would be a reproduction of the
proxy, not of a harness — and the report says so when the mode was
proxy. The key is `$EUGENE_PLEXUS_TOKEN` in the copied text unless
"include key" is toggled.

Time to first frame is measured by a clock on the client — the moment
the first `data:` frame is parsed, not when `fetch` resolved its headers
— because a buffering path anywhere between browser and engine shows up
there and nowhere else (the step 1 lesson: frame counts cannot tell a
streaming proxy from a buffering one; a clock can).

## 7. What stays out, and why

- **Personas, system-prompt libraries, saved conversations.** Prove
  nothing about the backend (§7 of the agent-clients design). A system
  message can be typed — the transcript is the request — but nothing
  stores or names one.
- **Tool execution.** §4.3.
- **Image and audio attachments.** No content-parts shape in the
  contract; adding one is a gateway + driver + contract change with its
  own questions (which local engines accept `image_url`, and how). Not
  decided here.
- **A long-lived client key.** §2.3. The prefill shows the session token
  and its lifetime instead.
- **CORS on operator paths.** §3.1.
- **A separate `/diagnostic` page.** The instrument is the comparison,
  and a comparison needs the two paths on one screen.

## 8. Contract and radius

- `gateway.yaml`: prose on the front door (CORS; the two config keys by
  name). No schema change.
- `agent.yaml`: the proxy paragraph amended. No schema change.
- Consumers: `gateway` re-pins (it implements what the prose describes).
  `ui` consumes no new generated type — `Tool`, `ToolCall`,
  `ToolCallDelta`, `ResponseFormat` and `NamedToolChoice` have been in
  `gateway.ts` since `95dfa8f`. Confirmed by regenerating both.

## 9. Verification

**Unit, gateway** — `tests/test_cors.py`: a preflight on each of the
three paths is 204 with the right headers and never reaches auth; a
preflight on `/v1/config` is 405 with no CORS headers; a `GET /v1/models`
with `Origin` carries `Allow-Origin`; `corsAllowedOrigins` narrows and
`Vary: Origin` appears; `corsEnabled: false` removes every header; both
take effect **without restart** through the real `ConfigStore`; and a
streamed completion through the middleware arrives in as many frames as
without it (the sabotage check: a buffering middleware fails this).

**Unit, UI** — `completions.test.ts`: `tool_calls` deltas accumulate by
index from split fragments and from whole-call deltas, and a
tool-call-only stream produces a message with `tool_calls` and
`content: null`. A new `lib/diagnostic.ts` (pure) with tests for the
base-URL guess (port from a topology URL, page host, the two hints), the
`curl` builder (redaction, shell quoting of a body containing quotes),
the attachment inliner (fence shape, refuses binary, refuses over-limit),
and the report summary line.

**Acceptance** — `scripts/playground-diagnostic-acceptance.sh`, **safe
beside the live install**: clears every `EUGENE_PLEXUS_*` variable, binds
+100 from the defaults (agent 8179, gateway 8180, library 8182, control
8183, driver 8191), refuses to start if any is taken, tears down **by
pid**. Backend: the local Ollama with `qwen3-coder:30b`, the model step
6 proved calls tools. Checks, in order:

0. isolated: no ambient variable survives into the run
1. agent, control, gateway, library up; the UI served at `/`
2. a driver on Ollama; `/v1/models` lists the model with `tool_calling: true`
3. a browser preflight on `/v1/chat/completions` is answered with CORS
4. a `GET /v1/models` with `Origin` carries `Allow-Origin: *`
5. a preflight on `/v1/config` is **not** answered with CORS
6. `PATCH corsAllowedOrigins` narrows live: the listed origin allowed,
   another refused, `requiresRestart: false`
7. `PATCH corsEnabled: false` removes the headers; restored
8. the session token minted by `/v1/auth/initialize` works as the bearer
   on a direct request, non-streaming, with the envelope
9. **browser**: Playwright signs in, switches to Direct, the base URL is
   prefilled with the gateway's port, a message round-trips and the
   report says `direct`, names the driver, and counted more than one frame
10. **browser**: with the example tool on, "what is the weather in Oslo"
    produces a `get_weather` card whose arguments parse and name `city`
11. **browser**: sending the prefilled result closes the loop — the answer
    mentions the temperature or the sky
12. **browser**: a text attachment carrying a canary word is answered
    with the canary, and the report's `prompt_tokens` exceeds the
    unattached turn's
13. **browser**: the report's `curl` reproduction, copied out of the DOM
    and executed by the script with the real key, returns 200 with an
    envelope — the browser's request replays outside a browser
14. **browser**: pointed at the agent's port instead of the gateway's,
    direct mode fails with a report that names the 404 and the URL, and
    the same message still works through the proxy — row two of §1,
    reproduced
15. teardown by pid; no owned port still listening

**Record** in `docs/acceptance/playground-diagnostic-run.md`.

## 10. Traps known in advance

- **Chrome's local-network permission.** A page on a LAN address
  fetching `127.0.0.1` may be gated behind a permission prompt, and a
  headless browser answers no. The acceptance run keeps page and
  gateway on the same address class (both loopback); the panel's hint
  in §2.1 covers the live case.
- **`BaseHTTPMiddleware` buffers.** §3.1; the test is written to fail
  if it is used.
- **The browser's `fetch` hides everything about a network failure.**
  `TypeError: Failed to fetch` is all a script gets for CORS refusal,
  connection refusal, mixed content and a blocked private-network
  request alike. The report cannot distinguish them; it says so and
  lists the candidates, ordered by likelihood given the URL's shape.
- **A `curl` reproduction that is not the request.** The builder uses
  the same serialized body the browser sent, not a re-serialization;
  check 13 replays the copied text verbatim.
- **The first-run gate.** The playground redirects to `/setup` when
  `firstRunComplete` is false; the throwaway install writes it true, as
  `m11-acceptance.sh` does, because the wizard is not the subject here.
- **A 30B model's first turn is cold.** Ollama loads on the first
  request; the browser checks wait up to 150 s the way the auth arc's
  completion check already does.

## 11. Implementation record

**BUILT AND LIVE-VERIFIED 2026-09-13 (late), one unattended session.**
Contracts `0749c54` (prose only, no schema change); gateway `f48b7c2`;
`ui` `f3dcce1` (dist `552afff`). Record:
[`../acceptance/playground-diagnostic-run.md`](../acceptance/playground-diagnostic-run.md),
**15 checks, 28 `PASS` lines, third attempt** — the first two attempts
failed in the harness and in the `curl` builder, not in the gateway or
the panel.

### What was built

- **Gateway** — `cors.py`, a pure ASGI middleware on exactly the three
  OpenAI-compatible paths; `corsEnabled` and `corsAllowedOrigins` on
  the config trio, read per request, in a new *Browser clients*
  category; `url_list` validation the gateway had never needed before
  (it fell through to "unsupported valueType"). Twelve tests, including
  the sabotage check §3.1 promised: a buffering middleware deadlocks
  into a `TimeoutError`, verified by substituting one.
- **UI** — `lib/diagnostic.ts` (pure: the base-URL guess, the hints, the
  `curl` builder, the attachment inliner, the failure explanations, the
  report summary); `lib/completions.ts` gains a `Transport`, a
  `RequestReport` delivered on every request through `onReport`, and
  `accumulateToolCallDeltas`; `DiagnosticPanel`, `ToolsPanel`,
  `RequestReport`; `ChatLog` renders tool-call cards, tool-result
  bubbles, the results form, and collapses long user messages;
  `ChatInput` attaches text files. 118 unit tests (38 new), and
  `e2e/diagnostic.spec.ts`.
- **Specs** — `scripts/playground-diagnostic-acceptance.sh`, the prose in
  `gateway.yaml` and `agent.yaml`, this record.

### Decided during the build, within the calls above

- **The base URL is displayed and copied in the `/v1` form**
  (`http://host:8080/v1`), because that is what `OPENAI_BASE_URL`,
  OpenCode's `baseURL` and the SDK's `base_url` want; both forms are
  accepted and the path is appended once.
- **`/v1/models` goes through the active transport too.** In direct
  mode the picker is part of the surface under test, and its failure is
  a result ("Gateway unreachable (direct) — …") rather than something
  to route around.
- **The key is never persisted.** Mode and base URL survive a reload in
  `localStorage`; the key defaults to the session token on every load
  and a typed one lives for the tab.
- **A refused preflight is a `403 Problem`, not Starlette's bare 400.**
  A browser reports every CORS failure as `Failed to fetch`; the `curl`
  of the same preflight deserves the sentence naming the config key.
- **`tool` messages are visible in the transcript.** A harness sends
  them, and the transcript is the request.

### What the run found

Two defects in the `curl` builder, both real, both found only by
replaying the copied line (§6 of the record): the key placeholder was
single-quoted and did not expand; and non-ASCII in the body does not
survive the Windows command line. And one harness defect of the
recurring kind: a selector that did not name its subject. All three are
in the acceptance record.

### Open

- **Two real origins.** Both ends were loopback here. The live install
  is where CORS between hosts and Chrome's local-network permission are
  real; nobody has clicked through the panel there yet, and the
  container must first be updated to a gateway at or past `f48b7c2`.
- **A long-lived client key** (§2.3) — the next slice on this surface,
  deliberately not started here.
- **Image attachments** need content parts in the contract (§7).
- `response_format: json_object` is offered and was not exercised live.

## 12. Where the build departed from this design

- **§6 said "byte for byte"**; the `curl` body is ASCII-escaped (§6,
  corrected in place, and the record says why).
- **§9's check list said the browser checks read "frames > 1 and the
  driver"**; they do, and the spec also records the prefill and the
  key-is-session-token facts as separate lines, which is why 15 checks
  print 28 `PASS` lines.
- **§3.2 said a refused origin is refused**; the actual request from an
  unlisted origin still *runs* and only the header is withheld — the
  browser blocks the read, which is what CORS can do and all it can do.
  A preflight from that origin is refused outright with the 403. Test
  and script assert both halves.
