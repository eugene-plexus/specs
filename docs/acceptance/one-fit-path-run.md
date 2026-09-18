# R1.3 — one fit path: the run

**2026-09-18. `scripts/r13-acceptance.sh`, 17 PASS, zero failures, third
execution. `scripts/r13-sabotage.py`, 13 sabotages, 13 caught, 0 escaped.**
Roadmap: [`../design/release-roadmap.md`](../design/release-roadmap.md) §2.3.
Findings closed: review §6.1 #4 (two fit paths, and the golden path used the
wrong one) and §6.3 #36 (the `contextSize`/`parallelSlots` contradiction).

Repos: `library`, `agent`. **No contract change and no UI change** — the config
descriptions render from the schema, so the corrected copy reaches the browser
without a `dist` rebuild. Neither installer is re-pinned; the six pins stay as
R1.1 left them, to be bumped once at the end of R1.

---

## 0. The measurement that had to come first

**§6.3 #36 was a contradiction inside this repo, and the review marked it
Plausible and explicitly did not verify it.** The two `ConfigField`
descriptions the profile form renders verbatim said `-c` is per-slot and that
memory multiplies with slots; `fit.py` and `admission.py` compute the opposite.
One of them was wrong regardless — but which one depends on current
`llama-server` semantics, and `--kv-unified` changes them. Rewriting the copy
off the unverified premise risked being wrong in the other direction, so the
slice opened with a launch.

`llama-server` **b11001** (0.4.1-dev, f266648fa) on a Qwen3-0.6B Q4_K_M, and
independently **b10991** (930e2fa59) on a Qwen3-1.7B Q8_0, `-ngl 99`:

| launch | `llama_context: n_ctx` | per-slot window |
| --- | --- | --- |
| `-c 32768 --parallel 1` | **32768** | 32768 |
| `-c 32768 --parallel 4` | **32768** | **8192** (×4) |

plus `load_model: n_slots = 4, n_ctx_slot = 8192, kv_unified = 'false'`.

**The allocated cache is 32768 in both.** `-c` is the *total* KV budget and
`--parallel` divides it into per-request windows. **So the arithmetic was right
and the copy was wrong** — and wrong in the expensive direction: it told an
operator that raising slots would cost memory, making the apparently-sensible
response to "I want 4 concurrent requests" to lower context. That is the one
change that really does shrink each request's window, for no memory saved.

**And it explains a number that reads as a failure.** `/props` exposes only
`default_generation_settings.n_ctx`, the per-slot value (`props.n_ctx` was
absent on both builds), so a runtime launched at 32768 with 4 slots reports
`capabilities.contextLength: 8192` — against a contract whose word for a
number that differs from the request is **clamped**, which sends an operator
looking for memory they are not short of. The field keeps its meaning (what one
request can use, which is what the truncation detector needs); the admission
reason now says the division out loud, and only when it happens.

---

## 1. The fit path

**Four call paths produce a fit verdict and only one was wrong — the one the
golden path uses.** Catalogue search and detail, preflight and the starter set
all build their shape through `preflight.shape_from_gguf`. `GET
/v1/models/{id}/fit` built its own in `routes/guidance.py::_shape_for`, whose
`by_suffix` accepted only `int` and never set `layers`. That route has one
commit in its history, from M3, and the 43x per-layer KV fix of 2026-09-16
landed everywhere but there.

`_shape_for` rebuilds a `GgufMetadata` from the stored KV dict and delegates.
**A second shape builder is the defect; there is one now**, and
`shape_from_gguf`'s docstring says so. The route puts back the two values the
library reconciles rather than reads — `contextLength` and `parameters` — which
is the only thing the delegation has to add.

**Two more things on the same screens.** `attention.layer_indices` is honoured
as well as `full_attention_interval` (it always was, in `attention_layers()`;
the route just never called it). And `_INLINE_ARRAY_LIMIT` was **64** while the
shipped starter block counts are 32, 42, 48 and **65** — so a per-layer array
on a model in the product's own starter file was stepped over, the scalars
answered, and the fit still said `basis: metadata`. The limit is 512 now (the
thing being excluded is a vocabulary, three orders of magnitude away, so there
is no squeeze), **and a shape whose per-layer terms were dropped stops claiming
they were read** — which is what a library scanned before this fix still looks
like, until it is re-scanned.

---

## 2. What the live run proves that the unit checks cannot

| check | what it shows |
| --- | --- |
| 1 | the measurement above, re-run against whichever llama-server this box has |
| 3 | `GET /v1/models/{id}/fit` over a real scanned per-layer GGUF: **0.520 GiB** of KV at 16k, `basis: metadata` |
| 4 | **two readers, one file, one number** — the route's `557842432` against `preflight.shape_from_gguf`'s `557842432`, read in a separate interpreter |
| 5 | a **65**-element per-layer array survives the scan |
| 6 | **the golden path**: a real agent's admission, consulting that real library over HTTP, reports `basis: metadata` and the **same** `maxContextLength` (173,056) |
| 7 | the admission reason for a 4-slot launch states the 8,192-token per-request window measured in check 1 |

The fixture GGUFs are written by the run itself and declare what a real current
12B declares: `head_count_kv` an array, `sliding_window_pattern` a **bool**
array, five layers in every six sliding over a 1024-token window.

---

## 3. The sabotage pass

`scripts/r13-sabotage.py`: baseline green in both repos, **13 sabotages, 13
caught, 0 escaped**, both gates green again after every restore. Restores from
a copy taken up front, never `git checkout --`.

**Three escaped on the first pass and every one named a missing check rather
than a needless guard.**

**`per_layer_dropped` could return `False` and nothing failed** — because the
test for the honest-basis rule built its `ModelShape` by hand, so it asserted
the *reporting* and never called the *detection*. This repo's recurring shape,
and the fix is a check that builds a stored entry the way a pre-fix scan left
one (a `<key>.length` with no value) and drives `_shape_for` over it.

**The route could stop reconciling the entry's own `contextLength`** and every
check stayed green, because for a scanned GGUF that value comes from the same
KV block. Reachable only through a stored entry, so the check builds one —
40,960 recorded against 262,144 in the block, and the entry's value has to win
because `max_context_that_fits` uses it as the ceiling.

**The fixture could write the bool array as int32** and nothing noticed, since
the reader tolerates both and answers the same. That means the whole suite was
asserting about a type the reader never meets in the wild — `bool` is an `int`
in Python, so an encoder that checks `int` first writes every one of these as
int32. There is a check on the type itself now, which is what makes the
roadmap's *Done when* true rather than claimed.

---

## 4. Two harness defects, both in this run's own instrument

**`-v` is required or the engine never prints the line the measurement needs.**
Without it `llama_context: n_ctx` is absent, the check read an empty string, and
the first execution reported a correct engine as a failure — the measurement
that the whole copy rests on, inverted by a missing flag.

**`sort | tail -1` over paths does not find the newest build.** It sorts the
whole path, so `/tmp/ep-one-click-run/.../b10991` beat
`/tmp/ep-download-and-run/.../b11001`. Sorted numerically on the build number
now. (The measurement replicates on both builds, so this changed no result —
but the script's comment claimed something it was not doing.)

---

## 5. What the unit checks pin

- `library/tests/test_one_fit_path.py` — 13 cases over **written GGUFs**, not
  hand-built `ModelShape`s. A `ModelShape` fixture would have passed against
  the old `_shape_for` unchanged, because the defect was in the reading and the
  arithmetic has had per-layer tests since S6.
- `agent/tests/test_context_and_slots.py` — 10 cases. The copy is checked
  against the measurement; `check_admission` is driven end to end for both the
  slot-invariant memory and the divided-window sentence, because a helper being
  right proves nothing about its caller.

---

## 6. Not covered

- **No screen was opened.** The two-number divergence was visible on the
  Library detail card and `StarterSetPanel`; this proves the route and the
  admission agree, not that the browser renders it.
- **The measurement is two builds on one machine**, both Windows/CUDA. A build
  with `--kv-unified` on by default would change the answer, and nothing here
  would notice until the acceptance run was re-run.
- **No real per-layer model was launched** — the fixtures carry the metadata
  and no weights, and the engine measurement used ordinary Qwen3 files.
- **A library scanned before this fix is not re-scanned by anything.** It
  reports `basis: estimate` with a note saying to re-scan, which is honest and
  is not a migration.
