# Eugene Plexus — `specs`

[![CI](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI-3.1-6BA539.svg)](https://spec.openapis.org/oas/v3.1.0)

OpenAPI 3.1 schemas for every cross-component contract in [Eugene Plexus](https://eugeneplexus.com).

This is the **single source of truth** for how Eugene Plexus components talk to each other. Every other repo in the org depends on this one via codegen — never via direct import — to physically enforce the principle that *components share schemas, not code*.

## What is Eugene Plexus?

A consciousness framework that wraps existing LLMs (Claude, GPT, local OSS models) instead of relying on a custom from-scratch model. Treat the LLM as the "neocortex" and build the consciousness scaffolding — bicameral hemispheres, NT system, multi-pass reasoning, memory, sleep consolidation, corpus callosum — as a framework around it.

The **bicameral cross-vendor commitment**: left hemisphere and right hemisphere run on *different* model families (e.g. Claude and GPT). Genuinely different RLHF distributions and priors produce real architectural tension; multi-pass termination maps cleanly to "hemispheres agree → terminate, hemispheres diverge → another pass."

## Layout

```
openapi/
  orchestrator.yaml         user-facing chat API + admin
  hemisphere-driver.yaml    interface every hemisphere adapter implements
  memory.yaml               storage / retrieval interface (v0.1: stub)
  watchdog.yaml             process supervisor + UI host
  components/
    common.yaml             shared schema components (messages, NT state, errors, config protocol)
```

## Repos in the Eugene Plexus v0.1 set

| Order | Repo | Status |
|-------|------|--------|
| 1 | [`specs`](https://github.com/eugene-plexus/specs) | this repo |
| 2 | [`hemisphere-driver`](https://github.com/eugene-plexus/hemisphere-driver) | working |
| 3 | [`orchestrator`](https://github.com/eugene-plexus/orchestrator) | working |
| 4 | [`ui`](https://github.com/eugene-plexus/ui) | working — chat + config editor + first-run wizard |
| 5 | [`memory`](https://github.com/eugene-plexus/memory) | working — v0.1 in-process stub |
| 6 | [`watchdog`](https://github.com/eugene-plexus/watchdog) | working — process supervisor + UI host |

Build order was deliberate: specs first so contracts don't conflict at integration time; hemisphere-driver before orchestrator so the orchestrator integrates against real backends, not mocks; UI before memory because the UI doubles as the debugging surface for hemispheres and NT state. The watchdog was added during the build when first-run UX surfaced the need for a process owning the body components.

## Using these schemas

### Python (Pydantic v2 models)
```bash
pip install datamodel-code-generator
datamodel-codegen \
  --input openapi/orchestrator.yaml \
  --input-file-type openapi \
  --output-model-type pydantic_v2.BaseModel \
  --output gen/orchestrator_models.py
```

### Python (typed async client)
```bash
pip install openapi-python-client
openapi-python-client generate --path openapi/orchestrator.yaml
```

### TypeScript (types)
```bash
npm install -D openapi-typescript
npx openapi-typescript openapi/orchestrator.yaml -o gen/orchestrator.ts
```

We deliberately **avoid the Java-based `openapi-generator`** — verbose output, opinionated templates you fight, heavyweight install.

## Architectural commitments

These are settled. Don't relitigate them in PRs without a strong reason.

- **OpenAPI 3.1** for everything. HTTP+JSON for control, SSE for one-way streams, WebSocket+JSON for bidirectional. gRPC/Protobuf deferred until concrete hot-path need emerges.
- **Polyrepo**, no shared `core` library. Components share *schemas* (this repo), not code.
- **Apache 2.0** — explicit patent grant matters in AI/ML; chosen by PyTorch, Kubernetes, vLLM, llama.cpp.
- **Open-core**. Core stays Apache 2.0 forever. Future commercial enterprise add-ons (SSO, multi-tenancy, compliance, managed hosting) live in *physically separate repos* under commercial license. Core never gets polluted with commercial-only code.
- **DCO**, no CLA. CLAs scare off contributors and the open-core model doesn't need them. See [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Mesh VPN (Tailscale / WireGuard)** for component-to-component auth. User-facing auth lives at the API gateway only; no per-component JWT validation.

## Versioning

- This repo follows [SemVer](https://semver.org). `0.x` means breaking changes can land on minor bumps; pin exactly until 1.0.
- Each OpenAPI document carries its own `info.version`. The repo tag is the umbrella version.
- Breaking schema changes require a major (or pre-1.0 minor) bump and a migration note in the changelog.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
