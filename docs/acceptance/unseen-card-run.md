# R2.3 — a card we cannot see: the run

**2026-09-18. `scripts/r23-acceptance.sh`, 14 PASS live, zero failures.
`scripts/r23-sabotage.py`, 21 sabotages, 21 caught, 0 escaped** — after one
escaped on the first pass and one more after the live run forced a change, and
both named something real. Roadmap:
[`../design/release-roadmap.md`](../design/release-roadmap.md) §3.3. Findings
closed: review §6.1 #11, §6.2 #29, §6.2 #28 (the Intel half).

Repos: `specs` (two contract documents), `agent`, `library`, `ui`, plus
`control` regen-only. **Both installers re-pinned and `dist` rebuilt**, because
the UI changed.

**`scripts/install-acceptance.sh EP_MODE=posix` re-ran green at the new pins —
16 checks, a real install from nothing in WSL2. It did not, the first time**, and
that failure is §4.

---

## 0. The shape of it

Three findings, one sentence: **the software could not tell "no card" from "a
card we did not look for" or "a card we could not measure", and answered as
though the machine had nothing.** Every consequence follows from that one
confusion, and each is a different component:

| finding | the confusion | what the person got |
| --- | --- | --- |
| §6.1 #11 | a Windows GPU no vendor tool reports | a CPU build, silently |
| §6.2 #29 | a vendor tool that ran and failed | *"its tool is not on your PATH"* |
| §6.2 #28 | a card whose size nothing will state | *"a 30 GB model fits"* |

**Two contract changes, in two documents.** `HostAccelerator.accelerator` gains
`vulkan`; `FitVerdict` gains `unknown`. Radius measured by regenerating all six
consumers: `agent`, `control` and `library` came back with real type changes and
`ui` gained both; **`gateway` and `inference-driver` came back byte-identical
apart from the SHA in a generated header and were reverted rather than
re-pinned**, which is the rule this repo has followed since M9.

---

## 1. #11 — the card nobody looked for

`_has_rocm` looks for `rocm-smi` or `/opt/rocm`. `_has_sycl` looks for `sycl-ls`
or `/sys/bus/pci/drivers/i915`. **None of those four exists on Windows**, there
was no Vulkan probe and no `Win32_VideoController` query, so every AMD and Intel
card on Windows fell straight through to `none` — a CPU build, *"no accelerator
was detected"*, a fit scored against RAM, and the starter set inverted to the
smallest model, on a machine built around a graphics card. `win-rocm-10.0-x64`
sat in the variant map **unreachable**, because `_has_rocm` could never be true
there: dead code that reads as AMD support.

**Vulkan is the answer, and the reason is about the user's machine rather than a
table.** Upstream ships `llama-*-bin-win-vulkan-x64.zip` in every release, it
needs no vendor SDK, and one build covers AMD and Intel alike. ROCm is still
reported when AMD's HIP SDK is actually on disk — `HIP_PATH`, `ROCM_PATH`, or
the two install prefixes — which makes `win-rocm-10.0-x64` reachable without
betting the common case on it. **`win-sycl-x64` is not used**: the roadmap
records that the name appears nowhere this repo can verify, and a variant nobody
ships turns a slow install into a failed one.

**No new dependency.** `pywin32` arrives with the Windows `[service]` extra both
installer paths take, and `firewall/windows.py` already reads WMI through it.
**Measured here: 26 ms** for `SELECT Name FROM Win32_VideoController`, against
the 112 ms in-tree precedent.

The fallback runs **last**, after `nvidia-smi`, `rocm-smi` and `sycl-ls`, so a
working CUDA host is unaffected — a sabotage moving it in front is caught.

## 2. #29 — a tool that ran and failed

`_run` returned stdout plus stderr whatever the exit code, so `nvidia-smi`
printing *Failed to initialize NVML: Driver/library version mismatch* and
exiting 9 came back as a non-empty string that `_has_nvidia` read as a card. The
install plan then fetched a CUDA build that cannot load, for a reason nothing
mentions. **A driver/library version mismatch after an update is the commonest
Linux failure there is.**

Both components now carry a three-state result — absent, failed, or output — in
**one place each**, because `_has_nvidia`, `_has_rocm` and `_has_sycl` all need
the same distinction and three copies is three chances to get one wrong. The
library's warning says the tool *ran and exited non-zero* and stops blaming this
process's PATH.

**And the agent now probes the resolved path rather than the bare name.**
Measured 2026-09-18, and it is a real disagreement rather than a tidy-up:
`shutil.which` answered with a stub first on PATH while `subprocess.run` ran the
System32 copy, because **CreateProcess searches the application directory, the
current directory, System32 and the Windows directory before PATH**. The gate
and its subject were two different programs, on every Windows machine with an
NVIDIA driver. An operator who puts a newer tool earlier on PATH now gets the one
they chose.

## 3. #28 — a card we could not measure

`_verdict` branched on `vram_total == 0`, which is true of a machine with no GPU
**and** of a machine with a GPU whose size no vendor tool will state.
`_intel_gpus` fills in exactly that — `xpu-smi discovery` reports device names
and no memory figure in any stable form — so an Arc owner's 16 GB card took the
CPU branch, 30 GB of weights was compared against 32 GB of host memory, and the
answer was **`fits`**, with `gpuCount: 1` printed beside it. Wrong in the
direction that runs out of memory at load.

`card_of_unknown_size` asks the question the object could always answer: is
`gpuCount > 0` while the size is not. **Every candidate on such a host reports
`unknown`, small ones included** — the missing number is a property of the
machine, and a favourable answer computed against a number we do not have is
right by luck.

**The half a person actually meets was in `starter.py`**, asking the same
question the same wrong way: an Arc owner opening Discover for the first time
was handed the *smallest* model in the set, with a sentence explaining that
their machine has no graphics card.

**And the existing test is the one that should have caught it.**
`test_a_card_with_no_free_reading_falls_back_to_total` built an Intel GPU with
`vramTotalBytes=16 * GIB` — **a value the Intel detector cannot produce** — and
asserted the fallback worked. Green about a case that does not occur while the
case that does occur was unasserted; it is the AMD shape it actually describes
now, and every fixture in the new file is what `_intel_gpus` emits.

In the UI, three `Record<FitVerdict, string>` maps failed typecheck the moment
the contract landed, which is the point of generating the type. `unknown` reads
**can't tell**, wears the warn role rather than the success one, and the budget
line stops rendering *"measured against 0 B free of 0 B on the GPU"* — which is
§6.2 #28 in one sentence, printed beside the word `fits`.

---

## 4. What the live run found that reading did not

**This box is the fixture, and that is why the live half is worth having.** It
has an AMD integrated adapter beside the 5090 — `Win32_VideoController` returns
`AMD Radeon(TM) Graphics` and `NVIDIA GeForce RTX 5090` — so taking NVIDIA's
tool away turns it into precisely the machine #11 is about. With `nvidia-smi`
either absent or exiting non-zero, a real agent picks **`win-vulkan-x64` off a
real upstream release**. It picked `win-cpu-x64` before.

**Three things the harness had to get right, each measured rather than
reasoned about.**

1. **A `.cmd` cannot shadow a real `.exe`.** The first stub ran the machine's
   real `nvidia-smi`. The stub is a **copy of `find.exe`** — a genuine
   executable that exits 2 and writes to stderr, which is the shape of a wedged
   driver. (`xpu-smi.cmd` is fine, because the library resolves the path first.)
2. **A PATH list must be all-POSIX or all-Windows.** MSYS converts a POSIX list
   when handing it to a Windows program; a list with one Windows entry spliced
   in front is passed through verbatim, and everything after it is unusable to
   the child. The agent found the stub and the library it spawned found nothing.
3. **The agent mirrors its console to two files**, and a run that cleared only
   the redirected one read the *previous* run's warning — reporting a tool as
   failing on a run where none had been executed.

**A fourth harness fact, and a small product finding beside it.** The variant
checks ask the agent for a plan, which asks GitHub for the upstream release
list — and GitHub's **unauthenticated limit is 60 requests an hour per
address**. Ten runs of this script in an afternoon exhausts it, after which
every variant check fails for a reason that is about the network. The script
reports the remaining budget, SKIPs those assertions rather than calling the
finding reproduced, and **says so loudly at the end**, because a sabotage pass
reads its exit status and a green run that looked at nothing would report a
defect as caught. *The 14 PASS above were measured with upstream reachable.*

The product finding, recorded and not fixed here: with the budget exhausted the
agent says **"could not reach the upstream release list. Check network access"**
— which sends a person to look at their network when the truth is a 403 and an
hourly reset. It is the same *which kind of nothing* shape as §6.2 #29, one
layer out, and it belongs with R1.5's `/v1/engines` work rather than in this
slice.

**And two product findings came out of it.**

- **The wedged-tool warning disappeared behind `if not gpus`.** On a machine
  with a working Intel card and a wedged NVIDIA driver, the NVIDIA card is the
  one the person cares about and the whole warning vanished.
- **With every verdict `unknown`, `recommend` fell into the nothing-fits
  branch** and produced *"None of these fits entirely in 0 B at 8,192 tokens"* —
  a number that is not a number, about a card we can see and cannot size. There
  is a branch for it now, with no `sizeClass`, which the contract has always
  allowed.

**Then the real install run caught a regression the live run could not.**
`install-acceptance.sh` failed check 14 — *one process on the install's
interpreter survived* — twice, reproducibly, and passed at the previous pins. It
bisected to `library` in two runs. **The cause was the first version of #29's
fix**: answering *which tool failed* by scanning all three vendor tools again at
the end of `detect()`, which is up to three extra subprocesses **on every
hardware read, on a request path**, for a fact the detectors had already learned
and thrown away. In WSL2 `nvidia-smi` is real and takes about a second, so a
library process was still alive after its own ASGI shutdown. Same family as
review §6.1 #5. `_run` records the failure in passing now, and a check asserts no
vendor tool is run more than once per `detect()`.

---

## 5. The sabotage pass

**21 sabotages, 21 caught**, across four gates — the agent's detector, the
library's verdict, the UI's badge, and the live run that joins them. The six
findings are put back against the **live processes**, not only the unit files.

**Two escapes, and both were diagnoses rather than gaps to paper over.**

1. **An exclusion list of adapters that are not GPUs** (`microsoft basic`,
   `virtual`, `citrix` …) was **unreachable**: none of those names contains a
   GPU vendor word, so the allowlist beside it had already rejected them.
   Removing it changed no answer. **It is deleted rather than kept** — an
   unreachable filter that reads as protection is exactly the defect this slice
   removed from `win-rocm-10.0-x64` — and the test now names four such adapters
   and lets the one surviving mechanism reject all of them.
2. **A sabotage stopped expressing its defect once the fix moved.** Suppressing
   the `wedged` tie-breaker changed no output after the warning moved into
   `_run`, and the live run cannot reach the state it was about: its Intel stub
   supplies a card, so the no-GPU branch never runs. It is aimed at the unit
   gate and at what that variable actually decides.

**Two harness defects the pass found in itself**, both worth recording because
they are the same family as R2.2's #34: vitest writes UTF-8 and Python decoded
it as cp1252, raising inside the reader thread and reporting **a red gate for a
green suite**; and under `cmd /c` vitest answers *"failed to find the current
suite"* and `no tests`, while the same command from bash is green. **A runner
that invokes a gate differently from the way a person does is reporting on
something else.**

---

## 6. What this run does not cover

- **Real AMD or Intel hardware.** The Vulkan path is chosen for a real AMD
  adapter on this box and the engine is never *installed* for it, and no Arc
  exists here. `_amd_gpus` and `_intel_gpus` remain unverified against their own
  tools, as their docstrings have always said.
- **`win-rocm-10.0-x64` end to end.** Reachable now; nothing here installs it.
- **The Apple half of §6.2 #28**, which needs a Mac and goes to R3 by the
  roadmap's own call.
- **A genuinely wedged driver.** The stub exits non-zero with stderr, which is
  the shape; a real NVML mismatch is a machine nobody here has.
- **`_windows_display_adapters` without `pywin32`.** It returns an empty list,
  which the caller reads as *could not look*; untested against an install that
  lacks the extra, because both installer paths take it.
