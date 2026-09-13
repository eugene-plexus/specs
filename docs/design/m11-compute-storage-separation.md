# M11 — Compute/storage separation (design)

**Status:** designed 2026-09-13; **built and verified the same day** —
§13 is the implementation record and §14 records where the build
departed from this document. Milestone **M11** of
[`local-inference-control-plane.md`](local-inference-control-plane.md),
following [M10](m10-token-streaming.md), which took its number and left
this one as *"decided and undesigned"*.

**What it is.** A library on one machine describes model files that an
engine on another machine has to open. Today the library reports each
model's path *as its own host sees it*, that string is copied verbatim
into a runtime declaration, and the agent on the GPU node opens it —
where it does not exist or, worse, names something else. M11 gives each
node a way to say where another host's model directories are on *its*
disk, applies that everywhere the agent opens a model, and makes the
launch screen say what will happen before the button is pressed. Beside
it, the thing that was asked for at the same time: a **folder picker**
for every path field in the config editor, which needs a directory
listing from the component whose disk the path is on.

**What it is not.** Not a file-transfer protocol, not a node-side cache,
not a managed store. The source thread's most repeated grievance is
Ollama's managed store, and the rule this project keeps is that the
user's files stay where the user put them. The operator mounts the
share; we map the path. **Nothing here moves a byte.**

---

## 0. What scoping this found, before any of it was built

Every milestone since M4 has opened with the things the previous one had
agreed to without checking. Six here; the first two are why this is a
milestone rather than a config field.

1. **The refusal every note relied on does not exist.** `agent.yaml` has
   said since M0 that `POST /v1/runtimes` answers 400 for *"a model path
   that does not exist"*, and the inference-screen record said a
   cross-node launch would meet *"the honest failure (that path does not
   exist here), relayed from the agent"*. Measured against the agent's
   own test app on 2026-09-13, with the path `/srv/models/nowhere.gguf`:

   ```
   admission: 200 admit | admit on faith: /srv/models/nowhere.gguf could not be
              fully measured against device 0 ... required unknown by file size
              warning: /srv/models/nowhere.gguf could not be sized on disk
   create:    201 starting /srv/models/nowhere.gguf
   declared:  ['ghost']
   companion: ['control', 'gateway', 'library', 'ghost-driver']
   ```

   `validate_spec` checks the engine and the flags; `build_argv` passes
   `modelPath` verbatim; admission reads an unsizable file as *unknown*
   and `unknown` never refuses. So a launch of a path this host does not
   have is **accepted**, a companion driver is declared for it, and an
   engine is spawned that dies on a file it cannot open. The operator
   learns about it from a `crashed` runtime a minute later, in
   llama-server's words. There was never anything to relay.
2. **A worker never consults the library.** `_library_client` looks for
   a `library` in the agent's *local* topology, and an enrolled node
   declares none (`should_seed` refuses to seed a control plane onto a
   worker, correctly, since M9). So on the only real multi-host install,
   every admission on the GPU node has been `basis: file_size` — the
   metadata arithmetic M3 built and M6 wired into admission has never
   been used for a launch on the machine that launches. Nothing said so:
   `basis` is on the response and no screen shows it.
3. **The library's identity is its host's spelling of the path.** `id`
   derives from the normalized path, `GET /v1/models?path=` normalizes
   on the library's own platform, and the runtime dashboard links
   `Runtime.modelPath` back through it; admission's `metadata` basis
   goes through the same lookup. Any design that persists a *translated*
   path on the runtime severs that join — with it the fit basis, the
   profile link, and the answer to "which library entry is this
   runtime". That decides §3: **the declaration keeps the library's
   path, and the node resolves its own at the point of use, every
   time.**
4. **A POSIX path on a Windows node is not a missing path; it is a
   different one.** `os.path.abspath("/models/x.gguf")` on Windows is
   `C:\models\x.gguf` — the same trap M3's acceptance run hit with
   `/tmp`. A mapping therefore has to match the declared string
   **before** any local normalization touches it, and on the string's
   own separator convention.
5. **No screen can reach another node's agent settings.** Config's tabs
   are the local agent, the three singletons and every driver, because
   control's `/v1/components` lists *components* and the agent is not
   one. A setting that lives on the worker's agent is invisible from the
   root's console until Config gains an `Agent @ <node>` tab — which it
   should have had anyway: `advertiseUrl` and `vllmBinary` are already
   per-node settings you can edit only from that node's own browser.
6. **`path_list` has promised a picker since M2.** Its contract text:
   *"the UI renders it as an add/remove list of directory pickers"*.
   The renderer has been text rows for three milestones. A picker needs
   a directory listing from the component whose host the path is on,
   and no component has one.

---

## 1. The seam, as an operator meets it

The first two-machine install (2026-09-11) is the shape this is for. The
control plane runs in a container on a NAS: the library's one model
root is `/models`, a bind mount of the NAS's `/mnt/user/models`. The
GPU is in a Windows box down the hall, enrolled as `Amish_Station`.

Discover — scored against `Amish_Station` since the node-scored
guidance work — recommends a quant and downloads it. The file lands on
the NAS, under `/models/<publisher>/<repo>/`, plainly named. The library
lists it. Library → pick `Amish_Station` → Launch. The declaration
carries `modelPath: /models/<publisher>/<repo>/<file>.gguf`, control
forwards it to the worker's agent, and (§0.1) the worker **accepts it**,
declares a driver, spawns `llama-server --model /models/...` — which on
Windows reads `C:\models\...` — and the runtime goes `crashed`.

Meanwhile the NAS exports that very directory over SMB and the box has
it mounted as `Z:\models`. Every file the library described is reachable
from the worker. Nothing knows.

With M11: the worker's agent carries one mapping, `/models` →
`Z:\models`. The same declaration arrives; the agent resolves
`Z:\models\<publisher>\<repo>\<file>.gguf`, checks it exists, sizes it
against what the library said, admits, and spawns the engine on the
local path. `Runtime.modelPath` still says `/models/...` — the library's
name for it, which is what links the runtime to its library entry — and
`Runtime.localPath` says what was opened. The Library screen said all
of this *before* Launch was pressed, and when the mapping is missing it
says that instead, with a link to where it goes.

---

## 2. Where the mapping lives

Three candidates. One measurement decides each.

**On the library, per root per node.** The library would learn node
names from control and answer "where is model X on node Y". Rejected on
three counts: a launch that does not pass through the library — control
forwarding a hand-written declaration, the gateway's start-on-demand,
`POST /v1/runtimes` from a script — would go untranslated; the mapping
is a fact about the *node's* filesystem that the library cannot check;
and the library "holds no engine knowledge and never calls the agent"
(its own info block) and would have to grow node awareness to do this.

**On the control root, as `Node.mounts`.** An install-wide view, and
replicated. Rejected: replicated state needs a `LogOp`, and M9's
argument for opening `LogOp` to ten — applied state that would otherwise
not replicate — does not apply to a fact about one host's mounts, which
is liveness rather than intent; the control root "spawns nothing" and
cannot stat a path, so it could hold the mapping and never verify it;
and the agent would still have to read it before every spawn, so the
data path would gain a dependency on management for no gain.

**On the node's agent, as config — chosen.** `pathMappings` on the
agent's config trio. The node is the only thing that can verify a
mapping (it stats the path); the mapping applies to every route a
foreign path can arrive by (create, update, admission, start, spawn) at
the one place they converge; it is the config trio, so the generic
editor renders it and it is remote-editable, which is the day-one rule;
it persists in `agent.yaml` beside `advertiseUrl`, another fact about
this host that only this host can state; and it needs no change on
control. The cost is §0.5 — an operator at the root's console has to
edit the worker's agent config — and §7 pays it with an `Agent @ <node>`
tab over the `node:<name>` proxy target the console already has.

---

## 3. The rule

`pathMappings` is an ordered list of `{from, to}`:

- **`from`** is a directory *as another machine states it* — in
  practice a library root, spelled exactly as `GET library/v1/config`
  lists it. **`to`** is the same directory on this host.
- **Matching is by path components, not string prefix.** `/models2/x`
  is not under `/models`. The same rule the library's `is_within` uses
  to attribute a model to its root.
- **The `from` decides the convention.** A `from` that starts with a
  drive letter (`Z:`) or a UNC prefix (`\\`) is Windows-shaped: matching
  is case-insensitive and `/` and `\` are interchangeable in the
  declared path. A `from` that starts with `/` is POSIX-shaped:
  case-sensitive, `/` only. The agent cannot know the library's
  operating system, so the shape of the string stands in for it — and
  it is the right proxy, because the string *came from* that system.
- **Matching happens on the declared string, untouched** (§0.4). No
  `abspath`, no `expanduser`, no separator normalization until a rule
  has or has not matched.
- **Longest `from` wins** (most components); ties go to the first
  listed. `to` is used verbatim (`~` expanded), the remainder re-joined
  with *this host's* separator. Nothing matches → the path is used as
  given, so a single-box install behaves exactly as before.
- **Applied everywhere this agent opens a model**: the spawn argv,
  admission's existence check and its file-size fallback, and the
  observed `Runtime.localPath`. **Never written onto the declaration.**
  `RuntimeSpec.modelPath` stays the library's path (§0.3). Because it is
  computed per use, changing a mapping takes effect at the next start
  with nothing re-declared — the "compute per launch so it reverts
  itself" half of the easy-default-expert-override rule.
- **Validation at PATCH** rejects an empty side, a relative path on
  either side (`/…`, `X:…`, `\\…`; `~…` on `to`), and a duplicate
  `from`. Existence is deliberately **not** checked at PATCH: the agent
  already holds that rule for `file_path` ("an operator may point at an
  environment they are about to create"), and a share about to be
  mounted is the same case. `POST /v1/config/test` is where existence
  is checked (§5).

---

## 4. What refuses, and what explains

`Admission` gains **`location: ModelLocation`** — `path` (as declared),
`localPath` (what this host would open), `exists`, `mapping` (the rule
that applied, or null), `sizeBytes` (on this host), `librarySizeBytes`
(what the library says the same file is) and `sizeMatchesLibrary`.

- **`exists: false` refuses.** `decision: refuse`, `fit: unknown`, and a
  `reason` that names the declared path, this node, what it resolved to,
  and the fix — which differs by case. No mapping matched: *"If these
  files live on another machine, mount its share here and map its
  directory: Config → Agent @ `<node>` → Model directory mappings."* A
  mapping matched and its target is missing: *"the mapping `X` → `Y`
  applied and `Y\…` does not exist here; check the mount."* `?force=true`
  still launches, for the same reason it always has — the estimate is
  the operator's to override, and the engine's own error is one line
  away.
- **This is consistent with "`unknown` never refuses".** That rule is
  about a *budget* that could not be measured — a verdict computed from a
  guess is worse than none. A file that is not there is a measurement,
  not a guess. The dry run exists to predict launches, and this is the
  one failure it can predict with certainty; predicting it with
  `admit on faith` and a warning nobody reads is how §0.1 happened.
- **A size mismatch warns, never refuses.** `exists: true` with
  `sizeMatchesLibrary: false` admits with a `warning` naming both
  numbers. The likelier cause is a library scan that is stale after an
  upstream replacement, not a wrong mapping; and the engine will say if
  the file is broken. Explain a real failure; do not predict one.
- **The 400 for a missing path is retired from the contract**, because
  it never existed (§0.1). Its work is done by the 422 the dry run
  already produces, which carries structure a 400 could not.
- **`Runtime.localPath`** is observed on every runtime, live from the
  current mapping — so a stopped runtime shows what the next start would
  open, and a changed mapping is visible before anything restarts.

---

## 5. Reaching the library from a worker

`_library_client` gains a second source. When the local topology has no
library and this node is enrolled, the agent resolves `library`'s owning
node through `InstallTopology.owner_of` — the same lookup the console
hop uses, "address nodes, not components" — and reaches it at
`<that node's agent>/api/proxy/library`, presenting a `service:agent`
token it mints itself (the library's reads accept any service
audience). Three consequences:

1. Admission on a worker is `metadata`-based for the first time (§0.2).
2. `ModelLocation.librarySizeBytes` is fillable, which is what makes the
   size check possible.
3. **A mapping can be tested against real files.** `POST
   /v1/config/test` with a `pathMappings` override lists the library's
   models whose paths fall under each `from`, resolves each through the
   override, and reports how many exist on this host and match in size:
   *"3 of 3 models under /models are reachable at Z:\models; sizes
   match."* That is the Test button beside the mapping editor, and a
   verification that launches nothing.

The lookup spends a credential this node holds: for admission, the
caller's (an operator, or `service:control` when control forwards — the
control root's `/v1/components` accepts either); for the config test,
the operator's. When the lookup fails, admission falls back to file
size exactly as today and logs why — **the data path never gets worse
than it is now.**

---

## 6. The folder picker — a directory listing on two components

`GET /v1/directories?path=&includeFiles=&showHidden=` on the **library**
(its host holds the model roots) and on the **agent** (its host holds a
mapping's `to`, and `vllmBinary`). One pair of shared schemas in
`common.yaml`, `DirectoryListing` and `DirectoryEntry`, so the UI has
one picker; the implementation is duplicated in the two repos —
components share schemas, not code, and it is eighty lines.

- **No `path`** returns the places to start: every drive on Windows,
  `/` on POSIX, and the home directory. **With `path`** it returns that
  directory's children, directories only unless `includeFiles`, hidden
  entries skipped unless `showHidden`. `parent` is given so a picker
  can go up without doing path arithmetic in a browser.
- **Operator-only, and unrestricted.** The operator can already type any
  path into config, and `/v1/config/test` already stats any path they
  name; listing what they could type is not a new capability. It is
  still a directory walk of the operator's disk on request, so it takes
  the strongest credential there is and no service token.
- **Problems** as everywhere: 404 for a path that does not exist, 400
  for one that is not a directory, 403 for one this component may not
  read. An entry the component may not stat is skipped, not fatal.
- **`host`** on the response names whose disk this is, because on a
  multi-host install the answer to "browse" is frequently a machine
  other than the one the browser is on — the same fact Config now prints
  on every tab.
- **UNC paths and un-mounted places are typed, not browsed.** The
  picker keeps a path box beside the list, and a typed path is listed
  from there.
- **Degradation**: a component that does not implement the endpoint
  answers 404; the UI hides Browse and leaves the text field. Every path
  field keeps working as it does today.

`includeFiles` exists so a `file_path` field (`vllmBinary`) can use the
same endpoint later without a contract change. The UI half of that is
deferred; the endpoint half costs three lines and is built.

---

## 7. UI

- **`path_mappings` renderer.** Rows of `from` → `to`. The `from` box
  offers the library's `modelRoots` as suggestions (read from
  `library /v1/config`; failing softly to none), because a mapping's
  `from` is a library root in every case this design is for. The `to`
  box has **Browse** against the tab's own target — the agent whose disk
  it is. The editor's Test button runs `/v1/config/test` with the draft
  as an override, so the mapping is verified against the library's real
  files before it is saved.
- **Browse on every `path_list` row**, against the tab's target — the
  promise from M2, kept.
- **Config gains `Agent @ <node>` for every enrolled node**, over the
  `node:<name>` proxy target, and honours `?tab=` so a link can land on
  one. The banner Config already prints — *"runs on `<node>`, paths in
  these settings are paths on that host"* — is exactly right for it.
- **Library says what Launch will do, before Launch.** The launch panel
  asks the picked node's admission dry run for the default profile and
  renders the location and the verdict: *"On `Amish_Station`:
  `Z:\models\…\x.gguf` · fits"* — or the refusal, with a link to that
  node's mapping tab. It is the same call Launch makes, so there is no
  second opinion to disagree with; and it makes the M6 refusal ("36.0 GiB
  needed, 26.5 GiB free") visible before the click rather than as an
  error after it, which the fit panel above it never quite did (the fit
  panel scores the model; admission scores the *launch*, at the
  profile's context, against what is running).

---

## 8. Contract

| Document | Change |
| --- | --- |
| `common.yaml` | `ConfigValueType.path_mappings`; `PathMapping`; `DirectoryListing`, `DirectoryEntry`, `DirectoryEntryKind` |
| `agent.yaml` | `Runtime.localPath`; `Admission.location` + `ModelLocation`; `GET /v1/directories`; `POST /v1/runtimes` 400/422 prose; `RuntimeSpec.modelPath` prose; the config tag's prose names `pathMappings` |
| `library.yaml` | `GET /v1/directories`; `LibraryModel.path` prose (a path on the library's host, and how a node maps it) |
| `control.yaml` | `POST /v1/runtimes` prose: the spec's path is the library's, and the target node maps it |

**Radius.** A new `ConfigValueType` member reaches every consumer's
generated models through `ConfigField` — M2 learned this with
`path_list` and the M5 re-pin with `url_list`. So all six re-pin, and
each Python consumer's config validator falls through to "unsupported
valueType" for a type it does not emit, as they did then. Measured by
regenerating each side and diffing, never by reading the spec diff.

---

## 9. Scope

**In:** everything above.

**Out, deliberately:**

- **Any file transfer, cache or store.** The rule that made this project
  worth building.
- **Automatic mount detection.** There is no way to know that `Z:\` is
  the NAS's `/models` without comparing content, and comparing content
  is hashing, which is the store arriving by the back door. The operator
  states the mapping; the Test button checks it.
- **Per-model mappings.** A mapping is per directory; a model is under a
  root. A model that is *not* under a mapped root is exactly the case
  the refusal names.
- **The control root learning mounts.** §2.
- **Downloading to a node other than the library's host.** Downloads
  land where the library is; the mapping is how a node reaches them.
  "A model downloaded to the NAS is a model the NAS can serve" becomes
  "…and any node that mounts the share and maps the path", which is the
  sentence `container.md` gets.
- **The file picker for `file_path` fields.** The endpoint supports it;
  the UI is later.

---

## 10. Risks

- **A mapping that points at a look-alike.** A directory with the same
  layout and different files. The size check catches a different file
  of a different size, which is the common case (a stale copy of a
  re-quantized model); a same-size different file is not catchable
  without hashing, and this design says so rather than pretending.
- **Case folding.** A Windows-shaped `from` matches case-insensitively,
  which is right for the files it names; a library on a case-sensitive
  filesystem that really holds `Models/` and `models/` as two roots
  would be mapped as one. Rare enough to accept and visible in
  `localPath` when it happens.
- **A dead network share.** `Path.exists()` on an SMB mount whose server
  is gone can block for as long as the OS takes to give up. Admission's
  location check runs in a worker thread, and the same reasoning the
  library's `test_config` gives for being a threadpool `def` applies: a
  request someone pressed a button to make may block; the event loop may
  not.
- **The install-wide library lookup adds a control-root dependency to a
  worker's admission.** Bounded: the lookup is cached and brisk (2 s
  connect), and on any failure admission falls back to file size, which
  is what it does today.
- **One box proves less than two.** In the acceptance run both agents
  can open the library's own path, so "the mapping was necessary" is not
  demonstrable there — what is demonstrated is that the mapped path is
  the one that was opened, that an unmapped foreign path is refused with
  the fix, and that the library join survives. Necessity is visible only
  on the live two-machine install, which is Troy's to run: mount the
  NAS share on `Amish_Station`, map `/models` to it, launch from the
  root's console.

---

## 11. Verification

`scripts/m11-acceptance.sh`, same-box, two agents — the shape
`m7-acceptance.sh` proved. Agent A spawns control, gateway and the
library, whose one root holds a real 1.8 GB GGUF; agent B enrolls as
`node-b` with **no library** in its topology and a second directory
holding a hard link of the same file — the "mount". Checks, in order:

1. A declaration on B through control of a POSIX-shaped path that does
   not exist anywhere on this box is **refused with 422** (relayed as
   control's 502), and the reason names the path, `node-b`, and the
   mapping fix. Admission's dry run on B says the same with
   `location.exists: false`.
2. `PATCH node-b /v1/config` with a mapping from that foreign prefix to
   B's mount directory. The same declaration is **201**; `Runtime.argv`
   and `Runtime.localPath` name the mount path; the runtime goes
   `ready`; a completion through the gateway is served by it. That is
   the whole of §3 on one host: prefix match, separator translation
   (POSIX `from`, Windows `to`), persistence of the declared path.
3. A second mapping from the **library's own root** to B's mount. A
   declaration of the library's own `path` for the model: 201,
   `localPath` is under the mount, `modelPath` is the library's, and
   `GET library/v1/models?path=<Runtime.modelPath>` still finds the
   entry — the join survives (§0.3). Admission for it on B reports
   `basis: metadata` — **B has no library and reached A's through the
   install** (§5) — and `location.sizeMatchesLibrary: true`.
4. `POST node-b /v1/config/test` with the mapping as an override reports
   the library's models under that root as reachable at the mount, sizes
   matching; with a mapping to a directory that does not exist, it
   names the mount as the problem.
5. `GET /v1/directories` on the library and on B: the roots without a
   path, a real listing with one, 404 for a path that does not exist,
   400 for a file, and **401 without a token**. Hidden entries absent
   by default.
6. Teardown by pid.

Plus, in the repos: a resolver matrix across POSIX-and-Windows shapes
on both platforms (the tests are platform-agnostic by taking the local
separator as a parameter, so CI's Linux and this box's Windows both
exercise both directions); admission's location and refusal; config
validation of the new type; the directory endpoint on both components,
including operator-only; and vitest for the mapping editor, the picker
and the Config tabs.

**What one box cannot prove**, said before the run: that the mapping
was *necessary* (§10); a share that is mounted read-only or lazily; a
Linux `to`. The live install proves the first when it is run there.

---

## 12. Decisions

Brought with a recommendation each. **Taken as recommended on
2026-09-13 in an unattended session** so the build could proceed; each
is Troy's to overturn, and #2 and #4 are the two with a real
counter-argument.

| # | The call | Recommendation | Counter-argument | Status |
| --- | --- | --- | --- | --- |
| 1 | Where the mapping lives | The node's agent config (§2) | Install-wide visibility wants it at control — answered by the `Agent @ <node>` tab | taken |
| 2 | A model that is not on this host refuses admission | Yes: 422 with `force`, structured `location` (§4) | "`unknown` never refuses" — but a missing file is measured, not unknown; and §0.1 is what warning-instead looks like | taken |
| 3 | The directory listing on the library **and** the agent, one shared schema | Yes (§6) | The ask was the library alone — but the mapping's `to` is on the agent's disk and a mapping editor without a picker would be the same bug report | taken |
| 4 | Admission on a worker reaches the library through the install | Yes (§5) | Adds a control-root dependency to the data path — bounded by the file-size fallback, which is today's behaviour | taken |
| 5 | Re-pin all six consumers for one enum member | Yes (§8) | Cost of a commit per repo — the generated models really change, so it is not a version-string commit | taken |

---

## 13. Implementation record

*Filled in after the build — see the bottom of this document.*

---

## 14. Where the build departed from this design

*Filled in after the build.*
