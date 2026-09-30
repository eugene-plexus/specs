# Profile builder: automatic load tuning

**Status: designed 2026-09-30, not built.** §0 holds the measurements, §1–§8
the design, and §9 the calls for Troy. Nothing is committed or pinned.

This is the first item on the next roadmap. It came out of the Unsloth
comparison, filtered through the saved Reddit threads (T2's largest group of
comments is settings, quants and "does it fit my card"). It is a
profile builder: the user can build a model profile by hand, or ask Eugene
to build one by measuring on their own machine.

## Decisions already taken (Troy, 2026-09-30)

- **On demand only, never forced.** It builds a model profile, and an
  expert can still edit the profile by hand.
- **Accuracy presets, like JPEG quality in Photoshop:** Low, Med, High, Max.
  A preset decides which output-changing settings the tuner may touch.
- **The user balances accuracy, speed and context size.** The widget is
  whatever is simplest and most intuitive, and is left to UX research (the
  design, not yet done).
- **MoE-aware fit in Discover and the library is a separate slice.**

## §0 Measurements

### The setup

- **Machine:** Amish_Station — RTX 5090 32 GB (30,991 MiB free at the
  start), Ryzen 9 9950X, 94 GB RAM, models on local NVMe. The live
  Amish_Station service was stopped for the run with Troy's agreement and
  restarted afterwards (health `ok`, its runtime back).
- **Engine:** llama.cpp **b11215**, `win-cuda-13.4-x64+vulkan`, taken from a
  test install on disk. The binaries were run directly on loopback port
  18190, not through the agent.
- **Models:**
  - A dense model: **Qwen3.6-27B Q4_K_M**, 15.8 GB.
  - A MoE model: **Qwen3-30B-A3B-Instruct-2507 Q4_K_M**, 18.56 GB,
    downloaded from `unsloth/…-GGUF`. Its sha256 matches the hub's LFS oid.
- **Smaller cards were simulated** with llama.cpp's own
  `--fit-target <margin MiB>` on the 5090. The simulation is honest to
  within a few hundred MiB: at the "8 GB" margin, the server actually used
  **7,731 MiB** (dense) and **8,014–8,246 MiB** (MoE), measured with
  `nvidia-smi`. A real 8 GB card has about 7.5 GiB usable, so the 8 GB rows
  are **slightly optimistic**.
- **This CPU is a 16-core desktop part with DDR5.** Anything offloaded to
  RAM runs faster here than on T2's laptop 4060 with 16 GB of RAM, so every
  offloaded number below is an **upper bound**.
- **Method:** llama-server numbers are its own reported `timings`. Each
  request is a 512-token prompt given as token ids, with the prompt cache
  off, EOS ignored and 128 tokens generated, and `-np 1`. llama-bench runs
  are `-p 512 -n 128 -r 3`. The scratch scripts were `server_bench.py` and
  shell loops in the session scratchpad; they aren't kept.

### M1. The engine already has the knobs, and an automatic fit that is ON by default

- **llama-bench b11215 accepts** `-ngl`, `-ncmoe/--n-cpu-moe`,
  `-ot/--override-tensor`, `-sm none|layer|row|tensor`, `-ts`, `-dev`,
  `-ctk`/`-ctv`, `-fa`, and its own `-fitt`/`-fitc`. It takes
  comma-separated lists for sweeps.
- **llama-server has `--fit on|off`, and the default is on.** It adjusts
  arguments that were left unset so the model fits in device memory, with
  `--fit-target` (default a 1024 MiB margin) and `--fit-ctx` (the minimum
  context it may set, default 4096).
- **`llama-fit-params` prints the arguments fit would choose, in about
  1.3 s, without loading the weights.** That makes it a cheap candidate
  generator.
- **Eugene's llama.cpp adapter maps none of** `--n-cpu-moe`, `-ot`, the
  cache types or `--fit*`; `_FLAG_CLI_NAMES` in
  `agent/…/engines/llama_cpp.py` has no entry for them. An expert can reach
  them only through raw `extraArgs`. Eugene leaves `gpuLayers` unset by
  default, so **upstream's fit already decides the placement at every
  launch today**, with the context Eugene prefilled.

### M2. What upstream's fit chooses

**Dense 27B**

| Card | Context left to fit | Context set to 16,384 |
|---|---|---|
| 32 GB | `-c 225024`, all layers on the GPU | all layers on the GPU |
| 24 GB | `-c 127488`, all layers | all layers |
| 16 GB | `-c 4096`, `-ngl 63` | `-ngl 60` |
| 12 GB | `-c 4096`, `-ngl 45` | `-ngl 42` |
| 8 GB | `-c 4096`, `-ngl 26` | `-ngl 25` |

**MoE 30B-A3B**

| Card | Context left to fit | Context set to 16,384 |
|---|---|---|
| 32 GB | `-c 129024`, all on the GPU | all on the GPU |
| 24 GB | `-c 64000`, all on the GPU | all on the GPU |
| 16 GB | `-c 4096`, all 49 layers on the GPU; **the expert weights of blocks 41–48 go to the CPU** via `-ot` | experts of blocks 37–48 on the CPU |
| 12 GB | experts of blocks 29–48 on the CPU | experts of blocks 25–48 on the CPU |
| 8 GB | experts of blocks 17–48 on the CPU | experts of blocks 13–48 on the CPU |
| 6 GB | experts of blocks 11–48 on the CPU | experts of blocks 7–48 on the CPU |

**Fit's policy is one fixed trade.**
- If everything fits, it takes the largest context.
- If not, it drops the context to `--fit-ctx` (4096) **before** it moves
  any weight off the GPU.
- Then it offloads from the last blocks: whole layers for a dense model,
  expert tensors only for a MoE model.

**So automatic MoE expert offload, one of the things Unsloth advertises,
is upstream's default.**

**KV-cache type only changes fit's answer when the cache is large.** For
the dense 27B on the full card, `q8_0` raises the context from 225,024 to
262,144 (the model's maximum). At the 16 GB margin, f16, q8_0 and q4_0 all
get `-c 4096 -ngl 63`.

### M3. llama-bench against llama-server, at the same settings

| Configuration | llama-bench decode / prefill (tok/s) | llama-server decode / prefill (tok/s) |
|---|---|---|
| Dense, all on the GPU | 76.6 / 3,609 | 78.8 / 2,768 |
| Dense, `-ngl 45` | 9.0 / 918 | 8.8 / 729 |
| MoE, 8 GB via fit | 48.5 / 773 | 46.5 / ~732 (steady) |

- **Decode agrees within 4%.** llama-bench reads prefill **6–30% higher**.
- **Every pair ranks the same way in both tools.**
- **The first request after a load prefills at a quarter to a third of
  the steady rate** (MoE: 222, 724, 740), so a measurement must throw
  that run away.
- **Instrument trap, found by running it:** llama-bench's `-fitc` does
  **not** change where it places the model. The context of a bench test is
  prompt + generated + depth (about 640 tokens), so fit always placed it
  for that. An eight-config sweep over `-fitc` 4096…65536 × f16/q8_0
  returned the same speed eight times (47.1–48.6 tok/s), and it is
  discarded. The placement for a target context must be worked out at that
  context (with `llama-fit-params -c N`, or by the server itself) and then
  handed to the measurement explicitly.

### M4. The three-way trade, measured (MoE, simulated 8 GB)

- **At equal memory, expert offload beats layer offload.** Fit's pick
  (8.1 GB, experts on the CPU) decoded at **46.5 tok/s**. `-ngl 19` (8.2 GB,
  whole layers on the CPU) decoded at **33.5**, so expert offload is
  **39% faster**. Prefill was about the same (~732 against ~746).
- **Dense against MoE on 8 GB:** the dense 27B decoded at **4.9 tok/s**
  (prefill 437) and the 30B-A3B at **46.5**, about **9.5×**. Fully on the
  5090, the MoE model decodes at 325 tok/s (prefill ~11,200, 19.8 GB).
- **Context costs speed, and quantising the KV cache buys some of it
  back.** All at the 8 GB budget, with fit placing the model:

| Context | KV cache | VRAM (MiB) | Decode (tok/s) | Prefill (tok/s) |
|---|---|---|---|---|
| 4,096 | f16 | 8,059 | 50.6 | ~795 |
| 65,536 | f16 | 8,031 | 34.4 | ~533 |
| 4,096 | q8_0 | 8,014 | 50.6 | ~798 |
| 65,536 | q8_0 | 8,079 | 40.7 | ~627 |

At 64k context, 8-bit KV is **18% faster** than f16, because the smaller
cache leaves more experts on the GPU. That is accuracy traded for speed at
a fixed context, which is exactly the balance the presets and the widget
have to express. **The accuracy side of it is not measured** (see Not
measured).

### M5. How long it takes

- **A candidate from `llama-fit-params`: about 1.3 s**, with nothing
  loaded.
- **One llama-bench configuration, pp512 + tg128 × 3, including the load:
  27 s** for the MoE model. The dense model took 69 s for two
  configurations.
- **llama-server is ready in 4.6–8.7 s**, from local NVMe with the file in
  the page cache.
- **A sweep of 8–12 candidates is therefore about 4–6 minutes on this
  machine.**
- **Storage dominates on anything slower.** At the measured 100 MB/s over
  SMB, loading 18.6 GB takes about 3 minutes, every configuration,
  whenever the file isn't cached. On a 16 GB-RAM machine it can't be
  cached. So tune from the node-local copy
  (`node-local-model-copy.md`), not over the share.

### M6. What Eugene says about the MoE model on an 8 GB card today

Read from `library/fit.py`, not run.
- `compute` gives verdict **`split`**, with the note "assumes full GPU
  offload".
- `max_context_that_fits` returns **None**, because the weights alone
  exceed free VRAM.
- The starter set only recommends a model that fits **entirely** in VRAM.

So on the card where upstream's fit decodes this model at 46–50 tok/s,
Eugene offers no context and would never suggest the model. That belongs
to the separate Discover/library slice.

### M7. What cache precision costs in quality

- **Perplexity** (`llama-perplexity`, `-c 8192`) is over the whole
  wikitext-2 test set.
- **KL divergence and "same top token"** are measured against each
  model's own f16-cache run, on 8 chunks at `-c 4096`, which is 16,384
  scored tokens.
- **Runs:** fully on the GPU, `-fa on`, the same b11215 build.
- **Controls:** a control run of f16 against its own stored baseline read
  **KLD 0.000000 and 99.994% / 100.000% same top token**, so the
  differences below are real, not noise.
- **Instrument note:** the "PPL ratio" printed in KL mode is biased
  (1.0015 and 1.006 in the controls), because the stored baseline is
  quantised to 16 bits. So perplexity comes from the separate full runs.

| Model | Cache | Perplexity at 8k | Mean KLD | Same top token |
|---|---|---|---|---|
| MoE 30B-A3B Q4_K_M | f16 | 6.2915 | — | — |
| | q8_0 | 6.2946 (+0.05%) | 0.0039 | 97.3% |
| | q4_0 | 6.3862 (+1.5%) | 0.0282 | 93.1% |
| Hybrid 27B Q4_K_M | f16 | 7.0998 | — | — |
| | q8_0 | 7.1028 (+0.04%) | 0.0357 | 97.1% |
| | q4_0 | 7.1270 (+0.38%) | 0.0486 | 96.0% |
| **Yardstick:** the MoE model one quant step down (UD-Q3_K_XL, 13.8 GB), f16 cache, against the Q4_K_M baseline | | 6.4024 (+1.8%) | 0.0294 | 92.7% |

1. **On the MoE model, a 4-bit cache costs about as much as one step down
   in weight quantisation**: KLD 0.028 against 0.029, and 93.1% against
   92.7%. An 8-bit cache costs about a seventh of that.
2. **The cost depends on the architecture, by about 9×.** The 27B turned
   out to be a **hybrid** (`qwen35`: 64 blocks, attention in every 4th, so
   only 16 layers hold a cache). Its q8_0 cache costs KLD 0.036, where the
   MoE model's costs 0.004. A fixed rule of "High means 8-bit cache" would
   be wrong by an order of magnitude on one of the two models measured. So
   **the quality cost has to be measured on the user's model, not assumed**
   (§3).
3. **Perplexity is too blunt for this.** q8_0 moves it by 0.05% on both
   models, inside the run-to-run noise, while KLD and same-top-token
   separate every row.
4. **This build's flash-attention kernels only handle matching K and V
   types.** The log reports
   `FA_QUANTS = q4_0-q4_0,q8_0-q8_0,f16-f16,bf16-bf16`, so the builder only
   ever sets them as a pair.

### What §0 suggests for the design

1. **Don't write a placement search. Upstream's fit already does
   placement, MoE included.** The tuner chooses the inputs fit does not:
   the context (and so `--fit-ctx`), the KV cache type (the accuracy
   preset), and possibly flash attention and the fit margin. It then
   measures the candidates and picks by the user's balance. Candidates come
   from `llama-fit-params` (1.3 s each); measurement uses llama-bench with
   the placement passed explicitly, or the server.
2. **Report decode from llama-bench. Treat prefill as relative only, and
   always discard a warm-up run.**
3. **It is a tasks-tray job measured in minutes.** It runs on demand with
   the node's runtimes stopped (R6.1's rule), and from the node-local copy.
4. **The accuracy presets choose the cache precision** (and quant level
   later, which is another download). M7 shows the cost varies 9× by
   architecture, so a preset is a **quality threshold measured on the
   user's model**, not a fixed cache type.

### Not measured

- **Quality on anything but wikitext-2 prose**: chat, code, tool calls.
  Quality on two models only.
- **A real 8 GB card, a laptop CPU, or 16 GB of system RAM.** Every
  offloaded number here is an upper bound.
- **Two GPUs, the integrated Radeon, Vulkan, AMD or a Mac.**
- **Speed at depth** beyond a 512-token prompt (R6.1's benchmark has depth
  curves), and concurrency (`-np` greater than 1).
- **Any agent-driven run.** Every number came from the binaries directly.

## §1 What it is

On a model's page, beside its profiles, a person presses **Build settings
for this machine**:
1. They pick an accuracy level.
2. Eugene tries a handful of settings on that machine for a few minutes.
3. It shows what each setting actually gave.
4. The person picks where they want to be between faster replies and a
   longer memory, and saves the result as a profile.

It never runs on its own. If models are running on that machine, it **asks
before stopping them** and starts them again afterwards, so nobody has to
leave the page (Troy, 2026-09-30). It works on the node the page is looking
at (`node:<name>`, the one-console rule). The profile it
writes is an ordinary profile that an expert can open and edit.

**It does not:**
- change the model file. A smaller quant is another download, which is the
  separate MoE/Discover slice.
- tune threads, batch sizes or parallel slots. It leaves llama.cpp's
  defaults.
- tune vLLM or MLX. llama.cpp only, as R6.1 is.
- invent a placement. §2 explains why.

## §2 What it chooses, and what it leaves to llama.cpp

**Placement is llama.cpp's.** `--fit` is on by default and places a model
well, including MoE expert offload (M1, M2, M4). A second placement search
would compete with upstream and lose on every model it hasn't seen.

**The builder chooses what fit doesn't:**
- **Context size.** This is the main lever. It costs speed once the cache
  pushes weights off the GPU (M4).
- **Cache precision.** Always as a K/V pair (M7.4), and only within the
  accuracy preset (§3).
- **Flash attention.** On whenever the cache is quantised, which the V cache
  requires. Otherwise left at llama.cpp's `auto`.
- **Memory margin**, `--fit-target`. It defaults to llama.cpp's 1024 MiB.
  It is an expert setting worded as **Leave this much graphics memory
  free**, for someone who games or renders on the same card.

**The profile stores these inputs, not a placement.** `gpuLayers` stays
unset, so at every launch fit places the model for the memory that is
actually free then. §6 covers what the page says when that differs from
build time.

## §3 Accuracy presets

**Troy's JPEG analogy is the right shape:** a short list of named levels,
each a promise about quality. M7 says the promise can't be a fixed cache
type, because the same 8-bit cache costs 9× more on one of the two models
measured. So **a preset is a quality threshold measured on this model**:

| Preset | Allowed | The promise |
|---|---|---|
| **Max** | f16 cache only. Nothing is measured, because nothing changes. | Answers exactly as this file allows (today's behaviour). |
| **High** | Any cache whose measured same-top-token rate is **≥ 96.5%** against Max | "Picks the same next word as Max at least 96 times in 100, on this model." |
| **Medium** | ≥ 92% | "…at least 92 times in 100." |
| **Low** | Deferred (§9, call 1) | — |

- **Boundary rule:** a type passes only if its measured value **minus one
  standard error** clears the threshold, so a borderline model can't flip
  between runs.
- **Against M7:** q8_0 passes High on both models (97.3%, 97.1%). q4_0 fails
  High and passes Medium on both (93.1%, 96.0%).
- **These thresholds are calibrated on two models** (§9, call 2).

**Why same-top-token rather than KLD:** it is the one number a person can be
told honestly ("the same next word, 97 times in 100"). KLD is recorded as
evidence, and an expert sees it in the hint.

**How it's measured:**
- `llama-perplexity` with `--kl-divergence-base` on the f16 cache, then
  `--kl-divergence` for each lower type the preset could allow.
- It runs over a bundled evaluation text: 4 chunks at 4096, so 8,192 scored
  tokens (§9, call 4).
- High measures q8_0 only. Medium measures q8_0 and q4_0.
- The baseline file is about **2.5 GB** of temporary disk (tokens × vocab ×
  2 bytes) and is deleted afterwards. The job refuses to start without twice
  that free, and names the drive.

## §4 The run

**Before it starts.** These are R6.1's rules, with one change:
- llama.cpp only.
- **Running models are stopped only after asking** (Troy, 2026-09-30).
  R6.1 refused instead, which sends the person to another page and back.
  - A preflight call lists the models running on the node.
  - The page asks: *"Stop qwen3-14b and gemma-4-12b while this runs?
    They start again when it finishes."* It adds one more line when
    something depends on them: *"Apps using them get an error until then."*
  - **Start stops exactly the models the person was shown** (`stopRuntimes`
    in the request), never "whatever is running now". A model started
    between the question and the click is not in that list, so the job
    refuses and asks again rather than stopping something nobody agreed
    to.
  - **Afterwards, the job restarts those models itself** (`restartAfter`,
    on by default). That happens whether the run completes, fails, is
    cancelled or times out. A model that fails to restart is reported by
    name on the result.
  - Stopping is never implicit. A request without the list, while models
    are running, is refused with their names, as R6.1 does.
  - **R6.1's Benchmark button moves to the same behaviour** (Troy,
    2026-09-30). One ask-stop-restart step in the agent serves both jobs, so
    the two pages behave identically (§8).
- One job per node, holding the launch lock, so a wake or Run waits.
- The tasks tray shows progress, a cancel reaps the child, and the result
  persists.
- It uses a valid node-local copy if one exists and never makes one.

**It also checks:**
- `llama-bench`, `llama-fit-params` and `llama-perplexity` are beside the
  `llama-server` that discovery would select. A missing one is named, with
  the engine version.
- There is disk for the quality step.
- **The estimated time**, from the number of candidates × (file size ÷ the
  read rate of where the file lives + about 20 s). The person sees it
  before pressing Start. Over a share at gigabit speed that is about 3
  minutes per load (M5), and the page says so and points at the local-copy
  switch.

**The phases:**

1. **Quality** (skipped at Max). The preset decides the allowed cache types
   (§3).
2. **Candidates.**
   - Build a ladder of contexts: 4k, 8k, 16k, 32k, 64k, 128k and the
     model's maximum, capped at its trained context.
   - For each context and each allowed cache type, ask
     `llama-fit-params -c N -ctk T -ctv T -fa on -fitt <margin>`. That costs
     1.3 s each and loads nothing (M1). Drop any candidate fit can't place
     at that context.
   - If two cache types place identically at a context, the more precise
     one costs nothing, so keep only it.
   - Otherwise keep both, because the smaller cache is faster only when it
     moves weights back onto the GPU (M4, 64k).
3. **Measure.** Run `llama-bench` with the placement **passed explicitly**:
   `-ngl`, `-ot` (fit's commas become `;`), `-ctk/-ctv`, `-fa`.
   - **Never `-fitc`.** That is M3's trap: it measures the same placement
     every time.
   - Use `-p 512 -n 128 -r 3` at depth 0 and at depth `min(N/2, 8192)`.
   - Decode is the reported speed. Prefill is shown only relative to the
     other candidates (M3).
4. **Confirm.**
   - Start `llama-server` once with the recommended candidate's inputs,
     letting fit place it.
   - Check that it loads, record the graphics memory used, compare its
     placement with the measured one, and send one short completion. Then
     stop it.
   - A placement that differs is reported, not hidden.
   - A failed load removes that candidate and confirms the next one.

**The Pareto set.** Drop every candidate that is both slower and shorter
than another. What remains is what the person chooses from.

**Time:** about 27 s per measured candidate here (M5), plus 1–2 minutes of
quality measurement, so **about 4–8 minutes on this machine**, and more
when the file is read over a share. The deadline is 30 minutes, against
R6.1's 15, with partial results kept on timeout.

## §5 The widget

**The research:**
- **Photoshop's Save for Web** pairs its Low/Medium/High/Maximum list with
  a **preview of the consequence**: the resulting file size under each
  preview.
  ([elated](https://www.elated.com/the-save-for-web-feature/),
  [Envato Tuts+](https://photography.tutsplus.com/tutorials/save-for-web-better-jpeg-compression-with-adobe-photoshop--cms-23080))
- **The NVIDIA App's Optimize** is one slider from Performance to Quality,
  tailored to the user's hardware, with the resulting settings previewed
  and described as a starting point.
  ([NVIDIA](https://www.nvidia.com/en-us/geforce/news/nvidia-app-download-and-features/),
  [XDA](https://www.xda-developers.com/the-nvidia-apps-game-optimizer-is-not-appreciated-enough/))
- **Research on three-criteria choices for non-specialists** found the
  triangle slider best for exploring a vague intuition, and parallel
  sliders best for setting a preference directly.
  ([IEEE CG&A 2023](https://pubmed.ncbi.nlm.nih.gov/37607155/),
  [TOP-slider](https://www.researchgate.net/publication/327866321_The_TOP-slider_for_multi-criteria_decision_making_by_non-specialists))
- **NN/g:** sliders are poor for precise values and a poor fit when each
  movement triggers a slow computation. Feedback should come within 0.1 s.
  ([NN/g](https://www.nngroup.com/articles/gui-slider-controls/))

**The recommendation is two controls, used at two different times.** Not a
triangle.

1. **Accuracy, before the run.** A four-segment control in Photoshop's
   order (Max · High · Medium, plus Low when it exists), with one plain
   line under the selected level. It is a decision made before measuring,
   because it changes *what* gets measured.
2. **Faster ↔ Longer memory, after the run.** One slider that **snaps to
   the measured options** (the Pareto set). Each stop shows its
   consequence, the way Photoshop shows file size, for example: *"About 35
   words a second · holds about 100 pages"*.
   - Exact tokens per second, context and cache type sit in the expert
     hint (`expertHint`, per S8).
   - The slider only moves over results that already exist, so it answers
     instantly (NN/g's 0.1 s), and it never starts work.

**Why not a triangle:**
- Accuracy is a constraint chosen before anything is known, and the
  speed/context trade only exists after measuring. A triangle would ask for
  three weights before any consequence exists.
- The research places it for exploration, not for stating a preference.
- It is also a 2-D drag target, which is hard at phone width (S9).

**Defaults:**
- **Accuracy:** High (§9, call 3).
- **Slider:** the **longest memory that keeps at least 80% of the fastest
  speed** measured at the 8k depth. For scale, M4's 512-token-prompt
  figures at the 8 GB budget put 64k with q8 at 40.7 against 50.6 tok/s
  for 4k, which is 80%.
- The person moves it. The default is stated, never silent.

**Copy:**
- The golden-path gate (`vocabulary.ts`) bans implementation nouns, and
  every sentence stays under 25 words.
- "Words a second" is tokens × 0.75, and "pages" is 650 tokens a page.
  Both are labelled "about", because they are approximations, and the hint
  carries the exact figure.

## §6 What it saves, and settings that never lie

**Save** writes a new profile named *Built for {node}* (editable), or
replaces the profile the person started from, after an explicit
confirmation.

**The profile gets the inputs:**
- `contextSize`
- the new `cacheType` flag
- `flashAttention: on` when the cache is quantised
- the margin, as a new `memoryMargin` flag

Nothing else. `gpuLayers` stays unset (§2).

**And a `builtBy` record:** job id, node, preset, date, engine version,
measured decode at depth 0 and 8k, graphics memory at the confirm step, and
the measured same-top-token rate.

**Settings never lie:**
- Each field the builder set reads *Set by the settings builder on 30 Sep*
  and stays editable.
- Editing one marks the profile *edited since it was built*. The measured
  numbers then no longer describe it, so they are labelled, not deleted.
- At launch, if fit places the model differently from build time (less
  free memory), the model's row says so. The agent captures fit's chosen
  arguments from llama-server's log; the build has to verify that they
  appear.

**Admission trusts the measurement.** For the same file, engine version
and node, a built profile's measured memory replaces admission's estimate.
Without this, the MoE model on 8 GB that the builder proved at 46 tok/s is
scored `split` and given no context by today's arithmetic (M6). This is the
narrow bridge; the MoE-aware estimate itself remains the separate slice.

## §7 Contract and repos

**`agent.yaml`:**
- `POST/GET /v1/profile-builds`, `GET /v1/profile-builds/{id}` and
  `POST /v1/profile-builds/{id}/cancel`.
- `POST /v1/profile-builds/preflight`, a dry run. It returns the running
  models it would need to stop, the time estimate, the disk check and any
  missing tool.
- `ProfileBuildRequest`: `modelId`, `profileId?`, `runtime` (a
  RuntimeSpec), `accuracy`, `memoryMarginMiB?`, `stopRuntimes[]`,
  `restartAfter` (default true).
- `ProfileBuild` records which models it stopped and whether each one came
  back.
- `ProfileBuild`: `state`, `phase`, `progress`, `detail`, `quality[]`,
  `candidates[]`, `recommended`, engine version, commands, hardware.
- **Every enum is named** (`ProfileBuildAccuracy`, `ProfileBuildPhase`,
  `CacheType`). An inline enum once renamed `Source` to `Source1` across
  the library.

**`library.yaml`:** `ModelProfile.builtBy`, optional.

**Agent code, not the contract:** the curated flags `cacheType` (→
`-ctk`/`-ctv`, checked against the build's `--help`) and `memoryMargin` (→
`--fit-target`). The UI renders them from the agent's flag schema as it
does today.

**Radius:** regenerate all six consumers and diff. Re-pin only where
something consumes the change: the agent, the library and the UI, with
control regen-only by the usual rule.

## §8 Slices and acceptance

**PB1: the job (specs, agent).**
- The two flags, tool discovery, the four phases, persistence, cancel, the
  lock and the preconditions.
- **The shared ask-stop-restart step, wired to both jobs.**
  `BenchmarkRequest` gains `stopRuntimes[]` and `restartAfter`, beside a
  Benchmark preflight, so R6.1's Benchmark uses the same step as the
  builder. PB2 changes the Benchmark form to ask.
- **Done when:** `scripts/profile-builder-acceptance.py` runs the builder
  through the agent's API on this box against the MoE model at a
  7.5 GB margin, and:
  - reproduces M4's ordering (expert offload wins, 64k is slower than 4k,
    q8 is faster than f16 at 64k);
  - chooses q8_0 at High;
  - never quantises at Max;
  - produces a candidate that loads within the margin.
- A CPU run on a small model covers CI.
- **Sabotages include:**
  - `-fitc` instead of explicit placement (M3's trap);
  - dropping the warm-up;
  - a missing tool;
  - the boundary rule removed;
  - a model stopped that was not in `stopRuntimes`;
  - a stopped model not restarted after a cancel or a failure.
- **Acceptance uses its own throwaway models, never the live install's.**

**PB2: the page (ui, library, and admission in the agent).**
- The builder panel, the presets, the slider over results, Save, the
  never-lie labels, the tray, and admission trusting `builtBy`.
- The Benchmark form asks before stopping, like the builder.
- **Done when:** a browser run builds, saves and launches the profile, and
  the launched model's row matches what was saved.
- Phone width, and the S8 copy gate.

**Separate, already decided:** a MoE-aware fit in the library, Discover
and the starter set.

## §9 Calls for Troy

| # | Call | Recommendation | Against it |
|---|---|---|---|
| 1 | Four presets or three | **Three now (Max, High, Medium). Low arrives with the MoE/Discover slice**, where its lever, a smaller file, exists | A Low that did what Medium does would break settings-never-lie. The cost is not matching the JPEG list on day one |
| 2 | Thresholds | **High ≥ 96.5%, Medium ≥ 92% same top token**, re-checked on more models in PB1's acceptance | Calibrated on two models |
| 3 | Default accuracy | **High.** 8-bit cache passes it on both models and buys speed at long context | Max is today's behaviour and changes nothing |
| 4 | Evaluation text | **A bundled text we own** (prose, code and chat), so it works offline with no licence question | wikitext-2 is the field's standard for comparison, but it is CC BY-SA and needs a download |
| 5 | Admission trusts a built profile's measured memory | **Yes, for the same file, engine and node** | It is a second rule in admission until the MoE-aware estimate lands |
| 6 | Where the button lives | **The model's profile page first.** Home's Run could offer "make it faster" later | Home is where beginners are |
