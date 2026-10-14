# Workbench rich content RC5: the run of record

Slice: RC5 of the [rich content roadmap](../design/workbench-rich-content-roadmap.md)
(saved artifacts and isolated previews). What building found, the calls made
and the limits left are in the roadmap's "RC5: what building found".

## The run of record

Workbench RC5 (landed as the commit the roadmap's status names), 2026-10-14,
Chrome 155.0.8059.39 (headless, system install), Windows 11.
`tests/test_rich_artifacts_browser.py` makes, through the API, an answer with
eight artifact fences (Markdown notes; an SVG; an SVG with a script; an HTML
page that tries every way out of its frame; a page that loops for ever; a
page that goes elsewhere after 300 ms; a TSX counter with a form; a JSX
component that imports lodash) and a plain HTML block, and a searched answer
with Google's search suggestions. `web/scripts/artifacts-browser.mjs` then
opens them in the built page under Workbench's own headers. All 50 checks passed
(`1 passed in 16.61s`):

```
PASS  the chat's page keeps its own policy, and no page may frame it
PASS  the preview's page has its own policy: no origin, no network, framed by Workbench alone
PASS  the preview's script is Workbench's own file
PASS  dark: an answer's artifacts are cards, and nothing runs
PASS  dark: a plain block of HTML can be opened as an artifact
PASS  dark: a card's title reads at least 4.5:1
PASS  dark: Markdown reads as an answer does, opened by keyboard
PASS  dark: Escape closes it and gives focus back to Open
PASS  dark: an SVG is a picture written anew
PASS  dark: an SVG with a script is not shown, saying why, and its source is there
PASS  dark: a page runs nothing until Run
PASS  dark: the preview's parent-dom is refused
PASS  dark: the preview's top-dom is refused
PASS  dark: the preview's cookie is refused
PASS  dark: the preview's storage is refused
PASS  dark: the preview's popup is refused
PASS  dark: the preview's worker is refused
PASS  dark: the preview's service-worker is refused
PASS  dark: the preview's form-script is refused
PASS  dark: the preview's form-button is refused
PASS  dark: the preview's api is refused
PASS  dark: the preview's network is refused
PASS  dark: the preview reached nothing but its own page and script (no form, no picture, no API)
PASS  dark: it did not move the page, or change its title
PASS  dark: what it could not load is said in words, and the source stays
PASS  dark: its form is never sent, and that is said
PASS  dark: Stop takes the frame away
PASS  dark: a page that never stops leaves this page free, and Stop ends it
PASS  dark: run at once after a stuck page was stopped, a page waits, saying why, and then runs
PASS  dark: a page that tries to leave is stopped, and says so
PASS  dark: a React component runs, and answers a click
PASS  dark: a component's form runs its own handler, and sends nothing
PASS  dark: Reload starts it afresh
PASS  dark: a component that imports what is not there says so, and its source stays
PASS  dark: an edit is saved as revision 2 and downloads under the title
PASS  dark: after a reload it opens at revision 2, and revision 1 is the answer's
PASS  dark: each version of the answer keeps its own revisions
PASS  dark: the page's own policy refused nothing
PASS  light: an answer's artifacts are cards, and nothing runs
PASS  light: a plain block of HTML can be opened as an artifact
PASS  light: a card's title reads at least 4.5:1
PASS  light: Markdown reads as an answer does, opened by keyboard
PASS  light: Escape closes it and gives focus back to Open
PASS  light: an SVG is a picture written anew
PASS  light: an SVG with a script is not shown, saying why, and its source is there
PASS  light: the page's own policy refused nothing
PASS  the search suggestions' frame is as it was: inert, its chips links
PASS  phone: the dialog, its frame and Stop fit the screen
PASS  every request of the page went to Workbench itself
PASS  the browser reported no refusal by the page's policy
```

Measured in the same run:

```
refused before reaching anything: https://cdn.example.com/lib.js csp | http://127.0.0.1:65223/api/me?from=img csp
busy preview, page frame gap 0.4 ms; Stop 21 ms
run at once after Stop of a stuck page, it ran in 6818 ms
the leaving page's address was never asked for
```

"Refused before reaching anything" lists the requests Chrome reported and
refused under the preview's policy (a request event, then a failure, and no
response): only a response would mean something reached a server, and the
preview got none but its own page and script. The leaving page was stopped as
it began to go; its address was never asked for in this run, but a page can
get its request out first (the roadmap says so).

The rules the browser cannot see are unit tests: `tests/test_artifacts.py`
(16: the digest Python and the page compute alike; the answer's block found
in order, set in by a list, not from lines apart; kept at the first save as
revision 1 by the answer and the edit as revision 2, in one transaction;
an edit begun before the last revision refused; the same words no new
revision; each version of an answer its own; nothing kept while an answer is
written; limits of size, revisions, artifacts a message and a person's bytes;
another person 404 everywhere; the install owner reads and never writes; an
artifact of a message hidden from the owner 404; a chat's deletion takes them;
a request with a character that is no text a 422; the preview's headers and the
chat's), `web/src/components/Artifact.test.tsx`, `lib/artifacts.test.ts` and
`preview/runtime.test.ts`.

The checks RC5 could have broken passed unchanged: the Media screens
(`test_media_browser.py`, `test_media_audio_browser.py`,
`test_media_video_browser.py`), versions, conveniences, tool content (22),
citations and charts (34), diagrams (84) and reading (89).

## Unit tests and gates

- web: **3,210 tests in 83 files**; typecheck, lint, format and build clean.
- Python: the whole suite, **1,989 passed** and 27 skipped (the browser
  checks), no failure, before the last change (forms allowed in the sandbox,
  which changed the preview's policy and its test); after it, the artifact,
  schema, conversion and page tests again, 66 passed. ruff, format and
  `mypy src` clean.

## The review

One adversarial review; no blocker, isolation and authorization found sound.
Fixed from it: the Run caption claimed no network, where a page may still go
to another address itself (it now says such a page is stopped, and the
roadmap says the first request may go out); "from the answer" was given to a
block made of the answer's lines in any order, and to an empty one (now its
lines in order, never empty); a lone surrogate in any request's JSON made
FastAPI's own refusal an error of the server's (Workbench now writes that 422
itself, on every route); the first save kept the block even when its edit was
refused (now one transaction); an edit begun from an older revision was put
after a newer one saved in another tab (now refused, saying so, and kept on
the page); switching to Source stopped a running preview (both panels now
stay); "1 revisions" in an export; Home and End on the tabs. Left as limits:
the preview's `script-src 'self'` lets it load Workbench's own scripts (no
cookie goes with them from a page with no origin, and none is a way out
today); the dialog names its message by being opened from it.

## Sabotage

`scripts/check-artifacts-sabotage.py`, scoped to RC5's code (27 unit cases
and 1 browser case, on RC3's runner): **28 of 28 caught**, each restored from
exact bytes (all 28 backups compared byte for byte with the files after, and
`git status` the same before and after).

The first pass caught 27. The miss, "a written page's form is sent", removed
the reporter's override of `form.submit()`, and the run still passed: the
preview's own script had already overridden it, and that survives the page
being written (`document.open` clears listeners, not the window's
prototypes). The duplicate is gone, and the case now removes what only the
reporter does. Chasing it found that a sandbox refusing forms fires no
`submit` at all, so a button's sending went straight to Chrome's refusal (and
the stuck process), and a component's form did nothing; hence `allow-forms`
with the sending stopped (the roadmap). The case is now "a written page's
form is sent by its button", against a test page that sends by script and by
its button.

In the final pass the runner's re-check of its 21 checks on the restored
tree reported a failure and then could not print it (its stdout was a
Windows code page and vitest's output holds `❯`); the same 21 checks run
again on that tree all passed. The runner now prints such output instead of
stopping on it.

## Bundle

The page's own script: 984.55 KB to 989.52 KB (285.66 to 287.55 KB gzip); its
CSS 61.02 to 64.36 KB. The artifact dialog is its own chunk (12.20 KB, 4.73
gzip), fetched when an artifact is first opened; the preview's runtime
(`preview/runtime.js`, 425.76 KB, 116.03 gzip: React and sucrase) is fetched
only by a preview's frame, at Run. A chat of words alone fetches neither (the
runtime: checked, no request for the preview's page before Run; the dialog: by
construction, a lazy import, not measured).
