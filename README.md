# Eugene Plexus — `specs`

[![CI](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI-3.1-6BA539.svg)](https://spec.openapis.org/oas/v3.1.0)

OpenAPI 3.1 contracts for every cross-component interface in [Eugene Plexus](https://eugeneplexus.com).

This is the **single source of truth** for how Eugene Plexus components talk to each other. The six active consumers (`agent`, `control`, `gateway`, `inference-driver`, `library`, and `ui`) depend on a pinned revision via codegen, never via direct import. Retired repos retain historical pins; they do not consume today's contracts. Components share *schemas, not code*.

## What is Eugene Plexus?

**A self-hosted control plane for local LLM inference.**

It supervises engine processes it does not own, manages a model library on your own disk, holds per-model settings profiles, exposes one OpenAI-compatible endpoint that routes across local runtimes and cloud providers with failover, and serves a web UI with real auth so it works over a tailnet — not just localhost.

**It is not an inference engine.** We supervise upstream llama.cpp and user-installed vLLM; MLX integration is planned. We do not fork or replace the engines.

Everyone else builds an *engine* (llama.cpp, vLLM, MLX) or a *desktop chat app* (LM Studio, llama.app). The operations layer — supervise, configure, route, authenticate — is unclaimed. That layer is the product:

1. **It supervises engines it doesn't own,** and manages their binaries so you don't install llama.cpp by hand first.
2. **Discovery and download happen in the app.** Search a catalogue, read what a model is, pick a quant, download with resume and progress.
3. **Your model files stay yours.** Point it at your existing GGUF directories; downloads land *there*, as plainly-named files. No content-addressed cache, no hash mismatches. Delete us and you still have your models, correctly named, where you put them.
4. **Schema-driven config UI with per-model profiles.** Every knob is a form field with help text and defaults, generated from the config schema the component already publishes.
5. **Networked-first, with auth.** Headless server, browser UI, tokens.
6. **Hardware-aware quant guidance, on the discovery screen.** `Q3_K_S` or `Q4_K_M` is a question you should be answered at the moment you are asking it, not in a separate tool.
7. **Many backends at once, load-balanced, with failover.** Several models resident simultaneously; replicas balanced by outstanding requests and capacity; a priority-list cascade when a backend dies. Drivers can front local engines, hosted APIs, and subscription CLIs.

Full design: [`docs/design/local-inference-control-plane.md`](docs/design/local-inference-control-plane.md).

## Current status

As of **2026-09-11**, this is a pre-1.0 control plane under active development. Milestones M0 through M9 are built, and each has a re-runnable acceptance script rather than a claim.

- **Live-verified on real hardware:** llama.cpp *and* vLLM supervision, model scanning and profiles, catalogue search and resumable downloads, quant guidance, replica balancing, priority-tier failover, idle unload, wake on demand, memory admission, and retained per-request metrics.
- **Multi-host is proven on two real machines** (Windows + WSL2 Ubuntu, across NAT and a host firewall): non-loopback binds, derived advertise addresses, a cross-host completion, an idle unload decided on one host and executed on the other, and a full signing-key rotation. Enrollment, un-enrollment and address re-advertisement all run from a terminal on the machine being added.
- **The browser path is verified too**, as of M9: Playwright drives first run, login, restart-on-login and the topology-resolved proxy against a live install.
- **Still unverified:** a rotation with a genuinely offline node, clock skew between hosts, a partitioned-but-alive old control root, two-GPU placement, and AMD/Intel/Apple memory detection. **MLX has no adapter** — it is the last engine named above that is not implemented.
- **Known gaps:** a short post-unload routing window found by M7 and never diagnosed; ~116 ms of HTTP-driver-path overhead, measured but not explained; rolling engine upgrades; and, in the UI, no structured model-slot editor and only one control-root screen (`/nodes`). The agent still serves the UI assets; moving them to the control root is undecided.

Records: [M9](docs/acceptance/m9-onboarding-run.md) ·
[M7 on two hosts](docs/acceptance/m7-two-host-run.md) ·
[M4 vLLM](docs/acceptance/m4-vllm-run.md) ·
[M8 metrics](docs/acceptance/m8-metrics-run.md) ·
[M6](docs/acceptance/m6-six-process-run.md).
Deploying over a tailnet: [`docs/deployment/tailnet.md`](docs/deployment/tailnet.md).

## Layout

```
openapi/
  gateway.yaml              the OpenAI-compatible front door; routing + failover
  inference-driver.yaml     the uniform surface over one backend (N instances)
  library.yaml              the operator's model directories, scanned + profiled;
                            catalogue search, downloads, quant guidance
  agent.yaml                per-host supervision, engine lifecycle, enrollment
  control.yaml              trust root, node registry, replicated control state
  components/
    common.yaml             shared schemas (messages, errors, config protocol, auth)
```

## Shape

Two layers, never collapsed: a routing `gateway` above N per-backend `inference-driver` instances.

| Component        | Repo                                                                    | Port                   | Job                                                                                                                                                                                      |
| ---------------- | ----------------------------------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| node agent       | [`agent`](https://github.com/eugene-plexus/agent)                       | 8079                   | One per host. Supervises components and engines; owns adapters, admission, local topology and logs; currently serves UI assets                                                           |
| control root     | [`control`](https://github.com/eugene-plexus/control)                   | 8083                   | Install trust root, node registry, union topology, single-writer replicated log and warm standbys. Spawns nothing                                                                        |
| gateway          | [`gateway`](https://github.com/eugene-plexus/gateway)                   | 8080                   | One OpenAI-compatible endpoint. Model → driver resolution, load balancing, priority-list failover. **No backend knowledge.**                                                             |
| inference-driver | [`inference-driver`](https://github.com/eugene-plexus/inference-driver) | 8081                   | **One instance per backend.** Owns provider choice, model id, secrets and health; generation parameters come from the gateway                                                            |
| library          | [`library`](https://github.com/eugene-plexus/library)                   | 8082                   | The operator's own model directories: recursive scan (GGUF + safetensors), metadata, per-model launch profiles; catalogue search, resumable downloads, quant table, hardware fit scoring |
| ui               | [`ui`](https://github.com/eugene-plexus/ui)                             | 3000 dev / 8079 served | Config editor, runtime dashboard, library browser, discovery, chat playground, logs                                                                                                      |
| specs            | this repo                                                               | —                      | Contracts; consumers codegen from a pinned SHA                                                                                                                                           |

The layering matters and is not an accident of history. A driver belongs *next to its engine*, so it can run on a remote GPU host while the gateway reaches it over the tailnet — that is the whole multi-host story. Two replicas of one model on two GPUs need N independently-configured backends with something above them. And `claude_code_cli` / `codex_cli` are subprocess backends with no endpoint to proxy to, so a driver has to be able to sit in the request path regardless.

### Components vs. runtimes

The agent supervises two different kinds of process and keeps them in separate collections, because they share only their supervision *mechanics*:

|               | Component (`/v1/components`)                                                       | Runtime (`/v1/runtimes`)        |
| ------------- | ---------------------------------------------------------------------------------- | ------------------------------- |
| What it is    | a Eugene Plexus process                                                            | a third-party engine binary     |
| How it starts | `<python> -m <module>`                                                             | argv built by an engine adapter |
| Readiness     | the shared `/healthz`                                                              | engine-specific probe           |
| Config        | the standard config trio                                                           | curated engine flag surface     |
| Auth          | receives signing key + service token, except the control root, which owns its auth | gets none; fronted by a driver  |

`ComponentKind` contains exactly `gateway`, `inference-driver`, `library`, and
`control`. The agent and UI are processes but are not members of that enum.
Ports above are defaults, not fixed assignments for every instance.

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

## Installing it

One command on any machine, from nothing — no Python needed first, because
`uv` brings its own:

```sh
curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.sh | sh
```

```powershell
irm https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.ps1 | iex
```

Both install into a single prefix they own, write an autostart unit (systemd
user unit, launchd agent, or a Windows logon task — a real Windows service if
you run it elevated), start it, and print the URL. `--uninstall` / `-Uninstall`
undoes it, keeping your config and logs. A worker node for an existing install
joins in the same command: `--join <control-root-url> --token <jwt>`.

Nothing is published to PyPI or npm yet; the installers fetch GitHub archives at
pinned commits. See
[`docs/design/install-paths-and-distribution.md`](docs/design/install-paths-and-distribution.md)
§6.1 and §12 for why, and for what is verified and what is not — macOS and the
Windows service are written but have not been run.

## Setting up a dev environment

Eugene Plexus is a polyrepo targeting **Python 3.12** — every component pins `requires-python = ">=3.12"`, ruff `target-version = "py312"`, and mypy `python_version = "3.12"`, and CI runs on 3.12. Develop on 3.12 so local matches CI.

Clone the **active** repos as siblings on Windows:

```powershell
foreach ($repo in 'specs', 'agent', 'control', 'gateway', 'inference-driver', 'library', 'ui') {
  gh repo clone "eugene-plexus/$repo"
}
```

In each Python consumer, create a Python 3.12 virtualenv and install `.[dev]`;
follow that repo's README and contributor guide. For a supervised local stack,
install the component packages into the **agent's environment too**, because
children use its interpreter. In `ui`, use Node.js 24 to match CI, `npm ci`, and
`npm run dev`. Committed generated files already match each consumer's pin;
regenerate when changing the pin or verifying freshness.

**Do not use the existing bootstrap script as the current setup path.**
[`scripts/bootstrap.ps1`](scripts/bootstrap.ps1) clones the seven live repos,
builds a Python 3.12 venv per repo, and then installs every component into the
**agent's** venv as well. That last step is not redundancy: the agent supervises
children by spawning them with its own `sys.executable`, so a component missing
from the agent's environment cannot be started by it at all, and the agent
declines to declare it on a first boot.

Afterwards there is nothing else to run. Start the agent and it declares and
spawns the control root, gateway and library itself; the browser UI is for
setting a passphrase and pointing the library at your models.

### VS Code Tasks (Windows)

[.vscode/tasks.json](.vscode/tasks.json) is shared in Git; other editor settings
and local task state remain ignored. The tasks use Windows PowerShell 5.1,
[scripts/dev-tasks.ps1](scripts/dev-tasks.ps1) and
[scripts/dev-seed.ps1](scripts/dev-seed.ps1), which share
[scripts/dev-common.ps1](scripts/dev-common.ps1):

- **Start** launches **Agent** and **UI Dev** concurrently, and on a first boot
  that is the whole of getting a control plane running: the agent declares and
  spawns the control root, gateway and library itself. The agent runs from the
  dev install directory, not from a source checkout: everything it persists
  (`agent.yaml`, `node.yaml`, `logs/`, companion driver configs) lands beside its
  config file. Defaults to `.dev-install` beside the repo checkouts;
  `EUGENE_PLEXUS_DEV_INSTALL` overrides it.
- **Finish Install (optional)** is the unattended equivalent of the first-run
  UI, for a dev loop or CI that should not need a browser: it sets the operator
  passphrase on the agent and control root, points the library at a model
  directory, marks first run complete and declares one llama.cpp runtime. It
  does this over the same endpoints the UI uses; there is no privileged path.
  Nothing requires it. It is idempotent, waits for the agent rather than failing
  if run first, and reads the passphrase from `EUGENE_PLEXUS_DEV_PASSPHRASE` or
  a private `SecureString` prompt - never from disk or a command line, and there
  is no recovery path for it by design. `-Model` / `-Binary` override the paths;
  `-SkipRuntime` stops after configuration. Without a llama-server binary the
  install is still configured and the runtime is skipped with a reason.
- **UI Dev** runs the installed Next.js executable on port 3000 and fails if it
  is occupied. `EUGENE_PLEXUS_DEV_UI_PORT` overrides the port for launch and checks.
- **Health Check** reads `/v1/components` and `/v1/runtimes` from the agent, probes
  every discovered component URL, and checks the UI. Degraded/safe-mode services,
  crashed runtimes, missing topology and network/auth failures return exit
  code 1. A `stopped` runtime does not fail the check — idle unload is policy
  working — and neither does one that is still `loading`, which is a snapshot of
  something in progress. Companion drivers are probed whether or not their engine
  is loaded: per the agent contract a companion deliberately keeps running while
  its runtime is stopped, which is what lets the gateway keep listing an
  on-demand model, so a dead one has to surface rather than be skipped.
- **Stop All** is a force-stop fallback: it stops only the Agent/UI launcher
  trees recorded by these tasks, including their supervised descendants. It
  verifies PID, creation time and launcher command; it never selects listeners
  by port. Use Ctrl+C in the task terminals for normal shutdown. Legacy launches,
  detached orphans and other workspaces are deliberately not targeted.

Default agent address: `http://127.0.0.1:8079`. `EUGENE_PLEXUS_AGENT_BIND_PORT`
also updates the UI/check defaults; an explicit `AGENT_URL` overrides their
target. `GATEWAY_URL` remains the UI's gateway bootstrap override. Set bootstrap
environment variables before launching VS Code so tasks inherit them; topology
and model settings still belong in the application config UI.

Health Check accepts `EUGENE_PLEXUS_DEV_TOKEN` from the environment or prompts
privately for an operator token on HTTP 401. Obtain the token through the normal
login flow. It is not stored in task arguments or files, printed, or sent to
discovered health endpoints. Do not put tokens in tracked task definitions.
The check covers one agent's topology, not the install-wide control view.

Run the focused tests with Windows PowerShell (Pester 3.4.0 and Node.js):

```powershell
Import-Module Pester -RequiredVersion 3.4.0
Invoke-Pester -Script ./scripts/dev-tasks.Tests.ps1 -EnableExit
```

The tests use mocks and temporary synthetic processes, not your running stack.

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
- **Apache 2.0** — permissive adoption with an explicit patent grant.
- **Open-core**. Core stays Apache 2.0 forever. Future commercial add-ons live in *physically separate repos* under commercial license.
- **DCO**, no CLA. See [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Mesh VPN (Tailscale / WireGuard)** for component-to-component transport between hosts. The control root owns install-wide trust; enrolled agents distribute credentials to their children, and user-facing endpoints enforce bearer auth.

## History

Eugene Plexus began in May 2026 as a consciousness framework wrapping commercial LLMs, then grew a from-scratch LLM training platform in June 2026. **Both were retired as of 2026-09-08.** The code still exists and worked; it is archived, not deleted. If you find consciousness or training concepts in old commits or tags, they are historical — `main` is the control plane.

The organization contains **15 repositories: seven active, one deferred, and seven
retired**. `connector` is deferred; `memory`, `identity`, `coordinator`, `trainer`,
`data`, `eval`, and `inference` are retired. None is GitHub-archived: status labels
describe project scope, not read-only repository settings. `cluster` is not an
existing repository. Historical pins and documentation are retained.

The name is a legacy of that era and was kept deliberately, which is why this README does the work a descriptive name would have done for free.

## Versioning

- This repo follows [SemVer](https://semver.org). `0.x` means breaking changes can land on minor bumps; pin exactly until 1.0.
- Each OpenAPI document carries its own `info.version`. The repo tag is the umbrella version.
- Breaking schema changes require a major (or pre-1.0 minor) bump and a migration note in the changelog.
- Cross-component release notes live in [`CHANGELOG.md`](CHANGELOG.md).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
