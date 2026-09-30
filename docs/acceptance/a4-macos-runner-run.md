# A4 acceptance: Eugene on a Mac, on GitHub's macOS runners

**2026-09-30.** `scripts/a4-macos-acceptance.py`, run by
`.github/workflows/a4-macos.yml` on **macos-14, macos-15 and macos-26**
(arm64): **82 of 82 checks on each image** on the pins, eighth run
(runs 1-7 are the history below). Pinned in both installers: agent
`d197a7a`, library `6e22230`, gateway `e050c15`; contract prose `da14926`
(library re-pinned to it). Sabotage `scripts/a4-sabotage.py`: **12 of 12
caught**. Every script specs CI runs passed locally against the fixes
before each pin.

**The rule this run follows (Troy, 2026-09-30):** we own the integration,
not MLX. The run checks what our code decides: the installer and launchd,
the MLX recipe the agent shows, how the agent launches `mlx_lm.server`,
proves it ready and routes to it by the right model id, and how the agent
and library score unified memory. Whether MLX generates good tokens is
upstream's.

## The runner exposes Metal

The first question was whether a hosted runner has a GPU at all. Measured
with MLX 0.32.3 on every arm64 image:

| Image | macOS | Machine | RAM | Metal | Working set |
|---|---|---|---|---|---|
| macos-14 | 14.8.9 | Apple M1 (Virtual) | 7 GB | Apple Paravirtual device | 5,010,800,640 (2/3) |
| macos-15 | 15.7.9 | Apple M1 (Virtual) | 7 GB | Apple Paravirtual device | 5,010,800,640 (2/3) |
| macos-26 | 26.6.2 | Apple M1 (Virtual) | 7 GB | Apple Paravirtual device | 5,010,800,640 (2/3) |
| macos-latest | 26.6.2 | Apple M2 Pro (Virtual) | 14 GB | Apple Paravirtual device | 10,021,601,280 (2/3) |

A matrix multiply runs on the GPU (64-115 ms against 203-748 ms on the
CPU), and `mlx-community/Qwen3-0.6B-4bit` generates at 92-277 tokens/s.
So this is the real `mlx_lm.server` on a real, if virtual, Apple GPU. The
CPU fallback the brief allowed for was not needed.

## What the runner found, each fixed and pinned

Run 1 installed the pins of the day and failed exactly these; each fix
has a unit test in its repo, and each is one sabotage in
`a4-sabotage.py`.

1. **A Mac's GPU budget was 75% of RAM, and Metal allows two thirds.**
   Both the agent and the library reported 5,637,144,576 bytes on the 7 GB
   machine. Metal's `recommendedMaxWorkingSetSize` is 5,010,800,640, which
   MLX's own `mx.device_info()` reports byte for byte. So a small Mac was
   told a model fits that Metal will not hold. Both now read the figure
   from Metal itself (`gpu_probe.metal_device()`, ctypes into the
   Objective-C runtime, no new dependency, byte-identical in both repos).
   The fraction survives only as the fallback, now two thirds, with a
   warning saying so.
2. **A running process never sees a changed wired limit.** Found by the
   run's own experiment (it has passwordless sudo): after
   `sudo sysctl iogpu.wired_limit_mb=5973`, a new process's Metal device
   reported 6,263,144,448 bytes, which is 5973 MiB exactly, and the running
   agent kept 5,010,800,640. Metal hands a process one device object whose
   working set is fixed when it is made, and the agent and library run for
   days. The sysctl is now read on every call through `sysctlbyname` and
   wins whenever it is set. The run raises it, lowers it and sets it back
   to 0, and the agent and library follow each.
3. **The Metal device was named `arm`**, which is `platform.processor()`
   on Apple silicon. It is named by Metal now (`Apple Paravirtual device`
   here; the chip's name on a real Mac), and the CPU by
   `machdep.cpu.brand_string`.
4. **The MLX recipe the agent shows could not run.** It began with a bare
   `uv`, and `install.sh` puts uv in `<prefix>/bin`, never on PATH, so the
   command answered `uv: command not found` on the machine that had just
   installed Eugene with uv. It names the install's own uv by path now. It
   also asks uv for `cpython-3.12-macos-aarch64-none` by name, so it builds
   a native environment even when pasted into a Rosetta shell. The run
   pastes it into both, verbatim.
5. **A sealed control root made every engine on one machine routable on
   faith.** A platform-independent routing defect, found because the run
   onboards through the API and the root was sealed after enrollment.
   The gateway fell back to its own agent, keyed as `None`, while that
   enrolled agent stamps its node name on every runtime. The two keys never
   met, so every driver was "routable on faith", and stopped, loading or
   crashed engines were sent requests. A container restarted with no
   keyring comes back in exactly this state. Runtime facts are keyed by
   the node the gateway asked, as the drivers from the same read are
   (gateway `e050c15`).
6. **The library read a 4-bit MLX model's packed words as its
   parameters**: `Qwen3-0.6B-4bit` read as 93,188,096. The contract had
   recorded that as a caveat, and the UI still showed the number. Each
   quantized module now counts as `scales x group size`, with per-module
   group sizes honoured: 596,049,920 on the runner, the model's true
   count. It is absent when a group size cannot be read. Contract prose
   corrected (`da14926`).
7. **The same model read as having no chat template.** It keeps the
   template in `tokenizer_config.json`, which the library never looked in;
   most HF models do the same.

## The checks, all passing on the pins

On all three images. Each number is a check in the script; facts are
recorded beside them.

- **Rosetta install (R1-R2).** `install.sh` run from an x86_64 shell
  (`arch -x86_64`) completes and installs a native arm64 Python.
- **Install and launchd (1-9).** From nothing in 5-8 s. Python is arm64
  CPython 3.12. The LaunchAgent plist is written and loaded, and the
  process on the agent's port is launchd's job, a child of pid 1. Health
  and the UI are served. Control, gateway and library are declared.
- **Onboarding (10-17c).** Control and the agent initialize, a join token
  is minted, and the agent enrolls with its own root. The agent says
  launchd starts it and names the `launchctl kickstart` it would use. The
  keyring is available to the launchd agent, so it is chosen on both, as
  the wizard does, and sign-in unlocks the root.
- **Unified memory (18-22).** The agent reports a Metal device with shared
  memory, budgeted at Metal's working set and named for the device. The
  library reports unified memory at the same figure.
- **The MLX recipe (23-32).** MLX is listed experimental, manual and not
  available. The command it offers runs verbatim, from a Rosetta shell
  and from a native one, and builds a native environment with the pinned
  mlx-lm 0.31.3, where MLX sees Metal. MLX's own working-set figure agrees
  with the agent's. `mlxBinary` set with a `~` makes MLX available, with
  its version and interpreter. All 11 curated flags are real
  `mlx_lm.server` options, and it has no `--served-model-name`.
- **Models through the library (33-37).** `mlx-community/Qwen3-0.6B-4bit`
  downloads through the library and is catalogued as safetensors with the
  MLX marker, its true parameter count and its chat template. Vanilla
  `HuggingFaceTB/SmolLM2-135M-Instruct` carries no marker.
- **The upstream claims (38-41).** `/health` answers 200 before the model
  can generate (4 to 39 polls with health up and no token, 5 to 13 s
  apart). Nothing in `mlx_lm.server`'s answers names a model we chose or
  states a context length. `default_model` resolves to `--model`. **Any
  other model id sends `mlx_lm.server` to the Hugging Face Hub**: it tried
  to download `a4-public-alias`. That is why the alias must never reach it
  (upstreamModelId's reason, now shown live).
- **MLX runtimes through the product (42-63).**
  - Admission answers on the Metal device and admits, with fit `unknown`
    because Apple gives no free figure.
  - The runtime reaches ready in 40 s (the load includes shader
    compilation). The agent launched exactly
    `mlx_lm.server --model <path> --host --port`, and that is the live
    process's command line.
  - Readiness was proved with **exactly one** generated token, and none
    more in the 20 s after. MLX reports no context length.
  - The gateway lists the alias, never the sentinel or a path. A
    completion and a stream (47 frames) answer under the alias, served by
    this runtime. The engine never saw the alias.
  - A **vanilla HF safetensors model runs under MLX** with nine curated
    flags set, each rendered as upstream spells it.
  - **Two MLX runtimes behind one sentinel are two models**: 3 requests to
    one alias and 2 to the other reached exactly their own engines.
  - A stream the caller closed early leaves nothing in flight. Stop ends
    the process. Start re-proves with one token.
  - `launchctl kickstart -k` restarts the agent under launchd. The root
    comes back **unlocked with nobody signing in** (keychain). Both MLX
    runtimes come back ready, each proved once, with no orphans, and the
    gateway serves again.
- **llama.cpp's macOS build (64-69).**
  - The agent picks `macos-arm64` and installs it (b11301 on the run that
    had GitHub's quota), and the build lists the Metal device.
  - A GGUF downloaded through the library reaches ready and answers
    through the gateway.
  - **This had never run on a Mac before today** (install-paths §8 carried
    it as unverifiable).
- **The wired limit (73-75).** A raised limit reaches Metal, and the
  running agent and library follow it. So does a lowered one, and so does
  the default again.
- **Uninstall (70-72).** The LaunchAgent is removed and the config kept.
  Nothing it started is still running, engines included, and launchd no
  longer knows the job.

**GitHub's anonymous API limit.** It is 60 requests an hour per address,
and a hosted runner's address is shared. It was spent before the job
started on some runs. The agent's refusal said so plainly (*"GitHub's
limit of 60 requests an hour for this network's address is used up. It
resets at 23:16"*). The run then records checks 64-65 as **skipped**,
with that reason, and runs the rest of the llama.cpp half on a build the
workflow fetched with its own token, trusted through `engineBinaryRoots`
and named on the runtime.

## Found and not ours

- **`mlx_lm.server` 0.31.3's `/v1/models` crashes on a machine with no
  Hugging Face cache.** `scan_cache_dir()` raises `CacheNotFound` and the
  answer is an empty 200. That is exactly a Mac whose models came through
  our library. Nothing of ours calls it: the engines see `/health`,
  `/props`, `/version`, one embeddings probe and completions.

## What the runner cannot show: the rented-Mac list

Each item needs Troy's OK to rent (AWS EC2 Mac or Scaleway, 24 h minimum).

1. **A bare-metal Apple GPU at a real size.** Every runner is a VM with a
   paravirtual device at 7 or 14 GB, and two thirds on each. Our budget
   reads Metal, so it is right by construction. What a real 24-64 GB Mac
   reports decides how much a Mac user is offered, and whether the
   fallback's two thirds is right there.
2. **A model near the working set, on real memory**, with a desktop's
   other apps holding some of it. Apple gives no system-wide free-GPU
   figure, so admission answers `unknown` and never refuses. What MLX and
   llama.cpp do at the edge, and whether our explanation of a failure
   names the cause, needs a machine where running out is real.
3. **A reboot and a login.** The runner can kickstart the LaunchAgent but
   not reboot, log out, switch users or sleep. A LaunchAgent runs only
   inside a login session, so after a reboot nothing serves until someone
   logs in. That is the known macOS limitation (*"On macOS, Eugene cannot
   run under its own account yet"*), and a real Mac shows what a person
   sees.
4. **A second device reaching the Mac**, with the macOS application
   firewall on: its prompt for the venv's Python, and the Reach card's
   verdict.

**Not on the list, because a runner can do it:** an Intel Mac. The
`macos-15-intel` image exists, so the MLX refusal and llama.cpp's
`macos-x64` build can be covered by a job without renting anything. Not
built yet.

## Not done

- **MLX is still marked experimental.** The runner's evidence meets the
  bar of the 2026-09-30 rule. But the UI uses `experimental` to hide MLX
  on machines that cannot run it (`offeredOnThisNode`), so clearing the
  flag puts *"mlx: not installed"* on every Windows and Linux box. It
  needs a UI change and a dist rebuild. Troy's call.
- The Rosetta check proves the installer and the recipe. It does not
  prove what an Intel Homebrew environment on a real Mac would leave on
  PATH.
