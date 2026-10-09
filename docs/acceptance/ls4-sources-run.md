# LS4: catalogue sources are a list; engines publish what they support (2026-10-09)

Slice LS4 of [library-sources-and-engines.md](../design/library-sources-and-engines.md)
(§4.4; Troy's call on Discover's default and calls B30-B42 in §6.5). Contract
specs `b461ab6` + `4e8b4d1`; library `9ea692a`; agent `b88dd3a`; ui
`59fcacbe`. Pinned with this record (ui dist `aadccf2f`).

## The run of record

`scripts/ls4-sources-acceptance.py` on Amish_Station (Windows 11, Python
3.14, editable agent and library), **11 of 11**. A throwaway standalone agent
on free loopback ports supervises its own Library. Two fake hubs on loopback
stand for the public hub and a company's own hub; they answer only the hub
endpoints the Library calls, and record every request with its
`Authorization` header. The Library starts from a config file written before
LS4: `catalogueBaseUrl` (the first fake hub) and `hfToken`. Nothing runs but
the agent and its Library; one 2 KiB file is downloaded from the second hub.

| Check | What it proves |
| --- | --- |
| S1a | The old file's hub address and token become the first source (`huggingface`, kind `hf_hub`, the old address, `hasToken: true`, `token: null`), beside every engine's list; the token is nowhere in `GET /v1/config` |
| S2 | The real agent's `GET /v1/engines` publishes Strata's own list, uninstalled: upstream setup's nine choices in its menu order, each a named first shard at a 40-hex pinned revision; Strata's GGUF requirement names exactly those files; llama.cpp publishes none |
| S3 | A second hub saved through the agent's proxy as the console saves it, with its own token; both tokens stay hidden |
| S1b | The file keeps `catalogueBaseUrl` and `hfToken` beside the list, mirroring the first hub and sealed alike, for an older Library |
| S4a | One `POST /v1/catalogue/search`, the node's lists sent as the console sends them: Strata's nine first, then the first hub's two rows, then the second hub's one, each result naming its source; `sources` counts 2, 9, 1 |
| S4b | Each hub was asked with its own token and never the other's |
| S5 | The judge, through the proxy: every list entry is *after preparation* for Strata, not approximate; another publisher's Flash-Next repo is *after preparation*, approximate, as a search row (no file named), and *no* for Strata once its version's file is known ("runs only the 9 files on its own list, and FlashNext-UD-Q2_K_XL-00001-of-00002.gguf is not one") |
| S6 | A list entry opens its repo at the revision it pins, on the default hub (`/revision/<commit>` and `/tree/<commit>`), the second hub untouched; the version whose first file the entry names is Strata's, *after preparation* |
| S7 | A repo on the second hub is opened and downloaded from that hub with its token, the first hub never asked; the record names `source: corp`; the file lands whole (sha-256 checked by the Library) |
| S8 | The second hub stopped: the search still answers from the others, and `sources` says why that hub gave nothing ("Could not reach ...") |
| S9 | The second hub switched off through a round trip that never saw its token: not asked, said so; its token survives; an older console's `GET` search still answers from the first hub alone, with no `source` |

S8 first passed a dead hub on the instrument: the Library keeps a hub's
search for 60 s, so the same search answered from that cache. S8 now searches
anew (a query of its own).

`scripts/ls1-eligibility-acceptance.py` and `scripts/ls3-prepared-acceptance.py`
changed in the same push: their Flash-Next GGUF had a name Strata's setup
would refuse, so under B32 Strata answered *no* for it. They now use the name
Strata's setup gives IQ2_XS's first shard. LS1 11/11, LS2 11/11 and LS3 16/16
on the same working trees. All four run in specs CI against the pinned
components.

## Unit tests and sabotage

- library: `tests/test_catalogue_sources.py` (the old file migrates, sealed
  token and all, and keeps the old keys; the default list; nine malformed
  lists refused naming the entry; the old keys need a hub; which hub a call
  means; the POST search over two mocked hubs and a list: order, sources,
  facts, each hub's own token, one hub down, a hub switched off and its token
  through the round trip, the lists' query, format and engine filters, a node
  with no list said, a later page, an unknown source, a pasted link's host,
  the air-gap switch; the detail and a download ask the hub they name, the
  transfer included), `tests/test_eligibility.py` (the `files` term: on and
  off the list, case, a row with no file, a long list counted, a library
  model's path either separator), `tests/test_settings_truth.py` (an empty
  token through the old key; a round trip keeps the token, `""` clears it; a
  saved token reaches the hub's client and the download manager's), facts
  carry the file name for a hub version and a starter entry; the tests that
  injected one hub client now point every hub at the mock. Full suite 709
  passed, 25 skipped; ruff, mypy both platforms clean.
- agent: `tests/test_strata.py` (upstream setup's nine choices, each a named
  first shard at a pinned revision, needing preparation; Strata's GGUF
  requirement names exactly those files), `tests/test_engines.py` (the
  descriptor carries the adapter's list whether or not the engine is
  installed). Full suite 2,087 passed, 17 skipped; ruff, mypy both platforms
  clean.
- ui: `CatalogueSources.test.tsx` (a saved token says so and a rename sends
  none; forget sends `""`, typing sends it; on/off and whose list; add a hub
  or a list; remove; new ids), `page.test.tsx` (the POST names the node's
  lists; every row's source and a failed hub's sentence; an entry opens at its
  pinned revision with its card and the version marked; another hub's repo is
  opened and fetched from it; a 405 falls back to one hub and says so; Troy's
  default, *Everything* with Strata alone, a chosen filter remembered and the
  old stored default not), `eligibility.test.ts` (the lists sent; the
  default's rule). Two older tests moved off the replaced keys
  (`ConfigEditor`, `DownloadsPanel`). Full suite 1,788 passed; tsc, eslint,
  prettier clean.
- Sabotage of the changed code, `scripts/ls4-sabotage.py`, each restored from
  a copy: **42 of 42 caught** (library 25, agent 4, ui 13). The first pass
  found one not caught: a source naming one engine was only tested with that
  engine's list absent, which an earlier check answers; the test now sends
  two engines' lists, and catches it. Its first baseline also failed once: a
  Discover test clicked a red row that the new *Works here now* default hides
  once judged, so it passed only when the click won the race; it now chooses
  *Everything* first. `scripts/settings-sabotage.py` follows the token into
  `catalogue_sources.py`: 3 of 3 caught.

## Not covered

- The real hub. Strata's nine entries were read off upstream's setup at
  `6f32ec0` and checked against huggingface.co's file listings at the pinned
  revisions on 2026-10-09 (every first shard there, every one `qwen4exp`, the
  sizes summed from the listing); the run above uses fake hubs.
- Preparing from Discover: LS5. Downloading a list entry fetches its files;
  Strata's own setup still prepares them.
- The console in a browser: Discover's and the settings editor's behaviour is
  covered by their vitest suites, not by a browser run.
