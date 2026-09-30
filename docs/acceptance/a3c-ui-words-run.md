# A3c (UI half) acceptance: a split says what sits where

**2026-09-30.** ui `f185a85` (dist `f943f3b`), library `dc08842`, both pinned
in both installers. ui re-pinned to specs `f2d7922`. Sabotage
`scripts/a3c-ui-sabotage.py`. Design:
[`../design/moe-aware-fit.md`](../design/moe-aware-fit.md) §1.3 and §5.

**The defect.** Since A3c's library half, the starter set recommends a 30B-A3B
to an 8 GB card with its experts in system memory. Every screen wrote that
split as *partial offload*, the dense-spill wording. On the same 8 GB budget
the two kinds of split measured 46.5 tok/s and 4.9 (design §0 M2). The
recommendation carried the word for the slow one.

## What the UI says now

`ui/src/lib/fitWords.ts` is the one place a verdict becomes words. The badge,
the starter rows, Discover's per-quant table, the Library's fit panel and
Home's first-model card all read it.

The sentences are the real ones for the shipped list on an 8 GB card with
7 GiB free and 24 GiB of RAM at 16k: the 30B-A3B, then the dense 27B.

| Verdict | `Fit.offload` | Badge | What sits where |
|---|---|---|---|
| `split` | `experts` | experts in RAM | The card holds everything except the experts: 3.70 GiB with the cache. Up to 18.22 GiB of experts go to system memory. That way it fits up to 189,184 tokens. |
| `split` | `layers` | partial offload | About 10.3 GiB does not fit on the card, so some whole layers run from system memory. |
| `split` | null | needs RAM too | (nothing: the file's expert share was not read) |
| `tight` | either | tight | as for `split`, since it would run that way right now |

- **No speed is predicted.** The experts wording says nothing about speed. The
  layer wording keeps "runs more slowly", which is what *partial offload* has
  always said here.
- **Null is neither.** A Discover estimate before **check**, or a scan from
  before the tensor table was read, gets *needs RAM too*. Calling it a dense
  spill would be the same guess in the other direction.
- **Home** says an experts pick in those two short sentences instead of the
  library's reason, which is four long ones. Discover keeps the reason.
- The meanings behind each badge are hover text, marked with `expertHint`.
  `fitWords.ts` joined the copy gate.

## The offer: a new profile starts at the experts-in-RAM context

**Found while wiring the offer, and it is the half that changes what runs.**
Home's reason said *this way it fits up to 189,184 tokens*. The run it started
held **4,096**:
- Admission's `maxContextLength` is the whole file on the card. For this model
  on 8 GB that is 0, so the new `default` profile started with no context.
- With no context set, llama.cpp's fit drops it to its 4,096 floor before it
  moves an expert (profile-builder §0 M2). Set, fit keeps it and moves experts.

`ui/src/lib/contextSuggestion.ts` is now where Run and the profile form both
start a profile:
- The whole-card number first, exactly as before.
- Where there is none and the engine is llama.cpp, the library's
  `maxContextExpertsInRam` for this model, scored against **the node the run
  goes to** (its `GET /v1/node` devices), and only when the fit says
  `offload: experts`.
- **Always set explicitly on that path**, capped at the model's own context.
  `contextPrefill` answers null when the model's own context fits, which is
  right for a whole file on the card and wrong here: unset is the one context
  fit shrinks.
- A dense spill, a node that lists no devices, and vLLM still start empty.
- The profile form's note says which way the number was worked out. "The
  largest context at which this file fits entirely" would have been a setting
  that lies.

No contract change: admission's `maxContextLength` keeps its meaning.

## Checked against the real library, and what that found

The UI's fixtures were checked against `starter.build` itself, scored for an
8 GB card (7 GiB free, 24 GiB of RAM) and a 16 GB one at 16k:

| Card | Pick | MoE entry | `maxContextExpertsInRam` |
|---|---|---|---|
| 8 GB | `30B MoE` | `split`, `experts`, 19,568,525,312 expert bytes | 189,184 |
| 16 GB | `30B MoE` | `split`, `experts` | 262,144 (the model's own) |

**It found a gap in the shipped list.** The four dense entries carried no
`expertBytes`, so the dense 27B's split on 8 GB came back `offload: null`. The
new words would have relabelled it from *partial offload* to *needs RAM too*.

**Fixed in the library, from a measurement.** Each file's tensor table was
read over HTTP Range, header only (12-24 MB of each):

| Class | File | Expert bytes |
|---|---|---|
| 4B | Qwen3.5-4B-Q4_K_M | 0 |
| 8B | gemma-4-E4B-it-Q4_K_M | 0 |
| 14B | gemma-4-12b-it-Q4_K_M | 0 |
| 30B | Qwen3.8-27B-UD-Q4_K_M | 0 |
| 30B MoE | Qwen3.6-35B-A3B-UD-Q4_K_M | 19,568,525,312 (as shipped) |

Library `dc08842` records the zeros. Two tests fail without them: every
shipped entry records its expert share, and the dense 27B on 8 GB scores
`split` with `offload: layers`. Library suite: 570 passed.

## Checks

- **ui:** 1,519 tests, typecheck, lint, format and the copy gate green. New
  files: `fitWords.test.ts`, `FitBadge.offload.test.tsx`,
  `StarterSetPanel.test.tsx`. New cases in the Library page, Home, the run
  chain (a remote node included) and the profile form.
- **Sabotage: 32 of 32 caught** (`scripts/a3c-ui-sabotage.py`), from a copy,
  after a baseline that passed. Two checks were added before the run, because
  a guard had no case that could fail without it: a stray experts number on a
  dense model in the Library panel, and a whole file on the card not asking
  for the experts number.
- **The pinned archive** (`dist` `f943f3b`, fetched from GitHub) carries
  *experts in RAM*, *That way it fits up to*, *needs RAM too* and
  `maxContextExpertsInRam` in its chunks. BUILD_INFO names ui `f185a85`.
- **Every script specs CI runs** passed locally in a Python 3.12 venv with all
  six components editable at their pinned trees, before the pin.

The re-pin also brought PB1's contract into the UI: the new `measurement` stop
reason has words ("a test of this machine paused it, and it starts again when
the test ends"). The benchmark request's two new fields have defaults, and the
UI does not send them yet; that is PB2's shared form.

This `dist` also carries ui `70af2aa` and `1ef3b22`, the Plexus action styling
and its settings-cache test. They were on `main` and in no build until now.

## Not done

- **No engine has loaded a MoE model at the context the prefill writes.**
  189,184 is the library's arithmetic, not a measurement. The profile builder
  is what measures it (PB2 puts it on a page).
- No browser drove these screens. The words are asserted in rendered
  components and in the built chunks.
- Discover's catalogue verdicts before **check** read *needs RAM too* for
  every model, dense or not, because a size-only estimate has no expert
  share. That is honest, and it is one click from the real word.
- The machine with no graphics card is unchanged (design §5).
