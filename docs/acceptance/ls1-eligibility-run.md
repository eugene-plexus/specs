# LS1: engines declare what they accept; the Library judges (2026-10-09)

Slice LS1 of [library-sources-and-engines.md](../design/library-sources-and-engines.md).
Pinned at specs `93c3d1d` (ui dist `45f12f2`). Contract specs `f1850ec` and `b11964f`; library `a7486cf` + `15bed1c`; agent
`ec7d91e` + `e4179a8`; ui `4b5fec49` + `662cbbde`.

## The run of record

`scripts/ls1-eligibility-acceptance.py` on Amish_Station (Windows 11, Python
3.14, editable agent and library), **11 of 11**. It starts a throwaway
standalone agent on free loopback ports, supervising its own Library over four
header-only fixtures: a llama GGUF, a Qwen3.8-Flash-Next GGUF (`qwen4exp`), an
MLX-quantized safetensors folder and a plain one. No engine is installed in its
engine root and nothing is started.

| Check | What it proves |
| --- | --- |
| E1 ×3 | The real agent's `/v1/engines` carries `accepts` for every engine; Strata's is a `qwen4exp` GGUF after preparation, with no `modelFormats` for older consoles; vLLM forbids MLX-quantized folders and leaves the architecture to itself |
| E2 ×6 | The console's question through the agent's own proxy (`/api/proxy/library/v1/eligibility`, as the browser sends it): an unknown id left out; llama.cpp runs the llama GGUF and Strata names the architecture it needs; the level follows llama.cpp being installed (*other engine* here); Strata runs Flash-Next after preparation; MLX runs the MLX folder and vLLM says why not; vLLM and MLX *may run* the plain folder, in vLLM's words |
| E3 ×2 | Run through the real agent's run worker: the GGUF reaches *install llama.cpp?* on llama.cpp's verdict; the MLX folder fails naming vLLM's reason, which only the Library writes |

## Unit tests and sabotage

- library `tests/test_eligibility.py` (7), full suite 631 passed (one
  intermittent failure in `test_routes.py::test_cancelling_when_nothing_runs_is_a_conflict`,
  untouched code, passed on rerun).
- agent `test_run_worker.py` and `test_engines.py` (new: Run follows the
  judge, falls back on a 404, names each engine's reason; `accepts` declared
  and held to `modelFormats`); full suite 2,062 passed; ruff, mypy both
  platforms, vendored check clean.
- ui `lib/eligibility.test.ts`, `app/library/page.test.tsx` (the panel and
  dot, Run follows the verdicts, the 404 fallback); full suite 1,752 passed;
  tsc, eslint, prettier clean.
- **Sabotage, changed code only: 18 of 18 caught** (library 8: each matching
  term, authority, preparation, the level's installable rule, unknown ids,
  ordering; agent 5: Run in registry order, no 404 fallback, `accepts` not
  reported, Strata's architecture, vLLM's MLX rule; ui 5: the panel, Run's
  source, installable, an older agent's formats, the list dot). Each restored
  from a copy.

## Found by this run

- **library#7:** on an agent that has not joined a root, one-click Run never
  leaves *checking*: the console submits `node: null` and the Library hands
  operations only to the node a token names, `local` for such an agent. Not
  LS1's; the script names `local` so E3 tests the judge.

## Not covered

- The browser page itself (the console's unit tests cover the panel and dot;
  E2 covers the request it sends, through the same proxy).
- A node with vLLM or MLX installed: verdicts are judged the same way, but no
  run here had either.
