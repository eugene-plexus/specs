# Row 43: hardware health readout, and restarting on the cards that are left

Lane LIB, after row 16. Sources: the setups pass's hardware readout
(`docs/history/audience-roadmap.md`: "PCIe generation and width against the
maximum, P2P, temperature, power cap"), DI6 in `deepinfer-lessons.md`
("Restart on the cards that are left"), agent `engines/devices.py`,
`host_probes.py`, `admission.py`, `runtimes.py`, `supervisor.py`.

## 1. What it delivers

- **Each machine's page shows its cards' health.** Per card: the PCIe link
  it runs at against what it supports ("Gen 4 x4; supports Gen 4 x16"),
  which cards can talk directly (P2P), temperature, the power cap against
  the card's default, why it is slowing down (heat, power cap), and
  uncorrected memory errors. A card on a narrow link, or one that
  throttles, is a warning on Home that says what it costs and what to
  check.
- **A runtime starts on the cards that are left.** When a card a runtime
  used has dropped off the bus (common on riser rigs), the runtime starts
  on the cards present, with what fits (a smaller context, or more of the
  model in RAM), and says which card is missing and what changed. The
  profile is not changed: when the card is back, the next start uses it.
- **Cards keep their identity.** Today a card is only an index, and when
  one drops the others renumber, so a pin to card 1 can land on another
  card. The agent now records each card's UUID and launches by it.

## 2. Design

### The readout (`components/common.yaml`, `ComputeDevice`)

New optional fields, each null when the platform cannot read it (never a
guess):

| Field | Source (NVIDIA: NVML, already loaded by `host_probes.py`) | AMD on Linux |
|---|---|---|
| `uuid` | `nvmlDeviceGetUUID` | `unique_id` in sysfs |
| `pciBusId` | `nvmlDeviceGetPciInfo` | the sysfs device path |
| `pcieLink` {`generation`, `width`, `maxGeneration`, `maxWidth`} | `nvmlDeviceGetCurrPcieLinkGeneration/Width`, `...MaxPcieLink...` | `current_link_speed/width`, `max_link_speed/width` |
| `powerLimitWatts`, `powerDefaultLimitWatts` | `nvmlDeviceGetEnforcedPowerLimit`, `...PowerManagementDefaultLimit` | hwmon `power1_cap`, `power1_cap_default` |
| `throttleReasons` (list: `thermal`, `power-cap`, `hardware-slowdown`, `other`) | `nvmlDeviceGetCurrentClocksThrottleReasons` | null |
| `uncorrectedMemoryErrors` | `nvmlDeviceGetTotalEccErrors` (volatile, uncorrected) where ECC is on | null |
| `peers` (UUIDs this card reaches by P2P) | `nvmlDeviceGetP2PStatus` (read) | null |

Read every 600 s with the device list (`host_probes.py`), and on each
`GET /v1/node`. Windows non-NVIDIA cards: nulls, as today for temperature.

**PCIe generation drops when a card idles** (power saving), so a lower
generation is a warning only while the card is busy (utilisation over 50%
in the last minute of host history). A narrower width is a warning at any
time.

### Console

- **The machine's page** gains a Hardware section: one block per card with
  the fields above, the temperature and power from host history, and
  "Can reach directly: RTX 3090 #1" for P2P.
- **New issue kinds** (`lib/issues.ts`, warnings):
  - `gpu-link-narrow`: "RTX 3090 #2 runs at PCIe x4; it supports x16.
    Loading models onto it takes longer, and splitting a model across
    cards is slower. Check its slot or riser."
  - `gpu-throttling`: "RTX 4090 is slowing down: power cap (300 W of
    450 W)." / "…: too hot (87 °C)."
  - `gpu-memory-errors`: "A100 #0 reported 3 uncorrected memory errors
    since it started. Answers on it may be wrong; restart the machine, and
    replace the card if it keeps happening."
  - `runtime-on-fewer-cards` (below).

### Starting on the cards that are left (DI6)

- **What a runtime used.** At each successful start the agent records the
  UUIDs of the cards the runtime ran on (`lastDevices`, in the runtime
  record; an observation, not a setting).
- **The check** runs before every start: create, start, boot start, a
  crash respawn and restart (today fit runs only on create and start). It
  compares the cards the profile pins (by `CUDA_VISIBLE_DEVICES`,
  `devices`, `mainGpu`, `tensorSplit`), or else `lastDevices`, with the
  cards present, by UUID.
- **All present:** launch as today, except that the agent rewrites index
  pins to UUIDs (`CUDA_VISIBLE_DEVICES=GPU-…`), so renumbering cannot move
  a runtime onto another card.
- **One or more missing**, with the profile's "If a card is missing"
  setting at its default, **Start on the cards left**:
  - The agent builds a launch override, never saved: the missing cards
    leave `--device`, `CUDA_VISIBLE_DEVICES` and `tensorSplit` (the split
    renormalised over the cards left), and `mainGpu` moves to the largest
    card left if it was the missing one.
  - It asks the library's fit (`GET /v1/models/{id}/fit`) for the cards
    left. `fits`: start. `tight` or `split`: start with the library's
    suggested context or RAM offload, as admission does for a new
    runtime. `no`: do not start, and say so with the numbers.
  - **vLLM:** tensor parallelism must divide the model's heads; the agent
    uses the largest valid size not above the cards left, or does not
    start, naming the sizes it tried.
  - The runtime's state says it: "Started on 3 of 4 cards: RTX 3090
    (was #2) is missing. Context 32,768 → 16,384." Home shows the warning
    `runtime-on-fewer-cards` until the runtime next starts with every card.
- **The other choice, Do not start:** the start fails with "RTX 3090 (was
  #2) is missing; this runtime is set not to start without it."
- **When the card is back,** the next start uses the profile unchanged and
  the warning clears. The agent does not restart a running runtime to win
  the card back; the person restarts it (a button on the warning).

### Contract (`agent.yaml`)

- `Runtime` gains `lastDevices` (UUIDs) and `startedOnFewerCards`
  (nullable: `missing` [{uuid, name, lastIndex}], `changes` [one sentence
  each]).
- The profile setting is the llama.cpp and vLLM adapters' new field
  `missingCard` (`start-on-cards-left` default, `do-not-start`), in the
  engines' GUI schema with the other launch fields.

## 3. Repositories and files

specs (`components/common.yaml`, `agent.yaml`), agent (`engines/devices.py`,
`host_probes.py`, `admission.py`, `runtimes.py`, `supervisor.py` respawn
path, `engines/llama_cpp.py`, `engines/vllm.py`), ui (the machine page,
`lib/issues.ts`, `lib/hostHistory.ts` for power in the fleet row). Library:
no change (its fit already takes the budget it is given). Regenerate agent,
ui and library (library reads `common.yaml`) and diff.

## 4. Tests that fail before

- agent `tests/test_devices.py::test_nvml_readout_fills_link_power_and_uuid`
  (a fake NVML) and `test_unreadable_fields_are_null`.
- agent `tests/test_admission.py::test_a_missing_pinned_card_refits_on_the_cards_left`
  (today: admitted against every card, and the engine fails at spawn).
- agent `tests/test_runtimes.py::test_index_pins_launch_by_uuid` and
  `test_a_crash_respawn_runs_the_card_check`.
- agent `tests/test_vllm.py::test_tensor_parallel_drops_to_a_valid_size`.
- ui `issues.test.ts`: `gpu-link-narrow` only under load for a lower
  generation; `runtime-on-fewer-cards`.

## 5. Acceptance (CI, Linux, about 2 minutes)

`specs/scripts/row43-cards-left-acceptance.py`: a real agent with a stub
`nvidia-smi` and stub NVML library on the search path (two cards, then one)
and the fixture engine that records its argv and environment.
1. Two cards: `/v1/node` carries UUIDs and the readout; a runtime pinned to
   card 1 launches with `CUDA_VISIBLE_DEVICES=GPU-<uuid of card 1>`.
2. Card 0 is removed and the others renumber: the runtime starts on the
   card left, by its UUID, with the refit context, and its state names the
   missing card.
3. The profile is byte-identical before and after.
4. The card returns: the next restart uses the profile and the warning
   clears.

A real multi-card box is not available here; the run on one is not on the
roadmap (Troy, 2026-10-21).

## 6. Do not change

- agent `engines/strata*.py` (row 63) and the Strata `--pcie-frac` flag.
- library `fit.py` (call it; do not change its rules).
- ui `app/hosts/page.tsx` beyond the power column (row 38 owns dashboards).

## 7. Size and risks

M, about 2 days. Low-cross (no review required; the orchestrator reads the
argv rewrite closely). Risks:
- **Launching by UUID changes every NVIDIA launch.** CUDA accepts
  `GPU-<uuid>` in `CUDA_VISIBLE_DEVICES`; the acceptance proves the argv,
  and the change falls back to index pins when no UUID was read.
- **An automatic refit can surprise.** The runtime's state and a Home
  warning say what changed, and "Do not start" is one setting away.
