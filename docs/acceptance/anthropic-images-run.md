# Images on the Anthropic door — a real vision engine, a real Claude Code

**Run 2026-09-23 on this box.** llama.cpp b10948 serving Gemma 4 E4B
(`gemma-4-E4B-it-Q4_K_M.gguf` with `mmproj-gemma-4-E4B-it-BF16.gguf`, the same
files and SHA-256 as the [A4 run](a4-application-workflows.md); `-ngl 0`,
projector on the CPU, `-c 32768`) → the real `eugene-plexus-inference-driver`
(`6391945`, unchanged) → the real `eugene-plexus-gateway` (`3ac2a3e`) →
`r4-stubs.py agent`, plus a real Claude Code 2.1.207 (agent-sdk 0.3.280).
[`scripts/anthropic-images-acceptance.py`](../../scripts/anthropic-images-acceptance.py):
**10 PASS, 0 FAIL, second execution.** Contract `b7f3cc6`. Both installers
re-pinned to gateway `3ac2a3e`; `ui` deliberately not re-pinned (no screen
reads an Anthropic content block).

## 0. What Claude Code actually sends, captured before anything was written

`scripts/r4-capture.py --mode imageread` answers Claude Code's first turn with a
`Read` of a file the operator names, so its next request carries the client's
own image:

| Read of | Arrived as |
| --- | --- |
| a 64×64 PNG (184 bytes) | a `tool_result` whose `content` is **one `image` block and no text** — `{"type": "base64", "media_type": "image/png", "data": …}`, the file's own bytes; `cache_control` on the result |
| a 4000×3000 noise PNG (36 MB) | the same shape, as a **490 KB `image/jpeg`**: the client resizes and re-encodes before sending |
| a small `.webp` | `image/webp`, **as itself** |
| a small `.gif` | `image/gif`, **as itself** |

So the commonest way an image reaches this door is inside a tool result, which
an OpenAI backend has no slot for (a `tool` message carries text; image parts
ride on user messages), and a door taking PNG/JPEG only would refuse `Read` of
two file types the client passes through untouched. Our limits (5 MiB, 8192 px)
never bite on a large image because the client has already shrunk it.

## 1. What was built

- An `image` block with a `base64` source becomes an inline image part and
  takes the OpenAI door's path from there — the same limits, the same "is it
  the picture it claims to be" check, and **routing only to a backend that
  confirms image input**, so a text-only model is never asked (400, nothing
  forwarded or woken).
- **A tool's picture moves.** The `tool` message keeps its call id and says, in
  a bracketed line, that the tool returned an image attached to the next user
  message; that user message follows the turn's tool messages at once and opens
  with `The image returned by tool call <id>:` and the picture, ahead of the
  person's own words. A person's own image block stays where they put it.
- **GIF and WebP are re-encoded to PNG**, losslessly; an animated one is
  refused. PNG and JPEG pass through byte for byte.
- A `url` source is refused and **never fetched**; so is a Files API `file`
  source. An image on an assistant or system turn is refused. `document` stays
  refused. Every refusal names the block in the caller's coordinates
  (`messages.2.content.0.content.0.source`).
- One `ImageBudget` holds the per-request limits for both doors.

## 2. What the run proved

| # | Check | Evidence |
| --- | --- | --- |
| 1 | The driver confirms image input from the engine's own `/props` | `imageInput: true` |
| 3 | A user image block reaches the engine — **as a pair** | red → `Red`, blue → `Blue` |
| 4 | The picture's tokens are in the prompt | 111 input tokens with the image, 28 without |
| 5 | Streamed, same | `Blue`, stream ends at `message_stop` |
| 6 | Claude Code's shape (a `tool_result` holding a lone image) is seen — as a pair | red → `Red`, blue → `Blue` |
| 7 | WebP is re-encoded and still seen | green → `Green` |
| 8 | A URL source is a 400 naming the block, never fetched | `messages.0.content.0.source: send the image inline as base64…` |
| 9 | **A real Claude Code `Read`s `sample.png` and answers from it** — one file name, two colours | red → `red` (11 s), green → `green` (12 s) |
| 10 | `/context` answers without `count_tokens` — by falling back to inference | 14 `count_tokens` 404s, 14 `/v1/messages` requests (see §4) |

`scripts/anthropic-images-sabotage.py`: **19 of 19 caught**, restoring from a
copy after a baseline. The over-corrections covered: the picture left after the
person's words, without its call id, or with the tool's error flag lost; an
image accepted on an assistant turn; a URL source let through; GIF/WebP passed
through as themselves or refused outright; an animated GIF flattened; the
re-encode skipped; the limit counted per block rather than per request, on
either door; the refusal naming the turn rather than the block; adjacent text
blocks no longer joined.

## 3. The run's findings

**Two instruments were wrong on the first execution; the product was not.**
(a) Check 4 asked for the prompt to grow by "more than 100" tokens and Gemma 4
E4B spends **83** on a 224×224 image; the threshold is 32 now, well clear of any
text difference. (b) The Claude Code check asked for a colour in free words and
the model answered **"Emerald"** — a green, from a file whose name says nothing,
so it had seen the picture and the check failed it. It asks from three words
now, twice, with one file name in two colours. A third check read the engine's
log for an image encode: llama.cpp b10948 logs none at its default level, and
the driver deliberately never logs an image payload, so that check was deleted
rather than loosened — the pair is the direct evidence.

**Two unit tests had been asserting the rule this change removes, and would
have kept passing.** `test_an_image_block_is_refused_naming_the_field` and its
nested twin sent a four-character "PNG" and asserted `"image" in message`. With
images carried, that payload is refused for being no picture at all — and the
old assertion could not tell the two apart. Both are amended to name the block
and the reason.

**The four-image limit counts the whole conversation.** A client sends its
history on every request, so a Claude Code session that has read five
screenshots is refused on every turn after the fifth until it compacts or
clears. The refusal says which block tipped it. Recorded in the contract; the
limit itself is unchanged and is Troy's to revisit.

## 4. Two measurements for the rest of slice 3

**`message_start` carries `input_tokens: 0` and Claude Code does not care.**
`r4-capture.py --usage-in start|delta` reported 31,337 input tokens on
`message_start` only, or on `message_delta` only. Both the
`--output-format json` result and the session transcript — which is what the
client's context accounting reads back — held **31,337 either way**. Auto-compact
did not fire from `-p` mode at 39,000 (with `CLAUDE_CODE_MAX_CONTEXT_TOKENS`),
at 199,000, or inside a single tool loop, in either placement, so that half is
not reachable from print mode and is recorded as unmeasured. **No fix:** the
count is not known until the backend finishes, and the client keeps the one on
`message_delta`.

**`/context` calls `POST /v1/messages/count_tokens?beta=true` 13–14 times, and
without it Claude Code counts by inference.** Captured through the SDK's
`--input-format stream-json` (print mode sends `/context` to the model as text).
The bodies are `{model, messages, system?, tools?}` with no `max_tokens`, one
per category (system prompt pieces, tool groups, skills). Against this gateway,
which has no such route, every 404 was followed at once by a real
`POST /v1/messages` on the same connection; the engine evaluated prompts of up
to **9,050 tokens for one output token each** (17.8 s apiece on this CPU). The
table `/context` printed was right — the counts are the engine's own — but one
diagnostic command cost fourteen prefills, would wake an idle-unloaded model, and
lands fourteen one-token requests in `GET /v1/metrics`. **Built the same day:**
[the count_tokens run](count-tokens-run.md) — 14 counts answered, no fallback.

## 5. Not done

- Only llama.cpp served an image. vLLM and a hosted vision model were not run.
- No image refusal was seen by Claude Code live (the five-image case, a URL).
- A `.gif` was re-encoded in the unit tests only; the live run used WebP.
- The OpenAI door still takes PNG and JPEG only; no client of it was measured
  sending anything else.
