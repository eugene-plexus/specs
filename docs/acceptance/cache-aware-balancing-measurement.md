# Many conversations, many replicas: what the prompt cache sees

**Measured 2026-10-02 (late)** on Troy's box (RTX 5090, 32 cores, 96 GB) with
llama.cpp **b11211** (CUDA build), Claude Code **2.1.283** and Codex CLI
**0.130.0**. Behind [`docs/design/cache-aware-balancing.md`](../design/cache-aware-balancing.md),
which follows [`prompt-cache.md`](../design/prompt-cache.md) and its record
[`prompt-cache-measurement.md`](prompt-cache-measurement.md). Troy's brief:
load balancing that is cache-aware **at scale, dozens of users across dozens
of backends**; PC4 had been measured one request at a time on at most two
replicas.

Every port was chosen by the OS and none was in 8079-8290; the live install
was not touched, and its runtime was already stopped (the GPU held 1.2 GB,
no `llama-server` running).

**In short:**

- **Today's install fails agent turns under concurrency** (§8): an 8B at
  `-c 65536` with four agents a replica answered 46 of 204 turns. A few
  prompts outgrow the pool the four slots share; the gateway's circuit
  takes each healthy replica out for it.
- **Placing new conversations by what a replica holds (spread) is what
  scales** (§5, §7): within noise on three replicas, 60% → 80% reused on
  eight.
- **A token budget per replica removes the pool's failures** (§5, §7): 0 in
  1,088 turns where spread alone failed 153.
- **llama-server keeps one conversation per prompt family in its slots**
  (§1); pinning slots from Eugene adds ~3.5 points where the pool has room
  for a conversation per slot and loses up to 10 where it does not; and
  **pinning to a busy slot wedges the engine** (§4), which waiting in front
  of it avoids.
- **Prefix placement, rendezvous hashing and two gateways** measured at or
  below the simpler choice (§3, §5, §7).
- **After the build (§9):** the 8B shape answers every turn (204 of 204,
  where it answered 46); the pool's failures are gone under `spread` on eight
  replicas; driver pinning stalled no turn in 612; and with the budget in,
  `spread` and `least_busy` reuse about the same.

## 0. Instruments

| Instrument | What it does |
|---|---|
| `prompt-cache-capture.py` | As before. **Fixed here:** its Codex shell steps were one pre-quoted string, which Codex's `shell` tool quotes again, so every Codex tool result captured before this (the previous record's included) was `The filename … syntax is incorrect` or a sandbox refusal, never a file. Steps are argv lists now |
| `prompt-cache-measurement.py --experiments concurrent` | New. 2-8 replicas behind a real one-node install; many sessions at once; one run per balancing policy, each on fresh engines and a fresh gateway (§2) |
| `prompt-cache-summary.py` | Gained the concurrent table |

**Sessions:** 32 Claude Code and 32 Codex, each one `-p` / `exec` run of 8 tool
turns (9 requests) over one of four sets of six source files (3-8 KB each).
A Claude Code session grows from ~19,700 to ~31,000 prompt tokens, a Codex
one from ~11,000 to ~22,000. Claude Code's billing header is normalised and
its in-conversation system messages folded before replay (what the gateway
does since PC1/PC2), so the direct and gateway paths see one prompt.

## 1. What one llama-server does with several conversations

Before anything about balancing: how many conversations can one replica
keep warm? Sequential, direct, one engine, Llama 3.1 8B Q4_K_M,
`-c 131072`, llama-server's automatic 4 slots sharing one pool (what the
agent launches when a profile leaves `parallelSlots` unset). Room for every
conversation below several times over.

**Default settings keep ONE conversation per prompt family warm, however
many slots and however much pool it has.** Five Claude Code sessions taking
turns: every request after the first reused exactly 17,857 tokens, the
shared system prompt and tools, and read its own history again:

| | t1 | t2 | t3 |
|---|---|---|---|
| A session alone (previous record) | 19,729 | 148 | 2,506 |
| Five sessions taking turns, default | 19,729, then 1,869-1,871 | **2,009-2,012** | **4,515-4,518** |

The engine log says why: every one of the twelve requests was placed in
slot 3 (`selected slot by LCP similarity, f_sim_best = 0.905`); slots 0-2
were never used. A new conversation that shares 90% of another's prompt is
sent to that conversation's slot, over an empty one, and the other's tail is
gone. The RAM prompt cache (`--cache-ram`, 8 GiB by default) does not save
it, because keeping 90% of the slot looks like a continuation. This is
upstream's #22083 ("massive cache trashing", open PR since 2026-04) and the
reason the previous record's eight sessions on one replica reread each
history every turn: **its conclusion that the limit is the pool, not the
choice, is wrong.** The pool had room; the choice wasted it.

**Every setting llama-server offers fails in a different way:**

| Setting | What happened (three or five sessions, sequential) |
|---|---|
| default (`-sps 0.10`, idle slots cached) | one slot for every session; tails lost (above) |
| `-sps 0.95` | slots chosen least recently used; on each new task every idle slot is copied to RAM and cleared (`--cache-idle-slots`, on by default with a unified pool), so tails are still lost, and each request costs ~1 s for the copy |
| `-sps 0.95 --no-cache-idle-slots` | t2 reads 140 tokens (perfect), then **t3 rereads 22,375**: the similarity is the shared length over the NEW prompt's length, and a turn that adds more than 5% (any file read) falls below the threshold |
| `id_slot` on `/v1/messages` | ignored: the Anthropic conversion does not carry it (upstream PR #28554, open) |

**Pinning by `id_slot` on `/v1/chat/completions` (the path Eugene's driver
uses) works, but only with `--no-cache-idle-slots`** (or `--cache-ram 0`).
Three synthetic agent sessions (a 5,775-token system prompt, a file a turn):

| | t1 read | t4 read | |
|---|---|---|---|
| default | 5,775, then 13, 13 | 4,394-5,116 | prefix shared, tails reread |
| pinned, idle slots cached (default) | 5,775 each | **10,156-10,878 (everything)** | an empty pinned slot never consults the RAM cache: upstream #28139, fix PR #28992 open |
| pinned, `--no-cache-idle-slots` | 5,775 each | **1,514-2,041** | each session reads only its new turn |

The pinned engine pays once for what the default shares: a new conversation
in an empty slot reads the whole prefix (slots never share KV in
llama-server). It pays nothing after that.

**When pinned slots outgrow the pool, the engine says nothing.** Three
pinned sessions growing past a 24,576-token pool: from t4 the engine cleared
slots and reread them in full (`cache_n = 0`, 10,156-15,833 tokens), with no
error and no log line at the default verbosity. The only signal is the
cached-token count on the next answer, which Eugene already records (PC5).

**A correctness note, not a caching one:** upstream #27148 (open) reports
the default RAM prompt cache restoring an unrelated conversation into a
fresh slot under concurrent load, with `cached_tokens: 0` in the answer.
Not reproduced here; every replay below checked status, not content.

## 2. The concurrent replay

`ConcurrentBench`: N replicas of one model, each `llama-server --parallel 4
--kv-unified -c <ctx>` (the agent's default made explicit, so the gateway
can be told the true slot count) behind a recording proxy; a driver per
replica; a real gateway. Sessions are closed loops: a turn is sent when the
previous one answered and a seeded exponential think time (mean 2 s, the
same draws for every policy) has passed; `--concurrency` sessions run at
once, the next starting as one ends. Each turn streams, generates up to 64
tokens (so a slot is busy as long as a turn really is) and is timed to its
first output event at the client. One client key per session.

Two things the bench does that an install does not, both measured to change
nothing they should not:

- **The gateway is told each replica's slot count.** The bench's drivers
  front engines it started, with no supervised runtime, so the gateway would
  read every replica as one slot, and PC4 would move a conversation whenever
  its replica had anything in flight. `bench_parallel_slots` replaces only
  the source of the number.
- **The proxy sets `tool_choice: none`**, because a 1B's malformed tool calls
  make llama-server's parser drop the stream mid-answer. The prompt is
  byte-identical (the next request reused 782 of 783 tokens); the answer
  arrives as text.

Its numbers: the engines' own counters are the headline; the proxy's
per-request `timings` must sum to them (they do, exactly, in every run);
every request is joined to its engine record by the gateway's
`X-Request-ID`. A later turn's history is **held** if the engine reused at
least the previous turn's whole prompt, **evicted** if not and the turn went
to the same replica, **moved** if it went elsewhere.

**The harness's own routers.** Placements the gateway does not have are made
by the harness and sent through the gateway to one replica's own model id,
so the prompt is exactly what the balanced path would send. Its
re-implementation of PC4 matched the gateway's `conversation` to 3 tokens in
703,504 (two replicas, four sessions, both modes).

## 3. Three replicas, twelve sessions at once

Llama 3.2 1B Instruct Q8_0 (the Llama 3 tokenizer and template, so the
token counts match the previous record's 8B; a quarter of its KV cache per
token, so three replicas with four pinned slots each fit on one card),
`-c 131072` per replica, 24 sessions (12 Claude Code, 12 Codex), 12 at once,
204 requests a run. "Read" is the engines' counter; t1 is the first turn of
each session (a new conversation), "later" every other turn. TTFT is the
client's, so it includes the gateway and any queueing; the replicas share
one GPU, so a run that reads less is faster for everyone.

| Mode | Policy | Reused | Read (k tokens) | t1 read, avg | Later read (k) | Claude Code | Codex | TTFT p50 | p90 | p99 | held / evicted / moved | Stalled |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| default | `least_busy` | 67.7% | 1,355 | 6,897 | 1,189 | 72.1% | 61.0% | 1.49 s | 3.72 | 8.61 | 56 / 10 / 114 | 0 |
| default | `round_robin` | 65.2% | 1,461 | 7,838 | 1,272 | 70.8% | 56.5% | 1.04 | 6.40 | 8.56 | 39 / 12 / 129 | 0 |
| default | **`conversation` (PC4)** | **80.8%** | 804 | 7,096 | 634 | 80.1% | 82.0% | 0.71 | 1.93 | 6.03 | 141 / 34 / 5 | 0 |
| default | spread | 81.3% | 782 | 8,036 | 589 | 80.9% | 82.0% | 0.73 | 2.11 | 4.27 | 143 / 33 / 4 | 0 |
| default | prefix | 81.4% | 781 | 7,835 | 593 | 81.2% | 81.6% | 0.66 | 2.46 | 5.98 | 143 / 30 / 7 | 0 |
| default | hrw (stateless) | 76.4% | 987 | 8,037 | 794 | 77.1% | 75.4% | 1.13 | 4.28 | 8.48 | 117 / 32 / 31 | 0 |
| default | PC4, two gateways | 75.2% | 1,037 | 8,037 | 845 | 77.5% | 71.9% | 0.93 | 3.65 | 6.52 | 94 / 22 / 64 | 0 |
| default | hrw, two gateways | 76.4% | 988 | 6,897 | 823 | 79.5% | 71.7% | 0.95 | 3.94 | 7.18 | 110 / 35 / 35 | 0 |
| default | PC4, table lost at 20 s | 80.6% | 812 | 7,294 | 637 | 80.5% | 80.8% | 0.67 | 2.56 | 6.96 | 138 / 30 / 12 | 0 |
| default | hrw, state lost at 20 s | 75.8% | 1,016 | 7,144 | 844 | 78.0% | 72.3% | 0.94 | 4.01 | 7.18 | 101 / 25 / 54 | 0 |
| pinned | `least_busy` | 70.8% | 1,223 | 10,460 | 971 | 75.8% | 63.3% | 1.88 | 5.29 | 8.90 | 75 / 8 / 97 | 0 |
| pinned | `round_robin` (three runs) | 68.4-71.5% | 1,197-1,300 | 8,780-9,521 | 981-1,071 | 73-77% | 61-63% | 1.07-1.54 | 3.2-6.4 | 8.5-30 | 53-63 / 4-5 / 107-122 | **8**, 0, 0 |
| pinned | **`conversation` (PC4)** | **84.1%** | 668 | 10,462 | 416 | 85.9% | 81.3% | **0.47** | 2.15 | 6.32 | 166 / 7 / 7 | 0 |
| pinned | **spread** | **85.1%** | **622** | 11,400 | **349** | 87.1% | 82.1% | **0.42** | 2.41 | 7.41 | 170 / 6 / 4 | 0 |
| pinned | prefix (two runs) | 82.7-83.5% | 687-726 | 10,269-11,619 | 413-510 | 84% | 81-83% | 0.44-0.46 | 2.6-4.1 | 6-11 | 155-162 / 12-13 / 4-12 | **2**, 0 |

**Run to run, the same policy moves 1.5 points** (three pinned
`round_robin` runs: 68.4, 71.5, 69.0%; two pinned prefix runs: 83.5, 82.7%).
Differences smaller than that are not results.

What it says:

1. **Under concurrency, affinity is worth far more than the sequential
   record showed.** PC4 against `least_busy`: 80.8% against 67.7% reused,
   41% fewer tokens read, TTFT p50 0.71 s against 1.49 s. `least_busy`
   placed 114 of 180 later turns on a replica without their history.
2. **Pinning slots adds about three points on top of affinity, and only on
   top of it.** PC4 pinned: 84.1% against 80.8%; later turns read 416k
   tokens instead of 634k, TTFT p50 0.47 s instead of 0.71 s, evicted turns
   7 instead of 34. It costs new conversations: a fresh slot shares nothing,
   so a first turn reads 10,462 tokens on average instead of 7,096. Without
   affinity, pinning buys almost nothing (`least_busy` 70.8% against 67.7%).
   Claude Code gains most (80.1 → 85.9%); Codex does not move (82.0 → 81.3%),
   because its turns add little history.
3. **Placing new conversations by the conversations a replica holds (spread)
   or by prompt family (prefix) is within noise of PC4's least busy** at
   this scale: 81.3% and 81.4% against 80.8% default, 85.1% and 82.7-83.5%
   against 84.1% pinned. With twelve sessions on three replicas, least busy
   already spreads them evenly.
4. **Stateless rendezvous hashing costs five points.** Its bounded load is
   recomputed on every request, so a conversation changes replica when the
   load shifts (31 moved turns against PC4's 5). **Two gateways with their
   own tables cost the same** (75.2%), and hashing does not rescue them
   (76.4%). **Losing PC4's table at 20 s costs almost nothing** (80.6%): only
   the conversations whose next placement happened to differ moved (12).
5. **Pinning stalled llama-server, intermittently**: in the first matrix,
   8 of 204 turns under pinned `round_robin`, 2 under pinned prefix and at
   least 2 under pinned hrw (a run stopped part-way) waited for the
   gateway's 600 s deadline; two re-runs of each at default verbosity and one
   at `-lv 4` stalled 0 times. Every stall has the same shape in the engine
   log: a task pinned to a slot is launched (`launch_slot_ … processing
   task`) and never processed, no prompt timing, no release, until its client
   gives up (`stop: cancel task`), while the task counter climbs by about
   17,000 a second; once, the whole server accepted nothing else for eight
   minutes. No `failed to find free space` or `purging slot` line, so it is
   not the pool. Not found upstream (nearest: #27361, a pool-full deadlock
   with idle slots; #27505, a deadlock under sustained chat load on Vulkan).
   Never seen without pinning. **§4 shows it is pinning to a busy slot, and
   that waiting in front of the engine instead (`pinsafe`) removes it.**

## 4. Three replicas, twenty-four sessions at once: past the slots

The same 24 sessions all at once: eight per replica against four slots. The
shared GPU is saturated (TTFT in seconds), so every token not read again is
latency everyone gets back.

| Mode | Policy | Reused | Read (k) | TTFT p50 | p90 | p99 | held / evicted / moved | Stalled |
|---|---|---|---|---|---|---|---|---|
| default | `least_busy` | 64.7% | 1,477 | 7.57 s | 14.49 | 18.25 | 44 / 29 / 107 | 0 |
| default | PC4 | 75.0% | 1,047 | 4.51 | 8.49 | 12.58 | 104 / 71 / 5 | 0 |
| default | spread | 75.6% | 1,022 | 3.77 | 8.86 | 13.29 | 114 / 56 / 10 | 0 |
| default | prefix | 75.8% | 1,016 | 3.29 | 9.44 | 11.81 | 114 / 47 / 19 | 0 |
| default | hrw | 75.4% | 1,032 | 3.65 | 9.79 | 15.99 | 97 / 34 / 49 | 0 |
| default | PC4, two gateways | 66.5% | 1,404 | 5.41 | 11.68 | 14.77 | 54 / 39 / 87 | 0 |
| pinned | PC4 | — | — | — | — | — | — | **9 of 200; stopped after 70 min** |
| pinned0 (`--cache-ram 0`) | PC4 | **36.2%** | 2,674 | 8.63 | 28.94 | 56.74 | 37 / **136** / 7 | 0 |
| pinned0 | spread | 48.2% | 2,172 | 4.13 | 22.75 | 71.20 | 71 / 100 / 9 | 0 |
| **pinsafe** | PC4 | 76.2% | 996 | 4.49 | 8.76 | 12.80 | 121 / 49 / 10 | **0** |
| **pinsafe** | spread | **77.8%** | **932** | 4.30 | 8.44 | 10.78 | 116 / 56 / 8 | **0** |
| **pinsafe** | `round_robin` | 63.0% | 1,551 | 5.08 | 25.18 | 33.98 | 31 / 21 / 128 | **0** |

**Past the slots, the engine's RAM prompt cache is what holds the overflow,
and pinning that turns it off is a disaster.** Without it (`pinned0`) a slot
taken by another conversation loses its state outright: 136 of 180 later
turns reread their history, 36% reused. llama-server's default copies every
idle slot to the 8 GiB RAM cache on each new task and restores the best
match, which on a 1B is room for about ten conversations a replica.

**What wedged llama-server is pinning a request to a slot that is busy.**
Every wedge in the logs follows requests pinned to a slot still serving
another; on that path `get_available_slot` returns the busy slot and, with
the RAM cache on, runs its prompt-cache update on it (save, then load or
clear) before the caller defers the request (b11211 and master `bed0a8566`,
`tools/server/server-context.cpp`). A 24-at-once run, eight conversations
per four slots, does it constantly: 9 stalls in 200 turns and a main loop
that processed nothing for 30 minutes (replica a: three tasks launched
between 0:20 and 0:26, decode slowing to 209 ms a token, then no line but
three unanswered cancellations until 30:22). A deterministic two-request
repro on one CPU engine did *not* wedge, so the trigger is not that alone.
**`pinsafe`** keeps the RAM cache and never names a busy slot: a request
whose slot is busy, or a new conversation when none is idle, waits in front
of the engine. **Zero stalls in 612 turns** of the three patterns that
wedged worst, and the best numbers in the table: spread 77.8% and 932k
tokens read against PC4's default 75.0% and 1,047k.

## 5. Eight replicas, thirty-two sessions at once: the pool, not the slots

All 64 sessions (32 Claude Code, 32 Codex), 32 at once, on eight replicas
with a q8_0 KV cache and `-c 98304` each so eight fit on the card (30.9 of
32.6 GB): four conversations a replica, as many as its slots, but four
Claude Code prompts of 25-31k tokens are more than its pool. 544 requests a
run (this said 576 until 2026-10-02, late; the files say 544).

| Mode | Policy | Reused | Read (k) | TTFT p50 | p90 | p99 | held / evicted / moved | Failed |
|---|---|---|---|---|---|---|---|---|
| default | `least_busy` | 49.7% | 4,841 | 6.35 s | 18.78 | 40.68 | 131 / 8 / 251 | 60 |
| default | PC4 | 60.4% | 3,839 | 4.00 | 16.26 | 30.99 | 251 / 25 / 124 | 56 |
| default | **spread** | **80.2%** | 2,007 | **1.05** | 10.83 | 30.51 | 360 / 37 / 37 | 44 |
| default | prefix | 77.4% | 2,110 | 1.79 | 13.11 | 29.20 | 316 / 39 / 45 | 76 |
| default | hrw | 73.5% | 2,301 | 2.23 | 14.44 | 26.71 | 246 / 57 / 62 | 102 |
| default | PC4, two gateways | 66.7% | 2,875 | 2.81 | 15.46 | 44.63 | 185 / 19 / 150 | 114 |
| default | **spread_fit** | **81.5%** | 2,070 | 1.26 | **7.89** | **16.93** | 398 / 82 / 0 | **0** |
| pinsafe | PC4 | 71.4% | 2,979 | 1.66 | 15.81 | 42.80 | 341 / 10 / 86 | 29 |
| pinsafe | spread | 79.1% | 2,076 | 1.20 | 11.80 | 35.26 | 373 / 19 / 32 | 53 |
| pinsafe | spread_fit | 78.7% | 2,190 | 1.18 | 10.53 | 27.22 | 383 / 55 / 0 | 41 |

**Every failure is the pool.** Four slots share `-c` (the agent's default,
llama-server's automatic slots with one unified pool); when the prompts in
flight on a replica add up past it, llama-server refuses the next with
`500 Context size has been exceeded` or cuts a stream mid-answer. The
driver reports both as a 502, so the gateway's circuit counts them as a
broken backend and cascades the turn to another replica (PC4's 124 moved
turns), where it arrives cold and reads more, which overflows that pool in
turn. On the harness's routes there is no other replica to cascade to and
the circuit's "cooling down" 503s are the failures counted. **It reaches
real installs**: any profile whose context is shared by several slots, with
agent clients whose prompts are tens of thousands of tokens.

1. **At eight replicas, placing new conversations by the conversations a
   replica holds is the difference between 60% and 80%.** `least_busy` sees
   in-flight requests, and a replica whose four agents are all thinking
   between turns looks empty, so new conversations pile onto it. Spread
   counts what it holds. On three replicas this was 1.2 points; here it is
   20, and TTFT p50 falls from 4.00 s to 1.05 s.
2. **A token budget removes the failures.** `spread_fit` holds a turn until
   its replica's prompts in flight plus this one (estimated from the
   request's size) fit the pool: no failures in 544 turns, and the tail
   halves (p90 7.89 s against 10.83, p99 16.93 against 30.51).
3. **Pinning does not help when the pool cannot hold a conversation per
   slot.** Pinned slots keep their histories in the pool between turns,
   which the in-flight budget does not see (41 failures with it): pinsafe
   is 1-3 points below default here. With room for a conversation per slot
   (§3, 131,072 / 4 slots and conversations to 31,000 tokens) it is 3.4
   points above.
4. **Prefix placement, hashing and two gateways are below spread here too.**

## 6. How much two users share

The bench's sessions all ran in one directory. Real users do not, and
Claude Code's system prompt carries a per-project path (its memory
directory) at character ~2,790 of ~5,970, before its tools in the rendered
prompt. Measured on one engine, a session's first turn after another's:

| | Same project, another session | Another project |
|---|---|---|
| Claude Code | 17,859 of 19,725 tokens reused | **668-670 (3.4%)** |
| Codex | — | **9,641 of 11,046 (87%)** |

So a "prompt family" is one *project* for Claude Code and one *client
version* for Codex, whose per-project details (`<cwd>`, shell, date) sit in
the first input message after its instructions and tools. A prefix-aware
placement can save a Codex user's first turn ~9,600 tokens on a replica that
served any other Codex user; it can save a Claude Code user's only when the
same project (another session, a subagent of the same prompt) was there
before.

## 7. Eight replicas, sixty-four at once: overload

All 64 sessions at once on the eight replicas of §5: eight conversations a
replica against four slots and a pool that holds about three. Deep overload
(TTFT p50 in seconds to tens of seconds). With this many failed turns the
"reused" column is the engines' read over the *answered* turns' prompts, so
work done for a turn that then failed counts against it; read it with the
failures beside it.

| Mode | Policy | Reused | Read (k) | TTFT p50 | p90 | p99 | held / evicted / moved | Failed |
|---|---|---|---|---|---|---|---|---|
| default | `least_busy` | 43.6% | 5,213 | 16.11 s | 48.29 | 150.21 | 71 / 21 / 278 | 76 |
| default | PC4 | 45.4% | 4,668 | 15.02 | 47.36 | 85.28 | 165 / 109 / 80 | 100 |
| default | spread | 71.4% | 2,459 | **2.96** | 35.47 | 84.77 | 231 / 45 / 85 | 109 |
| default | **spread_fit** | **72.7%** | 3,054 | 4.01 | **11.21** | **19.01** | 287 / 193 / 0 | **0** |
| default | hrw | 70.0% | 2,368 | 13.64 | 26.09 | 34.37 | 193 / 90 / 57 | 130 |
| default | PC4, two gateways | 58.4% | 3,180 | 15.77 | 32.75 | 52.13 | 105 / 59 / 162 | 137 |
| pinsafe | PC4 | 40.6% | 4,877 | 14.23 | 48.89 | 86.61 | 165 / 106 / 56 | 115 |
| pinsafe | spread | 67.4% | 2,642 | 12.97 | 24.56 | 36.70 | 226 / 120 / 17 | 115 |
| pinsafe | spread_fit | 62.9% | 4,151 | 5.91 | 15.89 | 24.92 | 289 / 191 / 0 | 0 |

- **The budget is what keeps overload honest**: no failed turns, and a tail
  of 19 s where everything else reaches 35-150 s. It costs the median (a
  turn waits for room) and evictions rise (193: a turn that waited found
  its history pushed out of the RAM cache meanwhile), but every turn is
  answered.
- **Spread still carries the reuse**: 71-73% against PC4's 45%.
- **Pinning loses under overload**, every policy 4-10 points below default:
  the pool cannot hold a conversation per slot, and pinned histories crowd
  out what is in flight.

## 8. The 8B: what a real install does today

Llama 3.1 8B Q4_K_M, three replicas, `-c 65536` each with a q8_0 KV cache
(what fits three on the card), the agent's default four slots sharing it,
24 sessions, 12 at once: four agents a replica, and a pool that holds two or
three of their prompts at a time. Of 204 turns:

| Mode | Policy | Answered | Read (k) | TTFT p50 | p90 | p99 | Failed: circuit "cooling down" / cut mid-stream / refused / other |
|---|---|---|---|---|---|---|---|
| default | `least_busy` | 45 | 933 | 8.52 s | 28.41 | 53.34 | **159**: 115 / 39 / 3 / 2 |
| default | PC4 | 46 | 859 | 7.88 | 27.13 | 39.38 | **158**: 115 / 35 / 2 / 6 |
| default | spread | 49 | 554 | 2.71 | 21.38 | 35.89 | **155**: 131 / 21 / 1 / 2 |
| default | **spread_fit** | **166** (60.8% reused) | 1,343 | 4.58 | 16.41 | 23.61 | **38**: 35 / 2 / 1 / 0 |
| pinsafe | PC4 | 41 | 872 | 9.85 | 26.07 | 41.25 | 163 |
| pinsafe | spread | 71 | 598 | 2.34 | 18.44 | 39.53 | 133 |
| pinsafe | spread_fit | 204 (31.5% reused) | 2,872 | 13.99 | 25.16 | 39.20 | 0 |

**Through Eugene as it is, three quarters of these agent turns fail.** The
cause is two things in series. A few prompts in flight outgrow a replica's
pool (refused, or cut mid-stream: 22-42 a run); the driver reports each as a
502, the gateway's circuit counts it as a broken backend, and every request
to that replica is then refused as "cooling down" (115-131 a run) while it
is perfectly healthy. With every replica of the model tripped, nothing
answers. **The circuit turns a capacity problem into an outage** (filed as
eugene-plexus/gateway#8).

- **The budget alone** answers 166 of 204, and 35 of its 38 failures are
  still the circuit, tripped by the two overflows its estimate let through
  (characters ÷ 3.5 against a pool that holds two prompts is close).
- **A pool refusal that does not trip the circuit**, together with the
  budget and a margin on the estimate, is what this shape needs; neither
  was built for the run.
- **Pinning on a pool this small starves**: with the budget, every turn is
  answered, but at 31.5% reused and a 14 s median, because pinned histories
  hold the pool between turns.

## 9. After the build (CB1-CB5, 2026-10-02, late)

The same instrument, the same captures and llama-server b11211, against the
gateway and driver as built: CB3 (the capacity outcome, the pool on runtime
capabilities, the budget and the wait), CB1 (affinity under every strategy),
CB2 (`spread`), CB5 (`evicted`) and CB4 (the driver's slot map). Every policy
below is the gateway's own (`eugene:`), so the cascade runs; none is a
harness route. Each run on fresh engines and a fresh gateway; component code
was frozen in worktrees for the runs (`PYTHONPATH`), because a gateway
restart re-imports its source. The bench gained one shim beside
`bench_parallel_slots`: `bench_context_pool`, the pool the agent would have
reported for an engine it launched, and both of a replica's drivers keyed to
its one engine.

**The 8B shape (§8: three replicas at 65,536, q8_0 KV, 12 + 12 sessions, 12 at
once), the gate for CB3.** Before, PC4 answered 46 of 204.

| Build | Policy | Answered | Failed | Reused | TTFT p50 | p90 |
|---|---|---|---|---|---|---|
| before (§8) | PC4 `conversation` | 46 | 158 (115 "cooling down") | — | 7.88 s | 27.13 |
| CB3 | `conversation` | **204** | **0** | 66.2% | 11.50 s | 27.98 |
| CB3 | `least_busy` (no affinity then) | 197 | 7 (none "cooling down") | 50.2% | 17.84 s | 31.92 |
| CB1-CB5 | **`spread`** (the default) | **204** | **0** | 67.8% | 8.60 s | 27.30 |
| CB1-CB5 | `least_busy` (affinity on) | **204** | **0** | 64.6% | 10.93 s | 29.32 |

**No turn was refused as "cooling down" in any run.** The seven failures under
CB3's `least_busy` were streams the engine cut, six of them after output, so
they could not fail over. The ledger held what it counted (the proxy's records
put every replica's peak in-flight prompt-plus-answer at 58,375-58,918
tokens, under 90% of 65,536) and the estimate runs high, not low (characters
over 3.5 gave 21,751 for a first Claude Code turn the engine counted 19,703,
and 13,829 for a first Codex turn it counted 11,035). So the engine held more
than the turns in flight. llama-server's source says where: a slot chosen by
LRU has a whole cached prompt loaded into it from the RAM cache before it is
trimmed, and idle slots are cleared only after the new task launches
(`server-context.cpp`, `get_available_slot` and `TAG_IDLE_SLOT_CLEAR`). It
happened only without affinity, which moved 108 turns; with affinity, and
since CB1 affinity is on under every placement, it did not happen at all.

**Two words were wrong at the doors, found by this gate and fixed before the
pins.** A turn every replica refused for want of room reached Codex as
`context_length_exceeded` ("A backend serving this model is not ready yet"),
which stops it, and Claude Code mid-stream as `api_error`. llama-server's words
for a full pool are "Context size has been exceeded", and the Responses door's
context words matched them. A capacity refusal is now its own failure: Codex
gets `server_error` and Claude Code `overloaded_error`, both of which retry.

**The 8-replica shape (§5: eight replicas at 98,304, q8_0 KV, 32 + 32
sessions, 32 at once), the gate for CB2 and CB3.** 544 requests a run.

| Build | Policy | Reused | Read (k) | TTFT p50 | p90 | held / evicted / moved | Failed |
|---|---|---|---|---|---|---|---|
| before (§5) | PC4 `conversation` | 60.4% | 3,839 | 4.00 s | 16.26 | 251 / 25 / 124 | 56 |
| before (§5) | harness `spread` | 80.2% | 2,007 | 1.05 | 10.83 | 360 / 37 / 37 | 44 |
| before (§5) | harness `spread_fit` | 81.5% | 2,070 | 1.26 | 7.89 | 398 / 82 / 0 | 0 |
| CB1-CB5 | **`spread`**, four runs | **78.3, 77.4, 77.4, 80.0%** (mean 78.3) | 2,239-2,520 | 1.95-3.13 | 11.9-14.0 | 346-381 / 75-96 / 21-45 | **1, 0, 1, 0** |
| CB1-CB5 | `least_busy` (affinity on), three runs | 79.7, 77.3, 81.2% (mean 79.4) | 2,104-2,479 | 1.75-2.34 | 11.8-12.6 | 370-390 / 67-78 / 16-29 | 0, 9, 0 |

- **The pool's failures are gone under `spread`**: none in 2,176 turns. One
  `least_busy` run had eight streams the engine cut for room, the transient
  above.
- **The gate as written (at least 78% reused, none failed) is met by two of
  four `spread` runs.** Its mean is 78.3%, inside the run-to-run noise of the
  threshold, and the failures in the other two are not the pool (below).
- **With the budget and affinity in, `spread` and `least_busy` place new
  conversations about as well** (means 78.3% and 79.4%, noise about 2
  points). §5's +20 points were measured against PC4 without a budget; the
  budget itself sends a new conversation to whichever replica has room, which
  is most of what `spread` did. `spread` keeps one measured advantage: no pool
  overflow in four runs, against eight in one of three for `least_busy`.
- Evictions are about twice §5's harness `spread` (75-96 against 37) and match
  `spread_fit` (82): a turn that waits for room finds its history pushed out of
  the RAM cache meanwhile. That is what CB5 now shows per backend.

**What the remaining failures are: llama-server pausing its whole main loop.**
Three turns in 3,808 (two under `spread`, one under `least_busy`) got a first
token and then nothing for 30 s, so the driver's stall check
(`streamStallSeconds`, 30 s) ended them. In the one whose engine log survived,
every slot picked by LRU shows 6-10 s between `selected slot by LRU` and
`launch_slot_` with no other line: the RAM prompt cache update (save the slot,
load the best match) runs on the main loop, and with eight engines sharing
this box's memory bandwidth it takes seconds, during which no slot decodes.
Back-to-back, that silences a stream past 30 s. Not something placement can
fix; for Troy's upstream report beside §4's wedge.

**The 24-at-once shape (§4: three replicas at 131,072, 12 + 12 sessions, all
at once), the gate for CB4.** Mode `driverpin`: the engines get
`--no-cache-idle-slots`, every driver `slotPinning: true`, the gateway hands
each turn's conversation to its driver, and the proxy pins nothing (its record
shows the slot the driver named).

| Policy | Answered | At the 600 s deadline | Slowest | Reused | TTFT p50 | p90 |
|---|---|---|---|---|---|---|
| `spread` | 204 | **0** | 37.1 s | 74.6% | 4.77 s | 9.31 |
| `least_busy` | 204 | **0** | | 74.2% | 4.58 | 11.15 |
| `round_robin` (the pattern that wedged worst, §4) | 204 | **0** | | 73.3% | 4.72 | 11.54 |

None of 612 turns reached the deadline, where pinning without the safe rule
stalled 9 of 200 and once held an engine for 30 minutes (§4). Each
conversation names its own slot, and its next turn reads its whole history
from it (19,699 of 19,699 tokens on the first checked). Reuse is 1-3 points
below §4's harness `pinsafe spread` (77.8%) and about at default `spread`
(75.6%): this shape has two conversations a slot, where pinning was measured
as noise, which is why the setting is off by default.

**Sabotage: 69 of 69 caught** (`scripts/cb-sabotage.py`, driver, gateway, agent
and the doors), after three checks were strengthened: an estimate fixture
whose numbers agreed with the no-history formula, a cascade whose reservation
nothing observed mid-attempt, and slot tests that hung rather than failed when
a slot was never given back.

**One estimate is worth a call (§6 of the design does not settle it):**
Claude Code sends `max_tokens: 32000`, and the budget counts it whole. The
replays send 64, so none of these runs shows it, but on a 65,536-token pool
one Claude Code turn of 20,000-31,000 prompt tokens plus 32,000 reserved
leaves no room for a second, where two fit by their real use. It is the safe
reading (an overflow cuts every stream in the batch, and an answer can use
its whole allowance); a smaller reservation for the answer would trade that
for concurrency.

## Not measured

- **Real separate GPUs.** Every replica shares one 5090, so TTFT is the
  whole card's load, not one replica's; a policy that reads less is faster
  for everyone here, which separate cards would show less.
- **Bigger models at scale.** The 8-replica runs are a 1B; the 8B (§8) is
  three replicas. A bigger model's KV per token makes the RAM prompt cache
  hold fewer conversations (§1) and the pool fill sooner.
- **Long sessions.** Eight tool turns, prompts to ~31,000 tokens; real agent
  sessions run to hundreds of thousands, which no pool here holds.
- ~~**The gateway's own spread and budget.**~~ Measured since: §9.
- **Real tool loops**: the replay sends the captured answers, so the 64
  tokens generated each turn are replaced by the next request.
- **vLLM and MLX** under concurrency.
