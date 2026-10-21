# Row 9: Engine cache settings on a profile, sized from the machine

Lane ENG. Risk: cross. Size: M. Call: LD-C5. Sources: PC7, LD2, CB4.

## 1. What the row delivers

- A llama.cpp profile gets "Prompt cache in system memory" (`--cache-ram`), "Reuse moved text" (`--cache-reuse`) and "Checkpoints per slot" (`--ctx-checkpoints`), beside `parallelSlots` and CB4's `slotPinning`.
- Unset, the prompt cache is sized from the machine at start. Eugene always passes the size, and the running model shows it.
- A vLLM profile gets the same setting. It becomes CPU KV offload (`--kv-offloading-backend native --kv-offloading-size <GiB>`) when the installed vLLM offers it.
- Admission counts every running prompt cache against system memory. A refusal names whose cache holds the memory.
- The default follows a measurement of llama-server's cache-update pause (LD-C5).

## 2. The design

**Step 0, measure: `specs/scripts/cache-ram-pause.py` (new).** It wraps `prompt-cache-measurement.py`, which found the 6-10 s pause.
- **Shapes:** A is one replica, `--parallel 4`, 16 sessions, concurrency 8, so most turns pick a slot by LRU. B is §5's 8-replica shape, where the pause appeared.
- **Sizes:** 8192 MiB, the computed size (about 20 GiB for an 8B on the 96 GB box) and 65536 MiB. Each run adds `--engine-arg --log-timestamps --engine-logs <out>/<size>`.
- **A pause** is the time from `selected slot by LRU` to the next `launch_slot_` line. `cache state:` lines give the MiB held.
- **Report, per size:** pause p50, p90 and max; MiB held; 30-second stalls; the share of each prompt reused.
- **Verdict:** the computed size wins when its p90 is at most 0.5 s above 8 GiB's, its max at most 1.25 times 8 GiB's, and it has no more stalls.
- If the build lacks `--log-timestamps`, the script stamps lines with `perf_counter()` as they arrive. The record is `docs/acceptance/cache-ram-pause-measurement.md`.

**llama.cpp (`engines/llama_cpp.py`).** New `ConfigField`s (category `memory`) and `_FLAG_CLI_NAMES` entries:
- `cacheRam`: GiB, minimum 0, where 0 is off; the argv takes MiB. "Keeps recent conversations in system memory, so their next turn is not read again." `unsetMeans` if LD-C5 holds: "Not set: sized from this machine when the model starts: a quarter of the memory the model leaves, from 8 to 64 GiB." Otherwise "Not set: 8 GiB."
- `cacheReuse`: tokens, `default=0`. "Reuses repeated text found at a new place in the prompt, in pieces of at least this many tokens. 0 is off."
- `ctxCheckpoints`: `default=` the managed build's value from its `--help`. "How many points in each conversation a hybrid or sliding-window model can return to. Each one uses memory."

Eugene always passes all three, so an upstream change of default cannot make a setting lie. A flag missing from the build's `--help` (`_help_flags`) is left out, and the runtime says so.

**vLLM (`engines/vllm.py`).**
- Field `kvOffloadGb`, with `cacheRam`'s label and `unsetMeans`.
- Passed only when `vllm serve --help=all` lists `--kv-offloading-size`. The help is read once per binary path and modification time.
- The build confirms the flags in `RECIPE_VERSION` 0.30.0's `engine/arg_utils.py`. If they are not there, the row ships llama.cpp only, and the field reads "Not offered by this vLLM".
- The build also measures whether vLLM takes the offload memory at start or as it fills.

**Size (`admission.py`, new `prompt_cache_bytes`).**
- `left = ram_available − this launch's model bytes in system memory − other caches' claims`.
- Model bytes in system memory: all of `required` on CPU; `max(required − budget, 0)` on a discrete GPU that spills; on a shared-memory device (Mac, iGPU, GB10), the pool's free bytes less `required`.
- `size = clamp(left / 4, 8 GiB, 64 GiB)`, never above `left / 2`. Below 512 MiB it is 0, which is off.
- An explicit profile value is used as set. `Admission` reports `promptCacheBytes`.

**Counting.**
- A llama.cpp cache fills over time, so its whole size stays a claim against later launches (`RunningRuntime.prompt_cache_bytes`). Counting a cache that is not full refuses rather than admits, the direction the ledger already accepts.
- vLLM, if it takes the memory at start: the ledger holds it until `ready`, and the memory reading shows it after that.

**Launch (`runtimes.py` `_launch_spec`).** The computed size goes into the argv only. The stored profile is never rewritten. If `extraArgs` repeats `--cache-ram`, the last one wins, and the runtime reports it.

**Contract (`agent.yaml`).**
- `Admission.promptCacheBytes`.
- `Runtime.promptCache`: `{bytes, source, note}`, with a named enum `PromptCacheSource`: `profile`, `machine`, `engine_default`, `off`, `unsupported`.

**UI.** `ProfileEditor` renders the fields from `flagSchema` with no new code. The inference page gets `lib/promptCache.ts` `promptCacheLine`, beside `speculationLine`:
- "Prompt cache: 24 GiB of system memory, sized from this machine."
- "Prompt cache: 8 GiB, set on the profile."
- "Prompt cache: off."
- "Prompt cache: not set; this llama.cpp build has no --cache-ram."

**Failures, each naming its cause.**
- **Admission refuses:** "Not enough system memory: the model needs 30 GiB, and the prompt caches of qwen3-8b and gemma-4 hold 16 GiB of the 40 GiB free. Lower their prompt cache, or start anyway."
- **No memory reading:** 8 GiB, with the note "this machine's free memory could not be read".
- **vLLM refuses the memory:** `explain_exit` says "vLLM could not reserve 24 GiB of system memory for the prompt cache. Lower Prompt cache in system memory."
- **llama-server turns `--cache-reuse` off:** upstream's line goes into `promptCache.note`.

## 3. Repositories, files, codegen

- **specs:** `openapi/agent.yaml`, `scripts/cache-ram-pause.py`, the record, PC7's "what building found".
- **agent:** `engines/llama_cpp.py`, `engines/vllm.py`, `admission.py`, `runtimes.py`, `routes/runtimes.py`.
- **ui:** `src/lib/promptCache.ts` and its test, and one line in `src/app/inference/page.tsx`.
- **Codegen:** agent, control (it generates `agent.yaml`) and ui. Confirm the others by regenerating and diffing.

## 4. Tests that fail before the change

- `agent/tests/test_admission.py::test_running_prompt_caches_are_counted_against_system_memory`: with a 16 GiB cache running, a launch needing 30 GiB of 40 GiB free is refused, naming the runtime.
- `test_prompt_cache_is_a_quarter_of_what_the_model_leaves`: 96 GiB free with 8 GiB spilled gives 22 GiB; 300 gives 64; 10 gives 5.
- `agent/tests/test_engines.py::test_cache_flags_are_always_passed`: unset gives `--cache-ram <MiB> --cache-reuse 0 --ctx-checkpoints N`; a flag the help lacks is left out.
- `agent/tests/test_vllm.py::test_kv_offload_only_when_the_build_offers_it`.
- `ui/src/lib/promptCache.test.ts`: the four lines.

## 5. Do not change

`library/fit.py`, `hardware.py` (rows 16, 43); `agent/host_probes.py`, `engines/gpu_probe.py` (43); `engines/speculation.py` (17, 41); `engines/acquisition.py` (13, 42); `ui/src/lib/settingsTopics.ts`, `ConfigField.tsx` (33, 62); `inference-driver/slots.py` (15).

## 6. Size, risks, open questions

- **Size:** M. The measurement takes about half a day on the 5090, on free ports, with `EUGENE_PLEXUS_*` cleared.
- **Risk:** counting whole caches can refuse a second model that runs today on a 32-64 GB machine. The refusal names the cache and the setting, and `force` stays.
- **Risk:** small machines get less than upstream's 8 GiB (`left / 2`). That protects them, and it is shown.
- **LD-C5 (Troy):** recommendation: build the computed default, and ship it only if Step 0's rule passes. Otherwise 8 GiB, with the larger size as the setting.
- **Open:** "about 9 conversations of this model" (LD2) needs KV bytes per token at the slot's context. Recommendation: later, from row 10's records.

## Calls answered by Troy (2026-10-21)

- **LD-C5: the owner can resize the cache.** The default follows the measurement in this design. The size is a setting on the runtime's profile, with the default shown.
