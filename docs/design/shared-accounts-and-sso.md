# Shared accounts, delegated access and external sign-in

Troy approved this order on 2026-10-15: shared accounts and permission
groups, delegated administration and backend enforcement, then SSO. The first
provider set is Google, Microsoft and configurable OpenID Connect.

Eugene's control root remains the identity authority. Workbench's local people
table keeps profiles and ownership by the existing Eugene subject; it is not a
second account directory. Existing subject IDs, chats, site ownership and links
must survive. The owner's `operator` subject stays reserved and protected. The
passphrase also unseals the root, so local unlock/recovery remains independent
of everyday external sign-in.

## Model routing and a simple default experience

Direction agreed with Troy on 2026-10-16; the additions below are design
requirements, not shipped behavior. Model routing profiles may be assigned to
people or groups, with a selection for each task role. The first roles are
conversation, document search (embeddings), and result sorting. A compatible
model may serve several roles without another loaded copy. Chat-based result
sorting needs an explicit implementation; assigning that role does not turn
a chat model into a native reranker or an embedding model.

**The single-person, single-machine experience must require none of this
configuration.** Installing and starting one suitable chat model must be enough
to chat and search documents. There must be no required role assignment,
profile creation, group setup, embedding download, or reranker download.
Document search already works by words without a dedicated model. Automatic
selection can use suitable dedicated models when available. Reusing the chat
model for sorting is planned; its quality and latency must be established before
it becomes an automatic default. Missing optional roles must not block answers.

The proposed presentation follows the existing hobbyist UX principle of
disclosing details beside the feature that uses them:

- **Everyday use:** show the selected model, document availability, storage,
  updates, and actionable health information. The default routing profile is
  managed automatically and does not require an editor in this path.
- **Customize:** put model roles, ordered alternatives, and detailed limits
  behind a contextual control. It remains available to an authorized person
  on a single machine. Settings search and direct links reveal the relevant
  details, without requiring a global expert-mode switch.
- **Sharing:** put people, groups, profile assignments, delegated administration,
  and SSO under a clear "Share Eugene" / "People and access" entry. Detailed
  sharing setup is not part of a fresh personal installation's ordinary flow.
  Existing shared installations retain visible access-management entry points.
- **Machines:** reveal connection and placement controls when managing machines;
  adding another machine does not imply adding another person. A single person
  with several machines should still be able to keep the everyday experience.

Sharing and technical detail are independent. Do not introduce a required
"single tenant / multi tenant" setup choice or make expertise depend on user
count. Hiding a panel changes presentation only: it never disables authentication,
clears settings, removes people, or bypasses backend authorization. An ordinary
shared user sees their permitted experience, not the administrator's controls.
Existing custom values and active policies survive any presentation change;
show a concise "Customized" or effective-value summary where they affect behavior.
Errors, pending changes, and important operating status remain visible even when
their detailed controls are collapsed. Raw config keys belong in technical
details rather than the everyday form.

Profiles select preferred models; permission grants constrain every actual
target, including fallbacks. Groups may grant access to multiple profiles, with
an explicit default and an explicit permission to choose alternatives. Do not
silently merge competing model preferences from several groups. Embedding
selection is bound to the document index's compatible model; switching embedding
models requires a controlled rebuild, not ordinary cross-model failover.

U2's delegated administration design accounts for managing and assigning
profiles. U3 checks the person and app key for every actual model request,
including current chat, embedding and sorting calls and routing fallbacks.
When role profiles are implemented, their resolution and model grants must feed
that same enforcement path. Do not expose profile permissions before they are
enforced. Profile routing and chat-based sorting remain future implementation;
the presentation slices completed so far are recorded below.

### A download must lead visibly to using the model

Troy's observation on 2026-10-16: Library -> Discover -> finding a model that
fits the NAS -> downloading it offered no obvious next step to launch it. He
had to find the launch controls himself. Simplification therefore covers the
whole task, including what happens after success, as well as fewer settings.

Source inspection found an existing Run action in the expandable Downloads
panel, but the model's main action does not become a launch handoff. There is
also a completion race: Library marks a download done before `_locate_model`
finishes, while `useDownloads` stops polling when no transfer is active. A final
record without `modelId` can therefore remain on screen without its Run action.
Completed ordinary downloads also leave the Tasks list. These are observed code
paths, not a reproduction of Troy's specific session. The local implementation
below addresses them.

The proposed flow is Find -> Download -> Run -> Use, with a visible next action
at each step:

- The selected model's main card shows download progress, then **Run on
  [machine]**. Preserve the machine used for the fit/launch choice; do not silently
  replace it with whichever machine the user later browses. On one machine,
  there is no placement question to answer.
- Offer **Download and run** as a clearly named combined action where supported,
  with **Download only** available. Choosing download only never implicitly
  starts a model or stops an existing one.
- Between file completion and launch readiness, say **Adding to your Library**
  and keep tracking readiness. If registration or preparation fails, retain the
  completed file and show the observed reason with a retry or repair action.
- The continuation stays on the model card and is reachable through Downloads
  and recent Tasks, including after navigation or refresh. A transient toast or
  a separate panel below the model is not the sole place to find it.
- After Run, show progress and the destination machine. Once ready, a chat model
  offers **Open in Workbench** with that model selected. A specialist model offers
  the relevant next action or explains that it is available for search, sorting,
  or another supported task; it must not be sent to a chat it cannot serve.
- Running status identifies the actual machine and reported GPU/CPU use. A fit
  prediction and completed download must not be presented as evidence of GPU
  execution.

Acceptance for that work must include:

- A fresh personal installation with one chat model can answer a question about
  a saved document without configuring roles or installing a second model.
- A single person can add a second machine without being forced through group
  or profile administration; several people can share one machine.
- Customizing and collapsing settings preserves saved values, exposes effective
  behavior, and leaves every permitted setting discoverable through search.
- Shared profiles and all their fallbacks respect the caller's effective access;
  changing presentation never changes those grants.
- Discover -> download -> run -> use succeeds without hunting for another page,
  both on one machine and with the NAS selected. A delayed Library registration
  does not leave the finished download stuck without its next action.
- Navigating away and returning preserves the next step and intended machine;
  download-only never starts a model. Launch failures keep a visible recovery
  action, and a specialist model gets a relevant completion action.

#### Download handoff implementation, 2026-10-16 (local, unpublished)

The first implementation slice covers Discover -> Download -> Run -> Workbench.
The model card offers Download and run or Download only, then progress and the
next action. Download-only remembers its destination per browser without granting
permission to launch. A missing destination disables Run rather than silently
choosing a different host. Combined runs use the existing durable operation,
including the selected source, revision, and companion files.

Library now finishes registration before marking a transfer done. Registration
failures retain the file and show a scan recovery action; later scans reconnect
the finished transfer to its Library entry. The UI also briefly follows older
Libraries that finish the transfer before returning its model ID.

Recent completed downloads remain in Tasks without inflating its active count.
Their links identify the exact transfer, and its continuation remains available
even if the catalogue cannot be read. Successful run receipts survive navigation.
Downloads starts collapsed in Discover so it does not crowd the model's next
action; its management link opens it when needed.

After a launch, the UI checks the runtime on the destination agent and uses its
served model alias for a Workbench link. Workbench retains that choice through
sign-in and validates it against the current user's model list when New chat is
pressed. Opening the link itself creates no chat. Embedding/reranking runs lead
to Documents instead. Old launch receipts distinguish a stopped or unavailable
runtime from a ready one.

Validation: 130 focused UI tests, 71 Workbench App tests, and 26 Library download
tests passed. Both frontends passed TypeScript and focused ESLint checks; Library
passed focused Ruff and mypy checks. Two Chrome fixture flows covered local and
NAS destinations, download-only without an implicit launch, returning through
Tasks on the same page, refresh, catalogue failure, served-alias handoff, and
phone-width layout. The browser flows use isolated API fixtures, not physical
inference engines (`ui/e2e/discover-handoff.spec.ts`, opt-in with
`EP_HANDOFF_FIXTURE=1` and an isolated `EP_UI_URL`). The Library suite still emits
existing dependency deprecations and a pending supervisor-task cleanup warning.

This slice does not implement the broader settings simplification, model-role
profiles, permissions enforcement, or chat-based sorting. Actual GPU/CPU execution
is not available in the runtime summary consumed here: the handoff links to the
selected model's backend details and makes no GPU-execution claim. The NAS
container's physical GPU validation remains outstanding. Nothing was released,
deployed, or changed on the live installation for this validation.

#### Everyday settings implementation, 2026-10-16 (local, unpublished)

Troy asked to queue several slices locally before publishing or running release
CI. This slice adds contextual Customize controls to the existing settings
editors. Known document limits, specialist-model selection and technical tuning
start folded; everyday controls and unfamiliar/new fields stay visible. Workbench
gets settings search, including raw keys, and fragment links open the relevant
control. Raw config keys now live under each field's Technical details.

Collapsed customization shows saved overrides, unsaved edits and reported model
status. Warnings, invalid values, rejected edits and pending restarts remain
visible outside the fold. Summaries never serialize secrets or structured
credentials. Search keeps the topic editors mounted, fixing a draft-loss path
when a search previously removed a topic. Hidden and visible changes still use
the existing Save/Discard operations. People and access remains discoverable by
sharing, group and account searches; this makes no change to authorization and
does not infer sharing from the number of machines.

Troy also requested choosing widgets to suit their data. Default temperature
and Workbench's sorting-time budget now pair a slider with a precise number
input. Bounds come from the served schema. Unset/default and invalid values are
preserved, rather than saved implicitly or clamped. Exact counts and resource
limits remain number inputs; model names use the previously held dropdown work.

Validation: 104 focused settings tests passed, plus TypeScript, focused ESLint,
format and diff checks. A Chrome fixture flow checked keyboard slider use,
precise entry, collapse/search/save, preservation of an unrelated custom limit,
and phone-width layout (`ui/e2e/settings-customization.spec.ts`, opt-in with
`EP_SETTINGS_FIXTURE=1` and an isolated `EP_UI_URL`). Temporarily restoring the
old search unmount behavior made the draft-preservation regression test fail;
the source was restored from a copy before the passing run. No release build,
remote CI, push or live-install deployment was performed. Model-role profiles,
delegated administration and external SSO remain separate implementation work.

## Slices

- **U1 — account and group foundation (complete).** Central group CRUD and
  memberships, explicit individual/group access, effective app and job-site
  permissions, durable replication, People UI, and a Workbench link to the
  authoritative directory. Group access is enforced at OIDC authorization and
  refresh and the existing job-site gates. The owner remains the only account
  manager until delegated checks land.
- **U2 — delegated administration (published to Edge).** Separate account management, group
  definition and scoped membership assignment. Named console sessions and
  backend capability gates replace assumptions that every console session is
  the owner. Account administration never implicitly grants private-chat access.
- **U3 — cross-component enforcement (published to Edge).** Propagate person identity through app
  credentials, intersect person and app permissions, define revocation bounds,
  and audit changes across console, gateway, Workbench and job sites.
- **U4 — external sign-in and shared sessions.** Google, Microsoft and generic
  OIDC connect to the root. Bind provider issuer/subject to stable Eugene IDs
  through explicit linking, with invitation/admission controls. Shared sign-in,
  session visibility, logout and recovery are tested together.

## U1 access semantics

`Person.groups` absent or null means individual access: existing `apps` and
`permissions` keep their current semantics, including the install defaults.
An explicit list selects group access; the effective grant is the union of
those groups. An empty list grants no apps or job-site permissions. Individual
settings are retained for an explicit switch back, but do not participate while
group access is selected. Unknown groups are refused on writes and snapshots.

Each group has a stable ID, unique case-insensitive name, optional description,
explicit job-site permissions and app grants. New groups start with no access;
null app grants deliberately mean all apps. Deleting a group removes its
memberships atomically; a person's resulting empty list stays empty. Deleting
an app removes its explicit grants from people and groups.

`appsInEffect` and `permissionsInEffect` are computed by the root. The UI shows
these values separately from the editable individual policy. Group edits affect
new OIDC authorizations and refreshes immediately; existing app sessions retain
the existing expiry bound (Workbench refreshes within ten minutes). Job-site
checks read current root state. Groups do not bypass local OS or folder grants.

Only permissions with implemented enforcement are exposed in U1. Broad
Administrators/Operators/Viewers templates arrive with their backend gates;
storing an unenforced permission would imply access guarantees that do not exist.

New log operations are `putPermissionGroup` and `deletePermissionGroup`.
Snapshots gain `permissionGroups`; old snapshots load with no groups and
unchanged individual access. A standby must understand these operations before
it can follow group mutations. Rollout upgrades the root/standby before the UI.


## U1 result

Published with [acceptance evidence](../acceptance/u1-shared-accounts-2026-10-15.md).
A real existing Workbench account kept its subject and chat through group
assignment, root restart, last-group deletion and an explicit switch back to
individual access. The owner has a Workbench shortcut to the central directory.

Review found a race between approving an OIDC sign-in and exchanging its code:
current group access is now checked at code exchange as well as authorization,
refresh and user-info. A regression test covers withdrawal during that window.

U2, U3 and the two UX slices were published to Edge on 2026-10-16;
[publication evidence and CI status](../acceptance/edge-accounts-2026-10-16.md)
supersede the local-only status in the historical implementation records below.
Next is U4, external provider setup and shared sessions. No external provider
credentials were needed for these foundation slices.

## U2 implementation result, 2026-10-16

The owner can grant three independent powers under a person's Administration
access: manage ordinary accounts, define permission groups, and assign members
to explicitly selected groups. These grants live on the stable person record,
outside app/site groups. Only the owner delegates administration; changing a
group cannot make someone an administrator. Future profile-management and
profile-assignment permissions will follow the same separation when their
enforcement exists. No placeholder profile grants are exposed now.

Account managers create accounts in empty group mode with no effective access,
edit display names, disable/enable or delete ordinary accounts. They cannot edit
themselves or other administrators. Password resets and email changes remain
owner-only: both can become account takeover in apps. Account managers cannot
set individual grants or switch individual/group mode. Membership delegates
can change only their assigned groups, preserving all other memberships.
Group designers can change app/site access for existing members through group
definition or deletion; that authority is stated explicitly at delegation.

Named administrators sign in at `/administration/` with their existing Eugene
name/password. The page uses its own session storage and never falls back to an
owner credential. It presents permitted tools, explicit membership checkboxes
and Save, current grants, and account search. Owner delegation stays under the
existing People page; the owner unlock and recovery flow is unchanged.

A new `ep-administration+jwt` credential is addressed only to control. The agent
proxy forwards it there but never exchanges it for a machine or owner session.
All existing infrastructure, app-registration and secret-management routes keep
their owner/service gates. Administration reads current active-root policy on
every request. Logout, changed delegation, disable/enable, password reset,
account deletion and removal of a delegated group invalidate existing named
sessions immediately. A sealed/unreachable root cannot authorize administration.
Named sessions last one hour plus the existing clock-skew allowance; shared
external sign-in/session management remains U4.

Grants and an administration-session version persist in person log records and
snapshots. Old records default to no administration. Group deletion removes
its delegation scopes atomically. Directory writes log actor ID, action and
target; a durable cross-component audit surface remains U3.

[Local acceptance evidence](../acceptance/u2-administration-2026-10-16.md) covers
real root/agent/Workbench APIs, Chrome, restart, private-chat separation and
revocation. The subsequent Edge publication regenerated from published contracts
and updated the distribution and installer pins together. Upgrade active and
standby roots before new person records are written, then agents/UI for named
sign-in. Publishing did not upgrade any running installation.

## U3 implementation result, 2026-10-16

### Directory presentation follow-up (published to Edge)

Troy's first Edge review asked for a scalable account list and a clearer tree
entry. Owner and delegated administration now share a searchable, paginated
directory which opens one person's editor. People is one entry in the left tree;
the directory owns individual accounts. Each person's page uses visible sections
for account details, groups and app access, administration permissions, and
separate account actions. Only explanatory help remains folded. The owner can
reset passwords and change email; delegates see only their permitted account and
group controls. Existing person links and permission gates remain intact. See the
[implementation and acceptance record](../acceptance/people-directory-2026-10-16.md).

### Person enforcement

Workbench now sends its app key together with the current person's root-issued
OIDC access token. The gateway asks the active root to verify the proof, its
binding to the registered app, the current account, session and individual/group
app grant. The verified stable person ID follows admission, reservation renewal
and gateway request metrics. The app key still constrains every selected model,
including aliases and fallback targets, gateway-run tools, locality, shared
concurrency and request rate. A person's proof never replaces the app key.

This intersection currently means **person's app entitlement AND app key's
runtime limits**. It does not introduce per-person model allowlists or per-group
model-role profiles. The proof requirement applies to installed Workbench app
keys. Other API clients keep their existing app-only behavior unless they adopt
the protocol; supplied proofs are always verified and app-bound.

Workbench keeps access proofs on its backend, refreshes legacy sessions on first
model use, and scopes model-list caches by person/session. Document indexing uses
the document owner's session; chat and resumed media work retain their owner.
Missing, expired or revoked owner credentials stop model use; background work
never borrows another person's session or falls back to app-only inference.
The existing private-chat and document ownership rules remain independent of
administration grants.

Every new model admission reads current root policy. Long-running requests renew
at ten-second intervals, with a four-second authority timeout; withdrawal ends
the request when renewal fails. The real-service acceptance observed 10.00 seconds
from group withdrawal to a stopped Workbench stream. Root unavailability fails
closed even with a cached app-key lookup. Access proofs expire after ten minutes;
Workbench refreshes before starting another request, but an existing stream can
end when its proof expires. Already-completed downstream work is not undone.
Ordinary Workbench private-page sessions retain their existing refresh bound;
U3 does not claim instantaneous logout of every open page.

Two explicit app-only checks preserve non-inference operations: agent log ingress
and a filtered model catalogue for owner settings. Neither can acquire or renew
an inference reservation. Opening Settings no longer starts the sorter's speed
measurement; it starts when a signed-in person uses Documents. Existing job-site
calls already recheck current root app/person permissions and retain site-local
OS, folder and key grants. Tests cover group and membership withdrawal using an
already-issued job-site credential; site-local activity remains in its own audit.

Committed account, group, app, key, password and session changes now produce
bounded audit receipts in the same durable log operation as the mutation. The
latest 1,000 receipts survive replication, snapshots and restart. People has a
folded owner-only Access history panel; Gateway Metrics shows the verified person
on attributed requests. Receipts contain actor, action, target, time and log
index, never passwords, prompts or credentials. Legacy log entries are labelled
unattributed; events already compacted before this upgrade cannot be recovered.
This is a history of committed access changes, not a failed-login audit.

[Local acceptance evidence](../acceptance/u3-person-access-2026-10-16.md) covers
real root/agent/gateway/Workbench processes, the browser's real agent proxy,
revocation during streaming, excluded fallbacks, root restart/outage, retained
private chat ownership, historical database migration and request attribution.
Only inference was simulated; no physical GPU or external provider was used.

This was published to Edge with U2 and the UX slices, with generated contracts,
distribution builds and installer pins recorded in the publication evidence.
Upgrade active/standby roots before agents, gateway and Workbench. Mixed old/new
person-proof participants fail closed. U4 is the next account slice: Google,
Microsoft and generic OIDC, explicit identity linking, admission controls,
shared sign-in, session visibility, logout and recovery.

## U4 implementation result, 2026-10-16 (published to Edge)

People now has an optional **External sign-in** setup panel for Google,
Microsoft and generic OpenID Connect. The owner chooses the stable HTTPS Eugene
address, copies the callback URL to a provider's web application registration,
and enters its client ID and secret. HTTP is limited to literal loopback for
local testing. Microsoft uses a specific tenant ID, with a preset for personal
Microsoft accounts; additional tenants use separate registrations. Generic
providers retain their exact advertised issuer, including a trailing slash.

Admission is invitation-only. The owner first creates an ordinary Eugene member
account, then issues a one-use, 24-hour connection invitation from that person's
**Sign-in and sessions** section. The invitation code is shown once and pasted
into a form, never carried in a URL. The member explicitly confirms which Eugene
account they are connecting. Only the verified `(issuer, subject)` is linked;
matching names or email addresses never merge accounts or grant access.
Provider setup, identity linking and unlinking remain owner-only controls.

Both local member login and upstream login establish an eight-hour shared browser
sign-in. Apps can offer **Continue as [person]**. Named administration can use
that same session with its existing grants. Stable person IDs, Workbench chat
ownership, individual/group permissions and U3 inference admission stay intact.
The protected owner still uses the local passphrase/unlock path. No external
identity can become the owner, unlock the root or create machine authority.

The account page, linked from Workbench, shows connected accounts and active
browser sign-ins and can end one or all shared sign-ins. Owners can revoke these
from a person's page. App and administration credentials are bound to the parent
sign-in: revocation, unlinking, provider edits/disable, account disable/delete or
password reset prevents subsequent refresh, person admission and administration
requests. Existing U3 renewal and ten-minute private-page refresh bounds apply;
this does not erase already viewed content. App sign-out still signs out of that
app. Shared sign-out does not log out the upstream provider. Legacy app sessions
and direct password-based administration sessions retain their own logout paths.

The authorization-code flow uses PKCE S256, browser-bound state, nonce, signature,
issuer, audience/authorized-party, time and subject validation. Google accepts its
two documented issuer spellings; Microsoft checks tenant and signing-key issuer.
Only RS256 and ES256 signatures are supported. Provider HTTP uses bounded JSON,
no redirects and no shared cookies. The agent forwards only Eugene's dedicated
HttpOnly, SameSite=Lax sign-in cookies and explicitly suppresses pooled cookies
for a visitor without one. HTTPS uses Secure cookies. Account actions require
a browser-bound CSRF proof.

Provider secrets are sealed with the existing root master key. Cookie and
invitation capabilities are stored as hashes. Providers, identities, invitations
and shared sessions use replicated log operations and snapshots, with bounded
active sessions/invitations and access-audit receipts. Provider edits invalidate
pending invitations as well as prior provider sessions. In-progress authorization
requests are deliberately temporary; restart requires starting those again.

[Acceptance evidence](../acceptance/u4-sso-2026-10-16.md) covers real root, agent,
Workbench and Chrome, plus a local upstream provider signing real RSA tokens.
Google and Microsoft discovery were checked read-only and their token profiles
were tested. Live Google/Microsoft account authentication awaits actual provider
registrations; no credentials or running installations were changed.

This slice and the directory/detail presentation changes are included in the
[Edge publication](../acceptance/edge-sso-2026-10-16.md). Control/UI were regenerated
from the published contracts, and both distribution builds and release pins were
refreshed. Other platform consumers carry only the canonical token-verifier update.
Upgrade active/standby roots before enabling SSO; Workbench has a separate app
update. No running installation was upgraded as part of publication.
