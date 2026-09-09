# M3 — Discovery, download, guidance (design)

**Status:** contracts landed 2026-09-08. Milestone **M3** of
[`local-inference-control-plane.md`](local-inference-control-plane.md).
Follows [M2](m2-model-library.md).

Verified against the live HuggingFace hub, not fixtures: one real GGUF repo
of 35 entries read through three different API surfaces, a 16.5 GB remote
file's metadata read over HTTP Range, an interrupted download resumed and
verified against upstream's own digest, and the fit arithmetic run against
this box's actual free memory. Every number in §1–§3 was measured on
2026-09-08. §1 is where the milestone's shape came from, again.

**What it is:** the operator searches a catalogue, reads what a model
actually is, is told which quant their machine can run *and why*, and
downloads it — resumably — into a directory they chose, as a plainly-named
file.

**Why now:** M2 made "the set of models the operator owns" a thing the
system can enumerate. This is the milestone that puts models *into* it.
Sequenced ahead of lifecycle policy deliberately: swap policy only matters
once someone has several models, and acquisition is the step that decides
whether they stay. It is also the one thing `ollama pull` genuinely got
right, which is why differentiator #2 calls it required scope rather than
a convenience.

**The rule this milestone is built to honour** is M2's, unchanged: the
files are the operator's. Acquisition is a convenience layer over a plain
filesystem, never a managed store. A download writes one plainly-named
file into a directory the operator picked, and deleting Eugene Plexus
leaves it exactly where it is.

---

## 1. What the hub actually serves

Read off `huggingface.co` on 2026-09-08, mostly against
`unsloth/Qwen3.8-27B-GGUF`. Ten findings; five of them traps. Three more
traps live in §2, where the arithmetic is.

### One repo is twenty-five choices, and five files that are not choices

35 tree entries, 30 of them `.gguf`. Grouped by what they actually are:

| Count | What | Example |
|---|---|---|
| 24 | single-file quant candidates | `Qwen3.8-27B-UD-Q4_K_M.gguf` |
| 1 | a **split** candidate, 2 files | `BF16/…-00001-of-00002.gguf` + `…-00002…` |
| 2 | vision projectors, and the operator picks one | `mmproj-BF16.gguf`, `mmproj-F16.gguf` |
| 1 | the imatrix calibration file, 13.6 MB | `imatrix_unsloth.gguf` |
| 1 | an MTP draft model, 1.37 GB, in a subdirectory | `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` |

So the discovery screen's job is not "list the `.gguf` files" — that
produces 30 rows, four of which cannot be launched and one of which is
half a model. **25 candidates, from 30 files.** The classification rules
are M2's, applied to a remote listing instead of a local directory: an
`mmproj-` prefix and `general.type: mmproj`, `-0000N-of-0000M` shard
grouping, and a name-based skip for imatrix and draft files.

Note also that quants live in **subdirectories** when they are split
(`BF16/`), so a repo-relative path is not a filename.

### Trap 1 — the digest is `lfs.oid`, and there is a decoy beside it

```
"oid":  "e663c1e26c3e19799a7a7383ce2ea9de194fb115"          40 hex  git blob sha1
"lfs":  { "oid": "322e194ff79741c7…39123482", "size": … }   64 hex  sha256 of the content
"xetHash": "76b9d90a…4e3a1473"                              64 hex  Xet chunk-tree hash
```

Three hashes per entry, all plausible, and only the middle one is the
content sha256 the download can be verified against. `oid` is the sha1 of
the LFS *pointer file* — 136 bytes of text — so a verifier that uses it
compares a 16 GB download against a hash of the stub that stands in for
it, and passes nothing.

**Non-LFS files have no `lfs` object at all.** In a safetensors repo the
weights are LFS and `config.json`, `tokenizer_config.json`, `merges.txt`,
`vocab.json` and `model.safetensors.index.json` are plain git blobs. They
are still verifiable, just differently: the git blob sha1 is
`sha1("blob <len>\0" + bytes)`, which was checked exactly —
`Qwen/Qwen3-8B`'s `config.json`, 728 bytes, hashes to
`d46195ac87f837ad233d02b2f80f148bf7c005e0`, the `oid` the API reported.

So: **sha256 from `lfs.oid` for LFS files, git blob sha1 from `oid` for
the rest, and no unverified writes.** M1's Trap 5 lesson holds — upstream
publishes no checksum *file*, and that is not a reason to skip
verification when the API hands you a digest.

### Trap 2 — the size, the digest and the commit are on the redirect, not on the response

`GET /{repo}/resolve/{rev}/{file}` answers **302** to a signed CDN URL.
The headers that matter are all on that 302:

```
X-Linked-Size:  16464440224
X-Linked-ETag:  "322e194ff79741c7…39123482"      <- the sha256, matches lfs.oid
X-Repo-Commit:  4ca720788d1e01f1bff70c033e0d0028fd02e502
Accept-Ranges:  bytes
RateLimit:      "resolvers";r=2999;t=69
```

Follow the redirect transparently — which every HTTP client does by
default, `urllib` included — and **all four are gone.** The CDN's own
`etag` is the *Xet* hash, a different 64-hex string that matches nothing
in the tree API. This cost a debugging cycle while writing this document:
a HEAD through `urllib.request.urlopen` returned `X-Linked-Size: None`.

The rule: **read the headers off the first response, then follow the
redirect for the body.**

And the corollary trap, found the same way: a client that does *not*
follow the redirect writes the redirect body to disk. Non-LFS files answer
**307** to an internal `/api/resolve-cache/…` path, and a 230-byte file
reading `Temporary Redirect. Redirecting to …` is what lands where
`config.json` was meant to be. Two redirect shapes, both mandatory to
follow, and neither carrying the metadata.

### Trap 3 — the CDN URL expires, so resume must re-resolve

```
Location: https://us.aws.cdn.hf.co/xet-bridge-us/…?Expires=1788926395&Policy=…&Signature=…
```

The redirect target is signed and time-limited. A downloader that stores
the resolved URL alongside its `.part` file and reuses it an hour later
gets a 403 that looks like a network failure. **Resume always
re-resolves** through the `huggingface.co/…/resolve/…` URL, which is
stable, and re-reads the digest from the new 302 to confirm the remote
file has not changed under the partial.

### Trap 4 — `main` is a moving target

`X-Repo-Commit` on that 302 is the resolved commit. Repos are re-uploaded,
requantized and fixed in place; `main` today is not `main` next week. A
download records the **resolved commit** and reports it, so a resume can
tell "the transfer broke" from "the file I was fetching no longer exists".
Uploaders do requantize under the same filename, which is precisely the
case where resuming blindly concatenates two different files into one
plausible-sized corrupt model that fails a digest check with no clue why.

### Finding — Range works through Xet, and the whole loop is proven

Large repos are on Xet storage now (content-defined chunking, dedup) —
hence `xet-bridge-us` in the redirect and the `rel="xet-reconstruction-info"`
link header. The question that decides whether resumable download is even
possible is whether the bridge serves plain HTTP ranges. It does:

```
GET …/Qwen3.8-27B-UD-Q4_K_M.gguf   Range: bytes=0-63
206 Partial Content   content-range: bytes 0-63/16464440224
0000: 4747 5546 0300 0000 …   "GGUF"
```

Proven end to end, not inferred — 13.6 MB fetched in two legs with the
connection abandoned mid-stream between them:

```
tree API:  13,642,656 B  sha256 0ee5b10b…6599f1c1
HEAD:      X-Linked-Size and X-Linked-ETag agree with the tree API
leg 1:     abandoned at 5,242,880 B
leg 2:     Range: bytes=5242880-  ->  206, content-range 5242880-13642655/13642656
           8,399,776 B in 0.56 s
verify:    size OK, sha256 OK
rename:    .part -> final
```

That loop — resolve, HEAD, compare, range, verify, rename — is the whole
downloader. It is written down here because it is cheap to get subtly
wrong and it worked on the first honest attempt once Trap 2 was understood.

### Trap 5 — a gated model browses perfectly and only the download fails

```
GET /api/models/meta-llama/Llama-3.3-70B-Instruct        200, "gated": "manual"
GET /api/models/meta-llama/Llama-3.3-70B-Instruct/tree   200, full file list with sizes
GET /meta-llama/…/resolve/main/config.json               401
    X-Error-Code:    GatedRepo
    X-Error-Message: Access to model … is restricted. You must have access to
                     it and be authenticated to access it. Please log in.
```

Metadata, sizes and digests are public; the bytes are not. So a gated
model is fully searchable, sizeable and scoreable, and the *only* thing
that fails is the transfer — after the operator has picked a quant and
pressed the button.

`gated` is `false`, `"auto"` or `"manual"` on the model API, so the
warning is available before anything is attempted. **Surface it on the
detail screen, not as a download failure**, and distinguish the two
cases: `auto` needs a token and one click-through on the model page,
`manual` needs an approval that can take days. The download path still has
to handle the 401, because a token can be absent, expired, or belong to an
account that has not accepted the licence, and `X-Error-Code` makes that
diagnosable rather than generic.

### Finding — remote metadata is readable for 0.07% of the download

This is the milestone's best result. M2's Trap 3 established that a GGUF's
quant is machine-readable locally (`general.file_type`) and that the
filename is not to be trusted. For a model still on the hub, the filename
is apparently all there is — the API exposes no per-file quant.

It is not all there is. The KV block is at the *front* of the file, and
Range requests work:

```
Range: bytes=0-12582911     12.6 MB in 0.8 s (15.3 MB/s)
kv_block = 10,945,379 B     87% of the fetch, 0.066% of the 16.5 GB file
  general.file_type              = 15        <- Q4_K_M, machine-read
  general.size_label             = 27B
  qwen35.block_count             = 65
  qwen35.full_attention_interval = 4
  qwen35.attention.head_count_kv = 4
  qwen35.attention.key_length    = 256
  qwen35.attention.value_length  = 256
  qwen35.context_length          = 262144
  tokenizer.ggml.tokens          = 248,320 entries
```

Which means **quant guidance for a remote model can be built on the file's
own metadata rather than on its filename** — the exact standard M2 held
local models to. Same read works on a projector (KV block 1,743 B, 1 MB
probe is plenty) and on the first shard of a split model (10,945,292 B,
`file_type: 32` = BF16, so probing shard 1 describes the whole set).

Two mechanics worth recording. The KV block size is not known in advance,
so the probe is a doubling read: fetch 1 MB, and when the parser runs off
the end it reports how far it got — a 1 MB probe of the Qwen file failed
cleanly with *"needs ≥ 1,048,581 B"* — and one more range request
finishes it. Two requests, worst case. And the cost is per-candidate, so
this is a **preflight on the one file the operator chose**, never a
sweep across 25 candidates for a listing (that would be 270 MB).

Safetensors is the same idea and two orders of magnitude cheaper: an
8-byte read gives the header length, a second read gives the header.
`sentence-transformers/all-MiniLM-L6-v2` — 11,408 B of header, 105
tensors, `params=22,713,728`, `dtypes={F32: 22,713,216, I64: 512}`, both
requests inside half a second. M2's local asymmetry (GGUF has a quant and
no parameter count; safetensors the reverse) reproduces exactly over the
network, at wildly different cost.

### Finding — the search API gives no sizes, and there are two rate-limit buckets

```
GET /api/models?search=&filter=gguf&sort=downloads|trendingScore|likes|lastModified&limit=&full=true
    -> id, author, downloads, likes, trendingScore, gated, tags, pipeline_tag,
       library_name, lastModified, createdAt, sha, siblings[{rfilename}]
    Link: <…&cursor=eyJ…>; rel="next"
    RateLimit-Policy: "fixed window";"api";q=500;w=300
```

`siblings` is **filenames only** — no sizes, no digests. Sizes come from
`/tree/{rev}?recursive=1`, one call per repo. So a search screen cannot
show sizes or fit verdicts without N extra calls, and the shape of the
feature follows from that: **search lists repos, detail scores
candidates.** Trying to badge fit on the search results is what turns one
keystroke into fifty API calls.

Pagination is **cursor-based** (opaque `cursor` in a `Link: rel="next"`),
not offset — so the contract carries a cursor, not a page number.

Two separate limits, both generous and both easy to blow through from a
UI: `api` is **500 per 300 s** and `resolvers` is **3000 per 300 s**.
Search-as-you-type at 100 keystrokes a minute is over the API budget
inside two minutes, so search is debounced client-side and cached
server-side. Unauthenticated requests also carry
`X-HF-Warning: unauthenticated … set a HF_TOKEN to enable higher rate
limits and faster downloads` — which is the argument for the token config
field applying to *public* models too, not just gated ones.

### And the repo-level `gguf` object is real, and useful

```
"gguf": { "total": 27320697856, "architecture": "qwen35",
          "context_length": 262144, "chat_template": "…",
          "quantize_imatrix_file": "…/imatrix_unsloth.gguf" }
```

`total` is a **parameter count** — 27.32 B, matching the `27B` in the repo
name. Repo-level rather than per-file, so it says nothing about quants,
but it is the number that makes §2's bits-per-weight computation possible
with no extra request. Also present: `config.model_type` and `cardData`
(the card's YAML front matter — license, base model, tags), while the card
*prose* is a separate 7–10 KB fetch of `/{repo}/raw/{rev}/README.md`.
That prose is what answers the source complaint — *"no search page with
summaries, just an autocomplete list"* — so the detail screen renders it.

---

## 2. Guidance: the arithmetic, and the three ways it goes wrong

The complaint this exists to answer is verbatim from the thread:
*"Q3_K_S vs 2Q_K_M? No one fucking knows."* On the repo above that is a
choice between **25 options**, and the honest answer has two halves that
must not be confused with each other:

- **What will fit** — arithmetic, computable, ours to state.
- **Which is better** — a quality judgement we will not invent. See below.

### What decides fit

```
required = weights + kv_cache(ctx) + overhead
kv_cache = ctx x attention_layers x head_count_kv x (key_length + value_length) x bytes_per_element
```

Every term but one comes from the metadata read in §1. `overhead` —
compute buffers, the graph, the CUDA context — is a flat allowance
(1 GiB), and it is the term that makes the estimate an estimate.

### Trap 6 — a hybrid model has far fewer attention layers than layers

`qwen35.block_count = 65`, but `qwen35.full_attention_interval = 4` and
the file carries a full set of `qwen35.ssm.*` keys. Every fourth layer is
attention; the rest are state-space and hold no KV cache. Measured
against the naive formula:

| | attention layers | KV per 1k tokens | 32k ctx | 262k ctx |
|---|---|---|---|---|
| hybrid, every 4th | 16 | 64.0 MiB | 2.00 GiB | 16.00 GiB |
| naive, all 65 | 65 | 260.0 MiB | 8.12 GiB | 65.00 GiB |
| | | | **×4.1 over** | **×4.1 over** |

A 4.1× overestimate at every context length. At 262k it is the difference
between "fits on a 5090 with room" and "needs 65 GiB of KV cache", which
would make every candidate in the repo unrunnable and the whole guidance
feature a liar. Hybrid architectures are not exotic any more — this is a
current mainstream release — so the layer count that matters is the
*attention* layer count, and where the metadata does not say, the
assumption has to be stated rather than buried.

### Trap 7 — free is not total, on both sides

Measured on this box while writing this, with nothing unusual running:

```
RTX 5090   32,607 MiB total   29,582 MiB free   2,606 MiB already held
RAM        93.56 GiB total     58.75 GiB avail   34.81 GiB already held  (37% load)
```

2.9 GiB of VRAM is gone to the desktop before any engine starts, and on a
24 GB card that is 11% of the budget. A third of RAM is already in use.
Scoring against *total* tells the operator a model fits and then it OOMs
or swaps; scoring against *free* is pessimistic on a box that is about to
close its browser. So **report both and score against free**, with the
totals visible so the operator can see what they would get back by
quitting something. This is the difference between guidance that is
trusted after the first failure and guidance that is not.

### Trap 8 — scoring shard 1 of a split model understates it

`BF16/…-00001-of-00002.gguf` is 46.55 GiB; the second shard is another
4.35 GiB and the model is **50.90 GiB**. Score the file named on the
launch line and you understate the candidate by the size of everything
else, so every fit figure is a **sum over the shard set**. Fit is per-*candidate*, never per-file,
which is the same grouping rule §1 needs for the listing and M2 needed
for the local scan.

### The verdict, and why four values

| Verdict | Means |
|---|---|
| `fits` | `required` ≤ free VRAM. Fully offloaded, no host memory in the path. |
| `tight` | ≤ total VRAM but > free. It would fit on an idle GPU; something is holding memory now. |
| `split` | > total VRAM, ≤ VRAM + available RAM. Runnable with partial offload, materially slower. |
| `no` | Larger than both. |

Not a percentage. A percentage of what — VRAM, VRAM+RAM? — is exactly the
ambiguity the operator is trying to resolve, and the four cases have
different *advice*: close something, accept slowness, pick a smaller
quant. `tight` and `split` are the two the field gets wrong, and they are
the two worth naming.

Every verdict carries the arithmetic that produced it (`weightsBytes`,
`kvCacheBytes`, `overheadBytes`, the budget it was measured against, the
context length assumed) plus a `basis` saying whether the KV term came
from a real metadata read or from a heuristic. Differentiator #6 says
*show why*; this is the "why", and it is also what lets the operator
notice when our arithmetic is wrong.

### The one honest quality number: bits per weight

`weights_bytes × 8 / parameters`. Both terms come from the API for free —
sizes from the tree, the parameter count from the repo-level `gguf.total`.
Run across the whole repo it orders all 25 candidates monotonically, and
lands exactly where it should:

```
UD-IQ1_S      5.77 GiB   1.81 bpw        UD-Q5_K_M    18.41 GiB   5.79 bpw
UD-IQ2_XXS    6.77 GiB   2.13 bpw        UD-Q6_K      20.47 GiB   6.44 bpw
UD-Q2_K_XL    9.15 GiB   2.88 bpw        UD-Q6_K_XL   23.56 GiB   7.41 bpw
UD-IQ3_S     11.21 GiB   3.53 bpw        Q8_0         27.05 GiB   8.51 bpw
UD-IQ4_XS    13.27 GiB   4.17 bpw        UD-Q8_K_XL   29.30 GiB   9.21 bpw
UD-Q4_K_M    15.33 GiB   4.82 bpw        BF16         50.90 GiB  16.00 bpw
```

BF16 comes out at **exactly 16.00**, which is the check that says
`gguf.total` really is a parameter count and the sizes really are
comparable. This is the number that makes `IQ2_S` and `Q2_K` and
`UD-Q3_K_XL` commensurable when their *names* are three different
vocabularies from three different upstream families.

**What we will not do is score quality.** No stars, no "recommended for
chat", no invented perplexity. The quant families churn (imatrix, IQ,
Unsloth Dynamic, MXFP4), their relative quality is upstream's research
and is model-dependent, and M2's rule stands: guidance built on a guess is
worse than no guidance. What ships instead is a **static quant table** —
tier → family, nominal bits per weight, what the K/IQ/UD naming means, and
the one broadly-agreed shape of the curve, which is that below roughly
4 bpw degradation becomes noticeable and below 3 it becomes severe.
Shipped as reference content, keyed by tier, identical for every model,
and never blended with a per-model number.

### The recommendation

**The largest candidate that `fits` at the operator's target context.**
Target context is a parameter with a configured default, not a constant,
and the UI exposes it as a slider — because seeing Q6_K_XL become Q4_K_M
as you drag context from 8k to 128k *is* the guidance. On this box, at
32k, against 28.89 GiB of free VRAM, that resolves to
`UD-Q6_K_XL` — 23.56 GiB of weights, 2.00 GiB of KV, 26.6 GiB required.

One warning rule: when the largest thing that fits is **below 4 bpw**, say
so, and name the alternatives (shorter context, partial offload, a smaller
model) rather than silently recommending `IQ1_S` as though it were fine.
Recommending a 1.81 bpw quant without comment is how a first impression
becomes "this thing is stupid".

---

## 3. Hardware detection

Detected on the library's own host, because that is where the fit question
is asked from. Verified here:

| | How | Result on this box |
|---|---|---|
| RAM total / available | `GlobalMemoryStatusEx` (Windows), `/proc/meminfo` (Linux), `sysctl hw.memsize` (macOS) | 93.56 GiB / 58.75 GiB |
| GPUs | `nvidia-smi --query-gpu=index,name,memory.total,memory.free,compute_cap,driver_version --format=csv` | RTX 5090, 32,607 / 29,582 MiB, cc 12.0, driver 610.47 |
| CPU count | `os.cpu_count()` | 32 |

**Stdlib plus vendor CLIs, no new dependency.** `ctypes` on Windows,
`/proc` on Linux, `sysctl` on macOS — deliberately not `psutil`, because
[[agent-venv-is-runtime]] has collected four victims already and every
dependency the library gains has to be installed into the agent's venv
as well. The Windows path is `ctypes`, which the CI-vs-devenv lesson flags
as the class of code that passes locally and is untested on the platforms
the audience actually runs.

**Three detection paths are unverified**, and named rather than assumed
working: AMD (`rocm-smi` — not present here), Intel (`xpu-smi` — not
present here), and Apple unified memory, where the whole
VRAM-versus-RAM distinction collapses and the real budget is the wired
limit (`iogpu.wired_limit_pct`, ~75% of RAM by default) rather than a
separate pool. That last one is not a detail: it is the difference between
telling a 96 GB M3 Ultra owner they can run a 70B and telling them they
have no GPU. Same posture as M1's Linux+CUDA refusal and M2's unverified
split-GGUF grouping — the unverified thing gets a name and a risk entry,
not a confident code path.

**Multi-GPU is designed but only single-GPU is verified** — this box has
one card in it today. llama.cpp splits layers across GPUs by default, so
the budget has two meanings (largest single card, and the sum), and the
contract reports per-GPU entries plus both totals. Two replicas on two
cards is M5's case and is exactly why the sum is not the only number.

**The host the library runs on is not necessarily the host with the GPU.**
Multi-host topology is a locked commitment — a driver lives next to its
engine, and Troy's own GPUs are planned for different buildings — so a
fit verdict computed from local memory is answering a question about the
wrong machine in that deployment. Two consequences, both cheap: the fit
surface accepts an **explicit budget override** so a caller who knows the
target host's numbers can score against them, and the reported hardware
carries the hostname it was read from so a UI can say which machine it is
talking about. Building a cross-host hardware inventory is not M3's job
and probably belongs to the agent's topology when it is.

**Not shared with the agent's `HostAccelerator`, on purpose.** That
schema answers "which engine build do I fetch" and its own description
already says the VRAM-and-fit surface belongs here. The two overlap on
`os` and `arch` and diverge on everything else, so this duplicates two
enums rather than coupling two surfaces that will evolve apart —
"components share schemas, not code" means sharing the schemas that are
genuinely referenced twice, not the ones that look similar. When the two
disagree it is because they are on different hosts, which is information.

---

## 4. Downloads

### What a download is

**One transfer job over N files, keyed by a resolved commit.** Not one job
per file: a split GGUF is 2–9 files, a multimodal model is a quant plus a
projector, and a safetensors model is a directory of 15 entries
(`Qwen/Qwen3-8B`: 16.4 GB across `model-0000N-of-00005.safetensors`, plus
`config.json`, `tokenizer.json`, `merges.txt`, `vocab.json` and the index,
none of which are optional). "Download this model" is one
operator action and must be one resource, with per-file progress inside
it.

The caller names the files explicitly. The catalogue detail response
groups them into candidates and says which files each one needs, so the
UI passes a list it was given rather than composing one — but the list is
in the request, because "download the model" has to mean something exact
by the time it reaches the transfer loop.

### Where the bytes land

```
<root>/<owner>/<repo>/<filename>          default layout, LM Studio's and the de-facto one
<root>/<filename>                         flat, for people who keep one directory
```

`root` is one of the configured model roots from M2 — the `path_list`
whose description already promised that *"M3's downloader offers the first
entry as the default destination"*. Layout is a config field with those
two values, and a per-download `subdirectory` overrides both. The
repo-relative subdirectory of a split quant (`BF16/`) is **not**
reproduced: llama.cpp wants the shard set in one directory, and the shard
naming already keeps them together.

The file keeps its upstream name. That is the whole of differentiator #3
in one sentence, and it is also what makes M2's scanner find the result
without being told: the plainly-named file appears under a configured
root, and the incremental rescan picks it up.

### The `.part` protocol

```
<destination>.part          in flight; the only file we create that is ours
<destination>              after verification, by atomic rename
```

- **Verification is mandatory and happens before the rename.** sha256
  against `lfs.oid` for LFS files, git blob sha1 against `oid` for the
  rest (Trap 1). A file that fails is left as `.part` with the record in
  `failed` — never renamed into place, and never silently retried into the
  same bytes.
- **The `.part` is ours; the finished file is the operator's.** That line
  decides the delete semantics: cancelling a download removes its `.part`,
  because that file only ever existed as a side effect of a job the
  operator just abandoned. Nothing in this component ever deletes a
  completed model file — same guarantee `DELETE /v1/models/{id}` already
  makes.
- A `.part` in a scanned root is reported by the scan with
  `incomplete_download`, the reason M2 reserved for exactly this and
  deliberately shipped before it was needed.

### Resume

```
1. re-resolve   GET /{repo}/resolve/{commit}/{file}, no redirect following
2. compare      X-Linked-ETag and X-Linked-Size against what the record stored
3. continue     Range: bytes=<size of .part>-      expect 206
4. verify       full digest over the whole file
5. rename       .part -> final
```

Step 2 is the one that matters. When the digest disagrees, the remote file
changed under the partial (Trap 4) and the only correct move is to
**discard the `.part` and restart from zero**, saying so. Concatenating
the tail of a requantized upload onto the head of the old one produces a
file of exactly the right length that fails verification, and — if
verification were ever skipped — a model that loads and generates
nonsense.

**Retries are automatic and bounded; resume is what a retry does.** A
40 GB download over a domestic connection will meet a transient failure,
and treating that as terminal makes the feature useless. So a failed
transfer re-resolves and continues with backoff, up to a budget, and only
then goes `failed` with the attempt count visible. An operator-issued
`resume` on a `failed` or `paused` record runs the same loop.

Concurrency is a collection, not M1's singleton: several downloads can be
queued, `maxConcurrentDownloads` caps how many transfer at once
(default 1 — two 40 GB fetches sharing a link finish later than one after
the other, and the progress bar people watch is the one they started
first).

### After a download

The record carries the destination path from the moment it is created —
before a byte moves, so the operator sees exactly where it will land — and
on completion the library runs an **incremental scan of the destination
directory** and fills in the `modelId` of the resulting library entry.
That closes discovery → download → library → profile → launch in one flow
without the UI having to poll for a model to appear.

### What we never do

**Never `--hf-repo` / `--hf-file`.** M2's Trap 9, restated because this is
the milestone where it becomes tempting: `llama-server` will download a
model itself, projector included, into its own cache. Using it would put
the operator's files somewhere the operator did not choose, which is the
precise thing differentiator #3 exists to refuse. We fetch; we place; the
launch line always carries an explicit `-m <path>`.

**No content-addressed store, no dedup, no `blobs/`.** Xet gives HF
chunk-level dedup and we get none of its benefits by writing plain files.
That is the trade, made knowingly, and it is the same trade the
non-negotiable rule already made.

---

## 5. Contract

All on `library.yaml`. Eleven new paths, 25 new schemas, and **no change to
`common.yaml`** — which has an operational consequence worth stating:
unlike M2, this re-pin reaches only the `library` repo and the `ui`.
The gateway and the inference-driver are untouched, because nothing in
M3 lands in a shared schema. (Checked against the actual diff, not
assumed — M1 made this claim and M2 disproved it for itself.)

```
# Catalogue — the remote half
GET  /v1/catalogue/search?q&sort&direction&format&author&limit&cursor   CatalogueSearchPage
GET  /v1/catalogue/model?repo&revision                                 CatalogueModel
GET  /v1/catalogue/model/card?repo&revision                            CatalogueCard
GET  /v1/catalogue/model/preflight?repo&revision&file                   CataloguePreflight

# Guidance — the local half
GET  /v1/hardware                                                      HostHardware
GET  /v1/models/{id}/fit?contextLength&kvCacheType&vramBytes&ramBytes   ModelFit
GET  /v1/quants                                                        QuantTable

# Downloads
GET    /v1/downloads                          DownloadList
POST   /v1/downloads          DownloadSpec -> 202 Download
GET    /v1/downloads/{id}                     Download
POST   /v1/downloads/{id}/pause               Download
POST   /v1/downloads/{id}/resume              Download
DELETE /v1/downloads/{id}                     cancel in flight / forget; removes .part
```

**The repo id is a query parameter, not a path segment.** It contains a
slash (`unsloth/Qwen3.8-27B-GGUF`), and the two obvious alternatives both
break: `%2F` in a path segment is mangled by intermediaries — and every UI
call goes through the agent's proxy — while `{owner}/{name}` as two
parameters cannot address the single-segment canonical repos that also
exist (`gpt2`). A query parameter is the shape that covers the whole space
without encoding tricks.

Key schemas:

```
CatalogueModel     repo, owner, name, gated(false|auto|manual), private, downloads,
                   likes, trendingScore, createdAt, lastModified, tags[], pipelineTag,
                   libraryName, license, revision, resolvedCommit, formats[],
                   parameters?, architecture?, contextLength?, chatTemplate?,
                   candidates[], projectors[], otherFiles[], recommended?, warnings[]

CatalogueCandidate label, format, files[], sizeBytes, quantization?, quantSource,
                   bitsPerWeight?, fit?, alreadyOwned?

CatalogueFile      path, sizeBytes, sha256?, gitBlobSha1?, role

Fit                verdict(fits|tight|split|no), requiredBytes, weightsBytes,
                   kvCacheBytes, overheadBytes, contextLength, kvCacheType,
                   attentionLayers?, basis(metadata|estimate), budget, notes[]

MemoryBudget       vramFreeBytes, vramTotalBytes, ramAvailableBytes, ramTotalBytes,
                   largestGpuFreeBytes, gpuCount, unifiedMemory, source(detected|override)

HostHardware       hostname, os, arch, cpuCount, ramTotalBytes, ramAvailableBytes,
                   unifiedMemory, gpus[], detectedAt, warnings[]

Gpu                index, name, vendor, vramTotalBytes, vramFreeBytes?, computeCapability?,
                   driverVersion?

CataloguePreflight repo, resolvedCommit, file, format, bytesRead, quantization?,
                   fileType?, architecture?, blockCount?, attentionLayers?,
                   contextLength?, parameters?, dtype?, capabilities, recommendedSampling?,
                   agreesWithFilename?, fit?

DownloadSpec       repo, revision?, files[], root?, subdirectory?
Download           id, state, repo, revision, resolvedCommit, root, destinationDirectory,
                   files[], bytesTotal, bytesDownloaded, bytesPerSecond?, etaSeconds?,
                   attempts, modelId?, startedAt, finishedAt?, error?, errorCode?, message?
DownloadState      queued|resolving|downloading|verifying|done|failed|paused|cancelled
QuantTable         tiers[] { tier, family, nominalBitsPerWeight, summary, guidance }
```

`Fit` appears in three places on purpose — per candidate in the
catalogue, on `GET /v1/models/{id}/fit` for something already owned, and
inside a preflight — because it is one computation and three questions.
`basis` is what distinguishes them honestly: a catalogue candidate scored
from size alone says `estimate`, and the same candidate after a preflight
says `metadata`.

`alreadyOwned` is the join only this component can make: the discovery
screen says "you already have this file" with the local `modelId`,
because the library holds both halves. Cheap, and it prevents the most
annoying possible outcome of a 16 GB download.

`DownloadState` mirrors M1's `EngineInstall` phases rather than a
percentage, for the reason M1 gave: the phases fail differently and the
operator needs to know which one they are in. `errorCode` carries
upstream's `X-Error-Code` (`GatedRepo` and friends) so the UI can say
something specific instead of surfacing a 401.

### Config additions

Six fields in the standard trio, all rendered by the generic editor with
no new `ConfigValueType`:

| Field | Type | Why |
|---|---|---|
| `hfToken` | `secret` | Gated repos, higher rate limits, and upstream's own advice that it makes public downloads faster. |
| `catalogueEnabled` | `boolean` | An air-gapped install turns off every outbound request, and gets a legible refusal instead of timeouts. |
| `catalogueBaseUrl` | `url` | Enterprise hubs and regional mirrors are real; hardcoding `huggingface.co` makes the component useless behind either. |
| `downloadLayout` | `enum` | `publisher_repo` (default) or `flat`. §4. |
| `maxConcurrentDownloads` | `integer` | Default 1. §4. |
| `guidanceContextLength` | `integer` | The context every fit verdict is computed at when a caller passes none — so the one number that decides which quant gets recommended. A config field rather than a constant because 4k and 128k give different answers and neither is wrong. |

The catalogue being unreachable is **not** a degraded-health state. No
roots configured is `ok` (M2's rule: a fresh install is not a fault), and
an offline box is the same kind of thing — the failure belongs in the
search response, where the person who just pressed the button can see it.
`details.catalogueReachable` carries it for anyone watching health.

---

## 6. Scope

**In:** catalogue search with cursor pagination, model detail with
candidate grouping, model-card prose, ranged metadata preflight, hardware
detection, the fit computation and its three surfaces, the static quant
table, the recommendation and its below-4-bpw warning, resumable verified
downloads with pause/resume/cancel and per-file progress, the
post-download rescan, and the discovery + download UI.

**Out:**

- **Cross-host hardware inventory.** The fit surface takes an override and
  reports which host it measured; building a real inventory is topology
  work and belongs to the agent if it belongs anywhere. §3.
- **Quality scoring of quants.** Permanently, not just for now. §2.
- **Xet-native chunked transfer.** The reconstruction API is right there in
  the `Link` header and would give dedup across quants of one model. It
  also means adopting content addressing internally, which is the one
  thing the project has refused twice. Plain Range requests, measured at
  15.3 MB/s, are enough.
- **Downloading anything but models.** Datasets and Spaces are out of
  scope for a component whose job is the model library.
- **Torrent / mirror / multi-source fetching.** One upstream, one
  connection, resumable.
- **Automatic quant selection.** We recommend; the operator picks. A
  one-click "get the best one for me" is a fine M6 wizard step and a bad
  default, because the whole complaint is about not being told what is
  happening.
- **Re-quantizing locally.** `llama-quantize` exists and this is not the
  milestone.
- **Adopting `general.sampling.*`** from a preflight. Still reported,
  still applied by nothing — M2's Trap 8 and a gateway decision.

---

## 7. Risks

- **Search quality is HuggingFace's, and it is not good.** Sorting
  `gemma` by trending returns a finetune with a keyword-stuffed name above
  the official release. We can rank, filter and describe better, but we
  cannot fix the index — and the source complaint was *specifically* about
  HF's search. Partly answered by rendering the card prose and the
  publisher prominently; not fully answerable.
- **The remote-metadata preflight is 12 MB of someone else's bandwidth**
  per candidate examined. Fine for the file an operator is about to
  download; abusive if a UI fires it on hover. It is an explicit endpoint,
  never automatic, and the `resolvers` budget (3000/300 s) is the ceiling
  to respect.
- **The fit estimate will be wrong sometimes.** The overhead allowance is
  flat, KV cache type is a launch flag, MoE models hold experts
  differently, and llama.cpp's own allocation changes between builds. It
  reports its inputs so a wrong answer is diagnosable, and `tight` exists
  precisely because the boundary is fuzzy. What must not happen is a
  confident `fits` on something that OOMs — hence scoring against free
  memory, not total.
- **Upstream API shape is not a contract.** The `gguf` object, `xetHash`,
  the `Link`-header cursor and the `X-Linked-*` headers are all
  undocumented-ish implementation surface that has changed before (`oid`
  vs `lfs.oid`, the Xet migration itself). Every reader degrades to "size
  and filename" rather than failing, and the fit `basis` field is how a
  degraded read announces itself.
- **Three unverified detection paths** — AMD, Intel, Apple unified memory
  (§3). Apple is the one that matters most, because a Mac with 96 GB of
  unified memory is a genuinely good local-inference box and the naive
  reading of "VRAM" on it is zero.
- **A 40 GB download on a metered connection** is a thing we will
  initiate on someone's behalf. Show the size before the button, not
  after; refuse-with-a-reason when the destination drive cannot hold it;
  and never start a second transfer the operator did not ask for.
- **Gated `manual` repos can take days to approve.** Nothing we can do
  except distinguish the two gate kinds up front so nobody waits on the
  wrong thing.
- **`.part` files in scanned roots** are now real rather than reserved,
  and the skip reason lands in the same release as the thing that creates
  them.
