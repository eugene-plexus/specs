# P4: images at `/v1/images/*` — record

**2026-09-28. Built, run and pinned in both installers** (inference-driver
`e484972`, gateway `3e54fbb`). Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§10, calls P4-1 to P4-4. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §9
($0.139 of OpenRouter).

| Repo | Commit |
|---|---|
| specs (contract) | `8455ff2` |
| inference-driver | `e484972` |
| gateway | `6be3f0a`, `3e54fbb` |

- **`scripts/p4-images-acceptance.py`**: 15 fixture checks, in specs CI.
  `--live` adds two OpenRouter checks. **17 of 17 PASS with `--live`.**
- **`scripts/p4-sabotage.py`: 31 of 31 caught**, and two declared escapes: the
  driver's own refusals of a mask and of a stream it cannot give, which the
  gateway's routing reaches first (removing both layers is caught, twice).
  **The first pass escaped one and it named a missing check:** the gate sent
  `quality: high` with `n: 2`, and `n` alone rules flux out, so the quality
  rule was never isolated. The gate sends one setting per request now, and
  that sabotage is caught.
- **Unit suites:** inference-driver 802 (20 new), gateway 925 (26 new, plus a
  v7 metrics migration test). The new test modules do not import against the
  previous source, which has no image schemas.

## The done-when

**The same SDK call works against OpenAI and OpenRouter.**
`client.images.generate(model=..., prompt=..., size="1536x1024")` from the
unmodified OpenAI SDK (3.20.0) is answered through an OpenRouter account's
flux and an OpenAI account's `gpt-image-1`, as `b64_json` the SDK decodes.
OpenAI's half is proven against a fixture playing its API from its own spec,
since there is no OpenAI key; OpenRouter's is proven live as well: flux made a
512×512 image and edited it, and `gpt-image-1-mini` streamed one.

**A URL input is refused.** An edit whose `image_url` is not a `data:` URL is
a 400 naming `images[0].image_url` ("is not fetched"), a `file_id` a 400
naming `images[0].file_id`, and nothing reaches an upstream. The same edit
with a `data:` URL is served.

## What it does

- **Two doors, OpenAI's shapes.** Generation is JSON. An edit is multipart,
  as the SDK sends it (`image` for one image, `image[]` for several, `mask`),
  or OpenAI's JSON form with `data:` URLs. An image's type is read from its
  bytes: the SDK labels a `BytesIO` `application/octet-stream` (measured).
- **One normalised driver request** (`POST /v1/image`, call #9): an edit is a
  generation with `references`. OpenRouter has no edit route and takes the
  images as `input_references` objects on `/images/generations`; OpenAI gets
  its own multipart `/v1/images/edits`. `dall-e-*` is asked for `b64_json`,
  since it answers a URL otherwise, and a GPT image model is sent no
  `response_format`, which it refuses.
- **Settings route by each model's own listing**, which on OpenRouter is only
  `GET /images/models`: the main listing's parameters for an image model are
  chat-style. A listed `n`, `quality`, `background` or `output_format` goes
  only where the listing takes the value. An unlisted `quality` or
  `background` is not taken, because flux answered an opaque JPEG with a 200
  for `background: transparent` (measured). An unlisted `output_format` is
  carried, because `gpt-image-1-mini` honours it, and the answer says what the
  image is. With nothing in the slot able to take a request, a 400 names the
  setting and each model's reason; `auto` never counts.
- **Tiers, as chat.** `pictures → [flux, mini]` with `quality: high` never
  asks flux; with flux rate-limited it is answered by mini at tier 2; a
  provider's content filter is relayed with its words and does not cascade.
- **Streaming (P4-3)** only to a model that streams, or a 400 naming
  `stream`. The first event is the commit point. The stream relays each
  partial render as it arrives (1.2 s apart in the fixture, arriving 1.2 s
  apart through the SDK), fills every field OpenAI's events require
  (OpenRouter's carry none of them), sends one `completed` per image, and puts
  the routing envelope on the last.
- **`mask` only to OpenAI's API**; an edit-only model makes no generation.
- **`response_format: url` is ignored (P4-1)**; OpenRouter's `aspect_ratio`,
  `resolution` and `seed` are refused by name, pointing at `size` (P4-4);
  `/v1/images/variations` answers a 400 (P4-2).
- **Metrics schema v8:** a row counts its images beside the tokens; a v7
  store migrates in place.
- **All three doors** are under client admission, CORS and the body limit
  (edits 36 MiB, for 25 MiB of images as base64 `data:` URLs).

## Found on the way

- **OpenRouter's image guide is wrong about `input_references`.** It shows
  plain `data:` strings; OpenRouter answers them with a Zod 400 (*expected
  object, received string*). Objects `{"type": "image_url", "image_url":
  {"url": ...}}` are what it takes (measured), and a sabotage sending strings
  is caught.
- **OpenRouter validates a listed setting and ignores an unlisted one**, and
  its listing is not complete: flux silently drops an unlisted `background`,
  while `gpt-image-1-mini` honours an unlisted `output_format`. So the rule is
  not "the listing is the truth" but "trust it where it names a value", with
  `output_format` labelled after the fact.
- **A streamed image was recorded as an error.** The route stopped reading at
  the final event, so the tiered client, which marks an attempt served when
  its stream ends, never did. The route now reads past it. Found by the
  gateway's metrics test; the acceptance now checks it through the real
  processes, and a sabotage putting the early stop back is caught.
- **An existing test file was overwritten.** The gateway's image-attachment
  tests live in `tests/test_images.py`, the name first chosen for the new door
  tests; the file was replaced and 20 tests vanished from the count. Restored
  from `HEAD` before anything was committed; the door tests are
  `tests/test_image_doors.py`. The suite's count is how it was noticed.
- **Control's CI ruff was newer than its pre-commit ruff**, so the keyring
  probe's `try/except/pass` passed the hook and failed CI (`2cf09ab`); fixed
  with `contextlib.suppress` (`847200f`), as the agent's copy already was.
- **`TieredClient`'s whole-answer tier walk is one helper now**, shared by
  transcription and images, rather than a third copy of the loop.

## Not done, named

- **OpenAI's own image API is untested live**: there is no OpenAI key. It is
  classified by id (`gpt-image-*`, `dall-e-*`) and carried as its API checks.
- **Live streaming gave no partial render.** `gpt-image-1-mini` at low quality
  answered in 7.5 s with one `completed` event, although `partial_images: 1`
  was sent (the fixture proves it reaches the upstream). OpenAI's contract
  says *up to* N partials, and the morning's probe got one at 3.6 s.
- **No local image engine.** stable-diffusion.cpp and other OpenAI-shaped
  servers are unmeasured (§6), and a custom account lists its models as chat.
- **No keepalive on the gateway's image stream.** OpenRouter sends `: `
  comments every 0.4 s; the gateway relays events only, so a proxy with a
  short idle timeout could cut a slow render.
- **No `ui` screen consumes P4.**
- **Agent, control and library pin P3's specs.** Only `inference-driver.yaml`
  and `gateway.yaml` changed, which none of them generates from.
