# What a prompt cache sees through Eugene

**Measured 2026-10-02** on Troy's box (RTX 5090, 32 cores, 96 GB) with
llama.cpp **b11211** (the CUDA build for the GPU runs, the CPU backends of
the Vulkan build with `--device none` for the CPU runs), Claude Code
**2.1.283**, Codex CLI **0.130.0** and vLLM **0.29.0** in WSL2. Behind
[`docs/design/prompt-cache.md`](../design/prompt-cache.md). Instruments, all
in `scripts/`:

| Instrument | What it does |
|---|---|
| `prompt-cache-capture.py` | Answers a real client with a scripted run of read-only tool calls and records every request whole |
| `prompt-cache-prefix.py` | Finds where each request stops continuing the one before it |
| `prompt-cache-measurement.py` | Replays captured sessions at real llama-server processes, direct and through a real one-node install (control root, enrolled agent, gateway, a driver per replica), reading the engine's own `llamacpp:prompt_tokens_total` before and after every request |
| `prompt-cache-summary.py` | The tables below, from its results |
| `prompt-cache-slot-restore.py` | A saved slot, restored into a fresh process, against reading the prompt again |
| `prompt-cache-mac.py` + `.github/workflows/prompt-cache-mac.yml` | The Apple-silicon half on GitHub's runners |

**The headline number is always the engine's counter**, the prompt tokens it
actually computed ("read" below). "Reused" is the share of all prompt tokens
it did not have to compute. Every replay sends `max_tokens: 1` (Responses:
16), so a request's time is almost all prompt reading.

The captures are not committed: they hold the clients' system prompts, which
are the vendors' text. Every port was chosen by the OS; none was in
8079-8290, and the live install was not touched (Troy stopped its runtime
for the GPU half).

## 1. What the clients send

Four sessions per client, each five requests (a first turn, then four tool
results), against `--read-dir` of three of the gateway's own source files.

**Within a session both clients send strict continuations**: every request
is the one before plus new messages, nothing earlier changed, for Claude
Code in `-p` mode, in `--continue` and interactive in a pseudo-terminal
(`cc_entrypoint=cli`), and for Codex in `exec` and `exec resume`.

**Across sessions they differ**:

| | Claude Code 2.1.283 | Codex 0.130.0 |
|---|---|---|
| Shared by every session | system prompt + 23-26 tools, ~75,000 characters | instructions + 10 tools, ~47,000 characters |
| Where two sessions first differ | **character 47 of system block 0** | the first user message |
| Why | `x-anthropic-billing-header: cc_version=2.1.283.<3 hex>; cc_entrypoint=…;`. The suffix follows the session's first prompt (`.485`, `.b98`, `.870`, `.146` for four prompts; the same prompt gives the same suffix every time) | — |
| A key the client offers | `session_id` inside `metadata.user_id` | `prompt_cache_key` = the session id, every request |

This build sends no `cch=` or `cc_prev_req=` against a non-Anthropic address,
even with the stub returning `request-id` headers. Older and other builds
do, and those change on every request (ggml-org/llama.cpp #21793,
musistudio/claude-code-router #1372, RimantasZ/contextspy #65). Turning the
header off on the client is `CLAUDE_CODE_ATTRIBUTION_HEADER=0`.

**Workbench**, read from source: the chat's instructions as one system
message, then the history, with only the final answer text of each
assistant turn sent back. Cache-friendly.

## 2. One replica, direct and through Eugene

Sessions one after another on a fresh engine. CPU, Qwen3-0.6B Q4_K_M,
16 threads, `-c 40960`:

| Client | Path | Prompt tokens | Read | Reused | Seconds | First turn of sessions 1-4 read |
|---|---|---|---|---|---|---|
| Claude Code | direct | 448,997 | 111,725 | 75.1% | 334.5 | 18,670 · 18,667 · 18,669 · 18,667 |
| Claude Code | Eugene, before the fix | 448,997 | 111,725 | 75.1% | 337.2 | same |
| Claude Code | Eugene, header normalised | 449,002 | 61,383 | 86.3% | 250.8 | 18,670 · 1,887 · 1,888 · 1,886 |
| Codex | direct | 219,770 | 13,782 | 93.7% | 34.6 | 10,600 · 18 · 19 · 17 |
| Codex | Eugene | 219,570 | 13,772 | 93.7% | 35.6 | 10,590 · 18 · 19 · 17 |

**Eugene reads exactly what the engine reads direct**, turn for turn, on both
doors, and the `cache_read_input_tokens` / `cached_tokens` it reports match
the engine's counter. A cached turn takes 0.99 s where the same turn cold
takes 36 s. Turns that carry a tool result read the result (2,506, 4,189,
2,420 tokens); nothing can save that.

**The fix, measured through Eugene itself** (GPU, Llama 3.1 8B Q4_K_M,
`-c 49152`; the gateway's Anthropic door now takes the header line off,
gateway working tree 2026-10-02):

| Client | Path | Reused | Seconds | First turns read |
|---|---|---|---|---|
| Claude Code | direct (header as sent) | 75.3% | 16.9 | 19,719 · 19,717 · 19,718 · 19,716 |
| Claude Code | **Eugene, header taken off** | **86.7%** | **9.3** | 19,693 · 1,860 · 1,861 · 1,859 |
| Codex | direct | 93.9% | 3.6 | 11,043 · 18 · 19 · 17 |
| Codex | Eugene | 93.9% | 4.3 | 11,035 · 18 · 19 · 17 |

## 3. Model families (GPU, direct, `-c 65536`, three sessions)

| Model | Attention | Claude Code reused, header as sent → normalised | Seconds | Codex reused |
|---|---|---|---|---|
| Llama 3.1 8B Q4_K_M | full | 75.3% → 85.2% | 12.5 → 6.2 | 92.3% |
| gemma-4-12B Q4_K_M | sliding window (1,024), 5 of 6 layers | 74.1% → 83.5% | 20.3 → 12.1 | 92.1% |
| Qwen3.5-4B Q4_K_M | hybrid: SSM + full attention every 4th layer | **refused**; with in-conversation system messages folded: 74.9% → 84.8% | 8.9 → 6.5 | refused direct (§5) |
| Qwen3.8-27B UD-Q4_K_M | hybrid | **refused**; folded: 75.0% → 84.8% | 29.1 → 19.6 | 92.1% |
| Qwen3.6-35B-A3B UD-Q4_K_M | hybrid MoE | **refused**; folded: 74.9% → 84.8% | 15.2 → 10.7 | — |

**Hybrid and sliding-window models cache a growing conversation as well as
full attention does on this build**: no "full prompt re-processing" line in
any engine log, and per-turn reads equal to the plain model's. On the 27B a
new Claude Code session's first turn takes 5.50 s with the header and 0.88 s
without.

## 4. Several sessions on one replica

Sessions taking turns (s1 t1, s2 t1, … s1 t2, …), through Eugene.

**CPU, Qwen3-0.6B, four Claude Code sessions, header as sent: 33.4% reused,
850 s**, against 75.1% and 334 s one after another. By turn 4 every session
re-read its whole prompt (25,513 tokens, 72 s); the engine log shows its
8 GiB host-RAM prompt cache evicting ("making room for prompt cache entry,
removing oldest entry", 2.3-3.0 GiB per entry). Codex held at 91.5%.

**GPU, Llama 3.1 8B, eight sessions, header normalised: 74.2% reused**
(Codex 94.2%), against 86.7% for four one after another. Tokens read per
turn:

| | t1 | t2 | t3 | t4 | t5 |
|---|---|---|---|---|---|
| Taking turns, sessions 2-8 | 1,860 | 1,990 | 4,486 | 8,626 | 11,093 |
| One after another | 1,860 | 148 | 2,506 | 4,189 | 2,420 |

The shared system prompt stays warm; **each session's own history is read
again on every turn**. `--cache-ram 32768` changed nothing (identical
reads, no evictions logged in either run): a slot holding another session
already matches ~80% of the prompt, so llama-server takes it and does not
look in its RAM cache for the session's own state.

**Raising `--slot-prompt-similarity` makes it worse, not better.** At 0.95
and at 0.99 (with `--cache-ram 32768`) Claude Code fell to 45.6% reused and
101.9 s / 94.2 s. The engine did reach for the session's saved state and
could not put it back: `failed to restore state with size 3468090180 …
error loading state: failed to restore kv cache`, after which turn 5 read
28,924 tokens. A 3.4 GB state does not fit back into a 49,152-token pool
that other slots hold (related upstream: ggml-org/llama.cpp #17527, closed).
So on one replica the engine's own multi-session caching is bounded by its
KV pool, and no flag Eugene could set fixes that; more replicas with
affinity, or a pool sized for the sessions, does.

## 5. Claude Code and the Qwen 3.x templates (not caching, found here)

Claude Code sends `system` messages inside the conversation. Every Qwen 3.x
chat template raises `System message must be at the beginning`, so
llama-server answers 500 and the gateway answers 502 *"Every backend
serving this model failed"*. Measured on Qwen3.5-4B through Eugene and on
Qwen3.8-27B direct: **three of the five starter classes cannot serve Claude
Code through Eugene**. Folding each one into a user turn in place (the
replay's `--fold-system`) makes all three answer, and keeps the prefix
stable. Filed as eugene-plexus/gateway#6.

**And the failure spreads.** That 500 trips the backend's circuit like a
dead engine would, so Codex's next requests to the same model, which
worked a request earlier, got 503 *"cooling down"* for the rest of the run.
Filed as eugene-plexus/gateway#7.

## 6. Restarting the engine

`prompt-cache-slot-restore.py`, GPU:

| Model | Read the prompt again | Save | Restore | Next turn after restore |
|---|---|---|---|---|
| Llama 3.1 8B (Claude Code, 19,849 tokens) | 1.84 s | 3.06 s, 2,481 MiB | 0.85 s | 1 token, 0.06 s |
| Qwen3.8-27B hybrid (Codex, 11,116 tokens) | 3.51 s | 0.57 s, 845 MiB | 0.33 s | **11,101 tokens, 3.47 s: nothing reused** |
| Qwen3.6-35B-A3B hybrid MoE (Codex, 11,078 tokens) | 1.82 s | 0.20 s, 279 MiB | 0.17 s | **11,063 tokens, 1.92 s: nothing reused** |

On full attention a restore works and is about twice as fast as reading
again, for gigabytes of disk. On hybrid models (and sliding-window ones)
it reuses nothing, because context checkpoints are not saved with the
slot: known upstream, ggml-org/llama.cpp #28194 and #25913 (open). So
saving slots across an idle unload would help only full-attention models,
and three of the five starter classes are hybrid.

## 7. Two replicas behind the gateway

GPU, two Llama 3.1 8B replicas (`-c 49152` each), header normalised, one
request at a time. "Eugene" is today's `least_busy` balancer; "pinned" sends
each session to one replica (odd sessions to A, even to B), which is what
affinity routing would do:

| Sessions | Client | Eugene today | Pinned |
|---|---|---|---|
| 1 | Claude Code | 52.8% reused, 6.0 s | **75.3%, 3.3 s** |
| 1 | Codex | 59.1%, 2.7 s | **79.4%, 1.6 s** |
| 3 | Claude Code | 65.9%, 14.5 s | 70.8%, 11.8 s |
| 3 | Codex | 83.8%, 4.6 s | 84.5%, 4.0 s |

**One session on an idle two-replica install alternates every turn**
(A, B, A, B, A). Turn 2 lands on the cold replica and reads everything
(19,823 tokens). Turns 4 and 5 each read the two turns their replica missed
(6,636 and 6,607, against 4,189 and 2,420 on one replica). Pinned, the same
session reads exactly what one replica does. The gap narrows with more
sessions because both replicas soon hold the prefix every session shares,
and it widens with longer histories and bigger tool results, which is what
agent sessions are.

With four sessions the alternation happens to keep each session on one
replica (requests alternate A, B and sessions repeat with period four), so
Eugene and pinned tie at 68.5%; that run is recorded and not counted.

## 8. Hosted backends (cost: about $0.08)

Direct to the provider, a 7,277-token system prompt:

| Backend | Request 1 | Request 2 |
|---|---|---|
| Claude Haiku 4.5 via OpenRouter, nothing marked | $0.0073, 0 cached | $0.0073, 0 cached |
| same, `cache_control` on the system block | $0.0091, 7,256 written | **$0.00077, 7,256 cached** |
| same, request-level `cache_control`, a growing conversation | $0.0091, 7,267 written | **$0.00077, 7,267 cached** |
| OpenAI gpt-4.1-mini, nothing marked | 0 cached | 6,144 of 6,283 cached |
| gpt-4.1-mini via OpenRouter, request-level `cache_control` | accepted | 6,144 cached |
| Gemini 2.5 Flash via OpenRouter | 0 cached | 0 cached |

Anthropic models cache only when asked; OpenAI does by itself. Request-level
`cache_control` on OpenRouter places the breakpoint after the last message,
so it caches a conversation's earlier turns (a probe whose last message
changed while the rest stayed put wrote twice and read nothing). **The
gateway drops `cache_control` at the Anthropic door**, so a client routed to
a Claude model through OpenRouter pays the full price on every turn.

## 9. vLLM and Apple silicon

**vLLM 0.29.0** (WSL2, Qwen3-0.6B, `--max-model-len 40960`, no caching
flags, which is what the agent's recipe passes): automatic prefix caching
is on by default and works across sessions. Two Codex sessions on
`/v1/responses`: every later turn reused all but ~200 tokens, and the
second session's first turn reused 10,608 of 10,629 (the engine's own
`prefix_cache_hits_total` agrees). **But it reports that only on the
Responses API.** On `/v1/chat/completions`, the path Eugene's driver uses,
the second of two identical-prefix requests ran in 0.03 s against 0.08 s
and reported `prompt_tokens_details: None`; with
`--enable-prompt-tokens-details` the same pair reported `cached_tokens: 0`
then `5136`. So Eugene shows no vLLM cache today, and one flag fixes it.
(Its `/v1/messages` refused Claude Code's tools without
`--enable-auto-tool-choice`; not a caching matter.)

*Apple silicon pending: mlx_lm.server 0.31.3 and llama.cpp's Metal build on
GitHub's macOS runner.*

## 10. What Eugene does today, from the code

- `RoutingTable._order` (gateway `routing.py`) rotates a per-model cursor on
  every request, then under `least_busy` sorts by in-flight per slot. No
  notion of a conversation.
- The Anthropic door drops `cache_control` and `metadata`; the Responses and
  chat doors forward `prompt_cache_key` only to OpenAI's own API.
- The metrics table records `prompt_tokens` per attempt and no cached count.
- The agent passes none of `--cache-ram`, `--ctx-checkpoints`,
  `--cache-reuse`, `--slot-save-path` or `--slot-prompt-similarity` to
  llama-server, and neither `--enable-prefix-caching` nor
  `--enable-prompt-tokens-details` to vLLM; it does expose MLX's
  `--prompt-cache-size` and `--prompt-cache-bytes`. Admission does not
  count llama-server's default 8 GiB of host RAM for its prompt cache.
- Idle unload is opt-in and nothing in the UI sets it.

## Not measured

- Concurrency: every replay is one request at a time.
- A real tool loop with the model's own answers: the replay appends the
  captured stub's answer, so the engine generated one token that the next
  request replaced. Templates that strip earlier reasoning would cost a
  little more.
- Open WebUI's requests, and its title and tag side requests competing for
  slots.
- The live install's own hardware mix, and a second machine.
