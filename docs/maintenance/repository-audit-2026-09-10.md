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

| Item                                             | Why it remains open                                                                                                                                                                                       |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows bootstrap and VS Code task migration     | Existing script still clones retired/renamed repos and omits control/library; task descriptions retain the old topology. Behavior changes are outside this pass. README now warns against the stale path. |
| Dependency maintenance                           | Existing Dependabot PRs and grouping policy were not merged, closed or changed. Retired repos remain writable, so automation may continue until explicitly disabled.                                      |
| Website and namespace administration             | Domain content, registration and package publication were not changed or audited.                                                                                                                         |
| Historical release/tag documentation             | Preserved as historical evidence; not rewritten to imply current support.                                                                                                                                 |
| Security reporting policy and adversarial review | No new reporting channel or response-time promise was invented. The control-root security design still needs adversarial review.                                                                          |

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