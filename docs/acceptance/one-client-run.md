# R1.1 — one client, one context, one clock: the run

**2026-09-18. `scripts/one-client-acceptance.sh`, 21 PASS, zero failures,
third execution.** Roadmap: [`../design/release-roadmap.md`](../design/release-roadmap.md)
§2.1. Findings closed: review §6.1 #2 (the per-call client), §6.2 #23 (the
clock), §6.2 #25 (`trust_env`).

Repos: `agent`, `gateway`, `inference-driver`, `library`, `control`. No contract
change — this is entirely below the wire.

---

## 0. The numbers

Measured on this box (Windows 11, CPython 3.12 in the gateway and driver venvs —
the Python both installers provision), against a stub backend that thinks for
5 ms, so everything above that is the control plane.

| | before | after |
| --- | --- | --- |
| `httpx.AsyncClient()` construction | **104–136 ms** | **0.03 ms** |
| driver hop, 1 ms stub, median | **110.3 ms** | **2.0 ms** |
| control-plane overhead per request, end to end | ~116 ms (M8's unexplained figure) | **3.2 ms** |
| ten concurrent completions, wall clock | ~1 s of blocked loop in client builds alone | **31.3 ms** |
| agent readiness poll, four ready runtimes | ~0.84 s of every 2 s | nothing measurable |
| `monotonic()` resolution, CPython 3.12 Windows | **15.625 ms** (20 distinct values in 300 ms) | `perf_counter`, 1e-7 |

The driver's reported `latencyMs` came back **8–9 ms** across fifteen requests.
On `monotonic()` every one of those would have been `0` or `15`.

**The 116 ms is closed.** It was `ssl.create_default_context(cafile=certifi.where())`
— a PEM parse — running synchronously on the event loop inside a client this
project built once per call, in five repos, at 28 construction sites of which 20
were per-call and 14 sat on repeating paths.

---

## 1. What the run does

Four processes and a stub: an agent that spawns a gateway and an
inference-driver, pointed at a Python stub backend with a fixed think time.
**No GPU, no model, no engine binary** — the subject is client lifetime, clocks
and proxy handling, and a real engine's own variance would swamp all three.

Safe beside the live install, by this repo's standing rules: every ambient
`EUGENE_PLEXUS_*` variable dropped, ports +100, teardown by pid, never a
name-matching kill (this box is a worker node).

| # | Check | Result |
| --- | --- | --- |
| 0 | isolated: no ambient `EUGENE_PLEXUS_*`, no ambient proxy | PASS |
| 1 | a **cold** interpreter builds its first shared client, in all three packages | PASS |
| 2 | stub answering; its own floor measured through a pooled client | 5.9 ms |
| 3 | agent spawns gateway and driver; both `running` | PASS |
| 4 | one completion end to end | PASS |
| 5 | control-plane overhead single digit | **3.2 ms** |
| 6 | reported durations are not on the 15.6 ms lattice | 15/15 off-grid |
| 7 | ten concurrent completions do not serialise | 31.3 ms |
| 8 | the whole install again, with a dead `HTTP_PROXY` in the environment | PASS |
| 9 | teardown by pid; no owned port still listening | PASS |

---

## 2. The findings

### 2.1 The slice introduced a deadlock, and a full test run hid it

The first cut of `_http.py` guarded the SSL-context cache with a
`threading.Lock` and had `shared_internal_client()` hold that lock while
calling `ssl_context()`, **which takes the same lock**. A plain `Lock` is not
reentrant, so the first call in a process deadlocked — and only the first,
because every later caller finds the context already built and returns before
the acquire.

**Every suite was green.** Some earlier test in each run had always built the
context first, so nothing in 1,699 tests could reach the deadlock. It showed up
as one agent test that hung when run alone and failed inside the full run for
an unrelated-looking reason. A cold agent would have hung on its first engine
readiness probe, forever, on every install.

The lock is an `RLock`. **Check 1 runs a fresh interpreter per package**,
because no test inside a warm process can be first.

### 2.2 The review's `trust_env=False` was right and its scope was wrong

The review phrased the fix as `trust_env=False` on loopback clients. Applied
blanket it breaks the two things in this product that legitimately talk to the
internet: the model hub and the GitHub release feed. For a user behind a
corporate proxy that is not a slowdown, it is total — no discovery, no
download, no engine acquisition.

So the rule is per site, and `_http.is_internal()` decides it from the URL:
loopback, link-local, private ranges and a dotless hostname are internal;
anything else keeps `trust_env`. **The driver is the case that proves it
matters** — the same engine class fronts `127.0.0.1:8081` and
`api.openai.com`, so the decision cannot be made per call site. Both
directions are checked, and the sabotage pass runs the blanket version to
confirm the cloud check catches it.

### 2.3 Check 8 reproduces #25 verbatim

Sabotaged back to `trust_env=True` and re-run, the script reports:

```
NOTE  components under a dead proxy: gateway=starting stub-driver=starting
FAIL  components did not reach running under a proxy
FAIL  no completion under a proxy: ... "No models are currently routable" ...
```

Both processes are up and serving; the health poller cannot reach them through
a proxy that cannot dial 127.0.0.1; the poller gates the `starting → running`
promotion rather than restarting anything, so **the install sits at `starting`
while actually serving** and the gateway reports nothing routable. That is the
symptom exactly as the review described it, produced on demand.

### 2.4 The first execution measured the floor with the wrong instrument

Check 5 reported **-15.5 ms** of overhead: the control plane faster than the
backend it forwards to. The stub's floor had been measured with `urllib`, which
opens a fresh connection per request, while the control plane uses a pooled
client — two spans, two instruments. That is the same mistake that produced the
original "unexplained 116 ms", so the check now measures both ends with one
pooled `httpx.Client`, **and fails on a negative result** rather than passing it.

### 2.5 The second execution reported a stale credential as a proxy defect

Check 8 restarts the agent, and a session minted before the restart is not
valid against the key the restarted agent derives. The check read that 401 as
the proxy defect it exists to find. It signs in again after the restart now.

---

## 3. What the unit checks pin

`tests/test_http_client_reuse.py` in each of the five repos — **43 checks**:
10 (agent), 11 (gateway), 12 (driver), 6 (library), 4 (control). Full suites
after the slice: agent 718, gateway 245, driver 169, library 427, control 140.

The sabotage pass ran **13 sabotages, all caught** — twelve scripted against
the unit checks ([`../../scripts/one-client-sabotage.py`](../../scripts/one-client-sabotage.py),
`12 caught, 0 escaped`), plus §2.3's live one against the acceptance script. It
restores from a copy, never `git checkout --`, and opens with a baseline
assertion that every gate passes unsabotaged, without which a sabotage that
"fails" proves nothing. The twelve: a client per call in each of the driver,
gateway and agent; `response.elapsed` back under `latencyMs`; `trust_env` on
for everything; off for everything; the SSL context rebuilt per call; a
duration back on `monotonic()`; the topology client outliving its table; the
plain `Lock`; the browser proxy taking the user's proxy; the hub losing it.

**One escaped on the first pass, and the sabotage was what was wrong.**
Disabling *either* half of a double-checked lock changes nothing — the other
half still guards — so two successive single-line attempts on the context
cache both left it working and reported as escapes. Removing the guard whole
reproduces the defect, and two separate checks then catch it
(`test_the_ssl_context_is_built_once_per_process` and
`test_building_a_client_does_not_reparse_the_bundle`). Recorded because the
lesson is general: a cache with two guards needs a sabotage that removes both,
and an "escape" is a claim about the sabotage before it is a claim about the
check.

---

## 4. Not covered

- **No live install, no real engine, no browser.** The numbers above are
  against a stub. The 21 s-to-serving and 56–58 tok/s figures the live install
  produces are unchanged by this slice by construction — it removes a fixed
  per-request cost, not anything in the engine path — but that is an argument,
  not a measurement.
- **Nothing is re-pinned and `dist` is not rebuilt**, deliberately: no UI
  change, and no contract change, so the installers' six pins are untouched.
  The five component repos need their own commits and a pin bump before this
  reaches an install.
- **The synchronous `urlopen` in `engines/acquisition.py` is still on the event
  loop** — review §6.1 #5, scheduled as R1.5. A shared SSL context does not
  help it; it needs to move off the loop.
- `library`'s and `control`'s clients were already per-instance, so what
  changed there is the shared context and the proxy rule, not a lifetime.
