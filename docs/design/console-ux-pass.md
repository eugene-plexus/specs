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

## Open call

- **CX-C1: Machines or nodes.** The menu says Machines; that page says "Add
  a node" and "No nodes are enrolled" (`ui/src/app/nodes/page.tsx:533,771`),
  and the picker, Library, Backends, glossary and guide say node. Open since
  the console copy pass of 2026-10-10. CX1 leaves the wording alone until
  Troy picks one.

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

### CX3: one-click run asks first (agent, ui; M)

*Confirmed in part.* "Download and run" asks whether to install the engine
only after the download (`agent/src/eugene_plexus_agent/run_worker.py:186`,
step `awaiting-install` after `checking`), so a person who walked away from
a long download comes back to a question, not a running model. Escape on
the dialog cancels the whole run (`ui/src/components/RunDialog.tsx:19,47`).
Decide the engine at the click (the button already says "We'll ask before
installing llama.cpp"), and let Escape only close the dialog.

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
