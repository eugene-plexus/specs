# A node keeps its own copy of the models it runs — the run

**Script:** [`scripts/model-copy-acceptance.sh`](../../scripts/model-copy-acceptance.sh)
**Design:** [`docs/design/node-local-model-copy.md`](../design/node-local-model-copy.md)
(§11 is the verification list, §13 step 6 the slice)
**Date:** 2026-09-17 · **Host:** this Windows box (RTX 5090), agent + library on +100 ports
**Result:** **30 PASS, zero failures, second execution.** The first found
one product defect and one harness defect, both recorded below.

Under test: `specs` `db5c279`, `agent` `4380f22` (the copier `c78c2f5`,
the wiring `35142d3`, the validator fix `4380f22`), `ui` `7969cf2`.

---

## What only a live run could prove

The agent's unit tests pin the copier against a stubbed spawn and the
wiring against a fake process; the UI's pin the rendering against
fixtures taken off the wire. None of them can say that a **real
`llama-server` is handed the copy** rather than the share, that the set
is really one copy when two runtimes point at one file, that a headroom
refusal leaves a model **serving**, or that Clear leaves a file a
running engine is holding.

The run is the two-machine shape on one box: the Library folder is
`/models`, a POSIX path this Windows host does not have, and a
`pathMappings` override says where it is mounted here. Declarations
carry the library's spelling, exactly as a worker's do.

## The checks

| # | What it proves | Result |
| --- | --- | --- |
| 0 | isolated: no ambient `EUGENE_PLEXUS_*`, +100 ports, teardown by pid | PASS |
| 1 | the folder is stated once and mapped here | PASS |
| 2 | `copying` is observed — a status with no process in it | PASS |
| 3 | the copy lands, is byte-for-byte the source's size, and **the engine's own argv names it** | PASS (4 checks) |
| 4 | two runtimes over one model file → **one** copy | PASS |
| 5 | a second model → a second copy | PASS |
| 6 | a runtime removed takes its copy; the other is untouched | PASS |
| 7 | a copy that will not fit is skipped, the model still serves, and the reason is on the wire | PASS (5 checks) |
| 8 | Clear keeps an in-use copy **by name** and stops nothing | PASS (5 checks) |
| 9 | the toggle off opens the share again, with the copy still on disk | PASS (3 checks) |
| 10 | no `.ep-partial` anywhere | PASS |
| 11 | teardown: no owned port still listening | PASS |

Check 3's argv assertion is the one that matters most and is the
easiest to leave out: the runtime view would report `localPathSource:
copy` just as happily if the resolution were right and the spawn wrong.
The log line it passes on:

```
spawning alpha: …\llama-server.exe --model
  C:\Users\troyc\AppData\Local\Temp\ep-model-copy\copies\Qwen3-0.6B-Q4_K_M.gguf …
```

Check 7's refusal, in the words the Inference screen prints:

```
not copied to this machine: 997529.1 GB more free space is needed to keep
999999 GB free. Reading it from C:\Users\troyc\.eugene-plexus\acceptance-models\
nomic-embed-text-v1.5.Q8_0.gguf instead.
```

---

## THE FINDING: an integer config field could never be saved

**The first execution raised the headroom past the size of the disk,
read HTTP 200, and watched a copy happen anyway.** Three checks failed
and every one of them read as a product defect in the copier. The
copier was fine.

`_validate` in the agent's config store had branches for `boolean`,
`enum`, the string family and `path_mappings`, and fell through to
*"unsupported valueType for agent config: integer"* for everything else.
`modelCopyMinFreeGb` is **the first integer field this agent has ever
declared**, so it is the first to meet a gap that has been there since
M0.

**What hid it is the shape of the config trio's own contract:** a
refusal is reported inside a **200**, per field, in `rejected`. Nothing
that checks a status code can see it. So the value could be set only by
editing `agent.yaml` by hand — which is to say the setting was invisible
to the UI that exists to expose it, against
`gui-equality-for-configurable-things`.

Fixed in agent `4380f22`, with a boolean refused explicitly
(`isinstance(True, int)` is True in Python) and a float refused rather
than truncated, because 49.5 GB of headroom is a number someone typed.
**And the script now asserts on `applied`**, not on the status code.

This is the same family as M11's note that a new `ConfigValueType`
member reaches every consumer's validator — except the member was not
new. The field was.

## The harness defect, on the same execution

Check 7 first emptied the copy directory with `rm -rf` and declared a
runtime on a model whose copy had just been deleted. **Windows will not
delete a file two running engines hold open**, so the copy survived, the
new runtime correctly reused it, and the check reported "a copy was made
despite the headroom" — true, and about the wrong copy.

It uses the second model instead, whose copy check 6 had legitimately
removed. The product behaviour it originally reported as a defect is in
fact the design working: **an existing valid copy is used and no new
copy is made.**

---

## Not proved here, and said rather than faked

- **The timing claim** — §11 items 1-2, the whole point of the feature —
  needs a model on **another machine**. That is step 8 on the live
  install, and one box cannot stand in for it.
- **A mid-copy disk breach.** It needs a disk to fill; the abort and the
  partial's removal are unit-tested.
- **No browser drove this run.** The UI half is covered by page tests
  (`src/app/inference/page.test.tsx`) and the two library suites.
- Check 8's final Clear reported **0 files deleted** and an empty disk:
  the reconcile that follows an undeclared runtime got there first.
  Both are the feature working, which one wins is a race, and the run
  says which it saw rather than letting a zero pass unremarked.
