# M6 acceptance — six processes, two replicas, one GPU

**Status:** passed 2026-09-10, on the second run. Script:
[`scripts/m6-acceptance.sh`](../../scripts/m6-acceptance.sh).
Follows [M5's kill-the-control-root run](../../scripts/m5-acceptance.sh)
and closes the gap [M2's run](m2-five-process-run.md) named.

```
agent ──spawns──> control, gateway, library
      ──declares (via the API, no config written)──> qwen3-a, qwen3-b   two llama-server
      ──and declares beside them, itself──────────> qwen3-a-driver, qwen3-b-driver
gateway ──balances──> qwen3-a-driver ─> qwen3-a
                  └─> qwen3-b-driver ─> qwen3-b      (one Qwen3-1.7B Q8_0, loaded twice, CUDA_VISIBLE_DEVICES=0)
```

What separates this from every earlier run: **nothing here was wired
by hand.** M0 through M5 each carried a `driver.yaml` the script wrote
with the engine's port in it. This run writes none. The two runtimes
are declared over the API and arrive routable, because the agent
declares their drivers. Everything downstream — balancing, the kill,
idle unload, the wake, admission, tiers — happens on top of that.

The first run failed three stages and passed four. Both defects it
found were real, neither was in the fixtures, and both are recorded
below. That is the reason the live run exists.

---

## What it proved

Twenty-nine checks, all green on the second run.

- **`GET /v1/node` answers.** For the first time from a real agent: one
  accelerator, `NVIDIA GeForce RTX 5090`, 29.2 GiB free. M5's control
  root has polled for this since it was written.
- **Launch ends routable.** Two `POST /v1/runtimes` with one alias and
  `CUDA_VISIBLE_DEVICES=0`. Each 201 named its companion. Both
  companions appeared in `/v1/components` beside `control`, `gateway`
  and `library`. When both engines were `ready`, `gateway /v1/models`
  listed `qwen3-1.7b` once, behind both drivers, `ready_backends: 2`,
  one tier, context 4096.
- **The companion costs what the design guessed.** 74 MB and 73 MB
  resident, measured over the venv launcher's process tree (§9 of the
  design said 60–80).
- **Round-robin.** Six sequential completions went a, b, a, b, a, b.
  Each response named the driver *and the runtime* that served it —
  attribution by name, which the alias-keyed join could not do for
  replicas.
- **A killed replica is survived.** `Stop-Process` on qwen3-b's engine
  pid; the next completion returned from qwen3-a in 172 ms with
  `attempts: 1` — the refresh-on-demand had already dropped the dead
  replica, so the cascade never had to fire. The supervisor respawned
  qwen3-b to `ready` afterwards.
- **Idle unload returns VRAM.** Both replicas declared
  `idleUnloadSeconds: 20`. With no requests, both went
  `stopped / stopReason: idle` by the gateway's hand. `nvidia-smi`
  memory.used went 5,051 MiB → 2,289 MiB, 2,762 MiB released, against
  an idle baseline of 2,291 MiB before anything loaded. The alias stayed
  listed, `on_demand: true`.
- **Swap on demand.** A completion for the sleeping alias returned in
  2,953 ms wall clock: `swapped_in: true`, `waited_ms: 2546` for the
  wake, 141 ms for the generation. Exactly one replica came back; the
  other stayed asleep.
- **Admission refuses with the arithmetic.** The 40B Q4_K_S at
  `contextSize: 131072`, `gpuLayers: 99`: `refuse`, verdict `split`,
  basis `metadata` (the library computed it), **36.0 GiB required
  against 26.5 GiB free of 31.8 GiB**, blocker `qwen3-a (ready,
  evictable)`. `POST /v1/runtimes` returned 422 with that sentence;
  `?force=true` declared it (201); it was deleted before it finished
  reading weights.
- **Tiers cascade.** A `sleeper` runtime serving alias `sleepy`, declared
  `autoStart: false` and not on demand — its companion runs, so
  `sleepy` is a real tier that is never eligible. `modelSlots` patched
  to `coder → [sleepy, qwen3-1.7b]`. A completion for `coder` answered
  from qwen3-a with `tier: 2` and `model: qwen3-1.7b` — the response
  names what answered, not what was asked for.
- **Clean teardown.** No `llama-server` survived the supervisor.

## The two defects the first run found

Both would have shipped on the fixtures alone.

**1. The routing table was a refresh interval behind about readiness.**
Every completion in stage 3 was a 503 — `qwen3-a (loading), qwen3-b
(starting)` — while the agent reported both `ready`. The snapshot was
up to `routingRefreshSeconds` old (3 s in the script, **15 s by
default**), and the whole of stages 3 and 4 fit inside that window. In
production that is fifteen seconds of 503s after every model load, and
after every replica death the table has not noticed. The gateway now
refreshes on demand when a request finds nothing eligible — shared,
at most once a second — before waking anything or answering. A request
that finds a backend never pays for it. The script also stopped
declaring "routable" on the driver list alone: it waits for
`ready_backends`.

**2. `gpuLayers: 99` read as partial offload.** Admission's full-offload
threshold was 999, so the 40B at 128k was *admitted* as "partial
offload the operator chose" (36 GiB, `split`). 99 is llama.cpp's idiom
for "everything", every profile in this project writes it, and `-1` is
upstream's other spelling. Both are full offload now, and the design's
table says 99.

A third thing the first run showed was a measurement, not a defect: the
companion's resident size read as 5 MB because the pid the agent holds
is the venv's `python.exe` launcher on Windows, whose child is the real
interpreter. The script sums the tree.

## What one GPU could not prove

`nvidia-smi -L` lists the RTX 5090 alone on this box today. Both
replicas ran on device 0. The env var was passed and appears in each
runtime's argv, and the engine would honour a different index — but the
observable is identical to not pinning. `EP_DEVICES="0 1"` re-runs the
same script on two cards; per-device `nvidia-smi` is then the check.

Also not exercised: a wake that has to **evict** (the 40B's start was
refused and force-declared rather than woken through the gateway),
`round_robin` as a strategy, and any of this across two hosts. Eviction
and both strategies are covered by the gateway's fake-agent tests; the
two-host question is the same one M4 and M5 are waiting on.

## Timings worth keeping

| What | Measured |
|---|---|
| Qwen3-1.7B Q8_0, `llama-server`, cold to `ready` | ~10 s from disk cache (both replicas in parallel) |
| Two replicas resident, context 4096 | 5.4 GiB of device memory over baseline |
| Wake on demand, stopped → serving | 2.5 s wait + 141 ms generation |
| Completion after a replica killed | 172 ms, one attempt |
| Companion inference-driver | 73–74 MB resident |
| Whole run | about four minutes |
