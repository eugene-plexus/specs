# R6.1 — profile context-depth benchmark

Benchmark belongs beside each saved Library profile and runs on the currently
selected node through the existing node proxy. The agent owns the child,
cancellation, progress and persisted results. Closing a tab must not stop a
job; another console can find it. The task tray discovers jobs from enrolled
agents. Keep the latest 20 records per node, with model/profile snapshot,
resolved file metadata, engine version, actual argv, hardware and timestamp.
An interrupted agent marks unfinished records failed on restart.

Use the installed llama-bench beside the same llama-server discovery would
select. Check its own help before execution; no shell, downloads, arbitrary
benchmark binary, or inherited Plexus credentials. Library path containment,
node mappings, valid existing local copies and memory admission use the
runtime path. No new local copy is made by a benchmark.

Only llama.cpp, explicit context 256–262144, one sequence and supported profile
flags are accepted. Raw extraArgs and unsupported environment/serving settings
are refused with an explanation. Transfer GPU layers, threads, batch sizes,
GPU selection, tensor split, flash attention and supported loading options.
Do not turn profile temperature or top-p into benchmark flags: llama-bench
measures token evaluation, excluding tokenization and sampling.

Default sweep: 128 generated tokens, three repetitions, depths zero, half of
context-minus-generated-tokens, and context-minus-generated-tokens. The reserved
tail keeps the whole operation within the chosen context. Expose repetitions
and generated tokens in the benchmark form. Report mean, standard deviation,
samples and speed relative to the zero-depth baseline, as a curve and table.
The figure describes this run; it replaces neither fit guidance nor a real
request latency measurement, and does not measure parallel serving.

Require every managed runtime to be stopped first; never stop a user's model
implicitly. Serialize benchmark start with runtime create/update/start/restart,
including gateway wake requests, and refuse those mutations during a benchmark.
This also closes the check-before-start race. External GPU use cannot be
controlled: tell the operator to close other workloads. Only one job per node,
with a 15-minute deadline and bounded output. Cancellation, timeout and shutdown
terminate and reap the child before releasing the node. Failure keeps partial
points and a useful reason, never a successful curve from incomplete output.

Validate the structured output against the requested depths, generated tokens
and sample count; reject missing, duplicate, extra, nonfinite and nonpositive
results. Progress is test/repetition progress, not estimated remaining time.
Result snapshots remain readable after profile edits and are labeled as such.

Evidence for the instrument: the installed b10948 help and upstream
[llama-bench documentation](https://github.com/ggml-org/llama.cpp/blob/b10948/tools/llama-bench/README.md)
and [source](https://github.com/ggml-org/llama.cpp/blob/b10948/tools/llama-bench/llama-bench.cpp).
`--n-depth` prefills context; `--n-prompt 0` isolates decode. Progress is emitted
on stderr, structured results on stdout. No `--parallel` or `--ctx-size` is
passed to the benchmark.

Acceptance must cover real child execution, persistence, cancellation and
failure, supported flag mapping, concurrent launch exclusion, remote-node UI,
task progress, result presentation and deliberately broken checks. Use
disposable state; no live model is stopped to run acceptance.
