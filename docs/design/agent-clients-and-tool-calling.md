# Agent clients, tool calling, and what the playground is for

**Status: design, 2026-09-11. Nothing here is built.** Every claim marked
*verified* was checked against a file, a registry or a live source on the
day of writing; everything else is reasoning and is marked as such — the
same convention as
[`install-paths-and-distribution.md`](install-paths-and-distribution.md).

Sits **after** the install work, not instead of it. A backend nobody can
install serves no agent harness either. See §8.

## Decisions needed

| #     | The call                                                                      | §   | Status                 |
| ----- | ------------------------------------------------------------------------------ | --- | ---------------------- |
| **1** | Carry tool calls end to end                                                     | §5  | **DONE 2026-09-11** — §9 |
| **2** | Does `/v1/embeddings` belong in scope, or is that Open WebUI's own problem?     | §5  | **OPEN**               |
| **3** | Context-window honesty: refuse, truncate-and-report, or configurable?           | §6  | **OPEN**               |
| **4** | The playground is a reference client and diagnostic, not a product             | §7  | **DECIDED 2026-09-11** |
| **5** | No native OS chat/agent application                                            | §4  | **DECIDED 2026-09-11** |

## 0. The finding: the gateway cannot carry a tool call

**Verified 2026-09-11 against `openapi/gateway.yaml` and
`openapi/inference-driver.yaml`.**

`ChatCompletionRequest` accepts exactly nine fields:

```
model  messages  max_tokens  temperature  top_p  stop  seed  stream  user
```

There is **no `tools`, no `tool_choice`, no `response_format`**. The
OpenAI-compatible surface is two endpoints — `/v1/models` and
`/v1/chat/completions` — and there is **no `/v1/embeddings`**.
`finish_reason` is an enum of exactly `stop` and `length`, whose own
docstring reads:

> `stop` for a natural end or a matched stop sequence, `length` for
> hitting the token cap — **OpenAI's two values for a completion without
> tool calls.**

The string "tool" appears **once** across both documents: in that
comment.

So a harness sends tool definitions, the gateway drops them, the model
never sees them, and there is no return path to report a tool call even
if a backend emitted one.

> **Claude Code, OpenCode, Hermes and every other agent harness cannot
> work against Eugene Plexus today. Not "works badly" — cannot.**

This is the same shape of gap as M10's: carried as a small thing, and in
fact a whole capability that was never built rather than one that was
broken. Nothing had noticed because nothing had pointed a harness at it.

## 1. Who the client is

The client is **an agent harness**, and a chat UI we happen to own is
not it. That follows from §0 in reverse: the surface a harness needs is
the surface we don't serve, and the surface we do serve is the one that
has commoditised.

This does **not** mean building a harness. See §4.

## 2. The evidence, and its limits

From the r/LocalLLaMA thread *"Friends Don't Let Friends Use Ollama"*
(2026-09-07, 1,152 points, 355 comments), read in full. Counts are of
distinct commenters:

**Supports the direction:**

- **Nine people ask "what should I use instead?"** — the most common
  comment shape in the thread. The answers are llama.cpp, llama.app, LM
  Studio, Unsloth Studio, KoboldCpp, llama-swap, Lemonade, textgen,
  MTPLX, OMLX, Msty, Dwarfstar, Hermes. **The thread demonstrates the
  piecing-together problem in its own answer set.**
- **Five people, unprompted, raise "I couldn't use the models I already
  had on disk"** — differentiator #3, and the single most-upvoted
  substantive complaint (147 points). One names *"the constant hash
  mismatches"*; another, *"downloading it in some unknown cache
  directory"*.
- **Quant choice is incomprehensible** — differentiator #6. Best
  articulation in the thread: HuggingFace's search is unusable and
  between two quantisations *"What's the difference? No one fucking
  knows."*
- **Six mentions of agent harnesses** (OpenCode, Hermes Agent, "a simple
  built in agent harness", an OpenCode VM against llama.cpp), including
  the one that matters most here: *"Ollama is the source of the vast
  majority of 'Help, my [agent/harness] is looping and can't seem to use
  any of the tools I installed'."*

**Cuts against current plans:**

- **Docker is explicitly rejected by this audience.** Three upvoted
  commenters: *"for many users 'just run it in docker' is a
  non-starter"* (38 points, the top reply in its subthread) and
  *"docker is literally the ollama of containerization"*; *"Fuck
  Docker. It is NOT a drop-in replacement."* This does not kill the
  Compose path — SMB is a different audience — but the container must
  never be the answer offered to a home user. The install design says
  this on architectural grounds; it now has evidence.
- **Differentiator #7 has essentially no demand signal.** Multi-host,
  load balancing and failover across heterogeneous backends: **one
  commenter out of 355**, asking about server deployment and RPC. The
  thing CLAUDE.md calls *"what makes the platform useful past a single
  desktop"* is not what this audience is asking for. Demoted, not
  deleted — see §8.

**The limit, stated by the thread itself:** its second-highest-voted
comment (251 points) is *"You are on a technical reddit, where like 1%
of users visit."* Another commenter: *"none of the programmers I know
who have decent graphics cards have tried any local AI… there isn't
much motivation to get into self hosted AI."* **This is evidence about
pain, not about market size.**

### 2.1 The competitive ground moved, and CLAUDE.md predates it

Both verified 2026-09-11 by search, not from the thread:

- **`llama.app` launched 2026-05-29** — the official llama.cpp site,
  with a cross-platform one-liner installer, a single unified `llama`
  binary, and a built-in web UI. The thread's own OP (llama.cpp flair)
  concedes the point: *"`llama serve -hf xyz` is more or less similar.
  But the llama.cpp/HF team is not expending enough calories to surface
  this, pretty it up and market it as cleanly as ollama does."*
- **NVIDIA has acquired Hugging Face** — announced roughly a week
  before this writing; primary source is Gerganov's own post. `ggml-org`
  sits inside that. Gerganov states llama.cpp/ggml stays hardware-
  agnostic and community-driven.

**Consequence: the easy-onboarding gap is closing from below, and the
entity closing it owns the model hub and has NVIDIA's resources.**
Discovery, download and quant guidance — #2 and #6 — are exactly where
HF-under-NVIDIA has the strongest natural position. That is not a reason
to stop. It is a strong reason **not to stake the positioning on "the
easiest way to run one model on one box."**

## 3. Chat is commoditising, not dying

The framing that opened this discussion was "web chat is a dying
platform." The correction matters because the two readings imply
different work:

- **Dying** → don't ship chat.
- **Commoditising** → ship it adequately, stop investing, don't remove.

The evidence favours the second. Open WebUI is actively building SSO,
SCIM and group RBAC — a product investing for enterprise, not one in
decline. The thread still contains people asking for a chat front end
they can deploy to a local network. What has changed is that chat is no
longer **differentiating**.

## 4. Not a native OS application — DECIDED 2026-09-11

A native desktop app "so more agent-like capabilities are possible" was
considered and is **not** being built. Two reasons.

**We already ship an OS-native process on every host: the agent.** It
runs as a service, supervises processes, holds filesystem access, and
after the install decisions is first-class on Linux, macOS and Windows.
Any OS-native capability belongs there. A second native surface is new
distribution work for a position already occupied.

**A native app for agent capabilities is a harness**, which means
competing with Claude Code, OpenCode, Hermes, Cline and aider on prompt
design and tool ergonomics — a different competency from process
supervision, in a field moving faster than a solo maintainer can track.
It also fights differentiator #5: **a harness wants to run where the
files are; the control plane runs where the GPU is.** In this project's
own two-building topology those are different machines.

## 5. The contract work

In dependency order. **Nothing below item 1 matters until item 1 lands.**

1. **Tool calls, end to end.** `tools` and `tool_choice` on
   `ChatCompletionRequest`; `tool_calls` on `ChatCompletionMessage` and
   on the streaming delta; `tool_calls` as a third `finish_reason`. The
   same additions on the inference-driver's `GenerateRequest` /
   response, since the driver carries none of it either. Radius:
   `gateway`, `inference-driver`, `ui`.
2. **`response_format`** — JSON mode and structured outputs. Harnesses
   use it constantly.
3. **`/v1/embeddings`** — *open call #2.* Open WebUI's RAG wants it but
   can also use its own embedder, so this is "first-class integration"
   rather than blocking. Worth deciding deliberately rather than by
   drift.
4. **Context-window honesty** — §6.

**The streaming interaction is a trap.** M10 established that failover
is possible until the first token and impossible after it. A tool call
arrives *as* streamed deltas that accumulate into a call. Deciding
whether a partially-streamed `tool_calls` delta counts as "the first
token" for failover purposes is a real question and must be answered in
the contract, not discovered in an acceptance run.

## 6. Context-window honesty is the actual differentiator

This is the one that earns the operations layer its keep, and it is
where the looping in *"my harness is looping and can't seem to use any
of the tools I installed"* comes from: a harness sends a long prompt
plus tool definitions, the server silently truncates to fit the context
window, the tool definitions fall out of the window, and the model —
which can no longer see the tools — loops.

Ollama is where those reports come from. LiteLLM routes but does not
supervise the engine, so it cannot know the window. **We launch the
engine, so we know the window, and we already own every
output-affecting parameter by standing decision.**

So the claim becomes testable, which is how this project prefers to
decide things:

> **Point a harness at Ollama and it loops. Point it at Eugene Plexus
> and it either works, or it tells you exactly why it can't.**

The behaviour itself is **open call #3** — refuse, truncate-and-report,
or configurable. The principle to apply is
`easy-default-expert-override`, whose corollary says to explain a real
failure rather than predict one; the failure here is real and
measurable, not predicted, so the bar for reporting it is low.

## 7. The playground — DECIDED 2026-09-11

**Troy's framing, adopted:** the playground exists to give a user a
starting point, to let development prove the backend, and to serve as a
**diagnostic instrument**:

> *"Playground connects to it and uses the tool just fine, so maybe my
> problem is with OpenCode."*

That is a bisection tool, and it is the reason the playground gets tool
calling, file attachment and the rest — **not** to compete with Open
WebUI or OpenCode. It is explicitly not a product.

The framing is load-bearing because it also decides what **not** to
build: a playground feature is justified when it proves something about
the backend or isolates a fault. Conversation management, prompt
libraries, personas and agent workflows prove nothing about the backend
and belong to the clients we are trying to serve.

### 7.1 The trap, and it is this project's recurring one

**A reference client that shares its path with the thing it tests,
tests nothing.** Every trap recorded this milestone and last is the same
family: *a check whose subject is not where it is looking*. If the
playground reaches the gateway through the UI's privileged proxy and its
generated TypeScript client, then "the playground called the tool" proves
that path works — **not** that a third-party OpenAI client works, which
is the claim the diagnostic is making.

So the diagnostic mode must go through **the same public surface a
harness uses**: `POST /v1/chat/completions` on the gateway with a bearer
token, no proxy privileges, no internal shortcuts. If that means the
playground is slightly awkward compared to what the UI could do
internally, that awkwardness *is* the instrument.

And it should **report what it observed**, not merely that it worked:
the `x_eugene_plexus` envelope already carries driver, runtime, backend,
`latency_ms`, `attempts`, `tier`, `swapped_in` and `waited_ms`, and
since M10 it rides the final stream frame too. Surfacing that turns "it
worked" into "it worked, and here is the path it took" — which is what
makes the bisection actionable for someone filing a bug.

## 8. What this does not change

- **The install work still comes first.** A backend nobody can install
  serves no harness. Canonical order is
  [`install-paths-and-distribution.md`](install-paths-and-distribution.md)
  §9.

  **Corrected 2026-09-11, after the first draft of this document said
  otherwise: the release now comes AFTER this work, not before it.**
  Troy's call and his reasoning — *if the project exists to relieve the
  pain in that thread, the project as it stands today would fail.* A
  control plane no agent harness can use does not answer that thread.
  And a release is a positioning event: shipping first would announce
  into the space `llama.app` and NVIDIA/Hugging Face just moved into
  (§2.1), rather than the one that is unclaimed.
- **Differentiator #7 is demoted, not deleted.** One commenter in 355 is
  weak demand *from this audience*, which is the home enthusiast. It is
  still what M5/M6/M7 built, it is still live-verified on two hosts, and
  it is still the SMB story. It just should not lead the pitch.
- **The seven differentiators are not rewritten here.** This argues for
  re-ranking (#2, #3, #6 and a working backend ahead of #7), not for
  dropping any.

## 9. Implementation record

**§5 items 1 and 2 are BUILT AND LIVE-VERIFIED, 2026-09-11 (late).**
Contracts `95dfa8f`; inference-driver `b2aab87`, gateway `bf2c930`,
`ui` `be94751`, the other three re-pinned because `common.yaml` changed.
Record: [`../acceptance/tool-calling-run.md`](../acceptance/tool-calling-run.md),
**16 checks, second attempt.** Items 3 (`/v1/embeddings`, open call #2)
and 4 (context honesty, §6 and install-paths step 7) are still open.

**§0 understated it in one direction and overstated it in another.** The
gateway really could not carry a tool call — but the driver could not
either, in three separate ways, each of which looked like something
else. `_FINISH_REASON_MAP` mapped a backend's `tool_calls` to
`FinishReason.stop`, so a model that *had* asked for a tool reported a
clean natural end and the calls were dropped one line later. The
non-streaming parser required `content` to be a string and raised
otherwise — and `content` is null on every tool-call-only turn, so the
well-formed case was the one that 502'd. And `_to_openai_messages`
coerced any unrecognised role to `user`, which with `tool` in the enum
would have turned a tool result into the human talking.

### Decided here rather than left to a run

**A backend that cannot carry tools fails the request; it is never
silently stripped.** §0 named the harm without naming the rule. A
harness receiving a plain answer cannot distinguish "the model chose not
to call anything" from "nobody ever offered it the tools" — and the
second is a bug wearing the first one's clothes, which is precisely the
looping symptom §6 describes. Producing it ourselves while claiming to
route around it would be worse than not shipping tools.
`capabilities.toolCalling` and `x_eugene_plexus.tool_calling` make the
question answerable before a request is sent.

**The two capability answers differ on purpose.** `GET /v1/models`
reports `tool_calling` only when *every* backend serving the model can —
the honesty rule `context_length` already follows, since a request may
land on any replica. The refusal asks whether *any* can. One advertises
what a caller may rely on; the other decides whether to fail a request
that would otherwise have worked.

**§5's streaming trap resolved without code.** A `tool_calls` delta is a
first token, so M10's commit point covers it, and `TieredClient.stream`
already set `committed` on the first event of any kind. The contract now
states it separately because the failure it prevents is worse than
M10's: spliced prose reads oddly, while spliced `arguments` — half
written by one model, completed by another — can parse as valid JSON
naming real parameters. A wrong *action* taken confidently, with nothing
at the seam to notice, handed to a harness that will execute it.

### What the live run taught

**Local engines do not fragment tool calls.** Ollama emits the entire
call — id, name and complete `arguments` — in one delta. The first
version of the streaming checks demanded many fragments and an early
time-to-first-fragment, which is a property of the *backend*: the check
could only have passed against a backend that fragments, and it failed
our correct pass-through. This project's recurring failure, in the
script written to avoid it. The checks are now equality with a baseline
measured in the same run, and a structural assertion that fragments
precede the terminal frame. OpenAI proper does fragment, so the
accumulation path is real and unit-tested with a fake that splits
`arguments` mid-token.

**`content` going nullable has the widest blast radius of anything
here** — five Python call sites and three TypeScript ones, all found by
the type checkers rather than at runtime, none of which would have
failed until a tool call actually came back.
