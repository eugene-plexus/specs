# Library: many model sources, many engines

**Status: calls L1-L11 taken by Troy 2026-10-09 (§6); v0.2.0 is LS1-LS6
(L1). LS1 built and pinned 2026-10-09 (§6.2); LS2 built and pinned
2026-10-09 (§6.3); LS3 next.** Troy (2026-10-09), after installing Strata on Amish_Station and finding
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
- **Three levels, one dot (L5, Troy).** Every model and candidate carries a
  dot with its words beside it (never colour alone), and a popover naming the
  engines and what to do:

  | Dot | Words (Troy's) | When |
  | --- | --- | --- |
  | green | *Will work on this machine now* | an engine installed here runs it as it is (`runs`, or `may_run`, whose popover says *may*) |
  | amber | *Will work with a different engine* | an engine this machine can run, but has not installed, runs it; or an installed engine runs it after preparation (popover: *Strata can run it after preparing it, about 12 GB more*) |
  | red | *Can not work on this machine* | no engine that can run on this hardware accepts it; or every engine that would accept it has a fit of `no` |

  Calls building made, for Troy's veto: preparation counts as amber (one
  more step, like an install); `may_run` counts as green with *may* in the
  popover; red includes *does not fit for any engine that would load it*,
  but never *fit unknown*. `tight` and `split` stay green, with the fit badge
  saying how it would run.
- **The format filter becomes a filter on those levels:** *Works here now*,
  *Works with another engine*, *Everything* (the default, ordered green,
  amber, red). GGUF stops being a default for its own sake.
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

**v0.2.0 waits for this work (L1).** Proposed bar: LS1-LS6, so Strata is
found, prepared, profiled, run and fitted from the console. LS5's
preparation needs Troy's go for the ~80 GB download when its acceptance
runs.

## 6. Calls (Troy, 2026-10-09)

| # | Question | Troy's call |
| --- | --- | --- |
| L1 | When? | **Before v0.2.0.** *"Move the v0.2 release until after, since using Strata was to be a noted feature of v0.2."* |
| L2 | Where is eligibility judged? | The Library, one endpoint (§4.2) |
| L3 | Rules as data, or a per-engine check the agent runs? | Data (`accepts`) |
| L4 | A verdict only a load can make | *May run*, for now; may be revisited |
| L5 | Discover's default | A dot with three levels (§4.3): *Can not work on this machine*, *Will work on this machine now*, *Will work with a different engine* |
| L6 | Prepared models in the Library | Yes, through the provenance file (§4.5) |
| L7 | Who publishes an engine's model list? | Its adapter, in the agent |
| L8 | Where does preparation run? | On the agent with the engine installed |
| L9 | `EngineKind` | Closed enum |
| L10 | Which engine Run picks when several can | The adapter's `preference`, then the person's default per format in Settings |
| L11 | Fit for engines without a fit model | Each engine owns its fit model; *Fit not estimated* until it has one; LS6 is in v0.2 (§6.1; approved with the v0.2 bar) |

### 6.1 L11: why llama.cpp's fit cannot stand in for every engine

- **Any GGUF on llama.cpp: yes, and it stays.** The Library reads the GGUF
  header (layers, KV heads, context, expert bytes) and computes a real fit.
- **A Hugging Face safetensors model on llama.cpp: no file to fit.**
  llama.cpp loads only GGUF; a safetensors folder must be converted first,
  and the result's size depends on the quantization chosen. The fit the
  Library reports for safetensors today is weights at their dtype plus a KV
  estimate, labelled an estimate, and is used for vLLM and MLX.
- **Other engines use memory differently, so llama.cpp's verdict is wrong for
  them in both directions:**
  - **vLLM** reserves a fixed share of each GPU up front
    (`gpuMemoryUtilization`, 0.9 by default) and fills the rest with KV cache.
    It does not spill to system RAM by default, and splits evenly across
    cards. llama.cpp's *split, experts in RAM* is *will not start* on vLLM.
  - **Strata** is built to keep every expert in RAM and a lookup table on
    the SSD. For its 125B model on a 32 GB card, llama.cpp's arithmetic says
    *no*; Strata's own table says IQ2_XS runs with 48 GB of RAM.
  - **MLX** on a Mac uses unified memory, of which macOS lets the GPU wire
    only part; neither VRAM nor RAM in llama.cpp's sense.
  - Admission today calls the same fit for vLLM and MLX as for llama.cpp, so
    their admission numbers carry this error now.

**Recommendation:** each engine owns its fit model, declared beside its
`accepts` (L3: data where it can be). llama.cpp keeps today's. vLLM's is the
next easiest (weights plus KV within its reserved share). Strata's comes from
its documented RAM-per-size table. Until an engine has one, it says *Fit not
estimated* and admission treats it as unknown. LS6 becomes part of the v0.2
work, not after it.

## 6.2 LS1 built (2026-10-09)

Record: [ls1-eligibility-run.md](../acceptance/ls1-eligibility-run.md), 11/11.

**Calls building made**, for Troy's veto:

- **B1.** The request and answer shapes live in `common.yaml`: the agent's Run
  calls the judge as well as the console.
- **B2.** The Library names engines only by kind; the console words them
  ("llama.cpp", "Strata"). Engine names stay engine knowledge.
- **B3.** A Library older than the judge answers 404, and Run and the console
  fall back to the format rule: a container root can lag its workers.
- **B4.** L10's per-format default in Settings is not built yet: no format has
  two engines that can both run it as it is on one machine (vLLM and MLX never
  share one; Strata's GGUFs need preparation). It arrives with the first that
  does; the adapter's `preference` orders Run now.
- **B5.** llama.cpp declares no architecture list yet, so any GGUF `runs`, as
  before. The pinned build's list (the starter review already extracts it)
  comes with LS2, where Discover judges remote models of new architectures.
- **B6.** `modelFormats` is the formats of the requirements needing no
  preparation, so an older console never offers Strata for every GGUF.
- **B7.** A list row shows the dot with short words (*works here*, *other
  engine*, *not here*); the model's page shows Troy's full phrase and each
  engine's reason.

**What building found:**

- `run-operations.json` copies `ModelFormat`'s description, so editing that
  description means regenerating the file from the Library's router and
  re-vendoring it into agent, library and ui.
- An enum `default` in the contract generated a plain-string default in
  Python that warned on every serialization; *absent means eugene* instead.
- library#7 (above, in the record).

## 6.3 LS2 built (2026-10-09)

Record: [ls2-discover-run.md](../acceptance/ls2-discover-run.md).

**Calls building made**, for Troy's veto:

- **B8 (B5 settled).** llama.cpp's architectures come from the build actually
  installed. Eugene installs upstream's newest build, not a pinned one, and
  the binary cannot be asked, so the agent reads that build's own
  `src/llama-arch.cpp` at its tag once, in the background, and keeps it
  beside the builds by tag (`<engine root>/llama_cpp/architectures/`). With
  it, an architecture the build does not name is *no*. Until then (not
  installed, not read yet, offline, a build with no tag) the agent declares
  the list it ships (`b11530`, 156 names, refreshed by
  `agent/scripts/llama-cpp-architectures.py`) as *runs* and anything else as
  *may run*: upstream adds architectures and does not drop them.
- **B9.** The Library makes each candidate's facts (`facts` on search rows,
  versions and starter entries) and the console sends them back unread, so
  no rule lives in the console (L2).
- **B10.** On a candidate an absent fact is *not known yet*: a term resting
  on it is at best *may run* (*after preparation* stays), the reason names
  what was assumed, and the answer is marked approximate. On a library model
  it stays *unreadable*, as in LS1.
- **B11.** A search row is judged from the same search call: the GGUF
  architecture from the hub's repo-level GGUF block, the MLX marker from the
  `mlx` tag, always approximate. A row's dot is its best format's.
- **B12.** A GGUF version's quantization is the name a file's own metadata
  would use (the scan's filename rule), so a publisher tier such as
  `UD-Q4_K_XL` is *not known* rather than a second vocabulary. No engine
  declares quantizations yet.
- **B13.** *Works here now* shows green only, *Works with another engine*
  amber only, *Everything* (the default) all, green then amber then red, the
  hub's order within each, rows with no verdict last. A filter whose engines
  load one format asks the hub for that format, so thirty results are not
  mostly hidden; what was hidden is counted beside *Show everything*.
- **B14.** The stored GGUF format preference is not carried over: it was a
  default, not a choice.
- **B15.** Rows and versions show the short words (B7); the suggestion cards
  Troy's full phrase; every dot opens each engine's verdict and reason.
- **B16.** A Library older than LS2 (422 on `candidates`) or LS1 (404): no
  dots, and a line saying every model is listed.
- **B17.** library#7 fixed in the Library: `local` (an unjoined agent's
  tokens) and `null` (its console) name one node, at submit and at claim.
  LS1's acceptance now submits `null`, as the console does.

**What building found:**

- **Upstream llama.cpp now names `qwen4exp`** (b11530): llama.cpp itself
  loads Qwen3.8-Flash-Next GGUFs, so on a machine with a current llama.cpp
  such a GGUF is green, with Strata's *after preparation* beside it. Whether
  it fits is LS6's question.
- The hub's `expand[]` replaces `full=true` rather than adding to it, so a
  search names every field it shows (`hub.SEARCH_FIELDS`); `siblings`, which
  no row used, is no longer fetched. A thirty-row search is about 230-340 KB
  between the Library and the hub (chat templates in the GGUF block), up
  from about 85 KB, and cached for 60 s.
- The hub's own `config` reports an MLX repo's quantization as
  `quantization_config: {bits}`, the key GPTQ and AWQ use too, so it cannot
  tell MLX apart; the detail call reads the folder's `config.json` instead.

## 7. Found while mapping (not part of this design)

Inferred from the code while mapping; settled during LS2:

- ~~A safetensors candidate never shows *already on disk*~~: fixed in LS2
  (matched on the first weights file inside the folder and the weights'
  size).
- ~~`tokenizer.model` is missing from the safetensors companion files~~: fixed
  in LS2.
- A Kev repo downloaded through Discover does not scan:
  [library#8](https://github.com/eugene-plexus/library/issues/8).
- A node's own model copy takes one file, so a split GGUF's copy is used
  without its shards: [agent#10](https://github.com/eugene-plexus/agent/issues/10).
- ~~Stale contract text~~: `common.yaml`'s safetensors line was fixed in LS1;
  MLX is no longer called experimental (LS2, and `run-operations.json` with
  it).
