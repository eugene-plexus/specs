# MLX — built, unverified, and on a branch

**Status: written 2026-09-11, never run.** MLX is the last engine the
thesis names and was the only one unimplemented. It is also the only one
this project cannot test: `mlx` is Apple-silicon-only, and the box here
is Windows with an RTX 5090 (plus WSL2, which is where vLLM was proved).

Every other adapter met a real host before it landed. This one has not,
so it lives on a branch instead of `main`:

| Repo    | Branch            | Commit    |
| ------- | ----------------- | --------- |
| `specs` | `feat/mlx-engine` | `60cc15e` |
| `agent` | `feat/mlx-engine` | `0a4da70` |

The `agent` branch pins `SPECS_REF=60cc15e`, which is a commit on the
specs branch. That works because a consumer fetches a GitHub archive at
a SHA and a SHA on a branch is just as fetchable — so nothing on `main`
moves in either repo while this is being tested.

## Why not just merge it

Because M4 is the precedent and it cuts the other way. The vLLM adapter
needed **no change** on first contact with a real host, and that was not
luck: every claim in it had been read off upstream source first. What
the fixtures could not have produced was the other half of
`docs/acceptance/m4-vllm-run.md` — four host preconditions that kill the
engine 20–40 s in with a traceback naming none of them, and which only
appeared because someone ran it.

The expectation here is the same shape. The claims below that were read
off source will probably hold. The claims about the **host** are the
ones that will surprise, and there are none in this adapter yet, because
there is no way to know what they are from here.

## How to test it

```bash
# On an Apple silicon Mac.
git clone -b feat/mlx-engine https://github.com/eugene-plexus/agent
cd agent && uv venv && uv pip install -e '.[dev]'

# mlx-lm in an environment of its own; it does NOT go in the agent's venv.
uv venv ~/mlx/.venv && uv pip install --python ~/mlx/.venv mlx-lm

# Then, in the agent's config: mlxBinary = ~/mlx/.venv/bin/mlx_lm.server
# and declare a runtime with engine: mlx.
```

A model has to be MLX-format — `mlx_lm.convert` produces one, and the
`mlx-community` org on Hugging Face publishes them pre-converted.

## The claims, and how to check each one

All source references are **mlx-lm v0.31.3** (released 2026-04-22, the
current release on 2026-09-11), file `mlx_lm/server.py` unless noted.

| # | Claim | Read from | How to check it |
|---|---|---|---|
| 1 | The console script is `mlx_lm.server` — the dot is part of the name | `setup.py` console_scripts | `ls ~/mlx/.venv/bin` |
| 2 | `--model --host --port` are the launch flags | `main()` `add_argument` | the runtime starts at all |
| 3 | There is **no** `--served-model-name` | `main()` — no such argument | see "the blocker" below |
| 4 | The eleven curated flags exist under those exact names | `main()` | start a runtime with each set; an unknown flag is an argparse error |
| 5 | Booleans are `store_true`, so presence-only | `main()` | `--trust-remote-code` with no value is accepted |
| 6 | The HTTP server answers **while the model loads** | `run()` builds `ResponseGenerator` (whose thread calls `load_default()`) then `_run_http_server()` | `curl /health` immediately after launch, with a large model |
| 7 | `/health` is a hardcoded `{"status": "ok"}` and says nothing about the model | `handle_health_check` | same call — it should answer 200 before the model is resident |
| 8 | `/v1/models` reflects the HF cache, not what is loaded | `handle_models_request` calls `scan_cache_dir()` | `curl /v1/models` during the load |
| 9 | `model: "default_model"` resolves to whatever `--model` named | `APIHandler`: `body.get("model", "default_model")`; `ModelProvider.__init__` seeds `_model_map` | a completion naming `default_model` serves |
| 10 | `pip install mlx-lm` succeeds on a non-Apple host and installs no engine | `setup.py`: `mlx>=…; platform_system == 'Darwin'` | already true — this is why the refusal carries no command |

**The one that matters most is #6 plus #7 together.** They are why this
adapter proves readiness by asking for one token rather than by reading
a status. If either turns out to be wrong — if `/health` does reflect
the model, or if the server does not bind until the model is resident —
then `probe_readiness` should be rewritten to the much cheaper thing,
and `answers_while_loading` revisited.

## The blocker: MLX has no model id we can route on

**This is the finding, and it is not fixed on this branch.**

Every other engine lets us name what it serves. vLLM's
`--served-model-name` exists precisely because its default served name
is the `--model` argument verbatim, and we launch by absolute path — so
without the flag it would publish the operator's directory layout as an
OpenAI model id.

`mlx_lm.server` has no such flag. The only ids it answers to are:

- `default_model`, upstream's sentinel; and
- the resolved absolute path, which is what `handle_models_request`
  publishes (`str(model_path.resolve())`).

Neither can be a routing key. `default_model` **collides across every
MLX runtime in an install**, so two MLX runtimes serving different
models would look to the gateway like a replica set of one model and be
load-balanced across — returning the wrong model's output, silently. The
absolute path leaks the directory layout and differs per host for the
same model, which breaks `modelSlots` written against a model id.

The driver cannot paper over it today either: `InferenceDriverInfo`'s
`modelId` is a single value, documented as "backend-specific model
identifier", and it is both what the driver advertises to the gateway
*and* what it sends upstream. There is no advertise-X-send-Y split.

**Recommended fix, not implemented here because it is a contract change
with its own radius:** add an optional `upstreamModelId` to the
inference-driver's config and info, meaning "send this to the backend,
advertise `modelId` to the gateway". It is small, it is useful beyond
MLX (any backend whose served name is not ours to choose), and it is a
change to `inference-driver.yaml` — radius `inference-driver` and
`gateway`, which is a decision rather than a detail.

Until that exists, **an MLX runtime is launchable and not routable**,
except as the only MLX runtime in an install.

## Open questions the live run should settle

1. **The readiness probe costs a token per poll.** `probe_readiness`
   issues a real one-token completion every time, including long after
   the engine is ready, because an adapter is a stateless singleton and
   cannot remember that it already proved residency. Measure whether
   that is a nuisance. If it is, the fix is a base-class change — let a
   probe report "you may stop asking the expensive question" — not a
   quiet weakening of the check.
2. **Does a vanilla HF safetensors model load, or only an MLX-converted
   one?** The adapter claims `ModelFormat.safetensors`, which is the
   format; it does not claim the conversion. If unconverted models do
   not load, the library's format join is now wrong for this engine and
   needs a narrower answer than "safetensors".
3. **No context length, anywhere.** MLX publishes none on `/v1/models`
   or on a completion, so `RuntimeCapabilities` comes back empty and the
   library computes fit against the operator's declared number only.
   Confirm there is really no source for it.
4. **A stall shows as a permanent `loading`.** `startup_budget_seconds`
   is deliberately unset, because the base uses it only for the silent
   load case (`answers_while_loading = False`), which is not this
   engine. If a wedged MLX is a real failure mode, flagging one needs a
   small base change rather than a wrong flag here.
5. **Unified memory and admission.** M6's admission check refuses a
   launch that will not fit, using per-device memory the agent detects.
   Apple unified memory has never been detected on real hardware by this
   code — it is in the carried-forward list with AMD and Intel — so
   whether admission does anything sensible on a Mac is unknown, and is
   a second thing this branch's tester is well placed to answer.

## What is on the branch

- `specs`: `mlx` added to `EngineKind` in `components/common.yaml`, plus
  the readiness sentence. That is the whole spec delta, deliberately —
  `EngineKind` lives in the shared components document, and a
  `common.yaml` change reaches all six consumers the day it lands.
- `agent`: `engines/mlx.py`, registered in `engines/__init__.py`;
  `mlxBinary` on the config trio; `tests/test_mlx.py` (21 tests); the
  three existing engine-parity tests updated to expect a third engine.
