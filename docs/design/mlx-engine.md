# MLX — the third engine, experimental until a Mac says otherwise

**Status: integrated on `main` 2026-09-22 (roadmap B1), physical Apple
silicon checks pending.** Supersedes the branch-only
`feat/mlx-engine` work (`specs 60cc15e` / `agent 0a4da70`, 2026-09-11)
and its design record `mlx-engine-unverified.md`, which stays on that
branch as history. The port was a rewrite, not a merge: the branch
predates the one-client rule (R1.1), the readiness-cost answer, the
`(node, name)` runtime keying (R1.6) and the model-identity split this
document records, so the useful knowledge came forward and the code was
written against current `main`.

## The pinned upstream

**mlx-lm v0.31.3** (released 2026-04-22) — still the newest release as
of 2026-09-22, and the version every claim below was re-verified
against by reading `mlx_lm/server.py` at the `v0.31.3` tag on
2026-09-22. The claims table from the branch document holds unchanged:

- The console script is `mlx_lm.server`; the dot is part of the name.
- `--model --host --port` launch it; the eleven curated flags exist
  under those exact names; booleans are `store_true`.
- The HTTP server answers **while the model loads** (`run()` builds
  `ResponseGenerator`, whose thread calls `load_default()`, then
  `_run_http_server()`).
- At v0.31.3, `/health` is a hardcoded `{"status": "ok"}` — it says
  nothing about the model.
- `/v1/models` reflects the HF cache plus the resolved absolute
  `--model` path; there is **no `--served-model-name`**.
- `model: "default_model"` resolves to whatever `--model` named
  (`ModelProvider.__init__` seeds `_model_map["default_model"]`).

**Upstream `main` has since changed `/health`** (inspected at
`c69d128` for the roadmap): it answers `503 {"status": "unavailable"}`
until the model is resident. That is unreleased, so the pin stays
0.31.3 — but the adapter already reads a 503 `unavailable` from
`/health` as `Loading`, so the day a release carries it, the readiness
probe gets cheaper with no adapter change.

## The blocker, and its fix: `upstreamModelId`

The branch's finding stands: `mlx_lm.server` has no model id we can
route on. It answers only to `default_model` (collides across every MLX
runtime in an install) and the resolved absolute path (leaks the
operator's directory layout, differs per host). `InferenceDriverInfo`'s
`modelId` was a single value — both advertised to the gateway and sent
upstream.

**Fixed as the branch document recommended, as a contract change on
`inference-driver.yaml`:** the driver grows an optional
`upstreamModelId` config key and `DriverInfo` field. `modelId` is the
public identity — the gateway routes, authorizes, groups replicas and
filters scopes on it, and every response reports it, streams included.
`upstreamModelId` is what actually goes to the backend, resolved once
at engine construction and used nowhere else. It defaults to `modelId`,
so every existing configuration is unchanged.

The gateway needed **no code** for this, and that was verified before
it was assumed: the forwarded request body carries no model field at
all (the driver serves its one configured model), the routing key is
`DriverInfo.modelId`, and the caller-visible `model` comes from
`GenerateResponse.modelId` — all of which stay on the public side of
the split. Two MLX runtimes serving different models behind the same
`default_model` sentinel are two public aliases end to end.

Supervised runtimes supply the mapping: the agent's companion-driver
config for an MLX runtime writes `modelId: <public alias>` and
`upstreamModelId: default_model`. The key is rendered for every
companion (null where the engine needs no translation), so a runtime
that changes engine has it cleared rather than left lingering.

## Readiness: one token once, not one token per poll

At the pinned release no read-only probe can tell loading from ready,
so the adapter proves residency by asking for one token. The branch
version paid that token **on every 2 s poll forever**; the open
question it recorded ("let a probe say you may stop asking the
expensive question") is answered with the base-class change it asked
for: `probe_readiness` takes `established: bool` — true when this same
process has already been proved resident. The supervisor keys that on
the process's own restart marker, so a crash-and-respawn resets it: a
fresh process answers `/health` immediately and would otherwise read as
ready while loading. Once established, the MLX probe is a plain
`/health` read like every other engine's.

What that trades away, stated: after residency is proved, a wedged
generation path shows as `ready` until requests fail — the same
blindness llama.cpp's narrated health has. The alternative was a
permanent per-runtime forward pass every two seconds on a
unified-memory machine.

A prolonged load is bounded the other way: `interpret_readiness` now
flags any `Loading` outcome past the adapter's `startup_budget_seconds`
(previously only silent loads were budgeted), and MLX declares 600 s —
the state stays `loading`, flagged, with the elapsed time.

## Installation recipe (versioned, isolated)

mlx-lm never goes into Eugene's own environment. The recipe the agent's
`manualInstall` carries for Apple silicon:

```bash
uv venv ~/eugene-mlx --python 3.12
uv pip install --python ~/eugene-mlx/bin/python "mlx-lm==0.31.3"
# then, in the agent's config: mlxBinary = ~/eugene-mlx/bin/mlx_lm.server
```

Three traps the recipe and the config field's description both name:

1. **`pip install mlx-lm` succeeds on any platform** — upstream marks
   its `mlx` dependency `platform_system == 'Darwin'`, so on Linux or
   Windows you get the server package with no engine behind it and the
   failure is an ImportError at launch. On non-Apple hardware the
   refusal explains this instead of offering the command.
2. **A Rosetta terminal poisons the environment**: `uv` fetches an
   x86_64 CPython, `mlx` cannot reach Metal, and detection reads the
   machine as Intel. The recipe pins the check:
   `~/eugene-mlx/bin/python -c "import platform; print(platform.machine())"`
   must print `arm64`.
3. The console script's shebang binds its own interpreter, so nothing
   needs activating and the path survives an agent restart and the
   launchd environment — which is also why `mlxBinary` points at the
   console script, never at a Python interpreter or a venv directory.

## The pinned known-compatible model

`mlx-community/Qwen3-0.6B-4bit`, revision `73e3e38d`, Apache-2.0.
Small enough to download and load on any Apple silicon machine, from
the org that publishes MLX conversions, quantized so its `config.json`
carries the MLX `quantization` block the library records as
`SafetensorsDetail.mlxQuantization`. The library treats that block as
the one positive marker of MLX conversion; its absence means unknown,
not incompatible (an unquantized MLX conversion has none).

## What a physical Apple silicon run must still settle

Everything below is pending, and the support matrix says experimental
until it is recorded. Fixture results in the acceptance record are
labeled simulated.

1. Fresh install → model acquisition → first reply → streaming and
   cancellation → stop with memory observations → restart → agent
   restart → documented login startup → an application call from a
   second machine. Record hardware, macOS version, Python architecture,
   engine/model revisions and logs.
2. Whether a **vanilla** (non-MLX-converted) HF safetensors model loads
   — the adapter claims the format, not the conversion.
3. Whether unified-memory admission behaves: the metal device reports
   no free-memory reading, so admission answers `unknown` honestly
   rather than treating host RAM as free VRAM (fixed on the agent this
   slice); a Mac run is what turns `unknown` into a measured number.
4. A Rosetta-started install, when a tester can run one.
5. Context length: MLX publishes none on `/v1/models` or completions,
   so `RuntimeCapabilities` stays empty and fit is computed against the
   declared context only. Confirm there is really no source for it.

A known routing or shutdown defect is a blocker; missing hardware
evidence is a stated alpha testing limitation.
