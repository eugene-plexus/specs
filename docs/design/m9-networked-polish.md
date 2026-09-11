# M9 — Networked polish (design)

**Status:** designed 2026-09-11, unbuilt. Milestone **M9** of
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
5. **The wizard is 1548 lines in one file.** `src/app/setup/page.tsx`,
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

**Open for Troy — the screen list.** The current eight are Welcome,
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
`PATCH /v1/nodes/{name}` plus announce-on-startup and on-change.

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
