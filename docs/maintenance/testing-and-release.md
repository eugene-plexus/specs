# Testing and release policy

Approved 2026-10-17; work slices revised 2026-10-21 (development plan P2, P3,
P5, P10: [`development-plan.md`](../design/development-plan.md)). Edge is for
rapid development; Release is a separately qualified immutable candidate. Keep
existing regression tests, but stop repeating release qualification for every
work slice.

## Work slices

The merge gate is green CI on the branch. A builder runs only the tests for
the files it changed and the pre-commit hooks locally.

| Change | Required before merge |
| --- | --- |
| Documentation or metadata only | Applicable integrity, link and whitespace checks |
| Routine behavior | A regression test that fails without the change; green CI on the branch |
| Cross-component behavior | The same, plus the specs branch integration in CI (`scripts/branch-ci.py <branch>`, or a specs branch of the same name) |
| Auth, privileges, destructive filesystem operations, migrations, installers, publication | The same, plus an acceptance script that runs in CI on real Linux and Windows processes, and one adversarial review by a second model while CI runs. Only a blocker finding stops the merge. A change to the Windows service or UAC also gets one elevated run on the maintainer's machine |

No acceptance record, run document or handoff for a row: its GitHub issue
holds the brief and status, and the design doc gets a short "what building
found". A release keeps its acceptance record. Reuse a suitable existing test.
An acceptance defect gets a regression that fails without the repair.
Sabotage a new or changed critical check once; do not replay unchanged
mutations for every edit. Never restore sabotage with a destructive checkout
of a developer's files.

A flaky test is fixed the same day, or skipped with the issue number in its
reason. It is never re-run silently.

Unknown impact means broader coverage, not guessed test exclusions.
Platform-specific changes still test their actual platform. Shared
inference/control APIs do not justify dropping security tests.

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

A push to any branch runs CI (2026-10-21, P1). On `main` the planner's base is
the previous push. On any other branch it is the branch's merge-base with
`main`, and each component repository's branch of the same name, if it has
one, is tested in place of that component's pin. A candidate counts as a pin
change of its component; a site-host candidate selects full coverage, as a
site-host ship does. `scripts/branch-ci.py <branch>` dispatches the same run
by hand, after component branches move or when specs has no such branch.

Superseded branch and PR validation may be canceled. Each push to `main` runs
to the end, never canceled or held behind another push; so does each dispatch,
weekly run and call from another workflow (Release qualification's included). `ship.py` pushes
merged specs commits first and its pin commit alone (P11), so the pin push
plans the pins only; `--one-push` keeps them together for a merged script that
needs the new component code. A reduced plan on `main` trusts the previous
push's run for everything it did not change, so that run passes only after the
previous push's CI has passed (`scripts/previous_push.py`); the chain ends at a
run that planned full coverage. A red run on `main` therefore holds every later
reduced push, pin-only fixes included, until it is re-run and passes or a
full-plan push lands. Qualification and
publication are not canceled in progress. The reusable platform/service workflows no longer
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

Pinned integration runs in three parts per system side by side (W0.3); each
acceptance step runs in exactly one part, under the profile condition it had
before. The runtime receipts keep the unsplit job's names, `Pinned
integration (ubuntu-latest)` and `(windows-latest)`, and pass only when every
part on both systems passed; the publisher also requires every job named
`Pinned integration (...)`, each part included, to have passed.

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

Finish the candidate and its reviewed acceptance record, commit them, and
dispatch **Release qualification** on that commit's branch with `release_tag`
(the version it is for) and the committed `docs/acceptance/...md` record path.
Create the annotated version tag only after qualification passes, at the
qualified commit or a documentation-only descendant, so a failed candidate
never needs a tag moved (2026-10-19). A tag that already exists must name the
qualified commit.

A patch release is qualified the same way, on its line's record commit
(`scripts/release-line.py`, then `scripts/release.py` from the line's
worktree; [`release-script.md`](../design/release-script.md), "Patch
releases"). It moves only the line's own refs. Its notes and record reach
`main` after publication, as one documentation-only commit. Only the newest
line takes a patch, except for a security fix (`--security`).
`scripts/release-patch-acceptance.py` runs this path offline in CI on Linux
and Windows.

Dispatched with `release_tag` empty, or on its weekly schedule against `main`,
the workflow is a **rehearsal**: every job runs, its container builds as an
Edge candidate, and no receipt is produced, so it can never publish. Run one
before cutting a candidate; the session-start check names a failed scheduled
rehearsal.

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
The maintainer asking for a release is that action for the release asked for:
the session publishes once every gate and manual check passes, and stops
instead on any failure (Troy, 2026-10-19).

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