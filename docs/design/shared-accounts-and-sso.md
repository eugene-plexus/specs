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

## Slices

- **U1 — account and group foundation (complete).** Central group CRUD and
  memberships, explicit individual/group access, effective app and job-site
  permissions, durable replication, People UI, and a Workbench link to the
  authoritative directory. Group access is enforced at OIDC authorization and
  refresh and the existing job-site gates. The owner remains the only account
  manager until delegated checks land.
- **U2 — delegated administration.** Separate account management, group
  definition and scoped membership assignment. Named console sessions and
  backend capability gates replace assumptions that every console session is
  the owner. Account administration never implicitly grants private-chat access.
- **U3 — cross-component enforcement.** Propagate person identity through app
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

Next is U2: named console sessions and delegated, scoped account/group management.
External provider setup remains U4; no Google/Microsoft credentials are needed yet.
