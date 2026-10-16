# U3: person-aware model access and access history

Implemented and validated locally on Windows, 2026-10-16. Unpublished, queued
with U2, the Discover handoff and settings simplification at Troy's request.

## Real-service acceptance

`control/.venv/Scripts/python specs/scripts/u3-person-access-acceptance.py`
starts real control, agent, gateway and Workbench processes on ephemeral loopback
ports with disposable state, a null keyring and no ambient Eugene configuration.
Only the inference driver is a fixture. The gateway uses its production lease
timing. Next's development server forwards Chrome requests through the real
agent proxy to the real root; browser API responses are not intercepted.

- A registered Workbench key requires a valid app-bound person proof for model
  use. Its model catalogue is filtered by key limits; the explicit app-only
  catalogue exception cannot run inference.
- Ada signs in through the real OIDC flow and can use embeddings and chat. The
  gateway records her stable person and app IDs without storing her proof or
  prompt in metrics.
- Removing Ada's group membership ends an active Workbench stream in **9.996
  seconds**. New model requests are denied and the excluded fallback driver
  receives zero requests.
- Restarting the root preserves the withdrawal and the access history. Ada's
  existing private chat remains hers.
- After access is restored, stopping the root denies a new model request with
  503 despite the gateway's cached app-key lookup. There is no local allowance.
- Signing out removes the local session and revokes the root sign-in.
- Chrome opens and refreshes Access history through the real proxy. The final
  layout fits desktop and 390 px phone widths, with no page errors.

[Desktop](assets/u3-person-access/access-history-desktop.png),
[mobile](assets/u3-person-access/access-history-mobile.png),
[browser result](assets/u3-person-access/browser-result.json),
[integration result](assets/u3-person-access/result.json).

This validates development code and a development UI, not a packaged release.
The services were stopped after the run. No live installation, physical GPU,
external model/provider, release build or remote CI was used.

## Enforcement and revocation bounds

The primary Bearer remains the app key. `X-Eugene-Person-Token` carries the root's
OIDC access token as secondary proof. The root checks signature/type, exact app
audience, app-key ownership binding, session, password-change time, current
account and current individual/group app access. An ID token, refresh token,
forged token, different app's token or missing Workbench proof cannot authorize
model use. A proof cannot turn an operator credential into an app request.

Every admission and renewal checks current policy under the root's state lock.
The reservation digest includes the verified identity as well as key limits,
preventing a request ID from moving between people. Release remains possible
after revocation. The gateway refuses an authority response that drops or
changes verified identity; unavailable verification fails closed. App model,
alias/fallback, tool, locality, concurrency and rate constraints still apply.

Renewal happens every ten seconds with a four-second authority timeout; the
observed 9.996 seconds is a measurement, not a hard wall-clock SLA. This stops
future gateway work and streaming; it cannot undo work already sent downstream.
Access proofs expire in ten minutes and a long request can end on expiry.
Workbench refreshes before the next request. Existing private-page sessions
still use Workbench's previous refresh bound; current-root enforcement applies
to model requests and existing job-site authorization, not every cached page.

Foreground Workbench requests use their exact session; background indexing and
resumed media use an unexpired session belonging to their owner. No owner session
means no model call. Model-list cache entries cannot cross people, sessions or
the separate owner-configuration catalogue scope. Credentials are never sent to
inference drivers or included in gateway metrics/access receipts.

App-only metadata is explicit: log ingress and the filtered model catalogue use
check-only admission. They cannot acquire/renew model reservations. Settings may
inspect models without a person; sorter measurement waits for signed-in Documents
use. Other third-party API clients retain app-only behavior until they adopt this
proof protocol. Any proof supplied is validated and must bind to that app.

Job-site root checks already use current person/app policy, with site-local
OS/folder/key checks remaining authoritative for execution. Focused tests use an
existing credential to make a successful site call, remove group permissions or
membership, and verify the next call is denied. U3 does not relax site grants.

## Audit, upgrades and review

The root derives sanitized actor/action/target/time/index receipts from the same
committed log entries that apply access mutations. No independent best-effort
audit write can falsely report a successful change. The latest 1,000 receipts
persist through snapshot, compaction, replay and restart; the owner-only UI
shows the latest 50. Old retained log entries are unattributed. Compacted history
from before U3 is unavailable. Failed sign-ins and rejected mutations are outside
this committed-change history; model-request outcomes remain in Gateway Metrics.

The gateway migrates released metrics schema 12 to 13 in place, retaining
history and adding nullable person/app columns. Workbench schema 18 adds a
nullable backend access proof while preserving accounts, sessions, chats and
documents; legacy sessions refresh on first model use. Migration, rollback,
backup and restart tests cover older stores. Active/standby roots, agents,
gateway and Workbench must be upgraded as one coordinated batch; mixed proof
participants fail closed. Published `SPECS_REF` pins are deliberately unchanged
until the held batch is released.

Review covered wrong-app/subject proofs, caller-selected identity, reservation
reuse, policy withdrawal during streaming, fallback and tool constraints,
background-owner isolation, cached model lists, old/unreachable authorities,
metadata exceptions, secret-free receipts, and snapshot/replay equivalence.
Acceptance exposed two integration gaps that were fixed: app-only settings/log
checks needed an explicit non-inference purpose, and ingestion's model check
needed the document owner's identity as well as the embedding worker. Regression
tests cover both. Replay tests were updated to clear the new audit state in their
synthetic index-zero snapshot; migration expectations now name schema 18.
Temporarily disabling the gateway's refusal of an authority response without
verified identity made its regression test fail. The source was restored from a
byte-for-byte copy and the same test passed again.

## Local checks

Focused passing checks cover:

- Control person proof/admission, delegated administration, groups, OIDC,
  owner auth, real replication/replay, snapshots and job-site permissions.
- Gateway proof propagation/refusal, alias/fallback admission, request metrics,
  catalog-only refusal and preserved v12 metrics history.
- Agent admission forwarding, standalone proof refusal and app log ingress.
- Workbench sign-in/refresh, concurrent person and background-owner isolation,
  embeddings/rerank/chat headers, cache isolation, indexing/search, sorter
  settings, and store migration/rollback. Opening owner settings makes no sorter
  probe; subsequent signed-in Documents use does.
- Existing People/Metrics UI tests, TypeScript, focused ESLint, Python Ruff and
  mypy, and diff checks. Existing dependency deprecation warnings remain.

U3 intersects the person's current **app entitlement** with the app key's runtime
limits. Per-group model-role profiles and chat-based sorting are not implemented
here. U4 is next: Google, Microsoft and generic OpenID Connect with shared session
management and explicit account linking.
