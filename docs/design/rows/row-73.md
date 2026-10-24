# Row 73: Eugene installs and updates vLLM, as it does llama.cpp

Lane ENG, after rows 42 (vLLM's container) and 13 (checked engine
updates). **High risk** (it installs software). Sources: Troy, 2026-10-21
("supported like llama.cpp eventually"), M4's decision to drive vLLM and
not manage its environment (`m4-second-engine-vllm.md`), agent
`engines/vllm.py` (`install_policy = manual`, the `uv pip install` recipes
pinned at `RECIPE_VERSION`), `engines/acquisition.py` (two builds, checked
downloads).

## 1. What it delivers

- **One click installs vLLM on a Linux machine with a GPU.** Engines >
  vLLM > Install: Eugene makes a private Python environment, installs the
  vLLM version this release pins with the right PyTorch for the machine's
  GPU, and keeps it beside the previous one, as it keeps two llama.cpp
  builds.
- **Updates are checked before they are used** (row 13): a new vLLM is
  installed beside the old, started on a short check, and switched to only
  if it passes; otherwise the old stays and the page says why.
- **Each machine says how vLLM runs there:** "Installed by Eugene" (Linux),
  "Official container" (row 42; the only way on Windows), or "My own vLLM"
  (an expert's path, as today).

## 2. Design

### How it installs

- **uv, wrapped:** the agent fetches a pinned `uv` release (checksummed,
  like an engine build) and runs, in `engines/vllm/<version>/`:
  `uv venv --python 3.12` (uv's own standalone Python, with its headers),
  then `uv pip install vllm==<pinned> --torch-backend=auto`, which picks the
  PyTorch build for the driver's CUDA (or ROCm, from the ROCm index the
  current recipe uses). The pinned versions live in
  `release/manifest.json` (`vllmVersion`, `uvVersion`).
- **Recorded like a build:** `install.json` with the version, the torch
  build, the accelerator, the size and `installedAt`. The runtime's
  `binary` is the venv's `vllm`; everything after that is today's adapter.
- **Two kept:** current and previous (`acquisition.py`); "Keep the previous
  version" is on by default and says its size (vLLM with PyTorch and CUDA
  libraries is about 10 to 15 GB).
- **Progress and failures** come from uv's output: a missing wheel for the
  platform names it ("vLLM 0.12 has no wheel for aarch64 with CUDA 12.2;
  update the NVIDIA driver to 550 or newer, or use the container").

### What vLLM needs that Python cannot bring

- **A C compiler** (Triton and FlashInfer compile at first use; the
  adapter's exit explanations already name it). On a Linux system install
  the agent asks its root helper, the one that applies updates, to install
  the distribution's compiler package after the owner presses "Install
  what vLLM needs" (no terminal step). On a per-user install the page
  shows the one package to install, the only case left.
- **Shared memory and the driver** are checked before install: the page
  says what is missing.

### Updates (row 13)

A new pinned version arrives with an Eugene release. The agent installs it
beside the current one, runs row 13's check (start a runtime of the
owner's chosen vLLM model on the new build, a short prompt set, compare
with the old), and switches runtimes at their next restart only when it
passes. A failed check keeps the old version and shows the failure in the
engine's words.

### Which way runs where

| Machine | Default | Also offered |
|---|---|---|
| Linux, NVIDIA or AMD | Installed by Eugene | Official container (row 42), My own vLLM |
| Windows | Official container (Docker Desktop) | My own vLLM inside WSL (as today) |
| macOS | not offered (vLLM-Metal is not driven) | none |
| Eugene in a container | not offered (no compiler, no socket) | My own vLLM on another machine |

### Contract (`agent.yaml`)

The vLLM adapter's install policy becomes `managed` on Linux (it is
`manual` today); its `source` setting from row 42 gains `managed`;
`ManagedEngine` reports `version`, `previousVersion`, `torch` and size for
vLLM as for llama.cpp.

## 3. Repositories and files

specs (`agent.yaml`, `release/manifest.json`, `scripts/release-inputs.py`),
agent (`engines/vllm.py`, `engines/acquisition.py`, a `uv` wrapper beside
it, the root helper's package step), ui (the Engines page). Regenerate
agent and ui and diff.

## 4. Tests that fail before

- agent `test_vllm_install.py::test_install_runs_uv_with_the_pinned_versions`
  (a fake `uv` that records its arguments and writes a stub venv).
- agent `test_vllm_install.py::test_two_versions_are_kept_and_the_previous_is_removed_third`.
- agent `test_vllm_install.py::test_a_missing_wheel_names_the_platform_and_the_fix`.
- agent `test_engine_update.py::test_a_failed_check_keeps_the_old_vllm` (on
  row 13's check).
- specs `test_release_inputs.py::test_vllm_and_uv_are_pinned`.

## 5. Acceptance (CI, Linux, about 6 minutes)

`specs/scripts/row73-vllm-install-acceptance.py`: a real agent, a real `uv`,
and a local package index serving a small stand-in `vllm` package (a
console script that starts the fixture OpenAI server), so the run installs
for real without 10 GB of downloads:
1. Install: the venv exists, `install.json` records the versions, a runtime
   starts on it and the gateway routes a chat to it.
2. A second version installs beside it; row 13's check passes; runtimes
   move at restart; a third install removes the oldest.
3. A version whose check fails: the old stays, the reason is shown.

**Real vLLM on a GPU:** the orchestrator runs the managed install inside
WSL 2 on this machine's RTX 5090 (where the M4 run was made); it is not a
roadmap item otherwise.

**The reviewer should attack:** what the root helper's package step can be
made to install (only the fixed package name per distribution), the uv
download's checksum, a half-finished install picked as current, and disk
filling during install.

## 6. Do not change

- llama.cpp's acquisition (share the store, do not change its rules).
- Row 42's container path and row 13's check (call them).

## 7. Size and risks

L, about 3 days. One adversarial review. Risks:
- **Large and slow installs:** progress, size up front, and the previous
  version kept by choice.
- **A distribution package installed by the root helper:** one fixed name
  per distribution, after the owner's click, logged.
- **Driver and wheel mismatches** are vLLM's commonest failure; the check
  before install and the wheel message name the fix.
