# A node keeps its own copy, and a load says how far along it is

**Status: designed 2026-09-17, on Troy's calls, from measurements taken
the same day on the live two-machine install. NOT BUILT.** Two features
that arrived together out of one misdiagnosis and land independently:
**§7, load progress**, is small, contract-light and can ship on its own;
**§1-§6, the node-local copy**, is the larger one. Build order is §7
then the rest, because §7 makes the rest observable.

Reopens the storage half of
[`m11-compute-storage-separation.md`](m11-compute-storage-separation.md).
**It was never a numbered decision there** — it is in that document's
§"What it is not" (*"Not a file-transfer protocol, not a node-side
cache, not a managed store... Nothing here moves a byte"*) and in its
§9 scope, as *"Any file transfer, cache or store. The rule that made
this project worth building."* Which is worth knowing: a scope
exclusion carries no counter-argument and no owner, so nothing in M11
recorded what it would cost or who could reverse it. Troy reversed it
on 2026-09-17. The mechanism M11 built — a path rule on the
node's agent, applied at every spawn, never written onto the
declaration — is untouched; this inserts one step ahead of it.

---

## Where this came from

A misdiagnosis, which is worth recording because the feature exists to
prevent it happening to someone else.

Troy reported that his Windows worker `Amish_Station` would not talk to
the control root after a restart until he entered the passphrase on
that machine directly, and believed the OS-keyring auto-unlock was
failing. It was not. Measured 2026-09-17: the node was started cold from
its logon task with nobody signing in, recovered its master key from the
keyring, announced itself, and was polled by the control root **608
times with zero non-200 responses** — and then served a completion
through the NAS gateway in 925 ms.

What actually happened is that for **ten minutes and one second** the
node was up, enrolled, healthy and answering, while its runtime read a
24.95 GB model over SMB and had nothing to serve. Every surface in the
product during that window looks exactly like a node that is broken.

The person watching had no way to tell "reading, 40% done" from "hung",
and no way to make the ten minutes not happen. Those are §7 and §1-§6.

---

## Decisions

Troy's calls are recorded as calls, not as recommendations. The rest are
taken as recommended so a build can proceed; each is his to overturn.

| # | The call | Recommendation | Counter-argument | Status |
| --- | --- | --- | --- | --- |
| 1 | Whether a node may keep local copies at all | **Yes**, overturning M11's scope exclusion (not a numbered decision — see above) | M11 scoped it out to keep the slice finite, and differentiator #3 forbids a managed store — §1.3 is the line that keeps #3 honest | Troy's call |
| 2 | The toggle is per node, not per model | **Per node.** *"Some machines an operator is comfortable using local storage and some others they may not"* | A per-model pin is finer-grained — and is a decision the operator would have to take again for every model, on every node | Troy's call |
| 3 | The unit of a copy | **The model file**, and the set is the distinct files of that node's declared runtimes (§2) | Troy proposed one per active inference engine; that double-counts M6 replicas, which are N runtimes over one file (§2.1) | taken, from Troy's call |
| 4 | The disk knob | **Minimum free space to leave**, not a maximum to use (§3) | A cap is easier to reason about in isolation — but headroom is the quantity the operator actually cares about and stays meaningful as the disk fills for unrelated reasons | Troy's call |
| 5 | Copy first, then launch — or launch from the share and copy behind it | **Copy first** (§4.1) | Copying behind the launch never makes a first run slower — except the arithmetic says copy-first is already *faster* on the first run and costs half the wire traffic | taken |
| 6 | Staleness detection | **Size + mtime** against the library's listing (§4.3) | A content hash is honest — and costs a full read of both copies on every start, which is the cost being removed | taken |
| 7 | A **Clear local copies** button | **Yes**, and it says out loud that copies return while the toggle is on (§5.2) | Troy's call | Troy's call |
| 8 | Whether the adapter forces `--load-mode none` for network paths | **No.** Guidance on the field, not automation (§6.2) | It would make every network launch faster with no thought — and `easy-default-expert-override` says default only when the thing *cannot work* otherwise, never when it merely performs better | taken |
| 9 | Progress bar driven by a flag, or self-detecting | **Self-detecting** from the byte counter (§7.2) | A flag is simpler — and would be wrong for vLLM, for whatever upstream changes next, and for the mmap path where there are genuinely no bytes | taken |

---

## 0. What measuring found

All on the live install, 2026-09-17: `Amish_Station` (Windows, RTX 5090,
1 Gbps) reading a 24.95 GB Q6_K_L from an UnRAID SMB share at
192.168.16.252.

### 0.1 The load was 2.6x slower than the link allows, and it is a flag

| Path | Time to `model loaded` | Effective rate |
| --- | --- | --- |
| mmap (llama.cpp default) | **10m01s**, and 9m27s the run before | 41 MB/s |
| `--load-mode none` (buffered reads) | **4m16s** | 97 MB/s |
| Plain sequential read of the same file, same box | — | **113.6 MB/s** |
| Local NVMe on that box | — | multiple GB/s |

The whole 10 minutes sits between `load_model: loading model` and
`init: llama threadpool init`; nothing else is in it. A mapped read over
SMB never gets the read-ahead a buffered read does, which is the entire
gap. Fixed for the flag surface in agent `d4454ee` — see §6.1.

**So the prize for a local copy is not the 10 minutes, it is the 4.**
Copying at 113.6 MB/s and then loading from NVMe is a one-time 4 minutes
followed by loads of roughly twenty seconds, indefinitely.

### 0.2 Load progress is observable, but only on one of the two paths

`GetProcessIoCounters`, 268 MB touched per run:

| Read path | `ReadTransferCount` delta |
| --- | --- |
| buffered, local disk | **+268.4 MB** |
| buffered, over SMB | **+268.4 MB** |
| memory-mapped | **+0.0 MB** |

This **reopens the refusal in `hobbyist-ux.md` §11.9**, which recorded
that *"there are no bytes"* because llama.cpp mmaps and faulted pages
are not read I/O on Windows. That is still exactly true of the mmap
path, and now false of the buffered one — so the answer is per-path, not
per-product.

**A trap recorded because it produced a confident wrong answer first.**
The initial measurement reported `+0.0 MB` for *both* paths, which looks
like a clean confirmation of S7's finding. It was the API failing:
`GetCurrentProcess` returns a pseudo-handle of `-1`, ctypes defaults the
return type to `c_int`, and the truncated value made
`GetProcessIoCounters` return FALSE while the zeroed struct read as a
legitimate answer. **Set `restype` to `HANDLE` and check the BOOL.** A
measurement that agrees with the thing you already believe is the one to
re-run.

### 0.3 The window has no honest reporting today

During the 10m01s: `GET /v1/runtimes` reports `status: loading`,
`/healthz` on the engine answers 503 `loading model`, and the Inference
screen shows elapsed at best. Nothing distinguishes "reading, 40% done"
from "hung on a dead share".

---

## 1. The rule

> **A node with the toggle on keeps a local copy of exactly the model
> files its declared runtimes point at. Nothing else, ever.**

### 1.1 What that gives you for free

The set is a pure function of the node's runtime list, which the agent
already holds. That removes every policy that a cache normally needs:

- Two GPUs running two models → **two copies**.
- Four M6 replicas of one model → **one copy**.
- A runtime deleted, or repointed at a different model → **its copy goes
  with it**, no LRU, no timer, no heuristic.
- A runtime idle-unloaded by M6 but still declared → **the copy stays**,
  which is the case that matters most (§1.4).

### 1.2 What it is not

It is not a library and it is not a store. The distinguishing property
is not size or count:

> **You cannot put anything in it by choosing.** A library is browsed
> and acquired from. This only ever mirrors what the node is already
> configured to run.

That property holds however many models end up in it, which a count
limit would not have guaranteed.

### 1.3 The line that keeps differentiator #3 honest

Troy's position is that #3 is not a constraint he is bound by as the
solo developer, and he is right about that. The line is still worth
drawing, for a reason that is about behaviour rather than about a rule:

> **We manage what we made, and never touch what you put there.** The
> copy directory is created by us, named by us, and deleted by us. Every
> Library folder is the operator's, and nothing here writes to one,
> renames anything in one, or deletes from one.

Concretely: the copies are **plainly named**, at the model's own
relative path under a directory the operator picked. Not
content-addressed, not hashed, not opaque. Delete the product and what
is left on that disk is a folder of correctly-named GGUFs.

### 1.4 The consequence worth having on purpose

M6 built idle unload and start-on-demand. On a storage-separated node
nobody would switch them on today, because a wake costs four minutes.
With a local copy a wake is roughly twenty seconds and the GPU memory
comes back between uses for free. **This slice is what makes an M6
feature usable on the topology M11 built.**

---

## 2. The unit is the file

### 2.1 Why not "one per node"

Troy's first shape was one model per node. It does not survive a node
with two GPUs running two different models, which is an ordinary
homelab arrangement and is exactly what `Amish_Station` will be when
the 3090 goes back in.

### 2.2 Why not "one per inference engine"

The natural correction, and it fails the other way. M6's headline case
is **replicas**: two `llama-server` processes serving one GGUF, balanced
least-busy, proved live in `docs/acceptance/m6-six-process-run.md`. That
is two runtimes over one file. Keying a copy to the runtime would copy
the same 24.95 GB twice, or need de-duplication bolted on afterwards —
at which point the file was the unit all along.

### 2.3 Why not "one per GPU"

Because one engine can span several. `tensorSplit` on the llama.cpp
adapter and `tensorParallelSize` on the vLLM adapter both do it, and the
vLLM field's own description says a tensor-parallel runtime *"reports as
one backend"*. Troy raised this himself and is correct.

### 2.4 So

**Distinct `modelPath` values across the node's declared runtimes.**
De-duplication is free, because a set of paths already has it.

---

## 3. The disk knob is headroom

### 3.1 Minimum free space, not maximum used

Troy's call, and the argument for it generalises: *a minimum free space
remaining selection tends to be more useful than a never-use-more-than-N
selection.* Headroom is a property of the volume the operator cares
about for reasons that have nothing to do with us — the OS needs room,
so does everything else on that disk — and it stays meaningful as the
disk fills for unrelated reasons. A cap is relative to nothing, and
models running 4 GB to 70 GB make a count knob worse still.

Default **50 GB**, editable per node.

### 3.2 It is a moving target, so it is checked twice

- **Before a copy:** `free − size ≥ headroom`, else skip the copy, launch
  from the share as today, and say why on the Inference screen. A launch
  never fails because of this.
- **During a copy:** a 25 GB transfer takes minutes and something else
  can fill the disk underneath it. Re-check periodically; on a breach,
  abort and remove the partial.

### 3.3 A partial copy must never be usable

Copy to a temporary name in the same directory, `fsync`, then rename on
completion. The renamed file is the only thing anything ever opens. Same
discipline `library`'s downloader already has, and for the same reason.

### 3.4 Eviction, which the cap version did not need

If free space falls below headroom for an unrelated reason, give the
space back: delete copies, oldest first, until headroom is restored.

**The platforms differ here and it is worth knowing in advance.** On
Windows a file a process has open or mapped **cannot be deleted at all**,
so a running runtime's copy is protected by the OS rather than by our
code. On Linux the `unlink` succeeds, the running engine keeps its inode,
and the space is returned when that process exits — correct, but later
than an operator watching a disk meter will expect. Report what was
evicted and what is pending.

---

## 4. Mechanics

### 4.1 Copy first, then launch

The arithmetic settles this, and it is the opposite of the intuition
that says "never make the first run slower":

| | first launch | later launches | wire traffic, first run |
| --- | --- | --- | --- |
| copy first, then load locally | 3m40s + ~20s ≈ **4m00s** | **~20s** | 24.95 GB |
| launch from the share, copy behind it | **4m16s**, then 3m40s more | ~20s | 49.9 GB |
| today | 4m16s | 4m16s | 24.95 GB |

You pay the wire once either way, and a plain copy moves bytes faster
(113.6 MB/s) than an engine reading them (97 MB/s). Copy-first is
already marginally faster than today on the very first run and halves
the traffic against the background alternative.

### 4.2 Resolution order

The copy is a **resolution-time decision**. `RuntimeSpec.modelPath` is
untouched — M11's rule, and the reason `?path=` still finds the library
entry. The agent already resolves a declared path to a `localPath` via
folder mounts and per-node overrides; the copy gets first look:

1. A valid local copy exists → open it.
2. Otherwise → the M11/library-folders resolution exactly as today.

Turning the toggle off therefore reverts by itself, with no state to
unwind.

### 4.3 Staleness

Size + mtime against the library's own listing for that model. Mismatch
→ re-copy before launch.

**The tradeoff, stated rather than hidden:** a GGUF edited in place with
its mtime preserved would serve stale. A content hash would catch it and
costs a full read of both copies on every start — which is the cost this
whole slice exists to remove. If that trade is wrong, the alternative is
to hash once at copy time, store it beside the copy, and re-verify only
on operator request.

### 4.4 What a copy is named

`<copy dir>/<the model's path relative to its Library folder>`. So
`/models/huihui-ai/Huihui-…-Q6_K_L.gguf` under a copy directory of
`D:\eugene-models` becomes
`D:\eugene-models\huihui-ai\Huihui-…-Q6_K_L.gguf`. Plain, predictable,
and useful to a human with a file manager.

---

## 5. UI

### 5.1 Where the toggle lives

The node's Config, under **Model storage**, beside the Library folder
overrides — and cross-linked to them both ways, per
[[cross-link-related-settings]], because "where this node finds models"
and "what this node copies locally" are the same question asked twice.

Three fields, in plain words (S8's vocabulary rules apply — no "cache"
in the copy):

- **Keep a local copy of the models this machine runs** — the toggle.
- **Where to keep them** — a path, with the folder picker, defaulting
  under the install directory. Warn, do not refuse, if it lands on the
  same volume as the OS.
- **Always leave at least ___ GB free on that disk** — default 50.

### 5.2 Clear local copies

A button beside them. It deletes what it can and **reports what it
skipped and why** rather than stopping runtimes to get at their files.

Its own text must carry the thing that will otherwise surprise someone
who clicked it to free space:

> Copies are made again the next time these models start. Turn the
> option off first if you want the space to stay free.

### 5.3 The Inference screen

Each runtime already shows where its model is being opened from. It
gains **which copy** — the local one, the folder mount, or an override —
and, when the copy was skipped, the reason (not enough headroom, copy
failed, toggle off).

---

## 6. Interaction with the load mode

### 6.1 What already landed

agent `d4454ee`, 2026-09-17: `noMmap` and `mlock` on a runtime profile
were spawning `--no-mmap` / `--mlock`, which llama.cpp b10948 **rejects**
— upstream replaced both with `-lm/--load-mode MODE` — so ticking either
field in this project's own schema crash-looped the runtime. The
spelling is now read off the binary's own `--help`, and `explain_exit`
names a refused argument instead of leaving `lastError` at "exited with
code 1". Both installers pin it (specs `d573344`).

### 6.2 The right flag follows the path, not the node

Once a model is local, `--load-mode none` **stops being the right
choice**: mmap from NVMe is fast *and* does not need 25 GB of RAM to
hold the file. So the correct setting differs per launch, by where the
file is.

**It is not automated.** `easy-default-expert-override` says to default
only where the thing cannot work otherwise, never where it merely
performs better — and this is squarely the latter. What ships instead is
guidance: the `noMmap` field now carries the measurement in its own
description (agent `d4454ee`), and the Inference screen can suggest it
when a runtime is opening its model over a network path.

---

## 7. Load progress — the small half, which lands first

### 7.1 Why it is worth its own section

It is independently useful, it is small, and it is the thing that would
have prevented the misdiagnosis this whole document came from. It should
ship before §1-§6 and not wait for them.

### 7.2 Self-detecting, never a fake bar

The agent polls the engine process's read-byte counter and divides by
the model file's size. **It keys off the counter, not off a flag:**

- bytes advancing → a real percentage and a rate;
- bytes pinned at zero → elapsed, plus the path the bytes are crossing,
  and no bar at all.

That is right for mmap, for `--load-mode none`, for vLLM, and for
whatever upstream does next — and it never draws a bar it cannot back.

### 7.3 The counter, per platform

| | Source | Verified |
| --- | --- | --- |
| Windows | `GetProcessIoCounters().ReadTransferCount` | **yes**, §0.2 — set `restype` to `HANDLE` |
| Linux | `/proc/<pid>/io` → **`rchar`**, not `read_bytes` | **no.** `read_bytes` counts block-layer I/O and can be 0 on a network filesystem, which is the case that matters here |
| macOS | `proc_pid_rusage` → `ri_diskio_bytesread` | **no** |

An unavailable counter is the zero case above, not an error.

### 7.4 Where it stops being true

The read finishes before the engine is ready — VRAM upload and warmup
follow. So the bar reaches 100% and then sits. **Say "uploading to the
GPU" there** rather than letting 100% mean nothing for twenty seconds;
llama.cpp's own `load_model → threadpool init` boundary is where that
transition is observable.

### 7.5 Contract

`Runtime` gains `loadProgress { bytesRead, totalBytes, source }`, absent
when unmeasurable. `source` says which counter answered, so a Linux box
reporting nothing is distinguishable from one whose engine is genuinely
not reading.

---

## 8. Contract and radius

`agent.yaml`:

- config trio: `modelCopyEnabled`, `modelCopyDir`, `modelCopyMinFreeGb`
- `Runtime.loadProgress` (§7.5)
- `Runtime.localPathSource`: `folder | override | copy`
- `Runtime.localPathNote`: why a copy was not used, when it was not
- an operation to clear the copies, reporting what was skipped

`library.yaml`: nothing. The library remains authoritative and is not
told that copies exist.

**Radius, to be measured rather than assumed** — regenerate all six and
diff, per [[polyrepo-spec-codegen-workflow]]. Expected: `agent`,
`control` (regen-only, it reads the agent's surface) and `ui` move;
`gateway`, `library` and `inference-driver` codegen neither document and
should come back byte-identical apart from the header SHA. **Expected is
not measured** — the last three times this was predicted it was right
twice.

---

## 9. Scope

**In:** the toggle, the path, the headroom, the Clear button, copy
before launch, staleness by size+mtime, resolution ahead of the M11
rule, the Inference screen's source line, and §7 in full.

**Out, deliberately:**

- Any copy of a model no runtime on that node points at.
- Peer-to-peer or node-to-node transfer. The share is the source.
- Pre-warming a copy before a runtime is declared.
- Verifying a copy by hash on every start (§4.3).
- Copies on the control host. It runs no engines.

---

## 10. Risks

1. **Two copies of a large file can disagree.** Mitigated by size+mtime
   and by the source line on Inference, not eliminated. §4.3 names the
   hole.
2. **A full disk is a new failure mode we introduced.** Mitigated by
   headroom checked before *and* during, by aborting mid-copy, and by
   never failing a launch over it.
3. **It could grow into the store the project refuses to be.** The
   guard is structural, not a rule: the set is a function of the runtime
   list, so there is no mechanism by which an operator could put a model
   in it deliberately.
4. **The first launch after enabling is not faster**, and without copy
   progress in the tasks tray the operator will conclude the toggle did
   nothing — which is precisely the misdiagnosis in §0.3, reintroduced
   by the feature meant to fix it. The tray entry is not optional.

---

## 11. Verification

A run on the two-machine install, because one box cannot show the thing:
the whole point is a node whose models live on another machine.

1. Toggle off: a launch opens the share, `localPathSource: folder`,
   timed.
2. Toggle on: the same launch copies first, `localPathSource: copy`,
   timed — **and the second launch timed separately**, which is the
   claim.
3. Two runtimes, two different models, one node → two copies.
4. **Two M6 replicas of one model → one copy.** The assertion that
   distinguishes this design from the one Troy first proposed.
5. Delete a runtime → its copy goes.
6. Headroom: fill the disk to within the margin, launch, assert the copy
   is skipped, the launch still succeeds, and the reason is on screen.
7. Mid-copy breach: abort, no partial left behind, launch still
   succeeds.
8. Clear with a runtime running → reports what it skipped; on Windows
   assert the in-use copy survives.
9. §7: a load bar advances against `--load-mode none` and is **absent**
   under mmap — the negative case is the one worth asserting, because a
   bar that appears when it cannot be true is the failure mode.

Sabotage each, restoring **from a copy and not with `git checkout --`**
([[feedback-sabotage-runs-restore-from-a-copy]]), and open with a
baseline assertion that the suite passes unsabotaged.

---

## 12. Traps known in advance

- **`GetCurrentProcess` truncates through ctypes** and silently produces
  a zeroed, plausible answer (§0.2).
- **An open or mapped file cannot be deleted on Windows** and can on
  Linux, so eviction behaves differently on the two (§3.3).
- **A partial copy that is named like a finished one** will be opened by
  an engine and fail somewhere unhelpful. Temp name, then rename (§3.3).
- **`llama-server` rejects flags it used to take**, silently from the
  product's point of view until agent `d4454ee` (§6.1). Any new flag
  this slice wants is checked against `--help` for the installed build,
  not against a version number.
- **The acceptance script must clear the ambient environment**
  ([[project-acceptance-scripts-must-clear-the-environment]]) and must
  not run on the default ports on the box that also runs the live
  worker.
