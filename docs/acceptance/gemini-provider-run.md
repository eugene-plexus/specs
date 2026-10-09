# Gemini provider: a Google account of the user's own — run record

**Date:** 2026-10-09. **Design:**
[`gemini-provider.md`](../design/gemini-provider.md) (G1-G4 taken by Troy,
G5-G15 taken by building for him to confirm, *What building found*).
**Issue:** inference-driver#4. Built while Troy was away; the live run waits
for his `GEMINI_API_KEY`.

A driver with `provider: gemini` is one Google account: every model its key
may use, from Google's own listing, on the surfaces Eugene routes (chat,
embeddings, images, Veo video, speech, transcription), through Google's
native API rather than its OpenAI-compatible one (G1), with the thought
signatures a Gemini 3 model needs kept by the driver (G2).

| Repo | Commit | What |
|---|---|---|
| specs | `7c6178c` | contract: `gemini_api` in `BackendKind`; the design |
| inference-driver | `2fc66c7`, `7d22ac9` | the `gemini` provider and `gemini_api` engine (`engines/gemini_api.py`, `engines/_gemini_wire.py`), `GEMINI_API_KEY` fallback, `/v1/speak` defaults to the engine's own format; 65 tests (`tests/test_gemini.py`) |
| gateway | `b08efe0` | an unnamed speech format on a model with no mp3 gets the model's own (G11); regenerated |
| ui | `1b85f24`, dist `cfaa45d` | "Google Gemini API" in Add backend and on Inference; regenerated (dist `137fe64` and `3605321` under it carried main's source by mistake and are not pinned) |
| workbench | `1238dbe`, dist `2e52108` | the media screens name a Gemini account "Google Gemini" |
| agent | `80ca3bf` | catalogue: Workbench dist `2e52108` |
| specs | this push | `scripts/gemini-acceptance.py` (new, in CI), pins in both installers and `release/manifest.json` |

## What was run

**`scripts/gemini-acceptance.py` — 8 passed**, 2026-10-09, the run of
record, against the working trees (interpreter the agent's venv; the OpenAI
SDK 3.20.0 from its own interpreter). A control root, an enrolled agent, a
gateway and a `provider: gemini` driver whose `baseUrl` is a fixture playing
Google's native API as its documentation described it on 2026-10-09:

| Check | What passed |
|---|---|
| 1 | the account's listing read in two pages; six models published as `gem/<id>` with Google's window, each on its own surface (chat, embeddings, image, video, speech with Gemini's 30 voices and `wav`/`pcm`, transcription); Imagen (`predict`) and `aqa` not routed |
| 2 | chat through the unchanged SDK, plain and streamed (`alt=sse`): the system prompt as `systemInstruction`, `reasoning_effort: low` as `thinkingLevel: low`, thoughts back as `reasoning_content`, usage with the thoughts in the completion and the cached tokens |
| 3 | a tool call and its result, plain and streamed, from a client that cannot carry the signature: the driver put Google's `thoughtSignature` back on the `functionCall` part and the fixture's check, Google's rule, passed both times; the result went back as a `functionResponse` named for its call; tools as `parametersJsonSchema` |
| 4 | after a driver restart the same conversation is refused, as Google refuses it, and the answer says the signature was lost with the restart |
| 5 | `logit_bias` is refused naming it and never reaches Google; an answer Google stopped (`SAFETY`) is `content_filter` with its reason; an error quoting the key comes back with it redacted |
| 6 | embeddings in input order; an image; speech with no format named is a whole WAV around Google's 24 kHz PCM, and mp3 named is refused naming `wav, pcm` before anything is sent; a transcription with the audio inline as `audio/wav` |
| 7 | a 4-second 720p Veo video as a polled job (`predictLongRunning`, operation polled to `done`), downloaded through a redirect to storage followed without the key |
| 8 | the key rode `x-goog-api-key` on every request and never a URL |

**Sabotage, once each, restored from a copy:** the signature not put back
(check 3 failed: Google's refusal), the restart refusal not explained
(check 4), the key not scrubbed (check 5 — first missed, because the
fixture quoted the key as `key=…`, which a second pattern also redacts;
the fixture now quotes it bare), a redirect followed with the key
(check 7), the gateway's mp3 default back (check 6). All caught.

**CI, first run at the pins (`efd5424`):** Windows passed; Linux failed
check 4 with a 404 `model_not_found`. The script waited for the restarted
driver, not for the gateway's table, and on Linux a routing refresh had run
while the driver was down and dropped its models. The wait now waits for
the gateway to route them again, two refresh periods after the driver is up
(the script's fault, not the product's; the replay then reached Google as
before). **Green at `104d413`** on both, with every step after it (C2, C3
Workbench at its new pin, standby, Job Sites, A7); CI green in the driver,
gateway, ui, Workbench and agent at their pins.

**Unit tests:** inference-driver 1,044 passed and 5 skipped before the last
three tests were added; `tests/test_gemini.py` 65 passed after. gateway
1,254 passed, 1 skipped; the new speech test sabotaged once (fails with
the mp3 default back). ui `tsc`, `eslint` and 1,081 vitest tests. ruff,
`ruff format`, `mypy` and `mypy --platform linux` clean in the driver and
gateway; gitleaks clean over the five trees (one fake key in a test marked
`gitleaks:allow`).

## The live run

**`scripts/gemini-acceptance.py --live` — 12 passed**, 2026-10-09, with
Troy's key read into the live driver's environment only (the run of record:
the 8 fixture checks, then 4 against Google). Picked from the key's own
listing (32 chat, 3 embeddings, 6 image, 5 speech, 21 transcription, 3
video models): `gemini-3.5-flash`, `gemini-embedding-001`,
`gemini-3.1-flash-image`, `gemini-3.8-flash-tts`, `gemini-3.5-transcribe`,
`veo-3.1-lite-generate-preview`.

| Check | What passed against Google |
|---|---|
| L1 | a tool round trip on `gemini-3.5-flash` with `reasoning_effort: low`, plain and streamed: the call made, its result sent back with the thought signature the driver kept, and Google answered the second turn ("The weather in Paris is currently sunny with a temperature of 21 degrees Celsius."); usage with the thoughts counted |
| L2 | embeddings of 3,072 dimensions; a speech clip (WAV, 121 KB) from `gemini-3.8-flash-tts`, heard back by `gemini-3.5-transcribe` as "Hello from Eugene Plexus." |
| L3 | an image from `gemini-3.1-flash-image` |
| L4 | a 4-second 720p video from Veo 3.1 Lite (1.2 MB, 37 s), polled and downloaded |

**What the live runs found** (two runs before the one of record, each
stopped at a wire detail Google's documentation did not show; fixed in
inference-driver `7d22ac9`, with unit tests on the shapes Google sent):

- `gemini-3.5-transcribe` answers in an `audioTranscription: {text}` part,
  not `text`: every transcript read as empty.
- Veo refuses `durationSeconds` as a string ("needs to be a number"),
  before making anything. The fixture now refuses it as Google does.

**Spent:** about $0.30 over the three runs (two images, one 4-second
video, and a few cents of chat, embeddings and speech).
