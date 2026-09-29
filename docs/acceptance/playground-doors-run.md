# The playground's other doors — record

**2026-09-28 (late). Built, run in a real browser and pinned in both
installers** (ui `dist` `a81c8f4`, built from ui `c2cc39e`; gateway
`3419414`). Design: [`playground-doors.md`](../design/playground-doors.md),
Troy's four calls of 2026-09-28 (a door picker in the playground,
diagnostic depth, a confirmation before video and images, moderation left
out).

| Slice | What | Commits |
|---|---|---|
| U1, U3 | The door picker (`?door=`), the shared request layer, Completions | ui `ef84177` |
| U2 | Chat: recordings, PDFs, spoken replies | ui `55662de` |
| U4 | Speech, Transcription; the gateway says what served them in headers, and CORS exposes them | ui `abee1e2`; gateway `d29ac67`; contract `0ab7816` |
| U5 | Images; every door reads its saved form when its state is made | ui `6ea70a9` |
| U6 | Video | ui `b055064` |
| U7 | The browser run; completions say what served them | ui `c2cc39e`; gateway `3419414`; contract `026daab` |

- **`scripts/playground-doors-acceptance.py`: 11 of 11 PASS**, fourth
  execution. A signed install (control root, agent, gateway) with drivers
  in front of the P2–P6 gates' own fixture backends, the agent serving
  the UI, and the system Chrome walking every door
  (`ui/e2e/playground-doors.spec.ts`). Not in CI, like every browser run
  here: it needs Chrome, Node and the agent's environment.
- **Sabotage: 92 of 92 caught** across the slices (U1+U3 22, U2 25, U4 16
  in the UI and 5 in the gateway, U5 11, U6 11, U7 2). Two escaped first,
  and each needed a test, not a fix: a warning whose text was removed left
  an empty element the test only looked for, and a mask picked under one
  model and sent after switching to one that takes none had no test.
- **UI suite 1374 tests**; gateway 981.
- **Every acceptance script specs CI runs passed locally before the pin.**

## What the browser saw

| Check | Observed |
|---|---|
| Completions | `" a + b"` filled between the prompt and the suffix; served by `coder` |
| Speech, through the agent's proxy | an MP3 playing in place; served by `audio` |
| Speech, direct to the gateway | the same, with `audio` read off `x-eugene-plexus-driver` across origins |
| Transcription | "The quick brown fox jumps over the lazy dog." |
| Translation | "The fast brown fox jumps over the lazy dog." (`whisper-1`) |
| Images | a PNG the browser decoded, after the spending was confirmed |
| Image edit | a picture changed with a mask (`gpt-image-1`) |
| Video | a job watched to Finished and the MP4 fetched |
| Chat, a recording | answered (200) |
| Chat, a PDF | answered (200) |
| Chat, a spoken reply | a WAV playing, `pcm16` with a header put in front |

## Found

- **`/v1/completions` never said what served it.** `CompletionResponse`
  named `x_eugene_plexus` since P6b and the gateway never set it, and the
  stream had nowhere to carry it. The browser's report read an empty
  driver for a real completion. The answer carries it now, and so does a
  stream's finishing frame (`CompletionChunk`, contract `026daab`), as
  chat's final frame does. The P6 gate asserts it.
- **Speech and transcription had no way to say what served them**: the
  speech body is the audio, and a `text` transcript has no body for it.
  They carry the envelope as `x-eugene-plexus-*` headers now, as
  `/v1/messages` does, and the front door's CORS **exposes** those
  headers. Without that, a page in direct mode could not read them, since
  a browser hides every header not named.
- **A saved form loaded in an effect overwrote a fast choice.** Every door
  read its stored form after the first paint, so a click that landed first
  was undone. Two page tests went flaky on it. Each door reads its form
  when its state is made, and the speech voice and format are worked out
  while rendering.
- **A conversation holding a recording cannot move to a model that cannot
  hear.** The gateway refuses rather than drop the recording, which is
  the rule. The spec starts each chat step with a new conversation.
- **P4's fixture JPEG is bytes no browser decodes.** The run uses its real
  PNG model, so "the browser decoded it" tests the page, not the fixture.

## Not done, named

- **No live provider was used**: every door ran against the gates'
  fixtures. The gates' own `--live` runs cover the providers.
- **`/infill` has no door**, and llama.vscode's default route is still
  direct to `llama-server`.
- **Nothing is kept past a reload but the form** (Troy's call: diagnostic
  depth). A result is gone on reload.
- **The image stream has no keepalive** at the gateway; a slow first
  partial picture could meet an idle timeout. Still owed.
