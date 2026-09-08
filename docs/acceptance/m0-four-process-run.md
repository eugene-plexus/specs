# M0 acceptance — the four-process run

**Status: passed 2026-09-08.** Runner: [`scripts/m0-acceptance.sh`](../../scripts/m0-acceptance.sh).

M0 is "one engine, end to end": supervise a single `llama-server` from config, a
driver fronts it, `GET /v1/runtimes` reports it healthy, the gateway routes a
chat completion through the driver to it, the UI shows it. Every component had
its own tests for its own half and all of them were green — but nothing had ever
run the halves *together*.

That gap was not academic. Both existing end-to-end tests substitute the other
side:

| Test | Real | Substituted |
|---|---|---|
| `watchdog/tests/test_runtime_end_to_end.py` | supervision loop, subprocess, `/health` probe, status mapping | the engine (a Python script speaking llama-server's `/health` contract) |
| `gateway/tests/…` | routing table, OpenAI surface, failover cascade | the drivers below it |

Each proves its own half correctly. Neither can prove they fit, and the two
defects below lived exactly in the seam.

## What the run does

Four processes, nothing simulated:

```
watchdog  ──spawns──▶  gateway            (:8080)
          ──spawns──▶  inference-driver   (:8081)
          ──spawns──▶  llama-server       (:8090)   ← a real engine binary
```

then one chat completion travelling gateway → driver → engine and back.

Checks, in order: the supervisor comes up; auth initializes and children get
service tokens at spawn; both components reach `running`; the engine reaches
`ready` through its real readiness probe and reports its capabilities back; the
gateway's routing table — which nobody configured — resolves the model; a
completion returns real text with correct routing attribution; **an unmodified
OpenAI SDK** points `base_url` at the gateway and works; and killing the
supervisor takes the engine down with it, leaving no orphan.

## What it found

Two defects, neither reachable by any single-component test.

**1. A local engine needs no API key** (fixed, `inference-driver` `32957cf`).
The run failed at the first completion:

> This driver has no working engine. `openai_compat_http` engine has no API key

`openai_compat_custom` is the provider a driver uses to front a supervised
runtime — M0's headline case — and it required an API key for a process on the
same machine that ignores the header. The driver dropped into degraded mode, so
`GET /v1/models` reported nothing routable. `ollama_local` and `lmstudio_local`
already set `auth_required=False`; the custom-URL provider is at least as likely
to be a local engine and was the one that didn't. The adapter also sent the
literal string `Bearer None` when it had no key.

**2. `runtime` and `context_length` were documented but never set** (fixed,
`gateway` `b7dd922`). A completion served by a real `llama-server` came back with
`"runtime": null`, and the model advertised no context window although the
engine had reported 4096 tokens to the watchdog. Nothing *could* set them: a
driver knows its base URL but not that a supervised runtime is on the other end,
and its `/v1/info` says neither. The fix needs no contract change — a runtime's
`modelAlias` is by definition what a client asks the gateway for, so an alias
equal to what a driver serves identifies the runtime behind it.

## Timing worth knowing

The gateway normally finishes its **first** routing refresh *before* a large
quant finishes loading, so `context_length` is eventually-true, not
immediately-true: the alias is known straight away, but capabilities only exist
once the engine is `ready`, and the table refreshes on `routingRefreshSeconds`
(15s). The runner polls one interval rather than pretending otherwise. This is
the periodic-refresh design working, not a bug — but it is the kind of thing
that reads as a bug at 2am.

## Running it

Needs a real engine binary and a real model; both are the operator's to supply
until **engine acquisition lands at M1**. Configure with environment variables
(`EP_WATCHDOG_PY`, `EP_LLAMA_SERVER`, `EP_MODEL`, `EP_WORKDIR`) — the built-in
defaults suit only the machine it was written on.

```bash
EP_LLAMA_SERVER=/path/to/llama-server \
EP_MODEL=/path/to/model.gguf \
scripts/m0-acceptance.sh
```

It is a script and not a pytest deliberately: it needs a multi-gigabyte model and
a platform-specific binary, and a CI job that silently skipped both would be
worse than no test at all.

**The watchdog's venv is the runtime venv.** The supervisor spawns every
component with its own `sys.executable`, so `eugene_plexus_gateway` and
`eugene_plexus_inference_driver` must both be importable from it. The runner
preflights this, because the failure mode otherwise is a component that appears
to start and then vanishes.

## The passing run (2026-09-08)

```
llama.cpp build 9846, Qwen3.6-27B-Q4_K_M (15.7 GB), full GPU offload, ctx 4096

runtime qwen3-27b   ready, pid 58384, url http://127.0.0.1:8090/
capabilities        {contextLength: 4096, parallelSlots: 1, multimodal: false}
argv                llama-server.exe --model ...Q4_K_M.gguf --host 127.0.0.1
                    --port 8090 --alias qwen3.6-27b --ctx-size 4096
                    --n-gpu-layers 99 --parallel 1

GET  /v1/models              → qwen3.6-27b, drivers [qwen-driver], ctx 4096
POST /v1/chat/completions    → "391"   (17 × 23)
                               227 completion tokens, most of them a <think>
                               block the driver stripped
     x_eugene_plexus         → driver qwen-driver, runtime qwen3-27b,
                               backend openai_compat_http, 3143 ms, 1 attempt

OpenAI SDK 3.9.0, unmodified → models ['qwen3.6-27b'], reply 'OK'
teardown                     → no orphaned llama-server
```

## Known gaps this run confirms, deliberately

- **No token-by-token streaming.** `stream: true` returns correct OpenAI framing
  with a single content chunk. Real pass-through needs the driver's SSE plumbed
  through the failover cascade.
- **`GET /v1/engines` reports `available: false`** while a runtime using that
  engine runs happily. The endpoint answers "is a binary discoverable on this
  host" (PATH or managed); a runtime with an explicit `binary:` bypasses
  discovery. Correct as specified, confusing as displayed — worth revisiting
  when acquisition lands at M1 and `managed` becomes a real origin.
- **A 401 from the gateway is not OpenAI-shaped.** The two OpenAI-compatible
  operations return OpenAI's error envelope for their own failures, but the
  shared auth dependency raises before the route runs, so an unauthenticated
  caller gets `{"detail": …}`. An SDK reports that as a generic failure rather
  than an auth error.
- **Only one backend.** Failover, replicas and load balancing are M5 and this run
  says nothing about them beyond `attempts: 1`.
