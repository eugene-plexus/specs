# Lessons from DeepInfer

**Status: read 2026-10-20, the day DeepSeek released it. Nothing here is
scheduled; the calls at the end are Troy's.** Troy's brief: *examine the
DeepInfer codebase and take every design choice that improves ease of use or
inference speed for our users.*

What was read:
- DeepInfer `774ce24` (2026-10-20, three commits), all of it, and its design
  Q&A, `doc/inference_deployment_qa.md`.
- `deepseek-recipe` `935817c`, its companion protocol library.
- llama.cpp master `5a9a34d88` (2026-10-20), only where a lesson depended on
  what llama-server does today.

File references below are to those commits.

## What DeepInfer is

- **DeepSeek's production engine, released offline-only.** There is no HTTP
  server ("This release does not include an online-serving wrapper",
  `deepinfer/engine/llm_engine.py:140-141`). The release has a batch `LLM.generate`
  and an `LLMEngine.step()` loop, and nothing else.
- **One model and two kinds of hardware:**
  - The model is DeepSeek-V4.1-Flash, and the loader refuses any other
    (`deepinfer/hugging_face/config.py:237-262`).
  - The hardware is NVIDIA SM100 (B200/GB200 class) or Huawei Ascend 950, on
    Linux only. The 5090 is SM120. Unsupported hardware is found late: the
    first check that can fail on it runs after the weights are loaded and the
    graphs captured (`deep_cluster/hardware/device.py:151-156`).
- **Built from source, with no prebuilt wheels.** It vendors six kernel
  repositories and is configured through about 60 `DEEPINFER_*` environment
  variables, with no config file.
- **It is sized for clusters.** The smallest efficient unit is 64 GPUs of
  prefill plus 64 of decode (Q&A, "How large does the smallest deployment unit
  have to be?").
- **What the release leaves out is Eugene's layer.** The README lists three
  things a complete service needs that the release does not include:
  - a KV cache system;
  - prefill/decode disaggregation;
  - load balancing across replicas.

  Those are the gateway's and the agent's jobs in Eugene. The Q&A describes
  how DeepSeek built all three, and that description is most of what Eugene
  can use.

**Verdict: not an engine for Eugene now.** Nobody in Eugene's audience owns
the hardware it runs on, and it has no server for the driver to talk to.
Revisit it if it gains an online server and runs on a card our users own
(DI-C5). The model itself runs elsewhere: vLLM and SGLang serve it, and
community GGUFs exist for llama.cpp (DI8).

## What to take

The kernels, FP4 formats, asynchronous scheduling and speculative-decoding
internals belong to engines. Eugene gets them by installing newer engines,
not by copying them. What follows are the choices that fit a control plane.
They are ordered by what they do for Eugene's users, not by where they sit in
DeepSeek's system.

### DI1. Check an engine update before every replica takes it

**What DeepSeek does:**
- Its real release gate is a perplexity golden that must match exactly after
  any engine change (`tests/models/test_offline_inference.py:139-158`, refreshed
  by `examples/refresh_offline_decode_ppl.py`).
- It has KL checks between step decode and full prefill.
- Fault tolerance comes from spare capacity and moving requests elsewhere,
  not from faster restarts. A decode engine told to stop gets a one-minute
  grace period before it hands off what is unfinished (Q&A, "Autoscaling &
  fault tolerance").

**What Eugene has:**
- Installing a llama.cpp build never touches a running engine.
- `RETAINED_BUILDS = 2` keeps the previous build on disk.
- `POST /v1/engines/{engine}/install` takes a `version` for rollback, which
  has never been run.
- **Rolling upgrades are unbuilt.** Each runtime picks up whichever build is
  current when it next starts, so two replicas can silently serve from two
  builds (memory `project_open_threads`; `release-roadmap.md`, "Rolling engine
  upgrades").
- The profile builder already measures KL divergence and top-token agreement
  (`agent.yaml`, the quantised-cache check).

**The slice:** installing a build becomes a checked rollout.
1. **Check on one replica.** Run the new build against the old one on the
   models this node serves: llama-bench prompt and generation speed, and
   KL/top-token agreement on a fixed text against a reference kept from the
   old build. Bit-exact is not available across llama.cpp builds, since
   kernels change, so this uses the builder's existing KL instrument.
2. **Roll the remaining replicas one at a time, each drained first.** The
   gateway stops sending new conversations to the replica and waits a bounded
   grace period for the requests in flight. The replica then restarts on the
   new build. With DI2 it saves its hot slots first and restores them after.
   Unlike DeepSeek, Eugene cannot hand an unfinished stream to another
   engine (`failover-safety.md`: no fallback after emitted text), so a drain
   can only wait.
3. **Keep the old build when the check fails, and name the measured cause.**
   For example: "b11800 is 12% slower on Qwen3.6-27B on this machine; kept
   b11719." This is the rollback path that already exists but has never run.

A node with one replica, which is most hobbyists, has nothing to roll. Its
update waits for an idle moment, and the check runs before the old build is
retired (DI-C3).

This finishes an open thread and makes line 1 of what we say ("installs,
updates and restarts the engine for you") safe to say about updates. The risk
is moderate: it stops and starts engines, but on primitives that exist. It
also needs an acceptance run with two replicas.

### DI2. Keep the prompt cache on disk across restarts

**What DeepSeek does:**
- It keeps KV cache on SSD for 3 days for agent traffic and 7 days for chat,
  because chat has a long tail of prefixes read many times. A 3-day TTL cost
  chat 0.5-1 points of hit rate.
- A GC worker evicts least-recently-used entries under a disk watermark.
- Matching is a hash chain over metadata only (Q&A, "KV cache storage").

Their first stated design goal is "retain KV cache for more than 72 hours".

**What Eugene loses today:**
- Every engine stop throws the conversation caches away. Stops come from idle
  unload, a model switch on a one-GPU machine, a profile change, an update
  (DI1) or a crash.
- The next turn of each agent session rereads its whole prompt: about 17,900
  tokens shared between two Claude Code sessions in one project
  (`cache-aware-balancing.md` §1).
- On a machine that keeps a MoE model's experts in RAM, the audience A3 was
  built for, prefill is the slow part. Rereading is unmeasured there, and it
  is the case that most needs measuring.

**What llama-server already offers (master `5a9a34d88`):**
- `--slot-save-path` enables `POST /slots/{id}?action=save|restore`.
- A save writes the slot's tokens, its state and its context checkpoints, so
  it works for SWA and hybrid models (`tools/server/server-context.cpp:3022-3034`).
- A restore into a busy slot is deferred rather than run (`:3063-3068`), so
  the busy-slot wedge CB4 found does not apply to it.

**The slice:**
- **Launch with a cache folder.** The agent starts llama.cpp runtimes with
  `--slot-save-path` in the node's own data folder, never a Library folder.
- **Save before a planned stop.** The driver saves every slot that holds a
  conversation from the affinity table.
- **Restore on the next turn.** When a saved conversation's turn arrives,
  the driver restores it into an idle slot and sends the turn with `id_slot`,
  under CB4's rule never to name a busy slot.
- **Validate files by key.** A file is valid only for the same model file,
  engine build, cache type and context layout. It is keyed on those, and a
  mismatch is a miss, never a load.
- **Expire like DeepSeek.** LRU under a size cap, plus a TTL.
- **Show it.** The storage it uses appears on the node's page, with a Clear
  button.
- This extends PC7 (engine cache settings on a profile, unbuilt), which
  already plans `--cache-ram` and `--ctx-checkpoints`.

**Measure first:**
- Save and restore time against reprefill time, for:
  - a dense 8B and 27B on the 5090;
  - a 35B-A3B with experts in RAM;
  - a hybrid model.
- Disk use per conversation.

A crash saves nothing. Periodic saves cost disk writes and are not proposed
until the measurement shows they pay.

**Risk: high (data at rest).** A slot file holds the conversation's tokens,
so it is a copy of people's chats on disk. It has to stay in the agent's
private data folder, expire, and be covered by whatever the owner has decided
about reading chats. That needs one adversarial review (DI-C4).

vLLM and MLX come later. vLLM offloads KV cache to CPU, and LMCache adds
disk. `mlx_lm` can save a prompt cache to a file.

#### Later: move a machine's conversations before maintenance (DI2b)

Troy, 2026-10-20: a large install takes machines offline for maintenance, and
moving their KV to another machine may beat having every client's next turn
reread it. DeepSeek does this: a decode engine told to shut down gets a
one-minute grace period, then forwards its unfinished requests with their KV
to other engines (Q&A, "Autoscaling & fault tolerance").

**A planned drain changes the arithmetic** that rules out moving KV at
failover (see "Not taking"):
- **Nobody waits for the copy.** It runs during the drain and between turns,
  not while a client waits for its first token.
- **Evacuation is a herd.** Every conversation the machine held rereads on
  the remaining machines at about the same time, competing with their own
  users. Moving the KV turns that compute spike into network traffic.
- **Large installs favour the copy.** They have 10-25 GbE or faster, and
  larger models. Prefill work grows with parameters, while a GQA model's KV
  grows more slowly: a dense 70B is 320 KiB per token
  (80 × 8 × 128 × 2 × 2 bytes) against an 8B's 128 KiB, for about nine times
  the prefill work. A 30,000-token conversation on the 70B is 9.2 GiB, about
  8 s on 10 GbE. This is arithmetic; DI3's sweep and DI5's prefill fit give
  the reread side.

**The shape, on DI2's save and restore:**
1. The drain saves each conversation's slot (DI2).
2. The gateway picks each conversation's new replica.
3. The file goes over the node-to-node channel.
4. The target restores it, and the affinity table moves to the target.

**Which conversations move.** Move a conversation only when its estimated
copy time beats its estimated reread time on the target. Move the most
recently used first. Let the rest reread.

**The constraint.** A file is valid only on a replica with the same model
file, engine build and cache type (DI2's key). During a DI1 rollout that
narrows the targets to replicas already on the same build.

**Measure first:**
- whether a llama.cpp slot file saved on one machine restores on another
  with the same build, including across GPU vendors;
- the copy and restore time against a reread, on a 10 GbE pair.

Failover stays a reread: a machine that is gone has nothing to copy, unless
DI2 ever adds periodic saves. vLLM's KV connectors (NIXL, LMCache) are the
equivalent for business installs on vLLM.

**Risk: high.** Conversations cross the network. The node-to-node channel is
authenticated but clear text today (`remote-nodes.md` §7, "TLS between
machines on a LAN"), as is every prompt the gateway already sends to a driver
on another machine. DI2b waits for LAN TLS rather than adding its own
encryption. It needs the same privacy review as DI2.

### DI3. Measure how many people a runtime serves at what speed

**What DeepSeek does:** its benchmarks are Pareto curves of total throughput
against per-user speed, swept over concurrency
(`examples/sweep/run_sweep.sh`, `examples/sweep/plot_pareto.py`). The decode engine profiles
its own step-time curve once per hardware and parallel layout, caches it on
disk keyed by a hash of the model and configuration, and corrects it online
(`deepinfer/worker/decode_perf_cache.py`, `csrc/engine/mtp_varlen.hpp:19-131`).

**What Eugene has:**
- Per-request numbers: `ttftMs`, decode tok/s, prompt and cached tokens.
- A single-stream context-depth benchmark (R6.1).
- The profile builder.

**What is missing:** any measure of concurrent users on one runtime. The
release roadmap's deferred list says so: "never measured, and LM Studio leads
with it".

**The slice:** a sweep through the gateway.
- It is engine-agnostic: llama.cpp, vLLM, MLX and Strata take the same test.
- It runs 1 to N concurrent streams, using a chat mix and the replayed Claude
  Code/Codex sessions the cache-balancing harness already has.
- It draws the curve and states it as people at a speed: "12 people at 20
  tok/s each, or 4 at 60". That is the sentence a business needs before
  buying a second card.
- Results are kept per runtime with their provenance (engine build, profile,
  hardware), like R6.1's records, and go stale when any of those changes.

This one slice replaces three backlog items: the creators' cross-engine
benchmark with a concurrency sweep, the business candidate's gateway load
test at 1-256 streams, and, as an optional watts column, the creators' power
reading.

**Drafting on and off is one of the sweep's dimensions.** SD1's builder
trials drafting at one stream only, but drafting spends compute to save time,
so its gain should shrink as a runtime fills. DeepSeek's own table shows the
same kind of trade: choosing verify lengths dynamically loses 1.5% at 16
sequences per GPU and gains 4-7% at 48-72 (Q&A, "Speculative decoding").

Low risk. DI5 needs this harness.

### DI4. Stop control tokens written in messages from acting as control tokens

**What DeepSeek does:**
- `deepseek-recipe` renders the prompt itself.
- Only template code may insert a special token. User text, tool results,
  tool arguments and schemas are encoded with a tokenizer that has the
  special tokens removed, so `<｜User｜>` typed into a message stays ordinary
  text (`deepseek-recipe-core/src/prompt.rs`,
  `deepseek-recipe-encoding/src/tokenizer.rs:133-210`).
- On the way out, `</think>` and tool-call markers count only when they
  arrive as special-token IDs.

**What Eugene's engines do (llama-server, master `5a9a34d88`):**
- The chat template is rendered to one string.
- That string is tokenized with `parse_special = true`
  (`tools/server/server-context.cpp:2462, 4930`;
  `server-common.cpp:1055-1060` for multimodal prompts).
- So a web page fetched by Workbench's search, a file read by a folder tool,
  or a pasted document that contains `<|im_end|><|im_start|>system` reaches
  the model as a real end of turn and a real system turn.
- This is known upstream: #24382 (closed stale), #26273 (an escape flag,
  closed stale), #26532, and **#28249**, which is open and assigned. The
  Jinja engine already marks input, but the server never consumes the
  marking.
- Users report a second symptom: an agent editing chat templates breaks
  itself.
- vLLM and MLX tokenize a rendered template the same way, as far as is known.
  That is unverified, and the slice checks it.

Eugene sits where the commenters on #28249 built their own workaround: a
proxy in front of the engine.

**The slice:**
- **Write the failing check first.** Send content holding the model's own
  control-token spellings and observe them arriving as control tokens. It
  can be seen through `/tokenize` on the rendered prompt, or through the
  turn ending early.
- **Escape at the gateway.** In user and tool content, the gateway breaks
  each exact spelling of the model's special tokens with an invisible
  character. The Library already reads the GGUF vocabulary, so the list
  comes from the model's own vocabulary.
- **Retire it per build.** Builds that consume input marking skip the escape
  once #28249 lands.

The cost: a model asked to copy such text back, for example when editing a
chat template file, copies the invisible character too (DI-C2).

Rendering prompts and sending token IDs ourselves, as the recipe does, would
make Eugene own every model's template and its output parsing. That is
declined; see "Not taking".

**Risk: high (security).** One adversarial review.

### DI5. Place new conversations by the tokens a replica holds

**What DeepSeek does:**
- **Decode** balances two dimensions at once: the number of requests, which
  sets batch size, and the total KV length, which sets attention cost. Short
  requests go to replicas with few requests but much KV, and long requests
  to replicas with little KV.
- **Prefill** solves each chunk's size from a time budget, using a fitted
  cost model `cost(q, c)`: `q` is the new tokens and `c` the prefix already
  cached (Q&A, "Data-parallel load balancing").
- The cost model is described, not shipped. The released scheduler has no
  quota code.

**What Eugene has:**
- CB2's `spread` counts conversations per slot. Three short chats and three
  80,000-token agent sessions count the same.
- CB3's budget already estimates each conversation's prompt tokens.
- The gateway already records `ttftMs`, `promptTokens` and `cachedTokens` per
  request.

**The slice:**
- **Score by KV held.** `spread` scores a replica by the conversations it
  holds and the tokens they hold.
- **Fit a prefill model per runtime.** Fit
  `ttft ≈ a + b·uncached + c·uncached·cached` from the retained metrics.
- **Use the fit twice.** Placement breaks ties on predicted wait. Workbench
  can say "reading 80,000 tokens, about 40 seconds" before a long first
  token, rather than showing a silent spinner.

**Measure first,** with the cache-balancing harness on DI3's sweep. The rule
is to adopt only what beats `spread`, as CB did. Low risk.

### DI6. Restart on the cards that are left

**What DeepSeek does:** an expert-parallel instance that loses a GPU restarts
with its expert-parallel size set to the healthy GPUs it actually got (Q&A,
"What is the EP failover strategy?"). It neither waits for the card nor
fails.

**What Eugene does:** unknown, and the slice starts by finding out. A
profile's device list or `tensorSplit` names a card that a riser rig has
dropped off the bus. That is common in the r/LocalAIServers setups, and it is
why the setups pass asked for a hardware health readout.

**The slice:**
- **Refit and say so.** At launch, fit recomputes for the cards present and
  starts with what fits: a smaller context, or more of the model in RAM. It
  says which card is missing and what changed.
- **Leave the profile alone.** When the card is back, the next start uses
  the profile as saved.
- **Bundle the readout.** This ships with the hardware readout (PCIe
  generation and width, P2P, temperature, power cap) from the setups pass.

This follows the hardware-compatibility rule. Low risk. It needs a real
multi-card box to accept, which this machine is not.

### DI7. Repeatable answers where the engine supports them

**What DeepSeek does:** batch-invariant kernels, and a sampling seed hashed
with each token's position, give the same answer for the same input whatever
else shares the batch (`deepinfer/model_executor/layers/tilelang_ops/cuda/random_sampling.py:11-84`, `deepinfer/worker/runtime_config.py:67-69`).
It is NVIDIA-only and "slower", and it requires turning dynamic verification
off.

**What Eugene has:** `seed` is carried through, and the contract calls it
"asking for a reproducible answer". On a runtime serving several people, the
batch changes the numbers, so the same seed can still give a different
answer.

**The slice:**
- **A profile setting:** "Same answer every time (slower)".
- **On vLLM** it maps to the engine's batch-invariant mode (check the name
  against the pinned version when picked up).
- **On llama.cpp** the setting says exactly what holds. The slice measures
  whether an answer repeats with other requests running.
- **The audience:** evaluations, benchmarks, agent regression tests and
  businesses that audit answers.

Low risk. Low priority.

### DI8. DeepSeek V4.x Flash through Eugene

DeepInfer exists for this model, and people will want to run it. What Eugene
must handle:
- **The prompt format is code, not a template.**
  - The checkpoint ships no Jinja chat template. The prompt format lives in
    `encoding.py` and in `deepseek-recipe`.
  - A GGUF works only if its converter embedded a template. vLLM and SGLang
    carry their own support.
  - The Library should say when a model has no chat template, and which of
    the node's engines can serve it anyway.
- **Tool calls arrive in DeepSeek's DSML format.** The engine's parser has to
  know it. Check llama.cpp and vLLM.
- **It is large.** Community guides put V4 Flash at about 110 GB at 3 bits.
  That makes it a Mac Studio, a multi-GPU box or a box with a lot of RAM.
  MoE-aware fit applies.
- **It drafts from its own head,** five tokens at a time (`nextn`). If a GGUF
  keeps the head, SD1's own-head path covers it.

This needs hardware this machine does not have. Measure on a rented or
borrowed box, or wait for a user's report.

## Smaller things to check

Each of these is a check, not a finding.
- **A truncated or mismatched model file found before launch.** DeepInfer
  validates every shard's tensor table, shapes, dtypes and byte ranges from
  headers before it reads a tensor (`deepinfer/hugging_face/loading.py:77-170`,
  `deepinfer/hugging_face/weights.py:210-240`). Check whether the Library catches a GGUF whose
  tensor data runs past the end of the file, such as a copied Ollama blob or
  an interrupted manual copy, before the engine does.
- **Engine compile caches kept across restarts.** DeepInfer keeps its JIT
  kernel caches and its performance curve on disk to cut startup time. vLLM's
  `torch.compile` and CUDA-graph capture take minutes. Check that the vLLM
  adapter's cache folder survives a restart and is not a temporary or
  per-launch folder.
- **Errors that name the field.** The recipe's 400s carry the path, for
  example `messages.3.content[1]`. Check the gateway's doors do the same.
- **Model-repo code runs only by choice.** DeepInfer always passes
  `trust_remote_code=True` and imports `encoding.py` from the checkpoint. The
  agent's vLLM and MLX adapters already expose "Trust remote code" as a
  setting, and it must stay off by default.

## Not taking, with the reason

- **Prefill/decode disaggregation.**
  - DeepSeek needs it at 64+64 GPUs; a homelab has one to four cards per
    machine.
  - llama.cpp cannot split the two stages, and across engines the KV formats
    differ.
  - vLLM's disaggregated prefill is the only route. Reconsider it if a
    business user runs vLLM on one multi-GPU machine.
- **Moving a conversation's KV between machines at failover, on a small
  install.** A planned drain on a large install is different, and DI2b
  covers it.
  - The KV of a dense 8B at f16 is 128 KiB per token
    (32 layers × 8 KV heads × 128 × 2 × 2 bytes). A 30,000-token conversation
    is therefore 3.7 GiB.
  - That takes about 34 s on gigabit Ethernet and about 3.4 s on 10 GbE.
    Rereading it on a GPU is in the same range or faster. This is arithmetic,
    not a measurement.
  - DeepSeek can move KV because V4.1 compresses it hard (the SWA store is
    1.4 MB per sequence) and its links are 400 Gb/s.
  - Same-machine disk (DI2) is the tier that pays locally.
- **A shared KV store instead of affinity.**
  - DeepSeek routes prefill with no prefix affinity, because every machine
    can read every prefix from 3FS.
  - Eugene's caches live inside each engine, so affinity stays (CB1), and the
    LAN arithmetic above rules out sharing.
- **Per-expert load balancing (EPLB).**
  - DeepInfer replicates hot experts across GPUs in an expert-parallel group.
  - The local equivalent, keeping hot experts on the GPU and cold ones in RAM,
    needs per-expert placement, which llama.cpp's merged expert tensors do
    not allow. That is an engine feature.
  - If an engine adds it, it becomes a profile-builder trial.
- **Choosing verification length dynamically** (confidence-scheduled
  verification). It loses at 16 sequences per GPU and gains from 32 up, and
  Eugene's runtimes mostly serve 1-8 streams. llama.cpp b11719 already has a
  `draft-dspark` type for the drafting half.
- **Environment variables as the configuration surface.** About 60
  `DEEPINFER_*` variables and no config file is the opposite of GUI equality.
  When an engine Eugene wraps adopts one of these features, its switch
  becomes a profile setting.
- **Rendering prompts and tokenizing in the gateway,** as `deepseek-recipe`
  does. It is the complete answer to DI4, but Eugene would then own every
  model's template and output parser, which the engines maintain today.
  DI4's escape plus upstream #28249 covers the risk without that.
- **Never mixing prefill and decode in one step.** The released engine runs a
  prefill at most once every 70 decode steps (`csrc/engine/scheduler.hpp:295-341`). That
  only works with a separate prefill tier in front of it, and it is a reason
  not to wrap the engine as released.

## Calls for Troy

| # | Question | Recommended |
| --- | --- | --- |
| DI-C1 | Which of DI1-DI8 go on the roadmap, and in what order? | **DI4, DI3, DI1, DI2**, then DI5 after DI3's numbers. DI6 with the setups pass's hardware readout. DI7 and DI8 when someone asks. DI4 is small and closes a hole every agent client has today. DI3 answers the one capacity question Eugene has never measured, and it replaces three backlog items. |
| DI-C2 | DI4: escape control-token spellings at the gateway, or warn only until upstream #28249 lands? | **Escape by default, in user and tool content.** Each key gets a switch to turn it off, and the escape retires per engine build once input marking lands. The cost is the invisible character in text copied back verbatim. |
| DI-C3 | DI1: on a node with one replica, update at the next idle moment and revert by itself if the check fails, or ask first? | **Ask, showing the check's result:** "b11800: 3% faster, same answers. Switch now, or when idle?" The operator started the update, so one more click costs little. A silent revert would be a setting acting on its own. |
| DI-C4 | DI2: is the disk prompt cache on by default, and with what limits? | **On for llama.cpp, 3 days, a 20 GiB cap.** It shows on the node's page with Clear. It is in the agent's private folder and is never readable as text through the UI. The privacy review decides whether chats under "the owner may not read people's chats" are cached at all. |
| DI-C5 | Wrap DeepInfer as an experimental engine? | **No.** No server, no hardware our users own, one model. Revisit when it ships an online server and supports a consumer card. |
