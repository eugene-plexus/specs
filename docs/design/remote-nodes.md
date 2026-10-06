# Job Sites: Workbench working on your machines, wherever they are

**Status:** a design, 2026-10-05. **Every call (J1-J18) was decided by Troy
the same day** (§6), three more as slice 1 started (§6.1), six as slice 2
started (§6.2) and three during it (§6.3). Slice 2 is in progress (§5.2). **Slice 1 is built (2026-10-05)**: what it found is §5.1, and
the run is [`docs/acceptance/job-sites-run.md`](../acceptance/job-sites-run.md).

The file keeps the name `remote-nodes.md` because it began as that
question. The analysis of inference across networks it started with is now
Appendix B, and is out of scope.

## What a Job Site is

A Job Site is a machine a person owns, joined to the Plexus so that central
Workbench can work on its files, and later its other tools.

- It can be anywhere.
- It accepts no incoming connections.
- No cloud service sits in between.
- One person can own several, and run operations across them from one chat:
  for example, copying a folder from the desktop to the NAS.

**The recommendation.** The file helper Workbench already uses is pull-only:
every one of its connections is opened by the machine (§2). So a Job Site
outside the LAN needs no VPN and no tunnel. It needs four things:

1. **A route to the root that carries node traffic and nothing else,** on the
   port the owner already forwards, with no third party in the path (§3.1).
2. **A file-only kind of node**, one that holds no address and runs no
   inference (§3.2).
3. **Access that belongs to each site's owner**, never to Eugene's owner
   (§3.3).
4. **MCP between site and root**, before the tool set grows (§3.4).

Two things come after that: copying between sites (§3.5) and enrolling
machines in bulk (§3.6). §5 proposes the first slice, and §6 holds the calls.

---

## 1. What Troy decided on 2026-10-05

- **Files, not inference.** *"I'm not specifically interested in out of LAN
  inference."* The question is Workbench, on the server, using the file
  helper on a machine that is not on the server's network.
- **Away from the machine, many machines at once** (J2, answered).

  > I want one user to be able to access multiple machines under their
  > control.

  Claude Code and Codex work on the one machine they run on. This is the case
  only a central interface can serve (§4).
- **No cloud in the path.**

  > Many people who are interested in local LLM hate Cloud services.

  So there is no Cloudflare proxy in the path, and no Tailscale either,
  because its coordination is a cloud service. **That withdrew this doc's
  first recommendation, a guided Tailscale path.** That analysis is in
  Appendix B.
- **Operations across machines.**

  > Multiple machine control from a central chat window enables file copy and
  > other functions that usually require cloud based services, but a local
  > user might want to handle independently.

- **The name is Job Site** (J1). In Workbench it reads *Job sites (your
  machines)*, and *Add a job site* means joining one. The console keeps
  *Files on your machines*, under Troy's rule that keeps workshop names in
  Workbench.
- **Membership is not access.**

  > Maybe the owner can help a Jobsite join or leave the Plexus, but rights
  > to the Jobsite tools must be explicitly given to a user before they can
  > be used.

- **No role sees everything.**

  > I wouldn't count on the owner getting to see everything in the future.

  MSPs will want their own tools to join and remove customer machines, and a
  paid inference service will want automated user tools. Neither is to be
  built now, and the weekend novice keeps a simple path.
- **Plan for many tools.**

  > We only have 4 file tools today. That could be 100 next year. Even
  > Windows is planning to grant MCP access to system settings and tools.

  Windows 11 has shipped this in preview since Insider build 26220.7344
  (2025-12-05):
  - native MCP;
  - an on-device registry for MCP servers;
  - File Explorer and Windows Settings connectors, each *"contained in a
    secure environment with their own identity and audit trail"*.

---

## 2. What exists today

### 2.1 The file helper: four tools, not MCP

It is a bounded, custom protocol of four tools, each sent as a
`{tool, arguments}` command:

| Tool | Limit |
|---|---|
| `inspect` | — |
| `list_directory` | — |
| `read_text` | up to 32 KiB |
| `write_text` | up to 8,192 characters, hash-checked |

The path one operation takes:

1. **Workbench** offers them to the model as function tools, and the person
   approves each call. Workbench posts the call to control's
   `/oidc/node-helpers/execute` with its own client credential and the
   person's (`W/node_folders.py`; `C/routes/node_helpers.py:237-309`).
2. **Control** checks the grant and queues the job. It hands the job to the
   machine's next poll, and checks the grant again before releasing the
   result (`C/node_helpers.py:118-186`).
3. **The machine's agent** claims the job and passes it to the helper over
   loopback, with a separate random credential. The helper is a stdlib HTTP
   worker running in a restricted OS account (`A/node_file_helper.py:234-299`;
   `A/_node_file_helper/__main__.py`).

**The helper only runs where Eugene is installed as a system service** on
Windows or Linux. It is unavailable on macOS, in Docker, and on per-user
installs (`node-file-helpers.md`, *Platform and deployment limits*). A Job
Site inherits that limit.

**It must not become an MCP server on the machine.** An MCP client dials its
server, and that brings back exactly the NAT problem this design avoids
(Appendix A). MCP belongs *between* the site and the root, carried over the
connection the site opens (§3.4).

### 2.2 Nothing on its path dials the machine

| Step | How it reaches the machine | Anchor |
|---|---|---|
| Turn file support on | A replicated setting, delivered in the answer to the machine's own poll. The agent then installs and starts the helper | `C/routes/node_helpers.py:105-111`; `A/node_file_helper.py:144-200,285-286` |
| Register a folder | An `inspect` job, claimed through the same poll | `C/routes/node_helpers.py:114-180` |
| A read or write from Workbench | A job, as above | `C/node_helpers.py:118-186` |
| Its trust bundle | The machine pulls it every 60 s | `A/app.py:541-577` |
| "Available" | The machine polled within the last 25 s. **The probe is not consulted** | `C/node_helpers.py:26,103-116` |

**A node with no recorded address is already skipped** by:
- the probe, which reports *no url recorded* (`C/nodes_client.py:145-146`);
- the trust push (`C/trust.py:212`);
- the gateway's node map (`G/routing.py:1074-1080`);
- control's install-wide views.

**What is missing:**

- **The machine cannot reach control from outside.**
  - Control's port is LAN-only.
  - The entry point's nodes name must name its source networks
    (`A/entrypoint.py:205-206`).
  - That name routes control's whole API, sign-in and admin included
    (`:546-547`).
- **The machine would announce its own LAN address.** It derives that address
  from its socket (Appendix A, row N1). The root then dials it and reports
  *down*.
- **The helper's client hard-codes `trust_env=False`**
  (`A/node_file_helper.py:272-274`). That overrides `client_for`'s per-address
  rule, so a network that forces a proxy blocks it.

### 2.3 What Eugene's owner can do today (control `b667699`)

- **Nobody has access by default.** A folder's `ownerAccess` starts at `none`
  (`C/routes/node_helpers.py:45-48`).
- **The owner is the one who grants.** The owner gives themselves access in
  one click (`PATCH …/folders/{id}`, `:51-69`; `C/node_helpers.py:61-70`).
  The owner also writes every person's grants (`PATCH /v1/people/{id}`
  `helperGrants`, owner-only, `C/routes/people.py:56,159-185`).
- **The owner can become anyone.** The owner sets any person's password
  (`PUT /v1/people/{id}/password`, `:196-206`), then signs in as them.
- **The owner may read chats.** When Workbench's `ownerReadsChats` (W4) is on,
  the owner can read people's chats, and those chats hold every file result
  a person approved (`W/api.py:203-215,464-470`).

---

## 3. The design

### 3.1 A node-only route to the root, with no third party

**A `public_nodes` mode for the entry point's nodes name.** It needs a risk
acknowledgement, as `public_console` does. From any network the name answers
exactly these:

- `POST /v1/nodes/enroll`;
- `GET /v1/trust/bundle`, which **requires a node token** on this route,
  because today it publicly lists every machine's name, public key, grants and
  revoked session ids;
- `POST /v1/node-helpers/poll`;
- `POST /v1/node-helpers/operations/{id}/claim`;
- `POST /v1/node-helpers/operations/{id}/result`.

Everything else gets one sentence: *this name serves machines only; the
console is at …*.

**No third party.**
- The owner's router forwards one port to the root's entry point, which is
  what Troy already does for NPM.
- The name is DNS-only, or it is a bare address.
- **The join command carries the root's certificate fingerprint,** so the
  site pins the root at join. It then needs no public CA and no DNS name: the
  entry point's own CA is enough.
- The root's CA then needs a rotation path before this ships (J7).
- **Only a root on CGNAT needs anything outside the home**: a relay its owner
  runs (a VPS), or IPv6.

**The helper honours proxy settings** for a root URL that is not on the local
network. That means dropping the explicit `trust_env=False`.

**Joining from outside** uses the existing installer and one more flag,
roughly:

```
install.ps1 -Join https://nodes.example.com -Token … -NodeName … -FilesOnly
```

### 3.2 File-only Job Sites

Row 3's join tokens already carry `grants`. Add a `files` role, with these
rules:

- **A join through the public route can only take this role.** That rule is
  what stops a rogue machine announcing an address and being sent prompts.
- **It has no address.** The root refuses one if offered, and the agent
  neither derives nor announces one.
- **It is sent no inference work.** This is what the call table's *no run
  jobs* meant, and it means exactly this: Eugene's own model machinery never
  reaches the site.
  - no gateway grant, so nothing is routed to it;
  - no runtimes may be declared on it;
  - no engine installs or model starts;
  - the library run-operations poll (Appendix A, N7) is off.

  These are commands from the Plexus side (Eugene's owner and the gateway),
  carried out by the agent's privileged supervisor, and the site's owner
  never chose them.
- **Running scripts and OS actions is not inference work. It is a tool,**
  arriving in a later slice as an MCP server on the site (§3.4).
  - It is off by default, and only the site's owner enables it.
  - It runs in the unprivileged site-side host, never through the agent's
    supervisor.
  - Each call is approved under the site's own policy (J8).
  - A tool that can alter the machine's OS needs proof of admin or root at
    the machine before it turns on (J9).
- **Its status reads *last contact N s ago***, taken from its authenticated
  poll, not *down: no url recorded*.
- **A console hop to it** says *this machine only connects out; its files are
  under People*.

Most of this exists already: an address-less node is skipped everywhere (§2.2).

**Contract changes:**
- `control.yaml`: the `files` role, `Node.lastContactAt`, and an
  address-less enrolment;
- the entry point's settings gain `public_nodes`;
- no change to Workbench, or to the helper protocol, in this step.

### 3.3 Membership is not access

**Two roles, held by different parties:**
- **Eugene's owner** manages membership: invites a site, removes it, and sees
  that it exists and whether it is online. The owner does not see the site's
  folders, their contents, or who holds grants.
- **A site's owner** is the only one who grants its tools, including to
  themselves.

Four rules make that hold. Rule 3 is deferred (J12), and rule 4 depends on
the install's mode (J13):

1. **The invitation names a person, and that person confirms at the
   machine.** The join asks them to sign in there with their own password.
   The site records its owner from that, so ownership comes from presence plus
   the person's own credential, never from anything Eugene's owner holds.
2. **The site keeps its own list and refuses anyone not on it** (J8). Editing
   the root's state is then not enough to get in.
3. **Eugene's owner cannot become a person.** The owner may disable or remove
   an account, but not set its password.
   - **Deferred by Troy (J12):** the owner keeps setting passwords for now.
     Doing this properly, including recovery, is a slice of its own.
   - **Until then, the rule does not hold against the owner.** An owner who
     sets a person's password can sign in as them and use their grants. The
     person would notice their password had changed.
4. **What the owner sees of others' tool activity depends on the install's
   mode** (Troy, J13).
   - **Dev mode:** the owner can still see all tool information, job-site
     results included, and every user is told so.
   - **Production mode:** `ownerReadsChats` never shows a job-site result.
     The owner sees that a tool ran, and on which site, but not what it
     returned.

   Dev mode is for developing Eugene. Production mode is where owners are
   restricted. Three rules make the switch honest (J18, decided):
   - **It is not retroactive.** Results produced in production stay hidden
     if the install later switches to dev.
   - **Every user sees the current mode**, and is told when it changes.
   - **A new install starts in production.**

**Leaving needs no one's permission.** Eugene's owner can remove a site,
which revokes it at once. The site's owner can leave from the machine
(`POST /v1/node/unenroll`, which exists).

**No role sees everything.** Capabilities are separate and assignable:
- membership;
- people's accounts;
- a site's grants, which belong to its owner;
- reading others' chats, a per-business setting;
- later, billing and quotas.

**The novice default gives one person every administrative capability, and
never data access.** Job Site surfaces check a named capability, not *is the
operator* (J15). Today the code checks the operator: `require_operator`, and
`subject == "operator"` at `C/node_helpers.py:62`.

**The human is two identities.** Administration is the passphrase session.
Using a site needs a person account, so a solo owner makes one for themselves.
That is a little friction for a novice. It is also what makes the MSP case
honest: the MSP runs the Plexus, each employee owns their PC's site, and the
MSP cannot read it.

**The limit, stated plainly.** These rules stop Eugene's owner *through the
product*. A compromised root, or an owner willing to edit the root's state
and keys directly, can still mint a sign-in for "Alice" that her site accepts,
because the site trusts the root to say who Alice is. Closing that needs a key
the person holds and the root cannot mint: a passkey registered at the site,
with tool calls signed by it (J14). That is a design of its own.

### 3.4 MCP between site and root

**Before a fifth tool:**

- Today the four tools are named in four places: Workbench's tool
  definitions, control's broker, the agent's validation, and the helper.
  Every new tool means a release of three repos.
- MCP already provides what a growing tool set needs: discovery
  (`tools/list`, `list_changed`), schemas, annotations, progress and
  cancellation.

So the channel between site and root carries MCP messages (J6), and the four
file tools become Eugene's own MCP server on the site. Other servers sit
beside it: ones the owner adds, and Windows' own connectors through its
on-device registry. A new tool is then a new server on the site, with no
Eugene release.

**The site-side piece is a local MCP host with its own policy, and that policy
is final** (J8):
- default deny, per server and per tool;
- tools marked destructive or system-level need approval on the site, or the
  owner's standing pre-approval there;
- an audit log the site's owner can read;
- **a tool that can alter the machine's OS (Windows' Settings connector, a
  script runner) needs the person to prove admin or root access on that
  machine before it turns on** (J9, Troy's note);
- it meets Windows as a local agent with its own identity, so Windows' consent
  prompts and audit name it rather than "Eugene";
- **it never runs inside a privileged supervisor.**

The agent supervises it today. It is built so it can ship alone as an
unprivileged install when someone else's PC is the case (J5, §4.2).

**The channel grows from a queue to a held connection, at the message
level.**
- Request/response tool calls fit today's long poll.
- MCP's server-initiated messages, and tools that run long, want a connection
  the site holds open both ways: a WebSocket from the site carrying MCP
  JSON-RPC.
- Because it carries messages, not bytes, the root sees each call and can
  authorize, log or refuse it. A byte-level tunnel (B.5) cannot.
- Today's limits are file-tool limits and become per-tool: 32 KiB reads,
  70 KB results, 20 s per job, 8 jobs per node.

**Later, the root presents every site's servers as one remote MCP endpoint,**
signed in with Eugene. Then Workbench, Claude Desktop, Claude Code and Codex
reach site tools the same way. That satisfies Troy's brief for Workbench:
*"it can not have access to anything in Eugene that any other harness
wouldn't have."* Today the helper is reachable only through an
Eugene-specific API that Workbench alone calls. It is also the tool-side twin
of the gateway's *one endpoint for every model*.

### 3.5 Operations across sites

Copy a folder from the desktop to the NAS, and the other jobs people
otherwise hand to Dropbox, OneDrive or Google Drive (J10, after J6).

- **Neither site can dial the other, so a copy goes site A → root → site B.**
  It is streamed and never stored at the root. Its speed is the slowest of
  A's upload, the root's link and B's download. Two sites on the root's own
  LAN copy at LAN speed.
- **It is chunked, resumable and hash-verified**, as the library's downloads
  already are. It runs on a stream of its own, so a copy never stalls a chat.
  It is the first feature that needs the held channel of §3.4.
- **The tool lives at the root and drives each site's own tools.** Policy is
  checked at both ends: A must allow the read and B the write, and each
  site's rule is final. The approval shows both sites and both paths.
- **Contents never enter the replicated log**, which is already the helper's
  rule.
- **It runs on demand only.** Continuous sync, with its conflicts, deletions
  and versions, is a separate product.

### 3.6 Automation and managed fleets (direction, not built)

- **Every management action is an API that a scoped, non-interactive
  credential can drive.** The console is one client of it. That is what an
  MSP's own tooling, or a paid service's signup flow, needs.
- **Joining has two paths that end in the same state.**
  - Confirm-at-the-machine (§3.3) is the novice and household path.
  - A managed fleet installed by an MSP's deployment tool has no person at
    each machine. It needs enrolment in bulk by a scoped automation
    credential, naming each site's owner (J16).

### 3.7 Security

- **A site listens on nothing public.** Its agent and helper stay on loopback.
- **What the internet reaches before authentication:**
  - the join-token check;
  - token verification on the helper routes;
  - the bundle read, token-gated on this route.

  The rule *nodes are never public* (2026-10-05) narrows to *a public node
  route carries signed node traffic and nothing else* (J3).
- **A leaked join token** yields at most a file-only, address-less site within
  the token's 15 minutes. It appears under People, starts disabled, has no
  owner grants, and gets nothing until someone grants it.
- **A stolen site key** reaches, from anywhere, the bundle and that site's own
  jobs. That is narrower than the same key on the LAN, and revoking it is one
  step.
- **A compromised root** reaches every tool anyone has been granted on every
  site, and with §3.5 it can move data between a person's sites. That is why
  site-final policy and the site's audit log are not optional, and why J14
  exists.
- **Rate limits** apply to enrolment and to polls from public sources. The
  existing bound of 8 jobs per node limits a stolen key's queue.
- **On a managed PC, running the helper is the office's decision.** The
  route works over port 443 and, after the fix, through a proxy. Nothing is
  designed to look like web traffic in order to get past a policy.

### 3.8 Performance

- **One operation is two or three round trips** over a poll the site already
  holds open: roughly 100-300 ms across the internet. That is estimated, not
  measured. The ceiling is `JOB_SECONDS` (20 s).
- **Measured locally** (B.4):
  - a hop adds 0.4-1 ms;
  - streaming is unaffected;
  - a plain Python asyncio relay carried about 2 GB/s.

  So the root's relay will not be the bottleneck for a copy; the slowest
  internet link will be.

---

## 4. Why a central chat, when the field runs the interface where the files are

Troy: *"Claude Code... Codex... Hermes... OpenClaw... everyone else runs the
interface where the files are... There has to be a good reason for that."*

### 4.1 The field's reasons, and why Job Sites differ

The field has five reasons:

1. **Every connection leaves the user's machine**, so NAT never matters.
2. **Authority stays with the person, while they are there.** No central
   service holds standing grants into many machines.
3. **Real file work needs a shell, search, git and builds**, which cannot be
   brokered safely across machines.
4. **A task is hundreds of small operations**, and here each one crosses
   three machines.
5. **The approval belongs where the person and the files are.**

The cloud agents confirm the pattern. Claude Code on the web and Codex cloud
copy the repository to the agent; neither reaches into a PC.

**Workbench on the server was still right** for what it is: chat from any
device, one key held server-side, history kept centrally, several people, and
the small business. Job Sites answer the field's reasons one by one:

- **Reason 1:** the pull design (§2.2).
- **Reasons 2 and 5:** site-final policy and approval on the site (§3.3,
  §3.4).
- **Reasons 3 and 4:** these remain real. Brokered tools will stay a thinner
  set than a local shell.

What Job Sites buy in exchange is the one thing a local agent cannot do:
**work on several machines, from anywhere, in one conversation.** With MCP on
each site, an agent sitting at a machine can still use that machine's servers
directly, so the two placements stop being either/or:

| Where the files are | Interface |
|---|---|
| On the server | Central Workbench + C6 host folders. Works today |
| On the machine you are sitting at | Any agent on that machine, pointed at Eugene's gateway, or that machine's servers directly |
| On machines you are away from | Central Workbench + Job Sites |

### 4.2 A role on the node, or its own install?

| | Its own install | File-only node role |
|---|---|---|
| **What sits on the owner's PC** | **One unprivileged service that touches only shared folders, with no listener** | The full agent, a privileged supervisor, with the role switching most of it off |
| **Cost** | A new identity type at control, a second installer and updater, service-account setup, and a third copy of the folder code. It also reverses Troy's 2026-10-04 call of *one installation, one enrollment* | Small |

**Recommendation (J5): the role first.** Build the site-side piece (§3.4) as a
self-contained, unprivileged local MCP host that the agent supervises. It can
then ship alone, without rework, when someone else's PC or an MSP customer is
the case.

---

## 5. A first slice (proposal)

1. **Today's four tools, from outside the LAN, with the access model.** Calls
   J3, J4, J7, J9, J11, J13, J15 and J18, plus the proxy fix. J12 (owner-set
   passwords) is not in it.
   - *Done when:* a machine on another network joins over the public route,
     with WSL2 behind its NAT as the stand-in. Then:
     - Eugene's owner sees it online, with its last contact;
     - its own person grants a folder;
     - Workbench reads through it;
     - in production mode, Eugene's owner cannot read it, by grant or by
       chat;
     - in dev mode the owner can, and every user is told so;
     - a leaked join token yields only a disabled file-only site.
2. **MCP between site and root** (J6), and site-final policy (J8). The four
   tools become Eugene's own MCP server on the site.
3. **Cross-site copy** (J10), on the held channel.

### 5.1 What building slice 1 found (2026-10-05)

- **A bare address needs two things from Caddy.** A client sends no SNI for an
  address, so no name-matched TLS policy applies: the address's certificate is
  chosen by a `default_sni` policy. And Caddy's server-wide strict SNI check
  then answers every such request 421. For an address origin the server check
  is off and the first route makes the same check, letting through only
  requests to that address with no SNI. Measured on real Caddy 2.11.7: a TLS
  session made for the console's name and sent to the address is still 421.
- **Registering a folder was the operator's in two places**: the agent's relay
  and the helper worker each refused any other subject. On a job site its owner
  registers. The root now tells a site its owner in the poll answer
  (`siteOwner`), and the relay allows that person and nobody else, Eugene's
  owner included. The worker no longer knows who may register, only that a
  registration names someone and asks about one path.
- **A job site's key holds `files` instead of `node`.** Its tokens reach the
  root's node routes and its own machine, nothing else. The root also refuses
  a site's token on every route but the helper's three and the bundle, so a
  route added later cannot open to one by forgetting.
- **A site has no console.** Its local sign-in answers 409 and says to use
  Workbench. Reading it (the acceptance does) takes a token its own key signs
  for itself.
- **The owner's live view of someone's chat streams only "changed".** The page
  then re-reads the chat through the redaction, so a running answer never
  reaches the owner before production mode could hide it (J13a).
- **Codegen renamed `Person` to `Person1`** when a job-site schema had an
  inline item object; the schemas are named now. The trap this file's project
  notes record, met again.
- **Not done, named:**
  - Workbench's join commands use the installer from `main`, not the root's
    release tag, which Workbench does not know.
  - Ordinary nodes' file helpers stay operator-managed. Giving a LAN node a
    site owner is a later step.
  - A site skips its address announcement. No check can see that: the public
    route refuses the announcement anyway.
  - macOS, Docker and per-user installs cannot be job sites (§2.1).

### 5.2 What building slice 2 found (2026-10-05)

Built: MCP between site and root (J6) and site-final policy (J8), with J6g's
one file server per machine. Record:
[`job-sites-mcp-run.md`](../acceptance/job-sites-mcp-run.md).

Pins: agent `f6705fc` (site-host `38d7ed8`, Workbench dist `bf4aeef` from
`d872e00`), control `d4a7dda`, ui `52d84f7` / dist `8cbe323`.

- **Contracts `29cbf3c` and `b98899c`** revise `ba9a280` for J6g. Eugene's
  file server is `files`, once per machine; its tools take a `folder`
  argument whose value is the folder's name, unique on the machine (an older
  duplicate reads `Name (2)`). Folders carry their own people (read, or
  writable as a standing pre-approval for `write_text`), set by a new
  management action, `folder.people`. `grants` is a list. A site's report
  names each folder's identity, because Eugene's owner's dev-mode grant must.
- **`site-host`** builds the file server for one person and one request: the
  `folder` argument lists only that person's folders, and `write_text` only
  the ones they may change. The worker's folder-scope tests moved here.
- **The agent** relays to the host (`SiteHostRelay`) and has the elevated
  `site` CLI (`status`, `audit`, `server add|remove`). The bespoke helper and
  its worker are deleted.
- **Control** carries the envelope. Listings come from each site's last
  report, a cache: the site checks every call again. Every owner route is a
  relayed management action. The console's routes need the `node-files`
  capability (J15).
- **Workbench** shows one server per machine, narrowed to the folders a
  chat selected, and a job site's local servers as tools a chat can choose.
  Chats still select folders as `node:<id>`, so no stored id needed
  migrating. The Job sites page manages folder people, local servers, the
  dev-mode opt-in and the audit log.
- **The console** says when a site's owner has not let Eugene's owner in.

**Found by building it:**
- **The 2026-07-28 envelope requires `clientCapabilities`** in `_meta`, and
  the SDK answers a request without it with an error. The contract said it
  was optional, and Workbench's first build left it out. Workbench's fake now
  refuses such a request too.
- **The local servers cannot travel in the host's launch environment.** A
  list can exceed the agent's 2,048-character value cap, and an argument
  holding braces would trip the launcher's placeholder fill. The agent writes
  the list to a file beside the host's install, which the host's account can
  read and not write, and names its SHA-256 in the environment. The host
  refuses a file that differs.
- **`site server add --command X` started a whole agent.** The option shared
  its argparse dest with the subcommand. The acceptance found it, running the
  CLI unelevated. An argument beginning with `-` is given as `--arg=-x`.
- **A slice 1 defect: the TLS key list was decoded with no clock leeway.** A
  root 2.4 s ahead of the site (WSL2 behind its NAT) failed the join with
  *"not signed by its pinned key"*. It allows the 300 s every token here
  allows, and a list dated further ahead says to check the clocks.
- **Harness, not product:** from Git Bash on Windows, a child that inherited
  the script's standard input hung at start, twice: the site agent, and the
  build backend uv ran for the site host. Every child gets `DEVNULL` now.
- **A slice 1 site's folders do not carry over.** Slice 1 kept them on the
  root's replicated record. They still replay but grant nothing, so a site
  upgraded from slice 1 registers its folders again. Slice 1 reached edge
  only.

**Not done, named:**
- Approving each call at the machine waits for the held channel (slice 3).
- The service install on GitHub's runners
  (`node-file-helpers-service-acceptance.py`) needs the pushed pins. It is a
  manual dispatch.

**Later, each as its own design:**
- slice 2b, the workspace server under the person's own account (J6h, J6i);
- the standalone site install (J5);
- person-held keys (J14);
- managed-fleet enrolment (J16);
- the root's MCP endpoint for other clients.

---

## 6. Calls: Troy's decisions (2026-10-05)

| # | Call | Decision |
|---|---|---|
| J1 | The name | **Job Site.** *Job sites (your machines)* in Workbench; the console keeps *Files on your machines* |
| J2 | At the machine, or away from it? | **Away, and many machines at once** |
| J3 | A node-only public mode for the nodes name (`public_nodes`) | **Yes**, limited to the five paths in §3.1, with an acknowledgement |
| J4 | File-only Job Sites | **Yes**, with *no inference work* as defined in §3.2: no routing, runtimes, engines or model starts on the site. Scripts and OS actions are site tools for a later slice, not inference work |
| J5 | Its own install, or a role | **The role first**, with the site-side piece built so it can ship alone (§4.2) |
| J6 | MCP between site and root | **Yes, before a fifth tool** |
| J7 | No third party in the path | **Yes**: DNS-only or a bare address, with the root's certificate pinned at join by default. A rotation path is needed before it ships |
| J8 | Where policy is final | **On the site**: default deny, approval or standing pre-approval for destructive and system tools, and an audit log |
| J9 | Who may add a job site | **Any signed-in person, for their own machines.** Troy's note: **any future Job Site tool that could alter the machine's OS (Windows MCP, for example) needs the person to prove admin or root access on that machine before it turns on** |
| J10 | Cross-site copy | **Yes**, after J6 |
| J11 | Membership is not access | **Yes** |
| J12 | The owner setting another person's password | **Kept for now.** Doing it properly is a slice of its own. Until then, rule 3 of §3.3 does not hold against the owner |
| J13 | What the owner sees of job-site results | **A dev mode for Eugene.** In dev mode the owner can still see all tool information, and users are told so. In production mode owners are restricted. *"This will help me in developing Eugene properly"* |
| J14 | Person-held keys checked at the site | **Yes, later**, as its own design |
| J15 | Capabilities, not *the operator*, on new surfaces | **Yes** |
| J16 | Managed-fleet enrolment | **Design for it, do not build it** |
| J17 | The mesh-VPN commitment's wording | **Amend it.** Done in the local `CLAUDE.md` the same day. `README.md` changes when Job Sites ship |
| J18 | How dev mode switches | **Not retroactive**: results produced in production stay hidden after a switch to dev. **Every user sees the current mode** and is told when it changes. **New installs start in production** |

### 6.1 Calls taken when slice 1 started (Troy, 2026-10-05)

| # | Call | Decision |
|---|---|---|
| J7a | What a site pins | **The root's identity key, carried in the join command.** The root signs the list of TLS public keys its nodes name presents. A site accepts a connection only when the presented key is on a list it has verified. The list is public keys only, and is served at a **sixth public path, `GET /v1/trust/tls`**. Renewals need nobody: the root probes its own nodes name, and behind an outside proxy (NPM) it probes the public name; when it cannot, the console says so and joins fail closed |
| J13a | What production mode hides from the owner's chat reading | **Everything from the first job-site result on.** The model's later replies quote what it read, so hiding only the result would leak it. The owner sees the chat up to that point and one line saying the rest used files on a job site |
| J13b | What dev mode lets the owner do | **See everything and grant themselves folders.** Folders, grants and results become visible, and the owner may give themselves access to a site's folder. The owner's own grants on job sites stop working the moment the install is in production. Grants to other people stay the site owner's in both modes |

An existing install with no recorded mode is in production. Nothing changes
for it: before this slice there are no job sites, so there are no results to
hide.

### 6.2 Calls taken when slice 2 started (Troy, 2026-10-05)

Slice 2 is J6 and J8. Each call below was taken as recommended.

| # | Call | Decision |
|---|---|---|
| J6a | The channel | **The long poll, carrying MCP messages.** MCP's 2026-07-28 revision is one self-contained request in and one response out, with no handshake and no session, which is what the queue already carries. The six public paths stay. Tool-list changes ride the poll report, and calls stay bounded at about 20 s. The held WebSocket arrives with cross-site copy (slice 3) |
| J6b | Where a site's owner manages its policy | **Workbench, enforced on the site.** The site keeps its own copy and its own audit log, and accepts an edit only from the owner it pinned at its join. The root's copy is a cache. A destructive tool is allowed only as an explicit standing pre-approval; approving each call at the machine waits for the held channel. A local CLI shows status and the audit log. The limit of §3.3 stands: a compromised root could forge an owner's edit (J14) |
| J6c | MCP library and protocol | **The official `mcp` SDK, 2.3 series** (Workbench's pin since C5). **2026-07-28 between site and root**; the handshake revisions to local stdio servers |
| J6d | Ordinary LAN nodes | **The same host everywhere.** On a LAN node Eugene's owner still writes policy from the console, under a named capability; on a job site its own list is final. The bespoke `{tool, arguments}` path is deleted |
| J6e | Dev mode against rule 2 | **The site's owner opts in on the site.** A per-site setting, off by default: *let Eugene's owner in while Eugene is in dev mode*. J13b's self-grant then works there. Dev mode alone opens nothing |
| J6f | Where the host's code lives | **A new repo, `site-host`**, with its loopback API as a specs document. The agent installs it as a bundled app at a pinned commit, in its own OS account. It can ship alone later (J5) |

Two choices made with them, each the conservative reading, for Troy to
overturn:
- **A local MCP server is added at the machine, never from Workbench.**
  Adding one names a program on that machine, so it is the machine
  administrator's act, as C5b's local servers are: an elevated CLI on the
  site writes it into the install's protected configuration. Who may use it
  is then policy, set from Workbench.
- **J9's gate is an elevated CLI.** It checks for an administrator token
  (Windows) or uid 0 (Linux), and records the server's name and its
  program's hash in that same protected file, which the host's own account
  cannot write. The host refuses to enable a server marked `system` without
  that record. No such server ships in slice 2; a test server proves the
  gate.

### 6.3 Calls taken during slice 2 (Troy, 2026-10-05)

| # | Call | Decision |
|---|---|---|
| J6g | The shape of Eugene's file server | **One `files` server per machine, its tools taking a `folder` argument.** This replaces the first build's one server per folder (`files.<id>`, in contract `ba9a280` and site-host `f58a0a6`). Folder grants stay per person and per folder: read, or write as a standing pre-approval. Slice 1's `/oidc/job-sites/{node}/folders/{id}/people` comes back, relayed to the site. Per-tool access remains for local servers. The host lists, in a person's `folder` argument, only the folders they may use, and for `write_text` only those they may change. On a LAN node the root sends all of the person's grants on that node (`grants`, a list); the host checks the named folder against them. Workbench shows one server per machine and narrows the folder list to the folders a chat selected |
| J6h | Workbench and Eugene's MCP should *"act like Claude Code, Codex, or OpenClaw... full local access within permissions"* | **Slice 2b, on this host.** Slice 2 finishes the MCP channel, site-final policy and today's file tools (J6g), proven end to end. Slice 2b adds a workspace server like Claude Code's: read, write, edit and search within granted workspaces, under allow/ask/deny rules per tool and path; commands come with it, under J9's gate |
| J6i | Which OS account local-access tools run as | **The person's own account**, like Claude Code: everything the person can touch. Slice 2b's design has to answer how: a process in the person's session or holding their credentials. It also has to address that a compromised root then reaches everything the person owns, which raises J14's priority. Slice 2's host keeps its own unprivileged account for today's file tools |

---

## 7. What this design does not cover

- **Inference across networks.** It is out of scope by Troy's decision.
  Appendix B is the analysis, and its Tailscale recommendation is withdrawn.
  If this returns, the self-hosted candidate is the agent-held tunnel (B.5).
- **Clients reaching the install from outside.** That is the entry point and
  `public_console` (`single-port-entrypoint.md`).
- **Continuous sync between sites.**
- **macOS, Docker and per-user installs as Job Sites.** The helper is
  unavailable there today (§2.1).
- **Corporate proxies that need NTLM or Kerberos.**
- **TLS between machines on a LAN.** Today that traffic is clear text.
- **Defects found on the way, filed rather than fixed:**
  - [agent#8](https://github.com/eugene-plexus/agent/issues/8): the address
    announcement is never retried, nor re-sent when the address changes;
  - [agent#9](https://github.com/eugene-plexus/agent/issues/9): the HTTPS
    entry point on a worker hides its models from the root's gateway;
  - [control#5](https://github.com/eugene-plexus/control/issues/5): a
    standby cannot follow the root, because it has no credential.

---

## Appendix A. Every connection between a root and a node

Read from the code at agent `a8cfdde`, control `b667699`, gateway `219b191`,
inference-driver, library, tool-driver and workbench `main` (2026-10-05). The
code was read, not this repo's notes. The paths are abbreviated:

| Prefix | Repo path                                             |
| ------ | ----------------------------------------------------- |
| `A/`   | `agent/src/eugene_plexus_agent`                       |
| `C/`   | `control/src/eugene_plexus_control`                   |
| `G/`   | `gateway/src/eugene_plexus_gateway`                   |
| `D/`   | `inference-driver/src/eugene_plexus_inference_driver` |
| `T/`   | `tool-driver/src/eugene_plexus_tool_driver`           |
| `L/`   | `library/src/eugene_plexus_library`                   |
| `W/`   | `workbench/src/eugene_plexus_workbench`               |
| `U/`   | `ui/src`                                              |

The token kinds below are as follows:

| Token           | What it is                                                                                                            |
| --------------- | --------------------------------------------------------------------------------------------------------------------- |
| **svc:control** | A 5-minute token that control mints per node per call.                                                                |
| **svc:gateway** | A 15-minute token for `node:X`, signed by the gateway host's agent. It needs the `gateway` grant.                     |
| **svc:agent**   | A 15-minute token the node's own agent mints.                                                                         |
| **xchg**        | An operator session exchanged at the root for a token of at most 5 minutes, addressed to one node and carrying `act`. |

**Nothing between machines uses TLS.** Node and component URLs are built as
`http://` (`A/node_identity.py:197-201`, `A/routes/components.py:96`). On a
tailnet, WireGuard encrypts the traffic. On a LAN, prompts and tokens cross in
clear text.

### A.1 Opened by the root's host: a NAT in front of the worker breaks every one

| #   | Initiator → target                                     | Endpoint                                                                                                                                                                         | Purpose                                                                                            | Auth                                                                         | How often                                                                                             | Size                                  | If it fails                                                                                          | Anchors                                                                              |
| --- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| R1  | root gateway → worker driver                           | `POST /v1/generate`, `/v1/generate/stream`, `/v1/embed`, `/v1/image*`, `/v1/speak`, `/v1/transcribe`, `/v1/video*`, `/v1/decide`, `/v1/moderate`, at the driver's `advertiseUrl` | **Inference**                                                                                      | svc:gateway                                                                  | Every request. 600 s deadline, 10 s connect                                                           | Up to 16 MiB in; SSE token stream out | Fails over to a replica or a later tier before the first token; a circuit breaker per driver, 1→60 s | `G/driver_client.py:394,522`, `G/routing.py:1438-1442`; `D/routes/generate.py:50,78` |
| R2  | root gateway → worker driver                           | `GET /v1/info`                                                                                                                                                                   | Discovery and liveness                                                                             | svc:gateway                                                                  | Every 15 s (`routingRefreshSeconds`); per request when a key is `localOnly` or names settings         | 1-5 KB                                | Driver marked `unreachable`, not routed                                                              | `G/routing.py:1563-1583`; `D/routes/info.py:29`                                      |
| R3  | root gateway → worker agent                            | `GET /v1/components`, `GET /v1/runtimes` at `Node.url`                                                                                                                           | Driver URLs, runtime state                                                                         | svc:gateway                                                                  | Every 15 s, 5 s timeout                                                                               | A few KB                              | Keeps the node's last good facts                                                                     | `G/routing.py:1416,1470,1345-1359`                                                   |
| R4  | root gateway → worker agent                            | `POST /v1/runtimes/{n}/stop`, `/start`, `GET /v1/runtimes/{n}`, `POST /v1/runtimes/admission`                                                                                    | Idle unload, wake on demand, eviction                                                              | svc:gateway                                                                  | Idle sweep every 15 s; wake per request, polled every 1 s up to `swapWaitSeconds`                     | < 1 KB                                | Wake fails with a 503 naming the cause; a stop is retried next sweep                                 | `G/lifecycle.py:79-145,374-484`                                                      |
| R5  | root gateway → worker tool-driver (direct)             | `GET /v1/info`, `POST /v1/tools/web_search`                                                                                                                                      | Web search                                                                                         | svc:gateway                                                                  | Every refresh; per tool call (30 s)                                                                   | Small                                 | Tries the next account                                                                               | `G/routing.py:1516-1553`, `G/tool_client.py:116,138`                                 |
| R6  | root control → node agent                              | `GET /v1/node`                                                                                                                                                                   | Liveness probe                                                                                     | svc:control                                                                  | Every 15 s (`nodePollIntervalSeconds`), 5 s timeout                                                   | 2-10 KB                               | `reachable: false` with `lastError`. **Reporting only:** nothing routes on it (finding 3)            | `C/app.py:287-368`, `C/nodes_client.py:137-179`                                      |
| R7  | root control → every node agent                        | `GET /v1/components`, `GET /v1/runtimes`                                                                                                                                         | Install-wide views                                                                                 | svc:control                                                                  | Every call to control's views: the Inference page every 3 s, and every agent's lookup cache miss (N5) | A few KB per node                     | Node listed in `unreachableNodes`                                                                    | `C/nodes_client.py:190-242`, `C/routes/topology.py:78-85`                            |
| R8  | root control → node agent                              | `POST /v1/runtimes`                                                                                                                                                              | Forwards an operator's launch on that node                                                         | svc:control                                                                  | On click                                                                                              | ~1 KB                                 | 502 relaying the agent's answer                                                                      | `C/nodes_client.py:261-282`                                                          |
| R9  | root control → node agent                              | `POST /v1/node/trust-bundle`                                                                                                                                                     | **Push** of the signed trust bundle: a new node, a revocation, a sign-out, a rotation, a new epoch | None; a JWS signed by the root's identity key, which the node pinned at join | On each of those events                                                                               | 1-10 KB                               | Logged, not retried; **the node's 60 s pull (N3) replaces it**                                       | `C/trust.py:170-219`; `A/routes/node.py:414`                                         |
| R10 | root agent (console) → worker agent                    | `ANY /api/proxy/node:<name>/…`                                                                                                                                                   | Every per-machine console action: start, stop, engines, apps, settings, logs (SSE), updates        | xchg                                                                         | On click; Needs Attention reads 5 endpoints per node every 30 s                                       | Streams; up to 32 MiB                 | 502 "Upstream unreachable"                                                                           | `A/routes/proxy.py:364-406,500-577,651`; `U/lib/useIssues.ts:53,148-159`             |
| R11 | root agent → worker agent → worker component           | `ANY /api/proxy/<driver-or-tool>/…`                                                                                                                                              | Console reaching a remote component's settings                                                     | xchg                                                                         | On click                                                                                              | Small                                 | 502                                                                                                  | `A/routes/proxy.py:281-361`                                                          |
| R12 | worker OS → file server (often the root host or a NAS) | SMB 445, `WNetAddConnection2W`                                                                                                                                                   | Model files and the node-local copy, which **reads the share, not HTTP**                           | Share credentials sealed on the node                                         | Every model load; the copy once per model                                                             | GBs                                   | Launch falls back to opening the share directly                                                      | `A/share_credentials.py:163`, `A/model_copies.py:36-40,361`                          |

**R13**: when a console hops to another node, the agent serving the browser
dials that node directly at the `Node.url` it got from control. From a worker's
console that hop is worker → worker and never passes the root
(`A/routes/proxy.py:364-406`).

### A.2 Opened by the worker: these survive a NAT in front of the worker

They still need **the root** to be reachable from the worker's network.

| #   | Initiator → target                                 | Endpoint                                                    | Purpose                                                            | Auth                                                                  | How often                                                                                             | If it fails                                           | Anchors                                                                        |
| --- | -------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------ |
| N1  | worker agent → control host:port                   | TCP connect only                                            | Derives the advertise host from the local end of the socket        | None                                                                  | At join, at boot, on change                                                                           | Falls back to the stored address                      | `A/node_identity.py:204-231`                                                   |
| N2  | worker agent → control                             | `POST /v1/nodes/enroll`                                     | Join                                                               | Single-use join token (900 s)                                         | Once                                                                                                  | Nothing recorded                                      | `A/enrollment.py:202`; `C/routes/nodes.py:427`                                 |
| N3  | worker agent → control                             | `GET /v1/trust/bundle`                                      | **Pull** of the bundle: revocations and epoch fencing              | None; JWS checked against the pinned key                              | Every 60 s                                                                                            | Keeps the bundle it has                               | `A/app.py:541-577`; `C/routes/control.py:338`                                  |
| N4  | worker agent → control                             | `PATCH /v1/nodes/{name}` `{url, sequence, signature}`       | Address announcement                                               | Ed25519 signature by the node's identity key                          | Boot, a change to `advertiseUrl`, the Reach switch. **Not retried, and not sent on a network change** | Root keeps the old URL until the next trigger         | `A/enrollment.py:279-337`, `A/app.py:417,625-662`; `C/routes/nodes.py:155-323` |
| N5  | worker agent → control                             | `GET /v1/components` + `GET /v1/nodes`                      | "Who runs X, at which agent URL"                                   | svc:agent                                                             | Cached 30 s; each miss makes control fan out R7 to every node                                         | 503 naming the missing address                        | `A/install_proxy.py:84-89,223-269`                                             |
| N6  | worker agent → **root agent** `/api/proxy/library` | `GET /v1/folders`, `/v1/models`, `/v1/models/{id}/fit`      | Library folders, admission fit                                     | svc:agent                                                             | Per launch path; `folders/check` via Needs Attention every 30 s                                       | Admission falls back to file size                     | `A/admission.py:257-349`, `A/library_folders.py:249-274`                       |
| N7  | worker agent → root agent → library                | `GET /v1/run-operations/assigned`, claim, checkpoint        | Library-owned "run this model" jobs                                | svc:agent                                                             | **Every 2 s**                                                                                         | Retried in 2 s                                        | `A/run_worker.py:188-232,322-338`                                              |
| N8  | worker agent (console) → root agent                | `/api/proxy/{gateway,library,control}`                      | The worker's console showing install pages                         | Session to `control` passes unchanged, else xchg                      | UI polling                                                                                            | 502/503 with the reason                               | `A/routes/proxy.py:328-361`                                                    |
| N9  | worker agent → control                             | `POST /v1/auth/token`                                       | RFC 8693 exchange                                                  | svc:agent as actor                                                    | Cached per session and audience                                                                       | 503 "Control root unreachable"                        | `A/routes/proxy.py:497-523`                                                    |
| N10 | worker agent → control                             | `POST /v1/auth/login`, sign-out, unenrol                    | Forwarded sign-in and sign-out                                     | svc:agent / the session                                               | On click                                                                                              | 503; unenrol goes ahead with `controlNotified: false` | `A/routes/auth.py:422-475`, `A/routes/node.py:376-411`                         |
| N11 | worker agent → control                             | `/v1/auth/client-keys*`, `…/admission`                      | Client-key registry and admission                                  | svc:agent (+ subject token)                                           | Log-ingress key check every 15 s; per request for a gateway on a worker                               | **Fails closed**: 503                                 | `A/client_key_registry.py:82-139`                                              |
| N12 | worker agent → control                             | `GET/POST /oidc/*`                                          | Sign in with Eugene for apps on the worker; Workbench node folders | Forwarded headers + node token; client secrets checked at the root    | Per sign-in step                                                                                      | 503 `temporarily_unavailable`                         | `A/routes/oidc_forward.py:76-123`                                              |
| N13 | worker agent → control                             | `POST /v1/oidc/clients`, `PUT …/redirect-uris`, client keys | App install on the worker; callbacks moved at boot                 | svc:agent (+ subject token on install)                                | On install; at boot, retried 5→120 s                                                                  | Install fails                                         | `A/sign_in_refresh.py:36-62`, `A/routes/apps.py:296-361`                       |
| N14 | worker agent → control                             | `POST /v1/node-helpers/poll` (long poll, 8 s)               | File-helper work queue: **the root never dials the node**          | svc:agent                                                             | Continuous                                                                                            | Silent retry after 5 s                                | `A/node_file_helper.py:262-309`; `C/node_helpers.py:25,188-207`                |
| N15 | worker app → root agent `/api/proxy/gateway`       | OpenAI-compatible `/v1/*`                                   | Workbench or Open WebUI on a worker using inference                | App client key                                                        | Per request (SSE)                                                                                     | Named to the user                                     | `A/app.py:685-726`, `W/hub.py:81-82`                                           |
| N16 | standby control → active control                   | `GET /v1/control/log`, `/snapshot`                          | Replication                                                        | **None sent; the routes need a session**, so every tick is a 401 (§7) | Every 2 s                                                                                             | Retries forever                                       | `C/app.py:142-151`, `C/dependencies.py:175-183`                                |

Each node also fetches updates, engines and app packages from GitHub and PyPI
itself. The root never tells a node to update (`A/updates.py:70-79`).

### A.3 What the inventory says

1. **Inference is root → node and has no fallback.** R1-R5 are opened by the
   gateway, per request or every 15 s. The "public nodes name" floated on
   2026-10-05 would carry only N-rows (join, announcements, bundle pulls,
   helpers). The nodes hostname routes to control alone
   (`A/entrypoint.py:546-547`), and N6, N7, N8 and N15 dial the root *agent*,
   which is not on it. So a worker behind NAT could join and then serve nothing.
   An open port at the root, NPM's included, carries connections *to* the root.
   R1-R12 leave it.
2. **Of the twelve root → node connections, only the trust-bundle push (R9) has
   a worker-initiated replacement** (the N3 pull). R8 has a partial one, the
   library run-operations poll (N7). The file helpers (N14) already show the
   pull pattern: a long poll, and nothing dials the node.
3. **"Down" is reporting only.** Control's probe (R6) feeds the Nodes page. The
   gateway builds its node map from every node with a URL, ignoring
   `reachable` (`G/routing.py:1074-1080`), and stops routing to a driver only
   when its own calls fail. A node behind NAT shows *down: timed out* with
   nothing that names the cause or the fix.
4. **Behind a NAT, the derived advertise address is the worker's private
   address.** The worker learns it from the local end of its connection to the
   root (N1), and nothing checks that the root can dial it back. The join
   succeeding proves only the outbound half. `tailnet.md` §6 says so, and the
   product does not.
5. **One address per node, used by every caller.** N5-N8 and N15 dial the root
   agent at the root's single `Node.url`. On Troy's install that is a LAN
   address, `192.168.16.252:8279`. A remote node reaches it only if the private
   network carries that LAN (a Tailscale subnet route), or if every machine
   moves to tailnet addresses.
6. **Address rules.**
   - Moving from a private address to a public one is refused (409), and **any
     hostname counts as public** (`C/node_address.py:117-159`). A node joined
     at a LAN IP cannot later announce a MagicDNS name or a tunnel hostname; it
     must join again.
   - A tailnet address in `100.64.0.0/10` counts as private, which is right.
   - Driver URLs use the driver's own bind port, unadjusted for remaps
     (`A/routes/components.py:92-96`). Port forwarding would have to forward
     every companion port, 8090-8189, one for one.
7. **The rekey is gone.** It was replaced by the signed bundle on 2026-09-25
   (row 3). Its helpers survive as dead code in `C/sealing.py:185-244`.
8. **Model files reach a node over SMB (R12).** A remote node can run only what
   the root's library catalogues, so its models cross the WAN once, into the
   node-local copy, at the WAN's speed (B.1).

---

## Appendix B. Inference across networks (out of scope)

**Status: analysis only, out of scope by Troy's decision of 2026-10-05.** This
was the doc's first question: how a node outside the root's LAN could serve
inference.

**Its first recommendation, a guided Tailscale path, is withdrawn.** Troy
ruled out cloud services in the path, and Tailscale's coordination is one.

Two product checks that recommendation carried are still useful for LAN
nodes, and may be revived on their own:
- a return-path check at join: the root probes the announced address once,
  and says plainly when it cannot reach it;
- the class of each node's address (LAN, mesh or public), shown on the Nodes
  page.

If inference across networks returns, the self-hosted candidate is B.5.

### B.1 Scenarios

"Today" means the shipped product with nothing but its own docs.

| #   | Scenario                                                                      | Root → node today                            | Node → root today                                                                                 | What it needs                                                                                  | Also bites                                                                                                        |
| --- | ----------------------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1   | Home LAN, plus a friend's PC on another home network (consumer NAT both ends) | Refused at the friend's router               | Refused at Troy's router unless control's port is forwarded, and the nodes name may not be public | A private network that crosses both NATs, or a tunnel from the friend's PC to a reachable root | The friend's PC must not see Troy's whole network (B.3, Tailscale ACLs); models cross the WAN                      |
| 2   | Office PC behind business NAT, outbound TCP 443 only, perhaps an HTTP proxy   | Refused                                      | Only to 443, maybe only through the proxy                                                         | Something that rides TCP 443 through a CONNECT proxy                                           | **Whether a VPN or tunnel client may run on that PC is the office's decision, not ours** (§3.7)                 |
| 3   | CGNAT on either end                                                           | Impossible to forward into a CGNAT side      | Fine from a CGNAT worker if the root is reachable; impossible *into* a CGNAT root                 | NAT traversal with a relay fallback. A root on CGNAT needs a relay even for a built-in tunnel  | Relayed paths are slower (B.3)                                                                                   |
| 4   | GPUs in two buildings, each with its own internet (Troy's plan)               | Refused                                      | Refused unless forwarded                                                                          | As 1, with one owner at both ends                                                              | Models cross the WAN; clock skew (`tailnet.md` §7)                                                                |
| 5   | A laptop node moving between networks                                         | Works only on the network where it announced | Works where the root is reachable                                                                 | A stable address, or no address at all (a node-held tunnel)                                    | The announcement is sent at boot and on a settings change, **not when the network changes, and not retried** (N4) |

**Model files, under every option.** A remote node opens models through a
Library folder mount (R12). Over a WAN, that means SMB across the private
network into the node-local copy, once per model. Two figures below are
arithmetic, not measurements:

- A 23.8 GB model at a 40 Mbit/s home upload takes about **80 minutes**.
- The same model at the ~10 Mbit/s one Tailscale issue reports over a relay
  (#18017) takes about **5 hours**.

No transport choice changes the upload speed. A node that downloads from
Hugging Face itself would sidestep it (not designed).

---

### B.2 Options matrix

"Steps" counts what a weekend user does to add **one** remote node to an
existing install. Troy's bar: *"no weekend LLM enthusiast is going to do all of
this."*

| Option                            | Reachable from the internet                                                                                              | Steps / accounts                                                                                      | 443-only / proxy                                                             | CGNAT                                                                  | Path and speed                                                                            | Dependency when it fails                                                                                     | Our code                                                                                                                       | Fits the mesh commitment                                                                                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| **Tailscale**                     | Nothing. WireGuard answers only peers; relays carry ciphertext                                                           | ~5 steps, 1 account (a friend's PC needs none, with a tagged auth key)                                | Yes: DERP over HTTPS 443, through a CONNECT proxy; NTLM proxies are doubtful | Yes, relayed when both ends are hard NAT                               | Direct when hole-punched; DERP is QoS'd (#14661, #18017); peer relays need UDP            | Coordination outage: existing paths keep working, no new joins (Appendix C cites eight partial outages Jul-Oct 2026) | Docs + four small checks (withdrawn)                                                                                                  | Yes, as written                                                                                                          |
| **Headscale**                     | The Headscale server (HTTPS 443) and its DERP                                                                            | ~10 steps plus a VPS, a domain and TLS; no vendor account                                             | Same client as Tailscale                                                     | Yes (its own DERP, or Tailscale's by default)                          | Same as Tailscale                                                                         | You run it                                                                                                   | As Tailscale + docs                                                                                                            | Yes                                                                                                                      |
| **Plain WireGuard**               | One UDP port on a hub with a public address                                                                              | ~5-8 steps per node (keys, configs, a forward); admin on Windows                                      | **No** (UDP only)                                                            | **No** without a public hub                                            | Direct, kernel speed                                                                      | None                                                                                                         | Docs only                                                                                                                      | Yes                                                                                                                      |
| **ZeroTier**                      | Nothing on ours                                                                                                          | ~5 steps, 1 account, authorise each member                                                            | TCP relay on 443, "slow"; proxy not documented                               | Relayed via roots                                                      | Relayed is "slow"                                                                         | Central down: existing paths continue                                                                        | Docs only                                                                                                                      | Yes, but the controller is source-available non-commercial since 1.16.0, and the free tier is 10 devices, non-commercial |
| **NetBird**                       | Nothing on ours                                                                                                          | ~4 steps, 1 account (setup keys)                                                                      | Yes (WebSocket relay on 443); proxy partial (#5798)                          | Relayed                                                                | Relay ~25 Mbit/s reported (#6021)                                                         | Outages documented; existing paths stayed up                                                                 | Docs only                                                                                                                      | Yes; the server is AGPL                                                                                                  |
| **Nebula**                        | A lighthouse and relays on public UDP                                                                                    | ~7 steps self-managed PKI; Managed Nebula needs 1 account                                             | **No** (UDP only, #1001)                                                     | Via a public relay host                                                | Direct or relayed                                                                         | Lighthouse                                                                                                   | Docs only                                                                                                                      | Yes                                                                                                                      |
| **Cloudflare Tunnel + Access**    | A public hostname per worker port, gated by an Access service token; **Cloudflare terminates TLS and sees every prompt** | ~6 steps, 1 account + a domain on Cloudflare, per worker                                              | **No: needs outbound 7844**, and ignores `HTTPS_PROXY` (#1076)               | Yes                                                                    | Edge-proxied. **125 s to first response byte** (cold loads exceed it); 100 MB request cap | Cloudflare down = tunnel down                                                                                | Large: per-driver Access headers, per-port routes for dynamic companion ports, early headers that undo R2.5's first-chunk rule | No: an internet-facing proxy, not a mesh                                                                                 |
| **frp** (supervised, self-hosted) | frps on the root, on one public port (TLS + token)                                                                       | Root port forward + configs; we could automate both                                                   | Yes, in TCP mode through a proxy                                             | Worker yes; **root on CGNAT, no**                                      | Direct to the root; multiplexed TCP; ~390 MB/s with TLS here (B.4)                       | None (self-hosted); **Defender quarantines `frps.exe`** (B.4)                                               | Medium-large: supervise frpc/frps, map every dynamic port, a second auth system beside ours                                    | Partly: a tunnel, not a mesh                                                                                             |
| **rathole / ssh -R**              | sshd or the rathole server on the root                                                                                   | Per-port forwards, keys                                                                               | Yes (ssh via ProxyCommand)                                                   | Root on CGNAT, no                                                      | One TCP connection per call (rathole); HOL on one SSH link                                | None                                                                                                         | As frp; rathole dormant since 2023, autossh since 2019                                                                         | Partly                                                                                                                   |
| **ngrok**                         | A public endpoint per tunnel; ngrok terminates TLS                                                                       | 1 account, a card for TCP                                                                             | Yes                                                                          | Yes                                                                    | Edge-proxied                                                                              | ngrok down = down                                                                                            | Medium                                                                                                                         | No; proprietary agent, **1 GB/month** free                                                                               |
| **Port forward + mTLS**           | **The worker's agent, drivers and tool-drivers, to the whole internet**                                                  | A forward per port (~100), our own CA, client certs                                                   | n/a (inbound)                                                                | **Impossible**                                                         | Direct                                                                                    | None                                                                                                         | Large: TLS on every port, a CA, remap-aware URLs, the public-address rule reversed                                             | No; breaks "nodes are never public"                                                                                      |
| **IPv6 direct**                   | The worker's ports over IPv6                                                                                             | A router firewall rule per port, at both ends                                                         | n/a                                                                          | Bypasses IPv4 CGNAT where IPv6 exists (~41-52% of users, APNIC/Google) | Direct                                                                                    | None                                                                                                         | As port forward                                                                                                                | No; same exposure                                                                                                        |
| **Built-in tunnel** (B.5)        | **On the node, nothing.** On the root, one hub endpoint on the nodes name, with a signed handshake before anything else  | Root: one forward of 443 + a name (or Cloudflare/Funnel in front); node: the join command. No account | Yes: WSS on 443, `HTTPS_PROXY` honoured by `websockets`                      | Worker yes; **a root on CGNAT still needs a relay in front**           | Node ↔ root directly, no third party; one TCP link (head-of-line on loss)                 | None                                                                                                         | **Large**: framing, per-stream flow control, handshake, hub routing, gateway/control/console transport, UI, degraded mode      | Needs the commitment revisited (J17)                                                                                  |

### B.3 What separates the top three

- **Tailscale** is the only option that crosses NAT and CGNAT at both ends,
  runs over a 443-only proxy, and needs no public endpoint anywhere.
  - Its costs are a third-party account and a coordination server we do not
    control.
  - Its default policy is **allow-all**: a friend's PC added to Troy's tailnet
    can reach every device on it, and the reverse, until an ACL says otherwise.
  - A user device's key expires after 180 days by default, and the Windows
    client disconnects at sign-out unless `--unattended` is set. Both would
    silently drop a headless GPU box. A tagged auth key fixes the first, and
    the guide must cover both.
- **A built-in tunnel** needs no account and no VPN anywhere.
  - It moves the reachability problem from N nodes to **one** root: one port
    forward or one relay instead of a client on every machine.
  - It does not solve a root on CGNAT.
  - It puts the first pre-authentication surface for nodes on the internet.
- **Cloudflare Tunnel** looks closest to what Troy already runs, and fails
  three ways here:
  - it needs port 7844, not 443, and no HTTP proxy;
  - a cold model load overruns its 125 s first-byte deadline;
  - **Cloudflare decrypts every prompt** on a product whose reason to exist is
    local inference.

  Cloudflare Mesh (formerly WARP Connector, 2026-04) is layer 3 and free for 50
  nodes. Its nodes are Linux-only today. Worth re-reading when it reaches
  Windows and Docker.

### B.4 Measured on this box

**Setup.**
- Ryzen 9 9950X, running Windows 11 and WSL2 in NAT mode (172.19.x).
- A stub SSE server sends 200 frames at 10 ms intervals, so the ideal total is
  2.0 s.
- An unbuffered raw-socket client makes 50 requests per path, each on a fresh
  connection, after 5 warm-ups.
- Each path also carries three 2 GiB bulk transfers.
- frp v0.71.0. Scripts are in the session scratchpad (`remote-nodes/`).
- **Every number is a local hop.** None includes a WAN round trip.

| Path                                                                  | TTFT median / p90 (ms) | SSE total median (ms) | Max gap p90 (ms) | Bulk MB/s               |
| --------------------------------------------------------------------- | ---------------------- | --------------------- | ---------------- | ----------------------- |
| Windows → WSL direct                                                  | 0.35 / 0.59            | 2000.6                | 10.58            | 3167-4593               |
| frp, tcp + mux, TLS off                                               | 1.33 / 1.90            | 2001.8                | 10.44            | ~540                    |
| frp, tcp + mux, TLS on (its default)                                  | 1.09 / 1.64            | 2001.5                | 10.50            | ~390                    |
| frp, WebSocket transport                                              | 1.08 / 1.75            | 2001.5                | 11.09            | ~255                    |
| Python asyncio reverse relay (node dials out; one stream, no framing) | 1.25 / 1.53            | 2001.5                | 10.47            | ~1,980                  |
| WireGuard, two netns on one kernel (MTU 1420)                         | 0.74 / 0.82            | 2000.9                | 10.37            | ~64 (iperf3 538 Mbit/s) |

**What it says:**
- **No hop hurts token streaming.** Every path holds the 2.0 s total. A hop
  adds 0.4 to 1 ms to the time to first token, and about 0.1 ms to the worst
  gap between tokens.
- **On a real remote node, the WAN round trip dominates**: 10-60 ms at home,
  more through a relay. That figure is estimated, not measured; there is no
  second site here.
- **Python can carry a tunnel's bytes.** A plain asyncio relay moved about
  2 GB/s, far above any home upload. Framing and per-stream flow control will
  cost some of that, but not two orders of magnitude.
- **The WireGuard figure is a worst case.** Both ends encrypt on one kernel, so
  it is not a two-host rate.
- **Windows Defender quarantined `frps.exe` as `Trojan:Win32/Kepavll!rfn` the
  moment it was unzipped.** This counts against shipping frp to a Windows
  root. The measurement ran frps in WSL instead, with the Windows side as an
  frp visitor.

**Not measured:**
- Tailscale or Headscale. Joining a tailnet needs an account, which is
  outward-facing and was not done.
- DERP.
- Any path with real WAN latency or loss.

---

### B.5 A node-held tunnel in the agent

If a real install cannot or will not use a mesh, this is the option that needs
no account and no port on any node. The shape below follows the prior art in
Appendix C: Rancher's remotedialer, Kubernetes Konnectivity, Teleport's reverse
tunnel, Tailscale DERP, and the yamux and chisel designs.

- **Agent to agent only.** A remote node's agent holds one WSS connection to a
  *hub*: the agent on the gateway's host, normally the control host. Gateway and
  control never see the tunnel. For a tunnelled node, the hub serves a
  loopback relay URL, `…/v1/relay/<node>/<port>/…`, and they dial that. The
  tunnel stays inside one component, so "components share schemas, not code"
  holds. It is the existing `node:<name>` hop with a second transport.
- **The hub is a byte relay, not an authority.**
  - Tokens stay end-to-end: addressed to `node:X` and verified at X, exactly
    as today. The hub checks only that a caller's token names X before
    forwarding.
  - The node allowlists what may be opened: its agent, its drivers, its
    tool-drivers. Engines stay on loopback and off the list.
  - **The root computes the relay URL itself and never takes one from the
    node.**
- **The handshake is signed by the node's identity key** (the key that already
  signs announcements), over a fresh server nonce bound to the TLS session.
  Revocation removes the key from the bundle and closes the tunnel.
- **The frames are what the prior art converged on.**
  - `stream_id` + type + length.
  - Frame types OPEN, DATA, END, RST, WINDOW, PING, DRAIN and RESTARTING.
  - **Credit windows per stream**, so one large transfer cannot stall a token
    stream. Konnectivity #881 was exactly that stall.
  - Bulk copies never share the link with inference.
  - Keepalives under 25 s, for proxies.
  - Jittered reconnect.
- **The root must be reachable on 443.** That means a port forward plus the
  entry point's nodes name, which the existing Caddy setup already provides.
  Behind CGNAT it needs a relay in front: Cloudflare (WebSocket),
  Tailscale Funnel, or a VPS. Tailscale has no such limit.
- **Degraded mode.** A dropped tunnel is a node *unreachable: its tunnel to the
  hub closed at T (reason)*. In-flight streams fail as a backend failure before
  the first token (cascade) and truncate after it, which is R2.5's rule
  unchanged.
- **A middle step to consider before building transport:** the agent
  supervises an unmodified `tailscaled` (userspace mode, BSD-3), the same way it
  supervises Caddy, and the operator pastes an auth key once. It is the biggest
  cut in steps that keeps the mesh commitment (moot under the no-cloud rule). Tailscale's provisioning
  for third-party apps is alpha and single-tailnet, so the key is pasted, not
  minted for the user.

---

## Appendix C. Sources (fetched 2026-10-05)

**Tailscale.**
- v1.102.5, 2026-09-29, BSD-3 client: https://github.com/tailscale/tailscale
- Pricing: https://tailscale.com/pricing
- Ports and DERP: https://tailscale.com/kb/1082/firewall-ports, https://tailscale.com/kb/1232/derp-servers, https://tailscale.com/blog/how-nat-traversal-works
- The DERP proxy path in source: `derp/derphttp/derphttp_client.go`, `net/tshttpproxy/tshttpproxy_windows.go`
- Connection types: https://tailscale.com/docs/reference/connection-types
- Peer relays: https://tailscale.com/docs/features/peer-relay
- Auth keys and tags: https://tailscale.com/kb/1085/auth-keys, https://tailscale.com/kb/1068/tags
- Default allow-all policy: https://tailscale.com/kb/1192/acl-samples
- Unattended Windows: https://tailscale.com/kb/1088/run-unattended
- Coordination server down: https://tailscale.com/docs/reference/coordination-server-down
- Status history: https://status.tailscale.com/history
- Funnel: https://tailscale.com/kb/1223/funnel
- OAuth device provisioning (alpha, single tailnet): https://tailscale.com/docs/features/oauth-apps/device-provisioning
- Issues: #14661, #18017 (DERP throughput); #17698, #20801 (proxies); #18827, #18483 (serve streaming)

**Headscale.**
- v0.29.4, BSD-3: https://github.com/juanfont/headscale
- DERP and registration docs: `docs/ref/derp.md`, `docs/ref/registration.md`

**WireGuard.**
- https://www.wireguard.com/known-limitations/ (no TCP)
- https://www.wireguard.com/quickstart/

**ZeroTier.**
- 1.16.0 licence change: https://github.com/zerotier/ZeroTierOne/blob/dev/RELEASE-NOTES.md
- Pricing: https://www.zerotier.com/pricing/
- TCP relay: https://docs.zerotier.com/relay

**NetBird.**
- v0.80.0, BSD-3 client / AGPL server: https://github.com/netbirdio/netbird/blob/main/LICENSE
- Pricing: https://netbird.io/pricing
- Ports: https://docs.netbird.io/about-netbird/ports-and-firewalls
- Issues: #6021, #5798

**Nebula.**
- v1.11.2, MIT: https://github.com/slackhq/nebula
- Issue #1001 (no TCP)

**Cloudflare.**
- Ports (7844): https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/
- Proxy (#1076): https://github.com/cloudflare/cloudflared/issues/1076
- Buffering and SSE: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/
- 125 s / error 524: https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/
- Connection limits: https://developers.cloudflare.com/fundamentals/reference/connection-limits/
- Service tokens: https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- Mesh: https://blog.cloudflare.com/mesh/

**Reverse tunnels.**
- frp v0.71.0: https://github.com/fatedier/frp
- rathole: https://github.com/rapiz1/rathole
- ngrok free plan limits: https://ngrok.com/docs/pricing-limits/free-plan-limits/
- ngrok TCP endpoints: https://ngrok.com/docs/universal-gateway/tcp/
- OpenSSH on Windows: https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-overview

**IPv6 and certificates.**
- https://stats.labs.apnic.net/ipv6/XA
- Google's IPv6 statistics
- RFC 6092
- Let's Encrypt ending client authentication: https://letsencrypt.org/2025/05/14/ending-tls-client-authentication

**Prior art.**
- https://github.com/rancher/remotedialer
- https://github.com/kubernetes-sigs/apiserver-network-proxy (#881, #180)
- https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/1281-network-proxy
- Teleport RFD 69: https://github.com/gravitational/teleport/blob/master/rfd/0069-proxy-peering.md
- Tailscale `derp/derp.go`
- https://github.com/jpillora/chisel
- https://github.com/hashicorp/yamux/blob/master/spec.md
- https://github.com/erebe/wstunnel
- `websockets` keepalive, memory and proxies: https://websockets.readthedocs.io/en/stable/topics/

**Windows MCP.**
- Insider build 26220.7344 (MCP, the on-device registry, the File Explorer and Settings connectors): https://blogs.windows.com/windows-insider/2025/12/05/announcing-windows-11-insider-preview-build-26220-7344-dev-beta-channels/
