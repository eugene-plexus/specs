# M1 — Continuous-loop runtime (design)

**Status:** design-gate output for milestone **M1**. Provisional — the
functional-region direction is explicitly "expect to reshape during
implementation," and so is this. This is the *consumable* design; the running
decision log lives in the project memory (`functional-region-architecture`).

**What it changes:** it replaces the request-response pipeline as Eugene's
**top-level runtime shape.** The bicameral request → deliberate → blend → reply
loop does not vanish — it **demotes to a sub-mechanism** the new loop calls.

**Date:** 2026-06-06 · **Feeds:** M2 (loop core), and the `orchestrator`, `ui`,
and `connector` repos (new cross-component contracts in §7).

---

## 1. Why this exists

The v0.2 pipeline is a chatbot skeleton: every `POST /v1/chat` runs the
deliberation loop, scorer-gates to a termination, runs the voice pass, and
returns a reply. Three commitments make that the wrong shape for a consciousness:

- **Speaking is a decision, not an automatic terminal step.** Eugene must be
  able to decide *not* to respond — silence is a valid outcome.
- **Responding to the latest input is also a choice.** Perception is an event
  that *punctuates* an ongoing process; it is not the fixed start of a turn.
- **Attention is singular.** One consciousness has one workspace (Global
  Workspace Theory): it attends to one thing at a time and switches on salience.

The engine underneath every choice: **the action gate hill-climbs on anticipated
net NT valence** — reinforcement learning with neurotransmitter valence as the
reward signal. "Think more / switch / speak / rest" is simply whichever action
has the highest anticipated reward (and lowest anticipated aversive cost). This
doc takes that principle as given; see the decision log for its derivation and
the wireheading guardrails that keep it honest.

---

## 2. The shape: one loop, one workspace

A single long-lived `asyncio` task — *the* thing that thinks — started in the
orchestrator's FastAPI lifespan. HTTP endpoints are thin doors that push
**afferent events** onto an in-memory queue the loop drains. There is exactly
one such task per Eugene instance.

The loop owns a `Workspace` — the literal global workspace:

| field | meaning |
|---|---|
| `focus` | what Eugene is currently attending to (a conversation context, an internal topic, or nothing) |
| `train` | the current train of thought — the sequence of `thought`s on `focus` (working memory) |
| `nt` | live `NTState` (now ticked *inside* the loop, not once post-turn) |
| `adenosine` | accrued sleep pressure / cognitive fatigue (see §5) |
| `phase` | `awake` / `asleep` |

A **thought** is the unit of cognition: one LLM generation in service of
thinking. The ladder is *thought* → *train of thought* (a bout) → idle. ("Pass"
is retired to mean only the wire-level artifact.)

```python
# the ONLY thing that thinks; one per Eugene, started in the FastAPI lifespan
async def consciousness_loop(app):
    ws = Workspace(focus=None, train=[], nt=neutral(), adenosine=0.0, phase=AWAKE)
    while running:
        # 1. SENSE — drain injected afferent events (never blocks)
        for ev in drain(app.event_queue):
            ingest(ws, ev, salience(ev, ws.nt))     # capture focus / buffer / drop (lossy)
        # 2. FEEL — continuous NT tick + adenosine accrual
        tick(ws.nt, elapsed); accrue_adenosine(ws)
        # 3. GATE — pick the highest anticipated-net-valence action
        action = gate(ws)                           # think | switch | speak | idle | sleep
        # 4. ACT
        match action:
            case THINK:  ws.train.append(await one_thought(ws))   # the LLM call; await YIELDS
            case SPEAK:  await speak_effector(ws)                 # efferent tool → routed to a destination
            case SWITCH: refocus(ws)
            case SLEEP:  await consolidate(ws)                    # offline (M5 stub); clears adenosine
            case IDLE:   await asyncio.sleep(idle_cadence)        # cheap, no LLM
        # 5. CONSEQUENCE — outcome → NT impulses; publish observability
        apply_impulses(ws, action); publish(consciousness_stream, ws, action)
```

**What ends a bout (1a):** dopamine plateau. Dopamine tracks *improvement* (RPE
on thought quality): a more-refined thought bumps it; no improvement drops it,
and the gate stops picking `think`. No counter, no fixed threshold — a slope
hitting zero. (The agreement scorer feeds this "settledness" signal; convergence
is one way to plateau, running out of angles is another.)

**Episodic vs continuous (1b):** neither, as posed — it is emergent. Thinking
continues while *some* action has positive anticipated reward and quiets when
none does: continuous when there is reward to chase, idle when there isn't.
Speak falls out — alone + plateau → switch topics; not-alone + plateau →
speaking opens a *fresh* reward source (social reinforcement) that thinking-more
no longer offers, so the gate picks `speak`. **Presence reshapes the reward
landscape.**

**Why this shape is good (systems properties):**

- **One cognitive task ⇒ zero locks on cognition.** Because exactly one thing
  mutates `nt`/`Workspace`, the hardest class of bug here simply does not exist.
  Single-attention is not only philosophically right, it is the simplest
  possible implementation.
- **The LLM `await` yields the loop**, so HTTP handlers keep enqueuing events
  *even while Eugene is mid-thought*. Injection never blocks; perception never
  waits on cognition.
- **Idle is nearly free** — an `asyncio.sleep` with no model call. Continuous
  loop ≠ continuous spend.

---

## 3. Perception and action surfaces (the wire contracts)

One door in, two channels out — **no backwards-compatibility surface** (see
below). Addressing is symmetric: an afferent event carries a **source**; a
speech act carries a **destination**; both reuse the existing `MessageSource` /
`ChannelContextEntry` shapes.

### In — `POST /v1/events` (the pure interface)

Accepts one afferent event, enqueues it, returns **`202 Accepted`** immediately.
A user message, a presence change, and a future connector inbound are all the
same envelope, differing by `kind` and `source`.

```yaml
AfferentEvent:
  type: object
  required: [eventId, kind, source, timestamp]
  properties:
    eventId:   { type: string, format: uuid }
    kind:      { type: string, enum: [message, presence] }   # extensible
    source:    { $ref: '#/components/schemas/MessageSource' }
    timestamp: { type: string, format: date-time }
    message:   { $ref: '#/components/schemas/IncomingMessage' }   # when kind=message
    presence:  { $ref: '#/components/schemas/PresenceEvent' }     # when kind=presence
```

`PresenceEvent` is new (afferent occupancy — who entered/left an environment;
NT-modulated lossy salience, identity-resolved). `IncomingMessage`,
`MessageSource`, `ChannelContextEntry` already exist and are reused as-is.

> **Interrupt vs poll.** An *unsolicited* event arriving stays `role: user` —
> Eugene didn't "call hear." Only Eugene's *interpretation* of it (and any
> solicited perception, e.g. checking a channel or recalling) is an afferent
> `role: tool` cycle.

### Removed — the request-response surface

**No backwards compatibility** (Troy, 2026-06-06): nobody is running Eugene
Plexus, so breaking the project to reach the correct shape beats preserving the
old one. The v0.2 request-response endpoints — `POST /v1/chat`,
`POST /v1/chat/stream`, and the `ChatRequest` / `ChatResponse` schemas — are
**removed outright.** There is no compatibility adapter and no dual front door:
`POST /v1/events` is the only way in.

*Silence as a valid outcome* is still first-class — a caller observes it as a
`gate_decision` (and the absence of an ensuing speech) on the consciousness
stream, **not** as a synchronous "no response" reply. The UI breaks and is
rebuilt against the streams; that is acceptable and intended.

### Out — speech (efferent), routed to a destination

The tool model pays off here: **`speak` is an efferent tool** whose executor
routes the utterance to a destination.

```yaml
EfferentSpeechAct:
  type: object
  required: [destination, content, timestamp]
  properties:
    destination:  { $ref: '#/components/schemas/MessageSource' }  # same addressing, other direction
    content:      { type: string }
    inResponseTo: { type: string, format: uuid }   # the AfferentEvent.eventId, when reactive (optional)
    timestamp:    { type: string, format: date-time }
```

- Reply to a Discord message → the **connector's** outbound API for that channel.
- Reply in the UI → the UI's speech stream.
- *Initiated* speech (no triggering event) picks its destination from social
  context instead of inheriting it.

### Out — `GET /v1/stream/consciousness` (SSE; observability)

The live broadcast of Eugene's inner stream — the **direct evolution of the
v0.2 `/v1/chat/stream`**, generalized from per-turn passes to continuous
thoughts. The UI subscribes and renders it; Discord only *hears speech*. The UI
is the fMRI; the channel is the ears.

SSE event types (`event:` field, following the `/v1/chat/stream` precedent):

| event | `data` |
|---|---|
| `thought` | a `Message` (`role: hemisphere`/voice) — one generation, with `driverName` |
| `nt_update` | an `NTState` snapshot (level/baseline/decay per NT + adenosine) |
| `gate_decision` | `{ action: think\|switch\|speak\|idle\|sleep, anticipatedValence: number }` |
| `tool_call` | a `ToolInvocationRecord` (the existing M0.5 shape — afferent/efferent/internal) |
| `focus_switch` | `{ from, to }` — attention moved |
| `phase_change` | `{ phase: awake\|asleep }` — wake/sleep transition |

> **The M0.5 UI is not wasted.** `PassCard` → `ThoughtCard`, `ToolStrip`, and
> the NT rendering survive; only the data source changes from a static array in
> one `ChatResponse` to this subscription.

**Transport:** SSE, not WebSocket. Both channels are server→client and injection
is a plain POST, so a bidirectional socket is never needed — and the repo's
committed transport rule already says "SSE for one-way streams."

---

## 4. Reuse and migration

The bicameral pipeline is rewired, not deleted:

| v0.2 piece | role in the continuous loop |
|---|---|
| bicameral two-backend pair | the **deliberative** flavor of `one_thought` — run two backends when stakes/uncertainty are high; a plain thought is single-model |
| agreement scorer (`callosum`) | the **plateau / settledness signal** feeding dopamine/GABA — no longer a termination gate |
| voice pass (`voice.py`) | the **speak effector** — fired by the gate, not run unconditionally |
| NT `tick` (`nt.py`) | moves from once-post-turn into loop step 2 (continuous) |
| M0.5 tool trace | becomes the live `tool_call` events on the consciousness stream |

**Migration is replace, not coexist** (Troy, 2026-06-06: no backwards compat —
correctness beats compatibility, nobody is using it yet). The old
request-response handler is *deleted*, not flagged off. The UI is rebuilt to
post `AfferentEvent`s and subscribe to the two streams; the connector is already
async (posts inbound, sends outbound as separate actions) so it maps to the new
model directly. The risk this *removes*: no half-migrated dual runtime to keep
in sync — there is exactly one cognition path.

---

## 5. The wake/sleep cycle

`adenosine` is a homeostatic **fatigue** variable — the real sleep-pressure
signal. It accumulates with cognitive activity and is cleared by sleep. High
adenosine raises the cost / lowers the drift of `think` in the gate, so Eugene
**winds down because it is tired**, not because a counter tripped. (The token
ceiling is *not* a cognitive rule — it survives only as a cost fuse for metered
API backends.)

Functionally, fatigue = **unconsolidated experience accumulating** — analogous
to a context window filling before it must be compacted. So adenosine should
accrue from *experiential load*, not wall-clock (a quiet day needs little sleep;
a high-event day needs to consolidate).

The full cycle, with the two deferred refinements folded in:

```
AWAKE ──(never truly idle: engaged, or low-grade seeking/mind-wander)──► accrue adenosine
   ▲                                                                          │
   │                                                                  (adenosine high)
   │                                                                          ▼
WAKE: prime focus from recent episodic memory  ◄──────────────────────  SLEEP: the only
(not a blank start)                                                      true rest — offline
                                                                         consolidation +
                                                                         generalization +
                                                                         affective credit
                                                                         assignment (M5);
                                                                         adenosine cleared
```

**Sleep is where offline learning happens.** Credit assignment — binding a
consequence's valence (a kick, a warm reply) back to the behavior that caused it
— is done here, *not* in real time. Offline it is tractable: the whole session
is in hand with the outcome known, so it reasons backward over a bounded log.
Its home is the **existing `reflect` endpoint, generalized**. The sleep
*mechanism* is deferred (M5); its *contents* are pinned: consolidation +
generalization + affective credit assignment + adenosine clearing +
relationship-valence updates.

---

## 6. Decisions

**Locked:**

- **No backwards compatibility (Troy, 2026-06-06).** Nobody is running Eugene
  Plexus; breaking the project to reach the correct shape beats preserving v0.2.
  The request-response surface (`/v1/chat`, `/v1/chat/stream`, `ChatRequest`,
  `ChatResponse`) is removed outright — no adapter, no dual front door, one
  cognition path.
- **One loop, one workspace; single long-lived asyncio task** in the
  orchestrator lifespan; endpoints are thin event-injection doors.
- **Single-attention is literal.** One focus; other threads wait in a lossy
  buffer until the current bout plateaus or their salience interrupts. Accepted
  consequence: Eugene can feel "slow" on thread B while genuinely thinking about
  thread A — the price of being a mind, not a request router. Salience-interrupt
  covers the urgent case.
- **Speaking is an efferent tool** the gate elects; silence is valid.
- **Observability is SSE; injection is POST/202.**
- **Reasoning lives legibly on the wire** (thoughts are visible events), not in
  hidden per-component CoT.
- **Tokens only, never dollars**, for any usage surfaced.

**Deferred (wanted, but addable without reshaping this structure):**

1. **Wake-from-memory** — wake primes `focus` with a recent-episodic-memory
   recall step rather than starting blank. (A recall on the `awake` transition.)
2. **No true idle** — the `idle` branch is low-grade stimulation-seeking /
   mind-wandering (boredom is aversive), cost-bounded by cadence + adenosine,
   not terminal rest. (This is the M4 autonomous-thinking behavior; the loop
   already has the hook.)
3. **Autonomous-thinking behavior** (M4) — cadence config, background-thinking
   model slot nudged to local/subscription backends, token circuit-breaker.
4. **The learning loop** (M5) — credit assignment + retrieval-by-affect (needs
   the deferred memory search backend) + consolidation into durable identity
   valence.

---

## 7. Spec stubs this design calls for (M2 input)

Additive to `components/common.yaml` and `orchestrator.yaml`. Optional fields;
existing consumers are unaffected until they bump `SPECS_REF`.

- **`AfferentEvent`** — source-addressed perception envelope (§3). Reuses
  `MessageSource`, `IncomingMessage`.
- **`PresenceEvent`** — afferent occupancy (entered/left, person/alias, env).
- **`EfferentSpeechAct`** — destination-addressed utterance (§3).
- **`ConsciousnessEvent`** — the observability union behind the SSE stream (§3).
- **Endpoints:** `POST /v1/events` (202), `GET /v1/stream/consciousness` (SSE),
  the `EfferentSpeechAct` delivery path, and the `/v1/chat` adapter semantics.

These are drafted into the working tree when M2 begins to exercise them (per the
publish → bump → regen → land workflow); they are *not* landed ahead of an
implementation that proves the shapes.

---

## 8. Risks and open questions

- **Wireheading is the central risk** of a reward-pursuit engine: self-pleasing
  thought loops that accomplish nothing. Guardrails already chosen — dopamine
  rewards *improvement not activity* (spinning plateaus, pays nothing);
  adenosine makes thinking *cost* energy; the richest rewards (social NTs) are
  *exogenous* (need real others). First line of defense, not a proof — monitor.
- **Single-attention UX.** The "slow on thread B" effect is by design; whether
  it reads as thoughtful or unresponsive needs real-world observation. The
  salience model (what interrupts) is the tuning surface.
- **The API break** touches `ui` and `connector`. The `/v1/chat` adapter
  contains the blast radius during transition; the deliberate flip is the risk
  point.
- **Validation.** Stochastic gating makes *when* Eugene acts non-deterministic.
  The debug NT-injection rig (clamp a state, sample the gate N times) is how the
  distribution gets characterized — built alongside the loop, behind a debug flag.

---

*Drive ≠ consciousness: NT-pursuit answers "what drives behavior," not "what
consciousness is." By this architecture the consciousness is the workspace
broadcast; NT-pursuit is the motivation that moves through it. Keeping the two
distinct is what keeps the project empirical.*
