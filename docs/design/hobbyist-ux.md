# The weekend hobbyist: UX research and a plan (design)

**Status:** researched and designed 2026-09-15, on Troy's brief, ahead of
the release (`install-paths-and-distribution.md` §9, whose step 9 was deleted on
2026-09-18 — it stays
last). **All fourteen decisions were taken by Troy the same day**, in
two rounds; #4 on one condition, which §6.5 turns into a process, #6
amended to ask first, #12 on the condition that the jargon stays
available in hints, and #8 with a question that §6.6 answers. Only the
relabels (`Backends`, `Chat`) remain a separate open call.
**S0 through S7 are built and live-verified (S0-S5 on 2026-09-15, S6 and S7 on
2026-09-16; records in §11).** S7's measurement falsified four of its seven
issue kinds, the one contract field it needed is landed and served, and the
whole UI half shipped and was pinned; §11.9 is the record. **(This header said
PAUSED until 2026-09-17, in three places, while §11.9's own body said DONE —
the status line is what nobody updates.)**
**S10 is BUILT and GREEN ON BOTH TARGETS** (§11.10 Windows, §11.11 WSL2) — the budget is
measured on Windows and on WSL2, and each run found a defect that had
shipped: a fix that was on `main` and in no build, and a refusal that
rested on an upstream fact which had changed. **What the *Done when*
still lacks is `EP_DOWNLOAD=1` for the ten-minute target and the moderated
sessions (§8.4), so the release gate is not met** — **▶ AND SINCE 2026-09-17 ELEVEN HIGH
FINDINGS SIT IN FRONT OF THAT GATE — six slices before any public link and five
more before the first hostile review — FOUR OF THEM DEFECTS IN THE GOLDEN PATH
THIS DOCUMENT DESIGNED AND RECORDED AS BUILT.** The pre-release
adversarial review (`docs/private/adversarial-review-2026-09-17.md`; order of
work in [`release-roadmap.md`](release-roadmap.md)) found: **the recommended
model is scored one way before download and another after, and the second is
the one one-click Run uses** (§6 #4 — Home says *fits at 16,384*, the profile
is written at ~4,864); **a taken port dead-ends the wizard at 8083 and produces
a silently useless install at 8080, with an empty Needs-attention card because
no `IssueKind` covers a component that is down** (§6 #7); **a Windows AMD or
Intel owner gets a CPU-only llama.cpp silently and is then offered the SMALLEST
starter model** (§6 #11); and **the wizard's own reboot promise is false on the
default Windows install** (§6 #26). Two more land on exactly this audience: a
slow-but-healthy CPU answer reported as *"Every backend serving this model
failed"* after 240 s with the prompt computed twice (§6 #13), and an 8 GB
laptop — the beginner thread's OP — against which **the starter set has never
been scored** (§4.2 #6). **S8 completed 2026-09-20** — glossary, Config's Show more,
expanded copy checks, and a Hemingway Grade 6 pass; UI `48488ad`, dist `ad6836f`.
[Acceptance record](../acceptance/s8-vocabulary-run.md). **S9 is not started.** Every claim marked
*measured* was checked against a file or a running process on the day of
writing. Research claims cite a URL in Appendix A; **(F)** means the page
was opened and read, **(S)** means a search snippet only. §0 is the
measurement, §7 the plan, §8 how we will know it worked.

**Troy's words, which are the brief:**

> Before we do [the release], I would like to do serious research on UX
> and UI design, and to devise a plan to make the project's UI interface
> as easy as possible. We want the operation of Eugene to be simple
> enough for a weekend hobbyist to set it up and use it.

**In one line.** The system underneath is right for the hobbyist — their
own files, a detected fit, one endpoint — and the surface on top is
written for an operator. First chat is **15 clicks, 6 route changes and
one hand-typed filesystem path** after install, the first thing a new
user sees is **a disabled text box**, and every product hobbyists call
easy gets there in one to three steps. The fix is not a redesign of the
tree or the screens; it is a **Home**, a shorter wizard, three
"do it for me" defaults on the golden path, and a vocabulary pass.

---

## Decisions

| #      | The call                                                                                                            | §        | Recommendation                                                                                                                                                                   | Status       |
| ------ | ------------------------------------------------------------------------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| **1**  | What the browser lands on after sign-in                                                                             | §6.1     | **Home** — a task-shaped page on the install root: get a model, try it, connect an app, reach it from other devices, what is running, what needs attention. The Playground becomes one of its pages | **taken 2026-09-15 (Troy)** — **built, §11.2** |
| **2**  | The wizard shrinks to two screens, and Browse arrives in it                                                         | §6.2     | Yes. Passphrase, then "where should models live?" with a picker. Backend and Welcome leave; the install is enrolled on screen 1's Continue so screen 2 can browse                    | **taken 2026-09-15 (Troy): two screens** — **built, §11.3** |
| **3**  | A proposed default models folder beside Browse                                                                      | §6.2     | Yes — a plain folder under the user's home, created on first download, files plainly named. A folder the user can see is not a managed store; differentiator #3 is about renaming and hiding, not about who created the directory | **taken 2026-09-15 (Troy)** — **built, §11.3** |
| **4**  | A starter set of models, and one recommended for the detected card, on Home                                         | §6.3     | Yes, as *"the most-downloaded well-known instruct GGUF in the largest size class that fits at 16k"*, shown with why and **Choose another**. M3 said a one-click "get the best one for me" is a fine wizard step and a bad default; Home is that step | **taken 2026-09-15 (Troy), ON CONDITION: an automated pre-release review of the state of local inference that recommends keep or replace — §6.5.** Troy: *"This is something that will quickly grow stale as models continue to improve."* — **built, §11.7**, condition included: `starter-review` ran once end to end against the live hub and the list it produced is what ships |
| **5**  | Launch without a profile                                                                                            | §7 S3    | Yes. Launch creates `default` at the context that fits (already computed) when none exists; the editor stays for experts                                                        | **taken 2026-09-15 (Troy)** — **built, §11.4** |
| **6**  | Engine install happens inside the first Launch, as a task                                                           | §7 S3    | Yes. "No binary — install one from the Inference page" becomes a progress line in the same place the user is looking. Version pinning stays an expert path                     | **taken 2026-09-15 (Troy), AMENDED: ask first.** *"I could not find llama.cpp, would you like me to install it?"*, Yes as the default, with a warning that skipping is for advanced users only — **built, §11.4** |
| **7**  | Long-lived client keys                                                                                              | §7 S4    | Yes: minted by the agent with the install signing key, `aud: client`, one-year default, named, listed, revoked by the existing rotation. **Contract change**                     | **taken 2026-09-15 (Troy)** — **built, §11.5**, with per-key revocation rather than rotation: a Turn-off button that turns nothing off is P4's silent failure |
| **8**  | "Serve to other devices" as one switch                                                                              | §7 S5    | Yes. It sets `advertiseUrl` to a detected LAN address, shows the URL a phone types, and reports what is actually bound. The minimal version is in the release                    | **taken 2026-09-15 (Troy)** — **built, §11.6**. His question — *can we detect the Windows Firewall disposition so we can warn when it is blocking?* — is answered **yes**, and §6.6's reasoning was corrected in four places by measuring it |
| **9**  | Security default on a desktop OS is the keyring, written to **both** agent and control                              | §0.14    | Yes. The wizard's own copy already says the keyring is "best for AI hobbyists" and defaults to the other option. Servers and containers keep `prompt_on_startup` / `passphrase_file` | **taken 2026-09-15 (Troy)** — **built, §11.1** |
| **10** | The tree stays; the machine level appears only once there is more than one machine                                  | §6.4     | Yes. A standalone install today shows four rows reading "This machine". Reverses `ui-tree-navigation.md` §2.3 for the one-machine case only; a second machine restores it       | **taken 2026-09-15 (Troy)** — **built, §11.2** |
| **11** | No global Simple/Advanced switch                                                                                    | §4 P6    | Per-field: a collapsed **Show more** group per page where three or more fields qualify. Home Assistant is deleting its global toggle for the reasons in §2.4                    | **taken 2026-09-15 (Troy)** |
| **12** | Vocabulary                                                                                                          | §7 S8    | Keep the registry's object names; implementation nouns (`companion driver`, `declaration`, `mint`, `epoch`, `advertiseUrl`, `admission`) leave body copy for hover text; a test enforces a banned list on golden-path screens. Relabelling `Inference drivers` → `Backends` and `Playground` → `Chat` is a **separate, smaller call** | **taken 2026-09-15 (Troy), ON CONDITION: the proper jargon stays available in a tooltip or other hint for advanced users.** Relabels remain a separate call |
| **13** | What gates the release                                                                                              | §7       | S0–S6 and the measurement (S10). S7–S9 follow the release                                                                                                                       | **taken 2026-09-15 (Troy)** |
| **14** | Moderated sessions with three to five real hobbyists before release                                                 | §8.4     | Yes. The author's own four days on the live install produced twenty usability incidents (§0.13); strangers will find the ones he cannot                                          | **taken 2026-09-15 (Troy): "2-3 friends for sure"; he is in no hurry to release** |

---

## 0. What measuring found

### 0.1 The user in the documents is an operator

*Measured.* Across the nineteen design docs the word "operator" appears
190 times and is the user's name throughout. Three of the nineteen
mention a hobbyist, enthusiast or beginner at all, and two of those are
quoting the r/LocalLLaMA thread. The UI's own copy says "operator" 84
times and "hobbyist" once — in the wizard's description of the keyring
option (§0.14). The website's glossary has to define **Install, Node,
Component, Runtime, Backend, Replica** before the architecture page
makes sense.

None of this is wrong. It is the vocabulary of the people who built a
cluster manager, and it leaks into every label, tooltip and empty
state. The plan does not rename the architecture; it stops the
architecture from being the copy.

### 0.2 First chat is fifteen clicks away, and the field does it in one to three

*Measured* at desktop width against `ui` `8c1fafa`, counting one pointer
action as a click and one route change as a transition, assuming the
happy path at every step.

| Stage                                           | Clicks | Route changes | Typed                    |
| ----------------------------------------------- | ------ | ------------- | ------------------------ |
| Wizard complete (five screens)                  | 5      | 2             | passphrase ×2, **a path** |
| A download started (Library → Discover → row → download) | 9 | 4          | —                        |
| Launched and routable (open in library → new profile → create → launch) | 13 | 5   | —                        |
| …if llama.cpp is not installed yet (Inference → install → back → reselect) | 17 | 8 | —                        |
| First reply in the playground                   | **15** | **6**         | the message              |
| Base URL and key for an external client (Diagnostic → Direct → Copy → Copy) | **19** | 6 | —                     |

For comparison, install-to-first-chat as documented by each product
(Appendix A.1): Ollama CLI **1** step; Jan **~1** (a default model
downloads itself); `llama.app` **2** commands; Msty **2–3** clicks;
LM Studio **3**; Ollama's desktop app **3**; GPT4All **4**; Open WebUI
**4–5** plus a backend; Unsloth Studio **5–6**; AnythingLLM **7**
screens. Eugene is the long tail of that table, and the only product in
it where a first chat means visiting three different objects in a tree.

### 0.3 The first thing a new user sees is a disabled text box

*Measured.* The wizard's Start redirects to `/`. On a fresh install
nothing is serving, so the page-menu line reads **"No routable models.
See what is serving."**, the body reads **"Send a message to start a
conversation."**, and the composer is `disabled` with the placeholder
**"Waiting…"** (`ChatInput.tsx:130`). Three sentences, each true, none
of which says *download a model*. The link goes to Inference, whose
empty state is a 90-word paragraph beginning "Two ways in."

### 0.4 The wizard asks for the one thing a new user does not have

*Measured.* Screen 3, "Your models", is a text field with the placeholder
`D:\models  or  /home/you/models` and **no Browse** — the `FolderPicker`
exists but is reachable only from `/config` and `/library/folders`. A
hobbyist who has never downloaded a model has no such folder and types
nothing; Discover then refuses the first download with a 409 whose
remedy is "Add one under Config → Library → Model directories
(`modelRoots`)" (`library/downloads.py:158`) — four more clicks, a
different screen, and a typed path after all.

The wizard's five screens carry 112, 186, 65, 56 and ~146 words of
prose. Its progress bar says "Step n of 5". The "Add a backend" screen
serves the user who already runs Ollama, which is not the first-run
user; the Welcome screen serves nobody (`Continue →` is its only
control).

### 0.5 Three concepts stand between a downloaded file and a running model

*Measured.* A finished download offers **open in the library**. There:

1. **An engine.** `canLaunch` requires an installed binary
   (`ProfileEditor.tsx:231`). On a fresh box there is none, and the
   Library says *"…can load this, but no binary is installed. Install
   one from the Inference page."* — a detour of four clicks to another
   object in the tree, then back, then reselect the model.
2. **A profile.** *"Launching from here needs one: a profile is the
   saved engine flags for this file…"* → `new profile` → `create` (the
   context prefills from admission since 2026-09-15; the name prefills
   `default`) → `launch`. Three clicks for a noun the user does not have
   yet.
3. **Where to look.** The launch confirmation says *"Watch it load on
   the Inference page — a large quant takes a while."* The load can be
   four minutes over gigabit (`library-folders-run.md`), and nothing on
   any other screen shows it.

### 0.6 One hundred and twenty terms, eighty-two tooltips, no help

*Measured.* Enumerating every noun and identifier in rendered copy —
labels, buttons, body text, `title` attributes, status values, and the
server-declared config labels the generic editor renders — and
collapsing synonym families gives **120 distinct jargon terms**. The
list runs from `control plane` and `trust root` through `companion
driver`, `admission`, `mint a join token`, `epoch`, `advertiseUrl`,
`KV cache`, `importance-matrix`, `UD-`, `tensor split` to `mmap`. The
site's glossary defines six.

There are **82 `title` tooltips** (eleven on Inference alone, several a
paragraph long), **seven expandable explainers**, **zero links to
documentation**, **zero post-wizard guidance** (no checklist, no next
step, no dismissible hint; `firstRunComplete` is a boolean, not a
progress model), **zero toasts or notifications**, and **no search**
other than the catalogue's. Inline help is the only help, and it is
written in the vocabulary of §0.1.

### 0.7 Background work is invisible from anywhere but its own screen

*Measured.* Downloads are visible in a panel on Discover and Library;
scans on Library; model loads on Inference; engine installs on
Inference; restarts in a modal on Config. Navigate away and the progress
is gone. There is no header indicator of any kind. The longest waits in
the product — a 24 GB download, a four-minute load, an engine install —
are the ones most likely to be watched from the wrong page.

### 0.8 The second job has no path — **CLOSED by S4, 2026-09-15 (§11.5)**

The hobbyist's second job after a first chat is **pointing a tool they
already use at it** — Continue, Cline, Open WebUI, SillyTavern, a coding
harness. *Measured:* the only surface that shows a key is the
playground's Diagnostic panel, 19 clicks in, and the key it shows is the
**14-day operator session token**; `tailnet.md` says plainly *"There is
no long-lived client key yet."* The base URL is a guess labelled as
one, wrong on any port-remapped install. The three things that go wrong
for everyone (§3, #6) — the `/v1` suffix, a key field that must not be
empty, the exact model id — are shown nowhere together.

### 0.9 The third job has no surface at all

The third job is **opening it from the laptop or phone on the couch**.
*Measured:* a single-box install binds loopback until `advertiseUrl` is
set on the agent's Config page, a field whose description is written for
a tailnet deployment. Nothing in the UI says "other devices cannot reach
this yet", proposes the address, or reports what is bound. This is the
largest cluster of GitHub issues across every comparable project (§3,
#2), and the symptom is always the same: *connection refused*, or a
client that shows *no models*.

### 0.10 Config has no notion of importance

*Measured.* Sixteen `ConfigValueType`s render through one editor; every
field in every category has equal weight; the only conditional
visibility is `showWhen`. Categories per component: gateway 6,
library 6, agent 6, control 6, driver 3. Home Assistant's finding
(§2.4) is that a global toggle does not fix this; a per-page **Show
more** does, and `ConfigField.category` already exists to hang it on.
The hobbyist's real defence is different: **if the defaults are right,
they never open Config.** Every slice below that sets a default is a
Config field they will not have to find.

### 0.11 Phone width, focus, motion

*Measured.* **Seven responsive utilities in the whole app** (five `lg:`,
two `sm:`). Library and Discover are fixed two-column grids at every
width; config rows are a fixed `200px_1fr`. The tree drawer engages
below 1024 px, not only at 430 px. Every text field signals focus by a
1 px border colour change with `outline-none`. No
`prefers-reduced-motion` anywhere; the cyberpunk theme's loading pulse
runs regardless. Many sizes are fixed pixels (`text-[10px]`,
`text-[9px]`), so the font-size preference leaves the tree hints,
routing bar, badges and table sub-lines unchanged. 65 ARIA attributes,
one `sr-only` label, no focus trap in either modal.

### 0.12 The browser suite skips the middle of the golden path

*Measured.* 22 Playwright tests in five files walk the wizard, sign-in,
the tree, the diagnostic panel, folders and the login unlock. **None
walks Discover, the Library, profile creation or Launch** — the stages
that cost the clicks in §0.2. The step-count above was measured by
reading code, not by a browser, and a run that changes it has nothing
to assert against yet.

### 0.13 The author's live install is the usability study

*Measured* from `CLAUDE.md` and the acceptance records: between
2026-09-11 and 2026-09-15 Troy, who designed the system, hit at least
twenty distinct usability incidents on the two-machine install. A
selection, each with where it is recorded:

- Could not remove a driver; the endpoint had existed since M0 and the UI never called it.
- Could not tell **which machine** a model directory belonged to.
- A refusal that read *"this component will not invent one"*.
- Clicking Gateway on the worker returned 503; a worker could reach one of four proxy targets.
- Signing in on an enrolled worker bounced into the first-run wizard.
- Asked for the passphrase at sign-in and again on `/nodes`.
- Discover said "no GPU detected" because the library measured the NAS.
- Discover said `fits`, the profile was refused, and neither said the word "context".
- Set an override to `Y:` without ever seeing the folder's Windows-mount box.
- Read the node picker as "which node's models" when it meant "score and launch on".
- Half a second of clock skew read as "down" with no reason given.
- 54 buttons in a wrapping tab strip (the projection that produced the tree).
- The Library was "useless" because the container had no folder a node could reach.
- The container restarted sealed while every health check said `ok`.

He is the most expert user this product will ever have and he had the
architecture diagram in his head. Each incident became a fix within a
day, which is the right loop; the point for this document is the
**rate**. A stranger with a gaming PC will hit the same class of thing
several times a session, will not know it is a bug, and will not file
it.

### 0.14 The security default contradicts its own copy

*Measured.* The wizard's Security screen describes `OS keyring
auto-unlock` as *"Best for: home / personal-use installs, AI hobbyists,
anyone who wants Eugene to auto-recover after a power outage"* — and
defaults to `prompt_on_startup` (`draft.ts:81`). The choice is written
to the agent only; a comment in `setup/page.tsx:300` says control
"declares the same field… but nothing in it reads either", while
`CLAUDE.md` records control's keyring auto-unlock as built 2026-09-10.
One of the two is stale. For a single box the gateway keeps routing this
machine's own drivers when the root comes back sealed
(`routing.py:548`, *measured*), so a reboot does not stop chat — but a
cloud driver's sealed key does not open until someone signs in, and the
tree root reads `control root unreachable` until they do.

---

## 1. Who this is for

Two people, and the second already has a UI.

**Sam — the weekend hobbyist (the brief).** Windows 11 gaming PC, one
NVIDIA card of 12–24 GB, 32–64 GB RAM. **▶ THE FLOOR IS LOWER AND THE VENDOR
IS NOT ALWAYS NVIDIA (2026-09-17):** the beginner thread's OP has a **laptop
4060 with 8 GB of VRAM and 16 GB of RAM**, and *"if hardware limited…"* appears
three times in 41 comments; a Windows **AMD or Intel** owner is a large slice of
the burned-by-Ollama audience and today gets a CPU build silently (review §6
#11). Sam as written excludes both, and every number in this document that was
chosen against a 24 GB card should be re-checked at 8 GB — which is the one
concrete check the review names and nothing has ever run. Has installed Steam, Plex or
Jellyfin, maybe Ollama or LM Studio once. Uses, or wants to use,
Continue or Cline in VS Code, SillyTavern, Open WebUI, or a coding
harness. Has heard "Q4_K_M" and does not know what it means. Does not
know what a bind address, a JWT or a KV cache is and should never need
to. Wants three things, in this order:

1. **A model answering in the browser** from a file on their own disk.
2. **Their tool pointed at it** — base URL, key, done.
3. **The laptop or phone reaching it** from the couch.

And later, maybe, a NAS and a second GPU — at which point Sam becomes
Dana.

**Dana — the homelabber.** Unraid or Proxmox, a NAS, two or three boxes,
a tailnet. Knows what a node is and expects a tree. Dana is who the UI
was built for over the last five days and is well served; nothing here
takes anything from Dana. The measurement in §2.4 is that Sam's tools
and Dana's tools share no landing page anywhere in the field, and that
is the shape to copy: **a Home for Sam, the tree for Dana, one app.**

**Success targets** — these are targets, not measurements; §8 says how
they get measured.

| Job                              | Target after the plan                                          | Today (§0.2)                       |
| -------------------------------- | -------------------------------------------------------------- | ---------------------------------- |
| First reply in the browser       | ≤ 6 clicks, one typed value (the passphrase), no typed path, no docs | 15 clicks, a typed path, 6 routes |
| A tool connected                 | ≤ 3 clicks from Home, a key that outlives the fortnight        | 19 clicks, a 14-day session token  |
| Reachable from another device    | one switch and one URL shown                                   | a config field in a deployment doc |
| Time from install to first token | under ten minutes on a 100 Mbit line for an 8B model, download included | not measured                    |

---

## 2. What the field does

Research gathered 2026-09-15 (Appendix A). The short version.

### 2.1 The patterns every "easy" product shares

1. **A model is proposed, not searched for, on first run** — Jan
   downloads a default; Msty offers one at 1.6 GB; LM Studio shows "Get
   your first LLM"; Ollama's app prompts a pick; `llama.app` shows six
   cards with one-line blurbs.
2. **Fit is shown at discovery time, per quant, in colour or a number** —
   LM Studio's badges, Jan's "fits your hardware", GPT4All's **RAM
   Required** column, Hugging Face's hardware-compatibility panel.
3. **A plain-words rule beside the quant list** — bartowski's "Aim for a
   quant 1–2 GB smaller than your VRAM"; LM Studio's "Choose a 4-bit
   option or higher".
4. **One toggle to become a server, with the warning and the key beside
   it** — LM Studio's *Serve on Local Network*; Jellyfin's *Allow remote
   access*; Plex's *access outside my home*.
5. **One command to wire a coding harness** — `ollama launch claude`
   writes the config; "no environment variables or config files needed".
6. **Discovery before configuration** — Home Assistant's *Discovered*
   list, Portainer auto-detecting its environment, Synology's finder.
7. **Skippable wizard steps** — Jellyfin's libraries, Plex's Skip,
   Portainer's *Get Started*.
8. **A notification centre that can fix things** — Home Assistant
   *Repairs* (a badge, three severities, each with a fix or an
   explanation); Proxmox's bottom task log, which a 2026 homelab guide
   calls "super beneficial — they tell you what happened and why".
9. **A guided empty state** — "no model loaded. That is expected"; "You're
   in! Now what?".
10. **A daily-use rail of three to six destinations** — Chat / Discover /
    My Models / Developer. **None of them opens on an object tree.**

### 2.2 The complaints that recur

Model files held hostage (Ollama's hashed blobs, four open issues over
two years; LM Studio's mandatory folder layout and an import that
*moves* the file). Hidden defaults with no visible number (Ollama's
context). Misleading names. A global Advanced toggle gating essentials.
Heavy installs ("gave up after the first 12 gigabytes of pip packages").
Docs that lag the product. Redesign churn ("HATED it in the beginning").
A model picker with no sizes. **"Which node am I on?"** — Proxmox's
forum, and the same ambiguity exists in this UI's cross-node console.
Storage mental-model gaps (TrueNAS's `mnt`). Onboarding that ends in an
error. Licence drift.

Eugene answers the first complaint outright and should say so on the
first screen; it has the ingredients for the second and fourth; it
shares the ninth.

### 2.3 What hobbyists praise

Every "it just worked" quote names the same three things: **one
action, no decisions, built-in download.** *"I could have spent hours
googling, but I downloaded Ollama and it just worked."* *"It makes a
bunch of decisions for you so you don't have to think much."* Nobody
praises control. The people who left Ollama for llama.cpp kept it *"to
pull and list my models because it's so easy."*

### 2.4 Is a Proxmox-shaped tree right for Sam?

Honest reading: **for the operations half, yes; as the front door, no.**

- No product hobbyists rate as easy opens on an object tree.
  **Proxmox's own staff proposed a "simple view which reduces what's
  visible by default to the minimum"** after users reported "first time
  looking for where storages are" and no "indication of WHICH NODE this
  GUI is served from" (F). TrueNAS, the other infrastructure-shaped UI,
  is the one consistently called not beginner-friendly.
- **Home Assistant is deleting its global Advanced mode** (2026.6): "a
  blunt instrument", "essential features locked behind a poorly
  discoverable toggle", a label that creates "skill-level anxiety". The
  replacement is per-feature: *"A setting can be visible when it makes
  sense, sit under Show more, or live beside the feature it changes."*
  (F)
- The tree is right for Dana, is bounded at five branches whatever the
  install does, and answers a question no desktop app has to. Its two
  reported failure modes — depth, and not knowing which machine you are
  on — are both fixable in place.

**So: keep the tree, change what the root renders, and never add a
mode switch.** That is the shape of §6.

---

## 3. Where hobbyists actually get stuck

Ranked by how many distinct primary threads carried each (Appendix A.2),
with the current state of Eugene's answer.

| #  | Failure                                                             | Representative quote                                                                                                             | Eugene today                                                                                  |
| -- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1  | **Context vs VRAM** — silent truncation, then OOM when you raise it  | *"That 2k default is extremely low, and ollama silently discards the leading context."* (HN)                                      | **Built** 2026-09-12/15: `prompt_truncated`, `maxContextLength`, prefill, one-click fix. Discover's badge still reads a bare `fits` |
| 2  | **Reaching the server from another device or container**            | *"only able to access it via localhost:11434… I have disabled firewall"* (ollama #8304)                                           | **Missing** as a surface (§0.9)                                                               |
| 3  | **Model files trapped in a store**                                   | *"switching tools requires re-downloading everything… Nobody talks about it until they try to move their models."* (HN)           | **Built** — the thesis. Unsaid on any screen a new user meets                                 |
| 4  | **Which quant, will it fit**                                         | *"Q3_K_S vs 2Q_K_M? No one fucking knows."* (r/LocalLLaMA)                                                                        | **Built** (fit, recommendation, quant table); recommendation is a tag on a row, not the first thing shown |
| 5  | **GPU not used, silent CPU fallback**                                | *"not using the GPU even though it is available when you exec into it"* — the ROCm image on an NVIDIA box (Unraid forum)          | Partial: admission refuses with numbers; a running CPU-only runtime is not badged as a warning |
| 6  | **Pointing an OpenAI client at it** — `/v1`, non-empty key, model id | *"The `apiBase` differs for each tool. Otherwise, getting 404"* (continue #7658)                                                  | **Built** 2026-09-15 (S4): Home's card carries all three plus seven per-app recipes, and a long-lived revocable key |
| 7  | **Slow first response — the model was unloaded**                     | *"214 model load events… 11.4s to first token vs 0.9s warm"*                                                                      | Built (M6 policy); the load is visible only on Inference; no "keep resident" from the UI      |
| 8  | **Several models, eviction, VRAM juggling**                          | *"The log seems to say it runs out of memory, but I don't know what to do next."* (ollama #13235)                                 | Built (admission); no per-device memory bar on Inference                                      |
| 9  | **`<think>` tags in the answer**                                     | *"raw XML-like markup in the message body"* (open-webui #24839)                                                                   | Built (`ThinkingFilter`); the profile field is `thinkingMode`, not a plain-words control       |
| 10 | **Which model?**                                                     | *"Stop pretending like HF is in any way beginner friendly."* (HN)                                                                 | **Missing**: Discover opens on the catalogue's raw "most downloaded" list                      |
| 11 | **Docker as a barrier**                                              | *"for many users 'just run it in docker' is a non-starter"* (r/LocalLLaMA, 38 points)                                             | Answered: the one-liner installs on the gaming PC; the container is the NAS path              |

**▶ TWO ROWS THE TABLE NEEDS AND DOES NOT HAVE (added 2026-09-17 from the
adversarial review, both landing on exactly this audience).** **12 — a
slow-but-healthy answer reported as a failure:** the driver's read timeout is
120 s and the gateway's 180 s, a timeout arrives as an anonymous transport
error and cascades, so a 30B on CPU at ~3 tok/s is told *"Every backend serving
this model failed"* after 240 s — **with both engines having computed the
answer and the words "timed out" appearing nowhere** (review §6 #13; roadmap
R2.5). An 8 GB laptop runs on CPU spill by default. **13 — a component that
never came up: FIXED 2026-09-18 (R1.5).** Nothing probed a port before seeding
it, so 8080 taken meant the wizard completed, nothing was routable, Try it
never appeared, and the Needs-attention card was empty because no `IssueKind`
covered a supervised component that is down (review §6 #7). Seeding walks past
a held port now and `component-down` is the issue kind, rendering
`Component.lastError` — which names the port and the holding process.

Five of eleven are built underneath and unsurfaced or half-surfaced.
Three are missing. That ratio is the argument for a UX slice rather
than more system work.

---

## 4. Principles

Eight rules, each with where it comes from and which screen it governs.
They are the review checklist for every slice in §7.

- **P1 — Time to first token is the metric.** Kathy Sierra's "first
  success in one session"; the developer-tools "time to hello world"
  literature. *Governs:* the wizard, Home, the acceptance run (§8).
- **P2 — Detect, don't ask.** Apple HIG, Settings: *"Avoid using
  settings to ask for setup information you can get in other ways."*
  GPU, free memory, OS path shape, LAN address, control-root URL, the
  fitting context — all detected today; none should be a question.
  *Governs:* wizard, Reach, profiles.
- **P3 — Propose, don't search.** Hick's law; every product in §2.1.
  One recommended thing with a **why** and a **choose another**.
  *Governs:* Home's first-model card, Discover.
- **P4 — Nothing silent.** NN/g visibility of status; §3's top three
  failures all fail with a green status. The effective value and the
  tested reach are printed where the decision is made. *Governs:*
  Discover's badge, Reach, Inference's CPU/loading states, Issues.
- **P5 — Speak Sam's language; hide Dana's on hover.** GOV.UK: *"If you
  find yourself having to explain how the user interface works, that's a
  sign something has gone wrong. Fix the interface."* Reading age 9 for
  copy the golden path shows; specialist terms defined once, inline.
  *Governs:* every screen; enforced by a test (S8).
- **P6 — Disclose per field, never per mode.** NN/g progressive
  disclosure (two levels at most); Home Assistant's removal of Advanced
  mode. *Governs:* Config, the profile editor, Discover's table.
- **P7 — Background work is visible everywhere.** Proxmox's task log;
  NN/g indicators. One tray in the header for downloads, installs,
  loads, restarts; one Issues list for things that need a person.
  *Governs:* the shell.
- **P8 — Every state has a next step.** NN/g empty states: *"Provide
  direct pathways to getting started."* An empty Library, an empty
  Inference, an empty Metrics each end in one button. *Governs:* every
  empty and error state.

Standing rules from `CLAUDE.md` that these sit under, unchanged:
`easy-default-expert-override` (P2 and P3 are its UX form),
`gui-equality-for-configurable-things`, `one-console-never-hop-nodes`,
`cross-link-related-settings`, and M3's *"we recommend; the operator
picks"*.

---

## 5. Screen by screen

The hobbyist's question on arrival, what they meet, and the fix, keyed
to §7.

| Screen         | Sam's question                        | What Sam meets today (*measured*)                                                                              | Verdict          | Fix     |
| -------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------- | ------- |
| Installer      | "Is it on? Where?"                    | Windows: *"Eugene Plexus is running — open http://127.0.0.1:8079/"*. Linux with a service: a `systemctl` line and no URL | Good / fix Linux | S2      |
| Wizard         | "What do you need from me?"           | 5 screens, ~565 words, a passphrase and a hand-typed path; a backend screen for a user who has no backend        | Too long         | S2, S0  |
| Landing        | "Now what?"                           | A disabled composer reading "Waiting…"                                                                          | Fails P8         | S1      |
| Discover       | "Which one, and will it run?"         | Raw most-downloaded list; a recommendation as a small tag in a table sorted largest-first; `fits` with no context | Good bones, wrong emphasis | S6 |
| Library        | "Run it."                             | Engine detour; profile before launch; "watch it load on the Inference page"                                     | Three extra concepts | S3   |
| Playground     | "Is it working? Can I use it elsewhere?" | Adequate chat; the key is 4 clicks into a diagnostic panel and expires in a fortnight                          | Chat fine; connect missing | S4 |
| Inference      | "What is running, and why is it slow?" | Complete for Dana; `running` where Sam needs "on CPU — driver too old"; no memory bar                          | Add two states   | S7      |
| Config         | "Where is the one setting I need?"    | Every field at equal weight, six categories, implementation names in labels                                     | Fails P6         | S8      |
| Nodes          | "How do I add my NAS?"                | Right for Dana. `mint`, `epoch`, `advertiseUrl` in copy                                                          | Vocabulary       | S8      |
| Tree (1 box)   | "What are all these?"                 | Five branches, four rows saying "This machine", `control root unreachable` until sign-in                         | Noise on one box | S1, §6.4 |
| Header         | "Is anything happening? Anything wrong?" | Brand, *The system*, Sign out                                                                                  | Fails P7         | S1, S7  |
| Phone          | "Can I check it from the couch?"      | Fixed two-column grids; drawer works; badges and hints do not scale                                             | Secondary        | S9      |

---

## 6. The golden path, redesigned

### 6.1 Home

The install root's landing page after sign-in, and the tree's root
selection. Task-shaped, in this order top to bottom, each card present
only while it applies:

```
┌ This machine ──────────────────────────────────────────────────────────┐
│ RTX 5090 · 32 GB · 29 GB free      llama.cpp b10948      2 models on disk │
└────────────────────────────────────────────────────────────────────────┘
┌ Get your first model ──────────────────────────────────────────────────┐
│ Recommended for your card:  Qwen3-14B  ·  Q6_K_XL  ·  12.3 GB          │
│ Runs entirely on the GPU with 32k of context. Files land in            │
│ D:\Users\sam\Eugene Models, named as published.                         │
│ [ Download and run ]   [ Choose another ]   [ I already have models ]  │
└────────────────────────────────────────────────────────────────────────┘
        ▲ Built. One action, one tray entry, and it survives the tab:
          the intent rides on the download record, so a console opening
          after the laptop was shut claims it and carries on (§11.8).
┌ Try it ────────────────────────────────────────────────────────────────┐
│ ▸ qwen3-14b · 32k context                                              │
│ [ Say something…                                              ] [Send] │
└────────────────────────────────────────────────────────────────────────┘
┌ Use it from your apps ─────────────────────────────────────────────────┐
│ Address  http://192.168.1.20:8080/v1        [Copy]                     │
│ Key      eugene_…k9Q  (made 15 Sep, valid a year)  [Copy] [New key]    │
│ Model    qwen3-14b                          [Copy]                     │
│ Set up:  Continue · Cline · Open WebUI · SillyTavern · Claude Code · curl │
└────────────────────────────────────────────────────────────────────────┘
┌ Reach it from other devices ───────────────── off ▢ ───────────────────┐
│ Only this PC can reach Eugene. Turn on to open it from your laptop or  │
│ phone at http://192.168.1.20:8079 — Windows will ask about the firewall.│
└────────────────────────────────────────────────────────────────────────┘
┌ Running ───────────────────────────┐ ┌ Needs attention ──────────────────┐
│ qwen3-14b   ready   58 tok/s  0 busy│ │ nothing                            │
└────────────────────────────────────┘ └────────────────────────────────────┘
```

In the header, beside *The system*: a **tasks** indicator (downloads,
installs, loads, restarts — with bytes/s and an estimate) and an
**issues** badge. Both are one component fed by polling the endpoints
that already exist; §7 S1 and S7 say which.

The Playground keeps its diagnostic panel and becomes Home's second
page. "Try it" on Home *is* the composer, wired to the same code; a
first reply lands on Home, not on a screen the user had to find.

### 6.2 The wizard, two screens

```
1 of 2  Choose a passphrase
        It protects the keys and settings Eugene stores on this PC.
        [ passphrase ]  [ confirm ]
        ☑ Start Eugene on its own after a reboot (uses Windows Credential
          Manager). Untick to be asked for the passphrase every time.
        [ Continue ]

2 of 2  Where should models live?
        Eugene keeps model files as plain files with their published
        names. Move them, delete Eugene, they are still yours.
        ◉ Make a folder for me:  D:\Users\sam\Eugene Models   [change]
        ○ I already have models:  [ Browse… ]
        [ Finish ]
```

Screen 1's Continue runs today's steps 1–4 (initialize, components,
trust root, enroll), so screen 2 has a session and can browse. The
Backend screen leaves the wizard and becomes a Home card, *"Add an app
you already run (Ollama, a cloud CLI)"*, shown when Inference is empty.
The Welcome screen's content becomes the header of screen 1. The
security choice is written to both agent and control (§0.14).

### 6.3 The first model

"Download and run" does, in order and in one task-tray entry: download
(resumable, verified, as today) → install llama.cpp if absent → create
the `default` profile at the fitting context → launch → mark ready and
light up "Try it". Every step is a thing the system already does; the
slice is the orchestration and the one place it is reported.

> **▶ BUILT, 2026-09-16 (§11.8).** One click, one task-tray entry, all
> the way to a first reply. It shipped as two actions for a few hours
> after S6 — Home offering **Download**, S3's **Run** taking its place
> when the file landed — which asked the person twice, the second time
> minutes later when a multi-gigabyte download finishes and they may
> have walked away.
>
> **The hard half was never the chain: it was that a 16 GB transfer
> outlives the browser.** So the intent is not in a browser-side store;
> it rides on the **download record** as `runWhenReady`, which the
> library records and never acts on — a launch is a profile, an engine
> and a runtime on some node's agent, and which node is a question the
> library has no business answering. A console opening later claims the
> record and carries on. `POST /v1/downloads/{id}/claim` makes that safe
> from every console at once, and is also what stops a deliberate stop
> from being undone a week later by a browser that still sees the old
> intent.

The recommendation is *"the most-downloaded, well-known, permissively
licensed general-purpose instruct GGUF in the largest size class that
fits at 16k context on the detected card"*, from a **starter set** the
library ships as data (a handful of families across ~4B, ~8B, ~14B,
~30B, ~70B), refreshed at release time and overridable in the library's
config. The card says why (*"the largest of the starter set that runs
entirely on your GPU with room for 16k of context"*), and **Choose
another** opens Discover. That is M3's rule kept: we recommend, the user
picks, and the pick is one click away.

### 6.4 The tree on one machine

When the registry holds one machine and nothing names another, the
node level does not render: `Inference drivers` lists drivers directly,
`Agents` is a leaf, `Library` has no machine rows. The moment a second
machine enrolls, the level appears everywhere at once. The tree grows
with the install instead of describing an install the user does not
have. Everything else in `ui-tree-navigation.md` stands.

---

### 6.5 The starter set, and the review that keeps it honest

Troy took decision #4 on one condition:

> This is something that will quickly grow stale as models continue to
> improve. If we make a default, this project needs an automated process
> before new releases to review the state of local inference and make a
> recommendation about whether we keep or replace our default selection.

This section is that process. It recommends; a person decides; the
release cannot ship past a stale or unresolved review.

**The data.** `starter_models.yaml`, shipped inside the library wheel,
one entry per size class, every field something the review can check:

```yaml
reviewed: 2026-09-15
engine: llama_cpp b10948          # the build every entry was verified against
classes:
  - class: 8B                      # by parameter count: ~4B, ~8B, ~14B, ~30B, ~70B
    baseModel: Qwen/Qwen3-8B       # what the ranking is about
    repo: unsloth/Qwen3-8B-GGUF    # where the quants come from (one mirror of many)
    why: most-downloaded instruct GGUF in its size class in the last 30 days
    licence: apache-2.0
    evidence: { downloads30d: 412000, rank: 1, consecutiveReviewsAtTop: 3 }
```

The library reads it at start; `starterModelsFile` on the library's
config points at a different file for an expert or a fleet, and an
empty list turns Home's card into *Find a model*, which opens Discover.
No hard-coded model name exists anywhere in code.

**What the card says, exactly.** *"Recommended for your card: Qwen3-8B ·
Q6_K_XL · 6.2 GB. The most-downloaded well-known instruct model in the
largest size class that runs on your GPU with room for 16k of context.
Reviewed 15 Sep 2026."* The date is the staleness made visible (P4).
The word "best" never appears; the criterion is downloads, which is the
community's judgement and not ours, and M3's rule stands.

**The review — `eugene-plexus-library starter-review`.** A CLI in the
library repo, because the library already speaks the Hub, reads GGUF
headers, knows the quant table and can tell an embedding model from a
chat one. It runs monthly in CI and on demand, and does this:

> **▶ FIVE OF THIS SECTION'S CLAIMS ABOUT THE HUB WERE WRONG, and the
> corrections are in place below rather than appended, because the
> corrections are the value.** Measured 2026-09-16 against the live
> listing API while building this. (a) **`full=true` and `expand[]` are
> mutually destructive** — `full=true` returns neither `gguf` nor
> `cardData`, and passing both leaves a projection of three keys with
> the sort and filter silently ignored, so the ranking call cannot be a
> flag on the existing search one. (b) **`pipeline_tag` cannot be a
> filter**: adding `filter=text-generation` dropped the *second*
> most-downloaded GGUF repo on the hub, because the field is absent on
> many repos; the discriminator that works is a **chat template** in the
> repo's own `gguf` block, which also excludes the ASR, TTS, embedding
> and projector repos that made up 21 of the top 100. (c) **`base_model`
> is sometimes a list of sixty** — one top-twenty repo bundles every
> model it supports — so a multi-valued one is not an aggregation key.
> (d) **`gguf.total` is read off one file in the repo and is sometimes
> the wrong file**: a 27B repo reported 0.5B because the hub read its
> vision projector, so a class's parameter count is the **mode** of its
> contributors. (e) **Capitalisation splits a family** —
> `google/gemma-4-E4B-it` and `google/gemma-4-e4b-it` are one model
> spelled two ways by two publishers, and unnormalised they rank as two
> candidates with half the downloads each.

1. **Rank.** Ask the Hub for GGUF repos by 30-day downloads with
   `expand[]=gguf` (architecture, parameter total, chat template) and
   `expand[]=cardData` (`base_model`, licence) — **not** `full=true`,
   and **not** filtered by `pipeline_tag`; see the correction above for
   both. Aggregate the dozen quant mirrors of one model by a
   **case-folded** `base_model` — official, `unsloth`, `bartowski`,
   `ggml-org` and `lmstudio-community` are one candidate, not five —
   and bucket by the **mode** of its contributors' parameter counts.
   Drop: gated repos, and entries with no chat template, which is what
   removes base models, embedding models, rerankers, ASR, TTS and
   projectors in one rule. A candidate is **flagged, not ranked** — and
   so appears in the report but produces no proposal — when its
   publisher is not on a short known-publisher list, when its licence is
   not on a short allowlist, when its name carries a specialisation
   (`coder`, `ocr`, `embed`, …) or a de-alignment (`abliterated`,
   `uncensored`, …), when it declares many base models or none, or when
   **only one repo mirrors it**: one repo is a publisher, not a
   consensus, and the ranking is a consensus measure. Both lists grow by
   a human adding a line, never by the tool.
2. **Compare** each class's current entry against the ranking.
3. **Prove it runs.** Fetch the pinned llama.cpp build's architecture
   list (`src/llama-arch.cpp` at the build tag) and check each
   candidate's `general.architecture` against it. For classes whose
   smallest quant is under 6 GB, download it and produce one token on
   CPU in CI. Above that, the architecture check alone, **and the report
   says which check ran.** A model the pinned engine cannot load is the
   one recommendation that would be worse than none. *(Built: the
   architecture half. The CPU-token half is not, and the report says
   `proof: architecture` rather than implying both.)*

   The same step reads the chosen file's own header over a ranged
   request — about 11 MB — and records its shape, which is what lets
   `GET /v1/catalogue/starter` answer with `basis: metadata` and no
   upstream call at all.
4. **Verdict per class, with hysteresis.**
   - **KEEP** — the current base model is still in the top three of its
     class, ungated, its recommended file present, its architecture
     supported.
   - **REPLACE (candidate)** — a different base model has held first
     place for **two consecutive monthly reviews** and passed step 3;
     or the current entry is gated, gone, or unsupported, in which case
     immediately.
   - **REVIEW** — first place changed this month only (a launch-week
     spike is not a trend); the top two are within 20 % of each other;
     an unknown publisher or licence is at the top; or the Hub did not
     answer. **A failed lookup is REVIEW, never a silent KEEP.**
5. **Report.** A markdown report per run — current, candidates,
   numbers, which check ran, verdict — plus a proposed diff to
   `starter_models.yaml`, and a **"new this month"** section: the top
   entries by downloads that were not in last month's top twenty, and
   any architecture in them the pinned engine does not yet support.
   That last section is the "state of local inference" Troy asked for,
   and it is information for the reader, not an input to the verdict.
   **Nothing is applied automatically.**

**Cadence and the gate.** A scheduled workflow in `library` runs the
review monthly and files the report as an issue there. The release
step in `install-paths-and-distribution.md` §9 gains one line: *the
latest starter review is under 30 days old and carries no unresolved
REPLACE or REVIEW.* `hobbyist-acceptance.sh` asserts, before it
downloads, that every entry's repo answers and its recommended quant
file exists. A release with a stale list is a release that fails a
check, not one that ships with a note.

**What it will not do.** Judge quality — no benchmark column, no
leaderboard, no invented score; downloads are the only ranking and the
report says so in its header. Fetch the list at runtime from the
network — considered and declined for the release, because a remote
list that drives a 20 GB download is a trust and availability
dependency the installers deliberately avoid by pinning, and Discover is
one click from the card for anything newer. Revisit if the release
cadence is slower than the review's.

**Which quant ships, and it is one axis.** One file per class, and
the family decides before the width: `Q4_K_M` and its `UD-` and `-L`
relatives first, then any other K-quant, then everything else. Width
alone is not enough and the first run of this review proved it — at a
4.8-bit target it chose `IQ4_XS` for one class and `Q4_0` for another,
both within 0.1 bits of `Q4_K_M` and neither the file a stranger should
be handed first. **And the repo cannot be chosen before the quant:**
`ggml-org`'s gemma repo holds `Q4_0`, `Q8_0` and `BF16` and no K-quant
at all, so "the most-downloaded repo from a publisher we know" picked a
legacy layout for a model two other publishers ship a full ladder for.
The review opens up to three known-publisher repos and stops at the
first offering a preferred family. Offering a stranger eleven quants at
the same moment as a size class is the wall §0.5 measured; an expert
changes it in Discover, one click away.

**Traps named now.** Launch spikes (the two-review hysteresis).
Downloads split across mirrors (aggregate by `base_model`; where the
card lacks it, fall back to name parsing and flag). A repo whose name
does not match its base model's card — Ollama's stripped "Distill" is
the cautionary case — is never recommended over one that does. Licence
outside a short allowlist is REVIEW. The known-publisher list is itself
a curation that ages, which is why an unknown publisher at the top
surfaces as REVIEW instead of being dropped. And running the review
only on release day is too late to have two consecutive months of
evidence — which is why it is monthly.

### 6.6 Reach: detecting the firewall

Troy, taking decision #8: *"Is it possible for us to detect Windows
firewall disposition so we can warn user when it is blocking?"*

**Yes, and on Windows it is the well-instrumented case.** Reasoning, not
yet measured; S5 measures it.

> **S5 measured it, 2026-09-15, and four things below are wrong.** They
> are left in place because the corrections are the interesting part.
> (a) **The cmdlets are the wrong instrument** — `Get-NetFirewallPortFilter`
> raises *Access is denied* unelevated **and returns a truncated list on
> the way out**, so a detector built on them reports "nothing covers our
> port" from a partial read; COM enumerated all 708 rules with no error,
> in 78 ms against ~2.8 s. Nothing here uses a cmdlet. (b) **"Every
> profile's default inbound action is Block"** is true of the machine
> and not of the *report*: `Get-NetFirewallProfile` says
> `NotConfigured`, which means block and reads as not-blocking to a
> string comparison; `DefaultInbound` carries `unknown` as a third
> member for that reason. (c) **"Scope to ports, not the program"** is
> right for a rule we add and wrong as a detector: the rule that makes
> the live install on the measured host reachable is bound to the
> **program**, created by Windows' own Security Alert dialog, and there
> is no rule mentioning its ports at all — so a port-only detector calls
> that machine `blocked` while the control root probes it successfully
> every fifteen seconds. Program rules count, and `FirewallPort.scope`
> reports which kind decided, because the program it names is a
> **versioned** interpreter path that stops applying the day the
> interpreter is upgraded. (d) **`lastReachedByRoot` is not something
> the agent can know** — the root already records it as
> `Node.lastSeenAt` — and the useful field is any off-host caller, which
> on a standalone install is the person's own phone doing the test the
> card asked for.

**What Windows does when nothing is configured.** Every profile's
default inbound action is Block. When a program first listens on a
non-loopback address with no rule covering it, Windows shows the
*Windows Security Alert* dialog — if notifications are on and someone is
at the desktop. Cancel creates an explicit Block rule for that
executable. A process with no interactive desktop shows nothing and the
default block applies silently — which is exactly the service and the
scheduled task from step 3, the two ways this product runs on Windows.
And a home network Windows has classified as *Public* is the commonest
cause of "it worked at home yesterday".

**What the agent can read without elevation** — the `NetSecurity`
PowerShell cmdlets through a subprocess, or the `HNetCfg.FwPolicy2` COM
object through the `pywin32` the `[service]` extra already carries:

- `Get-NetFirewallProfile` — per profile: enabled, default inbound action.
- `Get-NetConnectionProfile` — each connected adapter's network category:
  Public, Private, Domain.
- `Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow`
  joined with `Get-NetFirewallPortFilter` (port, protocol) and
  `Get-NetFirewallApplicationFilter` (program) — whether any enabled
  Allow rule covers our TCP ports, or our interpreter's path, in each
  active profile; and whether an explicit **Block** rule names our
  program, which a dismissed dialog in some earlier session may have
  left behind.
- WMI `root\SecurityCenter2` → `FirewallProduct` — a third-party firewall
  registered with Security Center, by name. Windows Firewall's own state
  says nothing about it, and "Windows Firewall off" with Norton on reads
  as *allowed* to anyone who checks only the first.

**Verdict per published port:** `allowed` (an enabled Allow rule covers
it in every active profile), `blocked` (Windows Firewall on, default
Block, nothing covers it — or an explicit Block names our program),
`unknown` (a third-party firewall is registered, or the query failed).
Each carries the network category and the remedy.

**Remedies, easy default first.**

1. **Service install (elevated):** the agent adds the rule itself when
   Reach is turned on and removes it when turned off —
   `New-NetFirewallRule -DisplayName "Eugene Plexus" -Direction Inbound
   -Protocol TCP -LocalPort 8079,8080 -Action Allow -Profile
   Private,Domain`. Scoped to **ports, not the program**: a rule bound
   to a venv path breaks the day the venv moves.
2. **Logon-task install (unelevated):** the agent runs in the user's
   own session, so the card's **Allow** button launches one elevated
   PowerShell with the same command. Windows raises a UAC prompt on the
   desktop; one click on Yes.
3. **Declined or unavailable:** the card prints the command with "run
   as administrator" and stays `blocked`.

Private and Domain by default; **Public only as an explicit override**,
beside the warning *"Windows treats your network as Public. Change it
to Private in Settings → Network, or allow Eugene on Public networks
too."* A tailnet adapter reports its own category and `tailnet.md` is
the answer there; the card must never tell a tailnet user to reclassify
their Wi-Fi.

**Linux and macOS, honestly.** Whether `ufw` or `firewalld` is enabled
is readable without root (`/etc/ufw/ufw.conf`, `systemctl is-active
firewalld`); whether our port is allowed usually is not (`ufw status`
and `firewall-cmd --list-ports` want root), so a user-mode agent reports
`unknown` with the exact command to run. Neither present is `allowed`.
macOS's application firewall reports its global state through
`socketfilterfw --getglobalstate` and prompts per app on the desktop, so
a launchd agent can be silently blocked exactly as on Windows; the
remedy is `--unblockapp` on the interpreter, printed. A container is
`unknown`: the mapping is the host's, and the template already
publishes the ports.

**The proof is from outside.** Static inspection says the firewall
*should* allow. The only proof is a connection from another machine —
and the install already makes one: the control root probes every
enrolled node's advertised URL (`Node.lastSeenAt`, `reachable`). On a
multi-machine install the card says *"the control root reached this
machine at http://…:8079 twelve seconds ago"*, which is evidence of the
kind nothing local can produce. On a single box there is no second
machine; the card says *"open this on your phone — if the page loads,
it works"* and the firewall verdict is the best available evidence.
Nothing pretends otherwise.

**Contract.** `GET /v1/node` gains `reach`:

```yaml
reach:
  advertiseUrl: http://192.168.1.20:8079/     # null when only loopback
  boundAddresses: [{component: agent, host: 0.0.0.0, port: 8079}, …]
  firewall:
    product: Windows Defender Firewall          # or the third party's name, or null
    activeProfiles: [Private]
    ports:
      - {port: 8079, verdict: blocked, rule: null, remedy: "New-NetFirewallRule …"}
      - {port: 8080, verdict: allowed, rule: "Eugene Plexus", remedy: null}
  lastReachedByRoot: 2026-09-15T14:02:11Z        # null on a single box
```

Every field nullable; an OS the detector does not know reports
`unknown`, never `allowed`. Read per request, cached no longer than the
node refresh.

**Traps.** Checking only Windows Firewall's state (the Security Center
lookup is why). A stale Block rule for `python.exe` from a previous
account or install (detection names it). A rule scoped to a program
path (scope to ports). UAC needs a desktop: the logon task has one and
the service does not, and the service does not need it. The PowerShell
subprocess costs a few hundred milliseconds per read on Windows, so the
verdict is refreshed with the node view, not on every render. And a
`blocked` verdict with everything working — a third-party firewall
already allowing us, say — must read as *"we could not confirm"* rather
than as an error; the corollary of `easy-default-expert-override` is
that an eager refusal can be wrong and an explanation of a real failure
cannot.

---

## 7. The plan

Slices in recommended order. *Touches* names repos; **contract** marks a
change to `openapi/`. Sizes are relative (S under a day, M a day or two,
L several) and are estimates. Each ends with a **done-when** a script or
a browser can assert.

### S0 — Defaults that let a reboot come back working (S) — **BUILT AND LIVE-VERIFIED 2026-09-15**

Keyring on desktop OSes as the wizard default, written to agent *and*
control; the wizard copy says what happens after a reboot in one line;
`install.sh` prints the URL on every path. *Touches:* ui, agent
(default), control (verify the keyring path is live, or make it so).
*Done when* `m9-acceptance.sh` restarts both processes after the wizard
and signs nothing in, and `/v1/models` and `/v1/nodes` both answer.
Decision **#9**. **Record: §11.1.**

### S1 — Home, and the tasks tray (L) — **BUILT AND LIVE-VERIFIED 2026-09-15; record §11.2**

The page in §6.1 minus the cards that need later slices (Use it from
your apps waits for S4; Reach for S5). The tray polls
`library /v1/downloads`, `agent /v1/engines/*/install`,
`agent /v1/runtimes` (status + `lastError`) and the restart modal's
state, and renders one line per task anywhere in the app. Home is the
install root's first page; Playground its second. *Touches:* ui only.
*Done when* the fresh-install landing page has a primary button and no
disabled input, and a download started on Discover is visible from
Config. Decision **#1**.

### S2 — The two-screen wizard, with Browse and a proposed folder (M) — **BUILT AND LIVE-VERIFIED 2026-09-15; record §11.3**

§6.2. Enroll on screen 1; `FolderPicker` on screen 2 over the local
agent's `/v1/directories`; the proposed default is a plain folder under
the user's home, **created only when the first download lands in it**
(the library creates a configured folder that does not exist yet when
it is the download destination — a behaviour change in `downloads.py`,
no contract change). *Touches:* ui, library. *Done when* the wizard is
completed with one typed value and the first download succeeds without
a 409. Decisions **#2, #3**.

### S3 — One-click run (M) — **BUILT AND LIVE-VERIFIED 2026-09-15; record §11.4**

Launch with no profile creates `default` at `maxContextLength` — **and review
§6 #4 (2026-09-17) says that number comes from the wrong fit path: the on-disk
route's shape builder never sets `layers`, so the 14B starter class is scored
with the scalar KV reader the 43× fix replaced, and the profile is written at
~4,864 where Home advertised 16,384. The mechanism in this slice is right and
the number it writes is wrong** (roadmap R1.3); a
finished download offers **Run** in place; the Library's "install one
from the Inference page" sentence goes. **Launch on a node with no
engine asks first (Troy's amendment to #6):** *"I could not find
llama.cpp on this machine. Install it now?"* — **Install** is the
default and the primary button; **Skip** carries the line *"for advanced
users: the model cannot run until an engine is installed by hand"* and
leaves the runtime declared but not started, with the reason on
Inference. On Install, the tray shows the install and the launch as two
steps of one task and names which one failed if one does. The UI
orchestrates (install → poll → runtime); nothing new on the agent.
*Touches:* ui, library (implicit profile). *Done when* a fresh box goes
from "Download and run" through the one confirmation to `ready` with no
other click, and Skip leaves a stopped runtime whose reason is printed.
Decisions **#5, #6**. *As built:* ui only for the slice, plus two agent
fixes the acceptance run forced (§11.4) — the library needed nothing.

### S4 — Client keys, and "Use it from your apps" (M, contract) — **BUILT AND LIVE-VERIFIED 2026-09-15; record §11.5**

`POST /v1/auth/client-keys {name, ttl?}` on the agent, minting a token
with the install signing key, `aud: client`, default one year; `GET`
lists names, prefixes and expiries; `DELETE` records a revocation the
gateway checks by `jti`, or — simpler and already the project's model —
revocation is the existing signing-key rotation, and the list is
informational. The gateway accepts `aud: client` on its three OpenAI
paths only. Home's card shows address (with `/v1`), key, model id, and
per-tool recipes as copyable snippets: Continue `config.yaml`, Cline
"OpenAI Compatible", Open WebUI connection, SillyTavern custom endpoint,
Claude Code / OpenCode env block, `curl`. The Diagnostic panel's key
field offers the client key too. *Touches:* specs (`agent.yaml`,
`gateway.yaml` prose), agent, gateway, ui; control regen. *Done when*
`hobbyist-acceptance.sh` copies the three strings off Home, restarts the
gateway, and completes a request with them and nothing else. Decision
**#7**. *As built:* the revocation went the **first** way — a list the
gateway polls from its own node's agent, bounded by the routing refresh
interval — because a "Turn off" button that only pretends is the silent
failure P4 forbids, and because a key per app is pointless if revoking
one revokes them all. `scripts/client-keys-acceptance.sh` stands in for
the not-yet-written `hobbyist-acceptance.sh`. Claude Code is **not** in
the recipe list: it speaks the Anthropic Messages API, which this
gateway does not serve (§11.5).

### S5 — "Reach it from other devices" (M, small contract) — **BUILT AND LIVE-VERIFIED 2026-09-15; record §11.6**

One switch on Home and on the agent's Config: proposes the LAN address
the agent already derives, sets `advertiseUrl`, restarts what must
restart, and prints the URL a phone types. `GET /v1/node` gains `reach`
(§6.6): what each component actually listens on, **the firewall's
verdict per published port** with the active network category and the
remedy, and when the control root last reached this machine from
outside. The card says *"listening on your network, firewall allows
it"*, *"blocked by Windows Firewall — Allow"* (one click through a UAC
prompt on a logon-task install; done silently on a service install), or
*"only this PC"*, from evidence. `install.ps1` adds the rule when
elevated. *Touches:* specs (`agent.yaml`), agent, ui, scripts. *Done
when* the run flips the switch, reaches the UI and the gateway from a
second address on the same box, and — on Windows — the verdict reads
`blocked` before the rule exists and `allowed` after. Decision **#8**.

*As built (§11.6):* four sentences above were wrong and measuring fixed
them. **"the LAN address the agent already derives"** — it derives
`127.0.0.1` on a standalone install, because the derivation reads the
route to a control root that is on loopback, so `proposedUrl` is a new
derivation off the routing table. **"restarts what must restart"** — it
restarts the components, and *cannot* restart itself without being
asked, because a listening socket is fixed for the life of a process;
`restartRequired` says so rather than reporting success. **"when the
control root last reached this machine"** — the agent cannot observe
that and the root already records it as `Node.lastSeenAt`; what the
agent can observe is any off-host caller, which is better for a
standalone install because the phone the card told them to try *is* the
evidence. **The firewall verdict is not the done-when it looked like**:
`blocked` for a port and "the UI loads from the second address" are both
true in the same run, because host-local traffic is not filtered — which
is §6.6's own thesis, reproduced. The `blocked → allowed` half needs
administrator rights and is `EP_FIREWALL=1`, skipped and reported as
skipped.

### S6 — Discover: recommendation first, badge names the context, paste a URL (M) — **BUILT AND LIVE-VERIFIED 2026-09-16; record §11.7**

The recommended quant renders as a card above the table with the fit
sentence and a Download button; the table sits under **All versions**;
the badge reads *fits at 32k* and the context control moves beside it;
the search box accepts a pasted Hugging Face URL; the starter set from
§6.3 is Discover's empty-query view. **The review from §6.5 ships in
this slice**: `starter_models.yaml`, the `starter-review` CLI, the
monthly workflow in `library`, and the release-checklist line — the
first review report is what populates the file. *Touches:* library
(starter set, review CLI, URL parse), ui, specs (`install-paths` §9).
*Done when* the badge text contains the context, a pasted repo URL
resolves, and the review has run once end to end and its report is in
`docs/acceptance/`. Decision **#4**.

**Done, all three, plus one the slice could not ship without.** The
first accepted list scored a mainstream 12B as *partial offload* on a
32 GB card because `attention.head_count_kv` is an **array** on it and
five of every six of its layers slide over a 1024-token window — the
scalar arithmetic read 24.0 GiB of KV cache at 16k where the truth is
0.56 GiB. §11.7 has the table. Also corrected: the design's step-1
ranking call, four of whose assumptions about the hub's listing API were
wrong, and its "404" for an unresolvable URL, which the hub answers as
401.

### S7 — Issues, and two honest states on Inference (M) — **DONE AND LIVE-VERIFIED 2026-09-16; record §11.9** (this heading, the status block and §11.9's own title all said PAUSED until 2026-09-17; all three corrected)

The **Needs attention** card and header badge: sealed root, folder not
mounted, node down with `lastError`, clock skew warning, engine release
with no assets, mixed engine builds across replicas, a runtime on CPU.
UI aggregation over existing endpoints first; a `GET /v1/issues` on the
agent when the list stabilises. Inference gains *loading · ~2 min left*
(from bytes and rate) and *on CPU — reason* as a warning. *Touches:* ui;
later agent + contract. *Done when* a sealed root shows as one issue
with the unlock as its action, from any page.

**Four of those seven were not observable, and §11.9 has the
measurement.** Clock skew was **log only** — and behind it, *no
component put its own current time on any response body*, which is why
the slice's one contract change is `NodeIdentity.time` (landed, served,
`specs` `4a72644` / `agent` `763d10d`). Mixed builds, on-CPU and the
loading state all need per-node reads, because the control root's
`RuntimePlacement` carries no `engineVersion`, `flags`, `lastRestart`
or `localPath`. "Engine cannot be installed" **must exclude
`policy: manual`**, or vLLM puts a permanent unfixable issue on every
install there will ever be. And a machine with no accelerator is a
*state*, not an issue, while the case that would earn one — a CPU-only
engine build on a machine with a card — is not observable at all.

**And *loading · ~2 min left (from bytes and rate)* cannot be built as
written: there are no bytes.** No engine reports load progress, and
process I/O counters do not rescue it because llama.cpp memory-maps the
model and faulted pages are not read I/O on Windows. What is honest is
elapsed, plus the share the bytes are crossing — which is what actually
explains the four-minute load on the live install — plus an estimate
only once this browser has watched the same model load before.

### S8 — Vocabulary (M) — **COMPLETED 2026-09-20**

UI `48488ad`, dist `ad6836f`, pinned in both installers.
[Verification and scope](../acceptance/s8-vocabulary-run.md).

A banned-word test over the golden-path screens (Home, wizard, Discover,
Library, Playground): `companion driver`, `declaration`, `admission`,
`mint`, `epoch`, `advertiseUrl`, `trust root`, `runtime` (as a noun to
the user), `topology`, `routing table`; each occurrence moves to a
`title` or goes. A twelve-term glossary panel replaces nothing and hangs
off *The system*. Copy on those screens under 25 words a sentence.
Config gets a **Show more** group per page where three or more fields
qualify (Material's rule), with the order by change-frequency. Sizes
and units in plain form (*12.3 GB*, *32k context*). Relabels
(`Backends`, `Chat`) are decision **#12**'s second half. *Touches:* ui;
config schemas for the grouping flag (a `ConfigField.advanced: bool`
is a **contract** addition if it lives there; a UI-side list per
component is not). *Done when* the test passes and a Hemingway pass on
the extracted strings reports grade 9 or under. Decisions **#11, #12**.

### S9 — Phone, focus, motion (S–M)

Home, Playground and Library stack at one column under 640 px; a
visible focus ring; `prefers-reduced-motion` stops the pulse; the
fixed-pixel sizes on hints and badges move to rem so the font-size
preference reaches them. *Touches:* ui. *Done when* the 430 px e2e case
walks Home → Try it → a reply.

**BUILT 2026-09-20** — UI `94d0ce3`, dist `5306208`. Library and
Playground stack below 640px; Config and Preferences do too. Shared focus
rings, reduced motion and rem-based hints/badges are in place. The packaged
430px Home → Try it → real CPU-model reply passed, plus 390px layouts,
font preference and keyboard checks. **743 UI tests pass.** Record:
[`../acceptance/s9-phone-run.md`](../acceptance/s9-phone-run.md).

### S10 — Measure it (M; runs alongside everything above)

`scripts/hobbyist-acceptance.sh`: from `install.sh` on a clean guest to
a first token, driven by the system Chrome, **counting real pointer
actions and keystrokes**, asserting the budget in §1 and that no
filesystem path was typed; then the three strings from Home used by a
plain `curl`; then the Reach switch. Plus the readability lint and the
banned-word test from S8. And **moderated sessions** (§8.4). *Done when*
the script is green on WSL2 and this box and the session notes are in
`docs/acceptance/`.

**BUILT 2026-09-16, GREEN ON BOTH TARGETS** — §11.10 is the record and
`docs/acceptance/hobbyist-run.md` is the run. 22 checks on Windows and
22 with `EP_TARGET=wsl`: **5 clicks** on each where §0.2 measured 15,
one typed value and no typed path, **1 click** from Home to a connected
tool where §0.2 measured 19, a key good for a year, one Reach switch,
zero banned words. `install.sh` from nothing in 4 s, `install.ps1` in
7 s. The WSL2 half drives the guest install from a Windows browser,
because the guest has no Node and no browser and the UI is one static
export — what WSL2 is there to test is `install.sh`. Still owed by the
*Done when* above: **`EP_DOWNLOAD=1`** for §1's ten-minute target (not
measured) and **the moderated sessions** (§8.4), which gate the release.

**What gates the release (decision #13, taken):** S0–S6 and S10, **and
a starter review under 30 days old with no unresolved verdict (§6.5)**.
S7–S9 are real and can follow; none of them is on the path from install
to a first token or a connected tool. **▶ AND SINCE 2026-09-17 THIS GATE IS
UNCHANGED BUT NO LONGER FIRST:** the adversarial review's eight fixes sit in
front of any public link and five more in front of the first hostile review —
four of the eight are defects in the paths S3, S6 and §6.3 declared built. The
review is explicit that it *"does not shorten that list; it adds the fixes above
in front of it"*. Order: [`release-roadmap.md`](release-roadmap.md).

---

## 8. How we will know

### 8.1 The numbers

| Measure                                     | Today              | Target         | Instrument                        |
| ------------------------------------------- | ------------------ | -------------- | --------------------------------- |
| Clicks, install → first reply               | 15 (19)            | ≤ 6            | **5** — §11.10                    |
| Typed values before first reply             | 3 (incl. a path)   | 1              | **1**, no path — §11.10           |
| Route changes before first reply            | 6                  | ≤ 1            | same                              |
| Clicks, Home → tool connected               | 19 from landing    | ≤ 3            | **1** — §11.10                    |
| Time, install → first token, 8B, 100 Mbit   | not measured       | < 10 min       | not measured (`EP_DOWNLOAD=1`)    |
| Jargon terms on golden-path screens         | (not isolated)     | 0 banned words | **0**, four screens — §11.10      |
| Reading grade of golden-path copy           | not measured       | ≤ 9            | Hemingway over extracted strings  |
| Docs links from the UI                      | 0                  | ≥ 1 per screen | grep                              |
| e2e coverage of the golden path             | wizard + login     | every stage    | Playwright                        |

### 8.2 Traps in the measurement, named now

- **A step counter is not a click counter.** M10's check 7 passed
  against the failure it was meant to catch; a "≤ 6 steps" assertion
  that counts scripted actions will pass a flow with 15 real clicks.
  Count Playwright `click()` and `fill()` calls that the script made,
  and record the transcript as the evidence.
- **The author's machine is not a fresh machine.** `bootstrap.ps1`
  exercised nothing for four milestones for exactly this reason. Run on
  a clean WSL2 guest and a clean Windows user profile, as
  `install-acceptance.sh` already does.
- **The proxy path proves the control plane, not reachability.** The
  connect-a-tool check must use `curl` from outside the browser with
  the strings copied off Home, as the playground's direct mode already
  insists.
- **`locator(...).first()`** has matched the wrong textarea twice in
  this project's e2e history. Every selector on Home is a `data-testid`.
- **A recommendation list goes stale.** It is refreshed at release time
  and overridable; the run asserts the recommended file exists upstream
  before downloading it.

### 8.3 The standing loop

The live install's incident rate (§0.13) is the leading indicator. Each
incident keeps becoming a same-day fix, and each fix keeps landing with
a browser check that would have caught it. That loop stays; this plan
adds the instrument that measures the path *before* a stranger walks it.

### 8.4 Three to five strangers

Before the release, the two or three friends Troy can get — *"I can't
promise exactly 3-5, but yes I have 2-3 friends for sure"*; two who
match Sam are worth more than five who do not, and he is in no hurry
to release — each given the one-liner and five tasks, thinking aloud,
with no help: *get a model answering; make
it answer from your phone; connect it to a tool you use; find out why an
answer was slow; change the context size.* Record where each stalls,
what they say, and what they type. Twenty minutes per person. Written up
in `docs/acceptance/hobbyist-sessions.md` in the same shape as every
other record here. GOV.UK's point 1: *"Testing your assumptions early
and often reduces the risk of building the wrong thing."* Nothing in
this document survives contact with those five people unchanged, and
that is what they are for.

---

## 9. What stays out

- **No native desktop app**, no personas, no prompt library, no chat
  product — decided 2026-09-11 and unchanged. Home's "Try it" is the
  playground's composer, not a new chat.
- **No automatic quant selection** beyond one recommendation with a
  reason and a one-click alternative — M3's rule.
- **No renaming of the architecture.** Objects keep the registry's
  names; only body copy changes. Relabels are a separate call.
- **No global Simple/Advanced mode.** §2.4.
- **No Docker on the gaming PC.** The container stays the NAS path.
- **No managed store.** The proposed folder is visible, plainly named
  and the user's; nothing is renamed, hashed or hidden. If that ever
  stops being true the folder proposal goes, not the rule.
- **No tour, no tutorial overlay.** NN/g: they interrupt and do not
  transfer; contextual help on the field wins.
- **No changes to the tree's model** beyond §6.4.
- **Not in this plan:** a structured `model_slots` editor, a guided "add
  an external backend" form, image attachments, `role="tree"` semantics.
  Real, listed, later.

---

## 10. Traps known in advance

1. **Vocabulary creep.** Every slice built by people who know the
   architecture reintroduces its nouns. The banned-word test is the
   guard, and it must run on Home from S1, not from S8.
2. **Home must not hide the tree.** Sam becomes Dana; the tree is one
   click away at all times, and Home is a page *in* it.
3. **The proposed folder is one bad decision away from a store.** No
   sub-structure beyond what the publisher named, no index file the
   user cannot read, the path printed on every card that mentions it.
4. **A recommended model is a liability the day it is wrong.** The
   starter set is small, data-not-code, reviewed monthly by the process
   in §6.5 with a human accepting every change, dated on the card, and
   the card always says why. Troy's condition on decision #4 is what
   turned this trap into a gate.
5. **The Windows firewall.** Turning on Reach without a rule produces
   the exact "connection refused from my phone" this slice exists to
   remove. Elevated: add the rule. Not elevated: print the one command
   and say so on the card.
6. **Loopback advertise.** A card that says "reach it at
   `127.0.0.1`" is worse than no card; the derivation already refuses
   loopback for enrolled nodes and must here too.
7. **Client keys and rotation.** A rotation revokes every client key
   at once; the card must say so when it happens, or every connected
   tool fails silently with a 401 the user cannot see.
8. **Two wizards' worth of state.** Enrolling on screen 1 means an
   abandoned wizard leaves an initialized, enrolled install with no
   models folder. Screen 2 must be re-enterable from Home ("Where
   should models live?" appears as the first card until answered).
9. **`install.sh` on Linux with a service prints no URL.** Fix in S0,
   or the first Linux hobbyist's first experience is a `systemctl`
   line.
10. **Measuring on the proxy path.** §8.2.

---

## 11. Implementation record

### 11.1 S0 — a reboot comes back working. DONE 2026-09-15.

Contracts `e953c74` (`AuthStatus.unlocked`, `AuthStatus.keyringAvailable`
on both `agent.yaml` and `control.yaml`); agent `1e062e4`, control
`b3961df`, `ui` `c16cf50` + `53f4bd4` (dist `5b87c01`); both installers
pin all three. Radius measured: the three consumers that codegen the
two documents re-pinned; gateway, inference-driver and library generate
from neither and did not move.

**Which claim was stale: the wizard's.** `setup/page.tsx` carried a
comment saying the control root "declares the same field… but nothing
in it reads either", and wrote `securityMode` to the agent alone.
Control has read it since 2026-09-10 — `_auto_unlock` at startup, the
store on login, the store-or-delete on the config flip — so every
install whose operator ticked the keyring came back with a **sealed
root** after a restart, on the word of a comment. The wizard writes to
both now, after enrollment, so the one session it holds verifies at
both.

**The default follows a measurement, not the platform.** `GET
/v1/auth/status` gained `keyringAvailable`: a write, read-back and
delete of a throwaway entry, run once per process in a thread with a
3 s budget (a present-but-locked Secret Service can block on a prompt
nobody will answer; past the budget the field is absent, not `false`).
The config test endpoint runs the same probe in place of a read that
could not tell a working keyring with nothing stored from a `fail`
backend. The wizard reads the field before it has a token and defaults
to `os_keyring` on `true`; on `false` the checkbox is disabled and one
sentence says Eugene will ask for the passphrase after every restart,
naming the file-based path for servers and containers. Two radios and
two paragraphs became one checkbox — *"Start Eugene on its own after a
reboot"* — and one line. A choice made before a tab refresh survives
the probe.

**THE FINDING THE BUILD MADE, and it changed the code in both
processes: the keyring entry was one slot per product.**
`eugene-plexus-agent` / `master-key`, shared by every install on the
machine. With the keyring the desktop default, a second install's
wizard — a `.dev-install` beside the live worker, or **every acceptance
run on this box** — would have overwritten the live install's stored
key, and the live agent would have come back locked on its next start
with a warning nobody was watching for. Control's `_auto_unlock` would
have then discarded a key it thought was its own. The entry name now
carries a twelve-hex fingerprint of the install's master-key salt —
unique per install, minted before the master key, stored beside it — on
both agent and control (same shape, deliberately not shared code). A
legacy single-slot entry is read once, moved under the scoped name and
deleted, written-then-deleted so a failure between the two leaves a
duplicate rather than nothing; a root that predates scoping still
auto-unlocks across the upgrade (tested). Deleting clears both names.

**`unlocked` is on the wire too**, on both processes: the sealed root
said in a word, for S7's Issues list to read instead of parsing a 503.

**Verification.** 18 new tests across the two Python repos (both
keyring suites memoise the probe to `false` under test so no test
reaches the developer's real Credential Manager); 3 new wizard tests
(the healthy fixture answers `keyringAvailable: false` so the existing
sequence tests keep seeing the default path). `scripts/m9-acceptance.sh`
gained **check 2b**: after the browser walks the wizard, every process
is killed and the agent started again from the same state directory
with nobody signing in; where the host reported a keyring it asserts
both processes were written `os_keyring`, the agent reports `unlocked`,
and control answers `/v1/nodes` with `200`; where it did not, it asserts
`prompt_on_startup` was kept and both came back sealed as documented,
then signs in for the rest of the run. Either branch is a record, not a
skip. It flips both back to `prompt_on_startup` afterwards, which
deletes the throwaway entries. **Ran green on this box on the second
execution: 45 checks, zero failures**, `keyringAvailable=True`, both
modes `os_keyring`, the agent unlocked and the root answering its
registry with nobody present — on ports +100 so the live worker's agent
on 8079 was never in reach.

**The first execution failed one check, and it was the harness.** The
script ran `npx playwright test` unfiltered, so the specs added since
M9 — the tree's declared-driver case, the diagnostic's chat model, the
folders' second agent — failed for want of what their own scripts stand
up (8 failed, 4 did not run, 14 passed, 4.9 min). And the M9 arc's own
Nodes check asserted a screen heading the tree redesign removed on
2026-09-13; nothing it tests had changed. The script now runs only
`e2e/auth-arc.spec.ts`; the check waits for the registry's *"This
install"* heading, which renders only when the root answered. Same
family as every other "the instrument aged" entry in this repo.

**Also:** the Linux installer's service path ended in a `systemctl` line
and no URL; every path of both installers now ends with the URL and the
log and config locations. **Trap recorded:** a GitHub archive for a
commit pushed seconds earlier answers 404 for up to a minute, so a
codegen run straight after `git push` fails once and passes on retry.

**Not done, deliberately:** S0 did not touch the wizard's screen count
(S2), and the `Done` screen's summary line still reads in the wizard's
old register. Nobody has restarted the *live* two-machine install under
the new default; the worker there is `prompt_on_startup` and stays so
until Troy flips it under Config → Agent.

### 11.2 S1 — Home, the tasks tray, and a tree that fits one machine. DONE 2026-09-15.

`ui` `71130c5` (dist `9486086`), pinned by both installers. **No
contract change, no codegen, no Python consumer moved.** Built by two
agents on disjoint files in one session, integrated and verified here.

**What landed.** `/` is **Home**, the install root's first page; the
playground is unchanged at `/playground`, its second. Home is the page
in §6.1 minus S4's, S5's and S7's cards: a *This machine* strip (name,
GPU memory, engine build, models on disk — each source soft), a
**first-model card** that is a state machine with one primary action
(*Get your first model* → Find a model / I already have models when
nothing is on disk; *Run a model* → Choose a model to run when models
exist and nothing routes; one sentence when the library did not
answer; hidden once something routes — S6's recommendation arrives as
one more state), a **Try it** card (model picker, one-line composer,
the first reply streamed in place, the exchange written into the
playground's own transcript so *Continue in the Playground* carries it
over — one definition of that sessionStorage shape now, used by both
pages), and a **Running** card from the join the Inference screen
uses. The **tasks tray** sits beside *The system* on every signed-in
screen: downloads, the library scan, models loading anywhere in the
install, engine installs on this machine; five-second poll, paused
while the tab is hidden; each task a link with a progress bar where
progress is known. The tree renders the **machine level only once the
install has more than one machine**: drivers straight under their
type, a single *Agent* leaf, no machine rows under Library, every
selection token unchanged; a driver naming a node the registry lacks
still counts as a second machine, so the flag from the tree design's
§14.2 never hides.

**What it does not discover:** engine installs on *other* machines (a
read per node per poll; deferred with the reason in the code). The
strip scores the machine the browser is served from, so on the NAS
root it reads "no GPU"; correct, and the Library's node picker remains
where a launch target is chosen.

**Verification.** 284 unit tests from 214 (the pure `tasks.ts`,
`home.ts` and transcript helpers, a jsdom Home render driving a
streamed turn end to end, the tray, ten new tree cases with four
sabotages confirmed failing). New `e2e/home.spec.ts`: sign-in lands on
Home with **no disabled text input anywhere** and one primary action,
the tray opens with its empty state and closes on Escape, the
playground exists one page over. `tree.spec.ts` asserts the one- and
two-machine shapes by reading the registry through the proxy rather
than the tree, so a wrongly collapsed two-machine tree cannot pass.
**`scripts/navigation-acceptance.sh`: 22 checks, zero failures**
(14 browser tests) on the second execution; **`m9-acceptance.sh`: 46
checks, zero failures**, the wizard landing on Home, on ports +100.

**The first navigation run failed one check, and it was timing.** The
page-menu test read `a[data-page]` the instant `goto` returned and got
`[]`; the menu renders after the setup gate answers, and Home carries
more script than the playground did, so the gate's fetch now outlives
the load event on `/`. The read waits for the first entry now. The
gate-before-shell order itself is unchanged from the playground and is
a candidate for S9 (render the shell during the gate), not this slice.

**Not done:** Try it has not streamed a reply in a browser — this
install has no routable model; `playground-diagnostic-acceptance.sh`
is where one is, and its spec was repointed at `/playground`. Nobody
has opened Home on the live two-machine install.

### 11.3 S2 — two screens, a picker, and a proposed folder. DONE 2026-09-15.

`ui` `4cac718` (dist `5994dff`), pinned by both installers; library
`1c0b062` (a test only, no pin). **No contract change.** Five screens
carrying about 565 words and one hand-typed filesystem path (§0.4) are
two.

**Screen 1 — "Choose a passphrase."** The passphrase, its confirmation
and S0's checkbox, under one short paragraph that replaces Welcome.
**Continue commits**: initialize, the components check, the trust
root, enrollment, and the `securityMode` written to both processes —
today's steps 1–4 and 3 — so screen 2 has a session and a picker that
can browse. There is no Back from screen 2; the install exists.

**Screen 2 — "Where should models live?"** *Make a folder for me*
proposes `<home>/Eugene Models`, where `<home>` is the `Home` entry of
the library's own `GET /v1/directories` listing and the separator is
the one the home path's shape implies — a pure helper, tested for a
drive letter, a POSIX root and a UNC path — editable behind *change*;
or *I already have models*, with Browse over the library's host and a
typed path. **"Nothing is created until the first download lands
there"** is true by two measured facts: `resolve_destination` never
checks a configured root for existence, and `_transfer_one` creates
the destination tree (`downloads.py:370`). The library gained one test
pinning the first, so a root-must-exist check added later fails a test
instead of turning a fresh install's first download into a 409. Finish
writes `modelRoots` and `firstRunComplete` and opens Home. If the
library cannot be asked, the proposal is disabled and the typed path
is offered — no dead end.

**Resume (trap 8).** One status read on mount decides the screen:
uninitialized → 1; initialized with a session → 2, nothing re-run;
initialized and already finished → Home, so a wander to `/setup`
cannot overwrite existing folders; initialized without a session →
sign in, with `/setup` as the return. The draft persists the choices
and never the passphrase. **A trap found by the tests:** the probe
effect must run exactly once — a per-render router identity re-ran it
after Continue and dropped a committed install back on screen 1.

**The backend flow left the wizard intact.** `/backends/add`, *Add an
app you already run*, reuses the provider form, the model picker and
the creation helpers, inside the shell with the install selected (the
navigation registry gained `ROUTES_UNDER_INSTALL`, tested for
disjointness and existence). Home's first-model card links to it in
both of its states; Inference's *Add an external backend* points there
instead of at Config. The plain-words test caught *"Local engine
runtime…"* in a provider label.

**Verification.** 307 unit tests from 284. The auth-arc e2e walks both
headings and asserts the proposed folder ends in `Eugene Models`.
**`m9-acceptance.sh`: 46 checks, zero failures**, and its check 2b
proved the keyring default written on screen 1 survives the
unattended restart — the two-screen wizard and S0 verified together.
**`navigation-acceptance.sh`: 22 checks, zero failures**, the new
route served. The one flaky Home assertion S1 left (the two cards swap
on separate state updates) waits for the swap now; five consecutive
runs green.

**Golden path after S0–S2** (the §0.2 table, re-counted by reading
the code, not yet by the click-counting run S10 will build): wizard
complete in **3 clicks and one typed value** (Continue, Finish, and
the passphrase typed twice) against 5 clicks and a typed path; the
landing page has a primary button instead of a disabled box. The
download-to-first-reply stretch is unchanged until S3 and S6.

**Not done:** the Home card *"Where should models live?"* trap 8 also
asked for, until the folder question is answered — the setup gate's
`firstRunComplete` bounce covers the case today. `fields.tsx` still
exports the unused `Radio`. The Library page still says *missing* for
a configured folder that the first download has not yet created; the
Home card's *"Nothing is on disk yet"* is what a fresh install sees
first, so the wording is a wart, not a wall.

---

### 11.4 S3 — one-click run, and what a fresh box taught the agent. DONE 2026-09-15.

`ui` `75fb2a0` (dist `ddd4db8`), pinned by both installers; agent
`df22e8c`, pinned by both installers; contracts `c0a6c06` (prose on
`HostAccelerator.acceleratorVersion`, nothing generated changed but a
docstring). **The library was not touched** — the design's "library
(implicit profile)" turned out to be nothing: the store already makes a
model's first profile its default, and the UI composes the profile it
would have made by hand. Decisions **#5** and **#6** as amended.

**What landed.** **Run** is one button, in three places: the Library's
model detail (above the profile editor, which is labelled *for experts*
now and whose empty state says Run will make the profile), a finished
download's row on Discover and Library (beside *open in the library*,
reading the entry off the record's `modelId`), and Home's first-model
card when exactly one model is on disk and an engine here reads its
format (*"Qwen3-0.6B-Q4_K_M is on disk and not running." → Run*). Run
is orchestration and nothing else — `ui/src/lib/oneClickRun.ts`, a
module-level store the header tray and the pressing card both render:
**checking** (which engines the target node has) → **the one question**
(only when no installed engine reads the format and one can be fetched:
*"I could not find llama.cpp on this machine. Install it now?"*, Install
focused as the default, Skip under the line that it is for advanced
users, Cancel/Escape abandons) → **installing** (the agent's own install,
polled with the bytes) → **settings** (a profile named `default` at the
context the node's admission dry run says fits, made only when the model
has none for this engine — the profile form's own prefill rule, lifted
to `lib/launchSpec.ts` so the two cannot disagree) → **launching** (the
declaration, or a `start` when a runtime for this file already exists,
which is exactly what Skip leaves behind) → **loading** → **ready — try
it on Home**. Skip declares the runtime with `autoStart: false` and the
Inference row prints the reason under `stopped (autoStart)`: *"llama.cpp
is not installed on this machine, so this cannot start. Install it above,
then press start"* — derived on the client from the node's engines, not
a new field. The tray gains a `run` task kind with a dismiss (the only
verb allowed there, because dismissing changes nothing on any
component), a red failure line that never truncates, and one line per
thing happening: while a run installs or starts, the tray's own
`install:` and `load:` rows for the same engine and runtime are
suppressed. **Nothing new on the agent or the library for the slice**,
as the plan said; every call existed. The `Launch profiles` section, the
Inference row's `start`, and the old sentence's Inference page are all
still there for the expert; the sentence *"Install one from the
Inference page"* is gone, and the Library says instead what Run will ask.

**Departures, recorded.** (1) *The run is browser-local.* A reload
loses the compound framing (install → settings → start → ready) and
nothing else: the install and the runtime are then visible through the
endpoints the tray already polls. The honest cost of "nothing new on the
agent"; a run record on the agent is the fix if it is ever wanted. (2)
*A failed install declares nothing.* The plan said the tray "names which
one failed", and it does; a runtime declared after a failed install
could only crash, so none is. Run again re-asks. (3) *Run on Home is one
machine.* Home is about the machine the browser is served from; another
node is chosen on the Library's picker, as before. (4) *A generation on
every run.* Ids are per model per node and reused, so an orchestrator
between two polls must not adopt a newer task with its id; found by the
tests when one test's held install leaked into the next.

**THE RUN FOUND THREE THINGS BEFORE IT COULD RUN ANYTHING, and two are
upstream.** A fresh box is made by pointing the agent's engine root at
an empty directory, and the first execution's step 3 read *"llama.cpp
is not installable here"* on this Windows/5090 box. **(a) Upstream had
moved the Windows CUDA build from 13.3 to 13.4 that afternoon** — every
release from b10983 (13:09Z) ships `win-cuda-13.4-x64` and no 13.3 — and
the adapter's hardcoded matrix (`_PUBLISHED_CUDA`, written from b10867)
had no 13.4-x64 entry, so a driver reporting 13.3 chose 13.3 and read
*"release b10990 has no asset for 'win-cuda-13.3-x64'"*: a sentence
about upstream's publishing presented as one about the host, and **the
live worker (on b10948) had read it all day**. A table cannot fail
loudly on an entry it lacks. Fixed by reading the candidate minors off
the release's asset names, and by a rule NVIDIA's rather than ours: when
nothing at or below the driver's minor is published within its major,
take the lowest published minor above it under **CUDA minor-version
compatibility**, and log it; a different major is still never crossed.
**Verified empirically before it was coded:** b10990's 13.4 build was
downloaded by hand, loaded the 1.8 GB Qwen3-1.7B Q8 on this 13.3 driver
with every layer on `CUDA0`, `model loaded` at 1.6 s, and served a
completion (the build carries SASS for arch 1200, which is what the
guarantee needs). **(b) Forty minutes later the same check read "not
installable" again, for a different reason**: upstream had published
b10991 at 23:42Z and its CI had uploaded **five of thirty-three**
assets — a cudart for 12.4 and no server build — so *"the newest build
that has assets"*, the rule the 2026-09-12 b10931 finding left behind,
picked it and every host read *"publishes no Windows CUDA build for
x64"*. A release is complete for a host only when it carries THAT host's
assets; a count says nothing about which. `plan_latest` now plans
against the newest build and, when the only obstacle is an asset that
build lacks (`Unavailable.release_bound`), steps back up to eight builds
— about a day — logging *"b10991 has no 'win-cuda-13.4-x64' asset yet (5
asset(s) up; upstream's CI may still be uploading); using b10990"*; a
refusal about the host (Linux with NVIDIA, a driver with no CUDA
version) still stops at once. `latestVersion` keeps meaning the newest
build known (b10991) while the install fetches b10990, and the tray
names the build it installs. Sixth and seventh entries in M1's list of
upstream traps; 44 acquisition tests, both rules sabotage-checked. **The
step-back is unit-tested against b10991's five-asset shape as the run
saw it and has not fired live**: by the time the fix was in, b10991's
upload had completed and the recorded run installed it directly.
**(c) Four runs asserted about a build no browser ever saw.** Home's
card kept rendering the S1 wording while the pure state function, the
compiled bundle and the real bodies (captured by a diagnostic the
browser test now prints on failure) all said Run should be there. The
agent venv's `eugene-plexus-ui` was **a wheel installed from `ui/dist`
at 15:39**, not the editable install CLAUDE.md said it was, so the agent
served that afternoon's build; and the script's check *"the staged
bundle carries the run dialog"* grepped the staged directory rather
than what the agent serves — the recurring shape, a check looking
somewhere its subject had not arrived. The run now asserts that
`eugene_plexus_ui.static_dir()` in the agent venv IS the staged
directory and that a chunk the served `/` names carries the marker;
`navigation-acceptance.sh` got the served check too, because S1's and
S2's green runs rested on the same assumption. **A fourth, mine:**
editing an acceptance script while bash is still running it — bash reads
incrementally and died on a shifted line with `EXIT 2` and the fleet's
ports still held.

**Verification.** UI: 350 unit tests from 307 (`oneClickRun.test.ts`
drives the orchestration against the bodies the components return, in
call order — install before profile before runtime, Skip's `autoStart:
false`, a 422 relayed verbatim, cancel touching nothing; `launchSpec`,
the merge, the dialog, Home's one-model card). Agent: 566 tests, mypy
clean. **`scripts/one-click-run-acceptance.sh`: 26 checks, zero
failures, on the seventh execution** (the six before it were the three
findings above and two harness defects): a fresh box (empty engine root,
`llama-server` off PATH), the model downloaded from the hub through the
library, Chrome driving Home's Run, the finished download's Run, Run →
Skip → `stopped` on Inference with the reason, Run → Install → a real
llama.cpp fetched into the run's own engine root → the same runtime
started rather than a second declared → `ready`, 15.3 s after
pressing Install (the two assets, 570 MB, the unpack, the start and the load) → the first reply on Home; then exactly one profile named
`default`, one runtime, the alias on the gateway, a completion through
it. Record: this section; the runner and `e2e/one-click-run.spec.ts`.

**Golden path after S0–S3**, from a finished download to a first reply
(§0.2 counted 15 clicks, 6 route changes and a typed path; 19 when
llama.cpp had to be installed): **Run · Install · Send** — three clicks,
one route change (Home), nothing typed. Without an engine to install,
two. Still by reading the code, not by S10's click-counting run.

**Not done.** The run store is per tab (departure 1). ~~The recommended
model in the first card is S6~~ — **done 2026-09-16, §11.7**, though as
a separate Download button rather than chained into Run. A person with
several models on disk still chooses in the Library. The dialog has no focus trap
beyond autofocus. The Inference reason is derived and so appears only
once that node's engines have loaded. `role="dialog"` and the tray's
dismiss have no browser test. Whether the run should re-ask about
installing on a node that refused once is left to the person: it does.
The live worker still runs b10948 and still needs the upgraded agent
before *update* offers it b10990.

### 11.5 S4 — a key you can hand out, and a key you can take back. DONE 2026-09-15.

Contracts `f794916` (`agent.yaml`: four operations, five schemas;
`gateway.yaml`: prose); agent `e0ec0fc`, gateway `079d9bd`, control
`2ea881b` (regen-only), `ui` `b9e617c` (dist `b44c7db`); both installers
re-pinned. `library` and `inference-driver` codegen neither document and
stay a pin back, correctly. Decision **#7**.

**What §0.8 had measured.** The hobbyist's second job — pointing an app
they already use at the install — had no path. The only bearer on offer
was the **operator session token**: authority over every component,
reachable only from the playground's diagnostic panel nineteen clicks
in, dead fourteen days after sign-in. `tailnet.md` said so in as many
words — *"There is no long-lived client key yet."* And §3's
sixth-commonest failure across every comparable project (the `/v1`
suffix, a key field that must not be empty, the exact model id) had the
three strings shown nowhere together.

**What landed.** `POST /v1/auth/client-keys {name, ttlDays?}` on the
agent mints a JWT with the install's signing key, `aud: client`, a year
by default. `GET` lists the records, `DELETE` revokes one,
`GET .../revoked` serves the ids the gateway polls. Home gains **Use it
from your apps**: the address (with `/v1`), the model id, **Make a key**,
the live keys with **Turn off** beside each, and seven recipes —
Continue's `config.yaml`, Cline's settings, Open WebUI's connection,
SillyTavern's custom endpoint, OpenCode's `opencode.json`, the
`OPENAI_BASE_URL`/`OPENAI_API_KEY` pair every SDK reads, and `curl` —
each naming **where** the value goes. The diagnostic panel mints one
too, and stops describing the session token as the thing to give a
harness.

**The audience does its work by shape, not by a list anyone maintains.**
`client` is neither `operator` nor a `service:` audience, and every
check in every component tests for one of those two — so the agent, the
control root, the library and the gateway's own config, admin and
metrics paths refuse a client key **without having been taught it
exists**. Exactly one place opts in: `accept_client=True`, passed by
`require_authorized` and nowhere else, so an endpoint added later is
safe by omission rather than by vigilance. Thirteen live checks and
eight unit tests hold it down, including through
`require_operator_or_service` — the dependency a new endpoint is most
likely to reach for, and the one that accepts *any* service token.

**Revocation went the first way the plan offered, and the second way
would have been a lie.** The plan allowed "the list is informational,
revocation is the existing signing-key rotation". That makes a **Turn
off** button that turns nothing off — P4's silent failure — and it makes
a key per app pointless, since revoking one would revoke every session
and every node's credential at once. So: the record file keeps a
revoked stamp, the gateway polls `GET /v1/auth/client-keys/revoked` from
**its own node's agent**, caches it for the routing refresh interval,
and refuses a matching `jti`. Three properties, each deliberate:

- **Cached, not asked per request.** A round trip per completion would
  put the agent in the inference path, which the two-layer split exists
  to avoid. Revoking bites within about one refresh interval; the
  contract says that rather than promising instant. Measured live at
  **3 s with a 3 s interval**.
- **Fail-open on the list, never on the token.** An unreachable agent
  leaves the previous answer in place and requests keep being served:
  taking every harness in an install down for the length of an agent
  restart is a worse failure than a revoked key living fifteen seconds
  longer, and the token still needs a valid signature and an unexpired
  `exp`. A gateway that *emptied* the list on a failed read would
  un-revoke everything on the first blip, which is the shape that makes
  fail-open indefensible — there is a test for exactly that.
- **Nothing is fetched until a client key arrives.** An install where
  nobody minted one never makes the call.

**Where the record lives is the multi-node answer.** A client key is
install-wide — one signing key, so a key minted anywhere verifies
everywhere — but its *record* is not. It lives on the agent that minted
it, and the gateway asks its own node's agent. So the UI mints against
**the node the gateway runs on**, resolved from the control root's
placement view and reached through `node:<name>`; the card names the
machine. Nobody opens a browser over there
(`one-console-never-hop-nodes`). A root that did not answer falls back
to the local agent, which on a standalone install is the same thing.

**The token is never stored.** `client_keys.json` beside `agent.yaml`
keeps name, created, expires, revoked and the token's **tail** — six
characters off the *end*, because every JWT this install mints begins
`eyJhbGciOiJIUzI1NiIs` and a prefix identifies nothing. A live check
greps the file, the config files and the list response for the token and
finds it in none of them. Its own file rather than `agent.yaml` for two
reasons: `AgentState.set_passphrase` replaces the whole `auth` block,
and a growing list does not belong in a document the config trio serves.

**Departures, recorded.**

1. **Claude Code is not in the recipe list, and the plan named it.** It
   takes `ANTHROPIC_BASE_URL` and speaks the Anthropic Messages API at
   `/v1/messages`; this gateway serves the OpenAI shape at
   `/v1/chat/completions`. A recipe for it would 404 for everyone who
   followed it. A test asserts its absence so nobody adds it back from
   the plan. **Serving `/v1/messages` is a real thing to want** — it is
   the one shape a whole class of harnesses speaks — and it is a slice,
   not a snippet.
2. **The list shows a tail, not a prefix.** The plan said "names,
   prefixes and expiries". See above.
3. **`hobbyist-acceptance.sh` does not exist yet** (S10), so this slice
   has its own script. S10 absorbs it.
4. **`lastUsedAt` is on the contract and nothing writes it.** The agent
   never sees a client key — the gateway does — and a *last used* the
   install cannot observe would be worse than none. The field is in the
   shape so a future gateway-side counter has somewhere to land.
5. **No "never expires".** A ten-year ceiling, a one-year default. A
   token with no expiry at all leans entirely on a bounded-staleness
   revocation list.
6. **The address is still a guess.** Same derivation as the diagnostic
   panel's — the page's host plus the gateway's port from the topology —
   wrong on the container install by exactly as much as a harness handed
   the same numbers would be. It is labelled, and editable, and the
   correction is remembered per browser.

**THE RUN'S FINDINGS WERE ALL ABOUT THE HARNESS, AND TWO OF THEM WOULD
HAVE PASSED AS PRODUCT DEFECTS.**

**(a) A check that reported a defect that was not there.** Execution 1's
*"the control root refuses a client key"* failed — and the control root
was **uninitialized**, so it was 503ing every path and had never looked
at the audience. A refusal is not evidence of the refusal you meant. The
script initializes the root now, and the failure message names 503 as
the case that proves nothing.

**(b) A 401 from one component signs the operator out of another, and
that is real.** Executions 2 and 3 failed every browser test at sign-in
against a form that had just succeeded: login 200, navigate to Home,
then `GET /api/proxy/control/v1/runtimes` **401**, and `lib/api.ts`
treats *any* 401 as "this session is over" — it clears the token and
bounces to `/login`, after which the agent's own reads 401 for the
honest reason. The root cause was the install shape execution 1 had
created by accident and execution 2 made worse: **the control root
initialized while the local agent was not enrolled**, which is M9's
finding exactly — an unenrolled agent mints a fresh random signing key
per restart while the root mints the install's, so the root refuses
every session the agent issues. Fixed in the script by enrolling, which
is what M7 settled every node does and what the wizard has done since
M9. **Left standing, and worth knowing: the interceptor's rule is too
broad.** A 401 from the control root is not evidence about the agent
session, and on a degenerate install it logs a working operator out of a
working console. Not fixed here — it is the auth path of every screen
and not S4's to change on the way past.

**(c) A form that is inert until it hydrates.** `output: export` serves
the login form as static HTML, and React replaces it on hydration with a
controlled input whose state is `""` — so a `fill` landing between
"visible" and "hydrated" is silently discarded, leaving a filled-looking
form that submits nothing and a disabled button. The accessibility tree
in the failure artifact showed it: an empty Passphrase box and
`button "Unlock" [disabled]`. The spec's sign-in asserts the value stuck
and re-fills until it does. Same family as M9's *"`isVisible()` does not
wait"* and S1's *"the page menu renders after the setup gate"*, and
**the other four browser specs share the un-fixed helper** — they have
not flaked yet, which is not the same as being right.

**(d) A browser cannot observe the 401 it was written to expect.**
`/v1/config` deliberately answers no CORS, so Chrome blocks the
cross-origin fetch before a status exists and `fetch` rejects; the spec
asserted `401` and read the correct behaviour as a failure. It accepts
either refusal now and says why, and the script's `curl` — which does
not enforce the same-origin policy — is what pins the 401.

**Verification.** Agent: 601 tests (35 new), four sabotage-checked, mypy
clean. Gateway: 232 (20 new), five sabotage-checked — the first version
of that file patched the guard's `_fetch`, so the fail-open branch was
asserted about rather than run; it uses an `httpx.MockTransport` now, and
that change found the **401 case**, where a guard catching only
connection errors would parse the agent's refusal as an empty list and
silently un-revoke everything. UI: 371 tests (21 new), four
sabotage-checked. **`scripts/client-keys-acceptance.sh`: 45 checks
(52 `PASS` lines), zero failures, fourth execution** — a real fleet with
a real model, a key minted through the API and through the browser, a
completion carrying only that key, thirteen refusals across four
components, a revocation biting in 3 s, a second key still working after
it, and both surviving a restart of the agent because an enrolled node
keeps the install's signing key.

**Golden path after S0–S4**, from a finished download to a connected
app: **Run · Install · Send**, then **Make a key · Copy · paste**. Still
by reading the code, not by S10's click-counting run.

**Not done.** The address guess is not corrected automatically on a
port-remapped install — the person types it once. Nothing records when a
key was last used (departure 4). `ttlDays` is not exposed in the UI; the
card always takes the year. There is no "rotate this key" that mints a
replacement and revokes the old one in one step. The revoked-list poll
has no live proof at the contract's default 15 s interval — the run uses
3 s so the check is a run rather than a wait. And **nobody has pointed a
real Continue, Cline or Open WebUI at a real install with one of these
keys**; the recipes are asserted against their documented shapes, not
against those products.

---

### 11.6 S5 — three things have to be true, and now three lines say which. DONE 2026-09-15.

Contracts `a80e169` + `6ff4f96` (`agent.yaml`: one operation, eight
schemas, one field on `NodeIdentity`); agent `dfbd178` + `ef7511d` +
`f9cc927`, control `ff71f75` (regen-only), `ui` `d74ce6f` (dist
`0cd34cb`); both installers re-pinned. `gateway`, `library` and `inference-driver`
codegen neither document and stay back — measured by regenerating, not
by reading the diff. Record:
[`../acceptance/reach-run.md`](../acceptance/reach-run.md),
**39 checks, zero failures, second execution**. Decision **#8**.

**What §0.9 had measured.** The hobbyist's third job — opening the
install from a phone or a laptop — had no surface at all, and the
symptom of every way it can fail is the same: *connection refused*. A
standalone install answers only `127.0.0.1`, nothing says so, and the
person cannot tell whether the fault is Eugene, the firewall, the
router or the address they typed.

**What landed.** `GET /v1/node` carries `reach`, and
`POST /v1/node/reach` is the switch behind Home's **Reach it from other
devices**. Three things have to be true, each fails on its own, and each
now gets its own line, its own remedy and its own source of evidence:
something is listening off loopback (`boundAddresses`, from the value
each process was handed at bind time), the node advertises that address
(`enabled` / `advertiseUrl`), and the host firewall lets the connection
in (`firewall`, through `HNetCfg.FwPolicy2`). `lastReachedFrom` is the
fourth thing and the only *proof*.

**The plan's first sentence was wrong, and it is the measurement the
slice turns on.** *"Proposes the LAN address the agent already
derives"* — the agent derives that address from the local end of a TCP
connection **to the control root**, which on a tailnet is exactly the
interface the root can reach back on and on a **standalone install is
`127.0.0.1`**, because the root is on loopback. The one address that
cannot be it. `reach.proposed_host` is a second derivation for the
person S5 is for: a UDP socket connected to TEST-NET-1, which sends no
packet — the kernel picks a route and binds a local end — so it costs
half a millisecond, needs no network, and answers on a machine that has
never enrolled and never will.

**COM, not the cmdlets, and not on style.** Measured unelevated on this
host: `Get-NetFirewallPortFilter` raised *Access is denied* **and
returned a truncated list on the way out**, so a cmdlet-based detector
reports "nothing covers our port" from a partial read. `HNetCfg.FwPolicy2`
enumerated all 708 rules with no error, in **78 ms** against ~2.8 s for
three cmdlets — before a PowerShell subprocess has started. §6.6
budgeted "a few hundred milliseconds" and worried about caching; at
78 ms the read happens with the node view.

**THE FINDING WITH THE LONGEST REACH: this machine is allowed by a
PROGRAM rule, and there is no rule mentioning its ports at all.** The
live worker is probed successfully by the control root every fifteen
seconds, and no enabled rule names 8079 or 8080. What allows it is an
inbound allow for
`%LOCALAPPDATA%\EugenePlexus\pythons\cpython-3.12.14-...\python.exe`,
created by Windows' own *Windows Security Alert* dialog the first time
the agent listened off loopback in an interactive session. **A port-only
detector — which is what §6.6 specified — would have reported `blocked`
on a machine that demonstrably is not.** So program rules count, and
`FirewallPort.scope` says which kind decided, because that program is a
**versioned** path: the allow a person clicked once stops applying the
day the interpreter is upgraded, with nothing anywhere saying so. A rule
*we* add is scoped to ports, which is §6.6's advice kept for the half it
was right about.

**`NotConfigured` means block.** That is what `Get-NetFirewallProfile`
reports on a stock machine, while the COM property returns
`NET_FW_ACTION_BLOCK`. Compare the cmdlet's string to `"Block"` and a
blocking machine reads as not blocking. `DefaultInbound` has `unknown`
as a third member so the distinction survives into the contract.

**The agent's own socket cannot follow the setting, and saying so is the
design.** A listening socket is fixed for the life of a process.
Supervised components take their bind host from the environment at
spawn, so restarting them is the whole of their half and the switch does
it — the gateway answers on the LAN address within seconds, with no
agent restart. This agent does not, and reporting success there would be
exactly the silent failure the slice exists to remove:
`restartRequired` is true until the socket and the setting agree, and
`AgentRestart` says whether this agent can arrange its own restart and
what to type when it cannot.

**A restart asks this agent's own supervisor**, and never spawns a
replacement. A detached copy would not be a child of the service or the
task, so the next boot would start a *second* agent onto a port the
orphan holds — the stacking failure `ports.py` exists to diagnose,
manufactured on purpose. `restartAgent` is opt-in, because the browser
making the call is talking to the process that would go away, and it is
refused outright where nothing would start the agent again: **a browser
click must not be able to end an install.**

**`lastReachedByRoot` was contracted and then replaced, on the second
day of its life.** The agent cannot observe it, and the control root
already records the same fact as `Node.lastSeenAt` — a second copy on
the node would be a second source of truth. What the agent *can*
observe is better for the person this is for: the last connection from
anywhere other than this machine, whoever made it. On a standalone
install there is no root probing from elsewhere, and the phone the card
told them to try is both the test and the evidence it passed. Not
persisted: it describes this process, and a restart is exactly when
somebody wants to know whether reach still works rather than whether it
once did.

**A connect probe was written for `boundAddresses` and thrown away.**
Probing this host's own address to see what is reachable conflates two
answers — a closed local port on Windows is **dropped, not refused**
(362 ms to time out against 6.6 ms for an open one), and a connection to
the host's own LAN address is evaluated by the firewall, so a failure
could not say whether the bind was narrow or the firewall shut.
`restartRequired` hangs off that answer, and telling somebody to restart
Eugene when the problem is a firewall rule is precisely the confident
wrong advice this card exists to avoid. The bind value is exact, free,
and is the property being asked about.

**Departures, recorded.**

1. **`NodeReach`, beside `LibraryFolderReach`.** One word, two meanings
   in one document: that one asks whether *this node* can open a folder
   elsewhere, this one whether elsewhere can open a socket *here*. Both
   schemas say so in prose. Renaming either would be worse than the
   collision.
2. **The switch does not restart the agent by default**, and the plan's
   "restarts what must restart" reads as though it would. See above.
3. **Linux and macOS print the command rather than running it.** Adding
   a rule needs root on both, and the two ways for a web server to have
   root are a password prompt it has no terminal for and a permanent
   sudoers entry. Windows is the exception because an elevated service
   already has the right and an unelevated logon task can raise one UAC
   prompt on a desktop it demonstrably has.
4. **`install.ps1` does not add the rule when elevated**, which the plan
   said it would. The switch does, and an installer that opens a port
   before anybody has asked to share anything is the opposite of the
   default this slice is about.
5. **No Config-page switch.** The plan said "on Home and on the agent's
   Config". Config already has `advertiseUrl`, which is the expert
   override and must stay the thing that wins; a second control writing
   the same field from the same page would be two front doors one click
   apart. Instead the two **cross-link** — `cross-link-related-settings`,
   Troy's standing rule — with a test on the link.

**THE RUN'S ONE NOTE WAS A DANGEROUS DEFECT, AND THREE SABOTAGES
ESCAPED.**

**(a) A note that should have been a check.** Execution 1 printed
`canSelfRestart=True` for a throwaway agent started from a shell, in
this checkout's own virtualenv, on ports +100 — because the **live
worker install on this box owns a scheduled task by that name**, and the
detector asked only whether one existed. Pressing the card's restart
there would have run `schtasks /End /TN "EugenePlexusAgent"` against the
operator's real agent: stopping the live install and starting it again
while the throwaway kept its ports. Nothing was harmed because nothing
in the run asked for a restart — luck, not design. Same family as the
step-7 finding where a throwaway agent inherited the live install's
identity through the user environment. **A machine can hold two
installs**, and the rest of this codebase knows it: `keyring_store`
scopes its entry by install (S0), and every script since 2026-09-12
clears `EUGENE_PLEXUS_*`. Fixed by matching the task's program against
this process's **`sys.prefix`** — not `sys.executable`, which in a
uv-made virtualenv is the base interpreter under `pythons\cpython-...`,
outside the prefix and shared between installs, so comparing it would
call the real install's own task somebody else's. Verified both
directions on this box. `launchd` had the same shape and now requires
the parent to be pid 1. And the note is a check: **a note is what you
write when you do not want to decide**, and deciding it is the whole
reason to run on a box that also holds a live install.

**(b) Three sabotages escaped, all the same mistake** — the test
exercised a pure helper rather than the function that uses it. Removing
the `canSelfRestart` guard from `restart_argv` passed 34 tests, because
the only case asserted was `mechanism: none`, where no branch matches
and the guard is redundant; the case that matters is a mechanism
detected while its tool is absent. Replacing
`_windows_task_runs_this_install`'s body with `return True` passed 36 —
undoing (a) in the session that fixed it. Loosening the prefix
comparison to its **parent** passed 36, because the only negative case
was a task under another user's home; a negative case has to be near the
positive one. Same family as M10's check 7, step 6's fragmentation
checks and the navigation slice's `/librarian` case.

**(c) The run proves the bind, not reach, and says so.** Check 8 loads
the UI from `192.168.16.75` while check 10 reports that port `blocked`,
in the same run — because host-local traffic is not filtered by the host
firewall. Not a contradiction: §6.6's thesis reproduced. The only proof
is from outside, which is what `lastReachedFrom` is for and why the card
never dresses a firewall verdict up as one.

**Verification.** Agent: 639 tests (38 new), three sabotage-checked
after two escaped and were covered, mypy clean. UI: 392 tests (21 new),
four sabotage-checked, tsc and eslint clean. Control: 127, regen-only.
`scripts/reach-acceptance.sh`: **39 checks, zero failures, second
execution** — four processes with **nothing declared about binding**, so
the run tests the default rather than a value.

**Not done.** Reach from a genuinely second device (the run is one box).
`blocked → allowed` needs administrator rights and is `EP_FIREWALL=1`,
skipped and reported as skipped. Nobody has clicked Yes on the UAC
prompt. The Linux and macOS detectors are written, unit-tested and never
run against a live `ufw`, `firewalld` or `socketfilterfw`. No self-restart
has actually been executed — every mechanism's argv is asserted, and the
run restarts by hand, which is what the card tells an unsupervised
install to do. A third-party firewall registered with Security Center
turns every verdict `unknown`, and that branch is unit-tested only
because this box has none.

**Next: S6** (Discover recommendation-first, and the starter-model
review from §6.5) — **done 2026-09-16, §11.7.**

### 11.7 S6 — a suggestion before a search box, and the review that keeps it honest. DONE 2026-09-16.

Contracts `e130f36` + `2eb8afa` + `8a1abc9`; library `ec8c5dd`, `ui`
`5faad3e` (dist `d9f35c1`); both installers re-pinned. Gateway, agent,
control and inference-driver codegen neither document and stay back.
Record: [`../acceptance/starter-set-run.md`](../acceptance/starter-set-run.md),
`scripts/starter-set-acceptance.sh` — **41 `PASS` lines, zero failures,
third execution**.

**The shape.** `GET /v1/catalogue/starter` serves the list scored
against one machine, and it makes **no upstream call at all**: every
number a fit needs — the recommended file's size, the parameter count,
the layer and attention counts, the trained context — was measured once
by the review that produced `starter_models.yaml` and is carried in it.
The screen where someone picks their first model is not the screen that
fails first. `starterModelsFile` replaces the list, an empty one is a
valid "no recommendation", and no model name appears in the library's
source.

**Discover opens on it.** With nothing typed the screen is one card
naming the model this machine should take — with the sentence that says
why, and a Download button — above the rest of the set, rather than
whatever the hub sorted to the top today. A repo detail is the same
shape one level down: one suggested version with its own button, and
every other version under **All versions**. A pasted hub link resolves
to one repo and the screen selects it. Every verdict reads *fits at
32k*, and the context control moved from the window header to beside the
verdicts it governs.

**Home's empty-disk card gained a state of its own**
(`no-models-recommended`), which is what the card's S1 comment predicted
it would: one primary button that fetches a named file instead of
opening a catalogue.

#### ▶ THE FINDING WITH THE LONGEST REACH IS NOT ABOUT DISCOVERY: the KV cache was 43× too large on a mainstream 12B

The first accepted list scored its 12B as **partial offload** on a
29 GiB card while the 27B beside it read **fits**. The file declares
`attention.head_count_kv` as **an array of 48** — eight heads on five
layers of every six, one on the sixth — and five of every six layers are
sliding-window with their own shorter key and value lengths and a
1024-token window. `shape_from_gguf`'s scalar reader returns `None` for
a list and falls back to `head_count`, which is the pre-grouped-query
assumption, and nothing read `sliding_window_pattern` at all:

| context | scalar arithmetic | per-layer truth | over |
| ------- | ----------------- | --------------- | ---- |
| 4k      | 6.0 GiB           | 0.375 GiB       | 16×  |
| 16k     | 24.0 GiB          | 0.562 GiB       | 43×  |
| 256k    | 384 GiB           | 4.31 GiB        | 83×  |

**And it reported `basis: metadata` throughout**, because the layer
count *did* come from metadata — only the load-bearing term did not.
That is the failure this project keeps recording in other places: a
confident answer with no note saying which of its terms was guessed.

Built: `ModelShape.layers`, a per-layer form that wins over every
scalar; `kv_terms()` so `max_context_that_fits` solves an **affine**
cache rather than a linear one, since a sliding layer stops growing at
its window and the cache is therefore a line with an intercept; and a
run-length layer table in the starter file (`[count, heads, key, value,
window]`) so a person accepting the review's proposal can read the
pattern. It is the same *class* of defect `attention_layers()` was
written for at M3 — one architecture generation on, which is the reason
to expect a third.

**It is also why the acceptance script's context check had to be
rewritten.** It asked for the recommendation at 4k and 256k on a 12 GiB
card and expected them to differ; they do not, correctly, because a
sliding-window model's fit is nearly context-independent. A check that
assumes a linear cache is a check asserting the arithmetic this slice
replaced. It asks on a 24 GiB card now, from a measured table.

#### The hub does not answer 404 for a repo that does not exist

Check 7 of the first run wanted a 404 for a pasted URL naming nothing
and got 403, and the bare-`owner/name` fall-through raised instead of
searching. Measured: `GET /api/models/nobody/nothing` answers **401
`Invalid username or password`** — to an unauthenticated caller "gone"
and "private" are deliberately the same answer, an enumeration defence.
So "could not resolve" is 401, 403 and 404 together, and the 404 this
endpoint returns names all three causes instead of asserting the one it
cannot tell from the others. A gated repo keeps its own 403 and its own
advice, because accepting a licence is something an operator can do.

**The unit test passed against the broken code**, because its fixture
returned the 404 the contract described rather than the 401 the hub
sends. Fixtures invented from a contract test the contract.

#### A codegen hazard the contract change walked into

`datamodel-code-generator` names an inline enum after its property, so
`StarterSet.source` took the name `Source` and renamed the existing one
— `MemoryBudget.source`, `detected|override` — to `Source1`. Every
`Source.override` call site in the library broke, at a site the contract
change never mentioned. Found by regenerating and diffing the class
names, not by reading the spec diff. The fix is a named
`StarterSetSource`, and the schema says why, because the next inline
enum in that document will do it again.

#### Calls taken in the build

**One quant per class, family before width**, and the reason is
measured: at a 4.8-bit target the first review chose `IQ4_XS` and
`Q4_0`, both within 0.1 bits of `Q4_K_M` and neither the file to hand a
stranger. **The repo is chosen with the quant, not before it** —
`ggml-org`'s gemma repo ships no K-quant at all. **A single-mirror
leader is flagged**, which is why the 70B class shipped empty: one repo
is a publisher, not a consensus. **A de-aligned derivative is never a
default** — not a judgement about whether they should exist, but a
default is the one place this project's own choice shows, and shipping
an abliterated model to someone who did not ask for one is a choice made
for them. **On a machine with no accelerator the recommendation inverts
to the smallest**, because "fits" is a question about memory and the
question a person on a CPU actually has is about speed: 16 GB of weights
fits comfortably in 32 GB of host memory and generates at a couple of
tokens a second, which as a first sentence out of this software is
indistinguishable from broken. The guidance record already has this
mistake once, in the other direction.

#### Not done

~~**§6.3's single "Download and run" is not built**~~ — **closed the
same day, §11.8.** It shipped here as two actions, which asked the
person twice; the answer to "what happens when the browser is closed
across a 16 GB download" turned out to decide the design, and it is that
the intent belongs on the download record rather than in a browser-side
store.

Nothing is downloaded by this run: the set's sizes and filenames are
asserted, and no starter model has been fetched and launched end to end
(`one-click-run-acceptance.sh` fetches a different repo). The review's
**CPU-token proof** is unbuilt — the architecture check alone runs, and
the report says so. The **hysteresis has never fired**: this is the
first review, so every class was `REPLACE` from an empty list once and
`KEEP` since, and the two-consecutive-months path is exercised by unit
tests and nothing else until October. The monthly workflow has not run
on a schedule yet. And Discover's **search rows** still carry no fit
verdict, which is upstream's constraint rather than ours and is stated
on the endpoint.

### 11.8 §6.3 — one action, and one that survives the tab. DONE 2026-09-16.

Contracts `6e860bf` + `3d7921c`; library `fd7aeb7`, `ui` `1157da6` (dist
`32ba5f4`); both installers re-pinned. Record:
[`../acceptance/download-and-run-run.md`](../acceptance/download-and-run-run.md),
`scripts/download-and-run-acceptance.sh` — **28 `PASS` lines, zero
failures, second execution**.

**What it closes.** S6 left Home offering **Download**, with S3's
**Run** taking its place when the file landed. Every step existed; the
orchestration §6.3 calls "the slice" did not. So the person was asked
twice, and the second ask arrived minutes later.

**The hard half was never the chain.** Joining four calls in a browser
store is an afternoon. What decided the design is that a 16 GB transfer
outlives the tab that asked for it, so a store in the browser is a store
that forgets. Four places the intent could live were considered and
three rejected:

- **The browser, reconstructed on load.** Cheap, and wrong: it cannot
  tell a download someone started *in order to run* from one they
  started to keep, so it would launch things nobody asked to launch.
- **The agent.** It would have to drive the library's downloader, which
  is a component it supervises and does not command.
- **The library, acting on it.** The library cannot launch — a launch is
  a profile, an engine and a runtime on some node's agent — so it would
  have to call the agent, which is the boundary backwards.
- **The library, RECORDING it.** `runWhenReady` on the download record;
  the library never acts on it. The durable half lives beside the
  durable thing, and the interactive half — the engine question — stays
  where a person is. If nobody ever opens a browser again, nothing
  happens, which is correct, because the chain contains a question.

**`POST /v1/downloads/{id}/claim` is the other half, and it is not
bookkeeping.** Two browsers are two browsers: every console on the
install can see the same finished download, and without an atomic clear
every one of them would create a profile and launch a runtime for the
same model. It is also what stops a *deliberate* stop from being undone
— a console opening a week after someone stopped that runtime on purpose
would otherwise see the same intent and start it again. Idempotent by
construction, because a client that retried after a timeout has not done
anything wrong.

**One tray entry**, which is §6.3's actual words, and it needed no new
mechanism: a run already claims the tray's `install:` and `load:` rows
while it owns those steps, and the download row joins them. The browser
check asserts the count is exactly one.

**`findRunFor` scans rather than looking up by key.** A chained run is
filed under its *download's* id, because the model does not exist until
the file lands and the library's post-download scan names it — and the
moment it does, the Library and Home would otherwise offer Run for a
model the task above them is already running.

#### The one defect, and it was the harness, twice

Both browser passes of the first execution failed on
`getByTestId('home-try-it').locator('textarea')` — **Home's composer is
an `input`**. Sixty seconds of waiting for an element that does not
exist, in both passes, while the API checks in the same run reported the
runtime `ready`, the profile made, llama.cpp installed, and *"a runtime
exists that no human asked for in this browser"*. The product did the
whole job both times and the test could not see it. Same family as M10's
check 7.

#### Not done

The run arranges the closed-laptop state **through the API** — a
finished download with its intent still set — rather than by killing
Chrome mid-transfer and reopening it. The state the console meets is
identical; the path to it is not. Two consoles racing is asserted as two
sequential claims, not two simultaneous ones. A chained run targeting
another node (`node:<name>`) is unit-tested and has never been executed:
Home runs models on the machine the browser is served from, and this box
is one machine.

### 11.9 S7 — measured, one contract field landed, then built and pinned. DONE 2026-09-16.

**State: DONE — built, shipped and live-verified.** All seven steps taken
on 2026-09-16, though **6 came after 7**: the pins went out first at the
user's direction and the acceptance run followed. It found one thing in
that day, which is about the rate every other acceptance run here has
found. `scripts/issues-acceptance.sh`, **20 PASS lines, zero failures,
one deliberate SKIP, second execution**; record
[`../acceptance/issues-run.md`](../acceptance/issues-run.md).

| Repo      | Commit    | What it carries                                                  |
| --------- | --------- | ---------------------------------------------------------------- |
| `specs`   | `4a72644` | `NodeIdentity.time` on `agent.yaml`                              |
| `agent`   | `763d10d` | serves it, two tests, both sabotage-checked; suite 641 green     |
| `control` | `f84373c` | regen-only (`agent_models.py` changed, `models.py` untouched)    |
| `ui`      | `70dd910` | rules, reads, badge, Home's card, Inference's two states          |
| `dist`    | `893b669` | the static export of `70dd910`, pinned by both installers        |
| `specs`   | `f2f0a10` | the pins: ui `893b669`, agent `763d10d`, control `f84373c`       |

`ui` `055a9a4` is the pin bump, the regen and `issues.ts`; `f67e001` is
its test file (step 1), `acfac86` the polling hook (step 2) and
`9dbfd40` the header badge (step 3), `8979d4e` Home's card (step 4) and
`70dd910` Inference's two states (step 5), all landed 2026-09-16. **`issues.ts` is referenced now, so the next
`dist` build carries it** — which is why step 7's re-pin is no longer a
formality.

**Radius was measured by regenerating all six.** `gateway`, `library`
and `inference-driver` came back byte-identical apart from the SHA in a
generated header and were reverted rather than re-pinned; they codegen
neither changed document. **No installer was re-pinned**, deliberately:
nothing user-visible shipped, and `issues.ts` is unreferenced, so it is
tree-shaken out of the bundle.

#### Measuring the seven named issue kinds falsified four of them

The brief lists *sealed root, folder not mounted, node down with
`lastError`, clock skew warning, engine release with no assets, mixed
engine builds across replicas, a runtime on CPU*, over "existing
endpoints". Checked one at a time against the contracts and the agent's
source:

| Kind                  | Observable today?                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------------------ |
| sealed root           | **Yes**, twice over: `RoutingTableView.control_root.error` matching `locked`, and control's own `503 #locked` |
| node down + reason    | **Yes** — `Node.reachable` + `Node.lastError` on the root's `GET /v1/nodes`                                   |
| folder not mounted    | **Yes** — agent `POST /v1/library/folders/check`, `exists` / `isDirectory` / `problem`, per node              |
| clock skew            | **NO.** Log only. Fixed by this slice; see below                                                              |
| engine with no assets | **Yes**, with a trap that would have made the list permanently wrong                                          |
| mixed engine builds   | **Yes on one machine, no across the install**                                                                 |
| a runtime on CPU      | **Partly**, and the useful case is not observable at all                                                      |

**Clock skew was log-only, and the gap behind it was wider than skew.**
`_note_clock_skew` in all five `security.py` copies computes `iat - now`
exactly, on every token decode, and writes it to a log at most once a
minute. Nothing carries it. The wider finding: **no component put its
own current time on any response body**, so from outside a host there
was no way to tell that its clock was wrong until the drift crossed the
300 s leeway and the install stopped working — which is how half a
second of it took a morning to find on 2026-09-15.

The fix is one field, `NodeIdentity.time`, and it is deliberately **not**
a remembered skew observation: a remembered one says a peer was wrong at
some past minute, this says what this host thinks the time is *now*,
which is the quantity, and it needs no state. A console reads it from
two hosts milliseconds apart, brackets each read (`t0` before, `t1`
after), and the offset between two hosts is the difference of two
intervals — so a slow proxy hop widens the interval, shrinks the
reported number, and can only ever **hide** a skew, never invent one.

**Measured between nodes and never between a node and the browser.** A
laptop back from sleep, or a VM whose clock jumped, would otherwise
accuse every machine in the install of being wrong. What breaks an
install is two *hosts* disagreeing — the tokens one mints and the other
refuses — and a one-machine install has one clock and cannot have the
problem at all.

**`policy: manual` must be excluded from "engine cannot be installed",
or the list is permanently wrong on every install.** vLLM's
`acquisition.installable` is `false` on **every host that will ever
run** — its unit of installation is a Python environment we do not own,
which is a decision and not a fault. A rule that flagged every
`installable: false` would put an unfixable issue in front of every user
forever, which is how a needs-attention list becomes a thing nobody
reads. What is left is real: a *managed* engine with no build for this
machine (llama.cpp on Linux with an NVIDIA card) and a release upstream
shipped with its assets missing.

**The install-wide runtime view is too thin for three of the rules.**
`RuntimePlacement` on the control root is `{node, name, modelAlias,
status, url, engine}` — no `engineVersion`, no `flags`, no
`lastRestart`, no `localPath`. Mixed builds, on-CPU and the loading
state all need those, so they need the agent's own `GET /v1/runtimes`
**per node**, through the `node:<name>` hop that
`one-console-never-hop-nodes` exists for. That settles the polling
shape: four reads per node on a slow cadence, not the tray's five
seconds — an issue is not a task and does not change second to second.

**"A runtime on CPU" split into a state and an issue, and the useful
half is not observable.**

- *A machine with no accelerator.* True, permanent, needs nobody. A
  **state** on the Inference row, not an issue.
- *A profile declaring `gpuLayers: 0` on a machine that has a card.* An
  **issue**, read from the declaration. The agent's own rule has to be
  restated exactly: unset is *full* offload for llama.cpp, negative is
  "all", 99 or more is full — so **only an explicit zero** means the
  processor. Getting that backwards would warn about every correctly
  configured model in the install.
- *A CPU-only engine build on a machine with a card.* The commonest
  complaint in the field research (§3), and **not observable**.
  `EngineDescriptor` carries `version` and `binaryPath` and no installed
  variant; the managed store's layout is `<engine>/<version>/` with the
  variant only inside `install.json`; and
  `GET /v1/engines/{engine}/install` describes the last install *this
  agent performed*, not the build in use. It wants one more field,
  `EngineDescriptor.installedVariant`, and was not taken here.

#### §7's *loading · ~2 min left (from bytes and rate)* cannot be built — there are no bytes

Nothing on any wire counts a model load. `llama-server`'s `/health`
answers `503 {"status": "loading model"}` with no fraction; vLLM binds
its port and answers nothing at all until the weights are resident;
`RuntimeCapabilities` is read back from the engine and carries
`contextLength`, `parallelSlots`, `embeddings`, `multimodal` and nothing
about memory; and `Runtime` has no progress field.

**Reading the process's own I/O counters does not rescue it, and that is
the finding worth keeping.** llama.cpp memory-maps the model by default,
and faulted pages are **not** read I/O in `GetProcessIoCounters` on
Windows — so the obvious agent-side fix would report ~0 bytes for the
commonest case on the platform this project treats as first-class.
`/proc/<pid>/io` on Linux counts major faults under `read_bytes` but not
`rchar`, so the two platforms would disagree about the same load. And a
VRAM-delta estimate from `devices.py` is not a measurement: other
processes move VRAM, and two runtimes loading at once cannot be told
apart.

So `describeLoading` reports what is exact — **elapsed**, from
`Runtime.lastRestart` — plus **where the bytes are coming from**, which
is the thing that actually explains a four-minute load: on the live
install a 23.8 GB model crosses a gigabit link from a NAS on *every*
start, and the UNC path says so. An estimate appears only once this
browser has watched the same model finish loading before. A first load
has nothing honest to predict from, and says nothing rather than
guessing.

#### Where it resumed from (spent — the steps below all landed; kept as the handoff that worked)

`ui/src/lib/issues.ts` is written, typechecks, lints, and is committed
at `055a9a4`. It exports `issuesFrom`, `worstSeverity`, `skewBetween`,
`declaresNoOffload`, `hasAccelerator`, `describeCompute` and
`describeLoading`. **Nothing imports it.** In order:

1. ~~**`ui/src/lib/issues.test.ts`**~~ — **DONE 2026-09-16, `ui`
   `f67e001`.** 63 cases over the pure rules, against the bodies the
   live install returns. **Eight sabotages confirmed failing**,
   including the two that had to be: `declaresNoOffload` written as
   `!layers` (unset is not CPU) takes four cases with it, and dropping
   the `policy: manual` filter puts vLLM's permanent refusal in front of
   every user. Also caught: `Number(null) === 0`; `count <= 0`
   swallowing `-1`, which is upstream's *all layers*; `locked` inferred
   from any unreachable root; stale-build counting stopped runtimes;
   blocking-first ordering.

   **One sabotage ESCAPED and is recorded rather than patched over.**
   `clockSkewIssues`'s `measured.length < 2` guard is unreachable — the
   pairwise loop already yields nothing for a single node — so no test
   can distinguish it. The property it exists to protect, *compare node
   to node and never node to browser*, is caught by a different
   sabotage: counting the browser as a node fails five cases, the
   one-machine install among them.

   **And step 2's trap is an assertion now, not a sentence here.** A
   node read without a `readWindow` contributes no measurement, silently
   — `skewBetween` returns null and `issuesFrom` returns `[]` — which is
   pinned by its own test so that the omission below fails something.
2. ~~**`ui/src/lib/useIssues.ts`**~~ — **DONE 2026-09-16, `ui`
   `acfac86`.** Six reads on a one-box install, four per node beyond
   it, all soft, 30 s, hidden tabs skipped. The identity read **is**
   bracketed, and `useIssues.test.tsx` drives two hosts 45 s apart end
   to end so that dropping a mark fails something. **Seven sabotages,
   six caught.**

   **Two decisions this step took that the plan did not name.** Every
   read passes the session token as an explicit `bearer`, because
   `api.ts` exempts a supplied credential from the 401 interceptor:
   without it, M9's shape — root initialized, local agent not enrolled,
   so the root refuses every session the agent mints, which S4 hit live
   — logs the operator out every thirty seconds from every page, with no
   window in which to read the issue explaining why. And `isLocked` came
   out of `nodes/page.tsx` into `controlUnlock.ts` as `isLockedError`:
   two copies of sealed-vs-uninitialized are two chances to flatten a
   distinction this UI flattened once already, and the badge asks it
   everywhere now.

   **The seventh sabotage escapes, and is documented rather than
   covered.** Taking both `Date.now()` marks *after* the request narrows
   the interval to nothing and loses the property that latency can only
   ever hide a skew. It cannot be caught through this surface: the
   invented skew is bounded by the hop's own latency, and
   `READ_TIMEOUT_MS` (10 s) is a third of `SKEW_WARN_SECONDS` (30 s), so
   a read slow enough to invent a warning has already been aborted.
   **Both constants are load-bearing to that argument** — raising the
   timeout past the warning threshold makes a false clock warning
   reachable, and the docblock says so.
3. ~~**`ui/src/components/IssuesBadge.tsx`**~~ — **DONE 2026-09-16,
   `ui` `9dbfd40`. The slice's *Done when* is met.** Beside `TasksTray`,
   same disclosure, and it **renders nothing at all** when there is
   nothing to say *or* before the first read has answered — an all-clear
   shown half a second before the list fills, to somebody whose root is
   sealed, is worse than silence.

   **Every other issue links to the screen that owns its fix; the sealed
   root does not, and the asymmetry is the argument.** A one-click
   remedy for something with consequences belongs beside the words that
   explain them — but a locked root is the one case where every other
   screen is already useless, so a link is a door that is shut. A failed
   unlock is also not called a wrong password: the session is already
   good, and what failed is the root holding a *different* secret, which
   is a real state and is named as one.

   Eight sabotages, all caught, including the two that would quietly
   undo the slice: linking away instead of carrying the form, and
   treating a mismatch as success.
4. ~~**`ui/src/components/home/NeedsAttentionCard.tsx`**~~ — **DONE
   2026-09-16, `ui` `8979d4e`.** Beside `RunningCard`, per §6.1's
   wireframe, and the docblock line came out.

   **It says "nothing" where the badge says nothing at all.** The header
   is chrome on every screen, so an all-clear there is a decoration that
   teaches people to stop reading it; Home is where somebody asks *how
   is it?*, and there "nothing needs you" is the answer rather than the
   absence of one. Before the first read it says it is still looking.

   `IssueRow` and the unlock form moved into their own module, shared by
   both surfaces — a second copy is a second chance to get wrong the one
   form in this UI where a person types a secret outside the sign-in
   page.

   **Two sabotages escaped the first pass, both the same shape: the card
   was proved and its wiring was not.** Home could have fed it `[]`
   forever, or omitted `onFixed`, with every test of the card green
   because the card is fine. Both are covered now by driving *Home* — a
   sealed root arriving through the real poll, and an unlock from Home
   clearing the issue rather than leaving a fixed problem on screen for
   the rest of the interval. **A component test is not a wiring test,
   and this slice has now produced that lesson twice.**
5. ~~**Inference's two states**~~ — **DONE 2026-09-16, `ui` `70dd910`.**
   Shared with `useIssues` as planned: it already makes the four reads
   per node, so the screen consumes them rather than asking the same
   endpoints again.

   **The status comes from the fast poll and the fields from the slow
   one**, and that split is the only honest one: this screen reads every
   3 s and the Issues poll every 30, so a model that has finished
   loading must stop saying it has not at *this* screen's cadence. What
   the slow read carries is `lastRestart` — an absolute instant, so a
   stale read cannot make elapsed wrong — plus the share the bytes are
   crossing.

   `lib/loadMemory.ts` is the only material an estimate can have, since
   nothing counts a load: per browser **and per node**, because the
   number is dominated by where the bytes come from. The last
   observation, not an average.

   **Driving the page found a real defect in it**, and it was the one
   `nodeDetails` exists to prevent: `detail.devices ?? []` turned *that
   node has not answered* into *that machine has no accelerator*, which
   prints "on the processor" on every row of a node that is merely slow
   to reply. Two of seven sabotages escaped the first pass and both were
   fixtures that could not tell two things apart — the fast and slow
   status agreeing, and one assertion of a clock that never moved.
6. **`scripts/issues-acceptance.sh`** in `specs`, plus
   `docs/acceptance/issues-run.md`. The sealed root is producible:
   initialize the control root, restart it with no keyring, and it comes
   back `503 Locked`. Clock skew is **not** producible on one box and
   should be reported as not produced rather than faked.
6. ~~**`scripts/issues-acceptance.sh`**~~ — **DONE 2026-09-16, after
   step 7.** 20 PASS, zero failures, one SKIP.

   **Every issue in the run is produced by the install rather than by a
   fixture:** two Library folders with one never created; a real 0.6B on
   a real `llama-server` declared `gpuLayers: 0` on a box with a 5090;
   two runtimes pinned by `binary` to `b10930` and `b10948`, **both
   serving** — the mixed fleet nothing detected before S7; and a root
   restarted with no keyring. vLLM is deliberately *absent* from the
   list: it really does report `policy: manual, installable: false`
   here, so the exclusion is exercised against a host that reports the
   case rather than against a fixture.

   **THE FINDING, and it is about the product: a fresh sign-in cannot
   meet a sealed root.** The first execution sealed the root, signed a
   browser in, and found nothing to report — because since 2026-09-13
   the login page posts the passphrase to the control root too, so
   signing in *unlocks* it. The check was measuring a state its own
   setup had just destroyed. That is the two halves fitting together,
   and it names what the badge is for: login-time unlock covers the
   person who arrives after the root sealed, and **the badge covers the
   person already signed in when it sealed underneath them** — the case
   the live install produced on 2026-09-13, carried as open ever since
   (*"an already-open browser session still does not unlock it — sign
   out and in"*). **S7 closes it.** Check 11 seals the root from inside
   the page with the session the browser already holds, starts on
   `/library`, and asserts both that the issue clears and that the URL
   never changed — the *Done when* measured rather than asserted.

   **Clock skew was not produced and says so.** The rule compares two
   *hosts* and this box has one clock; moving the system clock would
   change the clock the live worker install is using, whose tokens a
   control root on another machine would then refuse. Also unproven:
   `node-down`, and the estimate half of `describeLoading`.

7. ~~**Then** re-pin both installers~~ — **DONE 2026-09-16, `specs`
   `f2f0a10`. THREE pins moved, not one.**

   - `ui` `11e7767` → **`893b669`** (`dist`, built from `ui@70dd910`).
   - `agent` `f9cc927` → **`763d10d`**, and this is the one that
     mattered: it **serves `NodeIdentity.time`**. Without it no host
     reports what time it thinks it is, `skewBetween` has nothing to
     measure, and the clock-skew rule can never fire on a fresh
     install. Pinning only the UI would have shipped a rule with no
     input — the same shape of defect this slice's own measurement was
     written to catch.
   - `control` `ff71f75` → **`f84373c`**, regen-only at specs
     `4a72644`, so the trust root's generated view of the agent's
     surface matches the agent it reads.

   `gateway` and `inference-driver` were already at their HEADs.
   `library` stays at `fd7aeb7`: its only commit since is a README, so
   the installed code is byte-identical.

   All three archives were verified to resolve, and **the pinned UI
   archive was unpacked and grepped** — it carries the built export and
   the strings S7 added, so "pinned a commit with no UI in it", the trap
   that produced the `dist` branch in the first place, cannot have
   happened silently.

**Known trap for the acceptance run, unchanged since S0:** the live
worker agent holds 8079 on this box. Run on +100 ports, clear every
ambient `EUGENE_PLEXUS_*` variable first, and tear down by pid.

### 11.10 S10 — the budget, counted. GREEN ON WINDOWS 2026-09-16; the WSL2 half is §11.11.

`scripts/hobbyist-acceptance.sh`, **22 checks, zero failures, fourth
execution**. Record: [`../acceptance/hobbyist-run.md`](../acceptance/hobbyist-run.md).
No contract change. One consumer moved, and it was not a code change:
`ui` `dist` `893b669` → **`50e0248`**, re-pinned in both installers.

**The numbers §1 committed to, measured rather than reasoned:**

| | §0.2 before | Target | Measured |
| --- | --- | --- | --- |
| Clicks, wizard → first reply | 15 | ≤ 6 | **5** |
| Typed values | 3, one a path | 1 | **1**, the passphrase |
| Paths typed | 1 | 0 | **0** |
| Clicks, Home → a connected tool | 19 | ≤ 3 | **1** |
| The key's life | 14 days | > 14 | **a year** |
| Banned words, four screens | — | 0 | **0** |

The five clicks are **Continue · Finish · Run · Install the default ·
Send**, counted by `pointerdown` listeners the page installs on itself
rather than by counting the lines of the test — §8.2's first trap, which
this project has produced twice.

`install.ps1` from nothing in **7 s**; wizard to a reply in **21 s**, on
a cold engine store (`askedAboutEngine: true`, llama.cpp **b11010**
fetched into the run's own prefix, the CUDA **13.4** build taken on a
**13.3** driver under the minor-version rule S3 taught the adapter).

---

**THE RUN'S FINDING IS ABOUT SHIPPING, NOT ABOUT CLICKS: a fix can be
on `main`, tested, merged, and in no build anyone installs.**

The third execution clicked a **16 GB download beside a folder that
already held a model** — the exact defect `ui` `f267fbd` had fixed hours
earlier. The fix was real and its tests passed. But `dist` was still
`893b669`, the export of ui@`70dd910`, and f267fbd is a child of that
commit that was never exported. **Both installers pin `dist`.** So the
fix could not reach a user, and this run — which is an *installer* test —
measured a UI without it.

Measured, not suspected: `"library","/v1/scan"` is in **five** chunks of
a build of ui@f267fbd and **zero** chunks of `893b669`.

This is S3's *"staging is not serving"* one layer over. There it was an
agent venv serving a wheel while the script grepped a staged directory,
and four runs asserted about a build no browser saw. Here it is a commit
on `main` that no `dist` build carries — and **the installer is the only
thing that can notice**, because the installer is `dist`'s only consumer.
A unit test cannot see it, CI cannot see it, and a developer running
`next dev` cannot see it.

Fixed: `dist` rebuilt as `50e0248`, both installers re-pinned, and **the
pinned archive downloaded, unpacked and grepped** before the re-run —
the precaution S7 introduced for this trap's other direction.

---

**AND THE SPEC DID NOT DETECT THAT DEFECT — IT DEPENDED ON IT.**

The arc waited for `data-testid="home-primary"` and clicked it. But
`home-primary` is the testid of `FirstModelCard`'s **no-models**
branches; the one-model branch renders a `run-button` and carries no
`home-primary` at all. So the spec could only ever match the state where
Home has nothing on disk, and it reported that state as a **pass**. With
the fix in place the old spec would have hung for two minutes on a
testid that no longer renders.

A check that cannot distinguish the failure it exists to catch is this
repo's most-repeated defect: M10's check 7 asserted on `"The "` and
matched `"The model 'flaky' does not exist"`; the tree slice's *"a driver
sits under its machine"* passed against a tree with the node level
removed; step 6's fragmentation checks demanded a property of the
*backend*. Here the shape is new and worse — the assertion was satisfied
**by** the bug.

The arc now waits on `run-button`, **races the download card against
it**, and fails if the download appeared; check 4e is that assertion in
the shell, so the wizard-scan regression is a gate rather than a
surprise.

---

**Three more harness defects, two of them guaranteed failures on any
run:**

- **Two checks read keys the spec never wrote.** The shell read
  `firstReply.text` and `connect.expiry`; the spec writes `turn`,
  `transcript` and `lifetime`. `jq_` raises, the substitution captures
  empty, and with no `set -e` checks 4d and 7 fail on a perfectly green
  install. Found by reading the two halves against each other rather
  than by spending a run on it.
- **Sixteen tokens is not a budget an answer fits in.** Check 6 asked
  for `max_tokens: 16` and got a `200` with empty `content`: the starter
  models are hybrid reasoning models whose first tokens are a thinking
  block the gateway strips. The check would have read a working install
  as a broken one. 256 now, with `finish_reason` on failure.
- **The run binds four ports, not one.** The header said "+100" and the
  preflight checked one. First-boot seeding declares the gateway,
  library and control root at the contract defaults — 8080, 8082, 8083 —
  whatever port the agent took (`default_topology.py`). All four are
  preflighted and reclaimed now, which is safe *because* the preflight
  proved they were free.

---

**Not done, and each for a stated reason:**

1. ~~**WSL2.** The `install.sh` half is not written~~ **— DONE 2026-09-16,
   green, §11.11 is the record.** The gate is still unsatisfied, for the two
   items below plus the adversarial review's eight pre-link fixes; leaving this
   reason standing made the list say the gate was blocked on something done.
2. **`EP_DOWNLOAD=1`.** §1's ten-minute install-to-first-token target,
   download included, is still unmeasured. The default seeds a small
   GGUF because the subject of the other three targets is the **count**,
   and a download changes how long the arc takes without changing how
   many times it is clicked. (The third execution accidentally
   downloaded a 27B and reached a reply in 261 s — wrong build, wrong
   model, an anecdote rather than the measurement.)
3. **Moderated sessions** (§8.4). Needs real people.
4. **The keystroke count is not a measurement.** Playwright's `fill()`
   sets a value and dispatches `change` with no `keydown`, so the run
   reports **0 keystrokes** where a person types about thirty. §1's claim
   is *one typed **value***, which the `change` listener does measure;
   the keystroke number is the counter's own blind spot and is recorded
   here so nobody quotes it.
5. **Reading grade** (§8.1) is still unmeasured. The run reports
   sentences over 25 words — Home 6, Discover 5, Library 2, Playground 2
   — as the number S8 has to drive down.

### 11.11 S10 on WSL2 — green, and the refusal it found had expired. 2026-09-16.

`EP_TARGET=wsl`, **22 checks, zero failures, third execution**. Record:
[`../acceptance/hobbyist-run.md`](../acceptance/hobbyist-run.md) §4b.
Agent `b4c0679`, re-pinned in both installers. No contract change.

**The budget holds on Linux**, identically: 5 clicks, one typed value,
no typed path, 1 click from Home to a connected tool. `install.sh` from
nothing in **4 s** against `install.ps1`'s 7 s; wizard to a reply in
39 s against 21 s.

**The shape: the install is Linux, the browser is Windows.** WSL2
forwards a guest listener on `127.0.0.1:8179` to the same port on the
host, so the same arc runs unchanged. The guest has `uv`, `python3`,
`curl` and `git` and **no Node and no browser** — `npm` there is the
*Windows* npm over interop, which answers `--version` while `node` does
not exist. Installing Playwright into it would change the machine to
prove something the UI does not depend on, because the UI is one static
export and the browser's OS is not what WSL2 tests. `install.sh` is.

**One platform difference is a finding, not a skip.** The account hazard
belongs to `install.ps1`, not to installing: `install.sh` writes the
config path into the systemd unit it generates, so a second Linux
install cannot repoint a first through the environment. Check 2 asserts
that rather than skipping.

---

**THE RUN'S FINDING: A REFUSAL THAT RESTED ON AN UPSTREAM FACT, AND THE
FACT HAD CHANGED.**

The first WSL2 execution reached one-click Run and stopped on M1's
deliberate refusal — *"llama.cpp publishes no prebuilt CUDA build for
Linux… we will not substitute [Vulkan] for CUDA without being asked"*.
`install-paths-and-distribution.md` decision **#2**, *"ship Vulkan,
badge it permanently"*, **DECIDED 2026-09-11**, was the agreed answer
and had never been built: zero occurrences of `vulkan` in the agent, and
the only one anywhere was a test asserting the refusal.

**Checking upstream before building it showed there was nothing to
build.** §7 of that document says the premise "was re-verified against
upstream on 2026-09-11, not taken from the code comment"; re-verifying
five days later, b11010 publishes `ubuntu-cuda-12.8-x64`,
`ubuntu-cuda-13.3-x64` and `ubuntu-cuda-13.3-arm64`. Decision #2 was a
workaround for a missing asset that now exists, so the fix was to map
the Linux CUDA variants — no degradation, no badge, no contract change.

**A second trap in the same change would have shipped a server that
could not start.** The companion archives are not named alike:
`cudart-llama-bin-win-cuda-13.4-x64.zip` carries no build number and
`cudart-llama-b11010-bin-ubuntu-cuda-13.3-x64.tar.gz` carries one.
`_CUDART_RE` required the Windows shape, and the companion is only
*demanded* for a variant the matcher recognises, so a Linux CUDA install
would have fetched the server, reported success, and died at load on a
missing libcudart.

**Proved, not inferred.** A 0.6B runs fine on a CPU, so a green run is
not evidence of a CUDA install. The guest's `install.json` reads
`"variant": "ubuntu-cuda-13.3-x64"` with the companion unpacked beside
it, and the installed binary answers `--list-devices` with
`CUDA0: NVIDIA GeForce RTX 5090 (32606 MiB, 30927 MiB free)`.

**Linux + NVIDIA is §7's own "most common serious setup, and the one
where differentiator #1 is currently false".** It was false for five
days longer than it needed to be, and the reason it went unseen is the
reason this slice exists: **nothing had ever walked the install path on
Linux with an NVIDIA card.** A design section is not re-verified by
being read.

---

**Two harness defects, both about the seam rather than the product:**

- **`setsid nohup` does not survive `wsl.exe -e`.** The interop session
  ends when the command returns and takes the agent with it. The symptom
  was a **zero-byte log and nothing listening** — no error, because
  nothing got far enough to write one; running the same command in the
  foreground showed all four components healthy, which is what isolated
  it. The agent is backgrounded from the Windows side now, which holds
  the session open, gives teardown a pid symmetric with the Windows
  path, and puts the log where the failure paths already look.
- **Windows `netstat` sees a forwarded guest port, but the pid is the
  relay.** `taskkill` on it would leave the real process running. Ports
  are reclaimed inside the guest with `fuser`, and check 10 treats the
  guest as the authority rather than the forwarder, which can linger.

**Still not done:** `EP_DOWNLOAD=1` and §1's ten-minute target; the
moderated sessions (§8.4); a Linux-native browser; a systemd-supervised
agent; the macOS/launchd path.

---

## Appendix A — sources

Gathered 2026-09-15. **(F)** opened and read; **(S)** search snippet
only; **(R)** the r/LocalLLaMA thread as recorded in
`local-inference-control-plane.md` §1 and `agent-clients-and-tool-calling.md`
§2 (Reddit refused fetches).

### A.1 Products and onboarding

- LM Studio modes and 0.4: https://lmstudio.ai/docs/modes (F), https://lmstudio.ai/blog/0.4.0 (F); download flow https://lmstudio.ai/docs/app/basics/download-model (F); server https://lmstudio.ai/docs/developer/core/server (F), https://lmstudio.ai/docs/developer/core/server/serve-on-network (F); import layout https://lmstudio.ai/docs/app/advanced/import-model (F); a user's manual-GGUF question https://github.com/lmstudio-ai/configs/issues/11 (F); first-run walkthrough https://houtini.com/articles/how-to-set-up-lm-studio/ (F); 0.4 reception https://alternativeto.net/news/2026/1/lm-studio-0-4-adds-parallel-model-requests-server-native-daemon-and-new-stateful-rest-api (F).
- Ollama desktop app https://ollama.com/blog/new-app (F), walkthrough https://apidog.com/blog/ollama-windows-mac-app/ (F); `ollama launch` https://ollama.com/blog/launch (F); context docs https://docs.ollama.com/context-length (S); the critique https://sleepingrobots.com/dreams/stop-using-ollama/ (F) and its summary https://dev.to/jamilxt/1175-redditors-just-told-you-to-stop-using-ollama-heres-why-local-ai-tooling-got-serious-2eia (F); blob-store issues https://github.com/ollama/ollama/issues/1981 (F), https://github.com/ollama/ollama/issues/13760 (F), https://github.com/ollama/ollama/issues/17554 (F), https://github.com/ollama/ollama/issues/1450 (S); ignored context slider https://github.com/ollama/ollama/issues/16896 (F).
- Open WebUI settings https://docs.openwebui.com/getting-started/quick-start/settings/ (F); HN threads https://news.ycombinator.com/item?id=48346990 (F), https://news.ycombinator.com/item?id=45798193 (F).
- Jan https://jan.ai/docs/desktop/quickstart (F); Msty https://docs.msty.app/getting-started/onboarding (F); GPT4All https://docs.gpt4all.io/gpt4all_desktop/models.html (F); AnythingLLM https://github.com/attilaszasz/AnythingLLM_Guides (F).
- llama.app https://llama.app/ (F), https://llama.app/docs/introduction (F), launch feedback https://github.com/ggml-org/llama.cpp/discussions/23875 (F); Unsloth Studio https://unsloth.ai/docs/new/studio/start (F), https://pinggy.io/blog/finetune_and_selfhost_llms_locally_with_unsloth/ (F).
- Proxmox GUI https://pve.proxmox.com/pve-docs/chapter-pve-gui.html (F); the "simple view" thread https://forum.proxmox.com/threads/concept-thoughts-for-improving-the-proxmox-ve-web-interface.155016/ (F); task-log praise https://www.virtualizationhowto.com/2026/01/proxmox-tips-i-wish-i-knew-before-building-my-first-home-lab/ (F).
- Unraid https://unraid.net/getting-started (F); Home Assistant onboarding https://www.home-assistant.io/getting-started/onboarding/ (F), integrations https://www.home-assistant.io/getting-started/integration/ (F), Repairs https://www.home-assistant.io/integrations/repairs/ (F), Advanced-mode removal https://github.com/OpenHomeFoundation/roadmap/issues/54 (F), https://developers.home-assistant.io/blog/2026/05/26/advanced-mode-config-flow-deprecation/ (F), https://community.home-assistant.io/t/advanced-mode-is-too-hidden/219516 (F), https://peyanski.com/home-assistant-advanced-mode-settings-less-scary/ (F).
- Jellyfin https://jellyfin.org/docs/general/post-install/setup-wizard/ (F); Plex https://support.plex.tv/articles/200288896-basic-setup-wizard/ (F); Portainer https://docs.portainer.io/start/install/server/setup (F); Pi-hole v6 https://pi-hole.net/blog/2025/02/18/introducing-pi-hole-v6/ (F); DSM vs TrueNAS vs Unraid https://www.xda-developers.com/synologys-dsm-is-fine-until-truenas-or-unraid/ (F); a first TrueNAS user https://www.truenas.com/community/threads/first-time-truenas-scale-user-and-the-learning-curve.113313/ (F).
- Hugging Face local apps https://huggingface.co/docs/hub/main/local-apps (F), hardware panel https://huggingface.co/docs/hub/en/hardware (F); a plain quant list https://huggingface.co/unsloth/Qwen3-8B-GGUF (F); bartowski's descriptions and VRAM rule https://huggingface.co/bartowski/Qwen_Qwen3-8B-GGUF (F); beginner rule of thumb https://ai-tldr.dev/learn/local-open-models/open-model-ecosystem/pick-gguf-quant-download/ (F).

### A.2 Where hobbyists get stuck

- Context vs VRAM: https://news.ycombinator.com/item?id=42833427 (F); https://github.com/ollama/ollama/issues/9890 (F); https://news.ycombinator.com/item?id=49613840 (F); https://github.com/ggml-org/llama.cpp/issues/8101 (S).
- Reaching the server: https://github.com/open-webui/open-webui/discussions/5903 (F); https://github.com/ollama/ollama/issues/8304 (F); https://docs.ollama.com/faq (S).
- Files trapped in a store: https://news.ycombinator.com/item?id=47788385 (F); (R).
- Which quant: https://news.ycombinator.com/item?id=49341724 (F); https://news.ycombinator.com/item?id=49368302 (F); https://news.ycombinator.com/item?id=47789393 (F); (R).
- GPU not used: https://github.com/ollama/ollama/issues/4563 (F); https://forums.unraid.net/topic/184427-ollama-not-using-nvidia-gpu/ (F).
- Pointing a client at it: https://github.com/caliban-ai/caliban/issues/641 (F); https://github.com/continuedev/continue/issues/7658 (F); https://news.ycombinator.com/item?id=48211003 (F); https://docs.cline.bot/provider-config/openai-compatible (S).
- Cold loads: https://dev.to/ji_ai/ollama-keepalive-my-model-reloaded-214-times-in-one-day-il4 (F); https://github.com/continuedev/continue/issues/783 (S).
- Eviction: https://github.com/ollama/ollama/issues/4681 (F); https://github.com/ollama/ollama/issues/13235 (F).
- `<think>`: https://github.com/open-webui/open-webui/issues/24839 (F).
- Docker: https://news.ycombinator.com/item?id=43903154 (F); https://news.ycombinator.com/item?id=41852577 (F); (R).
- Praise: https://news.ycombinator.com/item?id=47788385 (F); https://news.ycombinator.com/item?id=41342694 (F).

### A.3 Principles

- NN/g: heuristics https://www.nngroup.com/articles/ten-usability-heuristics/ (F); complex applications https://www.nngroup.com/articles/usability-heuristics-complex-applications/ (F); error messages https://www.nngroup.com/articles/error-message-guidelines/ (F); progressive disclosure https://www.nngroup.com/articles/progressive-disclosure/ (F); wizards https://www.nngroup.com/articles/wizards/ (F); empty states https://www.nngroup.com/articles/empty-state-interface-design/ (F); recognition over recall https://www.nngroup.com/articles/recognition-and-recall/ (F); onboarding tutorials https://www.nngroup.com/articles/onboarding-tutorials/ (F); indicators and notifications https://www.nngroup.com/articles/indicators-validations-notifications/ (F).
- GOV.UK: one thing per page https://designnotes.blog.gov.uk/2015/07/03/one-thing-per-page/ (F); question pages https://design-system.service.gov.uk/patterns/question-pages/ (F); writing for interfaces https://www.gov.uk/service-manual/design/writing-for-user-interfaces (F); clear language https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/clear-language/ (F); reading age https://design.homeoffice.gov.uk/accessibility/written-content/readability (F); point 1 https://www.gov.uk/service-manual/service-standard/point-1-understand-user-needs (F); the question protocol https://www.uxmatters.com/mt/archives/2010/06/the-question-protocol-how-to-make-sure-every-form-field-is-necessary.php (F).
- Apple HIG Settings https://developer.apple.com/design/human-interface-guidelines/settings (F); Android settings guidelines https://source.android.com/docs/core/settings/settings-guidelines (F); VS Code settings-GUI debate https://github.com/microsoft/vscode/issues/129594 (F).
- Krug https://charukiewi.cz/books/dont-make-me-think/ (F); Sierra https://mtlynch.io/book-reports/badass/ (F), https://businessofsoftware.org/talks/kathy-sierra-building-the-minimum-badass-user-product-development/ (F); Cooper https://thedesignersfieldguide.substack.com/p/most-users-are-intermediate-users (F); Jakob's and Hick's laws https://lawsofux.com/jakobs-law/ (F), https://lawsofux.com/hicks-law/ (F); time to hello world https://instruqt.com/glossary/time-to-hello-world (F), https://blog.postman.com/the-most-important-api-metric-is-time-to-first-call/ (F); Hemingway https://hemingwayapp.com/help/docs/readability (F).

## Appendix B — the inventory in numbers

*Measured* against `ui` `8c1fafa` on 2026-09-15.

| Thing                                  | Count                                                                                          |
| -------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Routes / navigable screens             | 11 / 7                                                                                         |
| Wizard screens / inputs (default path) | 5 / 5 (10 across branches)                                                                     |
| Wizard prose per screen                | 112 · 186 · 65 · 56 · ~146 words                                                               |
| HTTP calls on Start, no backend        | 8 (9 with a models folder)                                                                     |
| Jargon term families                   | 120                                                                                            |
| `title` tooltips / doc links / toasts  | 82 / 0 / 0                                                                                     |
| Expandable explainers                  | 7                                                                                              |
| `ConfigValueType`s rendered            | 16                                                                                             |
| Config categories per component        | gateway 6 · library 6 · agent 6 · control 6 · driver 3                                          |
| Responsive utilities                   | 7 (five `lg:`, two `sm:`)                                                                      |
| ARIA attributes / `sr-only` labels     | 65 / 1                                                                                         |
| Playwright files / tests               | 5 / 22 — none through Discover, Library or Launch                                              |
| Vitest files / cases                   | 20 / ~185                                                                                      |
| "operator" in design docs / UI copy    | 190 / 84; "hobbyist" 1 (the wizard's keyring option)                                            |
