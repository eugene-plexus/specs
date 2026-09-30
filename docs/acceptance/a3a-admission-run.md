# A3a acceptance: admission asks the engine whether it places models itself

**2026-09-30.** `scripts/a3a-admission-acceptance.py`. Design:
[`../design/moe-aware-fit.md`](../design/moe-aware-fit.md) call A, taken by
Troy the same day.

**The defect.** Admission read an unset `gpuLayers` as "the whole model
on the card", and refused any `tight` or `split` verdict for it. Every
profile the builder saves leaves `gpuLayers` unset on purpose, because
llama.cpp's own `--fit` places the model, experts or layers in system
memory as needed. So a built profile would have been refused at launch on
exactly the cards where the build had measured it running (M4 in the
design, shown by execution).

**The rule now:**
- Where the spec's llama-server lists `--fit` in its own `--help` (cached
  per binary), an unset `gpuLayers` is a partial launch the engine
  arranges. `tight` and `split` are admitted, and the reason says so.
- `--fit off` in `extraArgs` restores the old reading.
- An explicit `gpuLayers` is the operator's, whatever the build can do.
- `no` (more than the card and RAM together) is still refused.
- Another engine is always full offload.
- A binary that cannot be resolved or asked counts as not placing, the
  conservative answer.

**The run, first-time pass, launching nothing.**
- A disposable agent answered admission dry runs against this machine's
  real devices, with the live Amish_Station model holding about 28 GB of
  the 5090, and the real b11215 build.
- The model was Qwen3-30B-A3B Q4_K_M (18.6 GB, more than the free memory):

| Spec | Verdict | Decision |
|---|---|---|
| `gpuLayers` unset, b11215 (`--fit` listed) | `tight` | **admit**, "with GPU layers left to llama.cpp, which places what does not fit in system memory itself" |
| The same with `extraArgs: ["--fit", "off"]` | `tight` | refuse |
| `gpuLayers: 99` | `tight` | refuse |
| A context large enough to exceed the card and RAM | `no` | refuse |

**Tests and sabotage.**
- `tests/test_engine_places.py` covers the rule, the escape hatch, the
  help reading and the other engines.
- A conftest fixture stops every admission route test from reading a real
  llama-server's help. Seven route tests failed on this box and would
  have passed on CI, because they were reading the machine they ran on.
- `scripts/pb1-sabotage.py` now carries six more entries: the rule, the
  escape hatch, the help check, the route never passing the answer, and
  both thresholds Troy set (High 96%, Low 88%). **27 of 27 caught.**

**Not covered.** A real launch of a split model through the agent: the
PB1 acceptance runs launched the same model through llama-server
directly, with fit placing it. And the library's estimate is still the
dense arithmetic, which is A3b.
