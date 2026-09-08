# M1 — Engine acquisition (design)

**Status:** design, 2026-09-08. Milestone **M1** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M0](../acceptance/m0-four-process-run.md), which is complete.

**What it is:** the control plane fetches, verifies and updates the engine
binary itself, so a fresh install can serve a model without the operator
first finding, downloading and unpacking a llama.cpp release by hand.

**Why now:** M0 works end to end and leaves exactly one manual step —
someone has to put `llama-server` on the machine. Closing it is what makes
first run one click, and it is the smallest increment that does.

Locked already (2026-09-08): *manage engine binaries; don't make the user
install llama.cpp first.* Engine releases become a **third managed
artifact** alongside models and configs.

---

## 1. What upstream actually ships

Checked against `ggml-org/llama.cpp` build **b10867**, 2026-09-08. Four
things about it shape the whole milestone, and three of them are traps.

### The release matrix

Assets are named
`llama-b<BUILD>-bin-<os>[-<accel>][-<version>]-<arch>.{zip,tar.gz}`.
Twenty-seven per release:

| OS | Accelerator variants published |
|---|---|
| `win` | `cpu`, `cuda-12.4`, `cuda-13.3`, `cuda-13.4` (arm64), `rocm-10.0`, `vulkan`, `sycl`, `openvino`, `opencl-adreno` (arm64) |
| `ubuntu` | *(plain = CPU)*, `rocm-10.0`, `vulkan`, `sycl-fp16`, `sycl-fp32`, `openvino` |
| `macos` | *(plain — Metal is built in)*, `x64` and `arm64` |
| `android` | `arm64` |

### Trap 1 — `releases/latest` is not a llama.cpp build

`GET /repos/ggml-org/llama.cpp/releases/latest` returns **`v0.4.0`**, a
tag with one asset that has nothing to do with the server binaries. The
real builds are `bNNNN` tags. **Resolve by listing releases and taking the
newest tag matching `^b\d+$`**, never by asking for "latest".

### Trap 2 — Windows + CUDA is a two-asset install

`llama-b10867-bin-win-cuda-13.3-x64.zip` (142 MB) does **not** contain the
CUDA runtime. It needs `cudart-llama-bin-win-cuda-13.3-x64.zip` (373 MB)
unpacked alongside it, and that asset's filename carries no build number
even though it lives under the same release tag. A one-asset installer
produces a binary that exits on launch complaining about `cudart64_13.dll`.

*(Confirmed against the hand-made install this project has been using: it
contains `cudart64_13.dll`, `cublas64_13.dll`, `cublasLt64_13.dll` — the
contents of that second zip.)*

### Trap 3 — there is no prebuilt Linux CUDA binary

Not "hard to find" — **not published**. Linux gets CPU, Vulkan, ROCm, SYCL
and OpenVINO. CUDA on Linux means building from source or a container.

This lands on the exact configuration the design doc calls the core
audience, and it is the one place the "never make the user install
llama.cpp" promise cannot be kept.

**Decision (Troy, 2026-09-08): refuse, and say why.** On Linux + NVIDIA we
do *not* auto-install anything. We detect the situation, name it, and point
at the source build or container.

Rejected: silently installing the Vulkan build. It runs on NVIDIA but is
materially slower at prompt processing, and this audience is precisely the
one that would notice a substitution nobody offered them and conclude the
product is slow. Handing someone a worse engine without their say-so is a
bad trade for a one-click install, and the manual path already works — M0's
acceptance run uses it.

### Trap 4 — no checksums are published, but the API has digests

There is no `.sha256` or `.sig` asset. There *is* a per-asset
`digest: "sha256:…"` field on the releases API response — the same call
that picks the asset. So verification costs one extra comparison and no
extra request. Use it; do not skip verification on the grounds that
upstream publishes no checksum file.

---

## 2. Selection

Detection produces `(os, arch, accelerator, accelerator_version)`, which
maps to exactly one asset or to a refusal.

| Detected | Asset |
|---|---|
| Windows x64 + NVIDIA | `win-cuda-<major.minor>-x64` + its `cudart-` zip |
| Windows x64 + AMD | `win-rocm-10.0-x64` |
| Windows x64, no GPU | `win-cpu-x64` |
| macOS arm64 / x64 | `macos-arm64` / `macos-x64` (Metal is in the plain build) |
| Linux x64 + AMD | `ubuntu-rocm-10.0-x64` |
| Linux x64 + Intel | `ubuntu-sycl-fp16-x64` |
| Linux x64, no GPU | `ubuntu-x64` |
| **Linux + NVIDIA** | **none — refuse with a reason** |

**CUDA version matching.** The driver reports a maximum supported CUDA
version (`nvidia-smi` → `CUDA UMD Version: 13.3` on this box). CUDA has
minor-version compatibility within a major, so the rule is: pick the
highest published `cuda-<major>.<minor>` whose **major** matches and whose
**minor** is ≤ the driver's. Never pick a higher major. When no published
CUDA variant satisfies that, fall back to `cpu` **with a stated reason**
rather than silently — a driver too old for any published build is a real
situation and the operator needs to be told to update it.

**Vulkan stays reachable, but only if asked for.** The selection rule never
returns it. An operator who explicitly wants it can still install one by
hand and point `binary` at it — the same escape hatch M0 already has. We do
not build a comparison screen for this; guidance UI is M3.

---

## 3. Where it goes

```
<data>/engines/llama.cpp/<build>/        e.g. ~/.eugene-plexus/engines/llama.cpp/b10867/
```

- **Versioned directories, never one "current" folder that gets
  overwritten.** An in-place overwrite while a runtime is running is how
  you corrupt a loaded engine. A new build lands beside the old one and
  the pointer moves after it verifies.
- The Windows CUDA runtime unpacks into the **same** directory as the
  binary. `working_directory()` already defaults to the binary's parent for
  exactly this reason (prebuilt releases ship their shared libraries
  alongside the executable).
- **Retention: current + previous.** Older builds are pruned on a
  successful install. Windows CUDA is ~500 MB unpacked per build; keeping
  every one is not viable, and keeping only the newest means a bad upgrade
  has no way back.
- Discovery precedence becomes **explicit `binary` > managed > PATH.** A
  managed install should beat a stray `llama-server` on PATH, because the
  operator asked us to manage it; an explicit `binary` still beats
  everything, unchanged from M0.

---

## 4. Updates

llama.cpp published **five builds on the day this was written**. Any design
that treats "a newer build exists" as an alert is broken on arrival.

- **Never auto-update.** An engine upgrade can change flag behaviour, and a
  working local setup silently changing underneath someone is the exact
  failure the project exists to avoid.
- **Do not show a build-count delta.** "You are 1,021 builds behind" is
  noise. Show the **age** of the installed build and the newest available
  one, and let the operator decide.
- **Check at most daily**, cached, and never on the request path. A
  failed check is invisible — it is not an error state.
- Update is an explicit action that installs a new versioned directory and
  moves the pointer. Runtimes pick it up on their next restart, not
  mid-flight.

---

## 5. Contract

New on the watchdog. `EngineDescriptor` gains two optional objects, so the
existing `GET /v1/engines` answer stays valid and the UI's engines panel
grows rather than being replaced.

```
EngineDescriptor
  + managed:     ManagedEngine?      what is installed, if anything
  + acquisition: EngineAcquisition?  what could be installed here

ManagedEngine       version, binaryPath, variant, installedAt, sizeBytes
EngineAcquisition   installable, variant?, reason?, detected{os,arch,accelerator,
                    acceleratorVersion}, latestVersion?, latestPublishedAt?,
                    checkedAt?
```

One install runs per engine at a time, so it is a singleton sub-resource
rather than a job collection:

```
POST   /v1/engines/{engine}/install   {version?}  -> 202 EngineInstall
GET    /v1/engines/{engine}/install               ->     EngineInstall
DELETE /v1/engines/{engine}/install               ->     cancel in flight

EngineInstall  state: resolving|downloading|verifying|extracting|done|failed|cancelled
               version, bytesDownloaded, bytesTotal, message?, error?
```

`state` is explicit rather than a percentage because the phases fail
differently and the operator needs to know which one they are in: a stall
in `downloading` is a network problem, a stall in `extracting` is a disk
problem, and `verifying` failing at all is the one that matters.

Operator-only, like every other mutation on the watchdog.

### Two drift fixes fold in here

Both predate M1 and both need a specs bump to fix; doing them now means one
re-pin across four consumers instead of two.

1. **`/v1/auth/initialize` and `/v1/auth/status` are served but undocumented.**
   Not cosmetic — the UI calls `/v1/auth/status` on every page load to tell
   "fresh install" from "logged out", and `/v1/auth/initialize` is what the
   wizard's Start button commits to. Two load-bearing endpoints outside the
   contract that every consumer codegens from.
2. **`ConfigValueType.driver_list`'s comment references `DriverEntry`,**
   which exists in no spec since the strip. The value stays — it is the
   placeholder for M5's configured priority lists — but the comment has to
   stop pointing at a deleted schema.

---

## 6. Scope

**In:** detection, selection, download with progress and verification,
extraction, versioned install, pointer move, retention, update check, the
`GET /v1/engines` surface, and a UI panel to drive it.

**Out:**

- **vLLM.** Still *driven*, not managed — a CUDA-matched wheel and its own
  venv is a categorically harder problem than fetching a binary, and the
  open question in the main design doc stays open.
- **Resumable downloads.** Engine assets are 10–370 MB and a failed install
  can simply be retried. Resume is M3's problem, where a 40 GB model makes
  it load-bearing.
- **Building from source.** Including for Linux + NVIDIA. Named, not
  automated.
- **A comparison surface** between accelerator variants. That is M3
  guidance work.

## 7. Risks

- **Upstream asset naming is not a contract.** llama.cpp renames and adds
  variants freely (`ubuntu-` was `linux-`; ROCm and OpenVINO versions are
  baked into filenames). The matcher must fail *loudly and legibly* —
  "no asset matched win-cuda-13.3-x64 in b10867" with the list it saw —
  never fall back to something plausible.
- **GitHub API rate limits** are 60/hour unauthenticated. One release list
  per day, cached, stays far inside that; a UI that polls it does not.
- **Antivirus on Windows** quarantines freshly-downloaded executables. A
  verified download that then fails to launch needs to say so in those
  terms, not as a generic spawn error.
- **Disk.** ~500 MB per Windows CUDA build, ×2 retained. Report the size
  before installing, not after.
