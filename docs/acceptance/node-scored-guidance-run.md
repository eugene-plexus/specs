# Guidance is scored against the node you launch from — live run

**2026-09-12. Verified against the live two-machine install.** Contract
`550da7e`; `ui` `89ae40b` (dist `f528dea`). The library did not move:
its models were regenerated at `550da7e` and came back byte-identical.

Reported by the operator, from the worker node:

> when I am on the Amish node and go to Discover, it says no GPU
> detected. Back in early testing when we were a single PC install, it
> did detect the GPU.

Both halves of that are true, and the second is the explanation.

## It was telling the truth about the wrong machine

The library scores a model against the host **it** runs on. Its own
`/v1/hardware` description says so and names the limitation: *"in a
multi-host deployment the GPU that will load the model may be somewhere
else entirely."* On this install the library runs in a container on the
NAS:

```
GET /api/proxy/library/v1/hardware      (through the worker's proxy)
{"hostname":"734bbaf1cd8f","gpus":[],"ramAvailableBytes":73691791360,
 "warnings":["no accelerator was detected … its vendor tool (nvidia-smi,
  rocm-smi, xpu-smi) is not on this process's PATH …"]}
```

No GPU, correctly. And the warning's guess — a vendor tool missing from
PATH — is wrong for a container that genuinely has no GPU, which is the
first thing an operator would have chased.

Meanwhile the worker's own agent knew exactly what it had:

```
GET /v1/node        (the worker)
"devices":[{"kind":"cuda","name":"NVIDIA GeForce RTX 5090",
            "memoryTotalBytes":34190917632,"memoryFreeBytes":32446087168},
           {"kind":"cpu",…,"memoryFreeBytes":75783077888}]
```

In the single-PC install the library and the GPU shared a host, so the
reading happened to be about the right machine. It stopped being right
the moment the install spanned two.

## Two halves were built and never joined

**M3** built the override half: `vramBytes` and `ramBytes` on the fit
surface, *"how a caller who knows the target host's numbers can score
against them"*, and deferred the inventory: *"building a cross-host
hardware inventory is not M3's job and probably belongs to the agent's
topology when it is."*

**M7** built that inventory — `ComputeDevice` on the agent's
`GET /v1/node`, aggregated into `Node.devices` at the control root.

No caller ever passed the override. Discover, the Library fit panel and
every catalogue call scored against whatever host the library was on.
Before the cross-node proxy existed the worker could not reach the
library at all, so the line was simply blank; the day it could, the
answer became honest and useless.

## THE MEASUREMENT: the recommendation was wrong, expensively

`unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` at 8192 tokens, through the
worker's proxy, before and after:

| quant | size | scored against the NAS (library host) | scored against Amish_Station (5090) |
| --- | --- | --- | --- |
| UD-TQ1_0 … UD-Q6_K_XL (24 quants) | 7.5–24.5 GiB | fits | fits |
| Q8_0 | 30.3 GiB | fits | **partial offload** |
| UD-Q8_K_XL | 33.5 GiB | fits | **partial offload** |
| BF16 | 56.9 GiB | fits | **partial offload** |
| **recommended** | | **BF16** | **UD-Q6_K_XL** |

With no accelerator the library takes its CPU branch — *"everything
runs on the CPU, so there is no fits-in-VRAM to report"* — and 70 GiB of
host RAM holds all of it. So the NAS budget recommended **a 57 GB
download for CPU inference** to a machine with a 32 GB card in it. The
override answer recommends the largest quant the card actually holds.
`budget.source` reads `override` on every candidate, which is the field
a screen uses to say which machine a verdict is about.

## What was built, and three choices in it

`ui/src/lib/nodeBudget.ts` reads the local agent's `GET /v1/node` and
turns its device list into the two override parameters. Discover passes
them on `/v1/catalogue/model` and `/v1/catalogue/model/preflight`; the
Library fit panel passes them on `/v1/models/{id}/fit`. The hardware
line now names the node and the card; when the library's own reading is
the one in use (the agent reported no devices), it names the library's
host instead, and the library's warnings are shown only in that case.

**Which node: the one you are browsing.** Launch posts to the local
agent, so the browser's machine is the machine the model will run on.
Scoring against any other node would recommend a quant for a card the
launch never reaches. A picker — score here, launch there — belongs to
the install-wide inference screen that is still a design question, not
to a helper's default.

**The largest card, never the sum.** The library collapses free, total
and largest-card into one number under an override, so the sum of two
cards would report `fits` for a model neither card holds alone. The
cost is that the library's multi-GPU note cannot appear, because
`gpuCount` is not a parameter a caller can pass.

**No devices is null, not zero.** A host whose detection failed keeps
the library's reading; a fabricated zero would score every model as
CPU-only. A CPU-only host with a device list *is* a zero, which the
library already scores against host memory.

Nine unit tests on the derivation, three sabotage-checked: the sum
instead of the largest card, a zero budget for a host with no devices,
and `ramBytes` dropped from the query each turned their test red.

## The contract gap, and its radius

`/v1/catalogue/model` and `/preflight` had accepted both parameters
since M3 — the implementation's `Query(...)` declarations are there,
with descriptions — while the contract listed them on `/fit` alone.
Documented at `550da7e`, when the first caller appeared.

Radius measured by regenerating, not by reading the diff: the library's
`models.py` came back **byte-identical** (query parameters generate no
Pydantic models), so it is not re-pinned; the `ui`'s `library.ts` gained
the two parameter types on both operations, so it is.

## What this run does not cover

- ~~**The root's own console.**~~ **Closed the same day** by the node
  picker on Discover and Library (`ui` `f2b65c6`): one choice for both
  whose memory a verdict is about and where Launch goes. See
  `inference-screen-run.md`.
- **Apple silicon.** `unifiedMemory` still comes from the library's
  host and cannot be overridden, so a Mac worker scored by a Linux
  library is read as a discrete GPU with that much memory: right on the
  fits/no line, wrong about `split`, which does not exist on one pool.
  The budget flags it and Discover says so; the fix is a third override
  parameter, not taken here.
- **No browser drove it.** Every call the two screens make was
  exercised over HTTP with the exact parameters the code sends; the
  rendered line was not read from a browser.
- **The library's warning text** still blames a missing vendor tool on
  a host that has no GPU at all. Unchanged, and no longer shown on a
  node that has its own reading.
