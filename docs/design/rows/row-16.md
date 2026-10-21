# Row 16: Apple unified memory in fit

Lane LIB. Low risk. Size S. The change is in the library, plus new field descriptions and one console line.

## 1. What it delivers

- **Memory in use counts.** A Mac's fit verdict counts the memory other programs hold. A model that fits macOS's GPU limit but not what is free now reads `tight`, not `fits`.
- **The GPU limit is a hard limit.** A model larger than macOS's GPU limit reads `no`, not `tight`. Closing programs does not raise the limit.
- **The budget line names both numbers:** "29.6 GiB free of the 42.7 GiB macOS lets the GPU use, on this 64 GiB Mac".
- **Every unified-memory budget follows the same rules,** including an integrated GPU and a GB10, on this host or another.
- **Max context and the starter recommendation follow,** because they read the same budget.

## 2. The design

**What is wrong today.**

- On a unified budget, `vramFreeBytes` is Metal's working-set limit. The console sends the Metal device's `memoryTotalBytes`, because the agent reports no free figure.
- So `fits` ignores the RAM other programs hold, and `tight` reaches the whole of RAM. The cause is the test `required <= ramTotalBytes`.
- The memory note "no override" is out of date. `unifiedMemory` has been passed since 2026-09-27.

**Changes.**

**1. The budget** (`fit.budget_from_hardware`, `engine_fit.budget_of`), when the budget is unified:

- `vramTotalBytes` is the GPU limit.
- `vramFreeBytes` is the smaller of the limit and `ramAvailableBytes`.
- When RAM available is unknown, `vramFreeBytes` is the limit, and a note says "what other programs hold was not known".

**2. The verdict** (`fit._verdict`, unified branch):

- `fits` when the model's required memory is no more than free memory.
- `tight` when it is no more than the GPU limit.
- `no` otherwise.

The test against `ramTotalBytes` is removed.

**3. The notes and words** (`fit.compute` notes and `engine_fit._spill_words`):

- On Apple, the note names the limit: "macOS lets the GPU use {limit} of this Mac's {RAM}".
- tight: "fits once other programs close: {need}, {free} of {limit} free now".
- no: "too large: {need}, more than the {limit} macOS lets the GPU use".

**4. Hardware detection** (`hardware.py`): no change. Apple gives no free figure for the GPU. The two-thirds fallback stays, with its warning; the agent uses the same figure.

**5. The contract** (`library.yaml`): the `MemoryBudget` field descriptions say what each field means on a unified budget. Only descriptions change, so nothing is regenerated.

**6. The console** (`FitBadge.tsx` `BudgetLine`): "measured against {free} free of the {total} the GPU may use, memory it shares with the rest of the machine".

**Failures, each named.**

- RAM available unknown: the verdict is scored against the limit, and the note says so.
- Metal not reachable: the limit is two thirds of RAM, with the existing warning.
- Both unknown: `unknown`.

**Defaults:** none change. Nothing is deleted or exposed.

## 3. Repositories and files

| Repo | Files |
|---|---|
| library | `fit.py`, `engine_fit.py`, tests (`hardware.py` unchanged) |
| specs | `openapi/library.yaml`, descriptions only |
| ui | `src/components/FitBadge.tsx`, its test |

No codegen.

## 4. Tests that fail before the change

- **`library/tests/test_fit.py::test_unified_counts_memory_in_use`**
  - Budget: `vramBytes` 42.7 GiB, `ramBytes` 25 GiB, unified. Required: 35 GiB.
  - Expect `tight`. Today it is `fits`.
- **`test_unified_beyond_gpu_limit_is_no`**
  - Required: 50 GiB, against 64 GiB of RAM.
  - Expect `no`. Today it is `tight`.

## 6. Do not change

- **`agent/src/eugene_plexus_agent/admission.py`** (row 9, ENG).
  - On a Mac, admission still answers `unknown`, because it sends no RAM figure.
  - Sending RAM available is a follow-up for that lane.
- **`library/src/eugene_plexus_library/scanner.py`** (row 17).
- **`formats/gguf.py`** and **`preflight.py`** (rows 18 and 68).
- **`fit.py`** is also row 43's. That row is in the same lane and comes later, so it rebases.

## 7. Size, risks, open questions

- **Size:** S.
- **Risk:** a Mac that read `fits` by luck now reads `tight`, and that is the honest verdict.
- **Unproven on a physical Mac:** the tests use A4's measured numbers.
- **Question:** should a `no` name `iogpu.wired_limit_mb`?
  - Recommendation: no. That is a terminal step.
  - The limit is read live, so a raised limit shows up anyway.
