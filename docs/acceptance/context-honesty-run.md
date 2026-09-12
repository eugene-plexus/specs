# Context-window honesty — acceptance run

**2026-09-12. 18 checks, zero failures, first attempt with the run
isolated.** `scripts/context-honesty-acceptance.sh`. Install-paths §9
step 7; design
[`agent-clients-and-tool-calling.md`](../design/agent-clients-and-tool-calling.md)
§6, open call #3.

Contracts `37a1d96`; inference-driver `70de63f`, gateway `eae5d70`.
`agent`, `control` and `library` are **not** re-pinned: `common.yaml`
was untouched and regenerating each produced byte-identical models, so
a bump there would be a commit whose only content is a version string.

The script has 19 `ok` call sites and the run printed 18 PASS lines —
check 13 has two mutually exclusive branches for where it finds the log.

## What the call was

Open call #3 was **refuse / truncate-and-report / configurable**. Troy
took it on the measurements below: **let the engine refuse.** No
tokenizer anywhere in the stack, no preflight, no size check. The
gateway advertises the window, passes the engine's own refusal through
untouched, and detects after the fact the one case where a backend
refuses nothing.

The reasoning that decided it, and it is about what is *available*
rather than what is preferable: an engine that counts tokens counts them
exactly, and a count of ours would be a second implementation of one
that is already right. `chars/4` was measured to underestimate a real
prompt by **19.4%** (16,568 against 20,560 actual) — the wrong
direction for a fit predictor, since it lets oversized prompts through
while still being able to refuse ones that would have fit.

## What ran

Five processes on this Windows box — agent on **8179**, its declared
control root, gateway and library, plus two inference-drivers — against
**two real engines that behave the two different ways the design
assumes**:

| Engine                 | Window | Over-long prompt                              |
| ---------------------- | ------ | --------------------------------------------- |
| `llama-server` b9846   | 512    | **HTTP 400**, `exceed_context_size_error`     |
| Ollama 0.34.0          | 2048   | **HTTP 200**, answers on what survived        |

Neither behaviour can be proved by a fixture. Both are properties of
somebody else's server, and the recurring failure here is a check that
asserts a property of its own test double — step 6's first run demanded
tool-call fragmentation that no local engine produces.

The Ollama window is pinned on a **derived model** (`ollama create` with
`PARAMETER num_ctx 2048`) rather than by restarting the operator's
Ollama, because on this machine that Ollama is the backend a live
install routes to. Ollama 0.34 otherwise auto-sizes to the model's full
trained context — 131072 for an 8B, about 22 GB of VRAM — with nothing
set, which is a good default and useless for provoking truncation. The
derived model is deleted on teardown.

## The two headlines

### 1. An engine that counts is no longer contradicted

```
HTTP 400
{"error":{"message":"The backend rejected the request: The backend refused
 this request with HTTP 400, so it was not retried against another backend
 -- the next one would refuse it too. ... openai_compat_http returned 400:
 {\"error\":{\"code\":400,\"message\":\"request (15010 tokens) exceeds the
 available context size (512 tokens), try increasing it\",
 \"type\":\"exceed_context_size_error\",\"n_prompt_tokens\":15010,
 \"n_ctx\":512}}"}}
```

Both of the backend's numbers survive the whole trip, and the status is
a **400**, not the 502 it used to be.

**The 400 is itself the proof it did not cascade**, because the gateway
returns 400 only on the hard-fail path and a cascade that exhausted
every tier returns 502. The slot was configured with a second tier
pointing at the Ollama — which would have *truncated and answered 200*.
So a 200 there would not have been a near-miss; it would have been a
wrong answer substituted for a right error. Check 6 asserts the
refusal stands.

### 2. An engine that counts nothing is now caught

```
sent 68,597 chars across 6 messages -> backend reported prompt_tokens=77
HTTP 200
x_eugene_plexus.prompt_truncated = true
x_eugene_plexus.context_length   = 2048
gateway log: reported consuming only 77 prompt tokens for 68597 characters
```

One token per 891 characters. Nothing in the response said so before
this: 200 OK, a fluent answer, and a harness cannot distinguish it from
the model simply being wrong about code it was never shown.

And the half that makes it mean anything — **check 11, an intact prompt
through the same path**: `prompt_tokens=551`, `prompt_truncated=false`.
A detector that fires on everything proves nothing.

## The advertising half

`capabilities.maxContextTokens` was contracted at M0 and populated by
nothing, which is `capabilities.streaming`'s M10 story one field over.
Both drivers report a real number now, from two different places:

- llama.cpp — `GET /props` → `default_generation_settings.n_ctx` = 512
- Ollama — `GET /api/ps` → `context_length` = 2048

**The Ollama source is the find.** Its OpenAI-compatible surface carries
no window at all, and `/api/show` carries only the trained maximum,
which would *overstate* whenever the server picked something smaller —
the one direction that hurts, since a harness filling a window it does
not have is the silent truncation this exists to expose. `/api/ps` is
the only place the number it actually chose appears, and it is empty
until something loads the model, so a miss is cached briefly and never
overwrites an earlier hit.

`GET /v1/models` now publishes a `context_length` for both, where before
it published `null` for the most ordinary local setup there is.

## THE FINDING WITH THE LONGEST REACH, and it is not about contexts

**The first run of this script repointed the live install at a dead
port, and nothing in either process said so.**

`tool-calling-acceptance.sh` documents itself as safe beside a live
install: it binds 8179 instead of 8079 and tears down by port. Both
true, and both about *ports*. It does not isolate **state**.

`install.ps1` sets `EUGENE_PLEXUS_AGENT_CONFIG_FILE` in the **USER**
environment, deliberately — a scheduled task inherits the user
environment, and that is how the installed agent finds its install. Its
own comment says so. The consequence is that every shell on that account
inherits it too. So the throwaway agent this script started:

- loaded the operator's `agent.yaml` **and `node.yaml`**
- came up **enrolled as `Amish_Station` at epoch 1**, holding the
  install's signing key
- tried to spawn the operator's declared components on their real ports
  (it failed on 8081, correctly, and said so)
- and — since M9's announce-on-start — **told the real control root
  that `Amish_Station` is now at `http://192.168.16.75:8179`**

which is a port that died when the script exited. The control root
accepted it: the announcement is signed by the node, and the node
really did sign it. Every surface stayed green. Recovered by restarting
the real agent, which re-announced 8079.

Both halves are individually correct. The installer needs that variable
in the user environment or a logon task cannot find its config; the
script needs a clean environment or it is not a throwaway. Together they
made a documented safety claim false.

Fixed in both scripts by **dropping every ambient `EUGENE_PLEXUS_*`
variable and setting only what the run needs** — a loop rather than a
list, because naming the two known variables goes stale the first time a
third appears. This script makes it **check 0** and fails the run if
anything leaks; `tool-calling-acceptance.sh` gets the same guard,
printed but not counted as a check so its record's "16 checks" stays
true.

The shape is this project's most familiar one: a claim that was verified
in the dimension somebody thought of.

## Also found, not diagnosed

**The clocks on this box and the UnRAID container disagree.** Minting an
operator token here and presenting it to the control root returns
`401 ... The token is not yet valid (iat)`; backdating `iat` by 300
seconds works. CLAUDE.md lists clock skew as an M5 scenario this
hardware cannot produce — it turns out the two-machine install produces
it already, and the symptom is an authentication failure that names the
clock only if you read the `detail`. Not investigated here.

## What this run does not cover

- **vLLM.** Its window source (`max_model_len` on the `/v1/models` card)
  is unit-tested against the documented shape and **has not been read
  off a live vLLM**. Same status the accumulation path for fragmented
  tool calls has from step 6.
- **A backend that truncates *and* reports no usage.** It would be
  invisible to the detector, correctly — `null` is "we could not check",
  not "it was fine" — but nothing was pointed at one.
- **A cloud provider's 429 falling through to a local engine.** The
  carve-out that keeps `408`/`409`/`425`/`429` on a cascading 502 is
  unit-tested and parameterised; no live rate limit was provoked.
