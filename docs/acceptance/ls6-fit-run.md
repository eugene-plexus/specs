# LS6: each engine owns its fit model (2026-10-09)

Slice LS6 of [library-sources-and-engines.md](../design/library-sources-and-engines.md)
(§4.3 *Fit names its engine*, §6.1, Troy's L11; calls B58-B69 in §6.7).
Contract specs `6548eb2`; library `4e2a906`, agent `1e0541a`, ui `d4aba23f`
(dist `6521e8d3`), pinned with this record.

## The run of record

`scripts/ls6-fit-acceptance.py` on Amish_Station (Windows 11, Python 3.14,
editable agent and library; an RTX 5090 of 31.8 GiB and 93.6 GiB of RAM, so
Strata's table has a card to apply to), **17 of 17**. A throwaway standalone
agent on free loopback ports supervises its own Library over five fixture
models, headers only: a llama GGUF, a Qwen3.8-Flash-Next GGUF by the name
Strata's setup gives IQ2_XS's first shard, an MLX-quantized folder, a plain
one, and a prepared Strata model made from IQ2_XS (`Strata-data`, as LS5
writes it). No engine is installed and nothing starts.

| Check | What it proves |
| --- | --- |
| F1a | The real agent's `GET /v1/engines`: llama.cpp declares `spill`; vLLM `reserved_share` at 0.92, vLLM's own default on upstream main |
| F1b | MLX and Kev declare no fit model |
| F1c | Strata declares `engine_table` with a row for each of the nine files on its list |
| F1d | IQ2_XS's row on this node is setup's answer: *fits* (it needs 48 GB of RAM and a card Strata can use; the node has both) |
| F2a | The judge, asked with the node's memory through the agent's proxy, answers llama.cpp's own fit from the model's metadata: `fits`, model `spill` |
| F2b | Strata's fit for its GGUF is its own table's row for that file, word for word |
| F2c | A prepared model is found in the table by the file it was made from (`source.file`) |
| F2d | MLX's fit is *not estimated*: no verdict, no bytes, never llama.cpp's number |
| F2e | vLLM's fit is its share's: `reserved_share`, `fits`, a share of 92% of 24 GiB |
| F2f | A model that fits no engine that would run it is red (`not_here`), llama.cpp's own `no` deciding |
| F2g | Without the fit question nothing changes: no fit on any verdict, the same level |
| F3a | `GET /fit` by a share-taking engine's model: `fits` on an idle 24 GiB card, `tight` with 10 GiB free (vLLM does not start with less than its share free) |
| F3b | No share, or an engine's own table: 422 *Fit not estimated* |
| F4a | Admission (the real agent's dry run): MLX admitted on faith, *no memory estimate*, never measured by another engine's arithmetic |
| F4b | Kev the same |
| F4c | Strata measured by its setup's table: basis `engine_table`, fit `fits` here |
| F4d | vLLM measured by its share at its own `maxModelLen`: the reason names the share of the cards' total memory |

On a node without a card Strata can use (CI's runners), F1d and F4c expect
`unknown` and F4d is skipped: admission measures nothing without an
accelerator.

### What the run found

The first runs failed on the instrument (a split GGUF is listed without its
shard suffix; the agent writes explicit nulls; a cp1252 console), and on the
product once: admission refused a vLLM spec carrying `contextSize`
(`unknown flag(s) for vllm`). That is how a Run's profile has always given an
engine its context, so a Run of a vLLM model failed at launch whenever it
suggested one. Run now suggests a context only to an engine whose flags have
`contextSize` (B68); picking a vLLM context is
[library#9](https://github.com/eugene-plexus/library/issues/9). The check now
sets `maxModelLen`, vLLM's own flag.

## Unit tests and the sabotage pass

- library `tests/test_engine_fit.py` (the share arithmetic, the judge's
  per-engine fit and level, the route's `fitModel`, sizes in facts), with
  `test_catalogue_facts.py` and `test_catalogue_sources.py` updated;
- agent `tests/test_fit_per_engine.py` (setup's rule, the table, each
  adapter's declaration, admission per engine, the library client, Run's
  context), with `test_strata.py` updated;
- ui `src/lib/eligibility.test.ts`, `src/lib/nodeBudget.test.ts`, and the
  Library and Discover page tests.

`scripts/ls6-sabotage.py` puts each rule back or takes each check out, one at
a time, restored from a copy: **61 of 61 caught** across the library, agent,
ui and acceptance gates. The first pass caught 58 of 60. Its two escapes were
gaps, not equivalent mutants: a candidate's fit was marked approximate even
when its facts were read off the hub (it now follows the candidate's own
`approximate`, with a test each way), and no test reached Run's skipping of
vLLM's context (`test_run_worker.py` now does, and is in the agent gate).
Full suites before the push: library 743 passed, agent 2,152, ui 1,817.

## After the pin: A4 macOS

The pin's A4 macOS run failed one check on all three runners: 42, *admission
answers for an MLX runtime on the Metal device*. MLX's *not estimated*
answer returned before admission placed the launch, so it named no device.
Fixed in agent `b362ee4` (placed first, still admitted on faith), with a
unit assertion and a sabotage entry (62/62); `ls6-fit-acceptance.py` 17/17
again for the change.
