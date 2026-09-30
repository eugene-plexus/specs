# PB2 acceptance: the settings builder's page

**2026-09-30.** Contract specs `dc2f35d` (`ModelProfile.builtBy`); library
`0d9f1f2`; ui (see the pin commit) with dist rebuilt; both installers
pinned. Browser run `scripts/pb2-browser-acceptance.py` with
`ui/e2e/profile-builder.spec.ts`; sabotage `scripts/pb2-sabotage.py`.
Design: [`../design/profile-builder.md`](../design/profile-builder.md) §1,
§5, §6 and §8. Roadmap: A2.

**Troy took call 6 the same day, as recommended:** the button lives on the
model's profile page first. Home's "make it faster" can come later.

## What a person gets

On a model's page, beside its profiles, **Build settings for this machine**
opens the builder for the node the page is looking at (`node:<name>`, the
one-console rule):

1. **Accuracy**, Max · High · Medium · Low, with one line under the chosen
   level stating the agent's own threshold ("Picks the same next word as
   Max at least 96 times in 100, on this model"). Max is the default
   (call 3). Under *More options*: the memory margin, worded *Leave this
   much graphics memory free*, and the person's own text, pasted or chosen
   as a file (≤ 2 MB, sent with the request and not kept).
2. **The question before anything stops.** The page asks the node's dry
   run and says *Stop gemma-4-12b while this runs? It starts again when it
   finishes. Apps using it get an error until then.* Start sends exactly
   those names as `stopRuntimes`, with `restartAfter`. A model started
   between the question and the click makes the agent refuse with 409, and
   the page asks again with the new names. A reason the node would refuse
   (a missing tool, too little disk) is listed and Start is disabled. The
   estimate is shown ("About 7 minutes").
3. **Progress**, in plain words per phase, with Cancel, and the models it
   stopped named. It carries on if the page is left; the header tray shows
   it (every reachable node's builds, like benchmarks).
4. **The slider**, *Faster replies ↔ Longer memory*, snapping to the
   measured frontier only, starting on the build's own suggestion, marked
   *suggested*. Each stop reads *About 30 words a second · holds about 101
   pages*; the exact tokens a second, depth, context and cache are the
   expert hint. The cache's cost is the promise it keeps: *Picks the same
   next word as Max 96 times in 100* (rounded down), or *Answers exactly as
   this file allows* for full precision.
5. **Save** writes *Built for {node}* (editable) as a new profile, or
   replaces the profile it started from after a confirmation. It sets only
   `contextSize`, `cacheType`, `flashAttention` when the cache is quantised
   and `memoryMargin` when one was asked for. `gpuLayers` is dropped, since
   placement is llama.cpp's at every launch. The base's other settings are
   kept, because the build measured with them.

**Settings never lie, on a built profile:**
- The row carries a *built* badge and the measured line: *Measured on
  Amish_Station: about 30 words a second, room for about 101 pages. Same
  next word as Max 96 times in 100.*
- In the edit form, every field the builder set reads *Set by the settings
  builder on 30 Sep*. Changing one reads *…, and edited since*.
- Once a builder field changes (or `gpuLayers` is set by hand), the badge
  reads *built, edited since* and the numbers are labelled *measured before
  this profile was edited; these numbers may no longer describe it*. They
  are not deleted.

**R6.1's Benchmark asks the same question**, through the same component
(`AskBeforeStopping`), instead of sending the person to Inference to stop
models by hand.

## The contract and the library

`ModelProfile.builtBy` / `ModelProfileSpec.builtBy` reference a named
`ProfileBuiltBy`: build id, node, accuracy, when, engine version, the flags
it set, and what it measured.

**It is the one exception to the profile replace's whole-document rule.**
Every UI edit path writes a whole profile and none of them knows the field,
so a plain replace would have dropped the record on the first edit. A `PUT`
that omits it keeps it; only an explicit `null` clears it. Library tests
cover this through HTTP (the route must not rebuild the body and lose
`model_fields_set`) and across a restart. The gateway also generates from
`library.yaml` (R8 reads profile defaults) and consumes nothing new, so it
stays at its pin.

## Checks

**Browser run, 9 of 9 in Chrome, plus 8 API checks, all PASS.** A
throwaway standalone agent on free ports, supervising its own library; a
CPU-only llama.cpp build (b11254 `win-cpu-x64`) placed in the run's own
managed engine store; Qwen2.5-Coder-0.5B Q8_0 in the library's folder.
The live install kept serving on the 5090 throughout; a CPU build never
touches the card.

| Step | What it saw |
|---|---|
| open | the button on the model's page; Max the default |
| preflight | nothing running to stop; "About 2 minutes." |
| start | "Asking llama.cpp where each setting fits" |
| result | "About 55 words a second · holds about 50 pages · suggested. Answers exactly as this file allows." |
| save | "Saved as Built for Amish_Station." |
| measured | "Measured on Amish_Station: about 55 words a second, room for about 50 pages." |
| launch | the saved profile's launch |
| running | the model's page: "Running on this machine now" |
| phone | at 390 px the page is 390 px wide and the result ends at 361 px |

Then, from the APIs: one built profile whose record names a completed build
this node ran; the record's flags are the profile's (`contextSize` 32,768,
`cacheType` f16); no `gpuLayers`; **the launched runtime's flags are exactly
the saved profile's**; the runtime is `ready`; the engine answers a
completion. No process or listener from the run was left behind.

On a CPU every context places alike, so the longest is suggested. On the
execution before this one the speeds fell within 3% and one stop was the
whole frontier, which the page said ("Only one setting was worth keeping on
this machine"); on this one CPU noise kept a second. The GPU frontier (seven stops, two at 8,192) is the
unit tests' fixture: PB1's real Medium and High builds on the 5090 at an
8 GB margin, scrubbed of paths.

**Sabotage, 32 of 32 caught** (`scripts/pb2-sabotage.py`, from a copy, after
a baseline that passed) across the ui and the library.
- The first pass caught 32 of 33. The escape was a spare: an explicit f16
  guard in the record's quality lookup that the lookup already covered,
  because the agent never lists f16 in `quality[]`. It was deleted, with
  its sabotage.
- Before the run, four checks were added because the real fixture agreed
  with a plausible break: the precision tiebreak (the agent happens to list
  f16 first), depth against empty-context speed (both round to 30 words),
  round against floor (96.324), and the tray reading only this machine.

**ui:** 1,560 tests, typecheck, lint, format and the copy gate (the new
files are in it) green. The browser run's first two executions failed in
the harness, not the product: `engineBinaryRoots` is a trust list, not
discovery, so the build now goes into the run's managed store; and the
Unlock button stays disabled until a passphrase is typed, so the sign-in
fills until it enables rather than waiting for it first.

**Every script specs CI runs** passed locally before the pin (see the pin
commit).

## Not done

- **At launch, a different placement from build time is not reported.**
  §6 wants the model's row to say so when fit places it differently (less
  free memory), from fit's arguments captured in llama-server's log. That
  needs the agent to capture them and a `Runtime` field to carry them; it
  is its own slice.
- **The browser run is CPU and Max only.** The quality step (High, Medium,
  Low), the ask-to-stop path with a real running model, and the GPU
  frontier are PB1's API acceptance and this slice's component tests, not
  a browser run: the 5090 was serving the live install.
- **A3d**, Low's offer of a smaller file of the same model after a build,
  is next.
- Home's "make it faster" offer (call 6, later).
