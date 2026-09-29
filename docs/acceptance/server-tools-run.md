# P8: server-run tools — web search, and images for a local model — record

**2026-09-29. Built, run and pinned in both installers.** Troy: *"As long as
we don't code ourselves into a corner, lets just implement P8 as written."*
Design: [`server-run-tools.md`](../design/server-run-tools.md) (§9 the six
calls, §7 P8e's four, §12 the implementation record, §13 departures).
Measured first: [`server-tools-measurement.md`](server-tools-measurement.md).
Operator guide: [`../deployment/web-search.md`](../deployment/web-search.md).

| Repo | Commit | What |
|---|---|---|
| specs (contracts) | `c641e0b`, `f39ffe7`, `a9fc9b9`, `e53a6d9`, `c4e2fe4` | `tool-driver.yaml`, `ComponentKind.tool-driver`, `ClientKeyLimits.allowedTools`, server-run tools on three doors, `MetricToolExecution`, `ToolDriverInfo.billing`, P8e |
| tool-driver (new repo) | `7dc4794` | SearXNG and Brave, one process per search account |
| gateway | `10567d4` | the loop, the three doors' records, P8e, metrics v10 |
| agent | `14f8047`, `8579764` | spawns and seals a tool-driver, proxies to it by name, `allowedTools`, the seventh package |
| control | `2918b7e` | a union view that tolerates a kind it does not know; `allowedTools` |
| inference-driver | `02eea96` | regen-only (a new `ComponentKind` member reaches every consumer) |
| library | `b4af12f` | regen-only |
| ui | `01fd6ee`, dist `ecf12f0` | *Add a search account*, search accounts under Backends, a key's web-search permission, the playground's *Search the web* |

## The done-when

**A local model answers with sources through each client P8 exists for.**
On this box, against the real processes, a real SearXNG
(`searxng/searxng@4e2c1ea` in WSL2) and a local model fixture that calls
tools:

- **Claude Code 2.1.283**'s WebSearch — its own `/v1/messages` request with
  `web_search_20250305` — answered with `server_tool_use` and
  `web_search_tool_result` blocks, and Claude Code finished its answer.
- **Codex 0.130.0** with `web_search = "live"` searched; it accepts the
  `web_search_call` items and prints `web search: <query>` for each.
- **Chrome** added a SearXNG account through the page (its Test ran a real
  search), found it under Backends, and searched from the playground, which
  showed the source under the answer.
- The real SearXNG's results reached the model, which cited
  `https://github.com/searxng/searxng`.

**And P8e:** through the unmodified OpenAI SDK, a local model on
`/v1/responses` called `image_generation`; the router account's image model
made it; the SDK got an `image_generation_call` item with the bytes and the
model got only words, batch and streamed (`in_progress` → `generating` →
`completed`).

## The gates

- **`scripts/p8-search-acceptance.py`: 15 fixture checks, in specs CI.**
  `--clients --browser --searxng URL` adds Claude Code, Codex, Chrome and a
  real SearXNG: **19 of 19 PASS** on the final pins.
- **`scripts/p8-sabotage.py`: 45 of 45 caught, no declared escapes** — 32 for
  P8a-P8d, 13 for P8e. It restores from byte copies and opens with a
  baseline that every gate it uses passes unsabotaged.
- **Every acceptance script specs CI runs passed locally against the working
  trees before the pin** (18 scripts plus `s10-checks` and `a8-summarize`).
- **Unit suites:** gateway 1029 (28 P8 + 13 P8e in two new modules),
  tool-driver 60, agent 1408, control 262, inference-driver 844, library
  534, ui 1438 (vitest; lint, types and format clean).

## What the sabotage pass found

The first pass escaped three, and each named a check that could not fail,
not a weak fix:

1. **Failover after a search** was tested with a second turn that raised
   `RuntimeError`, which cascades nowhere whether or not the loop pins. It
   raises `httpx.ConnectError` now — a failure the first call would cascade
   on.
2. **A search called on the last turn** — the turn that offers no search
   tool, which a model may call anyway — was never tested reaching the
   caller. A stream test at `max_tool_calls: 1` covers it.
3. **The tool-scope sabotage went into the agent's `client_admission.py`**,
   which an enrolled node never consults: it forwards a key's admission to
   the control root, whose identical copy decides. This is P1's measured
   finding (2026-09-27) again. The control root's copy is sabotaged against
   the acceptance run now, and the agent's against its own unit test.

## What the acceptance runs found

- **Every search went to Brave**, the paid account, because accounts sorted
  by name. Hence `ToolDriverInfo.billing` and free accounts first.
- **Codex printed an empty `web search:` line** until the added
  `web_search_call` item carried `action.query` (closes the measurement
  record's owed item).
- **Claude Code's WebSearch looped** against the first fixture, which keyed on
  the last message; Claude Code puts a reminder after the tool result. The
  fixture reads tool results since its own last call, as a model does.
- **An OpenRouter image model must be listed on `/models/user` as well as
  described on `/images/models`** (P4's measured shape); the first P8e run's
  fixture listed it on one only, and the gateway rightly never saw it.

## Not done, named

- **Brave live**: no Brave key on this box. Built from its API documentation
  and a fixture that checks the subscription token.
- **A live image through the tool**: the P8e leg uses the OpenRouter-shaped
  fixture. P4's live run already proved the images path the tool reuses;
  the tool's own call to a live provider has not been made.
- **Codex does not send `image_generation`**, so no real client has made an
  image through the tool; the OpenAI SDK has.
- **The installers' Windows half** was not re-run: it writes this account's
  environment, which the live worker depends on. The POSIX half was, in
  WSL2 from nothing on the final pins: **16 of 16**, the seventh package
  installed and the install serving. Its checks 12-13 first failed because
  they had been stale since the Logs page (2026-09-27): every line now opens
  with a timestamp and the agent's with `[agent]`, so greps anchored at `^[`
  and `^INFO` matched nothing on a stop the log showed was graceful. The
  instrument is fixed; the product was not wrong.
