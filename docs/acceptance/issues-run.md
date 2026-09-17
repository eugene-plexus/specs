# Needs attention — acceptance run (2026-09-16)

**Result: 20 `PASS` lines, zero failures, one deliberate `SKIP`, second
execution.** The first execution failed two checks and one of them was a
real finding about the product rather than the harness — see *The
finding* below. `scripts/issues-acceptance.sh`: four processes plus two
llama.cpp engines and their companion drivers on +100 ports, the
environment cleared, teardown by pid, the system Chrome driving
`ui/e2e/issues-live.spec.ts`. Hobbyist UX plan S7. Design:
[`../design/hobbyist-ux.md`](../design/hobbyist-ux.md) §7 S7; record
§11.9.

This run was written **after** the pins, at the operator's direction, so
for one day S7 shipped with nothing but jsdom behind it. It found one
thing in that day, which is roughly the rate every other acceptance run
in this project has found.

## What only a live run could prove

The rules are pure and tested against bodies taken off the live install;
the reads are tested against a mocked wire; the badge and the card are
tested in jsdom. None of that could show that **a real agent puts
`NodeIdentity.time` on the wire**, that a **real llama.cpp declared with
no offload** reads back the way the rule expects, that **two real engine
builds serving at once** are visible as a mixed fleet, or that a
**genuinely sealed control root** can be opened from the header of
whatever page the person happens to be on.

Every issue in the run is produced by the install rather than by a
fixture:

| Issue | How the run produces it |
| --- | --- |
| `folder-unreachable` | two Library folders, one of them never created |
| `runtime-on-cpu` | a real 0.6B on a real `llama-server`, declared `gpuLayers: 0`, on a box with a 5090 |
| `engine-build-stale` | two runtimes pinned by `binary` to `b10930` and `b10948` — both serving |
| `control-sealed` | the root restarted with no keyring: `503 Locked` |
| `engine-unavailable` | **deliberately absent** — vLLM really does report `policy: manual`, `installable: false` here, and is correctly not counted |

## The finding: a fresh sign-in cannot meet a sealed root

The first execution sealed the control root, signed a browser in, and
found **no issue to report** — because there was nothing left to report.
Since 2026-09-13 the login page posts the passphrase to the control root
as well as the agent, so **signing in unlocks it**. The check was
measuring a state its own setup had just destroyed.

That is not a defect in either thing; it is the two halves fitting
together, and it says exactly what the badge is *for*. The login-time
unlock covers the person who arrives after the root sealed. The badge
covers the other one — the person **already signed in when the root came
back sealed underneath them**, which is the case the live install
produced on 2026-09-13 and which `CLAUDE.md` has recorded as still open
ever since: *"an already-open browser session still does not unlock it —
sign out and in."* S7 closes that, and this run is what shows it closed.

So check 11 seals the root **from inside the page**, with the session the
browser already holds, and then never navigates: it starts on `/library`
— neither Home nor `/nodes` — watches the badge turn blocking, opens the
row, types the passphrase into the row, and asserts both that the issue
clears and that the URL never changed. That is the slice's *Done when*
(*"from any page"*) measured rather than asserted.

The other first-execution failure was the harness: the accelerator probe
called a function that does not exist. It reads `devices` off the same
`GET /v1/node` body the rule reads now, so the run and the thing it
measures cannot disagree about the subject.

## What it does not prove

**Clock skew was not produced, and is reported as `SKIP` rather than
faked.** The rule compares two *hosts*, and this box has one clock.
Moving the system clock to manufacture a second one would change the
clock every other process on this machine uses — including the live
worker install's, whose tokens a control root on another machine would
then refuse. Two machines with independent clocks is the instrument, and
this is not it. To produce it: two enrolled machines, one with its time
service stopped and set 60 s ahead.

Also unproven: `node-down` (needs a second machine to go down), and the
estimate half of `describeLoading` (it appears only once a browser has
watched the same model on the same node finish loading, and each run
starts with an empty store).

## The numbers

| | |
| --- | --- |
| `NodeIdentity.time` vs this shell's clock | **0.188 s** |
| llama.cpp builds serving at once | `b10948` and `b10930` |
| installed version the descriptor reports | `b10948` |
| healthy-phase browser arc | 8.1 s |
| sealed-phase browser arc | 1.1 min (a control restart plus the 30 s poll) |

The sealed phase is slow on purpose. An issue is not a task: the poll is
thirty seconds because a sealed root, an unmounted folder and a mixed
engine fleet do not change second to second, and four reads per node is
a real cost on an install with ten of them. The run waits it out rather
than shortening it, because the interval is part of what is being
tested.
