# The playground's other doors: audio, PDFs, images, video and completions

**2026-09-28. Designed; not built.** First item in Troy's order after P6
(then P8, then P7). It pays a debt: every door P2–P6 added
(`openai-inference-compatibility.md`) shipped with no screen, so none of
them can be tried from the console.

## 1. What is missing

The playground today speaks one door, `/v1/chat/completions`, with text
and image attachments, plus the decision panel for `/v1/systemone`. None
of these can be tried from the UI:

| Door | Built | What a person cannot do today |
|---|---|---|
| Chat: `input_audio` and `file` parts | P2a | attach an audio clip or a PDF |
| Chat: `modalities: ["text","audio"]` | P2b | hear a spoken reply |
| `/v1/completions` | P6b | continue a prompt, or fill in the middle |
| `/v1/audio/speech` | P3a | turn text into speech |
| `/v1/audio/transcriptions`, `/translations` | P3b, P3-4 | turn a recording into text |
| `/v1/images/generations`, `/edits` | P4 | make or edit an image |
| `/v1/videos` | P5 | make a video |

`/v1/moderations` stays without a screen (Troy, 2026-09-28).

## 2. Calls taken (Troy, 2026-09-28)

| # | Call | Taken |
|---|---|---|
| 1 | Where the screens live | **A door picker in the playground.** One page; a picker (Chat · Completions · Speech · Transcription · Images · Video) that shows only the doors some model serves, as the decision panel does. Audio and PDF attachments and spoken replies go into Chat. No new tree pages or registry entries. |
| 2 | How deep | **Diagnostic.** One request, one result, what served it, and a curl line. Nothing but the form survives a reload. The playground is a reference client, not a product. |
| 3 | Spending | **Video and images ask once before they are sent**, saying they bill the provider account. Speech and chat send straight away. |
| 4 | Moderation | **Left out.** |

## 3. The shape

- **The picker reads `GET /v1/models`.** A door appears when at least one
  model lists its surface (`completion`, `speech`, `transcription`,
  `translation`, `image`, `video`). Chat is always there. The choice rides
  in `?door=`, so a link opens the right form.
- **Each door lists only the models that serve it** and builds its form
  from that model's own listing: `voices` and `speech_formats` for
  speech; `video_durations`, `video_sizes` and `video_first_frame` for
  video; `image_edits`, `image_mask` and `image_streaming` for images.
  A choice the model does not list is not offered, and nothing is
  invented. **The one exception is free text a person may already have
  typed** (the completions suffix): it stays on screen, and a model whose
  listing says it cannot take it gets the warning below, because hiding
  the box on a model switch would drop the text without a word.
- **The diagnostic panel applies to every door.** Proxy or direct, base
  URL and key, exactly as chat: "works through the proxy, fails direct"
  must be answerable for a picture as it is for a sentence.
- **Every result carries what served it and a curl line**, the way the
  chat request report does, from `x_eugene_plexus` and the response
  headers. A binary answer (audio, an image, a video) is shown or played
  in place and offered as a download.
- **A refusal is shown in the gateway's words**, with the field it names.
  The UI warns before sending when the listing already says the model
  cannot take something (an audio clip to a model with
  `audio_input: false`), the way `imageNote` does, and sends anyway if
  asked. It never strips.
- **The confirmation is a `ConfirmButton`**, never `window.confirm`.

## 4. Slices

Each slice lands with unit tests for its pure half and a page test that
drives the playground itself, not only the component (S7's lesson: a
component test is not a wiring test).

| Slice | Content |
|---|---|
| **U1** | Re-pin `ui` to current specs (types for P2–P6). The door picker, `?door=`, and the per-door model list. Chat unchanged. |
| **U2** | Chat: attach audio (`input_audio`) and PDFs (`file`), with the listing's warnings; spoken replies (`modalities`, `audio.voice`, `audio.format`) with a player, streamed or not. |
| **U3** | Completions: prompt, suffix when the model fills in the middle, sampling, streamed or not. |
| **U4** | Speech (text, voice, format, speed; play and download) and Transcription/Translation (upload, language, response format; the text). |
| **U5** | Images: generate (prompt, size, n, quality, format), edit (reference images, mask where listed), partial images when streaming; confirmation before sending. |
| **U6** | Video: create with a confirmation (prompt, duration, size, first frame where listed), poll the job, play and download. |
| **U7** | A browser run against the P2–P6 fixture backends through a real gateway, the `dist` rebuild, and both installers re-pinned. |

## 5. Not in scope

A gallery or history of results, prompt libraries, moderation, a screen
for `/v1/responses` or `/v1/messages` (the chat door is their reference),
and Realtime (P7).
