# P5: videos at `/v1/videos`, as signed jobs — record

**2026-09-28. Built, run and pinned in both installers** (inference-driver
`c9e0dcb`, gateway `ccfaa7c`). Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§11, calls P5-1 to P5-4. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §10.
**Video spend: $0.204 of the $10 Troy granted** ($0.102 measuring, $0.102 for
the live acceptance, read off OpenRouter's usage counter).

| Repo | Commit |
|---|---|
| specs (contract) | `c09b264` |
| inference-driver | `c9e0dcb` |
| gateway | `ccfaa7c` |

- **`scripts/p5-videos-acceptance.py`**: 8 fixture checks, in specs CI.
  `--live` adds two OpenRouter checks. **10 of 10 PASS with `--live`.**
- **`scripts/p5-sabotage.py`: 19 of 19 caught**, with two declared escapes:
  the gateway's and the driver's refusals of a first frame for a model that
  takes none each hide the other's removal (removing both is caught).
- **Every acceptance script CI runs passed locally against the working
  trees before this pin** (15 scripts), the rule P4's first pin taught.
- **Unit suites:** inference-driver 816 (12 new), gateway 948 (22 new, plus a
  v8 metrics migration test). The new test modules do not import against the
  previous source, which has no video schemas.

## The done-when

**A job submitted through one gateway is polled and downloaded through it.**
The unmodified OpenAI SDK's `client.videos.create_and_poll(...)` submits
through the gateway, which asks OpenRouter in its own shape, polls to
`completed`, and `download_content` streams the MP4 back as it arrives. Live:
`x-ai/grok-imagine-video` made one second at 480p from text and one from a
first frame.

**Another key's poll is refused.** The same handle, retrieved or downloaded
with another client key, is a 404, as is a tampered handle; the key that made
the job still reads it.

**A restart loses nothing.** A job submitted, the gateway stopped and started
again, then polled to `completed` and downloaded: in the fixture run and live.
The handle carries the job, and the gateway's secret, made once beside its
config, still verifies it.

## What it does

- **OpenAI's door, OpenRouter's backend.** OpenAI shut its video API down on
  2026-09-24 (`sora-2` and `sora-2-pro` carry that `shutdown_date`, and
  `/v1/videos` answers an empty 404), so the SDK's `client.videos` is served
  here and the driver translates: `seconds` becomes OpenRouter's integer
  `duration`, `size` is sent as is, and `input_reference` becomes
  `frame_images` with `frame_type: first_frame`. **The SDK sends every
  `create` as multipart** (captured), so the form is the main path.
- **The handle is the job** (call #5): `video_` and a payload naming the
  driver, its node, the model, OpenRouter's job id, the owner, and the
  `seconds` and `size` asked for, signed with the gateway's own secret
  (P5-4). There is no store.
- **The owner is the key** (P5-3): a client key's job is readable only with
  that key; an operator session's by any operator session.
- **A poll goes to the one driver that holds the job**, by `(node, name)`. A
  driver that is gone is a 503 saying the job is not lost; a job the upstream
  forgot is a 404.
- **OpenAI's words:** OpenRouter's `pending` is `queued`, `progress` is 0
  until the job ends and 100 when it completes (OpenRouter reports none), and
  a failure is `{code: "video_generation_failed", message}` with the
  provider's reason.
- **Settings route by the model's listing** (OpenRouter's `/videos/models`,
  supplementary like the images listing): `seconds` (any whole number a model
  lists, P5-1), `size`, and a first frame only to a model that takes one. A
  URL or `file_id` reference is refused (A4).
- **Failover at submit only**: with grok rate-limited, `clips → [grok, wide]`
  was accepted by wide at tier 2, and the job stayed wide's.
- **Refused:** `variant` other than `video` (OpenRouter ignores it and
  answers the MP4, measured), `GET /v1/videos` (no store). Remix, edits,
  extensions and delete are **not routed** (P5-2).
- **An OpenAI account stops listing a model past its `shutdown_date`**, both
  Sora models today, and makes no videos.
- **Metrics schema v9:** the submit's row counts the seconds asked for.
- **`/v1/videos/{video_id}` is the first door with a path parameter**:
  admission and CORS hold route templates now, matched in one place
  (`door_paths.py`).

## Found on the way

- **OpenAI's video API is gone** although its published spec of two days
  later still describes it; its SDK now warns *"The Sora API is scheduled to
  permanently shut down on September 24, 2026."* on every call.
- **OpenRouter reports no progress and no `in_progress`**: a job is
  `pending` until it is `completed` (24 s and 47 s here) or `failed`.
- **A bad first frame is accepted and fails later**, with a string `error`
  and no charge: a 1×1 PNG failed 17 s after submit.
- **OpenRouter's content ignores `Range`**, so a download is whole.
- **The gate's own direct calls first sent a urlencoded form**, which the
  door rightly refused as not JSON; the SDK always sends multipart, and the
  gate does too now.

## Not done, named

- **OpenRouter's `openai/sora-2-pro`** is still listed there and untried.
- **A job's expiry is unknown**: OpenRouter does not say how long content
  stays, so `expires_at` is null.
- **No `ui` screen consumes P5.**
- **A per-key spend limit is still deferred**, and videos are the costliest
  door yet (5¢ a second at 480p on the cheapest model).
