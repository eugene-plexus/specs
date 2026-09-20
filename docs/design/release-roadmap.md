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
whose steps 1-8 are built and whose step 9, *the release*, was **deleted on
2026-09-18** (decision #3), so that document’s build order is complete —
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
first verifications, not repeats** — **and #36's is DONE: measured 2026-09-18
against llama-server b11001 and b10991, `-c` is the total budget that slots
divide, so the arithmetic was right and both config descriptions were wrong
(R1.3, `../acceptance/one-fit-path-run.md` §0). **And R4's is DONE: measured
2026-09-19 against Claude Code 2.1.207 — `x-api-key` confirmed, and there is no
`Authorization` header on that path at all, so the premise was if anything
understated; four sub-claims beside it were wrong, `thinking` loudest
(`../acceptance/anthropic-messages-measurement.md`). ONE REMAINS —
`win-sycl-x64`.** Originally: — they were never established, so a session
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

| #     | The call                                                                                       | §          | Recommendation                                                                                                                                                                                                                        | Status                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----- | ---------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1** | Does Anthropic `/v1/messages` go in front of the release, or after it?                         | §5         | **In front, as R4, after R1 and alongside R2.** It is the one matrix row that decides the first review                                                                                                                                | **TAKEN 2026-09-18 (Troy): IN FRONT.** R4 is scheduled, not optional. Its first step is capturing a real Claude Code request, because the `x-api-key` half is upstream behaviour this review did not verify                                                                                                                                                                                                                                                                         |
| **2** | Adopt the review's §4.3 re-ordering and re-wording of the seven callings?                      | §6         | **Adopt the wording everywhere; keep the numbers attached to the old ideas** — a dozen documents cite `#N`                                                                                                                            | **TAKEN 2026-09-18 (Troy): ADOPT.** Applied as recommended — seven lines said in §4.3's order, eight numbered ideas, nothing renumbered. #4 keeps its number as a *mechanism*; the new *one endpoint for every tool you use* is **#8** and is the one line that is not true until R4                                                                                                                                                                                                |
| **3** | Are the eight pre-link fixes a new numbered step in install-paths §9, or a gate inside step 9? | §9         | **A gate inside step 9 (9a/9b)**, because "step 9 is the release" is cited in CLAUDE.md, the memory files and §12. **Written that way provisionally on 2026-09-17** — the call is whether to keep it or promote it to a numbered step | **TAKEN 2026-09-18 (Troy): NEITHER — THE STEP IS REMOVED.** *“We should remove and delete any notion that a release is due.”* Step 9 held no work of its own: 9a pointed here, and 9b’s two failing checks are already in §9 below. `install-paths` §9 now ends at step 8 and says its build order is complete                                                                                                                                                                      |
| **4** | Windows autostart: fix the copy, or change the mechanism?                                      | §3.2, §3.6 | **Fix the copy now (R2.2); treat a boot-time task or the service as its own slice** — S4U costs the mapped drive                                                                                                                      | **TAKEN 2026-09-18 (Troy): THE REAL SERVICE, as its own slice (R2.6). The copy fix is REJECTED, and the reason generalises — *"we're not releasing until the copy as it stands is TRUE, so fixing the copy only satisfies a checklist, not a real user pain point."* The recommendation had the dependency right and the goal wrong: the promise is the requirement, not the thing to negotiate down**                                                                              |
| **5** | The shared HS256 key (review §6.4): split it, withhold it from drivers, or accept it?          | §8, §10    | **Withhold it from processes that unseal nothing, and constrain `binary`/`extraArgs`; do not split the key yet**                                                                                                                      | **TAKEN 2026-09-18 (Troy): SPLIT IT, AND BEFORE THE RELEASE.** *“I would rather release with things correct than release too early and lose trust.”* Scheduled as §10 **R7**; the recommendation’s two halves become its first step rather than the whole answer                                                                                                                                                                                                                    |
| **6** | A benchmark button on a profile — "measure, don't predict" (review §1.9/§5 #4)?                | §7, §8     | **Yes, but after the release gate**, and not under the name "Measure it" (that is hobbyist S10)                                                                                                                                       | **TAKEN 2026-09-18 (Troy): BEFORE the release, in R6, for R5's reason** — *“it belongs in R5/R6 where the positioning is.”* The recommendation deferred it past the gate; the counter-argument in this row is the one that held, so the **depth number is a differentiator rather than a follow-up**. R5 is *no code*, so the surface lands in R6 and the claim it produces is R5's                                                                                                 |
| **7** | Release timing, against a clock that is now visible on both sides of the thesis                | §9         | **Keep decision #14 as taken** ("2-3 friends for sure", no hurry) and let R1-R2 be the reason, not the delay                                                                                                                          | **TAKEN 2026-09-18 (Troy): THE ROADMAP DOES NOT SET A RELEASE TIME, AND CARRIES NO ESTIMATE.** Finish the work as it stands, then re-assess where the project is and where the competition is, and decide then. *“Agents are notoriously bad at predicting the passage of time and the length of time it takes to do things.”* The forecast that used to sit in §9 is **deleted**, not revised — including the one added the same day for R2.6. Decisions #13 and #14 are untouched |

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r13-acceptance.sh`, **17
PASS, zero failures, third execution**; record
[`../acceptance/one-fit-path-run.md`](../acceptance/one-fit-path-run.md).
Findings §6.1 #4 and §6.3 #36 are closed. 23 unit checks across two repos, **13
scripted sabotages, 13 caught**
([`../../scripts/r13-sabotage.py`](../../scripts/r13-sabotage.py)). No contract
change and no UI change — the config descriptions render from the schema, so
the corrected copy reaches the browser with no `dist` rebuild.

**▶ AND #36'S PREMISE WAS MEASURED BEFORE A WORD WAS CHANGED, WHICH IS WHAT
THIS ITEM ASKED FOR.** `llama-server` **b11001** on a Qwen3-0.6B and
independently **b10991** on a Qwen3-1.7B: `-c 32768 --parallel 4` logs
`llama_context: n_ctx = 32768` — the same allocated cache as `--parallel 1` —
with `n_ctx_slot = 8192`, `kv_unified = 'false'`. **So `-c` is the TOTAL budget
that slots divide: the arithmetic was right and both descriptions were wrong**,
in the expensive direction (they told an operator that more slots cost memory,
making "lower the context" the apparently-sensible response, which shrinks each
request's window for nothing saved). It also explains the readback: `/props`
exposes only the per-slot `n_ctx`, so a 32768/4 runtime reports
`contextLength: 8192` against a contract whose word for that is *clamped*. The
field keeps its meaning; the admission reason states the division, and only
when it happens.

**The fit half came out as delegation.** `_shape_for` rebuilds a `GgufMetadata`
from the stored KV dict and hands it to `preflight.shape_from_gguf` — **a
second shape builder is the defect, and there is one now.**
`attention.layer_indices` comes free with it, and `_INLINE_ARRAY_LIMIT` went
from **64** to 512 because the shipped starter block counts are 32, 42, 48 and
**65**: it missed by one on a model in the product's own starter file. A shape
whose per-layer terms were dropped now stops claiming `basis: metadata`, which
is what a library scanned before this fix still looks like.

**Three sabotages escaped the first pass and every one named a missing check
rather than a needless guard** — the honest-basis test built its `ModelShape`
by hand and so never called the detection; the entry's own `contextLength`
could stop being reconciled invisibly; and the fixture could write the bool
array as int32, meaning the suite was asserting about a type the reader never
meets. **And the harness inverted the measurement twice**: `-v` is required or
the engine never prints `llama_context: n_ctx`, and `sort | tail -1` over paths
picks the wrong build.

**The original scope follows.**

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r14-acceptance.sh`, **18
PASS, zero failures, third execution**; record
[`../acceptance/stream-bookkeeping-run.md`](../acceptance/stream-bookkeeping-run.md).
Findings §6.1 #3 and §6.3 #38 are closed, **and so is the second leak this
section named below**. 14 unit checks in `gateway`, **13 scripted sabotages, 13
caught** ([`../../scripts/r14-sabotage.py`](../../scripts/r14-sabotage.py)). No
contract change and no UI change; nothing re-pinned.

**▶ AND THE RUN'S OWN FINDING IS ABOUT A CHECK, NOT THE PRODUCT: check 5
PASSED AGAINST A DELIBERATELY SABOTAGED GATEWAY.** It read `idle_seconds` off
the admin view, which is computed from the last-served mark and is blind to the
in-flight counter — so it answered the same whether or not the counter leaked.
This project's recurring failure, caught this time only because the live
sabotage run was performed rather than assumed. What cannot be faked is **the
agent being asked to stop**, so the stub records every stop it receives and the
check asserts the unload really happens. Sabotaged, it reads `stops the agent
was asked for: []` — and check 4 reads `in_flight is 4`, one per closed tab,
accumulating. Two harness defects besides: `tail -1` on an SSE file is the
blank line after the frame (two checks reported the product broken while it was
right), and `attempts` on a metrics row is a **count** — the per-attempt facts
are under `tries[]`.

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
the counter on an attempt identity. **Done the first way:
`on_attempt_start` RETURNS the runtime it counted against and the slot hands it
straight back, on all three methods. R2.1 still owns the reads that make the
snapshot wrong; this owns the pairing, which is wrong whatever the reads do.**

**Done when:** a test drives `TieredClient.stream`, consumes one event, closes
the generator, and asserts `runtime_inflight(name) == 0`; a stream that returns
without a `done` event is recorded `served=False` and the client gets a
terminal frame with a `finish_reason` before `[DONE]`.

### 2.5 R1.5 — The first hour survives a hostile box

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r15-acceptance.sh`,
**35 PASS, zero failures, fourth execution**; record
[`../acceptance/a-hostile-box-run.md`](../acceptance/a-hostile-box-run.md).
Findings §6.1 #5, §6.1 #6, §6.1 #7 and §6.3 #35 are closed. `agent`
`a5f482e`, `ui` `5cbcdfb` (dist `640e3de`); **no contract change** —
`Health.details` is free-form and `Component.lastError` has existed since M0.
Both installers re-pinned and `dist` rebuilt in the same session.

**Measured:** `/healthz` answers in **0.06 s** while `/v1/engines` resolves a
real 2-second `nvidia-smi`, and the probe runs **once** where it ran three
times. 8080 held before first boot → the gateway declared on **8084** and
`running`, library and control on their documented ports. A cut `agent.yaml` →
the agent **up**, `degraded`, the reason on the wire, `/v1/config` reachable, a
copy of the broken file beside it, and first-run setup **refused** with restore
as the remedy.

**Three things the build found that the plan did not have.** (a) `#35`'s
mechanism was wrong and running the extractor proved it — `start.ts` was always
scanned and the hole is that a **backtick literal** matched neither pattern; one
offender in the whole golden path, and it is the wizard's worst sentence.
(b) **`firstRunComplete` cannot be the signal that an install held a
passphrase**: it is also how every acceptance script says *skip onboarding* and
how an enrolled node reads, and a first version keyed on it and broke both. Only
the auth keys are evidence, and `yaml.safe_dump` sorts keys, so a half-written
file **keeps** its `auth` block and loses the tail. (c) The degraded load must
**reset** the in-memory state, not just report: `load()` mutates as it parses,
so the next `PATCH /v1/config` would persist a topology nobody declared.

**Two harness traps in the concurrency check, both of which passed against the
defect.** Its clock started *after* waiting for the first request to get going —
a blocked loop cannot resume the waiting coroutine either, so the mark was taken
after the half second had elapsed. And it was unauthenticated, so a 401 was
refused before the probe ran and nothing blocked.

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18**, in the same pass as R1.5 and with the
same acceptance script and record. Finding §6.1 #8 is closed. `gateway`
`1162bdc`; no contract change. **And it is the first time two nodes have been in
front of a LIVE gateway with one name between them** — a real gateway process
finding its agents through a control root's `/v1/nodes`, over two agents each
declaring `qwen` and `qwen-driver`: two backends one per node, node A `stopped`
→ only node B routable, a completion served, and an idle unload arriving at
**node B's** agent.

**The rename WAS the reproduction, exactly as this section predicted**, and it
cost eleven assertions: a list of distinct driver names cannot express a
two-node install once both are called `qwen-driver`, so they read node names
now.

**The driver maps needed it too, which this section says and is worth
repeating**, because it reaches further than the runtime half: `DriverClient`
gains a `node`, `RoutingHooks` a `node` keyword, and the `runtime` handle the
hooks pass back is a `(node, name)` pair. `served_by_node` sits beside
`served_by` for the same reason.

**And "routable on faith" is a WARNING now**, which M7's record asked for: it is
the eligibility rule saying yes to an engine whose state it does not know.

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r21-acceptance.sh`, **14
PASS, zero failures, second execution**; record
[`../acceptance/node-read-failures-run.md`](../acceptance/node-read-failures-run.md).
Findings §6.1 #9, §6.2 #18 and §6.2 #17 are closed. 19 unit checks in
`gateway`, **15 scripted sabotages, 15 caught**
([`../../scripts/r21-sabotage.py`](../../scripts/r21-sabotage.py)), **and all
three findings were put back against the LIVE gateway** and each failed the
checks written for it. No contract change and no UI change; nothing re-pinned.

**▶ THE LIVE SABOTAGE IS WHERE THE SEVERITY CAME OUT.** With §6.1 #9 restored,
**ten of ten completions died** across a failing read — not a narrow window.
With §6.2 #18 restored, a request for a *stopped* engine returned **200**: it
was routed to it. With §6.2 #17 restored, a backend was still eligible while its
engine was being stopped.

**One escape, and it named a missing check.** Removing the `try/finally` from
the reservation passed, because the test drove it with an `httpx.ConnectError`
and `AgentLifecycleClient.stop` catches **every** `httpx.HTTPError` and returns
`False` — so the exception never reached the `with` block. The `finally` earns
its place against what `stop()` does *not* catch: the idle loop's task cancelled
mid-stop at shutdown. Both are checks now.

**One harness defect:** check 3 asserted 404 where the product answers **503**,
which is the better sentence — the model *is* served by something this gateway
knows about and none of it can take a request.

**Window B is open by decision, and the record says why.** The reservation
covers the stop *call*; between the agent's 202 and the next refresh the
snapshot still says `ready`. Widening it needs a release rule that cannot get
stuck, and a healthy runtime permanently unroutable is worse than the window.

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
because until then a leaked counter was what accidentally kept a runtime out of
the idle pass — **and R1.4 landed 2026-09-18, so this is a live race now and
not a theoretical one**.

### 3.2 R2.2 — The installer's own advice, and the promise the wizard makes

**▶ BUILT AND VERIFIED 2026-09-18.** `scripts/r22-acceptance.sh`, **49 PASS
across three gates, zero failures**; record
[`../acceptance/installer-advice-run.md`](../acceptance/installer-advice-run.md).
Findings §6.1 #10, §6.2 #24, §6.2 #30, §6.3 #31 and §6.3 #34 are closed.
**29 scripted sabotages, 29 caught — after five escaped on the first pass, and
every one of the five named a missing check rather than a missing fix** (§6 of
the record). `scripts/install-acceptance.sh EP_MODE=posix` re-ran green
afterwards: a real install from nothing in WSL2, 16 checks, zero failures.
Repos: `specs` (both installers) and `agent` (`reach.py`); no contract change,
no UI change. **Both installers re-pinned** — the component pins had been five
repos stale since R1.1 because nothing until now shipped through them, and
#34's fix is in the agent, so it reaches nobody without a bump; all five go to
current HEADs and `ui` stays at dist `9fccf05`. **`ui` is untouched, so #10's
dependency for R2.6 is met.**

*Findings: §6.1 #10, §6.2 #24, §6.2 #30, §6.3 #31, §6.3 #34. Size:
M + S + S + S + S. Touches: `specs/scripts`, `specs/docs/deployment`,
`agent`, `ui`. **§6.2 #26 moved to R2.6 on 2026-09-18** — see below.*

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

**The wizard promises what only the elevated service delivers (§6.2 #26) —
▶ AND DECISION #4 IS TAKEN: THE PROMISE STANDS AND THE MECHANISM CHANGES
(Troy, 2026-09-18).** The default Windows install is `-AtLogOn` with no
`-Principal`: it dies at sign-out and does not start at a lock-screen reboot,
while the copy says the install *"comes back working without you"*. This
section used to recommend correcting the copy here and deferring the mechanism,
and **that recommendation had the dependency right and the goal wrong**. Troy:
*"fixing the copy is a waste of time because we're not releasing until the copy
as it stands is TRUE. So fixing the copy only satisfies a checklist, not a real
user pain point."* **The general rule, worth more than this slice:** when the
release gate is *the thing we say is true*, editing what we say to match a
weaker mechanism moves the gate instead of reaching it.

**So #26 leaves R2.2 entirely and becomes §3.6 R2.6**, which builds the real
Windows service. It still cannot land before #10 below — the service runs as
LocalSystem, which is exactly the SYSTEM-profile home #10 is about — so the
order within R2 is unchanged. What R2.2 keeps of this is nothing: no copy edit,
no interim wording. **`NodeReach.restart.detail` moves with it**, because what
that field should say is decided by the mechanism.

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r23-acceptance.sh`, **14
PASS live, zero failures**; record
[`../acceptance/unseen-card-run.md`](../acceptance/unseen-card-run.md).
Findings §6.1 #11, §6.2 #29 and §6.2 #28 (the Intel half) are closed. **21
scripted sabotages, 21 caught**, across four gates — after two escaped and each
named something real (an unreachable filter, deleted; and a sabotage that
stopped expressing its defect once the fix moved). **Two contract documents**,
`agent.yaml` (`vulkan`) and `library.yaml` (`unknown`); radius measured by
regenerating all six, with `gateway` and `inference-driver` byte-identical and
reverted. Repos: `specs`, `agent`, `library`, `ui`, `control` regen-only. **Both
installers re-pinned and `dist` rebuilt**, because the UI changed.

**The live run and the install run each found something reading did not.** On
this box — which has an AMD integrated adapter beside the 5090 — a real agent
with no working `nvidia-smi` now picks `win-vulkan-x64` off a real upstream
release where it picked `win-cpu-x64`. And `install-acceptance.sh` failed check
14 at the new pins, twice, bisecting to `library` in two runs: the first version
of #29's fix answered *which tool failed* by re-probing all three vendor tools
on every hardware read, which in WSL2 left a library process alive after its own
shutdown. Same family as §6.1 #5.

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.** `scripts/r24-acceptance.sh`, **21
PASS, zero failures, second execution**; record
[`../acceptance/proportionate-credentials-run.md`](../acceptance/proportionate-credentials-run.md).
Findings §6.2 #12, §6.2 #15 and §6.3 #33 are closed. **20 scripted sabotages,
20 caught** ([`../../scripts/r24-sabotage.py`](../../scripts/r24-sabotage.py))
across four gates, **the three findings themselves put back against the LIVE
processes** — after two escaped on the first pass and **each named a missing
check rather than a weak fix**: the agent's parametrized scheme cases could not
tell whether the scheme was looked at (`file:///…` has no host and was refused
by the next branch), and nothing asserted that the address check runs *before*
the join token is consumed. **Prose only in two contract documents**; models
came back byte-identical in both repos, and `control` and `gateway` re-pinned
because they IMPLEMENT the prose. Repos: `specs`, `control`, `agent`,
`gateway`. **Both installers re-pinned; no UI change, so no `dist` rebuild.**

**▶ THE RULE IS *BECOMING PUBLIC*, NOT *WIDENING*, AND THE REPRODUCTION CHECK
IS WHAT SAID SO.** Written first as a rank comparison — `loopback` < `private`
< `public`, refuse anything moving right — it refused `loopback → private`,
which is the **S5 Reach switch**: one click, on Home, on the commonest install
there is. The check went red immediately and the rule narrowed to the one
transition a homelab node never makes by itself. The rank version is a sabotage
of its own now. **And `is_private` is the wrong predicate**:
`ip_address("100.64.0.7").is_private` is **False** on the Python both installers
provision, and that is where a tailnet address lives — so the classes come from
the negation of `is_global`. The same trap bit the fixtures: `203.0.113.9` is
TEST-NET-3 and reports `is_global: False`, so the first "moves onto the open
internet" case was an address the rule reads as private.

**Left undone and named** in the record: the operator has **no surface** for a
refused announcement (it wants a contract field this slice does not take, so the
node reads `reachable: false` with a *probe* error rather than the real reason);
re-enrollment as the confirmation path is asserted in words and never walked;
and no browser drove any of it.

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

**▶ BUILT AND LIVE-VERIFIED 2026-09-18.**
`scripts/still-computing-acceptance.sh`, **29 PASS, zero failures, fifth
execution**; `scripts/r25-sabotage.py`, **29 sabotages over four gates, 28
caught and 1 escaped by measurement** — after a first pass that escaped eight
and **found that three of the run's checks could not fail** (see below); record
[`../acceptance/still-computing-run.md`](../acceptance/still-computing-run.md).
Findings §6.2 #13 and §6.2 #16 are closed. **A contract change after all, and
finding it was part of the work**: `gateway.yaml` said in two places that
*timeouts cascade*, which is exactly what this slice stops, and neither document
had a 504 or a 499 on any path. Prose plus five response entries — **no schema
moved**. Radius measured by regenerating: `gateway` and `inference-driver` came
back byte-identical apart from the header SHA and re-pinned anyway because they
IMPLEMENT the rule; `agent`, `control` and `library` codegen neither document;
`ui` gains only JSDoc no screen consumes and is deliberately left back, which
also avoids a `dist` rebuild for a comment.

**The four wrongs, and the fourth is the one that made the others pointless.**
The **order**: gateway `requestTimeoutSeconds` is **600 s** (the OpenAI Python
SDK's own default, so the commonest caller stops waiting when we do) and the
driver's is **660 s**, a backstop rather than a decision; both maxima are 3600 s
now. The **anonymity**: `BackendTimeout(CliError)` carries `limit_seconds`, and
the message names the seconds and the setting where `str(httpx.ReadTimeout(""))`
had left it ending in a colon. The **recomputation**: a fired deadline is
**504**, and neither `_is_cascade_eligible` nor either gateway route retries it.
The **durability**: `companions.py` merges the three fields it manages into the
companion's config instead of rendering the file, so the knob survives the boot
reconcile that had been eating it.

**The split inside `TimeoutException` is what makes this more than one line.**
`httpx.ConnectTimeout` IS a `TimeoutException` and is a *dead host* — nothing
was handed to an engine, the next backend is a real rescue, and it keeps
cascading. `ReadTimeout`/`WriteTimeout`/`PoolTimeout` mean the work started, and
they do not. Both repos split it the same way.

**The number now exists once per repo, and it had been written in seven
places** — the gateway's schema default, `app.py`'s `or 180` and
`RoutingTable`'s signature default; the driver's schema default and each of
three engines' `or 120`. That is how the order got inverted with nobody deciding
it. Neither repo can test the comparison, so it is pinned by a unit check in
each plus check 3 of the run, which reads both numbers out of the two **running
processes**.

**§6.2 #16 is five sites, not four**, and the fifth is the one reading gets
wrong: `StreamingResponse` already races the body against `http.disconnect`, but
`/v1/generate/stream` awaits its FIRST chunk before handing the generator over —
deliberately, so an early failure can still be a status code — and on a cold
engine that await is the whole model load plus the prefill.

**▶ AND `Request.is_disconnected()` CANNOT BE CALLED FROM A RAW
`asyncio.Task`.** It peeks inside an already-cancelled `anyio.CancelScope`,
which only behaves inside anyio's own task tree, so the first version **wedged**
the driver's entire suite under `TestClient` — whose receive blocks until the
response completes. One blocking `receive()`, the way Starlette's own
`listen_for_disconnect` does it, is the answer; it is also 250× faster because
nothing polls. Both repos now assert *an ordinary request still returns*, which
nothing had.

**▶ AND THE FIRST SABOTAGE PASS FOUND THREE CHECKS THAT COULD NOT FAIL — the
most useful hour in the slice.** (a) `r25-stalled` had **one** backend, so *the
second replica was never asked to recompute* was an assertion about a model with
nowhere to cascade to; it is two `modelSlots` now, and check 6 turned from *some
error code* into *the dead backend cascades and the backup serves it*, which is
the pair that tells the fix from the over-correction. (b) **A socket also closes
when a deadline fires**, so *did the engine's socket close* was satisfied by the
driver's own 12 s timeout; the stub records `cut@<elapsed>` now and the check
requires it inside 5 s — measured at **2.3 s**. (c) A unit helper's own
`wait_for(..., 5)` hid the *abandon rather than cancel* sabotage, because the
deadline's cancellation did the cancelling for it and the route returned a
perfectly good 499 five seconds late. Two more escapes named **missing checks**
(no test fed the agent an unreadable companion config; the driver gate omitted
the file the wedge actually hangs on), and **one escapes on measurement and
still does**: never *awaiting* the cancelled task is belt-and-braces, since
`task.cancel()` alone closes the socket inside the live check's window. The
`await` stays — "fast enough on this box today" is not a guarantee and the cost
is one line — but nothing here can prove it load-bearing, which is better said
than covered by a check that would pass either way.

**And the premise under all of §6.2 #16 was measured rather than reasoned:** a
FastAPI endpoint on **uvicorn 0.52.4 is NOT cancelled when the client
disconnects** — a 30 s sleep against a killed `curl` reported `cancelled: false,
finished: false`. Without that, the live escapes could as easily have meant the
server already did this for us.

**Two instrument defects beyond those, both reporting a working product
as broken.** The driver's env prefix is `EUGENE_PLEXUS_DRIVER_`, not
`EUGENE_PLEXUS_INFERENCE_DRIVER_`, so the first execution drove a driver on its
own default port with a config it wrote itself. And a zero-length `send()`
**returns 0 without raising** on a closed Windows socket, so the stub engine
recorded every cancelled call as `finished`; a readable socket that peeks empty
is the portable probe.

*Findings: §6.2 #13, §6.2 #16. Size: M + M. Touches: `inference-driver`,
`gateway`, `agent`. The plan as written follows, kept because the corrections
above are only legible against it:*

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

### 3.6 R2.6 — Windows comes back by itself

**▶ BUILT 2026-09-18, AND ITS FIRST STEP CHANGED THE SLICE.**
`scripts/r26-acceptance.sh`, **25 PASS, zero failures, fifth execution**;
`scripts/r26-sabotage.py`, **26 sabotages, 25 caught** (one escape
expected, one unexpected that named a check which could not fail);
design [`windows-comes-back-by-itself.md`](windows-comes-back-by-itself.md);
record [`../acceptance/windows-service-run.md`](../acceptance/windows-service-run.md).
Contract `dfe6b67`, `agent` `51d1c8a`, `ui` `e98ed30` / dist `14f9073`,
the other three regen-only; **all six level and both installers
re-pinned**. Closes §6.2 #26. **R2 IS COMPLETE, ALL SIX SLICES.**

**Step one came back NO, and not for the reason step one gave.** A
LocalSystem service cannot open the live install's models — but the
share is **guest-open**, it is **Windows 11 that refuses the guest
fallback** (`EnableInsecureGuestLogons` is 0), the box is a **workgroup**
member with no machine account, and the only thing bridging the gap is a
Credential Manager entry in one person's profile. `WinError 1272`, and
`WNetAddConnection2W` answers 1272 with no credentials and with bad ones
alike. So the conditional below fired and the slice became a credential
slice: `shareCredentials`, per node beside `pathMappings`, sealed with
the install's master key, one row per **server** because Windows refuses
a second credential to a server it already has a session with (1219).

**And the service loses FOUR per-user things, of which the roadmap named
one.** Name the pattern: *a LocalSystem service has none of the user's
secrets, and this install keeps three of them in the user's profile* —
the config-file variable (User scope; without it the service **raises a
second install**), the master key (sealed once after a migration,
re-sealed by the next sign-in), and the SMB credential. Drive letters
are the fourth and were already handled.

**▶ STEP THREE CAME BACK YES, AND REFUNDS A COST ACCEPTED ON 2026-09-11.**
`install-paths` §7 ruled out a service with `AllocConsole()` because
*"logs vanish"*. **Asserted, never measured, and false**: after
`FreeConsole()` + `AllocConsole()` a child is signalled in 0.036 s
against 0.034 s with an inherited console, and the file handler keeps
writing. That table row is corrected in place. The one thing session 1
cannot answer is `AllocConsole()` in **session 0**, which is check 2 of
six owed to an elevated run.

**Two live defects found by reading, neither on the roadmap.** The
three-second wait in both restart branches **does not exist** —
`timeout /t 3` exits rc 125 in 0.18 s under `stdin=DEVNULL`, which is
what `spawn_restart` passes, and this is live on `logon_task` today. The
tempting fix is worse: `powershell.exe` under `DETACHED_PROCESS` exits
in 0.05 s having run nothing, **successfully**, so `Restart-Service`
would have been a silent no-op that still reported success. And
`-Detect` closed the operator's terminal, against the rule stated forty
lines above the line that broke it.

**On Troy's ask, a notification-area icon** — turn Eugene off to play a
game, back on afterwards. Session 0 isolation forbids a service drawing
on a desktop, so the per-user logon task this slice takes away from the
agent **does not disappear, it changes job**. It drives the SCM and
holds no Eugene credential at all.

**NOT DONE, and it is the *Done when*:** a service registered, a reboot
with nobody signed in, session-0 `AllocConsole`, the master key in
SYSTEM's store, a real share opened by LocalSystem, and a tray click
with no UAC prompt. Six checks, printed by `install.ps1 -Verify`, all
needing Administrator. **Linux and macOS have the identical defect**
(a `--user` systemd unit and a launchd agent, both dead until login) and
are named rather than fixed.

*Finding: §6.2 #26. Size: L. Touches: `specs/scripts`, `agent`, `ui`,
`specs/docs/deployment`. **Depends on R2.2's #10** — the service runs as
LocalSystem and #10 is where the SYSTEM-profile home and the
strands-the-first-install trap are fixed. Nothing here starts before that.*

**Decision #4, taken 2026-09-18 (Troy): the real Windows service, and it is the
default.** The promise is the requirement. A self-hosted server that only
survives a reboot if somebody logs in is not one, and the wizard already says so
in as many words.

**This is not new ground.** `install-paths-and-distribution.md` decision #4
(2026-09-11) already committed to a service as a *supported surface* and
accepted its cost: no console, so `GenerateConsoleCtrlEvent` fails with
WinError 6 and engines are hard-killed rather than asked to stop. What changes
here is that it becomes what an ordinary Windows install **gets**, rather than
what an elevated one gets.

**What the slice has to answer, in order, and the first is a measurement.**

1. **Can a LocalSystem service open this install's models?** The live worker
   reads `\\192.168.16.252\downloads\models` through the inherited Library
   folder mount. A service authenticates to SMB as the **machine account**, not
   as Troy, so an authenticated share is a different question from a drive
   letter — and the drive letter is gone either way, which `container.md`'s
   Windows row already states. **Measure it against the real share before
   writing anything**, because if the answer is no, the slice is about
   credentials rather than about a service. Mirrors R4's rule: the premise gets
   captured, not reasoned about.
2. **What happens to installs that already exist.** Every per-user install on
   this box and on anyone else's is a logon task under `%LOCALAPPDATA%`, with a
   keyring entry scoped to that install's salt and, on the live one, an
   enrolled node identity. R2.2's #10 gives the discriminators; this slice
   gives the **migration**, and "the elevated run silently unregisters the
   per-user task" is the behaviour #10 is removing, not a migration.
3. **The graceful stop, which is really about engines.** A service has no
   console. Measured at step 2 of install-paths: a real `llama-server` holding
   a 1.8 GB GGUF exits **0.21 s** after `CTRL_BREAK_EVENT`, and a hard kill
   skips its ASGI lifespan shutdown. The agent supervises the engines, so the
   question is whether the *agent* can keep a console the engines inherit while
   itself running as a service — unmeasured, and worth one experiment before
   accepting the loss a second time.
4. **`NodeReach.restart.detail` gets rendered.** The agent already puts the
   supervising mechanism on the wire and **no screen prints it**; the fixture
   for it is sitting unasserted in a page test, which is the wiring lesson
   again. With a service the Reach card can offer a restart that actually
   works, and say what is starting this agent when it cannot.
5. **`reach.py`'s detection follows the mechanism.** §6.3 #34's COM fix (read
   `Schedule.Service` rather than decoding `schtasks` output as UTF-8) stays in
   R2.2; the service adds a second thing to detect, and `sys.prefix` stays the
   discriminator that stops a throwaway agent claiming the live install's
   supervisor — the S5 run's most dangerous note.

**Done when:** a Windows box with nobody logged in reboots and serves a
completion; an existing per-user install is migrated rather than stranded; and
the wizard's sentence is true without having been edited.

---

## 4. R3 — the correctness-and-contract pass

One slice per seam, in this order. Everything here is real and none of it is
reachable on a golden path in the first hour.

1. **§6.2 #21 — the thinking filter swallows the whole answer. ▶ DONE
   2026-09-19** (`inference-driver` `fd373e8`, both installers re-pinned;
   `scripts/r31-sabotage.py` 12 of 12). **The two halves disagreed about what
   a thinking tag is**: batch matched `<think…` so `<thinking>` was ordinary
   text, while streaming matched a bare `<think` and then waited for a literal
   `</think>` that `</thinking>` never provides. Both know both spellings now,
   the close must match the name that opened it, and the name is read to its
   end before anything is decided. **One decision rather than a detail: an
   unterminated opening tag is stripped on both paths** — what follows it is
   reasoning, and it is also the only way the two paths can agree at all.
   **Three sabotages escaped first and all three named a MISSING CASE**, not a
   weak fix. 208 cases at seven chunkings. Originally: Reproduced by
   execution: `<thinking>secret plan</thinking>The answer is 4.` streams as `''`
   at every chunking while the batch stripper keeps everything, because the
   streaming open match has no word boundary and the close match is a literal
   `</think>`. With `thinkingMode: off` a Claude-distill fine-tune streams an
   **empty 200** — the only finding on the list that returns a wrong answer
   rather than an error. It needs no hardware and the fix is S. The docstring
   claims the invariant is tested and **there is no test file at all**: the
   reverse of this project's usual failure, a prose claim of coverage standing
   in for the test.
2. **§6.2 #19 — admission reserves nothing. ▶ DONE 2026-09-19** (specs
   `b4a0a1d` — `Admission.reservedBytes`, a contract change after all; `agent`
   `01f6aad`, `control` `67f18e9` regen-only, `ui` `56ff7ea` / dist `afc1b2f`;
   **both installers re-pinned**; `scripts/r32-sabotage.py` 22 of 22; 864 agent
   tests). `reservations.py` is the ledger: an intended allocation recorded when
   a launch is scheduled, subtracted from free memory by the next caller, and
   released by one sweep at every read. The device pick is by free-minus-reserved
   too, or a second launch lands on the card that only looks empty. The
   context-blind fallback became the library's own estimate, duplicated rather
   than shared, so the two cannot disagree silently.

   **The three rules the finding did not carry all held, and one grew a
   qualifier.** A dry run reserves nothing; `copying` reserves before any
   process exists, and it was not even on the blocker list because `_RUNNING`
   had no member for a runtime with nothing to observe; the TTL is the backstop.
   The qualifier is **`force`**: it overrides the verdict, not the arithmetic, so
   create and start now measure under `force` as well and simply do not raise —
   without which a forced launch was invisible to the next admission.

   **The sabotage pass deleted three second mechanisms**, each of which escaped
   because something else already covered it: explicit releases on stop and
   delete (the sweep runs at every read and both routes change the status it
   reads) and a default context inside `file_size_requirement` (its one caller
   settles on a number first). **And two checks written in the first pass could
   not fail** — a dry run asked twice about the same spec cannot see a reserving
   dry run, since a runtime's own promise is never counted against it, and a
   20 GiB model on a 24 GiB card is refused whatever the ledger says.

   **Recorded, not fixed:** the reservation is counted in full for the whole of
   a load, so the total is high by up to the model's own size while the weights
   are being read — the refusing direction, and the alternative needs a
   per-engine load-progress number S7 established does not exist. **And boot
   reserves nothing**: `app.py` starts every declared runtime without consulting
   admission, which predates this and is unchanged by it.

   Originally: Two launches in quick succession
   both read the same free memory and both `fits`; the node-local copy widened
   that window from seconds to minutes by adding a `copying` state before any
   process exists. And the file-size fallback is context-blind: an 8B Q4 at
   128k needs ~17 GB of KV and is admitted at 5.5 GB.

   **▶ SCOPED 2026-09-19 — read this before opening it.** The
   mechanism is narrower and the fix is wider than the sentence above reads.
   `check_admission` already takes `running`, which looks like it accounts for
   other runtimes and **does not**: `_blockers` (`admission.py:411`) uses it
   only to build an advisory *list of what else is on the device*, and nothing
   subtracts it from anything. The fit arithmetic reads **live free memory off
   the `DeviceSnapshot`**, so a runtime that is declared, admitted and
   `starting` — or `copying`, which the node-local copy made minutes long —
   holds no memory yet, free memory still reads high, and the second admission
   says `fits` for memory the first one has already spent.

   So the fix is a **reservation ledger on the agent**, not a change to the
   arithmetic: an intended allocation recorded at admission, subtracted from
   available memory by the next caller, released when the process is observed
   holding the memory, when the launch fails, or on a TTL. Three rules that
   ledger needs and none of them are in the finding: **a dry run must not
   reserve** (`POST /v1/runtimes/admission` and `?force=true` share the path
   with a real launch, and `routes/runtimes.py:284` is the only call site, so
   the two are told apart there or not at all); **`copying` needs a reservation
   before any process exists**; and an abandoned launch must not strand memory
   forever, which is what the TTL is for and what makes it testable.

   The context-blind fallback is the small half, is independent of the ledger,
   and can land first. **Estimated too large for a short session — its own
   slice, with its own sabotage pass.** (Both halves landed in one session; the
   estimate was right about the shape and wrong about the size.)
3. **§6.2 #20 — `tier` is still renumbered for the natural slot shape. ▶ DONE
   2026-09-19** (specs `53428fa`, contract prose only; `gateway` `1fb5fa2`;
   **both installers re-pinned**; `ui` regenerated, JSDoc-only, reverted rather
   than re-pinned; `scripts/r33-sabotage.py` 8 of 8; record
   [`../acceptance/primary-still-a-primary-run.md`](../acceptance/primary-still-a-primary-run.md)).
   **The discriminator was already on the snapshot and nothing was reading
   it**: `_Snapshot.runtimes` is what every node DECLARES, independent of what
   is advertising anything this instant, so `_declares_runtime` asks that and
   not `by_model` — whose being empty is the condition under test. By alias OR
   by name, because `modelAlias` is optional, and **over-matching is the safe
   direction because this decides a label and never an order.**

   **The two sabotage entries that carry it are the finding and the
   OVER-correction**, since this defect has already been fixed once in the
   wrong direction: a check set that cannot fail *always keep* would pass the
   same bug facing the other way. One escape, and it named a missing check —
   narrowing the question to this node escaped everything, because no test put
   the primary on another machine, which is the install R1.6 exists for.

   **▶ AND THE FIXTURE WAS BUILDING A SNAPSHOT NO INSTALL CAN PRODUCE.**
   `install_snapshot` still keyed `runtimes` by bare name three weeks after
   R1.6 moved production to `(node, name)`, so it married a driver on one node
   to a runtime on another — the exact cross-node join R1.6 removed — and
   `test_the_routing_view_opens_the_table_up` was asserting that marriage.
   R1.6's own lesson, one fixture over. **And the contract said the opposite of
   the code:** `ModelRoutingInfo.tiers` had read *"Empty tiers are omitted"*
   since nine days after the 2026-09-10 fix made that untrue.

   Originally: A
   surviving second case rather than a regression: the 2026-09-10 fix's own
   recorded carve-out is correct for a virtual alias and wrong for
   `{model: <a real local model>, targets: [cloud]}`, and the two are
   distinguishable. Until it is fixed, `GET /v1/metrics` cannot tell *primary
   served* from *primary was dead at refresh*, which is the one question tiered
   failover exists to answer.
4. **§6.2 #22 — contract drift on the request path. ▶ THE CODE HALF IS DONE
   2026-09-19; THE PROFILE SENTENCE STANDS** (specs `031d90a`, a contract change
   — `GenerateRequest.topP`/`.seed` and `FinishReason.content_filter`, plus the
   two doors' enums; `gateway` `bb67692`, `inference-driver` `499836c`; **both
   installers re-pinned**; `ui` regenerated and **deliberately not re-pinned**;
   `scripts/r34-sabotage.py` **24 of 24 across two repos**; record
   [`../acceptance/contract-drift-run.md`](../acceptance/contract-drift-run.md)).

   **Three sentences made true and the fourth left standing on purpose.**
   `top_p` and `seed` had no field to land in, so the gateway accepted both,
   range-validated both and dropped both with nothing logged; `content_filter`
   was folded into the driver's `error` and flattened to `stop`, so a refusal
   arrived as a natural end; and a driver 401 — the gateway's OWN credential
   refused, which is what clock skew produced live on 2026-09-15 — was reported
   as `invalid_request_error`, sending a harness to re-read a prompt that never
   had a problem. It is 502 `upstream_auth_error` now, naming the driver and its
   URL, **and the non-cascade rule is asserted rather than assumed**: changing
   what we say about a 401 must not change what we do with it.

   **Each door renders the refusal in its own vendor's vocabulary** —
   `content_filter` for OpenAI, `refusal` for Anthropic — so neither is
   invented; the Anthropic half is marked unverified against a live SDK, which
   R4's own capture instrument could settle. `error` still reports `stop` and
   `end_turn`, and **that pair is what tells the fix from the over-correction**.

   **Two guards carry more than they look:** `seed=0` is a real seed and is
   falsy, so a truthiness check would have preserved the bug inside its own fix;
   and `top_p` is dropped by the same flag as `temperature` and only that flag,
   because OpenAI's reasoning models reject the sampler and accept the seed.

   **Two sabotages escaped.** One was a no-op — R2.4's mistake again, an
   assignment inside a branch that had already returned. The other named a
   hole the obvious diagnosis missed: after the test's one-character driver name
   was fixed it STILL escaped, because `str(DriverError)` carries the name and
   URL, so the belt-and-braces path was doing the work. Naming the driver is
   load-bearing only when the driver sent a real `problem+json` body, and that
   is a test now.

   **The profile sentence is UNMET and stays that way** (Troy, 2026-09-19).
   `ModelProfile` does carry `temperature` and `topP`, so it is meetable in
   code; what it costs is a gateway→library edge with a cache and its own
   failure modes, which is its own slice before the release. Originally, and
   left here because the split is the decision: `top_p` and `seed` are accepted
   and never forwarded (the contract promises pass-through or a warning and there is
   neither field nor warning); `max_tokens`/`temperature` come from
   gateway-wide defaults while the contract says *the model's settings profile*
   and the word "profile" occurs in gateway source only inside docstrings
   regenerated from that sentence; `content_filter` becomes `stop`, so a
   filtered answer reads as a natural end — **the same map, the next value,
   after `tool_calls` → `stop` was fixed at step 6**; and a driver 401 is
   reported to the caller as `invalid_request_error`, which is the shape a
   rotated service token takes on one node and is unfixable by the caller.
   **▶ THE RECOMMENDATION'S PREMISE WAS FALSE, AND THE CALL CHANGED
   (2026-09-19, Troy).** It said *"no per-model output store exists to point
   at, so the promise cannot be met by editing code"*. There is one:
   `ModelProfile` carries `temperature` and `topP` and the library serves
   `GET /v1/models/{id}/profiles`. The promise **is** meetable in code; what it
   costs is a gateway→library dependency edge that does not exist today, with a
   cache and its own failure modes, inside what was scoped as a correctness
   pass.

   **TAKEN: SPLIT IT, KEEP THE TARGET.** Fix `top_p`/`seed` here — they are
   accepted and silently dropped, which is pure code and needs no new edge.
   **Leave the profile sentence standing as an unmet promise** rather than
   softening it, and schedule the gateway→library profile read as its own slice
   before the release. Editing the contract to match the weaker mechanism would
   move the gate instead of reaching it (Troy, 2026-09-18), and *a correct
   sequencing argument is not an argument for a smaller outcome*.

   **Fix the code for the last two.** The 401 half is locked in by a passing
   test that uses 401 specifically, so that test is amended, not added to.
5. **§6.2 #27 — symlinks, and a shipped config field nothing reads.**
   **BUILT, VERIFIED AND PUBLISHED 2026-09-20.** Library `127c70c`,
   both installers re-pinned; archive resolves and library CI is green
   (run `35517442527`). No contract or UI change.
   Record: [`../acceptance/symlink-scanning-run.md`](../acceptance/symlink-scanning-run.md).
   `scripts/r35-acceptance.py`: **10 PASS on Linux symlinks and 10 PASS on
   Windows junctions**, including a real process restart. The copied-checkout
   sabotage gate catches **12/12 on Linux and 11/11 on Windows**; both restored
   baselines pass. Full library suites: **471 passed / 21 skipped Linux;
   468 passed / 24 skipped Windows**.

   The config value is now read for each scan. Directory symlinks and Windows
   junctions obey it; explicit roots still scan. **File links are always read**,
   including the links in a real HF-shaped snapshot. Directory identity is
   checked against **ancestors, not a global visited set**: cycles stop and are
   reported, while two named aliases keep their distinct path-derived IDs.
   A file-link inspection error no longer discards healthy sibling files.
   The runtime config description and timeout advice now match that behavior.

   Specs `93838cd`; CI `35519608405` and container workflow `35519608389`
   both passed. No service or live-install change was made.
   Native Windows symlinks require privileges this session lacks;
   junctions ran without elevation, and real symlinks ran in WSL Python 3.12.

   **As found:** the review understated it: `followSymlinks` had exactly one occurrence in the
   library's whole source tree, its own declaration, and the scan-timeout
   message advises the operator about that switch **by name**. A UI without a
   tunable behind it is `gui-equality-for-configurable-things` violated in the
   harder direction.
6. **§6.3 #37 — five respawns of an engine that dies during load**, which on a
   remote mount is up to five full 23.8 GB reads. Make the back-off aware of
   observed uptime rather than only of the crash count.

   **COMMITTED AND PUBLISHED 2026-09-20.** Contract `f545c2c`, agent `159ec39`,
   both installers re-pinned; the agent archive resolves. Only the agent's
   specs pin moved: the other consumers' R3.6 differences are docstrings only
   or byte-identical, measured by regeneration in temporary output directories.
   Record: [`../acceptance/engine-load-recovery-run.md`](../acceptance/engine-load-recovery-run.md).
   The reproduction counted **five actual spawn calls** for one failed load.
   A non-zero exit before this process has been observed ready now stops
   automatic retries, retaining the failure and naming Restart as the remedy.
   After readiness the existing bounded back-off remains; **60 seconds of
   continuously observed readiness resets crash history**, never time loading.
   Manual Restart now restarts an ended supervision task. Components retain
   their existing safe-mode recovery. Late readiness probes cannot credit a
   replacement process with the old process's success.

   `scripts/r36-acceptance.py`: **6 PASS each on Windows and Linux**, real
   agent API and child processes, no GPU or live install. Copied-checkout
   sabotage: **15/15 each platform**, restored baselines green. Windows full
   suite: **876 passed, 3 skipped**, after final regeneration (the
   final runtime file passes **14 tests**). Linux Python 3.12 full suite:
   **857 passed, 17 skipped, 5 failed**; those exact five also fail against
   an untouched archive of agent HEAD (two missing-sibling-package seeding
   tests, three Windows-assuming tests). They were not changed here.

   Contract prose only, no wire fields or enum
   members. Agent CI `35521633539` is tracked against the already failing Linux
   baseline; see the record for the five reproduced failures and harness limits.
7. **§6.2 #28's Apple half** — a Rosetta terminal produces an x86_64
   interpreter, after which Metal is never chosen and a Mac is scored CPU-only.
   Confirmed in code, unverifiable without a Mac, and the review's citation for
   *where* the x86_64 Python comes from is wrong (it is uv's own bootstrap plus
   `--python-preference only-managed`, not the installer's arch validation).

   **IMPLEMENTED 2026-09-20; physical Mac verification remains owed.** Both
   POSIX setup scripts request native ARM Python on Apple Silicon, including
   from Rosetta, and verify existing and newly created interpreters before
   package installation. Incompatible environments are preserved with recovery
   instructions; bootstrap keeps explicit interpreter overrides. **88 simulated
   checks and 13/13 sabotages pass**, with the original revision failing the
   behavior gate and R2.2's POSIX suite still green. CI runs the new gate.
   Record and remaining hardware steps:
   [`../acceptance/native-apple-python-run.md`](../acceptance/native-apple-python-run.md).
   Specs `a2b1a27`; CI `35523142047` and container workflow `35523142053`
   passed. Mac verification is still pending; the independent contract sweep
   is recorded below.
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

   **COMMITTED AND PUBLISHED 2026-09-20.** Contract `239fb04`; regenerated
   agent `99501e4`, control `b192481`, gateway `dfdf5df`, library `b3ad977`,
   inference-driver `cf5307c`. Both installers re-pinned. Regeneration from
   both revisions matched the old committed output before comparing the new;
   the UI's R3.8 difference is comments only, so its pin and dist stay put.
   Eight stale claims reproduced by `scripts/r38-contract-checks.py`, now
   corrected. The shared enum includes the control root's `passphrase_file`
   mode while explicitly retaining the agent's supported subset. Runtime
   identity is (node, name); local fits can still be estimates; historical
   overhead is identified as fixed by R1.1. Tier semantics were already
   corrected by R3.3. All **175 non-generated Python source files** across
   five consumers pass the duration-clock sweep; no remaining call needed
   replacement. **11/11 in-memory sabotages caught**. Both OpenAPI validators
   pass (one existing unused `StreamToken` warning).
   **231 focused consumer tests pass**, and all five mypy checks pass.
   Post-push CI exposed six environment-dependent tests: the agent's five
   recorded Linux failures and a driver check that required the real Claude
   CLI. Fixtures now supply their required facts without weakening assertions
   (agent `52c1109`, driver `5c9e3c6`, the final installer pins). Full Linux
   suites pass: **862/17 skipped agent, 407/3 skipped driver**.
   Specs CI `35523277582` passed. Record:
   [`../acceptance/contract-sweep-run.md`](../acceptance/contract-sweep-run.md).
   **Pickup: R6, section 7 — outstanding S10 download timing and moderated-session evidence.** S9 shipped on 2026-09-20 (UI `94d0ce3`, dist `5306208`): 430px real reply, 390px layouts, focus and motion checks; see [`../acceptance/s9-phone-run.md`](../acceptance/s9-phone-run.md). S8 shipped the same day (UI `48488ad`, dist `ad6836f`). The profile benchmark button landed on 2026-09-20, as did R5, R7 and R8; R3's implementation work is complete; the
   outstanding physical Mac check remains under item 7.

---

## 5. R4 — Anthropic `/v1/messages`

**▶ DECISION #1 IS TAKEN (Troy, 2026-09-18): THIS GOES IN FRONT OF THE
RELEASE.** R4 runs alongside R2, after R1. It is no longer a candidate feature
competing with eleven High defects; it is scheduled work, and calling **#8**
(*one endpoint for every tool you use*) is written down as **not true until it
lands** — see `local-inference-control-plane.md` §2.

*Scoped against the code, not reasoned: two slices of about a day, one contract
change, radius `gateway` + `ui`.*

**▶ STEP ONE IS DONE, 2026-09-19, AND IT MOVED A FIELD FROM THE REFUSAL LIST TO
THE DROP LIST.** Record:
[`../acceptance/anthropic-messages-measurement.md`](../acceptance/anthropic-messages-measurement.md);
instrument `scripts/r4-capture.py`, kept, because this wire will change under
us. Nine runs against Claude Code `2.1.207` — three credential paths, a tool
loop, seven HTTP statuses. **The premise held and four things beside it did
not**, two of which would have failed the shim on its first real request. What
follows is corrected in place; §5 of the record is the list.

**The blocker, now measured rather than reasoned.** Claude Code with
`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` sends **`x-api-key`** — and sends
**no `Authorization` header at all**, which is stronger than "prefers the wrong
one": the gateway's `HTTPBearer` sees no credential whatsoever and refuses.
`ANTHROPIC_AUTH_TOKEN` sends `Authorization: Bearer` and **no `x-api-key`**, so
the two are disjoint alternatives rather than a fallback order. **The recipe
names `ANTHROPIC_AUTH_TOKEN` first**, for two reasons the measurement found:
`ANTHROPIC_API_KEY` alone answers *"Not logged in · Please run /login"* in a
fresh profile until the key is approved (its last 20 characters land in
`customApiKeyResponses.approved`), and **an ambient subscription login silently
beats it** — the first capture recorded the operator's real
`sk-ant-oat01-…` OAuth token arriving at a loopback listener while the client
key went unused. A user who follows a recipe written the other way round sends
their Anthropic token to their own gateway and is told their key is wrong.

**And the status table is not the obvious one.** Measured by answering each
status and counting what the client did next: **400 is surfaced verbatim and
never retried; 403 is surfaced verbatim and never retried; 401 is retried
without bound** (nine attempts in 79 s, still climbing when the run timed out)
**and shows the user nothing**; 404 is retried twice and **our message is
discarded** for a generic one blaming the model; 429/500/503 are retried and
silent. `X-Stainless-Retry-Count` stayed `0` on every retry, so it cannot be
used to detect a storm. Therefore **a bad or revoked client key on this door is
403, not 401** — a deliberate divergence from every other route in this
project, which must be said in the contract or it will be "fixed" back — and
**a model nothing serves is 400, not 404**, or the sealed-control-root
explanation is thrown away by the client.

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
with a 400 naming the field: image and document blocks, server-side tools,
`mcp_servers`, more than four `stop_sequences`, and a missing `max_tokens`.
**Dropped silently, and this one is load-bearing:** `cache_control` — which the
measurement found on **three** blocks and not only the system ones: system
blocks 1 and 2, the last user content block, **and `tool_result`** — so a
blanket unknown-field refusal would pass every refusal test and then fail the
acceptance run on its first request. `top_k` is dropped and documented as a
real loss (both engines take it and neither contract has it), which is the same
omission `top_p` and `seed` already have.

**▶ AND `thinking` MOVED FROM THE FIRST LIST TO THE SECOND, WHICH IS THE
MEASUREMENT'S HEADLINE.** It is sent on **every** request, and its shape depends
on the model id: a known Claude id gives
`{"budget_tokens": 31999, "type": "enabled"}`, **an arbitrary local id — which
is the whole point of this door — gives `{"type": "adaptive"}`**, and
`MAX_THINKING_TOKENS=0` gives **`thinking: null`, the key still present**. So
refusing the field 400s everybody on request one, and a bare presence check
refuses the one configuration genuinely asking for no thinking. It is dropped,
and dropping it is honest rather than lossy: `ThinkingFilter` and the profile's
`thinkingMode` already own a local model's thinking behaviour, so this is ours
to decide and not the caller's. Document it beside `top_k`.

**Three more shape facts the scope did not carry.** The path is
`POST /v1/messages?beta=true` — **a query parameter on every request**, which
must not break routing, and the `anthropic-beta` list must be tolerated rather
than validated. **`stream` is `true` on every request Claude Code makes**, so
the non-streaming path is real, is not covered by this client, and the
acceptance run must not assume otherwise. And **an assistant turn comes back to
us carrying `tool_use` blocks**, so the translator needs an inbound
assistant→`tool_calls` mapping as well as the outbound one; a `tool_result` is a
block inside a **`user`** message, several to a message, not a role of its own.
A `HEAD /` probe from `Bun/1.4.0` precedes the first POST and **is not
load-bearing** — a run that answered it 404 completed normally.

**One piece of the hard half is already answered by a real client.** The
measurement's tool-loop run had the listener emit a streamed, fragmented
`tool_use` — text at block index 0, the tool at index 1, `input_json_delta` in
two pieces, `stop_reason: "tool_use"` — and Claude Code parsed it, ran the tool
and completed the loop. That is a worked reference for the stateful block
indexing above, taken from the strict SDK rather than from the docs.

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

**▶ THE DOOR IS BUILT AND THE LOOP COMPLETES (2026-09-19).** `specs`
`eb05ec7`, `gateway` `26109b3`; 44 new tests, 347 green, mypy and ruff clean.
Record: [`../acceptance/anthropic-messages-run.md`](../acceptance/anthropic-messages-run.md).
A real Claude Code with `--model local-qwen --allowedTools Glob` called a tool
through the real gateway and read the result back, asserted from the driver's
own record: the backend received exactly `maxTokens`, `messages`, `temperature`
and `tools`, so the dropped fields demonstrably never arrived, and
`GET /v1/metrics` carries three rows for that model — the shared-path claim
proved rather than stated.

**And the live run found a sixth shape the capture could not have.** Claude
Code sends a **`system`-role message inside `messages`**, 8 KB of it, after the
first user turn, *in addition to* the documented top-level `system` — and
Anthropic documents two message roles. The first execution was refused on its
own first request with `messages.1.role: Input should be 'user' or
'assistant'`. **43 green unit tests did not see it**, for an exact reason: every
fixture was built from step one's capture of a *simple* request, and this shape
appears only once tools are in play. Fixed in the contract, after which the
translation needed no change — the argument for putting a measured shape in the
schema rather than in a guard.

**What R4 still owes is its second half:** the eighth recipe in the UI, the
comment and the test that assert Claude Code's absence inverted, `dist` rebuilt
and both installers re-pinned. Until that lands the door exists and nothing
tells anybody how to use it. Plus what §3 of the record names: no real engine
behind it, no second client, the refusals unit-tested only, and no browser
preflight.

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
to CLAUDE.md and to the README's hybrid. **R5 completed the two remaining
surfaces on 2026-09-20:** Home's copy in `ui`, and the website, in separate
commits and with a rebuilt installable UI.

**COMPLETED 2026-09-20.** Website `0fd2e83` had already adopted most of the
positioning and removed the false no-copy claim. R5 finishes that work in
website `4ebd94a`: engine setup leads, model settings reflect R8, trust copy
reflects R7's completed verification split and explicit legacy rotation, and
Windows service verification is described at its actual boundary. UI
`fa69ae6` explains machine-specific starting settings and downloads into the
operator's own folders, names existing subscriptions, and includes Claude Code
alongside OpenAI-compatible apps. Its rebuilt dist is `a04a5eb`, pinned by
both installers. Home retains its task order and one primary action per state;
the seven positioning lines are not an extra marketing panel in the console.

The website's newer 2026-09-20 editorial decision removed the standalone
numbers showcase. R5 preserves that decision and publishes the observations
as a linked [technical measurement record](../acceptance/control-plane-measurements.md),
with setups and limitations. **172 ms was a completion after the dead replica
had already been excluded, not measured cascade latency; 21 s was a warm-cache
local start, and copying cost time on the first start.** The streaming figures
test non-buffering, not proxy speedup. No new performance measurement or
competitor comparison is claimed. The context-depth instrument remains R6.
Record: [R5 positioning acceptance](../acceptance/r5-positioning-run.md).

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
stranger reads first. **Completed in R5:** the remaining Home and website copy.

**The original measurement-publication scope, corrected by the record above.** The review's §3 notes
that **nobody in this field publishes the numbers that describe THIS layer**,
and we already have them measured: **failover around a killed replica in
172 ms**, **wake on demand in 2.5 s**, **time-to-first-token through two
proxies at 5-6.8 % of the request against 12.9 % direct**, and **a 24 GB model
serving in 21 s from a local copy against 266 s over SMB**. Publish those.
**tok/s is the engine's number, not ours** — and PolyServe's numbers are not
comparable to anything a hobbyist does, so borrow its method and never its
benchmark. **The one number that is ours to publish and is not yet measurable
by a user is the depth curve**, which is why decision #6 put the benchmark
button in front of the release rather than behind it: R6 item 1 builds the
instrument, and what it produces — *decode at the context you chose is a third
of decode at zero* — is a claim about the reader's own machine that nobody
else in this field offers to make.

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

**Original publication prerequisites (R1.2, R1.3, R1.6 and R4 have now landed):**
the fit claim (R1.3), the replica claim (R1.6), and the file-ownership card
(R1.2's download confinement). They are the first three things a reviewer
tests. Two site claims were outright false when this scope was written — *"gives
every tool you use one address to talk to"* with a `Coding agents` chip, which
R4 is what makes true, and *"never copied, never renamed"*, which our own
node-local copy falsified the same day it shipped (the replacement line exists:
*we manage what we made and never touch what you put there*).

---

## 7. R6 — the hobbyist remainder

**Item 1 completed 2026-09-20.** Saved llama.cpp profiles have **Benchmark** on
the selected node: three context depths, sample controls, progress, cancellation,
curve/table, recorded settings and history. Agent-owned work survives navigation;
the task tray discovers it across nodes. Managed models must be stopped first;
benchmark admission and model starts are serialized, including gateway wake.
Agent `c0b7f67`, UI source `ba235fd`, UI dist `1669119`, control codegen `612c56b`;
both installers pinned. Design: [`profile-benchmark.md`](profile-benchmark.md).
Evidence: [`../acceptance/r6-profile-benchmark-run.md`](../acceptance/r6-profile-benchmark-run.md).
Real CPU-only llama-bench and packaged-browser checks passed without changing
the installed service or running GPU model. The phone screenshot exposes the
existing Library split-pane clipping at 390 px; that remains in the S9 pass
below, not a claim of mobile acceptance for this item.

**1. The benchmark button (decision #6, taken 2026-09-18).** It is here rather
than after the gate because the number it produces is **positioning**, not a
convenience: prediction answers *does it fit*, measurement answers *how fast is
it here*, and only the second is a claim about this machine that no competitor
makes. R5 is *no code*, so the surface lands in this stage and the claim it
yields belongs to R5's publish-the-numbers half.

**The expensive half needs no building.** `llama-bench` is already in the
engine store in both retained builds, is already a sweep engine, and its
`--progress` output is the tasks tray's fraction for free.

**▶ AND THE KNOB THE REVIEW NAMED IS THE WRONG ONE.** Measured on this box,
`gpuLayers` 0→99 is **7.2×** — but only on a partial offload, and a model that
fits is already at 99, so there is nothing there to learn. What is invisible is
**depth, the context axis: 3.4×**, at 902 / 678 / 262 tok/s for 0 / 4096 /
16384. The library prints *the largest context that fits is N* and **nothing in
the product says decode at N is a third of decode at zero** — so an operator
can pick 70k context and pay two thirds of their speed for it without being
told. That sentence is the feature.

**`llama-bench` has no `--parallel` and no `-c`**, so `parallelSlots` is not
measurable with that instrument at all — which matters because R1.3 has just
made the *arithmetic* about slots honest, and this cannot confirm it.

**Naming is a real constraint, not a preference.** Not **“Measure it”**:
hobbyist S10 already owns that name. *Benchmark* is the obvious candidate and
is the word this audience uses; it must clear S8's banned-word gate for
whichever screens it appears on, and the button sits on a settings profile
rather than on Home, which is the expert side of decision #12.

**And the standing rule this must not violate:** *prediction is a filter, never
the decision* — PolyServe's own predictor ranked the true winner 15th of 25.
A measured number replaces nothing the fit verdict does; it answers the next
question.

---

**S8 completed 2026-09-20.** Twelve local definitions under The system; per-component
Show more for three or more infrequently changed settings; unknown fields stay
visible. Wrapped JSX and shared golden-path components join the copy gate;
technical hints remain. Extracted copy scored Hemingway Grade 6. UI `48488ad`,
dist `ad6836f`, both installers pinned. [Acceptance](../acceptance/s8-vocabulary-run.md).
The operator also completed the 70,000-context RTX 5090 profile benchmark after
the projector-fit correction: 58.7 / 54.6 / 50.4 tokens/s at the three depths.

**The rest of R6.** S9's phone/focus/motion
pass, and the two items S10 still owes its own *Done when*: `EP_DOWNLOAD=1` for
the ten-minute target, and the moderated sessions, which are decision #14 and
gate the release.

**One concrete check the review names and nothing has ever run:** score the
starter set against **8 GB of VRAM with 16 GB of RAM**, the beginner thread's
OP. The existing context checks use a 24 GiB card and a 12 GiB one. Two rows
also belong in that plan's stuck-points table and have no home today — a
slow-but-healthy answer reported as a failure (§6.2 #13) and a component that
never came up (§6.1 #7).

---

## 8. Deliberately not scheduled

Each with the reason, so silence is not read as an oversight.

- ~~**The shared HS256 key (review §6.4).**~~ **SCHEDULED 2026-09-18 as §10
  R7** — decision #5 taken the other way. It stays listed here only so the
  reasoning that moved it is not lost: the recommendation was to withhold the
  key and constrain `binary`/`extraArgs` *without* splitting, and Troy took the
  split, before the release, on the grounds that releasing early and losing
  trust costs more than the slice does. The two recommended halves survive as
  R7's first step.
- ~~**A benchmark button on a profile.**~~ **SCHEDULED 2026-09-18 as R6 item 1**
  — decision #6 taken the other way. Kept here for the reasoning that moved it:
  the recommendation was *yes, but after the release gate*, and the
  counter-argument in the decision row is the one that held. Troy: *“it belongs
  in R5/R6 where the positioning is.”*
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
  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ ALL SIX DONE 2026-09-18
R2.1 → R2.2 → R2.3 → R2.4 → R2.5 → R2.6     before the first hostile review
  ^^^^^^^^^^^^^ ALL SIX DONE 2026-09-18 ^^^^^^^^^^^^
R4  (alongside R2)                            decision #1, TAKEN: in front
R3                                            the correctness pass
R7  (R2.6 landed first, so its migration is
     written once more when R7 moves the
     credential shape)                        decision #5, TAKEN: split the key
R8  the gateway reads the model's settings
     profile                                  split out of R3 item 4, 2026-09-19
R5  (no code; can land any time)
R6 → the release                              decision #13's gate, unchanged
```

**R1.1 first** because every other measurement is taken through its
instrument. **R1.4 before R2.1** because a leaked counter currently masks the
race — and it no longer does, so R2.1's idle-unload race is reachable now
rather than hypothetical. **R1.5 and R1.6 were taken last and out of R2's
way**, which cost nothing: neither touches a seam R2.1 through R2.4 had
already moved, and R1.6's live half reuses R2.1's stub-agent shape. **R2.2's #10 before R2.6**, which is the behaviour change to the Windows
autostart: the service runs as LocalSystem, and #10 is where that home
directory and the strands-the-first-install trap are fixed. Everything else is
independent.

**R8 is R3 item 4's other half, split out on 2026-09-19 and completed
2026-09-20.** The gateway promised profile defaults but substituted its own
install-wide settings. The earlier roadmap also confused `RecommendedSampling`
metadata with persisted profiles: `ModelProfile` did not yet contain those
generation fields. R8 adds optional `maxTokens`, `temperature`, and `topP` to
Library profiles, persistence, and the profile editor, then fulfills the
gateway promise. Troy's call, **split it, keep the target**, stands.

For every backend attempt, caller values take precedence over the model's
**default profile**, then gateway settings. Lookup follows the selected
node/driver's runtime `modelPath`, including cross-model fallback; aliases and
local-copy paths never identify Library models. Both API doors and streaming
use the resolver. Reads use the agent's authenticated Library proxy, a bounded
cache, configurable fresh/stale lifetimes, and bounded retry after failures.
Saved edits, default changes, and deletion take effect after cache refresh
without restarting a runtime. Launch templates retain copy-at-launch behavior.
Design: [model-generation-defaults.md](model-generation-defaults.md).

Contract `88a6f63`; gateway `aa24529`, Library `db66715`, UI source `d384ba2`,
packaged UI `11c0a72`. Both installers pin the published consumers; their CI
passes. Full suites: gateway **399** on each platform, Library **487/24 skipped
Windows and 490/21 skipped Linux**, UI **731**. Isolated real gateway/Library
process acceptance passes on Windows and Linux; **10/10 deliberate regressions
caught on each platform**, with restored baselines passing. CI retains both
gates. The isolated UI export, dist payload, and wheel match across all 184
assets. No running install or model configuration was changed for R8.
Record: [R8 profile defaults acceptance](../acceptance/r8-profile-defaults-run.md).

**The release gate is unchanged and this roadmap does not shorten it:** it is
`hobbyist-ux.md` **decision #13** (what gates it — S0-S6 and S10) plus
**decision #14** (three to five moderated sessions), with `EP_DOWNLOAD=1` and
the ten-minute target still unmeasured, a starter review under thirty days old
with no unresolved verdict, and the `dist` branch rebuilt from the pinned
commit. R1 and R2 sit in front of it. *(Both numbers are cited here because
four documents cite one or the other and disagree.)*

**▶ THERE IS NO ESTIMATE HERE, AND THAT IS DECISION #7 (Troy, 2026-09-18).**
This paragraph used to carry one — *two to three days for R1, about a week for
R1 and R2* — and it is deleted rather than revised, along with the R2.6
addendum written the same day. Troy: *“agents are notoriously bad at predicting
the passage of time and the length of time it takes to do things.”* He is
right, and the record here proves it from both sides: R1's six slices were
forecast at two to three days by the same reasoning that then had to add *“R2.6
is outside that estimate”* within a day of two decisions being taken. **A
roadmap that forecasts is a roadmap that will be wrong in public.** This one
says what the work is and what order it goes in, and nothing about when.

**So the release is not scheduled, it is decided afterwards.** Power through
the stages as they stand; when they are done, re-assess **where the project is
and where the competition is**, and make the call then. That re-assessment is
real work, not a formality: the market read this roadmap rests on was taken on
2026-09-17 and has a shelf life — llamactl released twice during the review
week, router mode landed inside the engine, and the beginner thread's answers
converged in ten days. Read the field again before deciding, rather than
deciding against a snapshot.

**Decisions #13 and #14 are untouched by this.** They say *what* gates the
release and *who* sees it first; #7 says only that nothing here predicts the
calendar.

---

## 10. R7 — the trust boundary

*Finding: review §6.4, the architectural note. Size: L, and it is a contract
change. Touches: all five components' `security.py`, `agent.yaml`,
`control.yaml`, `common.yaml`, enrollment and rotation.*

**Decision #5, taken 2026-09-18 (Troy): split the key, and before the release.**
*“I would rather release with things correct than release too early and lose
trust.”* The recommendation was the smaller answer — withhold the key from
processes that unseal nothing and constrain what a runtime may execute — and it
is now this slice's **first step** rather than its whole content.

**Do not relitigate the recorded decision that the install key lives in the
clear on each node** (`m7-second-host-readiness`). That is about *nodes* and it
needs no change. What this slice fixes is that the code extended it to **every
child process**: the agent spawns with `os.environ.copy()`, so the gateway, the
library, the control root and **every companion driver** hold the key that mints
operator sessions — and an operator token can declare a runtime with an
arbitrary `binary` and `extraArgs` on any node. The driver is the process whose
whole job is talking to a third-party backend, and it is the one holding an
admin credential it never uses.

**▶ THE CRUX, AND IT IS WHY THIS IS A DESIGN RATHER THAN AN EDIT: HS256 IS
SYMMETRIC, SO *CAN VERIFY* AND *CAN MINT* ARE THE SAME PERMISSION.** Every
component must verify the tokens it is handed; today that is spelled as every
component holding the secret that signs them. Withholding the key from a driver
is therefore not a matter of passing one less environment variable — the driver
verifies operator tokens for its own config trio. Two routes out, and the first
is recommended:

1. **Asymmetric signing (EdDSA / Ed25519).** The minters hold a private key and
   everyone else verifies with a public one, so *verify* stops implying *mint*.
   **The machinery is already in this install**: every node has an Ed25519
   keypair (M7's signed re-key, M9's signed address announcements), `cryptography`
   is already a dependency, and PyJWT speaks `EdDSA`. The split then falls out as
   **minters = agent + control** (an agent mints operator sessions at login,
   service tokens for its children and `aud: client` keys; the control root
   mints its own) and **verifiers = gateway, library, inference-driver**, which
   mint nothing at all. That is exactly “stop handing the master key to
   components that unseal nothing”, enforced by arithmetic rather than by
   convention.
2. **Per-audience symmetric keys.** Smaller crypto change, larger product
   change: a driver that cannot verify an operator token cannot serve its own
   config trio, so operator config would have to reach it through the agent's
   proxy. It also leaves every agent able to mint everything, which is most of
   the blast radius.

**The migration is the machinery this project already built.** An install
changing signing keys is a re-key: signed by the control identity, fenced by
epoch, with the node adopting the new material and restarting its children —
M7's path, exercised live at the two-host run. Trusted agents remain minters and
therefore still need private signing material; the **public-only** distribution
is from those agents to gateway, library and inference-driver children. A build
that must accept both algorithms during the change is the part to design
deliberately rather than discover. Do not confuse the master encryption key
(still needed by library and driver for stored credentials) with the private
token-signing key (needed only by minters).

**Steps, in order.**

1. **The two recommended halves first, because they are independent and
   valuable on their own**: stop passing the master key to processes that unseal
   nothing, and constrain `binary`/`extraArgs` to the engine store plus the
   operator's configured paths, with an explicit override
   (`easy-default-expert-override`). Neither is a contract change. Do them even
   if step 2 is deferred by circumstance.
   **Done 2026-09-20:** agent `64ea8b2`, inference-driver `e10896d`; both
   installers pin those commits. Component environments discard ambient
   credentials and reject reserved overrides; gateway receives no master key.
   Engines, discovery probes, and backend CLIs receive no Plexus namespace.
   Canonical binary containment and the explicit raw-argument override run at
   API validation and again before any launch-time probe. Config exposes
   `engineBinaryRoots` and `allowUnrestrictedEngineLaunch` through the existing
   UI. Existing custom binaries/raw arguments require those approvals at their
   next launch; default managed/PATH/configured engines keep working.
   Windows and Linux checks, real harmless children, and **15/15 sabotage
   catches on each platform** are recorded in
   [`../acceptance/r7-launch-boundary-run.md`](../acceptance/r7-launch-boundary-run.md).
   Steps 2–4 below complete the asymmetric boundary; environment filtering
   alone did not satisfy the final acceptance.
2. **The contract**: what `alg` the install signs with, what enrollment hands a
   node, what rotation moves, and the token descriptions in all four documents.
   Radius measured by regenerating all six consumers, as always.
3. **The five `security.py` copies**, which are five copies on purpose —
   components share schemas, not code.
4. **Rotation across the change**, and the acceptance run that proves an
   existing install survives it.

   **Steps 2–4 done 2026-09-20:** contract `4b5d80a`; agent `c5ad280`,
   control `5cd8733`, gateway `e232fce`, library `337c987`, driver `4dc12fe`.
   New installs and explicit rotations use Ed25519; existing HS256 installs
   remain usable until rotation. Agent/control retain private signing material;
   the three verifier children receive public PEM only. Algorithms are selected
   from trusted key format, with no mixed allowlist or fallback. Migrated nodes
   reject an HS256 downgrade even at a newer generation/epoch.
   All six consumers were regenerated. UI source `bec0a4f` also refreshes stale
   sampling/finish-reason types; packaged dist `bd0b456` was rebuilt and checked.
   Both installers pin these versions. The
   [migration contract](r7-asymmetric-signing.md) documents upgrade-before-rotate
   ordering and session/client-key replacement. Isolated live five-process
   installs on Windows and Linux retained enrollment and stored secrets across
   legacy-to-Ed25519 rotation and restart; forged sessions were rejected.
   **23/23 mutation catches on each platform**, full consumer suites, and the
   repeatable CI gates are recorded in
   [`../acceptance/r7-signing-run.md`](../acceptance/r7-signing-run.md).

**Done when:** an inference-driver holding only what it needs cannot mint an
operator session, and a live install re-keys from the old scheme to the new one
without an operator re-enrolling a node.

**Where it sits:** no hard dependency on R2 or R3, and it should land **before
R2.6** if the order is free, so the Windows service's migration is written once
against the final credential shape rather than twice.

---

## Appendix — every finding, and where it went

`[S]` security pass, `[D]` data path, `[F]` first hour, `[me]` the review
session itself. **38 numbered findings plus §6.4, all re-verified present on
2026-09-17**, and one extra row for the market threat §5 #1. **This table is
the list — it is not a to-check list.** Read the row, open the slice, write the
failing check. Nothing here needs confirming again.

| #       | Finding                                                           | Slice                                                                                                                                                                                                   |
| ------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6.1 #1  | Login limiter driven by a supplied forwarded header `[S]`         | **R1.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #2  | Per-call `httpx.AsyncClient` = 104 ms on the loop `[D]`           | R1.1                                                                                                                                                                                                    |
| 6.1 #3  | Disconnect mid-stream leaks the in-flight counters `[D]`          | **R1.4 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #4  | Two fit paths; the golden path uses the scalar one `[F]`          | **R1.3 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #5  | `/v1/engines` blocks the loop on `nvidia-smi` + GitHub `[F]`      | **R1.5 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #6  | `agent.yaml` non-atomic write + unguarded load `[F]`              | **R1.5 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #7  | A taken port; no `component-down` issue kind `[F]`                | **R1.5 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #8  | Runtimes merged by bare name across nodes `[D]`                   | **R1.6 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #9  | A failed agent read closes that node's clients `[D]`              | **R2.1 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #10 | Elevated re-install strands the first install `[F]`               | **R2.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.1 #11 | Non-NVIDIA Windows GPU gets a CPU build silently `[F]`            | **R2.3 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #12 | Control snapshot readable by any service token `[S]`              | **R2.4 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #13 | GPU-sized timeouts cascade healthy CPU inference `[D]`            | **R2.5 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #14 | Download `filename` escapes every model root `[S]`                | **R1.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #15 | A worker names the URL the root will dial `[S]`                   | **R2.4 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #16 | No cancel on client disconnect; SDKs retry `[D]`                  | **R2.5 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #17 | Idle unload races an arriving request `[D]`                       | **R2.1 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #18 | `runtime is None` = always eligible `[D]`                         | **R2.1 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #19 | Admission reserves nothing; fallback context-blind `[D]`          | R3                                                                                                                                                                                                      |
| 6.2 #20 | `tier` renumbered for the natural slot shape `[D]`                | **R3 item 3 — done 2026-09-19**                                                                                                                                                                         |
| 6.2 #21 | Thinking filter swallows the answer when streaming `[D]`          | R3                                                                                                                                                                                                      |
| 6.2 #22 | Contract drift: `top_p`/`seed`/profile/`content_filter`/401 `[D]` | **R3 item 4 — code half done 2026-09-19; the profile sentence is a scheduled slice**                                                                                                                    |
| 6.2 #23 | `latencyMs` semantics + the 15.6 ms Windows grid `[D]`            | R1.1                                                                                                                                                                                                    |
| 6.2 #24 | Installers swallow network errors; port override ignored `[F]`    | **R2.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #25 | `HTTP_PROXY` applied to loopback traffic `[F]`                    | R1.1                                                                                                                                                                                                    |
| 6.2 #26 | The wizard promises an autostart the default lacks `[F]`          | **R2.6 — DONE 2026-09-18.** The mechanism changed, not the copy: a Windows install is a service. Step one's measurement turned the slice into a credential slice; step three refunded the graceful stop |
| 6.2 #27 | Symlinks dropped unreported; `followSymlinks` inert `[F]`         | R3                                                                                                                                                                                                      |
| 6.2 #28 | Intel reports zero VRAM; Rosetta hides Apple silicon `[F]`        | **Intel half R2.3 — done 2026-09-18**; Apple half R3                                                                                                                                                    |
| 6.2 #29 | An `nvidia-smi` that fails reads as "not on PATH" `[F]`           | **R2.3 — done 2026-09-18**                                                                                                                                                                              |
| 6.2 #30 | `tailnet.md` / `container.md` describe another install `[F]`      | **R2.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.3 #31 | Uninstall leaves engines, two keyring entries, copies `[F]`       | **R2.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.3 #32 | No frame-ancestors on the agent-served UI `[S]`                   | **R1.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.3 #33 | Operator-gated SSRF; probe spends a service token `[S]`           | **R2.4 — done 2026-09-18** (probe only; the SSRF reachability stays, by the slice's own call)                                                                                                           |
| 6.3 #34 | A non-ASCII prefix defeats self-restart detection `[F]`           | **R2.2 — done 2026-09-18**                                                                                                                                                                              |
| 6.3 #35 | Banned vocabulary through the wizard's error path `[F]`           | **R1.5 — done 2026-09-18, the review's mechanism corrected**                                                                                                                                            |
| 6.3 #36 | Parallel slots divide the context; the copy says otherwise `[me]` | **R1.3 — done 2026-09-18, premise MEASURED**                                                                                                                                                            |
| 6.3 #37 | Five respawns of an engine that dies during load `[D]`            | R3                                                                                                                                                                                                      |
| 6.3 #38 | A stream with no `done` frame is recorded served `[D]`            | **R1.4 — done 2026-09-18**                                                                                                                                                                              |
| §6.4    | One HS256 key mints sessions and signs service tokens `[S]`       | **R7** — decision #5 **TAKEN 2026-09-18: split it, before the release**                                                                                                                                 |
| §5 #1   | No Anthropic `/v1/messages` — **a market threat, not a defect**   | R4 — decision #1 **TAKEN 2026-09-18: in front of the release**                                                                                                                                          |
