# Discover, recommendation-first — acceptance run (2026-09-16)

**Result: 41 `PASS` lines, zero failures, third execution.** The first
two found two product defects and one check whose premise was wrong.
`scripts/starter-set-acceptance.sh`: four processes on +100 ports, the
environment cleared, teardown by pid, the system Chrome driving
`ui/e2e/discover.spec.ts` and `ui/e2e/home.spec.ts`, and the review CLI
run against the live hub. Hobbyist UX plan **S6**, decision **#4**.
Design: [`../design/hobbyist-ux.md`](../design/hobbyist-ux.md) §7 S6,
§6.3, §6.5; record §11.7.

## What was built, in one paragraph

`GET /v1/catalogue/starter` serves a handful of general-purpose instruct
models — one per size class — scored against one machine, and names the
largest that runs entirely in GPU memory at the scored context. It makes
**no upstream call**: every number a fit needs was measured once by the
review that produced `starter_models.yaml` and is carried in it.
`eugene-plexus-library starter-review` is that review: it ranks the
hub's GGUF repos by 30-day downloads, aggregates mirrors by
`base_model`, checks each leader's architecture against the pinned
llama.cpp build's own list, and files a report plus a proposed file,
never applying either. Discover opens on the set instead of on whatever
the hub sorted to the top today; a pasted repo link resolves to one
repo; every verdict names the context it was scored at; and Home's
empty-disk card fetches a named file instead of opening a catalogue.

## What the run proves

**The set answers with the hub switched off.** Check 4 turns
`catalogueEnabled` off and asks for the set again: the same four
suggestions, while `GET /v1/catalogue/search` beside it refuses with
409. That is the property the whole shape exists for — the screen where
someone picks their first model must not be the screen that fails first
— and it is the one thing a fixture could not have established.

**The recommendation is about the machine, not about us.** Scored
against 80 GiB it is the 30B; against 6 GiB the 4B; against no GPU at
all it inverts to the *smallest* and says why in the person's words
("on a machine with no graphics card that is the one to start with…
they just generate a few words a second"). Against the same 24 GiB card
it is the 30B at 4k and the 12B at 256k.

**Every entry scores from real metadata.** Check 3 asserts
`fit.basis == "metadata"` for all four: nothing on this card is a guess
with a number on it.

**The review runs end to end against the live hub** and files a
92-line report — a verdict per class, runners-up, a "new this month"
table, and the repos the ranking dropped with their reasons — plus a
proposed file. It exited 0 (every class KEEP), and the shipped file's
hash was identical before and after, which is the property the
two-review hysteresis depends on.

## What it does not prove

Nothing is downloaded. The starter set's `sizeBytes` and `file` are
asserted to exist and to be plausible, and the pasted-link checks read
one repo's metadata, but no run here has fetched a starter model and
launched it — `one-click-run-acceptance.sh` is where a model is
fetched and run, on a different repo. The first execution of *that*
script after this one is the join.

The review's **step 3 is the architecture check alone.** §6.5 also
specifies loading a small quant on CPU in CI for classes whose smallest
file is under 6 GB; that half is not built, and the report says which
check ran (`proof: architecture`) rather than implying both.

And the hysteresis has never actually fired: this is the first review,
so every class was `REPLACE` from an empty list on the first run and
`KEEP` on every run since. The two-consecutive-months path is exercised
by unit tests and by nothing else until October.

## The two product defects the runs found

### 1. The hub does not answer 404 for a repo that does not exist

Check 7 asked for `https://huggingface.co/nobody-eugene/nothing-here`
and got **403** where the contract promises 404 — and the bare
`owner/name` case, which is supposed to fall through to an ordinary
search, raised instead. Measured directly:

```
GET https://huggingface.co/api/models/nobody-eugene/nothing-here
401  {"error":"Invalid username or password."}
```

To an unauthenticated caller "gone" and "private" are deliberately the
same answer; it is an enumeration defence. So "could not resolve a
pasted reference" is **401, 403 and 404 together**, and the 404 this
endpoint returns names all three causes rather than asserting the one it
cannot tell from the others. A genuinely gated repo keeps its own 403,
because accepting a licence is something an operator can go and do.

**The unit test passed against the broken code**, because its fixture
returned 404 — a shape invented from the contract rather than measured
from the hub. It returns the hub's real body now.

### 2. The KV cache was 43× too large on a mainstream 12B

Found while scoring the first accepted list: the 12B in the set read
`partial offload` on a 29 GiB card while the 27B beside it read `fits`.
`attention.head_count_kv` is **an array of 48** on that file — eight
heads on five layers of every six, one on the sixth — and five of every
six layers are sliding-window with their own shorter key and value
lengths and a 1024-token window. The scalar reader returns `None` for a
list and falls back to `head_count`, and `sliding_window_pattern` was
not read at all:

| context | scalar arithmetic | per-layer truth | over |
| ------- | ----------------- | --------------- | ---- |
| 4k      | 6.0 GiB           | 0.375 GiB       | 16×  |
| 16k     | 24.0 GiB          | 0.562 GiB       | 43×  |
| 256k    | 384 GiB           | 4.31 GiB        | 83×  |

The starter card would have refused a 7 GB model on a 32 GB card, with
`basis: metadata` and no note saying a load-bearing term had been
guessed. `ModelShape` grew a per-layer form that wins over the scalars,
`max_context_that_fits` solves an affine cache rather than a linear one
(a sliding layer stops growing at its window, so the cache is a line
with an intercept), and the review records the layers as a run-length
table a person can read before accepting the file.

It is the same *class* of defect `attention_layers()` was written for at
M3 — one architecture generation on.

## The check whose premise was wrong

Check 5 originally asked for the recommendation at 4k and at 256k on a
**12 GiB** card and expected them to differ. They did not, correctly:
the 12B in the set is a sliding-window model whose cache barely grows
with context, so it fits at both. A check that assumes a linear cache is
a check asserting the arithmetic this slice replaced. Measured table,
which is what the check is now written from:

```
  8 GiB   4k:8B  16k:8B  64k:8B   256k:none
 10 GiB   4k:14B 16k:14B 64k:14B  256k:none
 12 GiB   4k:14B 16k:14B 64k:14B  256k:14B
 20 GiB   4k:30B 16k:30B 64k:14B  256k:14B
 24 GiB   4k:30B 16k:30B 64k:30B  256k:14B
 29 GiB   4k:30B 16k:30B 64k:30B  256k:14B
```

## Four things measuring the hub corrected in §6.5

Each would have produced a wrong list, and none was reachable by
reasoning about the API docs.

1. **`full=true` and `expand[]` are mutually destructive.** `full=true`
   returns neither `gguf` nor `cardData`; passing both leaves a
   projection of three keys with the sort and filter silently ignored.
   So the ranking call is its own method rather than a flag on the
   existing search one.
2. **`pipeline_tag` cannot be a filter.** Adding
   `filter=text-generation` dropped the *second* most-downloaded GGUF
   repo on the hub, because the field is simply absent on many repos.
   The discriminator that works is a chat template in the repo's own
   `gguf` block — which also excludes the ASR, TTS, embedding and
   projector repos that rank in the top twenty (21 of the top 100).
3. **`base_model` is sometimes a list of sixty.** One top-twenty repo
   bundles every model it supports; merging it would move its downloads
   into sixty families.
4. **`gguf.total` is read off one file in the repo and is sometimes the
   wrong file** — a 27B repo reported 0.5B because the hub read its
   vision projector. A class's parameter count is the mode of its
   contributors.

Plus one the design did not anticipate: **capitalisation split a
family.** `google/gemma-4-E4B-it` and `google/gemma-4-e4b-it` are one
model spelled two ways by two publishers, and unnormalised they were two
candidates with half the downloads each.

## Two things the first review runs taught

**Bits per weight is not enough to pick a quant.** At a 4.8-bit target
the first run chose `IQ4_XS` for one class and `Q4_0` for another, both
within 0.1 bits of `Q4_K_M` and neither the file a stranger should be
handed. Family first, then width.

**The repo cannot be chosen before the quant.** `ggml-org`'s gemma repo
holds `Q4_0`, `Q8_0` and `BF16` and no K-quant at all, so "the
most-downloaded repo from a publisher we know" picked a legacy layout
for a model two other publishers ship a full K-quant ladder for. The
review opens up to three known-publisher repos and stops at the first
offering a preferred family.

## Sabotage

Three, each confirmed to fail its own check and no other:

| removed                                              | what failed                                          |
| ---------------------------------------------------- | ---------------------------------------------------- |
| `withContext` on the starter badge                    | the browser check that every verdict names its context |
| `repo_ref.parse` on the search path                   | all five pasted-reference checks                     |
| the no-accelerator inversion in `starter.recommend`   | the no-GPU reason check, which then recommended a 16 GB model for CPU inference |

## The full run

```
== 3. the starter set is served, scored, and scored from real metadata
  PASS  4 suggestions, source=shipped, engine=llama_cpp b10999
  PASS  reviewed 2026-09-16, 0 days ago
  PASS  the list is inside the 30-day window a release is allowed
  PASS  every entry scores from its own recorded shape (basis=metadata), not from its size
  PASS  every entry names a file, a size and why it is there
  PASS  recommended: 30B -- Qwen/Qwen3.8-27B is the largest of these that runs
        entirely in GPU memory with room for 16,384 tokens of context

== 4. it answers with the catalogue DISABLED -- no upstream call at all
  PASS  the same 4 suggestions with the catalogue off
  PASS  and search beside it refuses with 409, as it must

== 5. the recommendation moves with the machine, and with the context
  PASS  80 GiB -> 30B, 6 GiB -> 4B
  PASS  with no GPU the rule inverts and says why
  PASS  the same 24 GiB card at 4k -> 30B and at 256k -> 14B

== 7. a pasted reference is a lookup, not a query
  PASS  a pasted URL with a /tree/ tail reads as one repo
  PASS  a URL that does not resolve is a 404 naming the repo, not an empty list
  PASS  a bare name that does not resolve falls through to a search

== 10. the review runs end to end against the live hub
  PASS  a report was written (92 lines)
  PASS  exit 0: every class KEEP -- the shipped list is current
  PASS  the review did not touch the file it reviewed (e4950b6842a5)

== result
  ALL CHECKS PASSED
```

## The list this run shipped

Produced by the review on 2026-09-16 against llama.cpp `b10999`, and
accepted by hand:

| class | model                 | repo                              | quant       | size    | 30-day downloads |
| ----- | --------------------- | --------------------------------- | ----------- | ------- | ---------------- |
| 4B    | `Qwen/Qwen3.5-4B`     | `unsloth/Qwen3.5-4B-GGUF`         | `Q4_K_M`    | 2.74 GB | 1,764,959        |
| 8B    | `google/gemma-4-E4B-it` | `lmstudio-community/gemma-4-E4B-it-GGUF` | `Q4_K_M` | 5.34 GB | 4,661,836 |
| 14B   | `google/gemma-4-12B-it` | `unsloth/gemma-4-12b-it-GGUF`   | `Q4_K_M`    | 7.12 GB | 2,645,907        |
| 30B   | `Qwen/Qwen3.8-27B`    | `unsloth/Qwen3.8-27B-GGUF`        | `UD-Q4_K_M` | 16.5 GB | 27,042,038       |

**The 70B class is deliberately empty.** Its leader was mirrored by a
single repo, which the review flags as thin evidence: one repo is a
publisher, not a consensus, and the ranking is a consensus measure.
