# Job Sites as their own enrollment, with the workspace server (slice 2b)

**Status:** a design, 2026-10-06. Nothing in it is built. **Calls J23-J35
(§4) are Troy's to take.** Troy answered J26, J27, J30 and J34 the same
day (§4.1): one install serves every person on a machine, each as their own
local account. The text below is revised to match, which changed J24 and
J27 and grew slice 2b.2. It builds on J1-J22 and J6a-J6i
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

**A job site is one install and one enrollment per machine, held by one
program, the site host, which serves each person as their own OS account.**

- The site host keeps the site's key, pins the root, polls it, and keeps the
  site's policy and audit log. It no longer depends on the agent's relay
  (J23). It runs in an unprivileged account of its own and never opens
  anyone's files (J24).
- **Each person's tools run in a worker process under that person's own OS
  account**, so they reach what that person can reach, and nothing has to
  be granted to a service account (J24, J26). A person's Eugene sign-in is
  linked to their local account at the machine, the same way once sign-in
  with Google arrives (J27).
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
by hand. Once tools run as each person (J6i), a forged edit reaches
everything a linked person's account can. J20 removes the step, as Troy
asked, and
J14 (person-held keys checked at the site) is what puts a check back (§2.8,
J29).

**What one machine looks like when it is both** (Amish_Station after this
design):

| Process | OS account | Holds | Talks to |
|---|---|---|---|
| The agent | LocalSystem (Windows service), `eugene-plexus` (Linux) | The node's enrollment (`node.yaml`) | The root, as the node |
| The site host | Its own unprivileged account: `NT SERVICE\EugenePlexusApp-site-host` (Windows), a system user (Linux) | The site's key, its policy, its audit log, the links between people and accounts | The root, as the site, by its own poll; the workers |
| A worker for each linked person: the workspace server, local MCP servers, later commands | That person's own account, e.g. `AMISH_STATION\troyc` and `AMISH_STATION\jessie` | Nothing | Only the site host, over a local channel that proves its account |
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
  covers it. It is live on edge: [control#6](https://github.com/eugene-plexus/control/issues/6).
  The site registry removes the route for sites entirely, and 2b.1 closes
  the issue.
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
- On Linux the OS enforces that. The site host's directory belongs to its
  own account, and `eugene-plexus` cannot read it. On Windows the agent is
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
2. It creates the site host's own account and data directory, readable only
   by that account and administrators.
3. It runs the site host's own `join` **as that account**. The person who
   will own the site confirms at the machine (rule 1 of `remote-nodes.md`
   §3.3). Today that is their Eugene password, typed into the installer.
   When the root's address is HTTPS, the site pins the root's identity key
   from the command (J7a).
4. The root answers with the site's id, its owner's person id and the root's
   key. **The site records its owner from that answer, once**, so the poll
   answer stops carrying `siteOwner`.
5. The installer links the owner to the OS account that ran it (below).
6. The installer writes the site's id and data directory to a file only an
   administrator can write. The agent reads it to know what to supervise.

**One site serves every person on the machine (J26).** There is one
install, one enrollment and one owner per machine. The owner decides who
may use the site at all. Each person who may is served as their own OS
account, once they have linked it.

**Linking a person to their OS account (J27).** A link says: *this Eugene
person is this account on this machine.* It is made at the machine, never
from the root:
1. The person opens a page served on loopback by the machine's privileged
   starter (the agent, on a node), in a browser on that machine, and signs
   in to Eugene there.
2. The starter learns the OS account from the connection itself: on
   Windows, the account of the process that owns the client socket; on
   Linux, the socket's uid.
3. The OS account proves itself, and the Eugene sign-in proves the person.
4. The starter records the link in a file only an administrator can write.
   The site host reads it and cannot change it.

Because it is a browser sign-in, it works unchanged once Eugene signs people
in with Google or Microsoft (control#4). The installer makes the owner's
link at join from the account that ran it, so the owner never needs the
page. If that account is an administrator other than the person signed in at
the machine, it uses the signed-in person; `-SiteAccount` overrides.

Links are refused for LocalSystem, root, the agent's and the site host's
accounts, service accounts, and Linux uids below 1000. One person has one
link per machine, and one account belongs to one person. **A root cannot
make a link**: a link needs someone at the machine, signed in as that
account. **Nor can a compromised site host**, because the starter makes
and keeps the links itself. Removing a link is the person's or the owner's
choice, from Workbench; the starter removes it and the person's task.

**Sign-in at the machine also replaces the password in the installer,
later.** A person who signs in with Google has no Eugene password to type,
so the join's confirmation (step 3) moves to the same page when single
sign-on arrives.

**Leaving and removal.**
- The owner leaves from Workbench, or at the machine by uninstalling.
- Eugene's owner removes a site from the console (the `membership`
  capability).
- Either one revokes the key at the root. The site host's next poll is
  refused; it stops, and says why.
- **Deleting a person removes the sites they own** (§1.5), and the root
  sends no call in their name to any other site again. Their links there
  stay inert until that site's owner removes them. A site has exactly one
  owner, and only the owner decides who may use it.

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

### 2.4 Running as each person (J24, J25)

**Two parts.** The site host runs in an unprivileged account of its own and
holds the enrollment, the policy, the audit log and the links. It opens no
one's files, so it needs no folder permission. **A worker per linked person
runs that person's tools**: the workspace server, local MCP servers and
later commands, all as that person's own account. The site host starts a
worker when a call for that person arrives and none is running, through the
machine's privileged starter, and stops it when it has been idle.

**The local channel.** A worker connects to the site host over a named
pipe (Windows) or a Unix socket (Linux). The site host checks the
connecting process's account on every connection: on Windows, the client's
token read by impersonating it at Identification level (the worker connects
with `SECURITY_IDENTIFICATION`, so the site host can learn who it is but
never act as it); on Linux, `SO_PEERCRED`. A worker that is not running
as the account its link names is refused. So a call for Jessie can only ever
reach a process running as Jessie.

| Install | The agent runs as | A person's worker is started by | It runs |
|---|---|---|---|
| Windows service | LocalSystem | **The agent**, with the person's own session token (`WTSQueryUserToken`), started in their session as the agent's supervised child (J25 as revised, §2.4.1). The token is UAC's filtered one; if it is not (UAC off, the built-in Administrator), the agent filters it by hand | **While that person is signed in.** Their network shares and Credential Manager work, as in any program they run. At sign-out Windows ends the worker, and calls for them are refused, saying so |
| Windows per-user | The person | The agent, as its own child | While the person is signed in. Only the installing person can be served |
| Linux system | `eugene-plexus` | The root broker: `eugene-plexus-site-worker@<uid>.service` with `User=` the person and `NoNewPrivileges=yes` | Always |
| Linux `--user` | The person | The agent, as its own child | As the agent does. Only the installing person can be served |
| macOS (per-user) | The person | The agent, as its own child | As the agent does. Only the installing person, and only their own workspaces, until a folder boundary exists for sharing (§2.6) |
| Docker | — | Not a site. A container's files are not a person's | — |

On the per-user rows the agent's account is the only account there is, so
the site host and the one worker are the same person. A site there serves
only that person.

**Rules that hold in every row:**
- **The starter runs a worker only for an account in its own link file**,
  and only the pinned worker program. A link exists only because someone at
  the machine made it (§2.2). Neither a root nor the site host can cause a
  worker to start for anyone else.
- **A worker refuses to serve unless it runs as the account its link
  names.** It never serves as LocalSystem, root, the agent's account or the
  site host's. This replaces the isolated-account check
  (`S/settings.py:37`).
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
- **The local-server list moves beside the links**, in the same
  administrator-only place. An administrator writes it at the machine (§6.2
  of `remote-nodes.md`). Workers read it directly and cannot write it. The
  agent's copy and its hash in the environment are no longer needed.
- **The site host's own account becomes valuable.** It chooses which worker
  a call goes to, so whoever controls it can act as any linked person, within
  the site's rules. It cannot add a link or start a worker for an unlinked
  account. It runs only its own code, and opens no one's files.

#### 2.4.1 What the S4U measurement found (2026-10-06)

Measured on Amish_Station (Windows 11 Pro 10.0.26200, a workgroup machine)
with `troyc` (a Microsoft account, an administrator, signed in over Chrome
Remote Desktop), `jessie` (a local standard user) and `ep-s4u-admin` (a local
administrator), the last two created for this and never signed in. Six
elevated passes; the scripts are not kept. The live install and the root
were not touched.

**The design's Windows row could not be built.** Windows lets an account
register an S4U task only for itself:
- `Register-ScheduledTask`, `schtasks /NP` and the Task Scheduler COM API
  (`RegisterTaskDefinition`, `TASK_LOGON_S4U`) each answered *Access is
  denied* when registering for another account, from an elevated
  administrator and from LocalSystem alike;
- LocalSystem was refused even for `troyc`, while `troyc`'s own elevated
  session registered his task;
- granting `jessie` `SeBatchLogonRight` changed nothing.

**S4U at run level Limited does not filter an administrator.** `troyc`'s own
S4U task ran with elevation type 1 (no split token), High integrity,
Administrators enabled and `SeDebugPrivilege` on. Only an interactive-token
task got the filtered token (type 3, Medium, Administrators deny-only, five
privileges).

**What works, from LocalSystem:**
- **An S4U logon made by the starter itself**: `LsaRegisterLogonProcess`,
  then `LsaLogonUser` with an `MSV1_0_S4U_LOGON` and logon type Network,
  for `jessie`, `ep-s4u-admin` and `troyc` (a Microsoft account), in about
  1 ms. Logon type Batch is refused for `jessie` (1385), since standard users
  lack the batch logon right; Network needs only *Access this computer from
  the network*, which Users hold by default.
- **Filtering it by hand**, as UAC does: `CreateRestrictedToken` with
  `DISABLE_MAX_PRIVILEGE | LUA_TOKEN` and Administrators deny-only, Medium
  integrity, **and the token's owner and default DACL set to the user**.
  Without that last step, an administrator's token keeps Administrators as
  its owner and default DACL, the child cannot open its own objects, and it
  dies at start with `0xC0000142`. With it: Medium, Administrators deny-only,
  one privilege.
- `LoadUserProfile` creates and loads the profile of an account that has
  never signed in (`C:\Users\jessie`); `HKCU` and `%LOCALAPPDATA%` work;
  `CreateEnvironmentBlock` gives the person's environment.
- `CreateProcessAsUser` on a window station and desktop made for the worker
  (its DACL grants SYSTEM and the person, labelled low) or on the service
  desktop. A worker of its own is the safer of the two; it shares no desktop
  with SYSTEM's windows.
- **`WTSQueryUserToken`** for a signed-in person gives the filtered token
  already (type 3, Medium, Administrators deny-only), in their session.
- Interactive-token tasks and a `BUILTIN\Users` group task with a logon
  trigger **can** be registered by LocalSystem for other accounts, and run
  only while the person is signed in. Not needed, given the above.

**What a worker reaches when started that way** (all three accounts, signed
out or never signed in):
- its own profile, documents and `%LOCALAPPDATA%`: yes; another person's
  profile (`C:\Users\troyc` from `jessie` or the filtered admin): **denied**;
- HTTPS out: yes;
- **DPAPI: denied for an account that has not signed in** (`jessie`,
  `ep-s4u-admin`); it worked for `troyc` while he was signed in. Anything a
  local MCP server keeps in Credential Manager is out of reach while its
  person is signed out;
- network shares: not measured against another machine (the only one on
  this network is the root, which was not touched). An S4U logon carries no
  credentials, so no share that asks for them will open.

**The peer check holds.** A pipe server reading its client by
`ImpersonateNamedPipeClient` at Identification level got the right account
and SID for every worker above, filtered or not, in session 0 or 1.

**Not measured:** an Entra ID account and a domain account away from its
domain (neither exists here); a `troyc` worker after he signs out; a machine
whose policy has removed *Access this computer from the network* from Users
(then the S4U logon fails, and the person is served only while signed in,
which is J25's fallback).

**Troy's call on it (2026-10-06): only while signed in, with the session
token** (J25 revised). The recommendation was the agent's own S4U logon,
which works signed in or out. Troy took the simpler shape: one start path,
no logon sessions made by the agent, and a worker that reaches what the
person reaches in any program they run, network shares and Credential
Manager included. The cost, stated and accepted: after a reboot a person's
calls on that machine wait until they sign in. The S4U findings above stay
recorded for the day signed-out service is wanted; the hand filter is still
used, for a session token that UAC did not filter.

### 2.5 What becomes of the permission step

**Nothing remains for anyone to run.**
- Each linked person's tools reach what that person's account can.
- A folder shared with someone who has no link on the machine is reached as
  the owner, confined to that folder (§2.7).
- No service account is granted anything. The site host's account opens no
  one's files.

At upgrade, the `node-files` virtual account, its service and its data are
removed. **Entries a person added by hand to their folders' permissions for
that account stay**, naming an account that no longer exists. They grant
nothing. This product does not edit the permissions of folders it did not
create.

### 2.6 The workspace server (J6h, J28)

**One server per site, with the id `files` kept.** Workbench, its tool
offers and its chats key on `files` (`W/tools.py:326-331`), so keeping the
id costs nothing. The folders it works in are now called workspaces. Each is
today's registered folder: a name unique on the machine, a path and an
identity. **The server is not the job site:** the job site is the machine
and its enrollment; the workspace server is the set of file tools on it that
Workbench's model calls; a workspace is one folder those tools work in.

**Each linked person keeps their own workspaces and rules**, from Workbench,
because their workspaces are folders their own account reaches. The site's
owner decides who may use the site, and what people without a link get
(§2.7). The owner does not see another linked person's workspaces.

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
Anything outside every workspace is denied. A person adds a workspace to
reach more, as Claude Code's additional directories do.

| Who | Reads, `glob`, `grep` | `write_text`, `edit_text` |
|---|---|---|
| A linked person, in their own workspaces | allow | ask |
| Someone without a link, given a folder to read | allow | deny |
| Someone without a link, allowed to change files | allow | ask, or allow when the owner chose *"without asking you"* (today's standing pre-approval) |

**Who answers "ask".** Workbench already asks the person to approve every
call (`W/answers.py:36,381-412`). Under these rules it asks only for "ask",
and runs "allow" without a prompt. The site records which one the call
claimed. **Until J14 the site cannot check that an approval happened**, so
an "ask" is exactly as strong as the root (J29).

**The boundary.**
- **For a linked person, their OS account and their rules are the
  boundary.** Their account's permissions decide what can be touched at all,
  and their rules narrow it. Beyond the rules, nothing confines a call to
  its workspace: J6i accepted that cost.
- **For someone without a link, every call is also confined to the shared
  folder in code**, as today:
  - on Windows, by C6's handle-relative opens that refuse links
    (`S/folder_windows.py`);
  - on Linux, by Landlock, which the kernel enforces per thread
    (`S/folder_linux.py`).

  macOS has neither yet, so a macOS site serves only its owner.

### 2.7 People on a site (J26, J27)

- **A person with a link works as themselves.** Their calls run in their own
  worker, as their own account, with that account's permissions (Troy:
  their sign-in is *"attached to the local permissions for that person"*).
  Commands, when they come, run as them too.
- **A person without an account on the machine** can still be given a
  folder by the site's owner. Their calls run in the owner's worker, as the
  owner, confined to that folder, with file tools only. They never get
  commands.
- **A local MCP server** runs in the worker of whoever calls it, so it acts
  with that person's permissions. For someone without a link, it runs as the
  owner, tool by tool as the owner granted, as it runs in the host's account
  today.
- **Who may link.** The site's owner chooses, from Workbench, which people
  may use the site. Each of them makes their own link at the machine.

### 2.8 What a compromised root reaches (J29)

| Through | Slice 2, today | 2b.1, own enrollment | 2b.2, runs as each person | 2b.3, workspace | 2b.4, commands |
|---|---|---|---|---|---|
| **Access people were given** | Granted folders, as the isolated account | The same | The same folders, as each linked person | Workspaces: read, write, edit, search | Everything each linked person's account can do |
| **A forged edit in a person's name** (J6b's stated limit) | Only folders a person granted the isolated account by hand | The same | **Anything a linked person's account can read or write** | The same | The same |

What a compromised root still cannot do: make a link, or reach an account
nobody linked. Those need someone at the machine (§2.2).

**The by-hand permission was the one check a compromised root could not
forge.** It was unintended, and it was the step Troy rejected. J20 removes
it. J14 is what puts a check back. It has two halves, and they guard
different things:
- **J14a, signed policy edits.** Every management action is signed by a key
  only the person it speaks for holds: the owner, for who may use the site;
  each linked person, for their own workspaces and rules. The site checks it
  against the public key it pinned at the machine, at the join or at the
  link. A compromised root is then held to what people actually granted.
- **J14b, signed calls.** Each call the person approves is signed by them,
  which the site checks. That makes "ask" a check the site makes itself. It
  is also what commands need: with commands, a forged call is the whole
  account.

**A sketch, for J14's own session.**
1. At the join, or when a person links, the machine shows a short pairing
   code, which never leaves the machine.
2. The person types it into Workbench. Workbench registers a passkey and sends
   its public key, with a MAC under the code, through the root.
3. The site accepts the key only if the MAC checks, so the root cannot
   substitute its own.
4. From then on, Workbench asks the passkey to sign each edit, and later
   each call.

A passkey wants a gesture every time, so silent forgery at scale stops. A
passkey prompt does not show what it signs, so a compromised Workbench could
still ask a person to sign one wrong thing.

**J14 is now designed:** [`person-held-keys.md`](person-held-keys.md)
(2026-10-06), calls J39-J49 for Troy. The browser measurement there changes the
sketch above: a passkey cannot bind to an IP and plain-HTTP LAN is not a secure
context, so a key usable *from central Workbench* needs the HTTPS entry point,
while the one key every install can hold is a WebCrypto key at the machine's own
loopback page — where the link ceremony already is.

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
  your calls run as on each site, and, on Windows, that they run only while
  you are signed in there (J25). A site you may use but have not linked says how:
  *"On that machine, open this page and sign in"*.
- **Add a job site** works on a LAN-only install (J31). It says that on a
  machine that is already a node, the same command adds the site (J35).
- **The rules editor** arrives with the workspace server (2b.3). "Allow"
  runs without a prompt; "ask" prompts as every call does today.
- **Old selections** (`node:<folder id>`, `site:<node>:<server>`) show as
  removed, which Workbench already does for a withdrawn grant.

### 2.11 Migration (J34)

**No migration (Troy, J34): nobody has used the old site policy.** Node
folders shipped on edge on 2026-10-04, and no release carries them (v0.1.0
is 2026-10-02).
- **Old records** (`putNodeHelper`, `ownerAccess`, `helperGrants`, and
  nodes with the `files` grant) replay and grant nothing. Nothing converts
  and nothing is imported.
- **What we made is removed:** the `node-files` service, its account and
  its data.
- **Troy's Amish_Station:** Troy adds it as his site from Workbench by
  running the one-liner on the machine, then adds `C:\Users\troyc\…`
  workspaces. Nothing has to be granted.

### 2.12 What J21's standalone install will need

This design is built so that none of it has to be undone:
- **The site host and its workers are self-contained.** They join, pin
  the root, poll, keep the policy and audit log, and serve tools, with none
  of the agent's code or files (J23).
- **The starter is a role, not the agent.** On a node the agent plays it:
  it serves the link page, keeps the links, and starts workers. A
  standalone install serving several people needs a small privileged
  service of its own to play it. An agent-hosted site and a standalone one
  differ only in who plays that role.
- **The standalone installer** installs a Python and the site host program,
  then one of two shapes:
  - **without administrator rights:** a logon task (Windows), a
    `systemd --user` unit (Linux) or a LaunchAgent (macOS). It runs while
    the person is signed in, and serves only that person;
  - **with them:** the starter service, which serves everyone linked.
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
- the old records replaying as inert.

The file tools still run in the site host's isolated account. *Done when:*
- Amish_Station is a node and Troy's site at once, each revocable alone;
- a site behind WSL2's NAT joins over `public_sites`;
- a site on the root's LAN joins with no public route;
- a site's key is refused everywhere but its four routes;
- deleting a person removes their sites.

#### 3.1 The build of 2b.1 (started 2026-10-06)

**On a node only (J21).** Until the standalone install, a site's machine
must already have the agent installed. A machine that is not a node waits;
slice 1's files-only node over the public route ends here. `public_sites` is
still built and tested, with a node whose site polls through it.

**The contract (specs), first:**
- `control.yaml`:
  - New paths:
    - `POST /v1/sites/invitations` (`membership`);
    - `POST /v1/sites/enroll` (a join token);
    - `POST /v1/sites/poll`, `…/operations/{id}/claim`, `…/operations/{id}/result` and `POST /v1/sites/leave` (a site token);
    - `GET /v1/sites`, with a dev section only in dev mode, and `DELETE /v1/sites/{id}` (`membership`);
    - `PATCH /v1/sites/{id}/folders/{folder_id}`, Eugene's owner's own grant, dev mode only (`dev-access`, replacing `node-files`);
    - `PUT /v1/nodes/{name}/hosted-sites` (that node's own token, J32).
  - `/oidc/job-sites/{site}/…` takes site ids, and `…/enabled` goes. The
    invite answers `joinUrl`, the nodes origin or else the root's own
    address, so it works on a LAN-only install (J31).
  - `/oidc/sites/*` takes `site` in place of `node`, and `jobSite` goes:
    every machine with tools is a site.
  - Removed: `/v1/node-helpers*`; `files` from join-token grants;
    `EnrollmentRequest.owner`; `Node.owner` and `Node.lastContactAt`.
  - **Replay.** `putNodeHelper`, `helperGrants`, and `enrollNode` with
    `files` stay readable and apply as nothing. New log operations:
    `enrollSite`, `removeSite`, `setSiteHost`, `setSiteDevGrants`.
    `Snapshot` gains `sites`.
- `components/sites.yaml` gains what control and the site host now share
  directly: `SiteReport`, `SitePollAnswer`, `SiteOperation`, `SiteResult`,
  `SiteEnrollmentRequest` and `SiteEnrollment`.
- `site-host.yaml` loses the agent-facing relay API. It keeps `/healthz`
  and documents the launch environment and the `join` command.
- `agent.yaml`: the entry point's `public_nodes` becomes `public_sites`,
  with six paths (J31).
- `specs/platform` `tokens.py`: the `site` grant. A site key signs only
  `aud: control`. Control checks site keys against its registry, never the
  bundle.

**Then, repo by repo:**
- **control:**
  - the registry, its log operations and the routes;
  - the broker keyed by *(site id, `enrolledAt`)*;
  - `deletePerson` removes the person's sites;
  - closes control#6.
- **site-host:**
  - `join`: the key, the root pin (the agent's `root_tls.py` moves here),
    the owner's confirmation;
  - the poll, claim and answer loop, checking each operation's binding;
  - `node` mode removed.
- **agent:**
  - removed: `SiteHostRelay`, `validate()`, the job-site join flags,
    `root_tls.py` and the job-site refusals;
  - it supervises the site host when a site is configured;
  - `eugene-plexus-agent site join` (elevated) installs the site host and
    runs its `join`;
  - it reports the sites it hosts;
  - the entry point serves `public_sites`.
- **Workbench:**
  - site ids, in place of node names;
  - no file-support toggle;
  - the invite works on a LAN-only install.
- **ui:**
  - the Job sites branch and page;
  - People's section and `helperGrants` removed;
  - Machines: the files-role code removed, and the *Also a job site* line
    added;
  - the node invite form loses its job-site option;
  - `public_sites`.
- **Installers:** `-JobSite` on an existing node runs `site join`. On a
  machine with no node install it refuses, naming J21.
- **Acceptance:** `job-sites-acceptance.py` reworked to the done-when list
  above, and a sabotage pass.

**2b.2, each person as themselves** (J24, J25, J26, J27):
- workers, and the local channel that checks their account;
- the link page at the machine, served by the agent, and the links file;
- per person, the S4U task, the logon task, or the broker's unit with
  `User=`;
- the owner's worker serving people without a link, confined;
- per-user installs on Windows and Linux hosting a site for their person;
- the site host's account opening no one's files.

*Done when:*
- on Amish_Station, Troy's calls run as `troyc` and Jessie's as `jessie`,
  each having linked at the machine, with nothing granted by hand;
- someone without a link reads only the folder Troy gave them;
- a worker running as the wrong account is refused;
- the root and the site host each fail to make a link.

**2b.1 and 2b.2 ship together.** No release has the first without the
second, because 2b.1 alone keeps the permission step.

#### 3.2 The build of 2b.2 (started 2026-10-06)

**Calls taken starting it** (Troy, all as recommended except J25, §2.4.1):

| # | Call | Taken |
|---|---|---|
| J25 | Windows while signed out | **Revised: only while signed in**, with the person's session token |
| J27 | People with no account on the machine | The owner's worker, as the owner, confined, file tools only |
| J36 | How a person links on a Linux system install | **The elevated one-liner** (`sudo`), which takes the person's Eugene sign-in and writes the link as root. The agent there is unprivileged, and a link it made would let its account become anyone. A headless server has no browser at the machine anyway |
| J37 | How the link page signs a person in | **One built-in public OIDC client** at the root, `eugene-site-link`, accepted only with a loopback redirect (`http://127.0.0.1:<port>/link/callback`, RFC 8252), PKCE required. The one exception to D2 of `sign-in-with-eugene.md` |
| J38 | Per-user installs in 2b.2 | **Yes.** The agent runs the site host and the installing person's worker as its own children |

**What 2b.2 reads as in scope.** Folders stay the owner's to register and
share, as in 2b.1. Each person keeping their own workspaces and rules is
2b.3 (§2.6). What changes is *as whom* a call runs: a linked person's in
their own worker, so the OS decides what a shared folder lets them touch;
anyone else's in the owner's worker, confined to the folder, as every call
already is.

**Where things live:**

| | Windows service | Linux system | Per-user (Windows task, Linux `--user`, macOS) |
|---|---|---|---|
| Site host program | `<prefix>\apps\site-host\versions\<v>`, installed by the agent (LocalSystem). Users get RX on it and its interpreter, so a worker can run it; nobody but administrators writes it | **Root-owned** `/usr/local/lib/eugene-plexus/site-host/`, installed and updated by `install.sh` and the root update unit, never by the agent | The agent's prefix |
| Site host runs as | `NT SERVICE\EugenePlexusApp-site-host` (C1) | Its own unit `eugene-plexus-site-host.service`, `DynamicUser=yes` (no longer a C1 app) | The person |
| Links | `<prefix>\site\links.json`: SYSTEM and Administrators write; the site host's account reads | `/etc/eugene-plexus/site/links.json`, root 0644 | `<config>\site\links.json`, one link, the owner's, made by `site join` |
| Local-server list | `<prefix>\site\servers.yaml`; read granted to the site host's account and each linked account, by the agent | `/etc/eugene-plexus/site/servers.yaml`, root 0600, handed to the site host and each worker as a systemd credential | `<config>\site\servers.yaml` |
| Channel | `\\.\pipe\eugene-plexus-site-<suffix>` | `/run/eugene-plexus-site/channel` (the unit's `RuntimeDirectory`, 0755) | the same names, in the person's own space |
| Worker started by | The agent: `WTSQueryUserToken` for each linked person's session, `CreateProcessAsUser` into it (§2.4.1) | Root: `eugene-plexus-site-workers.path` watches the links and reconciles `eugene-plexus-site-worker@<uid>.service` | The agent, as its own child |

**The worker** is the site host's own package, run as
`python -I -m eugene_plexus_site_host.worker --account <SID or uid>
--channel <name> [--host <SID or uid>]`. Before it serves:
- its own account must be `--account`, and never LocalSystem, a service SID,
  root, or a uid below 1000;
- on Windows its token must not be elevated;
- the far end of the channel must be the site host's account (Windows: the
  pipe's owner; Linux: `SO_PEERCRED`, matching the owner of the root-made
  runtime directory).

It runs the `files` tools and the local servers in its own process, as its
person, with today's code. It reads the local-server list itself, so the
site host cannot name a program for it to run. It refuses folders inside
the install's protected roots.

**The channel** carries newline-delimited JSON, each frame at most 256 KiB.
- The worker says hello. The site host reads the peer's account from the
  connection, not from the hello: on Windows by `ImpersonateNamedPipeClient`
  at Identification level (the worker connects with
  `SECURITY_IDENTIFICATION`); on Linux by `SO_PEERCRED`.
- An account in no link is refused and disconnected. A second worker for one
  account replaces the first.
- Calls are `{"t": "call", "id", "kind", ...}`, where `kind` is `files`,
  `local`, `inspect` (a folder's identity, at registration) or `tools` (a
  local server's list). Answers are `{"t": "result", "id", ...}`. Several
  can be in flight.
- The Windows pipe is made with `FILE_FLAG_FIRST_PIPE_INSTANCE` and a DACL
  of SYSTEM, Administrators and the site host's account full, and
  Authenticated Users read, write and read-control. A site host that finds
  the name taken stops and says so.

**Routing, in the site host.** The policy decides as in 2b.1, then:
- a linked person's call goes to their account's worker;
- anyone else's (no link, or Eugene's owner in dev mode) goes to the
  **owner's** worker, confined as every call is;
- registering a folder and listing a local server's tools run in the owner's
  worker;
- with no worker connected the call is refused, naming why: on Windows
  *"Jessie is not signed in on Amish_Station. Calls run as her account only
  while she is"*; elsewhere *"Jessie's worker is not running"*.

The isolated-account check retires. The site host opens no one's files.

**The report** gains, in `SiteSummary.links`, each linked person, their
account's display name and whether their worker is connected, plus
`linkPage` (the agent's loopback link page, on a Windows service install).
Workbench shows each person their own line.

**The link page** (Windows service installs; J36 keeps Linux elevated) is
served by the agent:
- **`GET /link`** answers only a loopback TCP peer with no forwarding
  header. The agent finds the OS account that owns the connecting socket
  (`GetExtendedTcpTable` → pid → its token's user) and refuses system and
  service accounts. The page names the account.
- **Sign in** runs the code flow with PKCE against the root through the
  agent's own `/oidc` (J37). `state`, `nonce` and the verifier are bound to a
  cookie set by `/link`, and the account is read again on each request.
- **The callback** exchanges the code and checks the ID token: RS256 against
  the root's JWKS, issuer, audience `eugene-site-link`, nonce, expiry.
- **A confirm page** names both, *"Link Eugene person Jessie to Windows
  account AMISH_STATION\jessie?"*, and only its POST, carrying a CSRF token,
  writes the link.
- **Rules:** one link per person; an account belongs to one person; a person
  can remove their own link on the same page. Workbench's *remove* (the
  person or the owner) reaches the agent from the root
  (`DELETE /v1/site/links/{subject}`, the root's token), because removing a
  link can only take access away.

**The owner's link at the join.** `site join` links the owner to the
account that ran it: on Windows the elevated caller, or the console's user
if that caller is SYSTEM; on Linux `SUDO_UID`. `--site-account` overrides
both. The owner's Eugene password, typed at the join, is the person's proof
there.

**Linux `site link`** (J36): `install.sh --site-link --account <user>`
asks for the person's Eugene name and password. Root checks them with the
root using the site's own key (`POST /v1/sites/links/check`, a seventh
`public_sites` path, rate-limited), writes the link, and the path unit
starts the worker. `--site-unlink` removes it.

**The contract:**
- `control.yaml`:
  - the built-in client `eugene-site-link` (J37);
  - `POST /v1/sites/links/check` (a site token);
  - `POST /oidc/job-sites/{site}/links/{subject}/remove` (the person, or
    the site's owner).
- `agent.yaml`:
  - `/link`, `/link/start`, `/link/callback` and `/link/confirm`;
  - `DELETE /v1/site/links/{subject}`;
  - `public_sites` gains the seventh path.
- `sites.yaml`: `SiteSummary.links` and `linkPage`, and `SiteReport.account`
  as the site host's own account.
- `site-host.yaml`: the launch environment (links, servers, channel), the
  worker, and `check-person`.

**Order:** contract → site host (worker, channel, routing) → control →
agent (starter, link page, owner's link, per-user) → installers (Linux
root-owned site host, units, `--site-link`) → Workbench → acceptance on
Amish_Station (an elevated throwaway agent run as LocalSystem on +100
ports, and Jessie signed in through *Switch user*) and on Linux in CI →
sabotage.

#### 3.2.1 What building found (2026-10-06)

Built on branches `slice2b1-sites` beside 2b.1 (contract `f52f8d4`, pushed):
site-host `01e47a4`, agent `f30f6c7`, control `2f3240a`, Workbench `53f6e81`,
installers specs `8113d96`, Windows acceptance `scripts/job-sites-windows-
acceptance.py`. Suites: site-host 174, agent 1974, control 416, Workbench 170
+ 78 (web), all green on Windows; the agent's 20 targeted sabotages caught.

- **A worker that is replaced stops.** The first build had a replaced worker
  reconnect, so a worker an earlier agent left behind and its replacement
  would trade the connection back and forth. The site host now sends
  `{"t": "replaced"}` (and `refused` to an unlinked account) and the worker
  exits; its starter decides whether to start another. On Windows the
  starter also puts workers in a kill-on-close job, so an agent restart
  leaves none behind.
- **The pipe grants clients data access only.** Generic write on a named pipe
  includes `FILE_CREATE_PIPE_INSTANCE`, which would let any local account
  create a second server instance and sit between a worker and the site
  host. Clients get read data, write data, read attributes, read control
  and synchronize (`0x120083`), and the worker opens the pipe with exactly
  that. The pipe's owner is set to the site host's own account, which is
  what a worker checks.
- **Tests found three defects in the first site host build**: a duplicated
  link left one person still reachable by subject; a complete frame over
  256 KiB passed on Windows; the first call after the links file broke gave
  the wrong reason. All fixed with tests.
- **On a Linux system install the local-server list is root's too**, in
  `/etc/eugene-plexus/site/servers.yaml`. `site server add` under `sudo` ran
  the agent's code as root, which its account can rewrite; it now refuses
  there and names the file. A root-owned way to add servers on Linux is not
  built.
- **The Linux site host runs as a static system account**,
  `eugene-plexus-site`, not a C1 dynamic user: a worker checks the channel's
  far end by uid, which a dynamic user does not keep.
- **Control, as built:** `linked`, `account` and `linkPage` appear on a grant
  only for a site that reports `links` (an older site's grants are
  unchanged); a person's own link counts as "may use the site" for removal;
  Eugene's owner on the link page is refused after the passphrase checks, as
  the app-list refusal is ordered.
- **An acceptance-only override**, `EUGENE_PLEXUS_AGENT_ACCEPTANCE_MECHANISM`,
  tells a throwaway agent started as LocalSystem by a task that it is a
  service install. Nothing else sets it.
- **Not built:** Workbench cannot tell a per-user install from a Linux system
  install when `linkPage` is null, so both show the Linux link command; and a
  link's display name in the owner's view comes from the folder and server
  people lists (`SitePersonLink` carries no name).

**What the Windows acceptance found** (Amish_Station, `troyc` and `jessie`,
9 of 9 on the third run; record
[`job-sites-each-person-run.md`](../acceptance/job-sites-each-person-run.md)):
- `site join` took a venv's `python.exe` for an installed site host. uv makes
  the interpreter before it installs anything, so a first join raced the
  install. The join now waits for the version `apps.yaml` records (agent
  `36f5a66`).
- One job for every worker refused the second person's worker: a process
  already in a job joins another only while that one is empty, and an agent
  that is itself in a job hands its job to each child. Each worker now has a
  job of its own (agent `e924ff3`).
- What the design said held: `troyc`'s worker ran with a filtered token (the
  file it wrote is his, not Administrators'); a worker started into a
  disconnected session served; the pipe's account check refused Jessie once
  unlinked; `logoff` ended her worker with her session.

**J14, designed next** in a session of its own. J14a (signed policy edits)
is then built.

**2b.3, the workspace server** (J28): the new tools, the rules, and
Workbench's editor and prompts.

**2b.4, commands** (J29, J30): `run_command`, after J14b, with J9's consent
given at join or later (the Windows tray behind a UAC prompt, or the
one-liner again).

**Then slice 3**, cross-site copy on the held channel (J10), as
`remote-nodes.md` §5 had it.

#### 3.3 The build of 2b.3 (measured 2026-10-07)

Measured at the J14a.3 pins (site host `2d70ee9`, Workbench `1890294`, agent
`6497721`, control `9886286`). `S/` is the site host, `W/` Workbench, `AG/`
the agent, `CT/` control.

**The file tools today.**
- Three tools (`S/file_server.py:41-63`). A read refuses a file over
  32 KiB or 16,384 characters (`S/folder_io.py:210-212,280-283`). A write
  rewrites the file in place, then `fsync`s it, and says *uncertain* if it
  stops midway (`S/folder_io.py:350-377`).
- On Windows, each name is opened relative to a held parent handle, and
  reparse points are refused (`S/folder_windows.py:88-141`). A directory
  listing asks only for names (`S/folder_windows.py:199-234`). A walk must
  ask for each entry's attributes instead, so it can skip links without
  opening them.
- On Linux, each call runs in a fresh thread under Landlock
  (`S/folder_linux.py:265-278,322-350`). It does not cross into another
  mount (`S/folder_linux.py:385-387`).
- **Size.** An answer over 70,000 bytes is refused after the worker has
  produced it (`S/host.py:365-371`). The local channel carries 256 KiB a
  frame (`S/local_channel.py:38`). Workbench cuts a result at 65,536
  characters (`W/tools.py:515-516`). So the new tools must cut their own
  answers below these limits, and say that they did.
- **Time.** The site host waits 25 s for a worker (`S/host.py:99`). It then
  reports any `tools/call` as *uncertain: it may have acted*
  (`S/host.py:348-354`). For a search that ran too long, that is the wrong
  word: a read cannot have acted.

**Who may do what today.**
- **Owner only:** every management action (`S/host.py:531-536`), every
  approval (`S/host.py:1084-1085,1099-1100`), and a passkey code
  (`S/host.py:1247-1254`; the page says so at `AG/routes/site_link.py:772-776`).
  The root's `/oidc/job-sites/{site}/…` routes are the owner's too
  (`CT/routes/sites.py:975-1157`).
- **Already per person:**
  - Any linked person can make and pin a key at the machine
    (`AG/routes/site_link.py:638-659`), and the links file keeps each
    person's keys on their own link (`S/links.py:84-98`).
  - The sequence and the held changes are kept per person (`S/signing.py`,
    `S/host.py:964-1014`).
  - Passkeys are kept per person, bound to that person's link
    (`S/host.py:764-775`).
- The policy is one set of rules with one approval digest, the owner's
  (`S/policy.py:44,92-113`). No tool runs until that digest is approved
  (`S/host.py:800-816`).

**Workbench today.**
- Every call asks the person (`W/answers.py:381-412`).
- An answer stops at 16 calls or 8 rounds (`W/answers.py:353-363,422`). A
  model that searches and reads as Claude Code does reaches that limit in
  one task.
- A site's tools reach the model with their own schemas
  (`W/tools.py:357-377`), cut to the folders the chat chose through the
  `folder` argument (`W/tools.py:380-392`). New tools that keep a `folder`
  argument need no change in Workbench.
- Workbench's own folders, on its own machine, are a separate copy of the
  file tools, with the same three (`W/folders.py:31-71`).

**The contract.**
- `SiteCall` has no field saying whether the person approved the call
  (`site-host.yaml:338-357`).
- `SiteManageAction` is described as the owner's alone
  (`site-host.yaml:359-395`).

**Settled without a call** (each follows from a rule already taken):
- `edit_text` writes in place, as `write_text` and Claude Code do. Writing
  a new file and renaming it over the old one would change the file's
  identity, and drop its permissions on Windows.
- Links are never followed: a read refuses one, and a walk skips it. Other
  mounts are not entered.
- A read-only tool that runs out of time fails, saying so. It is never
  reported as uncertain.
- Limits:
  - files up to 16 MiB for reading and searching, and 1 MiB for editing;
  - every answer under 48 KiB of text, so it fits the 70,000 bytes once
    escaped as JSON;
  - a search stops after 10 s or 20,000 entries.

  Each limit is stated in the tool's description.

**The split, recommended:**

1. **2b.3a, the tools**, on today's `files` server under today's grants:
   - `read_text` gains `offset` and `limit` in lines, and always returns the
     whole file's hash;
   - `edit_text` replaces an exact passage, or every copy of it when asked,
     and needs that hash;
   - `glob` and `grep`.

   Built in the site host, with prose in the contract; Workbench is
   unchanged. It needs J73 and J74.

   *Done when:* on Amish_Station, Workbench's model finds, searches, reads a
   range of and edits files in a real repository. These are refused: links,
   another mount, `..`, a stale hash and an ambiguous passage. Every answer
   that stopped short says so.
2. **2b.3b, each person's keys, workspaces and rules, at the site** (J67-J70,
   J72, J76):
   - a policy per person, each approved with that person's own key;
   - the actions `workspace.add`, `workspace.remove` and `rules.set`, from
     any linked person, held for their own key;
   - passkeys for every linked person;
   - `SiteCall.asked`;
   - the root's routes open to a linked person, for their own items only;
   - in Workbench, just a person's workspaces and approving with their own
     passkey.

   *Done when* (Troy and Jessie on Amish_Station):
   - Jessie's new workspace waits until Jessie's own key approves it;
   - Troy's key cannot approve it, and Jessie's cannot approve Troy's
     changes;
   - a rule the root forges for Jessie is refused;
   - Troy sees none of Jessie's workspaces;
   - a path that is denied stays hidden from `glob` and `grep`.
3. **2b.3c, Workbench's rules editor and prompts** (J71): the editor;
   prompting only for "ask"; the limits per answer.

   *Done when*, in the browser:
   - "allow" runs without a prompt, "ask" prompts, and "deny" is never
     offered;
   - a 40-call search-and-read task finishes;
   - Stop ends it.

Each slice is landed and pinned before the next, with one acceptance run of
record (CLAUDE.md's testing policy).

**Calls (J67-J76), for Troy:**

| # | Call | Recommendation | Trade-off |
|---|---|---|---|
| J67 | Each linked person's own key (J44; widens J62) | **Every linked person may hold both kinds of key.** A key at the machine works today. A passkey pairs with a code shown on that person's own `/link` page. Each person's key approves only their own workspaces and rules. The owner's key still approves who may use the site. A person's passkey actions from Workbench (pair, list, approve, turn down, remove) reach only that person's own items | J59's gap (any program running as the person can use their key page) now covers every linked person, until J14b. The alternative, the owner approving everyone's rules, means the owner sees their workspaces, which §2.6 forbids. A person's rules would also be signed by someone else's key |
| J68 | A linked person with no key | **Their workspace changes wait for their key, and never apply on the root's word** (J48, per person). Until then they have only what the owner shared with them. The link page offers to make the key in the same visit as the link | A person must make a key before their first workspace. Linking already takes a visit to the machine, so offering the key then costs no second trip |
| J69 | Today's folders and the new workspaces | **One word, "workspace"; every workspace belongs to one linked person.** Today's folders become the owner's workspaces, with nothing to convert. Only the owner's workspaces may be shared, with today's people lists (J27) | A linked person who wants to share a folder asks the owner. The owner approves their rules once more after the update, because the shape of the approval digest changes |
| J70 | The rules | **Allow, ask or deny per workspace, for two groups of tools: read and search, and change files.** The rules are stored per tool, so commands fit later. Path patterns inside a workspace can only *deny*, and a denied path is hidden from every tool, including `list_directory`, `glob` and `grep`. Defaults as §2.6's table | You cannot say "ask before reading `.env`, allow the rest", only deny `.env`. Per-pattern "ask" would make a search stop for approval on each matching result |
| J71 | How many calls an answer may make | **Calls the rules allow do not count against the prompt limit.** An answer may make up to 200 calls in 50 rounds. Stop ends it at any time, and the gateway's repetition safeguard stays | A runaway model spends tokens on reads until the person stops it. Reads cannot change anything, and today's 16 calls is one task's worth of searching |
| J72 | Telling the site a call was approved, before J14b | **`SiteCall.asked`, which Workbench sets when the person approved the call.** The site refuses an "ask" tool without it. The audit log records which rule applied, and that the approval was claimed, not checked | A compromised root can set it (J29), which J14b closes. Without the field, the site cannot catch a Workbench bug that runs an "ask" call unasked |
| J73 | What search skips | **`.gitignore` is honoured and `.git` is always skipped, unless `includeIgnored` is set.** Binary files, files that are not UTF-8 and files over the limit are skipped, and the answer counts them | One small dependency (`pathspec`). Without it, `node_modules` fills every answer to its limit |
| J74 | A search pattern that never finishes | **Patterns use the `regex` package with a timeout per file, under the 10 s limit for the whole search.** A search that is stopped says so, and returns what it found | One dependency. Python's own `re` cannot be stopped, and the thread would hold one of the worker's eight call slots for good |
| J75 | Workbench's own folders, on its own machine | **Unchanged in 2b.3**: they keep three tools. Banked: replace them with a job site on Workbench's own machine, which gives people their own accounts, rules and keys there too | The model has fewer tools on Workbench's own machine than on a site, until the banked idea is taken up |
| J76 | What the root keeps of a person's workspaces | **The site reports a workspace's name and id, never its path.** A person's paths are read live from the site, through the root, when they open their own workspaces. The root shows each person only their own | One more site action (`workspace.list`), and that page waits on the site. A compromised root still sees what it carries. An honest root keeps no one's paths at rest. It applies to the owner's workspaces too, so Eugene's owner's dev-mode grants name a workspace by id, and the site stops checking the path the root sends with them (`S/host.py:503-510`) |

**Troy's answers (2026-10-07).**
- **J28: fold**, as *"a unified MCP server"*. Troy had understood today's
  `files` server not to be MCP. It has been one since J6g: `S/file_server.py`
  is served by the MCP SDK and speaks MCP 2026-07-28, and Workbench calls it
  as it calls any MCP server. So folding the new tools into it is the
  unified server: one MCP server per site carries every file tool now, and
  `run_command` in 2b.4. MCP servers an administrator adds at the machine
  stay servers of their own.
- **J67: as recommended**, both kinds of key for every linked person, each
  approving only that person's own items.
- **J68-J76: as recommended.**
- **The split: two slices, not three.**
  - **2b.3a, the tools**, as above.
  - **2b.3b, everything else:** each person's keys, workspaces and rules at
    the site; Workbench's rules editor; prompting only for "ask"; the limits
    per answer. Its *done when* is 2b.3b's and 2b.3c's above, together.

**What building 2b.3a found (2026-10-07).** Built in the site host only:
`workspace_tools.py` (ranged read, edit, the walk, `glob`, `grep`); each
platform's folder code lists a directory with each entry's kind, size and
write time, so a walk skips a link without opening it; `file_server.py`
offers the six tools and checks every argument itself; the host gives
readers `glob` and `grep` and writers `edit_text`. No new calls.
- **The MCP SDK does not check a tool's arguments against its schema.** A
  40,000-character `oldText` reached the worker's own check. So the
  worker's check (`file_server.check_arguments`) is the only one between a
  call and the folder code; Workbench's schema check is the caller's. Before
  2b.3a the worker checked only the argument names and `path`'s type.
  `write_text`'s 8,192-character `text` was enforced by Workbench alone. The
  site host's test for that limit passed for another reason: its call was
  create-only on a file that existed, and that was refused.
- **A full read could be refused for its size before 2b.3a.** An MCP answer
  carries the result twice, as text and as structured content, and escapes
  the text a second time. A 16,384-character file of quotes made a
  98,494-byte answer, which the site refuses at 70,000, though `read_text`
  promised 32 KiB. Every tool now cuts its answer to 60,000 bytes for both
  copies, says so, and says where to read on.
- **A search that runs out of time was reported as *it may have acted*.**
  The site host said that of every timed-out `tools/call`. A file server read
  or search now fails, saying so.

**2b.3a landed and pinned (2026-10-07):** site host `4f6c075`, agent
`9cef806`. Acceptance `--root-wsl` 28 passed, 4 one-account skips;
sabotage 36/36 once three missing tests were added (record:
[`workspace-tools-run.md`](../acceptance/workspace-tools-run.md)).

**2b.3b: the contract (2026-10-07), and calls J77-J80 for Troy.** Written
first, as J67-J76 say; nothing is built on it yet. It follows J77 as
revised, J78 and J79 as taken, and J80's recommendation, which is open.
- **The site** (`site-host.yaml`, `components/sites.yaml`):
  - actions `workspace.add`, `workspace.remove`, `rules.set`,
    `workspace.list` and `audit.read` from any linked person, for their own
    items; `workspace.people` (sharing) from the owner alone. The passkey
    actions and `/v1/passkeys/code` serve any linked person (J67);
  - `SiteRules` (`read`, `change`: `allow`, `ask` or `deny`),
    `SiteDenyPattern`, `SiteWorkspace` (reported: id, name, holder,
    rules, whom it is shared with; no path, J76) and `SiteWorkspaceDetail`
    (live, with the path);
  - `SiteCall.asked` and `SiteOperation.asked` (J72); the audit line's
    `rule` and `asked`;
  - per person: `SitePersonLink.signing` and `held`; `SiteSigning.held` is
    the owner's alone; `SiteSigning.people` says a site keeps each person's
    items;
  - `SiteToolGrant.decision` (J78); `SiteGrantHint` without path (J76).
- **The root** (`control.yaml`, `components/job-sites.yaml`): routes
  `/oidc/job-sites/{site}/workspaces` (add), `…/workspaces/list` (live),
  `…/{id}/remove`, `…/{id}/rules` and `…/{id}/people` (owner only);
  `JobSite.role` and `workspaces`; `SiteMcpCall.asked`;
  `SiteServerFolder.mine`. The held, passkey and audit routes open to a
  person the site's last report links, for their own items.
- **People** (`control.yaml`, J77 revised): `PersonPermission`
  (`add-job-sites`, `use-job-sites`), `Person.permissions` and
  `permissionsInEffect`.

*Settled without a call* (each follows from a call already taken):
- **Today's folders become the owner's workspaces with §2.6's defaults**
  (read `allow`, change `ask`, or `deny` when registered read-only). J11's
  rule that the owner puts themselves on a folder's list retires: a
  workspace's holder has rules of their own. The owner sees and approves this
  in the re-approval J69 already requires. A person on a folder's list keeps
  what they had: `writable` becomes change `allow` (§2.6: the standing
  pre-approval), otherwise change `deny`; read `allow`.
- **`folder.add`, `folder.remove` and `folder.people` stay**, acting on the
  owner's workspaces, so a newer site works under an older root.
- **Workspace names are unique per holder**, so nobody learns another
  person's names by being refused one. Where a person's own name and a
  shared one meet, their view reads `Name (2)`.
- **`writable` stays as a workspace's ceiling**: when false, every `change`
  rule there is `deny`.
- **Deny patterns** use `.gitignore`'s syntax without `!`, at most 64 of 256
  characters each. A tool that names a denied path is refused whether or not
  it exists, so the refusal says nothing about what is there.
- **Workbench learns which calls to ask about from the site's own tool list**
  (`_meta` `eugene-plexus/ask` per tool), not from the root: the site is
  final (rule 2), and the root keeps no rules logic.
- **A linked person's changes are always held**, even before they have a key
  (J68); held changes expire after 24 hours, as today.
- **The owner's held count is theirs alone**, so it says nothing about
  another person's changes; each person's own count is on their link.
- **A site without `SiteSigning.people` gets 503** from the new routes, as an
  older site does for passkeys.

| # | Call | Recommendation | Trade-off |
|---|---|---|---|
| J77 | Who may add a workspace | *Revised in discussion (below).* Was: any linked person, with no word from the site's owner | Was: one answer for every install; different installs want different answers |
| J78 | Local servers under allow/ask/deny | **Each tool granted is `allow` or `ask`; a tool not granted is denied.** Default: `allow` for a tool the site does not treat as destructive, `ask` for one it does. Today's `standing: true` reads as `allow`. A destructive tool may now be granted `ask`, where today it is refused without a standing pre-approval | A read-only tool of a local server now runs without a prompt (today Workbench prompts for every call). Its read-only mark is the server's own word; the server was added at the machine by an administrator. The alternative, `ask` for every local tool by default, keeps today's prompts |
| J79 | Whose approval a call needs (J48, per person) | **A call runs under the approval of the rules it uses.** A person's own workspace needs their own approved rules; a workspace the owner shared, a local server or dev mode needs the owner's. With the owner unsigned or unconfirmed, Jessie's own workspaces still run | J48 said no tool runs on the site until the owner's key approved its rules. That still holds for everything the owner's rules govern, and Jessie is not stopped by the owner's re-approval after the update (J69). The alternative, the owner's state stopping everyone, is simpler to say and makes everyone wait on the owner |
| J80 | Who reads the audit log | **Each line belongs to one person, who alone reads it through the root**: a call or change in a workspace to its holder; one about a person's keys to them; the local servers, sharing and settings to the owner. Today only the owner reads it, and every line | Without it the owner reads Jessie's file names and searches (§2.6: the owner does not see another person's workspaces). An administrator at the machine can still read the whole file on disk |

**Who is who** (asked by Troy before answering): *Eugene's owner* holds the
install's passphrase, is not on the People list and owns no site. *The
site's owner* is the person from the People list who ran the join at that
machine and confirmed with their own password; the site records them once.
*A linked person* is a person from the People list who also linked an OS
account on that machine, at the machine (the owner is linked at the join).

**Troy's answers (2026-10-07).**
- **J77, revised: permissions per Eugene person.** Troy: different
  environments need different answers, so define permissions per Eugene
  user. Taken as proposed: `Person.permissions` at the root, set where People
  are managed, null meaning the install's defaults (the root's settings
  `peopleMayAddJobSites` and `peopleMayUseJobSites`, both on, so a household
  needs no setup and an organisation turns them off and grants person by
  person). `add-job-sites` gates `/oidc/job-sites/invite` (J9);
  `use-job-sites` gates linking at a machine (the link page's sign-in and the
  Linux link check) and keeping workspaces of one's own. They only narrow:
  the site's floor (an OS account, a link at the machine, the person's own
  key) stays, so a root that sets one wrongly gives no one more than the
  machine allows, and they need no signature at the site. The site's owner
  gets no per-site say on top for now (the OS account is the per-machine
  gate). A folder the owner shares is the owner's grant, not governed by
  `use-job-sites`. Taking it away leaves a link inert, not removed.
  Contract: `PersonPermission`, `Person.permissions` and
  `permissionsInEffect` (settings never lie), on create, update and the
  snapshot.
- **J78: as recommended.**
- **J79: as recommended.**
- **J80: as recommended (2026-10-07, at the start of the build).** Each
  line belongs to one person, who alone reads it through the root. A later
  per-person permission may let an auditor read everyone's lines (banked,
  not built).

**What building 2b.3b found (2026-10-07).** Built on contract `652ddc5`
(J80 recorded, and who names a person's view: both ends, the same way). No
new calls.
- **Names in a person's view are computed at both ends.** The report is per
  site, not per person, so it carries each holder's own name, and the site
  and the root each name a person's view the same way: their own, then what
  the owner shared, `Name (2)` on a repeat. The root copies the site's
  `unique_names`; a sabotage that breaks it at the root is caught.
- **An unlinked holder's workspaces are never served.** Only the holder's
  own worker opens them; with no link they are refused saying *link*, not
  passed to the owner's worker. (A key's state would refuse them too, since
  keys live on the link; the sabotage pass found that second mechanism and
  the refusal now names the first.)
- **`pathspec` hides a hidden folder's contents by itself.** The loop over
  the folders a path is in escaped every sabotage and was deleted. On
  Windows, matching is caseless, and an 8.3 short name (`SECRE~1`) is
  refused wherever a workspace hides paths, since Windows opens it as the
  long name.
- **Log compatibility.** A person left on the install's defaults carries no
  `permissions` key, so a standby older than J77 applies their entry as
  before; only a person given their own list carries one.
- **`asked` only to a site that gave rules.** Workbench sends it for an
  approved call whose site listed `_meta` `eugene-plexus/ask`; a site that
  lists nothing (older than 2b.3b) is asked about every call as before and
  never told, since an older root refuses the field.
- **Audit lines carry a `reader`**, stripped before any line leaves the
  site; lines written before 2b.3b have none and are the owner's.
- **An older root's `folder.people` naming the owner** (J11) is read
  without the owner: a workspace's holder has rules of their own.
- **Workbench's limits (J71):** 200 calls in 50 rounds; calls that ask stay
  capped at 16. A 40-call answer of allowed reads finishes with no prompt
  (unit test with the fake site and model).

Unit tests: site host 296 (16 new), control 435 (13 new), ui 1727, agent
2029, Workbench 71 Python + 97 web in the changed areas. Sabotage, changed
code only (`scripts/b23b-sabotage.py`): site host 34/34 once five escapes
were answered (four missing tests, one spare deleted), control 14/14.

**Landed on `main`, not pinned (2026-10-07):** site host `6773d81`, agent
`5478366` (pins that site host), control `be2dec1`, ui `db4bf501` (source;
`dist` not rebuilt), Workbench `f206b8f` (source). The existing
`--root-wsl` acceptance, run against them, found one regression: an owner
with no key and no workspace was told *no workspace*, hiding J48's reason.
Fixed in `6773d81`: with nothing offered, a linked person's own key state
comes first. It then stops at assertions written for the old wording. The installers still pin the 2b.3a
set until the acceptance of record: `docs/private/handoff-2b3b.md`.

**What the acceptance found (2026-10-07).** Record:
[`workspaces-people-run.md`](../acceptance/workspaces-people-run.md).
`--root-wsl` 35 passed with 4 one-account skips; the new scripted browser
check (`scripts/b3b-browser-check.py`: Chrome in Workbench's page, the real
gateway with a scripted model, the real site host) 11 of 11, and its
sabotage pass 5 of 5. Six defects, each with a test that fails without its
fix; no new calls.
- **The site host's channel dropped `asked`**, so every approved "ask" call
  was refused at the site (J72); **a nothing-offered refusal named the first
  blocked workspace**, not the one asked about (J79); **`check-person` hid
  the root's reason** (J77). Fixed in site host `26a4f0f`.
- **Workbench's rules editor showed a held change as in effect**, and the
  owner's sharing list did the same: after Save, a change that gives more
  (J68) stayed on screen until a reload. Both now show the person's edits
  only until Save, then what the machine reads back. **Two sentences said
  every file operation waits for approval**; on a job site the rules decide
  (J70), and Workbench's own folders still ask (J75). Fixed in Workbench
  `9e61bef`, dist `ce2103f`.
- **Where "deny" is decided:** the person's offer is built without a denied
  workspace's change tools; the listing's own filter after it is a second
  guard (a sabotage of the filter alone escapes, since it has nothing to
  drop).

**Landed and pinned (2026-10-07):** agent `aa2fe11` (site host `26a4f0f`,
Workbench dist `ce2103f`), control `be2dec1`, ui dist `c595c2a`, in both
installers. **Not yet:** the Windows two-person run (J1-J6, jessie's key in
her own Chrome and her files as her Windows account), and the deploy (the
NAS root first).

---

## 4. Calls

| # | Call | Recommendation |
|---|---|---|
| J23 | Which process holds the site's enrollment | **The site host, end to end**: its key, the pin, its own poll. The agent's relay retires |
| J24 | Which OS accounts the site runs in | *Revised after J26/J27:* **the site host in an unprivileged account of its own; each person's tools in a worker as their own account.** The permission step retires |
| J25 | Windows, while the person is signed out | **Taken (Troy), then revised after measurement (§2.4.1): only while the person is signed in**, with their own session token. Never a stored password |
| J26 | Several people on one machine | **Taken (Troy): one install serving everyone**, each as their own account |
| J27 | Whose permissions a person's calls carry | **Taken (Troy): their own local account's**, linked to their Eugene sign-in at the machine. **Also taken:** people with no account there get only folders the owner shares, as the owner, confined |
| J28 | The workspace server and `files` | **Taken (Troy, 2026-10-07): fold them**, *"a unified MCP server"*: one MCP server per site, id `files` kept, allow/ask/deny rules, "ask" answered in Workbench (§3.3) |
| J29 | What waits for person-held keys (J14) | **Widening edits before any release with sites running as their people; commands before commands ship.** J14 designed next |
| J30 | J9's proof of administrator rights, without a terminal | **Taken (Troy): at join, and later too.** Later: the Windows tray behind a UAC prompt, or the one-liner again; the CLI for experts |
| J31 | How a site reaches the root | **Like a node:** the LAN address, or the nodes name. **`public_sites` only for machines outside**, on six paths. Site keys stay out of the node bundle |
| J32 | Linking a node and the site it hosts | **Attested by the hosting node, for display only** |
| J33 | Dev mode in a console that is membership only | **A dev-mode section on the site's page**, absent in production |
| J34 | Migration | **Taken (Troy): none.** Nobody has used the old site policy |
| J35 | Making a node into a site | **The same installer one-liner, run at the machine**, adding the site without reinstalling the node |
| J36 | Linking on a Linux system install | **Taken (Troy): the elevated one-liner**, which writes the link as root (§3.2) |
| J37 | How the link page signs a person in | **Taken (Troy): one built-in public loopback OIDC client**, `eugene-site-link` (§3.2) |
| J38 | Per-user installs in 2b.2 | **Taken (Troy): yes**, the agent runs the site host and the person's worker as its children (§3.2) |

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

### J24. Which OS accounts the site runs in

**Revised after Troy's J26 and J27.** The first recommendation ran the whole
host as its owner. One install serving several people, each as their own
account, cannot be one process, so:

**Recommendation: two parts (§2.4).**
- The site host runs in an unprivileged account of its own. It holds the
  enrollment, the policy and the audit log, and it opens no one's files.
- Each linked person's tools run in a worker under that person's account,
  started by the machine's privileged starter (the agent, on a node). The
  worker reaches the site host over a local channel that proves its
  account.

**Trade-off:** more moving parts: a worker per person, the local channel,
and a starter that keeps the links. The site host's account can act as any
linked person within the rules, so it must run nothing but its own code.
Per-user installs and macOS still work, but serve only the installing
person, because only a privileged starter can run a process as someone
else.

### J25. Windows, while the person is signed out

**Revised (Troy, 2026-10-06), after the measurement of §2.4.1: only while
the person is signed in, with their own session token.** The text below is
the recommendation as first taken. The measurement found Windows refuses an
S4U task registered for anyone but the registering account, so the agent
would have had to make the S4U logon itself; Troy chose the simpler shape.

**First taken, as recommended: a Task Scheduler task with S4U
logon, where Windows allows it for that account.** It runs at boot, signed in or out, with this
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

### J26. Several people on one machine

**Taken (Troy, 2026-10-06): one install serving everyone,** *"based on
permissions of who is using it"*. One enrollment and one owner per machine;
the owner decides who may use it; each of those people is served as their
own account (§2.2, §2.4).

### J27. Whose permissions a person's calls carry

**Taken (Troy, 2026-10-06): their own.** A person's Eugene sign-in, and
later their Google or Microsoft sign-in, is *"attached to the local
permissions for that person"*. A link is made at the machine: the person
signs in to Eugene in a browser there, and the starter reads their OS
account from the connection (§2.2).

**Also taken (Troy, 2026-10-06), as recommended: people with no account on
the machine.** They can be given a folder by the owner, and their calls run in
the owner's worker as the owner, confined to that folder, with file tools
only and never commands. That is the only way to share a folder with someone
at another office.

**Trade-off:** on Windows that confinement is this product's code, not an OS
boundary, so a bug in it would expose the owner's account to that person.
OS-enforced confinement is a later hardening: an AppContainer whose SID the
owner's worker adds to the shared folder's permissions, with no
administrator needed. The alternative, giving people without an account
nothing, is simpler and stricter, but leaves Workbench no way to share a
folder across offices.

### J28. The workspace server and `files`

**Awaiting Troy, after one clarification.** The workspace server is not the
job site. The job site is the machine and its enrollment; the workspace
server is the set of file tools on it that Workbench's model calls; a
workspace is one folder those tools work in.

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
- **No release ships a site running tools as its people before J14a.**
  People sign their policy edits, and the site checks them.
- **Commands do not ship before J14b.** Persons sign their approvals.

Edge can carry 2b.1-2b.3 before J14a, with the limit stated, because Troy is
edge's only user.

**Trade-off:** the Claude-Code-like Workbench waits behind a design that
does not exist yet. The alternative, shipping everything root-trusted, means
a compromised root reaches every linked person's whole account: their files
first, and with commands everything. Today it reaches only what someone
granted by hand.

### J30. J9's proof of administrator rights, without a terminal

**Taken (Troy, 2026-10-06): consent at join, and later too**, *"in case
they didn't understand at join time"*.
- **At join**, the installer one-liner asks one question: *"Allow tools that
  change this machine's settings or run programs?"* It is already elevated,
  so its answer is the J9 proof.
- **Later, on Windows**, from the tray, which runs in the person's session.
  It raises a UAC prompt, and the elevated step records the consent.
- **Later, on Linux and macOS**, by running the one-liner again, the stated
  exception. Those sites are mostly headless and have no tray.
- **Taking consent back** needs no proof, and is a switch in Workbench.

The elevated `site` CLI stays as the expert path, and for adding local
servers. The later path ships with commands (2b.4), the first tool that
needs it.

**Trade-off:** the tray action is Windows-only. A Linux desktop would need
a polkit prompt, which nothing here has yet.

### J31. How a site reaches the root

**Recommendation:** a site joins and polls through the address node joins
already use: the root's LAN address, or the nodes name when the entry point
has one. The public mode, renamed `public_sites`, is only for machines
outside. It opens six paths:
- `POST /v1/sites/enroll`;
- the four site routes of §2.3;
- `GET /v1/trust/tls`.

The trust bundle leaves the public list, and leaving joins it. Site keys
are verified by the root only.

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

**Taken (Troy, 2026-10-06): no migration**, because nobody has used the old
site policy. Old records replay and grant nothing, and what we made (the
`node-files` service, account and data) is removed (§2.11).

### J35. Making a node into a site

**Recommendation:** Workbench's *Add a job site* gives the same installer
one-liner for every machine. On a node it detects the existing install. It
installs the site host at the version that node's agent pins, and adds the
site without upgrading or re-enrolling the node.

**Trade-off:** a terminal command remains, the installer's one-liner, which
is the stated exception. The alternative is the link page of §2.2, served by
the node's agent at the machine, which 2b.2 builds anyway. Joining from it
too would take a node from nothing to a site with no terminal at all, for
little more work. It does nothing for a machine that is not a node (J21), so
the one-liner stays either way. The page could take over joins on nodes
after 2b.2.

### 4.1 Troy's answers (2026-10-06)

| # | Answer | What it changed |
|---|---|---|
| J26 | *"One install serving multiple people based on permissions of who is using it."* | One site per machine. J24 is revised to the site host plus a worker per person (§2.4) |
| J27 | *"Eventually I wanted SSO through Google and other services, and I was hoping that login was attached to the local permissions for that person."* | Links between a sign-in and a local account, made at the machine through a browser sign-in, so they work with single sign-on (§2.2). People without an account there stay a recommendation (J27) |
| J28 | *"I'm taking 'workspace server' to mean jobsite? If so then this is perfect."* Then (2026-10-07): *"It's supposed to be a unified MCP server."* | It is not the job site; it is the job site's file tools, already an MCP server since J6g. Taken: fold (§3.3) |
| J30 | *"Let's make sure they can consent later, in case they didn't understand at join time."* | A later path: the Windows tray behind UAC, or the one-liner again (J30) |
| J34 | *"No migration needed because no one has used the old site policy yet."* | No import and no add-again listing (§2.11) |

**Then Troy said to begin the next slice.** That takes the calls 2b.1 rests
on as recommended: **J23, J31, J32, J33 and J35**.

**Starting 2b.2 (2026-10-06), Troy took J25 and J27's open question as
recommended:** an S4U task where Windows allows it, else only while signed
in, never a stored password; and a person with no account on the machine
can be given a folder, served by the owner's worker as the owner, confined
to it, with file tools only. **The S4U measurement then found the task
impossible (§2.4.1), and Troy revised J25: on Windows, a person's worker
runs only while they are signed in, with their own session token.** So a
person without an account on a Windows machine is served only while its
owner is signed in there. Still open:
- J28, which 2b.3 needs;
- J29, which gates a release.

The build order changed in one place: **2b.2 grew** (§3). It now builds the
workers, the local channel, the link page and the links file, instead of
running one host as its owner. 2b.1 shrank by the migration. J30's later
path lands with 2b.4.

---

## 5. What this design does not cover

- **J14 itself.** §2.8 sketches it; it gets its own session (J29).
- **The standalone site install** (J21). §2.12 lists what it will need.
- **Cross-site copy and the held channel** (slice 3), and approving a call
  at the machine.
- **OS-enforced confinement on Windows** for people without an account on
  the machine (J27's later hardening).
- **Single sign-on itself** (control#4). This design only makes links and,
  later, joins work with it.
- **A folder boundary on macOS**, so a macOS site can share with others.
- **TLS between machines on a LAN**, as before (`remote-nodes.md` §7).
- **Managed-fleet enrollment** (J16), and transferring a site to another
  owner.
