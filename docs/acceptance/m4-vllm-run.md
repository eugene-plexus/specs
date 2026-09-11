# M4 acceptance — a second engine, four milestones late

**Status:** passed 2026-09-10, **first execution ever**, 31 checks, zero
failures. **Re-run 2026-09-11 with the runtime declaring no `env` at
all** — 33 checks, zero failures, the agent supplying the host's
prerequisites itself; see the resolution near the end. Script:
[`scripts/m4-acceptance.sh`](../../scripts/m4-acceptance.sh); design in
[`m4-second-engine-vllm.md`](../design/m4-second-engine-vllm.md).

```
agent :8079 ──spawns──> gateway :8080
            ──spawns──> vllm-driver :8081        (runtimeName, no baseUrl)
            ──spawns──> qwen3-0-6b-driver :8091  (M6's companion, unasked for)
            ──spawns──> vllm serve :8090         (declared at runtime, not in the topology)
```

The host: WSL2 on the Windows dev box — Ubuntu 26.04, kernel
6.18.33.2, Python 3.14.4, RTX 5090 (32,607 MiB) visible inside it,
vLLM 0.29.0 on torch 2.13.0+cu132, 32 cores, 45 GB of the host's RAM.
The contracts were written 2026-09-09 and the adapter landed the same
day; both were built against upstream source and fixtures, because the
dev box could not run the engine. **The adapter needed no change.**
Every claim §8 listed as read-off-source-but-unobserved held.

---

## What it proved

- **The twelve curated flag names are right.** vLLM echoes its own
  `non-default args` line at startup, and it came back holding exactly
  what the adapter sent: `max_model_len`, `enforce_eager`,
  `served_model_name`, `gpu_memory_utilization`, `max_num_seqs`. No
  flag was rejected, on either startup path.
- **§2's readiness rule, which was the one claim marked as needing
  confirmation.** Across the load, *every* probe of the engine's own
  port was refused — 14 of 14 on the short path, 67 of 67 on the long
  one — and not one accepted-and-hung. "Process alive, connection
  refused" really is the only signal available, so reading it as
  `loading` from the process handle is not an inference, it is the only
  thing it can be. `interpret_readiness` is doing the right thing for
  the right reason.
- **The whole chain, by name.** The driver was written with
  `runtimeName` and no `baseUrl`, came up **degraded** against a runtime
  that did not exist yet — naming the missing runtime on `/healthz`,
  config endpoints still answering — and resolved `qwen3-0-6b` to
  `http://127.0.0.1:8090` on restart. Nobody typed a port anywhere.
- **Discovery through `vllmBinary`.** Before the PATCH: `available:
  false`, `policy: manual`, `installable: false`, and a refusal naming
  `uv pip install vllm --torch-backend=auto` for this host.
  `POST /v1/engines/vllm/install` → 422, as designed. After: `available:
  true`, `origin: configured`, `version: 0.29.0` read from distribution
  metadata through the venv's own interpreter, `python 3.14.4`,
  `torch 2.13.0+cu132`, `accelerator: cuda`.
- **`--served-model-name` does its job.** The model is routable through
  the gateway as `Qwen3-0.6B`, not as `/home/tcorbin/models/Qwen3-0.6B`.
  `contextLength: 4096` was read back off `/v1/models`' `max_model_len`.
- **An unknown flag is refused before anything spawns.** llama.cpp's
  `gpuLayers` on a vLLM runtime → 400.
- **Stop releases the card and keeps the declaration**, with no
  `vllm serve` process left behind — so the EngineCore child does not
  outlive the API server, which §8 had flagged as worth checking.

## The numbers

`STARTUP_BUDGET_SECONDS = 600` was the number most likely to be wrong.
It is not wrong, but not for the reason the design gave.

| | first `loading` | `ready` | `loading` lasted |
|---|---|---|---|
| `enforceEager: true` | t+2s | t+17s | **15s** |
| re-run, same | t+2s | t+18s | **16s** |
| `enforceEager: false` | t+2s | t+74s | **72s** |

The long path's 72s decomposes, from vLLM's own log: 13.66s of
compilation, then 39s of CUDA graph capture in two passes
(`PIECEWISE` 4 sizes, `FULL` 3), then the rest in profiling and KV
cache creation. `enforceEager` is doing exactly what §2 said it does.

**But the load that matters is the first one, and it is not in that
table.** The same command line that reports `init engine (profile,
create kv cache, warmup model) took 3.25 s` on a later start reported
**23.45 s** the first time — 40.7s to `ready` rather than 17s — because
vLLM writes JIT and warmup caches under `~/.cache/vllm` and `~/.triton`
and reuses them afterwards. Every number above except that one is a
warm-cache number. So: a 0.6B model on a 5090, cold, on the *short*
path, spends 40s loading. **600 stays**, and the reason to keep it is
this cold-start multiple rather than the model size — the budget only
decides when a still-loading runtime gets flagged on `Runtime.lastError`,
so being generous costs nothing and being tight would flag every first
launch of a large model.

## Three host preconditions upstream's install command does not give you

This is the finding with the longest reach, because it is not about vLLM
being hard to install — `uv pip install vllm --torch-backend=auto`
worked first time, in under two minutes, all wheels, no source builds,
on Python **3.14**. It is about what the installed package then needs
from the host at *run* time, none of which the install step checks.

Each of these killed the engine 20-40 seconds into a load, from inside a
subprocess, with a traceback that never named the fix:

| Symptom | Real cause | Fix |
|---|---|---|
| `RuntimeError: UVA is not available` at engine init | On WSL2 vLLM disables pinned memory by default, and 0.29.0's model runner hard-requires it via a UVA buffer. `is_uva_available()` is `is_pin_memory_available()`. | `VLLM_WSL2_ENABLE_PIN_MEMORY=1` — upstream's own switch, gated on a kernel floor of 4.19.121 (ours is 6.18.33.2) |
| `Failed to find C compiler` | Triton JIT-compiles a CPython extension at first use | `build-essential` |
| `CalledProcessError` from gcc | …and that extension needs `Python.h` | `python3-dev` |
| `Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist` | FlashInfer JIT-compiles its *sampling* kernels (not attention — that picked prebuilt FlashAttention 2) and wants a full CUDA toolkit | `VLLM_USE_FLASHINFER_SAMPLER=0` for native sampling, or install a toolkit |

Only the first is WSL-specific; the other three would hit any clean
minimal Linux host. **This revises §1's framing.** The design says the
unit of installation is a Python environment, and that CUDA-version
matching is not the hard part. Both still true — `--torch-backend=auto`
resolved `torch 2.13.0+cu132` against a 610.47 driver without being
asked. But the unit of *operation* is a Python environment **plus a C
toolchain plus the interpreter's dev headers**, because vLLM compiles at
first use, not at install. A control plane that spawns vLLM on a host it
did not provision will meet all three.

**`RuntimeSpec.env` carried the fix with no contract change**, which is
what it was put there for — the field description names
`CUDA_VISIBLE_DEVICES` as the motivating case and this is the same
shape. On the day of the run the acceptance script computed the set
itself; a day later the agent does it, and the script deliberately
declares nothing so that every run tests the agent instead. See the
resolution below.

**RESOLVED 2026-09-11 — the agent supplies both env vars now**, on
Troy's general rule: default to whatever makes the thing work for
someone with no technical knowledge, and always leave an expert a way to
take the wheel. `EngineAdapter.default_env` (agent `532be74`) injects
`VLLM_WSL2_ENABLE_PIN_MEMORY=1` on WSL2 and
`VLLM_USE_FLASHINFER_SAMPLER=0` with no `nvcc`, beaten by an exported
shell variable and beaten outright by `RuntimeSpec.env`, and logged
either way. **This script now declares no `env` at all**, so every run
re-proves it: 32 checks green on a host with no toolkit, `ready` at
t+22s, and the injection visible in `agent-run.log`.

**The other two — `gcc` and `Python.h` — are explained, not refused,
and the obvious design was wrong.** A preflight refusal naming the apt
command was the plan, until it was measured: a host with a warm Triton
cache runs vLLM with `CC=/nonexistent` and served in 19.9s, because
Triton caches its compiled extension under `~/.triton` and builds only
on a miss. Refusing would therefore reject a launch that works on any
host that has run the engine once. `SpawnPlanner.explain_exit` reads a
bounded tail of the engine's output on a non-zero exit instead, and
turns each known signature into the fix — so the failure is as fast as
it always was, but `exited with code 1` becomes an apt command.

## What the run changed in the script, not the adapter

1. **A host-precondition preflight** (above), so these fail in preflight
   with the apt command rather than 30 seconds into a load.
2. **`EP_ENFORCE_EAGER`**, so one script measures both startup paths.
   The design asked for the long path "if there is time"; it is one
   environment variable now.
3. **The socket instrument was wrong, and it reported a passing claim as
   a failing one.** It counted *any* successful connect during `loading`
   as "the port answered", including the HTTP 200 that means the engine
   is now servable. So the first run printed `answered 1` and a NOTE
   saying §1 Trap 1 needed revisiting — when what had actually happened
   is that the engine became ready in the one-second gap between the
   script reading a `loading` status and probing the port. The fix
   separates three outcomes: refused, answered-not-ready (which would
   genuinely refute §2, and never happened), and already-200 (which
   measures our own poll lag, and happened once per run). **A
   measurement that cannot tell its own sampling rate from its subject
   will manufacture findings.**
4. `pgrep -fc` prints `0` *and* exits non-zero when nothing matches, so
   `|| echo 0` printed a second zero and the teardown check read
   `NOTE 0\n0`.

## Two things worth knowing that nobody asked for

- **M6's companion driver turned up uninvited.** The script predates M6
  and declares its own `vllm-driver`; the agent additionally declared
  `qwen3-0-6b-driver` for the new runtime, so two drivers fronted one
  engine and the gateway was fine with it. Nothing to fix — but stage 8's
  restart-to-resolve is now demonstrating something M6 does
  automatically, and a reader of this script should not conclude that
  the manual driver is how it is done.
- **`root` leaks the model path**, exactly as §8 predicted off the
  source: `/v1/models` returns `"root":"/home/tcorbin/models/Qwen3-0.6B"`
  regardless of `--served-model-name`. We do not surface it, but
  anything that proxies vLLM's `/v1/models` verbatim would.

## What this run still does not prove

- **One engine, one card, one model, 0.6B.** No tensor parallelism, no
  two runtimes on one card, no model large enough for the cold-start
  number to bite for minutes rather than seconds.
- **Nothing about a real second host.** WSL2 is a genuinely separate
  kernel, network namespace and filesystem, which is why it answers M4 —
  but this run used it as the *only* host, with everything on loopback
  inside it. The two-machine question is still open.
- **The engine was never killed under load.** M6 and M7 proved that for
  llama.cpp; the vLLM path has not been asked what happens when
  EngineCore dies mid-request, which is the case §8's departure 1 exists
  for (`/health` 503 is `EngineDeadError`, not loading).
