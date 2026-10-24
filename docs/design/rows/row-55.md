# Row 55: batch jobs in idle time

Lane GW, after rows 11 (one fair queue, with bands) and 53 (the `store`
component, with Files). Cross risk. Sources: LD7 (`llm-d-lessons.md`: "Batch as
background-band traffic … never competes with chat … The job shows its
estimated time and tokens before it starts, because electricity is a real
cost for this audience"), row 11's `background` band, row 10's measured
knee (the speed a runtime holds), OpenAI's Batch API.

## 1. What it delivers

- **OpenAI's Batch API:** upload a JSONL file of requests (`/v1/files`,
  `purpose: batch`), `POST /v1/batches`, poll it, download the results
  file. Apps and scripts written for OpenAI batches work unchanged.
- **Batches use the machine's idle time.** Every batch request enters row
  11's queue in the `background` band, so a person chatting is always
  served first and a batch never slows them.
- **A cost before it runs.** The console's Batches page (and the batch
  object's `metadata`) shows the estimated tokens and time before work
  starts: "About 4.2 million tokens, about 6 hours on qwen3-32b at the
  measured 190 tokens/s." The owner can hold batches for a window
  ("only between 23:00 and 07:00").

## 2. Design

### The job (store)

- `POST /v1/batches` (`input_file_id`, `endpoint`:
  `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`,
  `completion_window: 24h`) creates a batch owned as row 53 says. States
  follow OpenAI: `validating`, `in_progress`, `finalizing`, `completed`,
  `failed`, `expired`, `cancelling`, `cancelled`.
- **Validation** reads the input file: each line's `custom_id`, `method`,
  `url` matching `endpoint`, and a body the door would accept (the
  gateway's own validation, called per line). A bad line fails the batch
  with OpenAI's `errors` list.
- **The estimate:** prompt tokens counted per line with the gateway's
  `count_tokens`, output from each line's `max_tokens` (or the model's
  default), time from row 10's latest measurement for the target model's
  runtime (its knee speed), or "unknown" without one. Stored on the batch
  and shown before it starts.
- **Running:** the store sends each line to the gateway with the
  owner's identity (as a service with the owner, row 53's header) and
  `queueBand: background`, a few at a time (the runtime's measured knee,
  or 4 without one). Results and errors are written to output and error
  files (`purpose: batch_output`) owned by the batch's owner.
- **The 24-hour window** is OpenAI's: lines not done by then are marked
  `expired` and the batch ends with what it has.
- **Hold windows:** the owner's setting `batchHours` (default: any time);
  outside them a batch waits in `in_progress` with "waiting for
  23:00".
- **Cancel:** stops sending; in-flight lines finish; state `cancelled`.

### The gateway

- Routes `/v1/batches` to the store (as row 53 routes Files).
- Accepts `queueBand: background` only from the store's component token (its per-node key)
  (a client cannot claim another band; row 11's rule).
- Anthropic's `/v1/messages/batches` maps to the same jobs
  (`requests` inline instead of a file), in this row.

### Console

A Batches page under Activity: each batch, its owner (people see only
their own), the estimate, progress, and Cancel. The owner sees counts per
person, never contents (row 53's rule).

## 3. Repositories

store (jobs, the runner, estimates), gateway (routing, the band
from the store's token, Anthropic's batch door), ui (Batches page), specs
(contracts: `gateway.yaml` batch paths, `store.yaml` the job).

## 4. Tests that fail before

- store `test_batches.py::test_a_bad_line_fails_validation_with_its_index`.
- store `test_batches.py::test_the_estimate_uses_the_measured_speed`
  and `test_unknown_without_a_measurement`.
- store `test_batches.py::test_lines_run_in_the_background_band`.
- gateway `test_batches_door.py::test_a_client_cannot_claim_the_background_band`.
- store `test_batches.py::test_hold_window_waits_with_the_reason`.

## 5. Acceptance (CI, Linux, about 4 minutes)

`specs/scripts/row55-batches-acceptance.py` on row 2's harness with the
store and the fixture backend limited to one slot:
1. A 200-line batch runs; meanwhile a person's chat request is served
   before the batch's next line (queue order), and its wait is under the
   fixture's one-request time.
2. The output file has 200 lines with matching `custom_id`s; the estimate
   was shown before `in_progress`.
3. Cancel a second batch midway: it ends `cancelled` with the lines done.
4. Another person cannot see or download either batch's files.

## 6. Do not change

Row 11's queue (call it with the band); row 53's ownership (call it).

## 7. Size and risks

M, about 2 days. Risks:
- **A big batch fills a disk:** the owner's quota (row 53) counts output
  files; over quota, the batch fails naming it.
- **Estimates can mislead:** each says its source (measured speed or
  unknown) beside the number.

**Calls:** none.
