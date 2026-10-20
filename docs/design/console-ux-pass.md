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

### CX4: one context for fit (ui, maybe library; M)

Home judges fit at 16k (`ui/src/app/page.tsx:103`), Discover at 8k
(`discover/page.tsx:246`) and the Library at the library's own guidance
(`library/page.tsx:232`). None of them is the context Run launches with.
One setting, shown beside every verdict, that Run uses; a running model's
Library row says the context it serves. Settings never lie.

### CX5: a Connect apps page (ui; M)

*Confirmed.* The endpoint address and app keys exist only on Home, and only
while a chat model is served (`ui/src/app/page.tsx:266`). Settings links to
`/#use-from-apps`, which is then missing, and Apps links to bare `/`. A
leaked key cannot be revoked while models are stopped. Move the card to a
page under Gateway that always renders; Home keeps a summary; Settings,
Apps and Metrics' per-key usage link to it.

### CX6: remove a machine (ui; M; high risk)

*Confirmed.* `DELETE /v1/nodes/{name}` revokes a machine's enrollment, and
no page calls it. A sold or rebuilt box stays down on Machines, Hosts, Logs
and the Apps picker forever. A confirmed "Remove from install" on each row,
offered first when the machine is down, saying it revokes the machine's key.
What becomes of its standby grant, its Job Site links and its local copies
is part of the design.

### CX7: saves that restart say so (ui; M)

A save whose patch needs a restart restarts at once
(`ui/src/components/ConfigEditor.tsx:424-431`), cutting every app's stream,
with only a small badge as warning. Save all awaits each save but not its
restart (`ui/src/app/config/page.tsx:309-316`), so a second gateway section
can PATCH a process on its way out. Label the button "Save and restart the
gateway", and in Save all restart each component once, after its last save.

### CX8: failures link to their logs (ui; S-M)

Only Inference links into Logs (`ui/src/lib/logs.ts:141`). Metrics' failed
tries, a down machine's error, a failed app and a silent host show the
error with no way to its log, and Logs reads only `?source=`, so no link can
open it on a request ID (`ui/src/components/LogsView.tsx:53-58`). Add `?q=`,
then "Logs →" beside each failure. With it, Routing waits after Save until
the gateway's `refreshed_at` passes the save before showing what a name
resolves to (`ui/src/app/routing/page.tsx:155,501`), and says why a
candidate is not ready.

### CX9: models already in Ollama (library; L; design first)

Most hobbyists arrive with models pulled by Ollama, which keeps them as
hash-named blobs the Library does not read
(`website/src/content/guides/bring-your-own-models.md:31`;
`library-sources-and-engines.md:794`; hobbyist-ux.md calls them "held
hostage"). They download them again. Read Ollama's manifests so its models
appear in the Library without a copy, as their own source. Check Ollama's
tracker for manifest-format changes first.
