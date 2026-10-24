# Row 74: DeepInfer as an experimental engine

Lane ENG, last on the roadmap on purpose. Low risk. Sources: DI-C5 (Troy,
2026-10-21: "yes, at the end of the roadmap"), `deepinfer-lessons.md`
(DeepInfer has no HTTP server, the release is offline only; it runs one
model, V4.1-Flash; it needs SM100 or Ascend 950 on Linux, while this
machine's 5090 is SM120; it is built from source and configured through
about 60 environment variables; it is sized for clusters), row 66's
pattern for experimental engines.

## 1. What it delivers

DeepInfer wrapped as an experimental engine, as row 66's engines are,
**once upstream has an online server and runs on a consumer card**.

## 2. Design

- **Step 1, the gate:** read DeepInfer's upstream at its newest release:
  is there an HTTP server (OpenAI-compatible or otherwise), and which GPUs
  does it support? Record the answer in `deepinfer-lessons.md` with the
  date and commit.
- **If either is missing,** the row ends there: the doc says what is
  missing, issue #102 stays open with that note, and the check is repeated
  when the orchestrator reviews the roadmap's end (not before each
  release).
- **If both exist,** wrap it as row 66 does: an `EngineKind`, an adapter
  that maps its environment-variable configuration to a GUI schema (the
  common ones as settings, the rest as expert environment values), a
  source-build or container install pinned to a version, health and model
  switch, and its one supported model family in the Library's `accepts`.

## 3. Repositories

specs (the doc), then agent, library, ui if the gate passes.

## 4. Tests that fail before

Only if the gate passes: the adapter's environment and argv from a
profile, and health parsing against a stub.

## 5. Size and risks

S if the gate fails (a recorded check), M if it passes. Risk: an engine
sized for clusters may not fit a home machine; the Library's fit and the
engine's hardware check say so before a start.

**Calls:** none.
