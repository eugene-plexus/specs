# M2 — Model library, both formats (design)

**Status:** contracts landed 2026-09-08. Milestone **M2** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M1](m1-engine-acquisition.md).

Verified against real files on the dev box, not fixtures: two large GGUFs
(21 GB `Q4_K_S`, 15 GB `Q4_K_M`) with their projectors beside them, a
GGUF embedding model, and a HuggingFace cache holding a safetensors model
at two revisions. Every number and metadata key in §1 was read off those
files. §1 is where the milestone's shape came from.

**What it is:** the operator points the control plane at directories they
already keep models in; it scans them, reads what each model actually is,
and holds named per-model launch profiles. Both formats from the start —
GGUF and HF safetensors — because format is a dimension of the data
model, not an assumption (locked 2026-09-08).

**Why now:** M0 and M1 got an engine onto the machine and one model
served. Everything after this needs *the set of models the user owns* to
be a thing the system can enumerate: M3 downloads into it, M5 swaps
between its entries, and the config-profile complaint ("tired of tweaking
llama.cpp settings for every different model") cannot be answered without
somewhere to keep the settings.

**The rule this milestone is built to honour:** the user's model files
stay theirs, in their own directories, under their own names. We read; we
do not relocate, rename, hash-address, or manage a store. Delete us and
every model is still where it was, correctly named.

---

## 1. What is actually on disk

Read off this box, 2026-09-08. Ten findings; most are traps.

### The layouts people already have

```
<root>/<publisher>/<repo>/<file>.gguf      LM Studio's layout, and the de-facto one
<root>/<file>.gguf                          a directory someone dropped files into
<root>/models--<org>--<name>/snapshots/<rev>/   a HuggingFace cache
```

Scanning is therefore **recursive**, and one root can hold all three
shapes at once. A flat listing of `*.gguf` in the root directory finds
nothing on the most common layout in the field.

### Trap 1 — the projector sits beside the model and is not small

```
Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf          16,547,398,784 B
Qwen3.6-27B-GGUF/mmproj-Qwen3.6-27B-BF16.gguf        931,145,856 B
```

A multimodal GGUF ships its vision projector as a second `.gguf` in the
same directory. Report it as a model and the library grows a 900 MB
phantom entry — and on the 40B model beside it, a 1.8 GB one.

The `mmproj-` filename prefix is a **convention**. The file declares
itself properly:

```
general.type         = mmproj      (the model file says `model`)
general.architecture = clip
clip.has_vision_encoder = True
```

Read `general.type`, not the filename — a renamed file still tells the
truth. But note the third finding in that block: **`general.type` is
absent entirely** on the nomic embedding model (23 KV pairs, no
`general.type`). Absence means "model"; do not require the key.

Pairing is by directory plus matching `general.name`, and the projector
becomes `--mmproj` on the launch line. llama-server also has
`--mmproj-auto` and finds it unaided — but the library still reports it,
because "this model can see" is a fact the browser should show and a
profile should be able to override.

### Trap 2 — reading GGUF metadata is not a cheap header read

| File | vocab | KV block | walk, buffered | walk, unbuffered |
|---|---|---|---|---|
| `Qwen3.6-27B-Q4_K_M.gguf` | 248,320 | **10,942,419 B** | 50.6 ms | 57.7 ms |
| `nomic-embed-text-v1.5.Q4_K_M.gguf` | 30,522 | 749,820 B | 6.0 ms | 3.6 ms |
| `mmproj-Qwen3.6-27B-BF16.gguf` | — | 1,183 B | 3.1 ms | 0.04 ms |

`tokenizer.ggml.tokens` and `tokenizer.ggml.merges` are *in the KV
block*, so the metadata a scanner wants is buried behind ~10 MB of
vocabulary. Three consequences, all measured:

- **You cannot skip past a string array in one seek.** Each string's
  length is inline, so stepping 248,320 of them is 248,320 reads of a
  `u64`. That loop, not the I/O, is the cost — buffering the whole
  header into memory first saves 12%, not 90%.
- **You cannot stop early either.** `general.file_type` — the quant — is
  the *last* KV pair in the Qwen file, after the vocab. KV order is not
  specified and the fields you need are on the far side of the big ones.
- So budget **~50–60 ms per large-vocab model, warm**. Fifty models is
  ~3 s warm and half a gigabyte of reads cold. That is why the scan is
  an asynchronous sub-resource with progress rather than a synchronous
  `GET`, and why a rescan is **incremental**: `(path, size, mtime)`
  unchanged means reuse the parsed metadata and never open the file.

### Trap 3 — the quant is an integer, and it does distinguish the mixtures

`general.file_type` is an enum, verified against filenames that agree:

| `file_type` | File says |
|---|---|
| 14 | `…-Q4_K_S.gguf` |
| 15 | `…-Q4_K_M.gguf` |
| 32 | `mmproj-…-BF16.gguf` |
| 0 | `mmproj-F32.gguf` |

So `Q4_K_S` vs `Q4_K_M` — the exact distinction the source thread
complains nobody can explain — is machine-readable, not filename
guesswork. Unknown values do happen (the imatrix and MXFP4 families
churn): **report the raw integer and the filename-derived label, and say
they disagree.** Never map an unrecognised number onto a plausible
neighbour; M3 hangs quant *guidance* off this field and guidance built on
a guess is worse than none.

### Trap 4 — GGUF has no parameter count; safetensors has an exact one

GGUF carries `general.size_label = "27B"` — a **string**, author-supplied
— and no numeric parameter count. To get a number you would have to sum
tensor shapes across the whole tensor-info block.

Safetensors is the reverse. An 11,416-byte header gave the exact count
and dtype for MiniLM-L6:

```
tensors=104  params=22,713,728  dtypes={F32: 22,713,216, I64: 512}
```

The inverted asymmetry lands directly on the contract: `parameters` is
**optional** and exact-or-absent, `sizeLabel` is a display string, and
neither is a required field. A schema requiring a parameter count would
be unfillable for every GGUF in existence.

### Trap 5 — metadata keys are architecture-prefixed

```
general.architecture = qwen35
qwen35.block_count       = 64
qwen35.context_length    = 262144
qwen35.attention.head_count_kv = 4
```

There is no fixed key set. Read `general.architecture` first, then build
the key names from it. A reader with a hardcoded list of keys silently
returns nothing for every architecture released after it was written.

### Trap 6 — a HuggingFace cache multiplies models by revision, differently per OS

```
models--sentence-transformers--all-MiniLM-L6-v2/
  refs/main                                    -> 1110a243…
  snapshots/1110a243…/  config.json, model.safetensors (90,868,376 B), tokenizer.json, …
  snapshots/c9745ed1…/  the same model, an older revision
  blobs/                                       EMPTY on this Windows box
  .no_exist/<rev>/adapter_config.json          zero-byte "we checked, it isn't there"
```

Four separate hazards in one directory:

- **Two snapshots of one model.** A recursive scan reports it twice.
  `refs/main` names the current revision, so the fix is to read it and
  label the others as older revisions rather than as separate models.
- **The layout differs by platform.** On Windows, snapshots hold real
  copies and `blobs/` is empty — verified above. On Linux and macOS the
  data lives in `blobs/<sha>` and snapshots are symlinks into it. A
  scanner that resolves symlinks reports `blobs/<sha256>` as the model's
  identity, which is content-addressing smuggled in through the back
  door; a scanner that double-counts reports twice the disk.
  **Do not resolve symlinks** — the named snapshot path is the identity.
- **`.no_exist/` is a negative cache** full of zero-byte files with real
  names. "Is there an `adapter_config.json`?" finds one there. Skip
  `.no_exist/`, `blobs/` and `refs/` by name.
- This is also the one place content-addressing exists in the wild, and
  we read it without adopting it. We never write into a HF cache.

### Trap 7 — the model's context is not the served context

`qwen35.context_length = 262144`. What llama-server actually serves is
whatever `-c` says, clamped by memory. Both numbers are real and they
live in different components on purpose: the library reports what the
*model* was trained for, `RuntimeCapabilities.contextLength` reports what
the *engine* resolved. Neither is a substitute for the other, and a UI
that shows only the first tells a comfortable lie.

### Trap 8 — the file carries the author's recommended sampling

```
general.sampling.temp  = 1.0
general.sampling.top_k = 20
general.sampling.top_p = 0.95
```

Locked rule: **the gateway owns every LLM-output-affecting parameter** and
no component substitutes a local default. That rule holds — but the model
file having an opinion is new information, and dropping it on the floor
means the operator has to go read the model card to find out.

So: the library **reports** these, verbatim, marked as the author's
recommendation. Nothing applies them. Whether a profile or the gateway
can adopt them with one click is a real question and it is not M2's — see
§7.

### Trap 9 — never pass `-hf`

`llama-server` has `--hf-repo` / `--hf-file` and will download a model
itself, projector included, into its own cache. Using it would put the
user's files somewhere the user did not choose, which is the exact thing
differentiator #3 exists to refuse. **The launch line always carries an
explicit `-m <path>`.** M3's downloader writes plainly-named files into a
directory the operator picked; it does not delegate to the engine.

### Trap 10 — llama.cpp cannot load safetensors

Which makes M2 honest about a gap: safetensors models are scanned,
browsed, described and profiled — and at M2 **nothing can launch them**,
because the only engine adapter that exists is llama.cpp's and it reads
GGUF. vLLM arrives at M4 and is the safetensors path.

The fix is not to hide them. It is to put format support where engine
knowledge already lives: `EngineDescriptor` grows `modelFormats`, the
agent fills it in from each adapter, and the UI joins the two
surfaces to grey out a launch button with a reason that names the
missing engine. The library stays format-agnostic and gains no engine
knowledge — the no-shared-code rule holds. It also pre-wires M4: vLLM's
descriptor lists `safetensors` and the button lights up with no library
change at all.

### While we're here: embedding models are detectable, and mislaunching one is silent

```
nomic-bert.pooling_type       = 1
nomic-bert.attention.causal   = False
```

llama-server's own help says `--embedding` is to "restrict to only
support embedding use case; use only with dedicated embedding models".
Launch that file as a chat model and it starts, serves, and returns
nonsense. A pooling type or non-causal attention in the metadata is
enough to know, so the library reports `capabilities.embedding` and the
profile gets the flag set. This is the cheapest correctness win in the
milestone.

---

## 2. What a model *is*, and what identifies it

**One model is one launchable thing**, which is format-dependent:

| Format | The model is | Not a model |
|---|---|---|
| GGUF | one `.gguf` file | the `mmproj-*` projector; shard members 2..N |
| GGUF, split | the **first** shard, `…-00001-of-0000N.gguf` | shards 2..N individually |
| safetensors | the **directory** holding `config.json` + weights | `blobs/`, `refs/`, `.no_exist/`, an adapter-only dir |

Split GGUF is the one convention here not verified on this box — there is
no split model on it. It is upstream's `llama-gguf-split` output, carries
`split.no` / `split.count` KV pairs, and `-m` takes the first shard.
**Confirm against a real split model before trusting the shard grouping**
— that is exactly the class of assumption M1's traps came from.

**Identity is the path.** The `id` is a URL-safe handle derived from it:
the first 16 hex characters of the SHA-256 of the normalized absolute
path. Normalized means absolute, separators canonicalized, case-folded on
Windows, and **symlinks left unresolved** (Trap 6). It is derived rather
than random so it survives restarts, and every entry reports its `path`
verbatim so nothing is hidden behind it.

This is not content addressing: it never reads a byte of the file. A
40 GB hash on every scan is not on the table, and hashing the *content*
would also mean an identity that changes when nothing the user did
changed.

Clients treat the id as opaque and get it from the list. They do not
compute it — normalization is fiddly enough on Windows that a client
which gets it wrong sees a 404 and no explanation. For the one case that
needs the reverse lookup — the runtime dashboard holding a `modelPath`
and wanting the library entry behind it — `GET /v1/models?path=…`
normalizes server-side and returns the entry or nothing.

**The consequence, stated plainly: move a model and it reads as a new
model.** Its old entry goes `missing` and keeps its profiles, so the
flags that took an afternoon to tune are still there to copy. Nothing
guesses that a file which vanished from one root and appeared in another
is the same file. A relocate action is cheap to add and deliberately not
in M2 (§7) — a wrong guess here silently applies one model's tuning to
another.

**What persists:** profiles, and only profiles. The model list is a scan
projection joined against the profile store. An entry appears if it was
found on disk, or if it has saved profiles. That is what makes
`missing` a real state and `DELETE` meaningful — the delete drops the
saved profiles, which is the only thing we own.

---

## 3. Profiles

A profile is **the launch settings that worked for this model**, named,
with N per model and one default. It answers the "tweaking llama.cpp
settings for every different model" complaint directly.

```
ModelProfile   name, default, engine, flags{}, extraArgs[], env{}, notes?
```

Those field names are `RuntimeSpec`'s field names, deliberately: a
profile maps onto a runtime declaration one-to-one, so composing one
into the other is a copy and not a translation.

**Named, plural, not one-per-model.** Three reasons, and the third is
already scheduled: a long-context profile and a fast one are different
GPU-layer and `-c` settings on the same file; a model you sometimes run
CPU-only is a second profile, not an edit; and **two replicas of one
model across two GPUs** — the load-balancing case M5 exists for — is the
same profile twice with different `CUDA_VISIBLE_DEVICES` in `env`. A
1:1 shape would need a migration by M5.

**The library does not validate `flags`.** It stores them. Validation is
the agent's, against the engine adapter's `flagSchema`, at
`POST /v1/runtimes` — which is where the curated flag surface lives and
where a bad flag has to fail anyway. Validating in two places means two
copies of engine knowledge and one of them going stale. The UI renders
the profile editor from the agent's `flagSchema` and posts the result
to the library, which is the same generic-config-editor path everything
else uses.

`PUT`, not `PATCH`, for a profile: `flags` is a document, and merge
semantics give no way to *remove* a flag. Replacing the whole profile is
unambiguous.

---

## 4. Scanning

A singleton sub-resource with named phases, following M1's engine-install
precedent — one scan at a time, because there is exactly one and
inventing job ids for a singleton is worse than not.

```
POST   /v1/scan   {full?}  -> 202 Scan
GET    /v1/scan            ->     Scan
DELETE /v1/scan            ->     cancel in flight

Scan  state: idle|scanning|done|failed|cancelled
      roots[] {path, status, modelsFound, filesScanned, error?}
      found/added/updated/missing counts, skipped[], currentPath?
```

**Incremental by default.** `(path, size, mtime)` unchanged means the
cached metadata is reused and the file is never opened — see Trap 2 for
why that matters. `full: true` re-parses everything, which is the escape
hatch for a metadata reader that got smarter since the last scan.

**`skipped[]` carries a reason per path, and this is the important
part.** Every trap in §1 shows up here: a projector, a shard member, an
adapter-only directory, an older HF revision, a header that would not
parse, a partial download. M1's lesson applies unchanged — a scanner
that silently drops files it did not understand is indistinguishable
from one that is broken, and "why isn't my model showing up" with no
answer is the failure mode that gets a tool uninstalled.

**Roots are config, not a resource.** They are a `path_list` field in the
library's standard config trio, which is what makes them editable in the
generic config UI with no library-specific code (`ConfigValueType` gains
`path_list` for this). `POST /v1/config/test` checks they are readable —
already promised in `common.yaml`'s own description of that endpoint,
written before the library existed.

**Degraded mode.** No roots configured is `ok`: that is a fresh install,
not a fault, and the wizard fills it in. A *configured* root that cannot
be read is `degraded` — the operator asked for something that is not
working, and a removable drive or a dead network share is exactly what
the health surface is for. Neither ever stops the component from
starting.

---

## 5. Who launches

**Not the library.** "Launch from the library" is a UI flow composed from
two surfaces it already talks to: read the profile from the library
(8082), `POST /v1/runtimes` to the agent (8079) with the model path
and the profile's flags. The library never calls the agent, needs no
service token for it, and carries no copy of `RuntimeSpec`.

The alternative — `POST /v1/models/{id}/launch` on the library — reads
tidier from a curl prompt and makes the library a client of the agent
with knowledge of runtime declarations, engine kinds and port
assignment. That is the coupling the profile's field-name alignment (§3)
exists to make unnecessary.

---

## 6. Contract

New document, `openapi/library.yaml`, port 8082 — the component the
agent's own description has claimed to supervise since M0.

```
GET    /v1/models                          LibraryModel[]   (?path= for reverse lookup)
GET    /v1/models/{id}                     LibraryModel
DELETE /v1/models/{id}                     forget a missing entry + its profiles
GET    /v1/models/{id}/profiles            ModelProfile[]
POST   /v1/models/{id}/profiles            ModelProfileSpec -> 201
GET    /v1/models/{id}/profiles/{pid}      ModelProfile
PUT    /v1/models/{id}/profiles/{pid}      ModelProfileSpec
DELETE /v1/models/{id}/profiles/{pid}
GET    /v1/scan   POST /v1/scan   DELETE /v1/scan
GET|PATCH /v1/config,  GET /v1/config/schema,  POST /v1/config/test
POST   /v1/admin/restart,  GET /healthz
```

`LibraryModel` carries the format-independent facts — path, root, format,
name, size, status, architecture, context length, capabilities, files —
and exactly one of `gguf` / `safetensors` for the rest. **The quant lives
on the GGUF object only**, correctly: quant tiers are a GGUF concept and
a safetensors model is sized, not tiered.

`DELETE /v1/models/{id}` refuses a model that is present (409). A present
model is on disk; forgetting it just means it reappears on the next scan.
Only a `missing` entry can be forgotten, and the response says what the
runtime delete already says: **the model file is never touched.**

### Shared-schema moves

`common.yaml` is for schemas more than one component references, so three
changes fall out:

1. **`ComponentKind` gains `library`.** The agent has described itself
   as supervising the library since M0 while the enum could not name it.
2. **`EngineKind` moves in from `agent.yaml`.** A profile names an
   engine, so it is now referenced by two components — the same
   reasoning `ComponentKind`'s own comment records.
3. **`ModelFormat` is new and shared,** because it appears on both a
   library entry and `EngineDescriptor.modelFormats` (Trap 10).

`ConfigValueType` gains **`path_list`** for the roots field. It is the
first list-typed config value; `driver_list` stays reserved for M5.

### One drift fix riding along

The agent's port is **8079** in its spec and in M0's acceptance
script, and `8083` in this design doc's shape table and the README's.
8079 is what the code binds and what the UI defaults to. The tables were
wrong; they now say 8079.

---

## 7. Scope

**In:** roots as config, recursive incremental scan of both formats,
metadata read, projector and shard grouping, skip-with-reason, capability
detection, `missing` entries, named per-model profiles, the browser and
profile editor in the UI.

**Out:**

- **Catalogue search, model detail from HF, downloads.** M3. This
  milestone is only about models already on the disk.
- **Quant guidance and hardware fit scoring.** M3, and it hangs off Trap
  3's `file_type`. M2 reports the quant; it does not opine.
- **Relocate / re-point a missing entry.** One endpoint, deliberately
  deferred: the interesting version guesses which new file is the moved
  one, and a wrong guess silently applies one model's tuning to another.
  Until then the profiles survive on the `missing` entry and can be
  copied by hand.
- **Adopting `general.sampling.*` into a profile or a request.** Trap 8's
  find is reported and stops there. The gateway owns request params, and
  the right place for "use the author's recommendation" is a gateway
  decision at M5, not a library field at M2.
- **Adapters / LoRA as first-class things.** Detected and skipped with a
  reason, not modelled. `--lora` is a launch flag and lives in
  `extraArgs` for anyone who needs it now.
- **MLX.** Format reserved, no scanner.
- **Launching anything.** §5.

---

## 8. Risks

- **Split GGUF is unverified here.** Grouping shards is the one §1
  claim with no local file behind it. It is also the one that, done
  wrong, either hides a large model or shows it N times.
- **The metadata reader is the maintenance surface.** Architecture
  prefixes (Trap 5) and quant enums (Trap 3) both grow with upstream, and
  the reader will meet models newer than itself constantly. Everything it
  does not recognise has to degrade to "here is the raw value" rather
  than to an exception or a guess.
- **Scan cost is per-model and measured, but the tail is not.** 50–60 ms
  warm on a 248k-vocab model; a network share or a spinning disk full of
  40 GB files is a different regime, and the incremental path is what
  keeps it off the second scan rather than the first.
- **`GET /v1/models` is unpaginated.** Dozens to low hundreds of entries
  at 1–2 KB each is fine; a library of thousands is not, and pagination
  is a backwards-compatible addition when someone shows up with one.
- **Windows path normalization is load-bearing** for ids (§2). Case
  folding, UNC paths and 8.3 short names all produce two spellings of one
  file, and two spellings mean two entries and split profiles.
- **`.part` files from M3's downloader will land in scanned roots.** They
  need a skip reason before M3, not after, or a half-downloaded 40 GB
  model shows up as a broken entry.
