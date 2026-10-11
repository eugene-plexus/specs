# Workbench reading: the run of record

Design: `docs/design/workbench-reading.md` (its header says what was built
and every call made while building). Troy, 2026-10-10: Workbench read "dry";
he wanted the console's "small splashes of color" on headers and boundaries,
and reading and using Workbench to be a pleasure.

## Before and after, measured

The reading check (`tests/test_reading_browser.py` driving
`web/scripts/reading-browser.mjs`) runs the real Workbench over a fake
gateway in Chrome, seeds a technical answer (headings, a table, code, lists,
a quote, a rule, a task list), a story, a cut-off answer and a running one,
and photographs every screen, dark and light, at 1440 x 900 and 390 x 844.

| | Before (main `530740f`) | After |
|---|---|---|
| Answer text | 16 px / 1.6 | 17 px / 1.65 |
| Characters a line | 109 | 74 on average, 78 at most |
| h2, h3 | 16 px, the body's size and colour | 1.25 and 1.1 times the text, a warm tone, h2 on a hairline with an apricot segment |
| Text colours on the chat page | 3 (body 72%, muted 23%, links 5%) | body, strong, heading, warm code, link, muted, faint |
| Bold | the body's colour | a brighter tier (dark), the body softened to `#202023` (light) |
| A `---` rule | 1 px in the text colour (14.8:1) | a hairline (under 3:1) |
| Code block | Copy bar ~8 px above its code; no colour | one box, the language named, syntax colour |
| Every text on the page | at least 4.5:1 | at least 4.5:1 (7:1 under "more contrast") |

## The run of record

Workbench main tree, 2026-10-11, Chrome 155, Windows 11. The reading check
now asserts what the design promises; each line is a check:

```
PASS  dark: an answer reads at 17 px
PASS  dark: lines are 1.5 to 1.8 times the type
PASS  dark: 60 to 85 characters a line
PASS  dark: an h2 is at least 1.2 times the text
PASS  dark: an h3 is larger than the text
PASS  dark: headings carry their own colour
PASS  dark: bold is brighter than the text
PASS  dark: inline code is a warm mark
PASS  dark: first-level bullets are marked in colour
PASS  dark: a rule is a hairline, not a bright line
PASS  dark: the Copy bar is joined to its code
PASS  dark: an answer's prose carries at least five colours: 6
PASS  dark: every text on the page is at least 4.5:1
PASS  dark phone: nothing is wider than the screen
(the same fourteen for light)
1 passed
```

Its first run failed one check: in light, bold and body were both `#0d0d10`,
so bold had no colour to rise to. Fixed by the light answer ink
(`--foreground-read: #202023`); the check stays.

Every opt-in Chrome check ran with the full suite (`WORKBENCH_PLAYWRIGHT`
set): **261 passed, 3 skipped** (Linux-only), all ten Chrome checks green.
Six of them had been failing on main before this slice (stale button names);
their scripts were repaired, no assertion weakened.

## Unit tests and gates

- web: **926 passed** (32 files), up from 261; typecheck, lint and format
  clean. New: the font gate (a weight or italic used but not loaded fails),
  the token gate (every text tier and edge against every fill, in both
  schemes and under "more contrast"), the stylesheet gate, Markdown (69:
  language label, table wrapper, task boxes, allowlist, alerts, breaks,
  highlighting as elements, focusable code blocks), and the surroundings and
  screens tests.
- Python: 251 passed, 13 skipped (Chrome opt-in); `check-vendored.py` clean.

## Sabotage

- R1 (stylesheet, Markdown, highlighting, plugins, gates): 86 cases, all
  caught.
- R2 (the chat's surroundings): 135 cases, all caught.
- R3 (the other screens): 86 cases, all caught.
- The reading check (`scripts/check-reading-sabotage.py`, each case breaks
  one rule of the stylesheet, rebuilds, and must fail on its named check):
  **12 of 12 caught**, the page rebuilt and passing after each restore. Its
  first pass caught 11: "an answer in one colour" escaped because the colour
  count included a code block's syntax colours, so a one-colour answer
  passed whenever it held code. The check now counts the prose only, at
  least five colours (the page has six in each scheme: body, bold, heading,
  warm code, muted, link), and the case is caught.

## Pinned

- Workbench main `67ac128`, `dist` `0e5ecf2`.
- agent `77ba78a` (the catalogue's Workbench: dist `0e5ecf2`).

## The live run

Owed: Troy updates Workbench from Apps (the agent never updates an app on
its own) and reads a real answer.
