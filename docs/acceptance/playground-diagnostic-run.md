# The playground as a diagnostic — acceptance run

**2026-09-13 (late). 15 numbered checks, 28 `PASS` lines, zero
failures on the third attempt.** `scripts/playground-diagnostic-acceptance.sh`.
Install-paths §9 step 8; design
[`playground-diagnostic.md`](../design/playground-diagnostic.md).

Contracts `0749c54` (prose only); gateway `f48b7c2`; `ui` `f3dcce1`
(dist `552afff`). The other four consumers are not re-pinned:
nothing in `0749c54` reaches a generated model, confirmed by regenerating
the gateway and getting back only the header comment.

## What ran

Five processes on this Windows box, +100 from the defaults — agent on
**8179** serving the UI, its declared control root (8183), gateway (8180)
and library (8182), and one inference-driver (8191) fronting the local
Ollama with **`qwen3-coder:30b`**, the model step 6 proved calls tools.
Then **the system Chrome**, driven by Playwright, through the
playground's new direct mode: the browser dialling the gateway's own
port with a bearer, no proxy.

The script drops every ambient `EUGENE_PLEXUS_*` variable before
starting anything and tears down by pid — the agent's, then whichever
pids still hold the ports it opened. This box is a live worker node of
the two-machine install, so the install's own agent on 8079 ran
untouched throughout.

## The headline

**A browser on `http://127.0.0.1:8179` completed a streamed chat turn
against `http://127.0.0.1:8180/v1/chat/completions` with the session
token as its API key, made a tool call, closed the loop, read an
attached file, and produced a `curl` line that replayed the same request
from a shell.** The gateway had answered that browser's preflight
`405 Method Not Allowed` the same morning.

```
direct · HTTP 200 · 0.13s · first frame 0.13s · 3 frames · finish stop · driver diag-ollama
tool call · call_4jm79ldf get_weather · arguments parse · {"city":"Oslo"}
tool result · call_4jm79ldf {"tempC": -3, "sky": "snow"}
attachment: answer carried CANARY-02RPDZ; prompt_tokens 372 vs 15 for the first turn
replay: 11 frames with the envelope and [DONE]
wrong port: status=404; report names the URL
proxy: via agent proxy · HTTP 200 · 0.16s · first frame 0.15s · 3 frames · driver diag-ollama
```

Row two of the design's §1 table — *works through the proxy, fails
direct* — was reproduced on purpose in check 14: the base URL pointed
at the agent's port, direct mode reported a 404 naming that URL, and the
same message went through the proxy at once. That is the bisection the
instrument exists for, performed once, on record.

## What the three attempts taught

**Attempt 1 — a selector picked the wrong subject.** The spec sent its
message to `locator("textarea").first()`, which the auth arc uses too.
With the diagnostic panels open the first textarea on the page is the
tools editor, disabled while tools are off, and the spec waited sixty
seconds for it to become enabled. Every gateway-side check (0–8) had
already passed. The composer has a test id now and the spec names it.
Same family as M9's *"a check looked somewhere its subject had not
arrived"*: a selector that does not name its subject picks whatever is
first.

**Attempt 2 — the reproduction could not reproduce, twice over.**
Everything passed except check 13, the replay of the copied `curl` line,
which the gateway answered `{"detail":"There was an error parsing the
body"}`. Two defects in the line, both real and both in the UI:

1. **The key placeholder was single-quoted.** `-H 'Authorization: Bearer
   $EUGENE_PLEXUS_TOKEN'` sends the literal dollar sign. A user who
   exports the variable and pastes the line gets a 401 — masked here by
   the body error, because FastAPI parses the body before it runs the
   auth dependency. Double quotes now.
2. **Non-ASCII in the body does not survive a Windows shell.** The model
   had answered `-3°C`; the degree sign rode into the transcript and so
   into the replayed body. Measured against a local echo server: bash
   parsed the argument correctly (4,663 bytes, valid JSON) and the
   `mingw64` curl received 4,662 — the two-byte UTF-8 sequence for `°`
   arrived as one byte, because the argument crossed the Windows command
   line through the ANSI code page. The line is correct for a POSIX
   shell and wrong for the shell Windows users of this project actually
   have. The builder escapes every character outside ASCII as `\uXXXX`
   now: the same JSON value, and pure ASCII. The design's §6 said "byte
   for byte"; it says "the same document, ASCII-safe" now and explains
   why.

**Attempt 3 — green.** No change between the second and third attempts
except those two lines of the builder.

## The checks

| #  | Claim                                                                      | Evidence                                                                                  |
| -- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 0  | isolated from the live install                                             | no `EUGENE_PLEXUS_*` survives into the run                                                |
| 1  | four processes up; the UI at `/`                                           | `<html` from the agent's root                                                             |
| 2  | the model is routable with tools                                           | `tool_calling: true` on `/v1/models`, within a bounded wait                               |
| 3  | Chrome's preflight is answered                                             | `204`, `Access-Control-Allow-Origin: *`, requested headers echoed                         |
| 4  | a real response carries the header                                         | `GET /v1/models` with `Origin`                                                            |
| 5  | operator paths do not                                                      | `OPTIONS /v1/config` → 405, no header                                                     |
| 6  | `corsAllowedOrigins` narrows live                                          | `requiresRestart: false`; listed origin echoed + `Vary: Origin`; other → 403 naming the key |
| 7  | `corsEnabled: false` live, and back                                        | 403 naming `corsEnabled`; 204 again in the same process                                   |
| 8  | the session token is the harness's bearer                                  | a completion with it, served by `diag-ollama`                                             |
| 9  | **browser**: prefilled, direct, streamed                                   | `http://127.0.0.1:8180/v1` prefilled; key = session token; 3 frames; driver in the envelope |
| 10 | **browser**: the example tool is called                                    | a `get_weather` card, arguments parse, name `city`, 1 tool-call delta                     |
| 11 | **browser**: the loop closes                                               | the typed `{"tempC": -3, "sky": "snow"}` sent back as a `tool` message; answered          |
| 12 | **browser**: an attachment is read                                         | the canary came back; `prompt_tokens` 372 vs 15                                           |
| 13 | the copied `curl` replays from a shell                                     | 11 frames, `x_eugene_plexus`, `[DONE]`                                                    |
| 14 | **browser**: wrong port fails with a named 404; the proxy still works      | `404` at the agent's port, URL in the report; then `200` via proxy                        |
| 15 | teardown by pid                                                            | no owned port still listening                                                             |

## Worth not rediscovering

- **Three frames is what a five-token answer looks like.** The streamed
  checks assert `frames > 1`, not a large number: "ok" is one content
  delta, plus the role frame and the terminal one. A check demanding
  more would be asserting a property of the prompt.
- **The first frame at 0.13 s of a 0.13 s request** is the model
  answering in one delta, not a buffering path. The clock is the
  instrument; the frame count is corroboration.
- **`String.raw` in a vitest file did not keep `°` raw** — the
  transpiler evaluated the escape and the expectation compared the
  degree sign to its escape. Doubled backslashes in an ordinary string
  did what was meant.
- **The browser results file is how the shell reads the browser.** The
  spec writes one JSON object per named check with the evidence beside
  it, and the script's `browser_check` turns each into a `PASS` line
  with that evidence — so the acceptance record quotes what the browser
  observed rather than that a test passed.

## What this run does not cover

- **Two real origins.** Page and gateway were both loopback; the live
  two-machine install (page on `192.168.16.75:8079`, gateway on
  `192.168.16.252:8280`) is where CORS between two hosts and Chrome's
  local-network permission are real. The panel's hints cover the shapes;
  nobody has clicked through them there. Troy's to run after the
  container is updated to a gateway at or past `f48b7c2`.
- **A tool call that fragments.** Ollama emits the whole call in one
  delta (`tool-call deltas=1`); the accumulation of split `arguments` is
  unit-tested against OpenAI's shape and live-tested nowhere, as step 6
  recorded.
- **`response_format: json_object`** is on the request panel and was not
  sent in this run.
- **A truncated attachment.** The file was small enough to arrive whole
  (`prompt_tokens: 372`); the step 7 badge for a dropped middle is on the
  same report and was not provoked here.
