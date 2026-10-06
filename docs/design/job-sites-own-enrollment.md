# Job Sites as their own enrollment, with the workspace server (slice 2b)

**Status:** a design, 2026-10-06. Nothing in it is built. **Calls J23-J35
(§4) are Troy's to take.** It builds on J1-J22 and J6a-J6i
([`remote-nodes.md`](remote-nodes.md) §6), which it does not reopen. J19-J22
(§6.4 there) are the reason it exists: a job site is its own enrollment,
the operator-managed node folders retire, the standalone install waits, and
all of it is designed together with slice 2b (J6h, J6i).

Code anchors are at the commits measured on 2026-10-06:

| Prefix | Repo, path | Commit |
|---|---|---|
| `A/` | `agent/src/eugene_plexus_agent/` | `f6705fc` |
| `C/` | `control/src/eugene_plexus_control/` | `d4a7dda` |
| `S/` | `site-host/src/eugene_plexus_site_host/` | `38d7ed8` |
| `W/` | `workbench/src/eugene_plexus_workbench/`, and `W/web/` = `workbench/web/src/` for its pages | `d872e00` |
| `U/` | `ui/src/` | `52d84f7` |

---

## 0. The shape, in one page

**A job site is an enrollment held by one program, the site host, running
as its owner's own OS account.**

- The site host keeps the site's key, pins the root, polls it, and serves
  the site's tools. It no longer depends on the agent's relay (J23).
- It runs as the person who owns the site, so their tools reach what they
  can reach, and nothing has to be granted to a service account (J24).
- On a machine that is also a node, the agent installs, starts and updates
  the site host. It holds none of the site's identity, and the two
  enrollments share nothing but the machine (J21).
- The root keeps sites in a registry of their own. A site has no address
  and no route to it, and its key opens four routes (J31).
- The console gets a **Job sites** branch for membership. Workbench keeps
  everything a site's owner does, and People loses *Files on your machines*
  (J19).
- The file server becomes the **workspace server** (J6h): read, write, edit
  and search inside workspaces, under allow/ask/deny rules per person,
  workspace, tool and path (J28). Commands come last (J29).

**One finding reshapes the order of work.** The by-hand folder permission
that Troy rejected was, by accident, the one check a compromised root could
not forge. Under J6b a root can already forge a site owner's policy edit;
today that edit can only reach folders someone granted the isolated account
by hand. Once the site runs as its owner (J6i), a forged edit reaches
everything the owner's account can. J20 removes the step, as Troy asked, and
J14 (person-held keys checked at the site) is what puts a check back (§2.8,
J29).

**What one machine looks like when it is both** (Amish_Station after this
design):

| Process | OS account | Holds | Talks to |
|---|---|---|---|
| The agent | LocalSystem (Windows service), `eugene-plexus` (Linux) | The node's enrollment (`node.yaml`) | The root, as the node |
| The site host | The site owner's own account, e.g. `AMISH_STATION\troyc` | The site's key, its policy, its audit log | The root, as the site, by its own poll |
| The site's tools: the workspace server, local MCP servers, later commands | The same account, as children of the site host | Nothing | Only the site host |
| Apps (Workbench, Open WebUI) | Their own accounts (C1), as today | Their own keys | The root and the gateway |

Revoking either enrollment leaves the other working. Neither key can sign
for the other.

---

## 1. What exists today (measured 2026-10-06)

### 1.1 A job site is a node with one grant

- **The record.** A site is a `NodeRecord` whose grants are exactly
  `["files"]`, with an `owner` (a person's id) and no `url`
  (`C/applied.py:178-215`; enrollment sets the grant at
  `C/routes/nodes.py:636`). No log operation is specific to sites; they go
  through `enrollNode` and `revokeNode` (`C/applied.py:78-102`).
- **It is named, everywhere, by its node name.** Jobs, reports and helper
  configuration are keyed by name. An operation is bound to one enrollment
  by the node's signing key plus `enrolledAt` (`C/applied.py:1010-1015`,
  `C/routes/node_helpers.py:123-131`).
- **Its key is in the trust bundle every node receives**, as issuer
  `node:<name>` with grants `["files"]` (`C/trust.py:85-89`). A `files`
  token reaches the helper's poll, claim and result, and the bundle;
  every other route refuses it (`C/dependencies.py:74-81,124-141`;
  `C/routes/control.py:371`).
- **Join tokens live in memory**, as hashes. They are not replicated and do
  not survive a promotion (`C/join_tokens.py:9-28,87-98`).
- **Workbench can invite a site only when the public route is on**: the
  invite needs both `nodes_origin` and `nodes_public`
  (`C/routes/node_helpers.py:733-737`). That did not matter while LAN nodes
  shared files through node folders. Under J20 it would leave a LAN-only
  install with no way to share files at all.

### 1.2 The agent holds it

- **One agent holds one enrollment.** There is one identity record with one
  name, one `node.yaml` and one pins file. A second join is refused as
  `already-enrolled` (`A/node_identity.py:304-335`,
  `A/enrollment.py:178-186`).
- **The agent relays for the site.** `SiteHostRelay` polls the root with
  the agent's own token, claims each operation, hands it to the site host
  over loopback, and posts the answer back (`A/site_host.py:393-432`).
  `validate()` refuses an operation unless its node name, signing key and
  `enrolledAt` match this machine's enrollment, so one queued for an
  earlier enrollment of the same name cannot run (`A/site_host.py:303-332`).
- **The site's owner arrives in every poll answer** (`siteOwner`) and is
  pinned from there (`C/routes/node_helpers.py:367-373`).
- **The site host is the app `node-files`**, a name kept from the helper it
  replaced. It runs in `node` mode or `site` mode, never both
  (`A/site_host.py:46-48,138-146`).

### 1.3 The account, and the permission step

- **Windows:** the host runs as the virtual account
  `NT SERVICE\EugenePlexusApp-node-files`, in a service the agent creates
  with pywin32 (`A/app_accounts.py:322-412`). The agent itself is
  LocalSystem.
- **Linux:** the host runs as a systemd dynamic user, started by a root
  broker the installer sets up (`eugene-plexus-apps-ctl.path`,
  `specs/scripts/install.sh:477-596`). The agent is the unprivileged
  `eugene-plexus` account with `NoNewPrivileges=yes`
  (`A/app_accounts.py:23-26`).
- **Per-user installs, macOS and containers get no site host**, because
  there is no account to isolate it in (`A/site_host.py:234-236`,
  `A/app_accounts.py:138-167`). The host refuses to serve tools unless it
  runs in one of the two isolated kinds (`S/settings.py:37,57`).
- **The permission step.** A folder that account cannot open is refused
  with *"Give it permission first"* (`S/host.py:422`). Workbench's Job sites
  page names the account to grant (`W/web/components/JobSites.tsx:176-181`).
- **Nothing in the agent runs a process as another user.** There is no
  `CreateProcessAsUser`, `LogonUser`, `WTSQueryUserToken`, `runuser` or
  `setuid` anywhere in it, and nothing finds the person signed in at the
  machine. The only process in a person's session is the Windows tray,
  started by its own logon task (`A/tray.py:9-27`).

### 1.4 Who names what

- **Workbench names machines by node name** in every call:
  - `/oidc/job-sites/{node}/…`;
  - the `node` field of `/oidc/sites/mcp`;
  - local-server ids `site:<node>:<server>`;
  - a chat's folder selections, `node:<folder id>` in `folderGrants`.

  These are in `W/api.py:300-307` and `W/node_folders.py:10-11,58-68,203-240`.
  It tells a LAN node's folders from a job site's only by a `jobSite`
  flag, and its pages call both *node folders*.
- **The console shows a job site as a machine**: an `agent:<name>` leaf
  under Machines, a Library leaf, and an apps query through the
  `node:<name>` hop (`U/lib/resourceTree.ts:494-506,556-566`;
  `U/components/ResourceTree.tsx:141-153`).
- ***Files on your machines*** is `NodeHelpers.tsx`, mounted on People
  (`U/app/people/page.tsx:113`). It turns file support on per node,
  registers folders, sets the owner's access, and edits each person's
  `helperGrants`. Those are written through `PATCH /v1/people/{id}` under a
  plain operator check, not a capability (`C/routes/people.py:56`).
- **The console points to Workbench in words only.** *"(Workbench, Job
  sites)"* has no link (`U/components/NodeHelpers.tsx:134-143`).

### 1.5 Found while measuring

- **A job site can announce an address.** The signed announcement route
  checks the signature and refuses only a move from a non-public address to
  a public one. A site has no previous address, so the check passes
  (`C/routes/nodes.py:164-320`, `C/node_address.py:145-158`). No test
  covers it. It is live on edge and wants a fix before this design is
  built; the site registry then removes the route for sites entirely.
- **Deleting a person leaves their sites enrolled**, owned by nobody
  (`C/applied.py:871-875`).
- **Revoking a node leaves its helper record behind.** It is ignored only
  because of the key-and-date binding (`C/applied.py:527-536`).
- **A re-enrolled site's old summary is served** until its next poll
  (`C/node_helpers.py:265-274`).
- **On Linux the `site` CLI probably reads the wrong data directory**, and
  `sudo … site server add` writes a file the agent's account cannot read,
  which is then treated as no servers (`A/site_cli.py`,
  `A/site_host.py:87-89`). This is read from the code, not run.

All but the first retire with this design.

---

## 2. The shape

### 2.1 Two enrollments, one machine

A machine may be a node, a site, or both (J19). The rule that makes "both"
safe: **the two enrollments share nothing but the machine.**

- Each has its own key, its own registry entry and its own channel to the
  root.
- Neither process uses the other's identity or reads the other's files.
- On Linux the OS enforces that. The site's directory belongs to the
  person, and `eugene-plexus` cannot read it. On Windows the agent is
  LocalSystem and could read anything; there, "does not hold" is a rule
  the code keeps, not one Windows enforces. That is the same limit
  `remote-nodes.md` §3.7 states for an administrator.
- **A machine that is only a site** (Troy's work PC) has no agent. It waits
  for the standalone install (J21). Nothing in this design gives the site
  host a dependency that install would have to remove (§2.12).

### 2.2 The site's enrollment (J23)

**The key.** The site host generates an Ed25519 token key at join, in its
own data directory. It signs short tokens with issuer `site:<id>` and
audience the root, and nothing else.

**The join.** The invitation names a person, as today, from the console or
from Workbench. At the machine:

1. The installer one-liner, run elevated, installs or updates the site host
   program. On a machine that is already a node it adds the site without
   reinstalling the node (J35).
2. It chooses the OS account the site will run as (below), and creates the
   site's data directory, readable only by that account and administrators.
3. It runs the site host's own `join` **as that account**. The person types
   their Eugene password there (rule 1 of `remote-nodes.md` §3.3). When
   the root's address is HTTPS, the site pins the root's identity key from
   the command (J7a).
4. The root answers with the site's id, its owner's person id and the root's
   key. **The site records its owner from that answer, once**, so the poll
   answer stops carrying `siteOwner`.
5. The installer writes the binding, *site id → account → data directory*,
   to a file only an administrator can write. The agent reads it to know
   what to supervise; on Linux the root broker reads it to know whom to run.

**Choosing the account.** The installer uses the account that ran it. If
that is an administrator who is not the person signed in at the machine,
which happens when a standard user elevates with someone else's password, it
uses the signed-in person. It prints the choice (*"Tools will run as
AMISH_STATION\troyc"*), and `-SiteAccount` overrides it. It refuses
LocalSystem, root, the agent's account, service accounts, and Linux uids
below 1000.

**Leaving and removal.**
- The owner leaves from Workbench, or at the machine by uninstalling.
- Eugene's owner removes a site from the console (the `membership`
  capability).
- Either one revokes the key at the root. The site host's next poll is
  refused; it stops, and says why.
- **Deleting a person removes the sites they own.** A site has exactly one
  owner, and only the owner can grant anything on it (§1.5).

### 2.3 The root's side

**A registry of its own.** `sites` sits beside `nodes` in the replicated
state. A site record holds:
- its id (random, fixed for the enrollment) and a label, the machine's name
  by default;
- its owner, a person id;
- its token public key and `enrolledAt`;
- the node that hosts it, if any, as that node attests (J32).

New log operations are `enrollSite`, `removeSite` and `setSiteHost`.
`deletePerson` also removes that person's sites.

**Its key.** The `site` grant replaces `files` in the canonical
`specs/platform` `tokens.py`, which is re-vendored as before. A site's key
may sign only tokens addressed to the root. **Site keys are verified by the
root alone and are not in the trust bundle nodes receive.** No node ever
checks a site's token, and the bundle today lists every site's name and key
to every node (§1.1).

**Its routes.** A site's token opens exactly four:
- `POST /v1/sites/poll`;
- `POST /v1/sites/operations/{id}/claim`;
- `POST /v1/sites/operations/{id}/result`;
- `POST /v1/sites/leave`.

Enrollment (`POST /v1/sites/enroll`) needs the join token, as node
enrollment does. A site has no address, so no address route accepts it
(§1.5).

**The relay and queue.** The broker keeps its limits and its three checks
(at submit, at claim, before the answer is released). It is keyed on site id
and bound to *(site id, key)*, so an operation queued for an earlier
enrollment never reaches a later one. That is the check `validate()` made in
the agent; the site host now makes it itself.

**Workbench's routes** (`/oidc/sites/*`, `/oidc/job-sites/{site}/…`) take
site ids. The invite no longer needs the public route (J31).

**Node folders retire (J20):**
- the console's `/v1/node-helpers` routes;
- `putNodeHelper`, `ownerAccess` and `devGrants` on LAN nodes;
- people's `helperGrants`;
- the `node-files` capability.

Their old log entries still replay, and grant nothing.

### 2.4 Running as the person (J24, J25)

**The whole site host runs as its owner:** policy, audit log, the workspace
server, local MCP servers and later commands. It is one process with its
tools as children. That is Claude Code's shape, and it is the only shape the
standalone install can have without administrator rights (§2.12).

| Install | The agent runs as | The site host is started by | It runs |
|---|---|---|---|
| Windows service | LocalSystem | A Task Scheduler task per site: principal the person, logon type S4U, limited token, at boot, restarted on failure. The agent starts, stops and watches it | Signed in or out. While signed out it has no network credentials, so it reaches this machine's own files only (J25) |
| Windows service, an account S4U refuses | LocalSystem | A task at the person's sign-in, with their interactive token | While the person is signed in |
| Windows per-user | The person | The agent, as its own child | While the person is signed in, as the agent is |
| Linux system | `eugene-plexus` | The root broker: `eugene-plexus-site@<id>.service` with `User=` the person and `NoNewPrivileges=yes` | Always |
| Linux `--user` | The person | The agent, as its own child | As the agent does |
| macOS (per-user) | The person | The agent, as its own child | As the agent does. The owner's own tools only, until a folder boundary exists for sharing (§2.6) |
| Docker | — | Not a site. A container's files are not a person's | — |

**Rules that hold in every row:**
- **The site host refuses to serve tools unless it runs as the account in
  its binding.** It never serves as LocalSystem, root or the agent's
  account. This replaces the isolated-account check (`S/settings.py:37`).
- **It always gets a limited token.** Tools never run elevated. J9's proof
  of administrator rights is about turning a tool on, not about running it
  elevated.
- **No password is stored.** R2.6 rejected a stored-password task because a
  Microsoft account's password changes online and the stored copy does not
  follow (`windows-comes-back-by-itself.md` §call 1). The same reasoning
  holds here.
- **On Linux, the program that runs as the person is root-owned.** The
  installer and the root update unit install and update it; the agent's
  account never writes it. Whoever can write that program can become the
  person. Keeping it out of the agent's reach keeps row 2's property: the
  agent's account cannot become anyone
  ([own-account-run.md](../acceptance/own-account-run.md)). The root
  update unit already follows this rule: the agent hands it only a commit
  or tag, and nothing the agent writes is ever executed as root
  (`A/update_apply.py:12-19,439-450`). On Windows the program sits in the
  administrator-only install directory, as the agent's does.
- **The local-server list moves beside the binding.** An administrator
  writes it at the machine (§6.2 of `remote-nodes.md`). The site host reads
  it directly, and cannot write it. The agent's copy and its hash in the
  environment are no longer needed.

**Owed by measurement before this is built** (Windows 11, on real accounts):
- S4U for a Microsoft account (Troy's `troyc` is one), for an Entra ID
  account, and for a domain account away from its domain;
- whether S4U for an administrator, with run level Limited, yields the
  filtered token;
- profile loading under S4U (`%LOCALAPPDATA%`, `HKCU`);
- what a signed-out S4U process can and cannot reach.

### 2.5 What becomes of the permission step

**Nothing remains for anyone to run.**
- The owner's tools reach what the owner can.
- A folder shared with another person is reached as the owner, confined to
  that folder (§2.6).
- No service account is granted anything.

At upgrade, the `node-files` virtual account, its service and its data are
removed. **Entries a person added by hand to their folders' permissions for
that account stay**, naming an account that no longer exists. They grant
nothing. This product does not edit the permissions of folders it did not
create.

### 2.6 The workspace server (J6h, J28)

**One server per site, with the id `files` kept.** Workbench, its tool
offers and its chats key on `files` (`W/tools.py:326-331`), so keeping the
id costs nothing. What a site shares are now called workspaces. Each is
today's registered folder: a name unique on the machine, a path and an
identity.

**Its tools:**
- today's `list_directory`, `read_text` and `write_text`, unchanged;
- `read_text` gains an offset and a length, so a large file is read in
  pieces instead of being refused at 32 KiB;
- `edit_text`: replace an exact passage, with the file's hash as a
  precondition, as `write_text` already uses;
- `glob`: files matching a pattern;
- `grep`: lines matching a pattern, with file and line.

Every answer stays under the channel's 70 KB, and says when it stopped
short. Commands (`run_command`) are the last slice (J29).

**Rules: allow, ask or deny, per person, workspace and tool, with optional
path patterns inside the workspace.** Deny wins, then ask, then allow.
Anything outside every workspace is denied. The owner adds a workspace to
reach more, as Claude Code's additional directories do.

| Who | Reads, `glob`, `grep` | `write_text`, `edit_text` |
|---|---|---|
| The owner, in their own workspaces | allow | ask |
| Someone the owner shared a workspace with to read | allow | deny |
| Someone the owner let change files | allow | ask, or allow when the owner chose *"without asking you"* (today's standing pre-approval) |

**Who answers "ask".** Workbench already asks the person to approve every
call (`W/answers.py:36,381-412`). Under these rules it asks only for "ask",
and runs "allow" without a prompt. The site records which one the call
claimed. **Until J14 the site cannot check that an approval happened**, so
an "ask" is exactly as strong as the root (J29).

**The boundary.**
- **For the owner, the rules are the boundary.** By J6i the OS is not: the
  host runs as the owner. Troy accepted that cost.
- **For anyone else, every call is also confined to the shared folder in
  code**, as today:
  - on Windows, by C6's handle-relative opens that refuse links
    (`S/folder_windows.py`);
  - on Linux, by Landlock, which the kernel enforces per thread
    (`S/folder_linux.py`).

  macOS has neither yet, so a macOS site serves its owner only.

### 2.7 Other people on someone's site (J26, J27)

- **A person given a workspace on someone else's site acts as the site's
  owner's account**, confined to that workspace, with file tools only. They
  never get commands.
- **A local MCP server the owner grants them, tool by tool, runs as the
  owner.** It runs in the host's account today; this keeps that.
- **A person with an account of their own on that machine can have their
  own site there** (J26). Each site is its own enrollment, owned by one
  person and running as that person. The console groups them by machine.

### 2.8 What a compromised root reaches (J29)

| Through | Slice 2, today | 2b.1, own enrollment | 2b.2, runs as its owner | 2b.3, workspace | 2b.4, commands |
|---|---|---|---|---|---|
| **Access people were given** | Granted folders, as the isolated account | The same | The same folders, as the owner | Workspaces: read, write, edit, search | Everything the owner's account can do |
| **A forged edit from the owner** (J6b's stated limit) | Only folders a person granted the isolated account by hand | The same | **Anything the owner's account can read or write** | The same | The same |

**The by-hand permission was the one check a compromised root could not
forge.** It was unintended, and it was the step Troy rejected. J20 removes
it. J14 is what puts a check back. It has two halves, and they guard
different things:
- **J14a, signed policy edits.** Every management action is signed by a key
  only the owner holds. The site checks it against the public key it pinned
  at its join, at the machine. A compromised root is then held to what
  owners actually granted.
- **J14b, signed calls.** Each call the person approves is signed by them,
  which the site checks. That makes "ask" a check the site makes itself. It
  is also what commands need: with commands, a forged call is the whole
  account.

**A sketch, for J14's own session.**
1. At the join, the installer shows a short pairing code, which never leaves
   the machine.
2. The owner types it into Workbench. Workbench registers a passkey and sends
   its public key, with a MAC under the code, through the root.
3. The site accepts the key only if the MAC checks, so the root cannot
   substitute its own.
4. From then on, Workbench asks the passkey to sign each edit, and later
   each call.

A passkey wants a gesture every time, so silent forgery at scale stops. A
passkey prompt does not show what it signs, so a compromised Workbench could
still ask a person to sign one wrong thing.

### 2.9 The console

**The Job sites branch** sits beside Machines, with `sel` tokens `sites` and
`site:<id>`. It is membership only (J19):
- **The list** shows each site's label, its owner (a link to People),
  whether it is online and its last contact, its version, and the node it
  runs on (a link to Machines).
- **Invite** names a person and shows the one-liner. It says the same
  command adds a site to a machine that is already a node (J35).
- **Remove** revokes the site.

**Machines** no longer lists job sites. There is no agent leaf, no Library
leaf, and no apps query through the node hop. A node that hosts a site shows
one line, *"Also a job site: Troy's"*, linking to it. **People** loses *Files
on your machines* and folder access; each person shows the sites they own,
linking to the branch. **Cross-links both ways**
(`feedback_cross_link_related_settings`):
- node ↔ site;
- site ↔ its owner in People;
- the site page → Workbench's Job sites, as a real link, with Workbench's
  address taken from the apps registry.

**Dev mode** (J13, J13b, J6e) adds a section to a site's page and only
exists in dev mode (J33). It shows:
- the site's workspaces and servers, from its last report;
- Eugene's owner's own grants there, which J13b allows;
- the line saying whether the site's owner has let Eugene's owner in.

The entry point's setting becomes `public_sites`, worded *"Job sites can
connect from anywhere"* (J31).

### 2.10 Workbench

- **Sites are named by id**, with labels like *Amish_Station (yours)*.
- **The Job sites page** drops the permission hint. It says which account
  the site runs as, and whether it works while the person is signed out
  (J25).
- **Add a job site** works on a LAN-only install (J31). It says that on a
  machine that is already a node, the same command adds the site (J35).
- **The rules editor** arrives with the workspace server (2b.3). "Allow"
  runs without a prompt; "ask" prompts as every call does today.
- **Old selections** (`node:<folder id>`, `site:<node>:<server>`) show as
  removed, which Workbench already does for a withdrawn grant.

### 2.11 Migration (J34)

Node folders shipped on edge on 2026-10-04. No release carries them:
v0.1.0 is 2026-10-02. **Nothing converts.**
- **LAN node folders and their grants** (`putNodeHelper`, `ownerAccess`,
  `helperGrants`) replay and grant nothing. The console says once what
  retired, and links to Job sites. Converting them is the wrong move: they
  were decided by Eugene's owner, and J11 says the owner's decisions do not
  become a person's.
- **Slice 1 and 2 job sites** are nodes with the `files` grant. After the
  upgrade the agent no longer relays for them, so they stop. Job sites lists
  them as *joined before sites had their own enrollment: remove it and add it
  again*. Their `policy.json` stays on disk. A new site for the same person
  on that machine imports its workspaces, people and servers.
- **Workbench chats** keep their history. Their old selections show as
  removed (§2.10).
- **Troy's Amish_Station:**
  1. The upgrade removes the `node-files` service and account.
  2. Troy adds Amish_Station as his site from Workbench, by running the
     one-liner on the machine.
  3. He adds `C:\Users\troyc\…` workspaces. Nothing has to be granted.

### 2.12 What J21's standalone install will need

This design is built so that none of it has to be undone:
- **The site host is self-contained.** It joins, pins the root, polls,
  keeps its policy and audit log, and serves its tools, with none of the
  agent's code or files (J23).
- **Its launch is a binding file and a data directory.** An agent-hosted
  site and a standalone one differ only in who starts it.
- **The standalone installer** installs a Python and the site host program,
  then registers the start:
  - **without administrator rights:** a logon task (Windows), a
    `systemd --user` unit (Linux) or a LaunchAgent (macOS), running while the
    person is signed in;
  - **with them:** the S4U task, or a system unit with `User=`.
- **Updates.** A standalone site host updates itself, to the version the
  root names in its poll answer. An agent-hosted one ignores that, and the
  node updates it.
- **Local servers and J9's consent need administrator rights**, because the
  file holding them must be one the person cannot write. A per-user
  standalone install has no local servers marked `system`.
- **What would have to be undone, and so is not built:**
  - any site logic in the agent beyond supervision;
  - any use of the node's enrollment, trust bundle or relay by the site;
  - any path in the site host's launch that only an agent can provide.

---

## 3. Slices, in build order

**2b.1, a site of its own** (J23, J26, J31-J35):
- the site registry, the routes and the `site` grant;
- the site host holding its enrollment and polling;
- the agent supervising instead of relaying;
- the Job sites branch, People's section removed, and Workbench by site id;
- the migration.

The site host still runs in its isolated account. *Done when:*
- Amish_Station is a node and Troy's site at once, each revocable alone;
- a site behind WSL2's NAT joins over `public_sites`;
- a site on the root's LAN joins with no public route;
- a site's key is refused everywhere but its four routes;
- deleting a person removes their sites.

**2b.2, it runs as its owner** (J24, J25, J27, J30):
- the S4U task, the logon task, and the broker's unit with `User=`;
- the isolated account removed;
- per-user installs on Windows and Linux host sites.

*Done when* Troy shares `C:\Users\troyc\Projects` from Workbench with
nothing granted by hand, and Jessie's workspace there is confined to it.
**2b.1 and 2b.2 ship together.** No release has the first without the
second, because 2b.1 alone keeps the permission step.

**J14, designed next** in a session of its own. J14a (signed policy edits)
is then built.

**2b.3, the workspace server** (J28): the new tools, the rules, and
Workbench's editor and prompts.

**2b.4, commands** (J29): `run_command`, after J14b.

**Then slice 3**, cross-site copy on the held channel (J10), as
`remote-nodes.md` §5 had it.

---

## 4. Calls

| # | Call | Recommendation |
|---|---|---|
| J23 | Which process holds the site's enrollment | **The site host, end to end**: its key, the pin, its own poll. The agent's relay retires |
| J24 | Which OS account the site host runs as | **Its owner's own account, the whole host.** The isolated account and the permission step retire |
| J25 | Windows, while the person is signed out | **An S4U task where Windows allows it** (this machine's files only), **else only while signed in.** Never a stored password |
| J26 | Several sites on one machine | **Yes, one per person**, each its own enrollment and account |
| J27 | Someone else using a site | **As the owner's account, confined to what was shared**, file tools only, never commands |
| J28 | The workspace server and `files` | **Fold them**: one server, id `files` kept, allow/ask/deny rules, "ask" answered in Workbench |
| J29 | What waits for person-held keys (J14) | **Widening edits before any release with sites running as their owners; commands before commands ship.** J14 designed next |
| J30 | J9's proof of administrator rights, without a terminal | **The installer one-liner asks when it adds the site**; the elevated CLI stays for experts |
| J31 | How a site reaches the root | **Like a node:** the LAN address, or the nodes name. **`public_sites` only for machines outside**, on six paths. Site keys stay out of the node bundle |
| J32 | Linking a node and the site it hosts | **Attested by the hosting node, for display only** |
| J33 | Dev mode in a console that is membership only | **A dev-mode section on the site's page**, absent in production |
| J34 | Migration | **Nothing converts.** Notices, add again, and the old site policy imported for the same person |
| J35 | Making a node into a site | **The same installer one-liner, run at the machine**, adding the site without reinstalling the node |

### J23. Which process holds the site's enrollment

**Recommendation: the site host, end to end.** It generates and keeps the
site's key, pins the root's identity key and TLS list, polls, claims and
answers. The agent's `SiteHostRelay` and `validate()` retire, and the agent
only installs, starts and updates the program.

**Trade-off:** the root-pinning and join code moves out of the agent into the
site host. That is a second copy, vendored from `specs/platform` like
`tokens.py` under the no-shared-core rule. It is also exactly what J21's
standalone install needs. The alternative, the agent polling for the site
with the site's key, keeps one copy but makes the agent hold the site's
identity, which J19 says it must not.

### J24. Which OS account the site host runs as

**Recommendation: the site owner's own account, the whole host.** That
covers its policy, its audit log, the workspace server, local servers and
later commands. There is nothing to grant and no isolated account, and it
works on per-user installs and macOS.

**Trade-off:** every program the owner runs can read the site's key and edit
its policy. That is acceptable, because those programs already reach every
file the site could. The alternative splits the host in two: a part in its
own account, holding the key and staying online, and a part per person.
That keeps the key from the owner's programs, but adds a local channel
between the two, a second process per person, and keeps the isolated-account
requirement that excludes per-user installs and macOS.

### J25. Windows, while the person is signed out

**Recommendation: a Task Scheduler task with S4U logon, where Windows
allows it for that account.** It runs at boot, signed in or out, with this
machine's files only. Network shares and EFS-encrypted files need the
person's credentials, which S4U does not have. Where Windows refuses S4U
(probably Entra ID, and domain accounts away from the domain; to be
measured), it falls back to running only while the person is signed in.
Workbench says which applies. Never a stored password.

**Trade-off:** two start mechanisms to build and test, and S4U on Microsoft
and Entra accounts is unmeasured. The simpler choice, only while signed in
(Claude Code's shape), leaves a site offline after every Windows Update
reboot until someone signs in. That is the problem R2.6 fixed for the agent
itself.

### J26. Several sites on one machine

**Recommendation: yes, one per person.** Each is its own enrollment running
as its own person's account. The registry, the agent's list and the installer
allow several from the start; the console groups them by machine.

**Trade-off:** a little more to build and test now: several tasks or units,
and a binding per site. A shared household PC is the case. The alternative,
one site per machine, is simpler, but then a second person on that PC can only
use what the owner shares, as the owner's account.

### J27. Someone else using a site

**Recommendation: their calls run as the owner's account, confined to the
workspace shared with them**, by C6's handle-based opens on Windows and by
Landlock on Linux. They get file tools only, never commands. A local server
the owner grants them tool by tool runs as the owner, as it does today in the
host's account.

**Trade-off:** on Windows the confinement is this product's code, not an OS
boundary. A bug in it would expose the owner's whole account to the other
person. OS-enforced confinement is a later hardening: an AppContainer whose
SID the site host, as the owner, adds to the shared folder's permissions,
with no administrator needed. The alternative, an isolated account per
grantee, brings the permission step back.

### J28. The workspace server and `files`

**Recommendation: fold them.** The `files` server keeps its id and becomes
the workspace server. It gains `edit_text`, `glob`, `grep` and ranged
reads, under allow/ask/deny rules per person, workspace, tool and path. Deny
wins, and anything outside a workspace is denied. "Ask" is the approval
Workbench already prompts for; "allow" runs without a prompt.

**Trade-off:** until J14b, the site cannot tell an "ask" that was approved
from one a compromised root claims was. The alternative, a second server
beside `files`, keeps two tool sets for one folder, and two places for its
rules.

### J29. What waits for person-held keys (J14)

**Recommendation:**
- **Design J14 next**, in its own session.
- **No release ships a site running as its owner before J14a.** Owners sign
  their policy edits, and the site checks them.
- **Commands do not ship before J14b.** Persons sign their approvals.

Edge can carry 2b.1-2b.3 before J14a, with the limit stated, because Troy is
edge's only user.

**Trade-off:** the Claude-Code-like Workbench waits behind a design that
does not exist yet. The alternative, shipping everything root-trusted, means
a compromised root reaches every site owner's whole account: their files
first, and with commands everything. Today it reaches only what someone
granted by hand.

### J30. J9's proof of administrator rights, without a terminal

**Recommendation:** the installer one-liner asks one question when it adds a
site: *"Allow tools that change this machine's settings or run programs, as
troyc?"* The installer is already elevated, so its answer is the J9 proof,
recorded with the binding. The elevated `site` CLI stays as the expert path
for changing it later and for adding local servers. A tray action behind a
UAC prompt can replace that later.

**Trade-off:** consent is asked at join, before the person knows they will
want it. Changing it later means the installer again, or the CLI, until the
tray action exists. The alternative keeps the CLI as the only path, which is
the terminal step Troy has ruled out.

### J31. How a site reaches the root

**Recommendation:** a site joins and polls through the address node joins
already use: the root's LAN address, or the nodes name when the entry point
has one. The public mode, renamed `public_sites`, is only for machines
outside. It opens six paths:
- `POST /v1/sites/enroll`;
- the four site routes of §2.3;
- `GET /v1/trust/tls`.

The trust bundle leaves the public list, and leaving joins it. Site keys are verified by the root
only.

**Trade-off:** a site on the LAN without the entry point talks to the root in
clear text, as nodes do today (`remote-nodes.md` §7). Requiring the nodes
name for every site would add TLS on the LAN, but make every LAN-only install
set up the entry point before it can share a folder. Renaming the setting and
paths is a one-time contract and configuration migration.

### J32. Linking a node and the site it hosts

**Recommendation:** the node's agent reports which site ids it supervises,
and the root records that as `setSiteHost`. It is used for display and
cross-links only, never to authorize anything.

**Trade-off:** one more fact to keep honest. A removed node leaves its sites
reading *host unknown*, and a lying node can only mislabel. Without it, Troy
sees two unrelated entries named Amish_Station.

### J33. Dev mode in a console that is membership only

**Recommendation:** J19's *membership only* holds in production. In dev mode
a site's page gains a clearly labelled section with its workspaces, servers,
and Eugene's owner's own grants there (J13b). It also shows whether the
site's owner has let Eugene's owner in (J6e). The section does not exist in
production.

**Trade-off:** one console page has two shapes, by mode. The alternative,
dev-mode grants only in Workbench, has nowhere to put them: Eugene's owner
is not a person there, and Workbench hides Job sites from the owner
(`W/web/App.tsx:232-242`).

### J34. Migration

**Recommendation: nothing converts.**
- Node folders and their grants replay and grant nothing, with one notice
  in the console.
- Slice 1 and 2 job sites are listed as needing to be added again.
- A new site for the same person on the same machine imports the old site's
  policy.
- Old chat selections show as removed.

Everything here is edge-only.

**Trade-off:** edge users set things up again. Troy's Amish_Station had file
support turned on but no folder registered, since he stopped at the
permission step. Converting node folders would carry Eugene's owner's
decisions into a person's site, against J11, for an install base of about
one.

### J35. Making a node into a site

**Recommendation:** Workbench's *Add a job site* gives the same installer
one-liner for every machine. On a node it detects the existing install. It
installs the site host at the version that node's agent pins, and adds the
site without upgrading or re-enrolling the node.

**Trade-off:** a terminal command remains, the installer's one-liner, which
is the stated exception. The alternative is a page served by the node's own
agent on loopback, at the machine, where the person signs in. It identifies
their OS account from the browser's connection. That has no terminal, but it
is a new local page and a lookup per platform, and it does nothing for a
machine that is not a node (J21). It could come later.

---

## 5. What this design does not cover

- **J14 itself.** §2.8 sketches it; it gets its own session (J29).
- **The standalone site install** (J21). §2.12 lists what it will need.
- **Cross-site copy and the held channel** (slice 3), and approving a call
  at the machine.
- **OS-enforced confinement on Windows** for people other than the owner
  (J27's later hardening).
- **A folder boundary on macOS**, so a macOS site can share with others.
- **TLS between machines on a LAN**, as before (`remote-nodes.md` §7).
- **Managed-fleet enrollment** (J16), and transferring a site to another
  owner.
