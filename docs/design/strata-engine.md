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

| Area | Existing Eugene seam | Work needed |
| --- | --- | --- |
| Initial connection | `inference-driver/.../providers.py`, `openai_compat_custom` | Measure against an existing Strata server. Eugene's address field takes the server origin, e.g. `http://127.0.0.1:8080`; the driver adds `/v1/...`. |
| Lifecycle | `agent/.../engines/base.py` and its adapter registry | Add `StrataAdapter` and the shared `EngineKind` value. Start Python plus `serve/server.py --engine strata --config <owned-config> --host 127.0.0.1 --port <assigned-port>`. Own both parent and child lifecycle, logs and cleanup. |
| Acquisition | `agent/.../engines/acquisition.py` | Install a pinned source/server bundle, isolated Python dependencies and verified native archive. Retain an earlier working version for rollback. Do not run the interactive setup launcher on every runtime start. |
| Model preparation | Library catalogue, downloads and profile lifecycle | Initially accept an explicitly selected upstream-prepared configuration and check its required files. Later automate the related GGUF, tokenizer, pack, PLE, expert-profile and MTP artifacts with resumable progress and space reporting. Preserve original files. |
| Model eligibility | `ui/src/lib/engineCompat.ts`, `EngineDescriptor` | The existing filter mostly joins by file format. Strata must not be offered for every GGUF: check supported architecture, quant and prepared artifacts on the agent as well as in the UI. Decide the shared eligibility representation before codegen. |
| Fit and admission | `library/.../fit.py`, `agent/.../admission.py` | Initially show fit as unestimated and use explicit saved settings plus upstream checks. Keep unknown memory out of automatic eviction decisions. Later account for resident experts, GPU cache, KV, MTP, scratch buffers and desktop reserve; the current layer-offload estimate is not evidence of Strata fit. |
| Protocol and capabilities | Existing OpenAI-compatible driver | Add only the Strata-specific capability/error handling demonstrated necessary by measurements. Report context, loaded state, reasoning, cache usage and effective request capacity honestly. |
| Profiles and UI | Existing schema-driven settings | Keep the experimental badge visible for engine selection, runtimes and profiles. Initially expose a small set of verified options and the selected prepared configuration. A richer tuning page is optional. |
| Model switching | Existing runtime lifecycle and gateway admission | Keep a saved configuration per prepared model; stop/drain the old runtime, start the selected one, and route only after readiness. Process restart is sufficient. A request for one model must never silently run on another. |
| Removal and recovery | New offline uninstall and checkpoint inventory | Track Eugene-owned software and generated assets. A borrowed Strata installation or external `Strata-data` folder is not Eugene-owned. Protect original GGUFs; show the size of optional generated/downloaded assets before deletion. |

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

| Report | Relevance and current evidence |
| --- | --- |
| [#481: Windows long-stream hang](https://github.com/Niko1221/Strata/issues/481) | Reported on 0.1.34. The maintainer added a silence/stop watchdog in 0.1.37; the reporter had not reproduced the freeze after moving to 0.1.38. Root cause remains open. Test long streams, cancellation and restart on our pinned version. |
| [#606: persistent repeated-token output](https://github.com/Niko1221/Strata/issues/606) | v0.1.39 adds finite-value clamping and a repeated-token cutoff. This is a mitigation to verify, not a basis for claiming the latest version still has the original reproduction. A healthy process alone did not establish healthy output in the report. |
| [#528: restored conversation slowdown](https://github.com/Niko1221/Strata/issues/528) | Reported on Windows 0.1.36; the maintainer could not reproduce on the current engine and supplied a benchmark. Keep optional RAM conversation snapshots out of the initial preset; measure normal prefix reuse and interleaved chats. |
| [#754: tools emitted as thinking](https://github.com/Niko1221/Strata/issues/754) | Reported through Strata's Anthropic interface on 0.1.38. Eugene would use its own client interfaces and Strata's OpenAI backend path; test that path, since the report alone proves neither success nor failure there. |
| [#765: large-context memory budgeting](https://github.com/Niko1221/Strata/issues/765) | A 524K-context report describes competing KV, expert and prefill allocations. Keep extended contexts out of the first preset and measure peak allocations at the selected context. |
| [#771: Linux startup stalls](https://github.com/Niko1221/Strata/issues/771) | New 0.1.39 report under RAM pressure, implicating transparent huge-page compaction. Relevant to Linux acceptance and available-memory checks; not a Windows blocker. |

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
