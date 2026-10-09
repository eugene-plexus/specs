# LS3: prepared models are Library models (2026-10-09)

Slice LS3 of [library-sources-and-engines.md](../design/library-sources-and-engines.md)
(Troy's L6; calls B18-B29 in §6.4). Contract specs `7ad52c7`; library
`69b24e2` + `dd78972`; agent `4edc250` + `fc305ff`; ui `cf898591` +
`8249b785`. Pinned with this record (ui dist `b20bce9`).

## The run of record

`scripts/ls3-prepared-acceptance.py` on Amish_Station (Windows 11, Python
3.14, editable agent and library), **16 of 16**. A throwaway standalone agent
on free loopback ports supervises its own Library over a folder holding a fake
prepared Strata bundle: Strata's JSON configuration (relative `--pack`,
`--native`, tokenizer), a pack folder, a tokenizer and the GGUF it was made
from (a header only, architecture `qwen4exp`). Strata is a borrowed
installation (`strataServer`, set through `PATCH /v1/config` as Settings does)
whose `serve/server.py` is a stand-in: it takes the argv the adapter builds,
answers `/health` as Strata does and keeps the launch configuration it was
handed. Its `.venv` is a real empty venv; `engine/strata` is an empty file
nothing executes. No real Strata, no model, no GPU.

| Check | What it proves |
| --- | --- |
| A1 ×3 | *Add a prepared model* through the agent's proxy: the Library writes `qwen-flash.eugene-prepared.json` beside Strata's configuration with the entry relative and `formatVersion` 1, lists a `prepared` model at once (no size, entry found) linked to the GGUF it was made from, and refuses the same name twice |
| A2 ×2 | A full rescan keeps it and finds a provenance file written by hand (absolute entry on "another node": listed, entry not found here); one written by a newer Eugene is unreadable and says so |
| E1 ×2 | The real agent's Strata declares `prepared` (`preparedFor: strata`) and is available from its borrowed install; older consoles see `modelFormats: ["prepared"]`, never every GGUF |
| J1 ×2 | The Library judges the prepared model: Strata *runs* it, llama.cpp does not (its reason names `prepared`), the dot is green; the source GGUF stays *after preparation* for Strata |
| F1 | Fit is *not estimated* (422), never llama.cpp's arithmetic on a JSON file |
| R1 ×3 | Run, through the real agent's run worker: Strata chosen, a profile made on the prepared model for Strata, a runtime declared on the provenance file under the Library's name, and the stand-in reports ready |
| L1 ×2 | What Strata was handed: `--pack`, `--native` and the tokenizer as absolute paths beside the entry, `model_name` `qwen-flash`; Strata's own configuration byte-for-byte unchanged |
| N1 | A second prepared model whose configuration names a missing MTP file fails at Run naming it, and the stand-in is never started |

`scripts/ls1-eligibility-acceptance.py` changed in the same push: its E1
asserted Strata's pre-LS3 declaration (`modelFormats: []`, the GGUF
requirement first). Both run in specs CI against the pinned components.

## Unit tests and sabotage

- library: `tests/test_prepared.py` (the scan: listing, a missing relative
  entry, an entry on another node, five unreadable files, unknown fields,
  the source link, a provenance inside a safetensors folder; the judge:
  own engine only, `preparedFor` absent and named; the route: beside the
  entry and listed at once, an entry as given, five refusals that write
  nothing, fit 422), `tests/test_auth.py` (a service token cannot adopt).
  Full suite 676 passed, 25 skipped; ruff, mypy both platforms clean.
- agent: `tests/test_strata.py` (a Library model launches its entry under
  the Library's name, beside it or absolute; four provenance files that
  cannot launch say why; Strata declares `prepared`; admission reads the
  entry through the node's mapping and names a missing asset),
  `tests/test_run_worker.py` (422 falls back like 404), `test_engines.py`
  and `test_runtimes.py` updated to the new declaration. Full suite 2,082
  passed, 19 skipped; ruff, mypy both platforms, vendored check clean.
- ui: `AddPreparedModel.test.tsx` (only engines that load prepared models,
  the name from the file, the folder compared as Windows does, no engine
  here), `page.test.tsx` (a prepared row and page, no fit request; the form
  posts what the Library writes; 404 and 422 fall back to the format rule),
  `ExperimentalModels.test.tsx` (the form is gone, Switch stays),
  `ProfileEditor.test.tsx` (*add stopped* declares `autoStart: false`).
  Full suite 1,770 passed before *add stopped* was added; after it, that
  file and the Library page's, 47 passed; tsc, eslint, prettier clean.
- Sabotage of the changed code, each restored from a copy: 24 of 24 caught
  (library 11, agent 6, ui 6, acceptance 3 by the run above failing 2-4
  checks each). The first pass found one not caught: the 422 fallback on the
  Library page changed nothing its test looked at; the test now checks the
  format rule's *no engine* mark, and catches it.

## Not covered

- The real Strata with a real prepared model (LS5's validation; Troy's go
  needed for the ~68 GB download).
- A container root with a Windows worker, where the entry is a path only the
  worker sees (B19): the unit tests and A2's hand-written file cover the
  listing; the agent's mapping of a provenance path is covered by
  `test_admission_reads_the_entry_through_the_nodes_mapping`.
- A browser driving the new form: the console's tests render it and post
  through a stubbed proxy.
