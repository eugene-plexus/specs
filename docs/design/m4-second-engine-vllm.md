# M4 — Second engine: vLLM (design)

**Status:** contracts designed 2026-09-09; **adapter and routing fix
landed the same day** — agent `53d815d`, inference-driver `97f6583`,
gateway `5ad5993`, no contract change needed. **DONE: the live run
passed 2026-09-10 in WSL2** — 31 checks, zero failures, and the adapter
needed no change. §8 records what the implementation verified and where
it departed from this document; **§9 is the live run**, and
[`docs/acceptance/m4-vllm-run.md`](../acceptance/m4-vllm-run.md) is the
record. Milestone **M4** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M3](m3-discovery-download-guidance.md).

**What it is:** a second engine adapter, so the control plane supervises
something that is not llama.cpp. This is where the format abstraction and
the two-layer split stop being speculative.

**How far it is verified.** Every claim below was read off vLLM's own
source at **v0.29.0** (tagged 2026-09-09, the day this was written) or
its published docs, and the file is named at each one — because when it
was written **no vLLM process had ever run for this project**: the dev
box is Windows and vLLM has no Windows build (§1). Decided with that in
view (Troy, 2026-09-09): land the contracts and the adapter with fixture
tests now, and hold the acceptance run until a Linux host exists.

**That run happened on 2026-09-10 and §2 is now proven rather than
designed** — see §9. It is worth knowing which way it went: reading
source instead of running the thing cost this milestone *nothing* in the
adapter, and every defect the run found was in the acceptance script or
in the host's own prerequisites. That is the opposite of M0-M3's
pattern and should not be read as a general licence; the run still
found four things, they were just not where the risk was thought to be.

Two decisions were taken to open the milestone, both 2026-09-09:

- **Drive a user-provided vLLM; do not manage its installation** — the
  recommendation that has been on file since 2026-09-08, now a decision,
  with §1's install matrix as the evidence. *And make driving
  first-class*, which is the part that is new work rather than an absence
  of it.
- **The M2 routing gap closes here** rather than at M5 — §4.

---

## 1. What vLLM is, and where it differs

The whole milestone is the difference. Both engines end up serving
OpenAI-compatible HTTP; almost everything about getting there diverges.

| | llama.cpp | vLLM |
|---|---|---|
| What you install | a prebuilt binary in a zip | a Python package in its own venv |
| Platforms | Windows, Linux, macOS, Android | Linux; macOS only via a separate project; **no Windows** |
| Model format | GGUF | safetensors (GGUF experimental) |
| Readiness | answers `/health` at once, 503 + `loading model` | **refuses connections until the model is loaded** |
| Version | `--version`, instant | needs the distribution metadata, not the CLI |
| Default model id | the model filename | **the `--model` argument, verbatim** |
| Live load signal | none | `/load` |

### The install matrix, and why we do not manage it

From upstream's installation index and GPU page:

| Target | How it installs |
|---|---|
| Linux x64 + NVIDIA | prebuilt PyPI wheel, built against **CUDA 12.9**, bundles PyTorch. `uv pip install vllm --torch-backend=auto` |
| Linux + AMD | wheels on a custom index (`wheels.vllm.ai/rocm/`), **Python 3.12 only**, ROCm ≥ 6.3 |
| Linux + Intel XPU | nightly custom index plus a second index for PyTorch XPU, **Python 3.12 only** |
| CPU (x86, ARM, s390x) | prebuilt wheels |
| Apple Silicon | **vLLM-Metal**, a separate community project with its own wheels |
| **Windows** | **unsupported. Upstream's answer is WSL** |

Set that beside M1's llama.cpp story — fetch one zip, compare one SHA-256
from the same API response, unpack into a versioned directory — and the
asymmetry the main design doc predicted is confirmed, but not where it
guessed. The guess was that CUDA-version matching would be the hard part.
It is the easy part: the default wheel bundles its own CUDA build and
`--torch-backend=auto` picks it, so *we* would never match a CUDA version
at all.

What is actually hard is that the unit of installation is **a Python
environment**:

- It needs an interpreter of a version we do not control, and the two
  non-NVIDIA accelerators need **specifically 3.12** — a constraint no
  amount of care on our side can satisfy on a host that lacks it.
- Retention "current plus previous", which M1 settled for llama.cpp at
  704 MB a build, becomes two venvs of several GB each.
- A venv is not verifiable the way an asset is. M1 gets a digest from the
  same call that picks the asset; there is no equivalent single number for
  the closure of a wheel install.
- Three of the six targets need a non-default index, and one is a
  different project entirely.

**Decision: drive it.** `acquisition.installable` is `false` for vLLM on
every host, permanently, and that is not a failure state — it is the
engine's install policy. What M4 adds is the half that makes driving
respectable rather than a shrug:

1. **The refusal names the command.** M1 built `installable: false` plus a
   `reason` for one host configuration (Linux + NVIDIA llama.cpp). Here it
   becomes the normal path for a whole engine, so the reason stops being an
   apology and becomes instructions: the exact command for the detected
   host, plus upstream's own install page. New `manualInstall` object, §5.
2. **Discovery finds a venv.** Today `discover()` checks the managed store
   then `PATH` (`engines/base.py`), and an install-wide binary override
   does not exist — only a per-runtime `binary`. For an engine we never
   manage, that leaves an operator with a perfectly good venv reported as
   `available: false` unless they either put it on `PATH` or repeat the
   path on every single runtime. So the agent's config gains a
   `vllmBinary` field, and `Origin.configured` gains a second, install-wide
   source. §3.

Rejected: **managing a venv on Linux + NVIDIA only.** It is genuinely
tractable there — one wheel, torch bundled, no version matching — and that
is exactly what makes it a trap. It would be the one accelerator, on the
one OS, that works one way, and the operator who reads "Eugene Plexus
manages your engines" would meet the exception on their second engine.
Uniform "we drive vLLM" is a smaller promise that is true everywhere.

### Trap 1 — the port is bound minutes before anything answers on it

vLLM binds its listening socket *before* loading the model, on purpose.
From `vllm/entrypoints/launchers/launcher.py`, in `setup_server`:

```python
# workaround to make sure that we bind the port before the engine is set up.
# This avoids race conditions with ray.
# see https://github.com/vllm-project/vllm/issues/8204
sock = create_server_socket(sock_addr, reuse_port=reuse_port)
```

and `create_server_socket` in the same file calls `sock.bind(addr)` and
returns — **no `listen()`**. The ordering in
`launchers/api_server/entry.py` is unambiguous:

```
run_server()                 line 175:  listen_address, sock = setup_server(...)
run_server_worker()          line 190:  async with build_async_engine_client(...)
                             line 194:  build_and_serve(engine_client, ..., sock, ...)
```

The socket exists at line 175. The model loads at line 190. Uvicorn — and
therefore `listen()`, and therefore anything that answers — starts at line
194. Between them sits the entire load: weight reading, `torch.compile`,
CUDA graph capture. Minutes, for a large model.

Three consequences, in increasing order of how much they matter.

**The port is reserved but dead.** A bound socket with no listen backlog
refuses connections, so throughout the load the endpoint looks exactly
like a process that never started — while the port is simultaneously
unavailable to anything else. *(The reservation is read from the source;
that connections are refused rather than accepted-and-hung follows from
bind-without-listen and is the one claim here that the live run should
confirm rather than assume.)*

**A TCP check is worse than useless.** M0's contract already says a
generic TCP probe cannot distinguish `starting` from `loading`. For vLLM
it cannot distinguish either of them from `crashed`, for minutes.

**`loading` versus `crashed` is decidable only from the process handle** —
and the process handle belongs to the supervisor. This is the milestone's
main architectural result, and it lands on a decision that was locked on
2026-09-08 with a thinner justification than it turns out to deserve:

> Lifecycle adapters (how to start an engine) live in the supervisor;
> wire protocol (how to talk to one) lives in the driver.

Had readiness lived in the driver, which sees only the network, vLLM's
entire load phase would be indistinguishable from a dead engine and the
dashboard would have nothing honest to show for it. The supervisor knows
the pid is alive because it spawned it. That is the whole answer, and it is
only available on one side of the split.

It also forces a contract fix. `RuntimeStatus.loading` is currently
written in llama.cpp's mechanism — *"answering, but reporting the model is
still being read into memory"* — and so is the adapter base class's
`Loading` outcome (`engines/base.py`: *"Answering, but the model is still
being read into memory"*). Under that definition **vLLM can never be
`loading`**, and a vLLM runtime would sit at `starting` for ten minutes
and then jump to `ready`. The state has to be defined by what it means,
not by how one engine reports it. §2.

### Trap 2 — the default model id is the path you launched from

`vllm/config/model.py`, on `served_model_name`:

> The model name(s) used in the API. […] If not specified, the model name
> will be the same as the `--model` argument.

We launch models by absolute path, because the user's files stay theirs.
So `vllm serve /home/troy/models/Qwen3-8B` serves a model whose OpenAI id
is `/home/troy/models/Qwen3-8B`. That is wrong three times over: it leaks
the operator's directory layout to every API client, it makes the routing
key differ per host for the same model — which breaks both the multi-host
story and any failover priority list that names a model — and it is ugly
in a dropdown.

**The adapter always passes `--served-model-name`,** from the resolved
`modelAlias`, and never lets the engine default. `RuntimeSpec.modelAlias`
was specified at M0 as *"an override, not a requirement"*, which is still
true of the operator's side of it — but the *resolved* value is now always
sent to the engine explicitly. Its description says so as of this
milestone.

llama.cpp is not affected in practice (its default is derived from the
filename, which is what we would send anyway), and that is precisely why
this was not visible until a second engine existed.

### Trap 3 — GGUF via vLLM is not a feature we can offer

Upstream's own wording:

> GGUF support in vLLM is highly experimental and under-optimized at the
> moment, it might be incompatible with other features.

and it needs a second model to work at all — `--tokenizer` pointing at the
original unquantized repo, because *"the tokenizer conversion from GGUF is
time-consuming and unstable, especially for some models with large vocab
size."* The documented examples are single-file only; nothing addresses
sharded GGUF.

So **`modelFormats` for vLLM is `[safetensors]`.** Adding `gguf` would
light up a Launch button on every GGUF in the library — the exact
population llama.cpp already serves properly — for a path that is
experimental, slower, and needs a HuggingFace repo the operator may not
have. The library's GGUF models keep going to llama.cpp.

### Finding — the format join is coarse, and this is its honest limit

M2 put format→engine support on `EngineDescriptor` rather than on the
library, and pre-wired M4 with it: *"vLLM lists `safetensors` and the
launch button lights up with no library change."* That holds, and it is
worth being exact about what it buys. A format match means the engine
*could* load this kind of file. It does not mean this engine can load
*this* model — vLLM's model registry is the authority on architectures,
and it answers only at spawn.

So the join stays a first filter, and the second one is the engine's own
error surfaced verbatim through `Runtime.lastError` and the captured
output. No architecture list is copied into the control plane; a copy is
the thing that goes stale, which is the same reasoning that put
`modelFormats` on the engine in the first place. The UI's honest promise
after M4 is "an engine exists that loads this format", not "this will
work".

### Finding — the probe needs no credential, and `/health` is not guarded

`vllm/entrypoints/serve/middleware/authenticate.py`:

```python
GUARDED_PREFIX = ("/v1", "/v2", "/inference", "/cohere")
```

with the docstring noting authentication is skipped when *"the request
path doesn't start with GUARDED_PREFIX (e.g. /health)"*. So `--api-key`
protects inference and leaves `/health`, `/version` and `/load` open. The
supervisor's readiness probe needs no credential; the driver's generate
calls would need one if a key were ever set. (We do not set one — §6.)

`/health` itself, from `serve/instrumentator/health.py`, is thinner than
llama.cpp's: **200 with an empty body**, or 503 only on `EngineDeadError`.
No loading status, no capabilities, nothing to read back. What the adapter
can learn about a running vLLM comes from `/version`
(`{"version": "0.29.0"}`) and `GET /v1/models`.

### Finding — `/load` is a real load signal, and llama.cpp has none

`serve/instrumentator/basic.py` serves `/load` as
`{"server_load": <n>}` — a live count of requests currently occupying the
GPU, listing the eleven inference routes it tracks. That is exactly the
input M5's load balancing wants, and it exists on one engine and not the
other. **Not consumed at M4** and no contract field for it: capabilities
are static and this is not one. Recorded here so M5 starts from the
knowledge that the two engines will not offer symmetric load signals, and
whatever balances them has to work when the number is absent.

### Trap 4 — `vllm --version` pays for a full import

`vllm/entrypoints/cli/main.py` registers `--version` as an argparse
`action="version"` over `importlib.metadata.version("vllm")`. The value is
cheap; reaching it is not, because the CLI module chain imports vLLM and
therefore PyTorch before argparse ever runs.

M1 already learned that probing a version by running the binary has
sharp edges — llama.cpp changed its `--version` format mid-2026 and broke
a scraper. vLLM's format is the easy case by comparison (a bare semver,
`0.29.0`), but the *cost* is the problem: `GET /v1/engines` calls
`probe_version` during discovery, and paying a torch import to render a
settings panel is not acceptable.

**Read the version from distribution metadata, not from the engine.** The
venv's `vllm-*.dist-info` answers it with a file read. M1 set the
precedent for not re-probing when the answer is already recorded — its
managed store returns the build number it installed rather than spawning
the binary — and this is the same trade for a different reason.

### Finding — quantized safetensors already sizes correctly

M2 decided quant fields exist only on the GGUF side, on the grounds that
*"safetensors has an exact parameter count and no tier"*. vLLM makes
quantized safetensors ordinary — AWQ, GPTQ, FP8 and compressed-tensors all
arrive as safetensors repos carrying a `quantization_config` in
`config.json`, and `--quantization` is normally auto-detected from it.

This does **not** break fit scoring, because M3 computes fit from
`sizeBytes` and says so: *"Fit is computed from `sizeBytes`, which is
authoritative."* A 4-bit AWQ 70B measures 35 GB on disk and scores as
35 GB. Nothing to change.

What is thin is *display*: such a model shows no quant information in the
library while a GGUF beside it shows a tier. Named, not fixed — it is a
metadata-reading change in the library with no contract consequence, and
M4 has no business growing one.

---

## 2. Readiness, redefined by meaning

The adapter contract already has the right shape — `engines/base.py`
returns a sum type of `NotAnswering | Loading | Ready`, and the comment
explains that this is *"most of why readiness is per-adapter"*. What needs
fixing is that two of the three outcomes are described in terms of one
engine's behaviour.

The definitions M4 needs:

| Outcome | Means | llama.cpp | vLLM |
|---|---|---|---|
| `NotAnswering` | the process is not yet serving *and* we cannot tell why | before the socket is up | — |
| `Loading` | the engine is alive and working, and is not servable yet | `/health` → 503 `loading model` | process alive, connections refused |
| `Ready` | servable | `/health` → 200 | `/health` → 200 |

The single behavioural change: **for an engine that does not answer while
loading, "the process is alive and nothing answers" *is* `Loading`.** It
is not an inference or a guess — there is no other thing it could be. The
supervisor holds the pid, so it can say this and a network probe cannot.

That leaves `NotAnswering` meaning what it should have meant all along:
*we have no information*. For vLLM it is reachable only in the moments
between spawn and the first probe.

Which raises the question `Loading` was invented to answer — the operator
staring at a dashboard needing to tell "working on it" from "wedged". With
llama.cpp the engine answers that itself. With vLLM it has to come from
somewhere, and the two candidates are not equal:

- **A startup budget, per adapter.** Alive and silent inside the budget is
  `loading`; past it, still `loading` but flagged, with the elapsed time
  and the captured output as the evidence. vLLM's budget is minutes, not
  seconds — `torch.compile` and CUDA graph capture are the bulk of it, and
  `--enforce-eager` is the curated flag that trades throughput for a much
  shorter start.
- **Scraping the engine's log lines.** vLLM narrates its progress and the
  supervisor already captures child output line by line. Rejected for the
  readiness *decision*: log formats are not a contract, they change
  between minor versions, and a readiness state that silently stops
  working on upgrade is worse than a coarse one that does not. The
  captured output is still shown to the operator — it is evidence, not a
  state machine input.

**Do not implement readiness for vLLM as a TCP connect, and do not give
the probe a long HTTP timeout.** A long timeout on an engine that refuses
connections just makes each poll slow; the probe wants a short timeout and
a wide budget, which are different knobs.

---

## 3. Discovery, and the curated flag surface

### Discovery

Precedence gains one rung, and `Origin.configured` gains a second source:

```
explicit RuntimeSpec.binary   >  configured (per engine, new)  >  managed  >  PATH
```

The new rung is a agent config field, `vllmBinary`, of type
`file_path`. A config field rather than a new endpoint on purpose: the
generic editor renders it with no engine-specific UI code, which is the
same rule that made `flagSchema` a `ConfigSchema`, and
`gui-equality-for-configurable-things` says a tunable thing is a UI
field. The pattern generalises as `<engine>Binary` if a third driven
engine ever arrives.

It points at the **`vllm` console script inside the operator's venv**, not
at a Python interpreter and not at a venv directory. A console script's
shebang binds it to its own interpreter, so nothing needs activating and
the argv stays a plain `[binary, "serve", ...]`. `managed` stays empty for
vLLM forever, and `available: false` keeps the meaning M1 gave it — "no
binary discoverable on this host" — with `manualInstall` now saying what
to do about it.

### The flag surface

Curated, on M0's terms: what a person actually turns, with `extraArgs` for
the rest. Model path, host, port and `--served-model-name` are the
adapter's, not the operator's, and are not in this table.

| Field | Flag | Why it is worth a form field |
|---|---|---|
| `maxModelLen` | `--max-model-len` | The context window, and the number every fit verdict in M3 is computed against. The direct analogue of llama.cpp's `contextSize`. |
| `gpuMemoryUtilization` | `--gpu-memory-utilization` | vLLM preallocates a *fraction of the card* (default 0.92) rather than counting layers. This is the flag that decides whether a second runtime fits on the same GPU, and it has no llama.cpp counterpart. |
| `tensorParallelSize` | `--tensor-parallel-size` | Shards one model across N GPUs in one process. Distinct from replicas — see below. |
| `pipelineParallelSize` | `--pipeline-parallel-size` | The other axis, for models too large for TP alone. |
| `maxNumSeqs` | `--max-num-seqs` | Concurrent sequences: vLLM's name for the capacity unit `RuntimeCapabilities.parallelSlots` already models. |
| `maxNumBatchedTokens` | `--max-num-batched-tokens` | The throughput/latency knob operators reach for after `maxNumSeqs`. |
| `dtype` | `--dtype` | `auto` is usually right and `float16` is the standard workaround for a card without bf16. |
| `quantization` | `--quantization` | Auto-detected from `config.json` in the normal case; needed explicitly for the ones that are not. |
| `kvCacheDtype` | `--kv-cache-dtype` | `fp8` roughly halves KV cache at long context — the single biggest fit lever vLLM has. |
| `enforceEager` | `--enforce-eager` | Skips CUDA graph capture and `torch.compile`. Costs throughput, buys a much shorter start, and is the first thing to try when startup itself is the problem. §2. |
| `trustRemoteCode` | `--trust-remote-code` | Required by a real share of HuggingFace architectures. Executes code from the model directory, so the UI must present it as what it is. |
| `tokenizer` | `--tokenizer` | For a model directory whose tokenizer lives elsewhere. |

**Tensor parallelism is not replication, and both are supported.**
`tensorParallelSize: 2` is one runtime, one model, two GPUs, one process.
Two replicas is two runtimes, each pinned with `CUDA_VISIBLE_DEVICES` via
`RuntimeSpec.env` — which is already why `env` exists on a runtime
("accelerator selection […] is how a runtime is pinned to one GPU, which
is what makes two replicas on two cards possible"). M5's load balancing
divides work across the second shape and must not be confused by the
first: TP reports as one backend because it is one.

---

## 4. The routing gap, closed here

M2 left a gap and named it plainly: **launching a model does not make it
routable.** The gateway builds its routing table from the drivers, and
nothing points a driver at a port the agent only chose at launch — so
the model loads, serves, and is unreachable, with `gateway /v1/models`
returning `[]`. Closing it by hand is one PATCH of a driver's `baseUrl`
plus a restart.

It moves into M4 (decided 2026-09-09) for three reasons. M4 is the first
milestone with two engine kinds, so the manual PATCH stops being a
one-off. The fix is a contract change on the driver, and M4 is already
changing engine and driver contracts — one re-pin instead of two, which is
the trade M1 made for its drift fixes. And the acceptance run this
milestone is *deferring* would otherwise have had to document the
workaround twice.

The contract already describes the fix. `RuntimeSpec.name` has said since
M0 that it is *"referenced by an inference-driver's config to say which
runtime it fronts"* — and no driver config field does that. So:

- **`runtimeName`** on the driver's config. When set, the driver resolves
  its backend URL from the agent topology by runtime name instead of
  using a literal `baseUrl`. `runtimeName` wins when both are set;
  `baseUrl` stays for every backend that is not a supervised runtime — a
  cloud provider, a remote LM Studio, an engine someone else runs.
- **`ConfigValueType.runtime_name`**, so the generic editor renders it as a
  dropdown sourced from the agent's `GET /v1/runtimes`. The existing
  `componentKindHint` cannot do this job: a runtime is deliberately not a
  component, and `/v1/components` does not list one.
- **`DriverInfo.runtime`** echoes it, and **`DriverHealth.runtime`**
  carries it up, so the gateway and the UI can show which engine process a
  driver is actually fronting.

**The real win is not saving a copy-paste.** The agent assigns the
port when the operator does not pick one, so a literal `baseUrl` encodes a
number the operator was never told and does not own. Following a runtime
by *name* means the driver survives whatever the supervisor does with
ports. A hand-typed URL is not just tedious, it is wrong the moment the
thing it points at moves.

**What stays out: who creates the driver.** Nothing here auto-provisions
one. After M4, wiring a launched model to the gateway is picking a runtime
from a dropdown; before it, it was hand-typing a URL and a port. Whether a
driver pool is declared by the wizard or a driver is created per launch is
routing policy, and that is still M5 — unchanged from M2's reading of it.

---

## 5. Contract

```
common.yaml
  EngineKind              + vllm
  ConfigValueType         + runtime_name                             §4

agent.yaml
  EngineAcquisition       + policy: managed | manual
                          + manualInstall: ManualInstall?
  ManualInstall             docsUrl, command?, notes?        (new)    §1
  EngineDescriptor        + python: PythonEngine?
  PythonEngine              interpreter, pythonVersion?,
                            packageVersion?, torchVersion?,
                            accelerator?                    (new)    §1
  FrameworkAccelerator      none|cuda|rocm|xpu|metal|unknown (new)   §1
  RuntimeStatus             loading / starting redefined by meaning   §2
  RuntimeSpec.modelAlias    resolved value always sent to the engine  §1
  EngineDescriptor
    .modelFormats           the "until vLLM lands" sentence is stale
    .version                for a Python engine, read from metadata   §1
    .origin                 `configured` is now also install-wide     §3
  /v1/engines/{engine}/install
                            a `manual` engine always 422s

inference-driver.yaml
  DriverInfo              + runtime: string?                          §4
  config prose            + runtimeName, and its precedence           §4

gateway.yaml
  DriverHealth            + runtime: string?                          §4
  (drift) two prose references to `DriverEntry`, deleted at the strip
```

`policy` is an enum beside `installable` rather than folded into it
because they answer different questions. `installable: false` on
llama.cpp means *not on this host* — Linux + NVIDIA, where a build exists
for other hosts. `policy: manual` means *not by us, anywhere*, which is a
property of the engine. The UI needs to render an install button in the
first case and instructions in the second, and inferring that from a
false boolean would be guesswork.

`PythonEngine` exists for the reason `ManagedEngine.variant` exists —
recorded because it is the answer to "why is this slow" often enough to be
worth surfacing. A venv holding a CPU-only PyTorch looks identical from
the outside to one holding a CUDA build, and runs orders of magnitude
slower. `torchVersion` and `accelerator` are that variant, for an engine
whose build is a property of its environment rather than of a filename.

### Re-pin radius: all five, and not for the reason it looks like

**Agent, gateway, inference-driver, library and `ui` all re-pin** —
M2's radius, for M1's reason: one bump carries both halves of the
milestone.

**There are five codegen consumers, not four**, and an earlier draft of
this section said four. `ui` generates TypeScript from all four spec
documents via `openapi-typescript` (`scripts/codegen.mjs`), so a
`common.yaml` change reaches it exactly as it reaches the Python
consumers. Counting the Python ones is the same mistake as counting
`$ref`s, one level up.

The interesting part is *why*, because reference-counting gets it wrong
and this was checked rather than reasoned about. `EngineKind` is named by
`agent.yaml` and `library.yaml` only; the gateway and the driver
reference it zero times. The natural conclusion — that adding `vllm`
leaves those two byte-identical, M3's shape exactly — **is false.** With
`vllm` added and nothing else, the gateway's generated models still
change.

`datamodel-code-generator` emits **every schema in the components
document**, not the reachable subset: the gateway's generated module has
carried an unused `EngineKind` and `ModelFormat` since M0. So *any*
`common.yaml` change re-pins every consumer, referenced or not.

This refines M3's note rather than contradicting it. M3's radius genuinely
was two — but not because the schemas it touched went unreferenced.
Because it touched only `library.yaml`, which is a separate top-level
document. The rule that survives is the one M3 already stated, and it is
the only reliable one: **generate both sides and diff them.** Counting
`$ref`s looks like the same check and is not.

Verified for this milestone: all four spec documents validate under
`openapi-spec-validator` 0.8.5 and lint clean under `@redocly/cli`
2.51.2, and all four generate importable Pydantic v2 models. `ui`'s
TypeScript generation was **not** exercised, which is the gap that hid
the fifth consumer. The one
generated-name collision the new schemas introduced — a second inline
`accelerator` enum arriving as `Accelerator1` — is why
`FrameworkAccelerator` is a named schema rather than an inline enum.

---

## 6. Scope

**In:** the vLLM adapter (discovery including the install-wide override,
argv, readiness, curated flag schema), `manualInstall` and the refusal
that names a command, the `PythonEngine` surface, the readiness
redefinition, the routing-gap fix end to end (driver config, `DriverInfo`,
`DriverHealth`, the UI's runtime dropdown), and fixture-level tests for
all of it.

**Out:**

- **A managed vLLM install.** Decided, not deferred — §1. Revisit only if
  upstream ships something installable that is not a Python environment.
- **The live acceptance run.** Decided 2026-09-09: no Linux host exists.
  This is the first milestone since M0 without one, and §1's status note
  says so where someone will read it.
- **vLLM-Metal.** A separate upstream project with its own wheels. If it
  is ever supported it is a question of whether it is the same adapter,
  and there is nothing to answer that with today.
- **GGUF through vLLM** — §1, Trap 3.
- **`--api-key` on a runtime.** Engines bind loopback because they have no
  auth of their own, and reaching a model from elsewhere is the gateway's
  job. Setting a key would mean threading a secret from a runtime
  declaration into a driver's config to buy nothing on a loopback socket.
  `extraArgs` covers the operator who wants it anyway.
- **Consuming `/load`,** and load balancing generally. M5.
- **Auto-provisioning a driver per launch.** M5, unchanged — §4.
- **Multi-node vLLM.** TP and PP *within one host* are in. A Ray cluster
  across hosts is a different supervision model and is not this.
- **TPU, AWS Neuron, s390x and the hardware-plugin matrix.** Upstream
  supports more targets than this project has any way to test.

---

## 7. Risks

- **Nothing here has met a running vLLM.** Stated first because it is the
  biggest one and because every prior milestone's worst defects came from
  a live run — M1's `--version` format, M2's snapshot-hash model names,
  M3's four hub defects. Most exposed: the readiness timing in §2, whether
  a `/health` 200 truly means servable, and whether the §3 flag names
  match 0.29.0 exactly. Treat the flag table as needing `vllm serve
  --help` run against it before anyone relies on it.
- **vLLM's CLI churns faster than llama.cpp's.** The V0→V1 engine
  migration deprecated a pile of flags, and this research watched
  `vllm.entrypoints.openai.api_server` become a deprecation shim for
  `vllm.entrypoints.launchers.api_server` — the module we read the startup
  ordering out of is itself newly moved. **Depend on the console script
  and on HTTP, never on a module path.** M1's rule applies unchanged: fail
  loudly and legibly, naming what was tried, and never fall back to
  something plausible.
- **The Python-version pins are unfixable from our side.** ROCm and Intel
  XPU need 3.12. If the operator's venv is 3.13 we can only report it,
  which is an argument for `PythonEngine.pythonVersion` being visible in
  the UI rather than only in a log.
- **Startup time is a first-impression problem.** A large model behind
  `torch.compile` and graph capture can sit unservable for minutes. §2
  makes that legible instead of alarming; if the UI renders it as a
  spinner with no elapsed time, the design has been implemented and the
  problem has not been solved.
- **The Windows dev/prod gap is now total for this engine.** The main
  design doc lists dev/prod platform mismatch as a standing risk; for
  llama.cpp it was a difference of build, and here it is the difference
  between running and not running at all. Every future change to this
  adapter carries the same caveat as this document until a Linux host
  exists.

---

## 8. Implementation notes (2026-09-09)

The adapter and the routing fix landed the day after the contracts:
agent `53d815d` (`engines/vllm.py`, the readiness redefinition in
`engines/base.py`, `vllmBinary`), inference-driver `97f6583`
(`runtimeName` resolution), gateway `5ad5993` (`DriverHealth.runtime`).
`EngineKind.vllm` is gone from the agent's `CONTRACTED_WITHOUT_ADAPTER`,
which was the proof the milestone asked for. No spec document changed:
every field the implementation needed already existed at `73ddc83`.

**At the time this section was written, no vLLM process had run** — the
dev box was Windows with no WSL, so the state machine was tested against
a fake process handle and a fake HTTP probe and §2's wall-clock
behaviour was a design estimate. That held until 2026-09-10; **§9 below
is the live run**, and it changed nothing here.

### What was checked against v0.29.0 source, and where

Each claim below was read off the tagged tree (`gh api` on
`contents/<path>?ref=v0.29.0`, base64-decoded), not off a summary.

| Claim | File | What was found |
|---|---|---|
| All twelve curated flags exist | `vllm/engine/arg_utils.py` `add_cli_args` | Each is an `add_argument` over the matching config field: `--max-model-len` (916), `--gpu-memory-utilization` (1272), `--tensor-parallel-size` (1108), `--pipeline-parallel-size` (1070), `--max-num-seqs` (1596), `--max-num-batched-tokens` (1582), `--dtype` (902), `--quantization` (917), `--kv-cache-dtype` (1277, over `CacheConfig.cache_dtype`), `--enforce-eager` (925), `--trust-remote-code` (900), `--tokenizer` (897), `--served-model-name` (953) |
| Booleans take no value | `arg_utils.py` `_compute_kwargs` | `bool` fields become `argparse.BooleanOptionalAction`, so `--enforce-eager` / `--no-enforce-eager`; presence-only is right |
| The model is positional | `vllm/entrypoints/cli/serve.py` | `vllm serve [model_tag] [options]`; `cmd()` copies `model_tag` onto `args.model`, and `--model` is hidden from `vllm serve --help`. The adapter uses the positional |
| Enum literals | `vllm/config/model.py`, `cache.py` | `ModelDType = auto, half, float16, bfloat16, float, float32` (used verbatim). `CacheDType` at 0.29.0 also has `fp8_inc`, `fp8_ds_mla` and four `turboquant_*` values; the schema exposes the six common ones and leaves the rest to `extraArgs` |
| `gpu_memory_utilization` default 0.92, per instance | `cache.py:111` | Confirmed, and the docstring says two instances on one card can each take 0.5 — which is what the flag description now says |
| `max_model_len` accepts `auto` / `-1` | `model.py:214` | New since the design was written; reachable through `extraArgs`, noted in the field description |
| Bind before listen | `vllm/entrypoints/launchers/launcher.py` | `create_server_socket` (205) calls `sock.bind()` (218) and returns; `setup_server` (248) creates it citing issue #8204 (264). Unchanged from §1 |
| `/health` is 200-empty or 503 | `serve/instrumentator/health.py` | 503 **only on `EngineDeadError`** — see the first departure below |
| `/version`, `/load` | `serve/instrumentator/basic.py` | `{"version": ...}`; `/load` lists sixteen tracked routes at 0.29.0, not eleven |
| Probe needs no credential | `serve/middleware/authenticate.py` | `GUARDED_PREFIX = ("/v1", "/v2", "/inference", "/cohere")`, unchanged |
| `/v1/models` carries the context | `entrypoints/openai/models/serving.py:66-71` | `ModelCard(id=..., max_model_len=..., root=<model path>)` — so `contextLength` is read back, and note `root` leaks the path regardless of `--served-model-name` |
| Install commands | `docs/getting_started/installation/*.inc.md` | Copied verbatim into `manual_install_for`: CUDA `uv pip install vllm --torch-backend=auto`; ROCm via `wheels.vllm.ai/rocm/`, **Python 3.12 only** with a silent fallback to the CUDA wheel otherwise; XPU nightly with two indexes; CPU release wheels by URL with `${VLLM_VERSION}`; Apple → vLLM-Metal; Windows → WSL |

### Where the implementation departs from, or refines, this document

1. **vLLM's `/health` 503 is not `loading`.** §2's table is right that
   vLLM's load reads as "process alive, connections refused" — but a
   *503* from vLLM is `EngineDeadError`: the API server is up and the
   engine core behind it has died. The adapter maps it to
   `NotAnswering(reached=True)`, which reports `starting` until the
   process exits and the supervisor says `crashed`. Reading it as
   llama-server's 503 would have shown a dead engine as "working on it".
2. **`NotAnswering` grew `reached`, `Loading` grew `past_budget`.** The
   first separates "the port refused" (the only thing that can be a
   silent load) from "something answered, just not readiness". The
   second is how §2's "still `loading` but flagged" surfaces: the
   status stays `loading` and `Runtime.lastError` carries the elapsed
   time and a pointer at the captured output. The contract already
   listed "a readiness probe that never passed" as a `lastError` source,
   so no schema change.
3. **The rule lives in one function.** `interpret_readiness(adapter,
   outcome, process_alive, elapsed)` in `engines/base.py`; the
   supervisor calls it after every probe with the pid and the time since
   spawn. `probe_readiness` stays a pure network observation, which is
   what makes it testable with a mock transport and what keeps the
   design's split honest: the probe cannot know the pid, so it does not
   pretend to.
4. **Version through the interpreter, not a file glob.** §1 Trap 4 said
   "the venv's `vllm-*.dist-info` answers it with a file read". The
   adapter instead runs the shebang's interpreter with `-I -c` and
   `importlib.metadata`. Same information, same constraint honoured
   (nothing of vLLM or torch is imported), but layout-agnostic — venv,
   uv, conda and `--user` installs all put `site-packages` somewhere
   different, and the target interpreter is the one authority on what it
   sees. One small subprocess per discovery, the same cost class as
   llama.cpp's `--version` probe.
5. **An untagged torch is `unknown`, and that will be common.** PyPI
   forbids PEP 440 local versions, so PyPI's default Linux wheel — a
   CUDA build — reports a bare `2.9.0`, as does the CPU-only macOS
   wheel. Only wheels from `download.pytorch.org` carry `+cu129` and
   friends, which is what `uv --torch-backend=auto` fetches. So a plain
   `pip install vllm` will show `accelerator: unknown` and that is the
   honest answer; `none` would claim an absence the data does not
   support.
6. **vLLM inherits the agent's cwd.** The base default of "the
   binary's own directory" exists for prebuilt llama.cpp with its
   shared libraries; a console script has no such need and `<venv>/bin`
   is a strange place to leave relative-path output.
7. **"At startup and again whenever it reconnects"** (§4, the driver)
   is implemented as *whenever the engine is constructed*: the lifespan,
   `/v1/admin/restart`, and `/v1/config/test` (so a pending
   `runtimeName` can be checked against the agent before it is saved).
   There is no per-request re-resolution, because the port is assigned
   and persisted at declaration time and does not change across the
   runtime's restarts. Consequence worth knowing: **a driver written
   before its runtime exists comes up degraded** (404 from the agent,
   reason on `/healthz`, config endpoints reachable) and resolves on the
   next restart. The acceptance script encodes that order on purpose.
8. **The driver finds the agent at loopback:8079** by default
   (`EUGENE_PLEXUS_DRIVER_AGENT_URL`), the same bootstrap assumption the
   gateway has made since M0. The agent does not thread its own URL into
   the children it spawns; if an agent ever binds only a non-loopback
   address, that is the fix, and it is the same fix for both consumers.
9. **`baseUrl` is no longer `required`** on the driver's schema; one of
   `runtimeName` / `baseUrl` is, and the engine says so when neither is
   set. A stale `runtimeName` on a CLI provider is ignored with a warning
   rather than failing a subscription-backed driver over a field the UI
   would not have shown it.
10. **The UI's runtime dropdown is not built.** `ConfigField.tsx` falls
    through unknown value types to a free-text input, so `runtimeName`
    is editable today by typing the name. §4/§6 asked for a dropdown
    sourced from `GET /v1/runtimes`; that is a `ui`-repo change with no
    contract consequence and is the one piece of §6's "In" list left
    undone.

## 9. The live run (2026-09-10) — passed, and what it revised

**`scripts/m4-acceptance.sh` ran for the first time on 2026-09-10 and
passed: 31 checks, zero failures.** Full record, with the numbers and
the four script defects it earned, in
[`docs/acceptance/m4-vllm-run.md`](../acceptance/m4-vllm-run.md). The
host was WSL2 — Ubuntu 26.04, Python 3.14.4, RTX 5090, vLLM 0.29.0 on
torch 2.13.0+cu132 — which is a genuinely separate kernel, network
namespace and filesystem, and is what finally unblocked four
milestones of "vLLM has nowhere to run".

**The adapter needed no change.** Every claim §8 recorded as
read-off-source-but-unobserved held. The three that mattered:

- **§2's readiness rule is confirmed.** Every probe of the engine's own
  port during the load was refused — 14 of 14 on the short path, 67 of
  67 on the long one — and not one accepted-and-hung. So "process alive,
  connections refused" is the only signal there is, and
  `interpret_readiness` reading it as `loading` from the process handle
  is the only thing it could be, not a guess.
- **Every curated flag name is accepted**, echoed back verbatim in
  vLLM's own `non-default args` startup line.
- **`/health` 200 means servable and `/v1/models` carries
  `max_model_len`**, so `contextLength` is read back as asked.

### The budget: 600 stays, for a different reason

| | `loading` lasted |
|---|---|
| `enforceEager: true` | 15s, 16s on a re-run |
| `enforceEager: false` | 72s — 13.7s compiling, 39s capturing CUDA graphs |

Both are *warm-cache* numbers, and the load the budget exists for is the
cold one: `init engine (profile, create kv cache, warmup model)` took
**23.45s the first time and 3.25s the next**, for the identical command
line, because vLLM caches JIT and warmup products under `~/.cache/vllm`
and `~/.triton`. A 0.6B on a 5090 takes 40s to `ready` on its first ever
start. `STARTUP_BUDGET_SECONDS` only decides when a still-loading
runtime gets *flagged* on `Runtime.lastError`, so generosity is cheap
and tightness would flag every first launch of a large model.

### §1's framing needs one correction

The design says the unit of installation is a Python environment, and
that CUDA-version matching is not the hard part. Both held —
`uv pip install vllm --torch-backend=auto` resolved `torch 2.13.0+cu132`
against a 610.47 driver in under two minutes, all wheels, no source
builds, on Python **3.14**, which the ROCm-only 3.12 note had made look
riskier than it is.

**What it missed is that vLLM compiles at first use, not at install.**
The unit of *operation* is a Python environment **plus a C toolchain
plus the interpreter's dev headers**. Four preconditions the install
command does not check, each of which killed the engine 20-40s into a
load with a traceback that never named the fix: pinned memory disabled
by default on WSL2 (`VLLM_WSL2_ENABLE_PIN_MEMORY=1`, upstream's own
switch, kernel floor 4.19.121) which 0.29.0's model runner hard-requires
via UVA; `build-essential` and `python3-dev` for Triton's CPython
extension; and a CUDA toolkit for FlashInfer's *sampling* kernels —
attention picked prebuilt FlashAttention 2 and was never the problem —
or `VLLM_USE_FLASHINFER_SAMPLER=0` instead. Only the first is
WSL-specific. **`RuntimeSpec.env` carried all of it with no contract
change**, which is what that field is for.

### The host defaults, decided and built (2026-09-11)

**Decided by Troy, as a general rule rather than a one-off:** default to
whatever makes the thing work for someone with no technical knowledge,
and always leave an expert a way to take the wheel. Applied here, that
splits the four preconditions in two.

**The two an environment variable fixes are now the agent's job.** New
`EngineAdapter.default_env` (agent `532be74`), applied with `setdefault`
semantics against the ambient environment and then overridden by
`RuntimeSpec.env`. vLLM supplies `VLLM_WSL2_ENABLE_PIN_MEMORY=1` on
WSL2 and `VLLM_USE_FLASHINFER_SAMPLER=0` when no `nvcc` is visible.
Three levels of control, in order: the runtime's own `env` wins
outright — including with a value that will fail, which is an expert's
prerogative; an exported shell variable wins next, so nobody debugging
from a terminal fights an invisible default; and otherwise ours applies
**and is logged**, because an environment variable nobody typed makes a
later bug report unreadable.

Only one of the two is a real trade. Pinned memory on WSL2 is free —
upstream's own default exists for a small performance regression that
0.29.0's model runner then makes moot by requiring the feature anyway.
The FlashInfer sampler genuinely costs a little throughput on large
batches, and it is still right, because what it is traded against is not
starting. It also reverts itself the moment a toolkit appears, since the
default is computed per launch rather than remembered.

**Proved rather than asserted:** `scripts/m4-acceptance.sh` now declares
**no** `env` on its runtime, so a green run is a test of the injection.
It passed — 32 checks — on a host with no toolkit, with
`VLLM_USE_FLASHINFER_SAMPLER=0, VLLM_WSL2_ENABLE_PIN_MEMORY=1 set by the
vllm adapter as this host needs it` in the log and `ready` at t+22s.

**The two no variable can fix are explained, not refused — and the
obvious design was wrong.** The plan was to preflight the host's
toolchain and refuse the launch early with the apt command. Measured
first: a host whose Triton cache is already warm runs vLLM with
`CC=/nonexistent` and served a completion in 19.9s, because Triton
caches the compiled CPython extension under `~/.triton` and only builds
on a miss. So a refusal on a missing compiler would have rejected a
launch that works, on **any host that has run the engine once** — a
false refusal, which is worse than a bad error message. Instead
`SpawnPlanner.explain_exit` gets a bounded tail of the engine's own
output on a non-zero exit, and the vLLM adapter turns the four known
signatures into a sentence naming the fix. `exited with code 1` was what
the operator used to get. **Explaining a real failure cannot be a false
refusal**, which is the whole reason it reads output afterwards instead
of probing beforehand.

One implementation mistake worth keeping, because the test hid it: the
first cut put `explain_exit` on `EngineAdapter` and had the supervisor
ask the *planner* for it through `getattr`, so it silently never fired —
and the test meant to prove otherwise asserted the adapter's own method
while being **named** as though it proved the wiring. `mypy` caught the
`Any`; the misleading test is the part that would have cost a day. Same
family as the socket instrument above and the teardown check in the
two-host run: **a test or a check whose subject is not where it is
looking will report confidently on the wrong thing.**

### Process notes from the build

- The parity test worked exactly as intended: registering the adapter
  made `test_the_contracted_without_adapter_list_is_honest` fail until
  the entry was deleted. Empty is the steady state again.
- Two test stubs had to learn the new `discover(configured=)` /
  `resolve_binary(spec, configured=)` signatures. The end-to-end test's
  fake adapter had the old one, and the failure mode was silent: a
  `TypeError` inside `plan()` killed the supervision task and the
  runtime sat at `starting` forever. The supervision loop catches only
  `SpawnPlanError`; an unexpected exception from a planner is a latent
  robustness gap, noted here and not fixed in this slice.
- The agent's venv (the install's runtime venv) turned out to hold a
  torch — an assertion that "this venv has no torch" was wrong on this
  box, and the test now asserts consistency instead of absence.
- `str(Path("/opt/venv/bin/python3.12"))` on Windows is
  `\opt\venv\bin\python3.12`, and `repr()` of a Windows path doubles its
  backslashes. The interpreter is carried as the shebang's literal
  string and error messages interpolate paths unquoted, so the same
  code reports the same thing on both platforms.
