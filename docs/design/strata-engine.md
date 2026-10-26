# Strata engine investigation

**Status: researched 2026-10-04; experimental support direction accepted,
first implementation included in Edge.** See the [usage guide](../deployment/experimental-engines.md)
and [verification record](../acceptance/strata-engine-run.md). Troy asked to investigate Strata for the hobbyist audience. The
three currently open Eugene issues (Gemini's client and provider interfaces,
and Google/Microsoft sign-in) are independent of this work.

The target is [Niko1221/Strata](https://github.com/Niko1221/Strata), not the
unrelated projects with the same name. This investigation used **v0.1.39**,
released October 4, source commit
`6f32ec070f23ced9f50e704d854d775da52591ab`. Upstream documentation, source,
release assets and issue discussions were read; model file metadata was
queried with `hf`. The subsequent implementation installed the real Windows
recipe in isolation and exercised Eugene against Strata's actual HTTP server
with its mock engine. No model weights were downloaded and no GPU inference
was performed. Performance remains upstream evidence until measured through Eugene.

## Integration audit, 2026-10-15

The current changes address four gaps in Eugene's adapter and API translation:

- **Reasoning controls:** the generic HTTP capability filter incorrectly removed
  Strata's declared `reasoningEffort`. Strata now advertises and receives it.
  Chat Completions, Responses and Messages share the same best-effort path;
  unsupported effort no longer blocks a request. Strata's configured thinking
  mode uses native effort controls without appending instructions to the prompt.
  An explicit request overrides the configured default.
- **Thinking disabled:** Anthropic's `thinking.type: disabled` now requests effort
  `none`, instead of only hiding the output. Unsupported controls are named in
  the response header using the client's field name. Exact Anthropic token
  budgets remain outside the shared driver contract.
- **Stop sequences:** the pinned server reads its model's stop tokens but does
  not implement caller-provided stop strings. Eugene now enforces them on visible
  answer text, retaining partial matches across stream chunks and closing the
  upstream connection at a match. Whole answers use the same path. Tool arguments
  and reasoning are not truncated. Early cancellation has no invented usage count.
- **Optional parallel requests:** a prepared config may request `parallel: 1..8`.
  The agent reports the effective `concurrency.serving` from `/v1/status`, not the
  requested count or the single entry in Strata's compatibility `/slots` endpoint.
  Missing or invalid status leaves capacity conservatively at one. Existing
  configurations retain their setting; parallelism is not enabled automatically.

Evidence: the pinned [request translator](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/serve/frontend.py),
[server](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/serve/server.py),
and [batching documentation](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/docs/BATCHING.md),
plus the locally prepared Qwen3.8 Flash Next IQ2_XS chat template. Regression
tests exercise the real Eugene routes with simulated upstream responses,
stream closure, split stop sequences, tool arguments, and effective capacity.
This audit does not measure GPU throughput or deploy the changes.

Known upstream limitations remain: `tool_choice: required` and named choices,
`parallel_tool_calls: false`, structured output together with tools, and log
probabilities. Multi-GPU preparation still requires separate integration work.
Optional image preparation is included in Edge as described below. The API
compatibility layer still cannot express Strata's exact per-request reasoning
token budget, although a prepared config can supply its native default.

### Edge image preparation follow-up (2026-10-17)

The preparation contract now offers `off`, `cpu` and `gpu` image modes for
supported Strata models. Omission remains text-only. Unsloth UD-Q4_K_XL does
not offer images, matching the pinned setup. Enabling images adds a conservative
1 GB disk allowance for the encoder; memory fit remains unknown.

The selected mode survives Library persistence and browser refresh, reaches
upstream setup, and is checked against setup's resulting encoder placement.
A GPU-to-CPU fallback fails explicitly rather than claiming the requested mode.
Encoder assets travel with the prepared model, but executable paths do not:
each node supplies its own installed encoder. A changed prepared configuration
restarts an existing runtime through admission; an unchanged replay does not.

The driver reads the running model's `/v1/status` before advertising image
input. Disabled, unavailable, errored, unloaded or mismatched models do not
claim it. Streaming and non-streaming routes preserve inline image parts.
These paths have automated coverage and scoped sabotage checks, not a new
GPU image-inference result. Edge pins the updated contracts and consumers,
including the rebuilt UI distribution. Native CPU/GPU image inference remains
for live-server validation. See the
[verification record](../acceptance/strata-engine-run.md).

## Row 63 contract and pinned-source findings (2026-10-22)

**Phase 1 contract committed at `c0ff043`; phase 2 consumers built in this worktree.**
The row design was read in full from
`D:/py/ep-wt/calls-1022c/specs/docs/design/rows/row-63.md`. It has no
"Calls answered by Troy" section and no open calls. Findings belong in this
worktree's investigation because that row design is on an unmerged branch.

No upstream source checkout is vendored in these row worktrees. The adapter
and preparation code record parts of setup at the pinned commit. The
following upstream files were also read successfully through GitHub, all at
`6f32ec070f23ced9f50e704d854d775da52591ab` (v0.1.39):

- [setup.py](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/setup.py)
- [serve/server.py](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/serve/server.py)
- [docs/DETAILS.md](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/docs/DETAILS.md)
- [docs/MULTI_GPU.md](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/docs/MULTI_GPU.md)
- [the projection README](https://github.com/Niko1221/Strata/blob/6f32ec070f23ced9f50e704d854d775da52591ab/data/experimental-speed-projection/README.md)

None of those reads was blocked. No model, vector asset or engine build was
downloaded, and no engine or agent was started. These findings are upstream
source and recorded measurements, not a new Eugene hardware measurement.

**The projection changes answers.** The bundled vector removes a direction
from the residual stream after layers 4 through 44. Its package describes
that direction as one associated with refusals. Upstream reports fewer
refusals and changes to ordinary predictions: a different most-likely token
at 10% of measured positions, with perplexity increases of 15% on code,
2.3% on a document and 0.4% on a chat. These are upstream's particular test
results. They do not predict the effect on another person's prompts.

This is not an engine speed optimization. On the same supplied text,
upstream measures an extra 0.2-0.4% cost per token. Any change in a chat's
tokens per second depends on the generated text and draft acceptance. The
GUI's first description line must say it changes answers and is
experimental, without promising a speed gain.

Setup takes `--experimental-speed-projection on|off`. When enabled, it
writes `--control-vector-scaled <vector-path>:1.0`,
`--control-vector-layer-range 4 44`, `--cvec-mode project` and
`--cvec-dir per-layer` into the native arguments. These are native launch
flags; passing the setup flag to `serve/server.py` is not equivalent.
Launch must resolve the vector from this node's installed source bundle,
without copying an executable path from another node. Its sampling default
also matters: `sampling.experimental_speed_projection: false` disables a
loaded vector. A per-request change drops the conversation cache once.

At this pin, setup enables the bundled vector for the original and Coder
families. For Swift and other families it warns and leaves it off. Report
that observed fallback and the actual mode. Missing tests alone are not a
reason to block an expert's launch choice; do not turn the absence of an
advertised preparation choice into a blanket model prohibition.

**Several cards use contiguous layer ranges.** Setup accepts `--gpus 0,2`
and `--layer-split auto` or an explicit boundary string. It writes
`gpu: [0, 2]` and `layer_split` to the prepared JSON. The server turns that
into `--layer-split`; it also sets process visibility from the ordered GPU
selection. The first card is the main card; the last stage also holds the
output head and MTP layer. For three cards, `16,32` means layers 0-15,
16-31 and 32 onward. It is not a list of layer counts. The server accepts
a boundary string or JSON list, checks one rising integer per later card,
and requires the first boundary to be at least 2. The adapter must also
check boundaries against the model's layer count before launch.

Automatic placement uses free VRAM and the expert profile. For two or three
cards it searches placements; for more it uses proportional placement.
The mode `auto` does not reveal the selected numerical boundaries. Upstream
records about 18-20% faster prompts for one 5080/3090 Coder test, with decode
depending on the workload. A much slower extra card can reduce speed. Those
numbers are not a Eugene performance claim or an admission gate.

Fit must use the selected cards, not every installed card or only the main
one. Sum their usable contributions after each card's dense-weight, KV and
buffer allowance. In particular, setup's low-RAM estimate sums each card's
expert capacity after roughly 5 GB of overhead per card at 32K context;
passing total VRAM through the old single-card formula overestimates it.
Count the shared host expert arena once. Unknown card memory remains an
unknown estimate, with its observed cause, rather than an automatic refusal.

Setup changes the low-RAM resident mode to memory mapping for a layer split,
and warns that free RAM can fall to zero during long prompts. A RAM-budget
model cannot use that budget with a split: setup instead requires the
model's downloaded size plus 24 GiB of host RAM and removes the budget.
Preserve and report setup's actual mode and warnings. Its automatic
`--remote-expert-opt` addition also needs to survive validation. Known
upstream incompatibilities are distinct from combinations not yet tested.

**Contract choices and defaults built.** `components/common.yaml` now owns
the preparation intent and the shared projection, ordered GPU selection
and layer-boundary shapes. `ModelPreparation.speedProjectionModes` advertises
choices for each model. Library exposes the intent for code generation;
profiles continue to store engine-owned flags without validating them.
The agent's adapter remains the validator, and its GUI schema must expose
`speedProjection`, `gpus` and `layerSplit` in phase 2.

New preparations default to projection `off`, the existing automatic
single-card selection, and `auto` boundaries if several cards are explicitly
selected. An omitted profile flag preserves the prepared value, including
an adopted multi-card configuration or enabled vector. The GUI must show
that value, not replace it with a form default. An expert may select the
ordered cards and explicit boundaries in the GUI.

This baseline's `ComputeDevice` has `kind` and `index`, with no UUID field:
row 43's stable device identities are not present here. The contract uses
node-local nonnegative ordinals, main first, with no duplicates. The
implementation must validate the selected cards on that node, handle
visibility remapping and name a missing or incompatible card instead of
silently choosing another. Use row 43's UUID mapping when it is available;
do not invent UUIDs or claim these ordinals are stable identities.

`Runtime.effectiveLaunch` is an optional, read-only `StrataEffectiveLaunch`.
It records the successfully spawned private launch configuration's
projection mode, resolved cards and split mode or boundaries. Each value
is required inside the record and has no default. A single card reports
`layerSplit: null`; unknown launch settings leave the record absent.
Stopped runtimes may retain a labelled last launch. This is not a claim
that inference succeeded or that an automatic split used particular
boundaries. Editing a profile or prepared file cannot rewrite the observed
record until another successful launch.

**Phase 2 protocol export.** Library now derives its run-operation intent
from the pinned generated `PreparationIntent`. Its boundary additionally
checks strict integer ordinals and duplicates, and validates enum defaults.
The router's actual FastAPI OpenAPI export supplies
`openapi/run-operations.json`, using the same router and app construction as
`scripts/run-operations-checks.py`; `scripts/run_protocol.py` defines the
consumer comparison. `scripts/vendor-platform.py --repo agent` and
`--repo library` regenerate the vendored copies and their integrity manifests.
No shared YAML contract, generated Python model or specs pin changed.

Local generation with the consumers' existing code generator succeeds for
common, agent and Library. It preserves GPU list order, but does not enforce
`uniqueItems` in the generated Pydantic validator. Enum defaults also arrive
as strings until validated. The adapter now validates duplicates and
normalizes defaults at its boundary instead of assuming code generation does
those checks. The contract script runs in the OpenAPI validation CI job.

Phase 2 now passes the projection, ordered cards and layer boundaries to
preparation and launch. Preparation checks the inventory while planning
and again before setup runs; launch checks it each time. Explicit boundaries
are checked against the model header, with this pin's 48-layer family as
the fallback. Setup's actual split and memory modes survive adoption;
an observed card or boundary fallback fails with the requested and produced
values. A projection fallback retains the actual mode and setup's warning.
The vector remains an installed engine asset and resolves on the launching
node, rather than travelling as another node's engine path.

Admission sums only the selected cards, subtracting each card's allowance
before combining expert capacity, and counts the host arena once. Unknown
card memory remains unknown and admits on faith. Several-card RAM-budget
models use upstream's downloaded-size-plus-24-GB rule. Known resident and
RAM-budget incompatibilities name the required new preparation.

The adapter's GUI schema exposes all three settings without replacing an
inherited prepared value with a form default. Its card editor uses the
shared ordered text-list control; digit rows resolve to integer ordinals.
The projection description begins with its answer changes and experimental
status and links the pinned upstream explanation. New preparations keep
projection off, automatic single-card selection and auto boundaries for an
explicit multi-card choice. Launch preserves omitted settings. The server's
`child_env` replaces native visibility with the ordered `gpu` selection;
effective reporting retains node inventory ordinals, not the remapped
native device numbers.

`Runtime.effectiveLaunch` snapshots the private configuration named by the
spawned argv, including the vector and sampling default together. The
supervisor records it only after process creation succeeds. Profile edits,
prepared-file edits, planning failures and failed process creation cannot
rewrite that snapshot. Tests use fake processes and a small stand-in setup
that replays the pinned output shapes; no engine or model was downloaded.
A live run remains for the owner of a machine with at least two suitable
GPUs: preparation and
launch, the actual split and projection state, peak RAM/VRAM, output changes
and throughput. No live result or default-port service start is part of this
builder's worktree validation.

Phase 2 validation (2026-10-22): the four changed agent test files pass
(187 passed, one platform skip), and Library's intent and exported-protocol
checks pass (26 passed). The whole Library suite passes (1,113 passed,
30 skipped). The whole agent suite has 2,943 passes, 19 skips and one
out-of-row failure: `test_apps.py`'s real-install test asks uv for a separate
managed Python, whose GitHub download is denied by this sandbox's network
policy. It cannot use the installed system interpreter because the install
explicitly requests `only-managed`. No product code or skip was changed for
that failure. A final regression also verifies upstream's null sampling
default: null is skipped, so it leaves a loaded projection on.

Both packages pass Ruff lint and formatting, Linux and native mypy, vendored
integrity and specs-ref checks. The real Library router's export matches
specs and both vendored snapshots through `run_protocol.verify_run_protocol`.
The focused specs contract/protocol checks pass (30 passed). An extra broad
`python -m pytest -q scripts` attempt cannot collect the repetition evaluator
because this three-repository workspace has no installed gateway package;
no specs script was changed. GitHub issue access is also denied by the
sandbox, so no issue assignment, label or completion comment was sent.

## Recommendation

Troy clarified the support bar on October 4: **Strata is experimental**, with
recognition, install/uninstall, start/stop, model switching and inference.
Follow the [experimental engine policy](experimental-engines.md). Full model
preparation, automatic tuning and comprehensive fit estimates are not gates
for this baseline. The badge remains after a successful hardware test; it
describes limited or evolving support.

Proceed with a thin adapter and a bounded compatibility measurement, then
complete the installation/removal recipe and model switching for the initial
Windows NVIDIA configuration. Strata fits Eugene's existing separation:
the agent starts and observes an engine; the inference driver speaks its
HTTP protocol. No gateway rewrite appears necessary.

First target: one NVIDIA GPU, text, Qwen3.8-Flash-Next GSQ-RCO IQ2_XS or
IQ3_XXS with MTP, a moderate context and one request at a time. A 12 GB or
larger GPU and 64 GB RAM are a useful initial reference configuration, not
a measured Eugene minimum. Keep images, AMD, Intel, older NVIDIA builds,
multi-GPU and batching outside the first acceptance claim. Linux can join
the measurement with an operator-installed engine; managed Linux acquisition
needs a separate source-build recipe. There is no native Mac backend in the
reviewed release. A Mac can still be a client of a Windows/Linux Eugene host.

One premise has changed: llama.cpp merged Flash-Next MTP support on October 1
in [PR #29761](https://github.com/ggml-org/llama.cpp/pull/29761), commit
`c061df19838ff60970faf54fd7e414953590125d`. Compare Strata with a build that
actually contains that change and has its draft model configured. Strata's
expert placement and prompt performance are still reasons to investigate it;
MTP is no longer exclusive at the source level.

## What upstream provides

- [v0.1.39](https://github.com/Niko1221/Strata/releases/tag/v0.1.39) provides
  Windows CUDA and HIP archives. The normal CUDA build requires NVIDIA driver
  580 or newer; a separate experimental CUDA 12 build targets older hardware
  and drivers. Linux uses a source build. Archive digests are available from
  GitHub's release API.
- The HTTP service is Python `serve/server.py`, which owns the native engine
  process. Launching `strata.exe` alone does not launch the HTTP service.
  The source bundle, Python environment, native engine and prepared model
  belong to one tested installation recipe.
- [API documentation](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/DETAILS.md#using-it)
  describes OpenAI chat, Anthropic messages, Responses, streaming, tools and
  cancellation. `/props` and `/v1/models` expose model information;
  `/v1/status` exposes effective concurrency. Cached prompt tokens are
  reported in OpenAI usage. These are promising interfaces, not proof that
  every client field has the same semantics.
- [Batching](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/BATCHING.md)
  is newly opt-in. Additional slots consume memory and can slow a small
  card. The engine may lower the requested slot count to what fits; Eugene
  must report the effective count, not the saved setting.
- The engine is MIT licensed. Bundled dependencies and models retain their
  own notices. The inspected ISTA-DASLab GGUF model card declares Apache 2.0.

## Integration work

| Area                      | Existing Eugene seam                                        | Work needed                                                                                                                                                                                                                                                                                                     |
| ------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Initial connection        | `inference-driver/.../providers.py`, `openai_compat_custom` | Measure against an existing Strata server. Eugene's address field takes the server origin, e.g. `http://127.0.0.1:8080`; the driver adds `/v1/...`.                                                                                                                                                             |
| Lifecycle                 | `agent/.../engines/base.py` and its adapter registry        | Add `StrataAdapter` and the shared `EngineKind` value. Start Python plus `serve/server.py --engine strata --config <owned-config> --host 127.0.0.1 --port <assigned-port>`. Own both parent and child lifecycle, logs and cleanup.                                                                              |
| Acquisition               | `agent/.../engines/acquisition.py`                          | Install a pinned source/server bundle, isolated Python dependencies and verified native archive. Retain an earlier working version for rollback. Do not run the interactive setup launcher on every runtime start.                                                                                              |
| Model preparation         | Library catalogue, downloads and profile lifecycle          | Initially accept an explicitly selected upstream-prepared configuration and check its required files. Later automate the related GGUF, tokenizer, pack, PLE, expert-profile and MTP artifacts with resumable progress and space reporting. Preserve original files.                                             |
| Model eligibility         | `ui/src/lib/engineCompat.ts`, `EngineDescriptor`            | The existing filter mostly joins by file format. Strata must not be offered for every GGUF: check supported architecture, quant and prepared artifacts on the agent as well as in the UI. Decide the shared eligibility representation before codegen.                                                          |
| Fit and admission         | `library/.../fit.py`, `agent/.../admission.py`              | Initially show fit as unestimated and use explicit saved settings plus upstream checks. Keep unknown memory out of automatic eviction decisions. Later account for resident experts, GPU cache, KV, MTP, scratch buffers and desktop reserve; the current layer-offload estimate is not evidence of Strata fit. |
| Protocol and capabilities | Existing OpenAI-compatible driver                           | Add only the Strata-specific capability/error handling demonstrated necessary by measurements. Report context, loaded state, reasoning, cache usage and effective request capacity honestly.                                                                                                                    |
| Profiles and UI           | Existing schema-driven settings                             | Keep the experimental badge visible for engine selection, runtimes and profiles. Initially expose a small set of verified options and the selected prepared configuration. A richer tuning page is optional.                                                                                                    |
| Model switching           | Existing runtime lifecycle and gateway admission            | Keep a saved configuration per prepared model; stop/drain the old runtime, start the selected one, and route only after readiness. Process restart is sufficient. A request for one model must never silently run on another.                                                                                   |
| Removal and recovery      | New offline uninstall and checkpoint inventory              | Track Eugene-owned software and generated assets. A borrowed Strata installation or external `Strata-data` folder is not Eugene-owned. Protect original GGUFs; show the size of optional generated/downloaded assets before deletion.                                                                           |

### Details that prevent a misleading integration

1. **Readiness is not HTTP 200.** At the pinned
   [server source](https://github.com/Niko1221/Strata/blob/v0.1.39/serve/server.py),
   `/health` returns 200 with a separate `loaded` boolean. Handle loading,
   unloaded and failed states explicitly. Choose one owner of idle unloading;
   for a supervised first version, use Eugene's existing runtime lifecycle.
2. **Do not reuse llama.cpp slot semantics.** Strata's `/slots` compatibility
   response still constructs one slot in this source, while `/v1/status`
   reports effective engine batching. Do not enable llama.cpp `id_slot`
   pinning or derive a shared KV pool from that response. Begin with one
   admitted request and bounded waiting, then measure batching separately.
3. **Tool support needs field-level checks.** Neither
   [the chat translator](https://github.com/Niko1221/Strata/blob/v0.1.39/serve/frontend.py)
   nor the reviewed chat handler reads `tool_choice`. This source-level
   finding needs a live regression: `none`, `required` and a named tool must
   either behave correctly or be refused explicitly by Eugene. Do not label
   all tool-choice modes supported merely because ordinary tools work.
   `/v1/status` describes structured output as prompt-and-validate, not
   constrained decoding; the chat handler refuses structured output together
   with tools. Do not reuse a forced-tool repair that assumes those combine.
4. **Disk and RAM sizes differ.** Live Hub metadata lists IQ2_XS shards of
   39,225,954,592 and 28,800,138,432 bytes: about 68 GB downloaded before MTP
   and preparation. The second shard contains the large lookup table; it is
   not simply another GPU weight allocation. Upstream's
   [installation details](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/DETAILS.md)
   describe additional MTP and pack space. Calculate the actual recipe's peak
   disk use rather than advertising one universal requirement.
5. **Preparation is versioned data.** Upstream's
   [MTP fetcher](https://github.com/Niko1221/Strata/blob/v0.1.39/tools/mtp_fetch.py)
   fetches selected tensors from a pinned original checkpoint and verifies
   hashes. Use the matching upstream preparation tools and record their
   revision. Do not silently substitute a different model revision or present
   incomplete preparation as a runnable model.

## Upstream reports to exercise, not assume reproduced

Read October 4, including maintainer replies where present:

| Report                                                                                  | Relevance and current evidence                                                                                                                                                                                                                           |
| --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [#481: Windows long-stream hang](https://github.com/Niko1221/Strata/issues/481)         | Reported on 0.1.34. The maintainer added a silence/stop watchdog in 0.1.37; the reporter had not reproduced the freeze after moving to 0.1.38. Root cause remains open. Test long streams, cancellation and restart on our pinned version.               |
| [#606: persistent repeated-token output](https://github.com/Niko1221/Strata/issues/606) | v0.1.39 adds finite-value clamping and a repeated-token cutoff. This is a mitigation to verify, not a basis for claiming the latest version still has the original reproduction. A healthy process alone did not establish healthy output in the report. |
| [#528: restored conversation slowdown](https://github.com/Niko1221/Strata/issues/528)   | Reported on Windows 0.1.36; the maintainer could not reproduce on the current engine and supplied a benchmark. Keep optional RAM conversation snapshots out of the initial preset; measure normal prefix reuse and interleaved chats.                    |
| [#754: tools emitted as thinking](https://github.com/Niko1221/Strata/issues/754)        | Reported through Strata's Anthropic interface on 0.1.38. Eugene would use its own client interfaces and Strata's OpenAI backend path; test that path, since the report alone proves neither success nor failure there.                                   |
| [#765: large-context memory budgeting](https://github.com/Niko1221/Strata/issues/765)   | A 524K-context report describes competing KV, expert and prefill allocations. Keep extended contexts out of the first preset and measure peak allocations at the selected context.                                                                       |
| [#771: Linux startup stalls](https://github.com/Niko1221/Strata/issues/771)             | New 0.1.39 report under RAM pressure, implicating transparent huge-page compaction. Relevant to Linux acceptance and available-memory checks; not a Windows blocker.                                                                                     |

These warrant an experimental integration and a limited support claim. They
do not require Eugene's unrelated feature backlog to be completed first, nor
do they justify treating every open upstream report as an unconditional stop.

## Proposed sequence and acceptance

1. **Basic experimental adapter:** connect a pinned Strata using prepared
   model files in a disposable Eugene environment. Prove recognition,
   start/stop, correct model identity and text inference through the gateway.
   Check streaming/cancellation, readiness, failed start and context errors.
   Record which combinations work; retain the experimental label.
2. **Install, uninstall and switch:** install the engine/server into owned
   storage; exercise interruption/retry and removal that keeps original
   model files. Switch between two compatible prepared configurations and
   back, including active requests and a failed second load. Show effective
   settings and unknown fit honestly. Full automatic preparation is a later
   convenience, not a requirement for selecting prepared models.
3. **Capability checks:** tools and forced-tool modes, reasoning, cache
   reporting, client-specific workflows and concurrency are separately
   measured. Refuse unsupported requests explicitly; a missing optional
   feature does not block basic text inference. A complete coding-client
   workflow must not be advertised before its requirements pass.
4. **Performance and usability:** on the same hardware and quant, measure
   cold/warm start, time to first token, prompt throughput, decode throughput,
   peak RAM/VRAM, cache reuse and answer/tool correctness. Compare Strata MTP
   on/off and current llama.cpp MTP on/off with recorded settings. Check a
   person can install, select a prepared model, run, switch, stop and remove
   the engine. Comparative speed wins are not an admission gate.
5. **Expand only after evidence:** Linux managed builds, AMD, images,
   multi-GPU and batching each need their own acceptance. A successful NVIDIA
   text run cannot establish those combinations.

Release the experimental baseline for combinations that pass basic
recognition, install/removal, start/stop, switching and inference. If only the
external connection passes, describe that limited connection accurately;
it does not complete the requested baseline. Improved fit, model preparation
and optional capabilities can follow without delaying basic support. Use
disposable installations and isolated ports for acceptance; stopping the live
Eugene install is not part of this investigation. No release is authorized by
this design alone.
