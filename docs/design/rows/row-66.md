# Row 66: experimental engines: NInfer, imp, TensorSharp

Lane ENG. Low risk. Sources: ENG-X and A8-NEXT;
`experimental-engines.md` (the pattern: recognize, install, start and
stop, switch model, infer, uninstall; a thin adapter on the closed engine
enum, no plugin system; NInfer and imp reviewed from source only),
`docs/deployment/experimental-engines.md` ("NInfer and imp remain future
adapters"), agent `engines/strata.py` (the experimental adapter pattern),
`docs/history/audience-roadmap.md` (TensorSharp, named by the setups pass,
not described).

## 1. What it delivers

Three more experimental engines, each wrapped the way Strata is, labelled
experimental, and never chosen by default:

- **66a NInfer:** `ninfer-serve` (OpenAI and Anthropic HTTP, `/health`),
  `.ninfer` v3 model artifacts, Linux, NVIDIA. Install from a pinned
  source build, or adopt a binary the owner supplies.
- **66b imp:** OpenAI and Anthropic HTTP, model set by `--model`, shipped
  as a Linux/WSL2 NVIDIA container: pulled by digest and run with row
  42's container runtime code.
- **66c TensorSharp: research first.** Nothing in the repo describes it.
  Step 1 reads upstream (what it serves, on which platforms, what models
  it takes) and writes it into `experimental-engines.md`; it is wrapped
  only if it has an HTTP server Eugene can drive. Otherwise the doc says
  why not and the part ends there.

## 2. Design

Per engine, as `experimental-engines.md` lays out: an `EngineKind` value,
an adapter (`engines/<name>.py`) with its GUI schema, install policy
(source build, supplied binary, or container), health and model switch
(stop then start), the Library's "which engines take this model"
(`accepts`) for its artifact format, and the deployment doc's section.
Each pins its upstream version.

## 3. Repositories

agent (adapters), specs (`EngineKind` in the contract, docs, acceptance),
library (artifact recognition for `.ninfer`), ui (engine pages).

## 4. Tests that fail before

Per adapter: argv and environment from a profile, health parsing, a
refused setting naming itself, and the install plan (a stub upstream).

## 5. Acceptance

Unit and planning tests in CI with stub binaries and a stub container. A
real run needs each engine's hardware (an NVIDIA Linux box); not a
roadmap item (Troy, 2026-10-21).

## 6. Size and risks

M each (66c may end at its research step). Risk: young upstreams; each
adapter pins a version and says what was read there.

**Calls:** none.
