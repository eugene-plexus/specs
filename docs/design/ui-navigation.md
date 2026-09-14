# Navigation that mirrors the architecture (design)

**Status:** designed 2026-09-13 (late). A UI-only slice, taken before
install-paths [§9 step 9](install-paths-and-distribution.md) (the
release), which stays last. Every claim marked *measured* was checked
against a file in `d:\py\eugene-plexus\ui` at `d03fdff` or
`d:\py\eugene-plexus\website` at `3b5129c` on the day of writing;
everything else is reasoning and marked as such. §10 is the
implementation record, appended as the work lands.

**What it is.** One shared navigation for the web UI, organised the way
`https://eugeneplexus.com/architecture` organises the system: the same
layer names, the same icons, the same colours. The test it has to pass
is Troy's: *a person who has read that page should know where every
screen lives before they click.*

**What it is not.** Not a product slice. No new screens, no new data, no
new endpoints, no contract change. Every link below already exists
somewhere in the UI today; this moves them into one place and says what
each one is part of.

---

## Decisions

| #     | The call                                                                 | §   | Recommendation                                                                       | Status |
| ----- | ------------------------------------------------------------------------ | --- | ------------------------------------------------------------------------------------ | ------ |
| **1** | Horizontal two-row header, not a left rail                               | §3  | Two rows. A rail rewrites the shell of seven pages, which is past "navigation only"  | taken as recommended (unattended) |
| **2** | Group the bar by the page's *two halves*, not by its eight layers        | §3.1 | Two groups. Six group labels for seven items is a label per item, which teaches nothing | taken as recommended |
| **3** | The icon is the primary identity; colour is secondary                    | §4.2 | Yes. `--accent-left` is blue in one theme of three, so colour alone cannot carry it   | taken as recommended |
| **4** | A layer map panel, reachable from every screen                           | §3.3 | Build it. It is the artifact that teaches; the bar is the artifact that is fast       | taken as recommended |
| **5** | `Config` files under **Agent**, and says it spans every component        | §2.2 | Yes. Its addressing is per node, and a node is an agent                               | taken as recommended |
| **6** | Green and grey become per-theme tokens, not literals                     | §4.3 | Tokens. A literal `#2f9e6e` is one theme's answer, and there are three                | taken as recommended |

---

## 0. What measuring the current navigation found

Seven measurements, all against `ui@d03fdff`.

### 0.1 The handoff's premise was wrong, and the truth is worse

The prompt for this slice said *"every page repeats an inline header row
(New, Library, Discover, Inference, Metrics, Nodes, Config, Sign out)"*.
**Measured: exactly one page has that row.** The other six each have a
different, shorter, hand-picked set. This is the project's recurring
documentation failure — a claim about the code that nobody re-derived —
and it is recorded here because it changes the work: the problem is not
*duplication of one row*, it is *seven disagreeing rows*, which is a
harder defect and a better reason to build a shared component.

Header blocks, measured by line span:

| Screen       | Header lines | Links in the header, in order                                                              |
| ------------ | -----------: | ------------------------------------------------------------------------------------------ |
| `/`          |           71 | Diagnostic (toggle), New, **Library, Discover, Inference, Metrics, Nodes, Config**, Sign out |
| `/library`   |           51 | ← Back to playground (`/`), Rescan/Deep rescan/Cancel, Discover, Config                     |
| `/discover`  |           34 | ← Back to library (**`/library`**, not `/`), Config                                         |
| `/inference` |           35 | ← Back to playground (`/`), Launch a model (`/library`), Add an external backend (`/config`), Nodes |
| `/metrics`   |           36 | window select, Refresh, Back (`/`)                                                          |
| `/nodes`     |           15 | Back (`/`)                                                                                  |
| `/config`    |           33 | ← Back to playground (`/`), the tab strip, Inference                                        |

**275 lines of hand-written header across seven files**, no two alike.

### 0.2 The topology is a star, and three screens are leaves

Counting only header links, the reachability graph is:

```
            /library ──→ /discover ──→ /config
               ↑ │           │            │
               │ ↓           ↓            ↓
   /  ←──────────────────────────────────────  (every screen's "Back")
   │
   ├──→ /library  /discover  /inference  /metrics  /nodes  /config
   │
/inference ──→ /library, /config, /nodes
```

Distinct header destinations per screen: `/` = 6, `/inference` = 4,
`/library` = 3, `/discover` = 2, `/config` = 2, **`/metrics` = 1**,
**`/nodes` = 1**.

So from `/metrics` or `/nodes` the only move is back to the playground.
From `/discover`, reaching `/inference`, `/metrics` or `/nodes` takes
two hops through a chat screen. **The playground is load-bearing as a
router**, which is not a job a chat screen should have.

### 0.3 "Back" means two different things

`/discover`'s back link goes to `/library`; every other back link goes
to `/`. Both are labelled with a leading `←`. So the one affordance that
appears on five screens is not one affordance.

### 0.4 Sign out exists on exactly one screen

*Measured:* `handleLogout` and the string `Sign out` occur only in
`src/app/page.tsx`. `clearSessionToken` is imported nowhere else.
An operator on `/metrics` cannot end their session without first
navigating to a chat screen.

### 0.5 There is no navigation landmark, no current-page marking, no skip link

*Measured:* `aria-current` — **0 occurrences**. `usePathname` — **0**.
`<nav>` — **1**, and it is `/config`'s tab strip, not navigation between
screens. No skip link anywhere. So a screen reader gets seven unlabelled
link clusters and no way to tell which screen is open, and a keyboard
user tabs through the whole header on every page.

### 0.6 Two page shells, and a shared header must live in both

*Measured:* five screens are `<main className="flex h-screen flex-col">`
with a fixed header and a scrolling body (`/`, `/library`, `/discover`,
`/inference`, `/config`). Two are ordinary scrolling documents
(`/metrics` is `mx-auto max-w-6xl px-6 py-8`, `/nodes` is `max-w-4xl`).
A shared header has to be droppable into both without either page's
layout changing, which rules out anything that owns the page's width.

### 0.7 There are four theme palettes, and blue is blue in one of them

*Measured* in `src/app/globals.css`: `:root`/`[data-theme="modern"]`,
`[data-theme="cyberpunk"]`, `[data-theme="editorial"]` (plus `system`,
which resolves to modern or cyberpunk and defines no tokens of its own).

| Theme      | `--accent-left`   | `--accent-right`  |
| ---------- | ----------------- | ----------------- |
| modern     | `#2a55e6` blue    | `#cf3a85` pink    |
| cyberpunk  | `#1bd9c2` teal    | `#ff7ac0` pink    |
| editorial  | `#2d6240` green   | `#a23b29` rust    |

The website is the modern palette by name and by value — `--panel`,
`--panel-soft`, `--panel-hover`, `--border`, `--border-hover`,
`--accent-left`, `--accent-right`, `--on-accent-*`, `--muted`,
`--radius: 6px` all match, byte for byte, between
`website/src/styles/global.css` and the modern block. So the handoff's
"the palette already exists" is true — **of one theme out of three.**

The consequence is §4.3's: `#2f9e6e` as a literal would be a second
green in editorial, sitting next to `--accent-left: #2d6240`, meaning
two different things. The colours have to be tokens with a per-theme
value, and the identity has to be carried by something that does not
vary — which is the icon.

### 0.8 What is on the site that the UI has none of

*Measured:* `grep -c '<svg'` across `ui/src` is **0**. The UI has no
icon library and no inline icon; the only image asset is
`public/eugene-icon.svg`. The site imports `@lucide/astro` **1.45.0**;
`lucide-react` **1.45.0** is the matching package and is reachable from
this box (`npm view` answered).

---

## 1. The vocabulary, transcribed

From `website/src/pages/architecture.astro`. This table is the contract
between the two repos; §6's test asserts the UI's registry against it.

**The request path, top to bottom:**

| Layer                   | Icon        | Colour role      | modern value |
| ----------------------- | ----------- | ---------------- | ------------ |
| Your tools              | `Terminal`  | `--accent-left`  | `#2a55e6`    |
| Gateway                 | `Radio`     | `--accent-right` | `#cf3a85`    |
| Inference drivers       | `Cpu`       | `--accent-left`  | `#2a55e6`    |
| Engines and backends    | `Cloud`     | `--accent-engine`| `#2f9e6e`    |
| Your hardware           | `HardDrive` | `--accent-hardware` | `#8a8a93` |

**Beside the path:**

| Service       | Icon         | Colour role      |
| ------------- | ------------ | ---------------- |
| Agent         | `Server`     | `--accent-left`  |
| Library       | `Database`   | `--accent-left`  |
| Control root  | `ShieldCheck`| `--accent-right` |
| Web UI        | `Monitor`    | `--accent-left`  |

**Elsewhere on the page:** model folders `FolderOpen`, secrets
`KeyRound`. Both are used below.

*Measured detail worth keeping:* on the site the Library rail card takes
the default `.layer-label svg { color: var(--accent-left) }` — only
`.rail-control` overrides to pink. So Library is blue there, and is blue
here.

---

## 2. Every screen, mapped

### 2.1 The map

| Screen       | Home                 | Also spans                                | Icon         |
| ------------ | -------------------- | ----------------------------------------- | ------------ |
| `/`          | Your tools           | —                                         | `Terminal`   |
| `/metrics`   | Gateway              | —                                         | `Radio`      |
| `/inference` | Inference drivers    | Engines and backends, Your hardware       | `Cpu`        |
| `/library`   | Library              | Your hardware (model folders)             | `Database`   |
| `/discover`  | Library              | Your hardware (fit guidance)              | `FolderOpen` |
| `/config`    | Agent                | every component, on every node            | `Server`     |
| `/nodes`     | Control root         | —                                         | `ShieldCheck`|

Plus, outside the navigation: `/login` and `/setup` (no session yet, so
no nav — §3.4), `/runtimes` (a redirect stub to `/inference`, kept for
old links), and `error.tsx`.

**Seven navigable screens.** The rest of this section defends the three
rows that are not obvious.

### 2.2 The three that resist a single layer

**`/inference` spans three layers, and that is the screen's whole
point.** Its rows are gateway drivers ⋈ control runtimes ⋈ placement —
a driver (Inference drivers), what it fronts (Engines and backends), and
the node it runs on (Your hardware). Filing it under one layer and
hiding the other two would misdescribe the one screen that exists
because those three are different things. So it files under
**Inference drivers** — the layer it is named for and the one it
addresses when you act on a row — and it **declares its span**, which
§4.4 renders.

**`/config` has a tab per component per node.** *Measured:* the tab
builder emits `UI`, `Agent @ <node>` for every node, and
`<Component> @ <owner>` for every component in the topology. So Config
is not the Agent's screen; it is every component's settings, *addressed
by node*. It files under **Agent** for the reason the addressing gives:
a node is a machine, a machine runs one agent, and every path in a
component's config is a path on the host that component runs on — which
is the sentence the Config page already prints on every tab. Its span is
"every component", which the map panel shows as a dashed tie to all of
them rather than as a fourth colour.

**`/discover` is a Library screen, not a third service.** Catalogue
search, downloads and quant guidance are all `library` endpoints. It
gets `FolderOpen` rather than a second `Database` so the two Library
screens are distinguishable at a glance while sharing a colour — and
`FolderOpen` is the site's own icon for "your model files, where you put
them", which is exactly what a download lands as.

### 2.3 What the map does *not* invent

`Web UI` (`Monitor`), `secrets` (`KeyRound`) and `model folders`
(`FolderOpen`) are on the site and have no screen of their own. They
appear in the map panel — `Monitor` labels the panel itself ("you are
here"), `KeyRound` labels Sign out — and nowhere else. No new noun is
introduced anywhere in this slice.

---

## 3. The shape

### 3.1 Two rows

**Row 1 — the navigation. Identical on every screen.** Brand mark, the
seven links in two labelled groups, the map toggle, Sign out.

**Row 2 — the screen header. Per screen.** Layer icon in its colour, the
`<h1>`, the layer breadcrumb (§4.4), then whatever controls that screen
already had.

Two rows rather than one because §0.1 measured what happens when a
screen's own controls compete with its links for a single row: six
different answers, three of which dropped links. Separating them means a
page can add a control without deciding which link to cut.

The cost is one ~40px row on seven screens. On `h-screen` chat that is
worth it; §0.6's second shell (`/metrics`, `/nodes`) pays nothing, since
those already scroll.

**Rejected: a left rail.** It mirrors the architecture page most
literally, since that page *is* a vertical stack. It is rejected because
it rewrites `<main>` on seven pages into a two-column shell, which is
past the boundary Troy drew for this slice ("navigation only"), and
because the playground is a chat screen that wants its width. If the
grouped bar turns out not to teach, the rail is the next thing to try,
and §0.6 is the measurement that says what it would cost.

### 3.2 Groups: the page's two halves

The architecture page is itself divided in two: a `layers-stack` (the
request path) and a `layers-rail` (three services beside it). The
screens divide the same way, so the bar does too:

```
  THE REQUEST PATH                     BESIDE THE PATH
  Playground · Metrics · Inference     Library · Discover · Config · Nodes
```

Within the request-path group the order is the stack's own order, top to
bottom: tools (Playground) → gateway (Metrics) → drivers, engines,
hardware (Inference). Within the second group the order is the rail's:
Library, Library, Agent, Control root.

**Rejected: one group per layer.** Eight labels for seven items is a
label per item, which is a caption, not a grouping. Two groups, each
with a name the reader has already seen on the site, is the grouping
that carries information.

### 3.3 The map panel

A single control in row 1 opens a panel that *is* the architecture
page's diagram: five layers stacked, three services beside them, each in
its icon and colour, each carrying the screens that live there as links.
Config appears as a dashed tie across the components rather than inside
one.

This is where the teaching happens. The bar is the fast path for someone
who already knows; the panel is for someone who read the page an hour
ago and wants to see the same picture. It renders from the same registry
the bar renders from, so the two cannot disagree.

It is a disclosure, not a route: no URL, no history entry, `Escape`
closes it, focus returns to the toggle.

### 3.4 Where the navigation does not appear

`/login` and `/setup`. Neither has a session, so every link in the bar
would 401, and `/setup`'s wizard is a linear transaction that a stray
click out of would abandon. *Measured:* both already render their own
standalone `<main>` and neither imports any nav link today, so this
costs nothing — it is a statement of intent for the next person, not a
change.

---

## 4. Rendering

### 4.1 One registry, one source of truth

`src/lib/navigation.ts` — pure, no React, no DOM:

```ts
export type LayerId =
  | "tools" | "gateway" | "drivers" | "engines" | "hardware"
  | "agent" | "library" | "control";

export interface Layer {
  id: LayerId;
  name: string;        // exactly the site's label
  icon: IconName;      // exactly the site's icon
  accent: AccentRole;  // "left" | "right" | "engine" | "hardware"
  side: "path" | "beside";
}

export interface Screen {
  href: string;
  label: string;
  icon: IconName;
  layer: LayerId;      // its home
  spans: LayerId[];    // additional layers, in path order
  blurb: string;       // one line, for the map panel and the title
}
```

The bar, the screen header, the map panel and both test suites all read
this. A screen added without a registry entry does not appear in the
nav, which is a failure a test can see.

### 4.2 Icons are the identity; colour is the echo

§0.7's measurement forces this. `--accent-left` is blue in modern, teal
in cyberpunk and **green** in editorial, so "the blue ones" is not a
sentence that survives a theme switch — and in editorial a literal
engine green would be a second green meaning something else. The icon
does not vary, so the icon carries the meaning and colour reinforces it
inside whichever palette is active.

This is also the accessible answer: colour is never the only channel.
Every nav item is icon + text label; the colour adds a third cue for
people who have learnt it.

`lucide-react@1.45.0`, the same version and the same icon set the site
uses, imported by name so twelve icons are what ships.

### 4.3 Two new tokens, three values each

Added to `globals.css` beside the existing accents:

| Token                | modern    | cyberpunk | editorial |
| -------------------- | --------- | --------- | --------- |
| `--accent-engine`    | `#2f9e6e` | `#5ef2a0` | `#7d6b1f` |
| `--accent-hardware`  | `#8a8a93` | `#9b93bd` | `#9a927f` |

Modern takes the site's exact literals, because modern *is* the site's
palette and the default theme (§0.7). The other two are chosen for
separation **within their own palette**, not for resemblance to the
site: cyberpunk's engine green has to clear its teal `--accent-left`,
and **editorial's engine role is not green at all** — it is an
olive-gold, because `--accent-left: #2d6240` already occupies green
there. That is a deliberate departure and the reason §4.2 puts the
identity in the icon.

A useful consequence of §2.1, worth stating because it bounds the risk:
**no screen's home layer is engines or hardware**, so the bar renders
only `--accent-left` and `--accent-right`. The two new tokens appear
exactly twice — in `/inference`'s breadcrumb and in the map panel — and
in both places the layer's **name is written next to the colour**. There
is no place where a reader has to resolve a hue with no label.

### 4.4 The breadcrumb, which is where the span is told

Row 2 on `/inference`:

```
 [Cpu]  Inference     Inference drivers → Engines and backends → Your hardware
```

each layer name in its own token colour, `→` muted. On a single-layer
screen it is one name, not a chain. This is the line that teaches, on
every screen, without crowding row 1 — and it is the only place
`--accent-engine` and `--accent-hardware` are seen outside the panel.

### 4.5 Current screen

`usePathname()` (§0.5: zero occurrences today) resolves the active entry
by longest-prefix match, so `/config?tab=…` and any future sub-route
still mark their parent. The active item gets `aria-current="page"`, a
2px bottom border in its layer colour, and `--panel-hover`. Row 2's icon
is the same colour, so the two rows agree.

### 4.6 Accessibility, since §0.5 measured none

`<nav aria-label="Main">` around row 1, `<h2>` group labels visible in
the bar, a skip link to `#main-content` as the first focusable element,
`aria-expanded`/`aria-controls` on the map toggle, focus returned on
close, and `Escape` to close. The map panel is a `<nav aria-label="The
system, by layer">`.

---

## 5. What it replaces

Each page loses its hand-written header links and keeps its own
controls:

| Screen       | Removed                                               | Kept as row-2 controls               |
| ------------ | ----------------------------------------------------- | ------------------------------------ |
| `/`          | 6 links + Sign out                                    | Diagnostic toggle, New               |
| `/library`   | Back, Discover, Config                                | Rescan, Deep rescan, Cancel          |
| `/discover`  | Back to library, Config                               | (its search controls stay in-body)   |
| `/inference` | Back, Launch a model, Add an external backend, Nodes  | — (both links survive **in-body**, where they carry the explanatory `title` an operator needs; §7) |
| `/metrics`   | Back                                                  | window select, Refresh               |
| `/nodes`     | Back                                                  | —                                    |
| `/config`    | Back, Inference                                       | the tab strip                        |

Body links (`/library` → Inference, `/nodes` → Inference,
`DownloadsPanel` → Config, `ProfileEditor` → Inference, `/metrics`'s
"not recording" → Config) are **not** touched. They are contextual
instructions inside a sentence, not navigation, and removing them would
delete an explanation.

---

## 6. Verification

**vitest, on the pure parts** (`src/lib/navigation.test.ts`):

1. Every screen's `layer` and every `spans` entry resolves to a real
   layer.
2. The registry matches the site, transcribed as a literal table in the
   test with a comment citing `website/src/pages/architecture.astro` —
   name, icon and accent role for all eight layers. This is the check
   that catches the two repos drifting.
3. Every registry `href` is a route that exists under `src/app`, and
   every route under `src/app` is either in the registry or in an
   explicit excluded set (`/login`, `/setup`, `/runtimes`). **A new
   screen that nobody added to the nav fails this**, which is the defect
   §0 is made of.
4. Longest-prefix active matching: `/` matches only `/`; `/config`
   matches `/config` and `/config/anything`; an unknown path matches
   nothing rather than falling back to `/`.
5. Group ordering is the stack order, asserted against a literal list.
6. Sabotage: each of the above is checked to fail when the registry is
   perturbed.

**Playwright** (`e2e/navigation.spec.ts`), against a real agent serving
a real export, in the modern theme:

7. From **each** of the seven screens, the nav shows seven links, and
   clicking each arrives at that screen (`aria-current="page"` lands on
   the right item). This is the §0.2 defect asserted away: reachability
   is now complete, from everywhere.
8. Sign out is present on all seven (§0.4).
9. The computed colour of each nav item's icon equals the expected token
   value for its accent role — `rgb(42, 85, 230)` for left,
   `rgb(207, 58, 133)` for right — read with `getComputedStyle`, not
   from a class name.
10. Each item's icon is the expected one, asserted on a `data-icon`
    attribute **we** emit from the registry rather than on lucide's own
    class names, so the test is about our contract and not a third
    party's internals.
11. `/inference`'s breadcrumb shows three layer names in three distinct
    computed colours, one of them `rgb(47, 158, 110)` and one
    `rgb(138, 138, 147)` — the only live assertion that the new tokens
    are wired.
12. The map panel opens, contains all eight layer names and all seven
    screen links, and `Escape` closes it with focus back on the toggle.

A note the project has earned: **check 7 is the one that could pass
while broken.** Asserting "a link with this text exists" would pass
against a nav rendered on the playground only, if the test never left
the playground. It is written as a loop over the seven screens with a
real navigation between each, and the loop's subject is named in the
assertion message.

---

## 7. What stays out

- **No new screens.** The control-root workflows past `/nodes` are still
  unbuilt and stay unbuilt here.
- **No product features.** No search, no command palette, no favourites,
  no recently-visited.
- **No layout rewrite.** Both page shells keep their `<main>` exactly
  (§0.6).
- **No contract change**, no codegen, no pin bump on any Python
  consumer. `SPECS_REF` in `ui` does not move.
- **`/inference`'s two explanatory links stay in the page body.** "Launch
  a model" and "Add an external backend" carry `title` text that says
  what the action does to the install; that is instruction, not
  navigation, and the nav's `Library`/`Config` links do not replace it.

---

## 8. Radius

`ui` only. New files: `src/lib/navigation.ts`,
`src/lib/navigation.test.ts`, `src/components/AppNav.tsx`,
`src/components/ScreenHeader.tsx`, `src/components/LayerMap.tsx`,
`e2e/navigation.spec.ts`. Edited: seven `page.tsx` headers,
`globals.css` (two tokens × three themes), `package.json`
(`lucide-react`).

Then `npm run build:python`, a rebuilt `dist` branch, and `PIN_UI` in
both `scripts/install.sh` and `scripts/install.ps1` — the one thing in
this slice that lands in `specs`. The default theme stays `modern` and
none of its four spellings is touched (the bootstrap script's two
fallbacks, `<html data-theme>`, `DEFAULT_THEME`, and which palette
`:root` carries); the new tokens are added *inside* the existing blocks,
so `:root` stays first in source order.

---

## 9. Traps known in advance

- **`:root` must stay first.** `:root` and `[data-theme="x"]` have equal
  specificity. Adding tokens is safe; reordering the blocks is not.
- **The four spellings of the default theme.** Not touched here, listed
  so the next reader does not have to rediscover them.
- **`trailingSlash: true`.** The export writes `/library/index.html`, so
  a Playwright `toHaveURL(/\/library/)` is satisfied by
  `/library/` — fine — but `toHaveURL(/\/$/)` is satisfied by *every*
  page. M9 lost three assertions to exactly this. Assert on a heading
  and `aria-current`, not on a trailing slash.
- **`locator("svg").first()`** will match the decorative background
  `eugene-icon.svg` in `layout.tsx`, not a nav icon. Name the subject.
- **The agent venv here has `eugene-plexus-ui` installed editable**, so
  the throwaway agent serves whatever `npm run build:python` last
  staged. Rebuild before the acceptance run.
- **Any script that starts an agent clears every `EUGENE_PLEXUS_*`
  variable and binds off 8079**, or it repoints the live install.

---

## 10. Implementation record

**Built and verified 2026-09-13 (late), one unattended session.** `ui`
`5cd6299` (dist `adc1926`); `specs` carries the design, the runner and
the `PIN_UI` bump in both installers. **No contract change, no codegen,
no consumer re-pinned** — `SPECS_REF` in `ui` did not move.

### 10.1 What landed

| File                              | Lines | What it is                                              |
| --------------------------------- | ----: | ------------------------------------------------------- |
| `src/lib/navigation.ts`           |   362 | The registry. Pure; no React, no DOM, no `next/*`        |
| `src/lib/navigation.test.ts`      |   253 | 31 cases, five sabotage-checked                          |
| `src/components/AppNav.tsx`       |   190 | Row 1, and `AppHeader` which composes both rows          |
| `src/components/ScreenHeader.tsx` |    81 | Row 2 and the layer breadcrumb                           |
| `src/components/LayerMap.tsx`     |   166 | The panel                                                |
| `src/components/LayerIcon.tsx`    |    76 | Icon name → lucide component, plus the `data-icon` attribute |
| `e2e/navigation.spec.ts`          |   195 | 8 browser tests                                          |

Seven `page.tsx` headers went from **275 hand-written lines to 181**, and
what is left is each screen's own controls: the diagnostic toggle and
New, the scan buttons, the context selector, the window selector and
Refresh, the two Inference actions, Config's tab strip. Not one link
between screens remains in a page file. Two new tokens × three themes in
`globals.css`, plus `.skip-link`. `lucide-react` pinned **exactly** at
`1.45.0`, the version the website pins for `@lucide/astro`, so the two
repos draw from one icon set.

### 10.2 Verification

`scripts/navigation-acceptance.sh` — **14 checks, ALL PASSED on the
first execution**, four processes on +100 ports with the environment
cleared and teardown by pid. It stages the export from the working tree
first, because the agent venv on this box has `eugene-plexus-ui`
installed editable and would otherwise serve the previous build; a
check then greps the staged bundle for `data-icon` so "the run asserted
about the wrong build" is a failure rather than a silent pass.

**Six sabotages, each confirmed to fail the check that should catch it:**

| Sabotage                                                    | Caught by                                    |
| ----------------------------------------------------------- | -------------------------------------------- |
| Links rendered only when `pathname === "/"` (the old state)  | reachability, and "each link navigates"      |
| Gateway's accent changed from `right` to `left`              | the colour check, and the vitest table       |
| `/inference` stops declaring its span                        | the three-colour breadcrumb                  |
| `Escape` no longer closes the map                            | the map test                                 |
| The skip link removed                                        | the Tab test                                 |
| Segment boundary removed from `activeScreen`                 | the prefix case — **after it was fixed**     |

**A test that could not fail, found by sabotage.** The prefix case was
written as `/librarian` against `/library` — which is *not* a string
prefix, since "librarian" diverges at the `i` — so it passed against an
implementation with the boundary check removed. It asserts on
`/configuration` and `/nodes-b` now, and asserts that
`"/configuration".startsWith("/config")` first, so the example cannot
quietly stop being one. This is the same family as M10's check 7 and
step 6's fragmentation checks: **an assertion whose subject cannot
produce the failure is green for the wrong reason.**

Also: 153 vitest cases pass (was 122), `tsc --noEmit` clean,
`eslint --max-warnings=0` clean, `next build` exports all twelve routes.

`scripts/install-acceptance.sh` re-run after the pin bump: **checks 1-16
pass in WSL2**, installing from nothing and serving the UI at `/` from
the new `dist` pin. **Check 19 fails on purpose** — the live install's
own agent holds 8079 on this box, and the Windows half refuses to run
rather than measure someone else's process. The pinned archive was then
fetched directly and confirmed to carry `data-icon` and a `BUILD_INFO`
naming `ui@5cd6299`.

### 10.3 What §0 predicted and the build confirmed

Screenshots in all three themes: modern renders the website's exact
palette; cyberpunk separates teal drivers from green engines from
violet-grey hardware; **editorial's olive-gold engine role reads as a
different thing from its deep-green `--accent-left`**, which a literal
`#2f9e6e` would not have. At 430px the bar wraps to three rows with both
group labels intact and nothing clipped.

---

## 11. Where the build departed from this design

1. **A fourth component file.** §8 listed `AppNav`, `ScreenHeader` and
   `LayerMap`. `LayerIcon.tsx` is a fourth, because all three need the
   icon-name → component mapping and putting it in one of them would
   make the other two import a sibling for a lookup table. `AppHeader`
   is a second export of `AppNav.tsx` rather than a fifth file.

2. **`/inference`'s two actions are row-2 controls, not body elements.**
   §7 said they stay "in the page body". They are in row 2's controls
   slot instead, which is what row 2 is *for* — the screen's own
   actions, as against the navigation's links. Moving them into the body
   would have restructured a screen this slice promised not to touch.
   They keep their explanatory `title` either way, which was the point.

3. **Five sabotages on the vitest suite, not fifteen.** §6.6 said "each
   of the above is checked to fail when the registry is perturbed".
   Five representative ones were, plus six on the browser suite. Eleven
   of them share one mechanism — a perturbed registry — so checking
   every case would have re-measured the same thing.

4. **Three existing test files gained a `usePathname` mock.**
   `config`, `metrics` and `nodes` mock `next/navigation` without it,
   and the shared nav reads it on mount, so all seventeen of their cases
   threw until it was added. Unforeseen and trivial, recorded because it
   is what a shared header costs in a suite that mocks the router
   per page.

5. **`__pycache__/` added to `ui/.gitignore`.** The acceptance run has
   the agent import `eugene_plexus_ui` as an editable install, which
   leaves bytecode in the checkout. One line, and it stops a future
   `git add -A` committing build droppings.

6. **`lucide-react` is pinned exactly**, not with a caret like the
   repo's other dependencies, so the UI and the website cannot drift to
   different icon sets.
