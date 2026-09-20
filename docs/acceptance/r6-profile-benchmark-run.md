# R6.1 profile benchmark — 2026-09-20

Implemented and published the profile benchmark button, not the remainder of
R6. The roadmap remains the pickup point. Agent `c0b7f67`, control codegen
`612c56b`, UI source `ba235fd`, UI dist `1669119`; contract `f82c0d6`.

Operator follow-up: a previously working 70,000-context profile was refused by
the existing Library fit calculation, which counted an unloaded vision projector.
Corrected in Library `766ecb8`; [evidence and verification](gguf-projector-fit-run.md).

Open Library, choose the machine and model, then **Benchmark** beside a saved
llama.cpp profile. Stop that machine's managed models in Inference first.
The benchmark does not stop them. Choose generated tokens (16–256) and
repetitions (1–5); defaults are 128 and 3. An explicit context and one parallel
slot are required. Raw arguments and unsupported environment overrides are
refused. Runtime create/update/start/restart, including gateway wake, return
409 while the benchmark owns the node. Stop and delete remain available.

The sweep reserves the generated tokens at the end of the selected context,
then measures decode at zero, halfway, and the remaining maximum depth.
It reports mean tokens/s, standard deviation, individual samples and percentage
of zero-depth speed. Partial output is labeled partial. A missing or duplicate
depth, wrong sample count, nonfinite timings, process failure, excessive output
or timeout cannot become a successful result. Cancellation and shutdown reap
the child before allowing another start. Windows Job Objects and Linux parent
death handling reuse the existing supervised-child safeguards.

Results retain model/profile identity, launch settings, resolved file metadata,
engine version, command and hardware. The latest 20 jobs are saved beside the
agent's configuration. Another console can discover active jobs through the
node API and task tray. A restart marks interrupted records failed. The model
file and Library profile are never written by the benchmark.

## Verification

- Windows full suites: **951 agent passed, 4 skipped; 169 control passed;
  736 UI passed**. Benchmark-specific checks: **28 passed** on Windows and
  Linux, with real harmless child processes. These cover credentials, bounded
  output, failure, timeout, cancellation/reaping, persisted history, auth,
  concurrent admission in both orders and gateway wake exclusion.
- `scripts/r6-benchmark-checks.py` detects **6/6 deliberate regressions** on
  Windows and Linux: incomplete results, duplicate depths, inherited Plexus
  credentials, missing launch exclusion, a busy node, and lost context tail
  space. Mutations affect disposable source copies. The restored baseline
  passes. This check joins the Windows/Linux launch-boundary CI job.
- `scripts/r6-benchmark-acceptance.py` runs a real isolated agent process,
  authenticates over HTTP, runs the installed llama-bench on CPU, checks a
  conflicting launch, cancels another run, restarts the agent, and verifies
  persisted points. No installed service, runtime, profile, firewall rule or
  model file is changed.
- Instrument: Windows llama.cpp **b10948**, Qwen3-0.6B-Q4_K_M, 396,705,472 bytes,
  two CPU threads, GPU layers 0, CUDA visibility disabled. Context 256,
  16 generated tokens, two repetitions. The HTTP run measured **96.0 / 89.8 /
  85.1 tokens/s** at depths **0 / 120 / 240**. These tiny CPU measurements
  validate the instrument and parser; they are not a 5090 performance claim.
- `scripts/r6-browser-acceptance.mjs` drives the installed wheel through an
  isolated agent. Only Library catalogue reads are fixtures; starting and
  reading the benchmark use the real agent and real CPU-only llama-bench.
  It changes the sample controls, verifies submitted values and actual points,
  reloads the page and finds the saved results. Desktop screenshot reviewed.
  This caught inputs being reset during initial node discovery and black SVG
  labels on the dark background. Both fixes are in the final wheel.
- The 390-pixel screenshot **does not pass mobile usability**: the existing
  fixed Library split pane clips the detail view. Recorded for the remaining
  R6/S9 phone pass. Rendering without JavaScript errors is not mobile acceptance.
- Production UI built from committed source in an isolated worktree.
  **184 assets match byte for byte** between that export, the published dist
  tree and wheel. Final wheel SHA-256:
  `f179760e6ca683988b8df7b59f4e03f699e4e47d6428cc25148cbda1409649bc`.
- Website boundary copy now describes the benchmark as shipped; Astro checks
  and all **30 website browser checks** pass. Its existing preview was reused
  through a temporary test config and left running. No timing showcase added.

## Limits and reproduction

llama-bench measures token evaluation, not tokenization, sampling, request
latency or parallel serving. Unset settings use its build defaults; the
server's automatic GPU placement is not reproduced. The UI says to set GPU
layers explicitly when comparing offload settings. Fit estimates remain
independent. Other programs' GPU work cannot be stopped or excluded by Eugene.
macOS inherits the existing absence of hard-exit child cleanup; graceful
cancellation and shutdown are supported. No physical Mac acceptance is claimed.

Run the HTTP acceptance with an agent-enabled Python environment:

```text
python scripts/r6-benchmark-acceptance.py --server <llama-server> --model <small.gguf> --report <result.json>
python scripts/r6-benchmark-checks.py
```

For browser acceptance, start a disposable agent with the newly built UI wheel
installed and `default_topology=False`. Initialize its operator session; save
`{"url":"http://127.0.0.1:<port>","token":"<disposable session>"}` to a local
file. Mark its `firstRunComplete` true. Do not use an installed node for this
test. With UI dependencies installed in the sibling checkout:

```text
node scripts/r6-browser-acceptance.mjs <session.json> <small.gguf> <screenshots-directory>
```

The browser test requires an installed llama.cpp discoverable by that agent,
and uses its real managed build. The catalogue fixture supplies CPU-only
profile settings. Local artifacts are under `%TEMP%/ep-r6-real-bench` and
`%TEMP%/ep-r6-browser`; session tokens are not committed.
