# Row 49: which machine hosts a model

Lane LIB, after row 14 (placement by predicted time to first token).
Cross risk. Sources: M6-PLACE (the roadmap's "Design first, after row
14"), row 10's measured knee per runtime, row 14's prefill fit, the
Library's fit verdicts, LS10 (a node prepares and copies model files in
16 MiB chunks), row 43's card readout.

## 1. What it delivers

- **"Where should this run?"** When the owner starts a model from the
  Library on an install with several machines, Eugene recommends a
  machine, with the reason in one line: "garage-pc: fits in VRAM with
  32,768 context, measured 41 tokens/s, model already there" against
  "nas: needs 6 GB in RAM, about 9 tokens/s". The owner picks; the
  recommendation is the default choice (easy default, expert override).
- **"Run it where it fits"** as a profile setting: the agent of the
  recommended machine starts it, and if that machine is busy or down at
  start, the next best one does.
- **Spread replicas:** asking for two replicas places them on two
  machines, never two on one machine unless asked.

## 2. Design

- **The score per machine,** computed by the root from what each machine
  reports (no new measurements):
  1. Fit: the Library's verdict for that machine's free memory (fits,
     tight, split, no). "No" machines are listed with why, never chosen.
  2. Speed: row 10's measured knee speed for this model on that machine
     if recorded; else row 14's prediction; else unknown (shown as
     unknown, ranked after measured ones).
  3. Load: runtimes already there and their measured use.
  4. Copy: whether the model file is already on that machine (a Library
     folder it mounts, or a copy); else the copy time at the link speed
     (LS10's chunks) is added to "time to first answer".
  5. Health: row 43's warnings (a narrow link, throttling) lower the score
     and are named.
- **Where:** `POST /v1/models/{id}/placement` on the root (control asks
  each agent for its fit and readout, the library for the verdicts);
  returns the ranked machines with each reason. The console's start dialog
  shows the first three.
- **Run it where it fits:** a runtime spec field `placement: auto`
  declares the runtime on the root, which chooses the machine at each
  start and records the choice on the runtime ("placed on garage-pc,
  20:14, because …").

## 3. Repositories

control (placement route, the auto runtime's start), agent (fit and
readout reports it already serves), library (verdicts), ui (start dialog),
specs (`control.yaml`, `agent.yaml`).

## 4. Tests that fail before

- control `test_placement.py::test_a_machine_that_cannot_fit_is_listed_not_chosen`,
  `test_a_measured_machine_ranks_above_an_unknown`,
  `test_two_replicas_go_to_two_machines`.
- control `test_placement.py::test_auto_falls_to_the_next_machine_when_the_first_is_down`.

## 5. Acceptance (CI, Linux, about 4 minutes)

Three agents on row 2's harness with fixture devices of different sizes:
the recommendation ranks them by fit and names why; `placement: auto`
starts on the best and, with it stopped, on the next.

## 6. Size and risks

L, about 3 days, after row 14. Risks: a recommendation built on stale
numbers (each reason says when its number was measured); auto placement
moving a model the owner wanted elsewhere (it is a setting, off by
default, and the runtime says where and why).

**Calls:** none.
