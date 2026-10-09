# LS2: Discover shows which engines can run what, before download (2026-10-09)

Slice LS2 of [library-sources-and-engines.md](../design/library-sources-and-engines.md)
(calls B8-B17 in §6.3). Contract specs `d63de19` and `21448e8`; library
`6f38b85` + `eb6b553`; agent `8f7a682` + `80996c9`; ui `7e689d45` +
`e79709e9`. Pinned with this record (ui dist `207d7c5`).

## The run of record

`scripts/ls2-discover-acceptance.py` on Amish_Station (Windows 11, Python
3.14, editable agent and library), **11 of 11**. A throwaway standalone agent
on free loopback ports supervises its own Library, whose catalogue address is
a fake hub on loopback (never huggingface.co). The engine root holds a
stand-in llama.cpp build `b1` (a receipt and an empty file, never started)
with its own architecture list already kept: every shipped name except
`qwen4exp`. Nothing is downloaded or started.

| Check | What it proves |
| --- | --- |
| D1 | The installed llama.cpp declares its build's own list on `/v1/engines`, not the shipped one, with no *may run* beside it |
| D2 ×2 | A search through the agent's proxy asks the hub for its GGUF block (`expand[]`, every field a row shows); every row carries approximate facts: the GGUF architecture from the hub, the MLX marker from tags |
| D3 ×3 | The Library judges every row through the proxy; a llama GGUF works here on the installed build (marked approximate); a Flash-Next GGUF is refused by this build naming `qwen4exp`, Strata would prepare it, and the level follows whether Strata can be had here |
| D4 ×2 | An MLX folder's detail reads its remote `config.json` once, ranged; MLX runs it and vLLM says why not, with nothing downloaded |
| D5 ×2 | A plain folder: vLLM *may run* it in its own words, nothing assumed; its `tokenizer.model` comes with the download (§7) |
| D6 | Every starter entry carries facts, and the installed build runs each |

`scripts/ls1-eligibility-acceptance.py` on the same code, **11 of 11**: its E3
now submits Run with `node: null`, as the console does on an unjoined agent,
so it is the real-environment check of the library#7 fix (the run is claimed
and reaches *install llama.cpp?*).

## Unit tests and sabotage

- library: `tests/test_eligibility.py` (candidates: assumed facts, counted
  lists, the MLX marker, the route's order), `tests/test_catalogue_facts.py`
  (search fields, the ranged `config.json` read, facts on rows, versions and
  starters, folder ownership, `tokenizer.model`), `test_run_operations.py`
  (library#7). Full suite 654 passed, 25 skipped; ruff, mypy both platforms,
  vendored check clean.
- agent: `tests/test_llama_architectures.py` (parse, tags, the kept list read
  once, retry backoff, a page that is not the list, the adapter's two
  declarations, `/v1/engines` wiring). Full suite 2,075 passed; ruff, mypy
  both platforms, vendored check clean.
- ui: `app/discover/page.test.tsx` (order, both filters, the hub format, the
  empty filter, a version's popover, an older Library),
  `StarterSetPanel.test.tsx`, `lib/eligibility.test.ts`. Full suite 1,762
  passed; tsc, eslint, prettier clean.
- **Sabotage, changed code only: 33 of 33 caught** (library 17, agent 8, ui 8),
  each restored from a copy and checked by hash.

## Found by this slice

- Upstream llama.cpp (b11530) names `qwen4exp`: llama.cpp loads
  Qwen3.8-Flash-Next GGUFs itself.
- library#8 (a Kev repo through Discover does not scan) and agent#10 (a
  node's model copy takes one file of a split GGUF), both from §7.

## Not covered

- The browser page itself (the console's unit tests drive the page; D2-D6
  cover the requests it sends, through the same proxy).
- The real hub: its search fields and `config.json` ranges were measured by
  hand on 2026-10-09 (§6.3); the run uses a fake hub shaped like them.
- A live background read of a build's `llama-arch.cpp` from GitHub (unit
  tests stand in for GitHub; the run uses a kept list).
