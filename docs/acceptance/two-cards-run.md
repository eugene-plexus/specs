# One model across two cards: the run

**2026-09-27. `scripts/two-cards-acceptance.sh`: 14 PASS live, zero
failures.** It was run again with the old largest-card rule put back, and failed
for exactly the original reason (§3). Sabotage passes: agent **16 of 16
caught**, library **7 of 7**, UI **5 of 5**.

Repos:

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `391420d` | the contract |
| `agent` | `2838674` | placement, admission, reservations, `splitMode`, the probe path |
| `library` | `b145075` | `gpuCount`, and an override's card count |
| `ui` | `7cfcb7f`, dist `b9fecb5` | the node budget and the launch preview |
| `control` | `e751afe` | regenerated only |

`gateway` and `inference-driver` regenerated a field description and a header
line only, and were reverted rather than re-pinned. Both installers pin the
rest.

---

## 0. What was wrong

The request (Troy): support a model too big for one card, spread across two.
His examples were a 5090 beside the integrated Radeon, and a user with two
5090s. This record is the second; the first is §5.

**llama.cpp already did it. The product refused it.** llama.cpp splits a
model's layers across every visible card by default (`--split-mode layer`), in
proportion to free memory. So two 5090s run a model neither card can hold
alone, entirely in GPU memory. Eugene got in the way in two places:

- **Admission** scored a launch against the *largest single card*. Its
  docstring said a model "that fits across two cards and on neither is
  `split`, not `fits`". `split` means spilling into system RAM, and a
  full-offload launch refuses it. The reasoning was wrong about what `split`
  means.
- **The UI and the library** did the same. The node budget was "the largest
  card, never the sum", because the library's fit override took one number and
  counted one compute-buffer allowance, so there was no honest way to describe
  two cards.

A related defect surfaced while reading the library: **an override kept the
library host's own card count.** On the live install the library is in a
container with no GPU and every launch goes to Amish_Station's 5090. The UI
passed 30 GiB as `vramBytes` with a `gpuCount` of 0. The starter set reads
`gpuCount` to decide whether a machine has a card at all, and so recommended
the smallest model, "on a machine with no graphics card", about a 5090.
Measured before the fix: `budget_from_hardware(nas, vram_override=30 GiB)`
returned `gpuCount 0`.

---

## 1. What each card needs

The same 27B Q6_K_L at a 16k context, loaded with `-fit off` so llama.cpp
sizes nothing itself:

| Loaded on | Compute buffers | KV | Recurrent state |
| --- | --- | --- | --- |
| the 5090 alone | 505 MiB | 1,024 MiB | 150 MiB |
| the 5090 + a second device (`--tensor-split 3,1`) | 226 + 609 MiB | 768 + 256 MiB | 118 + 31 MiB |

The KV cache and state divide across the devices. The compute buffers do not:
each device holds its own, plus its own driver context, which these buffers do
not include. So the library's 1 GiB allowance is now counted **once per card**
(`overhead_for`).

---

## 2. The change

**`place`** (agent) decides which cards a launch uses:

- **llama.cpp:** every card of the build's kind, unless the runtime is pinned
  (`CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES`) or `splitMode` is `none`.
- **vLLM:** `tensorParallelSize` × `pipelineParallelSize` cards, one by
  default.
- **Cards of one kind only.** On a Linux machine where both NVIDIA's and AMD's
  tools answer, the CUDA build uses the NVIDIA cards.

Each card's share follows `tensorSplit` when one is set: one proportion per
card, a missing one being zero, as llama.cpp reads it. Otherwise it follows
what the card has left, which is llama.cpp's own default. **The verdict is the
most the model can be while every card's share still fits in what that card
has left.** When the shares follow free memory that is the sum. A lopsided
`0.9,0.1` on two 30 GiB cards is bounded at 33 GiB, not 60.

**The reservation is divided by the same numbers**, card by card.
`Reservation.shares` holds each card's part, so a second launch while the
first loads is measured against what each card has actually promised.

A first version divided the promise by free memory alone. A test of two
cards, one already spoken for, caught it promising half of a new launch to the
card with no room.

Also:

- **Admission** gains `devices`; `freeBytes` and `totalBytes` are summed over
  them; `device` is the main card (`mainGpu`, else the first).
- **The library** takes `gpuCount` on its four fit routes and counts an
  allowance per card. An override's card count is the caller's: one when
  `vramBytes` is positive, zero when it is zero.
- **The UI** sums a node's cards of one kind and passes `gpuCount`. The picker
  reads "2 × NVIDIA GeForce RTX 5090 · … free of … between them", and the
  launch preview says "free across 2 cards".
- **`splitMode`** is a llama.cpp flag, with the four values llama-server b11211
  lists in its own help: layer, row, tensor (experimental), none.
- **`devices._run` runs the path `shutil.which` found.** This is R2.3's fix to
  `host._run`, which this copy never got. On Windows a bare name made
  CreateProcess run System32's `nvidia-smi` whatever `which` had found, so the
  device list and the engine picker could read two different programs.

Two agent tests and one UI test drove a default launch on two cards and
asserted the largest-card rule. They are **amended**, not added to: the agent
ones to `splitMode: none`, where one card is what the engine uses.

---

## 3. The live run

This box has one 5090. The script puts a stub `nvidia-smi.cmd` first on PATH
that reports this card twice, with its real free memory, total, compute
capability and driver, read from the real tool at the start of the run. R2.3
recorded that a `.cmd` could not shadow the real tool for the agent. It can
now, because of the probe-path fix above. The subject is the real 27B Q6_K_L
at 262,144 context.

| # | Check | Result |
| --- | --- | --- |
| 1 | one real card | refused, fitting up to 84,736 context, and about one card |
| 2 | two cards (the stub) | the agent reads two; **admitted**: "needs about 41.2 GiB at 262144 context (library metadata) and 2 cards (device 0 …, device 1 …) have 58.8 GiB free of 63.7 GiB between them; verdict fits". Devices 0,1; `freeBytes` is both cards' to the byte |
| 3 | `splitMode: none` on the same pair | refused |
| 4 | `CUDA_VISIBLE_DEVICES=1` | refused, on device 1 |
| 5 | the running library | a one-card override is one card, not the container's zero; `gpuCount=2` doubles the allowance |
| 6 | teardown | no owned port still listening |

**With the largest-card rule put back**, the same run failed four checks. The
reason was the original defect word for word: *"needs about 40.2 GiB … but
device 0 (NVIDIA GeForce RTX 5090) has 29.4 GiB free of 31.8 GiB; verdict
split … Set contextSize to 84992 or below"*. The requirement is 1 GiB lower
there because it counts one card's allowance.

---

## 4. Not proved, named

- **Two real cards.** The stub makes the product's arithmetic run against real
  processes and a real model. It does not make llama.cpp split across two real
  cards. That is upstream's default, and it was shown on this box across the
  5090 and the integrated Radeon with `--device CUDA0,Vulkan1`: layers and KV
  cache landed on both devices, and the answer was correct. Two NVIDIA cards
  (Troy's 3090 back beside the 5090) or a user's pair is the evidence owed.
- **Speed** of any split. Nothing here measures it.
- **vLLM tensor parallelism** is unit-tested only.
- **A single-card launch on a multi-card machine** keeps the old rule: it is
  measured against the card with the most room. That is right for a runtime
  pinned to one card. It is not what vLLM's default or `splitMode: none` does:
  those use the first visible card, or `mainGpu`, whether or not it has the
  most room. Recorded, not changed here.

---

## 5. The integrated GPU, and the other half of the request

Troy's first example, the 5090 plus the integrated Radeon, is a different
mechanism: two backends in one process. Measured the same day:

- The CUDA and Vulkan builds of one release share byte-identical
  `ggml-base.dll`, `ggml.dll`, `llama.dll` and `llama-server.exe`. Adding
  `ggml-vulkan.dll` to the CUDA build gives one process that lists CUDA0 (the
  5090), Vulkan0 (the 5090 again) and Vulkan1 (the Radeon).
- llama.cpp skips the duplicate by PCI id ("already using device CUDA0 with the
  same id"), and leaves the integrated GPU out while a card is present.
- `--device CUDA0,Vulkan1` splits one model across both.

Offloading 16 of a 27B's 66 layers was measured once, on this one rig:

| Where the 16 layers went | Prompt (tokens/s) | Generation (tokens/s) |
| --- | --- | --- |
| to the processor | 871 | 8.2 |
| to the integrated Radeon | 33 | 2.1 |

**This is one test on one rig, not a verdict (Troy).** It needs more testing to
find where integrated-GPU overflow helps. The merged build that would make it,
and a discrete second card of another vendor, possible from the product is the
next slice.
