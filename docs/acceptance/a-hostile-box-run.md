# R1.5 + R1.6 — the first hour on a hostile box: the run

**2026-09-18. `scripts/r15-acceptance.sh`, 35 PASS live, zero failures, fourth
execution. `scripts/r15-sabotage.py`, 38 sabotages, 36 caught, 2 escaped** —
and both escapes are recorded as uncovered *by measurement*, not patched over.
Roadmap: [`../design/release-roadmap.md`](../design/release-roadmap.md) §2.5 and
§2.6. Findings closed: review §6.1 #5, §6.1 #6, §6.1 #7, §6.3 #35, §6.1 #8.

Repos: `agent` (`a5f482e`), `gateway` (`1162bdc`), `ui` (`5cbcdfb`, dist
`640e3de`). **No contract change** — `Health.details` is a free-form object and
`Component.lastError` has existed since M0. **Both installers re-pinned and
`dist` rebuilt**, because the UI changed; the pinned UI archive was fetched and
grepped for the new sentence and for the absence of the old one.

---

## 0. The shape of it

Two slices, five findings, and one sentence each.

**R1.5 is three ways the first hour ends badly on a box that is already being
used**, and they are independent: a route that stalls the process serving the
browser, a config file that a power cut turns into an install that will not
boot, and a port somebody else is on. The fourth finding is the sentence a
person meets when the third one bites.

**R1.6 is one sentence: `RuntimeSpec.name` is unique per agent, not per
install.** The UI names a runtime after the model and a companion driver after
the runtime, so one model launched on two machines is `qwen` and `qwen-driver`
on both — and every map in the gateway was keyed by the bare name.

| finding | what it was | what the person got |
| --- | --- | --- |
| §6.1 #5 | three uncached host probes + a 60 s `urlopen`, on the loop | a UI that freezes for seconds at a time |
| §6.1 #6 | `open("w")` + an uncaught `load()` | an install that will not boot and cannot be repaired from the browser |
| §6.1 #7 | seeding onto a port something holds; no `component-down` issue | the wizard completes onto an install that routes nothing, and an empty Needs-attention card |
| §6.3 #35 | a backtick literal the extractor could not see | *"The trust root would not accept a passphrase"*, seventy words, ending in a `curl` instruction |
| §6.1 #8 | runtimes merged by bare name across nodes | an unload sent to the wrong machine; a stopped engine routed to and 502ing |

---

## 1. #5 — the engines route was the whole of its own cost

`describe_engines` called `detect_host()` three times per request — once in
`_acquisition_for`, once in `plan_for`, once more for the manual engine's
install command — and each of those shells out to a vendor tool with a 5 s cap.
Behind it, `GitHubReleases.list_releases` reached `api.github.com` through a
blocking `urlopen` on a **60 s** timeout and stamped only success, so an
unreachable upstream was re-dialled on **every** request. `GET /v1/engines` is
polled by Home every 15 s and by the Issues badge every 30 s **per node**, and
it is served by the process that also serves the browser its own UI and proxies
every other component.

Four changes: `asyncio.to_thread` on the route (the codebase already does this
at five comparable sites), the host resolved once and threaded through, a
failure stamp with a five-minute back-off, and a separate 10 s timeout for the
metadata read. Sixty seconds is right for half a gigabyte of engine and wrong
for one JSON body, and the two had shared a constant.

**Measured live, with a real 2-second `nvidia-smi` on PATH:** `/healthz`
answered in **0.06 s** while `/v1/engines` was resolving, and the stub recorded
**one** invocation for that request. The docstring on `_acquisition_for` had
asserted the opposite of the defect the whole time — *"never blocks on the
network beyond the release cache"* — which is the strongest evidence it was an
oversight.

**Two harness defects in the concurrency check, both worth keeping.** The first
version started its clock *after* waiting for the engines request to get
going, and **passed against the defect**: a blocked loop cannot resume the
waiting coroutine either, so the mark was taken after the half second had
already elapsed and `/healthz` then measured fast from a baseline that had
moved. The second version was unauthenticated, and `/v1/engines` is
operator-gated — a 401 is refused before the probe runs, so nothing blocked and
the timing assertion was green about a request that never happened.

---

## 2. #6 — the config file, and the two halves that are only a fix together

`_write_locked` used a bare `open("w")`, which truncates before the first byte
is written. **The write frequency is what makes the window reachable rather
than theoretical:** every config PATCH and every companion declaration rewrites
the file, and M6 declares one companion per runtime. And `state.load()` was
called uncaught in two places, so a half-written file was an install that
exited on boot — against `degraded-mode-required`, which had never been applied
to the component that owns the rule's own file. The only escape was
`EUGENE_PLEXUS_AGENT_SAFE_MODE=1`, which a scheduled-task user cannot know or
set, and the Windows task gives up after three restarts.

Now: temp + `fsync` + `os.replace`, and `load_or_degrade` — **one method rather
than a try/except at each call site**, because a rule enforced by remembering
to write four lines twice is a rule that gets half applied. A failure does
three things, and the last two are what make coming up on defaults safe:

* **resets the in-memory state.** `load()` mutates as it parses, so a raise
  part-way left a half-built topology — and the next `PATCH /v1/config` would
  have persisted that, turning a damaged file into a damaged install.
* **preserves the file** as `agent.yaml.unreadable`, so the first repair write
  cannot be the thing that loses the operator's topology.
* **remembers whether the raw text carried auth keys**, because `yaml.safe_dump`
  sorts keys: `auth` is written first, so a half-finished file *keeps* it and
  loses the tail. The loaded state then has no passphrase and the UI's next
  move is to offer first-run setup, which would mint a second `masterSalt` and
  orphan every secret the old one sealed — every provider API key, and the
  install signing key on every enrolled node — silently.

**`firstRunComplete` is deliberately not evidence that a passphrase existed,
and a first version keyed on it and broke two things at once:** it is also how
every multi-host acceptance script since M0 says *skip onboarding*, and how an
enrolled node with no passphrase of its own reads. Only the auth keys are
evidence.

`/healthz` carries the reason as `details.configError` plus the path of the
preserved copy. No contract change: `Health.details` is a free-form object and
the library already uses it for `unreadableRoots` and `scanError`.

**Live:** the agent was stopped, its `agent.yaml` cut inside the components
list, and restarted. It came up, reported `degraded` with the YAML scanner's own
message, answered `/v1/config`, kept a copy of the broken file beside it, and
**refused first-run setup** with *"Restore the configuration file from a
backup, or from the copy kept beside it."*

---

## 3. #7 — a port somebody else is on, and the card that said nothing

Two ports, two different failures. **8083** and the wizard's first Continue has
already set the agent's passphrase before the trust root fails five times.
**8080 — the commonest occupied port on any development box** — and the wizard
*completes*: the gateway crash-loops, `GET /v1/models` is empty, Home offers
nothing routable, Try it never appears, and the Needs-attention card is
**empty**, because `IssueKind` had no member for a supervised component that is
down.

`ports.is_free` / `ports.first_free` ask the **socket**, which is the only thing
that decides a bind — the half-existing pattern in the wizard's driver-port walk
is keyed on declared URLs, which says nothing about the operator's own web
server or their Docker publish. `default_topology.seed` walks past a held port
while skipping the install's own defaults, so walking off 8080 cannot land on
8081 and produce a second collision at the first Launch. **It is not
reclamation**: nothing is killed, because at boot the agent cannot tell its own
orphan from a server the operator meant to be running. The documented port is
kept whenever it is free — every doc, every acceptance script and the UI's
guessed gateway base URL assume the specs' `servers` defaults.

**Live: 8080 held before first boot, the gateway declared on 8084 and
`running`**, library on 8082 and control on 8083 untouched, and the log naming
the port and what it did about it.

The UI half is `componentDownIssues`, fed by a **fifth per-node read** in
`useIssues`. It has to be the owning agent's `/v1/components`: the control
root's `RuntimePlacement` carries no `lastError` and the gateway's driver list
says nothing about the gateway. `starting` and `exited` are excluded — every
boot passes through them, and a list that goes red for a few seconds after every
restart is one people close. `safe_mode` is a warning rather than blocking: the
process is up and answering, it is just running on defaults.

**Live, on a real crash-loop** (a component declared onto a held port):

```
port 8188 is already held by pid 52388 (python.exe). Stop it, or point this
component at another port in the topology. Nothing is killed for you: at boot
the agent cannot tell its own leftover from a process you meant to be running.
```

That is the sentence the card renders — produced by `ports.explain_collision`,
which had existed since step 2 and reached no screen.

And the two 409s. *"Reset the install by removing agent.yaml's auth block by
hand"* was the most destructive instruction in the product and one a browser
cannot carry out; it says **sign in** now.

---

## 4. #35 — the review's mechanism was wrong, and running the extractor said so

The finding placed the hole in the checker's file list. It is not there:
`app/setup` has always been in `GOLDEN_PATH` and `start.ts` has always been
read, so patching the list would have changed nothing. **The hole is the
quoting.** `extractCopy` matched double-quoted strings and JSX text; a
single-line backtick literal matched neither — and copy that needs a value
interpolated into it has no other quoting to use.

With a backtick pattern added (interpolations blanked so a sentence built around
a value is still a sentence, and the prose guard kept so `` `${base}/v1/models` ``
is not copy), the whole golden path yielded **exactly one** offender: the
wizard's control-root failure. It named the "trust root", ran to seventy words,
and ended by telling somebody sitting in a browser to POST JSON to
`/v1/auth/initialize` and look at a PowerShell script in a repository they may
not have. Three short sentences now — what happened, what not to do, and where
the diagnosis is — pointing at the Needs-attention card that R1.5's other half
just made able to answer.

**Check 9 reads the BUILT export, not the source**, which is S10's finding
applied: a fix that was on `main`, tested and merged reached no build, and the
acceptance run then clicked a 16 GB download beside a folder that already held
a model.

---

## 5. #8 — one model, two machines, and the first time a live gateway saw both

Merged by bare name, the last agent read won. Three consequences, and the review
named one of them:

* **the surviving entry carried the wrong node**, so an idle unload decided for
  A was sent to B's agent — which answers 404 for a runtime it does not have;
* **B `ready` masked A `stopped`**, so A's driver stayed eligible, was picked by
  the balancer and answered 502;
* and **both replicas shared one in-flight counter and one idle clock** — so B's
  traffic kept A looking recently used, and the idle pass, iterating the merged
  map, never considered one of the two at all. Those last two are the
  consequences the review did not name.

Keyed by `(node, name)` now: the snapshot's runtimes, `_ready_since`,
`_runtime_inflight`, `_runtime_last_request`, `_stopping`, `_inflight`,
`_last_request`, the client cache, `Resolution.runtimes`'s dedupe, **and both
joins** — the driver-to-runtime one and the alias fallback, because a bare name
and a shared alias each match another machine's replica just as well.

**That is the fix the rest of the system was already written for**: control keys
placements by `(node, name)` and sorts by it, and the metrics rollup's primary
key already carries `node`. Only the value was wrong, because it came from the
merged survivor.

`DriverClient` gains a `node` and `RoutingHooks` a `node` keyword, so
`TieredClient` can tell the table which machine an attempt hit; the `runtime`
handle it hands back is a `(node, name)` pair now, still opaque from its side.
`served_by_node` sits beside `served_by` for the same reason — the envelope's
`runtime` and `context_length` lookups matched by name and answered about
whichever backend sorted first.

**`test_multi_agent.py`'s fixture is renamed to what the UI actually
produces**, which is the roadmap's Done-when and is itself the reproduction:
the test written for this exact scenario had been passing on a shape no install
can produce. Eleven of its assertions could no longer be expressed as a list of
distinct driver names and now read node names instead — which is the point, and
is why the rename was the right move rather than a second fixture beside the
first.

**And the live half is the first time two nodes have been in front of a running
gateway with one name between them.** The M6 replica run passed because it was
one node. A real gateway process, finding its agents the way it really does —
through a control root's `/v1/nodes` — over two agents each declaring `qwen`
and `qwen-driver`:

* two backends, one per node, both naming the runtime `qwen`;
* node A set `stopped` → **only node B routable**, then both again when it
  recovered;
* a completion served, answered by node A, with `runtime: qwen` on the
  envelope;
* node B alone given an idle timeout → **the stop went to node B's agent**
  (`[['node-b', 'stop', 'qwen']]`) and node A kept serving.

---

## 6. The sabotage pass

`scripts/r15-sabotage.py`, five gates: the agent's unit file, the gateway's
two-node file, the UI's issue rules, the page that has to be wired to them, and
the vocabulary checker with the wizard. Baseline first, restores from a **copy**,
never `git checkout --`.

**38 sabotages, 36 caught.** Every "THE finding" entry was caught. Of the eight
that escaped on the first pass, **six named a check that did not exist** and one
named a claim of mine that was wrong:

| escaped | what it meant |
| --- | --- |
| the degraded load keeps its half-parsed state | the reproduction's fixture failed on its **first** component, so the reset was unobservable. A fixture that fails on the second is both observable and likelier — a cut loses the tail |
| the interrupted write leaves its temp file behind | no check paid for the atomic write's cost: litter in the one directory an operator is told to look at |
| the stop reservation is WRITTEN by bare name | the new two-node case takes the reservation itself, so it tests the read side. Driving `idle_pass` and sampling eligibility from inside the stop call is what sees the write |
| one wake in flight answers for both replicas | the case called `_wake_runtime`, which bypasses the map the key is in. Driven through `wake()`, two concurrent callers must produce one start |
| the alias fallback crosses nodes | every driver in the fixture named its runtime, so the fallback was never reached. A `/v1/info` with no `runtime` is the shape that gets there |
| a code template counts as copy | `checkCopy` returns nothing for `${base}/v1/models` **whether or not** the prose guard is there — no banned term, too short to be a long sentence. The assertion moved onto the extractor |
| a lifecycle action asks the merged survivor's agent | **mislabelled by me.** It edits the reservation key, not which agent is asked; the property it claimed is already covered. Relabelled to what it actually is |

**The two that still escape are recorded rather than covered, and the reason is
a measurement.** Removing `SO_EXCLUSIVEADDRUSE` from the port probe, and
setting `SO_REUSEADDR` instead, change no answer this function can be asked
about in a test: against an actively listening socket on this box every variant
refuses — no option 10048, `SO_REUSEADDR` **13**, `SO_EXCLUSIVEADDRUSE` 10048.
`SO_REUSEADDR` was expected to break the probe outright and does not. What the
exclusive flag buys is the `TIME_WAIT` case, which no check here can arrange
deterministically. Both entries stay in the list so the next person sees they
are uncovered rather than assuming they are not, and `ports.is_free`'s docstring
says the same with the numbers.

---

## 7. What this run does not cover

* **Two real machines.** The R1.6 half runs a real gateway over stub agents on
  four ports. What that cannot show is a real engine's weights on two real
  cards; this box has one GPU, and the second host is the live install's.
* **The release back-off against a real unreachable GitHub.** Unit-covered
  (three calls, one dial); the live run does not take the network away.
* **A browser.** Every UI assertion here is vitest against the page, plus a
  grep of the built export. Nobody opened Chrome on a seeded-around port.
* **The wizard's own screens** on an install whose ports moved: the seeded
  gateway on 8084 is what the topology says, and the UI reads the topology, but
  no browser walked it.
* **A real power cut.** The atomic write is proved by an interrupted
  `yaml.safe_dump`, which is the same window and not the same event.
