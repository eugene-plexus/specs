# P2a: audio and PDF inputs — record

**2026-09-28. On main in all three repos. NOT in an install**, because neither
installer has been re-pinned. The acceptance run and sabotage pass that come
before a pin have not been done. Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§8.

| Repo | Commit |
|---|---|
| specs (contract) | `ce0e467`, then `6ac2761` (names the new schemas) |
| inference-driver | `e231aaf` |
| gateway | `de7a65f` |

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

## Owed before an install gets it

1. **`scripts/p2-media-acceptance.py`**, following
   `p1-accounts-acceptance.py`: real signed processes, and a fixture upstream
   playing OpenRouter's listing with per-model input types.
   - A slot `assistant → [text model, audio model]` must answer an audio
     request from tier 2 while the text model's upstream count does not move.
   - A PDF sent as bare base64 must arrive upstream as the data URL.
   - The Anthropic and Responses shapes must arrive as file parts.
2. **`--openrouter-live`:** an audio question and a PDF question answered
   through chat, both measured against OpenRouter directly on 2026-09-28.
   - The audio: `scripts/fixtures/p2-fox.mp3`, 24 KB of generated speech. It
     answered *"The quick brown fox jumps over the lazy dog."* on
     `google/gemini-2.5-flash-lite` for $0.00003.
   - The PDF: one page whose only text is *"The secret word is zebra."* It
     answered *zebra*.
   - Also through a slot whose first tier is `mistralai/mistral-nemo`, which
     OpenRouter refuses with *"No endpoints found that support input audio"*.
3. **A sabotage pass** over the acceptance, restoring from byte copies.
4. **Re-pin both installers** to driver `e231aaf`+ and gateway `de7a65f`+.
5. **The other three consumers:** agent, control and library generate
   `common.yaml`, so their models change. They are re-pinned regen-only once,
   at P2's end, not three times. `ui` is re-pinned when a screen consumes
   `audio_input`/`file_input`; the playground cannot attach audio or a PDF yet.

## Not covered

- `llama-server`'s audio path has not run against a real audio model
  (Voxtral, Qwen2.5-Omni). The `/props` field is read by fixture only.
- Hosted OpenAI accounts confirm neither audio nor files, because their list
  says nothing per model. Audio or a PDF to `gpt-4o` through an OpenAI
  account is refused until something confirms it.
- Ollama and LM Studio listings are not read for audio.
