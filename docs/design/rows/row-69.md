# Row 69: creators items 2, 4, 5 and 6

Lane LIB, after row 10. Low risk, except 69d (high: a public dataset).
Source: the YouTube-creators pass of 2026-10-18
(`docs/history/audience-roadmap.md`): (2) a benchmark matrix of models ×
quants × context depths × engines × machines, run unattended into one
table; (4) a shareable card with full provenance; (5) a presentation view
for recording; (6) an opt-in public dataset, which needs a privacy design.
Items 1 and 3 became row 10 (the served-people sweep), whose records feed
these. Troy put these at the back (2026-10-18).

## 69a. The benchmark matrix (M)

- A job (the agent's measurement job from row 10) that runs row 10's sweep
  (or a single-stream run, for speed only) over a chosen set: models and
  their quants from the Library, context depths (for example 1k, 8k, 32k),
  engines that accept them, and machines. Unattended: runtimes are started,
  measured and stopped one after another; the owner sees the plan, its
  estimated time and energy first (as row 55's batches do).
- One table at the end: rows per combination, columns tokens per second
  (prompt and output), time to first token, the knee, watts, with each
  record's provenance; exportable as CSV and Markdown.

## 69b. A shareable card (S)

A card per record or matrix row (an image and a self-contained HTML page)
with the model, quant, engine build, hardware, driver, the numbers, and a
provenance footer (row 10's `provenanceKey`), so a viewer can see what was
measured. Nothing personal: no prompts, no machine names unless the owner
keeps them.

## 69c. A presentation view (S)

A full-screen console view for recording: a running measurement or a chat
with large type, live tokens per second, GPU use and power, and no
chrome; the owner chooses what shows.

## 69d. An opt-in public dataset (M, high)

- **Only records, never content:** the same fields as the card (no
  prompts or answers; hardware and software identities only), each upload
  chosen by the owner, never automatic.
- **Where:** a Hugging Face dataset under the owner's own account (with
  their token), or a file they share themselves. No Eugene-run service
  collects anything ("no cloud service in the path"). Call R69-DATASET.
- **Privacy review:** what a record could reveal (GPU serials, hostnames,
  paths) is stripped and shown before upload.

## Repositories

agent (the matrix job), ui (matrix, card, presentation view, upload),
specs (record format, docs).

## Tests that fail before

The matrix plan for a set; the table from records; the card carries
provenance and no names; the upload strips identifiers.

## Size and risks

M-L in total, after row 10. 69d gets one adversarial review (what leaks).

**Calls:** R69-DATASET (records go to the owner's own Hugging Face
dataset, never to a service of ours).

## Calls answered by Troy (2026-10-22)

- **R69-DATASET: Choice 1 today, kept open for Choice 2.** Records go to
  the owner's own Hugging Face dataset or a file they share. The publish
  step takes a destination (a kind and its settings), so a shared Eugene
  dataset can be added later as one more kind without changing the record
  format.
