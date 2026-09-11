# M9 acceptance — onboarding, leaving, moving house, and the first browser

**Status:** passed 2026-09-11, **40 checks, zero failures**, on the
fourth attempt. Script:
[`scripts/m9-acceptance.sh`](../../scripts/m9-acceptance.sh). Design:
[`m9-networked-polish.md`](../design/m9-networked-polish.md) — §8 is the
implementation record this run produced.

```
host A (this box)   agent :8079  -> control :8083, gateway :8080, library :8082
                    started with NO agent.yaml at all
                    ui dev server :3100, driven by Chrome via Playwright
host B (also here)  agent :8084 -> :8085, onboarded by
                    `eugene-plexus-agent join`, with nothing running there
```

**The point of this run is what it does not do.** Every multi-host script
since M0 pre-wrote `firstRunComplete: true` with an empty component list
before starting anything. That is the bypass for an onboarding feature
that did not exist, written so fluently that nobody noticed it was
standing in for one. Host A here starts with no config file and has to
declare its own control plane; host B is onboarded the way an operator
would be; **and a browser walks the first-run wizard**, which had never
happened.

---

## What it checks

| § | |
|---|---|
| 1 | a fresh machine declares control/gateway/library itself, with no config file and no TTY |
| 2 | Chrome walks the wizard, logs in, survives restart-on-login, and reaches the topology-resolved proxy |
| 3 | `join` mints nothing, enrolls with a token from the root, refuses a machine that already has components, and names `--force` |
| 4 | the joined node starts as a **worker**, not a rival root; a root-minted token verifies on it |
| 5 | a node that moves tells the root, signed; the sequence advances; a forged announcement is refused and moves nothing |
| 6 | a restart **re-derives** its address and announces it; a restart that did not move records nothing |
| 7 | un-enrolling discards the install key, keeps the node's own, and the root is told |

## The browser arc

Five steps, and a browser is the only client that takes them in the order
a user does. The row that matters is **restart-on-login**: logging in
respawns every supervised child, so the page that just authenticated is
talking to a fleet that is going away and coming back. A script sleeps
through that; a browser has to survive it. It does.

`test.skip` guards the playground completion unless `EP_CHAT_MODEL` is
set, so this run proves the arc rather than a generation. Everything else
runs on every invocation.

---

## Four attempts, and what each one bought

Recorded because the failures are the value here — three of the four
were defects in the product, not in the script.

**Attempt 1 — the wizard never hydrated.** The page server-rendered and
sat on "Loading setup…" forever. `next dev` since Next 16 refuses to
serve its own client bundle cross-origin, and **`127.0.0.1` is
cross-origin against a server announcing itself as `localhost`**. It is
not an error anywhere: the HTML arrives, the bundle is refused, hydration
never runs. Invisible to everyone who browses `localhost` — which is
everyone, until a browser drives it by IP. Fixed with
`allowedDevOrigins`, because *reaching this UI from another machine* is
the product.

**Attempt 2 — Start stalled with a bare `503`.** Two causes, one of them
already on record. The recorded one: `skipAuth` on a topology-resolved
target 401s the *lookup*, which renders as "no control component in the
agent topology" — alarming and false. The new one is structural and not
a mistake: **the wizard needs the control root's token to mint a join
token and the agent's token to discover where the control root is**, and
between initializing and enrolling those are genuinely two credentials.
One `Authorization` header cannot satisfy both.

**Attempt 3 — `/nodes` bounced to the login page.** The finding with the
longest reach: **the control host's agent had never enrolled.** M7's
design says every node enrolls the same way, the control host's included,
*"that is also what puts the control host in `/v1/nodes` at all"*, and
every acceptance script since M7 does it. The wizard did not. An
unenrolled agent mints a fresh random signing key on every restart while
the root mints the install's, so a token from the agent does not verify
at the root — every control-root page 401s, clears the session and
redirects. Nothing had noticed because until M9 there was no
control-root page to open.

**Attempt 4 — green.** The last fix was in the test, and it is the same
shape three times running: **`isVisible()` does not auto-wait**, so the
sign-in helper read a login form that had not rendered yet as "already
signed in", proceeded with no session, and turned every later call into a
401. A check whose subject is not where it is looking reports confidently
on the wrong thing.

---

## Findings the script itself earned

**A node onboarded by `join` has no passphrase of its own.** Correct —
it verifies with the install's signing key, so an operator session from
the control root is the credential for it. The 503 told it to run
first-run setup, which on a machine that has joined an install is advice
to raise a second one. Fixed; the message now names the control root.

**The teardown killed the pid it held, not the port.** `next dev` spawns
a child of its own, so a leftover server survived and the next run bound
nothing and silently tested the previous run's build. Same shape as M7's
*"the pid the script held was a subshell's"*, one layer further out.

**A check pointed at a step where nothing could change.** §6 asserted a
log line that only appears when an address actually changes, against a
restart where §5 had already moved it there — so a correct no-op was
reported as a missing announcement. §5 now moves the address somewhere
**nothing is listening** (which also exercises the rule that an expert
override wins even with a value that will fail), leaving §6 a real
change to make.

---

## What this proves, and what it cannot

**Proves:** a fresh machine declares its own control plane with no config
file and no browser; `join` onboards a second machine from a terminal and
leaves it a worker rather than a rival root; a node that moves tells the
root — signed, on a config change *and* on a restart — with replays
refused and an unchanged restart costing the log nothing; un-enrolling
discards the install key and the root is told; and a browser drives first
run, login, restart-on-login and the topology-resolved proxy.

**Cannot:** a node genuinely offline while it moves. Two real hosts —
that is [`m7-acceptance.sh`](../../scripts/m7-acceptance.sh) in
`EP_MODE=two-host`, and its
[record](m7-two-host-run.md). A tailnet address changing under a running
install, which this simulates with a port. Clock skew. A
partitioned-but-alive old control root.
