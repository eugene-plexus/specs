# C6: person-specific folder tools

2026-10-03. [Design and provisioning](../design/workbench-files.md).

Workbench main `38af0ae030e3909be70682d83da47f3734cf0a7d`, built dist
`251a0b955d2c951fcc9008346291598998ac2594`. Agent
`2e861f3cb3c4d6b15680cba74d8e319a1a46a1f4` pins that archive. Both
generated installers take this agent revision from the release manifest;
the dependency lock is unchanged. No shared API contract changed.
No live developer install was changed.

## What is built

In **Toolbox · Tools**, the owner grants an existing folder on Workbench's
host to a named person. Read-only is the default; text creation and editing
are explicit options. The person selects folders per chat and approves each
listing, read or write. Models receive relative paths and approved results,
not the host's absolute folder path. Grants and tool records survive restart.
SQLite schema 5 preserves earlier chats and MCP connections.

Only the named recipient can select a grant. The owner administers grants
but cannot use another person's grant or approve their call. Removing a
grant blocks pending calls without deleting files or prior chat results.
The broker rechecks recipient, permission, directory identity and current
file hash at dispatch. Cancellation retains the grant lock until native I/O
finishes; uncertain actions are never automatically replayed.

These are built-in operations, not a sandbox for arbitrary MCP programs.
Local programs remain owner-only and retain Workbench's OS access. Host
permissions must be provisioned separately: a specific Windows service
identity, or a root/stable-user-owned Linux project directory with a stable
group, setgid, a systemd write-path exception and an appropriate umask.
The application does not change ACLs or create privileged OS accounts.

## Measured checks

- **Windows full suite: 139 passed**, including three real Chrome flows;
  one POSIX-only test skipped. After the Linux adapter correction, the
  Windows folder suite passed **28 tests**, including Chrome, with three
  Linux-only cases skipped. **Final Linux suite: 139 passed**, three Chrome
  tests skipped. **49 frontend tests passed**. Ruff, formatting, mypy on
  both platforms, ESLint, Prettier, TypeScript, the production build,
  vendored integrity and staged secret scanning passed.
- Native files and authenticated HTTP cover member approval, read-only
  enforcement, another person's refusal, revocation, Stop, stale hashes,
  hard links, junctions/symlinks, replaced roots, path replacement during a
  read, special files, invalid text and bounded results. A failed flush
  preserves an uncertain write and prevents model continuation. Repeated
  cancellation cannot release the grant lock while its worker still runs.
- Chrome grants a folder, selects it in a chat, reloads pending approval,
  approves a create, closes the tab and reopens the saved result. Desktop
  folder administration and the phone result view were visually inspected.
- **12/12 Windows and 13/13 Linux sabotage mutations caught**, with exact
  source restoration and passing restored baselines. The Linux-specific
  mutation disables Landlock: real directory-move tests then expose an
  outside read and an outside create. With the boundary enabled, both fail
  before reading or creating a file outside the grant.
- **23 agent catalogue tests passed** after the final pin.
- **C3 published-archive regression: 42/42**, including Chrome, Eugene
  sign-in, search, attachments, session isolation, revocation and uninstall.
  Its explicit disposable chat-only entry also verifies that the catalogue
  refuses local actions when the host cannot provide an app account.
- **27/27 local release regression scripts passed**, including the contract
  sweep and sabotage, before the installer pin. Logs:
  `ep-c5b-release-checks-n6cy3vv8` under the local temporary directory.

## Published archive under real service accounts

**91/91 on Windows and 91/91 on Ubuntu**, installing the catalogue archive
through real system installs on disposable GitHub runners:
[run 37159269830](https://github.com/eugene-plexus/specs/actions/runs/37159269830).
The unchanged harness is `scripts/c6-folder-tools-acceptance.py` at specs
`b49849b`, dispatched with the final agent revision above. Reports are
retained as `c6-windows-latest` and `c6-ubuntu-24.04` artifacts.

This includes all C5 account, credential, private-file and child-process
checks. C6 then tests real folder provisioning, default read-only grants,
approved listing/read/edit/create, changed content, owner/member refusal,
decline and revocation. A verified new service process reads and edits a
file created before restart, checking durable OS permissions as well as
persisted grants and transcripts. The models are scripted integration
fixtures, not a benchmark of live-model tool accuracy.

Workbench CI:
[run 37159238381](https://github.com/eugene-plexus/workbench/actions/runs/37159238381).
Agent CI:
[run 37159259120](https://github.com/eugene-plexus/agent/actions/runs/37159259120).

## Defect found by the service run

The first run passed **91/91 on Windows**, but Linux stopped after **66
passing checks** when creating a grant. The initial Linux adapter used
`openat2`; systemd's `DynamicUser` implies `RestrictSUIDSGID`, which blocks
that syscall even on a supporting kernel. Ordinary development tests did
not run under that service policy.

The correction uses Landlock on a disposable thread for each built-in
operation, with no-link handle traversal and mount-ID checks. It retains
systemd's protections. The added race tests prove that moving a held parent
outside the grant cannot redirect a later read or create; sabotage proves
those tests detect a disabled boundary. Linux requires enabled Landlock ABI
3 or newer and filesystem creation-time/mount-ID support, failing closed
when unavailable. The second real service run passes on both platforms.

## Remaining scope

Writes are bounded, in-place text writes. A crash or disk error can leave a
partial file; there is no undo, deletion, rename or execution operation.
Linux file locks are advisory, so a hash precondition is not a transaction
with uncooperative external editors. Host administrators and trusted local
programs remain outside the member-access boundary.

Dedicated media screens, local media engine admission, answer versions and
the working animation remain separate slices. Arbitrary per-person process
isolation, MCP OAuth and non-text MCP results remain unimplemented.
