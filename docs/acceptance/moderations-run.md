# P6a: `/v1/moderations` and `GET /v1/models/{model}` — record

**2026-09-28 (late). Built, run and pinned in both installers**
(inference-driver `a2583a9`, gateway `8435420`). Design:
[`openai-inference-compatibility.md`](../design/openai-inference-compatibility.md)
§12, calls P6-1 to P6-4. Measured first:
[`provider-accounts-measurement.md`](provider-accounts-measurement.md) §12.

| Repo | Commit |
|---|---|
| specs (contract) | `c7b7ec8` |
| inference-driver | `a2583a9` |
| gateway | `8435420` |

- **`scripts/p6-acceptance.py`**: 5 fixture checks, in specs CI. `--live`
  adds two OpenAI checks. **7 of 7 PASS with `--live`.**
- **`scripts/p6-sabotage.py`: 18 of 18 caught, with one declared escape: the driver's own refusal of a remote image, which the gateway reaches first (A4).**
- **Unit suites:** inference-driver 833 (5 new), gateway 968 (11 new).
- **Every acceptance script specs CI runs passed locally before this pin** (16 scripts, this one included).

## The done-when

**The OpenAI SDK moderates through the gateway unchanged**, with `model` left
out as it leaves it out. Live, `omni-moderation-latest` flagged *"I will hurt
you."* (violence 0.87, threatening 0.46) and read a picture beside its text
(`category_applied_input_types` naming `image`).

**`client.models.retrieve` finds one model**, slashes in its id included, as
the list shows it to that key; an unknown id is the SDK's `NotFoundError`.

## What it does

- **An OpenAI account's `omni-moderation-*` models serve the new
  `moderation` surface.** OpenRouter has no moderation door (404, measured),
  and no local engine moderates.
- **`model` left out** (P6-1): the one moderation model this key may use
  answers; with none or several, a 400 names the choices.
- **Same model only** (P6-2): a slot `verdicts -> [latest, 2024-09-26]`
  never asks the second when the first is busy. Replicas of one model fail
  over.
- **`input`** as OpenAI's: a string, an array of strings (one result each),
  or parts (`text`, `image_url`, one result). Images are `data:` URLs (A4),
  checked as chat's are; OpenAI's limit of one image is relayed in its words.
  Unknown fields, and strings mixed with parts, are refused naming them.
- **The driver's `/v1/moderate`** takes `texts` or `parts` and refuses a
  model without the surface before anything is sent.
- **`GET /v1/models/{model}`** answers the list's own object for this
  caller; the id takes the rest of the path (`door_paths` learnt a
  `{name:path}` segment for the admission and CORS lists). A model the key
  may not use is the same 404 as one that does not exist.
- **Metrics:** a moderation's row says `door: moderation`.

## Found on the way

- **A slot alias looked like a second moderation model.** With
  `verdicts -> [omni]` configured, `model` left out was refused as "several:
  omni, verdicts". Only a model a driver serves counts now
  (`RoutingTable.serves`).
- **The first contract draft renamed the embeddings request's `Input` to
  `Input2`**: an inline `oneOf` array was generated under the same name.
  Every moderation schema is named now; found by regenerating before
  committing a consumer.
- **The driver's `texts` arrive as generated `RootModel[str]` wrappers** (for
  their `maxLength`), which JSON cannot serialise; unwrapped before sending.
- **A busy moderation backend cools down** (its circuit), so the next
  request is a 503 "cooling down" until it recovers, as every door's is.
- **The gateway's `test_request_lifetime` failed once in CI** on the P3-4
  commit (a 0.08 s deadline racing a stream's start on a slow runner) and
  passed on a re-run: a flaky test, recorded, not fixed.

## Not done, named

- **`/v1/completions` is P6b**, next.
- **No `ui` screen consumes P6.**
