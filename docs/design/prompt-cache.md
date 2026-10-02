# Keeping the engine's prompt cache warm

**Status: measured 2026-10-02; PC1 built the same day (gateway working
tree, not yet pinned); PC2-PC7 designed, waiting on the calls in §5.**
Troy's brief: *"this is at the core of what Eugene is: managing multiple
backends efficiently. So resolving this caching issue is high priority
before we go public."* The measurement, with every number below, is
[`docs/acceptance/prompt-cache-measurement.md`](../acceptance/prompt-cache-measurement.md).

## 1. Where the cache lives

A prompt cache is the engine's key/value state for prompt text it has
already read, held in its own GPU or host memory. It can reuse a prompt
**only up to the first token that differs** from one it holds. Eugene
cannot hold anything an engine could use, so it does not cache and should
not. What Eugene decides is everything around the cache:

1. **What prompt the engine sees.** Every door translates, and a translation
   that varies, or carries something that varies, makes each request a
   stranger.
2. **Which replica sees it.** With one replica the engine's own slot choice
   does the work. With two, the gateway chooses, and today it chooses with
   no notion of a conversation.
3. **How much the engine can keep, and for how long.** `-c`, `--parallel`
   and `--cache-ram` bound how many conversations stay warm; a stop, a
   restart or a crash empties it.
4. **What a hosted backend is asked for.** Anthropic models cache only when
   asked; OpenAI, DeepSeek and vLLM cache by themselves.
5. **Whether anyone can see it.**

## 2. What the measurement found

**The engines are good at this. Eugene was costing hits in five places.**

- **One replica: Eugene reads exactly what the engine reads direct**, turn
  for turn, on the Anthropic and Responses doors, and reports the cached
  count correctly. A cached Claude Code turn takes 0.99 s where the same
  turn cold takes 36 s (CPU, 0.6B); 0.30 s against 5.50 s on the 27B (GPU).
- **Claude Code's billing header made every new session a stranger.** Its
  first system block carries a suffix that follows the session's first
  prompt (other builds: fields that change every request), and the gateway
  put it first in the prompt. Each new session re-read its whole ~18,700-token
  system prompt and tool list. **Fixed (PC1):** through Eugene a new
  session's first turn now reads ~1,860 tokens instead of ~19,700, and four
  sessions take 9.3 s instead of 16.9 s (GPU, 8B). Eugene now beats direct.
- **Two replicas: today's balancer splits a conversation across them.** One
  agent session on an idle two-replica install alternates every turn and
  reuses 52.8% (Codex 59.1%); pinned to one replica it reuses 75.3% (79.4%)
  and takes half the time.
- **Claude Code cannot use the Qwen 3.x starters at all** (gateway#6): their
  templates refuse a system message after the first, and Claude Code sends
  them mid-conversation. **And one such refusal 503s every other client** of
  that model (gateway#7), because a request-caused 500 trips the circuit.
  Not caching, found by it, and in front of everything else.
- **Hosted Claude never caches through Eugene.** The Anthropic door drops
  `cache_control`; via OpenRouter a conversation's second turn costs
  $0.0073 unmarked and $0.00077 marked (9.4×).
- **Nobody can see any of it**: no cached count in the metrics, and vLLM
  reports none on chat completions without a flag the agent does not pass.

**What the engine itself cannot do, and Eugene should not try to:**

- **Many sessions on one replica.** Eight Claude Code sessions taking turns
  on one 8B: the shared system prompt stays warm, but each session's own
  history is read again every turn (11,093 tokens at turn 5 against 2,420
  alone). More `--cache-ram` changed nothing; a stricter slot similarity
  made it worse, because the saved state would not fit back into the pool.
  The remedy is a pool sized for the sessions, or more replicas with
  affinity, not a flag.
- **Restoring a saved slot after a restart.** Works on full attention (8B:
  0.85 s against 1.84 s to re-read, for 2.5 GB of disk) and **reuses nothing
  on hybrid or sliding-window models**, which are three of the five starter
  classes (llama.cpp #28194, #25913, open). Not worth building on until
  upstream persists checkpoints.
- **Hybrid and sliding-window models in a growing conversation** need no
  help: on b11211 they reuse exactly as full attention does.

## 3. The slices

Each ends with a check that fails without it: `prompt-cache-measurement.py`
is the instrument, and each slice adds the assertion that makes it a gate.

### PC1. The billing header off at the Anthropic door — BUILT 2026-10-02

`anthropic._without_billing_header`: a leading
`x-anthropic-billing-header:` line comes off every system block before the
prompt reaches any backend. Only the line: text after it in the same block
stays, and the same words anywhere else are the prompt's own. Tests assert
the property (two requests differing only in the header reach the backend
identical, for four real header shapes); two existing tests that asserted
the header was carried were amended, not added to. Sabotage 4/4. Owed: the
contract sentence in `gateway.yaml`'s Anthropic door section, and the pin.

### PC2. Claude Code on Qwen 3.x (gateway#6)

Each `system` message after the first becomes a `user` turn, in place, its
text wrapped `<system-reminder>…</system-reminder>` (the form Claude Code
itself uses for reminders in user turns). Measured as a replay transform:
all three Qwen 3.x starters answer, and reuse matches the full-attention
models (84.8% with PC1). **Not** merged into the first system message:
that changes the prompt's start every turn and would miss the cache on
every turn. Check: a real Claude Code turn through Eugene on Qwen3.5-4B is
200; the replay's Qwen rows need no `--fold-system`.

### PC3. A request's own failure does not trip the circuit (gateway#7)

The driver reports llama-server's request-shape 500s (`Jinja Exception`,
`does not match the expected … format`) as a 4xx that neither cascades nor
counts against the backend, and the circuit counts only failures that say
something about a backend: transport errors, timeouts, 502/503/504. Check:
a template refusal followed by a good request from another client is 4xx
then 200.

### PC4. A conversation goes back to its replica

A new `loadBalancing` value, `conversation`, in `RoutingTable._order`:

- **The key.** The client's own when it sends one: `prompt_cache_key` (chat
  and Responses; Codex sends its session id), Claude Code's `session_id`
  inside `metadata.user_id`. Otherwise a fingerprint of the conversation's
  start: model, system text, tool names, first user message. It does not
  change while a conversation grows. Two conversations that start alike
  share that prefix, so sending them to one replica is right.
- **The rule.** A key seen in the last 30 minutes goes to the replica that
  served it, while that replica is eligible and not saturated (in-flight
  below its slots) or no other replica is idle; otherwise least-busy, and
  the key moves with the request. A bounded table (4,096 keys, least
  recently used dropped). Tiers and failover are unchanged: a warm cache
  never outranks a working backend.
- **Recorded.** Each routed request says `affinity: hit | new | moved`, in
  the balancer-candidates table the metrics already keep.
- **Precedent.** OpenRouter's "provider sticky routing" (by `session_id` or
  a hash of the messages, 10-minute expiry) does this for hosted providers;
  SGLang's router and llm-d's scheduler do it for engine replicas.
- **Check.** The two-replica replay through Eugene reuses what pinned does
  (one session: 75.3%, not 52.8%), and a saturated replica still spills.

Workbench sends `prompt_cache_key` = the chat's id, so its conversations
carry an explicit key (one line in `conversation.request_for`).

### PC5. The cache is visible

- `attempt.cached_tokens` and `request.cached_tokens` in the gateway's
  metrics, from the driver's `cachedPromptTokens`; the Metrics page gains a
  *reused* column per model and backend, beside time to first token.
- The agent's vLLM recipe passes `--enable-prompt-tokens-details`: it adds
  reporting and nothing else, so it is a default, not a setting.
- Check: the replay's Eugene rows match the engine's counter from
  `GET /v1/metrics`, not only from the response body.

### PC6. Hosted backends get their breakpoints

1. **Carry the client's.** When a request carried any `cache_control` (Claude
   Code marks every request), the driver asks OpenRouter's `anthropic/*`
   models for request-level `cache_control`, which places the breakpoint
   after the last message and so caches each earlier turn. One field in
   `GenerateRequest` (a contract change): the client asked for caching.
2. **Add one for a client that sent none** (§5 call 4).

Check: a two-turn Claude conversation through Eugene via OpenRouter reports
`cached_tokens` on turn 2.

### PC7. The engine's cache settings on a profile

`--cache-ram`, `--cache-reuse` and `--ctx-checkpoints` beside the existing
`parallelSlots` on the llama.cpp profile, each showing upstream's default as
the default (settings never lie). **Admission counts `--cache-ram` against
host RAM**: today a runtime's 8 GiB of prompt cache is invisible to it, and
two runtimes are 16 GiB nobody accounted for. MLX's two cache settings are
already exposed.

## 4. Not scheduled

- **Saving slots across an idle unload** (§2): helps full-attention models
  only, until upstream persists context checkpoints. Revisit then.
- **Per-slot routing inside one llama-server** (`id_slot`): it would fight
  the engine's own slot choice, and the eight-session reading says the
  limit is the pool, not the choice.
- **`CLAUDE_CODE_ATTRIBUTION_HEADER=0` in the Claude Code recipe**: PC1
  makes it unnecessary through Eugene, and an easy default needs no setting.

## 5. Calls for Troy

| # | Call | Recommendation | Against it |
|---|---|---|---|
| 1 | Which slices go before going public | **PC1-PC5**: two are outright breakage (Claude Code on three starters; one client 503ing the rest), one is the core claim (many backends, efficiently), and PC5 is how anyone sees the rest. PC6-PC7 right after | PC6 is money for anyone using Claude through OpenRouter today |
| 2 | Is `conversation` the default balancing | **Yes.** It reduces to least-busy when no key repeats, and agent and chat traffic is conversations | A default that changes routing on upgrade; the old two stay selectable |
| 3 | Fold Claude Code's in-conversation system messages always, or only for a backend whose template refused | **Always.** Same prompt on every backend, no retry, no per-template knowledge | Templates that accept a mid-conversation system message lose the role, not the text |
| 4 | Add a breakpoint for a client that sent none (Anthropic models via OpenRouter) | **Only from a conversation's second turn on** (a request with an earlier assistant turn): never dearer for a one-off, caches from turn 3 | Always adding caches from turn 2 and makes every one-off 25% dearer |
