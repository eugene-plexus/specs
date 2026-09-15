# Library folders, and how every node reaches them

**Status: designed 2026-09-14, on Troy's calls. Build follows in the
same session.** Supersedes the *storage half* of
[`m11-compute-storage-separation.md`](m11-compute-storage-separation.md):
the mechanism M11 built (a path rule on the node's agent, applied at
every spawn, never written onto the declaration) stays exactly as it
is; what changes is **who states the rule and where the operator meets
it**.

---

## The three calls this comes from (Troy, 2026-09-14)

1. **Every model a node runs is under a Library folder.** *"I prefer to
   force all model locations to be declared as library folders. Whether
   the physical directory is on the Library's PC doesn't matter. The
   logical library layer is responsible for cataloging all models
   centrally. If a node runs a model, it must exist in a library
   folder."* A runtime declared from anywhere else is refused with the
   remedy, and `force` does not bypass it.
2. **The reach of a folder is stated once, on the folder.** The scheme
   as built put a row per node per folder on each node's agent, which
   *"puts more manual work on system operators. That work grows
   exponentially as we add nodes and library locations."* The fix is
   the unit: a folder is one exported share, mounted the same way on
   every node of the same OS, so the Library records *where nodes find
   this folder* and every node inherits it. A node carries an override
   only where it differs.
3. **One console.** *"Once a node is connected, I never want to have to
   hop from one node's UI to another node's UI to do anything. If I go
   to enter a node's map for the library directory, I should get a file
   picker as if I was on the remote node."* Recorded as a standing
   principle ([[one-console-never-hop-nodes]]); this slice is its first
   test.

Plus the label complaint that started it: the mapping field was under
**Model storage** as **Model directory mappings**, two names that do
not contain the word the tree, the screens and the docs all use.

## Decisions

Brought with a recommendation each. Calls 1-3 above are Troy's and are
not in this table. The rest are taken as recommended so the build can
proceed; each is his to overturn.

| # | The call | Recommendation | Counter-argument | Status |
| --- | --- | --- | --- | --- |
| 1 | Shape of a folder's reach | A list of mount paths on the folder record; **the path's own shape says which OS it is for** (§2) | An explicit `{os, path}` pair is clearer — but the agent already decides Windows/POSIX from a string's shape (M11 §3), and a second way to say the same thing would drift | taken |
| 2 | `modelRoots` changes type to `library_folders` rather than growing a sibling field | One record per folder, one field (§2, §6) | A sibling `path_mappings` field costs no new value type — but two fields that must agree is the configuration burden call 2 removes | taken |
| 3 | How a worker learns the folders | Request-scoped refresh + a persisted copy; **no background loop** (§3.2) | A loop is simpler to reason about — but the install-wide lookup spends the caller's credential by design and a loop has no caller | taken |
| 4 | `force` bypasses the folder rule | **No.** The override is "add the folder to the Library", one action away (§4) | `easy-default-expert-override` says always leave an override — it does; it is not a query flag | taken (Troy's wording is "force") |
| 5 | Where nodes appear in the tree | **Under Library too**, as "how this node reaches the Library", each with one page; the Library leaf gets the grid (§5) | The tree design measured that machines appear only under kinds that multiply — this is the deliberate exception, recorded in that doc's departures | taken |

---

## 0. What measuring found

Read before the design, because two of these change what "the fix" is.

**0.1 The node dropdown on Library → Models is not what it looks like.**
It is `NodePicker`: whose free memory a fit verdict is scored against
and where Launch runs. The catalogue does not change with it. The only
place that says so is a hover `title`; the operator read it as "which
node's models". A label, not a tooltip.

**0.2 The mapping already works from any console.** `FolderPicker` takes
a `browseTarget`, `ConfigEditor` passes the page's proxy target, and
`configTabFor` yields `node:<name>` for another machine's agent — so
Browse on a worker's mapping from the root's console lists the
*worker's* disk. Call 3 is met for this field today; the failure is
discoverability (the field is under Agents), not mechanism.

**0.3 Every `from` in the live install is a library folder.** The
container's library has one root (`/models`); `Amish_Station`'s one
mapping has `from: /models`. The free-list generality (a `from` that is
any foreign prefix) has zero users. The M11 acceptance run *did*
exercise it — `/srv/models` as a `from` that is nobody's root — which
is exactly the case call 1 forbids, so that check changes (§10).

**0.4 Nothing matches the declared path against the library's folders.**
`validate_spec` checks shape (absolute path, engine, name); admission
checks *existence after mapping*. A path that is absolute, exists on
the node and is under no library folder is accepted today. The 400 M11
added is for "not here", not "not ours".

**0.5 The install-wide library lookup spends the caller's credential and
nothing else** (`install_proxy`, "three properties, each deliberate").
`library_client_for` needs a `Request`. A spawn has none — the runtime
supervisor resolves paths from `get_config` alone. So "the agent
inherits the library's folders" cannot be a live read at spawn; it has
to be a copy the request-scoped paths keep fresh (§3.2). The library's
own config has no such constraint: `GET library/v1/config` with a
`service:agent` token works locally, and the control root's reads
accept any service token (`require_authorized`), so a *gateway's*
start-on-demand call also refreshes.

**0.6 Nodes-times-folders is the wrong unit.** A folder is one share.
On the live install there is one folder and one non-library node; the
row count is 1. At ten nodes and three folders it would be 30 rows,
each typed by hand, each carrying the same UNC path. With the reach on
the folder it is 3 records and 0 rows on any node that mounts the share
where the folder says.

**0.7 What already reads `modelRoots` as strings:** `ConfigEditor`
(suggestions for a mapping's `from`), the setup wizard (writes a
`string[]`), `config.model_roots()` in the library, `m11-acceptance.sh`
(writes `library.yaml` by hand), the container's default variable. A
type change must accept a bare string as a folder with no reach, or
every one of those breaks (§2.2).

---

## 1. The rule

> A node runs a model only from a Library folder. The Library says where
> each folder is on the machines that mount it. A node says only where
> it differs.

Three consequences, each a mechanism below:

- **Declaration:** `POST`/`PUT /v1/runtimes` refuses a `modelPath` that
  is under no Library folder, 400, with the remedy (§4).
- **Resolution:** at every spawn, admission and `compose`, the rules
  are the Library's folder reach **plus** this node's overrides, an
  override for the same folder winning (§3).
- **Editing:** the operator edits folders and their reach on the
  Library's pages, and a node's exception on the Library's page for
  that node — never on an agent page, though the field is still there
  (§5).

---

## 2. The folder record

### 2.1 Shape

`modelRoots` on the library's config trio becomes a list of
`LibraryFolder`:

```yaml
modelRoots:
  - path: /models                      # as the library's host sees it
    mounts:
      - /mnt/models                    # POSIX-shaped: Linux and macOS nodes
      - \\TOWER\models                 # Windows-shaped: Windows nodes
  - path: /models-archive
    mounts: []                         # reached at /models-archive, or not at all
```

- `path` is what it always was: the directory as the library's host
  spells it, the left-hand side of every mapping, the string a
  `RuntimeSpec.modelPath` starts with.
- `mounts` is where **other** machines find the same directory. A node
  picks the first mount whose shape matches its own OS — Windows-shaped
  (drive letter or UNC) on Windows, POSIX-shaped elsewhere — and uses it
  as the `to` of an inherited rule `path → mount`. No mount of its shape
  means no inherited rule, and the path falls through unchanged, which
  is the identical-mount convention and the single-box case.
- The shape test is `is_windows_shaped`, which M11 already uses to pick
  matching rules and separators. One classifier for one question.

### 2.2 Leniency, so nothing that exists breaks

A bare string anywhere a `LibraryFolder` is expected is `{path: <it>,
mounts: []}`. The file, the PATCH body, the default variable and the
wizard all keep working; `GET /v1/config` always returns the object
form. The value type is `library_folders` (§6); a UI that has never
heard of it falls through to the generic JSON editor, which is what
`path_list` did before its renderer existed.

### 2.3 What Discover and the scanner see

Nothing new. `model_roots()` returns the paths; the first is still the
download default; `ModelSummary.root` is still the path string. The
mounts are for nodes, and the library never opens one.

---

## 3. Resolution on a node

### 3.1 Effective rules

```
effective = overrides(pathMappings) ∪ inherited(library folders, this OS)
```

where an override whose `from` equals a folder's `path` replaces that
folder's inherited rule, and the union is then resolved exactly as M11
does: longest `from` wins, ties to the override. `Runtime.localPath`
and `Admission.location.mapping` report the rule that applied, and
`ModelLocation.mapping` gains nothing — a `PathMapping` is a
`PathMapping` whichever side stated it. The *source* of the rule is
reported by the new check endpoint (§5.3), where the operator is
looking.

### 3.2 The copy a worker keeps

The agent holds `library_folders.json` beside `agent.yaml`: the last
folder list it read, with when and from where. It is refreshed on every
request-scoped path that already talks to the library — admission,
`POST /v1/runtimes`, `PUT`, `/start`, `POST /v1/config/test`, and the
new check endpoint — through `library_client_for`, which is where the
caller's credential is. It is read, never fetched, at spawn and in
`compose`.

Why not a loop (decision 3): the install-wide lookup deliberately
carries the request's `Authorization` and nothing else. A background
task has no request. Giving it a minted service token would undo the
property `install_proxy` was built to have. And the moment a spawn
needs the list is always preceded by a request that could refresh it —
create, start, or the boot of an agent whose file already holds it.

When the library has **never** been reached (no file), the node has no
inherited rules and the declaration check (§4) cannot run; both degrade
to M11's behaviour and say so in the log and on the check endpoint. That
is the single-box install with a library that has not started yet, and
a worker on its first minute.

### 3.3 The agent's own field, demoted

`pathMappings` stays, same key, same type, same file — a rename of the
key would rewrite every `agent.yaml`. It is labelled **Library folder
overrides** under a category labelled **Library**, and its description
says what it is now: *"Only where this machine mounts a Library folder
somewhere other than the folder's own mount path. Leave empty."* At
PATCH, a `from` that is not a known Library folder is **rejected** when
the folder list is known, with *"X is not a Library folder; add the
directory to the Library first"*; accepted with a warning when the list
has never been fetched.

---

## 4. The declaration check

In `create_runtime` and `update_runtime`, after `validate_spec` and
before the companion and admission:

- the declared `modelPath` is matched, component-wise, shape-aware,
  against every folder `path` in the node's copy of the list (the same
  `match` the rules use — a folder is a rule with no `to`);
- no match → **400** `model-not-in-library`, title *"Not a Library
  model"*, detail *"`<path>` is not under any Library folder. Add the
  directory that holds it to the Library (Library → Folders), then
  scan. A node runs only what the Library catalogues."*;
- list never fetched → accepted, `log.warning` with the same sentence
  and "the Library could not be consulted", and the check endpoint says
  `libraryConsulted: false`.

`force` is admission's word for "I know it will not fit". It does not
apply here; there is nothing to know better than.

Not checked: that the library has *scanned* the model. A folder just
added, a file just downloaded, a scan not yet run — all launch, and
admission falls back to file size as it does today. The rule is about
where a model *lives*, which needs no scan.

---

## 5. UI

### 5.1 The tree

Under **Library**, one child per machine, in the same order and with
the same names as under Agents — `sel` = `library:node:<name>`
(`library:node` bare on a standalone box, mirroring `agent`). A child's
page menu has one page, **Folders**. The Library leaf gains **Folders**
as its first page, before Models. The exception to "machines only under
kinds that multiply" is recorded in
[`ui-tree-navigation.md`](ui-tree-navigation.md) §14.

### 5.2 The Folders page, `/library/folders`

One component, `LibraryFolders`, two views by selection:

**Library selected — the grid.** Rows are folders, columns are nodes.
The first column is the folder as the library spells it (Browse lists
the *library's* host), then its mounts (two boxes, POSIX and Windows,
each a text input — there is no host to browse until a node is chosen —
with "Browse on…" opening a node picker that browses that node and
copies the result back). Then one cell per node: the path this node
would open, badged **same path** / **inherited** / **override**, with
a status dot from the check endpoint (reachable · missing · unknown).
Clicking a cell opens the node's view. Add folder / remove folder edit
`modelRoots`; nothing here touches an agent.

**A node selected — one column.** One row per folder: the folder, the
path *this node* opens, the badge, the status, and an **Override** box
with Browse — which lists **that node's** disk through `node:<name>`,
per call 3. Clearing the box removes the override. Save writes that
node's `pathMappings`; the same Test the M11 editor had runs the check
endpoint with the unsaved overrides.

Both views degrade: no root or a sealed root means one column, this
machine; a library that cannot be reached means the folder list from
this node's copy with its age shown; an agent that cannot be reached is
a column of "unreachable", not an error page. The page you open when
the mount is wrong must not fail because the mount is wrong.

### 5.3 The check endpoint

`POST /v1/library/folders/check` on the agent, operator-only, body
optional `{pathMappings: [...]}` (unsaved overrides, like
`/v1/config/test`). Answers `LibraryFolderReach`:

```json
{
  "libraryConsulted": true,
  "folderListAgeSeconds": 12,
  "folders": [
    {
      "path": "/models",
      "localPath": "\\\\TOWER\\models",
      "source": "inherited",          // same_path | inherited | override
      "exists": true,
      "isDirectory": true,
      "modelsUnder": 4,
      "modelsReachable": 4,
      "problem": null
    }
  ]
}
```

It is `describe_checks` from M11 with structure instead of prose, plus
`source`. `/v1/config/test` keeps its prose answer and now checks the
*effective* rules, so the generic Test button on the agent's field
stays honest.

### 5.4 Labels

- Agent field: category **Library**, label **Library folder overrides**
  (§3.3). The admission refusal names the new place: *"Library →
  `<node>` → Folders"*.
- Library field: label **Folders**, description rewritten for the
  record shape.
- `NodePicker`: rendered as **Score & launch on: `<node>`**, the title
  kept.

---

## 6. Contract

| Document | Change |
| --- | --- |
| `components/common.yaml` | `ConfigValueType.library_folders`; `LibraryFolder {path, mounts[]}`; `ConfigValueType` description gains the paragraph |
| `library.yaml` | `modelRoots` prose in the config tag; the default-variable paragraph says a default folder has no mounts |
| `agent.yaml` | `POST /v1/library/folders/check` + `LibraryFolderReach`, `LibraryFolderStatus`, `FolderReachSource`; `POST /v1/runtimes` and `PUT` gain the 400 `model-not-in-library`; `pathMappings` prose (overrides); the config tag's prose |

No change to `PathMapping`, `ModelLocation`, `Runtime`, `RuntimeSpec`
or anything the gateway, drivers or control consume.

## 7. Radius

`ConfigValueType` gains a member, so **every consumer's generated models
change** — the M11 rule, measured then by regenerating all six. All six
re-pin. `control`, `gateway`, `inference-driver` are regen-only commits
whose config validators fall through to "unsupported valueType" for a
type they never see.

## 8. Scope

**In:** §2-§5, the two label renames, the m11 script's foreign-root
checks rewritten to the new rule, a new acceptance script, the tree
doc's departure note, the M11 doc's supersession banner.

**Out, deliberately:**

- **Library redundancy.** Troy's answer to "the library is down" and the
  right one; a separate slice. Until then §3.2's copy is the mitigation
  and the check endpoint says how old it is.
- **Transfer or a node-side cache.** Still refused; a folder's reach is a
  mount. The grid makes the mount question visible, which is how we
  learn whether it is a real complaint.
- **Per-model mounts.** A mount is per folder; a model is under one.
- **Mounting the share for the operator.** We say where; they mount.
- **A structured `source` on `ModelLocation`.** The check endpoint
  reports it where the operator looks; admission's answer is unchanged.

## 9. Risks

- **Two editors for one field.** The generic Config editor still renders
  `modelRoots` (as `library_folders`) and `pathMappings`. Both must keep
  working — GUI equality — and both link to the Folders page. Drift is
  bounded by the fact that both PATCH the same key.
- **A stale copy admits a path the library has since dropped.** The
  declaration check runs against the node's copy, refreshed on the very
  request that declares — so only when the library is unreachable *at
  that moment*, in which case it warns. Acceptable; the alternative is
  refusing every launch during a library restart.
- **The shape heuristic misfiles a mount.** A relative or bare-word
  mount has no shape; `validate` rejects it at PATCH with "an absolute
  path, Windows- or POSIX-shaped". Same rule M11's `validate_rules`
  applies to a `from`.
- **The m11 acceptance script encoded the old freedom.** Its check 4-7
  arc declares from `/srv/models`, which is nobody's folder. Rewritten,
  not deleted: the same declaration is now refused for the *new*
  reason, and the mapped launch uses the library's own folder (§10).

## 10. Verification

`scripts/library-folders-acceptance.sh`, M11's two-agent shape on +100
ports, environment cleared, teardown by pid:

1. The library's folder has **two mounts** declared once (a Windows
   `to` = node B's mount directory, and a POSIX decoy that must *not*
   be chosen on this Windows host). Node B has **no** `pathMappings`.
2. Declare a runtime on B from the library's path → **201**;
   `Runtime.localPath` is the mount; the engine's argv opens the mount;
   a completion is served. **The inherited rule was necessary on paper
   only** — the same caveat as M11, printed again.
3. Declare a runtime on B from `/srv/models/<file>` → **400
   `model-not-in-library`**, detail names Library → Folders; nothing
   declared. Also `PUT` on an existing runtime to that path → 400.
4. `POST B /v1/library/folders/check` → one folder, `source:
   inherited`, `exists: true`, `modelsReachable: 1`.
5. PATCH B `pathMappings` with the folder → a second directory holding
   the same bytes → check says `source: override`, and a new runtime's
   `localPath` is the override. PATCH with a `from` that is no folder
   → rejected with "not a Library folder".
6. `GET B /v1/config/schema` labels: category `Library`, field `Library
   folder overrides`; library schema: `library_folders`.
7. The browser (system Chrome, Playwright): sign in on **A's** console,
   tree shows `node-b` under Library, its Folders page shows the row
   with **inherited**, Browse in the Override box lists a directory
   that exists **only on B's side of the fixture** (a marker
   subdirectory created under B's mount, absent from A's root), the
   grid on the Library leaf shows both node columns.
8. `m11-acceptance.sh` re-run green with its rewritten arc.

## 11. Traps known in advance

- **`is_windows_shaped` on a mount decides the OS, so a POSIX decoy
   mount must not be picked on Windows.** Assert it in a unit test with
   both shapes present, and in the acceptance run (§10.1).
- **The declaration check must run before the companion is declared**,
   or a refused runtime leaves a driver behind — the same ordering
   `create_runtime` already keeps for the companion-name check.
- **The Folders page reads four sources** (library config, control
   nodes, each node's agent config, each node's check) and every one is
   soft. A fixture with the root sealed is the first test to write.
- **`?sel=library:node:<name>` has a colon in the name position**;
   `parseSelection` splits on the first colon today. Extend it, and add
   the bare `library:node` case for the standalone box — the first
   tree build dropped every driver on exactly that install.
- **Codegen from each repo's own `.venv`**, never the ambient 3.14 —
   the `ToolCallDelta` incident.
