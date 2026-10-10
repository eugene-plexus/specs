# Library: many model sources, many engines

**Status: calls L1-L11 taken by Troy 2026-10-09 (§6); v0.2.0 is LS1-LS6
(L1). LS1 built and pinned 2026-10-09 (§6.2); LS2 built and pinned
2026-10-09 (§6.3); LS3 built and pinned 2026-10-09 (§6.4); LS4 built and
pinned 2026-10-09 (§6.5); LS5 built and pinned 2026-10-09 (§6.6), with
Strata's real-model run; LS6 built 2026-10-09 (§6.7): v0.2's six slices are
done.** Troy (2026-10-09), after installing Strata on Amish_Station and finding
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
  *Works with another engine*, *Everything* (ordered green, amber, red).
  GGUF stops being a default for its own sake. The default was *Everything*
  until LS4; Troy then made it *Works here now* wherever an installed engine
  runs a hub's models as they are (§6.5, B39).
- **Fit names its engine.** Fit becomes a per-engine answer; an engine with no
  fit model says *Fit not estimated*, never llama.cpp's number in its place.
  Built in LS6 (§6.7).

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
never altered. Built in LS5 (§6.6).

## 5. Slices

| Slice | What | Repos |
| --- | --- | --- |
| **LS1** | `accepts` on every adapter; `POST /v1/eligibility`; the Library page and `run_worker` use it; the duplicated MLX rule goes | specs, agent, library, ui |
| **LS2** | Discover verdicts and the engine filter; remote `config.json` read for safetensors | library, ui |
| **LS3** | Prepared models in the Library (provenance file, scan, profiles); Strata's form moves there | specs, library, agent, ui |
| **LS4** | Sources as a list; `engine_list` with Strata's variants | specs, library, agent, ui |
| **LS5** | Preparation jobs, Strata first (the ~80 GB path in one action) | agent, library, ui |
| **LS6** | Fit per engine | library, agent, ui |
| **LS7** | A node runs a prepared model from its own copy of the Library's files (§6.8; agent#12, agent#10) | agent, ui |
| **LS8** | Delete a model from the Library, any format, with everything it owns (§6.8, Troy) | library, agent, ui |

Each slice ends with the real-environment acceptance on Amish_Station with
llama.cpp and Strata installed; LS5's is Strata's owed real-model validation.

**v0.2.0 waits for this work (L1).** Proposed bar: LS1-LS6, so Strata is
found, prepared, profiled, run and fitted from the console. LS5's
preparation needs Troy's go for the ~80 GB download when its acceptance
runs. Troy, 2026-10-09: LS7 and LS8 too, before v0.2.0 (§6.8), and then a cleanup
of every compatibility shim for versions before v0.2, which is the oldest
supported (*I do not value compatibility with v0.1*; specs#22).

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

## 6.4 LS3 built (2026-10-09)

Record: [ls3-prepared-run.md](../acceptance/ls3-prepared-run.md).

**Calls building made**, for Troy's veto:

- **B18.** The provenance file is the model's path, so it is also the
  runtime's `modelPath`; the agent reads its `entry` at every launch.
  Re-adopting a model with a new entry keeps its identity and profiles.
- **B19 (amended by Troy's principle, §6.8: a prepared model's files must be in a
  Library folder).** An absolute `entry` is a path on the node that runs the model,
  used as written; a relative one travels with its folder through the node's
  `pathMappings`. The Library checks only an entry on its own host (relative,
  or inside a Library folder). On Troy's install the Library is in the NAS
  container and Strata's files are on Amish_Station's own drive, so such an
  entry is listed with *not on the Library's machine*, never unreadable, and
  the agent checks it at Run, naming any missing file.
- **B20 (amended, §6.8: the entry must be in a Library folder).** *Add a prepared
  model* writes the file beside the entry when the
  entry is in a Library folder (entry written relative), otherwise into the
  Library folder the person picks (the console starts on the first).
- **B21.** `preparedFor` absent means the engine declaring the requirement;
  an engine may name another engine's preparation to load it.
- **B22.** A prepared model has no size, architecture, context or
  capabilities in the Library, since the engine's files are not read. Fit
  answers *Fit not estimated* (422) until LS6; the console never asks
  llama.cpp's arithmetic about it.
- **B23.** Strata's `modelFormats` is `["prepared"]` (B6's rule), so an older
  console still never offers it for a GGUF.
- **B24.** A Library older than LS3 refuses (422) an eligibility request
  carrying `prepared`; Run and the console fall back to the format rule, as
  B3 does for 404. Deploy the root first all the same.
- **B25.** The Inference page's *Add prepared Strata model* form is gone;
  *Switch model* stays there. A runtime declared before LS3 on a Strata JSON
  configuration still launches.
- **B26.** *Made from* offers the Library models the engine prepares from
  (its *after preparation* verdicts), linked by path; otherwise *not known*.
  No repo field in the form: LS4 and LS5 fill sources themselves.
- **B27.** No remove button: deleting the `.eugene-prepared.json` file
  removes the model, as deleting a GGUF does; *forget* clears a missing entry
  as before. The model's page says so.
- **B28.** A profile can *add stopped* (declare with `autoStart: false`), for
  any engine. Switching needs a second Strata model declared but not loaded,
  which the old form gave and Run does not. Such a runtime also stays stopped
  when Eugene restarts (compare agent#11).
- **B29.** The provenance file is versioned (`formatVersion` 1). A reader
  that meets a higher one lists the model unreadable, saying a newer Eugene
  wrote it; fields it does not know are ignored.

**What building found:**

- Switching between two Strata models was only reachable through the
  runtime-only form (B28).
- Run's hint promised *settings that fit* for a model whose fit is not
  estimated; reworded for prepared models.
- LS1's acceptance asserted Strata's pre-LS3 declaration (`modelFormats: []`
  and the GGUF requirement first); updated in the same push as the pins.
- **Found on the live install after the update (Troy):** Discover's *Works
  here now* found none of 30. Its narrowing to one hub format (B13) counted
  Strata's `prepared`: with Strata the only engine running anything as it
  is, the hub was asked for `format=prepared` and ignored it; with llama.cpp
  too, the search stopped narrowing to GGUF and most rows were hidden.
  Fixed in ui `2cfec94` (dist `c7f3a78`): no hub model is prepared.

## 6.5 LS4 built (2026-10-09)

Record: [ls4-sources-run.md](../acceptance/ls4-sources-run.md).

**Troy's call this slice:** Discover opens on *Works here now* when an engine
installed on the picked node runs a hub's models as they are, with
*Everything* one click away; otherwise on *Everything* (§4.3 changed).

**Calls building made**, for Troy's veto:

- **B30.** The list rides on the engine descriptor
  (`EngineDescriptor.supportedModels`), and the caller sends it with the
  search (`POST /v1/catalogue/search`, `engines`), as it sends `accepts` to the
  judge. The Library calls no agent, and the list is the picked node's: the
  adapter version that would prepare and run it.
- **B31.** Strata's list is upstream setup's **nine** choices, not the seven
  §4.4 guessed: the original Qwen3.8-Flash-Next in Q2_0, IQ2_XS, IQ3_XXS and
  IQ3_S; Swift 1.5 in IQ2_XS and IQ3_XXS (its Q2_0 files exist, but setup
  cannot prepare them, upstream #171); the Coder's IQ1_M; Unsloth's UD-IQ4_XS
  and UD-Q4_K_XL (experimental). Each is setup's own tag as its id, setup's
  words, the repo commit setup pins, and the size the hub lists at that
  commit (checked 2026-10-09: every first shard there, every one `qwen4exp`).
  IQ2_XS carries *recommended* (`docs/MODELS.md`).
- **B32.** Strata prepares only the files on its list, by name
  (`ModelRequirement.files`, filled from the list), as upstream's setup does:
  a `qwen4exp` GGUF by any other name (an Unsloth K-quant, a renamed copy) is
  *no* for Strata, naming its list. A search row names no file, so it stays
  *after preparation*, approximate. Names are compared ignoring case.
- **B33.** `catalogueEnabled` stays the switch that stops every outbound
  request, from any source; a source's own on/off stops searching it. The
  Library folders stay `modelRoots` (scanned, not searched), not an entry in
  the list.
- **B34.** The keys LS4 replaced: a file with only `catalogueBaseUrl` and
  `hfToken` becomes the first hub with both, the token moved still sealed;
  the file keeps both keys beside the list, mirroring the first hub, so an
  older Library reading it (a rollback) keeps its hub and token; `PATCH`
  still takes either, as the first hub's; neither is in the schema, so the
  settings page shows one place for each.
- **B35.** The default list is the public hub and one `engine_list` naming no
  engine, which covers every engine's list, engines added later included. A
  person can add one per engine to switch them separately.
- **B36.** One search answers the engines' lists first (each in its engine's
  own order), then each hub in the list's order; Discover then orders by the
  dot. A later page asks only the hubs that had more, and the lists are whole
  on the first. A pasted link is looked up on the hub at its host, else on
  the first enabled hub.
- **B37.** `GET /v1/catalogue/search` stays the first enabled hub alone, so an
  older console is unchanged. The calls about one repo (detail, card,
  preflight, download) take `source`, absent meaning the first enabled hub;
  an engine's list names repos on the public hub, so its rows' `hubSource` is
  that default hub.
- **B38.** A hub that fails says why in `sources[].problem` while the others
  answer, and Discover shows the sentence above the rows. A hub switched off
  is not shown as a problem on each search: it was the person's choice.
- **B39.** Troy's default (above) counts an installed engine with a
  requirement that is not `prepared` and needs no preparation: Strata alone
  opens on *Everything*, or it would open on nothing. The filter is
  remembered only once chosen (`chosenLevel`); the stored `level` from before
  is not read, since it was written on every visit (B14's reasoning).
- **B40.** A hub's row names its source; an engine's row says *Strata's list*,
  its size and the engine's *recommended* or *experimental*. Opening it opens
  the repo at the revision the entry pins, with the entry in the engine's own
  words above the versions, and any repo's table marks the versions an
  engine's list names (*on Strata's list*).
- **B41.** A download records its hub, the default resolved to its id, so a
  resume asks the same hub after the list is reordered, and a hub removed
  since says so (404) rather than another hub being asked.
- **B42.** A list entry's facts take the quantization by the scan's filename
  rule, as every candidate's do (B12): Unsloth's `UD-IQ4_XS` is *not known*
  there; the engine's own name for the size is `supported.quantization`.

**What building found:**

- §4.4 counted seven Strata variants; upstream's setup offers nine (B31).
- Strata's GGUF requirement, since LS1, accepted every `qwen4exp` GGUF;
  upstream's setup refuses all but its own files (`gguf_unsupported`,
  `SUPPORTED_GGUFS`). Fixed by B32. LS1's and LS3's acceptances used
  off-list fixture names for the Flash-Next GGUF; they now use the name
  Strata's setup gives IQ2_XS's first shard.
- The Library keeps a hub's search answer for 60 s, so a hub that went down
  since still answers that same search; the acceptance's S8 searches anew.
- The hub client was reconfigured on `PATCH` for downloads' sake; now every
  hub call, a download's transfer included, resolves its hub from live
  config, and the settings sabotage pass follows the token there.

## 6.6 LS5 built (2026-10-09): preparation is a job on the engine's node

Record: [ls5-preparation-run.md](../acceptance/ls5-preparation-run.md).

Read off upstream's `setup.py` at the commit the adapter pins (`6f32ec0`):
with `--gguf-dir` and `--data-dir` it checks the PC, installs its Python
packages (`requirements.txt`) into the interpreter running it, takes the
engine already in its own `engine/` folder (the release zip's `BUILD.json`
is there), downloads llama.cpp's source at the commit it pins (for
`gguf-py`), builds the pack and tokenizer from the GGUF (`tools/iq_pack.py`,
seconds), fetches the MTP draft layer from the original checkpoint (~5 GB,
once per data folder, SHA-256 checked) and writes `strata-<tag>.json` and a
start script into its **own** folder, with absolute paths. With `--yes` it
asks nothing and takes its own recommendation for every question.

**The recipe.** The run operation gains a step, `preparing`, between
*checking* (and *installing*, when Strata is not installed) and *settings*,
when the intent asks for it (`preparation: {engine, contextSize?}`). The
agent on the operation's node runs upstream's setup with the engine's own
Python, non-interactively, then makes its result a Library model; the
operation's model becomes the prepared one, and settings, launch and loading
continue as for Run.

**Calls building made**, for Troy's veto:

- **B43. Where the files go.** Strata's data folder is `Strata-data` at the
  top of the Library folder holding the GGUF, as the engine's node reaches it:
  one per Library folder, so the MTP helper (the same for every model) is
  fetched once. Strata's configuration and the provenance file sit in it; the
  entry is relative, and the configuration's paths are relative to it where
  they share a drive, so the folder travels.
- **B44. The scan skips an engine's own folder.** A directory holding
  `.eugene-engine-files` (written before setup starts) is an engine's own:
  the scan lists the provenance files in it and nothing else, and does not
  descend. Without it Strata's MTP helper, itself a GGUF
  (`mtp/mtp-q2_0.gguf`), would be listed as a model.
- **B45. Upstream's setup is the recipe**, run as `setup.py --family F
  --model M --gguf-dir <the GGUF's folder> --data-dir <Strata-data> --vision
  no --experimental-speed-projection off --no-browser --no-start --yes
  [--context N] [--gpu N]`. Setup makes every choice it makes for a person
  (KV cache, the low-RAM mode, the RAM budget, KV streaming, pool workers);
  Eugene reimplements none. Each run gets a fresh, empty `APPDATA` (and
  `XDG_CONFIG_HOME`), so setup's settings file never remembers a data folder
  and its "move an earlier install's files here" step finds nothing to move:
  a person's own Strata install is never touched.
- **B46.** Setup leaves `<shard>.done` beside each shard (its *checked whole*
  mark). The GGUF itself is unchanged.
- **B47. Preparation tools arrive with the first preparation, not the
  install.** The install stays the runtime subset, which an adopted model
  needs no more than. Before setup runs, the agent fetches llama.cpp's source
  at the commit Strata pins (39.6 MB, SHA-256 pinned) and unpacks only
  `gguf-py/` and `ggml/` into setup's `third_party/llama.cpp`: unpacked whole
  under the engine's folder, its deepest path is about 281 characters, past
  Windows' 260. Setup's own pip step then adds `requirements.txt` (numpy,
  pyyaml, tqdm, requests, cmake, ninja, pillow) to the engine's environment;
  the pins the install already has are left as they are.
- **B48. After setup** its `strata-<tag>.json` moves from the engine's folder
  into `Strata-data` with `cwd` dropped and the model's paths made relative;
  its expert profile (196 KB, in the engine's folder) is copied beside the
  pack, so a prepared model survives an engine reinstall; the start script is
  removed.
- **B49. Text, one GPU.** `--vision no` (the integration is text only) and the
  experimental speed projection off (a refusal-direction projection, whose
  flags the adapter refuses). On a node with several NVIDIA cards, `--gpu`
  names the one with the most memory, as setup's single-card default does: a
  layer split is not prepared, since the adapter does not run one.
- **B50. Context: setup's recommendation unless the person picks one** of
  setup's own sizes (8K to 512K). Preparing the same choice again replaces its
  configuration in seconds (the pack and MTP helper are kept); that is how a
  prepared model's context is changed. Setup's warnings (its `[!]` lines) are
  kept on the operation.
- **B51. Disk before anything starts.** Each supported model's
  `preparation.diskBytes` is setup's own rule on this node: 8 GB; plus the
  experts written into one file (their size plus 1 GB) when this node's RAM
  is under their size plus 10 GB; plus 40 GB for Q2_0, which setup repacks on
  an AVX-512 CPU (counted always: the CPU feature is not read). The agent
  checks free space on Strata-data's drive before setup starts and names both
  numbers when it is short.
- **B52. One preparation at a time per node**, since setup writes into the
  engine's own folder; a second waits and says so. Uninstalling Strata during
  one is refused (409), as during a running runtime.
- **B53. Cancel** stops setup and everything it started (the process tree).
  Setup's own marks let a later preparation carry on where it stopped. An
  agent restart starts the job again at the next claim, and setup skips what
  is done.
- **B54. Preparation is asked for, never implied.** Run still picks an engine
  that runs a model as it is. *Prepare for Strata* (a Library GGUF on Strata's
  list) and *Download and prepare* (an entry of Strata's list in Discover)
  carry `preparation`. A Run whose only engines would need to prepare the
  model fails at checking and names the action. *Skip* is not an answer to
  *install Strata?* in a preparation: without the engine nothing can be made.
- **B55. The Library writes the provenance file**
  (`POST /v1/run-operations/{id}/prepared`, the assigned agent under its
  lease), as *Add a prepared model* does, and the operation's model becomes
  the prepared one. A provenance file the same recipe wrote for the same
  entry is replaced; any other file of that name is a 409.
- **B56. Progress** is setup's step in its own words (its `=== Step N` lines),
  the bytes Strata-data has grown by against `diskBytes`, and setup's last
  line; when it stops, its last lines are the failure's cause.
- **B57.** The context sizes a preparation offers are the engine's to publish
  (`ModelPreparation.contexts`, a second contract commit), so the console
  lists setup's sizes without knowing the engine.

**What building found:**

- Setup unpacks llama.cpp's whole source under its own folder; under a
  Windows install's engine folder the deepest path is about 281 characters,
  past the 260 Windows allows without long paths (B47).
- The v0.1.39 release's `BUILD.json` lists sm_75, 86, 89 and 120 with PTX, so
  on an RTX 50 setup takes the engine already installed and compiles nothing.
- With `--yes` on two or more cards, setup recommends a layer split, whose
  configuration key (`layer_split`) the adapter refuses: hence `--gpu` (B49).
- Setup writes its configuration into its own folder, and its expert profile
  is a path inside it (B48).
- A Windows tool ends its lines with `\r\n`; the first reading took the text
  after the last `\r` and lost every line (caught by the unit test).
- On an install whose Library folder is on another machine (Troy's NAS), the
  GGUF and Strata's pack are read over the network while Strata answers:
  [agent#12](https://github.com/eugene-plexus/agent/issues/12), for Troy.
- The CI acceptance first used IQ2_XS. The Windows runner has 16 GB of RAM,
  so by setup's rule IQ2_XS also needs its low-RAM file there: 44 GB, against
  31 GB free. The disk check refused it, rightly. The fixture is now
  Unsloth's UD-IQ4_XS, a RAM-budget choice whose rule is 8 GB anywhere.
- The real run (Troy's go; 18 of 19, record §"The real-model run"): from
  download to running in one action, 87.8 tok/s with MTP. Two findings.
  First, a failed start did not name its cause: no `log` in the launch
  configuration, so Strata's server discarded the native engine's error
  output. Fixed in agent `e03ea78`. Second, a runtime reads *stopped* a
  moment before Strata's native engine has exited:
  [agent#13](https://github.com/eugene-plexus/agent/issues/13).

## 6.7 LS6 built (2026-10-09): each engine owns its fit model

Record: [ls6-fit-run.md](../acceptance/ls6-fit-run.md).

**The shape.** `EngineDescriptor.fit` (`EngineFitModel`) sits beside
`accepts`, one of three kinds (`FitModelKind`):

- `spill`, llama.cpp: today's arithmetic, unchanged.
- `reserved_share`, vLLM: read off its own `request_memory` (upstream main):
  it takes `gpuMemoryUtilization` of each card's **total** memory, refuses to
  start with less free, splits the model evenly across its cards, and moves
  nothing to system memory. `fits`, `tight` (less than its share is free) or
  `no`; never `split`.
- `engine_table`, Strata: its setup's own `--check` answer for each model on
  its list, applied to the node by the adapter (`EngineFitModel.table`).

The judge answers each engine's fit when asked (`EligibilityRequest.fit`,
`EngineVerdict.fit`), `GET /v1/models/{id}/fit` takes `fitModel`, and
admission measures a launch by its engine's own model.

**Calls building made: all twelve approved by Troy as written (2026-10-09).**
On B67 he noted that shims for scenarios that no longer exist (an older
Library, an older console) may want a cleanup pass later ([specs#22](https://github.com/eugene-plexus/specs/issues/22)).

- **B58. Data where it can be.** The kind and its numbers are data on the
  descriptor; the `spill` and `reserved_share` arithmetic is the Library's
  (one per kind, never per engine); Strata's table is worked out by its
  adapter on its node, as B51's disk is, so setup's rules stay in the agent
  and the Library only relays a row. The Library still names no engine (B2).
- **B59. Strata's verdict is setup's own.** `--check` at the pinned commit,
  on the node's total RAM as setup reads it and the card setup would take
  alone (the most memory, NVIDIA or AMD): *fits* and the RAM-budget mode are
  `fits`, the low-RAM mode `split` (it runs, part of the experts from the
  SSD), *tight* `tight` (a few GB short: the system pages), *does not fit*
  `no`; a node with no card Strata can use is `unknown`. Under 12 GB of VRAM
  the words add setup's *it will be slow*.
- **B60. Strata at admission.** `no` and `tight` refuse, as setup stops by
  default (`?force=true` overrides); the low-RAM mode admits. In the mode
  that copies every expert into RAM, less RAM free now than the experts is
  `tight`. Strata fills its card with its expert cache, so the ledger holds
  the card's free memory while it loads; an unknown holds nothing. A model
  made outside Eugene that names no source on the list is admitted on faith.
- **B61. vLLM's share is 0.92**, vLLM's own default on upstream main (§6.1
  said 0.9, the older default); a launch's `gpuMemoryUtilization` wins.
  `tight` refuses whatever `gpuLayers` says (vLLM refuses to start), the
  ledger holds the whole share, the buffers are llama.cpp's flat 1 GiB per
  card (not measured for vLLM), the KV term for a safetensors folder stays
  the labelled estimate (the scan does not read `config.json`'s heads yet),
  and its context is `maxModelLen`.
- **B62. MLX and Kev declare none:** *Fit not estimated*, admission
  `unknown`. MLX was already `unknown` in practice (Metal reports no free
  memory); Kev loses a file-size verdict that was llama.cpp's shape.
- **B63. The dot (§4.3, built now).** An engine whose fit is a measured `no`
  counts as one that cannot run the model: too large for llama.cpp but run
  by Strata after preparing it is amber; red only when every engine that
  would run it says `no`. *Not estimated* and `unknown` never count. Without
  the question, the level is as before (an older console).
- **B64. Sizes.** A version, a starter entry and an engine's list entry carry
  `sizeBytes` in their facts; a search row names no file and gets no fit. A
  fit resting on guessed facts (a search row's) is approximate, as is a KV
  term from a share of the weights.
- **B65.** A `spill` engine under a caller's budget compares free memory, as
  `GET /fit` with `vramBytes` alone does; the total in the question is for a
  share-taking engine, so the popover never says `tight` where the panel
  says `split`.
- **B66. Whose fit is shown.** The Library page's panel shows the engine Run
  would pick (its `preference`, unchanged by fit); every engine's fit is a
  line under its verdict there and in each dot's popover; Discover's version
  column shows the dot's engine: llama.cpp's detailed badge for a GGUF it
  scores, otherwise that engine's own answer, named. Until the node says
  which engines it has, no fit is shown.
- **B67.** A Library older than LS6 refuses the fit fields (422): the console
  asks again without them, so the dots stay engine-only rather than vanish.
- **B68. Run and vLLM's context.** Run suggests a context only to an engine
  whose flags have `contextSize`: a vLLM profile carries none, vLLM takes the
  model's own length, and admission measures that by its share, naming
  `maxModelLen` and the longest its share holds when it refuses. Picking a
  vLLM context from Run is [library#9](https://github.com/eugene-plexus/library/issues/9).
- **B69.** Strata's table reads the node's devices at most once a minute:
  `GET /v1/engines` is polled, and the totals do not move.

**What building found:**

- vLLM's default share moved to 0.92 on upstream main; the agent's flag help
  already said so, §6.1 did not.
- §4.3's red-for-*does-not-fit* was written down in LS2 and never built: a
  fit of `no` did not touch a dot.
- A Run of a vLLM model failed at launch whenever it suggested a context: the
  profile it wrote carried `contextSize`, which a vLLM spec refuses (B68,
  library#9). Admission asked vLLM about `contextSize`, which it never has.
- With a 32 GB card, setup's rule runs IQ2_XS on 16 GB of RAM in the low-RAM
  mode (the card holds about 76% of the experts): the table, not a guess,
  says Strata is green there.
- The Library page said *Fit not estimated* while the node's engines were
  still unknown, and would have printed llama.cpp's *runs from system
  memory* on vLLM's panel; both caught by the suite before they shipped.

## 6.8 Troy's principle: the Library is the home of a model's files (2026-10-09)

Vetoing B18-B20, Troy gave the rule rather than the details (he has not run
Strata): **every model's files and configs live with it in a Library folder,
and a node only ever holds a copy.** So nothing is lost when a node goes
down or an engine is updated, uninstalled or reinstalled, and several
identical nodes share one setup: *saving it in the library propagates the
config*.

- **B18** stands.
- **B19 and B20 change:** *Add a prepared model* accepts only an entry inside
  a Library folder, and says to move the engine's folder there; an entry on a
  node's own disk is refused. (LS5's preparations already write everything,
  the expert profile included, into `Strata-data` in the Library folder.)
  A runtime declared before LS3 on a JSON configuration stays a shim
  (specs#22).
- **agent#12 is option 1:** a node that copies a model to run it copies a
  prepared model's whole set (the provenance file, the engine's
  configuration, the pack, the MTP helper and the GGUF shards it names),
  keeping their layout, as a cache it can always rebuild from the Library.
  That closes agent#10 (a split GGUF copied without its shards). Option 2,
  preparing onto the node's own disk, is ruled out.
- **No shims for versions before v0.2** (Troy, the same day): B3, B6, B16,
  B23, B24, B25, B34, B37 and B67 serve only older versions and go in the
  cleanup slice after LS7 (specs#22).
- **B22 is replaced** (Troy: the Library exists to impart knowledge on the
  person's behalf, so it does not shrug). A prepared model shows what is
  known of it: recorded at preparation in its provenance file (the source
  model, the context it was prepared for, the engine's mode on that node,
  each file it wrote and its size), inherited from its source model
  (architecture, parameters, trained context, capabilities: the source GGUF
  in the Library, else the engine's list entry), read from the engine's own
  configuration where it is text (Strata's is JSON; every open-source engine
  that prepares models keeps a text configuration beside its weights), and
  measured (the size of the files it names). A fact that cannot be had is
  named with why, never a bare *unknown*. Part of LS7.
- **B21 approved. B24 and B25 go** in the pre-v0.2 cleanup. **B26 changes**
  (LS7): *Made from* is read from the engine's configuration (Strata's names
  the GGUF it was made from), with the picker only when that fails.
- **B28 and B29 approved. B27 is replaced by a Delete for every model**
  (Troy chose it over a Delete for prepared models alone, 2026-10-09): LS8,
  after LS7, before the cleanup. Today no model has one (files are deleted
  outside Eugene; *Forget* drops a missing entry). Building's starting
  points, for his veto in LS8: one button per model removes every file it
  owns (a GGUF and its shards, a folder, a prepared model's own files);
  files another model still uses stay (a projector shared by quants,
  Strata's MTP helper); the confirmation lists every file, its size and the
  saved profiles before anything goes; a GGUF a prepared model is made from
  (Strata reads it while it runs) names that model and offers both; refused
  while the model runs on any node or is downloading; nodes' copies follow
  on their own.
- **LS4: B31 and B32 approved; B30 approved with a fix in LS7.** The list is
  written by Eugene in the engine's adapter, read off the engine's own setup
  at the version the agent pins, and changes when the agent updates. Because
  an older engine build can stay installed after an agent update, each entry
  will carry the oldest engine version it needs (setup states it, e.g.
  UD-IQ4_XS needs v0.1.38), each node reports its installed version, and an
  entry the installed build cannot prepare is amber, *needs Strata vX: update
  Strata on this node*, one click from the update, never a failure halfway
  through a preparation.
- **B33 and B35 approved; B34 goes** in the cleanup (check the NAS's own
  Library config has moved to `catalogueSources` first). Troy means to
  explore Stable Diffusion-style image models after v0.2 (not designed):
  sources, fit and Delete stay general enough for them.
- **LS7 builds it, before v0.2.0** (Troy). Kickoff:
  `docs/private/next-session-ls7.md`.

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
