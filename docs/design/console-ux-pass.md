# Console experience pass (CX)

Troy, 2026-10-20: find places to improve the user experience in Eugene,
not Workbench (Workbench gets its own pass). Three read-only audits found
them: the path from install to a model answering, the pages used once it
runs, and the evidence already on file (issues, the website's guides, the
setups gap review). No GitHub issue was about user experience.

Every finding is a code read. Items marked *confirmed* were re-read in the
main session. None has been reproduced in a browser yet, so each slice
starts with a check that fails before the fix.

Left out:
- **Promoting the standby from the console.** Troy wants the standby to
  take over automatically, which is its own complicated slice: see
  "Not scheduled without Troy" in [`audience-roadmap.md`](audience-roadmap.md).
- **Connecting Codex and Claude Code** is the "Connect an app on this
  machine" candidate already on the roadmap.
- **Hardware health, vLLM from its Docker image, Prometheus, and one model
  across machines** belong to Troy's setups review.
- **Operations rights for people other than the owner** break "no role sees
  everything" today, but are a feature, not a fix.

## Calls

- **CX-C1: Machines or nodes. Taken: Machines** (Troy, 2026-10-20). The menu
  said Machines; that page said "Add a node" and "No nodes are enrolled"
  (`ui/src/app/nodes/page.tsx:533,771`), and the picker, Library, Backends,
  glossary and guide said node. Every word a person reads in the console
  says machine. "Node" stays where it is an identifier (`node:<name>`
  targets, API paths, `ComponentKind`, the `/nodes` route) and as the
  expert term in the glossary and tooltips. The website's guides follow in
  its next batch.

## The slices

Ordered by value for the effort. CX1 is routine Edge work; CX2 and CX6 are
high risk (sign-in, enrollment, revoking a machine's key) and get one
adversarial review and a real-environment run.

### CX1: quick fixes (ui; S)

1. **Saving library folders scans them.** *Confirmed.* Saving PATCHes
   `modelRoots` and never scans (`ui/src/components/LibraryFolders.tsx:231`),
   then says "Folders saved, and this machine has read them"
   (`ui/src/lib/stalePaths.ts:70`). Home goes on offering a 16 GB download
   to someone whose folder is full of models; setup's own Finish scans for
   exactly this reason (`ui/src/app/setup/page.tsx:452-469`). Scan after a
   save and say "Found N models". The Library's empty state also offers
   Discover, not only Library folders.
2. **Apps keeps a machine that does not answer.** *Confirmed.* Each
   machine's `/v1/apps` failure becomes an empty list
   (`ui/src/app/apps/page.tsx:99`), so its apps look uninstalled. Keep the
   group and say "<machine> did not answer: <reason>".
3. **Engine rows say what happened in a sentence.** Inference shows the raw
   status (`crashed`, `exited`) with the explanation in a hover tooltip only
   (`ui/src/app/inference/page.tsx:115-123,842`), in words like "readiness
   probe" and "not routable"; phones cannot hover. One plain sentence on the
   row with the observed cause and a Try again / Logs action.
4. **A missing engine is one button.** "{engine} is not installed on this
   machine… Open Engines below to install it, then press start"
   (`inference/page.tsx:863-867`) becomes "Install {engine} and start", on
   one-click run's install-then-launch path.
5. **Discover points at its own machine picker.** "Open Discover from that
   node's address" (`ui/src/app/discover/page.tsx:943-950`) breaks one
   console; the page already has a picker.
6. **Discover's starter set runs, too.** Its button only downloads
   (`ui/src/components/StarterSetPanel.tsx:172`); Home's same card is
   "Download and run".
7. **The add-backend page links what it names.** "under Settings"
   (`ui/src/app/backends/add/page.tsx:295,312,320`) links to that driver's
   settings, and the done state offers Try it in the Playground.
8. **Wording slips:**
   - the People and access tab title reads "People and access ? Eugene
     Plexus" (`ui/src/app/administration/page.tsx:67`, *confirmed*);
   - Recent requests show a person's raw ID (`metrics/page.tsx:1174`);
   - Metrics says "turn on … and restart the gateway"
     (`metrics/page.tsx:584-589`) though saving restarts it;
   - "tokens/s" in `ProfileBenchmark.tsx` where everything else says tok/s.

**Built 2026-10-20** (ui `d3123b4`, shipped to Edge). What building found:

- Saving folders waits up to 20 s for the scan it starts (a 409 means one is
  already running, and is waited on the same way), then says "Found N
  models, M of them new", or that the scan is still going, failed or was
  cancelled. It never claims a count for an unfinished scan.
- Apps did not group by machine: it is one flat list. A machine that does
  not answer now gets its own line under the list with the reason, and the
  empty state says "on the machines that answered".
- The engine row's sentence covers `starting`, `exited` and `crashed` only;
  loading, copying and a stop reason already had their own lines. Try again
  starts the runtime. The tooltip words were made plain too ("readiness
  probe", "not routable" are gone from the page).
- "Install and start" is a browser-side install-then-start: it installs
  through that machine's agent, follows the install, then starts the
  runtime. The run worker's path was not reused, because it creates a new
  runtime from a model and this row already has one. Leaving the page
  during the install loses only the start; the install goes on, and the row
  then offers Start. An engine that cannot be installed keeps the sentence
  pointing at Engines below.
- Discover's starter pick reads "Download and run · N GB" and goes through
  the same durable run operation as Home's card; "Download only" sits
  beside it. The list's small "download" buttons still only download.
- Metrics reads the people list to name a person; only the owner and
  directory administrators may read it, so anyone else still sees the ID.

### CX2: setup resumes where it stopped (ui, agent; M; high risk)

*Confirmed.* Screen 1's Continue makes several writes: the agent's
passphrase, then control root setup, enrollment and the security mode
(`setup/page.tsx:336-421`). Only the first is irreversible. When a later one
fails, the next visit sees `initialized` and opens screen 2
(`setup/page.tsx:229-259`), so the failed steps never run again. The control
root's error sends the person to Home, and Home's gate sends them back to
setup. Finish can then leave an install whose control root has no
passphrase. Choose the screen from each step's own state, resume from the
first step not done, and give the error a Retry for that step. Cancel on
screen 1 also loops (`setup/page.tsx:315-325`).

**Design (2026-10-20).** No new endpoint: each step already says whether it
is done.

| Step                  | Done when                                                         | Read with                                         |
| --------------------- | ----------------------------------------------------------------- | ------------------------------------------------- |
| Agent's passphrase    | `initialized`                                                     | agent `GET /v1/auth/status` (no session)          |
| Components            | control, gateway and library declared                             | agent `GET /v1/components`; read-only, always run |
| Control root's        | `initialized`                                                     | control `GET /v1/auth/status` through the proxy   |
| Enrollment            | `enrolled`                                                        | agent `GET /v1/node`                              |
| Security mode         | agent and control agree, and agree with a choice this tab made    | both `GET /v1/config`, read only once enrolled    |
| Folders (screen 2)    | `firstRunComplete`                                                | agent `GET /v1/config`                            |

Which screen opens:

- Not initialized: screen 1 as now.
- Initialized, no session in this tab: **screen 1 in its resume form**,
  which asks the passphrase once ("Your passphrase is set. Type it to
  carry on setting up."). Continue signs in at the agent, then reads the
  states and goes on. This replaces the bounce to `/login`, so a person
  who comes back later types their passphrase once, not twice.
- Initialized with a session: read the states. Anything up to the security
  mode left opens the resume form, saying what is left in words ("Securing
  the install", "Joining this machine"); the machine-name box shows only
  while enrollment is left, and the reboot choice shows prefilled from the
  agent's own `securityMode`. Nothing left opens screen 2;
  `firstRunComplete` opens Home, as now.
- A state that cannot be read (the root not answering) counts as not done:
  running its step then reports the real error, in its own words.

**The passphrase on a resume.** The control root's `POST /v1/auth/initialize`
takes whatever it is given and has no reset, so a mistyped passphrase sent
there would lock the root to the typo. A resume therefore **always signs in
at the agent with the typed passphrase first** (`POST agent
/v1/auth/login`), and only after a 200 sends it to the root. The agent is
not enrolled at that point (enrollment is after the root), so it checks its
own hash; its rate limit (5 tries in 60 s) applies. The first run needs no
extra check: the root gets the passphrase the agent accepted moments
before in the same click. The passphrase stays in component state only,
kept across a failure so Try again needs no retyping, and is cleared when
the steps finish. The security mode alone needs no passphrase: the session
writes it.

**Try again and Cancel.** A failure after the agent's passphrase is set
keeps the page on screen 1, switched to the resume form with the passphrase
still held, and the button reads Try again. Try again re-reads every state
and runs from the first step not done, so a step whose answer was lost
(the root took the passphrase but the reply did not arrive) is not run
twice. The root's error no longer tells the person not to run setup again
or to open Home. **Cancel goes:** before Continue nothing has been written,
and every page's gate sends an install without setup back here, so there is
nowhere for Cancel to go; closing the tab is the cancel. A resume has
nothing to undo either.

What this does not change: a root with no passphrase takes the first
`initialize` that passes its trusted-host check (`trusted_host.py`), as
before. Resuming shortens that window; closing it is not this slice.

**Built 2026-10-20** (ui `26f67f6`, on Edge with specs `95b2c0d`). One
adversarial review: no blocker; seven findings fixed. Its real-environment
run, `scripts/cx2-setup-resume-acceptance.py`, is written and waits for the
end of the pass (Troy). What building found:

- Every read of the root, and the root sign-in inside enrollment, carries
  the session as an explicit `bearer`. Without it, the api client took the
  root's 401 as a dead session and sent the person to `/login` mid-setup.
  That happens when the root holds a different passphrase (dev-seed, another
  tab), or when a sealed root is read on a finished install. That 401 now
  reads "the control root refused this passphrase, although this machine
  accepted it".
- The restart choice a resume offers is the agent's only when screen 1
  wrote it: the machine has joined and both processes agree, or the agent
  holds something other than its factory default. Otherwise it is the
  host's recommendation. A failure before the mode step leaves the factory
  default behind, and reading that as a choice would quietly drop the
  keyring.
- The progress reads get 30 s, not the status probe's 10 s, because
  `GET /v1/node` reads the host firewall.
- Inputs are disabled while a step runs, so a choice toggled mid-run cannot
  be shown without being applied.
- **CX2-C1: the passphrase once on every path. Taken and built**
  (Troy, 2026-10-20; specs `4d79f06`, agent `56d3dc6`, ui `5a6ee8b2`, on
  Edge with specs `19f781f`). A returning browser met the gate before
  setup, and with no session the gate sent it to `/login`. So a
  half-set-up install asked for the passphrase at sign-in and again on
  setup, because the root still needed it. The agent's open
  `GET /v1/auth/status` now carries `firstRunComplete` once initialized,
  and the gate sends a half-set-up install with no session to `/setup`.
  A finished install with no session that opens `/setup` goes to sign-in.
  An older agent that leaves the field out reads as finished. The status
  route now leaves out fields with no value, as its contract already said
  for `keyringAvailable`.

### CX3: one-click run asks first (library, ui; M)

*Confirmed in part.* "Download and run" asks whether to install the engine
only after the download (`agent/src/eugene_plexus_agent/run_worker.py:186`,
step `awaiting-install` after `checking`), so a person who walked away from
a long download comes back to a question, not a running model. Escape on
the dialog cancels the whole run (`ui/src/components/RunDialog.tsx:19,47`).
Decide the engine at the click (the button already says "We'll ask before
installing llama.cpp"), and let Escape only close the dialog.

**Design (2026-10-20).**

- **Where it is asked.** The download chains only: `startDownloadAndRun`
  (Home's card, Discover's starter, Discover's "Download and run") and
  `startDownloadAndPrepare` (Discover's prepare). Before anything is
  submitted, the store reads the target machine's `GET /v1/engines`. A
  run needs an engine that loads the format (and, for an engine that runs
  only named files, this file); a preparation needs its own engine. If one
  is installed, or none is installable, or the machine does not answer,
  nothing is asked and the run goes as before, so a wrong guess falls back
  to today's question after the download, never to a silent install. If
  the engine is missing and installable, the run dialog asks "Install
  llama.cpp too?" with **Install and run** and **Cancel**. Nothing has been
  submitted, so Cancel and Escape leave nothing behind. A Run or Prepare on
  a model already on disk keeps the question after checking: that takes
  seconds, nobody has walked away.
- **What the operation records.** `Intent.installEngine` (run-operations
  contract, optional): the engine the person agreed to install. The
  **library** honours it: a checkpoint to `awaiting-install` for that
  engine, with no answer yet, is recorded as the answer `install` and the
  step `installing`, the same change `POST /answer` makes. Any other engine
  still waits for an answer: agreeing to llama.cpp is not agreeing to
  whatever checking picks. In the library, not the agent, so an agent of
  any version honours it. The agent is unchanged. An older library refuses
  the field (the intent forbids extras): deploy the root first, as for any
  intent change.
- **Escape only closes.** On a run already waiting for its answer, Escape
  and a new **Later** close the dialog; the run keeps waiting, its tray row
  says "waiting for your answer: install llama.cpp?", and following that row
  (or Home's) opens the question again. **Cancel the run** is its own
  button. Closed questions are remembered per tab; a reload asks again.

Callers checked: Home's card and Discover's starter and model rows reach
`startDownloadAndRun`; Discover's prepare reaches `startDownloadAndPrepare`
(or `startPreparation` when the file is owned); the Library's Prepare and
`RunButton` submit for a model on disk and are unchanged.

**Built 2026-10-20** (library `6f62a81`, agent `40cab45` vendors the
contract, ui `b782ccd9`). What building found:

- The run operation lives in the library, not the agent, so the slice is
  library and ui; the agent's worker needed no change.
- The library treats two submissions with the same intent as one receipt,
  so a retried click with the same agreement is the same operation.
- `run-operations-checks.py` (specs CI, pinned library and agent) now runs
  an agreed install end to end: checking, installing and settings with no
  answer posted.
- ui CI had been red since CX1: the theme-token test read
  `data-testid="status-retry"` as a class. The test now skips test ids.
- Owed for the end of the pass: `scripts/cx3-ask-first-acceptance.py
  --output <new dir>` (Windows; disposable install, the pinned UI wheel,
  downloads a 20 MB GGUF and one llama.cpp build).

### CX4: one context for fit (library, agent, ui; M)

Home judges fit at 16k (`ui/src/app/page.tsx:103`), Discover at 8k
(`discover/page.tsx:246`) and the Library at the library's own guidance
(`library/page.tsx:232`). None of them is the context Run launches with.
One setting, shown beside every verdict, that Run uses; a running model's
Library row says the context it serves. Settings never lie.

**Design (2026-10-20).** No contract change.

- **The one number** is the library's existing `guidanceContextLength`,
  relabelled **Context to plan for**, default raised from 8,192 to 16,384
  (Home's reason for 16k: a model that fits at 8k and not at 16k is one a
  person outgrows in one conversation). An install that set it keeps its
  value. Every fit the library answers without an explicit context is
  already judged at it.
- **Home** drops its own 16k and asks the starter set with no context, so
  the setting applies. **Discover's** control starts from the setting on
  every visit; moving it is a try for this visit only (a stored
  `contextLength` preference is no longer read or written), and the line
  under it says so: "Trying 32k here only: Home, the Library and Run plan
  for 16k." **The Library** already judged at the setting. Home, Discover
  and the Library's fit panel each say "Judged at 16k of conversation, the
  context you plan for. Change", linking to the setting
  (`/config?sel=library#guidanceContextLength`); nothing is shown until the
  library answers, never a number that may not be the one in effect.
- **Run** (the agent's `settings` step, `context_size`): it starts a model
  with the longest context that fits wholly on the GPU, up to the model's
  own, which is at least the planned context whenever the verdict said
  "fits". The gap was the other case: a model that fits wholly only at
  6k, judged "needs partial CPU offload" at 16k, was started at 6k. Now,
  **for llama.cpp, Run never starts below the planned context** (or the
  model's own, if smaller): llama.cpp's own fit puts what the card cannot
  hold in system memory, which is what the verdict said. vLLM cannot
  spill, so it keeps the longest context that fits. The agent reads the
  planned context from the library's fit answer (`fit.contextLength` of a
  fit asked without a context).
- **A running model** says what it serves: the Library's fit panel reads
  "Running on this machine now, serving 32k of conversation" from the
  runtime's `capabilities.contextLength` (the engine's own resolved
  window, per conversation), falling back to the old line until the
  engine reports it.

**CX4-C1 (Troy): Run below the planned context.** Built as: llama.cpp
starts at the planned context with layers in system memory (slower, the
context the verdict promised). The alternative is the old rule, the
longest context that fits wholly on the GPU (faster, less context than
the verdict was judged at), with the served context then the only place
that says so. Recommendation: keep what is built; the verdict and the
running model then agree.

**Built 2026-10-20** (library `ecdfa9f`, agent `85ea7b1`, ui `24311e13`).
What building found:

- The library already judged every fit asked without a context at
  `guidanceContextLength`, so the Library page needed no change to its
  question, only the note and the served context.
- Discover remembered its own context in the browser, a second number
  that outlived any change to the setting. It is no longer read or
  written; a stored value from an older console is ignored.
- The served context is `capabilities.contextLength` (per conversation),
  not `contextPoolTokens` (shared by the slots).
- Not covered by a real run here: a model that fits wholly only below the
  planned context. No model small enough to download fails that way on a
  32 GB card; the agent's unit test covers the rule.
- Owed for the end of the pass: `scripts/cx4-planned-context-acceptance.py
  --output <new dir>`.

### CX5: a Connect apps page (ui; M)

*Confirmed.* The endpoint address and app keys exist only on Home, and only
while a chat model is served (`ui/src/app/page.tsx:266`). Settings links to
`/#use-from-apps`, which is then missing, and Apps links to bare `/`. A
leaked key cannot be revoked while models are stopped. Move the card to a
page under Gateway that always renders; Home keeps a summary; Settings,
Apps and Metrics' per-key usage link to it.

**Design (2026-10-20).**

- **`/connect`, "Connect apps"**, the first page under Gateway (before
  Metrics and Routing): the gateway's address is the front door's own. The
  icon is a plug, and the page belongs to the `gateway` branch in the tree.
- **It always renders the whole card**: address and its live check, model,
  keys (make, limit, turn off) and the per-app recipes. With no chat model
  served, the model row says nothing is running, the recipes carry
  `MODEL_ID`, and one line says so, but the address, its check and every key
  action work. The data is the same as Home's: the agent's node and
  components for the address, the gateway's model list, the root's
  placement for which registry answers. The address guess moves from Home
  into one helper both pages call.
- **Home keeps a summary**, always shown: the address it would hand an app,
  the number of live keys, and "Connect apps →". A Home opened at the old
  `/#use-from-apps` goes to `/connect`.
- **Links:** Settings' "Keys for your apps" topic → `/connect`; Apps and an
  app's own page ("listed on Home") → Connect apps; Metrics' "Usage by
  client key" gains "Manage keys on Connect apps".

**Built 2026-10-20** (ui `d6ef792d`). Its run,
`scripts/cx5-connect-apps-acceptance.py`, is written and waits for the end
of the pass. What building found:

- The card needed no change to work with no model. It already said
  "nothing is running" and kept `MODEL_ID` in the recipes; only its one
  caller hid it. The page adds the plain sentence above it, and a separate
  one when the gateway itself did not answer.
- The address guess and the saved correction's storage key moved to
  `lib/connectApps.ts`, so Home's line and the card show the same address,
  including a correction made on the page.
- Home's line reads the key registry itself for its count. When the
  registry cannot be read it leaves the count out rather than saying "no
  keys".
- Navigation gained a `Plug` icon. Gateway now has three screens, and the
  console fifteen.

### CX6: remove a machine (ui; M; high risk)

*Confirmed.* `DELETE /v1/nodes/{name}` revokes a machine's enrollment, and
no page calls it. A sold or rebuilt box stays down on Machines, Hosts, Logs
and the Apps picker forever. A confirmed "Remove from install" on each row,
offered first when the machine is down, saying it revokes the machine's key.
What becomes of its standby grant, its Job Site links and its local copies
is part of the design.

**What removal already did (read 2026-10-20).** One `revokeNode` entry
drops the node record (its label and grants, the standby grant included),
its declared components and runtimes, and publishes a bundle without its
key, pushed to the machines that remain. Its tokens stop verifying, and
console sessions addressed to it die. Every console list (Machines, Hosts,
Logs, Library, Inference, Discover, the Apps picker) reads control's
`/v1/nodes`, so the machine leaves them all; nothing else keeps it. The
removed agent is not told: it learns at its next trust pull (about once a
minute), takes the bundle, and a standby there stops and deletes its copy
(`standby.reconcile`). Its own `/v1/node` still says enrolled. Host history
and local model copies live on that machine's disk and stay there.

**Design (2026-10-20).**

- **Who may remove: the `membership` capability**, which the route already
  requires (the same one that mints join tokens and gives the standby
  grant). The console has no capability read, so the button shows to the
  signed-in operator and a refusal (403) is shown in the root's words.
- **Refused at the root, not only hidden (409, nothing changes):**
  - *the root's own machine*, by `node_name` or the probe's
    `hostsControl` (the standby route's rule). Its key leaving the bundle
    would end the root's own agent and every console session on it, and
    it could not re-join the root it runs;
  - *the last machine that reports a running gateway*, asked live from
    every machine's `/v1/components` (placement is live, not in the log).
    A machine that does not answer reports nothing, so **a dead or sold box
    can always be removed**. "Run a gateway on another machine first."
- **The button:** "Remove from install" in each row's Status cell, on every
  machine but the root's. On a down machine it is a plain button; on a
  running one a quiet link. The confirm ("Remove and revoke its key") says:
  its key is revoked now; to come back it must join again with a new
  token; and only when true: it is running now (its programs keep running
  on it, this install stops sending it work); it is the standby (no standby
  until you choose another; it deletes its copy when it next checks in);
  it hosts a person's job site (the site stays; remove it on Job Sites).
  Model files on its disk stay.
- **Job Site links:** a site the machine hosted keeps its own enrollment
  and loses its `hostNode`, so Machines and Job Sites stop naming a
  machine the install does not have. `_without_node` clears it, inside the
  same entry, so a replica applies it the same way.
- **Local copies and host history:** untouched, on that machine's disk.
  Nothing in control or the library records them per machine.
- **A running machine that is removed** keeps running what it runs, as a
  standalone box that no other machine trusts. Re-joining is the agent's
  leave (`POST /v1/node/unenroll`) and a new join token.

Not in this slice: telling the removed agent at once (it hears within a
minute), and a removed machine's own console saying "removed" (its
`/v1/node` still says enrolled). A library run job assigned to a removed
machine waits until someone cancels it (library#14).

**Built 2026-10-20** (control `2d153b4`, ui `5dd65fbe`; the 409 wording in
`control.yaml`). Its run, `scripts/cx6-remove-machine-acceptance.py`, is
written and waits for the end of the pass. What building and the review
found:

- **The root's machine is known three ways, and any one refuses.** The
  review showed `node_name` can be unset (a root started before its
  machine enrolled) or name the standby (`_local_node_name` takes the
  first `control` *or* `standby` record), and a probe says nothing while
  the root's agent restarts. The record's `role == control` covers both;
  `node_name` counts only when it does not name a `standby` record.
- **Only a gateway that is `running` or `starting` counts**, on both sides:
  a crashed second gateway does not let the only working one go, and a
  machine whose own gateway is stopped can be removed.
- **Removals run one at a time** (an `asyncio.Lock` around the check and
  the entry), so two at once cannot each count the other's gateway.
- **A removed standby does delete its copy:** `/v1/trust/bundle` on the
  LAN needs no credential, the revoked agent keeps pulling it, its grants
  come back empty, and `standby.reconcile` stops the standby and deletes
  `standby-state/`. A box that never comes back keeps its copy on its disk
  (outside what code can reach).
- **Mixed versions:** clearing `hostNode` changes how `revokeNode` applies.
  A standby on older code than its root keeps the stale `hostNode` until it
  is updated. Display only; nothing is authorized by it.
- The acceptance script cannot exercise "The only gateway" (its harness
  runs no real gateway); the unit tests cover it.

### CX7: saves that restart say so (ui; M)

A save whose patch needs a restart restarts at once
(`ui/src/components/ConfigEditor.tsx:424-431`), cutting every app's stream,
with only a small badge as warning. Save all awaits each save but not its
restart (`ui/src/app/config/page.tsx:309-316`), so a second gateway section
can PATCH a process on its way out. Label the button "Save and restart the
gateway", and in Save all restart each component once, after its last save.

**Design (2026-10-20).**

- **Which saves restart comes from the schema**, not a list in the UI:
  each field's `requiresRestart` (`common.yaml`). No contract change.
- **The button says it before the click**, for every component and app,
  not only the gateway: "Save and restart" while an unsaved field needs a
  restart, else "Save". Beside it one line: "Restarts {name}." The gateway
  adds "Answers that apps are reading stop.", since its restart is the one
  that cuts apps mid-answer. No extra confirm: the label is the warning,
  and a second click on every save would be noise.
- **Save all restarts each process once.** Sections of one process (same
  target and config path) are saved in turn with the restart held back.
  After the last one, the last section that needed a restart runs it (its
  progress dialog shows), and the others read their values again. The bar
  reads "Save all and restart" and names what restarts ("Restarts Gateway,
  once each, after its last save").
- **One section fails:** it keeps its draft and its error; the others still
  save; the process still restarts for what was saved, so nothing reads
  "Restart needed" for ever.
- **While it restarts** the existing progress dialog shows; it closes itself
  when the process is back. If the process does not come back, the other
  sections are not read again and keep "Restart needed", which is true.

**Built 2026-10-20** (ui `71635b19`). Its run,
`scripts/cx7-save-restart-acceptance.py`, is written and waits for the end
of the pass. What building found:

- Each section restarted its process from inside its own save, and the
  read-back that followed raced the restart. Save all now passes
  `deferRestart`; a single section's own Save restarts at once as before.
- A refused value has to outlive a restart run by another section: each
  section keeps what its deferred save refused and puts it back after.
- The type check caught the Save button passing its click event in as the
  save's options; it now calls `save()` with none.

### CX8: failures link to their logs (ui; S-M)

Only Inference links into Logs (`ui/src/lib/logs.ts:141`). Metrics' failed
tries, a down machine's error, a failed app and a silent host show the
error with no way to its log, and Logs reads only `?source=`, so no link can
open it on a request ID (`ui/src/components/LogsView.tsx:53-58`). Add `?q=`,
then "Logs →" beside each failure. With it, Routing waits after Save until
the gateway's `refreshed_at` passes the save before showing what a name
resolves to (`ui/src/app/routing/page.tsx:155,501`), and says why a
candidate is not ready.

**Design (2026-10-20).**

- **`/logs?q=<text>`** fills "Only lines containing" and asks each agent
  for only those lines (`contains=`), as typing does. A `q` that finds
  nothing gets the existing "No line contains “…”." and Clear.
- **One link helper, `logsHref({node, source, q})`.** No `node` means
  every machine on one timeline, which suits a request's id (unique, and
  the gateway may be anywhere) and a machine's name. Every link goes
  through the console (one console).
- **"Logs →" beside each failure:**
  - Metrics: a request with a failed try or an error outcome →
    `/logs?q=<request id>`. The gateway's failover warning did not carry
    the id, so it now ends "(request <id>)" (gateway); the id is the one
    Metrics shows.
  - Machines (a down machine's error) and Hosts (a machine not answering)
    → `/logs?q=<machine name>`: its own log cannot be read while it is
    down, and the root's probe lines name it.
  - An app's last error → its machine, source `app: <id>`; a failed
    install → its machine, `q=<id>`.
- **Routing.** The planned wait for `refreshed_at` is dropped: the gateway
  reads `modelSlots` on every request (`routing.py`, "read live on every
  resolve"), so the table read right after Save already resolves with the
  new lists. The saved line said "reads the lists on its next routing
  refresh", which was false; it now says "Saved. The gateway uses these
  lists now". The refresh only changes *which backends are up*, and the
  page already says "as of" its time.
- **Why a candidate is not ready**, one word each, after "x of y ready":
  the runtime's status (`loading`, `stopped`, `crashed`…), "stopping"
  for the gateway's "is being stopped", else "not ready". No sentence
  from the gateway, no internals.

**Built 2026-10-20** (ui `e28168fb`, gateway `6a614a2`). Its run,
`scripts/cx8-logs-links-acceptance.py`, is written and waits for the end of
the pass. What building found:

- The routing wait in the audit rested on the saved line's own claim. The
  code reads the lists live, so the fix was the sentence, not a wait.
- CX7 renamed Save to "Save and restart" on fields that need it, and the
  app settings test still pressed "Save": CX7's ui CI is red until the
  follow-up commit lands with CX8. The full ui suite now runs before a
  ship that renames a shared control.

### CX9: models already in Ollama (library; L; design first)

Most hobbyists arrive with models pulled by Ollama, which keeps them as
hash-named blobs the Library does not read
(`website/src/content/guides/bring-your-own-models.md:31`;
`library-sources-and-engines.md:794`; hobbyist-ux.md calls them "held
hostage"). They download them again. Read Ollama's manifests so its models
appear in the Library without a copy, as their own source. Check Ollama's
tracker for manifest-format changes first.
