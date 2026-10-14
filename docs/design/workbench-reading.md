# Workbench reading: as built (2026-10-11)

Troy, 2026-10-10: Workbench read "dry": almost all text one light gray, a
medium gray the only contrast, where Eugene's console has "small splashes of
color that highlight important headers, boundaries". He asked for a deep dive
(font, spacing, line-height, margins, padding, color) so that reading and
using Workbench is a pleasure, and then delegated every UX call: "use your
best judgment ... get us 90% there and we might tweak a little later on."

The design below is the spec the build followed: nine audits (typography,
colour, spacing, Markdown, the chat's surroundings, the other screens, the
console's visual language, outside practice, accessibility), one synthesis,
and a critique of it. This header records what was built and where the build
departed from the spec. Acceptance: `docs/acceptance/workbench-reading-run.md`.

## What was built

- **R1, the reading core:** the variable IBM Plex Sans (a real italic and
  every weight), tokens with four text tiers, a 17 px reading size on a
  measure of about 74 characters, real heading sizes in a warm tone with a
  hairline and an apricot segment under h1 and h2, the code block as one box
  with its language, tables with a header fill and an apricot rule, a quote
  bar, hairline rules, styled scrollbars, selection and focus; the font and
  token gates (`fonts.test.ts`, `tokens.test.ts`, `stylesheet.test.ts`).
- **R5, Markdown:** syntax colour with `lowlight` as React elements (never
  inner HTML), remembered per block and never applied to a fence still being
  written; capped at 8,000 characters or 400 lines a block, because
  highlight.js is quadratic on some inputs; the `br`, `sub`, `sup` and `kbd`
  allowlist; GitHub alerts; single newlines as line breaks (`remark-breaks`).
- **R2, the chat's surroundings:** a neutral top bar with icons and a 2 px
  underline on the current page; the open chat marked with a blue rail; the
  person's message as a quiet steel-blue bubble; message actions shown on
  hover, focus, touch and the newest message; reasoning as a quiet row with
  its text in a dashed scrolling box; the working line under a streaming
  answer with its token count or time; a cut-off answer in an amber box that
  names its cause; a floating "Jump to latest"; skip link, view focus and tab
  titles.
- **R3, the other screens:** shared `.btn`, `.control`, `.field`,
  `.notice`, `.badge` and heading patterns across settings, Tools, Media,
  Job sites, sign-in and the shortcuts overlay.
- **R4, robustness:** forced colours, `prefers-contrast: more` (every text
  tier at least 7:1 there), coarse pointers (44 px targets), short windows,
  focusable scrollers (code blocks and reasoning), long strings that wrap at
  390 px.

## Calls made while building (for Troy's tweaks)

1. **More colour than the spec's default.** The critique measured a short
   technical answer still 92% one colour in dark. Inline code is now warm
   (apricot text on the soft fill, 7:1 in both schemes), first-level bullets
   are apricot, and ordered-list numerals are bold in the heading colour.
2. **Light mode's answer text is a notch softer than ink** (`#202023`,
   15.6:1), so bold and headings (`#0d0d10` and plum) stand above it. Dark
   keeps `#e6e8ea` with bold at `#f4f6f7`.
3. **The measure is in em of the element's own size** (`33.88em`, 576 px
   at 17 px), so 14 px text (reasoning, notes, tool cards) gets the same
   characters a line instead of 92.
4. **Reasoning stays plain text** (re-parsing up to ~60 KB of Markdown on
   every streamed piece is too slow; a Strata answer reasoned for 16k tokens).
5. **Code blocks are focusable, named scrollers** (axe: a code line wider
   than a phone could not be reached by keyboard).
6. **The production-mode sentence is visible**, as developer mode's is; the
   search privacy line is visible text while search is on.
7. **Six old Chrome checks were repaired**: they looked for "Copy" and
   "Save" while the buttons are named "Copy this answer" and "Save
   settings" (they failed on main before this slice too). "Copied" is now
   the copy button's accessible name while it says so.

## Not done, named

- Math (KaTeX: about 140 KB and a CSP workaround), footnotes, per-turn
  speaker marks, display settings (text size, reading width, theme), dark
  weight tuning: section 12 below.
- On a phone with search on, the chrome takes 41.5% of the screen (budget
  40%); owner-only rows and two links are 20 to 28 px tall on touch.
- NVDA and VoiceOver runs for the announcer, the skip link and the
  disclosure rows.
- Two older sabotage scripts carry stale anchors
  (`check-media-sabotage.py`: "the owner's view has actions";
  `check-attachments-sabotage.py`: three Edit-box anchors that already
  matched twice on main).

---

# The spec the build followed

Base: Workbench `main` 530740f, 2026-10-10. Inputs: nine audits (typography, colour, spacing, Markdown, chat surroundings, other screens, the console, outside practice, accessibility), the screenshots in `scratchpad/reading/before/`, and the code. Audit IDs (T01, COL-03, SP-07, MD-04, SUR-06, F2, B1, S2, P1, C3, BP05, A11Y-04) are cited so each call can be traced; the last appendix says what became of every one.

Everything below was written against the real files. The CSS fenced as `/* styles.css §N */` is the whole stylesheet in order (§3a, 3b, 4, 6, 8, 9); it was compiled with Tailwind 4.3.3 and run in Chrome before this draft was handed over (section 13 records the numbers).

## Decisions at a glance

1. **The page is dry for two reasons, one mechanical and one structural.** Mechanically: it asks for faces it never loads (500 draws as 400, bold as 600, italic is a slant), runs 109 characters a line, and puts one 9.6 px gap between everything. Structurally: three text colours carry 100% of the text (72% / 23% / 5%), headings are body-sized, and nothing marks a boundary except a box.
2. **Two registers.** Chrome sets in 12 to 14 px; an answer reads at 17 px / 1.65 on a 36 rem measure (74 characters on average in prose, never more than 80). The price is height: a technical answer is 25% taller and prose 54% taller at desktop width (section 5.4); taste call 3 offers a roomier measure.
3. **Colour marks structure, not paragraphs.** Blue means you, a control, or what is current. Apricot (magenta in light) is the answer's own labels and boundaries: h1 to h3 and bold lead-ins as text, plus a 2.5 rem segment under h1 and h2, the quote bar and the table-head rule. Status colours appear only inside a status that also has a glyph and words.
4. **Four text values, not two:** strong `#f4f6f7` 16.7:1, body `#e6e8ea` 14.8:1 (unchanged), muted `#b3b9bf` 9.2:1 (unchanged), faint `#959aa0` 6.4:1 for placeholders and disabled only.
5. **One font change fixes every weight:** the variable IBM Plex Sans (normal and italic, 95.9 KB Latin, 26 KB less than five static faces), `font-synthesis: none`, and a vitest gate so a page can never again ask for a face it does not load.
6. **Nothing is left to the browser:** selection, scrollbars, caret, checkbox accent, placeholder, cursor, disabled look, focus ring, forced colors and `prefers-contrast` all come from tokens.
7. **One recipe each** for buttons, fields, notices, badges, page frame, headings and cards, so the next screen has something to copy (section 8).
8. **Order of work** (each slice ships on its own, with its acceptance and unit tests):
   - **R1 reading core:** fonts, tokens (including the one-line `bg-surface` alias that gives 20 media fields their missing fill), type scale, `.answer` CSS, `Markdown.tsx` (code block, table wrapper, lead-in, task box, quiet draft), `index.html` meta tags, font gate, token gate.
   - **R2 the chat's surroundings:** sidebar, top bar, header, thread, message chrome, reasoning, tool calls, working line, composer, jump pill.
   - **R3 the other screens:** `.btn`, `.control`, `.field`, `.notice`, `.badge`, `.page`, headings, per-screen conversions.
   - **R4 robustness:** forced colors, `prefers-contrast`, coarse pointers, short windows, focusable scrollers, live-region split, skip link, view focus and titles, an explicit text direction on each block.
   - **R5 optional:** syntax highlighting, `<br>` and `sub`/`sup`/`kbd` allowlist, `remark-breaks`, GitHub alerts.
   The shared CSS (§3 to §9) lands whole in R1; later slices only adopt it.

**What Troy will see in the rich chat.** The answer is a little larger and a quarter narrower, so a line is a sentence and not a wall. "How the cache is sized" is a pale-peach heading, bigger than the text, on a hairline with a short apricot segment at its left end; "### What to set in Eugene" is the same colour, smaller, with no rule. "**Note:**" and "**Why:**" are peach; other bold is a little brighter than the text. The Copy bar is part of the code block and says `bash` or `text`; the table keeps whole words, has a tinted header with an apricot rule under it, and numbers stay right-aligned. The quote has an apricot bar. Bullets are quiet gray, numerals are bold. Under the answer, Copy and Try again appear when the mouse is over it; a cut-off answer sits in an amber box with a scissors glyph and its cause in plain words. The sidebar's open chat has a blue rail. The top bar is gray words with small icons and a blue underline under the page you are on, and the only blue text left is a link. Each of these is written to hold in Windows High Contrast, with a mouse that draws scrollbars, at 200% zoom and on a phone (section 9).

---

## 1. Diagnosis

Troy: "Almost all text is the same shade of light gray, with a medium gray being the only contrast." The numbers say he is right, and say why.

| What he sees | What the page does | Measured (source) | Cause (file:line) |
|---|---|---|---|
| One shade | 3 text colours on the whole rich chat: `#e6e8ea` 94 of 131 runs (72%), `#b3b9bf` 30 (23%), `#7fb0cf` 6 (5%) | styles-dark.json census | `styles.css:7-29`: no strong, faint or heading tier; `--accent-right` declared, used by 0 components |
| Headings read as body | h2 and h3 are 600 16 px / 25.6 px, the body size, in the body colour; h4 to h6 are plain 400 text | kinds `answer h2`, `answer h3` | preflight resets h1 to h6; `styles.css:164-169` sets weight and margin only |
| Nothing groups | One gap, 9.6 px, between p, ul, ol, pre, table and quote; a heading has 12.8 px above and 9.6 px below (1.33 to 1 and 3.2 px more than a paragraph break); list items touch; a nested list floats 9.6 px off its parent | DOM gaps, rich chat | `styles.css:122-129` |
| Bold does not pop | strong is the body colour at a weight the page does not own: computed 700, drawn 600 (SemiBold file) | CDP platform fonts | `main.tsx:1-3` loads Sans 400 and 600 only |
| 24 labels look like their help text | `font-medium` (24 uses) draws at 400; "Model" is 38 px wide in both | pixel width, settings and media screens | same |
| Italic is a slant | `em` is the roman skewed; there is no italic file | CDP: IBMPlexSans-Regular for `em` | same |
| Lines are walls | 109 characters a line in the 768 px column (104 counted on real line breaks); the reasoning box 117; the length note 121 | harness `charsPerLine`; Chrome counts | `ChatView.tsx:310` `max-w-3xl`, no cap on `.answer` |
| A bright full-width line | `hr` is drawn in the text colour: 1 px `#e6e8ea`, 14.76:1, margin 0 | kind `answer rule` | preflight `hr`, no `.answer hr` rule |
| Code is two boxes and the smallest text | the Copy bar floats 8.4 px above its code (a rule loses to a later one); code is 12.88 px, smaller than the 14.72 px inline code; 80 px of dead right padding | kind `answer code block`, DOM | `styles.css:96-98` vs `:122-129`; `.answer code` 0.92em hits `pre code`; `Markdown.tsx:35` `pr-20` |
| Tables shred words | 'Quanti-zation', 'Q4_K_-M', '16.2-GiB'; headers centred over left cells | `__tableWords` probe | `overflow-wrap: anywhere` at `styles.css:120`; UA `th` centre |
| Colour sits in the chrome | the only hues on a chat page at rest are three blue top-bar links, "Jump to latest" and the Send fill | census | colour is on navigation, none on reading |
| States are prose | a cut-off answer, a failed tool call, a call waiting for approval and a finished one are the same 14 px muted sentence | cut-dark-desk.png; `ToolCalls.tsx:196` | one `text-muted` for all eight statuses |
| Controls are hard to find | field and button edges 1.60:1 dark, 1.28:1 light (3:1 required); placeholder 4.18:1 dark, 3.55:1 light; idle Send 3.01:1 dark, 2.26:1 light; the light user bubble is 1.06:1 against the page | computed | `--border` used for cards and controls alike; unlayered `button:disabled{opacity:.5}` |
| The browser decides the rest | default scrollbar with arrows, selection, caret, checkbox blue, no pointer cursor on 117 buttons | Troy's Brave screenshots; grep | no rule |

**What is not wrong and must not be broken.** Body text 14.76:1, muted 9.16:1, link 7.78:1 (all pass AA with margin); the 2 px focus ring (5.35 to 7.78:1) on all 43 recorded stops; reduced motion honoured; zoom not disabled; `lang="en"`; no clipping under WCAG 1.4.12 text spacing; axe-core 4.13 finds nothing on Tools, Media, Job sites, sign-in and the failed and versions chats; its findings elsewhere (unlabelled task-list checkboxes, unnamed scrollers, no h1 on the empty state) are fixed below.

**What the console does that Workbench does not** (C1, C2). The console's text is also two grays; what Troy sees as "splashes on headers and boundaries" is colour on marks: role-coloured 14 px icons, a 2 px rail on the current tree row and a 2 px underline on the current tab, 4 px role bars on the layer cards, a 1 px hairline under every panel title (30 uses), and status tints (~290 lines). The console's own Playground answer is as flat as Workbench's, with a 146-character measure, so it is a source of marks and tokens, not of Markdown.

---

## 2. Principles

1. **Value, weight, size, then hue.** Every kind of text gets its own look, and the order of means is that one. The ladder (dark): strong `#f4f6f7` 16.7:1 > body `#e6e8ea` 14.8 > muted `#b3b9bf` 9.2 > faint `#959aa0` 6.4. Hue is spent on labels and boundaries only.
2. **One colour, one meaning.** Blue (`#7fb0cf` dark, `#2a55e6` light) = you, a control, what is current, a link. Apricot (`#cf9a72`; `#cf3a85` in light, so marks only there) = the answer's labels and boundaries. Green, amber, brick, steel = a status, always with a glyph and words, never decoration. Budget: at most one warm text colour in an answer; a warm mark never marks something you can click; no more than three coloured things in any 400 px of screen.
3. **Two registers.** Chrome: 12 / 13 / 14 px (eyebrow, meta, UI). Reading: 17 px / 1.65 for answers, the person's words and the composer. Titles 20 and 24. Nothing meant to be read is under 13 px; 12 px is for uppercase labels and badges.
4. **Measure is a count of characters.** 75 on average, 80 at most (WCAG 1.4.8). In Plex Sans at 17 px that is 36 rem. Never `ch` (1ch is 0.600 em, an average prose character 0.4425 em, so `70ch` holds about 93).
5. **One gap scale on a 4 px grid, one owner per gap.** hug 4, tight 8, group 12, flow 16, section 24, turn 32. Space above a heading is at least 3 times the space below it. A block owns the space above it; the first and last child own nothing.
6. **Boundaries are quiet; controls are findable.** Hairlines 1.4 to 1.7:1 for structure (`--border`, `--rule`); what identifies a field or a button is 3:1 or better (`--border-control`); a state is a shape plus words plus hue, never hue or fill alone (forced colors drops fills).
7. **Never ask for a face the page does not load, never leave a default where the palette stops.** A test fails if a weight or italic is used and not loaded; selection, scrollbars, caret, checkbox accent, placeholder, cursor, disabled look and focus ring are all tokens.
8. **Text survives its surroundings.** It wraps (`overflow-wrap: break-word` on the body), scrolls (code and tables are focusable scrollers), mirrors (an explicit `dir` per block, logical properties), scales (rem, 200% zoom keeps a third of the window), and keeps its edges in Windows High Contrast.

### 2.1 Conflicts between the audits, and what was chosen

| # | One side | Other side | Chosen, and why |
|---|---|---|---|
| 1 | Tint h1 to h3 and bold lead-ins warm (T14, COL-11 dark, MD-02, BP07) | Neutral headings, colour on marks only (C1: the console has no precedent for coloured headings; COL-11 light) | **Warm tint on h1 to h3 and lead-ins, plus marks.** Troy asked for splashes on headers, and the complaint is about text colour. It departs from the console's note ("Apricot ... and nothing else", globals.css:44), so it is taste call 1, and one token (`--heading: var(--foreground-strong)`) reverts it. Blue headings were refused (BP07 t3, MD-01 option): blue is the action colour and a blue heading reads as a link. |
| 2 | Heading `#d7b196` (T14) | Cream `#eacab0` (COL-11); raw apricot (MD) | **`#e3c2a8`.** Computed OKLab distances: `#d7b196` is 0.036 from the amber warning text (a heading and a warning would be near-twins), `#eacab0` only 0.089 from the body (barely warm). `#e3c2a8`: 0.064 from warn, 0.099 from error, 0.109 from body; 10.83:1 on the page, 8.98 on soft. |
| 3 | Soften the answer body to 90% (`#ced0d2`, 11.72:1: T13, MD-00; `#dde0e3`: BP06) | Hold it (COL-01, APCA: body already at Lc 91.8, preferred tier) | **Hold `#e6e8ea`; add a brighter strong tier.** At 17 px / 400 on dark, dimming costs margin; weight and hue give the hierarchy. Softer body is taste call 4. |
| 4 | Measure 34.5 to 36 rem (T 36, SP 35), 38 rem (MD-22), 40 em (BP08) | | **36 rem**, in rem so zoom and text size move it. Measured at 17 px in Chrome: 70 to 77 characters on average, 80 at most (at 16 px it measures 76 to 80 and 85 at most; at 18 px 65 to 72); the cost in height is in section 5.4. |
| 5 | Narrow the whole frame to 40 rem (SP-04) | Keep 48 rem and cap only text (T03) | **Keep 48 rem** (no composer re-flow), cap text and its furniture at the measure. 40 rem is taste call 3. |
| 6 | Warm list markers and numerals (MD-13, COL-02) | Muted markers (T15, SP-02, BP11) | **Muted bullets, bold numerals.** Colour budget; warm markers are the "lively" option. |
| 7 | Quote text muted (T15, C4, COL-02) | Body colour (MD-12, BP12) | **Body colour, warm 3 px bar.** The caveat in a `> **Note:**` is the most important line, not the least. |
| 8 | `display:block` on `table` (T04, SP-06) | Wrapper `div.table-wrap` (MD-06, A11Y-10) | **Wrapper.** Keeps the table's semantics in Safari and VoiceOver, and gives a named, focusable scroller. |
| 9 | `th:not([align])`, reading GFM alignment as an `align` attribute (T04) | `th{text-align:left}`, because "alignment arrives as an inline style" (SP-06, MD-07) | **`th{text-align:start}`; SP-06 and MD-07 had the mechanism right.** `mdast-util-to-hast` 13.2.1 does write `properties.align`, but `hast-util-to-jsx-runtime` 2.3.6, which react-markdown 10.1.0 calls with its default `tableCellAlignToStyle`, turns that into `style="text-align: right"`; rendering `\| :-- \| ---: \| :-: \|` through the installed packages gives three inline styles and no `align` attribute. An inline style beats any stylesheet rule, so one plain rule sets an unaligned header (the browser's own is centred) and a `---:` column stays right-aligned. `:not([align])` would have matched every header and only looked as if it were doing something. `start`, not `left`, so it follows the block's direction. |
| 10 | Grid on every cell (today) | Rules only, header fill (MD-07, BP10, C9) | **Horizontal rules, header fill, warm 2 px rule under the header, 1 px border and radius on the wrapper.** |
| 11 | Language label mapped to display names (MD-04) | Raw token (T09, BP05) | **Raw token in mono, fallback "code".** No map to maintain. |
| 12 | Five static Sans faces (T01) | Variable pair (T01 alternative, BP03); two italics only (MD-03); 500 plus 400i (SUR-02) | **Variable pair.** 95.9 KB of Sans against 122 KB for five static faces, any weight 100 to 700, real italics, 22 files in the wheel against 70. |
| 13 | Dark-mode weights 370 / 460 / 550 (BP13, Claude's own CSS) | Keep 400 (T13) | **Keep 400/500/600.** The variable font makes the other available for free (taste call 6); not tested on Troy's Brave. |
| 14 | Keep 16 px (MD-22 raises to 17 only as an option) | 17 px (T05) | **17 px.** +6% x-height, still clearly apart from 14 px chrome. 16 and 18 are alternates. |
| 15 | Keep `#7fb0cf` for text links | `--link` `#9cc5df` in dark (COL-08, BP20) | **`--link`.** Lc 67.4 against 55.3, and it is the console's own `--action-primary-hover`. Light unchanged. |
| 16 | Control edge names and values: `--border-strong` `#6a747e` (COL-03), `--field-edge` `#6b7580` (F0), `--border-control` `#737c86` (A11Y-03), console `#758695` (C12) | | **`--border-control`** `#737c86` dark, `#80808a` light: 3.14:1 or better against every surface including a hovered button's fill. |
| 17 | Disabled = opacity (F4, B1) | Token recipe (COL-05, SUR-16) | **Token recipe** (`--faint` on soft or on the page: 4.77 to 6.39:1) for converted controls; legacy buttons keep `opacity:.5` in the base layer until converted. |
| 18 | Placeholder `--muted` (F5) | `--faint` (COL-06); foreground at 62% (SUR-16) | **`--faint`** (5.30:1 on soft dark, 4.77 light): readable, still clearly not typed text. |
| 19 | Tinted user bubble (COL-09, SUR-13) | Neutral, no border (T10, BP22) | **Tint plus a 1 px edge.** The light bubble is 1.06:1 against the page: invisible. |
| 20 | Actions always visible at 28 px (SP-11) | Reveal on hover, focus and for the newest message (SUR-06, BP15) | **Reveal**, newest and touch always visible, 28 px (44 coarse) targets. |
| 21 | Reasoning: dashed box (C8) | Left rail in apricot (SUR-07); bordered when open (SP-21) | **Borderless summary row; text in the console's dashed box; no warm.** Parity with the console's Thinking box; warm stays on the answer. |
| 22 | Top-bar links stay blue (C17 B, COL-14) | Neutral with icons, current marked (SUR-11, C17 A) | **Neutral with icons and a 2 px underline on the current page.** Blue stops being the only colour on the page. |
| 23 | Scrollbar standard properties everywhere (COL-07, BP17) | Gate them (C11) | **Gate** with `@supports not selector(::-webkit-scrollbar)`: measured, Chrome then shows a clean 10 px thumb with no arrows. |
| 24 | Keep the unlayered global focus rule | Focus on the field's border (SUR-25, COL-03) | **Move the ring into `@layer base`** so components can tune it; fields take `outline-offset:0` and a blue edge. |
| 25 | Retag answer headings under the message (A11Y-08) | Style headings by tag (T02) | **No retag in this release**; CSS stays by tag. Later: the contract is to key styles on `data-md`. |
| 26 | `text-wrap: pretty` guarded by `data-testid` (T18) | | **Guard on `[data-status="running"]`**, the article's own attribute. |
| 27 | Warm markers on `hr` (MD-15) | Hairline only (BP04) | **Hairline only**; the segment belongs to headings. |
| 28 | `kbd`, `mark`, `sub`, `sup` all allowed (MD-08) | | **br, sub, sup, kbd** (R5); `mark` dropped. |
| 29 | Name `--text-strong` (T13, COL-01) | | **`--foreground-strong`**: `--text-*` is Tailwind's font-size namespace. |
| 30 | KaTeX now (MD-10) | | **Defer**; cost and CSP workaround in section 10. |

---

## 3. Tokens

All values are hex or rgb(). Existing names keep working; **no token is renamed**. One repoint: the Tailwind alias `line-strong` (0 uses) now means the control edge. One name differs from the audits: `--foreground-strong`.

```css
/* styles.css §3a: tokens */
@import "tailwindcss";

/* Plexus, copied from the console (ui/src/app/globals.css), not shared:
   components share schemas, never code. Dark is Plexus; light is the
   console's "modern" palette. Blue is you, a control, what is current.
   Apricot (magenta in light) is the answer's own labels and boundaries.
   Status colours appear only inside a status. */
:root {
  color-scheme: dark;

  /* ground */
  --background: #141619;
  --foreground: #e6e8ea;
  --panel: #1b1e22;
  --panel-soft: #23272c;
  --panel-hover: #2b3037;

  /* text, brightest first (foreground is the body) */
  --foreground-strong: #f4f6f7;
  --muted: #b3b9bf;
  --faint: #959aa0;

  /* the answer's labels and boundaries */
  --heading: #e3c2a8;
  --accent-right: #cf9a72;
  --accent-right-text: #cf9a72;

  /* you, controls, what is current */
  --accent-left: #7fb0cf;
  --accent-hover: #9cc5df;
  --accent-active: #6e9cbb;
  --on-accent-left: #0c1216;
  --link: #9cc5df;
  --link-hover: #b4d6ec;
  --tint: #2b353d;
  --tint-edge: #506473;

  /* edges */
  --border: #3a4048;
  --border-hover: #5c646e;
  --border-control: #737c86;
  --rule: #3a4048;

  /* status: a glyph, words and a tint, never colour alone */
  --status-warn-fg: #dcb079;
  --status-warn-bg: rgb(131 96 41 / 0.18);
  --status-warn-border: #836029;
  --status-error-fg: #dd9a93;
  --status-error-bg: rgb(143 70 61 / 0.2);
  --status-error-border: #8f463d;
  --status-ok-fg: #93c6a6;
  --status-ok-bg: rgb(58 117 81 / 0.18);
  --status-ok-border: #3a7551;
  --status-info-fg: #9cc5df;
  --status-info-bg: rgb(127 176 207 / 0.12);
  --status-info-border: #476c84;
  --danger-edge: #aa766f;

  /* what the browser would otherwise decide */
  --selection: rgb(127 176 207 / 0.34);
  --scrollbar-thumb: #68717b;
  --scrollbar-thumb-hover: #8793a0;

  /* code colours come from the tokens above, so light follows */
  --hl-keyword: var(--link);
  --hl-string: var(--status-ok-fg);
  --hl-number: var(--status-warn-fg);
  --hl-title: var(--heading);
  --hl-attr: var(--status-error-fg);
  --hl-comment: var(--faint);
  --hl-punct: var(--muted);

  --radius: 4px;
  --measure: 36rem;
  --font-ui: "IBM Plex Sans Variable", "IBM Plex Sans", system-ui, -apple-system, sans-serif;
  --font-code: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
}

@media (prefers-color-scheme: light) {
  :root {
    color-scheme: light;
    --background: #fafafb;
    --foreground: #0d0d10;
    --panel: #ffffff;
    --panel-soft: #f3f3f5;
    --panel-hover: #e7e7eb;

    --foreground-strong: #0d0d10;
    --muted: #5a5a63;
    --faint: #6b6b73;

    --heading: #8f2f5e;
    --accent-right: #cf3a85;
    --accent-right-text: #b82773;

    --accent-left: #2a55e6;
    --accent-hover: #1f42c4;
    --accent-active: #1a37a8;
    --on-accent-left: #ffffff;
    --link: #2a55e6;
    --link-hover: #1f42c4;
    --tint: #e8edfc;
    --tint-edge: #a7b2dc;

    --border: #e3e3e8;
    --border-hover: #8a8a93;
    --border-control: #80808a;
    --rule: #c4c4cc;

    --status-warn-fg: #7c3f08;
    --status-warn-bg: rgb(243 194 90 / 0.18);
    --status-warn-border: #f3c25a;
    --status-error-fg: #971838;
    --status-error-bg: rgb(242 154 169 / 0.18);
    --status-error-border: #f29aa9;
    --status-ok-fg: #07664d;
    --status-ok-bg: rgb(122 220 176 / 0.18);
    --status-ok-border: #7adcb0;
    --status-info-fg: #1f42c4;
    --status-info-bg: rgb(42 85 230 / 0.07);
    --status-info-border: #9aaaf0;
    --danger-edge: #c24a68;

    --selection: rgb(42 85 230 / 0.22);
    --scrollbar-thumb: #8a8a93;
    --scrollbar-thumb-hover: #5a5a63;
  }
}
```

```css
/* styles.css §3b: Tailwind names */
@theme inline {
  --color-bg: var(--background);
  --color-fg: var(--foreground);
  --color-strong: var(--foreground-strong);
  --color-muted: var(--muted);
  --color-faint: var(--faint);
  --color-heading: var(--heading);
  --color-panel: var(--panel);
  --color-soft: var(--panel-soft);
  --color-surface: var(--panel-soft);
  --color-hover: var(--panel-hover);
  --color-line: var(--border);
  --color-line-strong: var(--border-control);
  --color-accent: var(--accent-left);
  --color-accent-hover: var(--accent-hover);
  --color-accent-active: var(--accent-active);
  --color-on-accent: var(--on-accent-left);
  --color-link: var(--link);
  --color-link-hover: var(--link-hover);
  --color-tint: var(--tint);
  --color-tint-line: var(--tint-edge);
  --color-apricot: var(--accent-right);
  --color-warn: var(--status-warn-fg);
  --color-warn-bg: var(--status-warn-bg);
  --color-warn-line: var(--status-warn-border);
  --color-error: var(--status-error-fg);
  --color-error-bg: var(--status-error-bg);
  --color-error-line: var(--status-error-border);
  --color-ok: var(--status-ok-fg);
  --color-ok-bg: var(--status-ok-bg);
  --color-ok-line: var(--status-ok-border);
  --color-info: var(--status-info-fg);
  --color-info-bg: var(--status-info-bg);
  --color-info-line: var(--status-info-border);
  --container-measure: var(--measure);
  --font-sans: var(--font-ui);
  --font-mono: var(--font-code);
  --radius-plexus: var(--radius);
}

/* The type scale by role (section 4). Tailwind's own text-xs and text-xl are
   retuned rather than renamed, so the 188 existing size classes keep their
   meaning. */
@theme {
  --text-xs: 0.8125rem;
  --text-xs--line-height: calc(18 / 13);
  --text-read: 1.0625rem;
  --text-read--line-height: 1.65;
  --text-xl: 1.25rem;
  --text-xl--line-height: 1.3;
}
```

### 3.1 What each token is for

| Token | Dark | Light | Used for |
|---|---|---|---|
| `--foreground` | `#e6e8ea` | `#0d0d10` | body and UI text (unchanged) |
| `--foreground-strong` | `#f4f6f7` | `#0d0d10` | bold, h4, table heads, titles; in light it equals the body, weight carries it |
| `--muted` | `#b3b9bf` | `#5a5a63` | meta, hints, secondary text (unchanged) |
| `--faint` | `#959aa0` | `#6b6b73` | placeholder, disabled, code comments; never the only carrier of information |
| `--heading` | `#e3c2a8` | `#8f2f5e` | h1 to h3 and bold lead-ins as text |
| `--accent-right` | `#cf9a72` | `#cf3a85` | segment under h1/h2, quote bar, table-head rule: marks only (light 4.38:1) |
| `--accent-right-text` | `#cf9a72` | `#b82773` | warm text where a mark's colour is not enough (5.63:1 in light); today only the IMPORTANT alert in R5 uses it |
| `--accent-left` | `#7fb0cf` | `#2a55e6` | fills, current-page rail and underline, focus ring, checked box |
| `--accent-hover` / `--accent-active` | `#9cc5df` / `#6e9cbb` | `#1f42c4` / `#1a37a8` | primary button states (hover, pressed) |
| `--link` / `--link-hover` | `#9cc5df` / `#b4d6ec` | `#2a55e6` / `#1f42c4` | text links and quiet buttons |
| `--tint` / `--tint-edge` | `#2b353d` / `#506473` | `#e8edfc` / `#a7b2dc` | the person's bubble and the current chat row |
| `--border` | `#3a4048` | `#e3e3e8` | cards, dividers: quiet (unchanged) |
| `--rule` | `#3a4048` | `#c4c4cc` | hairlines inside an answer and under titles (light needed a stronger line: 1.66 against 1.23) |
| `--border-control` | `#737c86` | `#80808a` | edge of a field or a button (3:1) |
| `--status-ok-*`, `--status-info-*` | see CSS | see CSS | new; copied from the console's success and a steel info |
| `--danger-edge` | `#aa766f` | `#c24a68` | danger button edge (the console's) |
| `--selection` | blue at 34% | blue at 22% | `::selection` |
| `--scrollbar-thumb(-hover)` | `#68717b` / `#8793a0` | `#8a8a93` / `#5a5a63` | scrollbars |
| `--hl-*` | aliases | aliases | code token colours (section 6.4) |
| `--measure` | 36rem | 36rem | the prose width cap (`max-w-measure`) |

**Tailwind names** (every alias in §3b; the rest are read through `var()` in CSS, not as utilities):

| Token | Utility |
|---|---|
| `--foreground`, `--foreground-strong`, `--muted`, `--faint`, `--heading` | `text-fg`, `text-strong`, `text-muted`, `text-faint`, `text-heading` |
| `--link`, `--link-hover` | `text-link`, `hover:text-link-hover` |
| `--background`, `--panel`, `--panel-soft` (and `bg-surface`, the name 20 fields already use), `--panel-hover` | `bg-bg`, `bg-panel`, `bg-soft` / `bg-surface`, `bg-hover` |
| `--accent-left`, `--accent-hover`, `--accent-active`, `--on-accent-left` | `bg-accent` `text-accent` `border-accent` `ring-accent`, `bg-accent-hover`, `bg-accent-active`, `text-on-accent` |
| `--accent-right` | `bg-apricot` `text-apricot` `border-apricot` |
| `--tint`, `--tint-edge` | `bg-tint`, `border-tint-line` |
| `--border`, `--border-control` | `border-line`, `border-line-strong` (repointed from `--border-hover`, which it never used) |
| `--status-warn-*`, `--status-error-*` | `text-warn` `bg-warn-bg` `border-warn-line`; `text-error` `bg-error-bg` `border-error-line` (unchanged) |
| `--status-ok-*`, `--status-info-*` | `text-ok` `bg-ok-bg` `border-ok-line`; `text-info` `bg-info-bg` `border-info-line` |
| `--measure` | `max-w-measure` |
| `--text-read`, `--text-xs`, `--text-xl` | `text-read` (new), `text-xs` and `text-xl` (retuned) |
| no utility needed | `--accent-right-text`, `--border-hover`, `--rule`, `--danger-edge`, `--selection`, `--scrollbar-*`, `--hl-*` |

### 3.2 Contrast, recomputed

WCAG 2 relative luminance, computed here for every pair; tinted backgrounds are composited over the page and over a panel and the lower value is shown. APCA Lc (0.0.98G) is given for the text tiers. Surfaces: bg `#141619` / panel `#1b1e22` / soft `#23272c` / hover `#2b3037` (dark); bg `#fafafb` / panel `#ffffff` / soft `#f3f3f5` / hover `#e7e7eb` (light).

**Text (must be 4.5 or better; headings 3 or better).**

| Pair | Dark: bg / panel / soft / hover | Light: bg / panel / soft / hover | Lc dark bg / light bg |
|---|---|---|---|
| foreground-strong | 16.72 / 15.43 / 13.86 / 12.26 | 18.60 / 19.41 / 17.51 / 15.73 | -100.8 / 102.7 |
| foreground (body) | 14.76 / 13.62 / 12.23 / 10.82 | 18.60 / 19.41 / 17.51 / 15.73 | -91.8 / 102.7 |
| muted | 9.16 / 8.45 / 7.59 / 6.71 | 6.54 / 6.82 / 6.16 / 5.53 | -63.2 / 80.6 |
| faint | 6.39 / 5.90 / 5.30 / 4.69 | 5.06 / 5.28 / 4.77 / 4.28 (not used on hover) | -46.5 / 73.3 |
| heading (h1 to h3, lead-ins) | 10.83 / 10.00 / 8.98 / 7.94 | 7.36 / 7.67 / 6.93 / 6.22 | -72.4 / 82.9 |
| accent-right-text | 7.35 / 6.79 / 6.09 / 5.39 | 5.63 / 5.87 / 5.30 / 4.76 | -52.7 / 75.0 |
| link | 9.90 / 9.13 / 8.20 / 7.25 | 5.69 / 5.93 / 5.35 / 4.81 | -67.4 / 75.9 |
| link-hover | 11.89 / 10.97 / 9.85 / 8.71 | 7.64 / 7.97 / 7.19 / 6.46 | |
| on-accent on accent / hover / active | 8.09 / 10.29 / 6.41 | 5.93 / 7.97 / 9.74 | |
| on the person's bubble (tint): foreground / strong / muted / link | 10.18 / 11.54 / 6.32 / 6.83 | 16.59 / 16.59 / 5.83 / 5.07 | |
| status text on its own tint (over page / panel): warn | 7.81 / 7.15 | 7.21 / 7.47 | |
| error | 6.81 / 6.32 | 7.15 / 7.41 | |
| ok | 7.99 / 7.30 | 6.15 / 6.37 | |
| info | 8.14 / 7.33 | 6.89 / 7.19 | |
| foreground on those tints | 10.93 to 12.77 | 16.54 to 17.76 | |
| code tokens on the code body (soft): keyword / string / number / title / attr / comment / punct | 8.20 / 7.77 / 7.53 / 8.98 / 6.52 / 5.30 / 7.59 | 5.35 / 6.28 / 7.37 / 6.93 / 7.57 / 4.77 / 6.16 | |
| language label and Copy (muted) on the code header (hover) | 6.71 | 5.53 | |
| selected text on the selection fill: strong / foreground / muted | 8.48 / 7.48 / 4.64 | 13.41 / 13.41 / 4.72 | |

**Non-text (must be 3 or better).**

| Pair | Dark | Light |
|---|---|---|
| `--border-control` on bg / panel / soft / hover | 4.28 / 3.95 / 3.55 / 3.14 | 3.75 / 3.91 / 3.53 / 3.17 |
| focus ring and current rail (`--accent-left`) on bg / panel / soft / tint | 7.78 / 7.18 / 6.45 / 5.36 | 5.69 / 5.93 / 5.35 / 5.12 |
| `--accent-right` marks on bg / panel / soft / hover | 7.35 / 6.79 / 6.09 / 5.39 | 4.38 / 4.57 / 4.12 / 3.70 |
| scrollbar thumb on bg / panel / soft | 3.66 / 3.37 / 3.03 | 3.28 / 3.42 / 3.09 |
| danger edge on bg / soft | 4.77 / 3.96 | 4.50 / 4.24 |
| the 2 px `--accent-right` rule under a table head, on the head fill (hover) | 5.39 | 3.70 |

**Deliberately quiet (decoration, no minimum).** `--border` on bg 1.73 dark, 1.23 light. `--rule` 1.73 and 1.66. The bubble fill on the page 1.45 and 1.12, its edge 2.94 and 2.00. The code body on the page 1.21 and 1.06. In light the bubble, the code body and the table header have a 1 px edge as well, so none of them depends on the fill.

**`prefers-contrast: more`** (section 9) lifts every text tier to 7:1 or better (dark: muted 10.08, faint 9.01, link 9.85, heading 10.72, edges 5.34 to 7.01; light: muted 8.70, faint 7.92, link 7.74, heading 8.96, edges 5.44 to 7.92, all on soft).

---

## 4. Type scale

Family `--font-ui` (IBM Plex Sans Variable, weights 100 to 700, real italic) and `--font-code` (IBM Plex Mono 400; it has no variable build). `html { font-synthesis: none }`. This Plex Sans Latin subset carries `kern` and `liga` only and its digits are already tabular (all ten 600/1000), so `tabular-nums`, `zero` and `ss0x` would change nothing (T17); do not add `text-rendering: optimizeLegibility`.

### 4.1 Chrome roles

| Role | Tailwind | rem / px | Line height | Weight | Tracking | Colour | Used for |
|---|---|---|---|---|---|---|---|
| display | `text-2xl` | 1.5 / 24 | 1.333 (32) | 600 | -0.015em | strong | sign-in title, empty-state headline |
| title | `text-xl` (retuned) | 1.25 / 20 | 1.3 (26) | 600 | -0.01em | strong | chat title, page titles, sidebar brand |
| section title | `.title-section` | 1 / 16 | 1.5 (24) | 600 | 0 | strong | h2 of a page, with hairline and segment |
| card title | `.title-card` | 1 / 16 | 1.5 | 600 | 0 | strong | a card or form title |
| sub-title | `.title-sub` | 0.875 / 14 | 1.43 (20) | 600 | 0 | strong | sub-block, legend |
| body | `text-base` | 1 / 16 | 1.5 (24) | 400 | 0 | foreground | short standalone copy, the 16 px floor for touch fields |
| UI | `text-sm` | 0.875 / 14 | 1.43 (20) | 400, 500 labels, 600 buttons | 0 | foreground | nav, buttons, labels, list rows, reasoning |
| help | `.help` | 0.875 / 14 | 1.57 (22) | 400 | 0 | muted | instructions under a field, 34 em wide |
| meta | `text-xs` (retuned) | 0.8125 / 13 | 1.385 (18) | 400, 500 | 0 | muted | timestamps, Copy, Try again, hints |
| eyebrow | `eyebrow` | 0.75 / 12 | 1.333 (16) | 600 | +0.06em | muted | CHATS, the Sources heading, settings group labels (answer h5 and h6 do the same in em; badges share the size and weight without the capitals) |
| read | `text-read` | 1.0625 / 17 | 1.65 (28.05) | 400, 600, italic | 0 | foreground | answers; the person's words and the composer at 1.55 (26.35) |
| code block | in `.answer pre` | 0.875 / 14 | 1.55 (21.7) | 400 | 0 | foreground | fences |

### 4.2 Reading roles (in em of the 17 px answer, so a 14 px draft scales)

| Element | Size | Line height | Weight | Tracking | Colour |
|---|---|---|---|---|---|
| paragraph, li | 1 em / 17 px | 1.65 | 400 | 0 | foreground |
| strong | 1 em | 1.65 | 600 | 0 | foreground-strong |
| bold lead-in (ends in a colon, 48 characters or less) | 1 em | 1.65 | 600 | 0 | heading |
| h1 | 1.5 em / 25.5 px | 1.2 (30.6) | 600 | -0.018em | heading |
| h2 | 1.25 em / 21.25 px | 1.25 (26.6) | 600 | -0.012em | heading |
| h3 | 1.1 em / 18.7 px | 1.3 (24.3) | 600 | -0.006em | heading |
| h4 | 1 em / 17 px | 1.4 (23.8) | 600 | 0 | foreground-strong |
| h5, h6 | 0.8125 em / 13.8 px, uppercase | 1.4 (19.3) | 600 (h6 500) | +0.06em | muted |
| inline code | 0.88 em / 14.96 px | inherit | 400 | 0 | foreground |
| table | 0.9 em / 15.3 px | 1.45 (22.2) | 400, th 600 | 0 | foreground, th strong |
| code label (language) | 12 px mono | 1.25rem | 400 | +0.04em | muted |

### 4.3 Fonts to load (`main.tsx`)

```ts
import "@fontsource-variable/ibm-plex-sans/wght.css";        // latin 45.7 KB, weights 100-700
import "@fontsource-variable/ibm-plex-sans/wght-italic.css"; // latin 50.2 KB, real italic
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.css";
```

`package.json`: add `@fontsource-variable/ibm-plex-sans` `^5.3.0`, remove `@fontsource/ibm-plex-sans`. Payload (Latin, woff2): 61.5 KB today (Sans 400 and 600, Mono 400); 110.6 KB after (95.9 Sans + 14.7 Mono); 136.6 KB with five static Sans faces. Fallback metrics: Plex Sans 44.72 per 100 px of prose, Arial 44.71, Segoe UI 44.13: the swap reflows by about 1% (typo/extras/fallback.json), so no metric-matched fallback face is needed.

```css
/* styles.css §4: scale, base rules, and what the browser would decide */
@utility eyebrow {
  font-size: 0.75rem;
  line-height: calc(16 / 12);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

@layer base {
  /* Preflight sets every heading to the body's size and weight; outside an
     answer a heading now has one meaning per level, and a utility
     (text-xl, eyebrow, font-medium) still wins. */
  h1,
  h2,
  h3,
  h4 {
    color: var(--foreground-strong);
  }
  h1 {
    font-size: 1.25rem;
    line-height: 1.3;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  h2 {
    font-size: 1rem;
    line-height: 1.5;
    font-weight: 600;
  }
  h3,
  h4 {
    font-size: 0.875rem;
    line-height: calc(20 / 14);
    font-weight: 600;
  }
  kbd {
    display: inline-block;
    min-width: 1.5rem;
    padding: 0.125rem 0.375rem;
    border: 1px solid var(--border-hover);
    border-bottom-width: 2px;
    border-radius: var(--radius);
    background: var(--panel-soft);
    color: var(--foreground);
    font: 0.8125rem/1.25 var(--font-code);
    text-align: center;
  }
  ::placeholder {
    color: var(--faint);
    opacity: 1;
  }
  /* In the base layer so a component can tune it; fields hug it (.control). */
  :focus-visible {
    outline: 2px solid var(--accent-left);
    outline-offset: 2px;
  }
  button:not(:disabled),
  summary,
  select,
  [role="tab"],
  label:has(> input[type="checkbox"]),
  label:has(> input[type="radio"]) {
    cursor: pointer;
  }
  button:disabled,
  input:disabled,
  select:disabled,
  textarea:disabled {
    cursor: not-allowed;
  }
  /* A button not yet converted to .btn keeps the old look; .btn:disabled wins. */
  button:disabled {
    opacity: 0.5;
  }
}

html {
  /* Every face a page uses is loaded, so none is faked. */
  font-synthesis: none;
  /* Light text on a dark ground looks heavier than it is; macOS honours this. */
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  accent-color: var(--accent-left);
}
@media (prefers-color-scheme: light) {
  html {
    -webkit-font-smoothing: auto;
    -moz-osx-font-smoothing: auto;
  }
}

html,
body,
#root {
  height: 100%;
}
#root {
  height: 100dvh;
}
body {
  margin: 0;
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-ui);
  /* A long unbroken string in reasoning, a source title or an error must not
     widen the page; an answer keeps `anywhere` only where it asks (.answer). */
  overflow-wrap: break-word;
}
.clipboard-field {
  position: fixed;
  left: -10000px;
  top: 0;
}

input,
textarea {
  caret-color: var(--accent-left);
}
::selection {
  background: var(--selection);
  color: var(--foreground-strong);
}

/* Chrome ignores ::-webkit-scrollbar once scrollbar-color is set, so the
   standard properties are for the browsers that lack it. Measured: this gives
   Chrome a 10 px thumb with no arrows, Firefox a thin native bar. */
@supports not selector(::-webkit-scrollbar) {
  * {
    scrollbar-width: thin;
    scrollbar-color: var(--scrollbar-thumb) transparent;
  }
}
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track,
::-webkit-scrollbar-corner {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  border: 2px solid transparent;
  border-radius: 8px;
  background-color: var(--scrollbar-thumb);
  background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover {
  background-color: var(--scrollbar-thumb-hover);
  background-clip: padding-box;
}
```

---

## 5. Spacing, the answer's rhythm and the column

### 5.1 The scale (Tailwind's 4 px steps; no new tokens)

| Role | rem / px | Tailwind | Used for |
|---|---|---|---|
| hug | 0.25 / 4 | `gap-1`, `mt-1` | an action row under its message; a list item pair; a hint under its field |
| tight | 0.5 / 8 | `gap-2` | a heading to its first block; continuation paragraph in an item; rows of controls |
| group | 0.75 / 12 | `gap-3` | the parts of one answer; box padding sides; loose list items |
| flow | 1 / 16 | `gap-4` | question to answer; fields in a form; thread side padding |
| section | 1.5 / 24 | `gap-6` | thread top; before a Sources block |
| turn | 2 / 32 | `gap-8` | between turns; thread bottom; between page sections |

A boxed text is inset 12 px plus its 1 px border in Reasoning, a tool card and a table cell (13 px), and 16 px plus the border in code (17 px, so a 14 px mono line has air at its edge); SP-10 wanted 13 everywhere and the typography audit 16 for code, and code kept its 16.

### 5.2 The answer, in em of its own 17 px

| From to | Value | px at 17 px | Why |
|---|---|---|---|
| block to block | 0.9 em (margin-top of every child after the first) | 15.3 | 55% of the 28.05 px line pitch; Butterick asks 50 to 100% of the size |
| block to h1 / h2 / h3 / h4 / h5-h6 | 1.6 / 1.6 / 1.5 / 1.4 / 1.6 em of the heading | 40.8 / 34.0 / 28.1 / 23.8 / 22.1 | proportional to the heading, always more than twice a paragraph gap |
| h1 / h2 / h3 / h4 / h5-h6 to its block | 0.5 / 0.45 / 0.4 / 0.3 / 0.35 em of the heading | 12.8 / 9.6 / 7.5 / 5.1 / 4.8 | the heading belongs to what follows: above is 3.2 to 4.7 times below |
| h1, h2 text to its hairline | 0.3 em of the heading | 7.7 / 6.4 | |
| li to li (tight / loose) | 0.3 em / 0.6 em | 5.1 / 10.2 | items read as items; loose items are further apart than a continuation |
| list in a list item | 0.3 em | 5.1 | the child hugs its parent |
| continuation block in an item | 0.5 em | 8.5 | |
| hr, above and below | 1.75 em | 29.8 | a section break outranks a heading gap above |
| first child, last child | 0 | 0 | the article's 12 px gap owns the outside |

### 5.3 The thread

| From to | px | Class |
|---|---|---|
| top of the thread / bottom | 24 / 32 | `pt-6 pb-8` |
| a question to its answer | 16 | `gap-4` |
| an answer to the next question | 32 | `gap-4` plus `[&:not(:first-child)]:mt-4` on a user message |
| parts of one answer (reasoning, tool calls, text, sources, notes) | 12 | article `gap-3` |
| a message to its meta row | 4 (person) / 8 (answer) | `gap-1`; `-mt-1` |
| a Reasoning summary to its text | 4 | `mt-1` |
| Sources block above | 24 | `mt-1` plus `border-t pt-3` on the article's 12 |

### 5.4 Widths and the arithmetic

Three widths, defined once: **measure** `36rem` (576 px), **thread** `48rem` (768 px, `max-w-3xl`, unchanged), **page** `48rem` (`.page-col`). Text and its furniture (Reasoning, draft, tool cards, status notes, Sources, the person's bubble) stop at the measure; objects (code, tables, media) and chrome (header content, composer) use the thread.

Characters per line = 0.957 x W / (c x s), where c is the average prose character in Plex Sans (0.4425 em measured over a 1,078-character story; 0.452 from the font files), s is the size in px, and 0.957 is how full a ragged-right line gets.

| W at 17 px | 512 | 544 | 560 | **576 (36 rem)** | 608 | 640 | 768 |
|---|---|---|---|---|---|---|---|
| average characters per full line | 65.0 | 68.8 | 72.6 | **74.5** | 78.0 | 79.5 | 100.1 |

At the 36 rem measure the arithmetic gives 78 characters at 16 px, 73 at 17 px, 69 at 18 px. Measured in Chrome on this stylesheet (Appendix B), counting real line breaks at 17 px: the rich answer's paragraph 71.3 average and 75 maximum; four story paragraphs 70.3, 74.0, 75.5 and 76.5 average (74.1 mean) and 80 maximum; on a 390 px phone 41 to 46 average and 48 maximum. The typography and spacing runs agree (69 to 71.3, and 74.5). WCAG 1.4.8 asks 80 at most. For 66, 72, 75, 80, 90 characters at 17 px the width is 32.4, 35.4, 36.8, 39.3, 44.2 rem.

**The price is height.** Shorter lines and larger type make an answer taller. Appendix B measured the shipped stylesheet and four settings of this one on the same answers (the harness column is 736 px; the app's is 768):

| Setting | story paragraphs: average / maximum characters | rich answer, px | story, px |
|---|---|---|---|
| shipped (16 px, no cap) | 97.5 to 101 / 105 | 2100 | 285 |
| **36 rem, 17 px (this spec)** | 70.3 to 76.5 / 80 | 2625 (+25%) | 439 (+54%) |
| 40 rem, 17 px | 76 to 80.5 / 85 | 2569 (+22%) | 382 (+34%) |
| 36 rem, 16 px | 76 to 80 / 85 | 2454 (+17%) | 360 (+26%) |
| 36 rem, 18 px | 65 to 72 / 76 | 2769 (+32%) | 464 (+63%) |

On a 390 px phone the rich answer goes from 2561 to 3044 px (+19%) and the story from 541 to 607 (+12%); the wide table from 771 to 484 (-37%), because its words stop breaking. Two readings of that: the 36 rem measure is the one choice that meets WCAG 1.4.8's 80 at 17 px, and it costs a quarter more scrolling on technical answers and half more on prose; 16 px at 36 rem is nearer the old height but runs to 85 characters (use 34 rem with it); 40 rem is the middle road. This is taste call 3.

Alignment at 1440 wide (pane 1152, frame x=480 to 1248): the chat title, bubble right edge, prose, code, tables and composer share one frame because the header content gets the same `max-w-3xl` wrapper (SP-08). At Troy's 2048 CSS px window the pane is 1760 and the frame still starts at x=784: with a 40 rem frame the margins would be 560 px each side instead of 496.

Reserve the scrollbar's space so the thread never shifts 7.5 px when the first answer overflows and always lines up with the composer: `[scrollbar-gutter:stable_both-edges]` on the scroller (SP-09).

---

## 6. Answer Markdown

### 6.1 The CSS

Unlayered, like the existing `.answer` rules, so it still wins over utilities on the elements inside an answer; `Markdown.tsx` drops the utilities that used to fight it.

```css
/* styles.css §6: an answer's Markdown */
.answer {
  font-size: var(--text-read);
  line-height: var(--text-read--line-height);
  /* Not `anywhere`: that lets a table's columns shrink to a sliver. */
  overflow-wrap: break-word;
}
/* A draft that a search or a tool call wrote first sits in a 14 px muted box. */
.answer.answer-quiet {
  font-size: inherit;
  line-height: 1.6;
}

/* Prose keeps to the measure; code and tables use the whole column. */
.answer > :is(p, ul, ol, blockquote, hr, h1, h2, h3, h4, h5, h6) {
  max-width: var(--measure);
}

/* One owner per gap: a block owns the space above it. */
.answer > * + * {
  margin-top: 0.9em;
}
.answer > :first-child {
  margin-top: 0;
}
.answer > :last-child {
  margin-bottom: 0;
}

/* Streaming rewraps the last lines on every chunk, so `pretty` waits. */
.answer :is(p, li, blockquote) {
  text-wrap: pretty;
}
[data-status="running"] .answer :is(p, li, blockquote) {
  text-wrap: wrap;
}

/* Headings */
.answer :is(h1, h2, h3, h4, h5, h6) {
  color: var(--foreground-strong);
  font-weight: 600;
  text-wrap: balance;
}
.answer :is(h1, h2, h3) {
  color: var(--heading);
}
.answer h1 {
  font-size: 1.5em;
  line-height: 1.2;
  letter-spacing: -0.018em;
  margin: 1.6em 0 0.5em;
}
.answer h2 {
  font-size: 1.25em;
  line-height: 1.25;
  letter-spacing: -0.012em;
  margin: 1.6em 0 0.45em;
}
.answer h3 {
  font-size: 1.1em;
  line-height: 1.3;
  letter-spacing: -0.006em;
  margin: 1.5em 0 0.4em;
}
.answer h4 {
  font-size: 1em;
  line-height: 1.4;
  margin: 1.4em 0 0.3em;
}
.answer :is(h5, h6) {
  color: var(--muted);
  font-size: 0.8125em;
  line-height: 1.4;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin: 1.6em 0 0.35em;
}
.answer h6 {
  font-weight: 500;
}
/* The hairline under h1 and h2, and the segment that closes it. */
.answer :is(h1, h2) {
  position: relative;
  padding-bottom: 0.3em;
  border-bottom: 1px solid var(--rule);
}
.answer :is(h1, h2)::after {
  content: "";
  position: absolute;
  inset-inline-start: 0;
  bottom: -1px;
  width: 2.5rem;
  height: 2px;
  background: var(--accent-right);
}
/* The heading's own bottom margin is the gap; the next block adds none. */
.answer :is(h1, h2, h3, h4, h5, h6) + * {
  margin-top: 0;
}

/* Emphasis */
.answer :is(strong, b) {
  color: var(--foreground-strong);
  font-weight: 600;
}
.answer strong.lead-in {
  color: var(--heading);
}
.answer :is(strong, b, h1, h2, h3, h4, h5, h6) code {
  font-weight: 400;
}
.answer del {
  color: var(--muted);
  text-decoration-thickness: 1px;
}

/* Links */
.answer a {
  color: var(--link);
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 0.2em;
  text-decoration-color: color-mix(in srgb, currentColor 55%, transparent);
}
@media (hover: hover) {
  .answer a:hover {
    color: var(--link-hover);
    text-decoration-thickness: 2px;
    text-decoration-color: currentColor;
  }
}

/* Lists */
.answer :is(ul, ol) {
  padding-inline-start: 1.5em;
}
.answer ol {
  padding-inline-start: 1.75em;
}
.answer ul {
  list-style: disc;
}
.answer ul ul {
  list-style: circle;
}
.answer ul ul ul {
  list-style: square;
}
.answer ol {
  list-style: decimal;
}
.answer ol ol {
  list-style: lower-alpha;
}
.answer li::marker {
  color: var(--muted);
}
.answer ol > li::marker {
  font-weight: 600;
}
.answer li + li {
  margin-top: 0.3em;
}
.answer li > * + * {
  margin-top: 0.5em;
}
.answer li > :is(ul, ol) {
  margin-top: 0.3em;
}
.answer li > p:last-child {
  margin-bottom: 0.6em;
}
.answer li:last-child > p:last-child {
  margin-bottom: 0;
}
.answer .contains-task-list {
  list-style: none;
  padding-inline-start: 0;
}
.answer .task-box {
  display: inline-block;
  box-sizing: border-box;
  width: 0.95em;
  height: 0.95em;
  margin-inline-end: 0.5em;
  vertical-align: -0.12em;
  border: 2px solid var(--border-control);
  border-radius: 3px;
}
.answer .task-box[data-checked="true"] {
  border-color: var(--accent-left);
  background: var(--accent-left);
}
.answer .task-box[data-checked="true"]::after {
  content: "";
  display: block;
  width: 0.26em;
  height: 0.5em;
  margin: 0.03em auto 0;
  border: solid var(--on-accent-left);
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

/* Quote */
.answer blockquote {
  padding: 0.15em 0;
  padding-inline-start: 1em;
  border-inline-start: 3px solid var(--accent-right);
}
.answer blockquote > * + * {
  margin-top: 0.6em;
}

/* Rule */
.answer hr {
  height: 0;
  margin: 1.75em 0;
  border: 0;
  border-top: 1px solid var(--rule);
}

/* Code: inline, then the block (header with the language and Copy, then the code) */
.answer code {
  font-family: var(--font-code);
}
.answer :not(pre) > code {
  padding: 0.08em 0.35em;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--panel-soft);
  font-size: 0.88em;
}
.answer .code-block {
  overflow: hidden;
  border: 1px solid var(--rule);
  border-radius: calc(var(--radius) + 2px);
  background: var(--panel-soft);
}
.answer .code-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  min-height: 2rem;
  padding: 0 0.5rem 0 0.875rem;
  border-bottom: 1px solid var(--rule);
  background: var(--panel-hover);
  color: var(--muted);
  font-size: 0.8125rem;
  line-height: 1.25rem;
}
.answer .code-lang {
  font-family: var(--font-code);
  font-size: 0.75rem;
  letter-spacing: 0.04em;
}
/* The block clips its corners, so the Copy button's ring stays inside it. */
.answer .code-head :focus-visible {
  outline-offset: -2px;
}
.answer pre {
  margin: 0;
  padding: 0.75rem 1rem;
  overflow-x: auto;
  font-size: 0.875rem;
  line-height: 1.55;
}
.answer pre:focus-visible {
  outline-offset: -2px;
}

/* Tables: whole words, rules not a grid, a header that anchors, left unless asked. */
.answer .table-wrap {
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--rule);
  border-radius: calc(var(--radius) + 2px);
}
.answer table {
  border-collapse: collapse;
  font-size: 0.9em;
  line-height: 1.45;
}
.answer :is(th, td) {
  padding: 0.5em 0.8em;
  border-bottom: 1px solid var(--rule);
  vertical-align: top;
  overflow-wrap: normal;
}
/* A column the Markdown aligned (`---:`, `:-:`) reaches the page as an inline
   style="text-align: ..." (react-markdown 10 turns the align attribute into
   one), which beats this rule; this is only for the header that was not. */
.answer th {
  text-align: start;
}
.answer thead th {
  border-bottom: 2px solid var(--accent-right);
  background: var(--panel-hover);
  color: var(--foreground-strong);
  font-weight: 600;
}
.answer tbody tr:last-child td {
  border-bottom: 0;
}
```

### 6.2 What each element does and why

| Element | Look | Source |
|---|---|---|
| paragraph | 17 px / 1.65, 36 rem, `pretty` once finished | T05, T03, T18 |
| h1, h2 | 25.5 / 21.25 px 600 warm, hairline plus a 2.5 rem x 2 px segment; 34 px above, 9.6 below (h2) | T02, MD-01, C3 |
| h3 | 18.7 px 600 warm, no rule | T02 |
| h4 | 17 px 600 strong, not tinted | T02 |
| h5, h6 | 13.8 px uppercase muted tracked (h6 500) | T02 |
| strong | 600, strong tier; a lead-in (see 6.3) takes the heading colour | MD-02 |
| em | a real italic (400i, or 600i inside strong) | MD-03, T01 |
| del | muted, 1 px line | MD-03 |
| link | `--link`, 1 px underline set back 0.2 em, 2 px and brighter on hover | COL-08, BP20 |
| ul, ol | 1.5 em / 1.75 em indent (holds "99."), muted markers, bold numerals; circle then square when nested | T15, SP-02 |
| task list | no disc; a drawn 0.95 em box (checked: blue fill and tick); "Done: " and "Not done: " for a screen reader | MD-14, A11Y-09 |
| quote | warm 3 px bar, body-coloured text | MD-12, BP12, C4 |
| hr | 1 px `--rule`, 1.75 em above and below | BP04, C3 |
| inline code | 0.88 em, soft fill and a 1 px edge (light mode needs it) | MD-16 |
| code block | one box: header (language, Copy) fused to the code, 14 px / 1.55, 16 px padding, scrolls sideways | T09, MD-04, SP-05 |
| table | whole words, scrolls inside its own bordered box; rules, header fill, warm 2 px rule; numbers align through `---:` | MD-06, MD-07, T04 |

### 6.3 `Markdown.tsx`

Changes against the file as it is (lines 28 to 90): the code block, a table wrapper, a lead-in tag on `strong`, a task box in place of the native input, and a `quiet` prop for the draft. `pr-20`, `p-3`, `text-sm` and `relative` go, because `.answer pre` now owns them.

```tsx
import { Children, isValidElement, type ReactNode } from "react";

/** The language a fence names, as written ("bash", "py"), or null. */
function languageOf(children: ReactNode): string | null {
  const code = Children.toArray(children)[0];
  if (!isValidElement<{ className?: string }>(code)) return null;
  return /language-([\w#+.-]+)/.exec(code.props.className ?? "")?.[1] ?? null;
}

function CodeBlock({ children }: { children: ReactNode }) {
  const text = textOf(children);
  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{languageOf(children) ?? "code"}</span>
        <CopyButton text={text} label="code" />
      </div>
      <pre>{children}</pre>
    </div>
  );
}

const components: Components = {
  // img, a: as now
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>;
  },
  table({ children }) {
    return (
      <div className="table-wrap">
        <table>{children}</table>
      </div>
    );
  },
  // "Why:", "Risks:", "Note:" : a short bold label ending in a colon.
  strong({ children }) {
    const label = textOf(children).trim();
    const leadIn = label.length > 0 && label.length <= 48 && /[:：]$/.test(label);
    return <strong className={leadIn ? "lead-in" : undefined}>{children}</strong>;
  },
  // The native disabled box is 13 px at 1.5 to 1.6:1 and unlabelled (axe: critical).
  input({ checked, type }) {
    if (type !== "checkbox") return null;
    return (
      <>
        <span className="task-box" aria-hidden="true" data-checked={checked ? "true" : "false"} />
        <span className="sr-only">{checked ? "Done: " : "Not done: "}</span>
      </>
    );
  },
};

export function Markdown({ text, quiet = false }: { text: string; quiet?: boolean }) {
  return (
    <div className={quiet ? "answer answer-quiet" : "answer"}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}
```

Checked in memory, assembled into the real `Markdown.tsx` (with the section 6.4 direction helper) and the real `lib/words.ts` (with the section 9.1 helpers): `tsc` under the project's strict options (`noUnusedLocals`, `noUncheckedIndexedAccess`) and ESLint under the project's config report nothing. The snippets are laid out for reading, not for Prettier; `npm run format` does the rest.

`MessageView.tsx:213` passes `quiet` to the draft's `<Markdown>`. Plugin arrays stay at module scope (streaming re-renders must not rebuild the processor). `'**Why**:'` (colon outside the bold) is not tagged, on purpose.

Tests to add (`Markdown.test.tsx`; the five existing ones stay green): a `py` fence shows `py` and one Copy button named "Copy code"; an unlabelled fence shows `code`; `**Why:** x` renders `<strong class="lead-in">`, `**plain**` and `**Why**:` do not; a table sits inside `.table-wrap` and `getByRole("table")` still finds it, with a `---:` column's header still carrying `style.textAlign === "right"` (react-markdown writes the alignment as an inline style, not an `align` attribute); a task list has no `input`, says "Done:" before the first item and "Not done:" before the second (compare with whitespace collapsed: the text node after the box starts with a space), and has one `.task-box[data-checked="true"]`; the draft gets `answer-quiet`.

### 6.4 Optional blocks, each behind its own slice

**R5: syntax colour** (section 10 weighs it). Only classes, so dark and light follow with no script; every colour is a token already verified above.

```css
/* optional §6.4: syntax tokens, once rehype-highlight lands */
.answer .hljs-comment,
.answer .hljs-quote {
  color: var(--hl-comment);
  font-style: italic;
}
.answer .hljs-keyword,
.answer .hljs-selector-tag,
.answer .hljs-doctag,
.answer .hljs-name,
.answer .hljs-tag {
  color: var(--hl-keyword);
}
.answer .hljs-string,
.answer .hljs-regexp,
.answer .hljs-template-variable {
  color: var(--hl-string);
}
.answer .hljs-number,
.answer .hljs-literal,
.answer .hljs-symbol,
.answer .hljs-bullet {
  color: var(--hl-number);
}
.answer .hljs-title,
.answer .hljs-type,
.answer .hljs-built_in,
.answer .hljs-section,
.answer .hljs-selector-class,
.answer .hljs-selector-id {
  color: var(--hl-title);
}
.answer .hljs-attr,
.answer .hljs-attribute,
.answer .hljs-property {
  color: var(--hl-attr);
}
.answer .hljs-punctuation,
.answer .hljs-operator,
.answer .hljs-meta {
  color: var(--hl-punct);
}
.answer .hljs-addition {
  background: var(--status-ok-bg);
  color: var(--status-ok-fg);
}
.answer .hljs-deletion {
  background: var(--status-error-bg);
  color: var(--status-error-fg);
}
.answer .hljs-emphasis {
  font-style: italic;
}
.answer .hljs-strong {
  font-weight: 600;
}
```

Wiring: `rehypePlugins={[[rehypeHighlight, { detect: false, languages: { ...common, powershell, dockerfile }, plainText: ["text", "txt", "plaintext", "log", "output"] }]]}`. `detect: false` means an unlabelled fence is never guessed. `textOf()` still returns the source, so Copy is unchanged; test it.

**R5: GitHub alerts** (`> [!NOTE]`), 15 lines of remark, no dependency: the plugin consumes the marker, sets `data-alert` and `className`, and CSS draws the label from the attribute.

```css
/* optional §6.4: alerts */
.answer blockquote.alert {
  --alert: var(--status-info-fg);
  border-inline-start-color: var(--alert);
  background: color-mix(in srgb, var(--alert) 9%, transparent);
  padding-inline-end: 1em;
}
.answer blockquote.alert-tip {
  --alert: var(--status-ok-fg);
}
.answer blockquote.alert-important {
  --alert: var(--accent-right-text);
}
.answer blockquote.alert-warning {
  --alert: var(--status-warn-fg);
}
.answer blockquote.alert-caution {
  --alert: var(--status-error-fg);
}
.answer blockquote.alert::before {
  content: attr(data-alert);
  display: block;
  margin-top: 0.35em;
  color: var(--alert);
  font-size: 0.75em;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
```

**R5: allowlisted HTML.** `skipHtml` turns `<br>` into nothing, so `| line one<br>line two |` shows "line oneline two" and `H<sub>2</sub>O` shows "H2O". A remark plugin maps exactly `<br>`, `<sub>`, `<sup>`, `<kbd>` to Markdown nodes, copying no attributes, before `skipHtml` runs; `<img onerror>`, `<script>`, `<b>` and `<br class=x>` stay dropped. `kbd` already has a base style; `sup` and `sub` are preflight's.

**R5: `remark-breaks`** (1.4 KB gz): a single newline becomes a line break, so `Name: Alice` over `Age: 30` stays two lines, as the person's own whitespace-preserving messages do. Trade-off: a model that hard-wraps prose at 80 columns shows ragged lines. Taste call 12.

**R4: direction.** An Arabic or Hebrew answer renders left-aligned, with bullets and numbers on the left and the sentence order scrambled around Latin words. Every side-specific property in this stylesheet is already logical (`padding-inline-start`, `border-inline-start`, `inset-inline-start`, `text-align: start`), so all that is missing is the direction itself. Give each block component an explicit `dir` computed from its own first strong character, with an early exit:

```tsx
// Arabic, Hebrew, Syriac, Thaana and their presentation forms are right to left;
// any other letter (or CJK) is left to right; nothing strong yet means "unset".
function dirOf(node: ReactNode): "rtl" | "ltr" | undefined {
  for (const ch of textOf(node)) {
    const c = ch.codePointAt(0)!;
    if ((c >= 0x590 && c <= 0x8ff) || (c >= 0xfb1d && c <= 0xfdff) || (c >= 0xfe70 && c <= 0xfeff)) return "rtl";
    if (ch.toLowerCase() !== ch.toUpperCase() || (c >= 0x3040 && c <= 0x9fff) || (c >= 0xac00 && c <= 0xd7af)) return "ltr";
  }
  return undefined;
}
const block = (Tag: "p" | "ul" | "ol" | "blockquote" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6" | "th" | "td") =>
  function Block(all: { node?: unknown; children?: ReactNode }) {
    const { node, children, ...props } = all;
    void node; // react-markdown passes its syntax-tree node; it must not reach the DOM
    return createElement(Tag, { dir: dirOf(children), ...props }, children);
  };
// components = { p: block("p"), ul: block("ul"), ... }
```

Why not `dir="auto"`: the browser skips any descendant that carries its own `dir` when it resolves `auto`, so a `blockquote` or a loose list whose children are `dir="auto"` paragraphs resolves to left to right, and its bar and indent stay on the wrong side. Measured in the harness (Appendix B), with the explicit value: the Arabic paragraph is `rtl`, the list's 1.5 em indent is `padding-right`, the numbered list's 1.75 em likewise, the quote's 3 px bar is its right border and the h2 segment starts at the right edge. `lang` (for CJK glyph forms and a screen reader's voice) is later.

---

## 7. The chat's surroundings

Classes shown are final; every `data-testid`, `aria-label`, accessible name and test-asserted class stays (the four asserted classes, `text-error` on the developer-mode badge, `border-error-line` on two marked fields and `text-warn` on heard words, are all kept as utilities). Shared classes (`.btn`, `.control`, `.notice`, `.badge`, `.act`, `.icon-btn`, `.nav-tab`) are defined in §8. Lines are as of `530740f`.

### 7.1 `web/index.html`

Add, so the first frame and a phone's address bar follow the palette (COL-17):

```html
<meta name="color-scheme" content="dark light" />
<meta name="theme-color" content="#141619" media="(prefers-color-scheme: dark)" />
<meta name="theme-color" content="#fafafb" media="(prefers-color-scheme: light)" />
```

Keep the viewport meta as it is (no `maximum-scale`); `interactive-widget=resizes-content` may be appended for Android (A11Y-19).

### 7.2 Sidebar (`Sidebar.tsx`)

| Line | Element | Becomes |
|---|---|---|
| 55 | "Workbench" | `text-xl font-semibold tracking-[-0.01em]` (was `text-lg`) |
| 71 | New chat | `btn w-full` with `<Plus size={16} aria-hidden className="text-accent" />`; testid, `aria-keyshortcuts`, `disabled` kept; its container (line 64) `px-2` |
| 83-88 | mode chip | `badge` (`tabIndex`, `title`, `aria-describedby` and the testid kept; its `<p>` takes `mx-2`); developer mode `badge border-error-line bg-error-bg text-error` (the test asserts `text-error`); a leading `<span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current">` |
| 91-93 | `#install-mode-explained` | developer mode: `help mt-1 block` visible, so keyboard and touch can read who sees what (A11Y-17); production: `sr-only` as now |
| 96-103 | owner reads | `notice notice--warn` (div, icon `Eye`), `data-testid` and text kept |
| 104 | CHATS | `eyebrow px-4 pb-1 pt-4 text-muted` |
| 107-134 | search | wrapper `mx-2 mb-2 flex items-center gap-1 rounded-plexus border border-line-strong bg-soft px-2 focus-within:border-accent focus-within:ring-1 focus-within:ring-accent`; input `outline-none`; 14 px, raised to 16 by the coarse-pointer rule |
| 135-142 | list error | `notice notice--error` with the same `role="alert"` and "Try again" |
| 161 | date label | `px-2 pb-1 pt-3 text-xs font-medium text-muted` |
| 163-184 | chat row | see below |
| 202-214 | person row | Sign out `btn btn-quiet text-muted hover:text-fg` |

The chat row (SUR-01, COL-09; no transparent border, forced colors would paint it):

```tsx
<ul className="flex flex-col gap-0.5">          // each group's list
  ...
  className={`flex w-full cursor-pointer items-center gap-2 rounded-plexus py-1.5 pr-2 text-left text-sm ${
    chat.id === current
      ? "border-l-[3px] border-accent bg-tint pl-[5px] font-medium"
      : "pl-2 hover:bg-hover"
  }`}
```

`truncate` leaves the button (the span at line 183 keeps it; a test asserts it). The running dot gets `animate-pulse run-dot` (reduced motion stops it; forced colors keep it as `Highlight`). The open chat is now a 3 px accent rail plus a tint plus weight 500: three cues, none a fill alone. On a phone add `pointer-coarse:py-2.5` for 40 px rows.

Edges (SP-16): the New chat container (line 64) `px-3` becomes `px-2`, and the chip, owner-reads and search wrappers (77, 99, 107) `mx-3` becomes `mx-2`, so the button, chip, search box and the chat pills all span x=8 to 279 and their text starts at x=16 (it started at three different x values: 12, 8 and 16). Sign out takes `-mr-2`, so its pill ends at 279 and its text at 271.

### 7.3 Top bar and shortcuts (`App.tsx`)

Lines 250 to 297. Always show every page, mark the current one, give each an icon (lucide: `Toolbox`, `Boxes`, `Laptop`, `Keyboard`), so positions stop moving (SUR-11, C17):

```tsx
<nav aria-label="Workbench" className="flex flex-wrap items-center border-b border-line px-2 py-1 sm:gap-x-1 sm:px-3">
  <button onClick={() => setShowChats(true)} aria-controls="chat-navigation" className="nav-tab md:hidden">Chats</button>
  <button aria-current={showTools ? "page" : undefined} className="nav-tab" onClick={...}>
    <Toolbox size={14} aria-hidden />Toolbox · Tools
  </button>
  <button data-testid="open-media" aria-current={onMedia ? "page" : undefined} className="nav-tab" onClick={...}>
    <Boxes size={14} aria-hidden />Bins · Media
  </button>
  {!phase.me.owner && (
    <button aria-current={showSites ? "page" : undefined} className="nav-tab" onClick={...}>
      <Laptop size={14} aria-hidden />Job sites<span className="max-sm:sr-only"> (your machines)</span>
    </button>
  )}
  <button aria-expanded={showShortcuts} aria-controls="keyboard-shortcuts" className="nav-tab needs-keyboard ml-auto text-muted" onClick={...}>
    <Keyboard size={14} aria-hidden />Keyboard shortcuts
  </button>
</nav>
```

`onMedia` is `media !== null && !showTools && !showSites`; clicking the current page is a no-op. The strings `Toolbox · Tools` and `Bins · Media` stay contiguous (`words.test.ts`), the name "Job sites (your machines)" is unchanged (the extra text is `sr-only` on a phone), and the owner still has no Job sites link. On a 390 px phone the bar is one row of 44 px (the four labels take 329 of the 342 px inside `px-2`: the icons are hidden under 40 rem, the padding tightens and the gap goes), where today it is two rows of 20 px links (69 px) whose targets are under the 24 px minimum; a 360 px phone still wraps to two rows.

Shortcuts panel (298-315): an overlay under the bar, not a push that moves the chat down 97 px. Wrap the bar and the panel in `<div className="relative">`; the `aside` (a sibling of the `nav`, so the nav's landmark stays clean) is `absolute right-4 top-full z-20 w-[min(30rem,calc(100vw-2rem))] rounded-plexus border border-line bg-panel p-4 shadow-lg`; Escape and Close still work. Content as a `.keys` list with `<kbd>` keys, grouped: **Anywhere:** Ctrl Alt N New chat, Ctrl Alt F Search chats, Ctrl Alt M Write a message (Control Option on a Mac, chosen by `navigator.platform`); **Message box:** Enter Send, Shift Enter New line; **Chat search:** Enter Open first match, Esc Clear; **Editing a message:** Ctrl Enter (Cmd Enter) Save, Esc Cancel. The text "Ctrl + Alt + N: New chat" must still be findable if a test looks for it (none does today).

Other App.tsx pieces: the install-mode notice (316-333) becomes `notice notice--warn notice--bar` with `Info`, its OK `btn btn-quiet`; the floating error (388-398) `notice notice--error notice--float absolute inset-x-3 bottom-3 z-10 shadow-lg`; the empty state (417-446) `h1 className="text-2xl font-semibold"` (was an `h2`; the page had no h1), its sentence `<span className="text-fg">Ask anything.</span> Answers keep going even if you close this tab.`, the button `btn btn-primary min-h-11 px-5 text-base`.

### 7.4 Chat header and thread (`ChatView.tsx`)

| Line | Element | Becomes |
|---|---|---|
| 121 | header | `border-b border-line px-4 py-1.5` around `<div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-2">`, so the title starts on the frame's left edge and the icons end on its right (SP-08) |
| 163 | h1 | `min-w-0 flex-1 truncate text-xl font-semibold tracking-[-0.01em]` |
| 181-214 | four icon buttons | `icon-btn`; Settings keeps `aria-expanded` (styled when open); Delete `icon-btn icon-btn--danger`; rename form's Save and Cancel `icon-btn` |
| 219-262 | delete confirm | one `notice notice--error w-full flex-wrap items-center` row: the sentence, then Keep it first (`btn`, `autoFocus`, `data-testid="keep-chat"`), then Delete chat (`btn btn-danger`, `data-testid="confirm-delete"`); Escape still cancels |
| 264-289 | error and read-only | `notice notice--error notice--bar` and `notice notice--warn notice--bar` |
| 297-345 | scroller and jump | see below |

```tsx
<div className="relative flex min-h-0 flex-1 flex-col">
  <div ref={box} onScroll={...} role="region" aria-label="Conversation" tabIndex={0}
       className="min-h-0 flex-1 overflow-y-auto px-4 pb-8 pt-6 [scrollbar-gutter:stable_both-edges]"
       data-testid="messages">
    <div ref={content} className="mx-auto flex max-w-3xl flex-col gap-4"> ... </div>
  </div>
  {away && (
    <button className="btn absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full shadow-lg" onClick={...}>
      <ArrowDown size={14} aria-hidden className="text-accent" />Jump to latest
    </button>
  )}
</div>
```

The pill floats over the thread, so showing it no longer resizes the pane (it was a 37 px full-width band between two rules). `role="region"` plus `tabIndex={0}` lets PageUp and the arrow keys scroll from the keyboard (A11Y-05); `.msg` and the scroller keep their testids.

### 7.5 A message (`MessageView.tsx`)

| Line | Element | Becomes |
|---|---|---|
| 62-71 | redacted note | `rounded-plexus border border-line px-3 py-2 text-sm text-muted` stays; the arrows row is `text-xs` as now |
| 77 | person's root | `msg flex flex-col items-end gap-1 [&:not(:first-child)]:mt-4` |
| 145 | bubble | `max-w-[85%] whitespace-pre-wrap break-words rounded-plexus border border-tint-line bg-tint px-4 py-3 text-read leading-[1.55] sm:max-w-measure` |
| 87, 120 | edit form and textarea | form `max-w-measure`; textarea `control text-read leading-[1.55]`; Cancel `btn btn-quiet`, Save and ask again `btn btn-primary` |
| 150-154, 319-323 | version or retry error | `notice notice--error` (role and text kept) |
| 155-171 | person's meta row | `flex min-h-7 flex-wrap items-center justify-end gap-1 text-xs text-muted`; time `pr-2 tabular-nums`; Copy and Edit inside `<span className="msg-actions">`, each `act`; the Edit button's `aria-label` kept; `-mr-2` so the last glyph meets the bubble's edge |
| 187 | answer | `<article className="msg flex flex-col gap-3" ...>` |
| 189-201 | Reasoning | see below |
| 203-215 | draft | same shape, label `Written before ...`, hint `text-xs` inside the body; `<Markdown text={draft} quiet />` |
| 218-226 | working line | see below |
| 227 | answer | `<Markdown text={answer} />` |
| 228-265 | Sources | wrapper `mt-1 border-t border-line pt-3 text-sm max-w-measure`; h3 `eyebrow flex items-center gap-2 text-muted` with `<Globe size={14} aria-hidden className="text-accent">` and the count `<span className="font-normal normal-case tracking-normal">`; list `mt-2 space-y-1 pl-5 marker:text-muted`; link `link` (it was `text-accent underline`); Google's iframe untouched |
| 266-278 | status | see below |
| 279-318 | answer meta row | `-mt-1 flex min-h-7 flex-wrap items-center gap-1 break-all text-xs text-muted`; time `pr-2`; Copy and Try again inside `.msg-actions`; arrows stay visible; model name `pl-2` |
| 373-384 | version arrows | `act justify-center` instead of `p-0.5`; `disabled:opacity-40` goes (it never applied: the unlayered `button:disabled` won) |
| 415 | `shortTime` | `hour: "numeric"` (7:12 PM, not 07:12 PM); the `Polish.test` asserts only the date part |

Reasoning (borderless summary, the console's dashed box for the text; no outline bar above every answer):

```tsx
<details className="group/r text-sm text-muted max-w-measure">
  <summary className="flex w-fit list-none items-center gap-1.5 rounded-plexus py-1 pl-1 pr-2 hover:bg-hover hover:text-fg [&::-webkit-details-marker]:hidden">
    <ChevronRight size={14} aria-hidden className="transition-transform group-open/r:rotate-90" />
    Reasoning
  </summary>
  <div role="group" aria-label="Reasoning text" tabIndex={0} className="reasoning-body mt-1">
    {thoughts.map(...)}   {/* each thought: <div className="whitespace-pre-wrap break-words py-1"> */}
  </div>
</details>
```

`.reasoning-body` (§8) is the dashed, 20 rem scrolling box. `getByText("Reasoning").closest("details")` and "closed by default" still hold. A long token in a thought no longer widens the page (`break-words`; the body rule is the backstop): measured before, one 400-character token made the transcript 3,878 px wide (A11Y-01).

The working line, after the draft and tool calls (SUR-05, SUR-08, SUR-09):

```tsx
const { say, tail } = splitWorking(workingWords(progress, message, now));   // lib/words.ts
<p aria-live="polite" className="text-sm" data-testid="progress">
  <span className="text-fg">{say}</span>
  {tail && <span aria-hidden="true" className="tabular-nums text-muted">{tail}</span>}
</p>
```

`splitWorking` splits at the first ` · ` or `: ` followed by a digit; `textContent`, the testid and `aria-live` are unchanged, so the tests pass. A reader hears "Thinking" once, not every second. After the first token the answer is visible and the line used to vanish; show it below the text while running (the user's own Stop is in the composer): `{running && answer && <p data-testid="writing" className="flex items-center gap-2 text-sm text-muted"><span aria-hidden className="working-dots"><span /><span /><span /></span><span className="tabular-nums">{workingWords(progress, message, now)}</span></p>}`, no `aria-live` (the growing answer is not announced either). `WorkingScene.tsx:80`: the phrase `text-sm italic text-muted` (now a real italic). The scene appears after 600 ms and used to move the line 84 px right and grow the article 48 px (SP-15); reserve its slot from the first frame: the wrapper `min-h-[4.5rem]`, and while no scene shows, the plain line starts at `pl-[84px]`.

Status notes (`MessageView.tsx:266-277`, `statusWords` strings unchanged):

```tsx
const cut = message.finish === "length" || message.finish === "repetition_detected" || message.status === "interrupted";
className={
  message.status === "failed" ? "notice notice--error max-w-measure"
  : cut ? "notice notice--warn max-w-measure"
  : "text-sm text-muted"          // a plain "Stopped." by the person
}
```

with a leading `aria-hidden` glyph: `CircleAlert` failed, `Scissors` a length stop, `TriangleAlert` repetition or interrupted. The cap note was the quietest text under the answer (14 px muted, 27 px below the cut line, 15 px above the footer); now an amber box with the cause's words, 12 px below the text.

### 7.6 Tool calls (`ToolCalls.tsx`)

State is a tone, not a sentence. Beside `labels` add `tone` (pending, signing, uncertain `text-warn`; running `text-info`; done `text-ok`; failed `text-error`; declined, cancelled `text-muted`) and `edge` (pending, signing, uncertain `border-warn-line`; failed `border-error-line`; a pending call the site's rules allow, `ask === false`, is not waiting on you and stays muted).

| Line | Element | Becomes |
|---|---|---|
| 189-192 | card | `rounded-plexus border p-3 text-sm ${edge[call.status] ?? "border-line"}`, `max-w-measure` on the section |
| 193 | h3 | `flex items-center gap-1.5 font-semibold` with `<Wrench size={14} aria-hidden className="text-apricot" />` |
| 196 | status | `mt-0.5 flex items-center gap-1.5 ${tone[call.status]}` plus a leading `<span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-current">` (pulses while running); `role="status"` and every string unchanged |
| 207, 220 | summaries | `text-muted hover:text-fg` |
| 214, 224 | `pre` | `mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-plexus border border-line bg-soft p-2 font-mono text-[0.8125rem] leading-5` |
| 92 | signature box | keeps `border-accent`: it asks something of you |
| 115, 246 | primary | `btn btn-primary` |
| 126, 136, 255 | Sign with passkey, Do not sign, Decline | `btn` |
| 268 | safety sentence | `text-xs text-muted` stays; it appears once per tool section |

### 7.7 Composer (`Composer.tsx`)

| Line | Element | Becomes |
|---|---|---|
| 279 | container | `border-t bg-panel px-4 pb-4 pt-3` (+ the dragging ring as now) |
| 282 | inner | `mx-auto flex max-w-3xl flex-col gap-3` |
| 315-344 | textarea | `control block w-full resize-none overflow-y-auto px-3 py-2.5 text-read leading-[1.55] min-h-[4.5rem]`; `rows` 2; the height floor in rem, not 80 px (below) |
| 345 | hint | `text-xs text-muted max-sm:sr-only` (still the `aria-describedby` text; phones have no Shift+Enter); 4 px under the field: wrap textarea and hint in `<div className="flex flex-col gap-1">` |
| 353-431 | controls | two groups in one wrapping row, so a label never strands from its switch: group one `flex min-w-0 flex-[1_1_16rem] items-center gap-3` (Attach, Model label and select; the 16 rem basis is what makes the group wrap: a basis of 0 would let it shrink to nothing instead), group two `ml-auto flex items-center gap-3` (Tools label, search switch, Send or Stop). Measured with these classes: at 768 px the two fit one row exactly (417 + 12 + 339); at 640 px still one row, with the select squeezed to 141 px; at 358 px two rows (80 px; 96 on touch), no overflow. The wrap point is about 607 px |
| 367 | Attach | `btn` |
| 378 | select | `control control--sm min-w-0 max-w-full sm:max-w-72` (the `max-w-52` cap outgrew a phone at 125 to 150% text) |
| 371 | model label | `flex min-w-0 max-w-full flex-1 items-center gap-1` |
| 390 | Tools label | `inline-flex items-center gap-1.5 text-muted` with `<Toolbox size={14} aria-hidden className="text-accent" />`, text exactly `Toolbox · Tools:` |
| 410, 426 | Stop, Send | `btn` and `btn btn-primary`, the same height and border so the composer is the same height idle and while an answer runs (it was 177 and 179) |
| 433 | search-off note | `flex items-start gap-1.5 text-sm text-muted` with `Info` |
| 437-441 | problem | `notice notice--error` (role, text kept) |

`useLayoutEffect` (125-130): `const rem = parseFloat(getComputedStyle(document.documentElement).fontSize); field.style.height = Math.min(15 * rem, Math.max(4.5 * rem, field.scrollHeight)) + "px";` so the box follows the person's text size. `autoFocus` on the textarea: `autoFocus={!window.matchMedia("(pointer: coarse)").matches}` so opening a chat on a phone does not raise the keyboard over it (A11Y-19).

### 7.8 Smaller files

`CopyButton.tsx:49` `act` (and "Copied" `text-ok`); `Composer.tsx:303` remove X `icon-btn`; `Mascot` unchanged. `MessageView` `Attachment` chips keep `max-w-xs` and `truncate` (`Polish.test` asserts both).

---

## 8. The other screens

### 8.1 Shared patterns

All in one `@layer components` block, so any utility (`border-error-line`, `text-xs`, `w-24`) still wins. Cards, forms, notices, badges, page headings and states each have one recipe; a screen takes the class and nothing else.

```css
/* styles.css §8: shared patterns */
@layer components {
  /* Buttons: four kinds. One primary per visible form. */
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.375rem;
    min-height: 2.25rem;
    padding: 0.375rem 0.875rem;
    border: 1px solid var(--border-control);
    border-radius: var(--radius);
    background: var(--panel-soft);
    color: var(--foreground);
    font-size: 0.875rem;
    line-height: 1.25rem;
    font-weight: 600;
    white-space: nowrap;
    text-decoration: none;
    transition:
      background-color 0.12s,
      border-color 0.12s;
  }
  .btn:disabled,
  .btn[aria-disabled="true"] {
    border-color: var(--border);
    background: transparent;
    color: var(--faint);
    opacity: 1;
  }
  .btn-primary {
    border-color: var(--accent-left);
    background: var(--accent-left);
    color: var(--on-accent-left);
  }
  .btn-primary:disabled {
    border-color: var(--border);
    background: var(--panel-soft);
    color: var(--faint);
  }
  .btn-primary:not(:disabled):active {
    border-color: var(--accent-active);
    background: var(--accent-active);
  }
  .btn-danger {
    border-color: var(--danger-edge);
    background: var(--status-error-bg);
    color: var(--status-error-fg);
  }
  .btn-quiet {
    min-height: 2rem;
    padding: 0.25rem 0.5rem;
    border-color: transparent;
    background: transparent;
    color: var(--link);
    font-weight: 500;
  }
  .btn-quiet.btn-danger {
    border-color: transparent;
    background: transparent;
    color: var(--status-error-fg);
  }
  @media (hover: hover) {
    .btn:not(:disabled):hover {
      border-color: var(--accent-left);
      background: var(--panel-hover);
    }
    .btn-primary:not(:disabled):hover {
      border-color: var(--accent-hover);
      background: var(--accent-hover);
    }
    .btn-danger:not(:disabled):hover {
      border-color: var(--status-error-fg);
      background: var(--status-error-bg);
    }
    .btn-quiet:not(:disabled):hover {
      border-color: transparent;
      background: var(--panel-hover);
    }
    .btn-quiet.btn-danger:not(:disabled):hover {
      background: var(--status-error-bg);
    }
  }

  /* Icon buttons (header), and the quiet actions under a message. */
  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 2rem;
    min-height: 2rem;
    border-radius: var(--radius);
    color: var(--muted);
  }
  .icon-btn[aria-expanded="true"] {
    background: var(--panel-hover);
    color: var(--link);
  }
  .act {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    min-height: 1.75rem;
    padding: 0.25rem 0.5rem;
    border-radius: var(--radius);
  }
  @media (hover: hover) {
    .icon-btn:hover,
    .act:not(:disabled):hover {
      background: var(--panel-hover);
      color: var(--foreground);
    }
    .icon-btn--danger:hover {
      background: var(--status-error-bg);
      color: var(--status-error-fg);
    }
  }
  /* Reveal on hover, on focus, and always for the newest message and on touch. */
  .msg-actions {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    opacity: 0;
    transition: opacity 0.12s;
  }
  .msg:hover .msg-actions,
  .msg:focus-within .msg-actions,
  .msg:last-child .msg-actions {
    opacity: 1;
  }
  @media (hover: none), (pointer: coarse) {
    .msg-actions {
      opacity: 1;
    }
  }

  /* Fields. The edge is 3:1; focus turns it blue and the ring hugs it. */
  .control {
    min-width: 0;
    min-height: 2.25rem;
    padding: 0.375rem 0.625rem;
    border: 1px solid var(--border-control);
    border-radius: var(--radius);
    background: var(--panel-soft);
    color: var(--foreground);
    font-size: 0.875rem;
    line-height: 1.25rem;
  }
  textarea.control {
    min-height: 5rem;
    padding-block: 0.5rem;
    line-height: 1.5;
  }
  .control--sm {
    min-height: 2rem;
    padding-block: 0.25rem;
  }
  .control:focus-visible {
    border-color: var(--accent-left);
    outline-offset: 0;
  }
  .control[aria-invalid="true"] {
    border-color: var(--danger-edge);
  }
  .control:disabled {
    border-color: var(--border);
    color: var(--faint);
  }
  .field {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 0.375rem;
  }
  .field-label {
    font-size: 0.875rem;
    line-height: 1.25rem;
    font-weight: 500;
  }
  .field-label small {
    color: var(--muted);
    font-weight: 400;
  }
  .help {
    max-width: 34em;
    color: var(--muted);
    font-size: 0.875rem;
    line-height: 1.375rem;
    text-wrap: pretty;
  }
  .help strong {
    color: var(--foreground);
    font-weight: 600;
  }
  .check {
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
    min-height: 2rem;
    padding-block: 0.25rem;
    font-size: 0.875rem;
    line-height: 1.25rem;
  }
  .check > input {
    flex: none;
    width: 1rem;
    height: 1rem;
    margin-top: 0.125rem;
  }

  /* Notices: a rail, a tint, a glyph, a title, words. */
  .notice {
    --n-fg: var(--status-info-fg);
    --n-bg: var(--status-info-bg);
    --n-line: var(--status-info-border);
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
    padding: 0.625rem 0.875rem;
    border: 1px solid var(--n-line);
    border-left: 3px solid var(--n-fg);
    border-radius: var(--radius);
    background: var(--n-bg);
    color: var(--foreground);
    font-size: 0.875rem;
    line-height: 1.375rem;
  }
  .notice > svg {
    flex: none;
    margin-top: 0.1875rem;
    color: var(--n-fg);
  }
  .notice-title {
    display: block;
    color: var(--n-fg);
    font-weight: 600;
  }
  .notice--warn {
    --n-fg: var(--status-warn-fg);
    --n-bg: var(--status-warn-bg);
    --n-line: var(--status-warn-border);
  }
  .notice--error {
    --n-fg: var(--status-error-fg);
    --n-bg: var(--status-error-bg);
    --n-line: var(--status-error-border);
  }
  .notice--ok {
    --n-fg: var(--status-ok-fg);
    --n-bg: var(--status-ok-bg);
    --n-line: var(--status-ok-border);
  }
  .notice--bar {
    padding-inline: 1rem;
    border-width: 0 0 1px;
    border-radius: 0;
  }
  .notice--float {
    background-color: var(--panel);
    background-image: linear-gradient(var(--n-bg), var(--n-bg));
  }
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-height: 1.5rem;
    padding: 0 0.625rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--muted);
    font-size: 0.75rem;
    line-height: 1rem;
    font-weight: 600;
    white-space: nowrap;
  }
  .badge--ok {
    border-color: var(--status-ok-border);
    background: var(--status-ok-bg);
    color: var(--status-ok-fg);
  }
  .badge--warn {
    border-color: var(--status-warn-border);
    background: var(--status-warn-bg);
    color: var(--status-warn-fg);
  }

  /* Pages: one frame, one set of heading levels, one card. */
  .page {
    min-height: 0;
    flex: 1 1 0%;
    overflow-y: auto;
    padding: 1.5rem 1rem 3rem;
  }
  .page-col {
    display: flex;
    flex-direction: column;
    gap: 2rem;
    width: 100%;
    max-width: 48rem;
    margin-inline: auto;
  }
  .page-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }
  .title-page {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    font-size: 1.25rem;
    line-height: 1.3;
    font-weight: 600;
    letter-spacing: -0.01em;
  }
  .title-page > svg {
    flex: none;
    color: var(--accent-left);
  }
  .title-section {
    position: relative;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border);
    font-size: 1rem;
    line-height: 1.5;
    font-weight: 600;
  }
  .title-section::after {
    content: "";
    position: absolute;
    inset-inline-start: 0;
    bottom: -1px;
    width: 2.5rem;
    height: 2px;
    background: var(--accent-right);
  }
  .title-card {
    font-size: 1rem;
    line-height: 1.5;
    font-weight: 600;
  }
  .title-sub {
    font-size: 0.875rem;
    line-height: 1.25rem;
    font-weight: 600;
  }
  .section {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .subsection {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid var(--border);
    border-radius: calc(var(--radius) + 2px);
    background: var(--panel);
  }
  .card--add {
    border-style: dashed;
    background: transparent;
  }
  .empty {
    padding: 0.75rem 1rem;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    color: var(--muted);
    font-size: 0.875rem;
    line-height: 1.25rem;
  }
  .facts {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 0.25rem 1rem;
    font-size: 0.875rem;
    line-height: 1.25rem;
  }
  .facts dt {
    color: var(--muted);
  }
  .facts dd {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .keys {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    align-items: center;
    gap: 0.5rem 1.25rem;
    font-size: 0.875rem;
  }
  .keys dt {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
  }
  .link {
    color: var(--link);
    text-decoration: underline;
    text-decoration-thickness: 1px;
    text-underline-offset: 0.18em;
  }
  @media (hover: hover) {
    .link:hover {
      color: var(--link-hover);
      text-decoration-thickness: 2px;
    }
  }

  /* Tabs (Media), nav tabs (top bar). The current one has a real 2 px
     underline; the others have none, so nothing wobbles and forced colors
     does not paint a transparent border. */
  .tabs {
    display: flex;
    gap: 0.25rem;
    border-bottom: 1px solid var(--border);
  }
  .tab {
    min-height: 2.5rem;
    margin-bottom: -1px;
    padding: 0.5rem 0.75rem calc(0.5rem + 2px);
    color: var(--muted);
    font-size: 0.875rem;
    line-height: 1.25rem;
  }
  .tab[aria-selected="true"] {
    padding-bottom: 0.5rem;
    border-bottom: 2px solid var(--accent-left);
    color: var(--foreground);
    font-weight: 500;
  }
  .nav-tab {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    min-height: 1.75rem;
    padding: 0.25rem 0.625rem calc(0.25rem + 2px);
    border-radius: var(--radius);
    color: var(--foreground);
    font-size: 0.875rem;
    line-height: 1.25rem;
  }
  .nav-tab > svg {
    color: var(--muted);
  }
  .nav-tab[aria-current="page"] {
    padding-bottom: 0.25rem;
    border-bottom: 2px solid var(--accent-left);
    background: var(--panel-soft);
    font-weight: 600;
  }
  .nav-tab[aria-current="page"] > svg {
    color: var(--accent-left);
  }
  @media (hover: hover) {
    .tab:not([aria-selected="true"]):hover,
    .nav-tab:hover {
      background: var(--panel-hover);
      color: var(--foreground);
    }
  }
  /* A phone keeps the top bar to one row: no icons, tighter padding. */
  @media (max-width: 40rem) {
    .nav-tab {
      padding-inline: 0.5rem;
    }
    .nav-tab > svg {
      display: none;
    }
  }

  /* The chat's settings: the fields scroll, Save and Close do not. */
  .sheet {
    display: flex;
    flex-direction: column;
    max-height: clamp(8rem, 40dvh, 28rem);
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  .sheet-body {
    min-height: 0;
    flex: 1 1 auto;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 1rem;
  }
  .sheet-foot {
    flex: none;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--border);
  }

  /* Reasoning and the draft: the console's dashed box for derived text. */
  .reasoning-body {
    max-height: 20rem;
    overflow-y: auto;
    padding: 0.5rem 0.75rem;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    line-height: 1.6;
  }

  /* A working answer. */
  .working-dots {
    display: inline-flex;
    gap: 3px;
  }
  .working-dots > span {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.35;
    animation: working-pulse 1.2s ease-in-out infinite;
  }
  .working-dots > span:nth-child(2) {
    animation-delay: 0.2s;
  }
  .working-dots > span:nth-child(3) {
    animation-delay: 0.4s;
  }
  @keyframes working-pulse {
    0%,
    80%,
    100% {
      opacity: 0.35;
    }
    40% {
      opacity: 1;
    }
  }
}
```

**Adoption rules.** One primary button per visible form; a form's submit is left-aligned under its fields; a sheet or confirm footer is right-aligned with the safe choice first and focused (Escape cancels). Help sits below its control, joined by `aria-describedby`, at most 34 em wide. A consequence that can hurt (access, spending, running as you) is a `notice notice--warn`, never muted help. A state that matters to the person is a badge or a notice, never a grey sentence. Status words in the page are `text-ok`, `text-warn`, `text-error`, `text-info` only inside a status. A `<button>` with no class is a defect (ten exist today: Back to chat in Tools and Media, Keep it, Remove, Check connection, and others read as plain text): give it `btn` or `btn btn-quiet`. Every `text-accent` text action (24 sites) becomes `link` (an anchor) or `btn btn-quiet` (a button), so text links take the lighter `--link`; `text-accent` stays only on decorative icons.

### 8.2 Screen by screen

| Screen | File and lines | Changes |
|---|---|---|
| Chat settings | `ChatSettings.tsx:102-203` | A sheet: `<section className="sheet">` with `.sheet-body` (fields) and `.sheet-foot` (Close `btn btn-quiet`, Save `btn btn-primary`, the problem `notice notice--error mr-auto`, "Saved. The next answer uses these." `text-ok mr-auto`, `role="status"` kept). Three groups, each opened by an `eyebrow`: **Answers** (Instructions, Temperature, Top-p, Longest answer, Repeated response protection), **Toolbox · Tools**, **Folders**, separated by `.subsection`. Every field is `field` / `field-label` / `control` / `help` with `aria-describedby` (the Top-p, Temperature and Longest answer descriptions that the tests read keep their text). Tool and folder lists use `.check` rows with the suffix (` · Local, owner only`, ` · Read only`) in a muted span, the visible text unchanged. Below 48 rem the sheet is `fixed inset-0 z-30` so the composer is never pushed off (§9). Before: the panel took 540 of 900 px, left 101 px of conversation, and hid Save under its own scroll. |
| Tools | `Tools.tsx:44-278` | `<section className="page"><div className="page-col">`; head `.page-head` with `<h1 className="title-page"><Wrench size={20} aria-hidden />Toolbox · Tools</h1>` and Back to chat as `btn` with `ArrowLeft`; one intro paragraph (`help`), merging the two; **Tool servers (MCP)** first as a `section` with `title-section` (cards, or `.empty` "No tool servers yet."), then the add forms as `card card--add`, then **Folders** with its own `title-section`. Cards use `.facts` and badges (Local server / Owner only / "can change this machine's settings" `badge--warn`). A check's result is a `notice notice--ok` ("Available tools: ...", the test's text) or `notice notice--error` with "Could not reach {server}" and the observed cause as a `role="alert"`; "Checking..." stays a muted status. Remove / Keep it / Remove connection become the confirm row (below). |
| Folders | `Folders.tsx` (45, 54-64, 82, 137, 178, 190-210, 221-237, 279) | `title-section` and `title-card`; "Grant an existing folder" is `title-card` (it was `font-medium` at 14 px: a regular line); `.control`; "they are not automatically undone" (233-237) becomes `notice notice--warn`; the `data.reason` becomes `.help` or a notice; "Remove access" and "Keep access" the confirm row. |
| Local tool form | `LocalToolForm.tsx:6, 74-143` | `.control` replaces `inputClass`; **"Only add programs you trust. They run with Workbench's file access, including everyone's chats and the app's credentials." (79-83) becomes `notice notice--warn` titled "Runs with Workbench's access"**: it is the most consequential sentence in the app and was muted help. |
| Media (Bins) | `Media.tsx:215-250, 595-796`; `AudioForms.tsx`; `VideoForm.tsx` | `.page`; header like Tools; tabs `.tabs` / `.tab` (the selected one no longer sits 1 px higher: it had the only border); fields `field` / `control` (the 20 `bg-surface` fields were transparent: the alias in §3b fixes them at once, the class swap makes the type consistent: the 16 px Model/prompt fields inside 14 px labels become 14 px; 16 on touch); the three copies of the primary button string become `btn btn-primary`; "Reference images" and "Recording" get `role="group"` with `aria-labelledby`; "Checked by ... when sent" is the field's `help`; the video price is a `notice notice--warn`; invalid fields keep `border-error-line` (tests) and add `border-2`, `aria-invalid` and `aria-describedby` to the alert, whose text starts with the field's label. Card actions: `btn btn-quiet`, Delete `btn btn-quiet btn-danger ml-auto`, the confirm row for "Delete this result?". |
| Job sites | `JobSites.tsx:72-1117`; `Workspaces.tsx`; `SiteLinkNote.tsx` | `.page` (the scroller was its own 736 px column with a scrollbar floating at x=1248); `title-page` with `Laptop`; Back to chat `btn`; a site is a `card` with `title-card` and a `badge--ok` Online / `badge--warn` Offline plus "last contact" as meta; Passkeys, Local server, Workspaces and Sharing are `.subsection` blocks with `title-sub` instead of nested bordered boxes (a box only for repeated rows); the invite becomes an ordered list (the machine must have Eugene joined; run the command within 15 minutes; it asks for your Eugene password there: that phrase stays, `JobSites.test.tsx:192`), the commands `pre` at 13 px in a bordered block with Copy beside it; approval, save and make-the-command are `btn btn-primary` (one per block), destructive `btn btn-quiet btn-danger`; DecisionSelect `grid grid-cols-[11rem_minmax(0,1fr)]` with `control control--sm max-w-xs`, so selects line up; "Not saved yet." `badge badge--warn` with `role="status"`; "It waits on {label} until you approve it with your own key there" a `notice` titled "Needs your key"; the command rule's warning a `notice notice--warn` at 14 px; the audit list a three-column grid (time, who and what, verdict `text-ok` allowed / `text-error` refused). The bare "Not Found" becomes "Could not read job sites" plus the cause. |
| Shortcuts | `App.tsx:298-315` | §7.3. |
| Sign in | `SignIn.tsx:13-56` | h1 `text-2xl`; the lede in two lines (`text-balance`): "Chat with the models your Eugene install serves." and `text-sm text-muted` "Sign in with your Eugene account, or with Eugene's passphrase if you are its owner."; notices `notice` or `notice notice--warn` at 14 px (**"You signed out." is an acknowledgement: `notice` with `role="status"`; "Your sign-in ended" stays `notice--warn`**); Sign in `btn btn-primary min-h-11 px-5 text-base` (`data-testid="sign-in"` kept); Check again `btn`. |

The confirm row, one component for the five different "are you sure" strips (B2):

```tsx
<div role="group" aria-label="Remove Shared search?" className="notice notice--error flex-col">
  <p>Remove Shared search? Pending calls will not run. Saved server files will remain.</p>
  <div className="flex flex-wrap gap-2">
    <button autoFocus className="btn">Keep it</button>
    <button className="btn btn-danger">Remove connection</button>
  </div>
</div>
```

Sentence on its own line, safe choice first and focused, danger second, Escape cancels; every existing `aria-label` is kept (`Tools.test.tsx` names them). Whether the three removals that act at once (a workspace, "Remove my link", "Remove link") should ask first is Troy's call; a removed workspace needs his key to come back, so asking is cheap.

---

## 9. Accessibility

```css
/* styles.css §9: preferences, and the bits that need a query */
.scene-in {
  animation: scene-in 240ms ease-out;
}
@keyframes scene-in {
  from {
    opacity: 0;
  }
}

/* Windows High Contrast: fills are dropped, so every meaning rides on a
   border, an outline or text. The running dot is the one thing that was only a
   background. */
@media (forced-colors: active) {
  .run-dot {
    forced-color-adjust: none;
    background-color: Highlight;
  }
}

/* Increase contrast (macOS, iOS, Windows contrast themes): every text tier to 7:1. */
@media (prefers-contrast: more) and (prefers-color-scheme: dark) {
  :root {
    --foreground: #ffffff;
    --foreground-strong: #ffffff;
    --muted: #d0d4d8;
    --faint: #c4c9ce;
    --heading: #f0d5c0;
    --accent-right: #e0ab82;
    --accent-right-text: #e0ab82;
    --accent-left: #a9d0e8;
    --link: #b4d6ec;
    --link-hover: #cfe5f3;
    --border: #939ba5;
    --border-hover: #aab2bb;
    --border-control: #aab2bb;
    --rule: #939ba5;
    --status-warn-fg: #ecc08a;
    --status-error-fg: #f0b4ad;
    --status-ok-fg: #a9d7b9;
  }
}
@media (prefers-contrast: more) and (prefers-color-scheme: light) {
  :root {
    --foreground: #000000;
    --foreground-strong: #000000;
    --muted: #44444c;
    --faint: #4a4a52;
    --heading: #6f2a4d;
    --accent-right: #a3326b;
    --accent-right-text: #a3326b;
    --accent-left: #1a3fb8;
    --link: #1a3fb8;
    --link-hover: #1a3fb8;
    --border: #62626c;
    --border-hover: #4a4a52;
    --border-control: #4a4a52;
    --rule: #62626c;
    --status-warn-fg: #6a3406;
    --status-error-fg: #7d1230;
    --status-ok-fg: #05523d;
  }
}
@media (prefers-contrast: more) {
  :focus-visible {
    outline-width: 3px;
  }
}

/* Touch: 44 px targets, and no field under 16 px (iOS Safari zooms the page
   into one). The composer is already 17 px (.text-read). */
@media (pointer: coarse) {
  .btn,
  .control:not(textarea),
  .tab,
  .check {
    min-height: 2.75rem;
  }
  .btn-quiet,
  .act,
  .icon-btn,
  .nav-tab {
    min-height: 2.75rem;
    min-width: 2.75rem;
  }
  input:not([type="checkbox"], [type="radio"], [type="file"]):not(.text-read),
  select:not(.text-read),
  textarea:not(.text-read) {
    font-size: max(1rem, 16px);
  }
}
@media (hover: none) {
  .needs-keyboard {
    display: none;
  }
}

/* A short window (a landscape phone, 200% zoom): keep a third of it for the
   conversation and Send on screen. */
@media (max-height: 32rem) {
  #composer-hint {
    display: none;
  }
  [data-testid="composer-area"] {
    padding-block: 0.5rem;
  }
  #message-composer {
    height: 3rem !important; /* beats the inline height the composer sets from its text */
    min-height: 0;
  }
  .sheet {
    max-height: clamp(6rem, 30dvh, 28rem);
  }
}
@media (max-width: 47.99rem) {
  .sheet {
    position: fixed;
    inset: 0;
    z-index: 30;
    max-height: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  * {
    animation: none !important;
    transition: none !important;
  }
}
```

| Concern | What is done | Source |
|---|---|---|
| **Forced colors** | Borders, not fills, carry meaning: bubble (real 1 px edge), current chat (3 px left border), buttons (1 px border), badges, notices, inline code, the quote bar, the task box. The only fill-only thing, the running dot, is `Highlight`. No `border-transparent` reserves space (forced colors paints it): the tabs and the current chat use padding compensation instead. | A11Y-04 |
| **Increase contrast** | Tokens lifted as above. | A11Y-15 |
| **Focus** | The 2 px ring stays (5.35 to 7.78:1). It lives in `@layer base`, so a field hugs it (`outline-offset: 0`, blue edge) and a scroller can pull it inside (`outline-offset: -2px`). The conversation is `role="region"`, `tabIndex={0}`, named, so PageUp and arrows scroll from the keyboard (before: 700 to 700 from the composer; 700 to 172 once inside). A "Skip to the conversation" button is the first stop (`sr-only focus:not-sr-only`), a button not an `href` because the popstate handler closes Tools, Media and Job sites on any history event. Opening Tools, Media or Job sites moves focus to that view's h1 (`id="view-heading" tabIndex={-1}`) and sets `document.title` ("Toolbox · Tools · Workbench"); today focus drops to the body and the title does not change. | A11Y-05, -16, SUR-25 |
| **Scrollers and tables** | An overflowing code block or table is a keyboard stop with a name ("Code, scrolls sideways" / "Table"), applied only while it overflows (a `ResizeObserver` guarded with `typeof ResizeObserver !== "undefined"` for jsdom). The table keeps `display: table` inside its wrapper. | A11Y-10 |
| **Long strings** | `overflow-wrap: break-word` on the body plus `break-words` on the reasoning body: one 400-character token made the transcript 3,878 px wide; after, 1152 px at desk and 390 on a phone. | A11Y-01 |
| **Zoom and reflow** | rem everywhere (the composer's JS height too); the model picker is `max-w-full` (it was 13 rem: at 125 to 150% text a phone scrolled sideways, page 400 to 534 px); settings is a sheet (below). At 200% (720 x 450), measured before: the composer was 49% of the window, and an open settings panel left 32 px of transcript with Send off screen. The audit's patch used the three levers this spec uses (hint hidden, a 3 rem field, settings capped at 30dvh) and measured a 147 px composer and 86 px of transcript with settings open and Send in view; this spec's composer differs (two groups), so the check asserts the outcome (13.1), not those pixels. | A11Y-02, -07, -20 |
| **Phone** | 44 px targets under `pointer: coarse`; 16 px fields; the hint hidden (kept as the description); the top bar one row (52 px); the chrome falls from 46% of a 390 x 844 screen (386 px) to about 38% (317 px by arithmetic from the DOM sizes: bar 52, header 56 with 44 px icon buttons, composer about 209 with two 44 px control rows; the audits' 30% assumed 32 px controls and is not reachable with 44 px targets) and the 37 px "Jump to latest" band is gone; opening a chat does not raise the keyboard; the keyboard-shortcuts button is hidden on touch. | A11Y-13, SP-18, SUR-19 |
| **Live regions** | The progress line's time, count and speed are `aria-hidden` (a polite region that changed every second spoke 11 times in 9 s). One `aria-live` announcer, a div and not `role="status"` (the tests use `getByRole("status")` and expect one), says only a phase change: "Waiting for the model.", "Thinking.", "Writing the answer.", "Answer finished.", "Answer finished at its length limit.", "Answer stopped.", "Answer interrupted."; a failure is already `role="alert"`. `aria-busy` on a running answer. | A11Y-06, SUR-08 |
| **Forms** | An invalid field keeps `border-error-line` and gains `border-2`, `aria-invalid` and `aria-describedby` to the alert, which begins with the field's label (colour was 1.55:1 apart and alone). | A11Y-14 |
| **Information in a tooltip** | The developer-mode sentence and the search hint are visible text, not only a `title`. | A11Y-17 |
| **Direction** | An explicit `dir` from each block's first strong character (section 6.4) and logical properties; `lang` for CJK is later. | A11Y-11 |
| **Text spacing (1.4.12)** | Verified: no clipping under line-height 1.5, paragraph spacing 2x, letter-spacing .12em, word-spacing .16em. | audit |
| **Motion** | The global reduced-motion rule stays; the scene is already swapped for the still mascot; new animations (dots, pulse) are covered by it. | |
| **Colour never alone** | Links are underlined; every status has a glyph and words; the current page has a rail or underline plus weight; disabled has the attribute plus a different look. | WCAG 1.4.1 |
| **Targets** | Every control is 24 x 24 or more (28 under messages, 32 in headers); 44 on touch. | WCAG 2.5.8 |

### 9.1 The two small helpers

```ts
// lib/words.ts. "Thinking · 1 s" is said once as "Thinking"; the tail is what ticks, and is aria-hidden.
export function splitWorking(line: string): { say: string; tail: string } {
  const at = line.search(/ · |: (?=[0-9])/);
  return at < 0 ? { say: line, tail: "" } : { say: line.slice(0, at), tail: line.slice(at) };
}

// What a screen reader is told when the state of the newest answer changes. A failure is already role="alert".
export function announce(m?: Message): string {
  if (!m || m.role !== "assistant") return "";
  switch (m.status) {
    case "running":
      return m.content ? "Writing the answer." : m.reasoning ? "Thinking." : "Waiting for the model.";
    case "done":
      return m.finish === "length" ? "Answer finished at its length limit." : "Answer finished.";
    case "stopped":
      return "Answer stopped.";
    case "interrupted":
      return "Answer interrupted.";
    default:
      return "";
  }
}
```

In `ChatView`, next to the conversation: `<div aria-live="polite" aria-atomic="true" className="sr-only" data-testid="announcer">{announce(messages[messages.length - 1])}</div>`. It is a div with `aria-live`, not `role="status"`, because several tests call `getByRole("status")` and expect exactly one.

---

## 10. Dependencies weighed

| Item | Recommendation | Bundle | CSP | Maintenance |
|---|---|---|---|---|
| **`@fontsource-variable/ibm-plex-sans` 5.3.0** (normal and italic, Latin) | **Adopt, R1.** | 45.7 + 50.2 = 95.9 KB against 46.9 KB for the two Sans faces today (+49 KB, with weights 100 to 700 and a real italic); five static faces would be 122 KB. 22 font files in the wheel (34 today, 70 static). | `font-src 'self'`: files are emitted (`assetsInlineLimit: 0`). | Replaces `@fontsource/ibm-plex-sans`. Mono has no variable build and stays static. The font gate must understand a range. |
| **`rehype-highlight` 7.0.2 + lowlight (`common` + powershell + dockerfile)** | **Adopt, R5.** Every chat UI puts its one big splash of colour here, and a local model mostly writes code. Static import. | +45 to 50 KB gz on 159.8 KB gz (+28 to 34%); 2.0 ms for 300 lines, 6.2 ms for 990 per streamed chunk. A curated 21-language set saves only 10 KB. | Tokens are React elements: 0 `securitypolicyviolation` events and 0 inline styles (measured under the real policy). | Class names are stable; add a language only on request. `detect: false` so an unlabelled fence is never guessed. Rejected: Shiki (the default engine is WebAssembly, 230 KB gz, refused by `script-src 'self'`; the JS engine works but adds 9 to 16 KB per grammar), starry-night (WebAssembly), prism-react-renderer (33 KB gz but ~30 fixed languages and JS needed for light and dark), sugar-high (JS only), highlight.js as an HTML string (needs `dangerouslySetInnerHTML`). |
| **KaTeX 0.19** | **Defer.** Raw `$E=mc^2$` is legible; formulas are rare in this audience. | ~140 KB gz lazy chunk (katex 77 + parse5 62 + remark-math 2.6), 3.5 KB CSS, 260 KB woff2 on demand | `rehype-katex` as shipped fires 33 `style-src-attr` violations for one inline and one display formula (DOMParser, `setAttribute('style')`). The fix is rendering through parse5 (0 violations); loosening `style-src-attr` is a security decision and not recommended. | A `normalizeMath` regex (currency such as `$5 and $10` becomes a formula under remark-math defaults; `\(x\)` and `\[x\]` lose their backslashes in the Markdown parser before any plugin sees them). |
| **GitHub alerts plugin** | **Adopt, R5, optional.** | 0 (15 lines) | none | one test; `[!NOTE]` otherwise shows as a bracketed code word. |
| **HTML allowlist plugin** (`br`, `sub`, `sup`, `kbd`) | **Adopt, R5.** `<br>` in a table cell is the commonest silent corruption. | 0 | No attributes are copied; everything else stays dropped. | Tests, including the existing "raw HTML renders as nothing that runs". |
| **`remark-breaks` 4.0.0** | **Adopt, R5**, taste call 12. | 1.4 KB gz | none | Hard-wrapped prose shows ragged lines. |
| **IBM Plex Serif for answers** (Claude's choice) | **No.** | +40 KB; 5% fewer characters a line | `font-src` fine | A setting is needed first. |
| `@tailwindcss/typography` | **No.** | | | The `.answer` block is smaller than overriding it. |

---

## 11. Taste calls for Troy

Each has the recommended default (what the CSS above does), and one or two alternates so he can picture them. Most are one token, one class or one line.

1. **How much colour in an answer.** Default: *labels and boundaries.* Headings h1 to h3 and bold lead-ins ("Why:", "Risks:") are a pale peach (`#e3c2a8`; plum `#8f2f5e` in light); h1 and h2 sit on a hairline with a short apricot segment; quote bar and table-head rule are apricot. Alternate A, *boundaries only (the console, literally):* headings stay bright white-gray, the segment, hairline, quote bar and table rule carry all the colour (`--heading: var(--foreground-strong)`). Alternate B, *lively:* A plus apricot bullets and numbers and a tinted h4. Variant: a *bolder peach* `#d7b196` (9.17:1) shows more colour, but sits 0.036 from the amber warning text, so a heading and a cut-off note would be near-twins. This is the one call that departs from the console's note that apricot carries nothing else.
2. **Reading size.** Default 17 px / 1.65. Alternate 16 px (as today): 76 to 80 characters a line at 36 rem and 85 at most, so pair it with a 34 rem measure; the answer is 17% taller than today instead of 25%. Alternate 18 px: 65 to 72 characters at 36 rem, 32% taller; widen the measure to 39 rem to get about 77. One token: `--text-read`.
3. **Width.** Default: the 48 rem frame stays; text and its furniture stop at 36 rem, code and tables run to the frame. Alternate 40 rem for everything: one left and right edge, 79 characters of code, but the composer controls wrap to two rows. Alternate "Roomier measure": keep the frame, set `--measure: 40rem`: 76 to 80 characters on average and 85 at most, and the story is 34% taller than today instead of 54%. Alternate "Full": prose uncapped (`--measure: 100%`), 91 to 97 characters a line in the 736 px harness column (more in the app's 768), the story 14% taller and the rich answer 20% (the larger type and the new gaps remain).
4. **Body brightness.** Default: body unchanged, bold and titles one notch brighter. Alternate "softer body": answer text `#dde0e3` in dark (13.68:1) and `#202023` in light (15.58:1) so bold and headings have more headroom; costs some of the margin APCA wants at 17 px.
5. **The rule under h1 and h2.** Default hairline plus 2.5 rem segment (the console's heading hairline plus its LCARS strip). Alternate: the segment *above* the heading, no hairline (12 px more height per heading). Alternate: none.
6. **Weight on dark.** Default 400 / 500 / 600. Alternate: 370 / 460 / 550 on dark only (Claude's own CSS lowers its dark weights about 10%; light-on-dark looks heavier than it is). Free with the variable font; judge it on Troy's Windows and Brave, where I could only measure widths (-0.7%).
7. **The person's bubble.** Default: right-aligned, a quiet steel-blue tint with a hairline, 36 rem max. Alternate: neutral gray (as now; 1.06:1 and invisible in light). Alternate: left-aligned on the answer's edge, so the eye does not cross 464 px between a short question and its answer.
8. **Actions under a message.** Default: Copy, Try again and Edit appear on hover, on keyboard focus, always on touch and always on the newest message; the time, the version arrows and the model stay visible. Alternate: always visible at 13 px.
9. **The top bar.** Default: neutral labels with small icons and a 2 px underline on the page you are on. Alternate: keep three blue links (Troy's "only colour on the page" stays).
10. **Reasoning.** Default: a quiet "> Reasoning" row; open, the text sits in the console's dashed box, 20 rem tall, scrolling. Alternate: a left rail instead of a box; or render it as Markdown (it is shown raw today, with asterisks).
11. **Lists.** Default muted bullets, bold numerals. Alternate warm (apricot) markers.
12. **Single newlines.** Default (R5): a newline in a paragraph is a line break, as most chat apps show it and as the person's own messages already do here. Alternate: strict CommonMark (a model that hard-wraps shows no ragged lines).
13. **Tables.** Default: rules, header fill, apricot 2 px rule under the header. Alternate: zebra rows (`tbody tr:nth-child(even)` at 4.5% of the foreground). Alternate: the full grid as today.
14. **CHATS, answer h5 and h6.** Default: Plex Sans 600, +0.06em. Alternate: Plex Mono 400, +0.08em, as the console's section labels.
15. **Developer mode's colour.** Red today (a test asserts it); the console uses amber. One class and one test line.
16. **Shortcuts panel.** Default: an overlay under the top bar, grouped with `kbd` keys. Alternate: inline as today, capped to the frame.
17. **Light-mode headings.** Default plum `#8f2f5e` (7.36:1). Alternate: ink with a magenta segment, no coloured text.
18. **Where the "answer is being written" line shows.** Default: below the streaming text with three pulsing dots and the token count and speed. Alternate: as now (only before the first token).
19. **The Tools page order.** Default: servers first (with their own title), then the add forms, then Folders. Alternate: as now (Folders first).

---

## 12. Out of scope, or later

- **Math** (section 10) and **footnotes** (the references are dead text today; the fix is a prefix for ids, a `#` branch in the `a` component that scrolls instead of changing the hash, and `section[data-footnotes]` styles: MD-18). *Built 2026-10-13 as [rich-content RC1](workbench-rich-content-roadmap.md#rc1-what-building-found-2026-10-13): KaTeX in a worker, read into React without parse5; footnotes move focus instead of scrolling.*
- **Image chips** (an image an answer names is a link; a dashed chip with an icon and the host would help: MD-19) and the dead-link address (`[config](./x.yaml)` shows "config" with nothing to say it was a link).
- **Heading outline** for screen readers: retag an answer's headings under the message's own and key the styles on `data-md` (A11Y-08). Not now: CSS stays by tag.
- **Settings for display** (BP16, A11Y-12): text size as a percent of the browser's size (never the console's `16px` override, which beats a person's own browser setting), reading width (Narrow 34 rem / Comfortable 36 / Full), theme (System / Dark / Light). Stored per viewer; the label of the default says the effective px. Needs a place (the sidebar footer is reachable on a phone).
- **Speaker labels** per turn (the website's transcript draws them in mono; the website gives the person apricot and the model blue, the reverse of this grammar), the **avatar initial**, a **progress bar** for "Reading your message: 41%", the **composer as one card**, **scroll shadows** on tables, `copy-tex`.
- **Dark-weight tuning**, **Plex Serif** (taste calls 6, section 10), **`lang` for CJK** (Japanese falls back to a Chinese font under `lang="en"`).
- **Not copied from the console** (C19): its 80% bubble, 146-character lines, 9 to 11 px helper text, the 4% watermark behind the chat, the missing `color-scheme`, the focus frame around the content area.
- **Issues to file** on the repos that own them, per the project rule: `ui` (no `color-scheme` set: native boxes and selects are light on the dark theme; `IssuesBadge.tsx:82-88` focuses `#main-content`, so the 2 px frame stays on the whole content area; the Playground answer's flat headings and 146-character measure); `website` (the transcript's speaker colours are the reverse of the grammar here).
- A real iOS Safari run (the 16 px rule and the keyboard behaviour are documented browser behaviour and measured computed sizes, not reproduced here) and VoiceOver on the table wrapper.

---

## 13. Verification

### 13.1 The Playwright reading check (`web/scripts/reading-browser.mjs`)

Today it records numbers and fails only on page errors. Make it assert. The thresholds are for the rich chat at 1440 x 900 and 390 x 844, dark and light; tolerances are the pixel rounding of Chrome. The right-hand column is what Appendix B measured on this draft's CSS in Chrome 155 (Windows), so every threshold has been shown to pass on the design it guards; the rows marked (live) can only be measured on the real app and are the acceptance run's to fill in.

| Check | Assertion | This draft measures |
|---|---|---|
| Paragraph | `.answer p`: font-size 17 px (+-0.5), line-height 28.05 px (+-1), weight 400; width at most 577 px; harness `charsPerLine` 62 to 80 | 17 px / 28.05 px / 400; 576 px; real counts 71.3 average, 75 maximum (rich answer) and 70.3 to 76.5 average, 80 maximum (story) |
| Phone line | `.answer p` average characters per full line 38 to 52 at 390 px | 41 to 46 average on full lines, 48 maximum (a paragraph with inline code reads lower because the chips split the count) |
| Heading ladder | h2 font-size / paragraph font-size at least 1.2; h2 weight 600; h2 margin-top / margin-bottom at least 3; h2 colour equals the computed `--heading`; h2 has a 1 px bottom border and a 40 x 2 px `::after` in `--accent-right` | 1.25; 600; 34.0 / 9.56 = 3.55; `#e3c2a8` and `#8f2f5e`; 1 px `--rule`; 40 x 2 |
| Bold | `strong` weight 600 and colour equals `--foreground-strong`; `.lead-in` colour equals `--heading` | `#f4f6f7` / `#0d0d10`; `#e3c2a8` / `#8f2f5e` |
| Italic and faces | `em` is `italic`, `font-synthesis` is `none`, `document.fonts` holds loaded Plex Sans normal and italic faces; CDP platform fonts for `em` and `strong` are not the roman regular (the variable file names its instances IBM-Plex-Sans-Italic and -SemiBold); code inside an h2 is the Regular mono | all of these |
| Value ladder | among the kinds p, strong, lead-in, h2, h5, a, del, th at least 5 distinct text colours in dark and 4 in light (strong equals body there by design); before: 2 | dark: `#e6e8ea`, `#f4f6f7`, `#e3c2a8`, `#b3b9bf`, `#9cc5df`; light: `#0d0d10`, `#8f2f5e`, `#5a5a63`, `#2a55e6` |
| Contrast | every kind at least 4.5; `::placeholder` against its field at least 4.5; disabled Send at least 4.5 | lowest 5.53 (the language label on the light header); placeholder 5.30 / 4.77; disabled Send 5.30 / 4.77 |
| Controls | `.control` and `.btn` borders against the page at least 3.0 | 4.28 dark, 3.75 light (4.77 / 4.50 for the danger edge) |
| Code | `pre` top minus `.code-head` bottom is 0; `pre` and its `code` 14 px (+-0.5); padding-right 16 px; header 32 px; `.code-lang` text equals the fence's language, `code` when none | 0; 14 px; 16 px; 32 px; `text`, `bash` |
| Tables | no cell word broken across lines (a break after a hyphen is allowed); an unaligned `th` computes `start`, and a header the Markdown aligned (an inline `text-align`) computes `right` or `center`; `.table-wrap` `overflow-x: auto`; at 390 px a 6-column table scrolls inside its wrapper (scrollWidth above clientWidth) and the page does not | no broken words; `start`, `right`, `center`; 680 over 356 inside the wrapper; page 390 |
| Rule | `hr` colour equals `--rule`, not the text colour | `#3a4048` / `#c4c4cc`, 1 px, 29.75 px margins |
| Overflow | `[data-testid=messages]` and the page: `scrollWidth <= clientWidth` at 1440 and 390 with a 300-character token in a paragraph, a list item and a table cell | page 1440 / 390; the answer 736 over 736 and 358 over 358; the token's table scrolls inside its wrapper |
| Rhythm | paragraph to paragraph 15.3 px (+-1); gap above h2 at least 3 times the gap below; tight list gap 5.1, loose 10.2, nested 5.1; the first and last child margins 0 | 15.3; 34.0 / 9.6; 5.09, 10.19, 5.09; 0 and 0 |
| Message actions | the first message's actions are `opacity: 0` and the last's `1`; hovering the first makes it `1`; under touch all are `1` | 0 / 1; 1; 1 / 1 |
| Targets | every button at least 24 x 24; under `isMobile` at least 44 x 44; a field's font-size at least 16 px under touch | `.btn` 36 and 44, `.nav-tab` 30 and 44, `.tab` 40 and 44, `.control` 36 and 44, fields 16 px, textarea keeps 80 |
| No wobble | the current and a non-current `.tab` and `.nav-tab` have the same top and height | 40 and 30, same tops |
| Increase contrast | with `contrast: "more"`, body, h2, link and muted at least 7 against the page; control edges at least 5 | dark: 18.13, 12.93, 11.89, 12.16, edges 8.45; light: 20.13, 9.52, 8.23, 9.25, edges 8.41 |
| Forced colors | with `forcedColors: "active"`, the running dot's background is `Highlight` and fields keep a visible border | `rgb(26, 235, 255)`; border contrast 21 |
| Short window | at 720 x 450 the hint is `display: none`, the composer field is 48 px, and the settings sheet is `position: fixed` over the whole window; (live) `[data-testid=messages]` is at least a third of the window with settings closed and Send is inside the viewport with them open | hint `none`, field 48 px, sheet fixed at 450 px (at 1440 x 900 the sheet is capped at 360 px); the live part is to measure |
| (live) Phone chrome | at 390 x 844 the top bar is one row and top bar + header + composer are at most 40% of the height (before: 46%; about 38% expected) | to measure |

Existing numbers stay in `styles-<scheme>.json` for the record.

### 13.2 What jsdom can pin

jsdom lays nothing out and resolves no `var()`, so it pins source, structure and arithmetic:

- **Font gate** (`fontGate.ts` and `fonts.test.ts`; written and run by the typography audit against the static faces, to be adapted): every weight the markup (`font-*` classes) and the stylesheet (`font-weight:`) ask for must be inside the loaded range (100 to 700 for the variable file), both the normal and the italic file must be imported in `main.tsx`, and `font-synthesis: none` must be set. Today's three-file `main.tsx` fails it with three named problems; removing the italic import fails it with "italic 400 is needed and not loaded".
- **Token gate** (`tokens.test.ts`): parse `styles.css` and compute the pairs in section 3.2 from the hex values (WCAG 2 in about 15 lines), asserting the thresholds (text 4.5; large and headings 3; control edges, focus ring, marks and scrollbar 3). Also: every `--color-*` alias points to a `--` property that exists, and every Tailwind colour utility used in the TSX (`bg|text|border|ring|divide`-name) resolves to an alias, so the next `bg-surface` fails the test instead of rendering nothing.
- **Markdown** (`Markdown.test.tsx`, section 6.3): code header, lead-in, table wrapper and a column's inline `text-align`, task box, quiet; later `<br>` in a cell, sub and sup, an alert's marker consumed, `dir="rtl"` on an Arabic paragraph, list and quote and none on English, Copy returning the source of a highlighted fence, `<img onerror>` and `<script>` still absent.
- **Words** (`lib.test.ts`): `splitWorking` ("Thinking · 1 s" to "Thinking" and " · 1 s", "Reading your message: 25%" to "Reading your message" and ": 25%"); `announce` per status.
- **Components:** the chat row has `aria-current` and a class; the running dot has `animate-pulse`; the conversation is `role="region"` named "Conversation" with `tabindex="0"`; the action rows hold Copy and Try again inside `.msg-actions`; the hint has `max-sm:sr-only` and is still the textarea's description; a cut answer has `notice` and the unchanged words; the developer-mode badge still has `text-error`; invalid fields have `aria-invalid`.
- **Unchanged and still green:** the four class assertions (`text-error` on the mode badge, `border-error-line` on two fields, `text-warn` on heard words), the `closest("details")` and `closest("article")` queries, the single `getByRole("status")` and `getByRole("alert")` tests (no new live region has a role), `words.test.ts` (the two strings stay contiguous in the source).

Sketches of the two gates. The font gate is the typography audit's, written and run against the static faces in a scratch copy and shown failing when the 500 import was removed ("weight 500 is asked for and not loaded"); this is the same gate for the variable pair. The token gate is the arithmetic of section 3.2 restated. Both sketches below were run in Node (not under vitest) against this draft: the token gate's parser reads 34 hex tokens in dark and 34 overrides in light, and all eleven pairs pass in both schemes; the font gate returns nothing for the variable imports and one named problem each for a missing italic import, a stylesheet weight of 800 and `font-synthesis` left on, and four problems for today's static `main.tsx`.

```ts
// web/src/fontGate.ts (read only by tests; the page never imports it)
const WEIGHT_CLASSES: Record<string, number> = {
  "font-thin": 100, "font-extralight": 200, "font-light": 300, "font-normal": 400, "font-medium": 500,
  "font-semibold": 600, "font-bold": 700, "font-extrabold": 800, "font-black": 900,
};

export function loadedFaces(main: string) {
  const normal = /@fontsource-variable\/ibm-plex-sans\/wght\.css/.test(main);
  const italic = /@fontsource-variable\/ibm-plex-sans\/wght-italic\.css/.test(main);
  return { range: normal ? ([100, 700] as const) : null, italic };
}

export function fontProblems(main: string, markup: string, css: string): string[] {
  const { range, italic } = loadedFaces(main);
  const asked = new Set<number>([400]);
  for (const [name, weight] of Object.entries(WEIGHT_CLASSES)) {
    if (new RegExp(`(?<![\\w-])${name}(?![\\w-])`).test(markup)) asked.add(weight);
  }
  for (const m of css.matchAll(/font-weight:\s*(\d{3})\b/g)) asked.add(Number(m[1]));
  const problems: string[] = [];
  for (const weight of [...asked].sort((a, b) => a - b)) {
    if (!range || weight < range[0] || weight > range[1]) problems.push(`weight ${weight} is asked for and not loaded`);
  }
  if (!italic) problems.push("italic is needed (em, and bold inside it) and not loaded");
  if (!/font-synthesis:\s*none/.test(css)) problems.push("font-synthesis is not off, so a missing face would be faked");
  return problems;
}
```

```ts
// web/src/tokens.test.ts
const css = readFileSync(join(import.meta.dirname, "styles.css"), "utf8");
const block = (start: string) => { const from = css.indexOf(start); return css.slice(from, css.indexOf("\n}", from)); };
const tokens = (text: string) => Object.fromEntries([...text.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2]]));
const dark = tokens(block(":root {"));
const light = { ...dark, ...tokens(block("@media (prefers-color-scheme: light) {")) };
const lin = (c: number) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
const lum = (hex: string) => { const [r, g, b] = [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16))); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const contrast = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// [text or mark, surface, minimum]: the rows of section 3.2, one per tier and surface that is used
const PAIRS: [string, string, number][] = [
  ["foreground-strong", "background", 7], ["foreground", "panel-soft", 7], ["muted", "panel-hover", 4.5],
  ["faint", "panel-soft", 4.5], ["heading", "panel-soft", 4.5], ["link", "panel-soft", 4.5],
  ["accent-right-text", "panel-soft", 4.5], ["border-control", "panel-hover", 3],
  ["accent-left", "panel-hover", 3], ["accent-right", "background", 3], ["scrollbar-thumb", "panel-soft", 3],
];
for (const [name, scheme] of [["dark", dark], ["light", light]] as const) {
  it.each(PAIRS)(`${name}: --%s on --%s is at least %d`, (fg, bg, min) => {
    expect(contrast(scheme[fg], scheme[bg])).toBeGreaterThanOrEqual(min);
  });
}
```

### 13.3 Before each push

`npm run typecheck`, `npm run lint`, `npm run format:check` (the stylesheet in section 13.4 is already Prettier-clean at `printWidth: 100`), `npm test`, the secret scan; rebuild the `dist` branch (a merged change that is not rebuilt ships to nobody); then the opt-in browser run of record (`WORKBENCH_PLAYWRIGHT` set; through the test's own `world` fixture and ports, with every ambient `EUGENE_PLEXUS_*` variable cleared, never against the live install) once per slice, with the pictures kept. Sabotage per slice, from a copy: remove `font-weight: 600` from `strong` (the Bold row fails); set `--measure` to `48rem` (the paragraph row fails); delete `.table-wrap` (the table row fails); restore `overflow-wrap: anywhere` (the table words row fails); drop the italic import (the font gate fails); change `--border-control` to `#3a4048` (the token gate and the controls row fail). A check that cannot fail does not count.

### 13.4 Assembling the stylesheet

Concatenate the fences in order: §3a, §3b, §4, §6 (and §6.4 only when its slice lands), §8, §9. The result is about 1,300 lines and compiles under Tailwind 4.3.3 to 30 KB before utilities. Nothing else in `styles.css` survives except `.clipboard-field` and `.scene-in`, which are carried in §4 and §9. The old rules at `styles.css:87-103` and `:117-169` are deleted (`button:disabled`, `.answer pre{margin-top:0}`, the table, and the whole `.answer` block).

### 13.5 Where this could bite

- **Unlayered `.answer` rules beat utilities.** `Markdown.tsx` must drop `pr-20`, `p-3`, `text-sm` and `relative` from the code block, or they sit there dead (harmless, but a reader of the file will believe them).
- **The focus ring now lives in `@layer base`**, so an `outline-none` utility works for the first time. A component that adds it must draw its own focus indicator (the search wrapper does: a blue border and a 1 px ring on `focus-within`).
- **`button:disabled{opacity:.5}` is now in the base layer**, so `disabled:opacity-*` utilities would start to apply. Delete the five of them rather than rely on that.
- **Roles in the chat tree.** Several tests call `getByRole("status")` and `getByRole("alert")` and expect one. Add no new `role="status"` or `role="alert"` there; the announcer is a plain `aria-live` div.
- **Hover-reveal actions** cost discoverability on a laptop with no mouse; keyboard focus, touch and the newest message always show them, and the cost is taste call 8.
- **Height.** Answers are 25% (technical) to 54% (prose) taller at desktop width (section 5.4). That is the largest visible change and it is one token.
- **Browser support.** `text-wrap: pretty` is Chrome 117 and Safari 26 (others ignore it, which is the right fallback); `balance` Chrome 114, Firefox 121, Safari 17.5; `color-mix()` Chrome 111, Firefox 113, Safari 16.2 (the underline colour and the alert tint fall back to the plain default); `:has()` is used only to give a checkbox's label a pointer cursor; `selector()` in `@supports` Chrome 83, Firefox 69, Safari 14.1; `dvh` Chrome 108, Safari 15.4. A real Safari and iOS run is owed.
- **The wheel** carries 22 font files instead of 34 (Vite emits every subset), and one new npm dependency (`@fontsource-variable/ibm-plex-sans`, pinned) replaces one.

---

## Appendix: what became of every audit finding

**Adopted as proposed (or with only the changes named in section 2.1):** T02 T03 T05 T06 T07 T08 T09 T11 T12 T15 T16 T19; COL-02 COL-03 COL-04 COL-05 COL-06 COL-07 COL-08 COL-09 COL-10 COL-13 COL-14 COL-16 COL-17; SP-01 SP-02 SP-03 SP-05 SP-06 SP-07 SP-08 SP-09 SP-10 SP-11 SP-12 SP-13 SP-15 SP-16 SP-17 SP-18 SP-19 SP-21; MD-01 MD-02 MD-04 MD-06 MD-07 MD-08 MD-12 MD-13 MD-15 MD-16 MD-21; SUR-01 SUR-03 SUR-04 SUR-05 SUR-06 SUR-08 SUR-11 SUR-12 SUR-13 SUR-14 SUR-16 SUR-17 SUR-18 SUR-19 SUR-20 SUR-22 SUR-24 SUR-25; F0 F1 F2 F3 F4 F5 B1 B2 B3 B4 B5 S1 S2 S3 S4 S6 P1 P2 P3 P4 P5 P6 P7 P8 P9 P10 P11 P13; C1 C2 C3 C5 C7 C9 C10 C11 C13 C15 C16 C17 C19; BP01 BP02 BP03 BP04 BP05 BP09 BP10 BP11 BP12 BP14 BP15 BP17 BP18 BP20; A11Y-01 A11Y-02 A11Y-03 A11Y-04 A11Y-05 A11Y-06 A11Y-07 A11Y-09 A11Y-10 A11Y-13 A11Y-14 A11Y-15 A11Y-16 A11Y-17 A11Y-18 A11Y-19 A11Y-20 A11Y-21.

**Adopted with a change:** T01 (variable pair, gate adapted); T04 (wrapper); T10 (tint added); T13 (strong tier, body held); T14 (value `#e3c2a8`); T18 (guard); COL-01 (trimmed: no `--surface-code*`, `--surface-selected` merged into `--tint`, `--faint` raised, `--rule` added); COL-11 (see conflicts 1 and 2); COL-12 (code body soft, head hover; reasoning dashed); COL-15 (13 px via T08); SP-14 (two groups, not two rows); SP-20 (sheet with sticky footer; overlay is an alternate); MD-00 (tokens trimmed); MD-03 (italic via the variable file); MD-17 (hover adopted, the dead-link address later); MD-20 (`break-word`; the `bare-url` class dropped: identical in prose, and a long URL in a cell scrolls in its wrapper); MD-14 (a component, not CSS appearance); MD-05 (R5); MD-09 (R5, taste); MD-11 (R5); SUR-02 (variable file); SUR-07 (dashed box, no warm rail); SUR-09 (sizes only); SUR-10 (button, search, chip; success tokens); SUR-21 (the h1 and the sentence); C4 (warm bar, not role bar); C6 (tokens; the pill colour is a taste call); C8 (reasoning and draft); C12 (edge and not the console's blue-tinted button fill); C18 (as `.badge` and `.notice`); BP06 (strong tier); BP07 (warm, not blue); BP08 (36 rem, not 40 em); BP22 (tinted); S5 and S7 (adopted as the default look, taste); A11Y-08 (empty-state h1 only); A11Y-11 (the explicit `dir` helper, `lang` later); B6 (the sentence made visible; the colour a taste call); P12 (icon at a page title, segment under section titles).

**Deferred:** MD-10 (math), MD-18 (footnotes), MD-19 (image chips), MD-24 (reasoning as Markdown: ask), SUR-15 (composer as one card), SUR-23 (avatar), C14 (speaker labels), BP13 (dark weights), BP16 and A11Y-12 (display settings), BP21 (serif), SP-04 (40 rem frame), SP-22 (left-aligned bubble).

**Superseded or no action:** MD-22 (36 rem chosen), SP-23 (17 x 1.65 = 28.05 px is within 0.05 of a whole pixel), T17 and BP19 (nothing to enable; the facts are in section 4), MD-23 (emoji: no defect).

---
