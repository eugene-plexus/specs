# Row 23: folder access for Workbench without a terminal (C6-ACL)

Lane AG2, first in its lane. **High risk (privileges).**

Sources:
- `workbench-files.md` §"Provisioning an existing folder";
- memory `feedback_no_terminal_setup_steps` and `feedback_gui_equality_for_configurable_things`;
- agent `app_accounts.py` and `install_permissions.py`;
- J20 in `job-sites-own-enrollment.md`.

## 1. What it delivers

- **Give access from the console.** On Workbench's app page, the owner picks a folder and Read only or Read and write. The agent adds the permission for Workbench's own account and records what it added.
- **Remove takes back only what Eugene added.** A permission set by hand stays.
- **Workbench links to it.** When Workbench's account cannot open a folder, it says "Workbench's account cannot open D:\Projects\acme. Give access in Eugene", with a link.
- **The agent refuses** drive roots, system folders, Eugene's own folders, homes, links and network paths. Each refusal names its cause.
- **J20, reused.** J20 removed the by-hand step for Job Sites: each person's tools run as that person, so no folder permission is needed. A person's own folders keep that route: "Use a Job Site to work in your own folders." This row covers shared project folders.

## 2. Design

### Who may act

- **Add and remove: an operator session only** (`require_operator_session`, as `/v1/directories` uses). Never a service token, a gateway token or a client key.
- **Workbench never adds.** A compromised Workbench (C5b programs run in its account) must not widen its own reach.
- **Release (FA-C1): the app's own client key** (`app:workbench@<this node>`). It may only remove what Eugene added for that app, so it cannot widen access. It would be the second route on the agent that takes a client key, after the log ingress.
- **Unavailable where the app runs in Eugene's own account** (a per-user install, Linux `--user`, macOS). The agent answers 409: "Workbench runs in Eugene's own account here, so it already reaches what Eugene reaches. Folder access needs a Windows service or a Linux system install."

### Contract (`agent.yaml`)

```yaml
/v1/apps/{app}/folder-access:  get listFolderAccess, post addFolderAccess   # operator session
/v1/apps/{app}/folder-access/{id}:  delete removeFolderAccess              # operator session
/v1/apps/{app}/folder-access/release:  post releaseFolderAccess {path}     # that app's key (FA-C1)
FolderAccessRequest: {path: string(1..4096), mode: [read, write]}
FolderAccess: {id, app, path, mode, account,
  state: [applying, ready, removing, removed, changed_outside, failed],
  preexisting: boolean,     # the account already had these rights; nothing added
  notInheriting: integer,   # items inside that keep their own permissions
  restartNeeded: boolean,   # Linux write access, until Workbench restarts
  message, addedAt, addedBy}
FolderAccessRefusal: [not_a_folder, link, drive_root, network, system, eugene, home, unavailable]
```

A refusal is a 400 Problem that carries `refusal`.

### The agent (new `folder_access.py`; routes in `routes/directories.py`)

**Records.** The agent keeps a record per grant in its private `folder-access.json`. Each record holds the folder's identity (volume or device, file id, creation time) and exactly what was added.

**Refusals.** `refusal(facts)` is one pure function. It runs on the final path, opened without following links. A folder that *contains* a refused one is refused too.

| Refusal | Covers | Words |
|---|---|---|
| `not_a_folder`, `link` | a missing path, a file, a junction, a symlink, a reparse point | "Choose an existing folder, not a link." |
| `drive_root` | `C:\`, `/`, a mount root | "Choose a folder inside D:\, not the whole drive." |
| `network` | UNC paths, mapped network drives | "Network folders are not supported." |
| `system` | `%SystemRoot%`, Program Files, `%ProgramData%`, `Recovery`, `System Volume Information`, `$Recycle.Bin`; `/bin /boot /dev /etc /lib* /opt /proc /root /run /sbin /snap /sys /tmp /usr /var` | "Eugene does not give apps system folders." |
| `eugene` | the prefix, and the data, config, apps and engines folders | "This is Eugene's own folder." |
| `home` | every `ProfileList` profile, `C:\Users`, `/home`, every home in `/etc/passwd` | "This is inside a person's home. Use a Job Site to work in your own folders." |

**Windows (the agent is LocalSystem).**

To add:
1. Open the folder with `OPEN_REPARSE_POINT | BACKUP_SEMANTICS`. Refuse a reparse point.
2. Check its identity.
3. Read its DACL with `install_permissions._read_aces`. If the account already holds the rights, set `preexisting`.
4. Add one explicit, inheritable ACE through that same handle (`SetSecurityInfo`), so the folder cannot be swapped after the check:
   - read: `(OI)(CI)(RX)`;
   - write: `(OI)(CI)(RX,W)`. Workbench never deletes, so this is narrower than the "modify" that the doc asks for today.
5. Propagation runs in a worker thread (`applying`). Count the children that do not inherit, and leave their permissions as they are.

Parents need nothing, because of bypass-traverse.

To remove: check the identity, then remove the one ACE whose SID, mask and flags match the record. If anything differs, change nothing and record `changed_outside`.

**Linux (the agent is unprivileged).** The root helper `eugene-plexus-apps-ctl` (`install.sh`, `write_app_units()`) gains two verbs:
- `folder-grant <app> <read|write> <id>`;
- `folder-revoke <app> <id>`.

The path is in `<id>.path`, which the helper reads as the `eugene-plexus` account.

**The helper is the boundary, so it checks everything again:**
- no control characters;
- `realpath -e` equals the path, so there is no link anywhere on it;
- it is a directory;
- the same refusals;
- no parent writable by any account but root;
- no named ACL entry masked out, because recalculating the mask would widen it.

Then it:
1. Uses the app's stable group `eapp-<hash>-files`. The group is made at `start` and listed in a `20-folders.conf` drop-in, so read access needs no restart.
2. Runs `setfacl -P -R -m g:<group>:rX` plus the default ACL (`rwX` for write).
3. For write, adds `ReadWritePaths=` to the drop-in, because `DynamicUser` makes the system read-only. Write therefore starts after a Workbench restart, which the console asks for: "Workbench restarts to write in /srv/acme. Answers running in it stop."

**Revoking.** The helper revokes only entries on its own root-owned list (`/etc/eugene-plexus/folder-access/<app>`). A revoke removes the ACL at once. The drop-in line goes at the next restart.

**Packages.** `install.sh` adds the `acl` package where it is missing.

### Workbench and console

- **Workbench.** `folders.py` turns a `PermissionError` at an owner's add into "Workbench's account cannot open {path}." The response carries `giveAccessUrl`: the console app page with the path and mode filled in. This follows `manageUrl`'s pattern, and `AddFolder.tsx` shows the link.
- **Release (FA-C1).** When no grant names a folder any more, `folders_api.remove` calls `release`. If that fails, Workbench shows: "Workbench no longer uses D:\Projects\acme, but its access stays: {cause}. Remove it in Eugene."
- **Unchanged:** `folder_windows.py` and `folder_linux.py` stay the per-operation boundary.
- **Console.** `app/apps/app/page.tsx` gets the section **Folders Workbench can open**, in new `FolderAccess.tsx`. It reuses the directory picker.
  - A row: "D:\Projects\acme · read and write · ready".
  - The confirm: "Give NT SERVICE\EugenePlexusApp-workbench read access to D:\Projects\acme and everything in it?" Buttons: Give access, Cancel.
  - After a grant: "Workbench can read D:\Projects\acme. 3 items inside keep their own permissions and stay closed."
  - When the permissions changed elsewhere: "D:\Projects\acme's permissions were changed outside Eugene, so they were left as they are."

**Defaults.** Read only. Nothing changes before the confirm, and nothing is deleted. **It exposes private data:** every Workbench person the owner grants the folder can read it, so the confirm names the account and says "everything in it". Rewrite `workbench-files.md` §Provisioning: the console does this now, and the by-hand steps become the expert override.

## 3. Repositories and codegen

- **specs:** `openapi/agent.yaml`. In `scripts/install.sh`, only `write_app_units()` and the package list. `workbench-files.md`. `scripts/row23-folder-access-acceptance.py` and its CI job.
- **agent:** new `folder_access.py`, plus `routes/directories.py`, `app.py` (the router), and `app_accounts.py` (the group at `start`).
- **workbench:** `folders.py`, `folders_api.py`, `AddFolder.tsx`, `Folders.tsx`. Workbench hand-writes its one call.
- **ui:** `app/apps/app/page.tsx` and new `components/FolderAccess.tsx`.

Regenerate agent and ui. Control generates from `agent.yaml` but uses none of it, so it gets no re-pin.

## 4. Tests that fail before the change

- **agent `test_folder_access.py::test_refusals`.** A table of facts: a drive root, `C:\Windows`, the prefix, a profile, `/etc`, a junction, a UNC path and an ancestor of the prefix each get their refusal. `D:\Projects\acme` and `/srv/acme` pass. It fails today: the module does not exist.
- **agent (Windows CI) `test_windows_add_then_remove_touches_one_ace`**, on a test account's SID:
  1. Adding read leaves exactly one explicit ACE.
  2. A by-hand ACE for another account survives.
  3. Removal takes only the one ACE Eugene added.
- **Also:**
  - `test_add_needs_operator_session`: a client key, a gateway token and the app's key are refused;
  - `test_release_only_own_app`;
  - `test_identity_change_is_changed_outside`;
  - `test_preexisting_rights_left_alone`;
  - Workbench's `test_permission_error_links_to_console`.

## 5. Acceptance (disposable GitHub runners, Windows and Linux)

**`row23-folder-access-acceptance.py`** builds on `c6-folder-tools-acceptance.py`, without its by-hand `icacls` and `setfacl` step. It installs a Windows service and a Linux system install with the agent on port 18179 (`EUGENE_PLEXUS_AGENT_BIND_PORT`; add that variable to `install.ps1` if it lacks it). It refuses to run unless `RUNNER_ENVIRONMENT=github-hosted`.

It checks:
1. Workbench, installed from the catalogue, cannot add a grant for `C:\ep-r23` or `/srv/ep-r23`, and shows the console link.
2. After read access, `read_text` works and the OS refuses `write_text`.
3. Write access works; on Linux, after the restart.
4. A by-hand entry for another account is unchanged.
5. Removing the Workbench grant releases the access (FA-C1).
6. Every refusal holds, including a link to `C:\Windows` or `/etc`, and a test user's home.
7. A folder swapped for a link after the add reads `changed_outside`, and the link's target is untouched.
8. The records survive an agent restart.
9. On Linux, a masked named ACL entry is refused.

**The reviewer should attack:**
- unusual path forms: 8.3 names, `\\?\`, trailing dots, ADS, case, mount and bind points, `/proc/self/root`;
- a folder swapped between the check and the act;
- parents the agent's account can write;
- the shell helper's quoting;
- a widened ACL mask;
- `release` removing another app's access, or a by-hand entry;
- a compromised Workbench reaching `add`;
- a huge tree blocking the agent.

## 6. Do not change

- **agent:** `apps.py`, `apps_catalogue.yaml`, `client_doors.py` (rows 25, 34); `tray.py`, `tokens.py` (row 35); `admission.py` (row 9).
- **workbench:** `store.py` (rows 7, 26-28, 30, 47; no new table is needed); `tools.py` (rows 29, 32); `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (rows 52, 60); `MessageView.tsx`, `Markdown.tsx` (row 31).
- **ui:** `ResourceTree.tsx`, `settingsTopics.ts` (row 33); `ConfigField.tsx`, `configValue.ts` (row 62).
- **Shared:** `install.sh` belongs to row 8. Change only `write_app_units()` and the package list, then rebase on row 8.

## 7. Size, risks, split, calls

**M, about 3 days,** on one branch, `r23-folder-access`:
- **23a (M):** the contract, the refusals, Windows, the console, and Workbench's link.
- **23b (S-M):** the Linux helper.
- **23c (S):** release, if FA-C1 is taken.

Then one acceptance run, and one adversarial review.

**Risks:**
- A privilege change sits behind a button.
- A shell helper parses paths as root.
- Propagation on a large tree is slow.
- J20's finding: an operator session, or a compromised root that forges one, can now widen Workbench's reach with nobody at the machine. A compromised root is out of scope (memory `feedback_compromised_root_machine`). An operator can already run any binary as LocalSystem through a runtime's `binary`.

**Calls only Troy can make:**
- **FA-C1: should revoking a grant in Workbench remove the OS access?** Today it does not. Recommended: yes, when no other grant names the folder, and only what Eugene added. The removal goes through a route that only removes and takes the app's own key, so it cannot widen access.
- **FA-C2: may a folder inside a person's home be given?** Recommended: refuse, and point to Job Sites. They work as the person and need no permission change (J20), and Linux's `ProtectHome` blocks homes anyway. The expert override is the OS's own Security tab.

## Calls answered by Troy (2026-10-21)

- **FA-C1: Choice 1.** Revoking a grant removes the permission Eugene added, and only that one.
- **FA-C2: Choice 1.** Folders inside a home folder are refused, with a pointer to Job Sites.

## Calls answered by Troy (2026-10-24)

- **R23-OVERLAP: Choice 1, as built.** Windows refuses a grant inside or around another grant for the same app, and names the grant to remove first.
- **R23-UNKNOWN: a new choice, "Prompt the user whether to delete or not."** When removal finds an entry that lets the app's account in and that Eugene did not add (Linux or Windows), the removal stays incomplete and the console asks the owner, naming the folder and the entry: "Remove this entry too" or "Keep it". Remove: the agent checks the entry again and deletes only that entry, then finishes the removal. Keep: the entry stays, and the grant's card says that the app still has that access through an entry Eugene did not add. This also covers a null DACL and an item the app owns, when Eugene cannot restore them itself. Only an operator session can decide.

## What building found (2026-10-24)

Built after two adversarial reviews. Each item has a test that failed before it, and the acceptance runs each one on real Windows and Linux.

**Removal on Windows takes back what the app's account can reach, or says what it cannot.**
- An app owns what it makes, and an owner can always change an item's DACL. Removal gives each item the app's account owns to the owner of the granted folder (the person). The agent enables `SeRestorePrivilege` on its own thread for this, and LocalSystem has it.
- A null DACL lets everyone do everything. Removal replaces a null DACL that the app set with what the item inherits from its parent.
- An app can protect a folder it made. Then Eugene's inherited entry becomes an explicit copy. Removal removes that copy and the inherited entries below it.
- If removal cannot remove Eugene's own entry, it fails and names the item. If it finds an entry that Eugene did not add, or it cannot restore a null DACL or an app-owned item, the removal is incomplete and the owner decides each entry (R23-UNKNOWN). Nothing of unknown origin is deleted without the owner's choice.
- The grant saves the account's own entries, the folders already protected, the items it already owned and the null DACLs. Removal leaves all of these as they are.
- One grant per folder tree: Windows refuses a grant inside or around another grant for the same app. A grant inside another finds the outer grant's inherited rights and records nothing, so removing the outer grant would also take the inner grant's access. Linux keeps overlapping grants, because its helper restores them.

**The Linux root helper checks every name a folder has.**
- A bind mount, a disk mounted twice, or a home's disk bound elsewhere gives a folder another name, and `realpath` keeps it. The helper reads the mount table and refuses when any name is a system folder, a home or Eugene's folder. If the table cannot be read, the helper refuses. It reads the table again just before it applies a grant.
- Removal keeps the entries for Eugene's group that were there before the grant, and finds them by identity, so a rename does not lose them. An item nobody changed since the grant gets its recorded ACL back exactly.
- An entry for Eugene's group that someone changed after the grant stays, and the owner decides it. The helper acts only on an entry that its own root-owned ledger lists, and checks the same item and the same value again before it removes it.
- On a Linux system install, a folder inside Eugene's prefix or a home is refused with that rule ("This is Eugene's own folder", or the pointer to Job Sites). An unsafe parent is named only when no other rule refuses the folder.
