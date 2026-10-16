# Eugene Plexus — `specs`

[![CI](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/eugene-plexus/specs/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI-3.1-6BA539.svg)](https://spec.openapis.org/oas/v3.1.0)

**Manage local AI engines, model files and application access from your browser.**

[Install Eugene Plexus](https://eugeneplexus.com/install/) ·
[See it in use](https://eugeneplexus.com/#uses) ·
[Release notes](docs/releases/v0.2.3.md)

**[v0.2.3](https://github.com/eugene-plexus/specs/releases/tag/v0.2.3) is the
latest release**, published 2026-10-15. It is early software, with rough edges
and [known limits](#current-status).

## What is Eugene Plexus?

**A self-hosted control plane for local LLM inference.**

Eugene installs and supervises upstream inference engines, keeps models as
plain files in your own folders, and gives your applications one address for
local models and any cloud backends you choose to connect. Start on one
computer and add more machines as your setup grows.

1. **Engine setup and restarts.** Install and manage llama.cpp, MLX on Apple
   silicon, or experimental Strata from the browser. Connect a vLLM
   installation you already have. Crashed engines restart; idle models can
   unload and wake when an app needs them.
2. **Settings that start with your hardware.** See model and memory-fit
   guidance before downloading, then save per-model launch settings. Fit
   estimates guide a launch; they do not predict speed or shared-service capacity.
3. **Your model files, in your folders.** Search model catalogues, download
   with progress and resume, or scan models already on disk. Removing Eugene
   preserves your original model folders.
4. **One endpoint for your applications.** Use OpenAI-compatible APIs,
   including chat, embeddings and Responses, plus an Anthropic Messages
   subset. Connect tools such as Claude Code, Codex and Open WebUI with their
   own revocable keys. See the [API compatibility limits](docs/api-compatibility.md).
5. **Keep the backends you already use.** Connect existing HTTP servers,
   cloud accounts and supported CLI backends. Routing can keep a conversation
   with the replica holding its prompt cache and fail over when retry is safe.
   See [cache-aware balancing](https://eugeneplexus.com/cache-aware-balancing/)
   and the [failover rules](docs/design/failover-safety.md).
6. **Use it from your other devices.** Sign in from your phone or another
   computer over a trusted LAN or a private network such as Tailscale.
7. **Grow into a homelab.** Manage machines from one console, keep a model
   library on a NAS, and let workers keep local copies of the models they run.

For everyday chat, install [**Workbench**](https://eugeneplexus.com/workbench/)
from **Apps** in the console. It supports documents with sources, saved memory,
and tools you approve. v0.2.3 adds supported MCP Apps, A2UI forms and AG-UI
conversations, plus central account groups and a redesigned operations dashboard.
Open WebUI is also available from Apps.

## Current status

v0.2.3 has versioned installers and a Linux amd64 container image. Its
[release checks](docs/acceptance/v0.2.3-release-run.md) include packaged Windows
and WSL installs with real CPU model replies, Linux system-service update
checks, macOS runner checks, and container acceptance.

Hardware and first-time-user verification remain uneven:

- Windows and WSL have real inference evidence, including NVIDIA GPU runs.
  Those runs do not establish support for every device or unattended boot scenario.
- MLX has run on GitHub's macOS runners; physical Mac installation, reboot and
  real-size model workloads remain unverified. AMD, Intel, modest-memory and
  multi-GPU configurations have varying levels of evidence.
- Strata remains experimental. The container's GPU path still needs a physical
  hardware check. API compatibility is a documented subset of vendor features.
- [Observed first-time-user sessions](docs/acceptance/hobbyist-sessions.md)
  remain incomplete; one outside Windows installation was reported successful.

The [support matrix](docs/support-matrix.md) records measured, simulated,
pending and unsupported cases through v0.2.0; read it with the
[v0.2.3 changes and release limits](docs/releases/v0.2.3.md).
Development priorities live in the [audience roadmap](docs/design/audience-roadmap.md).

## Installing it

Start with the [installation guide](https://eugeneplexus.com/install/) for
requirements, first setup, your first reply and troubleshooting. A small first
model needs about 16 GB of RAM and 10 GB of free disk space. You do not need
Python, Node.js, Git or an inference engine installed first.

**Windows:** open PowerShell and approve the administrator prompt.

```powershell
irm https://eugeneplexus.com/releases/v0.2.3/install.ps1 | iex
```

**Linux:** use a terminal as your normal user. The installer asks for `sudo`
when setting up its service; see the guide for systemd and WSL requirements.

```sh
curl -fsSL https://eugeneplexus.com/releases/v0.2.3/install.sh | sh
```

These commands stay on **v0.2.3**. The
[release assets](https://github.com/eugene-plexus/specs/releases/tag/v0.2.3)
include the installer source, component manifest and SHA-256 checksums.
Follow the installer's final instructions to open the browser console.

**Docker / NAS:** use `ghcr.io/eugene-plexus/control-plane:v0.2.3` with the
published [Compose and storage instructions](https://eugeneplexus.com/install/#docker).
The container runs the console, control root, gateway and model library. It
can also run models on its CPU or a passed-through NVIDIA GPU; the GPU path
has not been verified on physical hardware. A separate Windows or Linux
worker can run the models instead.

**Mac:** the installer supports Apple silicon and native arm64 Python,
including from a Rosetta terminal. See the
[Mac installation guidance](https://eugeneplexus.com/install/#mac) and the
verification limits above before trying it.

**Updating:** make a checkpoint using the [backup and recovery guide](docs/recovery.md),
then update the control root before the other machines. Once the root runs
v0.2.2, **Machines → Versions → Update all** coordinates the remaining machines
and installed catalogue apps, including Workbench. Containers use their host's
update controls; a root requiring a manual update pauses the remaining work. Follow the
[update instructions](https://eugeneplexus.com/install/#update) for your current
version; do not run an older installer over a newer installation.

**Removal:** v0.2.2 includes offline Windows and Mac removal utilities.
On Windows, use **Settings → Apps → Installed apps → Eugene Plexus → Uninstall**.
On Mac, use **Remove Eugene Plexus** in your home folder's **Applications** folder.
They remove the software while keeping settings, app data and downloads by
default, with separate choices to remove retained data. Original model folders
are preserved. See [removal for each installation type](https://eugeneplexus.com/install/#remove)
and the [offline removal guide](docs/deployment/uninstall.md).

## Help and documentation

- [Report a problem or ask a question](https://github.com/eugene-plexus/specs/issues/new):
  include your Eugene version, OS, GPU/RAM, what you tried and the error text.
  Remove credentials and private content from logs or screenshots.
- [Application setup guides](https://eugeneplexus.com/guides/) and
  [client keys and revocation](docs/client-keys.md).
- [Architecture overview](https://eugeneplexus.com/architecture/) and
  [full design](docs/design/local-inference-control-plane.md).
- [Contributing](CONTRIBUTING.md): code contributions use DCO sign-off.

## About this repository

`specs` holds the OpenAPI 3.1 contracts, installers, release records and design
documents for Eugene Plexus. It is the source of truth for cross-component
interfaces. Consumers pin a revision and generate models or clients from it;
components share **schemas, not code**. Retired repositories retain historical
pins and do not consume today's contracts.

## Layout

```
openapi/
  gateway.yaml              the OpenAI-compatible front door; routing + failover
  inference-driver.yaml     the uniform surface over one backend (N instances)
  library.yaml              the operator's model directories, scanned + profiled;
                            catalogue search, downloads, quant guidance
  agent.yaml                per-host supervision, engine lifecycle, enrollment
  control.yaml              trust root, node registry, replicated control state
  tool-driver.yaml          server-run tools, including web search
  site-host.yaml            a person's Job Site enrollment and local tools
  components/
    common.yaml             shared schemas (messages, errors, config protocol, auth)
    ...                     client keys, sites and Job Sites
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
| tool-driver      | [`tool-driver`](https://github.com/eugene-plexus/tool-driver)           | 8190                   | Server-run tools, including web search, per account |
| ui               | [`ui`](https://github.com/eugene-plexus/ui)                             | 3000 dev / 8079 served | Config editor, runtime dashboard, library browser, discovery, chat playground, logs                                                                                                      |
| Workbench        | [`workbench`](https://github.com/eugene-plexus/workbench)               | assigned at install    | Chat app with documents, memory and approved tools; signs people in with Eugene |
| site-host        | [`site-host`](https://github.com/eugene-plexus/site-host)               | loopback               | A person's Job Site enrollment and tools running under their own OS account |
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
| Auth          | receives the trust bundle's path + a token for its own machine, never a key; the control root owns its auth | gets none; fronted by a driver  |

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

## Setting up a dev environment

Eugene Plexus is a polyrepo targeting **Python 3.12** — every component pins `requires-python = ">=3.12"`, ruff `target-version = "py312"`, and mypy `python_version = "3.12"`, and CI runs on 3.12. Develop on 3.12 so local matches CI.

One command does the whole polyrepo — it needs only `git`, because `uv` brings
its own Python and every repo is public:

```sh
git clone https://github.com/eugene-plexus/specs
sh specs/scripts/bootstrap.sh     # Windows: powershell specs/scripts/bootstrap.ps1
```

It clones the core development repos as siblings, gives each Python repo a
3.12 virtualenv with `[dev]` and pre-commit hooks, sets up `ui` and `website` with npm, builds
the UI export, and installs every component into the **agent's** virtualenv —
which is the step that matters, because the supervisor spawns children with its
own interpreter. Pass `--root DIR` / `-Root DIR` to build it somewhere else.
Node is optional; without it the two Node repos are skipped and the dev agent
serves no browser half.

Workbench and site-host have their own development instructions in their
repositories; this bootstrap does not set them up.

The rest of this section describes what that automates. Committed generated
files already match each consumer's pin;
regenerate when changing the pin or verifying freshness.

The step worth understanding, because it is the one people skip when setting up
by hand: both bootstrap scripts install every component into the **agent's**
venv as well as its own. That is not redundancy. The agent supervises children
by spawning them with its own `sys.executable`, so a component missing from the
agent's environment cannot be started by it at all — and on a first boot the
agent checks with `find_spec` and declines to declare what it cannot import,
leaving a working supervisor with nothing to supervise.

Since the UI became a Python package, the same applies to it: without
`eugene-plexus-ui` in the agent's venv you get the API and a "no web UI
installed" page. The scripts install it editable, so `npm run build:python` in
`ui` is immediately visible to a running agent.

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
- **Eugene's own per-node keys** authenticate components to each other on any network. Machines on one private network (a LAN, or a mesh the owner runs) talk directly; a machine outside reaches the root only over a node-only route that carries signed node traffic and nothing else (Job Sites, [`docs/design/remote-nodes.md`](docs/design/remote-nodes.md)). No cloud service is required in the path. The control root owns install-wide trust; enrolled agents distribute credentials to their children, and user-facing endpoints enforce bearer auth.

## History

Eugene Plexus began in May 2026 as a consciousness framework wrapping commercial LLMs, then grew a from-scratch LLM training platform in June 2026. **Both were retired as of 2026-09-08.** The code still exists and worked; it is archived, not deleted. If you find consciousness or training concepts in old commits or tags, they are historical — `main` is the control plane.

`connector` is deferred; `memory`, `identity`, `coordinator`, `trainer`, `data`,
`eval` and `inference` are retired. These labels describe project scope.
Historical pins and documentation are retained.

The [September 2026 README status snapshot](docs/history/readme-status-2026-09.md)
preserves the earlier development status and review findings. Subsequent fixes
are recorded in the [release roadmap](docs/design/release-roadmap.md); use
[Current status](#current-status) above for the released product.

## Versioning

- This repo follows [SemVer](https://semver.org). `0.x` means breaking changes can land on minor bumps; pin exactly until 1.0.
- Each OpenAPI document carries its own `info.version`. The repo tag is the umbrella version.
- Breaking schema changes require a major (or pre-1.0 minor) bump and a migration note in the changelog.
- Cross-component release notes live in [`docs/releases/`](docs/releases/).
  [`CHANGELOG.md`](CHANGELOG.md) retains earlier development entries.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
