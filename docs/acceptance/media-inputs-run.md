# P2a: audio and PDF inputs — record

**2026-09-28. Built, run and pinned in both installers.** Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§8.

- **`scripts/p2-media-acceptance.py`: 9 checks with fixtures, 14 with
  `--openrouter-live`, all PASS.** Real signed processes; the live run cost
  well under a cent.
- **`scripts/p2-sabotage.py`: 21 of 21 caught, and 1 escaped as the pass said
  it would** (below).
- **Pins, both installers:** inference-driver `934d824`, gateway `ba25538`.
  These are P2a plus the provider-key fix
  ([record](decision-run.md#hosted-jev-through-openrouter-2026-09-28)). Both
  archives were fetched from GitHub (HTTP 200).
- **The specs CI acceptance set** (12 steps, now including the P2 fixture
  half) passes locally against exactly these heads, before the pin moved.

| Repo | Commit |
|---|---|
| specs (contract) | `ce0e467`, then `6ac2761` (names the new schemas) |
| inference-driver | `e231aaf`; pinned at `934d824` |
| gateway | `de7a65f`; pinned at `ba25538` |

## What it does

- **Chat** takes `input_audio` (WAV or MP3, base64) and `file` (an inline PDF)
  as user content parts, alongside text and images.
- **`/v1/responses`** takes `input_file` and `input_audio`.
- **`/v1/messages`** takes `document` blocks: a base64 PDF becomes a file
  part, and a plain-text source becomes its text. This includes a document
  inside a `tool_result`, which moves to the next user message the same way an
  image does.
- **Checked by bytes:** a WAV must start `RIFF....WAVE`, an MP3 with an ID3 tag
  or an MPEG frame sync, and a PDF with `%PDF-`. A mislabelled attachment is
  refused here, naming its field, rather than as whatever the provider says.
- **Limits:** 10 MiB decoded per clip or file, and 11 MiB across every
  attachment in the request, images included. That is what fits in the 16 MiB
  body once base64 grows it by a third. The design first said 12 MiB, which
  could never have bound; it is corrected there.
- **Bare base64 is sent on as a data URL.** OpenAI's schema calls
  `file_data` base64, and OpenRouter refuses anything but the data URL
  (measured: *"Invalid content"*).
- **Refused:** a `file_id`, a `file_url` and a document URL, since each names
  a store or an address this install does not fetch. Also refused:
  `citations` enabled on an Anthropic document, because no citation blocks
  come back, so the answer would read as uncited.
- **Routed only where confirmed.** The driver reports `audioInput` and
  `fileInput` per model, under the same rule as `imageInput`: unknown counts
  as no.
  - An OpenRouter account takes them from the listing's `input_modalities`.
  - `llama-server` confirms audio from `/props` `modalities.audio`.
  - Nothing local confirms PDFs.
  - The CLIs confirm neither.

  The gateway picks only backends that confirm *every* kind in the request, in
  every tier, so a fallback cannot hand a recording to a model that cannot
  hear it. With none it returns a 400 naming `x_eugene_plexus.audio_input` or
  `file_input`, which `GET /v1/models` now reports. If each kind is confirmed
  by a different backend but none takes both, it says so.
- **`count_tokens`** refuses a request with an attachment, as it does for
  images.
- **Upstream error bodies stay omitted** for any attachment request, as for
  images, with a hint specific to audio or files.

## Found on the way

- **A schema error named no field.** A content part is a union, and the
  gateway reported Pydantic's first branch error: `messages.0.content.str`,
  whatever was wrong. It now takes the branch whose `type` matched and drops
  the generated class names, so a bad format reads
  `messages.0.content.1.input_audio.format`. This predates P2; images had the
  same defect.
- **Inline enums would have been renamed.** Generated as `Format` and `File`,
  the next inline enum would have renamed them, as S6's `Source1` showed. The
  contract names them instead: `InputAudio`, `InputAudioFormat`, `InputFile`.
- **Three tests locked in the old refusals:**
  - `test_a_document_block_is_still_refused`;
  - `test_a_document_block_is_refused`;
  - a Responses case whose `input_file` was `JVBERi0=`, which is literally
    `%PDF-` and so now a valid PDF.

  Each was amended to a shape that is still refused (a URL source, a
  `content` source, a `file_id`, a `file_url`), not deleted.

## Evidence

- **Driver:** 20 new tests; the suite has 680, with ruff and mypy clean.
  Against main's pre-P2 driver source with the new generated models, **19
  fail**. The twentieth passed for the wrong reason: the old code called every
  non-text part "images". It was tightened to the new wording.
- **Gateway:** 25 new tests; the suite has 809, with ruff and mypy clean.
  Against main's pre-P2 gateway source, **all 25 fail**.

Both reproductions were run by swapping the source files for their `HEAD`
versions and restoring from a byte copy.

## The acceptance run

`scripts/p2-media-acceptance.py` starts a control root, an enrolled agent, a
gateway and a driver, all signed, with isolated ports and state. The driver is
the real `openrouter` provider with its `baseUrl` pointed at a fixture that
plays OpenRouter's account listing (`/v1/models/user`). So the driver's own
listing reader decides what each model takes. The fixture lists three models:
`acme/text-only`, `acme/hears` (audio) and `acme/reads` (files). Like
OpenRouter, it answers an unconfirmed attachment with a 404 *"No endpoints
found that support input …"*. It counts every request per model and keeps the
bodies, so a check can say exactly what reached the upstream.

**Fixture checks (9, second execution; the first died on a harness bug that
passed two `headers` arguments):**

1. The driver reads `audioInput`/`fileInput` per model from the listing, and
   `GET /v1/models` reports each. A slot reports what any of its backends
   takes.
2. A text request to `assistant → [text-only, hears]` is answered by tier 1,
   so tier 1 is live and preferred.
3. An audio request to the same slot is answered by **tier 2 in one attempt**,
   streamed and not. **The text model's upstream count does not move**, and the
   clip arrives byte for byte.
4. With no backend confirming the attachment, the answer is a 400 naming
   `x_eugene_plexus.audio_input` or `file_input`. Audio plus a PDF, each
   confirmed by a different backend, is refused as "together". Nothing reaches
   the upstream.
5. MP3 bytes declared `wav`, a `file_id`, and an MP3 sent as a PDF are each
   refused **by the gateway itself**, with `param` naming the exact field. The
   driver checks the same bytes, but its 400 relayed through the gateway
   carries no such `param`, so this check cannot be passed by the driver
   standing in for the gateway.
6. A PDF sent as bare base64 arrives upstream as the data URL. A data URL
   arrives unchanged.
7. Anthropic `document` blocks arrive upstream as file parts. A top-level one
   carries its `title` as the filename. One inside a `tool_result` moves to
   the next user message, and the tool message says it moved.
8. The Responses door's `input_file` arrives as a file part, and its
   `input_audio` as `input_audio`, routed past the slot's text-only tier.
9. **The driver, called directly,** refuses audio or a PDF its model's listing
   does not confirm, and MP3 bytes declared `wav`, sending nothing upstream. It
   sends a bare-base64 PDF on as the data URL. It does not rely on its caller
   having routed or normalised.

**Live checks (5 more; passed on both executions, the second with the final
script, 14 PASS in all):** a second driver on the real
OpenRouter account, `catalogueInclude` narrowed to the two models below. The
key went to that driver only as `OPENAI_API_KEY`.

10. OpenRouter's listing says `google/gemini-2.5-flash-lite` takes audio and
    files and `mistralai/mistral-nemo` neither. `GET /v1/models` reports the
    same.
11. Through chat, the fox (`scripts/fixtures/p2-fox.mp3`) was transcribed as
    *"The quick brown fox jumps over the lazy dog."* A bare-base64 PDF whose
    only text is *"The secret word is zebra."* was answered *zebra*.
12. Through the Anthropic door, a `document` block was answered *zebra*.
13. A slot `live-assistant → [mistral-nemo, gemini-2.5-flash-lite]` answered
    text from tier 1 and the fox from **tier 2 in one attempt**. Sent the audio,
    OpenRouter refuses mistral-nemo with *"No endpoints found that support input
    audio"*, a 4xx that does not cascade. So a 200 from tier 2 in one attempt
    means tier 1 was never sent the clip.
14. The key is in none of the 24 files of the run's state and logs.

The one-page PDF is built inline by `one_page_pdf()`, so no binary is
committed for it.

## The sabotage pass

`scripts/p2-sabotage.py` opens with a baseline that the gate passes
unsabotaged. It restores every file from byte copies, never `git checkout
--`. **22 sabotages: 21 caught, 1 escaped, and that one was declared in
advance with its reason.**

- **Driver (6):** the listing read without audio; every model said to read
  files; an attachment sent to a model its listing does not confirm; audio
  bytes unchecked; a bare-base64 PDF sent on as it arrived; the data URL
  worked out but never written back.
- **Gateway routing (6):** `takes()` saying yes to everything; `pick()`
  ignoring what the request needs; the chat door never working out what it
  carries; `/v1/models` reporting no audio input; file input read from the
  audio flag; kinds confirmed by different backends reported as one kind
  missing.
- **Gateway doors (5):** audio bytes unchecked at the gateway; a `file_id`
  accepted; neither layer checking audio bytes; neither layer turning a
  bare-base64 PDF into a data URL; the Responses door sending every clip on
  as `wav`.
- **Anthropic door (4):** a base64 PDF document refused again; the title not
  used as the filename; a document inside a `tool_result` dropped; the tool
  message not saying its document moved.

**Two rules are enforced twice, once in the gateway and once in the driver:**
checking an attachment's bytes, and turning bare base64 into a data URL. The
driver's copy is not a spare, because the driver is its own contract surface
and may be called by something other than this gateway. Check 9 was added so
the driver's copy is seen on its own, and check 5 asserts `param` so the
gateway's copy is. Removing both copies of each rule is caught.

**The one escape is the gateway's bare-base64 rewrite on the chat door.** The
driver does the same rewrite, and only a driver that confirms `fileInput` is
ever routed a PDF, so the gateway's rewrite cannot be seen through any door.
Its unit test is the check for it:
`gateway/tests/test_attachments.py::test_bare_base64_reaches_the_driver_as_the_data_url`
passes unsabotaged and fails with the sabotage in place (measured, restored
from a byte copy).

## Still owed

- **The other three consumers:** agent, control and library generate
  `common.yaml`, so their models change. They are re-pinned regen-only once,
  at P2's end, not three times.
- **`ui`** is re-pinned when a screen consumes `audio_input`/`file_input`. The
  playground cannot attach audio or a PDF yet.

## Not covered

- `llama-server`'s audio path has not run against a real audio model
  (Voxtral, Qwen2.5-Omni). The `/props` field is read by fixture only.
- Hosted OpenAI accounts confirm neither audio nor files, because their list
  says nothing per model. Audio or a PDF to `gpt-4o` through an OpenAI
  account is refused until something confirms it.
- Ollama and LM Studio listings are not read for audio.
