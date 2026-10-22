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

## Row 68: DeepSeek V4.x Flash contract staging (2026-10-22)

**Phase 1 only.** The Row 68 design was read from the separate
`calls-1022c/specs/docs/design/rows/row-68.md` worktree. This row's specs
worktree does not yet contain that document. No engine, model, or hardware
run was performed for this work.

The existing contracts can describe the GGUF architecture, expert bytes,
embedded-template presence, engine eligibility, and an own-file `nextn`
prediction head. They cannot distinguish an available Eugene template from
the template actually in use. The `chatTemplate` boolean must continue to
mean that the file embeds a template, even when Eugene supplies one. This
requires an additive contract change before consumer code is regenerated:

- Library `GgufDetail.chatTemplateFallback` and
  `CataloguePreflight.chatTemplateFallback` reference `ChatTemplateFallback`.
  The optional, read-only observation names the reviewed template, its
  upstream source, and the engines whose adapters can apply it. Report it
  only after a header confirms a recognized variant and no embedded
  template. An unknown header or a filename is not enough evidence.
- Agent `Runtime.chatTemplate` references `RuntimeChatTemplate`. Its
  read-only observation gives the effective name, source, and SHA-256 of
  the exact template text reported by the engine. An optional id links to
  the Eugene fallback; an optional path names the launch-time file on
  that node. Match against captured launch-time contents before claiming
  an embedded, Eugene, or override source; otherwise report `engine`.
  Omit the observation while unconfirmed or stopped, and clear it before
  another start. Editing a saved setting or template file does not rewrite
  what the existing process is using.
- Neither field changes eligibility or blocks an untested engine. Fallback
  availability does not assert that hardware can load the model. A missing
  effective-template observation does not prevent inference.

The default is an explicit operator override, then the embedded template,
then a reviewed Eugene fallback for the recognized variant on an adapter
that supplies it, then the engine's own behaviour. Phase 2 exposes the
template-file override through the engine's existing GUI flag schema;
`RuntimeSpec.flags` already supports this and needs no new declaration
field. Existing SD1 drafting defaults remain unchanged: offer the own head
only when the tensor table proves it; do not enable MTP based on a name or
on `nextn_predict_layers` alone.

`openapi/run-operations.json` embeds both `GgufDetail` and `Runtime`. It was
not edited by hand. The owner must regenerate that embedded schema through
the normal consumer/export workflow after committing, pushing and pinning
these contracts. Pin and regenerate consumers before implementing Phase 2,
including the model and runtime UI types that will display the observations.

Source inspection found a usable starting point for the remaining fixtures:

- llama.cpp **b11719** already contains a
  [V4 Jinja template](https://github.com/ggml-org/llama.cpp/blob/b11719/models/templates/deepseek-ai-DeepSeek-V4.jinja)
  and [V3.2/V4 DSML format detection](https://github.com/ggml-org/llama.cpp/blob/b11719/common/chat.cpp).
- The agent's reviewed vLLM **v0.29.0** contains the
  [V4 DSML parser](https://github.com/vllm-project/vllm/blob/v0.29.0/vllm/parser/deepseek_v4.py).
  The old `tool_parsers/deepseekv4_tool_parser.py` path is absent at this
  tag; it is not evidence of missing parser support.
- DeepSeek publishes separate
  [V4](https://github.com/deepseek-ai/deepseek-recipe/blob/main/deepseek-recipe-encoding/src/v4/dsv4.rs)
  and [V4.1](https://github.com/deepseek-ai/deepseek-recipe/blob/main/deepseek-recipe-encoding/src/v4/dsv41.rs)
  format implementations. Review and pin the matching source before
  bundling a template or recording DSML samples. Do not assume one template
  covers every V4.x variant.

Phase 2 still owes failing-first GGUF architecture/cache/MoE fit tests,
with-head and stripped-head tests, template selection/override argv tests,
engine read-back and restart tests, model/runtime page coverage, and native
DSML streaming/non-streaming fixture tests. Add a family-scoped gateway
fallback only if those tests show a parser missing in a supported engine;
the source findings above do not establish live behaviour. All of these
checks must use fakes and recorded upstream examples here.

The owner alone runs live acceptance on borrowed/rented hardware with about
110 GB of model memory plus the context and engine overhead. Record the
exact model/quant, engine build, template digest, context, cache/offload and
draft settings. Verify gateway text, streaming/cancellation, tool arguments
and tool-result round trips, effective template reporting, fit versus peak
RAM/VRAM, and own-head drafting on/off with acceptance and timing results.
No model or engine download, engine start, or new performance claim is part
of this contract phase.
