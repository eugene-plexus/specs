# C6: folder grants and built-in file tools

Troy chose all three scope decisions on 2026-10-03: built-in tools with
person-specific grants; read-only by default with optional text creation
and editing; existing folders on the machine running Workbench. Arbitrary
local MCP programs remain owner-only. This slice does not sandbox them.

## Access and user flow

In **Toolbox · Tools → Folders · File tools**, the install owner names an
existing host folder, chooses a person who has signed into Workbench, and
optionally enables text writes. The default is read-only. A grant does not
change host permissions. The machine administrator provisions those for
Workbench's existing C1 account first. This is the host's path, not a path
on the browser's machine; network/device paths on Windows are unsupported.

Grants are immutable. Remove one and create another to change its folder,
recipient or mode. Granting the same folder to several people is explicit
sharing. Only its named recipient can select a grant in a chat, even when
the owner can administer it or read that person's chat. Other people do
not see it. The owner sees host paths for administration; models and
members receive only the folder name, relative paths and operation results.

The person enables a folder per chat, off by default. Built-in
`list_directory`, `read_text`, and (only for writable grants) `write_text`
use the existing tool approval/dispatch/transcript loop. Every call waits
for that chat's owner to approve exact arguments, including proposed text.
Read results go to the selected model and remain in the chat. Revocation
prevents pending calls; completed results and host files remain.

Listings stop at 200 names and say when truncated. Files must be UTF-8
text, at most 32 KiB and 16384 characters; each write accepts at most 8192
characters within the existing tool-argument limit. Binary controls are
refused. There are no deletion, rename, directory creation, recursive scan
or execution tools. An empty expected hash creates only a new file. An edit
requires the SHA-256 returned by a prior read and refuses a changed file.
Writes are in place and flushed; a crash or I/O failure may leave a partial
write, which is uncertain and never replayed. There is no automatic undo.

## Boundary

These are trusted built-in operations inside Workbench, not arbitrary code
run for a member. C5b local programs still inherit Workbench's OS account
and can reach everything that account can reach, including granted folders
and Workbench's own storage. The page explains that distinction.

Both grant creation and execution require the C1 account signal. Workbench
refuses its private data, credential directories and installation, and any
ancestor of those paths. A grant pins the directory's volume/device, file
identity and creation time; replacing it requires a fresh grant. No grants
are inferred from old chat settings or the owner-reads-chats setting.

The file boundary uses OS handles, not `resolve()` followed by an ordinary
open. Relative paths reject absolute names, parent traversal, alternate
data streams and Windows device-name aliases. Links/reparse points and
multiply linked or special files are refused. Linux opens descendants with
`openat2` beneath the root, without symlinks or mount crossings; unsupported
kernels/filesystems fail closed. Windows opens single components relative
to held parents, refuses reparse points, and retains directory handles
without delete sharing. It enumerates the directory handle directly.
Root identity also uses creation time to detect file-ID/inode reuse.

File calls and grant mutations serialize. Dispatch rechecks the grant's
recipient and mode under the same lock as revocation. Cancelling a call
keeps that lock until its file worker finishes, then retains C5's uncertain
dispatch state. Windows file sharing excludes competing writes/deletes;
Linux takes an advisory file lock. Uncooperative host programs can still
modify files on Linux: the hash is a precondition, not a transaction with
every external editor. Administrators and trusted owner-installed programs
are outside the member-access boundary.

References for the OS primitives:
[Linux openat2](https://kernel.googlesource.com/pub/scm/docs/man-pages/man-pages/+/refs/tags/man-pages-6.12/man/man2/openat2.2),
[Windows NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile),
[Windows directory enumeration](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntquerydirectoryfile).

## Provisioning an existing folder

The administrator chooses a dedicated project folder rather than granting
a drive, home or install tree. Keep host ACLs narrow: this gives the entire
Workbench app account access, while Workbench's grants decide which signed-in
person can use its built-in tools. Revoking a grant does not remove OS ACLs.

On Windows, grant the service identity shown on Eugene's Workbench app page
read/list permission, or modify permission when writes are intended, on
that specific folder. The usual identity is
`NT SERVICE\EugenePlexusApp-workbench`. Do not grant access to SYSTEM, all
services or Everyone as a substitute. Existing children must have the
intended inherited permissions. Workbench does not run `icacls` itself.

On Linux, use a dedicated folder under `/srv` and a stable group that only
Workbench and the intended host users join. Do not assign persistent ACLs
to the systemd dynamic UID: it can change after a restart. A machine
administrator can add a drop-in for
`eugene-plexus-app@workbench.service` containing:

```ini
[Service]
SupplementaryGroups=workbench-project
ReadWritePaths=/srv/workbench-project
UMask=0007
```

Create the group first. Keep the project directory owned by root or a stable
host user, so a recycled service UID cannot traverse it. Give it the group, group access,
and its setgid bit so new files keep the stable group; provision existing
files' group permissions too. Workbench creates files with mode 0660,
subject to the service umask. Then reload systemd and restart Workbench.
For read-only use, omit `ReadWritePaths` and give only read/list permissions.
C1's home-directory protection and private install remain in force; do not
turn those protections off to make a folder accessible. The acceptance run
exercises this setup on a disposable runner, including a service restart.
See systemd's [service execution documentation](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)
for `DynamicUser`, `SupplementaryGroups`, `ReadWritePaths` and `UMask`.

## Acceptance

Use real Windows/Linux filesystem primitives, real authenticated HTTP and
Chrome, including a member's approved read/write, read-only grants, another
person's refusal, revocation during approval, changed content, links,
hardlinks, replaced roots, cancellation and persisted grants/results.
Mutations must show that the permission and path tests can fail. Install the
published dist through the catalogue on disposable Windows and Linux service
runners, check the actual OS boundary and restart, and pin both installers.
