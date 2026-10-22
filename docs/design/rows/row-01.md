# Row 1: Contract cleanup in one regeneration

Lane OPS. Risk: cross. Size: S. Call: B2-REV (default built: add the field).

## 1. What the row delivers

- A `/v1/systemone` answer names the backend's model revision in `x_eugene_plexus.reported_model`. The contract's sentence becomes true.
- Agent and control no longer offer `uiTheme`/`uiFontSize`. A PATCH of either is refused as retired. An old file or log entry that holds them still loads.
- Claude Code through the Anthropic door to an OpenRouter `anthropic/*` model is cached upstream; turn 2 reports `cached_tokens`. The ignored-settings header names `cache_control` only when the answering backend did not carry it.
- Specs CI fails when a consumer pins a specs commit holding a document it should generate, and its codegen config does not name it.

## 2. The design

**Finding: (b) is not a contract change.** The two settings are `ConfigField`s in `agent/state.py` and `control/config.py`, in no yaml. Agent and control change code only and keep their pins.

**(a) B2-REV, `gateway.yaml`.** `CompletionRoutingInfo.reported_model: string`: "What the backend said served this request, verbatim. Provenance, never a routing key. Only the decision door sets it today; absent when the backend reported none." `SystemOneResponse.model` now says "surfaced as `x_eugene_plexus.reported_model`". Code: `gateway/routes/inference.py`. `_routing_info` takes `reported_model=None`; `create_decision` passes `result.reportedModel`.

**(b) SET-1.**
- `control/config.py`: delete both fields. Add them to `RETIRED` with "retired: nothing read it; the console's look is set in the console". `as_document` already hides retired keys that a replayed log entry holds.
- `agent/state.py`: delete both fields and add a `RETIRED` map like control's. `apply_config_patch` uses its message instead of "unknown field". `load` already skips unknown keys.
- Tests that use `uiTheme` as a harmless key move to keys without side effects. Agent: `modelCopyMinFreeGb`; invalid enum `securityMode: "neon"`. Control: `joinTokenTtlSeconds`; invalid enum `logLevel`. `specs/scripts/standby-acceptance.py` (~line 498) changes the same way.
- `ui/src/lib/settingsTopics.ts` keeps both keys hidden: an older agent on another machine still reports them.

**(c) PC6, `inference-driver.yaml`.**
- New named schemas: `CacheTtl` (enum `5m`, `1h`) and `CacheControlHint` (`{ttl?: CacheTtl}`).
- `GenerateRequest.cacheControl: CacheControlHint`: "The client marked part of the prompt for caching (Anthropic `cache_control`). A hint: never in `callerSettings`, never a routing input."
- `supportedSettings`: it also names the hint `cacheControl` for each model whose adapter carries it.
- `GenerateRequest` allows extra fields, so an older driver ignores the new one.

Code:
- `gateway/anthropic.py` `translate_request`: set `cacheControl` when any top-level, system, message, tool or `tool_result` block carries `cache_control`. Use the longest `ttl` sent.
- `gateway/routes/inference.py` (Anthropic paths, ~1566 and ~1615): leave `cache_control` off the ignored list when the answering candidate lists `cacheControl`.
- `inference-driver/engines/openai_compat_http.py` `_payload_for`: catalogue `openrouter` and a target id starting `anthropic/` send `"cache_control": {"type": "ephemeral"}` plus `ttl`, and those models list `cacheControl`. Elsewhere, `_warn_dropped("cache_control", target)`.

**(d) `specs/scripts/codegen-inputs.py` (new).**
- A table in the script: each document and its consumers. Fragments name the document that reaches them. A document nobody generates says why (`workbench-ag-ui.yaml`: prose contract). The table is not under `openapi/`, where CI validates every yaml as OpenAPI.
- **Rule A:** every `openapi/*.yaml` and `openapi/components/*.yaml` has a row.
- **Rule B:** fail when a document is in the table for a consumer, is present at that consumer's `SPECS_REF`, and its codegen config (`scripts/codegen.py`, or ui's `codegen.mjs`) does not name it. That is the `control.yaml`/ui case. Fail too when a config names a document the table does not give it. Rule B never blocks the specs-first order, because a consumer not yet re-pinned is not checked against the new document.
- `--root DIR` reads sibling checkouts. Without it, the script reads each file at its pin from `raw.githubusercontent.com`. Pins: `install.sh` `PIN_*`, the agent's site-host and Workbench pins.
- CI: one step after "Validate every OpenAPI document", Linux, `fetch-depth: 0`.
- Message: "ui pins specs abc1234, which has openapi/control.yaml; ui/scripts/codegen.mjs does not generate it."

**Failures.**
- A provider that refuses `cache_control`: the driver's `_backend_error` already names the provider's 400.
- A consumer file (d) cannot read: the step fails, naming the URL and the HTTP status. It never passes silently.

## 3. Order, repositories, codegen

1. One specs commit on `r1-contract-cleanup`: both yaml changes, `codegen-inputs.py` and its test, the `ci.yml` step, the `standby-acceptance.py` line. Push it.
2. `inference-driver`: set `SPECS_REF`, regenerate from `.venv`, then the code.
3. `gateway`: set `SPECS_REF`, regenerate `models.py` and `driver_models.py`, then the code.
4. `ui`: set `SPECS_REF`, `npm run codegen`, commit the generated types only. It names both changed documents.
5. `agent`, `control`: code only. Regenerate and diff to prove their output (and library's, tool-driver's, site-host's, workbench's) unchanged. Leave those pins.
6. Merge the consumers, then specs.

## 4. Tests that fail before the change

- `gateway/tests/test_decisions.py::test_the_backend_revision_rides_on_the_envelope`: `x_eugene_plexus.reported_model == "<jev reported>"`. The conftest already returns that value.
- `inference-driver/tests/test_chat_fields.py::test_cache_control_reaches_openrouter_anthropic_models_once`: the payload holds `cache_control` for `anthropic/claude-sonnet-4.5`, and has none for `openai/gpt-5`.
- `gateway/tests/test_anthropic_messages.py::test_cache_control_is_carried_when_the_answering_backend_takes_it`: the driver receives `cacheControl`, and the header lacks `cache_control`. `test_cache_control_is_dropped_wherever_it_appears` stays green.
- `agent/tests/test_config.py::test_ui_theme_and_font_size_are_retired` and `control/tests/test_config.py::test_ui_theme_is_retired`: gone from the schema; PATCH refused with "retired"; an old file or log entry still loads.
- `specs/scripts/test_codegen_inputs.py::test_a_consumer_pinned_past_a_document_it_does_not_generate_fails` (a fixture git repo), and `test_every_openapi_document_has_a_row` (the real tree).

## 5. Do not change

`ui/src/lib/settingsTopics.ts` (row 33), `gateway/routing.py` (11, 14, 37, 61), `gateway/chat_contract.py` (29), `gateway/metrics.py` (12, 38), `inference-driver/slots.py` (15).

`gateway/routes/inference.py` is the GW lane's. Row 1 edits three small places in it and merges before any GW row that touches it. The row's `hot_files` should name it in place of `decisions.py`, which row 1 does not need.

## 6. Size, risks, open questions

- **Size:** S, about one day.
- **Risk:** a GW branch cut before row 1 merges conflicts in `routes/inference.py`.
- **Risk:** Rule B reads over the network. An outage turns the step red, naming the URL.
- **B2-REV (Troy):** add the field, or fix the sentence. Recommendation: add it (built). It is one optional field, and the only place a caller sees which Jev revision decided.
- **Open:** the OpenAI chat door's `cache_control` on content parts. Recommendation: wait until a measured client sends it.

## Calls answered by Troy (2026-10-21)

- **B2-REV: add the field.** Every `/v1/systemone` answer names the model revision that made it, as the contract promises.
