# Workbench rich content RC3: the run of record

Slice: RC3 of the [rich content roadmap](../design/workbench-rich-content-roadmap.md)
(content blocks and authorized assets). What building found, the calls made
and the limits left are in the roadmap's "RC3: what building found".

## The run of record

Workbench `78a3ea2` (RC3 on `17d97fd`), 2026-10-13, Chrome 155.0.8059.39 (headless,
system install), Windows 11. `tests/test_rich_tool_content_browser.py` runs a
real MCP server (the SDK's own, over streamable HTTP) whose `mixed` tool
returns words, a PNG, a WAV, a link to an outside address, an embedded HTML
page that calls itself `text/html`, embedded plain text and structured
content; the person approves the call through the API, then
`web/scripts/tool-content-browser.mjs` opens the chat afresh in the built
page under Workbench's own headers. All 22 checks passed (`1 passed in
4.31s`):

```
PASS  dark: the tool's picture is shown after a fresh load, from Workbench
PASS  dark: a sound is not fetched until asked
PASS  dark: asked for, it has its controls and does not play by itself
PASS  dark: a page that said it was a picture is a file, saying what it claimed
PASS  dark: it downloads under its own name, as the bytes it is
PASS  dark: an address the tool named is a link that goes nowhere by itself
PASS  dark: a file's words read at least 4.5:1
PASS  dark: the page's policy refused nothing
(the same 8 for light)
PASS  phone: nothing the tool returned is wider than the screen
PASS  signing out lets go of the picture's address, so it cannot be shown again
PASS  and of a download's address, which no view holds
PASS  every request went to Workbench itself
PASS  the browser reported no refusal by the policy
```

"Lets go" loads each `blob:` address as an image before and after signing
out: it shows before, and is gone after. A picture's address is let go twice
over (its view lets go of it as the chat closes, and signing out lets go of
every one), so the second check takes a download's, which no view holds for
the 10 s the download keeps it: only signing out can let that go. (The page's policy refuses
a `fetch` of a `blob:` address, `connect-src 'self'`, so the first form of
this check counted its own refusal; and signing out first ended the session
the light run needed, so it runs last.)

The rules the browser cannot see are the backend's tests
(`tests/test_tool_content.py`, 20): every kind of block kept in order and
said to the model; a page, an SVG and a GIF that call themselves pictures
are files; what cannot be kept says why (bad base64, over a limit, no
bytes); 8 files a call and 1 GiB a person; structured content said once;
64 blocks; the mixed tool through an answer, shown after a refresh, served
as `private, no-store` under `sandbox`, the page as an
`application/octet-stream` attachment, 404 to another person and to the
install owner, replayed as words with no file id; a chat's deletion takes
its tool files; an orphan removed and a named file kept; a job site's
picture kept, and hidden from the install owner as its message is; an
upload after a site's result hidden too, and one before it not; the words
kept on a call capped where the model's are; NaN data not kept; names
without paths; a full disk saying so; a stopped call's file let go.

The checks RC3 could have broken passed unchanged: diagrams
(`test_rich_diagram_browser.py`, 84), formulas (`test_rich_math_browser.py`,
66), reading (`test_reading_browser.py`, 89) and tools (`test_tools.py`, 30,
its browser test included).

## Unit tests and gates

- web: **3,140 passed** (77 files); typecheck, lint and format clean. New:
  `ToolContent.test.tsx` (10).
- Python: the whole suite, 1,967 passed and 25 skipped (the browser checks),
  with one failure: `test_memory_store.py`'s own pin of schema 13, which the
  migration to 14 moved, as it moved four other tests' pins. Pinned to 14,
  that file passes (16). ruff, format and `mypy src` clean.
- The same commit's neighbour, `17d97fd`, makes Workbench's mascots the
  website's again (CI's check of that had failed since RC1) and serves them,
  as working scenes are served, with the policy that lets their own style
  run.

## The review

One adversarial review; no authorization hole found: a second person and the
install owner were denied through every route, and a tool file cannot be
sent as an attachment (the send checks uploads only). Fixed: the words kept
on a call were stored whole while only the model's copy was capped (now
capped alike); a NaN in structured content made the chat unloadable (now
not kept, saying why); a stopped call could leave a file no answer names
until the next start (now let go when the answer ends); a `.part` file left
by a failed write; a full disk failing a site's whole answer (now that
file's block says so); a tool's name for a file kept as given (now no path
or control character, and a picture named for what its bytes are). Left as
limits: a direct MCP server's response is capped at 2 MiB (pictures to about
1.5 MiB that way); two answers at once can pass the per-person total by one
call's 20 MiB; a picture opened in a tab of its own is let go with the
message.

## Sabotage

`scripts/check-tool-content-sabotage.py`, scoped to RC3's code: **29 of 29
caught** (28 unit cases and 1 browser case), the tree restored byte-identical
each time (status and hashes compared) and the page rebuilt.

The first pass caught 27 of the 28 unit cases and stopped at the browser
case. Each of the three misses was the instrument's:

- **"Bytes that are not base64 are read anyway" changed nothing.** The test's
  `not base64!` fails to decode with or without validation. It is now
  `aGVsbG8=*`, which is valid once the `*` is dropped.
- **"Signing out does not let the files go" broke the build.** Removing the
  call left its import unused, and `tsc` refused it before any check ran. The
  call is now only named, not made.
- **That case then escaped**, for the reason the check above now covers: a
  picture's address is let go by its view as well.

Each was rerun on its own: 1/1 caught each time.

## Bundle

The page's own script: 963.62 KB to 969.63 KB (279.2 to 280.87 KB gzip),
for the content view; its CSS 57.74 to 58.35 KB. Nothing of it loads
another chunk.
