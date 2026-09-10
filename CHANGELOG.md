# Eugene Plexus changelog

Cross-component release notes. Each repo has its own commit history; this file consolidates what shipped together.

---

## Unreleased — local-inference control plane (direction change, 2026-09-08)

Eugene Plexus becomes a **self-hosted control plane for local LLM inference**: it supervises engine processes it does not own, manages a model library on the user's own disk, holds per-model settings profiles, exposes one OpenAI-compatible endpoint that routes across local runtimes and cloud providers with failover, and serves a web UI with real auth so it works over a tailnet.

This retires **both** prior directions as headline work — the consciousness framework (May 2026) and the from-scratch training platform (June 2026). Neither is deleted; both are archived. Full reasoning, evidence, milestones and locked decisions: [`docs/design/local-inference-control-plane.md`](docs/design/local-inference-control-plane.md).

The initial pivot retained five repos and added `library`; M5 added `control`.
The current seven are `agent` (formerly `watchdog`), `gateway` (formerly
`orchestrator`), `inference-driver` (formerly `hemisphere-driver`), `library`,
`control`, `ui`, and `specs`. Milestone entries below retain names used at the time.

### Repository and Documentation Maintenance (2026-09-10)

- Updated all 15 GitHub descriptions, topics and project links, plus the
	organization profile, to distinguish seven active repos, one deferred
	connector and seven retired repos. Archive flags remain unchanged by choice.
- Refreshed active READMEs, contributor guides and stale package descriptions;
	added dated status notices above inactive repos' historical documentation.
- Reconciled control-root ownership, six codegen consumers, M7 enrollment,
	lifecycle policy and outstanding verification. No contracts, generated code,
	dependency versions or application behavior changed.
- Documented the obsolete bootstrap/task setup instead of recommending it.
	See the [maintenance record](docs/maintenance/repository-audit-2026-09-10.md).

### specs — M0 (contracts)

M0 is "supervise one `llama-server` end to end": the supervisor starts it, a driver fronts it, the gateway routes a chat completion through to it, the UI shows it. This is the contract half.

**Renames**

- `openapi/orchestrator.yaml` → `openapi/gateway.yaml`; `openapi/hemisphere-driver.yaml` → `openapi/inference-driver.yaml`. `orchestrator` survives as the gateway rather than being replaced — it already sat above N drivers and routed to them.
- Env prefixes move with the components: `EUGENE_PLEXUS_ORCH` → `EUGENE_PLEXUS_GATEWAY`, `EUGENE_PLEXUS_HD` → `EUGENE_PLEXUS_DRIVER`.

**Deleted**

- Spec documents for every killed component: `identity`, `connector`, `memory`, and the six training-platform documents (`coordinator`, `training`, `data`, `eval`, `inference`, `cluster`).
- 51 schemas from `common.yaml` (2183 lines → 653): the tool family, the NT system, bicameral and continuous-runtime schemas, identity, memory, connector adapters, and the whole `TrainingProject` family.
- The gateway's consciousness surface: `/v1/events`, `/v1/stream/consciousness`, `/v1/conversations/{id}`, `/v1/admin/nt-state`, `/v1/admin/memory-search`.
- The watchdog's `/v1/pending-links` identity badge.
- `GenerateRequest.ntState` / `.passIndex` / `.tools`, `GenerateResponse.toolCalls`, and the `tool_use` finish reason.

The tool family (`ToolChannel`, `ToolEffect`, `ToolDefinition`, `ToolCall`, `ToolResult`) went rather than being kept "for later" because it was never generic: `channel` encoded an afferent/efferent/internal perception-action model and `effect` was a reversibility class feeding a System-1/System-2 escalation gate that required bicameral agreement. Tool passthrough returns in OpenAI shape when the gateway implements it.

**New — engines and runtimes (watchdog)**

- **`GET /v1/runtimes`** plus full CRUD, `restart`, `stop` and `start`. A *runtime* is a supervised third-party engine process, deliberately a separate collection from `/v1/components`: a component is a Eugene Plexus process (`python -m`, config trio, service token), a runtime is a foreign binary (adapter-built argv, engine-specific readiness probe, no auth of its own). They share supervision mechanics and nothing else. `stop` exists as distinct from `delete` because an engine holds GPU memory.
- **`RuntimeSpec` / `Runtime` / `RuntimeStatus` / `RuntimeCapabilities`.** `RuntimeSpec` carries intent — engine, model path, curated `flags`, `extraArgs` escape hatch — and deliberately *not* a command line; the adapter builds the argv. The resolved `argv` is reported back read-only on `Runtime`, because the first question anyone debugging a local engine asks is what command actually ran.
- `RuntimeStatus` has a `loading` state distinct from `starting`. A large quant off a spinning disk sits there for minutes, and an operator needs to tell "working on it" from "wedged" — which is exactly what a per-engine readiness probe buys and a generic TCP check cannot.
- **`GET /v1/engines`** with `EngineDescriptor`, exposing each adapter's **curated** flag surface as a standard `ConfigSchema`, so the generic config editor renders engine flags with no engine-specific UI code. Curated, not complete: `llama-server` has hundreds of flags and `extraArgs` covers the long tail.
- `ComponentKind` is down to `gateway` and `inference-driver`, and now states explicitly that engines are not components.

**New — the OpenAI-compatible front door (gateway)**

- **`POST /v1/chat/completions`** and **`GET /v1/models`**, with the full OpenAI wire schemas including streaming chunks.
- These two operations use **snake_case field names and OpenAI's error envelope**, unlike every other surface in Eugene Plexus. That is deliberate: "OpenAI-compatible" is worth nothing unless an unmodified OpenAI SDK can point its `base_url` here and work, and OpenAI SDKs parse the error shape to build their exceptions. One surface, one foreign convention, honoured exactly.
- `GET /v1/models` is a *view of the routing table*, not a configured list — the gateway asks each driver what it serves. Two drivers serving one model produce one entry; replicas are a routing detail a client should not see.
- Namespaced `x_eugene_plexus` extensions report which driver, runtime and backend served a request, its latency, and the number of `attempts`. OpenAI clients ignore unknown fields, and `attempts > 1` is the visible evidence that priority-list failover fired. The failure mode of a routing layer is being opaque.
- Status codes distinguish the cases that matter operationally: 404 no driver serves the model at all, 502 the cascade ran and every backend failed, 503 a driver serves it but is not ready (engine still loading) and the call is retryable.

Validated with `openapi-spec-validator` 0.8.5 and `@redocly/cli` 2.30.4, and confirmed to generate importable Pydantic v2 models via `datamodel-code-generator`.

### specs — M1 (engine acquisition)

*Landed at `8abfc91`; this entry was written retroactively alongside M2, which is why it is a summary rather than a full one. The design doc is the record: [`docs/design/m1-engine-acquisition.md`](docs/design/m1-engine-acquisition.md).*

The control plane fetches, verifies and manages the llama.cpp binary itself, closing the one manual step M0 left. `EngineDescriptor` gained `managed` and `acquisition`, plus a singleton install sub-resource (`POST`/`GET`/`DELETE /v1/engines/{engine}/install`) whose state names its phases — `resolving` / `downloading` / `verifying` / `extracting` — because they fail differently and the operator needs to know which one they are in.

Four of the five things upstream actually ships turned out to be traps, all documented: `releases/latest` is not a llama.cpp build, Windows + CUDA is a two-asset install, no prebuilt Linux CUDA binary exists, and `--version` changed format mid-2026. Linux + NVIDIA is refused with a reason rather than silently handed the slower Vulkan build.

Two drift fixes rode along: `/v1/auth/status` and `/v1/auth/initialize` became documented (the UI calls status on every page load), and `ConfigValueType.driver_list` stopped naming the deleted `DriverEntry` schema.

### specs — M2 (model library)

M2 is "point it at the directories you already keep models in": scan them, describe what is in them, and hold the launch settings that worked for each model. Design, with every metadata claim verified against real files on the dev box: [`docs/design/m2-model-library.md`](docs/design/m2-model-library.md).

**New — `openapi/library.yaml`** (port 8082), the component the watchdog's own description has claimed to supervise since M0.

- **`GET /v1/models`** and **`GET /v1/models/{id}`.** One entry per *launchable* model, which is the whole difficulty: a vision projector sits beside its model as a second `.gguf` (931 MB on one of the models used to check this, 1.8 GB on another), shards 2..N of a split GGUF are not models, and a HuggingFace cache holds one directory *per revision* of the same model. `LibraryModel` carries the format-independent facts; exactly one of `gguf` / `safetensors` carries the rest.
- **The quant fields live on the GGUF side only.** Quant tiers are a GGUF concept; a safetensors model is sized, not tiered. `general.file_type` does distinguish the K-quant mixtures (verified: 14 is `Q4_K_S`, 15 is `Q4_K_M`), so the tier is machine-read rather than guessed from a filename — and the raw integer is reported alongside the label because the quant families churn and an unrecognised value must degrade to "here is the number", never to a plausible neighbour.
- **`parameters` is optional, and `sizeLabel` is a string.** Forced by a measured asymmetry: a safetensors header gives an exact parameter count from ~11 KB, while GGUF gives none at all — only an author-typed `"27B"`. A schema requiring a parameter count would be unfillable for every GGUF in existence.
- **`GET`/`POST`/`DELETE /v1/scan`**, a singleton sub-resource with named phases, following M1's engine-install precedent. Asynchronous because reading GGUF metadata is not a cheap header read: the tokenizer lives in the KV block, so a 248k-vocab model means walking ~10.9 MB to reach fields that sit *after* it — ~50–60 ms per model warm, measured both buffered and not. Rescans are incremental on `(path, size, mtime)`.
- **`Scan.skipped[]` carries a reason per path,** and `SkipReason`'s eight values are all real cases off a real disk, not defensive placeholders — projector, shard member, adapter-only directory, older HF revision, HF cache infrastructure (including `.no_exist/`, a *negative* cache full of zero-byte files with real-looking names), unparseable header, unsupported format, and `incomplete_download` reserved for M3's `.part` files. A scanner that silently drops what it did not understand is indistinguishable from a broken one.
- **Per-model profiles** (`/v1/models/{id}/profiles`), named, N per model, one default. Plural because a long-context profile and a fast one are different flags on one file — and because two replicas of one model across two GPUs is the same profile twice with a different `CUDA_VISIBLE_DEVICES`, which is the load-balancing case M5 exists for. `PUT` rather than `PATCH`: `flags` is a document, and merge semantics give no way to *remove* a flag.
- **The library validates no engine flags and launches nothing.** Flags are validated by the watchdog's adapter `flagSchema` at runtime-creation time, because that is where the curated surface lives and where a bad flag has to fail anyway. Launching is composed by the caller — read a profile here, `POST /v1/runtimes` there — and `ModelProfile`'s field names are `RuntimeSpec`'s field names so that composition is a copy rather than a translation.
- **`DELETE /v1/models/{id}` refuses a model that is present** (409), and never touches a file. It drops the saved profiles, which is the only thing this component owns. A moved model reads as a new model and its old entry goes `missing` keeping its profiles: nothing guesses that a file which vanished from one root and appeared in another is the same file, because a wrong guess silently applies one model's tuning to another.
- Model roots are **config, not a resource** — a `path_list` field in the standard trio, so the generic config editor edits them with no library-specific UI code. `POST /v1/config/test` checks they are readable, which `common.yaml` promised before the library existed.

**Changed — shared schemas**

- **`ComponentKind` gains `library`.** The watchdog has described itself as supervising the library since M0 while the enum could not name it.
- **`EngineKind` moves from `watchdog.yaml` into `common.yaml`.** A profile names an engine, so two components reference it now.
- **`ModelFormat` is new and shared** (`gguf`, `safetensors`), because it appears on both sides of a join.
- **`ConfigValueType` gains `path_list`** — the first list-typed config value. `driver_list` stays reserved for M5.

**Changed — watchdog**

- **`EngineDescriptor.modelFormats`**, required. llama.cpp cannot load safetensors, so at M2 those models are scanned, browsed and profiled with nothing able to launch them. Format support goes where engine knowledge already lives rather than into the library, so the UI can grey out a launch button and name the missing engine — and so vLLM at M4 lights it up with no library change.
- `RuntimeSpec.modelPath` now says that a sharded GGUF is named by its *first* shard, and where a path comes from when a runtime is created from the library.

**One drift fix riding along:** the watchdog binds **8079** — its own spec and M0's acceptance script both say so, and the UI defaults to it — while the README and the main design doc's shape tables said 8083. The tables were wrong.

Validated with `openapi-spec-validator` 0.8.5 and `@redocly/cli` 2.30.4; all four specs confirmed to generate importable Pydantic v2 models via `datamodel-code-generator`, and `library.yaml` to generate types via `openapi-typescript` 7.13.

### specs — M3 (discovery, download, guidance)

M3 is "get models, and be told which one to get": search the upstream catalogue, read what a repo actually holds, find out which quant this machine can run *and why*, and download it resumably into a directory the operator chose. Design, with every fact verified against the live hub rather than fixtures: [`docs/design/m3-discovery-download-guidance.md`](docs/design/m3-discovery-download-guidance.md).

All of it lands on **`library.yaml`**, which grows eleven paths and 25 schemas. `common.yaml` is untouched — so unlike M2, the re-pin reaches only `library` and `ui`; the gateway and the inference-driver generate byte-identical models.

**New — the catalogue**

- **`GET /v1/catalogue/search`** and **`GET /v1/catalogue/model`.** Search lists *repos*; detail scores *candidates*. That split is forced by upstream: the search response carries filenames with no sizes, so sizes and fit verdicts cost one extra call per repo — badging fit on search results would turn one keystroke into fifty API calls. Pagination is cursor-based because upstream's is.
- **Guidance and discovery are one response.** `GET /v1/catalogue/model` returns each download candidate with the fit arithmetic already attached, because the moment someone is choosing between `Q3_K_S` and `Q2_K_M` is the moment they need to be told which one their box can hold — and a UI that has to join two calls to say so will ship without the second one.
- **Candidates, not files.** One verified repo held 35 entries, 30 of them `.gguf`, and **25 actual choices**: shards summed into one candidate, and the two vision projectors, the imatrix calibration file and the MTP draft model pulled out into `projectors` / `otherFiles`. A screen that lists `.gguf` files offers four things that cannot be launched and one that is half a model.
- **`GET /v1/catalogue/model/preflight`** reads one remote candidate's *real* metadata over HTTP Range without downloading it. Measured: the KV block of a 16.5 GB GGUF is 10.9 MB at the front of the file, fetched in under a second — **0.07% of the file** — yielding `general.file_type`, the layer count, the KV head count and key/value lengths. So remote quant guidance is built on the file's own metadata rather than its filename, which is the standard M2 already holds *local* models to. Safetensors is two orders cheaper: 8 bytes for the header length, then ~11 KB for an exact parameter count.
- `CatalogueCandidate.quantSource` says `filename` or `metadata` so a client can see which standard a given row was held to, and fit is always computed from `sizeBytes`, which is authoritative either way.

**New — guidance**

- **`GET /v1/hardware`**, **`GET /v1/models/{id}/fit`** and **`GET /v1/quants`**. `Fit` is one computation with three callers — a catalogue candidate, a local model, a preflight — and reports its inputs (`weightsBytes`, `kvCacheBytes`, `overheadBytes`, the budget, the assumed context) so a wrong answer is diagnosable rather than merely wrong. `basis: metadata | estimate` is the honest line between arithmetic and a guess with a number on it.
- **`FitVerdict` has four values, not a percentage:** `fits` (inside free VRAM), `tight` (inside total but not free — something is holding memory), `split` (needs host memory, runnable and slower), `no`. A percentage *of what* — VRAM, or VRAM plus RAM? — is precisely the ambiguity the operator is trying to resolve, and the four cases have different advice.
- **Free memory, not total, decides the verdict.** Measured on the dev box with nothing unusual running: 2.9 GiB of a 32 GiB card was already held by the desktop, and a third of RAM was in use. Scoring against total promises a fit that OOMs; both numbers are reported so the operator can see what quitting something buys back.
- **Hybrid attention is the trap that would have made guidance a liar.** A current 27B declares 65 blocks with `full_attention_interval: 4`, so 16 layers hold a KV cache and the naive formula overestimates it by **4.1×** at every context length — 8.12 GiB instead of 2.00 GiB at 32k, 65 GiB instead of 16 at the model's trained 262144. `Fit.attentionLayers` is the field that stops this, and where the metadata is silent the assumption is stated in `notes` rather than buried.
- **Bits per weight** (`size × 8 / parameters`, both free from the hub) is the one quality-adjacent number here that is arithmetic rather than judgement. Across the verified repo it ordered all 25 candidates monotonically from 1.81 to exactly **16.00** for BF16 — that last value being the check that the parameter count is real — and it is what makes `IQ2_S`, `Q2_K` and `UD-Q3_K_XL` comparable when their names come from three different upstream naming schemes.
- **`GET /v1/quants` explains the schemes and scores no model.** Relative quant quality is upstream research, model-dependent, and would have to be invented; a fabricated quality score is worse than none — the same rule that makes an unrecognised `general.file_type` degrade to the raw number. The recommendation is "largest that fully fits at your context", with a warning when the only thing that fits is below ~4 bits per weight, because recommending a 1.81-bpw quant without comment is how a first impression becomes "this thing is stupid".

**New — downloads**

- **`POST`/`GET`/`DELETE /v1/downloads`** plus `pause` and `resume`. A collection rather than M1's singleton install, and **one job over N files** — a split GGUF is 2–9 files, a multimodal model is a quant plus a projector, and a safetensors model is a directory of which nothing is optional. `DownloadState` names its phases for M1's reason: a stall in `downloading` is the network, a stall in `verifying` is the disk.
- **The destination is resolved before a byte moves** — root, layout, upstream filename — because the one thing this component must never do is put a file somewhere the operator did not choose. Root must be one of the configured model roots; `downloadLayout` picks `<root>/<owner>/<repo>/<file>` or flat.
- **Verification is mandatory, and the digest has a decoy beside it.** Each tree entry carries three hashes: `lfs.oid` (the content sha256), `oid` (the sha1 of the 136-byte LFS *pointer*, which passes on any download at all) and `xetHash`. Non-LFS sidecars have no `lfs` object and are verified by git blob sha1 — `sha1("blob <len>\0" + bytes)`, checked exactly against a real repo — so every file has something to check and nothing is written unverified. `.part` is renamed into place only after it passes.
- **Resume was proven end to end, not assumed.** Large repos are on Xet storage now; the question that decides whether resumable download is possible at all is whether the bridge serves plain HTTP ranges, and it does. A 13.6 MB file was fetched in two legs with the connection abandoned mid-stream: `Range: bytes=5242880-` → 206, digest verified, `.part` renamed.
- **Three traps in that loop, all found by running it.** The size, sha256 and resolved commit live on the hub's **302**, not on the CDN response it points at, so a client following redirects transparently loses all three (this cost a debugging cycle). The CDN URL is signed and expires, so a resume must re-resolve rather than reuse a stored URL. And `main` moves — repos are requantized under the same filenames — so a download pins `resolvedCommit` and a resume that finds a different digest discards the partial and says so via `restartedFromZero`, rather than appending new bytes to old ones and producing a file of exactly the right length that fails verification.
- **A gated repo browses perfectly and only the download 401s** (`X-Error-Code: GatedRepo`). Metadata, file list, sizes and digests are all public. So `GateKind` is `open | auto | manual` on the detail response — `auto` needs a token and a click-through, `manual` needs an approval that can take days — and the warning appears before a quant is chosen rather than after the button is pressed.
- **`CatalogueCandidate.alreadyOwned`** is the join only this component can make, and it is what stops a 16 GB re-download of a file already on the disk. `matchedOn: digest | name_and_size` labels the guess as one, because the library deliberately never hashes model content.
- `Download.modelId` is filled in from the post-completion scan of the destination directory, closing discovery → download → library → profile → launch without the UI polling for a model to appear. And `.part` files in scanned roots are now real rather than reserved — the `incomplete_download` skip reason M2 shipped early lands in the same release as the thing that creates them.

**Config** gains six fields in the standard trio and needs no new renderer or `ConfigValueType`: `hfToken` (a `secret`; upstream's own advice is that a token means faster transfers even for public files), `catalogueEnabled` (the air-gap switch), `catalogueBaseUrl` (enterprise hubs and regional mirrors both exist), `downloadLayout`, `maxConcurrentDownloads`, and `guidanceContextLength` — the single number that decides which quant gets recommended, and therefore a config field rather than a constant.

**Not done, deliberately:** Xet-native chunked transfer (it would give dedup across quants of one model, and it means adopting content addressing internally, which this project has now refused three times), quality scoring of quants, automatic quant selection, and a cross-host hardware inventory — the fit endpoints take an explicit budget override and report which host they measured, which is the honest answer when the GPU is in a different building. Three detection paths are unverified on real hardware and named as such: AMD, Intel, and Apple unified memory.

Validated with `openapi-spec-validator` 0.8.5 and `@redocly/cli` 2.30.4, and confirmed to generate importable Pydantic v2 models via `datamodel-code-generator` (82 models) and types via `openapi-typescript` 7.13.

### library — M3 (implementation)

Seven new modules behind the eleven endpoints: `hub.py` (the only outbound network in the component), `catalogue.py` (a repo's file list into launchable choices), `fit.py`, `hardware.py`, `quants.py`, `preflight.py`, `downloads.py`. 288 tests, plus an opt-in suite that drives the live hub (`EUGENE_PLEXUS_LIBRARY_LIVE_HUB=1 pytest tests/test_live_hub.py`).

Four defects the first live run earned, none of which a fixture would have produced:

- **Candidate labels collided.** Four files read as `UD-Q6_K` — they were `UD-Q6_K`, `_M`, `_L` and `_XL` — while others fell back to their whole filename. One cause: the label was matched against llama.cpp's own `file_type` names, and publishers invent tiers (`Q4_K_XL`, `UD-Q8_K_XL`) no fixed list will contain. The label now comes from the data — every candidate stem in a repo shares a prefix, and what remains is the distinguishing tier. Four identical rows on a screen whose whole job is "pick one" is the worst thing this could have shipped.
- **Verification used a digest captured before the transfer,** so a file replaced upstream mid-download could never verify however often it was retried. The HEAD preceding each transfer is authoritative now.
- **A digest mismatch retried five times against the same bad partial** — one failure five times, and four sleeps. It discards the partial and allows exactly one clean retry.
- **A performance regression, introduced and then measured away.** Bounds-checking the GGUF reader's `skip()` cost two seeks per stepped string and `tell()` on every `raw()` cost more: together 3.4× slower (0.61 vs 0.18 ms/model), which broke a test that busy-polls a live scan. The reader tracks its own offset now — faster than the original, and exact where a buffered `tell()` after a short read is not.

`httpx` is the one new runtime dependency. The watchdog's venv is the runtime venv for every component it spawns, so that venv needs it too.

### ui — M3

**`/discover`**: search, then one repo's launchable choices with a fit verdict on every row. Guidance and discovery are the same screen deliberately — the moment someone is choosing between `Q3_K_S` and `Q2_K_M` is the moment they need to be told which one their box can hold, and a UI that has to join two calls to say so ships without the second one. The context control in the header is the other half: watching the recommendation walk down the list as it moves from 8k to 128k *is* the guidance.

- **`FitBadge` opens into its own arithmetic.** Differentiator #6 is "show why", so a verdict is a disclosure rather than a chip: weights, KV cache with the attention-layer count, the overhead allowance, the budget it was measured against, and whether the KV term came from the model's declared shape or was estimated from its size.
- **A `check` button per candidate** runs the ranged metadata read, which flips that basis from `estimate` to `metadata` and reports it if the file's own metadata disagrees with its filename.
- **`DownloadsPanel`** is shared by the discovery and library screens, because a transfer outlives the screen it was started from. Pause, resume and cancel are distinct verbs and the panel says which: cancel asks first, because a paused 40 GB download is an hour of bandwidth sitting on the disk and the buttons are next to each other.
- **`QuantReference`** renders `GET /v1/quants` — the schemes, the naming decorations, and where on the curve quality goes — with no per-model judgement anywhere in it.
- **`ModelCard`** renders the card prose, which is the "with summaries" half of the original complaint. Untrusted content: Markdown with no raw HTML, images dropped, links `noopener noreferrer`.
- The library page gains a fit panel on the selected model, where the scan has already read the real metadata — so it reports `maxContextLength`, the number that goes in a profile's context flag and is routinely far below what the model declares.

### specs — M3 acceptance

[`scripts/m3-acceptance.sh`](scripts/m3-acceptance.sh), 27 checks, passed 2026-09-09. Three processes, and **every call goes through the UI's own proxy** — the seam M3 adds and the one no single-component test can reach, since the browser knows no component URLs and a request has to be resolved through the watchdog's topology by kind. Against the live hub, not a mock. Full record: [`docs/acceptance/m3-three-process-run.md`](docs/acceptance/m3-three-process-run.md).

It found a fourth instance of this project's POSIX/Windows path class: a Git Bash path (`/tmp/x`) in a component's config is a *mount*, not a directory, so Python wrote the download to `C:\tmp\…` while the shell looked under `AppData\Local\Temp`. Both halves were internally correct and disagreed about where the disk is. Translate at the boundary — `cygpath -m` going in, `cygpath -u` coming back.

### specs — M4 (second engine: vLLM)

M4 is "supervise something that is not llama.cpp". Design, with every upstream claim read off vLLM's own source at v0.29.0 and the file named at each one: [`docs/design/m4-second-engine-vllm.md`](docs/design/m4-second-engine-vllm.md).

**Unlike M0–M3, no live run stands behind this.** The dev box is Windows and vLLM has no Windows build, so the contracts and the adapter land with fixture tests and the acceptance run waits for a Linux host (decided 2026-09-09). The design doc says so where it will be read rather than in a footnote.

**Smaller than predicted in one direction.** The main design doc called M4 "a second adapter and a second driver kind". There is no second driver kind: vLLM speaks OpenAI-compatible HTTP, so `BackendKind.openai_compat_http` already covers it and the wire-protocol half of the two-layer split needs nothing. `EngineKind` gains `vllm`; the engine half needs all of the work. That is the `EngineKind` / `BackendKind` separation earning its keep on the first case that tested it.

**And more interesting in another — readiness is inverted.** `llama-server` answers `/health` while loading and reports that it is loading. vLLM binds its listening socket *before* the engine initialises (deliberately, upstream #8204) and does not `listen()` until the model is resident, so for minutes it is indistinguishable over the network from a process that died. `loading` versus `crashed` therefore becomes decidable only from the process handle — which the supervisor holds and a driver never sees. `RuntimeStatus` is redefined by what its states *mean* rather than by how one engine reports them, and the new rule is that for an engine which does not answer while loading, a live process answering nothing **is** `loading`. This is the locked "lifecycle adapters live in the supervisor" decision turning out to rest on more than convenience.

**Engine acquisition stays llama.cpp only** (decided 2026-09-09, settling the design doc's open question). vLLM's unit of installation is a Python environment — an interpreter version we do not control (3.12 exactly, for the ROCm and Intel wheels), several GB per retained copy, three of six targets on a non-default index, Apple silicon on a separate project, and no digest that verifies the result. So `EngineAcquisition` gains **`policy: managed | manual`**, separate from `installable` because they answer different questions: `installable: false` under `managed` means *not on this host* (Linux + NVIDIA llama.cpp), while `manual` means *not by us, anywhere*, and the UI owes instructions rather than a disabled button. New **`ManualInstall`** carries the command for the detected host, with `docsUrl` required — upstream's page stays correct longer than any copy of it we make.

- **`PythonEngine`** on `EngineDescriptor` describes the environment a Python engine was found in: interpreter, Python version, package version, PyTorch version *including its build tag*, and a **`FrameworkAccelerator`**. Deliberately separate from `HostAccelerator`: that says what the machine has, this says what the wheel was built for, and a CUDA box running a CPU-only PyTorch is a real, quiet failure visible only as the disagreement between them. Same justification as `ManagedEngine.variant` — recorded because it answers "why is this slow".
- **`vllmBinary`**, a `file_path` in the watchdog's config trio, is the install-wide path to the operator's `vllm` console script. Without it a perfectly good venv reads as unavailable, since discovery only checked the managed store and `PATH`. A config field rather than a new endpoint, so the generic editor renders it with no engine-specific UI code.
- **`RuntimeSpec.modelAlias`'s resolved value is now always passed to the engine.** vLLM's default served name is the `--model` argument verbatim, and we launch by absolute path — so leaving it unset publishes `/home/you/models/Qwen3-8B` as an OpenAI model id, leaking the operator's layout and making the routing key differ per host for the same model. llama.cpp derives its default from the filename and would have been fine, which is exactly why this was invisible until a second engine existed.
- **`modelFormats` for `vllm` is `safetensors` only.** Upstream's GGUF path is documented as highly experimental and needs a second `--tokenizer` model, so claiming the format would light up a Launch button across the whole GGUF population llama.cpp already serves properly. The description also now says what the format join actually buys: a first filter, not a promise — vLLM's model registry is the authority on architectures and answers only at spawn.

**The M2 routing gap closes here** rather than at M5. Launching a model declared a runtime and stopped, so the model loaded, served, and was unreachable. `RuntimeSpec.name` has claimed since M0 to be "referenced by an inference-driver's config to say which runtime it fronts" and no such field existed; now **`runtimeName`** does, with **`ConfigValueType.runtime_name`** so the generic editor renders it as a dropdown off `GET /v1/runtimes` (`componentKindHint` cannot do this — a runtime is deliberately not a component). **`DriverInfo.runtime`** and **`DriverHealth.runtime`** carry it up so a mis-wired install is visible in the routing table. The point is not saving a copy-paste: the watchdog assigns the port, so a literal `baseUrl` encodes a number the operator never chose and is wrong the moment the runtime moves. Who *creates* a driver is still M5.

Two drift fixes ride along, per M1's precedent of spending one re-pin on both: `gateway.yaml`'s two prose references to `DriverEntry`, deleted at the strip, now describe the `drivers` config instead.

**Re-pin radius: all five consumers — and reference-counting says otherwise, wrongly.** There are five, not four: `watchdog`, `gateway`, `inference-driver`, `library` and `ui`, the last generating TypeScript from all four spec documents via `openapi-typescript`. `EngineKind` is named only by `watchdog.yaml` and `library.yaml`, which suggests the gateway and driver stay byte-identical. They do not: `datamodel-code-generator` emits *every* schema in the components document, not the reachable subset, so the gateway's generated module has carried an unused `EngineKind` and `ModelFormat` since M0 and an `EngineKind`-only change still moves it. This refines M3's note rather than contradicting it — M3's radius really was two, because it changed only `library.yaml`, a separate top-level document. The rule that survives is the one M3 stated: **generate both sides and diff them.** Counting `$ref`s looks like the same check and is not.

Validated with `openapi-spec-validator` 0.8.5 and `@redocly/cli` 2.51.2; all four spec documents generate importable Pydantic v2 models. `ui`'s TypeScript generation was not exercised — the gap that hid the fifth consumer. `FrameworkAccelerator` is a named schema rather than an inline enum because a second inline `accelerator` arrived from codegen as `Accelerator1`.

### specs — M5 (multi-host, trust, and the control root) — design only

Inserted 2026-09-09 **ahead of** lifecycle policy, pushing M5→M6 and M6→M7, and **M4's implementation is paused for it**. Design: [`docs/design/m5-multi-host-and-trust.md`](docs/design/m5-multi-host-and-trust.md). No contracts have changed yet; this entry records the design and its decisions.

**Why it jumps the queue.** Multi-host is *designed* today — `Component.spawn` being absent already means "remote", and the gateway resolves remote driver URLs from topology — but it is **not authenticable**. The watchdog holds "the install's trust root" and service tokens are "rotated on each watchdog restart", so a driver spawned by watchdog B rejects a token signed by watchdog A. Add one master key per watchdog, per-watchdog `/v1/runtimes` with no union view, and an `os_keyring` mode that is inherently host-bound, and N hosts means N passphrases, N UIs and N key domains: uncoordinated rather than merely incomplete. A distributed trust model is expensive to retrofit, which is the whole argument for doing it before more milestones land code that assumes one host.

**The watchdog splits into a control root and a node agent** — two components, not one binary with a role flag, per the generative rule: supervision is per-host and there are N of them, while the trust root, install topology and UI are inherently one. The agent is today's watchdog minus the trust root, keeping every bit of the supervision machinery. Crucially **the agent supervises the control root** as just another local component, which is what stops the split from needing a second copy of the supervisor — "components share schemas, not code" would make that a genuine copy, not an import. `ComponentKind` gains `control`; the agent stays out of it for the same reason the watchdog never was in it. Cost stated plainly: a single-host install runs six processes where five sufficed.

**Per-node sealing replaces the install-wide master key.** Each node gets an identity keypair at enrollment whose private half never leaves it, and a secret is sealed to the node whose component will read it — topology already says which that is. The control root never holds plaintext, and never holds a key that reads every node's secrets in normal operation. Every secret carries a second **recovery recipient** sealed under the passphrase-derived key, unsealed only during explicit recovery, so a dead node's secrets are not lost. Blast radius becomes: one node compromised yields that node's secrets; the control root alone yields nothing. The driver was "GPUs in different physical buildings" — one compromised remote box yielding every credential in the install is the wrong shape.

**Warm standby, log-shaped, deliberately not Raft.** The decision that matters is that control state is a **single-writer ordered log** rather than a copied blob: every mutation goes through one choke point that stamps a monotonic index, the existing topology file becomes the snapshot, and timestamps are never used for ordering so clock skew between buildings stays out of the correctness argument. That keeps a later move to consensus a **swap of transport and election** rather than a rewrite — the log, apply function, snapshot and epoch all already exist, and only the commit rule ("leader applied" → "majority acknowledged") and the election would change. Recorded honestly: mature Raft is Go and Rust, so for Python components going hot means a sidecar dependency or hand-written consensus, and the value being protected here is a *management* plane, not data integrity — unlike Ceph, which implements quorum because it *is* the storage layer and has nothing to stand on.

- **`down` versus `out`**, borrowed from Ceph because the distinction is the one that matters. An agent `down` means its runtimes are unknown, not dead; `out` means the operator removes it. A control root `down` pauses *management* while **inference continues**; `out` means the operator promotes a standby. **A control root is never marked `out` automatically** — no `mon_osd_down_out_interval` equivalent — because automatic promotion without quorum is split-brain by definition. That single property is what makes two-hosts-claiming-root structurally impossible rather than merely unlikely.
- **Epoch fencing** gives safety without consensus: every control root carries a monotonic epoch, agents record the highest they have seen and refuse to go backwards, and promotion increments it. A returning old root is fenced permanently, with no election and **no agent needing to agree with any other agent**. The caveat is written into the doc rather than left to be discovered — an agent partitioned *during* a promotion still trusts the old root until it reconnects, which is bounded to the partitioned nodes, visible on the dashboard as an epoch disagreement, and self-healing.
- **Revocation is a rotation, not a deletion.** A revoked node still *holds* the signing key, so removing its registry row does not stop it authenticating. Revoking therefore rotates the signing key across every remaining node — which is why rotation becomes a first-class distributed operation with its own log entry, and why "rotated on each watchdog restart" has to stop being true: with N nodes a restart that re-keys everything is an outage.
- **`Node.accelerators` is the cross-host hardware inventory M3 deferred**, landing exactly where M3 predicted — *"topology work, and it belongs to the watchdog if it belongs anywhere."* M3's fit surface already takes a hardware override and reports which host it measured, so multi-host fit scoring works the moment nodes exist. Pre-wiring, not retrofitting.

**Names settled, and the rename executed.** The two components are **`control`** and **`agent`**. `agent` because there is one per host reporting to a central authority — the sense Consul, Nomad, Datadog and Puppet all use — and because the name it replaces was a survivor of the retired anatomical scheme (the watchdog was the *medulla*) rather than a description of the job. Weighed and accepted against it: in an LLM product "agent" also reads as an autonomous AI agent; the `control`/`agent` pairing disambiguates and the fleet-daemon sense is older and still dominant in ops. `control` because the product is already described as a control plane.

`watchdog` → `agent` is **done in the org and in this repo** (2026-09-09): the repo is renamed with redirects, and **`openapi/watchdog.yaml` is now `openapi/agent.yaml`** with 264 replacements across the specs, README, scripts, CI, editor tasks and the M1–M4 design docs. `EUGENE_PLEXUS_WATCHDOG_*` becomes `EUGENE_PLEXUS_AGENT_*`. All four spec documents still validate and generate importable Pydantic v2 models under the new name.

Deliberately **not** rewritten: `docs/acceptance/*`, which are transcripts of runs that really happened under the old name, and the M0–M4 changelog entries above. Rewriting evidence to match a later rename makes the record worse.

One trap the rename introduced and closed in the same commit: the agent's *runtime config* file is also called `agent.yaml`, and `.gitignore` listed it as a bare pattern — which matches `openapi/agent.yaml` too. It only looked harmless because the spec was already tracked, and tracked files ignore `.gitignore`; a fresh clone would have been fine but any future untracked spec would not. The pattern is now root-anchored as `/agent.yaml` with the reason written beside it.

**The rename is half absorbed, deliberately.** `gateway`, `inference-driver`, `library` and `ui` still carry `watchdog` in prose, in their codegen input paths, and in the gateway's and UI's persisted **`watchdogUrl`** config key. Those ride along with the M4 re-pin they need anyway — one pass rather than two, per M1's precedent. Nothing is broken meanwhile *only* because each consumer is pinned to a specs SHA that predates the move, which is the pin model doing exactly what it exists for.

**Contracts landed the same day.** **New `openapi/control.yaml`** (port 8083): 17 paths, 21 operations, 23 schemas — plus `/v1/node` and `/v1/node/enroll` on the agent, `Runtime.node`, `ComponentKind + control`, `ConfigValueType + node_name`, and a shared `ComputeDevice` / `ComputeDeviceKind`. Design §10 records the shape and the four places the built contract departed from the sketch:

- **Nodes are addressed by `{name}`, not `{id}`** — consistent with components and runtimes. A node's *identity* is its `publicKey`; a name is a label a human reads, the keypair is what makes a node the same node across a restart and what a secret is sealed to.
- **The replication surface is explicit:** `GET /v1/control/log?after=` and `GET /v1/control/snapshot`. Standbys **pull** — that keeps one writer, lets a standby measure its own lag honestly, and puts the connection in the direction that survives a firewall between buildings. Log entries carry `epoch` so a standby fences a superseded root out of the log as well as out of the agents, and `at` is documented as informational so clock skew between buildings cannot affect ordering.
- **`RuntimeSpec` did *not* gain a `node`.** Placement lives on the control root's `RuntimePlacementSpec` (`{node, spec}`); the agent's own declaration is unchanged, because an agent supervises only its own host and a `node` field there would be one it cannot act on and could contradict. `Runtime.node` *is* reported, filled from the agent's identity rather than declared, so it cannot disagree with reality.
- **`ComputeDevice`, not `Accelerator`,** and this one was a real trap. The device list belongs in `common.yaml` because it sits on both sides of a join — the agent reports, the control root aggregates — but naming it `Accelerator` collided with the enum generated from `HostAccelerator.accelerator`, which the agent's `engines/host.py` imports by that exact name and uses as `Accelerator.metal`. Codegen resolved the clash by demoting the enum to `Accelerator1`, so an existing import would have silently begun resolving to a Pydantic model and failed at attribute access — discovered only at the agent's next re-pin. `ComputeDevice` avoids it and is the better name regardless, since `cpu` is a member and a CPU is not an accelerator. **Second instance of M4's lesson:** name a schema explicitly whenever a field name repeats across documents, or codegen names it for you.

`LogOp` is a closed enum of the nine control-state mutations, which is the contract-level expression of "one writer, one ordered path" — an operation not in that list is an operation that would not replicate. `KeyRotation` names its phases rather than reporting a percentage, and lists `nodesPending` by name, because "which host is stale" is the question an operator actually has during a rotation that stopped partway.

Validated with `openapi-spec-validator` 0.8.5 and `@redocly/cli`; all five documents generate importable Pydantic v2 models **and** TypeScript that typechecks under `tsc --strict`. That last check is new: not running it at M4 is what hid the fifth consumer.

**Two tests are required deliverables, not nice-to-haves.** *Replay equivalence* — a standby's applied state must be byte-identical to the active root's after applying the same log — is what makes a promotion trustworthy rather than hopeful, and is exactly what consensus would later depend on. And *kill the control root, assert a chat completion still succeeds*, because §1 identified the surviving data path as currently an accident rather than a designed property.

### All five consumers re-pinned — 2026-09-09

One bump carried three specs changes together, per M1's precedent of spending a single re-pin on everything pending: the `watchdog` → `agent` rename (`76f9090`), M4's contracts (`aff219d`) and M5's (`811112b`).

| Repo                                 | Was            | Now       |
| ------------------------------------ | -------------- | --------- |
| `agent` `gateway` `inference-driver` | `8288926` (M2) | `811112b` |
| `library` `ui`                       | `a1e8e46` (M3) | `811112b` |

All five level with `specs` HEAD; tests, mypy, ruff, `tsc --noEmit`, eslint, Prettier and the Next.js production build all green, and every repo's CI passed including the codegen-freshness check that asserts regenerated models match what was committed. The rename is now **fully absorbed**: `openapi/agent.yaml` is the spec, `agentUrl` is the config key, `ui/src/lib/agent.ts` is the module. Nothing was broken in the interim only because each consumer had been pinned to a SHA predating the move.

**Three things the re-pin shook out, all of them contract changes masquerading as broken code.**

- **The library's `test_an_unknown_engine_is_rejected_by_the_schema` used `vllm` as its example of an unknown engine.** M4 made `vllm` real, so the profile started being *accepted* and the assertion failed — a passing contract change that looks exactly like a regression. The value is now `not_an_engine`: a negative test wants something the enum cannot grow into, not the next item on the roadmap. `mlx` would have re-broken it later.
- **The agent's `test_registry_covers_every_engine_kind` failed,** because `EngineKind` gained `vllm` and no adapter is registered. The test is right — the enum and the registry are two views of one fact — so rather than weaken the parity check, the gap is now *named*: `CONTRACTED_WITHOUT_ADAPTER` lists kinds whose contract landed ahead of their adapter, and a companion test asserts every entry is still genuinely missing one. The allowlist therefore cannot silently keep excusing an engine after its adapter lands, and registering the vLLM adapter is proved by deleting an entry instead of by remembering to. Empty is the correct steady state.
- **`ui/src/lib/watchdog.ts` needed a real file move,** not a text substitution. Rewriting the import sites to `@/lib/agent` without moving the module left `tsc` reporting a missing module *plus* a cluster of downstream implicit-`any` errors that looked unrelated and vanished with the move. A rename script that edits contents and not filenames is a script that half-renames.

**`control` is a sixth consumer that does not exist yet.** Its contract is `openapi/control.yaml`; the repo has not been created.

---

### specs — M7 (second-host readiness)

Landed at `a0d793e`. Design and record: [`docs/design/m7-second-host-readiness.md`](docs/design/m7-second-host-readiness.md), [`docs/acceptance/m7-two-agent-run.md`](docs/acceptance/m7-two-agent-run.md). `common.yaml` untouched; re-pin radius `agent`, `control`, `ui`, the rest bumped for levelness.

- **`agent.yaml`**: `POST /v1/node/rekey`, declared for the first time — control's rotation had called it since M5. `security: []`; the credential is an Ed25519 signature by the control identity over a three-field canonical message, and 409 on a lower epoch is where fencing happens. `RekeyRequest`. `NodeIdentity` + `advertiseUrl`, `signingKeyId`, `controlPublicKey`. `Component.advertiseUrl` (read-only, derived). `POST /v1/runtimes` accepts `service:control`. The agent's port is a setting.
- **`control.yaml`**: `EnrollmentRequest.url` — without it every really-enrolled node had no address. `Enrollment.signingKeyId`. Promotion announces its epoch through the signed re-key with the key unchanged.

## Superseded — local-LLM-training platform (v0.3 direction)

> Archived 2026-09-08. Contracts only ever landed as schemas; no implementation shipped. The documents are deleted from `openapi/` but preserved in git history at `113559a`.


Direction change: Eugene Plexus expands into a full-stack, UI-driven platform for local LLM training, evaluation, and inference. This first spec PR introduces the `TrainingProject` abstraction and the contracts for six new components. Schemas only — no implementation yet. Contracts are drafted upfront (not incrementally) so they don't conflict at integration time; implementation lands later, starting with `data` + `trainer`.

### specs

- **`ComponentKind` extended** with `coordinator`, `trainer`, `data`, `eval`, `inference`, `cluster`.
- **New shared schemas in `common.yaml`** — the `TrainingProject` family (`TrainingProject`, `TrainingGoal`, `ModelTemplate`, `ArchitectureConfig`, `TrainingRecipe`, `Hyperparameters`, `HardwareTopology`, `TrainingRun`, `RunStatus`, `TrainingMetricPoint`, `Checkpoint`, `CheckpointRef`, `DatasetRef`, `TokenizerRef`, `EvalSuiteRef`, `ExportSettings`) plus the coordinator pipeline + hand-off schemas (`PipelineRun`, `PipelineStage`, `PipelineStatus`, `TrainingRunRequest`).
- **New spec files** — full `coordinator.yaml` (owns the `TrainingProject` aggregate and sequences pipeline runs across components) and `training.yaml` (executes training runs, owns checkpoints); thin `data.yaml` / `eval.yaml` / `inference.yaml` stubs; deferred `cluster.yaml` placeholder (multi-host, post single-host milestone).
- **Component ports** — coordinator 8086, trainer 8087, data 8088, eval 8089, inference 8090, cluster 8091.
- **CI** — the six new top-level specs are added to the Redocly lint set.

---

## v0.2.0 — 2026-05-25 (shipping; pending tag)

The "Eugene gains agency" release. v0.1 was a working bicameral loop with a thin shared system prompt and no persistence. v0.2 turns Eugene into a multi-component organism: a stored identity that survives restarts, person-keyed memory, drives-and-NT modulation of the deliberation loop, and a first external sense organ (the Discord-aware `connector`). Late in the cycle, three architectural fixes to the user-facing reply path raised the practical persona ceiling further than any of the v0.2 features could have on their own.

Eight repos under `github.com/eugene-plexus`: `specs`, `orchestrator`, `hemisphere-driver`, `ui`, `watchdog`, `memory`, plus the new `identity` and `connector`.

### Security

A complete identity-and-secret arc grafted on top of v0.1's anonymous LAN-only assumption.

- **Argon2id passphrase + master-key derivation.** First-run wizard takes an operator passphrase, derives a master key via Argon2id, stashes salt + verifier on the watchdog. Subsequent boots prompt, re-derive, hold the master key in memory only.
- **OS keyring auto-unlock** (opt-in). Switch `securityMode` to `os_keyring` and the master key persists to the system keyring so Eugene boots unattended. Passphrase still works if the keyring is unavailable.
- **libsodium secretbox at-rest encryption** for sensitive config fields (`apiKey`, `botToken`). Plaintext is never written to YAML once a master key exists.
- **JWT bearer auth across all components.** Watchdog mints session tokens for the operator and service tokens for inter-component calls. Every body component verifies against the shared signing key without holding the secret itself.
- **Restart-on-login**: when the operator first sets up, the watchdog restarts supervised children so they all receive the freshly-derived master key as an env var.
- **`/login` page + session management** in the UI. Pre-init probe so the unlock vs. set-passphrase screen doesn't flash the wrong copy. Sign-out revokes server-side.

### New component: `identity`

A "default mode network" for Eugene — the constitution + self-model + relationship layer that the orchestrator consults before every chat turn.

- **Constitution** — declarative facts (name, pronouns, core values, free-text).
- **Self-model** — patterns Eugene notices about himself over time. Manually editable; reflection populates programmatically.
- **Persons** — people Eugene knows. One operator (you) is created at first run; others land via the pending-link flow from the connector.
- **Platform aliases** — `{platform, accountId}` pairs mapping external chat-platform users to a `personId`. Spoof resistance lives here.
- **Pending identity links** — unknown platform users → adapter files a pending link, replies "ask the operator to authorize," STOPS. No orchestrator call until the operator approves.
- **Reflection backend** — `POST /v1/identity/self-model/reflect` reads recent memory turns, asks a hemisphere driver to extract self-model observations, persists them. End-to-end shipped; NT-driven autonomy is v0.3.

### Memory upgrades

- **Person-keyed entries.** Every turn carries `personId` of who said it. Global timeline + per-person retrieval. Both ends of a chat turn (user message + Eugene's reply) are now full `MemoryEntry` objects with personId + NT snapshot + hemisphere attribution.
- **Backend registry.** `backend: local_sqlite` (default, durable) and `backend: in_process` (volatile, for tests / short-lived experiments). Schema is the same; storage is pluggable.
- **Recent-turns context** — orchestrator pulls recent turns with the speaker on every chat turn and injects them into per-hemisphere prompts as concrete relationship context.
- **Search wire-stub** — endpoint accepts the request shape and returns 503; sentence-transformers backend lands in v0.3.

### NT system (drives-and-modulation)

Eugene now has internal state that evolves across turns and modulates the bicameral loop.

- **Live state** — per-NT `{level, baseline, decay}` shape on `NTState`. Persisted snapshot lives on every memory entry so future analyses can correlate output style against state.
- **Observation impulses** — final-pass agreement, pass count, average pass latency feed back into NT state at end of each turn.
- **Modulated `max_passes`** — anxious / alert Eugene gets more deliberation passes; calm Eugene short-circuits.
- **Modulated `temperature`** — dopamine / GABA stretch or compress per-pass temperature.

Modulation is live but parameter tuning is empirical; expect shifts in v0.3 as we get real operator observation data.

### New component: `connector` + Discord adapter

The first external sense organ. Bridges Discord (today; Slack/Matrix/Telegram/Gmail in v0.3+) to Eugene's chat surface.

- **Adapter registry** — one connector process can host multiple platform adapters. Adding a kind is one class implementing the `Adapter` protocol; the UI's `ConnectorPanel` discovers each adapter's config schema at runtime via `GET /v1/adapters/{name}/config/schema` and renders it with the same machinery as the rest of the UI.
- **Discord adapter** — DMs always honored; `@<bot>` mentions in operator-allowlisted channels. Channel-context lookback (last N messages before the mention) goes to the orchestrator as prompt-side context, NOT persisted to memory.
- **Pending-link flow** — unknown Discord users → adapter files a `PendingIdentityLink` on identity, replies "ask the operator to authorize this link" on the platform, STOP. Spoof-resistant by construction.
- **Operator runbook** at [`connector/docs/discord-setup.md`](https://github.com/eugene-plexus/connector/blob/main/docs/discord-setup.md) — 10-section end-to-end walkthrough from "I have a running install" to "Eugene replies to my DMs."

### Persona ceiling (v0.2.x architectural fixes)

A late-cycle empirical finding: the bicameral architecture's persona ceiling was limited not by which models were in the hemispheres but by how the user-facing reply got produced. Three changes lifted the practical ceiling substantially.

- **Voice pass** — a single post-deliberation LLM call that converts the inner-dialog register of the hemispheres into a user-facing reply. The hemispheres' raw outputs become diagnostic artifacts; the voice pass output IS the user-facing message. `voiceDriver` is operator-configurable (defaults to first driver). The voice driver choice is empirically the **persona lever** — same hemispheres, only the voice driver swapped, takes user-facing output from helpful-assistant to short/dismissive/in-character.
- **Scratchpad structure** — deliberation summary lives in the voice pass's system message as private notes the model can't address, not as a trailing user-role message. The prior structure made the model address the deliberation back at the user, producing "you just narrated my internal monologue back at me"-shaped responses.
- **Social-context directive** — voice pass directive includes explicit anti-helpful-assistant language ("if the message is confusing, weird, or a strange opener, react to THAT, briefly. Don't explain, don't catalog, don't lecture."). Real-person-like reactions to unusual openers are now reachable.
- **Embedding-based agreement scoring** — Jaccard word-overlap replaced with sentence-transformer cosine similarity (`all-MiniLM-L6-v2` default, operator-configurable). Two responses meaning the same thing in different words now score 0.7-0.85 instead of 0.05-0.15; the loop terminates at the actual point of substantive agreement instead of grinding to `cap_reached`. `agreementThreshold` default bumped 0.5 → 0.75 to match the embedding cosine scale.
- **Thicker `DEFAULT_SYSTEM_PROMPT`** — explicit `Format requirements:` (first person, no speaker labels, no script format, one contiguous response) ahead of `Character:`. Anti-script directives are no-ops for commercial models and load-bearing for less-RLHF'd models. Side effect: commercial models also produce tighter defensive responses with the thicker prompt.

Net effect: where v0.1 produced a polished essay for *every* prompt, v0.2.x produces "What? I don't know what that's supposed to mean. Are you quoting something?" to a weird opener and "I like some of it — mostly the older stuff. Miles Davis, John Coltrane — that era" to a normal one. Both registers from the same baseline.

### First-run wizard

Linear 10-screen flow (v0.1 had 7; v0.2 inserted Security, then split Memory / Identity / Connector out of one screen):

1. Look & feel — local theme + font, live preview
2. **Security** (new) — passphrase + securityMode
3. Welcome — plain-language "body parts" framing
4. Deployment — all-local vs. networked
5. Orchestrator host:port (networked only)
6. Driver 1 — provider + credential + model
7. Driver 2 — same with a "pick a different vendor" hint
8. **Memory** (new screen) — backend choice + path
9. **Identity** (new screen) — display name override + reflection wiring
10. **Connectors + Start** (new screen) — Discord opt-in, summary, Start

Transactional commit: the wizard treats the whole flow as one transaction. Initialize → security mode → driver configs → memory → identity → orchestrator's `identityUrl` → connector adapter → `firstRunComplete: true` → restart everything that picked up new config.

A visual progress bar in the wizard header animates fill width across screen transitions.

### UI polish

- **Combobox for `suggestions`-bearing string fields.** The new `ConfigField.suggestions` spec field lets backends emit advisory dropdowns alongside free-text input. `modelId` (live model list from the driver) and `voiceDriver` (configured driver topology) both use this. Operators pick from a dropdown OR paste an id the backend doesn't know about yet (just-pulled Ollama model, just-deployed custom endpoint) — validation accepts either.
- **Auto-restart on save.** When a config patch requires a restart, `ConfigEditor.save()` triggers `performRestart()` directly. The "restart now? / later" confirmation modal is gone. The progress modal still surfaces and the success phase auto-dismisses after 1.5s. Click count for a restart-required change went from 5+ to 2.
- **Theme-aware status banner CSS.** Modern light theme is now readable — previous amber/rose/emerald palette was dark-theme-only. `--status-{success,warn,error}-{fg,bg,border}` variables drive `.status-*` and `.text-status-*` utility classes.
- **`CopyTraceButton`** — diagnostic component that copies the full bicameral trace of the most recent turn as Markdown (user prompt + per-pass inputs/outputs + voice pass input/output + final response). Pastes cleanly into a Claude follow-up or a GitHub issue.
- **`ConnectorPanel`** — Settings + Adapters sub-tabs in `/config`. Add / configure / test / delete adapters with schema-driven editor. v0.3+ adapter kinds drop in without UI changes.
- **Error clearing on user action** — ConfigEditor and ConnectorPanel clear last test/save status on any field edit, preventing stale "test failed" banners from persisting next to successful saves.

### Hemisphere-driver

- **`thinkingMode` config field** (auto / off / low / medium / high). Controls reasoning-block emission for thinking models (MiniMax-M2, DeepSeek). `off` appends an anti-reasoning system-prompt directive AND strips `<think>...</think>` blocks post-response. Solved cases where reasoning leaked into the user-facing chat surface.
- **At-rest encryption for sensitive fields** (`apiKey`) — libsodium secretbox envelopes, plaintext never written to disk once a master key exists.
- **Local providers don't require API keys.** Ollama + LM Studio adapters set `auth_required: false`; engine no longer rejects construction on a blank `apiKey` for these. Bearer header is omitted from outbound calls when the key is empty.
- **Local providers don't filter the model list.** The chat-prefix heuristic stays on for OpenAI (filters out embeddings / audio / image models) but is off for local servers that list ONLY what the operator pulled.
- **`modelId` carries suggestions instead of a strict enum.** The discovered model list is advisory; the operator can paste a just-pulled id without losing it to validation.

### Spec additions

- `ConfigField.suggestions: string[]` — advisory discovery hints; UIs render as combobox.
- `ConfigField.componentKindHint: ComponentKind` — declarative "this field points at a peer component of this kind"; UI renders kind-hinted fields as dropdowns sourced from the watchdog topology with `(off)` as the first option. Stops operators from copy-pasting URLs they shouldn't need to know.
- `ComponentKind` relocated from `watchdog.yaml` to `common.yaml` — multiple components now reference it (watchdog directly, anyone using `componentKindHint` indirectly).
- `PassRecord.hemisphereInputs: HemisphereInput[]` — per-driver input snapshots for diagnostic traces.
- `VoicePassRecord` + `ChatResponse.voicePass` — voice-pass driver name, input messages, output, latency.
- `Health.safeMode: bool` — uniform safe-mode reporting across components.
- `ComponentKind.identity` + `ComponentKind.connector` — watchdog topology kinds for the new components.
- Full v0.2 entity set: `Constitution`, `SelfModelEntry`, `Person`, `PlatformAlias`, `PendingIdentityLink`, `RelationshipSummary`, `MemoryEntry`, `MemorySearchRequest/Result/Hit`, `MemoryBackendKind`, `AdapterEntry`, `AdapterKind`, `MessageSource`, `ChannelContextEntry`, `MasterKeyEnvelope`, `SecurityMode`, `AuthLoginRequest/Response`.
- New v0.2 `NTState` shape — per-NT `{level, baseline, decay}` + `lastUpdated`.

### Fixes

- **Proxy trailing-slash bug** — watchdog topology URLs arrive with a trailing slash; naive concatenation produced double-slash paths that FastAPI 404'd. Affected Memory / Identity / Connector config tabs. Normalized in the proxy.
- **Chat page auth gate** — probes `/v1/auth/status` (public endpoint, no auth cost) before any `/v1/config` call so the auto-redirect-on-401 path can't bounce a fresh install through `/login` on its way to `/setup`.
- **Proxy auth threading** — incoming `Authorization` header forwarded to the resolver so per-driver `/v1/config` lookups don't 401 when the orchestrator's resolve path needs auth.
- **`<think>` block leaks** — thinking-mode `off` strips them with a post-response regex pass even when the upstream chat template ignores the prompt directive.

### Late hardening (post-smoke-test, 2026-05-25)

Items surfaced during the v0.2 smoke test and fixed before the tag.

- **Identity startup deadlock (release blocker).** `IdentityStore.ensure_operator()` held a non-reentrant `threading.Lock` while calling `get_person()`, which tried to re-acquire it. First boot worked (no row → fell through to the lock-released `create_person` path); every subsequent boot deadlocked silently — no traceback, no crash counter. Fixed by closing the `with self._lock:` block before the cross-call. Regression test runs the second `ensure_operator()` on a background thread with a 5s join-timeout, so a future re-introduction fails an assertion instead of hanging the suite.
- **Identity lifespan diagnostics.** Each step inside the lifespan now emits a `log.info("lifespan: <step>")` checkpoint and is wrapped in `asyncio.wait_for(..., timeout=30s)`. Future silent stalls surface as `TimeoutError` tracebacks with the exact step pinpointed. `logging.basicConfig(level=INFO)` added in `__main__.py` so the checkpoints actually reach stdout (uvicorn's `log_level=` only touches `uvicorn.*` loggers).
- **Reflection peer URLs require restart to take effect.** `reflectionHemisphereUrl` / `reflectionMemoryUrl` were missing `requiresRestart=True`. The cached `hemisphere_client` / `memory_client` are built once in the lifespan; PATCH'd URLs didn't change runtime behavior until restart. UI auto-restart-on-save now triggers correctly.
- **Watchdog supervisor pipes + prefixes child output.** Children inherited the parent terminal, so concurrent boots produced an unlabeled wall of `INFO: Waiting for application startup` with no source identification. Supervisor now PIPEs each child's stdout (with stderr merged), spawns a reader task per child, and re-emits lines as `[<name>] <line>`. Drivers (which can be named arbitrarily by operators) get the disambiguated prefix `[driver: <name>]` so a renamed driver is unmistakable.
- **Watchdog log signal-to-noise.** 2xx `/healthz` access logs (~24 lines/min across the body) are suppressed at the reader; non-2xx pass through so a newly-unhealthy component is still visible. `error` / `warning` words get ANSI color (red/yellow, word-only — full-line color is unreadable on dark terminals); honors `NO_COLOR` env var as the documented opt-out.
- **Watchdog rotating-file log capture.** `sys.stdout` / `sys.stderr` are mirrored to `<watchdog.yaml dir>/logs/watchdog.log` (10 MB × 5 backups = 50 MB cap). Operators get a sharable bug-report artifact without redirecting stdout at task-launch time or learning env vars; GUI-equality principle.
- **Peer-reference dropdowns end-to-end** (the `componentKindHint` rollout above). The 7 fields that adopted it: `identity.reflectionHemisphereUrl`, `identity.reflectionMemoryUrl`, `orchestrator.memoryUrl`, `orchestrator.identityUrl`, `orchestrator.drivers[].url` (per-row dropdown inside the driver list), `connector.orchestratorUrl`, `connector.identityUrl`. Wire shape unchanged — the hint only changes the input UX. Closes the OpenClaw trap of duplicating watchdog topology into per-component free-text URL fields.
- **`basicConfig` logging across all body components.** Identity / orchestrator / hemisphere-driver / memory / connector were emitting warnings without timestamps because uvicorn's `--log-level` only touches `uvicorn.*` loggers. Added `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)` in each component's `__main__.py` before `uvicorn.run`. Stale "encrypted on disk, no master key available" warnings are now distinguishable from current ones at a glance — surfaced by a smoke-test session where the operator couldn't tell whether the warning was from the failed save five minutes ago or the successful one thirty seconds ago.
- **Auto-engage safe mode after repeated crashes.** Watchdog supervisor flips a component to safe-mode after `autoSafeModeAfterCrashes` (default 5) consecutive crashes, and gives up entirely after twice that (default 10). Closes the "config edit soft-bricks the install" failure mode without needing operator intervention — paired with the GUI-equality principle (operator never needs to set an env var to recover). `restart()` clears the auto-engaged flag so the operator can re-test after the fix.
- **`POST /v1/config/test` on the watchdog.** Probes an OS keyring round-trip when `securityMode=os_keyring` (or under explicit override). UI Test button on the Watchdog tab now has something to talk to — was 404 before. Lets operators verify keyring access works before relying on auto-unlock at next boot.
- **`personRecentLimit` default bumped 10 → 30.** Smoke-test caught Eugene confabulating personal history because the recent-turns slice for the speaker was too short — the relevant prior turn had aged out of context. Bumping to 30 fixes the confabulation without measurable latency cost (the slice is system-prompt material, not user-input length).
- **Discord adapter UX fixes.** Pending-link reply reworded from "ask the operator to authorize this link" (ambiguous — sounded like it referred to the Discord connector itself, not the speaker's identity) to point explicitly at the Identity → Pending screen. Typing indicator wraps the orchestrator call so users see Eugene is "thinking" while passes run. Orchestrator-side failures now send a Discord fallback message including the exception class — previously a 502 fell silently through `on_message`'s try/except and the Discord user got nothing.
- **`ConnectorPanel` polls while transient.** After adapter save, panel polls `/v1/adapters` at 1.5s while any adapter is in `starting` or `rate_limited`. Previous one-shot reload raced the adapter's background task and left the UI saying "launching" until the next manual refresh, even when the adapter had already errored out.

### Late UI polish (post-smoke-test, 2026-05-25)

- **"Thought for X.Xs ›" chip.** ChatGPT-style chip rendered above the latest Eugene response showing total turn latency. Click expands to show pass count, agreement score, termination decision, voice driver, and per-pass mini-summary. Makes bicameral pass behavior legible without opening DevTools or pulling the trace via `CopyTraceButton`.
- **Watchdog tab on the Config page.** Closes the gap where the watchdog had a config endpoint but no UI tab. `Test` button drives the new `POST /v1/config/test` for keyring round-trip verification.
- **Pre-render auth gate.** Chat page checks `hasSessionToken()` before any authed call and redirects to `/login?next=...` if missing — the underlying page no longer paints first when an unauthenticated user arrives, which had been a small security smell (operator UI flash before the login modal popped). Catch path distinguishes `ApiError(401)` (stays in "checking" until the redirect completes) from other errors so the redirect can't be raced.
- **`--radius` theme token.** Bubble / badge / button / pass-card / modal / form-field switched from `rounded-md` to `rounded-[var(--radius)]` so themes can pick their own corner radius without per-component overrides. 118 swaps across 15 files. `rounded-full` (pills, dots, scrollbar) is intentionally untouched. `--pad` token added alongside for density tuning (declared per theme; not yet wired into spacing utilities — v0.3).

### Three themes (Cyberpunk / Modern / Editorial)

The token framework introduced by `--radius` + `--pad` paid off immediately: Claude Design produced three theme presets that each compose into roughly 50 lines of CSS without touching component code. Validates that the token framework holds up cleanly for new themes.

- **Cyberpunk** — Miami '26 palette (replaces the prior v0.2 cyberpunk colors). Dark violet (#0c0820) base, teal + pink accents (#1bd9c2 / #ff7ac0), Space Grotesk + JetBrains Mono. 4px corners, bubble blur, perimeter-pulse thinking animation. Default theme.
- **Modern** — light theme refresh. Near-white (#fafafb) base, deep blue + magenta accents (#2a55e6 / #cf3a85), Inter + JetBrains Mono, 6px corners, spinner-rail thinking state.
- **Editorial** (new third theme) — newsprint cream (#faf7f1) base, forest green + rust accents (#2d6240 / #a23b29), DM Sans throughout, 6px corners, no bubble blur, no Eugene letterform showing through the chrome.

`system` theme resolves to Cyberpunk (dark OS) or Modern (light OS) via `prefers-color-scheme`; Editorial is an explicit operator pick (it's a third option, not an OS-level concept).

### Known limitations (carried into v0.3)

- **Pending-link approval is API-only.** Operator runs curl against `/v1/identity/links/pending/{id}/approve` until the UI panel ships.
- **Memory search returns 503.** Storage half is done; sentence-transformers embedding backend (and the GET path) is the deferred piece.
- **One conversation per Discord message.** Each inbound message starts a fresh conversation; threading lands in v0.3.
- **NT modulation parameters are empirical placeholders.** Defaults work but haven't been tuned against real operator observation data.
- **No streaming chat.** `/v1/chat/stream` returns 501.
- **One operator per install.** Multi-operator support is v0.3+.
- **Reflection is manual-trigger only.** NT-driven idle-state mind-wandering is v0.3.
- **No voice-driver awareness of NT state.** v0.2 picks the voice driver from operator config; v0.3 should make this NT-aware so anxious Eugene picks a terser model than calm Eugene.

### Migration from v0.1

v0.1 installs need to:
1. Pull the new v0.2 repos (`identity`, `connector`, `memory` with v0.2 backend, watchdog with auth, all components with v0.2.x voice-pass + agreement scorer).
2. Run the wizard from scratch — v0.1 didn't persist a passphrase. The wizard's first-run path will set one up.
3. v0.1 `defaultSystemPrompt` is replaced with the thicker v0.2.x default. Custom prompts are preserved if you've already edited yours.
4. Hemisphere-driver configs from v0.1 keep working — the `provider` / `modelId` shape is unchanged. `thinkingMode` defaults to `auto`.

### Component versions

| Repo                | v0.2.0 HEAD |
| ------------------- | ----------- |
| `specs`             | `052fd19`   |
| `orchestrator`      | `9c26fe0`   |
| `hemisphere-driver` | `254038e`   |
| `ui`                | `9196d5b`   |
| `watchdog`          | `f84ab84`   |
| `memory`            | `3fbf9b2`   |
| `identity`          | `ca19f0a`   |
| `connector`         | `3c8e1e1`   |

---

## v0.1.0 — 2026-05-10

The initial release. A working bicameral loop across two hemisphere-driver instances, served through a Next.js UI.

- Five hemisphere-driver adapters: `anthropic_api`, `openai_api`, `claude_code_cli`, `codex_cli`, `openai_compat_http` (Ollama / vLLM / LM Studio).
- HTTP+JSON + OpenAPI 3.1 schemas for all cross-component contracts; `datamodel-code-generator` (Pydantic v2) + `openapi-typescript` codegen.
- Bicameral loop with Jaccard agreement scoring + multi-pass termination on consensus.
- Per-driver Test buttons, the remote-config protocol on every component, degraded-mode startup so bad config can't soft-brick the install.
- Watchdog process supervisor with orphan-kill protection (Job Object on Windows, prctl on Linux).
- First-run wizard (7 screens — pre-Security, pre-component-split).
- Six body components: orchestrator (8080), 2× hemisphere-driver (8081/8082), memory (8083), UI (3000), watchdog (8079).
