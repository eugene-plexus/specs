# Experimental engines

**Product direction accepted from Troy, 2026-10-04. First Strata implementation
is included in Edge; [usage](../deployment/experimental-engines.md) and
[verification](../acceptance/strata-engine-run.md). Real-model validation remains.**
Weekend tinkerers will try specialized engines for speed even when those
engines support few models, devices or API features. Eugene should make these
experiments manageable without requiring the integration depth of llama.cpp.
Strata is the first candidate. NInfer and imp are examples of the same need;
each still needs its own adapter and capability checks.

Troy's requested baseline includes **recognition, installation, removal,
start/stop, model switching and inference**. Automatic tuning, comprehensive
fit estimates and complete client compatibility are improvements beyond that
baseline. The direction below covers future adapters too; NInfer and imp are
not implemented. Strata's initial Edge implementation is documented above.

## What Experimental means

Reuse `EngineDescriptor.experimental`, with the meaning **limited or evolving
Eugene support**. A successful hardware run alone does not remove the label.
Promotion is a deliberate support decision based on the integration's scope
and evidence. Strata enters with `experimental: true` and retains that label
when its basic lifecycle works.

Show the label when selecting an engine and on its installed entry, runtime
and profile. Show a short description of supported hardware, models and
important missing features nearby. Proposed copy:

> Experimental — basic engine management and inference. Supported models,
> hardware and features vary; see this engine's limits.

Availability, evidence and support maturity are separate facts: installed
does not mean tested here; tested does not mean fully supported. Display
known capabilities, unavailable features and unmeasured features accurately.
Allow a person to choose an experimental engine on suitable hardware without
repeated acknowledgement dialogs. Do not automatically switch their selected
engine or replace the default recommendation with an experiment.

The first implementation updates the API description, adapter comment and UI
tooltip together, replacing the previous definition of experimental as
unproved on physical hardware. The existing boolean is sufficient for this
decision; there is no need to invent a hierarchy of support labels first.

## Baseline experience

| Action | Experimental support must provide | What can remain limited |
| --- | --- | --- |
| Recognize | Engine name, upstream/fork, version where detectable, local availability, hardware requirements and experimental label. Validate an explicitly supplied install path as well as known locations. | Exhaustive detection of third-party layouts or every fork. An OpenAI-shaped response alone does not identify an engine. |
| Install | On a supported platform, an actionable install recipe run as a progress-reporting job, with cancellation, logs, a recorded version and a usable final installation. | One-click provisioning of every compiler/toolkit, every OS and every GPU. Report unmet prerequisites before starting a large operation. |
| Start/stop | Launch a saved model configuration, determine actual readiness, capture useful errors and stop the owned process tree or container. | Automatic tuning, every engine flag, an upstream hot-load API. |
| Switch model | Select another prepared, compatible model/configuration, unload the current one and load the selected one. Keep both saved choices. | In-process hot swapping, instant switches, cache preservation, automatic conversion between formats. |
| Infer | Route basic text inference through Eugene's gateway with accurate model identity and errors. Support streaming and cancellation where verified. | Tools, forced tools, images, JSON constraints, reasoning controls and batching are separate capabilities, not prerequisites for text support. |
| Uninstall | Stop affected owned runtimes and remove Eugene-installed engine software and private dependencies, with an accurate result. Keep original model files by default. | Removal of a user-owned installation or shared drivers, compilers and container services. |

An address-only connection remains useful, but only offers inference. A
user-owned engine can be adopted for start/stop and model switching without
becoming Eugene-owned software. Show **Remove from Eugene** for that case,
not an Uninstall button that claims to delete it. These partial paths must be
named honestly and do not substitute for the requested install/uninstall
support on each engine's initial supported platform.

## Thin adapters and installation recipes

Reuse the existing adapter/supervisor/driver split. Share process lifecycle,
ports, jobs, logs and HTTP handling. An engine-specific adapter supplies:

- identity and version probing;
- supported platform and known model/configuration restrictions;
- a reviewed installation recipe, and an inventory of what that recipe owns;
- launch arguments, environment, working directory and configuration rendering;
- readiness interpretation and the inference protocol;
- known capability limits, plus any bounded cancellation/recovery behavior.

A shared OpenAI-compatible driver should do most protocol work. Add an
engine-specific override only when its observed behavior requires one.
Existing adapters remain the boundary for launching programs: a downloaded
model's metadata must not become an executable installation or shell recipe.
The first slice can use explicit adapters and the existing closed engine enum.
A dynamically installed plugin system is not a prerequisite.

Acquisition can use a release archive, a private Python environment, a pinned
source build or a pinned container image. Each recipe records provenance,
version/commit/digest, paths and ownership. Build in a staging location and
publish the installation only after verification. A cancelled/failed build
must not replace a working one; retry should reuse verified downloads where
possible. Shared OS prerequisites remain separately identified.

For containers, remove the dedicated container and Eugene-owned writable
state. Retain shared images/layers when other consumers reference them; do
not treat downloading an image as exclusive ownership of Docker's cache.

Uninstall has its own POST operation in the first implementation. The engine
install-job DELETE still only cancels a download. The existing managed
build inventory can ground removal, but removal must also handle private
Python dependencies, generated launch files and any container resources.
Resolve every deletion target under its recorded owned root, preserve
external links/model folders and report leftovers. Installation removal must
not trigger automatic reinstall by a saved runtime's restart policy.

## Switching models

Use an explicit transition, even when an engine only chooses a model at
startup: **ready A -> waiting/stopping A -> loading B -> ready B**.

1. Check B's files, required companion artifacts and known compatibility
   before disrupting A. Keep each model's profile and public identity separate;
   a request naming A must never silently receive B's output.
2. Serialize conflicting switches on the same engine/resource allocation.
   Stop admitting work to A. Reuse Eugene's existing active-request handling:
   show ongoing work and offer waiting or explicit cancellation; do not kill
   an unrelated active request as a hidden consequence of choosing B.
3. Stop the owned runtime and wait for its processes/device allocations to
   release before launching B. Use the engine's hot-load API only if its
   lifecycle has been verified; process restart is sufficient for the baseline.
4. Route to B only once its adapter confirms readiness. Show loading progress
   or logs. On failure, preserve both configurations and offer starting A
   again; do not report B as running or silently replay a partly answered turn.

Eugene already has runtime stop/start, `startOnDemand`, `idleUnloadSeconds`
and gateway admission. Reuse those mechanisms. User-requested switching with
unknown fit can work from saved settings and upstream checks, with **Fit not
estimated** shown. Automatic memory-driven eviction remains conditional on
adequate memory/capacity information; an unknown estimate is not zero cost.

Prepared model paths must remain usable when the library cannot parse their
format. For example, a `.ninfer` artifact needs a selectable engine-native
path/configuration; it does not need a full converter or tensor parser before
Eugene can supervise it. Inspect the existing runtime, profile and library
validation together rather than renaming that artifact to GGUF or inventing
fit metadata. Switching selects an engine-compatible prepared artifact; it
does not convert a llama.cpp model into a NInfer model automatically.

## Initial candidates

Primary sources inspected October 4; these establish integration candidates,
not Eugene acceptance or measured performance:

| Engine | Observed upstream interface | Initial recipe/switching approach |
| --- | --- | --- |
| [Strata v0.1.39](strata-engine.md) | Python HTTP server supervising a native engine; GGUF plus prepared pack and MTP artifacts. | Windows NVIDIA archive plus isolated server environment. Keep a configuration per model; stop/start the server and child. Automated model preparation can follow basic management of prepared models. |
| [NInfer](https://github.com/Neroued/ninfer/blob/d44ab58408aa389728cd8b1ee50179527e1f3e0d/README.md) | `ninfer-serve`, a v3 `.ninfer` artifact, OpenAI/Anthropic HTTP and `/health`. Upstream targets Linux and RTX 5090; other GPU/Windows projects are distinct forks. | Pinned source-build recipe with prerequisites, or adopt a supplied binary. Switch by relaunching with another artifact. Record a fork explicitly rather than inferring support from the name NInfer. |
| [imp](https://github.com/kekzl/imp/blob/d401d3e8f447ed4570d81668dce4c1c5fdbaa83f/README.md) | OpenAI/Anthropic HTTP, model selected with `--model`; upstream offers a GPU container on Linux/WSL2 for its specialized NVIDIA target. | Pin the upstream image by digest; own the container while mounting models separately. Recreate with the selected prepared model as the baseline switch. Native source builds and upstream administrative APIs are optional later recipes. |

The NInfer and imp entries are source/document review only. No engine was
installed or benchmarked for this decision. Narrow upstream requirements must
remain visible instead of being generalized to all NVIDIA cards or Windows.

## Acceptance and order

Strata is the first application of this policy. The implementation order is:

1. Correct experimental metadata/copy, implement its thin adapter and prove
   basic inference with a prepared model.
2. Add the installation recipe and explicit uninstall; prove interruption,
   retry and removal preserve borrowed software and original models.
3. Exercise A -> B -> A switching, active requests, failed B startup and
   process/memory release. Reuse the shared lifecycle for later adapters.
4. Measure any extra capability before advertising it. Add NInfer and imp
   through that same baseline, recording the exact platform and upstream fork.

Use fixture tests for lifecycle and error cases and record the real platform,
engine version and model combination used for end-to-end evidence. A
successful run does not automatically promote the engine out of experimental.
Unknown hardware combinations remain explicitly unverified. Comparative
tok/s wins, automatic fit, model conversion, media/tool parity and a complete
platform matrix are not gates for the baseline. Engine installation/removal
and switching are part of that baseline, not indefinite follow-ups.

This design does not publish a release, install tools/models on the current
machine or stop the live Eugene service. It records the requested support
scope; implementation and acceptance results belong in subsequent changes.
