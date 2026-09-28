# P2b: audio output on chat — record

**2026-09-28. Built, run and pinned in both installers** (inference-driver
`429d0d0`, gateway `e44b88b`; both archives fetched, HTTP 200). Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§8, calls P2-1 and P2-2. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §4.

| Repo | Commit |
|---|---|
| specs (contract) | `060f516` |
| inference-driver | `429d0d0` |
| gateway | `e44b88b` |

- **`scripts/p2-media-acceptance.py`: 14 checks with fixtures, 22 with
  `--openrouter-live`, all PASS.** P2a's checks plus five new fixture checks
  and three new live ones, in one script, because P2 is one gate.
- **`scripts/p2-sabotage.py`: 40 of 40 caught** (P2a's 21 and 19 new), plus
  P2a's one declared escape, which escaped again as declared.
- **The specs CI acceptance set** (12 steps, the P2 fixture half among them)
  passes locally against exactly the pinned heads.
- **Unit suites:** inference-driver 715 (18 new), gateway 828 (12 new). ruff,
  format and mypy are clean on both. Against each repo's pre-P2b source, with
  the new generated models, **14 of the driver's 18 and 11 of the gateway's 12
  new tests fail.** The ones that pass are tests of the new pure module
  (`audio_out`: format detection and the WAV header) and one regression guard
  in each repo, that a text request asks for no audio. Both should pass either
  way.

## What it does

- **`modalities: ["text", "audio"]` with `audio: {voice, format}`** asks chat
  for a spoken answer. The answer is `message.audio` (`delta.audio` when
  streamed), in OpenAI's shape plus `format`. What it says is
  `audio.transcript`; `content` is null.
- **Routed only to a model that speaks.** A new capability, `audioOutput`,
  comes from `audio` in an OpenRouter model's `output_modalities`. **Not from
  `supported_parameters`**: none of the four audio-output models lists
  `modalities` or `audio` there (measured), so A2's setting rule would route
  nothing. The gateway treats it like an attachment kind: every tier, and a
  400 naming `x_eugene_plexus.audio_output` when nothing speaks.
- **The backend is always asked for a `pcm16` stream.** That is the only way
  any of them answers audio (measured: a non-streamed one is refused before any
  provider, and a streamed `wav` or `mp3` is OpenAI's own 400).
  - A non-streamed answer is that stream assembled by the driver. Asked for
    `wav`, it gets a 44-byte header: 24 kHz, mono, 16-bit.
  - A streamed answer is the fragments as they arrive.
- **The format reported is what the bytes are** (P2-2). Lyria sends one MP3
  whatever it is asked, and it comes back labelled `mp3`.
- **Refused before anything is sent** (P2-1), at the gateway with `param`
  naming the field, and again at the driver:
  - a non-streamed format other than `wav` or `pcm16`;
  - a streamed format other than `pcm16`;
  - `audio` without `"audio"` in `modalities`, and the reverse;
  - an assistant message's `audio: {id}`, which names a store this install
    does not have.

## Found on the way

- **A lone MPEG frame sync is not an MP3.** P2a's input check treats eleven
  set bits after `FF` as an MPEG frame, which is fine for validating a clip the
  caller *says* is an MP3. It is not fine for deciding what unlabelled bytes
  are: a `pcm16` stream whose first sample is -1 begins `FF FF`. So
  `audio_out.detect_format` calls headerless audio MP3 only when a valid Layer
  III header is followed by another where the first says the frame ends. The
  acceptance fixture's samples open with a real header (`FF FB 90 00`) so a
  sabotage back to the weak test is caught.
- **Lyria's first call failed** with a transient Google 500 (relayed as
  OpenRouter's 502). The identical request succeeded minutes later. Recorded
  in the measurement.
- **gpt-audio-mini does not reliably repeat a sentence it is told to say.**
  The first live run asked it to "say exactly: The zebra is blue" and it
  answered conversationally, so a check on its words failed on the model, not
  the product. The check now compares what it said (its transcript) with what
  a second model hears in the WAV this gateway assembled: a wrong header plays
  at the wrong speed or not at all.
- **One gateway test locked in the old refusal:**
  `test_consequential_unsupported_settings` expected `modalities: ["text",
  "audio"]` to be refused as `modalities`. It is still refused, now naming
  `audio`, the missing object. Amended, not deleted.
- **One P2a sabotage anchor moved** when P2b put a line between the two it
  matched. The pass checks every anchor before editing anything, so it stopped
  with no file touched.

## The acceptance run

New fixture models, beside P2a's three: `acme/speaks` streams `pcm16` in two
fragments the way gpt-audio does, id and transcript first; `acme/sings` sends
one MP3 the way Lyria does. The fixture refuses a non-streamed audio answer and
a non-`pcm16` streamed one with the measured errors, and answers a model that
does not speak with a 404.

**Fixture checks (5 new; 14 in all, first execution):**

10. The driver reads audio output per model from the listing, and `GET
    /v1/models` reports it. The slot `speaker` does too.
11. A spoken request to `speaker → [text-only, speaks]` is answered by **tier 2
    in one attempt**, and the text model's upstream count does not move. The
    backend was asked for a `pcm16` stream with the caller's voice. The answer
    is a WAV whose header says 24 kHz and whose data is the samples sent, or
    the samples alone when `pcm16` was asked.
12. Streamed, the fragments arrive as `delta.audio` and reassemble to the
    samples sent, with the transcript in order.
13. The Lyria-shaped model asked for WAV answers MP3, returned byte for byte
    and labelled `mp3`, with its lyrics as `content`.
14. The five refusals above, each with `param` naming the field; a model that
    does not speak is a 400 naming `audio_output`; the driver called directly
    refuses both the model and the format on its own. Nothing reaches the
    upstream.

**Live checks (3 new; 22 in all; failed on the first execution for the
reason below, passed on the second and third):**

- `openai/gpt-audio-mini` answered a non-streamed WAV request: 3.05 s of audio,
  transcript *"The zebra is blue and the kettle is singing."*
  `google/gemini-2.5-flash-lite` transcribed that WAV back as the same
  sentence, 4 of 4 words.
- A slot `live-speaker → [mistral-nemo, gpt-audio-mini]` answered a spoken
  request from tier 2 in one attempt.
- `google/lyria-3-clip-preview`, asked for WAV, returned MP3 labelled `mp3`:
  728,934 bytes on one run and 656,836 on the next. This meets the P2 slice's "Lyria returns music through
  chat".

About $0.05 per live run; the measurements before building cost about $0.12.

## The sabotage pass

`scripts/p2-sabotage.py` gained 19 sabotages for P2b, run with P2a's 22 in
one pass. It opens with a baseline that the gate passes unsabotaged, checks
every anchor before editing anything, and restores from byte copies.

- **Driver (9):** the listing read without audio output; the backend asked
  for the caller's format instead of `pcm16`; a non-streamed answer asked for
  without a stream; no WAV header on `pcm16` asked as `wav`; the clip labelled
  as asked rather than as it is; a lone frame sync taken for an MP3; the
  stream route never framing an audio fragment; a model that does not speak
  asked to; any format taken.
- **Gateway (10):** a spoken request routed like a text one; `/v1/models`
  reporting no audio output; any non-streamed format taken; any streamed
  format taken; `audio` without `modalities` ignored; an assistant's
  `audio: {id}` not told why; the driver never asked for audio; the answer's
  audio dropped; a streamed fragment not forwarded; the driver's audio events
  not read.

**All 19 were caught on the first pass.** One of them could only be caught
because the fixture was changed first: "a lone frame sync is taken for an
MP3" would have escaped against samples that did not open with a frame
header, which is why the fixture's do.

Several gateway rules are also enforced by the driver (the format and the
model's confirmation). The gateway's copy is still seen on its own, because
each refusal asserts `param`, which only a gateway door refusal carries, and
check 14 calls the driver directly for its copy.

## Still owed

- **P2c:** the missing fields and `/v1/responses/input_tokens`.
- **At P2's end:** agent, control and library re-pin regen-only, since
  `common.yaml` reaches them (`AudioOutputFormat` is new there). `ui` re-pins
  when a screen consumes `audio_output` or plays `message.audio`.

## Not covered

- **The 24 kHz rate is OpenAI's documented one**, and the round trip shows it
  is right for gpt-audio-mini: a wrong rate would not be heard back as the same
  words. No other `pcm16` source was measured.
- Lyria was not tried streamed through the gateway; its one fragment is the
  fixture's shape, and a streamed Lyria answer takes `pcm16` and would be
  labelled `mp3`.
- A text request (no `modalities`) to Lyria is still OpenRouter's 400
  *"Audio output requires stream: true"*, relayed. Lyria cannot answer in text
  alone, so that 400 is the true answer. It does name `stream`, though, which
  sends the caller to the wrong fix.
- Audio output on `/v1/messages` and `/v1/responses`: neither API has it.
