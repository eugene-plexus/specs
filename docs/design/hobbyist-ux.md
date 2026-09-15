# The weekend hobbyist: UX research and a plan (design)

**Status:** researched and designed 2026-09-15, on Troy's brief, ahead of
the release (`install-paths-and-distribution.md` §9 step 9, which stays
last). **All fourteen decisions were taken by Troy the same day**, in
two rounds; #4 on one condition, which §6.5 turns into a process, #6
amended to ask first, #12 on the condition that the jargon stays
available in hints, and #8 with a question that §6.6 answers. Only the
relabels (`Backends`, `Chat`) remain a separate open call.
**Nothing in this document is built.** Every claim marked
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
| **1**  | What the browser lands on after sign-in                                                                             | §6.1     | **Home** — a task-shaped page on the install root: get a model, try it, connect an app, reach it from other devices, what is running, what needs attention. The Playground becomes one of its pages | **taken 2026-09-15 (Troy)** |
| **2**  | The wizard shrinks to two screens, and Browse arrives in it                                                         | §6.2     | Yes. Passphrase, then "where should models live?" with a picker. Backend and Welcome leave; the install is enrolled on screen 1's Continue so screen 2 can browse                    | **taken 2026-09-15 (Troy): two screens** |
| **3**  | A proposed default models folder beside Browse                                                                      | §6.2     | Yes — a plain folder under the user's home, created on first download, files plainly named. A folder the user can see is not a managed store; differentiator #3 is about renaming and hiding, not about who created the directory | **taken 2026-09-15 (Troy)** |
| **4**  | A starter set of models, and one recommended for the detected card, on Home                                         | §6.3     | Yes, as *"the most-downloaded well-known instruct GGUF in the largest size class that fits at 16k"*, shown with why and **Choose another**. M3 said a one-click "get the best one for me" is a fine wizard step and a bad default; Home is that step | **taken 2026-09-15 (Troy), ON CONDITION: an automated pre-release review of the state of local inference that recommends keep or replace — §6.5.** Troy: *"This is something that will quickly grow stale as models continue to improve."* |
| **5**  | Launch without a profile                                                                                            | §7 S3    | Yes. Launch creates `default` at the context that fits (already computed) when none exists; the editor stays for experts                                                        | **taken 2026-09-15 (Troy)** |
| **6**  | Engine install happens inside the first Launch, as a task                                                           | §7 S3    | Yes. "No binary — install one from the Inference page" becomes a progress line in the same place the user is looking. Version pinning stays an expert path                     | **taken 2026-09-15 (Troy), AMENDED: ask first.** *"I could not find llama.cpp, would you like me to install it?"*, Yes as the default, with a warning that skipping is for advanced users only |
| **7**  | Long-lived client keys                                                                                              | §7 S4    | Yes: minted by the agent with the install signing key, `aud: client`, one-year default, named, listed, revoked by the existing rotation. **Contract change**                     | **taken 2026-09-15 (Troy)** |
| **8**  | "Serve to other devices" as one switch                                                                              | §7 S5    | Yes. It sets `advertiseUrl` to a detected LAN address, shows the URL a phone types, and reports what is actually bound. The minimal version is in the release                    | **taken 2026-09-15 (Troy).** His question — *can we detect the Windows Firewall disposition so we can warn when it is blocking?* — is answered **yes** in §6.6 |
| **9**  | Security default on a desktop OS is the keyring, written to **both** agent and control                              | §0.14    | Yes. The wizard's own copy already says the keyring is "best for AI hobbyists" and defaults to the other option. Servers and containers keep `prompt_on_startup` / `passphrase_file` | **taken 2026-09-15 (Troy)** |
| **10** | The tree stays; the machine level appears only once there is more than one machine                                  | §6.4     | Yes. A standalone install today shows four rows reading "This machine". Reverses `ui-tree-navigation.md` §2.3 for the one-machine case only; a second machine restores it       | **taken 2026-09-15 (Troy)** |
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

### 0.8 The second job has no path

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
NVIDIA card of 12–24 GB, 32–64 GB RAM. Has installed Steam, Plex or
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
| 6  | **Pointing an OpenAI client at it** — `/v1`, non-empty key, model id | *"The `apiBase` differs for each tool. Otherwise, getting 404"* (continue #7658)                                                  | **Missing** as a surface; the `curl` line is half of it (§0.8)                                |
| 7  | **Slow first response — the model was unloaded**                     | *"214 model load events… 11.4s to first token vs 0.9s warm"*                                                                      | Built (M6 policy); the load is visible only on Inference; no "keep resident" from the UI      |
| 8  | **Several models, eviction, VRAM juggling**                          | *"The log seems to say it runs out of memory, but I don't know what to do next."* (ollama #13235)                                 | Built (admission); no per-device memory bar on Inference                                      |
| 9  | **`<think>` tags in the answer**                                     | *"raw XML-like markup in the message body"* (open-webui #24839)                                                                   | Built (`ThinkingFilter`); the profile field is `thinkingMode`, not a plain-words control       |
| 10 | **Which model?**                                                     | *"Stop pretending like HF is in any way beginner friendly."* (HN)                                                                 | **Missing**: Discover opens on the catalogue's raw "most downloaded" list                      |
| 11 | **Docker as a barrier**                                              | *"for many users 'just run it in docker' is a non-starter"* (r/LocalLLaMA, 38 points)                                             | Answered: the one-liner installs on the gaming PC; the container is the NAS path              |

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

1. **Rank.** For each class, ask the Hub for text-generation GGUF
   repos by 30-day downloads with `gguf` (architecture, parameter
   total, chat template) and `cardData.base_model` expanded. Aggregate
   the dozen quant mirrors of one model by `base_model` — official,
   `unsloth`, `bartowski`, `ggml-org` are one candidate, not four — and
   bucket by parameter count. Drop: gated repos, entries with no chat
   template (base models), embedding and reranker models, and anything
   the library's own preflight cannot read. A candidate whose publisher
   is not on a short known-publisher list is **flagged, not ranked**;
   the list grows by a human adding a line, never by the tool.
2. **Compare** each class's current entry against the ranking.
3. **Prove it runs.** Fetch the pinned llama.cpp build's architecture
   list (`src/llama-arch.cpp` at the build tag) and check each
   candidate's `general.architecture` against it. For classes whose
   smallest quant is under 6 GB, download it and produce one token on
   CPU in CI. Above that, the architecture check alone, **and the report
   says which check ran.** A model the pinned engine cannot load is the
   one recommendation that would be worse than none.
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

### S2 — The two-screen wizard, with Browse and a proposed folder (M)

§6.2. Enroll on screen 1; `FolderPicker` on screen 2 over the local
agent's `/v1/directories`; the proposed default is a plain folder under
the user's home, **created only when the first download lands in it**
(the library creates a configured folder that does not exist yet when
it is the download destination — a behaviour change in `downloads.py`,
no contract change). *Touches:* ui, library. *Done when* the wizard is
completed with one typed value and the first download succeeds without
a 409. Decisions **#2, #3**.

### S3 — One-click run (M)

Launch with no profile creates `default` at `maxContextLength`; a
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
Decisions **#5, #6**.

### S4 — Client keys, and "Use it from your apps" (M, contract)

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
**#7**.

### S5 — "Reach it from other devices" (M, small contract)

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

### S6 — Discover: recommendation first, badge names the context, paste a URL (M)

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

### S7 — Issues, and two honest states on Inference (M)

The **Needs attention** card and header badge: sealed root, folder not
mounted, node down with `lastError`, clock skew warning, engine release
with no assets, mixed engine builds across replicas, a runtime on CPU.
UI aggregation over existing endpoints first; a `GET /v1/issues` on the
agent when the list stabilises. Inference gains *loading · ~2 min left*
(from bytes and rate) and *on CPU — reason* as a warning. *Touches:* ui;
later agent + contract. *Done when* a sealed root shows as one issue
with the unlock as its action, from any page.

### S8 — Vocabulary (M)

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

### S10 — Measure it (M; runs alongside everything above)

`scripts/hobbyist-acceptance.sh`: from `install.sh` on a clean guest to
a first token, driven by the system Chrome, **counting real pointer
actions and keystrokes**, asserting the budget in §1 and that no
filesystem path was typed; then the three strings from Home used by a
plain `curl`; then the Reach switch. Plus the readability lint and the
banned-word test from S8. And **moderated sessions** (§8.4). *Done when*
the script is green on WSL2 and this box and the session notes are in
`docs/acceptance/`.

**What gates the release (decision #13, taken):** S0–S6 and S10, **and
a starter review under 30 days old with no unresolved verdict (§6.5)**.
S7–S9 are real and can follow; none of them is on the path from install
to a first token or a connected tool.

---

## 8. How we will know

### 8.1 The numbers

| Measure                                     | Today              | Target         | Instrument                        |
| ------------------------------------------- | ------------------ | -------------- | --------------------------------- |
| Clicks, install → first reply               | 15 (19)            | ≤ 6            | `hobbyist-acceptance.sh`          |
| Typed values before first reply             | 3 (incl. a path)   | 1              | same                              |
| Route changes before first reply            | 6                  | ≤ 1            | same                              |
| Clicks, Home → tool connected               | 19 from landing    | ≤ 3            | same                              |
| Time, install → first token, 8B, 100 Mbit   | not measured       | < 10 min       | same, wall clock                  |
| Jargon terms on golden-path screens         | (not isolated)     | 0 banned words | S8 test                           |
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
