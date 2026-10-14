# Workbench rich content RC6: the run of record

Slice: RC6 of the [rich content roadmap](../design/workbench-rich-content-roadmap.md)
(artifacts shown and run in place), added 2026-10-14 at Troy's call: previews
run by themselves, every answer's. What building found, the calls made and the
limits left are in the roadmap's "RC6: what building found".

## The run of record

Workbench RC6 (landed as the commit the roadmap's status names), 2026-10-14,
Chrome 155.0.8059.40 (headless, system install), Windows 11.
`tests/test_rich_artifacts_inline_browser.py` makes three chats through the API:
one answer with Markdown, an SVG, a TSX counter with a form, a short page, a
tall page, RC5's page that tries every way out of its frame, and a fifth page;
one with a page first, eighty paragraphs, then a page that grows after it
loads; one with two calm pages and a page that loops 300 ms after it starts.
The install owner may read chats. `web/scripts/artifacts-inline-browser.mjs`
then opens them in the built page under Workbench's own headers, as the person
(the switch on, as it is until they turn it off) and as the owner. All
19 checks passed (`1 passed in 68.17s`):

```
PASS  Markdown is drawn where the answer puts it
PASS  an SVG is drawn where the answer puts it, as a picture
PASS  a component runs by itself once on screen, and answers a click
PASS  its frame grows with its page, and its form runs its own handler
PASS  a short page's frame is short, a tall one's stops at most of the window
PASS  a page run by itself is refused every way out, and reaches nothing
PASS  at most 4 run at once, the one longest out of view making room
PASS  the chat stays smooth while they run
PASS  a written page that grows after it loads: its frame follows
PASS  a preview out of view does not run until it is on screen
PASS  a preview that loops is named and stopped, and the others run again
PASS  after a reload, the one that looped waits for Run
PASS  the switch is on until the person turns it off
PASS  turned off, it is kept, and previews wait for Run
PASS  turned on, the preview on screen runs
PASS  the owner's view of someone's chat runs nothing by itself
PASS  phone: the artifacts and their frames fit the screen
PASS  every request of the page went to Workbench itself
PASS  the page's own policy refused nothing
```

Measured in the same run:

```
longest frame of the chat with 4 running, 14.0 ms
the others running again 8718 ms after the loop was stopped
```

"The others running again" is from the loop being stopped to both calm pages
running: most of it Chrome ending the stuck process, while RC5's frame
retries wait for it.

RC5's own run (`tests/test_rich_artifacts_browser.py`, the person's switch
turned off first, so its previews wait for Run as RC5's checks expect) passed
unchanged: 51 PASS lines, no FAIL (`1 passed in 15.28s`). The checks RC6 could
have broken passed unchanged: Media (`test_media_browser.py`), versions,
conveniences, citations and charts (`test_rich_structured_browser.py`) and
reading (`test_reading_browser.py`).

The rules the browser cannot see are unit tests:
`web/src/lib/previewRunner.test.ts` (10: one at a time after the one before
has had its source; a preview out of view or stopped by the person waits; the
one that left the screen first makes room, never one on screen; all silent:
all stopped, the one the person was in named and remembered, the rest
started again; else the one given its source last; never one whose frame
never got its source; the line held while the one before has none; no trip
while starting, across a stall of the page's own, or while hidden; the
memory cleared at sign-out), `components/ArtifactInline.test.tsx` (11: drawn
in place; run by itself; Stop holds; the switch off and the owner's view
wait; one at a time; the frame's height and its limits; a frame that floods
the page read only so far; its height moved only so often; a Markdown
artifact holds no artifacts; nothing by itself while the answer is written;
the last revision kept; the switch shows what is kept and says when keeping
failed), `preview/runtime.test.ts` (the beat and the height), and
`tests/test_artifacts.py` (the switch: on until turned off, a person's own,
a strict yes or no).

## Unit tests and gates

- web: **3,232 tests in 85 files**; typecheck, lint, format and build clean.
- Python: the whole suite, **1,990 passed** and 28 skipped (the browser
  checks), no failure; ruff, format and `mypy src` clean.

## The review

One adversarial review; no blocker; RC5's isolation found unchanged. Fixed
from it: the watchdog would have named a healthy preview after a hidden tab
or a stall of the page's own (it now counts every running preview as heard
across such a gap, while hidden, and as the tab is shown again); a preview
could flood the chat with `size` and `alive` messages (forty a second read
from a frame, its height at most every 200 ms and by 4 px or more); the
fences inside a Markdown artifact became artifacts that ran (its own blocks
are plain, in its card and its dialog); a preview ran by itself in an answer
still being written; what is remembered of a loop is now its words too, so a
revision that fixes it runs; the runner kept a slot's key as registered;
the frame's limit followed a window that had changed. Left as limits, in the
roadmap: the person's Run may run a fifth preview; the one named is a guess
when it loops later than its start.

## Sabotage

`scripts/check-artifacts-sabotage.py`, RC5's cases and RC6's (44 unit cases
and 1 browser case): **41 of 45 caught** on the full pass, each restored from
exact bytes (413 files' hashes and `git status` the same before and after).
The four that escaped were the instrument's, and each is caught now (1/1 on
its own):

- **"The person's switch is not obeyed"** looked for a frame at once, before a
  preview that runs by itself could have started; it now waits as long as one
  takes.
- **"A frame's height moves at every message"** was checked with a burst of
  messages at one moment, where waiting for the last changes nothing; it is
  now checked with a page that grows every 20 ms for 400 ms.
- **"A Markdown artifact's own fences are artifacts that run"** wrote the
  Markdown in a three-backtick fence, which the fence inside it closed; it is
  now in four.
- **"A written page's frame does not follow its page's height"** removed the
  reporter's watch, and the tall page still had its height from the load
  event; the run now has a page that grows four seconds after it loads.

## Bundle

The page's own script: 989.52 KB to 993.08 KB (287.55 to 288.87 KB gzip),
for the switch, the runner and the cards; its CSS 64.36 to 64.75 KB. An
artifact's body is a chunk of its own (`ArtifactBody`, 9.20 KB) fetched with
the first artifact on the page, the dialog another (6.94 KB), and the
preview's runtime (426.35 KB) only by a preview's frame.
