# R3.4 — three contract sentences made true, one left standing

**2026-09-19.** Roadmap §4 item 4, review §6.2 #22. Contracts `031d90a`;
`gateway` `bb67692`, `inference-driver` `499836c`; **both installers re-pinned**.
`ui` regenerated, **deliberately not re-pinned** — see §4.

No acceptance script. Every claim here is a shaping decision with exactly one
right answer per input, which a fixture states exactly and a live run would only
restate more slowly; there is no race, no timing and no second process involved.
The gate is `scripts/r34-sabotage.py`: **24 sabotages, 24 caught**, across two
repos, after two escapes covered in §3.

---

## 1. What was wrong

Four sentences in `gateway.yaml` described behaviour the code did not have. All
four are silent — nothing errors, nothing is logged, and every response looks
exactly like a correct one.

| # | The contract said | The code did |
|---|---|---|
| 1 | `top_p` and `seed` are passed through to backends that support them, and dropped with a warning where they do not | Accepted both, range-validated both, put neither on `GenerateRequest` — which had no field for either — and logged nothing |
| 2 | `temperature` is resolved from *the model's settings profile* | Took it from gateway-wide `defaultTemperature`. The word "profile" occurs in gateway source only inside docstrings regenerated from that sentence |
| 3 | (implicitly) a finish reason is the backend's | `content_filter` → the driver's `error` → the gateway's `stop`, so a filtered answer arrived as a natural end |
| 4 | a driver 4xx is the caller's bad request | True of every driver 4xx except the two that are about **our** credential |

Three are fixed. **The second is left standing as an unmet promise**, by Troy's
call on 2026-09-19, and §5 says why that is not the same as leaving it alone.

---

## 2. What was built

### `top_p` and `seed` (contract + both repos)

`GenerateRequest` gains `topP` and `seed`. The gateway fills them from the
caller's body with **no install default** — unlike `max_tokens` and
`temperature` above them, there is nothing sensible to invent, and inventing one
would change the answer to a request that never asked for it. The driver puts
them in `_payload_for`, shared by the batch and streaming paths, so the two
cannot drift.

Two guards are the substance rather than the detail:

* **`seed=0` is a real seed and is falsy.** The guard is `is not None`. A
  truthiness check would drop it and answer a request for a reproducible result
  with a different answer every time — which is exactly what the missing field
  was already doing, so the bug would have survived its own fix.
* **`top_p` is dropped by the same flag that drops `temperature`, and only that
  one.** OpenAI's reasoning models reject both, because the sampler is not the
  caller's to tune there; they accept a seed perfectly well. Widening the drop
  to every sampling parameter because two of them travel together is the
  over-correction, and both directions are sabotage-checked.

The agentic CLIs cannot carry either — the harness on the other side of the pipe
owns its own sampler — so `warn_dropped_sampling` in the driver's `base.py` says
which parameter was dropped, **once per field for the life of the engine**. Once,
because a line per generation is a warning an operator learns to filter out,
which costs it its only job. `maxTokens` and `temperature` are deliberately not
in that helper: the contract has said since M0 that adapters without those knobs
ignore them *silently*, and changing it under cover of this fix would be a
behaviour change nobody asked for.

### `content_filter` (contract + both repos)

`FinishReason` gains `content_filter` on the driver. Two states with two
remedies — something broke and a retry may work, versus a classifier stopped the
answer and it will not — had one value between them, and folded together the
gateway could only ever render the pair as `stop`.

**Each door renders it in its own vendor's vocabulary**: `content_filter` on the
OpenAI door, which is OpenAI's own value, and `refusal` on the Anthropic one,
which is Anthropic's. Neither is invented. The rule is the one `tool_calls` →
`tool_use` was fixed under at step 6, applied to the next value along.

`error` still reports `stop` and `end_turn`. No vendor has a value for *the
backend broke*, the truncation is reported in the log and the metrics row, and
**the pair is what tells this fix from the over-correction** — a check set that
only ever moved a value could not fail a map that moved every value.

**Unverified, and named as such:** `refusal` was not put in front of a live
Anthropic SDK. It is Anthropic's documented value for a classifier intervention,
the contract says the claim is unverified, and R4's own measurement instrument
(`scripts/r4-capture.py`) is the thing that would settle it.

### A driver 401 is not the caller's fault (gateway)

`_driver_failure` splits 401 and 403 out of the 4xx branch. They mean the driver
refused the **gateway's** `service:gateway` token — a rotated signing key on one
node is the shape it takes, and clock skew produced exactly this on the live
install on 2026-09-15 — so the request was correct and the install is not.
Reported as `invalid_request_error` it sent a harness to re-read a prompt that
never had a problem, and gave the operator no hint a credential was involved.

502 with `error.type: upstream_auth_error`, naming the driver **and its URL**,
because the operator has to know which node's credential to re-mint.

**Not 401**, and the reason is measured rather than preferred: a 401 from this
door is about the caller's own bearer, and R4 measured what a 401 costs a real
Claude Code — an unbounded silent retry loop showing the user nothing. Reusing
the status for something the caller cannot act on either would be the worse of
two wrong answers.

**The cascade rule is untouched and that is asserted, not assumed.** A 4xx has
never cascaded here; changing what we *say* about a 401 must not change what we
*do* with it, and a sabotage that widens the cascade under cover of an
error-message fix is caught.

**On the Anthropic door both render as `api_error`.** `permission_error` would
read as the caller's credential being wrong when it is ours, and Anthropic's
error vocabulary has no member for *our upstream refused us*.

---

## 3. The sabotage pass — 24 of 24, after two escapes

`scripts/r34-sabotage.py`. Two repos, because the fix is two repos and a
cross-repo fix whose only evidence is an end-to-end run is one nobody can
maintain. Each sabotage is caught by its own repo's gate.

Every entry has a pair somewhere in the check set, because each of the three
fixes has an over-correction that looks identical from one side: drop `top_p`
for every model; map every finish reason onto its vendor's nearest value,
including the one no vendor has; move every driver 4xx out of the caller's
range. So the entries come in kinds — put the finding back, put the
over-correction in, take the discriminator apart.

### The two that escaped first

**One was a no-op sabotage rather than a defect, and it is R2.4's mistake
repeated.** *"The status goes back to 400 while the error type stays honest"*
inserted `upstream = 400` as the first statement **inside** the branch that had
already been taken and still returned 502 — dead code. A sabotage has to change
an answer, not a variable nobody reads again. Rewritten to change `code=502` in
that `_Failure`, it is caught.

**The other named a real hole, and the hole was in the assertion.** *"The refusal
stops naming the driver"* escaped, and the first diagnosis — that the test used
the one-character driver name `a` and asserted `"a" in message`, which is true of
almost any English sentence — was correct and **was not the whole reason**. With
a distinctive name it still escaped, because `_driver_failure` falls back to
`str(e)` when the driver sent no `problem+json` body, and `DriverError.__str__`
already contains the driver name and URL. So the belt-and-braces path was doing
the work and no assertion could tell.

The case where naming the driver is load-bearing is the one a real driver
produces: a `problem+json` body, after which `detail` is `problem.detail` and the
summary never appears. That is a test now
(`test_a_real_driver_problem_body_still_names_the_driver`), and it is the only
thing putting an operator in front of the right node.

---

## 4. Radius, measured

`gateway.yaml` and `inference-driver.yaml` changed. Those two documents are in
the codegen list of `gateway`, `inference-driver` and `ui`, and of nobody else —
`agent` and `control` codegen `agent.yaml`/`control.yaml`/`common.yaml`,
`library` codegens `library.yaml`. So three repos are in radius by construction
and three cannot see the change at all.

**`ui` was regenerated and deliberately NOT re-pinned.** Its diff is real rather
than JSDoc — three union widenings (`finish_reason` twice, `stop_reason` once,
`finishReason` on the driver) and two new request fields — but **nothing in
`src/` narrows on any of them**: `lib/completions.ts` declares its own
`finishReason: string | null`, and the playground offers `temperature` and
`max_tokens` and neither of the two new knobs. Typecheck and the full vitest
suite pass at the new pin with no source change. A pin here would force a `dist`
rebuild for a type nothing reads, and the working tree was reverted.

The playground *does* display `finishReason` verbatim in its Request report, so a
filtered answer will now read `content_filter` there — that change comes from the
gateway and reaches the UI with no re-pin, which is the point of typing the field
as a string.

---

## 5. What was deliberately not done

**The profile sentence.** `gateway.yaml` says `temperature` is resolved from the
model's settings profile and the gateway uses its own install-wide default.
The recommendation carried into this slice said the promise *could not* be met in
code because no per-model output store exists; **that premise was false** —
`ModelProfile` carries `temperature` and `topP`, and the library serves
`GET /v1/models/{id}/profiles`.

What it actually costs is a **gateway→library dependency edge that does not exist
today**, with a cache, a staleness policy and its own failure modes, inside what
was scoped as a correctness pass. Troy's call on 2026-09-19: **split it, keep the
target.** The sentence stands as an unmet promise and is scheduled as its own
slice before the release. Softening the contract to match the weaker mechanism
would move the gate instead of reaching it.

**`top_k` is still dropped**, by both internal contracts, and is now the only
sampling parameter with that gap. It is documented in both places rather than
fixed, because adding it is a third field on the same schema and no caller has
asked.

**Nothing was run against a live backend.** Every assertion here is a unit test
over a mocked wire: no real engine returned `content_filter`, no real driver
returned 401 to a running gateway, and no real Anthropic SDK saw `refusal`. The
shaping is deterministic and the fixtures state it exactly — but *a filtered
answer from a real model* and *a rotated token on a real second node* are both
reachable on the live install and neither was reached.
