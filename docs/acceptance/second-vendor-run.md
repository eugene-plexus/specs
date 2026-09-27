# A second vendor's card beside an NVIDIA one: the run

**2026-09-27. `scripts/second-vendor-acceptance.sh`: 17 PASS live, zero
failures, on the fifth execution.** The first four failed on a defect in the
script, not the product (§4). The run was then repeated with the agent's pin
safeguard removed, and it failed for exactly that reason. Sabotage passes:
agent **18 of 18 caught** (after one escape named a missing test), library
**1 of 1**, UI **4 of 4**.

Repos:

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `5cd6b3e` | the contract |
| `agent` | `2dcf645` | the combined build, the second card, card identity, pins, `devices` |
| `library` | `8a25e71` | the second card in its own hardware reading |
| `ui` | `d819d35`, dist `cce0eb1` | the second card summed; an issue when it sits idle |
| `control` | `cfd8138` | regenerated only |

Both installers pin all of them.

---

## 0. The mechanism, measured before anything was built

- **The Windows CUDA and Vulkan builds of one release share byte-identical
  core files.** `ggml-base.dll`, `ggml.dll`, `llama.dll`, `llama-server.exe`
  and every CPU variant match. The Vulkan build adds exactly one file,
  `ggml-vulkan.dll`, and each backend is a plug-in llama.cpp loads from its
  directory.
- **Copied into the CUDA build, it gives one process with both backends.**
  `--list-devices` shows CUDA0 (the 5090), Vulkan0 (the 5090 again) and
  Vulkan1 (the integrated Radeon).
- **llama.cpp uses a card once**: "skipping device Vulkan0 … already using
  device CUDA0 with the same id". It keeps an integrated GPU out while there
  is a discrete card.
- **A pin reaches its own backend only.** With `CUDA_VISIBLE_DEVICES=-1` the
  combined build loaded the model onto the same 5090 through Vulkan. So two
  replicas pinned to two cards would each also have taken every card through
  Vulkan. `GGML_VK_VISIBLE_DEVICES=` (empty) hides every Vulkan device and
  leaves CUDA as pinned.
- **The Linux builds cannot be combined safely.** They are compiled
  separately: even `libggml-base.so` differs between the CUDA and Vulkan
  tarballs of b11211. Adding one's backend to the other would be an ABI
  gamble, so the combined build is Windows only. On Linux a second vendor's
  card beside NVIDIA is named as unused, with that reason.

---

## 1. What was built

- **`+vulkan` variants** (`win-cuda-13.4-x64+vulkan`). It is the default when
  `gpu_probe.beside_nvidia` finds a discrete AMD or Intel card beside
  NVIDIA, and it is offered for every Windows CUDA build otherwise.
- **The install merges it.** It unpacks the Vulkan archive beside the build
  and compares every file both carry. If one differs, it refuses, naming the
  file; otherwise it copies in what the build lacks. `HostAccelerator`
  gains `secondary: vulkan`.
- **The device list names the second card** as a `vulkan` device. It no longer
  reads `rocm-smi` or `xpu-smi` beside `nvidia-smi`. A Linux machine with both
  listed a card the CUDA build cannot use, and a split would have counted it.
- **A llama.cpp split takes every card in the list, whatever its kind.** vLLM,
  which has no Vulkan backend, keeps to its own kind.
- **A card is its kind and its index.** CUDA 0 and Vulkan 0 are two cards to
  the reservation ledger, and a pin reaches its own kind only.
- **A pinned runtime on a combined build is given an empty
  `GGML_VK_VISIBLE_DEVICES`**, as an adapter default. The runtime's own `env`
  or `devices` still wins, and the injection is logged.
- **A `devices` flag** (llama.cpp's `--device`) is the expert's way to test an
  integrated GPU as overflow, which is not judged yet. A `CUDA<n>` name is
  measured. A Vulkan name cannot be matched to a card (Vulkan numbers every
  GPU, the NVIDIA ones included, in an order nothing here reads), so such a
  launch is admitted unmeasured rather than refused.
- **The UI** sums every card a node lists. It raises
  `engine-build-missing-backend` when a `vulkan` card is listed, the default
  build is `+vulkan`, and the installed one is not.

Three agent tests asserted the one-kind rule and are **amended**, not added
to. The UI's one-kind test is amended the same way.

---

## 2. The live run

This box has an RTX 5090 and an **integrated** Radeon, so the combined build
is not its default. The run installs it by hand, which is the expert's path.
Every runtime passes `-v` through `extraArgs`, with the throwaway agent's R7
launch boundary opened the way an operator would, so llama.cpp's own device
choices are in the log.

| # | Check | Result |
| --- | --- | --- |
| 1 | the default here | `win-cuda-13.4-x64`: an integrated GPU is not a second card; `win-cuda-13.4-x64+vulkan` offered |
| 2 | the agent installs the combined build | both backends in one directory, verified on the way in; lists `CUDA0`, `Vulkan0` (the 5090), `Vulkan1` (the Radeon) |
| 3 | unpinned | `using device CUDA0`; "skipping device Vulkan0 … same id"; the Radeon not used; it answers |
| 4 | `CUDA_VISIBLE_DEVICES=0` | the agent logs `GGML_VK_VISIBLE_DEVICES=` set; `using device CUDA0`; no Vulkan device named |
| 5 | `devices: CUDA0,Vulkan1`, `tensorSplit: 3,1` | admitted unmeasured; `using device CUDA0` and `using device Vulkan1 (AMD Radeon(TM) Graphics)`; it answers |
| 6 | teardown | no owned port still listening |

**With the pin safeguard removed**, check 4 failed twice: the injection was not
logged, and a Vulkan device appeared for the pinned runtime (the 5090 again).

---

## 3. What it does not prove

- **A discrete second card.** Nothing here has one. The default choosing
  `+vulkan`, that card joining the device list, and the split across two
  vendors' cards are unit-tested; the mechanism underneath (one process
  splitting across backends) was run live, with the Radeon standing in.
- **Speed.** Nothing is measured. The one measurement of integrated-GPU
  overflow on this rig is recorded in the two-card run as a data point, not a
  verdict.
- **Linux.** Deliberately not built, for the reason in §0.

---

## 4. The script's own defect, named because it cost four executions

`set -o pipefail`, and `printf "$LINES" | grep -q …`. `grep -q` exits at its
first match, `printf` then dies of SIGPIPE writing the rest of a megabyte of
`-v` output, and pipefail reports the pipeline as failed. So every device
check failed on a product doing exactly what it should: each time, the lines
were in the log.

Two wrong explanations were written into the script first: log positions (a
line count across two mirrored files), then output arriving late. The checks
use here-strings now, and the script's comment says what happened.

**It also meant the negated check had been unable to fail.** "No Vulkan device
named" is `grep … && bad || ok`, so with pipefail it read `ok` whatever the log
held. That is why the pin safeguard was removed and the run repeated, and it
failed.
