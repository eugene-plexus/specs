# A person's Stop outlives the agent (agent#11)

Troy, 2026-10-09 and again 2026-10-10: a model he had stopped was running
again after every update and every reboot of Amish_Station. On 2026-10-10
the old `Huihui-Qwen3.8-27B-abliterated-Q6_K_L` llama.cpp runtime came back
at each reboot and took the VRAM Strata was meant to have.

**Cause.** `POST /v1/runtimes/{name}/stop` recorded its reason only in the
supervisor's memory. At boot the agent started every runtime whose
`autoStart` was not false, including ones a person had stopped. Only
`autoStart: false` survived a restart, and the console could not set it
on a runtime after declaring it.

## What changed

- **Contract** (specs `4bed046`):
  - `StopReason.operator` is remembered across agent restarts.
  - `PUT /v1/runtimes/{name}/auto-start` (`RuntimeAutoStart`) sets
    `autoStart` alone, without restarting the engine. `PATCH` replaces
    the whole declaration and restarts the engine, because every other
    field is on its command line.
- **agent.**
  - A stop for `operator`, or with no reason, is written to `agent.yaml`
    under `stoppedRuntimes`. Boot (`start_at_boot`) leaves that runtime
    stopped, with `stopReason: operator`.
  - Any start forgets it: Start, Restart, an edit, or a gateway wake.
    Removing or renaming the runtime forgets it too.
  - `idle` and `measurement` are not remembered. A restart stops only to
    start again, and the start forgets the stop.
- **ui.**
  - Each runtime row has **Start when Eugene starts**. It is shown only
    once the node has said what its runtimes are, so the box never shows
    a guess.
  - A stopped row says why in words. A person's stop reads *someone
    stopped it, and it stays stopped until it is started*.

### One call against the issue's text

agent#11 said "a stop for a switch is not" remembered. The gateway's
model switch stops the old model with `operator`, so it is remembered. That
is deliberate. A switch is a person choosing B over A on a machine that
cannot hold both. If A came back at boot beside B, the two would compete
for the memory, which is the very failure Troy hit.

## Acceptance of record

`scripts/ls5-preparation-acceptance.py`, extended to stop the Strata
runtime the way the console does and then restart the real agent process.
It ran on Amish_Station, 2026-10-10: **26/26 PASS**. That is the 23 before
this change, plus:

```
PASS  S1 a model someone stopped is still stopped after the agent restarts, and says why
PASS  S2 Start brings it back and forgets the stop
PASS  S3 Start when Eugene starts is saved without restarting the model
```

## Unit tests

- agent: `tests/test_remembered_stop.py` (12):
  - what `agent.yaml` keeps;
  - which stops are remembered;
  - boot;
  - a real stand-in engine that stays stopped across a supervisor
    restart until Start;
  - `create_app`'s own boot with the real runtime supervisor;
  - the route: saved without touching the engine, 404, and operator-only.
- ui: `app/inference/page.test.tsx` (3):
  - the reason in words;
  - the box saves with a `PUT` and nothing else;
  - a refused save leaves the box as it was and says why.

## Sabotage

`scripts/agent11-sabotage.py`: **18 caught, 0 escaped**.

The first pass had 19 entries and 2 escaped, and each escape changed the
code or a test:

- *A restart that stops only to start is remembered* escaped. The start
  that follows forgets the stop, so no check could tell the difference.
  The `remember=False` it sabotaged was dead weight, and it is gone.
- *The box shows the old value after saving* escaped. The test's stand-in
  node changed its answer as soon as the save landed. A real node's read
  is slower than the screen, so the test now keeps the old answer, and
  the box must show what was saved.

The agent and ui gates were rerun: 16 of 16 caught. The acceptance's 2
were caught in the first pass, and its code is unchanged since.

Full suites: agent 2200 passed; ui 1874 (151 files); lint, format and
types clean.

## Pinned

- agent `f384a0f`
- ui `dist` `dcea23c` (built from ui `b6b9c8d`)

## The live run (owed)

Once Edge has this, update Amish_Station. Stop a model there, then reboot
or Restart Eugene. It should come back *stopped*, with *someone stopped it,
and it stays stopped until it is started*. Start should bring it back.
