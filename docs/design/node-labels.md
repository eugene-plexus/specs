# Node labels — a name you can change, over an identity you cannot

**Status:** scoped, not started (2026-09-16).

A node's name is whatever `socket.gethostname()` returned when it
enrolled, and it is permanent. On a container that is the container ID,
so the live install's control host is called `468e3ed662bf` and wears
that hex string on every screen a person looks at. The template now sets
`--hostname` so new installs do not start this way, but no install made
before that can be fixed, and nothing stops the next operator from
enrolling a machine called `DESKTOP-4KJ2P9`.

This slice adds a **label**: an operator-set display name, over an
identity that never changes.

---

## §0 Measurements

Taken 2026-09-16, before any design.

**The name is a KEY in fifteen places across ten UI modules** — every
`node:<name>` proxy target, which is how one console reaches another
machine's agent (`one-console-never-hop-nodes`). `resourceTree.ts`,
`clientKeys.ts`, `launchPreview.ts`, `libraryReach.ts`, `nodeBudget.ts`,
`oneClickRun.ts`, `tasks.ts`, `inference/page.tsx`, `LibraryFolders.tsx`.
A label reaching any of these breaks the hop.

**It is a key in three more places outside the UI:**

| where | what |
| --- | --- |
| `control/state.nodes[name]` | the registry is a dict keyed by name |
| `sealing.address_message(name=…)` | **the name is inside the signed announcement**, verified against the key looked up by that name |
| each agent's `node.yaml` | every node persists its own |

**It is DISPLAYED in about ten places across seven screens**: Config's
`Agent @ <node>` tabs and its "Runs on" line, Inference rows and their
removal confirmations, Metrics group headers, the Nodes table, Home's
"Kept on …", the Library folders grid, and the resource tree.

**`updateNode` is not the seam.** Its docstring says *"Deliberately
narrow: this op exists because `Node.url` is applied … a signature over
`{name, sequence, url}`"*. It is the node-signed address path; a label is
operator-set and unsigned. Widening it would put an unsigned field on a
signed op.

**`LogOp` is closed at ten on purpose**, and says so: *"an operation that
is not in this list is an operation that would not replicate. Adding a
mutation means adding an op here."* M9 opened it from nine to ten with a
justification. This slice opens it to eleven, with one.

---

## §1 The shape

**`Node.label`, written by a new `labelNode` op, read by the UI.**

**It is replicated, and that is forced rather than chosen.** Every
console in the install must show the same label, or two operators
describing "the NAS" are describing different machines. Install-wide
state goes through the single writer; this system has exactly one rule
about that and it is the `LogOp` list. A browser-local label would be
cheaper and would fail the first time two people looked.

**The identity never moves.** The label is never a key, never signed,
never in a URL, never in a `node:<name>` target, never the dict key in
`state.nodes`. `Node.name` means exactly what it means today.

**One helper decides.** `nodeLabel(node) => node.label || node.name`, in
`ui/src/lib/`, pure and tested. Ten display sites call it; the fifteen
key sites keep using `.name` and a test asserts they still do.

### Endpoint

`PATCH /v1/nodes/{name}` is taken by the signed announcement, so:

    PUT    /v1/nodes/{name}/label   { "label": "NAS" }   operator-only
    DELETE /v1/nodes/{name}/label                        back to the name

### Validation, and the one rule that matters

Trimmed, capped (64), control characters refused — and **refused when it
collides with any node's real name.** Labelling node A as
`Amish_Station` when that is node B's identity produces an install that
actively lies: two screens say `Amish_Station` and mean different
machines, and the proxy hop goes to the one the label is not. This is
the sharpest failure this slice can create and it is cheap to forbid.

### What happens when the root is down

No labels; every surface falls back to names. The UI already swallows
`installNodes()` errors on purpose (`ui-tree-navigation`: the tree must
survive a sealed root), so this degrades the way everything else does —
the console gets less pretty and stays correct.

---

## §2 Radius

**Two documents, because decision #2 was taken** (§6). The label alone
would be `control.yaml` only — consumers `control` and `ui`. Carrying a
label through `join` adds `agent.yaml`, because enrollment is two hops:

    operator / CLI  ->  agent   POST /v1/node/enroll   (enrollWithControl)
    agent           ->  control POST /v1/nodes/enroll  (enrollNode)

so both request bodies gain an optional `label`. `agent.yaml`'s consumers
are `agent`, `control` and `ui`; the union is **`agent`, `control`,
`ui`** and the other three stay back — **measured by regenerating all six
and diffing, not by counting `$ref`s**
(`polyrepo-spec-codegen-workflow`).

Work: the contracts; control's apply + snapshot + the endpoint; the
agent's `join --label` and its enroll passthrough; both installers, which
already take `--join URL --token JWT` and are the unattended path where
nobody can answer a prompt; the UI helper and ten call sites; the Nodes
screen's edit affordance, since it is already the control-root screen;
`tailnet.md` and `container.md`.

---

## §3 The control host does not join, and this is the gap

**Taking #2 does not fix the case that prompted the slice**, and that is
worth stating plainly rather than discovering during the build.

`--label` rides on `join`, which is how a **worker** enters an existing
install. The **control host never joins**: the first-run wizard enrolls
the local agent itself (M9's *"the control host's own agent never
enrolled"* fix), and it does so with no name at all —

    ui/src/app/setup/start.ts
    await api.post("agent", "/v1/node/enroll", { controlUrl, token: minted.token });

— so the agent falls back to `socket.gethostname()`. On a container that
is the container ID. That is the exact path that produced
`468e3ed662bf`, and a `join` flag never touches it.

Three ways to close it, and they are not exclusive:

1. **`--hostname` in the template** — done (2026-09-16), and it fixes
   every *new* containerised install without any of this slice.
2. **The wizard asks.** One field on the passphrase screen, defaulted to
   the detected hostname, passed as the enroll `name`. This is the honest
   fix for the control host and it is small, but it adds a field to a
   two-screen wizard that S2 deliberately shrank — so it is a decision
   rather than an obvious yes (§6 #5).
3. **The label, applied afterwards** — which is this slice, and is what
   rescues installs that already exist. It is the only one of the three
   that helps `468e3ed662bf` today.

---

## §4 Acceptance

`scripts/node-label-acceptance.sh`, two agents in M7's shape:

1. a labelled node shows its label on every display surface
2. **and its real name on every key surface** — the `node:<name>` hop
   still resolves after labelling, proved from the far agent's access log
3. a label colliding with another node's name is refused
4. the label survives a control-root restart (it is in the log, so it is
   in the snapshot)
5. a sealed root degrades to names rather than to blanks
6. BROWSER: label a node from `/nodes`, see it on Home's "Kept on …",
   and confirm the Config tab for that node still reaches it

Check 2 is the one that earns the slice. The rest are ordinary.

---

## §5 Non-goals

- **Renaming the identity.** Separate, larger, and distributed: control
  moves the record, the agent must rewrite `node.yaml`, and until it
  does its next signed announcement is refused and the node reads as
  down. Worth doing only if the hex string must never appear anywhere,
  including proxy targets, log entries and `?sel=` URLs.
- Labels for components, runtimes or drivers.
- Per-browser labels.

---

## §6 Decisions needed

| # | Question | Recommendation |
| --- | --- | --- |
| 1 | Label in the replicated log, or control config? | **The log.** A config map needs a new `ConfigValueType`, which reaches every consumer through `ConfigField` (the M11 rule) — a six-repo re-pin to avoid a one-op change to a two-repo document. |
| 2 | Also accept a label at join time (`join --label "NAS"`)? | **TAKEN 2026-09-16: yes.** One flag on `join`, through both enroll bodies, and on both installers. Note what it does *not* cover: §3 — the control host does not join, so this helps the next worker and not the machine that prompted the slice. |
| 3 | Show the real name anywhere alongside the label? | **Yes, on the Nodes screen only** — it is the identity, and an operator debugging a proxy hop needs it. Everywhere else the label alone. |
| 4 | Label the control host at first boot from something friendlier than the hostname? | **No.** Guessing a name is how we got `468e3ed662bf`. Detecting one and *asking* is #5; inventing one is not. |
| 5 | Should the wizard ask for this machine's name? | **Recommended yes**, defaulted to the detected hostname, one field on the existing passphrase screen. It is the only thing that stops a fresh container install from enrolling as hex in the first place. The cost is a field on a wizard S2 deliberately cut to two screens, which is why it is a question and not an assumption. |

---

## §7 Effort

Small. One contract change to one document, a narrow op, a pure helper
with ten call sites, one form, one acceptance script. The risk is
concentrated entirely in one question — *did a label leak into a key?* —
which is why check 2 exists and why the helper is a single function
rather than a fallback repeated at each site.
