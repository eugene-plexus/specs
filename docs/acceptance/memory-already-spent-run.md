# R3.2 — memory already spent

**2026-09-19.** Roadmap §4 item 2, review §6.2 #19. Two halves of one
finding: a file-size fallback that could not see the context it was
asked for, and an admission that measured free memory without counting
the launches already spending it.

**Built:** specs `b4a0a1d`; `agent` `01f6aad`; `control` `67f18e9`
(regen-only); `ui` `56ff7ea`, dist `afc1b2f`. **Both installers
re-pinned**, and the pinned `dist` archive was fetched and grepped for
the new copy rather than the working tree.

**Gate:** `scripts/r32-sabotage.py` — **22 sabotages, 22 caught**, over
four passes. 864 agent tests, 164 control, 729 UI.

**No acceptance script.** The defect is a race between two launches
against one card's free memory, and the only honest live version needs
two real models that together do not fit a 5090 and a second Launch
pressed during the first one's load — minutes of hand timing for a
verdict a fixture states exactly. The sabotage pass is the gate, and
§"Not done" says what that leaves unproven.

---

## 0. What was actually wrong

`check_admission` already took `running`, which reads like an accounting
of the other runtimes on the device. It is not: `_blockers`
(`admission.py:411` as the review found it) turns the list into an
advisory *what else is on this card* and **nothing subtracts it from
anything**. The arithmetic reads live free memory off the
`DeviceSnapshot` — the right number, and the wrong one, because a
runtime that was admitted three seconds ago has read no weights.

So the finding reads as an arithmetic bug and is not one. The fix is a
record of intent, and the finding carries none of its rules.

The window is not seconds either. The node-local copy added `copying`
before any process exists at all, and on a remote mount that is the
longest part of a first launch: **266 s for 23.8 GB over SMB**, measured
on this project's own install.

The second half is separate and smaller: `required = size * 1.1`,
whatever `contextSize` asked for. An 8B Q4 at 128k needs about 17 GB
once its cache is counted and was admitted against 5.2 GiB.

## 1. The reproduction, written first

`agent/tests/test_admission_reserves.py`, 26 checks. On the first run
against the unfixed code: **12 failed, 5 passed**, the passes being the
unit tests of the ledger module (new code) and one deliberate pair — the
same 8B at 4k, which has to keep being admitted or the fix is just a
bigger constant.

Two existing tests in `test_admission.py` asserted the flat tenth
(`int(2 * GIB * 1.1)`, `"33.0 GiB"`). **Amended, not added to** — the R3
rule for a test that locks in the defect.

## 2. The shape

**`reservations.py`.** A promise per runtime name, carrying the device
admission chose, the bytes it measured, and `perf_counter()` at the
moment of promising. `held_bytes` is the pure half so admission can sum
a list it was handed. In memory only: a restarted agent has no launches
in flight, and persisting would hold a card across a reboot for runtimes
that died with the process.

**One release mechanism, `reconcile`.** A promise stands while its
runtime is observed `copying`, `starting` or `loading`, and is dropped
the moment it is anything else — `ready` holds memory the snapshot now
counts, a stopped or crashed one holds none, a deleted one is not in the
topology to observe. It runs at every read, which is the only moment its
answer is used.

**The device pick moved too.** `max` by the card's own free reading puts
the second launch on the card that only looks empty; it is by
free-minus-reserved now, and `freeBytes` on the wire stays the card's own
number with `reservedBytes` beside it. Reporting the reduced figure as
`freeBytes` would be a claim about the card that is not true.

**The fallback is the library's own estimate, duplicated.** Weights, plus
`ESTIMATED_KV_FRACTION` of them per `ESTIMATED_KV_BASELINE_CONTEXT`
tokens, plus a flat overhead — the same three constants `fit.py` carries,
copied rather than shared because components share schemas and not code,
with a comment in each direction. Two estimates of one quantity that
disagree is this project's signature defect.

## 3. The three rules, and the fourth

**A dry run must not reserve.** `POST /v1/runtimes/admission` is what the
launch panel asks on every keystroke of the context box. One
`check_admission` call site serves it, a create and a start, so the
three are told apart at the routes or not at all.

**`copying` reserves before any process exists** — and it was not even on
the blocker list, because `_RUNNING` had no member for a runtime with
nothing to observe. It is `_HOLDING` now, and `PENDING_STATUSES` is the
subset that has not taken its memory yet.

**The TTL, 30 minutes,** for the case the sweep cannot see: a runtime
never observed again. Long enough that no real launch reaches it, short
enough that an abandoned one frees the card inside a coffee break.

**And a fourth the finding does not name: `force` reserves.** `force`
overrides the verdict, not the arithmetic — a forced launch spends the
memory like any other. Create and start measure under `force` now and
simply do not raise. Before this, a forced launch was invisible to
everything that came after it.

## 4. The sabotage pass

Four passes. **First: 15 caught, 10 escaped** (three of those bad
anchors, ruff having reformatted the code out from under the list).
**Second: 19 of 23. Third: 20 of 22. Fourth: 22 of 22.**

**Three escapes named a SECOND MECHANISM rather than a weak check, and
each was answered by deleting the spare.**

* *Explicit `release()` on stop and on delete.* Both escaped because the
  sweep already covers them: it runs at every read, and both routes
  change the status it reads. No check could tell one from the other.
  `ReservationLedger.release` is gone.
* *A default context inside `file_size_requirement`.* Unreachable — its
  one caller settles on a number first, and it was a second place for
  the assumption to live where nothing would see them disagree. The
  parameter is required now.

The release on PATCH went for a different reason and left a comment
behind: a PATCHed runtime restarts and takes memory again, so dropping
its promise would reopen the defect for as long as the restart takes.

**The rest named missing checks:** two cards with one spoken for; a
forced Start; `copying` surviving the sweep; a zero-byte promise
asserted on `entries()` rather than on a byte total that is zero either
way; and the reported context being the number the arithmetic actually
used.

**Two checks written in the first pass could not fail, and the pass is
what said so.** A dry run asked twice about the *same* spec cannot see a
reserving dry run, because a runtime's own promise is never counted
against it — the shape where it is observable is the launch panel
re-measuring a runtime that already exists. And a 20 GiB model on a
24 GiB card is refused whatever the ledger says, so the check proving
the preview does not rewrite a promise had to name a model that fits.

## 5. The UI

`launchPreview.ts` printed `freeBytes` alone, so with a launch in flight
the panel would have read *"needs about 8.0 GiB; 24.0 GiB free"* and then
been refused — two screens disagreeing about one number, which is what
that surface was built to stop. It names the reservation now. The
refusal path already carried it, because it prints the agent's own
reason.

The refusal's fix line leads with **"Wait for the launch already under
way"** when there is a reservation. It is the one remedy on that list the
operator does not have to do anything for, and without it they go looking
for memory they are about to be handed back.

## 6. Not done, named

* **No live run.** Every verdict here comes from a shaped
  `DeviceSnapshot`. Nothing has raced two real launches on the 5090.
* **Over-counting during `loading` is accepted and unmeasured.** The full
  promise stands while the weights are being read, so the total is high
  by up to the model's own size for the length of one load. It shrinks to
  nothing as the load finishes and it errs toward refusing;
  the alternative needs a per-engine load-progress number S7 established
  does not exist.
* **Boot reserves nothing.** `app.py` starts every declared runtime at
  boot without consulting admission at all. That predates this slice and
  is unchanged by it — a box whose declared runtimes do not fit together
  is as broken after this as before.
* **The TTL has never fired outside a unit test** with an injected clock,
  and cannot in any run short enough to sit through.
* **The fallback's constants are the library's, and nothing enforces
  that.** Two comments point at each other. A check that reads both
  files as text would be the R1.1 `time.monotonic()` treatment and is not
  written.
