# R3.3 — a primary that is down is still a primary

`scripts/r33-sabotage.py`, **8 sabotages, 8 caught**, after a first pass
that escaped one and named a missing check. 353 gateway tests, ruff, ruff
format and mypy green. Closes review **§6.2 #20**; roadmap §4 item 3.

Repos: `specs` (contract `53428fa`, prose only, both installers),
`gateway` **`1fb5fa2`**. `ui` was regenerated, measured and **deliberately
not re-pinned**.

**No acceptance script, by the slice's own call.** What it changes is a
*number in a response envelope* under a condition — a companion driver
down at the moment of a refresh — that a live run reproduces by killing a
process and racing a 15 s refresh window, for a verdict three fixtures
state exactly. The instrument would be the flaky part.

---

## 1. The finding is a second case, not a regression

The 2026-09-10 fix stopped `resolve()` dropping empty tiers, because
dropping one renumbered every tier after it and a cloud fallback came
back as `tier: 1`. It carved out one exception — the slot's own implicit
name, which `_slot_targets` always puts first — and **that carve-out was
unconditional**. Its own docstring recorded why, and the why is sound for
exactly one of the two shapes an operator can write:

| slot | the self tier is | dropping it |
| --- | --- | --- |
| `{model: "chat", targets: [local-8b, cloud]}` | nothing — `chat` is a **virtual alias** nobody launches | **correct**; keeping it renumbers the operator's own two targets, which is how the first attempt at the 2026-09-10 fix broke five tests |
| `{model: "qwen3-8b", targets: [cloud]}` | **the primary**, and this is the shape the UI produces | **the defect**: the cloud answers `tier: 1`, so `GET /v1/metrics` cannot tell *primary served* from *primary was dead at refresh* |

Note what the second row needs to go wrong: not a misconfiguration, just
a companion driver that is not answering at the moment of a refresh.
Nothing is advertising `qwen3-8b`, so `by_model` has no entry, so the
tier vanishes and the numbering closes up behind it.

## 2. The discriminator was already on the snapshot

`_declares_runtime(model)` asks whether **any node in the install
declares a runtime under that name**, reading `_Snapshot.runtimes` — what
each agent reports it has, independent of what is advertising anything
right now.

Which map it does *not* read is the whole point: `by_model` is the
instant, and `by_model` being empty is the condition under test. A check
built on it would have been a check that cannot fail.

**By alias OR by name**, and both halves earn their place. The alias is
what a companion driver advertises as its `modelId` (M6), so it is the
match that fires on the live install; but `RuntimeSpec.modelAlias` is
optional, and a runtime declared without one still produces a driver
advertising something. Matching only on `alias` would drop the self tier
for every operator who never typed one — the same defect by another
route.

**Over-matching is the safe direction and the code says why.** This
decides a *label*, never an order: `_slot_targets` produces the same
sequence either way and `pick` walks it the same way. The cost of keeping
a tier that should have gone is one number; the cost of dropping one is a
fallback that claims to be the primary.

## 3. The sabotage pass, and the two entries that carry it

Eight entries. The two that matter are **THE FINDING** (drop the self
tier whenever nothing serves it now) and **THE OVER-CORRECTION** (keep
every empty self tier), because this defect has already been fixed once
in the wrong direction. A fix that only ever answers *keep* is the same
bug facing the other way, and a check set that cannot fail it would pass
it. Both are caught.

**One escaped on the first pass, and it named a missing check rather
than a weak fix.** Narrowing `_declares_runtime` to this node alone —
`if key[0] is None` — escaped every other entry, because no test put the
primary on another machine. That is precisely the install R1.6 exists
for: one model, two machines. `test_the_self_tier_is_kept_for_a_primary_on_another_machine`
is the check that was missing; with it, 8 of 8.

## 4. ▶ And the fixture was building a snapshot no install can produce

Found while writing the reproduction, and it is R1.6's own lesson one
fixture over — *the test written for this scenario had been passing on a
shape no install can produce*.

`tests/conftest.py::install_snapshot` still keyed `runtimes` by **bare
name** three weeks after R1.6 moved production to `(node, name)`. Nothing
failed, because no test using that helper does a keyed lookup. What it
did do was **marry a driver on one node to a runtime on another** — the
exact cross-node join R1.6 removed from the gateway — and
`test_the_routing_view_opens_the_table_up` was asserting that marriage:
the runtime declared on node `box`, its driver on no node at all, joined
anyway, and the view's `node`, `parallel_slots` and `idle_unload_seconds`
all read off a join production cannot make.

Corrected: the map is keyed by the tuple, `FakeDriverClient` has a
`node`, `by_model` sorts by `(node, name)` as the real refresh does, and
that test puts the driver on the same machine as its runtime. Two
assertions in it moved with the shape — `in_flight` needed
`on_attempt_start(..., node="box")`, because R1.6 keys the counters too.

## 5. The contract said the opposite of what the code does

`ModelRoutingInfo.tiers` read **"Empty tiers are omitted."** That
sentence outlived the behaviour it described by nine days: the
2026-09-10 fix's entire content was to stop omitting them. Corrected to
state the rule and the reason, including which tier can be absent and
why. `ChatCompletionExtras.tier` gains the half that makes it
answerable — positional over the slot's tiers, not over the ones that had
anything in them.

**Radius measured by regenerating both consumers**, not assumed: the
gateway's `models.py` changed by exactly the two descriptions, and `ui`
came back with a **JSDoc-only diff** — zero non-comment lines — that no
screen consumes, so it was reverted rather than re-pinned. The R2.5
precedent: re-pinning would force a `dist` rebuild for a comment.

## 6. Not done, named

- **Nothing was run against a live install.** The three new checks are
  fixtures; the live version is a race against a refresh interval.
- **`GET /v1/admin/routing` now shows the empty self tier**, which is the
  diagnosis an operator wants, and no browser has looked at it.
- **`tierCounts` in `GET /v1/metrics` is what this fix exists to make
  honest**, and no retained metrics row has been read back since it
  landed.
