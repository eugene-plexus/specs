# Row 31: reading and rich-content extras

Lane WEB, low risk. Seven batches, ordered by value. Five are TypeScript only; two need a little Python. **No store migration.** Sources: `workbench-reading.md` §12 and its risks; the "Not done" lines of RC1, RC2, RC4, RC5 and RC6 in `docs/history/workbench-rich-content-roadmap.md`.

## 1. What it delivers

| Batch | Delivers | Python? | Size |
|---|---|---|---|
| 31a | **Firefox and Safari:** Workbench is checked in Firefox and WebKit, and what breaks is fixed | no (`web.py` only if a preview's CSP must change) | M |
| 31b | **Display settings:** text size, reading width, theme, speaker labels | no | S-M |
| 31c | **Headings for screen readers, and the right font for Chinese, Japanese and Korean** | no | S |
| 31d | **A per-chat switch for running artifacts** | yes: `api.py` | S |
| 31e | **Artifacts from tool results** | yes: `artifacts.py`, `artifacts_api.py` | S-M |
| 31f | **What changed between two revisions** of an artifact | no | S |
| 31g | **Pie and stacked charts, and values on hover and focus** | no | S |

## 2. The design

### 31a Firefox and Safari

**Run each check in three browsers.**
- These scripts gain `--browser chromium|firefox|webkit`: `reading-browser.mjs`, `math-browser.mjs`, `diagram-browser.mjs`, `artifacts-browser.mjs`, `artifacts-inline-browser.mjs` and `structured-browser.mjs`. Playwright installs its own Firefox and WebKit.
- A new job in `ci.yml`, `browsers`, runs them on Linux for Firefox and WebKit. Chrome stays as it runs today.

**Check these first:**
- the math and diagram workers (module workers);
- the preview frame (sandbox, `srcdoc`, the 3 s ready rule, Stop);
- `color-mix()`, `dvh` and `text-wrap`;
- the footnote focus move;
- KaTeX's `font-display: block`;
- the 16 px composer rule on WebKit.

**What becomes of each failure.** It is fixed, or recorded in `workbench-reading.md` with the browser and version and what the person sees.

**Limit.** A real Safari or iOS run needs a Mac, which the project does not have. Until one runs, the README says: "Chrome, Edge and Firefox. Safari: checked with WebKit only."

### 31b Display settings (BP16, A11Y-12, C14)

**Where.** A **Display** part in the sidebar's footer, which a phone can reach.

**How it is kept.** Per viewer, in `localStorage`. Each read and write is wrapped. When storage is blocked, the setting works for this page and says "Not kept: this browser blocks storage."

| Setting | Choices | The default's label |
|---|---|---|
| Text size | 90, 100, 110, 125, 150% of the browser's size | "100% (17 px here)", computed from the page |
| Reading width | Narrow 34 rem, Comfortable 36 rem, Full | "Comfortable (36 rem)" |
| Theme | System, Dark, Light | "System (dark now)" |
| Speaker labels | Off, On | "Off" |

**Rules that keep each setting true.**
- **Text size** is a percent of the browser's own size, never a fixed px. A fixed size would override the person's browser setting.
- **Theme.**
  - The choice sets `data-theme` on `<html>`. Each `prefers-color-scheme` block in `styles.css` is repeated under `:root[data-theme]`.
  - Every place that asks `matchMedia("(prefers-color-scheme: light)")` reads one `useTheme()` instead: `MCPApp.tsx`, `diagramClient.ts` and the chart colours. A diagram drawn after the switch then matches it. Without this, the setting would lie.
- **Speaker labels** show "You", and the model's name, above each turn, in Plex Mono, as the website's transcript does.

**Files:**
- new `lib/display.ts` and `components/DisplaySettings.tsx`;
- `Sidebar.tsx`, `styles.css`;
- `MessageView.tsx` (the label), `MCPApp.tsx`, `diagramClient.ts`.

### 31c Heading outline and CJK (A11Y-08, the CJK line of §12)

**The outline.**
- Each message gets a heading that only a screen reader hears ("Answer from qwen3-8b"), at level 2.
- The answer's own `#` becomes h3, `##` h4, and so on, never deeper than h6.
- The styles move from the tag to `data-md="h1"` and the rest, so nothing moves on screen.

**`lang` for CJK.** In `Markdown.tsx`, each block-level element gets a `lang` when its text needs one:
- kana → `ja`;
- hangul → `ko`;
- Han characters only → the first of `navigator.languages` that starts with `zh` or `ja`, else `zh`.

This fixes Japanese drawn in a Chinese font under `lang="en"`.

### 31d A per-chat switch for running artifacts (RC6 "no per-chat switch")

**The setting.**
- `ChatSettings` gains `runArtifacts: bool | None`. Unset means on, as RC6 runs today.
- `chat_view` returns it. The switch follows the chat to another browser, so it is kept by the server, not the page.

**UI.** The chat's settings menu: "Run pages and components by themselves: On". With it off, each artifact shows its card with **Run**, as RC5 did.

**Files:** `api.py` (`ChatSettings` and `chat_view` only), `ChatSettings.tsx`, and the inline artifact component.

### 31e Artifacts from tool results (RC5 "no artifact from a tool's result")

**What the person sees.** A tool result's text block, or resource, that is HTML, SVG or Markdown (by MIME type, or by sniffing) gets **Open as artifact** in `ToolContent.tsx`.

**What runs.** It runs by itself, in RC5's isolated frame, like an answer's artifact. Troy's standing rule (2026-10-14): every answer's artifacts, web and tool answers included, are shown inline and run automatically.

**Python.**
- `artifacts.from_answer` becomes `found_in(original, message)`. It looks in the answer's text, then in its tool rounds' results.
- The keep route accepts the block when it is found in either.
- The revision's `author` stays `answer`: the table's check allows only `answer` and `person`, and a migration is not worth it.
- The view adds `origin: "tool"` and `tool: "server/tool"`, found again on read by the same check.

**UI text.** "Revision 1, from fetch_page's result".

**Coordinate.** Row 29 (pictures in tool results) also changes `ToolContent.tsx`. Whichever merges later rebases.

### 31f What changed between revisions (RC5 "no diff")

**What the person sees.** The artifact dialog gains **Compare with revision {n}**:
- added lines tinted green, removed lines tinted red and struck through;
- side by side at 1,024 px or wider, one column below that.

**How.** It uses `GET …/revisions/{number}`, which exists. A Myers line diff in a new `lib/lineDiff.ts` (about 120 lines), with no new dependency.

**Limit.** Over 5,000 lines: "Too long to compare here. Download both."

### 31g Charts (RC4 "no pie or stacked charts; no tooltips; colour only")

**The format grows, and stays version 1** (all additive):
- `"type": "pie"`: one series, at most 12 slices, the rest as "Other".
- `"stacked": true` on a bar chart.

**Values.** Hovering on a mark, or giving it keyboard focus, shows "Series · x · y".

**Telling series apart.** By marker shape and dash pattern as well as colour.

**Refused, with the reason:**
- "A pie cannot show negative values."
- "A stacked chart needs one value per category in each series."

**Files:** `chartSpec.ts`, `Chart.tsx`. Still no chart library.

### Failures

Each failure names its cause:
- the storage line (31b);
- a diff too long (31f);
- a chart refused, with the reason (31g);
- a block not found in the answer or its tools: 422, "This block is not in the answer or its tools' results" (31e).

### Defaults

Nothing deletes data or keeps chats anywhere new.
- 31d keeps RC6's default (runs by themselves).
- 31e does not run by itself.
- Speaker labels are off.

## 3. Repositories and files

**workbench only:**
- `web/src`: `components/DisplaySettings.tsx`, `Sidebar.tsx`, `Markdown.tsx`, `MessageView.tsx`, `MCPApp.tsx`, `ChatSettings.tsx`, `ToolContent.tsx`, `ArtifactDialog.tsx`, `Chart.tsx`;
- `web/src/lib`: `display.ts`, `lineDiff.ts`, `chartSpec.ts`, `diagramClient.ts`, `artifacts.ts`;
- `styles.css`, `web/scripts/*-browser.mjs`;
- `.github/workflows/ci.yml` (the `browsers` job);
- Python (31d, 31e only): `api.py`, `artifacts.py`, `artifacts_api.py`.

No contract and no codegen consumer. **specs:** the "What building found" notes in `workbench-reading.md`.

## 4. Tests that fail before the change

- **31a:** the `browsers` CI job, which does not exist yet. Its first run is the evidence. Each fix gets a Vitest or script assertion that failed in that browser.
- **31b `display.test.ts::theme_override_reaches_diagram_and_chart`.** With Light chosen on a dark system, `useTheme()` says light, and a diagram renders in the light palette.
- **31b, also:** `text size label shows effective px`, and `storage blocked keeps the setting for the page`.
- **31c `Markdown.test.tsx::answer_headings_nest_under_the_message`.** `#` renders as h3 with `data-md="h1"`.
- **31c, also:** `kana block gets lang ja`.
- **31d `test_chat_settings.py::test_run_artifacts_off_is_kept`,** and Vitest: an artifact in a chat with the switch off shows Run and does not start.
- **31e `test_artifacts.py::test_block_from_tool_result_is_kept_with_origin_tool`.** It also checks that a block found in neither is refused.
- **31f `lineDiff.test.ts::marks_added_and_removed_lines`.**
- **31g `chartSpec.test.ts::pie_and_stacked_read`,** and `negative_pie_refused_with_reason`.

## 5. Acceptance

Low risk. Changed-file tests, typecheck, lint and format; for each batch, one Playwright run of the script that covers it. No review is required. If one runs, it should attack:
- 31e: a tool result's page that escapes RC5's isolated frame (it runs by itself, so the frame is the boundary to attack);
- 31b: the theme override failing to reach a preview frame;
- 31a: a fix that changes Chrome's look.

## 6. Do not change

- **workbench:**
  - `store.py` (rows 7, 26, 27, 28, 30, 47): no migration here;
  - `tools.py` (rows 29, 32);
  - `context.py`, `conversation.py` (row 26);
  - `answers.py` (row 28);
  - `memory_servers.py`, `projects.py` (rows 27, 47);
  - `knowledge/*`, `SourcePassages.tsx`, `saved_api.py` (row 30);
  - `folder_windows.py`, `folder_linux.py` (row 23);
  - `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (rows 52, 60).
- **Shared:**
  - `api.py`: `ChatSettings` and `chat_view` only (rows 27 and 30 add fields too).
  - `ChatSettings.tsx`: one row each.
  - `ToolContent.tsx` with row 29.

## 7. Size, split, risks, calls

**Size:** about 6 days in all. 31a 2, 31b 1, 31c 0.5, 31d 0.5, 31e 1, 31f 0.5, 31g 0.5. Each batch is its own branch (`r31a-browsers` and so on), so a TypeScript-only builder can take 31a, 31b, 31c, 31f and 31g. 31d and 31e need a Python check: pytest and mypy on both platforms.

**Risks:**
- **WebKit on Linux is not Safari.** A real Safari or iOS run stays owed.
- **The theme override needs every colour reader to follow it.** A reader that is missed would lie, and the test covers the three known ones.
- **Re-levelled headings.** A user style keyed on the tag would move. Workbench has none.

**Calls only Troy can make:**
- **31-C1: speaker labels.** Recommended: off by default, as a Display setting. This is taste call C14.
- **31-C2: settled by Troy's standing rule (2026-10-14):** a tool result's artifact runs by itself, like an answer's. The isolated frame (RC5) is what keeps it safe, so the reviewer attacks the frame.
- **31-C3: what the README claims for Safari.** Recommended: "checked with WebKit only", until a Mac run.

## Added by Troy's answers (2026-10-21)

- **31h, MD-24: a model's reasoning rendered as Markdown,** in the same style as answers, collapsed by default. TypeScript only; size S.

## Calls answered by Troy (2026-10-22)

- **R31A-LOOP: Choice 3.** In Firefox and Safari only, Workbench detects an
  artifact that loops forever and runs only that one on a click; every other
  artifact still runs by itself, and Chrome and Edge are unchanged. Built as
  part **31i**. The detector cannot run while the page is frozen, so it works
  from evidence: a preview that started and never reported finishing before the
  page was closed or reloaded is marked, and its next showing waits for Run, with
  the reason in one line. The real fix (previews on another origin, so the
  engine gives them their own process, with no new port) stays in workbench#19.
