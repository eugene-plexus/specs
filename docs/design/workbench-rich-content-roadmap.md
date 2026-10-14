# Workbench rich content rendering roadmap

**Status: RC1 landed 2026-10-13 (Workbench `b10d2fe`, dist `8934301`, agent `ee3fbe7`; record: [RC1 run](../acceptance/workbench-rich-content-rc1-run.md)); RC2 landed 2026-10-13 (Workbench `36be7ab`, dist `7851a80`, agent `07e14f2`; record: [RC2 run](../acceptance/workbench-rich-content-rc2-run.md)); RC3 landed 2026-10-13 (Workbench `78a3ea2`, dist `3f1e813`, agent `cccb1d8`; record: [RC3 run](../acceptance/workbench-rich-content-rc3-run.md)); RC4 landed 2026-10-14 (Workbench `fd64990`, dist `cf45d79`, agent `f9d4410`; record: [RC4 run](../acceptance/workbench-rich-content-rc4-run.md)); RC5 landed 2026-10-14 (Workbench `de136f1`, dist `53384fc`, agent `0b7f910`; record: [RC5 run](../acceptance/workbench-rich-content-rc5-run.md)). The roadmap is complete.**

Workbench should display equations, diagrams, generated media, structured
results and interactive previews alongside a conversation. Keep the existing
React and Markdown foundation, complete its common rendering features, and
preserve rich results throughout storage and streaming before adding more
display components.

This roadmap covers the rendering work requested after the Workbench feature
review. It is intended for an implementation session that has not seen that
conversation. Start with **RC1**, then follow the dependencies below. The
defaults in this plan are implementation recommendations; record justified
changes in the relevant slice rather than reopening routine choices.

Related designs: [reading and Markdown](workbench-reading.md),
[answer versions](workbench-answer-versions.md), [MCP tools](workbench-mcp.md),
[memory and documents](workbench-memory-and-documents.md), and
[media screens](workbench-media-screens.md). This roadmap takes up the math and
footnote work deferred in the reading design. It does not reorder the broader
[audience roadmap](audience-roadmap.md).

## Scope and intended result

A person can ask for a technical explanation and see readable equations and a
diagram, ask a connected tool for a plot and see its image, inspect a data table
or chart, and open a generated document or small interactive preview. The same
content remains available after reconnecting or selecting an earlier answer
version. Unsupported or malformed content has a readable explanation and a
source or download fallback.

The scope includes rich Markdown, message and tool content representation,
authorized assets, source navigation, bounded charts and tables, and isolated
artifact previews. An artifact is a saved output with its own source, preview
and revisions.

Projects, long-chat compaction, research orchestration, a Python/code-execution
service, real-time voice, and an Office-style editor are separate work. This
roadmap displays files and results produced by existing models or tools; it
does not create a general computation service. Previewing an HTML/React
artifact runs browser code only inside the preview boundary defined in RC5.

## Current implementation

The source baseline was inspected at Workbench commit
`d5aad5f921778216be9d5a1f1782c57d6490f1a1`. Recheck the current checkout before
implementing; this is a dated baseline, not an installed-version claim.
Backend filenames below are under `src/eugene_plexus_workbench/` unless a
different path is shown.

| Area | Current behavior | Implementation entry point in Workbench |
|---|---|---|
| Markdown | CommonMark/GFM, tables, task lists, callouts, and attribute-free `br`, `sub`, `sup`, `kbd` | `web/src/components/Markdown.tsx`, `web/src/lib/markdownPlugins.ts` |
| Code | Language label, Copy, syntax highlighting, closed-fence detection, memoization and size limits | `web/src/lib/highlight.ts` |
| Math and diagrams | No math typesetting; Mermaid displays as code | Markdown plugin and code-block dispatch |
| Footnotes | Footnote text appears, but references/backlinks lose navigation because fragment links are rejected | `safeHref` and the Markdown `a` component |
| Images and HTML | Answer image URLs become links; most raw HTML/SVG is dropped | Markdown `img`, `skipHtml`, `src/eugene_plexus_workbench/web.py` |
| Assistant messages | Text and reasoning strings, with sources and attachments stored separately | `store.py`, `answers.py`, `web/src/lib/types.ts` |
| MCP results | Non-text blocks become unsupported placeholders; structured content becomes a JSON string | `tools.py`, `node_folders.py`, `web/src/components/ToolCalls.tsx` |
| Citations | Web annotation URL/title retained, but annotation positions discarded; document sources listed separately | `answers.py`, `web/src/components/SourcePassages.tsx` |
| Media | Images, audio and video work in the Media screen; uploads have their own attachment path | `media_api.py`, `web/src/components/Media.tsx`, `MessageView.tsx` |

The chat client currently uses `/v1/chat/completions`. A gateway capability,
including an output available through Responses, is not automatically available
in Workbench. Rendering support must name the input path that supplies it.

## Delivery order

| Slice | Deliverable | Dependency | Primary owner |
|---|---|---|---|
| RC1 | Math and working footnotes | Existing Markdown | Workbench frontend |
| RC2 | Mermaid diagrams with source fallback | RC1 rendering conventions | Workbench frontend |
| RC3 | Typed tool/message content, authorized assets and inline media/file cards | Independent of RC1/RC2; required by RC4/RC5 | Workbench backend and frontend |
| RC4 | Citation navigation and structured tables/charts | RC3 | Workbench backend and frontend |
| RC5 | Saved artifacts and isolated previews | RC3; reuse RC2/RC4 where applicable | Workbench backend and frontend |

Each slice must be usable and accepted before it is called complete. RC3 can
be designed alongside RC1/RC2, but keep shared-file edits coordinated. A fresh
implementation session per slice is appropriate.

## RC1 Math and footnote navigation

**Result:** equations render in ordinary answers, and a footnote reference
moves to the correct footnote and back without changing chats.

Use the existing Markdown extension points. Prefer KaTeX with Markdown math
parsing, bundled locally and loaded when needed. Check dependency versions,
licenses and Node compatibility against the actual package files before
pinning them. Keep reasoning as plain text; its rendering policy is a separate
decision already documented in the reading design.

Support inline `$...$` and `\(...\)`, and display `$$...$$` and `\[...\]`.
Recognize backslash delimiters before Markdown removes their escapes. Use
tokenizer-aware handling that excludes inline/fenced code, escaped delimiters
and URLs. Define and test the dollar-delimiter rules: `$5 and $10` must remain
currency. Do not apply a global replacement regex to the entire answer.

The reading design's section 10 records CSP failures with the then-tested
`rehype-katex` path and a working parse5-to-React alternative. Reproduce this
under the production headers with the chosen versions. Keep the parent chat's
CSP intact. Use a controlled syntax-tree-to-React path for renderer-produced
markup, with an explicit element/attribute/style allowlist; parsing alone is
not sanitization. Keep KaTeX trust disabled, bound expansion and visual size,
and retain accessible MathML.
Malformed or incomplete math must leave the answer readable and copyable.

Footnote IDs must be unique per rendered message/version and per draft/final
region. Preserve generated IDs and accessibility attributes on references and
backlinks. Resolve only known fragment targets inside that Markdown region;
move focus appropriately without mutating the app's routing hash. Do not turn
the fragment fix into permission for arbitrary URL schemes or element access.

**Acceptance:**

- Inline/display equations, fractions, matrices, Unicode and equations inside
  lists/tables render in both themes and at 200% zoom.
- Currency, escaped dollars, code samples and incomplete streaming delimiters
  retain their intended text. Copy and Markdown export preserve source.
- Bad formulas and excessive expansion/size fall back locally; they do not
  blank or freeze the chat. Macro state cannot leak between messages.
- Two answers using `[^1]`, a quiet draft, and an alternate branch have unique
  IDs and working keyboard-accessible references/backlinks.
- The production browser run reports no new CSP violations or external asset
  requests. Existing raw-HTML and unsafe-link tests still pass.

### RC1: what building found (2026-10-13)

Built in Workbench `web/src/lib/markdownMath.ts` (the parser),
`mathTypeset.ts` + `mathWorker.ts` (KaTeX, in a worker), `mathClient.ts` (the
worker's keeper and the cache), `mathMarkup.ts` (markup to React through an
allowlist), `components/MathFormula.tsx`, and footnotes in
`components/Markdown.tsx` + `lib/markdownPlugins.ts`.

- **A source cap cannot bound the work; a worker can.** Measured with KaTeX
  0.19.0 and `maxExpand: 1000`: a 488-character formula that defines and
  repeats a macro took **36 s**, a 2,008-character one **92 s**, while the
  largest legitimate fixture (a 25 x 25 matrix, 5,674 characters) took 20 ms.
  `maxExpand` counts expansions, not the tokens they produce. So KaTeX runs in
  a module worker, one formula at a time; a formula over **1.5 s** ends the
  worker, fails with "it took longer than 1.5 s to lay out", and a new worker
  takes the next one (the start, up to 10 s, is not counted). Also capped:
  8,000 characters of source and 600 KB of markup (a 20 x 20 matrix is
  358 KB). No CSP change: the worker is a same-origin script under
  `script-src 'self'`.
- **No parse5.** KaTeX's `renderToString` runs in the worker; the page reads
  its markup with a strict reader for exactly the shape KaTeX writes (anything
  else fails the formula) and builds React elements through an element,
  attribute, class and style allowlist. React sets styles through the style
  object, which the policy allows: zero refusals, and no 62 KB gz parser.
  `trust` stays off; no `macros` object is passed, so a `\gdef` dies with its
  formula.
- **`maxSize` caps only positive sizes.** `\kern{-500em}` became a -500 em
  margin that would pull the line across the page, and 300 of `\kern{-20em}`
  the same in small steps. The reader refuses one negative margin over 25 em
  and a formula's negative margins over 40 em in all (the most measured in
  real formulas was 19, for 60 `\!`). Offsets up and down are KaTeX's own
  layout and only held to a 2,000 em size limit: a first cap of 25 em on `top`
  refused a 40-row `aligned`, whose rows sit up to 70 em from its middle. A
  raised box keeps its own height in the line (KaTeX's strut reserves it), and
  the chat's scroller clips anything pulled sideways out of the column. A
  vertical-only `overflow: clip` on each inline formula was tried and dropped:
  it changed rasterisation (40 device pixels in 41 formulas) and contained
  nothing the above does not.
- **Dollar rules:** Pandoc's (a single `$` opens before a non-space and closes
  after one, not before a digit) plus "not after a digit", for "5$/month",
  plus TeX's own: `$x$` ends at its next bare `$`, so a `$` that cannot close
  means the first was money. "Costs $5, then $x$" is money, then a formula
  (Pandoc reads "5, then $x" as the formula). `$5 and $10`, `$10-$20`,
  `$HOME and $PATH` stay text; `$2x + 3 = 7$` is a formula. Known false
  positive: shell text outside code with a closing-shaped `$`, such as
  `$PATH:$HOME` followed by text.
- **Looking for closes is budgeted.** Every opener looks ahead for its close
  (a single `$` 1,000 characters, the others 20,000), and every chunk of an
  answer being written is parsed again. Built text such as `\(a ` repeated to
  32 KB took 3 to 6 s a parse. Now one parse may spend 200,000 characters on
  searches that found nothing, and an opener inside a stretch where an earlier
  one of its kind already searched to the end of the text does not search.
  The test asserts under 1.5 s for each such input; a real answer spends a few
  hundred characters.
- **`\[...\]` in prose is display math.** An answer escaping brackets as
  `\[1\]` loses them to a formula. Accepted: models write `\[` for display
  math far more often.
- **A `$$` or `\[` block may not interrupt a paragraph.** Otherwise "Total:
  $$", "x", "$$" opened a block at the last line and swallowed the rest of the
  answer; the paragraph's own `$$` pair is the formula instead. A block opens
  only on a line of its own, closes on its delimiter's own line or a line
  ending in it, and an unclosed one stays source, like an open code fence.
  A ```` ```math ```` fence is a display formula, as on GitHub.
- **Footnotes:** `clobberPrefix` takes each answer's `useId()` prefix, but
  mdast-util-to-hast 13.2.1 leaves the screen-reader heading as
  `footnote-label` (and the references' `aria-describedby` with it) in every
  answer; a rehype plugin prefixes both. A reference finds its note among the
  ids inside its own answer, not with `getElementById`, so a colliding id
  elsewhere cannot capture it; focus moves and the address and hash do not.
- **jsdom has no style on MathML elements**, and MathML's styles (a box's
  border, `\pmb`'s shadow) draw nothing in KaTeX's hidden MathML copy, so they
  are dropped. KaTeX 0.19 renamed `.strut`/`.base` to `.katex-strut`/`.katex-base`.
- **Bundle (measured against a build of `d5aad5f`):** the page's own script
  939.6 to 951.4 KB (272.1 to 276.2 KB gz); none of KaTeX is in it. The first
  formula loads a 3.4 KB view (1.8 KB gz), KaTeX's 22.5 KB stylesheet
  (3.5 KB gz) and the 260 KB worker (76.7 KB gz); the browser fetches each
  KaTeX face as it is used. A build plugin keeps KaTeX's faces as woff2 only:
  20 files instead of 60.
- **Dependencies:** `katex` 0.19.0, exact (MIT; released 2026-10-01 by a
  long-standing maintainer; its one dependency, `commander`, is the CLI's and
  is not bundled). `micromark-util-character` and `micromark-factory-space`
  become direct dependencies at the versions react-markdown already used;
  `mdast-util-from-markdown` (types) is pinned at the installed 2.0.3, because
  npm would otherwise have moved react-markdown's parser to 2.1.0, ten days
  old.
- **The cache:** at most 500 laid-out formulas and 16 MB of their markup,
  the least recently shown dropped first. A formula that failed because the
  worker would not start, stopped, or the display chunk would not load is
  tried again when it is next shown; its own error (bad TeX, too long, too
  slow) is final.
- **Not done:** copying a selected formula copies its drawn text, not its TeX
  (KaTeX's `copy-tex`); a `\color` the model chose is not adjusted per theme;
  reasoning stays plain text; no screen-reader, Firefox or Safari run. Slow
  formulas wait their turn: an answer with N formulas that each take the full
  1.5 s keeps the ones after them pending for N x 1.5 s (the page stays
  usable). An unclosed `$$` block at the end of a finished answer shows the
  rest as its source, as an unclosed code fence does. A footnote link opened
  in a new tab opens Workbench with the note's id as the hash, which does
  nothing. KaTeX's faces use `font-display: block`, so a formula is blank
  until its font arrives (from Workbench itself, so briefly).

## RC2 Mermaid diagrams

**Result:** a fenced `mermaid` block shows a diagram with Source, Copy, expand
and download controls. Invalid syntax still shows the original code and a
short explanation.

Add a dedicated code-fence renderer. Load Mermaid locally on demand; render
once a fence closes, cache completed results, and cancel or ignore obsolete
renders when a message/version changes. An unfinished fence remains source
text. Keep other code fences on the existing highlighting path.

Use fixed application-controlled Mermaid configuration, strict security and
disabled HTML labels/click callbacks. Source directives must not override that
configuration. Bound source size, diagram complexity and rendering work. Choose
and record enforceable limits after measuring representative fixtures; a
Promise timeout alone does not stop a synchronous layout that blocks the UI.

Treat the resulting SVG as untrusted output. Use a controlled, sanitized
display boundary; do not copy Mermaid examples that assign `innerHTML` into
the chat. Strip active content and external references, including from
downloads. Preserve the main chat's no-HTML-injection invariant. Keep the
diagram source and a textual alternative available.

**Acceptance:**

- Flowchart, sequence, class and state diagrams render from streamed answers.
- Repeated diagrams and branch switches do not collide on SVG IDs or rerender
  unchanged blocks on every token. Theme changes remain legible.
- Invalid, oversized and adversarial diagrams fail within the bounded path;
  the surrounding answer and Stop/navigation controls stay usable.
- Attempts to enable callbacks, inject HTML or fetch external resources fail.
- Source copying and SVG/PNG download work; export dimensions are bounded.
- Diagrams work at mobile width, with keyboard controls and reduced motion.

### RC2: what building found (2026-10-13)

Built in Workbench `web/src/lib/diagramDom.ts` (a page for Mermaid that is
not the page), `diagramRender.ts` + `diagramWorker.ts` (Mermaid, in a worker),
`diagramClient.ts` (the store and the theme), `diagramMarkup.ts` (the page's
allowlist), `workerQueue.ts` (the worker's keeper, now shared with RC1's
formulas) and `components/MermaidDiagram.tsx`.

- **Mermaid cannot run on the page under its policy, and cannot be stopped
  there.** It draws into the DOM and measures what it drew; while drawing it
  inserts a `<style>` and sets `style` attributes, which `style-src 'self'`
  refuses and reports. And a source cap again cannot bound the work: 100
  nested subgraphs (1,711 characters) took 20 s, 500 nodes with 1,000 edges
  9 s. So Mermaid runs in a module worker on linkedom's DOM, and
  `diagramDom.ts` supplies the sizes Mermaid reads back: text measured with an
  OffscreenCanvas in the font, size and weight its element would have (its
  attributes, its style, and Mermaid's stylesheet for the diagram, matched
  with linkedom's selectors), shapes from their geometry, a group through its
  children's transforms. Side by side with Mermaid on a real page, the 13
  kinds below laid out alike. A diagram over **4 s** ends the worker, says "it
  took longer than 4 s to draw", and a new worker takes the next (RC1's keeper,
  made generic). Measured in the worker: ordinary diagrams 10 to 250 ms, a
  300-step flowchart 0.6 s, 300 classes 3.8 s. The worker starts Mermaid and
  the flowchart's code before it says it is ready, so a first flowchart's
  time is its own. Also capped: 20,000 characters of source (a 500-step
  flowchart is 17,540), 20,000 elements, 6 MB of SVG, 50,000 px a side.
- **A picture the page writes itself, shown as an image.** The worker writes
  Mermaid's stylesheet into each element's style and sends the drawing as a
  tree. The page reads it through an allowlist (elements, attributes, styles;
  a value may point only inside the drawing, `url(#id)`) and writes a new SVG,
  every name from its own tables and every value escaped, shown as an `<img>`
  of a `data:` URL: an image runs no script and fetches nothing, and its ids
  meet no other diagram's, so repeated diagrams and branches need no id
  rewriting. A link (`click ... href`) becomes a group: Mermaid puts a linked
  node's place on the link, and unwrapping it first moved the node to the
  corner. A `foreignObject` and an `<image>` are dropped; any other element
  off the list fails the diagram, which shows its source. The policy refused
  nothing.
- **The configuration is Workbench's.** Strict security (no click callbacks),
  no HTML labels, dagre, the classic look, the base theme in the page's
  colours, and every key on Mermaid's `secure` list, so a `%%{init}%%`
  directive or front matter `config:` changes nothing (tested with HTML
  labels, a loose security level, a theme, ELK, `themeCSS` with an outside
  `url()`).
- **13 kinds are drawn:** flowchart, sequence, class, state, entity
  relationship, Gantt, pie, user journey, timeline, Git graph, mind map,
  quadrant and XY. Another kind says "Workbench does not draw this kind of
  diagram (sankey)" and shows its source; the kind is detected before any of
  its code loads, so `flowchart-elk` never loads ELK's 1.46 MB.
- **A diagram is drawn when it comes near the screen** (within one and a
  half screens of the chat's scroller), not when its chat opens: one answer
  of slow diagrams, each stopped at 4 s, would otherwise queue ahead of the
  one being read, and a long chat would draw all its history. A picture
  already drawn stays while a change of theme draws the new one, so a larger
  view open on it stays open.
- **The font is Arial (Liberation Sans on Linux).** An image cannot load the
  page's IBM Plex, and a family every computer has keeps a downloaded SVG's
  text inside its boxes elsewhere.
- **Colours come from the page's CSS variables,** read when a diagram is
  drawn; the theme is part of what is kept, so a change of theme draws each
  diagram once more. Shapes in `--tint` edged in `--accent-left`, notes edged
  in `--accent-right`, titles in `--heading`; a timeline's sections, a mind
  map's and a Git graph's branches in the status colours' edges under the
  strongest text (5:1 or more in both themes); pie slices and XY series in the
  accents. `--tint-edge` read 2.1:1 and 2.9:1 under a slice's text and was
  replaced. A user journey's section names are HTML beside a text fallback
  that Mermaid colours like the box behind it (invisible in both themes); the
  fallback now takes the text colour.
- **Mermaid's picture shape (`img:`) loads the picture** to learn its size
  (`new Image()`, which a worker lacks). The stand-in has no size and fetches
  nothing; the shape keeps the size the diagram gave it, and the page drops
  the picture.
- **Instrument traps:** a document the page parses (`DOMParser`) is held to
  the page's policy, so the check's own reading of each SVG reported
  `style-src-attr` refusals until it moved to Node. Windows' clipboard reads
  back `\r\n`. A phone's buttons are 44 px tall: "one row" is measured by the
  tools' middle lines, not the head's height.
- **Dependencies:** `mermaid` 12.1.0 and `linkedom` 0.18.13, exact (MIT and
  ISC; released 2026-10-02 by Mermaid's release workflow with provenance, and
  2026-07-07). npm `overrides` give Mermaid the KaTeX 0.19.0 RC1 pinned (one
  copy; 12.1.0 asked for 0.16.47, under GHSA-238p-pmpm-9mq7), and hold
  `dompurify` 3.4.16, `uuid` 14.0.2 and `package-manager-detector` 1.8.0
  (the resolved versions were 1, 3 and 8 days old). `npm audit`: 0.
- **Bundle:** the page's own script grew 11.4 KB (2.7 KB gz) for the block,
  its tools and the store; Mermaid's core (636 KB, 126 KB gz), linkedom with
  the stand-in (200 KB, 69 KB gz) and each kind's code load only with the
  first diagram.
- **Not done:** a diagram's text is in the picture, not the page (no
  find-in-page; a screen reader gets the kind, the diagram's own title and
  description, and the source). A wide diagram is shrunk to the column and
  read at size in Expand, which opens at no less than 50%. A model's own
  colours (`style`, `classDef`) are drawn as written, not adjusted per theme.
  Mermaid's math in labels was not checked. No Firefox or Safari run. Every
  kind's code is in the build (7.4 MB of assets in all, loaded only as used).

## RC3 Content blocks and authorized assets

**Result:** an MCP tool can return text plus an image or file, and Workbench
retains and displays those results after refresh. Existing chats continue to
work. This is the foundation for rich output beyond Markdown.

### Representation and compatibility

Define a versioned, ordered content-block representation with stable block
IDs. Start with text, image, audio, video, file and structured-data blocks,
plus an explicit unsupported-content fallback. Store citation annotations
against their text block. Exact field names belong in the implementation
contract; required semantics are:

- Original order, source tool/call, message/branch ownership and provenance.
- Source text or validated structured payload; large binary data is an asset
  reference, not base64 repeated in message JSON or SSE.
- An asset's media type, byte size, display name and availability state.
- Version/revision information and a bounded textual fallback.

Introduce this additively. Map legacy message strings and tool results to text
blocks without guessing that old code fences, JSON or URLs are rich assets.
Keep the existing text fields as a defined compatibility projection while
needed; document which representation is authoritative and prevent divergence.
Do not fabricate content that was already lost as an unsupported placeholder.

Follow the store's migration and pre-migration backup conventions. Test old
database fixtures and interrupted migrations. Define behavior for an older
browser tab seeing new events and for an older application opening a newer
store; do not assume schema downgrade is safe.

### Transport and model replay

Use one normalization path within Workbench for **both** direct MCP and Job
Site result handling. Preserve text,
supported embedded media/resources, resource-link metadata and structured
content. Validate type and size before persistence. Unsupported content gets
an explicit bounded fallback, not silent disappearance.

Keep remote resource URLs as link metadata by default. A URI alone is not
permission to fetch it, read another MCP resource, or access a local path.
Embedded bytes and an already-authorized asset are the first supported paths.

Make events idempotent with stable block IDs and revisions/offsets. Preserve
the existing UTF-16 text-offset convention used by the browser. Reconnecting
from a snapshot, duplicate delivery, gaps, partial results and branch changes
must not duplicate content or splice one result into another. Persist state
before advertising a completed asset.

Separate display from model replay. A rendered image must not silently be
omitted from the model request while the UI implies the model saw it. For the
first slice, retain the supported bounded text replay and explicitly describe
rich content unavailable to that model. Do not add Workbench storage paths,
access tokens or credentials from asset metadata to the projection. Preserve
existing authorization and replay behavior for tool-result text, which may
legitimately name a person's files. Preserve tool-call IDs and tool message
order.

Current public chat contracts do not provide a generic multimodal tool-result
or assistant-output channel. If a later implementation sends images back to
the model or ingests provider-native output parts, first extend the relevant
shared contracts/adapters and test an actual supported backend. Adopting
Responses wholesale is not a prerequisite for RC1-RC5.

### Asset access and lifecycle

Provide authenticated media/file routes and reuse appropriate existing media
components. Preview only validated assets whose authorization succeeds; model
authored image URLs remain links. Audio/video use explicit playback controls,
not autoplay. Files have readable names, type/size information and downloads.
Initially, formats without a safe preview remain downloadable file cards.

An asset inherits the restrictions of the result that produced it. Existing
chat readability alone is insufficient: a Job Site result hidden from the
install owner must also hide its filenames, thumbnails, bytes and downloads.
Apply saved-document restrictions where that provenance applies. Enforce the
same checks on metadata, preview, download, range requests and export routes.
Preserve `Cache-Control: private, no-store` on authenticated asset responses.
Clear rendered private assets, object URLs and application caches on sign-out
or a known loss of access; revalidate access when a preview is reopened.

Define per-asset and per-person storage limits, failure states and orphan
cleanup. Keep assets referenced by any surviving answer version. Delete only
unreferenced owned assets when their chat/artifact is deleted; never delete a
source file on a Job Site. Cancelled or interrupted calls retain their existing
uncertainty and non-replay semantics.

**Acceptance:**

- A fixture MCP server returns mixed text/image/resource/structured results
  through each tool path; order and supported content survive persistence,
  restart, reconnect, export and branch selection.
- A second person cannot access asset metadata or bytes. Owner read-only views
  obey hidden-result rules through direct URLs as well as the visible UI.
- Signing out, changing person or losing access cannot restore a prior private
  preview from application caches or an unreleased object URL.
- Duplicate/gapped events, emoji offsets, partial uploads and missing assets
  produce consistent recovery or explicit fallback.
- Spoofed MIME types, excessive payloads and hostile SVG/HTML cannot become
  active content in the main chat. Resource URLs cause no implicit fetch.
- Legacy chats and text-only tools still work. Tool transcripts replay within
  the gateway's supported schema and limits, without pretending image vision.
- Deletion preserves assets on surviving branches and cleans up true orphans.

### RC3: what building found (2026-10-13)

Built in Workbench `src/eugene_plexus_workbench/content.py` (the one reader
of a tool's result), `store.py` (schema 14), `tools.py` and `node_folders.py`
(both paths through it), `answers.py` (files kept before the checkpoint that
announces them), `api.py` (the hidden-result rule on files), `app.py`
(orphans at start), and `web/src/components/ToolContent.tsx`, `lib/api.ts`,
`App.tsx` and `lib/conveniences.ts`.

- **Every result went through two different flatteners,** one for MCP
  servers and one for job sites, which joined text and turned anything else
  into `[Unsupported image result]`; one appended structured content always,
  the other only when it differed from the text. Now one reader
  (`content.normalize`) makes an ordered list of blocks (`text`, `image`,
  `audio`, `video`, `file`, `data`, `link`, `unsupported`), each with a stable
  id (`<call id>:<n>`), kept on the call in `tool_rounds` (`content`,
  `contentVersion: 1`), and the text the model is sent again (`result`), from
  the same blocks. Structured content the words already hold is said once.
- **Representation:** blocks live on the call they belong to; a picture,
  sound or file is a row of the chat's `files` (schema 14 adds `message_id`
  and `origin`, `upload` or `tool`) and its bytes beside the person's
  uploads. The bytes are written first, then the row, then the call's blocks,
  then the checkpoint saves the answer and sends it: nothing is announced
  before it is kept. A crash between keeping a file and saving the answer
  leaves a file no answer names; it is removed at the next start. No event
  carries bytes; the `answer` event already carries the whole message, so a
  reconnect or a repeated event replaces rather than splices.
- **What a file is comes from its bytes.** A picture is shown only when its
  bytes are PNG, JPEG or WebP, a sound only when they are a sound Workbench
  plays; anything else, an SVG, a page that says it is a PNG, a GIF, is a
  file offered for download (served as `application/octet-stream`, as an
  attachment, under `sandbox`), with what it claimed beside it. An address a
  tool names (`resource_link`) is shown, and is a link only when it is a web
  address; nothing is fetched.
- **Limits:** 5 MiB a picture, 10 MiB a sound, video or file, 8 files and
  20 MiB a call, 1 GiB of tool files a person, 64 blocks a result, 65,536
  characters of structured data and of the text replayed. What is over says
  so in its place ("Not kept: a picture. It is larger than 5 MiB."), and the
  model is told the same.
- **The model is told what it did not see.** Each picture, sound or file is
  one line in the replayed text: `[The tool returned a picture, "chart.png"
  (image/png, 120 KB). The person sees it; you do not.]`. No file id, path or
  token of Workbench's is in it. A call made before keeps its text as it was.
- **The hidden-result rule now holds for files.** `/api/files/{id}` checked
  only that the reader could read the chat, so the install owner could fetch
  any chat file by id, a hidden message's upload included. A file is now
  hidden as its message is: a tool's by `message_id`, an upload by the
  message that carries it. Only what a person uploaded counts toward a
  chat's attachments, is listed among its documents, or can be taken back
  unsent.
- **The page:** pictures under the call's state, fetched with the session
  each time they are shown and let go when not; a sound or video loads only
  when asked and has its controls, never playing by itself; a file is a card
  with its name, type, size and Download. Signing out, however it comes
  about, lets go of every file's `blob:` address and of the drawn diagrams
  and laid-out formulas. Under the page's policy a `fetch` of a `blob:`
  address is refused (`connect-src`), so the check loads it as an image.
- **Job sites:** their results come through the same reader, so a site's
  picture is kept and hidden as its message is. But site-host and control
  each cap a site's answer at 70,000 bytes, so only small pictures pass a
  site; larger ones fail with the site's own words. Widening that is
  site-host's and control's change, not Workbench's.
- **Older pages and stores:** a page from before ignores `content` and shows
  the replayed text, which says what each file was. A Workbench from before
  refuses a schema-14 store, as it refuses any newer one; the copy made
  before the migration is the way back.
- **Bundle:** the page's own script grew 6 KB (1.7 KB gz) for the content
  view; nothing new loads with it.
- **Not done:** a direct MCP server's whole response is still capped at
  2 MiB, so pictures reach about 1.5 MiB that way (5 MiB through a site would
  need the site cap widened first); two answers at once can pass the
  per-person total by one call's 20 MiB; a picture opened in a tab of its own
  is let go when its message is; the model is never sent a picture (no
  shared contract carries one in a tool result yet); no Firefox or Safari
  run.

## RC4 Citations and structured results

**Result:** a citation opens its source detail, and supported structured
results display as useful tables or charts with the underlying data available.

Retain provider annotation positions when supplied. Specify the provider's
offset units and map them explicitly to the stored text block and browser
string; account for streaming, Unicode and draft/final separation. Do not
invent positions when a provider supplied only a URL. Keep existing Sources
lists as the reliable fallback.

Connect document citation markers to the existing passage detail view. Avoid
converting arbitrary bracketed numbers in code or unrelated prose into source
links. Reuse the source ownership and redaction rules, and preserve the
distinction between a passage sent to the model and one cited by the answer.

Support explicit structured table and chart blocks. Start with bounded tables
and bar, line and scatter charts using a declarative schema controlled by
Workbench. Do not execute JavaScript from data or interpret every JSON tool
result as a chart. Provide a table/raw-data view and download alongside a
visualization. Treat CSV exports as data, including spreadsheet-formula
injection handling. State truncation rather than silently dropping rows.

**Acceptance:**

- Citation navigation works with mouse and keyboard; missing/invalid spans
  retain a source-list fallback. Unicode and branched answers target the
  correct text and source.
- Text-only tool results remain text. Explicit table/chart fixtures render,
  sort or inspect predictably, and preserve their source data.
- Charts have labels and accessible data alternatives, and remain legible in
  both themes and at mobile width. Large results use an explicit bounded view.
- Unknown schemas, missing fields and invalid numbers produce useful fallback.
- No chart expression, source link or export bypasses RC3 access rules.

### RC4: what building found (2026-10-14)

Built in Workbench `answers.py` (`cite`, `sources_view`),
`web/src/lib/citations.ts`, `lib/chartSpec.ts`, `lib/csv.ts`,
`components/Chart.tsx`, `DataTable.tsx`, `Structured.tsx`, and in
`Markdown.tsx`, `MessageView.tsx`, `SourcePassages.tsx` and `ToolContent.tsx`.

- **The gateway already says where a web source is cited,** and Workbench
  dropped it. `server_tools.citations` annotates only an address the answer's
  text holds, with `start_index` and `end_index` as Python indexes into the
  text of the one request that wrote it (a whole Markdown link when the
  address is one). Workbench now notes where each request's text begins in
  the message and gives the page the place in the page's count, UTF-16
  (`marks`), never Python's. A source with no place is in the Sources list
  only, as before.
- **The gateway's count drifts after a draft.** It counts its rounds' text
  joined by a blank line it never streams, so in the most common searched
  answer (a draft, a search, the answer) every place was two characters past
  the stored text a round, and a bare address no longer fit its place (filed
  as gateway#16; its Responses door likely shares it). So a place is where
  the text holds the address, at the occurrence nearest the gateway's index,
  a Markdown link around it cited whole as the gateway cites it; where the
  text does not hold the address there is no place. No place is made up, and
  none depends on the gateway's arithmetic.
- **The number goes after the link that is the citation.** The answer's
  Markdown is the text after its draft, so each place is taken from where the
  answer begins (the same trim as `answerParts`). A remark plugin puts the
  source's number after the link whose source range meets the place; the
  number moves focus to that source in the answer's Sources, by mouse or
  keyboard, and leaves the address alone. Each version of an answer has its
  own sources and its own numbers.
- **A passage's `[n]`,** as Workbench asks the model to cite (context.py), is
  a link only for a passage that was sent with the question, only in the
  answer's words: not in code (which has no words to split), not inside a
  link, not a footnote. It opens that passage under the answer and focuses
  it. Any other bracketed number stays words. A model's own `[x](#web-1)` is
  no citation: only the plugin marks one, and a link to `#` is not a link.
- **Charts and tables are asked for in so many words:** a ```` ```chart ````
  block in an answer (JSON; it may leave out `"workbench"` and `"version"`),
  or a tool's structured content that says `"workbench": "chart"` or
  `"table"`, version 1. Nothing else is tried: a tool's other data stays data.
  The spec is read strictly (types, finite numbers, x as numbers or as
  categories but not both, 12 series, 5,000 points, 50 columns, 10,000 rows,
  200-character labels); what fails says why ("Chart not shown: `type` must
  be ...") and shows its source or data.
- **Workbench draws them itself,** bar, line and scatter, as SVG elements made
  from numbers, words as text, colours from the page's own variables by class
  (no `style` attribute, which the policy refuses), so they follow the theme.
  Each chart is named for a screen reader in one sentence and has its numbers
  a click away as a table. A table sorts by a column at a click
  (`aria-sort`), shows 200 rows and says how many there are; its CSV has them
  all.
- **A CSV is data:** a cell that starts with `=`, `+`, `-`, `@`, a tab or a
  return is written after an apostrophe (OWASP's guidance), numbers as
  numbers. No chart library: the drawing is about 250 lines.
- **A bar stands on a category,** so a bar chart's numeric x values (years)
  are categories in their order; a range too wide to step is drawn between
  its ends; long numbers are compact ("4.5M"); a chart's words are drawn
  larger on a phone. A tool's chart is read once for its data, not on every
  token of the answer around it.
- **Not done:** pie and stacked charts; no zoom or tooltips on a chart;
  series told apart by colour (and the legend's names) only; no Firefox or
  Safari run.

## RC5 Saved artifacts and isolated previews

**Result:** a user can open a generated Markdown document, SVG, HTML page or
small React app beside the chat, inspect/edit its source, save a revision and
download it. Begin with Markdown and static previews, then add executable
HTML/React once its isolation acceptance passes.

Give artifacts a title, type, source, revision history and a link to their
originating message. Use an explicit producer format or tool result, plus an
explicit user action to open an ordinary code block as an artifact. Do not
automatically execute all HTML/JavaScript fences. Earlier answer branches keep
their artifact revisions; user edits create revisions rather than overwriting
history. Markdown export should identify artifacts and revisions and must not
embed expiring authenticated URLs as permanent download links.

Render executable content inside an isolated preview with no access to chat
DOM, session credentials, authenticated APIs or arbitrary network destinations.
Bundle a small, fixed runtime locally for the first React slice; arbitrary npm
installation and public CDN dependencies are outside this roadmap. Keep the
parent chat's script policy unchanged and provide a source/download fallback.

Workbench currently applies CSP and `X-Frame-Options: DENY` broadly. Design the
preview route/origin, response headers and iframe sandbox together. Use a
narrow preview-specific policy; avoid the same-origin plus script combination
that lets untrusted content escape a nominal sandbox. Deny forms, popups,
navigation and service workers. Any parent/preview messaging must authenticate
the frame/channel and validate a small schema; it must not grant a general
Workbench API bridge. Apply RC3 permissions when loading preview assets.

Provide Run, Stop and Reload controls; opening a chat must not silently execute
an interactive artifact. Set bounded source/dependency limits and a stoppable
preview lifecycle. An error or expensive preview must not destroy the
conversation. Do not claim
that an iframe alone guarantees CPU isolation: measure the chosen design and
make failure/recovery explicit. Static SVG follows the sanitized rendering
rules from RC2, even when no scripts are intended.

**Acceptance:**

- Markdown, static SVG/HTML and the supported React subset have clear preview,
  source, edit, revision and download behavior. Unknown dependencies fail in
  words with source still available.
- Reopening, branch switching and revising artifacts preserve the right source
  and revision; deleting a chat follows RC3 asset-reference rules.
- Browser tests attempt parent DOM/cookie access, authenticated API calls,
  network fetches, forms, navigation and popups; each prohibited action fails.
- Main chat and preview headers are tested separately in the built app. Normal
  chat, Media screens and the existing search-suggestion iframe still work.
- Errors and resource-heavy fixtures have a usable stop/recovery path. Preview
  controls work by keyboard and at narrow widths.

### RC5: what building found (2026-10-14)

Built in Workbench `artifacts.py`, `artifacts_api.py`, `store.py` (schema 15),
`api.py`, `web.py`, and on the page in `lib/artifacts.ts`, `lib/svgArtifact.ts`,
`components/Artifact.tsx`, `ArtifactDialog.tsx`, `ArtifactPreview.tsx`,
`preview/runtime.ts` (built apart by `vite.preview.config.ts`), and in
`Markdown.tsx`, `Block.tsx`, `markdownPlugins.ts`, `MessageView.tsx`,
`conveniences.ts` and `App.tsx`.

- **The producer is the fence's own words:** a fence whose info string holds
  `artifact` (`html artifact title="Pricing table"`), in Markdown, SVG, HTML,
  JSX or TSX, is a card that opens the artifact, once the fence has closed;
  any other closed block of those languages has **Open as artifact**. Nothing
  runs because it is shown or opened. Workbench does not ask models to write
  the word: a person asks for it, or opens a block. A tool result as an
  artifact producer is left for later.
- **An artifact is kept at its first save, not when it is shown.** Until then
  it is the answer's block. The first save keeps the block as revision 1 (by
  "the answer" when the answer holds it, line by line for a fence set in by a
  list, its lines in their order) and the edit as revision 2, in one
  transaction; each later save is a new revision, never written over (the same
  words twice is no new one). An edit says which revision it began from, and
  one begun before the last saved one (another tab's) is refused, saying so,
  and kept on the page to be saved after it. Each belongs to the
  message whose block it was, so every version of an answer has its own, and
  they go with their chat (no files: the source is in the store). Limits: 512
  KB a revision, 100 revisions, 20 artifacts a message, 256 MB a person.
- **A block is found again by its words:** the store keeps a number of
  revision 1 (its length in UTF-16 units and cyrb53 over them), which the page
  computes for each block, so a card says "3 revisions" wherever the block is.
  The page and the server are tested on the same values (an emoji, an accent).
  The parser ends a block's text with the newline before its closing fence;
  that newline is not the block's.
- **The owner reading someone's chat reads its artifacts and keeps none;** an
  artifact of a message hidden from the owner (a job site's) does not exist to
  them, as its files do not. An export names each kept artifact and how many
  revisions it has; their sources are Workbench's, not the export's.
- **Markdown reads as an answer does, and SVG by RC2's rules:** the browser's
  XML reader makes a tree no one sees, RC2's allowlist writes it anew, and it
  is an `<img>`. A drawing with a script, a stylesheet or an outside picture is
  not shown, saying why, with its source.
- **A page or a component runs only at Run, in `/preview/frame`:** a page of
  its own whose policy (`PREVIEW_CSP`) gives it no origin (`sandbox
  allow-scripts allow-forms`, never `allow-same-origin`), no network
  (`connect-src 'none'`; pictures and fonts only from `data:` and `blob:`), no
  workers, frames or plugins, no form's sending (`form-action 'none'`, below),
  and lets only Workbench's page frame it
  (`frame-ancestors 'self'`, `X-Frame-Options: SAMEORIGIN` for that path
  alone). The chat's own policy is unchanged. Its script is one classic file
  (`/preview/runtime.js`, 426 KB, 116 KB gzip: React and sucrase), built apart
  from the page: a module from a page with no origin is fetched as another
  origin's, which needs CORS. The page and the frame speak in six messages,
  each heard only from the frame's own window, the source sent once when the
  frame says it is ready, and `started` and `failed` counted only with the
  run's nonce; what the frame says is shown as words.
- **A component imports React and nothing else,** compiled by sucrase (JSX and
  TypeScript); any other import fails in words ("This preview has React only:
  it cannot load "lodash"") with its source a tab away. An error thrown in
  Workbench's own script reaches the frame's error listener as "Script error."
  (another origin's script, to that page), so the component's code is run in
  an inline script that catches what it throws.
- **What a preview tries is refused and said:** a link that leaves is not
  followed; a script, picture or address it cannot load is listed. **One way
  out is left:** a frame may go to another address itself (by script or a
  `<meta>` refresh), and no policy Chrome keeps stops it (`navigate-to` was
  never shipped). The preview says so as it starts to go and the page removes
  the frame, but the request for that address may already have gone, carrying
  what the preview put in it; the run of record's page did not get that far.
  Its caption says it is stopped if it goes elsewhere, not that it cannot.
- **A preview keeps running while its source is read;** the two tabs are
  panels that stay (arrow keys, Home and End move between them).
- **A form's own script runs; the form never sends, and Chrome is not even
  asked to.** A frame whose form Chrome refused, then a preview that loops in
  the same process, left that process unable to end: every preview after it
  never started, a reload of the page too (85 s and counting, measured, with
  a sandbox that refused forms). And in a sandbox that refuses forms Chrome
  fires no `submit` at all, so a component's form (React's `onSubmit`) did
  nothing. So the sandbox allows forms, and the preview's script refuses
  `form.submit()` and stops each `submit` its page did not handle, once the
  page's own handlers have heard it; `form-action 'none'` refuses any it
  missed. A component's form works (by Enter and by its button, checked), a
  page's plain form says "Refused: sending a form", and the stuck process no
  longer happens.
- **A preview that never stops does not stop the page, and Stop ends it:**
  Chrome runs a sandboxed frame in a process of its own (the page's longest
  frame 0.2 ms while the preview looped; Stop 21 ms). That process lives on
  after Stop while it is stuck (a whole core for 5 s after, none 15 s after),
  and Chrome puts the next preview in it. So a frame that has not said it is
  ready in 3 s is replaced, up to 7 frames, and the preview says it waits for
  the browser to end the one stopped before; run at once after Stop, a preview
  started in 6.2 to 6.8 s. One that is ready and does not start in 10 s is
  stopped. A browser that runs frames in the page's own process (not measured)
  could stall with it; the source and Download stay beside it.
- **A request with a character that is no text** (a lone surrogate, which JSON
  may carry) was answered by FastAPI's own refusal with an error of the
  server's, on every route: its writer encodes as UTF-8. Workbench now writes
  that refusal itself (`web.invalid_request`), as a 422.
- **Not done:** no other npm package, no CDN, no `localStorage` in a preview
  (it has no origin); an artifact's title is the fence's and is not edited; no
  artifact from a tool's result; no diff between revisions; no Firefox or
  Safari run.

## Verification and release requirements

Follow [CONTRIBUTING.md](../../CONTRIBUTING.md) and the repository's current
engineering instructions. Shared contract changes belong in specs before
consumer implementation/codegen; Workbench-only rendering changes do not need
unrelated consumer re-pins. Keep this roadmap marked planned until each slice
has its own implementation and acceptance record.

For each slice, use a focused renderer/content fixture set and unit tests for
changed behavior, then one browser acceptance run against the built app with
production headers. Include partial streaming, malformed content, branch and
reconnect behavior, dark/light themes, mobile width, keyboard use and network
request inspection. DOM-only tests cannot establish CSP or iframe isolation.

The existing renderer tests intentionally reject raw HTML injection and unsafe
image fetching. Extend them to express the new controlled paths; do not disable
the protections globally. Add error boundaries and size/work limits around new
renderers. Record concrete performance and bundle measurements: ordinary
text-only chat should not eagerly load math, diagrams, charts or preview
runtimes, and finished blocks should not be reprocessed for every token.

Use the repo's runner workflow for checks and its scoped sabotage policy for
changed guards. Browser acceptance should use isolated fixtures and ports, not
the live installation's defaults. Run the relevant frontend type/lint/build
checks and backend checks for files changed. Record versions, measurements and
remaining limitations under `docs/acceptance/`, and update the relevant design
with what building found.

When shipping an implementation, follow the Workbench README's `dist` build
and catalogue-pin workflow; changing `main` alone does not update the installed
page. A documentation-only roadmap needs link and whitespace checks and no
codegen or runtime deployment.

## Starting the implementation session

Use this prompt for the first slice:

> Implement RC1 from `specs/docs/design/workbench-rich-content-roadmap.md`.
> Read the repository instructions and the existing Workbench reading design,
> inspect the current source, and implement math rendering and scoped footnote
> navigation using the roadmap's recommended defaults. Preserve production CSP,
> streaming behavior, source copying and existing safety guarantees. Complete
> the slice's unit and browser acceptance checks, record what building found,
> and update its status. Keep the change within RC1; leave the later slices
> planned. Follow the repository's normal landing and distribution workflow.

For subsequent sessions, replace RC1 with the next slice and read its
predecessor's acceptance record. Any unresolved blocker should identify the
specific failed behavior and the smallest remaining decision or dependency.

## Reference documentation

- [react-markdown](https://github.com/remarkjs/react-markdown) and
  [remark math](https://github.com/remarkjs/remark-math): the existing parser's
  extension points and math support.
- [KaTeX security](https://katex.org/docs/security) and
  [options](https://katex.org/docs/options): trust, expansion/size bounds and
  accessible output choices.
- [Mermaid configuration](https://mermaid.js.org/config/schema-docs/config.html):
  security and renderer configuration; verify against the pinned version.
- [Open WebUI Mermaid](https://docs.openwebui.com/features/chat-conversations/chat-features/code-execution/mermaid/):
  inline diagrams with source and navigation controls as a product benchmark.
- [Claude artifacts](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them):
  separate editable outputs and exports as a product benchmark.
- [LibreChat artifacts](https://www.librechat.ai/docs/features/artifacts):
  HTML/React/SVG/Mermaid previews as an advanced benchmark; this documentation
  describes its development version.
