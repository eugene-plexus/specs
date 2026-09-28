# P1: one driver serves many models — the run

**2026-09-27.** Design: [`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§2.1, §4 and §7 (the four calls P1 raised, all taken as recommended).
Measurements it was built against:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md).

**What it does.** An OpenAI-compatible connection with no model set is a
**provider account**: its driver reads the provider's own list and serves every
model in it. The gateway publishes those models as `<connection>/<model id>`
(`openrouter/anthropic/claude-opus-5.5`, `ollama/qwen3:8b`). One OpenRouter
driver process now serves 625 models where one process per model was the only
way before.

## Results

- **`scripts/p1-accounts-acceptance.py`: 7 checks with fixtures, 8 with
  `--openrouter-live`, all PASS.** The run uses a real control root, an enrolled
  agent, a gateway and three drivers, all signed, with isolated ports and state.
- **Live OpenRouter:** 625 models listed, 625 exposed, **492 on `/v1/models`**.
  The other 133 are speech, image, video and transcription models with no door
  here yet (P1-4). Two completions went through one driver process and one key
  scoped `openrouter/*`. The alias `~z-ai/glm-flash-latest` was reported under
  the id the caller asked for, although OpenRouter answers it as
  `z-ai/glm-5.3-flash`.
  - The key reached its driver in `OPENAI_API_KEY` only. A scan afterwards found
    it in 0 of 88 files of the run's state, logs and the session scratchpad.
- **`scripts/p1-sabotage.py`: 13 of 13 caught**, after the first pass escaped
  two (below). It opens with a baseline assertion that the gate passes
  unsabotaged, and restores every file from byte copies.
- **Unit suites:** inference-driver 660 (19 new), gateway 783 (15 new), agent
  1398, control 257, UI 1278 (10 new). ruff, format and mypy are clean on every
  Python repo; tsc, eslint and prettier are clean on the UI.
- **The specs CI acceptance set**, run against the branches: see the last
  section.

| Repo | Commit | What changed |
|---|---|---|
| `specs` | `619d052`, `f80e66d` | The contract: `DriverInfo.models[]` replaces `modelId`, `upstreamModelId` and the driver-wide `capabilities`; `DriverModel`, `DriverCatalogue`; `model` on every driver request; 404 `#model-not-served`, 400 `#model-required`; `/v1/info?models=false` and `?model=`; `DriverHealth` and `RoutingTableView.outdated_drivers`; `MetricAttempt.model`; `*` in `allowedModels`; the `string_list` config type |
| `inference-driver` | `ad0a022`, `8ff94e7` | Account mode and the catalogue (`engines/_catalogue.py`): OpenRouter's `/models/user?output_modalities=all`, Ollama's `/api/tags` and `/api/show`, LM Studio's `/api/v0/models`, the OpenAI `/v1/models` shape. Kept on disk, refreshed hourly, filtered live. Per-request model resolution and per-model gates |
| `gateway` | `0ddb6fe` | Candidates keyed `(node, driver, model)`, prefixed for an account; `BoundClient` per model (names the model, publishes the public id, owns its circuit); `/v1/models` only for models a door serves; `*` patterns; outdated drivers named; metrics schema v6 |
| `agent`, `control` | `d9a99b4`, `8874d48` | The same `*` matcher in client-key admission; regenerated |
| `ui` | `d121524` | Add-an-account flow; account rows on Inference and Nodes; three Issues; capped and filtered model pickers; `string_list` editor; key-pattern copy |

## The checks

1. One account driver lists two models, published as `acct/<id>`, **each with
   its own facts** (context windows of 8,192 and 32,768 come through as
   different). A single-model driver keeps its bare id.
2. Each request reached the upstream **as the model it named, unprefixed**, and
   the answer came back under the public id, both streamed and not. Counted at
   the upstream per model.
3. A key scoped `acct/*` sees and uses only the account's models. `acct/alpha/*`
   narrows it to one. The key's authority (the control root, since the agent is
   enrolled) refuses the rest with 403.
4. A driver still answering `/v1/info` with one `modelId` is routed nothing. It
   is named in `outdated_drivers` and `DriverHealth` with its machine and the
   model it used to serve.
5. Each metrics attempt records the published model it asked for (schema v6).
6. An exclude pattern takes effect **without a restart**. The excluded model is
   a 404 `#model-not-served` at the driver and never reaches the upstream.
7. **Restarted while the upstream's list is down**, the account serves the last
   good list from disk, says why on `/v1/info`, and a completion through it
   works.
8. (`--openrouter-live`) A real OpenRouter account, as above.

## The sabotage pass, and what its first run found

The first pass caught 11 of 13 and escaped two. Each escape was a different
thing, and neither was a weak fix:

- **"The per-model entry is ignored; a driver's first model routes every id"
  escaped because the check could not see it.** Both fixture models had
  identical capabilities, so which model's facts a candidate carried made no
  observable difference. The fixture now lists the two with different windows,
  the way vLLM's listing reports `max_model_len`, and check 1 asserts each
  model's own window. The sabotage is caught now.
- **"The agent's key matcher knows no wildcard" escaped by measurement, and
  correctly.** This run's agent is enrolled, and an enrolled agent forwards key
  admission to the control root, so the agent's copy decides only on a
  standalone install. The control root's copy was added to the pass and is
  caught. The agent's copy is checked by its own unit tests, and the same
  sabotage fails two of them.

## What was not done

- **Ollama and LM Studio were not run live.** The Ollama mapping (`/api/show`
  capabilities) is unit-tested against measured shapes. The LM Studio mapping
  was written from its documentation and never met an LM Studio.
- **No browser drove the new UI.** The add-account flow, the account rows and
  the Issues are component- and unit-tested.
- **A client key naming a model that left its provider's list** keeps working
  for the models still there, and nothing says that one entry now matches
  nothing. Routing choices get an Issue for this; key scopes do not yet.
- **Home's model selects have no filter.** A native `<select>` of 492 entries
  still type-ahead searches. The playground's picker and the Routing page have
  filters.
- **The per-request re-check** asks the driver for one model's entry
  (`?model=`). That is unit-tested in the gateway and not observed in this run.
- **An older driver on another machine** was simulated by a stub on this one.
  Updating a real worker is what clears it.

## The specs CI acceptance set, against the new pins

These 13 scripts ran in a fresh Python 3.12 environment holding the five
components, and all 13 pass: `s10-starter-check`, `r7-signing-checks`,
`r7-rotation-acceptance`, `row3-per-node-keys-acceptance --lan`,
`r8-profile-acceptance`, `a3-client-keys-acceptance`, `a5-scoped-keys-acceptance`,
`a6-local-only-acceptance`, `a6b-failover-acceptance`, `a7-recovery-checks`,
`r8-profile-checks`, `r6-benchmark-checks` and `b1-mlx-identity-acceptance`.

Three failed on the first run, and **each failure was its fixture, not the
product.**

- **R8 and A5 fake a driver that answers `/v1/info` in the shape from before
  P1.** The gateway now does to them what it does to any such driver: it names
  them as outdated and routes nothing to them. Both fakes answer in the current
  shape now, and the R8 fake also ignores `?model=`.
- **A6b builds a `CodexCliEngine()` by hand with no model.** A real driver reads
  its model from config, which this harness bypasses. Before P1, `/v1/info` took
  the model id from the config file even though the engine had none. It now
  reports what the engine serves, which was nothing. The harness passes the model
  now.

**Also updated but not re-run:** the fake drivers in `r4-stubs.py`,
`r14-acceptance.sh`, `r15-acceptance.sh`, `r21-acceptance.sh` and
`still-computing-acceptance.sh`, plus the old-shape reads in
`reasoning-samplers-acceptance.py` and the anchors of `b1-sabotage.py`. They are
manual, heavyweight runs, and each was syntax-checked only.

**Pins, both installers:**

| Component | Pin |
|---|---|
| agent | `d9a99b4` |
| control | `8874d48` |
| gateway | `0ddb6fe` |
| inference-driver | `8ff94e7` |
| ui | dist `323e3b5`, the export of `d121524` |

`library` stays at `cec7815`. It uses no new type, so a re-pin would only
regenerate a `ConfigValueType` enum. Every pinned archive was fetched from
GitHub (HTTP 200).
