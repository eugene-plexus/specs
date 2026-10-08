# Workbench media screens, slice 2: Speech and Transcription — record

**2026-10-08. Built, run and pinned.** Design:
[`workbench-media-screens.md`](../design/workbench-media-screens.md) §4
and call M10. What building found is §10b there. Slice 1 is
[`workbench-media-images-run.md`](workbench-media-images-run.md).

| Repo | Commit |
|---|---|
| specs (contract wording) | `902b737` |
| inference-driver | `334954a` |
| gateway | `48f5d59` |
| workbench (`main`) | `27b36f7` |
| workbench (`dist`) | `53004e4` |
| agent (catalogue) | `33e2c9a` |

## The run of record

`scripts/c3-workbench-acceptance.py --browser --openrouter-live`, from
`agent/.venv`, against the working trees at the commits above. **54 of 54
passed.** Workbench was installed by the registry from the agent's own
catalogue entry, at the pinned `dist` archive `53004e4`, from the console
on a second machine.

The speech and transcription checks use the same fixture account as the
image checks: the real `openrouter` provider, with its `baseUrl` set to the
fixture. The fixture plays OpenRouter's audio models as P3 measured them:

- **kokoro** lists two voices and answers an MP3 (an ID3 tag, then frames);
- **whisper** transcribes, does not translate, and reports hearing 1.525 s,
  as OpenRouter's whisper did with kokoro's 3.07 s MP3 (§10b).

Everything goes through Workbench's own API, as its page calls it.

| # | Check | Result |
|---|---|---|
| S1 | The Speech screen lists the model's own voices and the formats a browser plays; the Transcription screen lists the model, which does not translate | kokoro: voices `af_heart`, `af_bella`, formats mp3 and wav; whisper: `translates: false`; both `locality: external` |
| S2 | A clip is spoken through the gateway and kept in the bin as it came back | `speech.mp3`, `audio/mpeg`, 414 bytes, byte-identical; the provider got voice `af_heart` and `mp3` |
| S3 | A voice the model does not list is refused in the gateway's words, naming the field and the voices it has, and nothing reaches the provider | `voice: 'images/acme/kokoro' has no voice 'alloy'; it has af_heart, af_bella … Nothing was sent.`, `param: voice`; the fixture saw no request |
| S4 | A Chrome recording is kept, sent to the model unchanged, and its transcript kept beside what the model heard and the clip's own length | the provider got `recording.webm`, 204 bytes starting `1a45dfa3`, with `language: en`; kept: heard 1.525 s of a 3.07 s clip |
| S5 | The recording stays in the bin, to play again | the file read back whole |
| S6 | The gateway records the clip and the transcript under the app's key | doors `speech` and `transcription` under `app:workbench@c3-node` |
| SL | A real OpenRouter clip is spoken, kept, and transcribed back | kokoro-82m spoke *"The bench is ready. Bring your project."*; whisper-large-v3-turbo returned *"The bench is ready."*, heard 1.525 s |

**SL reproduced the half-heard MP3.** The real whisper heard 1.525 s and
dropped the second sentence, as in §10b's three measurements. SL passes on
its claim (the round trip works), but it sends no `clipSeconds`, so the
live run does not show Workbench saying the shortfall. The page measures
an upload's length itself and sends it. S4 checks that path with the
fixture, and vitest checks the words.

The earlier checks (1–27, M1–M8, ML and B1–B10) all passed unchanged
against the new Workbench, gateway and driver.

**Spent:** one flux.2-klein-4b image at 512×512 (about $0.004), one
kokoro clip of 39 characters and one whisper transcription of a few
seconds, each a small fraction of a cent.

## P3 and the other CI acceptances

- **P3's check 6 changed under M10** (§10b). It now asserts that the
  gateway refuses `alloy` for an ElevenLabs model before sending.
- **Every script specs CI's acceptance job runs passed locally before the
  pins,** 21 in all, from `agent/.venv` against the working trees above.
  - Not in that count: c3 (the run above), the Windows service smoke and
    Job Sites (Linux only).
  - p2 18, **p3 27**, p4 15, p5 8, p6 9 and p8 15 checks passed.
  - c2 passed 42 of 42; r7 signing 13 of 13, rotation 8 of 8; row3
    (`--lan`) 27.
  - r8 profile, a3, a5, a6, a6b, a7 recovery, run operations and the S10
    starter check all passed.
  - The sabotage checks caught every case: r8 profile 10, the R7 launch
    boundary 15, the R6 benchmark 6.

## Unit suites, the Chrome check and sabotage

- **inference-driver `334954a` and gateway `48f5d59`:** CI green on both.
  Voice sabotage, a scratch script: 7 cases written, 6 run, 6 caught.
- **Workbench:**
  - pytest **228**, with Chrome included (`test_media_audio_browser.py`
    records with Chrome's fake microphone on `127.0.0.1`, sends the
    transcript to a new chat and finds it waiting there as unsent text);
  - vitest **184**;
  - ruff, format, mypy, eslint and prettier are clean.
- **Workbench sabotage:** `scripts/check-media-sabotage.py`, 33 cases (12
  new for slice 2; 5 in Chrome), **all caught**, in two passes:
  - The first pass caught all 28 cases outside Chrome.
  - **Two Chrome mutations were the instrument's fault.** One removed the
    `saveDraft` call, the other the tab's `onDoor` call. Each left a symbol
    unused, which breaks the build instead of the behaviour, and stopped
    the pass. Both were rewritten to keep the symbol used: the draft is
    saved to "no chat", and the tab reopens the screen already shown.
  - The second pass ran the five Chrome cases: **5 of 5 caught**, and the
    restored baseline passes.
  - Every file was restored from exact bytes, and checked against them
    after each pass.

## Not run

- Deploying to Troy's install. His gateway lists no speech or
  transcription model, so both screens there show the empty state until he
  adds a provider account (`workbench-media-screens.md` §0).
- specs CI on the pin commit (checked next session). Workbench `27b36f7`
  and agent `33e2c9a` CI passed before it.

## Voice names

**2026-10-08, the same day. Built, run and pinned.** ElevenLabs lists voices
by id (`21m00Tcm4TlvDq8ikWAM`), and Troy approved a contract field for their
names after slice 2 landed.

| Repo | Commit |
|---|---|
| specs (contract) | `37baa39` |
| inference-driver | `5c500be` |
| gateway | `d275bba` |
| workbench (`main`) | `f4238a5` |
| workbench (`dist`) | `e26adc4` |
| ui (`main`) | `904d0a9` |
| ui (`dist`) | `ac6f816` |
| agent (catalogue) | `c5a195a` |

- **The field:** `DriverModel.voiceNames` and `ModelRoutingInfo.voice_names`,
  each a map from a voice's id to its provider's name. It is additive, and
  the id is still what a request sends.
  - The driver reads the names from ElevenLabs' `GET /v1/voices`.
  - The gateway lists the names from the backends that list voices. The
    first backend's name wins, and a name for a voice not listed is not
    carried.
- **Shown as:** Workbench's Speech screen and the console's speech door show
  the name. They add the id only where two voices share a name. In
  Workbench, *Find a voice* matches either.
- **The run of record:** `c3-workbench-acceptance.py --browser`, with no
  live spend: **53 of 53 passed**.
  - Workbench was installed from the catalogue's `dist` archive `e26adc4`.
  - New check **S7**: an ElevenLabs account (the real `elevenlabs`
    provider on the fixture) lists two voices by id. Workbench's Speech
    screen received both with their names, *Rachel* and *Sarah*.
- **P3:** check 1 now asserts the ElevenLabs model's `voice_names`, and
  that kokoro's are absent. 27 of 27 passed.
- **Every CI acceptance script passed locally before the pins** (the same
  21 as above).
- **Unit suites:** driver 979, gateway 1,250, Workbench pytest 228 and
  vitest 186, UI vitest 1,726. Static checks are clean in all four.
- **Sabotage: 14 of 14 caught.**
  - Driver and gateway: 6 of 6, with a scratch script.
  - Workbench: 5 of 5, added to `check-media-sabotage.py`.
  - Console door: 3 of 3, with a scratch script.
- **specs#17**, the P3 sabotage script's two dead anchors, was fixed the
  same day (`a6cdd4a`). The full pass ran against driver `334954a` and
  gateway `48f5d59`: 67 of 67 caught, and the 2 cases the script expects
  to escape did.
