# Workbench rich content RC2: the run of record

Slice: RC2 of the [rich content roadmap](../design/workbench-rich-content-roadmap.md)
(Mermaid diagrams). What building found, the calls made and the limits left
are in the roadmap's "RC2: what building found".

## The run of record

Workbench `36be7ab` (RC2 on `b10d2fe`), 2026-10-13, Chrome 155.0.8059.39
(headless, system install), Windows 11. `tests/test_rich_diagram_browser.py`
drives `web/scripts/diagram-browser.mjs` against the built page served by
Workbench itself, under its real headers (the check asserts the policy is
byte-for-byte Workbench's `CSP`). A fake gateway seeds:

- a plain chat;
- a chat whose first answer holds a flowchart, a sequence, a class and a state
  diagram, the flowchart again, a 30-step flowchart wider than a phone, a
  diagram that tries everything (its own `%%{init}%%` with loose security,
  HTML labels and a `themeCSS` that would fetch, HTML in a label, a shape
  that is a picture from an outside address, a click callback and a
  `javascript:` link), one that does not parse, one Mermaid has no kind for,
  one over 20,000 characters, and a Python block; a second answer tried
  again, whose first version holds a pie chart and the same flowchart, and
  whose shown version holds 100 nested subgraphs (20 s in Mermaid, measured)
  and an ER diagram after it;
- a chat with one of every other kind drawn (Gantt, user journey, timeline,
  Git graph, mind map, quadrant, XY);
- an answer streamed a piece at a time.

Each check is one line; all 84 passed (`1 passed in 38.83s`). The 35 for the
light theme repeat the dark ones:

```
PASS  a chat with no diagram loads no diagram code
PASS  the page is sent with its policy unchanged
PASS  dark: New chat opens at once while diagrams are drawn
PASS  dark: a diagram screens away is not drawn until it comes near
PASS  dark: every diagram in the first answer is drawn, named by its kind
PASS  dark: a diagram that cannot be drawn is its source, saying why
PASS  dark: its source is shown as written
PASS  dark: plain code stays code
PASS  dark: the same diagram twice, and in another answer, is drawn once
PASS  dark: a diagram's links, handlers, HTML and outside addresses are gone
PASS  dark: what the label said is its text
PASS  dark: a diagram that takes too long is stopped and says so
PASS  dark: the diagram after a stopped one is drawn
PASS  dark: the page kept drawing while a diagram was stopped
PASS  dark: no id is used twice on the page
PASS  dark: the other branch draws its diagrams
PASS  dark: switching branches draws nothing twice
PASS  dark: no id is used twice with the other branch shown
PASS  dark: Source shows the diagram's source, by keyboard
PASS  dark: and the diagram again
PASS  dark: Copy copies the source
PASS  dark: Expand opens the diagram on its own, by keyboard, with Close first
PASS  dark: Zoom in makes it larger
PASS  dark: Escape closes it and returns to Expand
PASS  dark: SVG downloads the drawing, and nothing it must not hold
PASS  dark: PNG downloads at twice the diagram's size
PASS  dark: a PNG is at most 4,096 pixels a side
PASS  dark: a diagram's text reads at least 4.5:1
PASS  dark: the picture is in this theme's colours
PASS  dark: the page's policy refused nothing
PASS  dark: every other kind Workbench draws is drawn, named by its kind
PASS  dark: and holds nothing it must not
PASS  dark: the page's policy refused nothing for them either
PASS  dark phone: nothing is wider than the screen
PASS  dark phone: a wide diagram fits the column, and Expand shows it at size
PASS  dark phone: a diagram's name and tools fit one row
PASS  dark phone: the larger view fills the screen, and nothing moves
(the same 35 for light)
PASS  a theme's pictures are its own
PASS  a change of theme draws the diagram in the new colours
PASS  live: a diagram not yet closed shows as its source
PASS  live: a diagram is not drawn before its block closes
PASS  live: the diagram is drawn once written
PASS  live: the diagram is drawn once, not on every chunk
PASS  live: the page's policy refused nothing
PASS  every request went to Workbench itself
PASS  the browser reported no refusal by the policy
PASS  no diagram opened a dialog of its own
PASS  diagram code was loaded once diagrams were shown
```

"The page kept drawing" is the longest gap between two animation frames
while the 20 s diagram ran and was stopped (under 250 ms). "Drawn once"
counts the diagrams posted to the worker. "Holds nothing it must not" reads
each picture's SVG in Node: no `script`, `foreignObject`, `a`, `image`,
`iframe` or `style` element, no handler, no `href` outside the drawing, no
`url()` but `url(#id)`, no `javascript:` and no outside address in any
attribute. The text check is on the colour pairs the palette puts text on,
read from the page's own CSS in each theme (21 pairs, each at least 4.5:1).
The phone runs with reduced motion: the larger view starts no animation.

Debug runs before the record found the defects the roadmap section names:
the link that moved its node to the corner, the user journey's invisible
section names, the black timeline and mind map, the dialog's first focus on
Zoom out, two rows of tools on a phone, and a larger view that opened a
long flowchart at 10%. They also found three faults in the instrument: the
check's own `DOMParser` reading of each SVG counted as refusals by the page's
policy, Windows' clipboard reads back `\r\n`, and a phone's 44 px buttons made
"one row" a matter of middle lines, not height.

The checks RC2 could have broken passed unchanged: the formulas
(`tests/test_rich_math_browser.py`, 66 checks, `1 passed in 21.77s`; its
worker keeper is now shared) and the reading check
(`tests/test_reading_browser.py`, 89 checks, `1 passed in 60.77s`).

## Unit tests and gates

- web: **3,130 passed** (76 files); typecheck, lint and format clean. New:
  Mermaid itself in the stand-in DOM in Node (25: every kind drawn, the
  stylesheet inlined in the page's colours, parse errors, kinds refused,
  ELK refused, the source cap, a directive and front matter that change
  nothing), the stand-in's geometry and stylesheet (10), the page's allowlist
  (40: hostile trees, escaping, prototype names, duplicate spellings, open
  quotes, limits, values), and the block, its tools, the keeper's limits and
  the palette (17).
- Python: ruff, format and `mypy src` clean.

## The review

One adversarial review; no blockers, and no way found to script, handlers,
navigation or an outside fetch through the page's allowlist. Fixed: `xlink:href`
written without its namespace (the picture would not parse: now `href`);
tables that found `constructor` through the object prototype (now maps);
two spellings of one attribute written twice; a quote the `;` split left
open; a late error from an ended worker able to fail the next job (also in
RC1's keeper); a path with a number after `Z` looping (the 4 s limit held
it); the cache not counting the picture's address; the larger view closed
by React's development run; a change of theme dropping an open view (the
old picture now stays until the new one is drawn); and one answer's slow
diagrams queueing ahead of the one being read (a diagram now waits until it
comes near the screen).

## Sabotage

`scripts/check-diagram-sabotage.py`, scoped to RC2's code: **30 of 30
caught** (26 unit cases and 4 browser cases), from a baseline of 24 checks.
The tree was restored byte-identical (status and hashes compared before and
after) and the page rebuilt.

## Bundle

The production build of `36be7ab`, against RC1's (`b10d2fe`), in kB:

| Asset | RC1 | RC2 | gzip RC1 | gzip RC2 |
|---|---|---|---|---|
| index JS | 952.20 | 963.62 | 276.48 | 279.2 |
| index CSS | 56.10 | 57.74 | 12.39 | 12.71 |

Loaded only once an answer shows a diagram: the worker entry (0.65), linkedom
and the stand-in (199.97; 69.45 gzip), Mermaid's core (636.48; 125.93 gzip),
the allowlist (4.86), and the code for each kind as it is first drawn
(flowchart and its layout loaded at the worker's start). All of Mermaid's
kinds are in the build, 7.4 MB of assets in all, whether used or not. The
first check confirms that a chat with no diagram loads none of it.
