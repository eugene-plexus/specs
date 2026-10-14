# Workbench rich content RC4: the run of record

Slice: RC4 of the [rich content roadmap](../design/workbench-rich-content-roadmap.md)
(citation navigation and structured tables and charts). What building found,
the calls made and the limits left are in the roadmap's "RC4: what building
found".

## The run of record

Workbench RC4 (uncommitted tree, landed as the commit this record names in
the roadmap's status), 2026-10-14, Chrome 155 (headless, system install),
Windows 11. `tests/test_rich_structured_browser.py` makes, through the API: a
searched answer citing a Markdown link and a bare address in place and a third
page with no place, tried again for a second version with its own source; an
answer citing a passage of a saved document as `[1]`, and `[9]`, which no
passage has; an answer with two charts asked for in `chart` fences, a table
and one that cannot be drawn; and a tool's chart through RC3's MCP server
(`plot`). `web/scripts/structured-browser.mjs` then opens each chat afresh in
the built page under Workbench's own headers. All 33 checks passed (`1 passed
in 4.85s`):

```
PASS  dark: a web source's number follows the link it cites
PASS  dark: a source the gateway gave no place has no number, only its line in Sources
PASS  dark: a number moves to its source, by mouse and by keyboard, and the address stays
PASS  dark: in the other version, its own number moves to its own source
PASS  dark: a number no passage has stays words
PASS  dark: a passage's number opens that passage, by keyboard
PASS  dark: a bar chart draws a bar a point, each series in its own colour
PASS  dark: the chart is named for a screen reader
PASS  dark: a chart's words read at least 4.5:1
PASS  dark: its numbers are a table a click away
PASS  dark: its CSV is data: a cell a spreadsheet would run is written as words
PASS  dark: a table sorts by a column at a click
PASS  dark: a chart that cannot be drawn is its source, saying why
PASS  dark: a tool's chart is drawn under its call
PASS  dark: the page's policy refused nothing
(the same 15 for light)
PASS  phone: a chart and a table fit the screen (a wide table scrolls in its own box)
PASS  every request went to Workbench itself
PASS  the browser reported no refusal by the policy
```

The rules the browser cannot see are unit tests: `tests/test_citations.py`
(5: places in the page's count past an emoji; a place re-anchored on the
address nearest the gateway's index when the gateway's count drifts; an
address written twice cited where the gateway says; none made up where the
text does not hold the address; older messages without places),
`web/src/lib/chartSpec.test.ts`, `components/MarkdownCitations.test.tsx` and
`components/Structured.test.tsx`.

The checks RC4 could have broken passed unchanged: tool content
(`test_rich_tool_content_browser.py`, 22), diagrams (84), formulas (66),
reading (89) and the Library (`test_library_browser.py`, 26).

## Unit tests and gates

- web: **3,171 tests in 80 files**; typecheck, lint, format and build clean.
  The first run failed the font gate three times over one cause: two comments
  wrote a `chart` fence with three backticks, an odd count, so the gate's
  reading of string literals paired backticks across files and found
  `font-mono` and `font-semibold` in one "literal". The comments now write
  `chart` fence; the gate passes (7).
- Python: the whole suite, 1,972 passed and 26 skipped (the browser checks),
  with one failure under load: `test_signed_calls.py::
  test_declining_a_held_call_runs_nothing` waited 15 s for its answer while
  the browser checks ran beside it; on its own its file passes (4). ruff,
  format and `mypy src` clean.
- CI for RC3's commit failed the page job on two tests this slice fixes:
  `ToolContent.test.tsx` built a `Response` from jsdom's `Blob`, which Node
  22's `Response` cannot read (locally Node 24 can; it now gives words), and
  a timing bound in `markdownMath.test.ts` met a loaded runner (1.7 s against
  1.5 s; the unbounded parse took 3 to 6 s, so the bound is now 2.5 s).

## The review

One adversarial review; no blocker. Fixed from it: a citation anchored on the
gateway's index alone (the drift above, found by this review and filed as
gateway#16); a tool's chart read again on every token; numeric bar positions
drawn as a scale, not categories; the chart region named; footnote
definitions and links left without passage numbers; chart words larger on a
phone; a tick loop with no guard for a range of one value; caps on magnitude,
empty series and a table's characters; a CSV cell with a formula after
leading spaces.

## Sabotage

`scripts/check-structured-sabotage.py`, scoped to RC4's code: **12 of 13
caught** on the first pass (12 unit cases and 1 browser case), the tree
restored from exact bytes each time. The one that escaped, "a citation's
number changes the address", removed the click's `preventDefault`, and the
unit test still passed: jsdom does not change the address for a `#` link, so
its check that the hash stayed empty could not fail. The test now asserts the
click was prevented; rerun by hand on its own, the sabotage is caught (1/1),
and the browser run's own check of the address stands beside it.

## Bundle

The page's own script: 969.63 KB to 984.55 KB (280.87 to 285.66 KB gzip),
for citations, charts and tables; its CSS 58.35 to 61.02 KB. No chart
library; nothing of it loads another chunk.
