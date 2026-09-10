# Repository Maintenance - 2026-09-10

Non-code cleanup after the local-inference control-plane pivot. GitHub metadata
and local checkouts were inspected directly; older bootstrap summaries were not
treated as authoritative where they contradicted the milestone records.

## Repository Inventory

| Repository                                                            | Status   | Current role or historical scope                                         |
| --------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------ |
| [specs](https://github.com/eugene-plexus/specs)                       | Active   | OpenAPI contracts, architecture and acceptance records                   |
| [agent](https://github.com/eugene-plexus/agent)                       | Active   | Per-host process supervision, engine lifecycle, admission and enrollment |
| [control](https://github.com/eugene-plexus/control)                   | Active   | Install trust root, node registry and replicated control state           |
| [gateway](https://github.com/eugene-plexus/gateway)                   | Active   | OpenAI-compatible routing, balancing, failover and lifecycle policy      |
| [inference-driver](https://github.com/eugene-plexus/inference-driver) | Active   | One backend protocol adapter per instance                                |
| [library](https://github.com/eugene-plexus/library)                   | Active   | Model metadata, profiles, discovery, downloads and fit guidance          |
| [ui](https://github.com/eugene-plexus/ui)                             | Active   | Browser control surfaces and same-origin proxy                           |
| [connector](https://github.com/eugene-plexus/connector)               | Deferred | Historical chat-platform bridge; current gateway integration unbuilt     |
| [memory](https://github.com/eugene-plexus/memory)                     | Retired  | Former consciousness conversation storage                                |
| [identity](https://github.com/eugene-plexus/identity)                 | Retired  | Former constitution, self-model and person records                       |
| [coordinator](https://github.com/eugene-plexus/coordinator)           | Retired  | Former training pipeline coordinator                                     |
| [trainer](https://github.com/eugene-plexus/trainer)                   | Retired  | Former training execution and checkpoints                                |
| [data](https://github.com/eugene-plexus/data)                         | Retired  | Former dataset preparation and tokenization                              |
| [eval](https://github.com/eugene-plexus/eval)                         | Retired  | Former training evaluation and checkpoint comparison                     |
| [inference](https://github.com/eugene-plexus/inference)               | Retired  | Former training platform's serving implementation                        |

**15 repos: seven active, one deferred, seven retired.** `cluster` does not exist.
No repo is GitHub-archived. Retirement is a project status, not a read-only flag.
All six active codegen consumers pin `a0d793e`; documentation changes do not
require re-pinning. Inactive repos retain historical pins whose contracts were
removed from current specs.

## Changes and Decisions

- Descriptions, topics and homepage links now describe the current project.
  Active repos no longer advertise consciousness/bicameral topics. The GitHub
  organization description was empty and now identifies the inference control plane.
- Homepage links point to the maintained specs README, not an unaudited website.
- Active READMEs distinguish implemented features, live verification and open
  gaps. Inactive README bodies remain historical beneath dated notices.
- Contributor guides use current repo/contract names. The library's copied driver
  guide was corrected. Specs guidance names all six consumers and the codegen
  input-list/pin coupling.
- The operator requested signed-off commits and pushes to `main`, and explicitly
  chose **not** to archive repositories. No releases, tags, branches, permissions,
  branch protections, dependency upgrades or workflow changes are part of this pass.
- The ignored local `CLAUDE.md` is a bootstrap aid, not a published project doc.
  Its stale status claims were reconciled locally; it must not be force-added.

## Deferred Work

| Item                                             | Why it remains open                                                                                                                                                               |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows bootstrap migration                      | Existing bootstrap script still clones retired/renamed repos and omits control/library. README warns against that setup path. VS Code tasks were migrated in the follow-up below. |
| Dependency maintenance                           | Existing Dependabot PRs and grouping policy were not merged, closed or changed. Retired repos remain writable, so automation may continue until explicitly disabled.              |
| Website and namespace administration             | Domain content, registration and package publication were not changed or audited.                                                                                                 |
| Historical release/tag documentation             | Preserved as historical evidence; not rewritten to imply current support.                                                                                                         |
| Security reporting policy and adversarial review | No new reporting channel or response-time promise was invented. The control-root security design still needs adversarial review.                                                  |

Product verification gaps remain visible in the [current overview](../../README.md#current-status):
the M7 post-unload routing window, real two-machine failure tests, a real vLLM
launch, two-GPU placement, browser acceptance, and unsupported hardware paths.
These were documented, not fixed or tested by a documentation-only change.

## Validation Scope

Metadata was read back from GitHub to check descriptions, role topics, homepages
and unchanged archive flags. Documentation checks cover local link targets,
current contract paths and removed stale claims. Package TOML/JSON is parsed and
compared with the prior revision to ensure only descriptions changed. Existing
formatting hooks and post-push CI remain the publication gates; no application
behavior or live acceptance run is claimed by this maintenance record.

## Follow-Up: VS Code Tasks

Later on 2026-09-10, the operator approved task migration. The shared task
definition now launches the agent and UI through a Windows helper that records
launcher identity and limits forced shutdown to those process trees. Health
checks discover component URLs and runtime states through the authenticated agent
API, check JSON health status, and exit nonzero on failure. Tokens are neither
tracked nor stored in task state. All other `.vscode` files remain ignored.

Focused Pester tests include real temporary parent/child processes, an unrelated
surviving process, PID reuse, topology-derived ports, HTTP health exit codes and
degraded/unloaded states. A Windows CI job runs these tests; no actual inference
stack is launched or stopped. See the [task guide](../../README.md#vs-code-tasks-windows).

## Follow-Up: A Development Install That Works

Later on 2026-09-10 the task migration above was exercised for the first time
and did not start anything. Three findings, in cost order.

**The agent's persisted config in the local checkout was a v0.2 fossil.** It
declared `orchestrator`, two `hemisphere-driver` entries, `memory`, `identity`
and `connector` — none of which are `ComponentKind` values any more. Loading it
through the agent's own state loader raises a `ValidationError` on the first
entry, and `state.load()` is not guarded at startup, so the agent exits rather
than degrading. Every acceptance script from M0 onward builds a throwaway
install under `$TMPDIR`, so no run had ever loaded the config a developer
actually had. It drifted through four milestones unobserved. The fossil state
(including a `connector` adapter file holding a live Discord bot token, never
committed and gitignored throughout) was moved out of the checkout.

**Nothing took an install from empty to working.** Clearing the fossil produced
a startable agent supervising nothing. The first-run wizard cannot close that
gap — it reads the topology and, by its own documentation, "assumes the operator
has components in the agent topology already and cannot create them." The only
path that has ever produced a running stack is an acceptance script that deletes
its install at the end.

[`scripts/dev-seed.ps1`](../../scripts/dev-seed.ps1) is the first durable path.
It writes each component's config file, then over HTTP initializes the operator
passphrase, declares the three components, initializes the control root, marks
first-run complete, and declares one llama.cpp runtime whose companion driver
the agent creates itself. It is idempotent and it is not a wizard: every step is
one the real first-run flow must take, and the steps that are awkward here are
the ones still missing from the product.

**The health check skipped the component most likely to be broken.** It treated
a stopped runtime's companion driver as intentionally absent. The agent contract
is explicit that the companion keeps running while its engine is stopped,
precisely so the gateway can keep listing an on-demand model — so a dead
companion breaks wake-on-demand and was being reported as merely skipped.
Companions are now always probed; `stopped` and `loading` runtimes no longer
fail the check.

Verified live rather than by fixture, on 2026-09-10: a wiped install, agent
started from it, seeded fresh (exit 0) and seeded again idempotently (exit 0),
six processes running, `GET /v1/models` listing the alias behind its companion,
and a real completion returned through the gateway in 151 ms at tier 1. Health
Check exited 0 with the UI up, and exited 0 on components with the runtime
deliberately stopped — its companion probed and healthy. Twenty-eight Pester
tests pass. Not verified: no browser has driven the UI, so the client-side
first-run redirect is asserted from the config flag, not observed.
