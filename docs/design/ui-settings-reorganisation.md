# Settings and the tree, reorganised for the person who does not know which process owns a setting

**Status: designed and built 2026-09-29, one session, on Troy's brief.** The
brief: *"it can be very difficult to figure out where particular config
options are found, to the point that last night I spent 4 minutes looking
for one thing… On the left nav tree we have 'Inference Drivers'. You would
think that all things Inference can be found here, but that is not true…
This split does not make sense for the end user."* No new features this
session; the UI is reorganised so related things sit together and a
setting can be found without knowing which process holds it.

Every call below was **taken as recommended and is Troy's to overturn**.
Each is data in one file — a label, a page list, a topic map — so
overturning one is a small diff, not a rebuild.

## Decisions

| #     | The call                                                                                                   | Recommendation, taken                                                                                                                                                                                                                                                                                                                                                                   |
| ----- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1** | Where does the Inference page live?                                                                        | **On the branch that lists the backends.** The branch is selectable now; its first page is the Inference page (route unchanged, `/inference`), its second is *Add a backend*. Each backend leaf gets *Overview* — the same page, opened on that backend's machine with its row marked — and *Settings*. Start, stop, restart, remove and engine installs are therefore reachable from the leaf, which is what the report asked for. No new page was invented. |
| **2** | How are settings organised?                                                                                | **One Settings page, by topic, with a search box** (`/config`, label *Settings*). Bare, it shows every setting on the install: 60 fields from the gateway, the library, the control root and every machine's agent, grouped into eleven topics that name what a person is trying to do, plus the browser's own Appearance. `?sel=<object>` shows that object's share of the same cards, so *Gateway → Settings* is the same page filtered, not a second organisation. Each topic card holds one section per owner; a section saves on its own; a sticky bar saves every dirty section. |
| **3** | What becomes of *Agents* and *Control root*?                                                               | **One branch, *Machines*.** Its pages are *Overview* (the Nodes page: the registry, versions, join) and *Settings* (the control root's); its children are the machines, each with *Settings* (that machine's agent) and *Logs*. The machine leaf renders on a one-box install too — the objection in hobbyist-ux.md §6.4 was to *four* rows reading *This machine*, and this is one row replacing the *Agent · this machine* row that exists today. |
| **4** | Relabels (hobbyist-ux.md decision #12 left them as "a separate call")                                      | **Taken:** *Inference drivers* → **Backends**; *Config* → **Settings**; *Control root* → **Machines**; *Agent* → the machine's own name, or **This machine**; *Preferences* folds into Settings as the *Appearance* card. **Not taken:** *Playground* → *Chat* — the playground is a diagnostic by decision (2026-09-11) and *Chat* would promise the chat product §9 of the hobbyist plan refuses. The implementation nouns stay as hover text on the rows (`inference drivers`, `control root`, `agent`), per decision #12's condition. |
| **5** | Branch order                                                                                               | **Library, Backends, Gateway, Machines** — the order of a hobbyist's questions and of Home's cards (get a model → run it → connect an app → add a machine). The layer map keeps the architecture page's order for whoever wants the request path. Was: Gateway, Inference drivers, Agents, Library, Control root. One array. |
| **6** | Dead and internal knobs                                                                                    | **Hidden from every settings page:** `firstRunComplete` on the agent and the control root (the wizard's flag, not a setting), and `uiTheme` / `uiFontSize` on both (v0.2 fossils; nothing reads them; the browser's Appearance card is the real one). Deleting them from the two Python schemas is a follow-up that re-pins two repos; hiding is UI-only and works against every pinned build. |
| **7** | Deep links                                                                                                 | **A link can name a field.** `/config?sel=gateway#defaultMaxTokens` opens the disclosure if the field is behind it, scrolls to it and marks it. The four cross-links that already point at a Config page (profile → gateway defaults, Reach → advertise address, downloads → catalogue token, apps → allow custom apps) now carry their field. |
| **8** | Search from the header?                                                                                    | **Not yet.** Settings is one click from the install root on every screen, and the search box is at its top. A header-wide "find a setting" is a small addition if the one click turns out to be the four minutes. |

---

## 0. What measuring found

*Measured 2026-09-29 against `ui` `6209595`, the alpha.5 build, and the
five components' schemas as their own venvs serve them.*

### 0.1 Sixty real settings, in nine places, filed by process

| Component        | Fields | Categories | Of which dead or internal                        |
| ---------------- | -----: | ---------: | ------------------------------------------------ |
| agent            |     20 |          9 | `firstRunComplete`, `uiTheme`, `uiFontSize`      |
| gateway          |     19 |          6 | —                                                |
| library          |     11 |          6 | —                                                |
| control          |      9 |          6 | `firstRunComplete`, `uiTheme`, `uiFontSize`      |
| inference-driver |     17 |          3 | — (per backend; stays on the backend's own page) |

Sixty-six fields, six of them dead or internal. **Nine places hold a
setting:** the five per-component Config pages; *Routing* (`modelSlots`,
its own page since 2026-09-21); *Folders* (the library's roots and their
mounts); Home's *Reach* card (the advertise switch) and *Use it from your
apps* card (client keys and their limits); the per-model profile on the
Library; *Nodes* (join tokens, versions); *Preferences* (theme, font).
Nothing lists them. Nothing searches them.

### 0.2 The report, reproduced

The tree reads `Eugene Plexus · Gateway · Inference drivers · Agent ·
Library · Control root`. *Inference drivers* expands to each driver, and a
driver's only page is *Config*. The page that starts, stops and restarts
a model — the one the report calls "all things Inference" — is *Inference*
on the **install root's** menu, beside Home and the Playground. The two
are three clicks apart and share no link in either direction except the
`config` button on an external backend's row.

### 0.3 The agent's Config page is where the four minutes go

Twenty fields over nine categories: Setup, Updates, Security, Appearance,
Engines, Node, Library, Model storage, Apps. *Appearance* duplicates
Preferences and does nothing. *Node* holds the advertise address the Reach
card links to. *Library* holds a machine's folder overrides, which the
Library branch also edits on its Folders page. *Setup* is one boolean
nobody should touch. The categories are the agent's own idea of itself;
none is named for what a person wants to change.

### 0.4 Two settings for the same thing, and three for a third

`defaultTemperature`/`defaultMaxTokens` live on the gateway; the same
values live per model on its profile (R8: the profile fills what the app
omits, the gateway fills what the profile omits). They cross-link, which
is right, and neither page says the other exists until you read the
paragraph. Theme exists three times (Preferences, agent, control) and one
of them works.

### 0.5 What the field does

Every settings surface hobbyists rate as findable is **searchable and
topic-shaped, not process-shaped**: macOS System Settings, Windows
Settings, Home Assistant (which is deleting its global Advanced mode for
per-field disclosure, hobbyist-ux.md §2.4), VS Code. None asks the user
which process owns a knob. Proxmox, the tree's model, is the one that
does, and its own staff proposed a simple view because of it.

---

## 1. The tree

Before, on one machine:

```
Eugene Plexus          Home · Playground · Inference · Apps · Logs · Preferences
  Gateway              Metrics · Routing · Config
  Inference drivers
    qwen3-14b-driver   Config
  Agent · this machine Config · Logs
  Library              Models · Folders · Discover · Config
  Control root         Nodes · Config
```

After:

```
Eugene Plexus          Home · Playground · Apps · Logs · Settings
  Library              Models · Discover · Folders · Settings
  Backends             Overview · Add a backend
    qwen3-14b-driver   Overview · Settings
  Gateway              Metrics · Routing · Settings
  Machines             Overview · Settings
    This machine       Settings · Logs
```

With two machines the machine level appears under Backends and Library as
before, and Machines lists both machines by name. Hover text on the
branches carries the implementation nouns.

**Selection tokens.** Two are new: `backends` (the branch) and
`backends:node:<name>` (a machine's group under it, which opens the
Overview on that machine). Every existing token keeps its meaning:
`control` is the Machines branch, `agent`/`agent:<name>` its leaves,
`driver:<name>@<node>` a backend. A bare `/inference` selects `backends`;
a bare `/config` selects the install (every setting) where it used to
select this machine's agent; `?tab=` still resolves as before.

**What did not change.** The root is the install, not the control root.
Type-first. Machines under the kinds that multiply. A machine with no
backends still appears. `?sel=` addressing. The registry, the icons, the
per-theme accents, the layer map. `role="tree"` is still not built.

---

## 2. Settings, by topic

### 2.1 The topics

The map is `ui/src/lib/settingsTopics.ts`, pure and tested. A field's
topic comes from its component and category, with per-key overrides where
a category mixes two topics.

| Topic                | Owners                | Fields                                                                                                                                                                                |
| -------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Models & downloads   | library               | `modelRoots` (with a link to Folders), `downloadLayout`, `maxConcurrentDownloads`, `catalogueEnabled`, `catalogueBaseUrl`, `hfToken`, `scanOnStartup`, `followSymlinks`, `guidanceContextLength`, `starterModelsFile` |
| Model storage        | each machine's agent  | `pathMappings`, `shareCredentials`, `modelCopyEnabled`, `modelCopyDir`, `modelCopyMinFreeGb`                                                                                          |
| Answer defaults      | gateway               | `defaultTemperature`, `defaultMaxTokens`, `profileCacheSeconds`, `profileMaxStaleSeconds` (with a note that a model's profile fills first)                                             |
| Serving & failover   | gateway               | `modelSlots` (with a link to Routing), `loadBalancing`, `swapWaitSeconds`, `idleCheckSeconds`, `requestTimeoutSeconds`, `routingRefreshSeconds`, `decisionMaxQuestions`, `maxImagesPerRequest` |
| Engines              | each machine's agent  | `engineBinaryRoots`, `allowUnrestrictedEngineLaunch`, `vllmBinary`, `mlxBinary`, `kevPython`                                                                                          |
| Access & security    | agent, control, gateway | agent `securityMode`, `advertiseUrl`, `allowedHosts`; control `securityMode`, `joinTokenTtlSeconds`; gateway `corsEnabled`, `corsAllowedOrigins`                                    |
| Machines             | control, gateway      | `standbyUrls`, `nodePollIntervalSeconds`, `nodeRequestTimeoutSeconds`; gateway `controlUrl`                                                                                            |
| Apps                 | each machine's agent  | `uvBinary`, `allowCustomApps`                                                                                                                                                         |
| Updates              | each machine's agent  | `updateChecks`, `updateChannel`                                                                                                                                                       |
| Metrics & logs       | gateway, every component | `metricsEnabled`, `metricsRetentionDays`, `metricsRollupEnabled`; `logLevel` ×4                                                                                                    |
| Appearance           | this browser          | theme, font size, About                                                                                                                                                               |

Hidden everywhere: `firstRunComplete`, `uiTheme`, `uiFontSize`. A field
the map has never heard of lands in a topic named after its own category,
so a component that adds a knob still gets a card.

### 2.2 The page

`/config` renders topic cards in the order above. A card holds one
**section per owner** — *Gateway*, *Library*, *Control root*, *This
machine*, *Amish_Station* — and a section is one instance of the existing
`ConfigEditor`, restricted to the topic's fields for that owner, with its
header replaced by the owner's name and its Save, Test and Discard shown
only while it is dirty. The editor's state machine — the draft, the
per-key refusal, the restart dialog, the secret handling — is untouched;
two sections of one owner share one fetch of its schema and document.

A sticky bar at the foot counts unsaved changes across every section and
saves them in turn.

**Search.** A box at the top (`?q=`) filters fields by label,
description, key, category and topic; a card with no match disappears; a
match behind *Show more* opens it. It also matches an index of settings
that live on other pages — Folders, Routing, client keys, the Reach
switch, join tokens and versions, per-model profiles, each backend's own
settings — so a search for *API key* or *join* answers with a link.

**One object.** `?sel=gateway` shows the gateway's cards only; the page
menu's *Settings* entry on every object points there. A backend's
Settings page is unchanged: the plain editor, with the *Runs on* line and
*Remove this backend*.

### 2.3 Deep links

`#<key>` on a Settings URL scrolls to that field, opens the disclosure
that hides it, and marks it for a moment. The links that used to say
"the Config page" now say which field.

---

## 3. Every setting, before → after

| Setting                                            | Before                                   | After                                                 |
| -------------------------------------------------- | ---------------------------------------- | ----------------------------------------------------- |
| start / stop / restart / remove a model or backend | Eugene Plexus → Inference                | Backends → Overview; each backend → Overview          |
| install or pin an engine build                     | Eugene Plexus → Inference (engines line) | Backends → Overview (unchanged line)                  |
| add an external backend                            | Inference → button; Home card            | Backends → Add a backend (and the same buttons)       |
| a backend's provider, model, address, API key      | Inference drivers → driver → Config      | Backends → backend → Settings                         |
| launch a model, its profile                        | Library → Models                         | unchanged                                             |
| library folders and mounts                         | Library → Folders; Library → Config      | Library → Folders; Settings › Models & downloads links there |
| catalogue token, downloads at once, scanning       | Library → Config                         | Settings › Models & downloads (also Library → Settings) |
| priority lists                                     | Gateway → Routing                        | unchanged; Settings › Serving & failover links there  |
| idle unload, wake wait, timeouts, balancing        | Gateway → Config                         | Settings › Serving & failover                         |
| default temperature, output cap                    | Gateway → Config                         | Settings › Answer defaults                            |
| CORS                                               | Gateway → Config                         | Settings › Access & security                          |
| request metrics                                    | Gateway → Config                         | Settings › Metrics & logs                             |
| this machine's engines, copies, overrides, updates | Agent → Config                           | Machines → this machine → Settings; and the topics    |
| security mode, allowed hosts, advertise address    | Agent → Config; Control root → Config    | Settings › Access & security (both owners, one card)  |
| the Reach switch, client keys                      | Home                                     | unchanged; indexed by search                          |
| standby roots, poll interval, join-token lifetime  | Control root → Config                    | Settings › Machines / Access & security               |
| join a machine, versions and Update                | Control root → Nodes                     | Machines → Overview                                   |
| theme, font size                                   | Eugene Plexus → Preferences              | Settings › Appearance                                 |
| logs                                               | Eugene Plexus → Logs; Agent → Logs       | Eugene Plexus → Logs; Machines → machine → Logs       |

---

## 4. What stays out

- **No rewrite of `ConfigEditor`'s state.** The sections are instances
  of it. A merged draft across owners would let one Save write two
  components and would need its own restart choreography; per-section
  save with a save-all bar is what every settings app does anyway.
- **No new pages.** Overview on a backend is the Inference page opened on
  it. Overview on Machines is the Nodes page.
- **No mode switch, no tour** (hobbyist-ux.md §9).
- **No deletion of the dead knobs from Python** this session (decision #6).
- **No header-wide search** (decision #8).
- **No change to the website.** Its architecture page names layers, not
  screens, and *inference driver* stays the layer's name there and in the
  layer map.

---

## 5. Verification

- `lib/settingsTopics.test.ts`: every field of every component, taken
  from the schemas the five venvs serve on the day of writing, lands in a
  topic; the hidden three are hidden; an unknown field falls back to its
  category; search matches label, description, key and the elsewhere index.
- `lib/resourceTree.test.ts`: the new shape on the same four fixtures
  (standalone, standalone with a driver, the live two-machine install, a
  sealed root, ten nodes); `backends` and `backends:node:` round-trip; a
  bare `/inference` selects the branch; a bare `/config` selects the
  install; every old token still lands.
- `app/config/page.test.tsx`: the install page shows one section per
  owner including another machine through `node:<name>`; `?sel=gateway`
  shows only the gateway's; the search hides a card with no match and
  opens a disclosure with one; `#key` focuses the field; a backend still
  gets the plain editor.
- `components/ConfigEditor.test.tsx`: the existing cases unchanged, plus
  `only`, the compact header and the shared fetch.
- Browser: `e2e/tree.spec.ts` (branch names, the backend leaf under its
  machine, the leaf's Overview arriving on `/inference`, a bare `/config`),
  `e2e/library-folders.spec.ts` (page order), run by
  `scripts/navigation-acceptance.sh` and
  `scripts/library-folders-acceptance.sh`.
- Sabotage: each new test broken by hand once, recorded in §6.

---

## 6. Implementation record

**Built 2026-09-29, one session, in `ui` (38 files changed, three new).
No contract change, no codegen, no Python consumer moved. Committed
locally on `main` as `931833b`; not pushed, not packaged into `dist`, not pinned** —
the shape and the words are for Troy to look at first (§Decisions).
Run record: [`../acceptance/ui-reorganisation-run.md`](../acceptance/ui-reorganisation-run.md).

### 6.1 What landed

| File                                 | What it is                                                                                          |
| ------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `src/lib/settingsTopics.ts` (+ test)  | The topic map, the hidden keys, the search, the owners a selection shows, the cards, the elsewhere index |
| `src/lib/configTrio.ts`               | One read of a component's schema and document, shared by every section asking at once (5 s)         |
| `src/app/config/page.tsx` (+ test)    | The Settings page: cards by topic, sections per owner, search, save-all bar, deep links; a backend keeps the plain editor |
| `src/components/ConfigEditor.tsx`     | `only`, `compact`, `expandMore`, `focusKey`, `onSection`; the fold decided on the whole schema; hidden keys never rendered |
| `src/lib/resourceTree.ts` (+ test)    | Library · Backends · Gateway · Machines; `backends` and `backends:node:<n>` tokens; `expert` hover nouns; `/inference` and `/backends/add` select Backends; bare `/config` selects the install |
| `src/lib/navigation.ts` (+ test)      | Labels *Backends*, *Settings*, *Machines*; `ROUTES_UNDER_OBJECT` / `subrouteSelection` replace the install-only version |
| `src/components/AppShell.tsx`         | `TopologyContext` for the page inside the shell; an Overview tab named after its object             |
| `src/components/ResourceTree.tsx`     | `useSharedTopology`; the row's hover text carries the implementation noun                            |
| `src/app/inference/page.tsx` (+ test) | `?sel=` narrows to a machine or marks a backend's row, with *Show everything*                        |
| `src/app/globals.css`                 | The deep link's mark                                                                                 |
| twelve other files                    | Cross-links carrying their field, *Config* → *Settings* in copy, the Home cards' anchors, the tests that quoted the old words |

### 6.2 What the build found

**A page renders the shell, so it sits above the shell's provider.** The
first Settings page read the topology through a context the shell
provides to its *children* and called the hook from the component that
rendered the shell — every owner but this machine's agent was missing,
silently, and the unit test that expected four sections found one. The
page's body is a child of the shell now (`ConfigBody`), which is the only
place the shell's topology exists.

**A shared read leaks between tests.** `loadConfigTrio` keeps an answered
read for five seconds so six sections of one component cost one request;
the editor's own suite then handed one test's fixture to the next, and
seven cases failed for a reason that looked like the secret handling.
`vitest.setup.ts` clears it after every test.

**The fold has to be decided before the section takes its share.** A
section of the Access card holds one folded candidate (`allowedHosts`);
decided on the section alone, it would show inline there and fold on
the machine's own page — two answers to "where is it". `foldedKeys` reads
the whole schema, and a page test pins it.

**`queryByLabelText` throws on two hidden matches**, so "the field is not
shown" is asserted as *not visible*, which is what a person means.

**The colour check had been asserting the default theme** since plexus
became it; this was the first run to meet it. It chooses modern now.

### 6.3 Not done

Decision #8 (a header-wide search), decision #6's Python deletion, and
the shipping steps: push `ui`, `npm run build:python`, the `dist` worktree,
`PIN_UI` in both installers, then a fourth `navigation-acceptance.sh` off
the pinned archive.
