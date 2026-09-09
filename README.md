# Eugene Plexus — `specs`

[![CI](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI-3.1-6BA539.svg)](https://spec.openapis.org/oas/v3.1.0)

OpenAPI 3.1 contracts for every cross-component interface in [Eugene Plexus](https://eugeneplexus.com).

This is the **single source of truth** for how Eugene Plexus components talk to each other. Every other repo in the org depends on this one via codegen — never via direct import — to physically enforce the principle that *components share schemas, not code*.

## What is Eugene Plexus?

**A self-hosted control plane for local LLM inference.**

It supervises engine processes it does not own, manages a model library on your own disk, holds per-model settings profiles, exposes one OpenAI-compatible endpoint that routes across local runtimes and cloud providers with failover, and serves a web UI with real auth so it works over a tailnet — not just localhost.

**It is not an inference engine.** llama.cpp, vLLM and MLX are the engines. We wrap upstream; we never fork it and never compete with it.

Everyone else builds an *engine* (llama.cpp, vLLM, MLX) or a *desktop chat app* (LM Studio, llama.app). The operations layer — supervise, configure, route, authenticate — is unclaimed. That layer is the product:

1. **It supervises engines it doesn't own,** and manages their binaries so you don't install llama.cpp by hand first.
2. **Discovery and download happen in the app.** Search a catalogue, read what a model is, pick a quant, download with resume and progress.
3. **Your model files stay yours.** Point it at your existing GGUF directories; downloads land *there*, as plainly-named files. No content-addressed cache, no hash mismatches. Delete us and you still have your models, correctly named, where you put them.
4. **Schema-driven config UI with per-model profiles.** Every knob is a form field with help text and defaults, generated from the config schema the component already publishes.
5. **Networked-first, with auth.** Headless server, browser UI, tokens.
6. **Hardware-aware quant guidance, on the discovery screen.** `Q3_K_S` or `Q4_K_M` is a question you should be answered at the moment you are asking it, not in a separate tool.
7. **Many backends at once, load-balanced, with failover.** Several models resident simultaneously; replicas of one model across two GPUs served round-robin; a priority-list cascade when a backend dies. Cloud subscriptions are just another backend — so it's one endpoint over your local models *and* the subscriptions you already pay for.

Full design: [`docs/design/local-inference-control-plane.md`](docs/design/local-inference-control-plane.md).

## Layout

```
openapi/
  gateway.yaml              the OpenAI-compatible front door; routing + failover
  inference-driver.yaml     the uniform surface over one backend (N instances)
  library.yaml              the operator's model directories, scanned + profiled;
                            catalogue search, downloads, quant guidance
  agent.yaml             process supervisor, engine launcher, UI host, auth root
  components/
    common.yaml             shared schemas (messages, errors, config protocol, auth)
```

## Shape

Two layers, never collapsed: a routing `gateway` above N per-backend `inference-driver` instances.

| Component | Repo | Port | Job |
|---|---|---|---|
| supervisor | [`agent`](https://github.com/eugene-plexus/agent) | 8079 | Spawns and monitors components *and* engine processes; owns engine adapters, topology, log capture, safe mode, auth root; serves the UI |
| gateway | [`gateway`](https://github.com/eugene-plexus/gateway) | 8080 | One OpenAI-compatible endpoint. Model → driver resolution, load balancing, priority-list failover. **No backend knowledge.** |
| inference-driver | [`inference-driver`](https://github.com/eugene-plexus/inference-driver) | 8081 | **One instance per backend.** Owns provider choice, model id, secrets, params, health |
| library | `library` | 8082 | The operator's own model directories: recursive scan (GGUF + safetensors), metadata, per-model launch profiles; catalogue search, resumable downloads, quant table, hardware fit scoring |
| ui | [`ui`](https://github.com/eugene-plexus/ui) | — | Config editor, runtime dashboard, library browser, chat playground, logs |
| specs | this repo | — | Contracts; consumers codegen from a pinned SHA |

The layering matters and is not an accident of history. A driver belongs *next to its engine*, so it can run on a remote GPU host while the gateway reaches it over the tailnet — that is the whole multi-host story. Two replicas of one model on two GPUs need N independently-configured backends with something above them. And `claude_code_cli` / `codex_cli` are subprocess backends with no endpoint to proxy to, so a driver has to be able to sit in the request path regardless.

### Components vs. runtimes

The agent supervises two different kinds of process and keeps them in separate collections, because they share only their supervision *mechanics*:

| | Component (`/v1/components`) | Runtime (`/v1/runtimes`) |
|---|---|---|
| What it is | a Eugene Plexus process | a third-party engine binary |
| How it starts | `<python> -m <module>` | argv built by an engine adapter |
| Readiness | the shared `/healthz` | engine-specific probe |
| Config | the standard config trio | curated engine flag surface |
| Auth | gets signing key + service token | gets none; fronted by a driver |

Engine knowledge splits the same way, with no shared library: how to **start** an engine (argv, readiness, curated flags) lives in the supervisor; how to **talk to** one (wire protocol) lives in the driver.

## Using these schemas

### Python (Pydantic v2 models)
```bash
pip install datamodel-code-generator
datamodel-codegen \
  --input openapi/gateway.yaml \
  --input-file-type openapi \
  --output-model-type pydantic_v2.BaseModel \
  --output gen/gateway_models.py
```

### Python (typed async client)
```bash
pip install openapi-python-client
openapi-python-client generate --path openapi/gateway.yaml
```

### TypeScript (types)
```bash
npm install -D openapi-typescript
npx openapi-typescript openapi/gateway.yaml -o gen/gateway.ts
```

We deliberately **avoid the Java-based `openapi-generator`** — verbose output, opinionated templates you fight, heavyweight install.

Consumers pin a specs SHA in their own `SPECS_REF` file and regenerate from GitHub at that SHA, so a change here never breaks a consumer until it chooses to bump.

## Setting up a dev environment

Eugene Plexus is a polyrepo targeting **Python 3.12** — every component pins `requires-python = ">=3.12"`, ruff `target-version = "py312"`, and mypy `python_version = "3.12"`, and CI runs on 3.12. Develop on 3.12 so local matches CI.

To set up every repo on a fresh machine (Windows):

```powershell
gh repo clone eugene-plexus/specs
.\specs\scripts\bootstrap.ps1
```

[`scripts/bootstrap.ps1`](scripts/bootstrap.ps1) clones every component as a sibling of `specs`, builds a 3.12 virtualenv per Python repo with dev extras, sets up `ui` (npm + codegen), and activates the pre-commit hooks. Prerequisites: Python 3.12 (`winget install Python.Python.3.12`), `git`, `gh` (authenticated via `gh auth login`), and Node.js. Re-running is safe — it skips repos already cloned and venvs already built.

## Conventions

- **camelCase** field names throughout — with one deliberate exception. The gateway's `/v1/chat/completions` and `/v1/models` use **snake_case** and OpenAI's error envelope, because "OpenAI-compatible" is worth nothing unless an unmodified OpenAI SDK can point its `base_url` at us and work. House style does not get to break every client.
- **RFC 7807 `problem+json`** for errors everywhere else.
- **SSE** for one-way streams, framed exactly as OpenAI frames them on the compatible surface.
- Every component implements the same config trio — `GET /v1/config`, `GET /v1/config/schema`, `PATCH /v1/config` — with rich UI metadata, so one generic editor manages all of them. This started as an internal convention; it is now a product feature.

## Architectural commitments

These are settled. Don't relitigate them in PRs without a strong reason.

- **Never ship an inference engine.** Wrap upstream, track it, don't fork it.
- **The user's model files stay in user-chosen directories.** No content-addressed cache. Non-negotiable.
- **Two layers: a routing gateway above N per-backend drivers.** Never collapsed.
- **OpenAPI 3.1** for everything. HTTP+JSON for control, SSE for one-way streams, WebSocket+JSON for bidirectional. gRPC/Protobuf deferred until a concrete hot-path need emerges.
- **Polyrepo**, no shared `core` library. Components share *schemas* (this repo), not code.
- **Apache 2.0** — explicit patent grant matters in AI/ML; chosen by PyTorch, Kubernetes, vLLM, llama.cpp.
- **Open-core**. Core stays Apache 2.0 forever. Future commercial add-ons live in *physically separate repos* under commercial license.
- **DCO**, no CLA. See [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Mesh VPN (Tailscale / WireGuard)** for component-to-component transport between hosts; user-facing auth lives at the gateway and the agent.

## History

Eugene Plexus began in May 2026 as a consciousness framework wrapping commercial LLMs, then grew a from-scratch LLM training platform in June 2026. **Both were retired as of 2026-09-08.** The code still exists and worked; it is archived, not deleted. If you find consciousness or training concepts in old commits or tags, they are historical — `main` is the control plane.

The name is a legacy of that era and was kept deliberately, which is why this README does the work a descriptive name would have done for free.

## Versioning

- This repo follows [SemVer](https://semver.org). `0.x` means breaking changes can land on minor bumps; pin exactly until 1.0.
- Each OpenAPI document carries its own `info.version`. The repo tag is the umbrella version.
- Breaking schema changes require a major (or pre-1.0 minor) bump and a migration note in the changelog.
- Cross-component release notes live in [`CHANGELOG.md`](CHANGELOG.md).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
