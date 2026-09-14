# A resource tree, the way a cluster manager does it (design)

**Status:** designed 2026-09-13 (late), on Troy's direction after seeing
the shared navigation land. Supersedes the top bar built that day
(`ui-navigation.md`), **not** the registry underneath it, which becomes
this design's spine. Every claim marked *measured* was checked against a
file or a running process on the day of writing; everything else is
reasoning and marked as such. §13 is the implementation record.

**Troy's words, which are the brief:**

> A tree going down the left side. Control is the root of the tree.
> Component types are the first branches. When you open a component in
> the tree that exists on multiple nodes, list the nodes under the
> component type. When the user clicks on the component→node, you get a
> vertical menu with any appropriate pages for that component on that
> node. Agents can show config. Libraries show Discover and Config.
> Config can be split into logical pages instead of one monolith. To me
> we're building something very much like a Proxmox cluster.

**Why it is right, in one line.** This product's nouns are *objects in a
topology* — a gateway, N agents, M drivers, a library, a control root,
each somewhere — and a link bar can only name *screens*. A cluster
manager's tree names objects, which is what an operator is actually
looking for.

**What it is not.** Not new features. No new endpoints, no contract
change, no invented screens. Every page in the second column below is a
screen that exists today.

---

## Decisions

| #     | The call                                                              | §    | Recommendation                                                                                      | Status |
| ----- | --------------------------------------------------------------------- | ---- | --------------------------------------------------------------------------------------------------- | ------ |
| **1** | The tree's root is **the install**, not the control root              | §2.1 | The install. A root that needs the trust root to answer disappears exactly when it is needed        | **taken as recommended — Troy's to overturn, he said "control is the root"** |
| **2** | Type first, node second                                               | §2.2 | Yes, as briefed. Measured: 3 of 5 kinds are install singletons                                       | taken as briefed |
| **3** | A second column of pages for the selected object                      | §3   | Yes, as briefed                                                                                      | taken as briefed |
| **4** | **Config does not split into pages in this slice**                    | §5   | Don't. Measured: 5-15 fields per component. The agent's 7 across 6 categories is one field a page    | **taken as recommended — Troy's to overturn, he asked for the split** |
| **5** | Tree state rides in query parameters, not path segments               | §7   | Forced by `output: "export"`; already this UI's pattern                                              | forced |
| **6** | A thin top bar survives for brand, sign out and the layer map         | §6   | Keep it. Proxmox keeps one, and sign out must not live inside a tree of objects                     | taken as recommended |
| **7** | The layer registry survives unchanged and becomes the tree's spine    | §1   | Yes. Type branches *are* layers; the icons and colours already exist                                 | taken as recommended |

---

## 0. What measuring found

### 0.1 The tab strip grows with the topology, and drivers dominate

*Measured* in `ui/src/app/config/page.tsx`: a tab is generated for the
UI, for **one agent per node**, for **up to three install singletons**,
and for **every `inference-driver` in the install**. Since M6 the agent
declares one companion driver per runtime (`agent/…/companions.py`:
*"one inference-driver per runtime"*), so:

```
tabs = 1 + nodes + (≤3 singletons) + every driver
```

| Install                        | Agents | Singletons | Drivers | Buttons |
| ------------------------------ | -----: | ---------: | ------: | ------: |
| This one, two nodes            |      2 |          3 |       0 |       6 |
| Ten nodes, four models each    |     10 |          3 |      40 |      54 |

Fifty-four buttons in a wrapping horizontal strip. This is the defect
that started the conversation, and it is a property of *one screen
holding every object*, which a tree removes by construction.

### 0.2 Three of five kinds are install singletons — so type-first is right

*Measured* against `ComponentKind` (`gateway`, `inference-driver`,
`library`, `control`) plus the agent, which is not a component:

| Kind              | Cardinality        |
| ----------------- | ------------------ |
| Gateway           | one per install    |
| Library           | one per install    |
| Control root      | one per install    |
| Agent             | one per **machine** |
| Inference driver  | one per **backend** |

Proxmox defaults to node-first and offers type-first as a second view.
**Here type-first is the better default**, and the reason is this table
rather than taste: node-first buries three install-wide singletons under
whichever host happens to run them, which is precisely the wrong mental
model for a gateway that is *the* front door. The two kinds that
multiply get nodes beneath them, exactly as briefed.

### 0.3 No single component's config is a monolith

*Measured* by counting `category="…"` in each component's config module:

| Component         | Fields | Categories |
| ----------------- | -----: | ---------: |
| `gateway`         |     15 |          6 |
| `library`         |     10 |          6 |
| `control`         |      9 |          6 |
| `agent`           |      7 |          6 |
| `inference-driver`|      5 |          3 |

`ConfigField.category` is **required** in `common.yaml` and
`ConfigSchema.categories` maps it to a display label, so a split is
already available as data and needs no contract work. But splitting the
agent's **7 fields across 6 categories** gives roughly one field per
page, which is worse than the sections it has now. **The monolith was
never a component's config; it was the screen holding every component's
config**, and §2 dissolves that. See decision #4.

### 0.4 The control root is already optional, and the code says so

*Measured* in `config/page.tsx`: `installPlacement()` and
`installNodes()` both swallow their errors, with the comment
*"Standalone, or the root is down or sealed: this host's own topology is
the whole answer."*

That is not an accident — it is this project's most expensive lesson,
learned twice. A restarted container comes back **sealed** while every
health check reports `ok`; and until `bccdebc` the gateway could not
find the control root at all. The UI is served by **every** agent
precisely so a worker's browser is a console for the install.

**A tree whose root node *is* the control root inherits all of that as a
navigation failure**: seal the root and the operator loses the tree,
including the branch describing the machine they are sitting at. So the
root is the install — an abstraction, assembled from soft sources, like
Proxmox's Datacenter — and the control root is a first-level branch
beside the others. If Troy wants the label to read differently that is a
one-string change; the structure is what matters.

### 0.5 Static export forbids arbitrary path segments

*Measured* in `next.config.ts`: `output: "export"` with
`trailingSlash: true`. An export emits one HTML file per route, so a
dynamic segment needs `generateStaticParams`, and **node and driver
names are not known at build time**. Tree state therefore rides in query
parameters.

That is already the convention here, not a workaround: `?tab=` on
Config, `?model=` on Library, `?next=` on login.

### 0.6 The screens are already object-shaped, and two of them say so

*Measured:* `/inference` joins four soft sources into rows keyed by
driver and node. `/library` and `/discover` already carry a node picker.
And `/inference` tells the operator to **go to the Config page for a
driver's settings in three separate places** — the code asking for this
design.

### 0.7 Two page shells, from the slice before this

Five screens are `flex h-screen flex-col`; `/metrics` and `/nodes` are
ordinary scrolling documents. A two-column shell has to wrap both.

---

## 1. What survives

`ui/src/lib/navigation.ts` — the eight layers of
`eugeneplexus.com/architecture` with their names, icons and colour
roles — **is unchanged and becomes the tree's spine**. The tree's first
branches *are* layers:

| Branch            | Layer             | Icon         | Accent |
| ----------------- | ----------------- | ------------ | ------ |
| Gateway           | Gateway           | `Radio`      | right  |
| Inference drivers | Inference drivers | `Cpu`        | left   |
| Agents            | Agent             | `Server`     | left   |
| Library           | Library           | `Database`   | left   |
| Control root      | Control root      | `ShieldCheck`| right  |

**Engines and backends** and **Your hardware** get no branch, because
neither is a component — and they need none: an engine is what a driver
fronts, and hardware is what a node has, so both appear as *content* on
the object that owns them. The layer map panel keeps explaining all
eight.

So the previous slice is not discarded. The registry, the icon set, the
per-theme accent tokens and the pure-module discipline are what make
this buildable at all.

---

## 2. The tree

```
▾ <install name>                     Playground · Inference
  ▸ Gateway                          Metrics · Config
  ▾ Inference drivers
    ▾ Amish_Station
        ollama-qwen                  Config
        llama-1                      Config
    ▸ nas
  ▾ Agents
      Amish_Station                  Config
      nas                            Config
  ▸ Library                          Models · Discover · Config
  ▸ Control root                     Nodes · Config
```

### 2.1 The root is the install

Labelled with the install's own name where the control root offers one,
and `Eugene Plexus` otherwise. Its pages are the things that are true of
the whole install rather than of one component: the **playground** (one
endpoint for everything) and **Inference** (what is serving, anywhere).

§0.4 is the argument. A sealed or unreachable root must degrade to a
tree that still shows this node and its components, with a line saying
why the rest is missing.

### 2.2 First branches are component types

In the registry's layer order. A singleton branch is its own leaf: click
`Gateway` and you get the gateway's pages, with no node level, because
there is exactly one. §0.2 is why this is the default rather than
node-first.

### 2.3 Nodes appear under the kinds that multiply

`Agents` and `Inference drivers` only. Under `Agents`, a node *is* the
leaf. Under `Inference drivers`, the node is a group and the drivers are
the leaves, which is what "two workers can each have a `llama-1`" makes
necessary.

**A node with no drivers still appears** under `Inference drivers`, as
an empty group. Hiding it would make "this machine is running nothing"
indistinguishable from "this machine is not in the install", which is
the ambiguity `/inference` was built to remove.

---

## 3. The page menu

A second column, as briefed, listing the pages that apply to the
selected object. Every entry is a screen that exists:

| Object            | Pages                       |
| ----------------- | --------------------------- |
| The install       | Playground, Inference       |
| Gateway           | Metrics, Config             |
| Driver @ node     | Config                      |
| Agent @ node      | Config                      |
| Library           | Models, Discover, Config    |
| Control root      | Nodes, Config               |

**Two of these are one item long, and that is reported rather than
padded.** The UI has seven screens and the tree has more objects than
that, so the column is thin for agents and drivers today. Inventing an
"Overview" to fill it would be adding product under cover of a
navigation slice. What the tree does instead is make the empty slots
*visible and obvious*, which is the same complaint Troy made about the
request path looking incomplete, one level deeper. The data for an agent
overview already exists at `GET /v1/node`; it is the obvious next slice
and it is not this one.

---

## 4. Where the seven screens land

| Today        | Becomes                                         |
| ------------ | ----------------------------------------------- |
| `/`          | The install → Playground                        |
| `/inference` | The install → Inference                         |
| `/metrics`   | Gateway → Metrics                               |
| `/library`   | Library → Models                                |
| `/discover`  | Library → Discover                              |
| `/nodes`     | Control root → Nodes                            |
| `/config`    | The **Config** page of whichever object is selected |

**No route is deleted and no page is rewritten.** `/config` stops owning
a tab strip and starts taking its subject from the URL; the tree is what
writes that URL. `/runtimes` keeps redirecting.

---

## 5. Config: not split, and the measurement is why

Decision #4, and the one place this design declines the brief.

§0.3 measured 5 to 15 fields per component across 3 to 6 categories.
Splitting those into pages produces pages with one or two fields. The
split Troy is reaching for is the one §2 already performs: **Config
stops being one screen holding every object and becomes one page
belonging to one object.**

If a component grows past roughly a dozen fields the split becomes
worthwhile, and it is then free: `category` is required on every field
and `categories` already carries display labels, so the page menu can
render one entry per category with no contract change. The gateway, at
fifteen, is the only candidate today. **Troy's to overturn** — the cost
is small and the mechanism is already there.

---

## 6. Layout

Three columns at desk width: tree, page menu, content. A thin top bar
survives above them for the brand, the layer map and **Sign out**, which
must not live inside a tree of objects.

**Narrow screens collapse the tree to a drawer** toggled from that bar,
because a 430px viewport has no room for three columns and the previous
slice's responsive behaviour is not something to lose. The page menu
becomes a horizontal scroller under the header at that width — bounded,
because a single object never has many pages.

The tree is `<nav aria-label="Install">` with `role="tree"` semantics,
keyboard-navigable, and remembers which branches are open per browser.

---

## 7. Addressing

Forced by §0.5. One query parameter names the selected object and the
existing routes are the pages:

```
/config/?sel=agent:Amish_Station
/config/?sel=driver:ollama-qwen@Amish_Station
/metrics/?sel=gateway
/library/?sel=library
```

`sel` is parsed by one pure function, so a bad or stale value selects
nothing rather than throwing, and a link pasted from an older build
still lands on a page. Config's existing `?tab=` keeps working and is
translated, because the launch panel's "map it" link writes it.

---

## 8. Degradation

The tree is assembled from four sources, each already soft: this
agent's `/v1/components` and `/v1/node`, and the root's `/v1/components`
and `/v1/nodes`. The rule from the Inference screen applies unchanged —
**the page you open when something is wrong must not fail because
something is wrong.**

With the root unreachable the tree shows the install root, this node's
agent, and this node's components, plus one line naming what is missing
and why. That is strictly more than today's Config strip manages.

---

## 9. What stays out

No new screens, no new endpoints, no contract change, no codegen, no
Python consumer re-pinned. No search box in the tree yet: it earns its
place past a few dozen objects and this install has six.

---

## 10. Radius

`ui` only, plus the `dist` rebuild and `PIN_UI` in both installers.
New: a tree model module and its tests, a `ResourceTree`, a `PageMenu`,
an `AppShell`, and an e2e spec. Edited: the seven pages' headers again,
and `AppNav` loses its link row and keeps its bar.

The default theme stays `modern` and none of its four spellings is
touched.

---

## 11. Verification

**vitest, on the pure tree model:** the tree built from a fixture
topology has the right branches in the right order; singletons carry no
node level; two nodes with a same-named driver produce two distinct
leaves; a node with no drivers still appears; the root's label falls
back; `sel` round-trips and a malformed `sel` selects nothing; every
page entry points at a route that exists; the root-unreachable fixture
still yields this node's subtree. Sabotage each.

**Playwright, against a real install:** every object in the tree is
reachable and selects; the page menu shows the expected pages for three
different object kinds; selecting a driver on another node lands on its
config; the tree survives a sealed root; the drawer opens at 430px; the
layer colours still match the website.

---

## 12. Traps known in advance

- **`useSearchParams` suspends during prerender.** Every page reading
  `sel` needs the Suspense boundary Config already has.
- **The acceptance run must stage the export first** — the agent venv
  here has `eugene-plexus-ui` installed editable.
- **`trailingSlash: true`** makes `toHaveURL(/\/$/)` match every page.
  Assert on the selection, not the slash.
- **Two workers can each have a `llama-1`.** A leaf's identity is
  `name@node`, never `name`.
- **An enrolled node declares none of the three singletons**, so a
  worker's own `/v1/components` will not contain the gateway. The tree
  must take singletons from the root's placement, as Config already
  does.

---

## 13. Implementation record

**Built and verified 2026-09-13 (late), one unattended session.** `ui`
`6cc568d` (dist `cc7651b`), pinned in both installers. **No contract
change, no codegen, no Python consumer re-pinned.**
`scripts/navigation-acceptance.sh`, **17 checks, ALL PASSED**.

### 13.1 What landed

| File                              | Lines | What it is                                        |
| --------------------------------- | ----: | ------------------------------------------------- |
| `src/lib/resourceTree.ts`         |   626 | The model. Pure; no React, no DOM, no fetching     |
| `src/lib/resourceTree.test.ts`    |   444 | 42 cases against four real topologies              |
| `src/components/ResourceTree.tsx` |   341 | The tree, and the `useTopology` hook               |
| `src/components/AppShell.tsx`     |   294 | Top bar, three columns, the page menu              |
| `e2e/tree.spec.ts`                |   238 | 11 browser tests                                   |

Gone: `AppNav.tsx` and `ScreenHeader.tsx`, the previous slice's top bar.
Kept and unchanged: `navigation.ts`, `LayerIcon.tsx`, `LayerMap.tsx`, the
per-theme accent tokens, the skip link.

**The seven pages now spend 94 lines between them on the shell**, down
from 181 on the previous header and 275 on the hand-written ones before
that. Config went from 311 lines with a tab builder reading four
endpoints to one page about one object.

### 13.2 The two defects the first build had

**Both were found by writing the fixture for the commonest install there
is**, and neither would have survived it.

**A standalone box has no node name anywhere.** It is not enrolled, so
`GET /v1/node` carries none and the registry is empty, and a companion
driver declared locally has no `node` field either. The first
`driverBranch` grouped by label and matched against the node list, so on
one box with a model launched it **dropped every driver**. Grouping is by
the driver's *resolved* machine now, and that key may legitimately be
null.

**`/config` with no query asks for the bare token `agent`, and an
enrolled node's row is `agent:<name>`.** The two never met: the page menu
rendered nothing and the tree highlighted nothing, silently.
`findSelected` resolves the two shapes that legitimately under-specify —
a bare `agent` is the local one, a bare `driver:<name>` is a legacy
`?tab=` link.

That second one also proved a structural point: **the tree and the page
menu must not build the topology separately.** The first version had each
fetch its own, and they disagreed the moment a selection under-specified.
One `useTopology` hook, one tree, both consumers reading the same object.

And one more, found by the browser: **the page list comes from the
selection's *kind*, not from the resolved row.** Reading it off the row
left the menu empty between first paint and the topology arriving, which
is a real flash and not only a test artefact.

### 13.3 Verification

**42 vitest cases**, five sabotage-checked, against four topologies: a
standalone box, the same with a driver, the live two-machine install, a
**sealed control root**, and a generated ten-node install with forty
drivers. The sealed case is the one nobody can produce on demand, which
is exactly why the model is pure.

**11 browser tests, and three sabotages were run against them. Two
escaped**, and one named the gap it left:

| Sabotage                                               | First suite | After |
| ------------------------------------------------------ | ----------- | ----- |
| Drivers hang off the type, with no node level          | **passed**  | fails |
| Page menu reads the resolved row (the empty-menu race) | fails       | fails |
| A bare `agent` no longer resolves to this machine      | **passed**  | fails |

**A check called "a driver sits under its machine" asserted only that the
leaf existed.** It never asserted the nesting its own name claims, so a
tree with the node level removed entirely passed it. Rows carry
`data-tree-children` now and the check asserts the nesting; a bare
`/config` is its own case. Same family as M10's check 7, step 6's
fragmentation checks, and the prefix case in the slice before this: **an
assertion whose subject cannot produce the failure is green for the wrong
reason.**

`install-acceptance.sh` after the pin bump: **checks 1-16 pass in WSL2**
from nothing, serving the UI from the new `dist` pin. **Check 19 fails on
purpose** — the live install's own agent holds 8079 on this box. Check 14
failed once and passed on a re-run, so it is flaky (a child still exiting
when the orphan count is taken); unrelated to this slice and worth
knowing.

### 13.4 Seen in a browser

Screenshots at 1500px and 430px: the tree reads `Eugene Plexus` →
Gateway, Inference drivers (→ machine → driver), Agents (→ machine),
Library, Control root, each with its layer icon and colour and its
machine as a muted hint. The page menu reads `nav-node · Config`, or
`Library · Models · Discover · Config`. At 430px the tree is a drawer
with a dimming backdrop, bounded below the header.

---

## 14. Where the build departed from this design

1. **The install root gained a third page, `Preferences`.** §3 listed
   Playground and Inference. The old Config page had a `UI` tab holding
   theme and font size — browser-local, the one thing there that is not a
   component's settings — and `gui-equality-for-configurable-things` says
   nothing may become unreachable. It hangs on the install root, the only
   row in the tree that is not a component.

2. **A node group is labelled by the machine even when the registry has
   never heard of it.** §2.3 implied an `Unplaced` group. In practice the
   driver's own `node` is a better label than a category, so the group is
   named and *flagged* (`no node in the registry`) instead. The node list
   itself is the registry plus this machine and nothing else — harvesting
   names out of placements would mint agent leaves for machines nothing
   has evidence of.

3. **`ResourceTree` does not own its data.** §10 implied a component that
   fetches. §13.2 is why it does not.

4. **No `role="tree"` semantics.** §6 asked for them. What landed is a
   `<nav aria-label="Install">` of links and disclosure buttons, which a
   keyboard reaches because links and buttons already are reachable. Full
   `treeitem` / `aria-level` semantics with arrow-key traversal is a real
   piece of work and was not started; the honest state is that this is an
   accessible list of links, not an accessible tree widget.

5. **The install has no name, so the root is labelled `Eugene Plexus`.**
   §2.1 said "labelled with the install's own name where the control root
   offers one". Nothing on control's surface offers one — not
   `/v1/control/status`, not the node registry. The model still takes an
   `installName` and the fallback is tested, because naming an install is
   an obvious contract addition; **an endpoint to read it was invented in
   the first draft and removed** rather than shipped.

6. **`scripts/navigation-acceptance.sh` declares a driver first.** Not in
   the design. The three-level path (type → machine → driver) is the only
   one of its kind in the tree, and a fleet with no drivers cannot
   exercise it.
