# Workbench rich content RC1: the run of record

Slice: RC1 of the [rich content roadmap](../design/workbench-rich-content-roadmap.md)
(math and working footnotes). What building found, the calls made and the
limits left are in the roadmap's "RC1: what building found".

## The run of record

Workbench `b10d2fe` (RC1 on `d5aad5f`), 2026-10-13, Chrome 155
(headless, system install), Windows 11. `tests/test_rich_math_browser.py`
drives `web/scripts/math-browser.mjs` against the built page served by
Workbench itself, so the page carries its real headers (the check asserts the
policy is byte-for-byte Workbench's `CSP`). A fake gateway seeds a plain
chat; a technical answer with every delimiter, a matrix, Unicode, formulas in
a list and a table, a math fence, a polynomial wider than a phone, money, an
escaped dollar, code with dollars, two bad formulas and two footnotes; a
second answer tried again, whose shown version holds a formula that takes
KaTeX 36 s, a `\kern{-500em}` and its own `[^1]`; a draft before a search and
its answer, each with a `[^1]`; and an answer streamed a piece at a time.
Every check is one line; all 65 passed (`1 passed in 21.33s`):

```
PASS  a chat with no formula loads no formula code, style or font
PASS  the page is sent with its policy unchanged
PASS  dark: New chat opens at once while formulas are laid out
PASS  dark: every formula in the first answer is drawn
PASS  dark: each drawn formula carries MathML and its source
PASS  dark: a formula that cannot be shown is its source, saying why
PASS  dark: money and an escaped dollar stay as written
PASS  dark: code with dollars stays code
PASS  dark: a display formula is a block of its own
PASS  dark: a formula that takes too long is stopped and says so
PASS  dark: a formula that would pull its line across the page is its source
PASS  dark: the formulas after a stopped one are drawn
PASS  dark: the page kept drawing while a formula was stopped
PASS  dark: no id is used twice on the page
PASS  dark: a reference in the first answer moves to its own note and back by keyboard
PASS  dark: a reference in the first answer's second note moves to its own note and back by keyboard
PASS  dark: a reference in the second answer moves to its own note and back by keyboard
PASS  dark: the other branch draws its formula
PASS  dark: the other branch's reference moves to its own note and back
PASS  dark: no id is used twice with the other branch shown
PASS  dark: a formula reads at least 4.5:1
PASS  dark: a formula's source reads at least 4.5:1
PASS  dark: the page's policy refused nothing
PASS  dark phone: nothing is wider than the screen
PASS  dark phone: a display formula wider than the column scrolls in its own box, by keyboard too
PASS  dark 200% zoom: nothing is wider than the screen
PASS  dark 200% zoom: a display formula wider than the column scrolls in its own box, by keyboard too
(the same 25 for light)
PASS  draft: the draft and its answer are each their own
PASS  draft: no id is used twice
PASS  draft: the draft's reference moves to the draft's note and back
PASS  draft: the answer's reference moves to the answer's note and back
PASS  live: half a formula shows as the text it is
PASS  live: a block not yet closed shows as its source
PASS  live: a block is not drawn before it closes
PASS  live: both formulas are drawn once written
PASS  live: each formula is laid out once, not on every chunk
PASS  live: the page's policy refused nothing
PASS  every request went to Workbench itself
PASS  the browser reported no refusal by the policy
PASS  formula code was loaded once formulas were shown
```

"The page kept drawing" is the longest gap between two animation frames while
the 36 s formula was stopped (under 250 ms); "laid out once" counts the
formulas posted to the worker while the answer streamed (exactly the two it
wrote). The policy checks listen for `securitypolicyviolation` in the page and
for the browser's refusal messages on the page's console.

Its first run failed four checks, all of the instrument: a tight list has no
`<p>` around its display formula, and the 2 x 2 matrix fits a phone, so a
polynomial wider than a phone was added. A second run failed the phone check
on the top bar, whose links scroll sideways on a phone by design; the check
now looks only at the scrollers that hold answers.

The reading check (`tests/test_reading_browser.py`, the answer stylesheet's
own) passed unchanged: 89 checks, run before the review's fixes, which
changed no stylesheet.

## Unit tests and gates

- web: **3,038 passed** (72 files); typecheck, lint and format clean. New:
  the parser (43: the four delimiters, money, code, addresses, escapes, blocks
  in lists and quotes, open blocks, reach, the search budget against built
  text), the reader and allowlist (44, against KaTeX's real output and
  hostile markup), the worker's keeper (8, a fake worker with fake timers),
  rendering (15) and footnotes (5), and the woff2-only fonts (3).
- Python: ruff and format clean; `mypy src` clean (no Python source changed).
- The font gate failed once: it pairs backticks across every component file,
  and a comment's ```` ```math ```` left an odd count. The comment was reworded.

## The review

One adversarial review (no blockers). Fixed: parsing built text such as
`\(a ` repeated to 32 KB took 3 to 6 s a chunk (now budgeted); 300 small
negative kerns passed a per-declaration cap (now capped in total); "$5, then
$x$" read money as the formula (TeX's own rule now: a bare `$` ends `$x$`);
a formula shown again while it was being skipped could stay pending; a worker
failure was cached for good (now retried when next shown); the cache had no
byte bound (16 MB now). Measuring the review's fixes found one more: a cap of
25 em on `top` refused a 40-row `aligned` (70 em), so vertical offsets went
back under the size limit. Left as limits: in the roadmap.

## Sabotage

`scripts/check-math-sabotage.py`, scoped to RC1's code: **39 of 39 caught**
(37 unit cases and 2 browser cases). The full pass caught 38, from a baseline
of 32 checks. The tree was restored byte-identical and the page was rebuilt.

The one escape was "a wide display formula widens the page", and it had two
faults:

- **The sabotage changed nothing.** It removed `max-width` and
  `overflow-x: auto` but kept `overflow-y: hidden`. When one axis is not
  `visible`, the other axis's `visible` computes to `auto`, and a block is
  already as wide as its column. So the box kept scrolling. The case now
  removes both overflow lines.
- **The phone check had a gap.** It counted `scrollWidth > clientWidth`, which
  is also true of a box that the formula spills out of. The check now also
  scrolls the box (`scrollLeft` must move) and requires the box to fit the
  window.

The case was rerun on its own with both fixes. The baseline was the full
browser check with the stronger test (`1 passed in 21.90s`). Result:
`1/1 caught; restored baseline passes`.

## Bundle

The production build of `b10d2fe`, compared with a build of `d5aad5f` (sizes in
kB; gzip from Vite, and from `gzip -9` for the worker):

| Asset | Before | After | gzip before | gzip after |
|---|---|---|---|---|
| index JS | 939.62 | 952.20 | 272.10 | 276.48 |
| index CSS | 54.90 | 56.10 | 12.17 | 12.39 |

Loaded only once an answer shows a formula:

| Asset | Size | gzip |
|---|---|---|
| `mathView` JS | 3.53 | 1.88 |
| `mathView` CSS (KaTeX's stylesheet) | 22.45 | 3.52 |
| `mathWorker` JS (KaTeX) | 259.90 | 76.70 |
| 20 KaTeX `woff2` fonts | 259.79 in all | (already compressed) |

The browser fetches a font only when a formula uses that face. The first
browser check confirms that a chat with no formula loads none of these.
