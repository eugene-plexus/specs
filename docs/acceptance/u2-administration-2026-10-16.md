# U2: delegated directory administration

Implemented and validated locally on Windows, 2026-10-16. Unpublished, queued
with the Discover handoff and settings simplification at Troy's request.

## Observed behavior

`control/.venv/Scripts/python specs/scripts/u2-administration-acceptance.py`
started real control, agent and Workbench processes on ephemeral loopback ports
with disposable state, a null keyring and no ambient Eugene environment values.
Next's development server forwarded browser requests to that actual agent. No
API responses were intercepted. No live installation, provider or model ran.

- A named administrator signed into real Workbench but could not read another
  person's existing private chat, even when requesting its exact ID.
- Restarting control preserved grants, stable subjects and that private chat.
  Named credentials could not unlock the sealed root; owner unlock restored it.
- Chrome signed into `/administration/`, created an account without access,
  assigned its allowed Builders group, and observed effective Workbench access.
- The page survived reload, fit at 390 px, and had no page errors.
- The real proxy/root refused the named credential for config and password reset.
- Removing the delegate's authority rejected its existing session immediately;
  reloading returned the browser to named sign-in. The other person's chat remained.

[Desktop](assets/u2-administration/administration-desktop.png),
[mobile](assets/u2-administration/administration-mobile.png),
[browser results](assets/u2-administration/browser-result.json),
[integration results](assets/u2-administration/result.json).

This validates a development UI against real services, not a production export
or packaged release. The screenshot predates the final removal of redundant
account names from row headings. Multi-node credential forwarding is covered by
the agent proxy tests; the physical NAS was not changed.

## Boundaries and review

The root enforces independent account-management, group-definition and scoped
membership grants. Delegates cannot grant administration, reset passwords,
change email identities/individual grants, alter administrators or change access
mode. New accounts receive explicit empty groups. Scope checks preserve all
out-of-scope memberships. Group-definition authority can change existing members'
app/site access and is described accordingly in the owner's form.

The distinct token class prevents inherited owner authority in older components.
It requires an authority signature, control-only audience, stable non-owner
subject, bounded lifetime and a valid session version. Worker forgery and owner
token exchange are refused. The active root checks current grants and version
on every request. Revocation covers logout, grant edits, disable/enable, password
reset, deletion and delegated-group deletion. Snapshots and real log replay retain
the policy; legacy records grant no administration. The owner is not constrained
by the delegate's 64-group scope limit.

Manual adversarial review followed each route and credential boundary, including
node-acting-for-owner app registration and potential takeover through passwords
or app email identity. Browser acceptance caught delayed checkbox feedback;
membership edits now use a local draft and explicit Save. Review also caught
an owner-access dependency on the delegate scope-size limit, which was removed
and covered by a 65-group regression. No remaining blocker was found.

## Local checks

- Control: 136 focused administration, group, auth, OIDC, site-person and token
  tests passed. This includes 20 new administration cases.
- Agent: 72 proxy/token tests passed, including control-only forwarding and
  refusal to exchange a named administrator into infrastructure access.
- UI: 47 People, named administration, delegation, login and permission-summary
  tests passed. TypeScript, focused ESLint and formatting checks passed.
- Changed Python modules passed Ruff and mypy. The OpenAPI contract passed
  Redocly with its three existing warnings. Existing dependency deprecations
  remain in Python test output.

No release build, remote CI, commit, push or deployment was performed. Generated
models/types use the local contract; published pins deliberately remain unchanged
until the queued batch is released. Active and standby roots must be upgraded
before writing new person fields; agents then need the proxy token-class support.
U3 person/app permission intersection and cross-component auditing, model-role
profiles, and U4 Google/Microsoft/generic OIDC remain future work.
