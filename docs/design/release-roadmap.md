# Release roadmap (design)

**Status: written 2026-09-17, and it is the order of work from here.** It comes
out of the pre-release adversarial review — three code passes over the six live
repos plus a re-verified field read — whose record is
`docs/private/adversarial-review-2026-09-17.md` (**gitignored**; `docs/private/`
is not in the repo). The review's §7 is a verdict and a ranked fix list; this
document is that turned into slices with acceptance checks, an order, and the
decisions it leaves to Troy.

**It supersedes two lists that are quoted all over this repo.**
[`install-paths-and-distribution.md`](install-paths-and-distribution.md) §9 —
steps 1-8 are built and its step 9, *the release*, is no longer the next thing —
and the hobbyist plan's S0-S10, where S8 is part-built, S9 is not started and
S10 is green on both targets with two items of its own *Done when* outstanding.
Both documents keep their reasoning; neither is the order any more.

**Every finding in it was re-verified against the working trees on 2026-09-17,
after the review was written and after that day's commits landed.** All are
still present. Nothing was already fixed; nothing was misdiagnosed.

**▶ AND THAT VERIFICATION IS DONE. DO NOT DO IT AGAIN. (Troy, 2026-09-18.)**
Every finding below was checked against the live clones by the session that
wrote this document, hours after the last commit it describes. **A future
session opening this roadmap executes it; it does not re-audit it.** Do not
re-read the review to confirm a finding is real, do not re-grep the repos to
confirm a line number still says what the appendix says it says, and do not
open a slice by re-establishing that its defect exists. This is a solo project
with one developer: a second opinion costs a day and buys a sentence that is
already written here. **If a coordinate has drifted, the fix's own failing
check is what tells you, at the moment you need to know** — and that costs
minutes, not a pass.

**The one thing this does NOT license you to skip.** Every slice still ships
with a check that reproduces its finding **before** the fix and fails without
it (§1). That is not re-verification; it is the fix's first half, and eleven of
these findings were found by reading with a green test sitting beside them.
Writing that check is the work. Re-confirming that the work is worth doing is
not.

**Three things are marked *unverified* rather than *verified*, and those are
first verifications, not repeats** — they were never established, so a session
that skips them is guessing rather than saving time: R4's `x-api-key` premise
(upstream Claude Code behaviour, reasoned about and never captured), R2.3's
`win-sycl-x64` variant (nothing in-tree supports it), and #36's parallel-slot
contradiction, whose resolution depends on an upstream premise this project has
not measured. Each says so where it lives.

**The count, stated once because it reached five documents wrong.** §6 of the
review enumerates **38 numbered findings** (§6.1 #1-11, §6.2 #12-30, §6.3
#31-38, no gaps) **plus the unnumbered architectural note §6.4** — 39 items,
**11 rated High**. The review's own §0 says "41" and nothing in it enumerates
41; treat 38+1 as the number, and the appendix below as the list. The appendix
carries one extra row, `§5 #1`, which is the **market threat** (no Anthropic
`/v1/messages`) rather than a defect, and is labelled as such.

**Several of the review's sub-claims were corrected by the verification, and
the correction is written into the slice that carries the finding rather than
listed here** — there are at least eight, and each changes what the work is:
#25's fix is per-site rather than blanket (§2.1), #35's stated mechanism was
wrong and patching the file list would have changed nothing (§2.5), #24 and #31
are each worse than recorded (§3.2), `win-sycl-x64` is unsupported by anything
in-tree (§3.3), #12's fix is larger than "reuse the existing dependency"
(§3.4), #13's timeouts are config fields and the defect is their order and
anonymity (§3.5), and the review's citation for where a Rosetta terminal gets
an x86_64 interpreter is wrong (§4, item 7).

---

## Decisions needed

Each has a recommendation and the counter-argument that would overturn it.
**This block is the decision log** — answers are recorded here as they are made.

| #     | The call                                                                                 | §    | Recommendation                                                                                                   | Status   |
| ----- | ---------------------------------------------------------------------------------------- | ---- | ---------------------------------------------------------------------------------------------------------------- | -------- |
| **1** | Does Anthropic `/v1/messages` go in front of the release, or after it?                    | §5   | **In front, as R4, after R1 and alongside R2.** It is the one matrix row that decides the first review            | **TAKEN 2026-09-18 (Troy): IN FRONT.** R4 is scheduled, not optional. Its first step is capturing a real Claude Code request, because the `x-api-key` half is upstream behaviour this review did not verify |
| **2** | Adopt the review's §4.3 re-ordering and re-wording of the seven callings?                 | §6   | **Adopt the wording everywhere; keep the numbers attached to the old ideas** — a dozen documents cite `#N`        | **TAKEN 2026-09-18 (Troy): ADOPT.** Applied as recommended — seven lines said in §4.3's order, eight numbered ideas, nothing renumbered. #4 keeps its number as a *mechanism*; the new *one endpoint for every tool you use* is **#8** and is the one line that is not true until R4 |
| **3** | Are the eight pre-link fixes a new numbered step in install-paths §9, or a gate inside step 9? | §9   | **A gate inside step 9 (9a/9b)**, because "step 9 is the release" is cited in CLAUDE.md, the memory files and §12. **Written that way provisionally on 2026-09-17** — the call is whether to keep it or promote it to a numbered step | **OPEN (provisionally taken in the doc)** |
| **4** | Windows autostart: fix the copy, or change the mechanism?                                 | §3.2 | **Fix the copy now (R2.2); treat a boot-time task or the service as its own slice** — S4U costs the mapped drive  | **OPEN** |
| **5** | The shared HS256 key (review §6.4): split it, withhold it from drivers, or accept it?     | §8   | **Withhold it from processes that unseal nothing, and constrain `binary`/`extraArgs`; do not split the key yet**  | **OPEN** |
| **6** | A benchmark button on a profile — "measure, don't predict" (review §1.9/§5 #4)?           | §8   | **Yes, but after the release gate**, and not under the name "Measure it" (that is hobbyist S10)                   | **OPEN** |
| **7** | Release timing, against a clock that is now visible on both sides of the thesis           | §9   | **Keep decision #14 as taken** ("2-3 friends for sure", no hurry) and let R1-R2 be the reason, not the delay      | **OPEN** |

---

## 0. What the review found, in one page

**Eleven High findings, each reachable by a hobbyist on day one or by a
reviewer in an hour, and none needing a design.** Four are worth stating on
their own, and the first is a single root cause whose radius crosses five
repos:

1. **Every `httpx.AsyncClient()` in this project is built per call**, and
   constructing one parses certifi's PEM bundle — **104-106 ms of synchronous
   CPU on the event loop**, measured in four of the repos' own virtualenvs. It
   *is* the ~116 ms this project has carried as unexplained since M8. It also
   burns **~0.21 s per ready runtime per poll — ~0.84 s of every 2 s with four
   resident** (two clients each, `/health` then `/props`, on the loop that
   serves the browser) and ~0.6 s per gateway routing refresh. §2.1.
2. **The 43× KV fix landed on one of two fit paths, and the golden path uses
   the other.** Home says a starter model fits at 16,384; one click later the
   `default` profile is written with a context computed by the scalar reader
   the fix replaced. Measured on this box: `fits`/262,144 from one path and
   `no`/15,872 from the other, for the same file, both reporting
   `basis: metadata`. §2.3.
3. **A closed tab mid-stream leaks the in-flight counters forever** —
   `CancelledError` is a `BaseException`, so neither the `except Exception` nor
   the `else` arm runs — after which that runtime never idle-unloads and can
   never be evicted for a wake until the gateway restarts. §2.4.
4. **The login rate limiter can be driven from a header the caller supplies**,
   because the browser reaches login through our own proxy and the proxy
   forwards the forwarding headers. The same path forges the Reach card's only
   *proof* that another device reached this machine. §2.2.

**What the review cleared, because silence should be informative:** JWT
verification and the whole audience model; route auth coverage; argv assembly
(no `shell=True` anywhere); enrollment, rotation, epoch fencing and signed
announcements; download integrity end to end; engine acquisition against live
upstream b11026; GGUF and safetensors bounds; stream termination and tool-delta
accumulation; the cascade taxonomy; wake de-duplication; metrics off the
request path; and most of both installers. §6.5 of the review lists it in full.

**And the market half:** the operations layer is no longer unclaimed —
`llamactl` has shipped this thesis in Go since 2025-09 and released v0.21.2 the
day the review was written, `llama-server`'s router mode took the single-host
half of callings #1 and #7 *inside the engine*, and Unsloth Desktop is the
beginner default on the strength of *automatic* hardware-aware settings. Three
matrix rows are still ours alone: replica balancing with tiered failover,
cloud and subscription CLIs as peer backends, and multi-host as enrolled signed
agents. Two rows decide the first review: Anthropic `/v1/messages`, which we do
not serve, and *shipped a release*, which we have not.

---

## 1. How a slice in this roadmap is shaped

Three rules, each earned by something in this project's own record — and a
zeroth one, which is **you do not re-verify the finding before you start it**
(see the top of this document, Troy 2026-09-18). Open the slice by writing the
check that reproduces it.

**Every fix ships with a check that reproduces the finding before the fix and
fails without it.** All eleven Highs were found by reading, not by a red test —
and in six cases a test exists that *should* have caught the defect and asserts
the wrong subject instead (a pure helper rather than its caller; a fixture the
detector cannot produce; a 401 asserted as the caller's fault). A check written
after the fix tends to assert the fixture. So: write the reproduction first,
watch it fail, then fix.

**A sabotage pass per slice, restoring from a copy.** Never `git checkout --` —
that reverts uncommitted work and deletes the change under test, and every
result after the first then reads *caught* for the wrong reason. Open the pass
with a baseline assertion that the gate passes unsabotaged.

**An acceptance script per slice, safe beside the live install.** Clear every
ambient `EUGENE_PLEXUS_*` variable (or a throwaway agent adopts the live
worker's identity and re-announces its address to the real control root), bind
+100, tear down by pid. And **rebuild `ui`'s `dist` branch and re-pin both
installers whenever the UI changes**, or the fix ships to nobody — which has
already happened once, to the one fix that would have prevented the 16 GB
download the acceptance run then clicked.

---

## 2. R1 — before any public link

The review's eight, regrouped into **six slices** by what they touch rather
than by severity, so each slice is one pass over one seam — **plus seven items
pulled forward because they sit on the same seam as one of the eight, which is
stated here so nobody sizes R1 at eight findings.** Pulled forward from the
review's later batches: **#14** (the download `filename`, which the review
placed after the hostile-review five — promoted because it is S-sized, needs no
signing key, and breaks the non-negotiable calling #3) and **#23**
(`perf_counter`, promoted because the 116 ms cannot be re-measured through the
instrument that hid it). Pulled forward from unscheduled: **#25, #32, #35, #36,
#38**. Nothing was demoted out of the eight. **Order within R1 matters in two
places only:** R1.1 must land before anything re-measures the hop, and R1.4
makes R2.1's race reachable rather than masked.

### 2.1 R1.1 — One client, one context, one clock

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/one-client-acceptance.sh`,
**21 PASS, zero failures, third execution**; record
[`../acceptance/one-client-run.md`](../acceptance/one-client-run.md). Findings
§6.1 #2, §6.2 #23 and §6.2 #25 are closed. **The ~116 ms is gone: control-plane
overhead per request is 3.2 ms** against a 5 ms stub, the driver hop went from
110.3 ms to 2.0 ms, and client construction from 104-136 ms to 0.03 ms. 43 unit
checks across five repos, 12 scripted sabotages all caught
([`../../scripts/one-client-sabotage.py`](../../scripts/one-client-sabotage.py)),
plus a live one that reproduces #25's silent install verbatim.

**Three things the build found that the plan did not have.** (a) The fix
introduced a **cold-start deadlock** — a non-reentrant lock held across a call
that takes the same lock — which every suite hid because some earlier test
always built the context first; it is an `RLock`, and the check that catches it
runs a fresh interpreter. (b) The review's `trust_env=False` had to become
per-URL rather than per-call-site, because **one engine class fronts both
`127.0.0.1:8081` and `api.openai.com`**. (c) The acceptance run's first
execution measured a **negative** overhead, because the backend floor was
measured without connection pooling and the control plane with it — two spans,
two instruments, which is the mistake that produced the original unexplained
116 ms; the check now fails on a negative result rather than passing it.

**Not done here and still owed:** the five component repos are uncommitted and
nothing is re-pinned, so this has not reached an install yet; and
`engines/acquisition.py`'s synchronous `urlopen` is still on the loop — that is
§6.1 #5, scheduled in R1.5, and a shared SSL context does not help it.

*Findings: §6.1 #2, §6.2 #23, §6.2 #25. Size: S for the minimal fix, M for the
full one. Touches: `inference-driver`, `agent`, `gateway`, `control`,
`specs/scripts`. The plan as written, kept because the corrections above are
only legible against it:*

**Take the minimal fix first and measure it.** One module-level
`httpx.create_ssl_context()` per package, passed as `verify=` at every
construction site, measured **106.3 ms → 0.0 ms**, changes no client lifetimes
and disturbs none of the three test harnesses that monkeypatch
`AsyncClient.__init__`. Then the per-instance client refactor for pooling and
keep-alive, which is where the care is needed.

**The verification produced the complete inventory: 28 construction sites
across five repos** (`ui` has no Python client), **of which 20 are built
per-call and 14 sit on repeating paths.** Those 14 are the ones that matter:
the driver's five, the agent's two engine adapters × two probes, its three
admission clients, the gateway's one JSON client, and the driver's synchronous
`runtime_lookup`. In order:

1. `agent/engines/llama_cpp.py:376` and `:404`, `vllm.py:305` and `:350` — the
   2 s readiness loop builds **two clients per ready runtime per poll**, on the
   loop that serves the UI and the browser proxy.
2. `inference-driver/engines/openai_compat_http.py:421` / `:549` / `:669` — one
   per completion, on the request path. This is the user-visible 105 ms.
3. `gateway/routing.py:475` — 5-7 per refresh, and again inside a request via
   `refresh_if_stale`, so it lands on the request path too.
4. `agent/admission.py:158,176,198` — three per admission, and the UI's
   new-profile form calls admission when it opens.
5. `agent/engines/acquisition.py:236` — not httpx but strictly worse: a
   synchronous `urlopen` with a 60 s timeout on the loop. That is §6.1 #5, in
   R1.5.

**Two sites the review did not name, found by the verification:**
`openai_compat_http.py:797` and `:905`, and **`inference-driver/runtime_lookup.py:69`,
a synchronous `httpx.Client` called from the async lifespan and from
`POST /v1/config`** — which blocks the loop for the whole request, not merely
for the construction.

**Who owns the client, per repo:** the driver's `OpenAICompatHttpEngine`
(lazily, because `routes/config.py:70` builds a throwaway engine to validate a
PATCH and eager construction would leak one per PATCH); the agent's
`LlamaCppAdapter`/`VllmAdapter` module-level singletons, each with a client
built **without** `base_url` since they pass absolute URLs, plus an app-level
client that `LibraryFitClient` takes as an argument; the gateway's
`RoutingTable`, closed in the `aclose()` it already has. `control` and `library`
are already correct.

**What breaks, and it is why this is not a blind sed:** four different timeout
budgets would end up on one client, so they must move to per-request
`timeout=` — `control/nodes_client.py:75-93` already documents that pattern and
its reason. And three test harnesses depend on construction happening inside
the call under test; they convert to constructor injection, the shape
`library/hub.py` already uses.

**`trust_env=False` is per site, not blanket** — the review's phrasing would
have broken the two clients that must honour a proxy: `library/hub.py:339` (the
hub, the only egress this product has) and the agent's GitHub fetch. Everything
dialling loopback or another node of this install opts out, plus `--noproxy '*'`
on the installer's health-wait `curl`. **And the Windows symptom is not
"components flap":** the health poller restarts nothing, it gates the
`starting → running` promotion, so the whole install sits at *starting* while
actually serving — a silent state no screen explains.

**`perf_counter` lands in this slice, not after it.** On the Python both
installers provision (3.12) `time.monotonic()` on Windows is `GetTickCount64`:
**20 distinct values in 300 ms**, a 15.6 ms grid, under every gateway `*_ms`.
CPython fixed it in 3.13 and the agent's local venv is 3.14 — so this is
invisible on the developer's box and present on every shipped install, the
`ci-hygiene-and-devenv-mismatch` pattern again. The 116 ms was obtained by
subtracting two spans measured by different instruments on that grid; without
`perf_counter` first, a re-measurement cannot tell a partial fix from a
complete one.

**Done when:** the driver's non-streaming `latencyMs` brackets the same span as
the streaming one; a test counts constructions across N calls; `elapsed_ms -
backend_ms` for one attempt is single-digit milliseconds against a stub; and a
test asserts no loopback client picks up an ambient `HTTP_PROXY`.

### 2.2 R1.2 — Two rules the product states and does not enforce

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r12-acceptance.sh`, **21
PASS, zero failures, third execution**; record
[`../acceptance/two-rules-run.md`](../acceptance/two-rules-run.md). Findings
§6.1 #1, §6.2 #14 and §6.3 #32 are closed. 35 unit checks across five repos,
**20 scripted sabotages, 20 caught**
([`../../scripts/r12-sabotage.py`](../../scripts/r12-sabotage.py)). No contract
change and no UI change, so `dist` is untouched and neither installer is
re-pinned — the six pins stay as R1.1 left them, to be bumped once at the end of
R1.

**The shape it came out as.** `peer.py` in `agent` and `control` (a copy, like
`security.py`'s five): the proxy strips every forwarding header *and* a
caller's copy of `PEER_HEADER`, sets `PEER_HEADER` from the peer it saw, all
five entrypoints pass `forwarded_allow_ips=[]`, and both login routes plus the
off-host witness read the header **only when the TCP peer is loopback** — the
one case where the peer is our own proxy and says nothing. `resolve_file` in
`library/downloads.py` bounds-checks the destination of *every* file (not just a
renamed one) and refuses with `PathTraversal`. `FRAME_HEADERS` in
`ui_assets.py`, on the static mount and on the degraded page.

**Three things the build found that the plan did not have.** (a) **The strip and
the overwrite are not redundant, and the sabotage pass is what proved it**:
removing `PEER_HEADER` from the stripped set escaped every check, because the
proxy overwrites it a line later — except when `scope["client"]` is `None`,
which ASGI permits and where the strip is the only guard. The guard was untested
rather than unnecessary; that case is a check now. (b) **The live instrument had
to bind its own source address** (`127.0.0.2` vs `127.0.0.3`): two loopback
peers is exactly the arrangement the finding is about, and `curl` cannot do it,
so the run carries a raw client. (c) **A check was green for the wrong reason**
— with the catalogue off, the library refuses a download before the resolver
runs, so "an ordinary rename is not refused as a traversal" would have passed
against a guard that refused everything; the hub is a dead port now, so an
accepted name must reach it.

**The original scope follows.**

*Findings: §6.1 #1, §6.2 #14, §6.3 #32. Size: M + S + S. Touches: `agent`,
`control`, `library`, and all five uvicorn entrypoints.*

**The forwarded-header trust chain (§6.1 #1).** The browser always reaches
login through our own proxy, so the inner peer is permanently `127.0.0.1` and
`request.client.host` can never be the limiter's key. Four parts: strip the
forwarding headers in the proxy's `_request_headers`; have the proxy set a
header **we** own carrying the outer peer — the `install_proxy.HOP_HEADER`
precedent, which is trustworthy precisely because it is in the stripped set;
pass `forwarded_allow_ips=[]` in all five entrypoints (five repos, five
commits, possibly five pins); and have both `login` routes and
`off_host._is_off_host` prefer our header when the peer is loopback. Two
distinct defects share the cause, and **the second needs no attacker at all**:
with no header every proxied login shares one bucket, so five mistyped
passphrases lock every UI login for a minute.

**A download destination that can leave every Library folder (§6.2 #14).** A
single-file download spec's `filename` is joined without the `is_within` check
its sibling field `subdirectory` already gets (`library/downloads.py`,
`resolve_destination`); the line-level reproduction stays in `docs/private/`.
**Operator-gated**, so it is post-authentication rather than network-reachable
— which is why it is in R1 for the invariant it breaks and not for an exposure. Refuse rather than sanitise —
a silently renamed file is worse than a 400 — with the `PathTraversal` code
`resolve_destination` already uses. **This is calling #3, the non-negotiable
one, and a rule the product does not enforce is a slogan.** The test for the
adjacent field sits two functions away, which is what makes the gap sharp.

**`X-Frame-Options` / `frame-ancestors` on the agent-served UI (§6.3 #32).**
Defence in depth, one header dict and one assertion, the cheapest item on the
list; it belongs in this slice because it is the same file family.

**Done when:** five wrong passphrases with five distinct forwarded headers still
429 the sixth; a proxied login's failures do not lock a direct one; a traversing
and an absolute `filename` both come back `PathTraversal`; `GET /` carries the
frame headers.

### 2.3 R1.3 — One fit path

*Findings: §6.1 #4, §6.3 #36. Size: S + S. Touches: `library`, `agent`
(copy only), `ui` (copy only).*

**There are four call paths that produce a fit verdict and only one is wrong —
and it is the one the golden path uses.** Catalogue search and detail
(`basis: estimate`, fixed 2026-09-17 by library `0252b38`), preflight
(per-layer, correct — this is where the 43× fix lives), starter (per-layer,
correct), and **`GET /v1/models/{id}/fit` → `routes/guidance.py::_shape_for`,
whose `by_suffix` accepts only `int` and never sets `layers`.** That route has
exactly one commit in its history, from M3.

**The fix is small because the material already exists:** rebuild a
`GgufMetadata` from the stored `kv` dict and delegate to
`preflight.shape_from_gguf`, which already calls `per_layer_kv` and
`attention_layers`; override `parameters`; keep the safetensors early return.

**Measured, in the library's own venv, for the 14B-class starter at the 16,384
Home advertises:** the starter path says `fits`, 8.20 GiB, max context 262,144;
the on-disk route says `no`, 31.63 GiB, max context **4,864 on a 16 GB card and
15,872 on this box's 5090** — both claiming `basis: metadata`. So the
divergence is visible on the project's own hardware, and the Library detail
panel renders the wrong verdict as *"Too large for this node"* about a 7 GB
model on a 32 GB card. **Two of the four shipped starter classes carry
`layerRuns`, so half the starter set is affected.**

**Two consumers, not one.** The review named the golden path through admission;
the verification found the Library model detail card reading the same broken
route, and `StarterSetPanel` and the Library page printing a `maxContextLength`
for the same file from two different shape builders — 262,144 and 4,864 side by
side on one install, with nothing telling a user which is the lie.

**Also here, because it lands on the same screens:** `_shape_for` handles only
the `full_attention_interval` hybrid form and not `attention.layer_indices`;
`_INLINE_ARRAY_LIMIT = 64` silently drops a longer per-layer array to the
scalar path **while still claiming `basis: metadata`** (confirmed latent, with a
margin of one — the shipped block counts are 32, 42, 48 and 65).

**And §6.3 #36 is a contradiction inside the repo, whose resolution depends on
a premise nobody has re-verified.** The two `ConfigField` descriptions the
profile form renders verbatim say `-c` is per-slot and that memory multiplies
with slots; `fit.py` and `admission.py` compute the opposite, and the `/props`
readback prefers the per-slot field. One of the two is wrong regardless — but
**which one depends on current `llama-server` semantics, which the review marked
Plausible and explicitly did not re-verify** (`--kv-unified` changes them). **So
step one of this item is a live check against the pinned build** (launch with
`contextSize: 32768, parallelSlots: 4` and read
`Runtime.capabilities.contextLength`), and only then correct the copy and carry
a per-request window into the admission reason and the launch preview.
Rewriting the copy off the unverified premise risks being wrong in the other
direction.

**Done when:** one route call over a written GGUF whose `head_count_kv` is a
list and whose `sliding_window_pattern` is a bool array asserts
`kvCacheBytes < 1 GiB` at 16k; the starter panel and the Library detail print
the same number for the same file; and the `contextSize`/`parallelSlots`
descriptions agree with the arithmetic.

### 2.4 R1.4 — A stream that ends leaves nothing behind

*Findings: §6.1 #3, §6.3 #38. Size: S, one commit, ~45 lines, one test module.
Touches: `gateway`.*

They are the same defect in the same two branches: the `except`/`else` pair is
asked to classify an outcome it cannot see — once for cancellation, where
neither arm runs, and once for a clean-but-incomplete stream, where the wrong
arm runs. One `saw_done` local and one `finally` arm close both. Fix `generate`
and `embed` in the same edit; they have the identical shape and no live
cancellation path today.

**The mechanism is confirmed all the way down, not inferred from the class
hierarchy:** starlette 1.6.0 takes its **disconnect-listening task group** for
any ASGI spec version **below (2, 4)**, and uvicorn 0.52.4 advertises **2.3** —
so the task group is taken and the response generator is cancelled on
`http.disconnect`. Triggered by the playground's own Stop button.

**The verification found a second, independent leak of the same counter, and it
is why R2.1 belongs right behind this one.** `on_attempt_start` resolves the
runtime name by scanning the live snapshot, and `on_attempt_end` scans it
*again* against whatever snapshot has since been installed. A refresh landing
mid-request on a node whose read failed makes the second lookup return `None`,
so the counter is incremented and never decremented — and the mirror case is
worse: a request that starts while facts are missing and ends after they return
decrements a counter it never incremented, `max(0, …)` absorbs it, and a live
in-flight request reads as zero in flight, after which the idle pass unloads a
runtime **mid-answer**. Capture the name at start and pass it through, or key
the counter on an attempt identity.

**Done when:** a test drives `TieredClient.stream`, consumes one event, closes
the generator, and asserts `runtime_inflight(name) == 0`; a stream that returns
without a `done` event is recorded `served=False` and the client gets a
terminal frame with a `finish_reason` before `[DONE]`.

### 2.5 R1.5 — The first hour survives a hostile box

*Findings: §6.1 #5, §6.1 #6, §6.1 #7, §6.3 #35. Size: S + M + L + S. Touches:
`agent`, `ui`.*

**`GET /v1/engines` blocks the agent's event loop (§6.1 #5).** Three uncached
`detect_host()` calls per request — up to six `nvidia-smi` subprocesses at a 5 s
cap — then a synchronous `urlopen` to `api.github.com` with a **60 s** timeout
and no failure stamp, on a route Home polls every 15 s and `useIssues` polls
every 30 s per node. `to_thread` (the codebase already does this at five
comparable sites), resolve the host once per request, and stamp failed release
fetches with a back-off. The docstring asserting the opposite is the strongest
evidence this was an oversight rather than a choice.

**`agent.yaml` is rewritten in place and loaded unguarded (§6.1 #6).** Two
independent halves and only the pair is a fix: temp + `fsync` + `os.replace`
for the write, and the `degraded-mode-required` treatment for the load that
`library/app.py:62-75` already has — with the partial-but-parsing case (an
`auth` block gone where a `masterSalt` was present) refusing to run the wizard
rather than inviting it. **The write frequency is higher than it looks:** every
config PATCH and every companion declaration rewrites the file, and M6 declares
one companion per runtime. This file has recorded the unguarded load since
2026-09-10 and never the non-atomic write that makes it reachable.

**A taken port (§6.1 #7).** 8083: screen 1's Continue has already set the agent
passphrase, then the trust root fails five times and a first-time user is told
to remove the auth block from `agent.yaml` by hand. **8080 — the commonest
occupied port on any dev box:** the wizard completes, the gateway never comes
up, Home shows nothing routable, Try it never appears, and the Needs-attention
card is **empty**, because `IssueKind` has no member for a supervised component
that is down or crash-looping. Three pieces: probe before seeding (the pattern
half-exists in the wizard's driver-port walk, keyed on declared URLs rather
than on sockets); a `component-down` issue fed from `Component.lastError`,
which no golden-path screen renders today; and the 409 copy replaced with the
real remedy. **Drive the page, not the issue function** — S7 produced the
"a component test is not a wiring test" lesson twice in one slice.

**The wizard's banned vocabulary (§6.3 #35), because it is the same eight
lines.** The review's mechanism was wrong in one respect and the verification
proved it by running the extractor: `start.ts` **is** scanned, and the hole is
that a backtick template literal matches neither extractor pattern — so
patching the file list would have changed nothing. Add a single-line-backtick
pattern, then rewrite the message.

**Done when:** a concurrent request completes while `/v1/engines` is resolving;
a truncated `agent.yaml` comes up degraded with `/v1/config` reachable and the
reason on the wire; an acceptance check occupies 8080 before the wizard and the
Needs-attention card names the gateway; the vocabulary test finds a banned term
inside a backtick literal.

### 2.6 R1.6 — A model on two machines is two runtimes

*Finding: §6.1 #8. Size: M. Touches: `gateway`.*

Key the gateway's runtime and driver maps by `(node, name)` and carry the tuple
through `_ready_since`, `_runtime_inflight`, `_runtime_last_request`,
`idle_seconds`, `_runtime_name_for_driver` and `agent_url_for`.

**That is the fix the rest of the system is already written for**, which is why
it is M and not L: control keys placements by `(node, name)` and sorts by it,
and the metrics rollup's primary key already carries `node` — only the *value*
is wrong, because it comes from the merged survivor. Control refusing
duplicates would forbid the same model on two nodes, which is the replica case
calling #7 exists for; a UI suffix hides the symptom on the golden path and
leaves `agent_url_for` sending lifecycle actions to the wrong host.

**Two consequences the review did not name:** `_runtime_last_request` and
`_ready_since` are keyed by bare name too, so two same-named replicas share one
idle clock — node B's traffic keeps node A's stopped runtime looking recently
used. And the idle pass iterates the *merged* map, so one node's replica is
never considered for unload at all.

**Done when:** `test_multi_agent.py`'s existing two-node fixture is renamed to
what the UI actually produces for one model on two nodes (`qwen`,
`qwen-driver`) — which turns the test written for this scenario into the
reproduction — and it passes.

---

## 3. R2 — before the first hostile review

### 3.1 R2.1 — A node that did not answer is not a node with nothing on it

*Findings: §6.1 #9, §6.2 #18, §6.2 #17. Size: M + M + S. Touches: `gateway`.*

**One failed agent read destroys that node's driver clients under in-flight
requests (§6.1 #9)** and un-routes its models until the next refresh, while the
control root eighty lines away gets keep-the-previous-map treatment. Return a
success flag from the fetchers, union in the previous entries for a node that
did not answer, and drop a cached client only when a **successful** read no
longer lists it.

**`runtime is None` = always-eligible (§6.2 #18), whose widest trigger is not
the post-unload window this project diagnosed in 2026-09-11 but an agent read
failure** — one 401 from clock skew, one 5 s timeout, or the agent restart the
Reach switch performs on purpose, after which every driver on that node is
eligible regardless of engine state.

**The narrow fix this project already sketched fixes neither finding as
worded**, and that is the most useful thing the verification found here. *"A
failed read means keep the faith"* is exactly the behaviour #18 identifies as
the widest trigger; change it to **keep the previous facts** and #18 closes
entirely. And the sketch is about `/v1/runtimes` while #9 rides on
`/v1/components` — two reads, two fixes.

**The idle-unload race (§6.2 #17)** is check-await-act with no reservation: a
`self._stopping` set consulted by the eligibility rule, set under `try/finally`
in `idle_pass` **and in `_evict_for`**, whose `for _ in range(8)` loop reopens
the same window up to eight times on a path a user is actively waiting on. It
is lower severity than the other two — one stop-latency wide, once per idle
timeout — except on the streamed path, where M10's commit-point rule turns a
retryable race into a visible truncation. **Fixing R1.4 makes it reachable**,
because today a leaked counter is what accidentally keeps a runtime out of the
idle pass.

### 3.2 R2.2 — The installer's own advice, and the promise the wizard makes

*Findings: §6.1 #10, §6.2 #24, §6.2 #26, §6.2 #30, §6.3 #31, §6.3 #34. Size:
M + S + M + S + S + S. Touches: `specs/scripts`, `specs/docs/deployment`,
`agent`, `ui`.*

**Re-running `install.ps1` elevated — which `install.ps1:427` tells you to do —
builds a second install and strands the first (§6.1 #10).** Detection is not
merely possible, it is already written and pointed the wrong way: the elevated
run finds the per-user install's task by its fixed name and unregisters it
without a word. Four markers in order of reliability: the task's action path
(the same discriminator `reach.py` already uses), the User-scope config-file
variable, `%LOCALAPPDATA%\EugenePlexus\agent.yaml`, and the install-scoped
keyring entry. Refuse or migrate, with a switch; and set the engine root and
the library's default model roots under the prefix so a LocalSystem service
does not propose `C:\Windows\System32\config\systemprofile\Eugene Models`.

**The wizard promises what only the elevated service delivers (§6.2 #26).** The
default Windows install is `-AtLogOn` with no `-Principal`: it dies at
sign-out and does not start at a lock-screen reboot, while the copy says the
install *"comes back working without you"*. **Decision #4 is here.** The three
options and what each costs: an S4U boot task loses the interactive session —
which is the live install's mapped drive letter *and* its UNC Library mount —
and whether it keeps a console, and therefore the graceful stop, is
**unmeasured**; the real service costs Administrator, the accepted hard kill,
and #10's SYSTEM-profile home, so it cannot land before #10; correcting the
copy and **rendering `NodeReach.restart.detail`, which the agent already puts
on the wire and no screen prints**, costs nothing but words and is the only
option that also answers the phone getting "connection refused" at 7 am. The
fixture for that unrendered detail is already sitting unasserted in a page
test — the wiring lesson again.

**Both installers discard the stderr of every network step (§6.2 #24)**, so a
TLS-intercepting proxy reads as "could not create a virtualenv"; and
`EUGENE_PLEXUS_AGENT_BIND_PORT` — the only lever when 8079 is taken — is
honoured in the health wait and never written into the unit, plist or task.
Worse than the review said: if the uv bootstrap's `curl` fails, the command
substitution is empty, `sh -c ""` exits 0, and the `|| die` that names the URL
never fires. The one test that sets the port variable passes
`--no-service --no-start`, so it cannot reach the code path the override is
missing from.

**Two deployment documents describe an agent the installer does not produce
(§6.2 #30)** — **the prose is corrected as of 2026-09-17**: `tailnet.md` §1 and
§2 now start from the installer, the Reach switch and the five bind variables,
and `container.md`'s Windows row distinguishes the logon task (your session, a
mapped drive works) from the service (LocalSystem, UNC only). **What remains
for this slice is whatever the installer changes force** — in particular
`--advertise`, which both installers accept on any invocation and honour only
in the join branch, so the standalone case is either wired up here or stays
documented as join-only.

**Uninstall leaves more than the review counted (§6.3 #31):** two keyring
entries rather than one (`eugene-plexus-control` as well as the agent's), and
the node-local model copy directory — an operator-set path the agent creates,
fills with whole model files and manages — which neither uninstall path
mentions.

**A non-ASCII character anywhere in the install prefix defeats the Reach card's
self-restart detection (§6.3 #34)**, because `schtasks` output is decoded as
UTF-8 rather than the OEM code page. The card then affirmatively says nothing
starts this agent automatically, which is false and discourages the one action
it exists to offer. Read it through the `Schedule.Service` COM object, as
`reach.py` already does for the firewall.

### 3.3 R2.3 — A card we cannot see is not a machine without one

*Findings: §6.1 #11, §6.2 #29, §6.2 #28 (the Intel half). Size: L + S + S.
Touches: `specs/openapi/agent.yaml` (a contract change), `agent`, `library`,
`ui`.*

**Any non-NVIDIA GPU on Windows gets a CPU-only llama.cpp, silently, and is
then scored as a machine with no accelerator.** `_has_rocm` looks for
`rocm-smi` or `/opt/rocm` and `_has_sycl` for `sycl-ls` or Linux sysfs — none
of which exist on Windows — and there is no Vulkan probe and no
`Win32_VideoController` query. A 7900 XTX owner gets a CPU build, "no
accelerator was detected", a fit scored against RAM, and **the starter set
inverted to recommend the smallest model**, with nothing anywhere saying why it
is slow. Lemonade is vendor-backed for exactly that user.

**The review's supporting claims, checked:** `win-vulkan-x64.zip` and
`win-rocm-10.0-x64.zip` are both in this repo's own verbatim release fixture,
so those two are internally supported; **`win-sycl-x64` appears nowhere in the
repo** and is an unverified external claim. `win-rocm-10.0-x64` is reachable
only in principle today, because `_has_rocm` can never be true on Windows —
dead code that reads as AMD support.

**No new dependency is needed:** `pywin32` is installed on every Windows
install regardless of elevation, and there is a measured in-tree WMI precedent
at 112 ms in the firewall detector. The contract change is a `vulkan` member on
`Accelerator`, which reaches `agent`, `control` and `ui` through codegen.

**`nvidia-smi` that exists and fails is diagnosed as "not on PATH" (§6.2 #29)**
on the library side, and on the agent side the return code is ignored entirely,
so a wedged driver — the commonest Linux case after an update — is reported as
`cuda` and the install plan asks for a CUDA build. One three-state result per
`_run` fixes `_has_nvidia`, `_has_rocm` and `_has_sycl` at once, which is why it
belongs with the probe.

**The Intel half of §6.2 #28 is the one that OOMs**: `_intel_gpus` reports
`vramTotalBytes=0`, so `_verdict` takes the *no accelerator* branch and tells a
16 GB Arc owner that a 30 GB model fits, with `gpuCount=1` displayed beside it.
Branch on `gpuCount == 0` rather than on `vram_total == 0`, and let a card whose
size is unknown be `unknown` rather than `fits`. **A test exists, is green, and
asserts the docstring against a fixture the detector cannot produce** — the
fixture-not-the-subject shape this project keeps recording. The Apple half goes
to R3: it needs a Mac, and the Intel half should not wait for one.

### 3.4 R2.4 — Credentials proportionate to the job

*Findings: §6.2 #12, §6.2 #15, §6.3 #33. Size: S + M + S. Touches: `control`,
`agent`, `gateway`.*

**The control snapshot hands sealed keys, the salt and the Argon2 verifier to
any `service:*` token (§6.2 #12)** — so a gateway, library or driver token
holder that does not hold the master key (the configured-but-locked window, a
restarted agent, a node whose agent never unlocked) can pull verifier and salt
and run an offline passphrase attack. One clause of the review is wrong and the
fix is slightly larger than it implies: revoke and rotate use
`require_operator`, and control has no exact-service dependency anywhere, so
this is a new `decode_token` parameter plus a new dependency, on
`/v1/control/snapshot` and on `/v1/control/log`. **The test that should have
caught it encodes the defect as intent** — it asserts a `service:gateway` token
gets 200 on status and nodes and stops one endpoint short of the one carrying
key material. One added assertion is the whole regression gate.

**A worker names the address the root and the console proxy will dial (§6.2
#15).** The signature and sequence checks are sound — this is not an
authentication defect; it is that a correctly authenticated worker is trusted
to name an arbitrary URL, with `is_loopback_host` as the only filter, so
cloud-metadata addresses pass. Validate scheme and range at the root, treat a
change of host family as needing confirmation, and stop forwarding the
operator's `Authorization` verbatim to a registry-supplied base.

**The admin driver probe hands `service:gateway` to a URL typed into a form
(§6.3 #33).** Leave the behaviour, make the credential proportionate: probe
anonymously and report a 401 as *reachable, refused our credential*, which is
the more diagnostic answer anyway. That is where a hostile reviewer will point.

### 3.5 R2.5 — A backend that is still computing has not failed

*Findings: §6.2 #13, §6.2 #16. Size: M + M. Touches: `inference-driver`,
`gateway`, `agent`.*

**The timeouts are not fixed** — both are config-trio fields — so the defect is
four things: the **order** of the defaults (the driver's 120 s fires before the
gateway's 180 s, so the knob an operator reaches for is not the one that
governs), the **anonymity** of the failure (a timeout arrives as a transport
error and cascades, and the measured error string is literally *"Last error:
openai_compat_http request failed: "*, because `str(httpx.ReadTimeout(''))` is
empty), the **recomputation** (the next replica and the next tier run the same
prompt again, so a 30B on CPU is told "Every backend serving this model failed"
after 240 s with both engines having computed the answer), and — found by the
verification — the knob is **not durable**: the agent's boot reconcile rewrites
every companion driver's config file and discards the operator's edit.

Catch `httpx.TimeoutException` separately and carry its identity up, so the
cascade still covers a dead cloud backend — a tested decision, motivated by a
real 429 — while a backend that is merely still computing is not retried. This
is the other edge of the standing rule that *an explanation of a real failure
cannot be wrong*: ours is.

**Nothing cancels the backend when the client gives up on the non-streaming
path (§6.2 #16)**, and OpenAI SDKs retry twice by default, so a slow box ends up
with three identical generations queued for a client that left. Four sites, not
two: the review named the gateway's completion and the driver's stream route;
the verification adds the gateway's embeddings call and the driver's own
non-streaming path. `is_disconnected` occurs zero times in either repo.

---

## 4. R3 — the correctness-and-contract pass

One slice per seam, in this order. Everything here is real and none of it is
reachable on a golden path in the first hour.

1. **§6.2 #21 — the thinking filter swallows the whole answer.** Reproduced by
   execution: `<thinking>secret plan</thinking>The answer is 4.` streams as `''`
   at every chunking while the batch stripper keeps everything, because the
   streaming open match has no word boundary and the close match is a literal
   `</think>`. With `thinkingMode: off` a Claude-distill fine-tune streams an
   **empty 200** — the only finding on the list that returns a wrong answer
   rather than an error. It needs no hardware and the fix is S. The docstring
   claims the invariant is tested and **there is no test file at all**: the
   reverse of this project's usual failure, a prose claim of coverage standing
   in for the test.
2. **§6.2 #19 — admission reserves nothing.** Two launches in quick succession
   both read the same free memory and both `fits`; the node-local copy widened
   that window from seconds to minutes by adding a `copying` state before any
   process exists. And the file-size fallback is context-blind: an 8B Q4 at
   128k needs ~17 GB of KV and is admitted at 5.5 GB.
3. **§6.2 #20 — `tier` is still renumbered for the natural slot shape.** A
   surviving second case rather than a regression: the 2026-09-10 fix's own
   recorded carve-out is correct for a virtual alias and wrong for
   `{model: <a real local model>, targets: [cloud]}`, and the two are
   distinguishable. Until it is fixed, `GET /v1/metrics` cannot tell *primary
   served* from *primary was dead at refresh*, which is the one question tiered
   failover exists to answer.
4. **§6.2 #22 — contract drift on the request path, in four parts whose fixes
   split between contract and code.** `top_p` and `seed` are accepted and never
   forwarded (the contract promises pass-through or a warning and there is
   neither field nor warning); `max_tokens`/`temperature` come from
   gateway-wide defaults while the contract says *the model's settings profile*
   and the word "profile" occurs in gateway source only inside docstrings
   regenerated from that sentence; `content_filter` becomes `stop`, so a
   filtered answer reads as a natural end — **the same map, the next value,
   after `tool_calls` → `stop` was fixed at step 6**; and a driver 401 is
   reported to the caller as `invalid_request_error`, which is the shape a
   rotated service token takes on one node and is unfixable by the caller.
   **Recommendation: correct the contract for the first two** (no per-model
   output store exists to point at, so the promise cannot be met by editing
   code) and **fix the code for the last two**. The 401 half is locked in by a
   passing test that uses 401 specifically, so that test is amended, not added
   to.
5. **§6.2 #27 — symlinks, and a shipped config field nothing reads.** The
   review understated it: `followSymlinks` has exactly one occurrence in the
   library's whole source tree, its own declaration, and the scan-timeout
   message advises the operator about that switch **by name**. A UI without a
   tunable behind it is `gui-equality-for-configurable-things` violated in the
   harder direction.
6. **§6.3 #37 — five respawns of an engine that dies during load**, which on a
   remote mount is up to five full 23.8 GB reads. Make the back-off aware of
   observed uptime rather than only of the crash count.
7. **§6.2 #28's Apple half** — a Rosetta terminal produces an x86_64
   interpreter, after which Metal is never chosen and a Mac is scored CPU-only.
   Confirmed in code, unverifiable without a Mac, and the review's citation for
   *where* the x86_64 Python comes from is wrong (it is uv's own bootstrap plus
   `--python-preference only-managed`, not the installer's arch validation).
8. **The `perf_counter` and contract-prose sweep** left over from R1.1: the
   remaining `monotonic()` call sites that feed a reported `*_ms`, the 116 ms
   prose in `gateway.yaml`'s overview and `AttemptView.backendMs` (the two
   design-doc copies, in `local-inference-control-plane.md` §3 and
   `m8-retained-request-metrics.md`, were corrected in place 2026-09-17), the
   tier semantics, the `RuntimeSpec.name` uniqueness claim that nothing enforces,
   the `basis: metadata` claim over a scalar fallback, and **two errors found
   while checking their neighbourhoods rather than in the review: both
   `agent.yaml` and `common.yaml` say "bcrypt" for a passphrase that is
   Argon2id everywhere else, and `SecurityMode` is missing `passphrase_file`.**

---

## 5. R4 — Anthropic `/v1/messages`

**▶ DECISION #1 IS TAKEN (Troy, 2026-09-18): THIS GOES IN FRONT OF THE
RELEASE.** R4 runs alongside R2, after R1. It is no longer a candidate feature
competing with eleven High defects; it is scheduled work, and calling **#8**
(*one endpoint for every tool you use*) is written down as **not true until it
lands** — see `local-inference-control-plane.md` §2.

*Scoped against the code, not reasoned: two slices of about a day, one contract
change, radius `gateway` + `ui`.*

**Step one is a measurement, not a line of code.** Point a real Claude Code at
a throwaway listener with `ANTHROPIC_BASE_URL` and capture the request: the
`x-api-key` claim below is upstream client behaviour that was reasoned about
and **not verified here**, and it is the premise the whole auth half rests on.
If it is wrong, the shim is simpler; if it is right, a shim wired to the
existing dependency 401s the one client it exists for.

**The blocker nobody had named.** Claude Code with `ANTHROPIC_BASE_URL` +
`ANTHROPIC_API_KEY` sends **`x-api-key`**, not `Authorization: Bearer` — **that
half is upstream client behaviour and was NOT verified here; capture a real
request before building the shim** — while the half that is about our code was
checked: the gateway's bearer scheme reads only `Authorization`, and the CORS
front-door set is an exact-match frozenset — so a shim wired to the existing
dependency would 401 the one client it exists for, and the 401 would read as
*my key is wrong*. Support both headers; write the recipe with
`ANTHROPIC_API_KEY`.

**Translate at the edge into the existing `ChatCompletionRequest`, never
directly to the driver.** The chat route carries six behaviours a second front
door must share rather than re-implement: the surface refusal, the tools
refusal checked *before* a backend is picked so the answer cannot depend on the
balancer, the refresh-and-wake, the install defaults, the truncation detector,
and the recording. Extracting a `_serve()` out of `create_chat_completion` is
the slice's one real refactor — and sharing it is what keeps
`GET /v1/metrics` from being blind to the new door, **which is M8's finding in
a new place**.

**What is mechanical, what is hard, and what must be refused.** Mechanical:
most of the request and response mapping, and every stream event except one.
Hard: **Anthropic numbers content blocks statefully and we do not** — text
carries no index and our tool fragments carry a per-call index — so the
translator holds `text_open` and a map from tool index to block index, and
getting it wrong means a strict SDK rejects a stream *inside* a 200. Refused
with a 400 naming the field: `thinking`, image and document blocks, server-side
tools, `mcp_servers`, more than four `stop_sequences`, and a missing
`max_tokens`. **Dropped silently, and this one is load-bearing:**
`cache_control`, which Claude Code sets on every system block — so a blanket
unknown-field refusal would pass every refusal test and then fail the
acceptance run on its first request. `top_k` is dropped and documented as a
real loss (both engines take it and neither contract has it), which is the same
omission `top_p` and `seed` already have.

**Two rules survive and one must not be forced.** The failover commit point is
below both translators, structurally, so the rule that failover ends at the
first token carries over unchanged — but `message_start` must be emitted on the
first driver event and never on request acceptance, or it commits a model name
the cascade can still change. And the `x_eugene_plexus` envelope **does not go
in the Anthropic body**: their wire is typed events and a strict client is
exactly who we are courting, so the envelope rides in response headers while
the *recording* rides the shared path. Map our 400 to `invalid_request_error`
and not to anything Claude Code retries, or step 7's looping symptom comes back
one layer up in the client we are courting.

**Acceptance: twenty checks, and the last one is the point** — Claude Code,
pointed at this gateway with a local model id, completing a tool loop, asserted
from a file on disk rather than from Claude Code's own account of itself. Plus
the eighth recipe in the UI, the comment and the test that assert Claude Code's
absence inverted, and `dist` rebuilt with both installers re-pinned.

---

## 6. R5 — positioning

**▶ DECISION #2 IS TAKEN (Troy, 2026-09-18): ADOPT §4.3'S WORDING AND ORDER,
KEEP THE NUMBERS.** Applied the same day to
[`local-inference-control-plane.md`](local-inference-control-plane.md) §2
(which now carries the order table and is the source of truth for the words),
to CLAUDE.md and to the README's hybrid. **What remains in R5 is the two
surfaces this repo does not own:** Home's copy in `ui`, and the website — a
separate commit in a separate repo, whose two outright-false live claims are
named below.

**The shape that was adopted: seven lines said, eight ideas numbered.** #4
keeps its number and becomes a mechanism; the new *one endpoint for every tool
you use* is **#8** rather than taking #4's slot, because `differentiator #4`
is cited elsewhere for the old idea and #7 splits into the backends line and
the homelab line. §2 of the direction document holds the table.

*No code.*

**Corrected in place already, 2026-09-17, in `local-inference-control-plane.md`
§1-§2 and in CLAUDE.md:** *the operations layer is unclaimed*, *supervises
engines it doesn't own* as the lead, *llama-swap swaps one model at a time and
no one load-balances replicas*, and *exactly what the "run it on a server"
crowd lacks*. **And the README's hybrid is closed (2026-09-18)** — #2, #4, #5 and #6 had
kept the old wording while #1 and #7 had the new, in the one document a
stranger reads first. **Still to do in R5:** the same four claims in Home's
copy and on the website.

**And one thing R5 should publish rather than re-word.** The review's §3 notes
that **nobody in this field publishes the numbers that describe THIS layer**,
and we already have them measured: **failover around a killed replica in
172 ms**, **wake on demand in 2.5 s**, **time-to-first-token through two
proxies at 5-6.8 % of the request against 12.9 % direct**, and **a 24 GB model
serving in 21 s from a local copy against 266 s over SMB**. Publish those.
**tok/s is the engine's number, not ours** — and PolyServe's numbers are not
comparable to anything a hobbyist does, so borrow its method and never its
benchmark.

**The order and the words, as adopted 2026-09-18.** Led by what router mode,
llamactl and Unsloth do *not* do: installs, updates and restarts the engine for
you → tells you what fits before you download, and starts your settings there →
finds and downloads models in the app, into your own folders, as plain files →
one endpoint for every tool you use → add the backends you already run and the
subscriptions you already pay for → reach it from your other devices, safely →
grows into a homelab. **The numbers stayed attached to the old ideas**, because
`#3` and `#7` are cited by number in a dozen documents, the acceptance records
and the memory files — so the fourth line is the new **#8**, the sixth is #5,
the second is #6, and the fifth and seventh are the two halves of #7.

**Three sentences must not be published before the fix that makes them true:**
the fit claim (R1.3), the replica claim (R1.6), and the file-ownership card
(R1.2's download confinement). They are the first three things a reviewer
tests. And two live site claims are outright false rather than dated — *"gives
every tool you use one address to talk to"* with a `Coding agents` chip, which
R4 is what makes true, and *"never copied, never renamed"*, which our own
node-local copy falsified the same day it shipped (the replacement line exists:
*we manage what we made and never touch what you put there*).

---

## 7. R6 — the hobbyist remainder

S8's glossary and Config grouping, S9's phone/focus/motion pass, and the two
items S10 still owes its own *Done when*: `EP_DOWNLOAD=1` for the ten-minute
target, and the moderated sessions, which are decision #14 and gate the
release.

**One concrete check the review names and nothing has ever run:** score the
starter set against **8 GB of VRAM with 16 GB of RAM**, the beginner thread's
OP. The existing context checks use a 24 GiB card and a 12 GiB one. Two rows
also belong in that plan's stuck-points table and have no home today — a
slow-but-healthy answer reported as a failure (§6.2 #13) and a component that
never came up (§6.1 #7).

---

## 8. Deliberately not scheduled

Each with the reason, so silence is not read as an oversight.

- **The shared HS256 key (review §6.4).** Decision #5. Established both ways in
  code: the key mints operator sessions with no state, and an operator token can
  declare a runtime with an arbitrary `binary` and `extraArgs` on any node. **Do
  not relitigate the recorded decision** that the install key lives in the clear
  on each node — it needs no change. What needs writing down is that the
  decision's blast radius exceeds its own reasoning: it was argued for *nodes*
  and the code extends it to *every child process*, including a companion driver
  whose whole job is to talk to a third-party backend. Recommended now:
  constrain `binary`/`extraArgs` to the engine store plus the configured path
  with an explicit override, and stop handing the master key to components that
  unseal nothing. The asymmetric split is a contract question, not an edit.
- **A benchmark button on a profile.** Decision #6, and it is better than the
  review framed it. The expensive half needs no building: `llama-bench` is
  already in the engine store in both retained builds, is already a sweep
  engine, and its `--progress` output is the tasks tray's fraction for free.
  **The knob the review named is the wrong one:** measured on this box,
  `gpuLayers` 0→99 is 7.2× but only on a partial offload, while **depth — the
  context axis — is 3.4× and completely invisible today** (902 / 678 / 262 tok/s
  at 0 / 4096 / 16384). The library prints *the largest context that fits is N*
  and nothing says decode at N is a third of decode at zero. `llama-bench` has
  no `--parallel` and no `-c`, so `parallelSlots` is not measurable by that
  instrument at all. **Name it something other than "Measure it"** — hobbyist
  S10 already has that name. The framing that makes it not an admission of
  defeat: prediction answers *does it fit*, measurement answers *how fast is it
  here*, and they are not competing.
- **Concurrent users on one runtime.** Never measured, and LM Studio leads with
  it. R1.3 makes the verdict honest about slots, which is the prerequisite.
- **MLX on `main`.** Still blocked on a real problem no Mac fixes: the server
  has no `--served-model-name`, so two MLX runtimes advertise one id.
- **Rolling engine upgrades**, and the mixed-version fleet the Issues run
  produced on purpose. Unbuilt, recorded, and now a two-engine problem.
- **Library redundancy**, Troy's answer to "the library is down".
- **The recommendation slot (review §5 #8).** Google's AI overview, LLM output
  and YouTube still say Ollama — the beginner thread's own complaint — and
  llamactl occupies the same search query we would want. **Not scheduled as a
  slice, deliberately: the words are R5's output and the channel cannot be
  bought.** Recorded here so the silence is a decision. The one thing that is
  actionable is R5's second half: publish the numbers that describe this layer,
  because they are the only claims an LLM could repeat that nobody else makes.
- **The macOS installer has never been run** (review §5 #5, second half). The
  code is written, the launchd plist is written, and there is no Mac. R3 item 7
  carries the Rosetta detection defect, which is readable without one; the run
  itself is unscheduled for the obvious reason, and the README says so.
- **vLLM's admission arithmetic is a second known-wrong basis** (review §1.9,
  check (b)). The adapter reports `parallelSlots=None` and scores by
  `maxModelLen`, where a paged-attention engine's real floor is closer to
  `0.25 × ctx × max_num_seqs`. Not scheduled: it needs a live vLLM to measure
  against, and R3 item 2 fixes the arithmetic that everyone actually hits
  first. Named here so it is not rediscovered as new.

---

## 9. Order, and what each stage ends with

```
R1.1 → R1.2 → R1.3 → R1.4 → R1.5 → R1.6      before any public link
  ^ DONE 2026-09-18
R2.1 → R2.2 → R2.3 → R2.4 → R2.5             before the first hostile review
R4  (alongside R2)                            decision #1, TAKEN: in front
R3                                            the correctness pass
R5  (no code; can land any time)
R6 → the release                              decision #13's gate, unchanged
```

**R1.1 first** because every other measurement is taken through its
instrument. **R1.4 before R2.1** because a leaked counter currently masks the
race. **R2.2's #10 before any behaviour change to the Windows autostart.**
Everything else is independent.

**The release gate is unchanged and this roadmap does not shorten it:** it is
`hobbyist-ux.md` **decision #13** (what gates it — S0-S6 and S10) plus
**decision #14** (three to five moderated sessions), with `EP_DOWNLOAD=1` and
the ten-minute target still unmeasured, a starter review under thirty days old
with no unresolved verdict, and the `dist` branch rebuilt from the pinned
commit. R1 and R2 sit in front of it. *(Both numbers are cited here because
four documents cite one or the other and disagree.)*

**The estimate is the review's, at this project's observed pace of one slice a
day with an acceptance run: two to three days for R1, about a week for R1 and
R2 together** — before the sessions, not instead of them. Nobody has held a
stopwatch to it.

---

## Appendix — every finding, and where it went

`[S]` security pass, `[D]` data path, `[F]` first hour, `[me]` the review
session itself. **38 numbered findings plus §6.4, all re-verified present on
2026-09-17**, and one extra row for the market threat §5 #1. **This table is
the list — it is not a to-check list.** Read the row, open the slice, write the
failing check. Nothing here needs confirming again.

| #      | Finding                                                     | Slice |
| ------ | ----------------------------------------------------------- | ----- |
| 6.1 #1 | Login limiter driven by a supplied forwarded header `[S]`     | **R1.2 — done 2026-09-18** |
| 6.1 #2 | Per-call `httpx.AsyncClient` = 104 ms on the loop `[D]`       | R1.1  |
| 6.1 #3 | Disconnect mid-stream leaks the in-flight counters `[D]`      | R1.4  |
| 6.1 #4 | Two fit paths; the golden path uses the scalar one `[F]`      | R1.3  |
| 6.1 #5 | `/v1/engines` blocks the loop on `nvidia-smi` + GitHub `[F]`  | R1.5  |
| 6.1 #6 | `agent.yaml` non-atomic write + unguarded load `[F]`          | R1.5  |
| 6.1 #7 | A taken port; no `component-down` issue kind `[F]`            | R1.5  |
| 6.1 #8 | Runtimes merged by bare name across nodes `[D]`               | R1.6  |
| 6.1 #9 | A failed agent read closes that node's clients `[D]`          | R2.1  |
| 6.1 #10| Elevated re-install strands the first install `[F]`           | R2.2  |
| 6.1 #11| Non-NVIDIA Windows GPU gets a CPU build silently `[F]`        | R2.3  |
| 6.2 #12| Control snapshot readable by any service token `[S]`          | R2.4  |
| 6.2 #13| GPU-sized timeouts cascade healthy CPU inference `[D]`        | R2.5  |
| 6.2 #14| Download `filename` escapes every model root `[S]`            | **R1.2 — done 2026-09-18** |
| 6.2 #15| A worker names the URL the root will dial `[S]`                | R2.4  |
| 6.2 #16| No cancel on client disconnect; SDKs retry `[D]`               | R2.5  |
| 6.2 #17| Idle unload races an arriving request `[D]`                    | R2.1  |
| 6.2 #18| `runtime is None` = always eligible `[D]`                      | R2.1  |
| 6.2 #19| Admission reserves nothing; fallback context-blind `[D]`       | R3    |
| 6.2 #20| `tier` renumbered for the natural slot shape `[D]`             | R3    |
| 6.2 #21| Thinking filter swallows the answer when streaming `[D]`       | R3    |
| 6.2 #22| Contract drift: `top_p`/`seed`/profile/`content_filter`/401 `[D]` | R3 |
| 6.2 #23| `latencyMs` semantics + the 15.6 ms Windows grid `[D]`         | R1.1  |
| 6.2 #24| Installers swallow network errors; port override ignored `[F]` | R2.2  |
| 6.2 #25| `HTTP_PROXY` applied to loopback traffic `[F]`                 | R1.1  |
| 6.2 #26| The wizard promises an autostart the default lacks `[F]`       | R2.2  |
| 6.2 #27| Symlinks dropped unreported; `followSymlinks` inert `[F]`      | R3    |
| 6.2 #28| Intel reports zero VRAM; Rosetta hides Apple silicon `[F]`     | R2.3 / R3 |
| 6.2 #29| An `nvidia-smi` that fails reads as "not on PATH" `[F]`        | R2.3  |
| 6.2 #30| `tailnet.md` / `container.md` describe another install `[F]`   | done 2026-09-17 / R2.2 |
| 6.3 #31| Uninstall leaves engines, two keyring entries, copies `[F]`    | R2.2  |
| 6.3 #32| No frame-ancestors on the agent-served UI `[S]`                | **R1.2 — done 2026-09-18** |
| 6.3 #33| Operator-gated SSRF; probe spends a service token `[S]`        | R2.4  |
| 6.3 #34| A non-ASCII prefix defeats self-restart detection `[F]`        | R2.2  |
| 6.3 #35| Banned vocabulary through the wizard's error path `[F]`        | R1.5  |
| 6.3 #36| Parallel slots divide the context; the copy says otherwise `[me]` | R1.3 |
| 6.3 #37| Five respawns of an engine that dies during load `[D]`         | R3    |
| 6.3 #38| A stream with no `done` frame is recorded served `[D]`         | R1.4  |
| §6.4   | One HS256 key mints sessions and signs service tokens `[S]`    | §8, decision #5 |
| §5 #1  | No Anthropic `/v1/messages` — **a market threat, not a defect** | R4 — decision #1 **TAKEN 2026-09-18: in front of the release** |
