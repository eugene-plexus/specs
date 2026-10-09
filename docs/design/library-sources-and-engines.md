# Library: many model sources, many engines

**Status: proposed 2026-10-09; calls L1-L11 are Troy's.** Nothing here is
built. Troy (2026-10-09), after installing Strata on Amish_Station and finding
a GGUF profile offered llama.cpp alone: *"We have introduced a separation
between installing the engine and installing the model through the Library.
I think it makes sense to keep that separation, but that also means our
library's Discover page, etc, needs to be able to show and distinguish between
models that work with an installed Engine, and those that do not. [...] For a
system that may have dozens of supported engines in the future, each with
their own file types and each coming from different sources, this seems like
the perfect place to pause and alter the design of the Library."*

## 1. What exists (mapped 2026-10-09)

- **One remote source:** a Hugging Face-compatible hub (`library/.../hub.py`).
  Discover searches it with the format filter defaulting to GGUF
  (`ui/src/app/discover/page.tsx:109`). The curated starter list
  (`starter_models.yaml`) is GGUF-only, and its monthly review's only proof
  that a model runs is that llama.cpp's `llama-arch.cpp` names the
  architecture (`starter_review.py:392-420`).
- **One join:** `ModelFormat` (`gguf | safetensors | kev_checkpoint`,
  `common.yaml:653`) against each adapter's `model_formats`. The contract
  calls it "a first filter". The one finer rule, MLX-quantized safetensors
  run only on MLX, is written twice by hand: `ui/src/lib/engineCompat.ts:28`
  and `agent/.../run_worker.py:244`.
- **Discover knows no engines.** No page under `app/discover` reads
  `/v1/engines`. A safetensors candidate cannot be told MLX from vLLM before
  download, because the detail view never reads the remote `config.json`.
- **Fit is llama.cpp's arithmetic** (`library/.../fit.py`), reused by
  admission for vLLM and MLX; Strata is always unknown.
- **Strata models are not Library entries.** The scanner ignores `.json`; the
  adapter claims no formats; *Add prepared Strata model* posts a runtime
  straight to the agent with no profile (`ExperimentalModels.tsx`). The
  ISTA-DASLab GGUFs Strata starts from would be offered to llama.cpp as
  ordinary GGUFs.
- **Engine choice on Run is registry order** (llama_cpp, vllm, mlx, kev,
  strata), not capability or preference.

Strata's design left exactly this open (`strata-engine.md:82`): *"Strata must
not be offered for every GGUF: check supported architecture, quant and
prepared artifacts on the agent as well as in the UI. Decide the shared
eligibility representation before codegen."* The experimental-engine policy
already requires prepared artifacts to stay usable without the Library
parsing them (`experimental-engines.md:126-132`).

## 2. What stays

- **Engines and models install separately** (Troy). An engine's install never
  downloads a model; a model's download never installs an engine.
- **Plain files in the person's own folders**, no managed store
  (`local-inference-control-plane.md` #3). A prepared model is files too.
- **We wrap upstream.** An engine's rules about what it loads, and its
  preparation tools, are the engine's; Eugene states them, never reimplements
  them.
- **Settings never lie; failures name their cause.** A verdict nobody can
  make before loading is shown as unknown, never as "runs".

## 3. The words

| Word | Meaning | Examples |
| --- | --- | --- |
| **Source** | Where models are found | a Hugging Face hub; an engine's own list of supported models; a Library folder |
| **Artifact** | What is on disk | a GGUF with its shards and projector; a safetensors folder; a Kev checkpoint; a prepared bundle |
| **Requirement** | What one engine loads, declared by its adapter | llama.cpp: GGUF of an architecture its pinned build knows. vLLM: safetensors, not MLX-quantized, architecture checked by vLLM at load |
| **Preparation** | An engine-owned step from one artifact to another | Strata: GGUF to expert pack, lookup table and MTP helper. NInfer: a `.ninfer` file |
| **Verdict** | One model against one engine | `runs`, `after_preparation`, `may_run` (the engine decides at load), `no` (with why) |

## 4. The design

### 4.1 Engines declare what they accept

`EngineDescriptor` gains `accepts: ModelRequirement[]` beside `modelFormats`,
which stays for older consoles. One requirement is data, not code:

```yaml
ModelRequirement:
  format: gguf | safetensors | kev_checkpoint | prepared   # one new value
  architectures: [string]      # allow list; absent = any
  quantizations: [string]      # allow list; absent = any
  markers: {mlxQuantization: required | forbidden}        # the one rule today
  companions: [role]           # files that must sit beside it (projector, tokenizer)
  preparedFor: EngineKind      # format: prepared only
  preparation: {recipe: string, extraBytes?: int}         # runs after this step
  authority: eugene | engine   # engine = only a load can tell (vLLM's registry)
  preference: int              # among engines that run a model, lower first
```

The adapters fill it from facts they already hold. llama.cpp's architecture
list comes from its pinned build, as the starter review already extracts it.
The MLX marker moves from two hand-written copies into the declarations.
Strata declares a `prepared` requirement, plus a GGUF requirement (Qwen3.8
Flash-Next's architecture and the quantizations it supports) carrying
`preparation: strata-prepare`.

### 4.2 One evaluator, in the Library

The Library holds the metadata, so it judges: `POST /v1/eligibility` takes
models or catalogue candidates and the engines (descriptors as a node reported
them) and answers a verdict per pair, with the reason in words. The UI's
`engineCompat.ts` and the agent's `run_worker` both call it, so the MLX rule
lives in one place. `/v1/engines` already lists every adapter, installed or
not, so a verdict can name an engine this node lacks: *"runs on vLLM, which
is not installed on Amish_Station"*.

### 4.3 Discover shows verdicts

- **Each candidate** (a quant, a folder) carries chips: *Runs here:
  llama.cpp*; *After preparation: Strata, about 12 GB more*; *Needs vLLM
  (install it from Backends)*; *Nothing here runs this: ...*.
- **Search rows** get a cheap verdict from tags and format, marked
  approximate; the detail view gets the full one. For safetensors the detail
  reads the remote `config.json` (one Range read, as preflight does for GGUF),
  so MLX and vLLM are told apart before 20 GB is downloaded.
- **The format filter becomes an engine filter:** *Runs on Amish_Station*
  (default), *Any engine I can install*, *Everything*. GGUF stops being a
  default for its own sake.
- **Fit names its engine.** Fit becomes a per-engine answer; an engine with no
  fit model says *Fit not estimated*, never llama.cpp's number in its place.

### 4.4 Sources are a list

`catalogueSources` replaces the single hub setting: each source has an id, a
kind and its own settings (address, token, on/off). Kinds:

1. **`hf_hub`**: today's hub, and any mirror of it.
2. **`engine_list`**: models an engine's adapter publishes as supported, each
   pointing at hub files plus the preparation it needs. Strata's seven
   variants (IQ2_XS ... Unsloth UD-Q4_K_XL, Coder, Swift 1.5) are the first.
   The list ships with the adapter, so a new engine brings its own.
3. **Folders**, as today.

Discover searches the chosen sources together; every result says which
source it came from. Other kinds (ModelScope, the Ollama registry, a direct
address) fit the same list later; none is in this design's first slices.

### 4.5 Prepared models are Library models

A preparation, or a person adopting one made by hand, writes a small
provenance file beside the result: `<name>.eugene-prepared.json` with the
engine, the recipe and its version, the source model, and the engine's own
entry file (Strata's config JSON). It is a plain file in the person's folder.
The scanner reads it and lists a model of format `prepared`, linked to its
source. A prepared model then has profiles, a row, Run and switching like
any other. *Add prepared Strata model* becomes *Add a prepared model* on the
Library page, and the runtime-only path goes.

### 4.6 Preparation is a job on the engine's node

The adapter owns the recipe; the agent runs it where the engine is installed,
with the engine's own tools, writing into a Library folder; the Library
rescans. Before anything starts, it reports disk needed, and any
prerequisite that is missing. It shows progress and can be cancelled. Run
operations already chain download, profile and launch; preparation becomes a
step between download and launch. For Strata the recipe wraps upstream's
setup non-interactively, as the install does today. The original GGUF is
never altered.

## 5. Slices

| Slice | What | Repos |
| --- | --- | --- |
| **LS1** | `accepts` on every adapter; `POST /v1/eligibility`; the Library page and `run_worker` use it; the duplicated MLX rule goes | specs, agent, library, ui |
| **LS2** | Discover verdicts and the engine filter; remote `config.json` read for safetensors | library, ui |
| **LS3** | Prepared models in the Library (provenance file, scan, profiles); Strata's form moves there | specs, library, agent, ui |
| **LS4** | Sources as a list; `engine_list` with Strata's variants | specs, library, agent, ui |
| **LS5** | Preparation jobs, Strata first (the ~80 GB path in one action) | agent, library, ui |
| **LS6** | Fit per engine | library, agent, ui |

Each slice ends with the real-environment acceptance on Amish_Station with
llama.cpp and Strata installed; LS5's is Strata's owed real-model validation.

## 6. Calls for Troy

| # | Question | Recommendation | Main trade-off |
| --- | --- | --- | --- |
| L1 | When? | Settle the design now; build LS1-LS2 after v0.2.0 | LS1 changes the engine and Library contracts in four repos, against the stability release. Before v0.2 instead: Discover is right at release, and the release moves later |
| L2 | Where is eligibility judged? | The Library, one endpoint (§4.2) | Every judgment is a call to the Library; the agent's Run depends on it already |
| L3 | Rules as data, or a per-engine check the agent runs? | Data (`accepts`) | Data cannot express everything; `authority: engine` and `may_run` cover what only a load can tell. A code check per engine is flexible but chatty, and opaque to the UI |
| L4 | A verdict only a load can make | Shown as *may run (vLLM checks the architecture when it loads)* | Honest, but less definite than people expect |
| L5 | Discover's default | Everything that matches, runnable here first, with chips; filter *Runs on this machine* one click away | Defaulting to the filter hides what an engine you could install would run |
| L6 | Prepared models in the Library | Yes, through the provenance file (§4.5) | A new file beside the person's models; the alternative keeps every engine's prepared form outside profiles |
| L7 | Who publishes an engine's model list? | Its adapter, in the agent | The list then changes with an agent release, not a Library one |
| L8 | Where does preparation run? | On the agent with the engine installed, into a Library folder | A preparation can only run on a node with the engine, which is where its result runs anyway |
| L9 | `EngineKind` | Stays a closed enum | Each engine is a contract change, but each engine is also new adapter code in the same change |
| L10 | Which engine Run picks when several can | The adapter's `preference`, then the person's default per format in Settings | Today's registry order is invisible and nobody chose it |
| L11 | Fit for engines without a fit model | *Fit not estimated*; admission treats it as unknown, as Strata's is today | Fewer green badges until each engine gets a model |

## 7. Found while mapping (not part of this design)

Inferred from the code, not yet reproduced. Each goes in a GitHub issue on
the owning repo once confirmed:

- A safetensors candidate probably never shows *already on disk*: `_owned`
  compares a weights file name to the model path, which is the folder
  (`library/.../catalogue.py:328-332`).
- `tokenizer.model` is missing from the safetensors companion files
  (`catalogue.py:76-86`).
- A Kev repo downloaded through Discover probably does not scan (no
  `adapter_config.json` or `head.pt` in the companion list).
- A node's own model copy handles one file; shards, projectors and
  safetensors folders are not copied (`agent/.../model_copies.py`).
- Stale contract text: `common.yaml:689-691` says nothing serves safetensors
  yet; `run-operations.json` still calls MLX experimental.
