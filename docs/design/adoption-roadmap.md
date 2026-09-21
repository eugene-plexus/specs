# Adoption roadmap

**Status: current work order, 2026-09-20.** Troy accepted the new adversarial
review and asked to defer further release work in favor of this roadmap.
The previous [release roadmap](release-roadmap.md) is historical: its scheduled
implementation is complete, while the verification obligations below remain
open. Completing implementation is not the same as completing acceptance.

**Pickup: A7.** A1 and A2 completed 2026-09-20; A3-A6 and A6b completed 2026-09-21.
A4's final user-supplied image passed through the actual Open WebUI frontend,
authenticated gateway, driver and local vision model. See
[A4 acceptance](../acceptance/a4-application-workflows.md).
[A1 acceptance](../acceptance/a1-home-readiness-run.md),
[A2 acceptance](../acceptance/a2-request-settings-run.md),
[A3 acceptance](../acceptance/a3-client-keys-run.md).
A5 passed scoped admission across two real gateways, durable recovery and usage
attribution on Windows and Linux; see [A5 acceptance](../acceptance/a5-scoped-keys-run.md).
A6 passed signed local-only routing through real drivers on Windows and Linux;
see [A6 acceptance](../acceptance/a6-local-only-run.md).
Work through A6, A6b, A7 and A8 in order. Troy approved adding A6b on
2026-09-21 and completing these slices before the next release. There is no
release slice, deadline, or duration estimate.
`v0.1.0-alpha.1` is already published and remains the available tester build;
do not retract it, move its tag, or silently replace its assets. A future
publication is a separate decision after reassessment.

The evidence is the private `docs/private/adversarial-adoption-review-2026-09-20.md`
and its isolated probes. That directory is gitignored. This roadmap contains
enough scope and acceptance criteria to execute without that private file.
Do not spend another pass re-establishing the review's findings. A fix starts
with a failing regression check against the affected public behavior; new
design decisions and unmeasured hardware behavior still require investigation.

## Objective and boundaries

Make Eugene dependable for someone operating several inference machines or
backends, then establish the minimum controls and recovery evidence for a small
team sharing that installation. Demonstrate why an existing application is
easier to operate through Eugene than through manually managed endpoints.

The first audience remains enthusiasts with an operational problem Eugene can
solve. A business pilot adds permissions, privacy boundaries, recoverability
and measured capacity. Completing enthusiast work does not imply business
readiness, and business controls need not block ongoing friend sessions.

Preserve the architecture: the gateway owns policy/routing, drivers own backend
protocols, agents own processes and local admission, and control owns install
coordination. Do not add backend-specific request handling to the gateway.
Runtime-start memory admission and request admission are separate concerns.
The existing refusal-first approach does not become an unbounded request queue.

## Closure of the previous roadmap

| Previous work | Disposition |
| --- | --- |
| R1-R8 implementation, including R6's benchmark and S8/S9/S10 automation | Complete as recorded in the previous roadmap; preserve the historical acceptance and limitations. |
| S10 moderated sessions with two or three friends | Open; Troy has these in progress. Continue independently of A1-A8. |
| R2.6 Windows service physical checks | Partly corroborated by the owner's successful migration and service use. Reboot before sign-in and the remaining explicit acceptance checks are not all demonstrated by that report. Carry forward; do not reset successful observations. |
| R3 physical Mac/native Apple Python verification | Open; simulated checks are not physical acceptance. |
| Alpha distribution and installation instructions | Already published, with [recorded acceptance](../acceptance/alpha1-release-run.md). The premature Home composer is assigned to A1. |
| Further release/stable-readiness decision | Deferred by Troy. No publication step in this roadmap. |
| Previously unscheduled work | Remains unscheduled unless explicitly pulled into a slice below. This is not a declaration that every known limitation is fixed. |

The previous roadmap's contemporaneous phrases such as "still owed" and
"before release" are historical. Use this document for the next action.

## Slices and order

| Slice | User-visible outcome | Main dependency |
| --- | --- | --- |
| A1 | The first prompt handles model loading correctly | None |
| A2 | Accepted request settings mean what the caller asked for | None |
| A3 | A revoked key stops working everywhere it is accepted | None; before broader shared access |
| A4 | Supported real applications complete useful local tasks | A1/A2; uses A3 credentials |
| A5 | Keys constrain model access and consumption, with attributable usage | A3 |
| A6 | A local-only workload cannot fall through to a cloud backend | A5 policy, driver capability contract |
| A6b | Failover preserves request policy, deadlines and uncertain outcomes | A6, existing stream commit boundary |
| A7 | A failed update or lost installation has a tested recovery path | Final state from A3/A5/A6/A6b included in backups |
| A8 | Capacity and hardware support claims have measured limits | A4-A7, including A6b |

A1-A6 and A6b are complete; A7-A8 are not started.
Completion entries must name the
implementation revisions, acceptance record, observed limitations and any
remaining physical checks. Do not mark a slice complete solely because unit
tests pass or its code has been written.

## A1 — First prompt through loading

**Completed 2026-09-20.** UI `78e8285`, packaged UI `6090b6c`; both development
installers pinned. Six browser scenarios and 756 UI tests pass. Fresh isolated
Windows and WSL installs each produced a real first response without manual
retry, using a seeded Qwen3-0.6B model and acquired CPU llama.cpp b11065.
[Implementation, timings and limits](../acceptance/a1-home-readiness-run.md).

**Problem:** the alpha's actual first WSL request failed because Home enabled
Send while its runtime was loading. Waiting and resubmitting succeeded; that
does not erase the failure. This concerns the first-use path, not an assertion
that every existing wake-on-demand path is broken.

**Scope:** UI readiness and progress, coordinated with existing gateway wake
behavior. Show the selected model's state and a useful loading explanation.
Disable Send until it can be used, or retain a submitted prompt through a
bounded wait. Choose the interaction during implementation; either must avoid
duplicate requests and preserve text through a recoverable failure. Loading,
failed, unavailable and ready are distinct states. A failed start must not
leave an indefinite spinner.

**Touches:** UI, gateway/agent only where the existing readiness contract needs
correction; the installed first-use acceptance instrument.

**Done when:**

- A browser regression reproduces the alpha behavior before the fix, with a
  deliberately slow but healthy startup and a separate failed startup.
- Fresh isolated Windows and Linux/WSL installs reach an actual first response
  through the packaged UI without knowing when to retry. Record the model,
  engine, hardware and whether the model was seeded or downloaded.
- Ready, loading, stopped/on-demand, crashed and unreachable states behave
  intentionally; navigating away or cancelling does not duplicate work.
- Preserve the original alpha failure record and add new evidence alongside it.

## A2 — Request settings and explicit compatibility

**Completed 2026-09-20.** [Acceptance and captured wire](../acceptance/a2-request-settings-run.md);
[supported feature matrix](../api-compatibility.md). Live updates may wait while
Troy accumulates slices; A2 acceptance used isolated processes.

**Problem:** the chat request model silently drops `max_completion_tokens`.
The real translation then substitutes a profile default. Image content parts
are rejected; other provider feature names are not automatically supported
merely because the endpoint is called compatible.

**Scope:** define and enforce supported request semantics at the API boundary.
Support the completion-limit spelling used by the selected clients, including
precedence/conflict behavior when both token-limit spellings are present.
Normalize before profile/default resolution and preserve the chosen limit on
every attempt and fallback. Treat materially unsupported settings explicitly;
do not indiscriminately reject harmless client metadata without checking the
selected clients. Existing structured-output support must not regress.

Publish a concise endpoint/feature matrix distinguishing supported, explicitly
rejected and unverified behavior. Image input is implemented and validated in
A4. Full compatibility with every provider endpoint, including a new Responses
API implementation, is not implied or automatically in scope.

**Touches:** specs, gateway, driver contract/translation as needed, compatibility
documentation and integration checks.

**Done when:**

- A real HTTP request specifying a 25-token limit reaches the driver with that
  limit despite a 2,048-token profile default. The original implementation
  fails the check. Capture the forwarded request, not only a helper result.
- Both accepted limit spellings, conflicts, invalid limits, streaming,
  cross-model fallback and default resolution have specified behavior.
- Unsupported consequential fields cannot silently change the intended work.
  Errors identify the field without exposing secrets or prompt content.
- Document the semantics each supported engine actually provides; do not claim
  all engines count generated/reasoning tokens identically without measurement.

## A3 — Install-wide key revocation

**Problem:** token acceptance spans the install while revocation records are
node-local. Cache loss and revocation-source outages also need explicit
behavior. Checking a remote list must not serialize a failed network call for
every waiting inference request.

**Scope:** establish one authoritative install-wide client-key lifecycle and
make every accepting gateway obey it. Use the existing control/agent trust and
persistence mechanisms; a second identity service is not a prerequisite.
Write a short design before contract changes: authority, replication/versioning,
standalone behavior, migration of existing node-local records, and outage bounds.
Existing minted keys need an explicit migration disposition, not accidental
invalidation or implicit permanent permission.

Known revocations survive a gateway restart. Persisted policy has an explicit
maximum age; unavailable or too-old policy must not authorize client access
indefinitely. Specify the availability/security tradeoff and a documented
default during design. Operators can still reach the management path needed
to repair the system. Use refresh deduplication and bounded retry/backoff.

**Touches:** agent, control, gateway, specs and key-management UI.

**Done when:**

- A key minted on one node works on two gateways, then revocation through its
  supported management path makes both reject it within the documented bound.
- Repeat through gateway restart, local-agent outage, control outage, stale
  persisted cache, no cache and recovery. Valid/invalid/expired/revoked tokens
  retain distinct intended outcomes.
- Concurrent requests during an outage do not perform N sequential refresh
  timeouts. The acceptance includes actual isolated component processes, not
  only mock transports.
- Existing keys migrate with clear operator-visible status. No private signing
  material is introduced into components that only need verification.

## A4 — Real application workflows, including images

**Problem:** a real-client protocol test with a stub driver and a separate
real-model tool-call test do not prove a complete application workflow. Image
input currently cannot traverse the chat gateway surface.

**Scope:** support two named client paths initially: Claude Code using Anthropic
Messages, and Open WebUI using OpenAI-compatible chat. Record exact client,
model and engine versions when running acceptance; current protocol details
must be measured from those clients. Preserve existing supported clients.

Demonstrate a small coding task against a disposable repository using a real
local tool-capable model: inspect files, propose/apply a bounded change, run its
check and complete a follow-up turn. Demonstrate chat and a user-supplied image
through the second client with a supported local vision model. This is a
supported frontend integration, not a new employee chat/RAG product.

Add bounded image input through the shared message contract and driver path,
with truthful per-model/engine capability reporting. Start with explicitly
supported image types and transport. Define size/count limits and safe handling
of any remote image references; unsupported references must be rejected rather
than fetched arbitrarily. Do not log image payloads or claim image support for
text-only runtimes. Image support is real implementation scope, not satisfied
by relabeling every model text-only.

**Touches:** shared schemas, driver and gateway translation, runtime capabilities
where necessary, connection recipes and acceptance scripts.

**Done when:**

- Both applications complete the stated tasks through a real gateway, driver
  and local model, with auth enabled and no stub output in the task result.
- The coding run includes a completed tool-result round trip and follow-up;
  a protocol trace alone is insufficient. Keep tool permissions confined to
  the disposable task and record model-quality failures separately.
- The image reaches the supported local backend, produces a grounded answer,
  and text-only targets reject it clearly. No fallback silently discards it.
- Cold loading, streaming, cancellation and an actionable backend failure are
  exercised. Recipes are usable by someone who did not write the integration.
- A compact task/versions/results matrix says exactly what was demonstrated.

## A5 — Scoped keys, consumption limits and attributable usage

**Completed 2026-09-21.** Model scopes, shared concurrency/rate admission, renewable
reservations and attributable per-key metrics are implemented. The UI manages new
and existing key limits, with explicit unrestricted legacy records. See
[A5 acceptance](../acceptance/a5-scoped-keys-run.md) and
[operator instructions](../client-keys.md).

**Problem:** named keys distinguish credentials from operator sessions, but do
not define which models an application may use or how much shared capacity it
may occupy. Retained request metrics do not attribute usage to the key.

**Scope:** per-key allowed models, bounded request concurrency and request-rate
limits, plus usage attribution by stable key ID/name. Include queued/waking
work in the accounting so on-demand loading cannot bypass the limit. Account
for actual fallback targets, not only the alias requested. Model lists must
respect the caller's permissions. Keep revocation and administration separate.

Choose and state the enforcement scope across multiple gateways; limits cannot
silently multiply with each gateway. Design the coordination/failure behavior
using the existing topology, not a new mandatory database/service. Local-only
constraints extend this policy in A6. Pricing/billing and monetary budgets are
not required for the initial local-inference pilot.

Prefer bounded admission/refusal with useful retry guidance over an unbounded
queue. Clean up reservations on cancellation, timeout, failed wake and client
disconnect. Existing keys get an explicit compatibility/migration policy;
new-key UI makes permissions and limits understandable. Do not retain prompts
to obtain attribution, or trust an arbitrary caller-supplied `user` value as
the authenticated identity.

**Touches:** key schemas/storage, gateway authorization/admission and metrics,
coordination where needed, UI and documentation.

**Done when:** two keys with different permissions and limits cannot read/use
each other's excluded model targets, exceed their documented allowance by
changing gateways, or retain capacity after cancellation. Normal operator
management still works. Usage totals identify each key through retries,
streaming and failures without recording credentials, prompts or images.

## A6 — Enforced local-only routing

**Completed 2026-09-21.** Per-key local-only policy, explicit active-engine
classification, checks before wake/fallback and driver-side refusal against
stale metadata. [Implementation and acceptance](../acceptance/a6-local-only-run.md).

**Problem:** an installation may intentionally mix local and cloud providers,
but sensitive workloads need a constraint stronger than operator convention.
Purely local installs are not assumed to leak to cloud by default.

**Scope:** a local-only restriction attached to a key or route that is checked
against every primary/fallback candidate before forwarding or waking it. Use
an explicit backend locality/trust contract reported through the driver layer;
the gateway must not infer privacy from a friendly model name or URL syntax.
Cloud-backed CLI subscriptions remain external even though their processes
run locally. Unknown classification is ineligible for local-only work. A request
cannot loosen the key's policy. Route changes and stale capability data cannot
bypass it. Explain the actual serving node/model in diagnostics.

This is a routing guarantee over the configured backend trust boundary, not a
claim to sandbox a malicious engine or prevent an administrator from changing
the host. Record that boundary and any recommended network-level controls.

**Touches:** driver capabilities, routing/policy schemas and enforcement, UI.

**Done when:** a local-only key continues using eligible local replicas but
refuses clearly when only a configured cloud or unknown target remains. A
counting external stub receives zero prompt/image requests in those cases,
including outage, fallback, alias, stale-cache and configuration-change paths.
A separate permitted key can still use the intended cloud route. No secret
or content appears in rejection diagnostics.

## A6b — Failover safety

**Completed 2026-09-21.** Gateway `4ead7e8`, driver `352993a`, UI `eea85b9`,
packaged UI `0e3a202`; both development installers pinned. Windows and Linux
process fixtures prove safe rescue, no ambiguous replay, deadline/disconnect
cancellation, cooldown/recovery and retained uncertainty. Signed A5/A6 acceptance
still passes. [Evidence and limits](../acceptance/a6b-failover-safety-run.md).

**Problem:** no response does not prove no work occurred. Existing protection
against switching after streamed output and retrying a timed-out generation
does not establish safe retries for every transport/server failure, a total
request deadline, or controlled recovery of an overloaded backend.

**Scope:** classify attempts as safe to retry, terminal, or indeterminate.
Do not automatically replay ambiguous work, including CLI-internal actions.
Keep the first text/tool fragment as the stream commit boundary. Carry one
request identifier across gateway/driver attempts and enforce a single elapsed
time budget over preparation, wake, generation and fallback. Cancel owned work
on disconnect or expiry; do not claim cancellation proves the remote provider
stopped computing.

Preserve provider retry hints, impose bounded cooldowns and controlled recovery
rather than immediately returning every new request to a failing primary.
Every fallback must preserve the request's required capabilities and A5/A6
permissions. Record attempt outcomes and total elapsed time, distinguish known
usage from unknown usage on failed attempts, and never equate unknown usage
with zero cost. Billing integration is outside this slice.

The gateway does not promise exactly-once external tool effects: execution,
idempotency and reconciliation remain responsibilities of the tool executor.
Refuse an unsafe automatic retry with an intelligible reason.

**Touches:** shared driver failure/policy contract, gateway request lifetime,
routing, metrics/diagnostics, operator documentation and isolated acceptance.

**Done when:** counting HTTP/CLI fixtures prove safe connection failure and
overload recovery, no automatic replay of ambiguous work, no mixed output after
partial text/tool fragments, no attempt after the total deadline, cancellation
and admission cleanup, cooldown/recovery without repeated primary hammering,
and zero requests to policy- or capability-ineligible fallbacks. A shared request
ID links attempts, and incomplete usage remains visibly incomplete. Include
streaming, non-streaming, embeddings, aliases and configuration changes where
applicable. Keep live installs and frozen release artifacts unchanged.

## A7 — Restore and failed-update recovery

**Problem:** installing packages into the active environment and advising a
configuration backup does not establish a usable recovery procedure. Source
pins alone do not reconstruct Python dependencies and engine versions.

**Scope:** define a versioned backup inventory and documented restoration path
for configuration, profiles, identity/trust state, encrypted secrets and the
credentials needed to unlock them, client-key policies/revocations, and relevant
component stores. Classify expendable logs/caches separately. Models may remain
external; inventory their paths/checksums and engine/build dependencies rather
than requiring a huge duplicate model archive. Protect backup secrets and file
permissions, validate restored state, and prevent a copied identity from
advertising alongside the original during a test restore.

Record the exact installed Eugene revisions, resolved Python dependencies,
Python and engine versions needed for a known-good recovery. Provide a
repeatable way to reinstall that known-good environment. A version manifest
that lists packages but cannot reconstruct them is not sufficient. Stage an
update or preserve the previous environment so a failed attempt has a tested
way back; never assume installing an old alpha reverses schema migrations.

A documented manual rollback is acceptable for this slice. Full automatic
rollback, offline distribution, byte-reproducible builds and rolling engine
upgrades are separate work, not hidden prerequisites.

**Touches:** installers, backup/restore tooling and schema compatibility where
needed, operational documentation and isolated acceptance.

**Done when:** restore a Windows worker and container control-plane backup into
isolated replacement locations, authenticate, recover profiles/policies and
serve a real request. Previously revoked keys remain revoked. Inject a failed
update after the old environment stops and recover with the written procedure.
Test missing/wrong unlock material and incompatible versions without damaging
the source. Record what survives, what must be re-created, and observed recovery
steps/time; leave the live installation untouched.

## A8 — Shared-load evidence and a truthful support matrix

**Problem:** context-depth decode speed does not answer how several people
experience a shared service. Hardware fixtures are not physical acceptance.

**Scope:** exercise the A4 client paths under controlled concurrent load, starting
with one client then a five-client mix of short chat and long work. Use an
actual model/engine and document context, slots, prompt/output lengths, hardware,
warm/cold state and request arrival pattern. Report time to first token,
completion latency (including p50/p95 with sample counts), throughput, errors
and rejected work. Cancellation and saturation are part of the run; retain
enough raw measurements to reproduce the summary. Five clients is a test
scenario, not a guaranteed capacity claim.

Use A5 admission to keep overload bounded. If measurements expose starvation,
leaks or unacceptable behavior against the declared workload target, fix the
specific defect and repeat the affected run. State the target before measuring
rather than picking a threshold afterward. Do not derive a user-count promise
from single-stream tokens/s or add a new benchmark dashboard to satisfy this.

Close the carried physical checks where hardware is available. Record other
platforms as pending/unsupported for the relevant promise instead of inventing
passes. A limited supported matrix is acceptable; weakening an intended promise
solely to close a checklist is not. An unavailable physical test does not stop
independent implementation work.

**Done when:** measured supported configurations have workload limits and
reproducible records; saturation has bounded, intelligible behavior; cancellation
returns capacity; and the support matrix distinguishes measured, simulated,
pending and unsupported paths. No platform-wide certification from one host.

## Carried verification and incoming user evidence

| Item | Evidence still needed | Where it belongs |
| --- | --- | --- |
| Two or three moderated friend sessions | Actual observed tasks, failures and recovery without maintainer guidance; record tested build | Existing [session guide](../acceptance/hobbyist-sessions.md); findings enter the relevant A slice |
| Windows unattended service behavior | Remaining [R2.6 checks](../acceptance/windows-service-run.md), especially reboot before sign-in, session-0 shutdown, service access to required storage, and tray operations | A7/A8; preserve Troy's successful service/migration reports |
| Physical Mac/native interpreter | Native and Rosetta-started installation, actual engine/inference and documented startup behavior | [Native Apple Python record](../acceptance/native-apple-python-run.md), A8 |
| Modest GPU baseline | Physical inference/concurrency evidence; the 8 GB/16 GB scoring fixture alone is insufficient | A8; use available tester hardware and record exact configuration |
| Platform-specific startup/support claims | Explicit Linux service-lingering/macOS login behavior and verified engine variants; no unsupported Windows SYCL assertion | A8 support matrix; future implementation if the promised scope requires it |

Sessions may continue against the existing alpha. Record the exact version and
do not erase its failures when a development build fixes them. New findings are
triaged by their effect on a useful task; they do not automatically create a
new broad redesign. Mark each as fixed with evidence, assigned to a slice, or
explicitly deferred with a reason. Requests for a disruptive physical reboot
or an unavailable tester device wait for that person's participation.

## Working and completion rules

- Prefer a failing behavioral regression and targeted acceptance to re-auditing
  known findings. Use actual HTTP/browser/client paths where the defect crosses
  that boundary; a helper-only check is not sufficient evidence there.
- Isolate acceptance from the owner's service, GPU workload and NAS. Clear
  inherited Eugene environment, use isolated identities/configuration/ports,
  and clean up only the processes and paths the acceptance owns.
- Keep contracts and generated consumers aligned. UI changes require a matching
  packaged build; development installer pins must identify the tested components.
  That is delivery of a slice, not authorization to change frozen alpha assets
  or publish another release. Check workflow triggers before a documentation or
  source push if it would publish a container or website.
- Run relevant checks and record meaningful failures and limitations. Do not
  rerun unrelated full acceptance merely because a documentation status changed.
- Update this document's pickup and the slice record when work is complete.
  This is the only current work order; older roadmaps retain design/history.
- After A8 and incoming user evidence, reassess usefulness, remaining blockers
  and supported audience with Troy. That conversation does not automatically
  create a release task or imply production readiness.

## Explicitly deferred

New chat/RAG products; broad provider/API parity beyond named workflows;
additional engine integrations for feature count; SAML and elaborate tenant
hierarchies; billing; compliance certification; multi-region HA; a new performance
dashboard; automatic rolling engine upgrades; library redundancy. The old
roadmap's [unscheduled work](release-roadmap.md#8-deliberately-not-scheduled),
including MLX and unmeasured vLLM admission behavior, remains visible. A real
dependency of a selected workflow must be solved or the scope decision recorded,
not silently marked complete.

Positioning accompanies A4/A8 evidence: demonstrate one app endpoint retained
while Eugene manages the supported machines/backends and state the manual work
it removes. Do not add unsupported competitor exclusivity claims or treat a
new marketing campaign as the next implementation slice.
