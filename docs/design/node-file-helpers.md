# Workbench files on enrolled Eugene nodes

Status: implemented locally, 2026-10-04; not released to Edge. Troy approved the architecture:
one Eugene node installation, independently enabled inference and file support,
one enrollment, and Workbench hosted either locally or centrally.

## Boundaries

- Workbench remains an ordinary application. Its sign-in cannot administer nodes.
- A node helper is bundled with the agent and managed with it. File operations
  run in a separate restricted account using the existing app-account launcher.
  No model, inference runtime, or Workbench installation is required on a helper.
- File support starts disabled. Enabling it exposes no folders. The operator
  registers existing folders, and People assigns read or text-write access to
  particular people. The operator must also explicitly select its own grants.
- Grants identify the enrolled node and its identity, an immutable folder id,
  and the permitted operation. Reusing a revoked node's name grants nothing.
- Every operation checks the current person, app, sign-in, node enrollment,
  helper setting, folder, and grant. Discovery is not authorization. Queued
  operations are checked again before dispatch. Already dispatched writes may
  finish; uncertain writes are never retried automatically.
- The existing bounded folder operations remain: 32 KiB UTF-8 reads, 8192
  characters per write, hash-checked edits, no links, deletion, or shell.
  Grants do not change OS permissions. Platforms without the existing safe
  file/account boundary report that reason on the capability's own screen.

## Transport and persistence

Nodes initiate authenticated polling connections to the control root. Workbench
uses the existing agent-served sign-in address to reach a narrow helper API.
Neither the browser nor Workbench needs a route to a user's computer. The local
file worker listens only on loopback and requires a separate random credential.
It receives no enrollment, model, or operator credential.

The control root replicates helper configuration and grants. Requests, file
contents, and results are ephemeral and never enter the control-state log.
Pending operations are bounded and expire. Claimed operations are never
requeued, including after disconnect or lost acknowledgement. Stop asks the
root to cancel queued work, and operation IDs cannot be reused for five minutes
in that root process. These are transient delivery protections, not a durable
exactly-once transaction or a rollback guarantee. Node status describes observed
availability; turning off an optional capability is not a Needs Attention issue.

An app authenticates with its own client secret and the signed-in person's
refresh credential, verified as that client's credential at the root. These
credentials stay server-side. The helper API never accepts a caller-supplied
subject as evidence of identity and never accepts an ordinary OIDC token as an
operator credential. Each customer's Eugene installation is a separate trust
domain; this does not introduce a shared MSP tenancy database.

## Screens and compatibility

The console manages node capabilities and exported folders from People, beside
per-person grants; machine pages link there. Workbench lists authorized folders
with their machine and availability, uses its existing per-chat selection and
per-call approval, and labels unavailable or removed selections explicitly.

Existing Workbench-host folder grants keep working. They are not silently
copied into central grants or widened. Central grants are usable by authorized
people from any permitted Workbench in this installation, on the same protocol
whether the helper and Workbench happen to share a machine or not.

## Using it

1. Update the control root and standby roots, node agents, console, and Workbench
   together. Older Workbenches keep their existing local grants; older control
   roots do not understand the new replicated helper configuration operation.
2. Install Workbench through Apps on the server or personal machine that will
   host its conversations. The core no longer requires a local file account.
   It still needs its normal model gateway and Eugene sign-in registration.
3. Enroll each machine that will supply files as an ordinary Eugene node. It
   does not need a GPU, downloaded model, inference runtime, or Workbench.
4. Open **People → Files on your machines**, expand the machine, and enable file
   support. Eugene prepares the bundled helper in its restricted OS account.
   There is no second enrollment or separately managed application.
5. Give the displayed helper account OS permission to the intended folder, then
   register that existing folder. On Windows, use the folder's Security settings
   to grant that specific service account Read, or Modify when text writes are
   intended. On Linux, use a stable dedicated group and a service drop-in for
   `eugene-plexus-app@node-files.service`, following the existing
   [folder provisioning guide](workbench-files.md#provisioning-an-existing-folder)
   with `node-files` in place of `workbench`. Do not attach persistent ACLs to a
   dynamic UID. Read/write folders also require the service's `ReadWritePaths`
   allowance. Reload systemd, then disable and re-enable file support to restart
   the helper with the new settings. Do not grant the helper access
   to Eugene's private configuration directories. Registration checks access
   and records the folder's identity; it does not change OS permissions.
6. Select the person and choose **No access**, **Read only**, or **Read and write
   text** for each folder. Save their access, and allow that person to sign into
   the central Workbench using the existing Apps permissions. The owner chooses
   its own Workbench access explicitly on each folder.
7. In Workbench, select the node folder in the chat's settings. Its machine name
   and availability are shown. Each listing, read, or text write still needs
   approval. Only approved results are sent to the model and saved in that chat.

Disable file support to stop the helper, or remove a folder/person grant to end
that access. Disabling keeps the helper environment and folder configuration so
it can be enabled again. Removing a folder and registering it again creates a
new identity/grant; existing people must be assigned it explicitly. None of these
actions deletes the user's files or previous chat results. Eugene's normal node
uninstaller also removes the helper's managed service and environment.

## Platform and deployment limits

| Host installation | Central Workbench | Node file helper |
| --- | --- | --- |
| Windows system service | Yes | Yes, separate service account |
| Linux system service | Yes | Yes, DynamicUser and Landlock ABI 3+ |
| Windows per-user, Linux user service | Yes | Unavailable: no isolated account |
| macOS | Yes | Unavailable: native file/account boundary not implemented |
| Docker | Yes | Unavailable: use a host-installed node for host files |

Local subprocess tools keep their existing account requirement. This adds
bounded folder tools, not remote shell execution, arbitrary file downloads,
binary editing, or a background file synchronization service.

Helpers initiate their connections; no new inbound firewall port on a desktop
is required. Workbench and the administration console retain separate origins.
This change does not install a public HTTPS reverse proxy or automatically turn
their existing HTTP listeners into one Internet-facing endpoint. An operator
can put both behind one HTTPS port using separate hostnames; customer trust
domains should remain separate installations for MSP deployments.

## Verification

Automated checks cover cross-person and cross-node denial, app and sign-in
revocation, node replacement, disabled helpers, read-only writes, cancellation,
expired and replayed requests, independent worker authorization, bounded
payloads, protected paths, persistence/recovery, and Workbench's approval flow.
Real Windows/Linux file-operation tests retain C6's handle-based checks.

`scripts/node-file-helpers-acceptance.py` passed on Windows and Linux (WSL): it
installs the bundled wheel into a clean environment, starts its loopback worker,
uses real control enrollment and OIDC sign-in, drives the actual outbound agent
relay, reads/edits a real file, refuses traversal and withdrawn access, and checks
that file contents never enter replicated state. It also detects drift between
the helper and Workbench copies of C6's safe file-operation code.

The control suite passed 357 tests, Workbench 149, the console 1658, and the
Workbench frontend 62 (the original 61 plus the selection regression).
Agent helper/app lifecycle tests passed 97; the helper's
16 tests also passed on Linux. Both frontend production builds, Python lint/type
checks, and replay/snapshot recovery checks passed. Platform-specific and
opt-in browser checks skipped by those suites are not counted as passes.

This acceptance uses the invoking OS account to verify the protocol and file IO.
It does not claim a new service-install isolation run: the service-account
mechanism is the existing C1 launcher. Repeat the disposable Windows/Linux
service-install acceptance against the release candidate before publishing.

The manual **Node file helpers** workflow accepts the three candidate commits
and repeats the protocol, permissions, recovery, worker and Workbench checks on
Windows and Linux without modifying an existing installation.
