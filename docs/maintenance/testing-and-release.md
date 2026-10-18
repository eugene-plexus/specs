# Testing and release policy

Approved 2026-10-17. Edge is for rapid development; Release is a separately
qualified immutable candidate. Keep existing regression tests, but stop
repeating release qualification for every work slice.

## Work slices

| Change                                                                                   | Required local evidence                                        |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Documentation or metadata only                                                           | Applicable integrity, link and whitespace checks               |
| Routine behavior                                                                         | Focused regression tests and applicable static checks          |
| Cross-component behavior                                                                 | Acceptance for the changed boundary                            |
| Auth, privileges, destructive filesystem operations, migrations, installers, publication | Focused real-environment acceptance and one adversarial review |

No automatic new acceptance harness, sabotage pass, adversarial review or run
document for a low-risk slice. Reuse a suitable existing test. An acceptance
defect gets a regression that fails without the repair. Sabotage a new or
changed critical check once; do not replay unchanged mutations for every edit.
Never restore sabotage with a destructive checkout of a developer's files.

Do not run full component suites locally merely to repeat CI. Reuse results
while their inputs remain unchanged. Unknown impact means broader coverage,
not guessed test exclusions. Platform-specific changes still test their actual
platform. Shared inference/control APIs do not justify dropping security tests.

## Automatic CI

The specs CI planner compares the push or PR base with its fixed checkout.
Missing history, dependency changes, installer logic, contracts, workflows and
unrecognized inputs select full coverage. Only explicit documentation paths,
semantically unchanged release metadata and known component-pin changes receive
the reduced plan. Markdown fixtures under scripts are not documentation.

- Documentation-only changes skip runtime acceptance.
- Manifest formatting retains input-integrity checks but no runtime or image build.
- Component pins run the existing signing, stolen-key, profiles, eligibility,
  runtime-stop, local-routing, OIDC and packaged Workbench smoke checks on Linux
  and Windows. Agent/driver pins also select launch-boundary checks; agent pins
  select real Linux system updates. Relevant engine pins select one macOS version,
  run on a push by `macos-push.yml` outside CI so Edge does not wait for it
  (2026-10-18). A macOS-only failure is a red run, not a held Edge.
- Full coverage retains every previous CI acceptance command, the three-version
  macOS matrix, app-account isolation, Open WebUI and folder-tool service checks.
- Full integration runs weekly, and CI's manual `profile=full` remains available.
  A scheduled failure is visible but does not automatically veto every Edge build.
  A discovered security or data-loss defect requires the safety hold below.

Superseded push/PR validation may be canceled. Qualification and publication are
not canceled in progress. The reusable platform/service workflows no longer
also run independently for the same push. Component repositories retain their
own CI; this change does not remove their unit suites or codegen checks.

## Edge publication

`Publish Edge` runs after named CI/container push workflows complete, daily to
heal a dropped event, or by manual dispatch. It executes trusted `main`, not
code or refs supplied by a completion event. One publisher runs at a time.

The publisher walks main's actual first-parent history, newest first, and
requires a successful push CI receipt plus real Linux/Windows runtime-job
receipts for identical inputs. A green documentation commit cannot conceal a
canceled or failed runtime check. Skipped jobs are not evidence.

Runtime fingerprints include tracked code, contracts, dependency locks,
workflows, harnesses and configuration. Image fingerprints include installers,
release inputs, all scripts, platform files, Docker/Unraid inputs, Docker ignore
rules and the build workflow. Manifest JSON is canonicalized so whitespace
does not invalidate evidence. Immutable agent pins transitively fix the
Workbench catalogue and site-host code. No nested source is taken from main.

The container workflow publishes `sha-<full-commit>` candidates only after
Compose/installed-Workbench checks. Recovery also runs for full/unknown-impact
changes. Each build retains its exact digest and input fingerprint in a
`verified-container` artifact. The Edge publisher finds an input-identical
successful build and validates that run's artifact, not a mutable commit tag.
It retags those bytes as `:edge`, verifies the digest, then
creates or fast-forwards the `edge` branch. It retains an `edge-publication`
receipt. No rebuild, force-push or inferred "all workflows" gate is involved.
Missing, expired or mismatched build receipts fail visibly; rebuild to renew
the 90-day evidence rather than bypassing this check.

Agents read `commits/edge`, validate its SHA/date and fetch installer pins at
that immutable SHA. Missing or malformed markers fail visibly, with no fallback
to workflow-history inference. The release updater and no-downgrade rules are
unchanged. Existing older agents retain their old reader until updated.

GitHub refs and registry tags cannot be updated atomically. A registry failure
does not move the branch. A ref failure after a verified retag can temporarily
leave the image ahead; the workflow fails visibly and a rerun converges. Do not
describe these two independent services as an atomic publication.

Set repository variable `EDGE_PUBLICATION_PAUSED=true` for a security/data-loss
hold. The publisher fails explicitly without moving either channel. Remove the
hold only after the repair's required checks pass. Do not suppress or rename a
failing critical gate to make a candidate eligible.

## Release qualification

Finish the candidate and its reviewed acceptance record, then create its normal
version tag. Dispatch **Release qualification** on that exact tag with
`release_tag` and the committed `docs/acceptance/...md` record path.

Qualification resolves all seven component pins plus Workbench and site-host
from the pinned agent, and rejects disagreements with the installer's site-host
pin. It runs full Python regression/static/codegen checks in each consumer's own
venv against shipped runtime constraints on Windows and Linux, UI/Workbench
frontend regression, broad integration and platform/service coverage. Console
browser journeys and wheel packaging use the pinned dist's static files, not
an independently rebuilt replacement.

Its version-specific container has `releases` metadata, undergoes Compose and
recovery acceptance, and is retained as `release-sha-<full-commit>`. Edge's image
cannot substitute for it. The final `release-qualification` artifact binds the
candidate fingerprint, all nested pins, reviewed record hash and tested digest.
No receipt is produced if any required job fails.

The reviewed record remains a human attestation, not automated proof of its
prose. Before dispatch, review actual packaged fresh-install, real upgrade and
recovery evidence, and explicitly record untested hardware/OS paths. CI's
process fixtures do not substitute for a Windows in-place upgrade or real-model
inference. Do not claim the workflow independently performs those manual runs.

To publish the versioned image, dispatch **Container image** with `release_tag`,
`qualification_run` and `publish=true`. It requires a successful qualification
from this repository, matching runtime inputs/tag/record and an unexpired
receipt, then retags the retained digest without rebuilding. Candidate builds
never publish a version alias. GitHub release assets continue to be generated
from committed blobs with `release-artifacts.py`; publishing a GitHub release
remains the maintainer's explicit action after these gates and manual checks.

The qualification artifact expires after 90 days. Missing/expired evidence
requires requalification, not a bypass. Documentation-only changes can reuse
input-identical evidence, but channel/version metadata must still match the
qualified image. Test-only/harness/workflow changes invalidate evidence too.

## First rollout

1. Land the specs workflows/scripts first, leaving existing component pins alone.
2. Verify the initial CI/container receipts and first forward-only `edge` marker.
   Protect `edge` against force-push/deletion with a repository ruleset; allow
   its authorized publisher to fast-forward it.
3. Only then land and pin the agent marker reader. Update root/standbys before
   workers when the underlying feature requires that order.
4. Confirm native Edge discovery and the retained registry digest agree. Run a
   real GitHub/registry publication and failure/retry trial before calling the
   remote rollout accepted. Until this sequence is completed and recorded,
   remote rollout is pending; local fixture tests alone do not prove that wiring.

No live install, repository setting, branch, release pin or remote image is
changed merely by preparing these source changes. This rollout order prevents
shipping a reader before its marker exists.