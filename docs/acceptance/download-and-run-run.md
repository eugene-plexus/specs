# Download and run, as one action — acceptance run (2026-09-16)

**Result: 28 `PASS` lines, zero failures, second execution.** The first
execution's two failures were the same harness defect, in both browser
passes, while every API check beside them passed.
`scripts/download-and-run-acceptance.sh`: four processes on +100 ports,
the environment cleared, an engine root of its own, teardown by pid, the
system Chrome driving `ui/e2e/download-and-run.spec.ts` twice against
two different prepared states. Closes **§6.3** of the hobbyist UX plan;
record §11.8.

## What it replaces

S6, a few hours earlier, shipped Home offering **Download**, with S3's
**Run** taking its place when the file landed. Every step existed and
worked; what was missing was exactly the orchestration §6.3 calls "the
slice". The person was asked twice, and the second ask arrived minutes
later — when a multi-gigabyte download finishes and they may well have
walked away from the machine.

## What the run proves

**One click reaches a running model.** From a fresh install with no
models and no engine: Home suggests one, **Download and run**, the
engine question (decision #6's "ask first"), and then a first reply in
the same card. The browser never navigates.

**It is one tray entry.** §6.3's own words, and the check asserts the
count is exactly 1 with `data-task-kind="run"` — the run's row claims
the tray's download row while it waits on it, the same mechanism that
already absorbed the engine install and the runtime load.

**The chain survives the laptop closing.** Section 6 takes the install
back to "nothing runs it", starts a download through the API with
`runWhenReady` set, and lets it finish **with no browser anywhere**.
Then a fresh Chrome opens Home and, with nobody clicking, the model is
running. The intent was on the record; the console claimed it and
carried on.

**Exactly one console can carry on.** Two claims on the same record
return `true` then `false`. Without that, every browser polling the
install would create a profile and launch a runtime for the same model —
and a console opening a week after someone deliberately stopped that
runtime would start it again.

## The one defect, and it was in the harness both times

Both browser passes failed at

```
Locator: getByTestId('home-try-it').locator('textarea').first()
Expected: enabled     Error: element(s) not found
```

**Home's composer is an `input`, not a `textarea`** (`home-composer`).
So the spec waited sixty seconds for an element that does not exist —
twice — while in the same run the API checks beside it reported the
runtime `ready`, the profile made, llama.cpp installed at `b11001`, and
in the second pass *"a runtime exists that no human asked for in this
browser"*. The product did the whole job both times and the test could
not see it.

Same family as M10's check 7 and step 6's fragmentation checks: a check
that looks somewhere its subject is not. The fix names the test id
rather than the tag, and says why in the spec.

## What it does not prove

Nothing about **closing the browser mid-transfer**, which is the
scenario the design talks about: the run arranges the equivalent state
through the API — a finished download with its intent still set — rather
than by killing Chrome during a download and reopening it. The state the
console meets is identical; the path to it is not.

Nothing about **two consoles racing in real time**. The claim's
exclusivity is asserted with two sequential calls, not two simultaneous
ones, and the atomicity underneath is the manager's own `asyncio.Lock`
rather than anything this run exercises concurrently.

Nothing about a **cross-node chain**: Home runs models on the machine
the browser is served from, and this box is one machine. A chained run
targeting `node:<name>` is unit-tested and has never been executed.

And the model is a 0.6B pointed at by a one-entry `starterModelsFile`,
so the run takes minutes rather than the half-hour the shipped list's
smallest entry would cost. That is what `starterModelsFile` is for, and
it means **this run says nothing about the shipped starter list** —
`starter-set-acceptance.sh` is where that is checked.

## The full run

```
== 3. a fresh box, and a one-entry starter list
  PASS  no models on disk
  PASS  llama.cpp is not installed here, so the question will be asked
  PASS  the starter list is this run's own: Qwen/Qwen3-0.6B Q4_K_M

== 4. the browser: one click from Home to a running model
  PASS  browser: one click on Home gets the model and runs it --
        the engine question, ONE tray entry, a first reply

== 5. what the components hold: the intent was carried, and taken down
  PASS  exactly one download: the chain did not start a second
  PASS  runWhenReady is down: the browser that ran it claimed it
  PASS  exactly one runtime: qwen3-0-6b-q4-k-m
  PASS  one profile named default, made by the chain
  PASS  llama.cpp was installed inside the chain: b11001

== 6. the closed laptop: a finished download picks itself up
  PASS  a download started with the intent set, and no browser open
  PASS  it finished with nobody watching
  PASS  the intent is still on the record, waiting for a console
  PASS  browser: a fresh console ran it with nobody clicking
  PASS  a runtime exists that no human asked for in this browser
  PASS  and the intent came down when it was claimed

== 7. exactly one claim wins
  PASS  a claim after the winner gets nothing
  PASS  first caller True, second False -- two consoles cannot both launch
  PASS  claiming a download that does not exist is a 404

== result
  ALL CHECKS PASSED
```

## Sabotage

Two, in the unit suite, each confirmed to fail its own check and no
other:

| removed | what failed |
| --- | --- |
| the `claimed` gate in `resumeClaimedRuns` | *does nothing when another console got there first* — a losing console launched anyway |
| the download branch of `mergeTasks` | *is one task-tray entry, not two* |
