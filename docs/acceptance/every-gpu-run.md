# Every GPU the operating system can see: the run

**2026-09-27. `scripts/every-gpu-acceptance.sh`: 19 PASS live, zero failures,
first execution.** It was then run twice more with a defect put back, and failed
both times for the defect's own reason (§4). Sabotage passes: agent **29 of 29
caught** (28 scripted, one by hand), library **6 of 6**, UI **9 of 9**.

Repos:

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `e7e2601` | the contract |
| `agent` | `5b6de3b` | detection, the build choice, the device list, admission |
| `library` | `6525f0e` | hardware reading, the fit routes |
| `ui` | `a52d85b`, dist `726bb28` | the device copy, the other builds |
| `control`, `gateway`, `inference-driver` | `c09a409`, `6bf371a`, `b952629` | regenerated only |

Both installers pin all six. **`scripts/install-acceptance.sh EP_MODE=posix`
re-ran green at the new pins: 16 checks, a real install from nothing in WSL2.**
That also exercised `gpu_probe` on Linux, where there is no DRM device to read.

---

## 0. The report, and what it turned out to be

An Intel Arc mini PC (a tester's, on bare metal) installed alpha.3. Its Inference
page read **"no GPU · 26.1 GiB host memory free"**. The tester bought the machine
for its Arc.

The cause was the half of R2.3 that was never built. The product has **two**
detectors:

- The **engine picker** (`host.py`). R2.3 taught it to read
  `Win32_VideoController` and give an Intel or AMD card the Vulkan build.
- The **device list** (`devices.py` in the agent, `hardware.py` in the library).
  This decides every fit, every admission, the starter pick and the context a
  new profile starts at. It asked only `nvidia-smi`, `rocm-smi` and `xpu-smi`,
  and a Windows machine with an Arc or a Radeon has none of them unless its
  owner installed an SDK.

So the tester's machine ran the Vulkan build on its Arc, and every number on
every screen was scored against system RAM. R2.3's own evidence was simulated,
which is why nobody saw this.

The same read found four more machines the product left out.

| Machine | alpha.3 | now |
| --- | --- | --- |
| Windows + Intel Arc | Vulkan build, "no GPU", fit against RAM | the Arc listed, with its memory |
| Windows + AMD Radeon | the same | the same fix |
| Windows on ARM (Snapdragon X) | asked for `win-vulkan-arm64`, which upstream does not publish: the **install failed** | `win-cpu-arm64`, and a note naming the Adreno build |
| Linux + AMD, no ROCm | the CPU build, with `ubuntu-vulkan-x64` published | `ubuntu-vulkan-*` |
| Linux + any Intel graphics | `ubuntu-sycl-fp16-x64`, chosen because the `i915` driver directory exists (so every Intel laptop); it needs a oneAPI runtime such a machine rarely has | Vulkan; SYCL only when `sycl-ls` sees a GPU |
| NVIDIA GB10 (DGX Spark) | `nvidia-smi` prints `[N/A]` for memory, so the row was "could not parse" and the machine read "no GPU" | a CUDA device that computes out of host memory |
| Windows + oneAPI | the CPU build (the branch was missing) | `win-sycl-x64` |

The last row had the same cause as Snapdragon. A comment in the code said
`win-sycl-x64` "appears nowhere", and nobody re-read a release after upstream
started publishing it.

---

## 1. The mechanism: ask the operating system

`gpu_probe` is one module, stdlib only. The agent and the library each keep a
byte-identical copy, because components share schemas, not code.

- **Windows.** DXCore lists the hardware adapters (Windows 10 version 2004 and
  later). For each it gives the vendor, whether the adapter is integrated, its
  dedicated memory and its shared allowance. The **`GPU Adapter Memory`
  performance counters** (PDH) give what every process on the machine is
  using, keyed by adapter LUID. DXCore's own memory budget reports the calling
  process only, so it cannot say what other programs hold.
- **Linux.** sysfs, `/sys/class/drm/card*/device`, with amdgpu's
  `mem_info_vram_*` and `mem_info_gtt_*`. **Unverified on hardware**: WSL2
  exposes no DRM devices. An Intel card's size on Linux is reported as unknown,
  so its verdict is `unknown` and not a guess.

`gpu_probe.family` is **the one decision** both detectors make. It returns the
build, the adapters that build computes on, and a note for each GPU left out:

- every discrete GPU, or the first integrated one when there is no card, which
  is llama.cpp's own default (§2);
- ROCm only for an AMD adapter, SYCL only for an Intel one that oneAPI sees;
- no Vulkan build on Windows on ARM, and no Vulkan without a loader, each with a
  sentence naming what to install or choose.

A GPU that computes out of host RAM is marked `sharedMemory`: an integrated GPU,
Apple silicon, or a GB10. Its total is the carve-out plus the shared allowance.
Its free memory is what is left of the allowance, capped by the RAM actually
available.

---

## 2. Measured on this box

This box has an **RTX 5090 beside an AMD integrated Radeon**. That makes it the
hard case: the Radeon's shared allowance is larger than the card.

| | DXCore + PDH | `nvidia-smi` | Vulkan (`--list-devices`) |
| --- | --- | --- | --- |
| RTX 5090 total | 32,187 MiB | 32,607 MiB | **32,187 MiB** |
| RTX 5090 free | 29,978 MiB | 29,996 MiB | 31,419 MiB (this process's budget) |
| Radeon, integrated | 2,022 MiB carve-out + 76,640 MiB shared = 78,662 MiB | — | 78,688 MiB |

Free memory from DXCore and PDH agreed with `nvidia-smi` to **18 MiB**. The
probe took 87 ms the first time (loading `dxcore.dll` and `pdh.dll`) and 1.4 ms
after that.

**What llama.cpp's Vulkan build actually uses**, read off its own log with
nothing pinned: `using device Vulkan0 (NVIDIA GeForce RTX 5090)`. It lists the
Radeon and does not load onto it. `vulkan_selection` mirrors that rule. Had the
device list reported every adapter, the Radeon's 77 GiB would have become "the
largest card" in the UI's budget, for a build that never touches it.

**Real inference on a non-NVIDIA GPU**, the project's first: upstream's
`win-vulkan-x64` b11211 with `--device Vulkan1` put a 0.6B Q4_K_M model onto the
integrated Radeon. It offloaded 29 of 29 layers and decoded at **44.9
tokens/s**, and it answered.

---

## 3. The live run

`scripts/every-gpu-acceptance.sh` starts a throwaway agent and library on ports
+100, with every ambient `EUGENE_PLEXUS_*` variable cleared. It runs once with
`nvidia-smi` on PATH, then with every directory holding it removed. Removing the
tool turns this box into what an Arc or Radeon owner has: a Windows machine no
vendor tool answers on.

| # | Check | Result |
| --- | --- | --- |
| 1 | with `nvidia-smi` | devices `cuda:NVIDIA GeForce RTX 5090`, no Radeon |
| 2 | without it | `vulkan:NVIDIA GeForce RTX 5090`. Its total is DXCore's to the byte; its free figure was read from the counters inside the agent's worker thread; it is not marked shared |
| 3 | the build | `win-vulkan-x64`. The other builds, off the real b11211 release: `win-cpu-x64`, `win-cuda-12.4-x64`, `win-cuda-13.4-x64`, `win-openvino-2026.4-x64`, `win-rocm-10.0-x64`, `win-sycl-x64`, `win-vulkan-x64`, and no build for another OS |
| 4 | `{"variant":"ubuntu-vulkan-x64"}` | 422, naming what this machine can have |
| 5 | the agent installs the default | `win-vulkan-x64` downloaded, verified and unpacked. The installed binary's `--list-devices` names the card |
| 6 | the library child, spawned by that agent | `gpus: NVIDIA GeForce RTX 5090`, not a shared pool, no "no accelerator" sentence |
| 7 | `GET /v1/catalogue/starter?…&unifiedMemory=true` | every verdict scored as one pool |
| 8 | teardown | no owned port still listening |

---

## 4. Proving the checks can fail

A first run that passes every check is exactly the case this project has learned
to distrust. The run was repeated twice, each time with a defect put back into
the running processes.

- **The original defect.** The agent's device list and the library's hardware
  reading were made to ask only vendor tools again. **6 failures**, and they
  are the tester's screen: no devices, no total, no free figure, `gpus ''`.
  The library said *"no accelerator was detected, by a vendor tool or by the
  operating system"*.
- **The integrated GPU let into the selection.** **3 failures**: devices
  `vulkan:AMD Radeon(TM) Graphics;vulkan:NVIDIA GeForce RTX 5090`, a total of
  82,483,144,294 bytes (the Radeon's), and `sharedMemory: True` on what was
  meant to be the card.

Each tree was restored from a copy and checked against its commit.

---

## 5. The other builds

`EngineAcquisition.alternatives` lists every build the release publishes for
this operating system and CPU, and `EngineInstallRequest.variant` installs one
of them. The Inference page shows the installed build beside its version and
offers the others, default first.

That is the expert's way past a default chosen for hardware nobody here has run:
SYCL on an Arc, the Adreno build on a Snapdragon, the CPU build to rule the card
out. A requested build this release lacks, when this machine could run it, is
looked for in older releases. One for another platform is refused at once, with
the list.

**The device list does not follow a chosen build.** It follows the default, so a
model is still scored against the card the default would use. The contract says
so. It is right for SYCL on the same Arc. It is wrong for the CPU build on a
machine with a card, where fit is still scored against the card.

---

## 6. Not done, named

- **An Intel Arc has not run this.** The tester's machine is the evidence owed.
  Whether it is an integrated Arc (`sharedMemory`) or a discrete one decides
  which half of the arithmetic it takes.
- **No discrete AMD card and no Intel GPU of any kind has computed here.** The
  one non-NVIDIA inference was on an integrated Radeon.
- **Linux is simulated** throughout: sysfs, the Vulkan loader check, the APU
  heuristic (VRAM under 2 GiB with a larger GTT), and the Intel integrated slot
  (`0000:00:02.0`).
- **GB10 and Snapdragon are written from documentation.**
- **SYCL, OpenVINO and the Adreno build** can be chosen, and none has been run.
- The two `gpu_probe` copies are identical by construction and checked by `cmp`
  when edited. No CI check enforces it, because neither repo's CI checks out the
  other.
