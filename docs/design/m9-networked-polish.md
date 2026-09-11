# M9 — Networked polish (design)

**Status:** designed 2026-09-11, **built and live-verified 2026-09-11**
— §8 is the implementation record and §9 is where the build departed from
this document. Milestone **M9** of
[`local-inference-control-plane.md`](local-inference-control-plane.md),
following [M8](m8-retained-request-metrics.md). Previously numbered M7
and then M8 — see the roadmap's §5 note for why it moved twice.

**What it is:** the last milestone that blocks a differentiator. #5,
*networked-first with auth*, is built and proven process-to-process —
Argon2id master key, libsodium envelopes, JWT bearers, service tokens
threaded at spawn, OS keyring auto-unlock, and as of 2026-09-11 an
enrollment and key rotation across two real hosts. **What has never
happened is a browser driving any of it.** Four items:

1. Re-verify the auth arc against the current topology **in a browser**.
2. Rewrite the wizard.
3. Document tailnet deployment.
4. Un-enroll and re-advertise.

Items 1-3 are debt. **Item 4 contains a defect**, found while scoping
this: a node announces its address exactly once, at enrollment, and
nothing ever re-announces it.

---

## 0. What scoping this found, before any of it was built

Every milestone since M4 has opened with a list of things the previous
one had agreed to without checking. This one is shorter, and the first
entry is the reason the milestone is worth doing rather than deferring.

1. **A node's advertise address is announced once and never again.**
   `node_identity.py` sends `advertise_url` inside the enrollment call
   and nothing else in the agent ever sends it. So a node whose address
   changes after enrollment — a new tailnet IP, a DHCP lease, a WSL2
   guest that rebooted and came back on a different subnet — leaves the
   control root holding a stale `Node.url`, and the gateway, which
   **prefers `advertiseUrl`** since M7, routes to a dead address. There
   is no error anywhere: the node is healthy, the root is healthy, and
   requests fail at a URL nobody is listening on. **This is the one
   thing in M9 that is a bug rather than a gap**, and it is exactly the
   failure a tailnet deployment invites, because tailnet addresses are
   stable *until the user reinstalls Tailscale*.
2. **There is no way for a node to un-enroll.**
   `DELETE /v1/nodes/{name}` on the control root exists and does the
   hard half — revocation-as-rotation, built at M5. The node side does
   not exist: an agent that has been revoked, or that the operator wants
   to move to a different install, has no way to discard the install's
   signing key and return to its own. `node.yaml` says enrolled forever.
3. **`ui` has no browser.** It gained vitest, jsdom and
   testing-library at M8, which is real verification of components and
   is **not** a browser: jsdom has no layout, no navigation, no real
   fetch, no cookie jar, and no way to be wrong about any of them. The
   four wizard bugs Troy found by hand on 2026-09-10 were all found by
   hand, and zero by tests, which is the empirical case for this item.
4. **There are no deployment docs at all.** `docs/` holds `acceptance`,
   `design` and `maintenance`. "Tailnet deployment" is discussed across
   three design documents and written down for an operator nowhere. The
   mesh-VPN decision is one of the architectural commitments, and the
   thing a reader needs — bind addresses, what to expose, what never to
   expose, how the three auth surfaces differ — does not exist.
5. **Nothing onboards a second machine, and every test has hidden
   it.** `default_topology.py` gets the enrolled case right — "a node
   that has joined an install gets its topology from the install, and a
   second node must never raise a rival control root" — and names its
   own blind spot in the next sentence: *"the case this cannot detect: a
   fresh node that is **about** to enroll."* The escape hatch is
   `EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0`. So **adding a second
   machine today means knowing to set an environment variable before the
   agent's first boot**, or raising a rival control plane on the worker
   and cleaning it up afterwards.

   Worse, **no test has ever walked that path.** Every multi-host script
   pre-writes `firstRunComplete: true` with an empty `components` list
   (`m7-acceptance.sh:146`, and the host-B setup for the 2026-09-11
   two-host run did the same by hand) — which is the bypass, written so
   fluently that nobody noticed it was standing in for a product feature
   that does not exist. Same shape as the v0.2 fossil config: acceptance
   scripts build throwaway installs and never touch the path an operator
   actually walks.
6. **The wizard is 1548 lines in one file.** `src/app/setup/page.tsx`,
   eight screens plus a Done screen, the draft state machine, the
   backend-creation logic, the topology checks and seven leaf components
   all in the same module. It has been patched at least four times since
   the direction changed and its screen list is still partly a fossil of
   the ten-screen consciousness-era flow.

---

## 1. The auth arc, and what "in a browser" has to mean

The arc is five things, and a browser is the only client that exercises
them in the order a user does:

| Step | Surface | Never browser-driven because |
|---|---|---|
| First run | `POST /v1/auth/initialize` on the agent, then on `control` | every acceptance script calls it with `curl` |
| Login | `POST /v1/auth/login`, session token to the browser | the token is read from a shell variable in every test |
| Restart-on-login | the agent restarts every child once unlocked | scripts sleep; a browser has to *survive* it |
| Topology-resolved proxy | `ui` resolves `control`/`library`/drivers through the agent's bearer-protected `/v1/components` | the proxy is bypassed except at M3 |
| Auto-unlock | OS keyring, so a restart needs no passphrase | tested headlessly in `agent`'s own suite |

**The third row is the one that matters and the one a script cannot
test.** Logging in restarts every child — it is in the memory as a trap
because it surprised us once already. From a browser that means: the
page that just authenticated is talking to a fleet that is going away
and coming back, and whether it recovers, spins, or shows a wall of
errors is a property nothing has ever observed. `skipAuth` breaking
every topology-resolved call is the same family, and is already recorded
as a trap that was wrong on first instinct.

**Decision: Playwright, driving the system Chrome, as a durable
acceptance script.** Not a one-off manual pass.

- *Why durable:* every milestone from M0 has a re-runnable
  `scripts/mN-acceptance.sh`, and that is why M6's and M7's regressions
  were caught by re-running rather than by memory. A manual browser pass
  verifies M9 once and protects nothing afterwards.
- *Why the system Chrome:* `channel: "chrome"` uses the browser already
  on the box, so CI and a dev machine need no 300 MB download and no
  browser-version pinning. Windows has Chrome and Edge; Linux CI can
  install one package.
- *Why Playwright over the alternatives:* it is the only one of the three
  that drives a real browser, waits on real navigation, and can be
  pointed at an already-running server — which is what an acceptance
  script needs, because the fleet is started by `dev-seed`, not by the
  test runner.
- *Scope guard:* Playwright is for the **arc**, not for component
  behaviour. Anything assertable in jsdom stays in vitest, which is
  faster and already in CI. The browser suite covers first run, login,
  restart-on-login, and one completion through the playground — the
  path no other test can reach.

## 2. The wizard

**What it must do, which is narrower than what it does.** Since the
first-boot change of 2026-09-10 the agent **declares `control`,
`gateway` and `library` itself on first boot**, so the wizard no longer
has to create a control plane — starting the agent *is* getting one.
That decision already removed the wizard's hardest job and nothing has
re-scoped it since. What is left is genuinely small: set a passphrase,
point at model directories, optionally declare a backend, and get out of
the way.

**Decision: rewrite as one screen per module with the draft state
machine extracted**, not a re-theme. The current file mixes eight
screens, a persisted draft, backend-creation logic, port allocation,
topology validation and seven leaf inputs; nothing in it can be tested
without mounting the whole wizard, which is why its test is 258 lines
and asserts a call sequence.

**SETTLED 2026-09-11, and the answer is five — but not for the reason
argued below.** Troy kept eight at M9 ("just split the file for now")
and handed the call back. Reading the split code in order to make it
turned up what the argument below never suspected: **three of the eight
screens did nothing at all.** `deployment`, `gatewayHost` and
`gatewayPort` were collected, displayed on the Ready screen as though
they were configuration, and never written by the Start transaction —
the only reader of any of them was the summary itself. An operator who
typed `0.0.0.0:9000` got an install on `127.0.0.1:8080` and a summary
claiming otherwise, which is worse than a wasted screen: it is a false
statement on the one screen whose entire job is to say what is about to
happen. The Gateway screen additionally rendered **no inputs at all** in
the default local path. Look & feel wrote only `localStorage`, and
`UIPreferences` on `/config` has been the same two controls all along.

So the cut is Welcome, Security, Models, Backend (optional), Ready —
the same five recommended below, but reached by finding the inert ones
rather than by weighing screens against each other. Shipped as `ui`
`4f07702`; live-verified by `scripts/m9-acceptance.sh` with the browser
arc, first attempt. Welcome also moved from third to first, where it had
been arriving *after* the operator chose a font size and committed a
passphrase.

**The finding worth carrying past this milestone:** the e2e walk
navigated the wizard by clicking Continue in a counted loop, naming
screens only in a comment. It would have walked the five-screen flow
just as happily while typing into whatever happened to be under it.
Every step now asserts its screen's heading before acting — the same
defect shape as the three this milestone found live, and writing the
assertions turned up a fourth instance immediately.

**The original argument, kept because it still governs the two screens
that were not inert.** The eight are Welcome,
Look & Feel, Security, Gateway, Models, Deployment, Backend, Pick a
model, Done. Two are questionable now:

- **Look & Feel first.** It is first because v0.1 put UI preferences
  first, when the wizard was ten consciousness-era screens. Asking a
  user to choose a font size before the thing works is the wrong first
  impression, and both settings are in `/config` anyway.
- **Deployment.** It branches on local-vs-networked, which the agent's
  own first-boot topology and `advertiseUrl` now decide better.

My recommendation: **five screens** — Welcome, Security, Models,
Backend (optional, skippable), Done — with Look & Feel and Deployment
dropped to `/config`, and Gateway/Pick-a-model folded into Done as a
"here is what you have, try it" step. That follows the rule from
2026-09-11: the default should be right before anyone opens the UI, and
every screen that is not load-bearing is a screen a non-technical user
can get wrong.

## 3. Tailnet deployment, written down

**Decision: `docs/deployment/tailnet.md` in this repo**, not in a
component README. It spans every component, and `specs` is where the
shared truth already lives. It has to answer, concretely:

- **Which addresses to bind.** `EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0`
  plus a non-loopback `advertiseUrl`, and the consequence M7 built and
  the two-host run proved: **a component binds wide only when its node
  advertises non-loopback, and enrollment does not restart the control
  root** — so the advertise address must be set *before* first boot or
  the root stays on loopback and no other node can reach it. That
  ordering cost an hour to discover and belongs in a document.
- **Engines are never widened, deliberately.** `vllm serve` and
  `llama-server` bind loopback even on a wide-open node, because an
  engine is reached by its own companion driver on its own host. Say so,
  because it looks like an oversight until it is explained.
- **The three auth surfaces are not interchangeable:** the operator
  passphrase, per-node service tokens threaded at spawn, and the control
  identity's signature (which is what re-keying uses, *never* a bearer,
  because a rotation invalidates every bearer). An operator who assumes
  one token opens everything will be confused in a way the API cannot
  fix.
- **What not to expose.** The tailnet is the perimeter; nothing here is
  written to survive the open internet, and the honest version of that
  sentence belongs in the doc rather than in a design nobody reads.

## 4. Un-enroll and re-advertise

The two halves of item 4 are different in kind: one is a missing
operation, the other is a bug.

### Re-advertise — the defect

A node must tell the root when its address changes, on change **and on
every startup**, because the startup case is the one that matters: a
host that reboots onto a new address never gets an `advertiseUrl`
config change to react to.

**Decision: the node announces, the root records — same direction as
M7.** M7 settled that the node tells the root where it is and the root
never guesses from a source address; re-advertising is that same rule
applied more than once, not a new principle. So this is a small contract
addition, not a redesign.

**Contract:** `PATCH /v1/nodes/{name}` on `control`, accepting `{ url }`,
authenticated by the node's own service token, recorded in the
replicated log. It must be **idempotent** — the common case is a
restart that announces an unchanged address — and an unchanged
announcement must not write a log entry, or every reboot of every node
grows the log for nothing.

*Not chosen:* having the root poll each node for its address. It inverts
M7's direction, and a root that guesses is the thing M7 explicitly
refused.

### Un-enroll — the missing operation

**Decision: `POST /v1/node/unenroll` on the agent, operator-authenticated,
and it proceeds even when the root is unreachable.**

The reasoning that matters is why this is *safe* to allow locally.
Revocation exists because **a node that still holds the signing key can
still authenticate**, so removing a registry entry alone does nothing.
Un-enrolling **discards** that key and returns the node to its own —
the opposite of the dangerous direction. A node cannot escape revocation
by un-enrolling; it can only disarm itself.

Consequences to implement deliberately:

- It **must** discard the install signing key, the epoch and the
  recorded control URL from `node.yaml`, and mint the node's own key
  again — which logs out every session on that node, exactly as
  enrollment does today.
- It should tell the root first (`DELETE /v1/nodes/{name}`) when the root
  is reachable, so the registry does not keep a ghost. When the root is
  unreachable it proceeds anyway and says so, per
  `degraded-mode-required`: an operator detaching a node from a dead
  install is precisely the case where refusing is useless.
- Its runtimes stay declared and its model files are untouched. Only
  routing stops, which is already the documented consequence of
  revocation.

**Open for Troy:** whether un-enroll should also be reachable from the
control root's UI as "detach this node", which would need the root to
reach the node — the direction M5 deliberately avoided for liveness.
Recommendation: no. Revoke at the root, un-enroll at the node; two
operations, each local to the thing whose keys are changing.

## 4a. Onboarding a machine — one question, asked three ways

*(Added 2026-09-11 after Troy asked how non-root nodes get configured.
The honest answer was: an environment variable, and no test has ever
used it.)*

`eugene-plexus-agent` is the same entry point on every machine, root
included. **So the machine must ask, rather than require the operator to
have known a flag.** On a boot that is genuinely fresh there is exactly
one question — *am I the root of a new install, or joining an existing
one?* — and everything else follows from it.

`should_seed(state, enrolled)` is already the single place that decides,
gated by `settings.default_topology`. This adds inputs to that decision;
it does not add a second decision.

### The three ways to answer

| Path | When | What it is |
|---|---|---|
| **Interactive prompt** | fresh boot **and** a TTY | the non-CLI answer: the agent asks before `create_app()` and routes accordingly |
| **`eugene-plexus-agent join`** | scripted, provisioning, Ansible | `--control <url> --token <jwt>` (+ optional `--name`, `--advertise`) |
| **`EUGENE_PLEXUS_AGENT_DEFAULT_TOPOLOGY=0`** | a service unit or container that is a node | already exists; now the non-interactive expression of "node" rather than a thing operators must discover |

**No TTY means today's behaviour: seed as root.** A service-managed or
containerised start has no stdin and **must never block on a question**.
Seeding as root is both the existing behaviour and right for the
single-machine case, which is the overwhelmingly common one; a node
started by a service unit is by definition being provisioned, and
provisioning has `join` and the env var. This is the one place the
milestone deliberately keeps a silent default, and it is the safe
direction — a spurious control plane on a machine that meant to be a
node is recoverable, whereas an agent that hangs at boot waiting for a
terminal nobody is watching is not.

### Why the web wizard cannot be the only path

A bootstrap paradox, not a preference. You cannot reach a worker's web
UI from your laptop until that agent binds non-loopback; it binds
non-loopback only when it advertises a non-loopback address; and setting
that address is part of what joining does. The browser arrives after the
thing it would configure.

This is the same argument that already settled first-boot seeding —
*"headless is the argument that settles it; a tailnet install has no
browser at first boot"* — and it is stronger here, because a worker in
another building is the case the whole multi-host arc exists for.

**Consequence, and it simplifies rather than complicates: the web wizard
is the first-install experience, full stop.** A worker node's UI shows
*which install it belongs to*, not a setup flow. The "am I a worker?"
fork never has to exist in the browser, which is an argument for fewer
screens rather than more.

### What joining needs that does not exist yet

A join token is minted at the control root
(`POST /v1/nodes/join-token`, single-use and short-lived, built at M5).
**Minting one from a browser needs a control-root screen, and there are
none** — so today the answer is `curl`, which fails the rule this
project now works to. M9 therefore owes one minimal root screen: *add a
node* → mint a token → show the exact `eugene-plexus-agent join`
command to paste on the other machine, the way `k3s`, `docker swarm` and
`tailscale up` all do it.

That is a *minimal* screen and not the control-root workflows that are
still blocked on the undecided "should the agent own the UI" question —
it mints a token and renders a command, and it would be built the same
way wherever the UI ends up living.

## 5. Contract

The first contract change since `a0d793e`, so it triggers the re-pin
dance — and the footgun from
[[polyrepo-spec-codegen-workflow]] applies: **a consumer sees a document
because its codegen config names it**, not because the pin covers it.

| Document | Change |
|---|---|
| `openapi/agent.yaml` | `POST /v1/node/unenroll` |
| `openapi/control.yaml` | `PATCH /v1/nodes/{name}` taking `{ url }` |

`common.yaml` is untouched, so by the rule the M8 re-pin earned, **the
radius is computed by regenerating and diffing, not by counting
`$ref`s**. Expected: `agent`, `control` and `ui` need the pin; `gateway`,
`inference-driver` and `library` do not, since neither document is in
their codegen lists — *verify it rather than assume it.*

## 6. Scope

**In.** A Playwright acceptance script covering first run, login,
restart-on-login and one playground completion; the wizard rewritten to
five screens with the draft extracted and each screen independently
testable; `docs/deployment/tailnet.md`; `POST /v1/node/unenroll`;
`PATCH /v1/nodes/{name}` plus announce-on-startup and on-change; **and
the onboarding question of §4a — an interactive first-boot prompt, an
`eugene-plexus-agent join` subcommand, and one minimal "add a node"
screen at the root that mints a token and renders the command.**

**The acceptance run must stop pre-writing `firstRunComplete`.** A
second host has to be onboarded the way an operator would, or this
milestone repeats the omission it was written to fix.

**Out.** MLX (the next item after this one). The structured `model_slots`
editor and the `runtime_name` dropdown — real gaps in differentiator #4,
but cosmetic and independent. The `~2 s` post-unload routing window and
the `~116 ms` HTTP-driver-path overhead, which are their own
investigations. Control-root screens: **still undecided whether the
agent should own the UI at all**, and building root workflows before
that is decided would be building them twice.

## 7. Risks

- **The browser suite finds something structural in the wizard.** Likely,
  given four hand-found bugs. Mitigation: land the Playwright script
  against the *current* wizard first, so it is a before-and-after rather
  than a test written to pass the new code.
- **Restart-on-login is genuinely broken from a browser** and the fix is
  not in the UI. Possible: the fleet going away under an authenticated
  page is a real race and nothing has looked at it. This is the one item
  that could grow past its milestone, and finding that out is the point.
- **Playwright in CI on Linux** needs a browser package. Mitigation: the
  suite is opt-in by script, like every other acceptance run, and CI runs
  vitest as now.
- **A stale `Node.url` may already be masked by something.** The gateway
  falls back when `advertiseUrl` is absent, not when it is *wrong*, so
  the reproduction should come before the fix.

---

## 8. Implementation record

**Status: built and live-verified 2026-09-11.** Contracts specs
`094dec7`; control `71ec4fa`; agent `a2baef3`; ui `d4989e4` and the
follow-ups below. `scripts/m9-acceptance.sh` is the durable run.

### What was built

| | |
|---|---|
| `POST /v1/node/unenroll` | agent; discards the install key, tells the root, proceeds if it cannot |
| `PATCH /v1/nodes/{name}` | control; signed by the node, tenth `LogOp`, replay-fenced by a sequence |
| announce-on-startup / on-change | agent; **re-derives** rather than reading the persisted value back |
| the first-boot question | agent; TTY only, `join` subcommand, env var unchanged |
| `eugene-plexus-agent join` | enrolls with nothing running, refuses a machine that already has components |
| the wizard split | one module per screen, plus `draft.ts` / `start.ts` / `chrome.tsx` / `fields.tsx` |
| `/nodes` | mint a join token, render the command |
| Playwright | the auth arc against the system Chrome, driving a live install |
| `docs/deployment/tailnet.md` | bind addresses, the three auth surfaces, what not to expose |

### What the live run found that nothing else could

Five things, in cost order. **The first two are the milestone's real
yield** and neither was in §0.

**1. The control host's agent never enrolls, so the browser's session
cannot reach the control root.** M7's design is explicit — *"every node
enrolls the same way, including the control host's … that is also what
puts the control host in `/v1/nodes` at all"* — and every acceptance
script since M7 does it. **The wizard never did.** An unenrolled agent
mints a fresh random signing key per restart while the root mints the
install's, so a session token from the agent does not verify at the root,
every control-root page 401s, clears the session and bounces to login.
Nothing had noticed because until M9 there was no control-root page to
open. The wizard now enrolls the local agent as step 2b and replaces its
own session, which is the price enrollment always charges.

**2. `next dev` refuses to serve its own client bundle when the page is
reached by IP.** Since Next 16, `127.0.0.1` is cross-origin against a
server announcing itself as `localhost`, and the dev-resource block is
**not an error**: the page server-renders, the client bundle is refused,
hydration never runs, and the wizard sits on "Loading setup…" forever.
Invisible to everyone who browses `localhost` — which is everyone, until
a browser drives it by IP. For a project whose product is *reaching this
UI from another machine*, that is worth fixing rather than working
around: `allowedDevOrigins` in `next.config.ts`.

**3. A node onboarded by `join` has no passphrase of its own, and the
503 told it to run first-run setup.** Correct behaviour with misleading
advice: a worker verifies tokens with the install's signing key, so an
operator session minted at the control root already works there. The
message now says so, and says not to run setup on a machine that has
joined — which would raise a second install on a host already in one.

**4. The `skipAuth` trap, met for the third time, plus a new shape of
it.** `skipAuth` on a topology-resolved target 401s the *lookup*, which
renders as "no control component in the agent topology". That one was
already on record. The new shape is structural: the wizard needs the
**control root's** token to mint a join token and the **agent's** token
to discover where the control root is, and between initializing and
enrolling those are genuinely two different credentials. One
`Authorization` header cannot satisfy both, so the proxy grew
`x-eugene-plexus-upstream-authorization` — one caller, and the window it
exists for closes the moment enrollment makes the install one key.

**5. A check whose subject was not where it was looking, twice more.**
The script's §6 asserted a log line that only appears when an address
actually changes, against a step where §5 had already moved it there —
so it reported a correct no-op as a missing announcement. And the
teardown killed the pid it held rather than the port, so a leftover
`next dev` survived and the next run silently tested the previous run's
build. Same family as M7's "the pid the script held was a subshell's",
one layer further out.

### The split duplicated every docblock, and the assertion did not catch it

The wizard split was done by script precisely so bodies were lifted
rather than retyped, and it asserted that each slice *started* with the
signature it expected. That assertion is true of both copies: slicing a
declaration "to the next top-level declaration" swept up the comment
block above that next one, and then slicing *that* declaration walked
back over the same block and took it again. Six docblocks landed twice
and the commit carried them.

The lesson is not "assert the edit" — that was done. It is that **an
assertion about where a slice begins says nothing about where it ends.**

### Open, unchanged

- The five-screen wizard of §2 was not built; Troy's call was to split
  the file and keep eight screens. The screen list is still a question.
- Control-root workflows beyond `/nodes`, still blocked on whether the
  agent should own the UI.
- `test.skip` guards the playground completion unless `EP_CHAT_MODEL` is
  set, so the run proves the arc rather than a generation.

## 9. Where the build departed from this design

*(Opened 2026-09-11 while landing the contracts. The convention is M5's
§10: a design is not edited to look like it was right, it records where
it was wrong.)*

### 9.1 "Authenticated by the node's own service token" does not work

§4 settled the direction correctly and then named a credential that
cannot do the job. Two independent reasons, found by reading
`control/dependencies.py` rather than by reasoning:

1. **A service token names a kind, not a host.** `issue_service_token`
   encodes `aud: service:<kind>`, so `service:agent` from any node in
   the install is indistinguishable from `service:agent` from the node
   whose address is being changed. Every agent could re-address every
   other node.
2. **The sharper one: it would have been the first mutation on the trust
   root authenticated by a service credential.** Every write on
   `control` today is `require_operator`, and the module says why — *"a
   compromised peer holding a service token must not be able to enroll a
   host or re-key the install"*. Re-advertising cannot be operator-
   authenticated either, because the case that matters is an unattended
   reboot at 3am. So the choice was never "operator or service"; it was
   "find a third thing".

**Built instead: the node signs the announcement, exactly as the control
root signs a re-key.** The symmetry is the argument — *the root proves
itself to a node with its identity key, and a node proves itself to the
root with its own, and neither uses a bearer, because a bearer does not
survive the rotation that makes these two operations necessary in the
first place.*

**Cost, stated plainly: a node needs a second keypair.** The identity
key it has is X25519, generated to have secrets *sealed* to it, and
X25519 does not sign. Deriving one from the other only runs
Ed25519 → X25519, which is the direction we do not have. So
`ensure_keypair` mints an Ed25519 pair alongside, `EnrollmentRequest`
and `NodeIdentity` grow `signingPublicKey`, and `Node` records it.
Optional on the wire, so an older agent still enrolls — **and a node
enrolled before this existed cannot re-advertise and must re-enroll**,
which is surfaced as an absent `Node.signingPublicKey` rather than left
to be inferred from a 401.

**Also added, not in §4: a `sequence`.** Strictly increasing per node,
persisted on the node, mirrored in applied state. Without it a captured
announcement can be replayed to pin a node to an address it has left,
which is a denial of service that costs an attacker nothing. It resets
with the node record on re-enrollment, because `enrollNode` replaces
the record wholesale.

### 9.2 `LogOp` opened to ten, and M5's decision did not forbid it

`updateNode` is the tenth op. The M5 memo says *"LogOp stays closed at
nine — do not relitigate"*, so this needs an argument rather than an
edit.

The rule that closed it was about what does **not** belong: minting a
join token and initializing the install are not replicated state, so
they got no op. `Node.url` is the opposite case — it lives in the
snapshot, and `LogOp`'s own description says *an operation that is not
in this list is an operation that would not replicate*, and *adding a
mutation means adding an op here*. Closing the set at nine and then
mutating applied state outside it is the one combination the design
rules out.

**Rejected: reusing `enrollNode` as an upsert.** It would have worked —
`_apply_enroll_node` already replaces the record by name, so the apply
function needs no change at all. It is worse for one reason that is not
about correctness: the log is read by operators, and a node that moved
house would appear in it to have enrolled again.

Snapshot cost checked, per the rule M5 learned the hard way (*a snapshot
is the log's compacted head; every op must have somewhere to land*):
`Snapshot.nodes` already carries `Node`, so `updateNode`'s effect lands
with no schema change beyond the two new fields.

### 9.3 §0's first finding was overstated in one respect

*"There is no error anywhere: the node is healthy, the root is healthy,
and requests fail at a URL nobody is listening on."* The first clause is
wrong. `GET /v1/components` on the control root assembles the union view
by asking every node, and a node it cannot reach lands in
`unreachableNodes` — deliberately, and with a comment saying why. So a
stale `Node.url` **is** visible.

What is not wrong is the defect. A node at an unknown address is
unreachable *by the only address the root has*, so the root cannot poll
its way out of it — which is also why "have the root ask" is not a fix
and the announcement has to be a push. Until M9 the only recovery was
an operator editing state by hand. The finding stands; its second
sentence does not.

---
