# Library folders and their reach — acceptance run (2026-09-14)

**Result: ALL CHECKS PASSED — 61 `PASS` lines, zero failures, on the
second execution.** `scripts/library-folders-acceptance.sh`, two agents
on one box (M11's shape, +100 ports, environment cleared, teardown by
pid), a real `llama-server` on a real 1.8 GB GGUF, and the system Chrome
driving `ui/e2e/library-folders.spec.ts` against agent A's console.
Design: [`../design/library-folders-and-reach.md`](../design/library-folders-and-reach.md)
§10 is the plan this followed.

Then `scripts/m11-acceptance.sh`, its foreign-root arc rewritten to the
new rule, **re-ran green: 56 checks, first execution after the rewrite.**

## What was built, in one paragraph

A Library folder carries `mounts` — where Linux/macOS nodes and Windows
nodes find the same directory — and a node inherits the mount of its own
OS shape as a path rule, so the reach of a folder is stated once and a
new GPU box needs nothing typed. `pathMappings` on the agent is that
node's **overrides**, labelled so. A runtime declared from a path under
no Library folder is refused (`400 model-not-in-library`) before any
companion exists, and `force` does not bypass it. `POST
/v1/library/folders/check` says per folder what a node would open and
which rule said so. In the tree, each machine appears under Library with
one page, Folders; the Library leaf gains a Folders grid; Browse in a
node's Override box lists **that node's** disk from whichever console the
operator is at.

## The topology

```
host A (this box)   agent A :8179 -> control :8183, gateway :8180, library :8182
host B (also here)  agent B :8184 -> the runtime, NO library, NO pathMappings
```

`library.yaml` on A, written by hand in the object form:

```yaml
modelRoots:
  - path: 'C:\...\ep-library-folders\nas\models'
    mounts:
      - '/mnt/decoy-models'                       # POSIX: must NOT be taken here
      - 'C:\...\ep-library-folders\node-b\mnt\models'   # Windows: B's mount
```

B's `agent.yaml`: `components: []`, `runtimes: []`, nothing about paths.

## The checks

| # | Section | What passed |
| --- | --- | --- |
| 1 | preflight | binary, model, five components import; every port free; no ambient `EUGENE_PLEXUS_*`; folder, mount (with `only-on-b/` under it) and override directory laid out |
| 2 | this working tree's UI | `npm run build:python` staged the export; the staged export carries `/library/folders` |
| 3 | the install | A's fleet up, B up, both enrolled, the root reaches both |
| 4 | the folder record | `GET library /v1/folders`: one folder, two mounts, object form; library schema `library_folders`; `GET /v1/config` object form; B's schema labels **Library folder overrides** under **Library**; B carries no overrides |
| 5 | B inherits | `libraryConsulted: true` through node-a's agent; `source: inherited`; `localPath` is the **Windows** mount, not the POSIX decoy; exists, is a directory; 1 of 1 models reachable; `library_folders.json` written beside B's `agent.yaml` |
| 6 | the inherited launch | `201` with **nothing configured on B**; `modelPath` untouched; `localPath` the mount; engine `ready`; argv names the mount; B still has no overrides |
| 7 | served | gateway `ready_backends=1`; completion `'OK'` from `qwen-inherited` |
| 8 | not a Library model | control relays `502`; the node answered **400**, not 201 and not 422; detail says why and names `Library -> Folders`; `?force=true` still 400; only `qwen-inherited` declared; no `stray-driver`; a PATCH of the existing runtime to the foreign path is 400 and its `modelPath` unchanged |
| 9 | the override | `/srv/models` as a `from` rejected *"is not a Library folder"*; the folder's override applied; check says `source: override`, `localPath` the override dir; `qwen-override` (autoStart false) resolves to the override while the running runtime keeps the mount; an unsaved override to a missing directory is reported and not saved; clearing returns to `inherited` |
| 10 | the library refuses a bad record | a relative mount rejected naming *absolute*; two POSIX mounts rejected (*a node takes the first of its shape*); the record unchanged |
| 11 | the browser | five Playwright tests passed (below); **B's own access log gained 2 `GET /v1/directories` requests during the browser run**; the override round-trip left B clean |

The five browser tests, from A's console:

1. `node-b` sits **under** the Library row (`[data-tree-children="library"]`), and Library's page menu is `models · folders · discover · config`.
2. The grid has a column for `node-b`; the folder's cell is `data-tone="ok"`, reads *inherited* and the mount; the folder's Windows-mount box holds B's mount.
3. `node-b`'s Folders page: the row is ok, opens as the mount, badged *inherited from the folder*, Override empty; the page menu's `data-sel` is `library:node:node-b`.
4. **Browse in the Override box** opens the picker, the typed path `MOUNT` lists `only-on-b`, *use this folder* fills the Override, **Test** answers *Checked on node-b*, **Save** flips the badge to *override*, **clear + Save** flips it back to *inherited*.
5. `node-b`'s own Config page names the field *Library folder overrides* and says *No overrides.*

## What the first execution found — three harness defects, no product defect

1. **A Windows path inside a CSS attribute selector.** Three browser tests
   located the folder row with `tr[data-folder="${FOLDER}"]` and `FOLDER`
   is `C:\Users\...`; in a CSS string every backslash is an escape, so the
   selector matched nothing and the tests reported *no row for the
   folder*. Escaped now (`css()` in the spec). Same family as the
   selector defects in M9, M10 and step 6: a locator that could not match
   its subject.
2. **A `sed` over JSON-escaped backslashes.** The "update to a path outside
   the Library" check swapped the library path out of a JSON body with
   `sed "s|$LIB_PATH_JSON|…|"`; the pattern's `\\` read as escapes and
   never matched, so the PATCH carried the library's own path and the
   `200` it got was the right answer to the wrong question. The body is
   built explicitly now, and a second assertion confirms the runtime's
   `modelPath` did not change.
3. **A consequence, not a cause:** with the browse test never reaching
   its click, B's log showed no directory listing and that check failed
   too. On the second execution it counted **2**.

The agent's unit test for the PATCH case had passed throughout; the
harness was what disagreed with itself.

## What one box proves and does not

**Proved:** B inherited the folder's Windows-shaped mount with nothing
configured; the POSIX decoy was not taken; the engine opened the mount
while the declaration kept the library's spelling; a completion was
served; a model under no folder was refused with the remedy and `force`
did not bypass it; an override on B won over the inherited mount and
cleared back; an override for a non-folder was rejected; the library
refused a malformed record; the browser saw B under Library, read B's
Folders page, and its picker browsed **B's disk from A's console**, as
B's own access log shows.

**Not proved, and said so:** that the inherited rule was *necessary* —
both agents can open the library's own path on one box (M11's caveat,
unchanged; the live two-machine install is where it is visible); a POSIX
node taking the POSIX mount (this host is Windows — the decoy being
*refused* is the same classifier seen from the other side, and the unit
tests cover both shapes); a share mounted read-only or lazily; library
redundancy, which is the answer to "the library is down" and a separate
slice.

## Numbers

| | |
| --- | --- |
| `library-folders-acceptance.sh` | 61 PASS, 0 FAIL, execution 2 (execution 1: 3 harness failures) |
| `m11-acceptance.sh` (rewritten arc) | 56 PASS, 0 FAIL, first execution |
| library unit tests | 325 passed |
| agent unit tests | 537 passed (20 new; 2 sabotage-checked) |
| ui vitest | 207 passed (11 new) |
| directory listings on B during the browser run | 2 |
