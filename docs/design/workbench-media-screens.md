# Workbench: media screens

**Status: designed 2026-10-08; Troy took all eleven calls (§1) as
recommended the same day. Slice 1 (images and the shared frame) is built
and pinned the same day** ([record](../acceptance/workbench-media-images-run.md);
what building found is §10a). **Slice 2 (speech and transcription) is
built and pinned the same day too**
([record](../acceptance/workbench-media-speech-run.md); §10b). Video is
next.
This is roadmap A6's last Workbench item ([`audience-roadmap.md`](audience-roadmap.md)
A6, [`workbench.md`](workbench.md) §5 and §8, [`workbench-v1.md`](workbench-v1.md)
§6). It covers images, speech, transcription and video as screens of their own.

**What first (Troy, 2026-10-08): images, built together with the shared
frame.** Speech and transcription come second, as one small slice that
reuses the frame. Video comes last, because it is paid and runs as a job.
This design covers all four, so the shared parts are decided once.

**Not in this design:** local media models. A GPU app admitted by the
agent's ledger needs its own design (`workbench.md` §8).

## 0. Measured (2026-10-08)

### This install

- **How it was reached.** The root's gateway port, `192.168.16.252:8280`,
  refuses connections. The gateway answers through the root agent's proxy,
  `:8279/api/proxy/gateway`, which is also the path an app on another node
  is given. The measurement used a client key Troy minted with the default
  limits (all models, not local-only).
- **`GET /v1/models` lists one model:** `Huihui-Qwen3.8-27B-abliterated-Q6_K_L`,
  `surfaces: ["chat"]`, on Amish_Station. The install has no provider
  account and no local media model. **On Troy's install today, every media
  screen would be empty.** The empty state is the first thing a local-only
  install shows, so it is a main path, not an edge case.
- **Every media door refuses that model in the gateway's own words, for
  free:**
  - images, speech, transcription, translation, video:
    *"The model 'Huihui-…' serves chat and not image. Send this request to
    /v1/chat/completions instead. GET /v1/models reports
    x_eugene_plexus.surfaces per model."* (400, `param: model`);
  - no model: *"model: has an invalid or missing value."* (400);
  - an unknown model: *"The requested model is unavailable or not
    permitted."* (404, `model_not_found`);
  - a made-up video id: *"No video job 'video_nope' for this key."* (404,
    `param: video_id`);
  - `GET /v1/videos`: *"Videos are not listed here: this install keeps no
    store of jobs, and the provider's list would show every key's. Keep the
    id POST /v1/videos returned and poll GET /v1/videos/{video_id}."* (400).

### A throwaway install with provider accounts

Troy chose this so his live install stayed unchanged. It ran the same
pinned control, agent, gateway and driver on test ports, with his
OpenRouter, OpenAI and ElevenLabs keys. Only OpenRouter made paid calls.

**The listing, by surface:**

| Surface | Models | By account |
|---|---|---|
| image | 69 | OpenRouter 59, OpenAI 10 |
| speech | 47 | OpenRouter 32, ElevenLabs 9, OpenAI 6 |
| transcription | 38 | OpenRouter 26, OpenAI 8, ElevenLabs 4 |
| translation | 1 | OpenAI `whisper-1` |
| video | 30 | OpenRouter only |

**What a model's listing says, and what it leaves out:**

- **Images.**
  - The listing gives `image_streaming` (18 of 69), `image_edits` (66) and
    `image_mask` (10, all OpenAI). That is all it gives.
  - **The driver already reports more** (`ImageCapabilities`: `maxImages`,
    `qualities`, `backgrounds`, `outputFormats`, `minReferences`,
    `maxReferences`), and the gateway refuses on it before sending, for
    example *"n: … makes at most 1 per request. … Nothing was sent."* The
    gateway does not list any of it.
  - **Sizes are listed nowhere.** OpenRouter takes aspect ratios and maps a
    `size` itself. Flux took `333x333` and answered 200.
- **Speech.**
  - The listing gives `voices` and `speech_formats`: kokoro has 54 voices
    and mp3, wav and pcm; each ElevenLabs model has 22 voices and mp3, opus,
    wav and pcm.
  - **OpenAI's six TTS models list no voices** (null: the backend checks).
  - **A voice that is not listed is sent anyway.** The provider's refusal
    names nothing: *"The backend rejected the request: openai_compat_http
    returned 400 for speech: {"error":{"message":"Provider returned
    400","code":400}}"*.
- **Video.**
  - The listing gives `video_durations` (grok: 1–15 s, where P5 measured
    1–5 on 2026-09-28; the longest model goes to 30), `video_sizes` (grok:
    14) and `video_first_frame` (26 of 30).
  - A duration that is not listed is refused before sending: *"seconds: …
    does not make 99 s; it makes 1, 2, … 15. … Nothing was sent."*
- **Nothing in the listing says whether a model is local or bills an
  account.** The drivers know (`DriverInfo.locality`); only `owned_by`
  hints at it.

**What each door returned:**

| Door | Call | Result |
|---|---|---|
| Image | flux.2-klein-4b, 512x512 | 3.5 s. JSON with `data[0].b64_json`: a 512×512 JPEG, 101 KB, carrying a C2PA manifest. Also `output_format: "jpeg"`, `usage` in tokens (11 in, 1024 out) and `x_eugene_plexus` (driver, backend, latency, attempts, tier). **No price** |
| Speech | kokoro, 39 characters, mp3 | First byte at 0.42 s, done at 0.53 s. 21 KB `audio/mpeg`. What served it is in `x-eugene-plexus-*` headers. The metrics row has `characters: 39` |
| Transcription | whisper-large-v3-turbo, on that clip | 0.57 s: `{"text":" The bench is ready.","usage":{"type":"duration","seconds":1.525}}`. **Half the 3.07 s clip was heard.** The same bytes sent again with `verbose_json` came back whole, with `duration: 3.07` and 10 s billed. Seen once and not explained |
| Video | grok-imagine-video, 1 s, 854x480 | The create took 3.25 s and returned a `queued` job. Polled every 3 s, it was still `queued` at 3.4 s and `completed` at 24.9 s; progress went from 0 straight to 100. The content was a 444 KB `video/mp4`. The job comes back with `prompt: null` and `expires_at: null` |

- **The video handle names the key that made it** (`"o": "key:<id>"`,
  signed: P5-3/P5-4). Workbench uses one key for everyone, so the gateway
  cannot tell one person's job from another's. Workbench has to.
- **OpenRouter still served both videos' content** 9 and 6 minutes after
  they were made. It does not say how long it keeps them.

**Money.**

- The gateway passes no price or cost anywhere: not in responses, not in
  metrics.
- OpenRouter publishes prices:
  - video, per SKU in `/videos/models`, for grok: 5 cents a second at
    480p, 7 cents at 720p, and 0.2 cents per input image;
  - images, per endpoint, for flux.2-klein-4b: $0.014 per output megapixel.
- OpenRouter reports the billed `usage.cost` on a finished video. That is
  how the two videos below were priced.

**Spent this session: about $0.68.**

- **$0.65 on video, against P5's $10 budget**, which now stands at $0.85
  spent. **$0.60 of that was my mistake:** a call I sent as a "refusal"
  check asked for 12 s, which grok now makes.
- Two flux images, at most $0.014 each. One was the same kind of mistake
  (`333x333`, served).
- One speech clip and two transcriptions, a fraction of a cent.

## 1. Calls taken (Troy, 2026-10-08)

**All eleven taken as recommended.** M1–M9 shape slice 1; M10 and M11
apply when their slices come.

| # | The call | Taken | The main trade-off |
|---|---|---|---|
| M1 | Where the screens live, and their name | **One area with a tab per door**, at `/media/images`, `/media/speech`, `/media/transcription` and `/media/video`. It opens from a header button, **Bins · Media**, beside *Toolbox · Tools*. A tab shows only when a model serves its door, and the area always opens (§2.6) | A button per door would be quicker to reach, but it adds four buttons to a header that already has three |
| M2 | Where a request runs | **On Workbench's server, as answers do (W1).** Closing the tab loses nothing, images included | A paid image lost to a closed tab is money gone. The cost is a jobs table and a watcher, which mostly reuse `answers.py` |
| M3 | Whose results they are, and the owner's view | **Each result is its owner's (W4).** `ownerReadsChats` also covers media, and both its label and the standing line become *chats and media* | Two settings would let a business watch chats but not pictures. One is simpler, and it widens what an existing *on* covers, which the line then says |
| M4 | A storage limit | **None in this slice.** Each person sees their bins' total. A full disk fails the job and names the disk and its free space | A per-person cap now would protect a small disk, but nobody has asked for one, and every cap needs a setting and its wording |
| M5 | How a screen picks a model and builds its form | **Only models that list the door's surface.** The list is searchable and grouped by account (69 image models), and a person's last choice is remembered per door. **No model is picked on a first visit**, so a paid one is never chosen for them. The form offers only what the listing names, and **the gateway lists the image settings it already enforces** (§6.1) | Free-text fields, as the Playground has, need no contract change, but a beginner should not have to know that flux makes one image at a time |
| M6 | Cost on a paid backend | **Units, and a line on every external model:** *Runs on OpenRouter; that account is billed.* It needs `locality` in the listing (§6.2). Video also asks before sending, with the price where the provider publishes one (slice 3, §6.4) | A confirmation on every image is friction, and the line alone is easy to miss. The money that matters most is video's ($1.05 for grok's longest at 720p, and other models run to 30 s), and that gets the confirmation |
| M7 | Whether a result can go into a chat | **Yes, as a copy.** *Send to a chat* attaches an image or a speech clip to a new chat. A transcript goes into the composer as text. The copy belongs to the chat, so deleting either one leaves the other. Video cannot, because the gateway carries no video in a chat | A link instead of a copy saves disk, but then deleting a picture would break a chat |
| M8 | Deleting a result | **Each result can be deleted, and so can a whole tab's bin.** Stop works on a running job. A stopped video may still be billed, and the screen says so (P5-2: the provider's delete is not routed) | This is W7's first exception to *nothing is deleted but a whole chat*. Deletes are final; there is no trash |
| M9 | Slice 1's image scope | **Make, and edit from reference images** (66 of 69 models take them), chosen from the bin or uploaded. **Masks and partial images later**: a mask needs a canvas editor and works only on OpenAI's 10 | Masks now would double the slice for 10 models |
| M10 | Speech and transcription specifics (slice 2) | **The gateway checks `voice` against the listing,** as it does `n` and `seconds`. **OpenAI's documented voices are listed.** Recording is offered only where the browser allows it, meaning HTTPS or localhost, and elsewhere a line says why. A transcript shows how much audio was heard beside the clip's own length | Without the voice check, a typo reaches the provider and comes back as *"Provider returned 400"* |
| M11 | Video as a job (slice 3) | **A Work orders · Long jobs list.** The job is kept in the store and **polled again after Workbench restarts**, because the provider keeps running and billing. The result is **downloaded the moment it is done.** The price is shown before sending, from the listing (§6.4) | Resuming needs the handle stored. A job can be lost if the app's key changes, and then the gateway's words are shown |

## 2. The frame (slice 1, shared by every door)

### 2.1 Where it lives

- **Workbench has no router.** It has one path pattern (`/chats/<id>`) and
  flags for its other screens.
  - The media area adds the paths `/media/<door>` and `/media/<door>/<id>`,
    parsed beside `chatFromPath`. A link opens the right tab and result.
  - The server already answers every page path with `index.html`.
- **The header button** (M1) sits beside *Toolbox · Tools*.
- **Each tab** has its form on top and its bin below: that door's results,
  newest first, paged.

### 2.2 A request is a job on the server

- **`POST /api/media/<door>`** stores a `media` row with status `running`
  and starts a task, the way `Answers.start` does.
- **The task:**
  1. calls the gateway with the app's key;
  2. writes each returned file under `files/`;
  3. ends the row as `done`, `failed`, `stopped` or `interrupted`.
- **The page watches one stream per person,** `GET /api/media/events`
  (SSE). That is not one stream per chat, because one person can have
  several jobs running.
  - It reuses the `watch`/`publish` fan-out, the 15 s keepalive that
    re-checks the session, and the *reload* rule for a watcher that falls
    behind.
  - `events.ts` takes the URL as a parameter.
- **When Workbench restarts:**
  - an image, speech or transcription job that was running ends
    `interrupted`, and says it *may have been billed*;
  - a video is polled again (M11).
- **The prompt and settings are kept in the row,** so *Again* can re-send
  them. The gateway does not echo a video's prompt back (`prompt: null`).

### 2.3 Picking a model (M5)

- **The model list comes from `GET /v1/models`, every 20 s,** as the chat
  picker does. It is filtered on `x_eugene_plexus.surfaces`:
  - the Images tab takes `image`;
  - Speech takes `speech`;
  - Transcription takes `transcription`, and offers *Translate to English*
    when the model also lists `translation`;
  - Video takes `video`.
- **A model slot is listed like a model,** so the owner's slot (say,
  *pictures*) is how a business sets a shared default. No new setting is
  needed.
- **The list is grouped by account** (`owned_by`) and can be searched.
  Each entry shows *local* or the account it bills (§6.2).
- **The choice is remembered per person per door.** With none remembered,
  the picker is empty and asks.
- **The form offers only what the chosen model lists.** A setting that is
  not listed is not offered. A setting whose listing is null (*the backend
  checks*) gets a free-text box, marked *Checked by <account> when sent*.
  This keeps the Playground's rule (`playground-doors.md` §3) for a
  product screen.

### 2.4 What a result shows

- **The file,** shown or played in place, and a download.
- **What was asked, and what came back, side by side when they differ.**
  A size is read from the image's own bytes, so asking for 333×333 and
  getting 1024×1024 says both (*settings never lie*). The same goes for a
  transcript: *heard 1.5 s of a 3.1 s clip*.
- **What served it:** the model, the account, the latency and the
  attempts, from `x_eugene_plexus` or the `x-eugene-plexus-*` headers.
- **Units as measured** (M6): images and their size, characters spoken,
  seconds heard, seconds of video. No money appears until the gateway
  carries it (§6.4).
- **Actions:** *Again* (the same request), *Edit and send* (the form, filled
  in), *Send to a chat* (M7), *Use as reference* (images, M9) and *Delete*
  (M8).

### 2.5 Failures (standing rule: failures name their observed cause)

- **A refusal is shown in the gateway's words.** When the refusal carries
  `param`, that field is marked in the form, and the request is kept so
  the person can change one thing and send again.
- **A provider refusal that names nothing** (*"Provider returned 400"*)
  is shown as it is. Underneath it goes a line listing what was sent: the
  model and every setting. Slice 2's voice check (M10) removes the one
  case measured.
- **Workbench's own failures name their cause:** a full disk, with its free
  space (M4); a file the gateway answered that cannot be decoded; a job
  interrupted by a restart.
- **A key that is revoked or limited** gives the gateway's sentence, as
  chat does (C3).

### 2.6 When nothing serves a door

The media area always opens. **A door with no model says why, with the
*guide* mascot:**

- for everyone: *No model here makes images yet.*
- for the owner: *Add one in Eugene, under Backends, then Add a provider
  account*, with a link to the console. This is the W6 pattern.
- for anyone else: *Ask the owner of this Workbench to add one.*
- one line for everyone: *Image models that run on your own machines are
  coming later.*

With every door empty, as on Troy's install today, the area shows one
message, not four.

### 2.7 Whose, and who else sees it (M3)

- **Every media row and file has one owner** (`sub`), and every read is
  filtered by it, as chats are.
- **With `ownerReadsChats` on, the owner sees each person's bins, read
  only.** This extends the existing *People's chats* panel to media.
- **The job-site redaction (J13a) has nothing to hide here.** The media
  doors call the gateway only, never a job site's tools.
- **`GET /api/files/{id}` re-checks the file's owner.** Today it checks
  the chat's owner and relies on file ids being unguessable. A media file
  has no chat, so the check moves to the file's own `owner`, and the
  owner's read goes through the setting.

### 2.8 Storage (M4)

- **The bytes stay where W7 put them,** under
  `files/<sha256(sub)[:32]>/<id>`. The database never holds them.
- **New types** are accepted when a door returns them:
  - `image/webp`, when a model lists it as an output format;
  - `audio/ogg` (opus), `audio/aac` and `audio/flac`, when a speech model
    lists them. mp3 is the default, and pcm is not offered, because a
    browser cannot play raw pcm;
  - `video/mp4`.
- **Bytes are sniffed, as W7 does now,** and a mismatch fails the job and
  names both types.
- **`GET /api/files/{id}` streams from disk** and answers `Range`
  requests, so audio and video can seek. Today it reads the whole file
  into memory.
- **Each person sees their bins' total** at the foot of the area.

## 3. Images (slice 1)

- **The form:**
  - prompt;
  - shape: *Square* (1024x1024), *Wide* (1536x1024), *Tall* (1024x1536),
    or *Model's choice* (no `size`). *Custom* takes a typed WxH;
  - *how many*, up to the listed `n`;
  - quality, background and format, each only where listed;
  - reference images, between the listed minimum and maximum, from the bin
    or uploaded.
- **References go as the gateway takes them:** JSON with `data:` URLs on
  `/v1/images/edits`. The P4 SDK path, multipart, is not needed by a
  server.
- **Sizes are not listed anywhere.** The shapes are OpenAI's gpt-image
  sizes. OpenRouter maps them to its aspect ratios. OpenAI's API refuses a
  size its model does not make, and that refusal is shown (§2.5). The
  result's real pixel size is always shown (§2.4).
- **A refusal costs nothing.** `n`, `stream`, references, quality,
  background and format are all checked before sending (*"Nothing was
  sent"*).
- **Several images from one request are one result** with several files.
  Each can be deleted, sent to a chat or used as a reference on its own.
- **Not in slice 1 (M9):** masks, partial images while streaming, and
  variations, which P4-2 refuses.

## 4. Speech and transcription (slice 2)

- **Speech:**
  - the form is text, voice and format;
  - **voices are listed and searchable** (kokoro has 54). OpenAI's are
    listed once the driver lists them (M10). A model whose voices are null
    gets a free-text voice box;
  - the clip is saved, then played. The stream's first byte comes at
    0.4 s, so playing it while it streams is later work;
  - *Send to a chat* attaches the mp3 or wav as `input_audio`.
- **Transcription:**
  - an upload, or a recording where the browser allows one. Microphone
    access needs HTTPS or localhost, and over plain LAN HTTP the button is
    replaced by a line saying why;
  - language, optionally;
  - *Translate to English* when the model lists `translation`;
  - the text, with *heard N s of M s* from `usage.seconds` against the
    clip's own length, as measured in §0;
  - **Copy** and **Send to a chat** (into the composer).
- **Measured in slice 2, before building on it:** which backends take a
  browser recording (Chrome makes `webm`/opus), and whether the half-heard
  clip happens again.

## 5. Video (slice 3)

- **The form:**
  - prompt;
  - duration and size, from the listing;
  - a first frame, where listed, from the bin or uploaded.
- **Sending asks first** (M6, the Playground's P3 call): *12 s at 480p.
  About $0.60, billed to OpenRouter.* The price comes from the listing
  (§6.4), or, when no price is listed, *Billed per second by OpenRouter.*
- **Work orders · Long jobs** lists running and finished videos, with
  their state and how long they have run. Grok has no progress (0 → 100),
  so the screen says *Working, 18 s so far* and the *working* animation
  plays (`workbench.md` §6.1).
- **The Foreman** polls each running job from the server, every 5 s. It
  stores the gateway's handle in the row, so a restart resumes polling
  (M11). When a job is done, the Foreman downloads the content into
  `files/` at once, because the provider's retention is unknown.
- **When a poll fails, the job ends with the gateway's words.** For a
  handle bound to an older key, that is *"No video job … for this key."*,
  and the screen adds that the job *may have been billed*.

## 6. Contract changes (apps call #1: a gap is fixed for every client)

### 6.1 Slice 1: the image settings the gateway already enforces

`ModelRoutingInfo` gains what the driver reports in `ImageCapabilities`.
The gateway already holds these values and refuses on them:

- `image_max_images`
- `image_qualities`
- `image_backgrounds`
- `image_output_formats`
- `image_min_references` and `image_max_references`

Null keeps meaning *the backend checks*, and `[]` keeps meaning *not
taken*. **The gateway is the only component that changes;** the driver
already sends these. The console's Playground can use them later, in place
of its free-text boxes.

### 6.2 Slice 1: whether a model runs locally

`ModelRoutingInfo.locality` is `local`, `external` or `unknown`, taken from
the serving drivers' `DriverInfo.locality`:

- `external` if any tier is external;
- `local` only if every tier is local.

This drives the *that account is billed* line (M6). *External* does not
always mean billed: a subscription, or a friend's server, is external too.
So the line names the account rather than claiming a charge.

### 6.3 Slice 2: voices

- **The gateway refuses an unlisted `voice` before sending,** naming the
  listed ones, as it does `n` and `seconds`.
- **The OpenAI driver lists its documented voices** for its TTS models, so
  the refusal and the picker both have something to name.

### 6.4 Slice 3: what a video costs

- **Before sending:** `video_prices`, from OpenRouter's `pricing_skus` (for
  example, cents per output second by resolution, and per input image),
  carried through the driver.
- **After a video is done:** the job's `x_eugene_plexus.cost_usd`, when the
  provider reports `usage.cost`.
- **This is the gateway's first money.** It is enough for video's
  confirmation. Money across chat, metrics and per-person limits is its own
  later design (*per-person usage at the gateway*, sign-in call 1).

## 7. What the store keeps (schema 7)

- **`media`:**

  | Column | Holds |
  |---|---|
  | `id` | the result's id |
  | `owner` | the person (`sub`) |
  | `door` | images, speech, transcription or video |
  | `model` | the model asked for |
  | `request` | JSON: prompt or text, and settings |
  | `status` | running, done, failed, stopped or interrupted |
  | `created_at`, `finished_at` | when it started and ended |
  | `served` | JSON: driver, backend, latency, attempts, request id |
  | `units` | JSON: images and size, characters, seconds |
  | `text` | a transcript |
  | `error` | JSON: the gateway's message, `param` and status |
  | `job` | video only: the handle and the last poll |

- **`files` gains `media_id`.** `chat_id` becomes nullable, and a file has
  exactly one of the two. Sending to a chat (M7) copies the bytes to a new
  file with a `chat_id`.
- **Migration 6 → 7** follows the existing `_MIGRATIONS` pattern, in one
  transaction.

## 8. The API

| Route | Does |
|---|---|
| `GET /api/media/doors` | The doors this key can use, each with its models and their form fields, shaped by the server as `api.py` shapes the chat list |
| `POST /api/media/{door}` | Starts a job and returns its row |
| `GET /api/media?door=&before=` | The person's results, a page at a time |
| `GET /api/media/{id}` | One result |
| `DELETE /api/media/{id}` | Deletes the result and its files (M8). A running job is stopped first |
| `DELETE /api/media?door=` | Deletes that tab's whole bin, after a `ConfirmButton` |
| `POST /api/media/{id}/stop` | Stops a running job |
| `POST /api/media/{id}/to-chat` | Copies the result into a new chat (M7) and returns the chat |
| `GET /api/media/events` | SSE: this person's jobs |
| `GET /api/people/{sub}/media` | The owner's read-only view, only with the setting on (M3) |

Every route that changes something checks the owner; the owner's view gets
a 404 there, as chats do. Each route carries the session cookie and the
`X-Workbench-Secret` header, as every route does now.

## 9. The checks (slice 1)

**The real-environment acceptance** extends `scripts/c3-workbench-acceptance.py`
or sits beside it. It runs real processes on test ports:

- a control root, an agent and a gateway at the new pin;
- the **real `openrouter` driver** pointed at P4's fixture (`acme/flux`
  makes one image at a time; `acme/mini` makes up to 10 and takes
  quality);
- Workbench installed from the pinned archive.

Chrome drives it. `--live` adds one real flux image, about a cent.

- **A model with no `image` surface is never offered.** The chat-only
  install shows the empty state with the owner's link.
- **A closed tab loses nothing.** The fixture holds the image for 2 s; the
  tab closes; another tab opens and finds the image in the bin.
- **The form offers what the listing says:** at most 1 for flux, 10 for
  mini; quality only on mini.
- **A refusal shows the gateway's words** and marks the field (`n` past
  the limit, sent through the API).
- **Another person cannot fetch my image by id** (404). The owner can,
  only with the setting on, and the standing line says *chats and media*.
- **Send to a chat** copies the file. Deleting the result keeps the
  chat's copy, and deleting the chat keeps the result.
- **Delete removes the file from disk.**
- **External models show the account line; a local fixture model does
  not.** This needs §6.2.
- **A restart mid-image** ends the job `interrupted`, with *may have been
  billed*.
- **The asked and returned sizes** both show when they differ. The fixture
  answers an image whose size differs from the one asked.

**Unit tests** cover the changed files, in both the gateway (§6.1, §6.2)
and Workbench. **Sabotage covers only the changed code**, and each check
is run once against a sabotaged copy to prove it can fail.

## 10. Order (slice 1)

1. **Contract:** §6.1 and §6.2 in `gateway.yaml`. Regenerate every
   consumer whose codegen names it, and diff.
2. **The gateway:** the new listing fields, with unit tests.
3. **Workbench:**
   - the store (schema 7);
   - the media job runner, the API and the file-route changes;
   - the front end: the paths, the area, the Images tab and the bin;
   - the tests and the Chrome check.
4. **The `dist` branch,** then the agent's catalogue at that commit.
5. **Pins:** the gateway, and both installers.
6. **One acceptance run of record**, then the slice's sabotage pass.

## 10a. What building slice 1 found (2026-10-08)

Built the same day the calls were taken: specs `9e6125f` (contract),
gateway `e7488dc`, Workbench `09d2e62` (`dist` `eff62e2`), agent `e1ea390`.
The run of record (`c3-workbench-acceptance.py --browser --openrouter-live`)
passed 47 of 47.

- **The gateway lists what it already enforced.** `_image_listing` in
  `routing.py` builds every image field from the drivers'
  `ImageCapabilities`, the same values `rules_out` routes on. A slot lists
  what *some* backend takes (the largest limit, the union of choices) and
  null once one backend leaves a field to its own API, because a request
  routes to any backend that takes it. The first tests covered only
  single models; the sabotage pass found that a slot mixing flux with an
  OpenAI model, and a chat model's `image_min_references`, went unchecked.
  Both are tested now (7 of 7 caught).
- **A file is guarded by what it belongs to, and by its own owner.**
  `GET /api/files/{id}` reads a chat's file through the chat and a media
  file through its row, and either way checks the file's own `owner`
  matches. It now streams from disk with `FileResponse`, which answers
  `Range` (206), where it used to read the whole file into memory.
- **Schema 7 makes `files` again.** SQLite cannot drop `NOT NULL`, so
  migration 7 copies the table. A store from before attachments had no
  `files` table at all, so the migration creates schema 1's first.
- **A graceful restart never exercised the boot sweep.** Shutdown marks
  its own running requests `interrupted` (`MediaJobs.aclose`), so the
  first restart test passed with the boot sweep removed; the sabotage
  pass found it. Only a row left `running` while Workbench was stopped,
  as a crash leaves one, tests the sweep.
- **One watcher set per person.** The first build kept watchers in a set
  of dataclasses, which are unhashable by default; the event-stream test
  caught it (`eq=False`).
- **"Bins" passes the copy gate only with its plain meaning.** The page's
  workshop-name test (`words.test.ts`) now holds each built name to its
  pair, *Toolbox · Tools* and *Bins · Media*. It reads comments too, and
  caught one in `ChatView.tsx`.
- **Back now resets every screen.** The address handling for
  `/media/<door>` fixed workbench#4 on the way: `popstate` did not reset
  the Job sites screen.
- **A sent image waits in the new chat's composer.** *Send to a chat*
  creates the chat with the copy attached on the server; the page opens it
  with that file already pending, so the person writes the question.

## 10b. What building slice 2 found (2026-10-08)

**Measured first** (throwaway install, Troy's keys; under $0.02):

- **A Chrome recording works everywhere measured.** Chrome's
  `MediaRecorder` makes `audio/webm;codecs=opus`. OpenRouter's
  whisper-turbo, OpenAI's whisper-1 and gpt-4o-mini-transcribe, and
  ElevenLabs' scribe_v2 each transcribed a 3.07 s recording correctly.
- **The half-heard clip is reproducible, and specific.** OpenRouter's
  whisper-turbo heard 1.525 s of kokoro's 3.07 s MP3 three times out of
  three, as `json` and as `verbose_json`. It heard the same speech whole
  as WebM, and whisper-1 heard the MP3 whole. It looks like that
  provider's MP3 decoding, not the audio. The upstream report is Troy's to
  make, if he wants one.
- **"Heard" is only a claim when it falls short.**
  - `verbose_json` carries `duration` on three of the four backends, but
    OpenAI's gpt-4o-mini-transcribe refuses it (its own 400).
  - OpenAI's `json` counts whole seconds rounded up: 4.0 for 3.07 s.
  - So Workbench asks `json`, and says *heard N s of M s* only when N is
    short of M by more than a quarter second. Otherwise it gives only the
    clip's length.
- **OpenAI's voices differ by model family.** `tts-1` (and `-hd`, dated)
  takes nine voices and refuses `ballad`, `cedar`, `marin` and `verse`.
  `gpt-4o-mini-tts` takes all thirteen. The driver lists them per family
  (inference-driver `334954a`). A TTS id outside those families still
  lists none.

**Built:** specs `902b737` (the speech door's contract wording),
inference-driver `334954a` (OpenAI's voices per family), gateway
`48f5d59` (the voice check; sabotage 6 of 6, with the driver's), and
Workbench `27b36f7` (below), shipped as `dist` `53004e4` from agent
`33e2c9a`'s catalogue. The C3 run passed 54 of 54
([record](../acceptance/workbench-media-speech-run.md)).

- **The voice check changed one of P3's checks.** P3's acceptance check 6
  asserted P3-3's pass-through: `alloy` to an ElevenLabs model that lists
  its voices, relayed as ElevenLabs' own 404. Under M10 the gateway now
  refuses it first, naming the voices, and nothing is sent. The check now
  asserts that, and the P3 run passes 27 of 27. A model that lists no
  voices still passes the voice through.
- **P3's sabotage script had two dead anchors** from earlier refactors
  (specs#17). It refuses to start until they are re-anchored.
- **ElevenLabs lists voices by id** (`CwhRBWXzGAHq8TQ4Fs17`). The picker
  shows what the listing has. Names need a contract change, the voices'
  names beside their ids, which is banked for Troy.
- **A recording is measured by the clock; an upload by decoding.**
  Chrome's WebM recordings carry no duration, so the page times a
  recording itself, and decodes an upload with `decodeAudioData`. Either
  way the length rides the request as `clipSeconds`.
- **A transcript goes to a chat as the new chat's unsent text.** It is
  saved as that chat's draft. No server copy is needed, since text is not
  a file.
- **Recording needs a secure context.** HTTPS, or `localhost` on the
  machine itself. The Chrome check records with Chrome's fake microphone
  on `127.0.0.1`. Over plain LAN HTTP, the page says why there is no
  Record button.

## 11. Not in this design

- **Local media models**, which need their own admission design
  (`workbench.md` §8).
- **Masks, partial images and streamed playback** (M9, §4).
- **Images in a chat's answers.** W5 shows an image in an answer as a
  link, and model-made images in chat are their own question.
- **Making media from a chat message** (*make an image of this*). Sending
  the other way, into a chat, is M7.
- **Per-person rights to paid models,** *the shop*. For now, the app key's
  `allowedModels` decides for everyone.
- **Money beyond video's confirmation** (§6.4).
- **Batches of images as work orders.** A batch is one request with `n`
  until someone asks for more.
- **Banked from reading the code:** the composer's *Remove* leaves the
  uploaded file on disk, where it still counts toward the chat's 11 MiB,
  and `popstate` does not reset the Job sites screen. Filed as
  [workbench#3](https://github.com/eugene-plexus/workbench/issues/3) and
  [workbench#4](https://github.com/eugene-plexus/workbench/issues/4).
