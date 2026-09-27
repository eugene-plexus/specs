# What the model is doing: the run

**2026-09-27. `scripts/progress-acceptance.py`: all 22 checks pass live, on
the second execution.** The first execution found a product defect (§3),
which was fixed and put back as a sabotage. Sabotage pass
(`scripts/progress-sabotage.py`): **46 of 46 caught** across the driver, the
gateway and the UI. It needed three rounds; §4 says what each round found.

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `7999b67`, `807024d` | the contract: `reportProgress`, `event: progress`, `stream_options.include_progress`, `StreamProgress` |
| `inference-driver` | `59fb2a5`, `87cf908` | progress from every backend; Claude Code's thinking; Codex's own failure reason; the loading-503 fix |
| `gateway` | `6f2994a` | progress carried to a caller who asked, never the commit point or the first token |
| `ui` | `e936b7c`, dist `35461c3` | the wait described from what the backend says; the thinking shown |

Both installers pin all three. `agent`, `control` and `library` codegen
neither changed document, so they were not moved.

---

## 0. Why

A tester sent a prompt to a model running on the processor. He saw one
still line for minutes, concluded the request had failed, and left. The
answer was waiting when he came back.

The first fix was a clock and moving dots. That was honest, but it only said
that time was passing. Troy asked for a proper one: say what is happening.
Two measurements, taken before anything was built, showed what could be
said:

- **llama.cpp b11215 reports how far it has read a prompt, but only when
  asked.** With `return_progress: true` it sends a frame per batch,
  `{total, cache, processed, time_ms}`. Without it, a 3,700-token prompt on
  the processor produced **no frame at all for 21 s**, then the first token.
- **A reasoning model's thinking was already on the wire.** The gateway has
  streamed it as `reasoning_content` since 2026-09-23, and the page read
  past it. So a model that thought for a minute showed nothing for that
  minute.

Troy asked for cloud services to be covered too. A real Claude Code 2.1.207
capture showed what the CLI reports and the driver was discarding:

- `system init`;
- `status: requesting`, once per request it sends;
- 118 thinking deltas;
- a `tool_use` start for `Read`.

Codex on this box could not run a turn: its CLI is too old for the
account's model. Its failure showed a second defect instead. Codex gives
the reason on stdout, two JSON levels deep. The driver reported stderr's
log noise, or "produced no agent_message", in its place.

---

## 1. What was built

- **Progress, from each backend, reporting only what it can observe:**
  - llama.cpp's prompt reading (`stage: prompt`, with counts);
  - `working` from any HTTP backend when the response opens and at SSE
    keepalive comments, at most every 2 s (OpenRouter's
    `: OPENROUTER PROCESSING`);
  - `working` and `tool` from Claude Code and Codex.
- **Only a caller who asks gets it.** `stream_options.include_progress` is
  an Eugene extension. A progress chunk has `choices: []` and an
  `x_eugene_plexus` holding only `progress`.
- **Progress is not output:**
  - it is not the gateway's commit point, so a backend that fails safely
    after reporting progress still fails over;
  - it is not the first token, in the gateway's metrics or in the page's
    rate;
  - a progress-only frame never arms the driver's stall clock.
- **Only a llama-server is sent `return_progress`**, decided from its
  `/props`, because a hosted API refuses an unknown field.
- **The page says:**
  - "Reading your message: 48%", with the counts, about how long is left,
    and a bar;
  - "The model has your message and is working on it";
  - "Using a tool: Read";
  - "Starting the model. It was asleep, so it loads first";
  - "Thinking", with the thinking itself open while it arrives and folded
    to "Thought for 42 s" once the answer starts.

  The thinking is display-only and never sent back to the model.

---

## 2. The live run

A real `llama-server` b11215 on the processor (2 threads, batches of 256)
with a real Qwen3-0.6B, a real driver over it, a real driver over a stub
hosted API, the real Claude Code CLI behind a third driver, and a real
gateway. A client reads the gateway's stream with httpx as it arrives.

| # | Check | Result |
| --- | --- | --- |
| 1 | three real drivers routable through a real gateway | yes |
| 2 | asked: a 5,266-token prompt | 22 progress chunks from 0.13 s, rising 0 → 5,266 of 5,266, all before the first word at **16.2 s** |
| 3 | unasked | no progress chunk, and **no frame of any kind for 16.3 s**: the tester's silence, reproduced |
| 4 | the gateway's retained time to first token | 16.1 s, the first word and not the first progress frame |
| 5 | hosted API, asked | not sent `return_progress`; `working` at 0.12 s, 3 chunks for 5 keepalives; first word at 3.6 s; answer intact |
| 6 | hosted API, unasked | nothing extra, no flag |
| 7 | the real Claude Code (Haiku), asked | its `Read` tool reported at 3.7 s, before its first word at 5.4 s; 71 fragments of its thinking reached the caller; it answered from the file |
| 8 | teardown | no owned port still listening |

---

## 3. What the first execution found

**Prompt progress never arrived from the real llama-server.** The driver
first probes `/props` when it starts, and the model is still loading then.
llama-server answers **503** while loading. The probe counted any error
status as "not llama.cpp" and cached that, so the flag was never sent on
the one path the feature exists for. Every unit fixture had answered
`/props` with 200 or 404.

Now only 404, 405, 410 and 501 settle that a backend has no `/props`;
anything else is asked again. There is a test for the 503 case, and a
sabotage that puts the old rule back (caught).

The script's own defect: it sent `max_tokens` to Claude Code, which refuses
a setting it would otherwise drop.

---

## 4. The sabotage rounds

- **The first round had one escape.** A test matched "requires a newer
  version of Codex", and the raw JSON blob contains that phrase too. The
  test now requires the API's own sentence, with no JSON and no stderr in
  it.
- **The second round had two escapes, and neither was a weak check.** Each
  was a guard shadowed by another guard:
  - the gateway refusing `stream_options` without `stream: true` makes a
    second "batch requests don't ask" guard unreachable;
  - a live answer's bubble is never rendered, so an `!live` inside `empty`
    could not matter.

  Both spare guards were deleted, and the guard that does the work is what
  is sabotaged now.
- **One check was missing, and was added before the pass.** Nothing checked
  that a progress chunk does not start the page's first-token clock. The
  test uses a real pause, since an instant fake cannot tell the two apart.

---

## 5. What it does not prove

- **No browser drove it.** The page tests drive both pages with the exact
  wire shapes, and the dist archive was fetched and grepped for the new
  copy. Nobody has watched the bar move in a browser on a real install.
- **Codex's tool mapping is from its documentation, not a capture.** The
  CLI here is too old to run a turn.
- **OpenRouter itself was not called.** Its keepalive is reproduced by a
  stub.
- **vLLM, Ollama and MLX report no prompt progress.** They get `working`
  when the response opens, and their thinking if they stream it.
