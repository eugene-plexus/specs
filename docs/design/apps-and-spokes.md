# Apps: the hub and its spokes

**Status: designed 2026-09-23; calls taken the same day; §10 steps 1-3
(contract, agent, UI) BUILT and live-verified the same day** —
[`../acceptance/apps-run.md`](../acceptance/apps-run.md), 58 PASS. The
chat app (step 4) is next and gets its own design. Troy took calls #1-#7 and
#9 as recommended and **deferred #8: no deposit endpoint until a training
module exists to deposit something.** §11 records where the build departed
from what follows, and why. It came out of a
question about giving the playground a web-search tool. The answer is
that the playground stays a bare diagnostic
([`playground-diagnostic.md`](playground-diagnostic.md): *"no tool
execution"*), and tool execution belongs in an optional chat app. That
app needs a way to exist, and this document describes it.

---

## The idea, in Troy's words

> Eugene's Gateway is the hub, and each module is a potential spoke. The
> end user decides whether they want to use their own spokes or ours, but
> Eugene will still be the hub.

The aim is to be open and flexible, the opposite of Ollama: as easy as
Ollama if that is all you need, and powerful enough to sit at the centre
of someone else's apps. That is why every component has its own repo,
and why the training platform was archived rather than deleted.

Three things were agreed on 2026-09-23 before this document was written:

1. **Our spokes get no back doors.** An app we ship reaches the hub
   exactly the way Open WebUI, OpenCode or a stranger's script would. If
   our app needs something the public contract does not offer, that is a
   gap in the contract, and it gets fixed there for everyone.
2. **The registry is built once; the list of apps is not.** A later
   release adds an app by adding a catalogue entry. The agent needs no
   new code for it.
3. **The hub also consumes what spokes produce.** A weekend
   experimenter's first fine-tune lands in the Library by itself, in a
   folder of its own, with the option to publish it to Hugging Face. So
   "hub" means the whole control plane, not the gateway alone: the
   gateway for inference traffic, the Library for models going in and
   out, and the agent for the machines.

**An app** is an optional, separately installed program the agent
supervises and the console shows. It uses the hub only through public
surfaces. The first three candidates are a chat app with tools, the
Discord `connector` (rewritten), and one day a trainer.

---

## Decisions

Troy's calls. Each has a recommendation so a build can proceed; each is
his to overturn.

| # | The call | Recommendation | Counter-argument |
|---|---|---|---|
| 1 | Whether an app is a new `ComponentKind` or a new collection | **A new collection, `apps`**, beside `components` and `runtimes` (§2) | One collection is simpler, and the supervisor already knows how to run a component |
| 2 | Where an app's Python lives | **Its own environment per app**, built with `uv` (§3) | The agent's venv is how every component runs today (`watchdog-venv-is-runtime`) |
| 3 | How an app's web UI reaches the browser | **On its own port, i.e. its own origin, linked from the console and never embedded or proxied** (§5) | A second port to open, a second sign-in, and one more thing for Reach to cover |
| 4 | What credential an app holds | **A client key minted at install**, named after the app, listed and revocable like any other (§4) | A per-spawn service token never expires on disk and needs no registry |
| 5 | Whether an operator may install an app that is not in the catalogue | **Yes, by repo URL and commit, operator-only, with a plain warning that it runs as this user** (§3.1) | A curated list alone is safer, and a registry of arbitrary code is a supply-chain surface |
| 6 | How a person signs in to an app's own UI | **The app's own sign-in for now**; single sign-on with the console later, if ever (§5.2) | Two passwords on one install is exactly the friction the hobbyist plan removed |
| 7 | Whether the config trio is required of apps | **Required for apps we ship, optional for third-party entries** (§6) | Requiring it of everyone keeps the Config page uniform |
| 8 | How a trainer gets a model into the Library | **A new public deposit endpoint, reached with a client key carrying a `library:deposit` scope** (§8) — **DEFERRED by Troy 2026-09-23: not built until a training module exists to use it** | An internal service call is less work, and it would be a back door |
| 9 | Whether apps become a ninth layer on the architecture page and in the UI registry | **Yes: "Apps", above the front door** (§7) | The eight layers are the site's vocabulary, and a ninth changes the website too |

---

## 1. What the code does today

Measured 2026-09-23 against the current checkouts.

- **There is no app or module concept anywhere.** No design doc, no
  schema and no route. `connector` is deferred and cannot run against
  the current stack: it calls the retired orchestrator's `POST /v1/chat`,
  looks up `orchestrator` and `identity` by kind, and expects HS256 keys
  and a `WATCHDOG_URL` that the agent no longer provides.
- **`ComponentKind` is closed at four values**, and the agent enforces
  that in four places:
  - `_COMPONENT_SPECS` in `supervisor.py:124-177` maps each kind to a
    module and an environment prefix;
  - the proxy resolves only those kinds or a driver name
    (`routes/proxy.py:215-234`);
  - companion drivers are declared by kind (`companions.py:73`);
  - the runtimes routes find the library by kind (`routes/runtimes.py:183`).
- **One unknown kind in `agent.yaml` takes down everything with it.**
  `ComponentEntry.model_validate` raises inside `load()`, and
  `load_or_degrade` then discards the whole topology, every runtime and
  the auth block (`state.py:445`, `:489-512`). An app that later
  releases stopped recognising must not be able to do that.
- **Components receive hub-internal credentials.** Every non-control
  child is handed:
  - the install's verify key;
  - a `service:<kind>` token;
  - for the library and drivers, the master key (`supervisor.py:412-433`).

  The gateway's front door accepts **any** `service:*` token
  (`gateway/dependencies.py:94-98`). So making an app a component would
  give it a credential no third-party spoke can have. That is a back
  door by construction.
- **`POST /v1/components` never checks that the package imports.** A
  missing package loops through five crashes, then five more in safe
  mode, and ends at `crashed` with `lastError: "exited with code 1"`.
- **Every package lives in the agent's own venv**, installed by
  `uv pip install` from GitHub archives at six pinned commits
  (`install.sh:42-49, 377-387`; `install.ps1:105-122, 1181-1190`). On
  Windows a running agent's console-script `.exe` is locked, so the
  agent cannot upgrade packages in its own venv while it runs.
- **Engine acquisition is the closest precedent**
  (`engines/acquisition.py`). It installs into a versioned store
  (`<root>/<engine>/<version>/` plus `install.json`) through a staging
  directory that is renamed into place. It keeps two builds
  (`RETAINED_BUILDS`), reports progress through `resolving → downloading
  → verifying → extracting → done`, and runs one install per engine.
  Updates are operator actions only ("never auto-update",
  `m1-engine-acquisition.md:178`). Kev and MLX already run out of an
  interpreter that is not the agent's (`kevPython`).
- **`uv` stays on disk after install** at `$PREFIX/bin/uv`
  (`install.sh:93`, `install.ps1:287`). Nothing in the agent knows that
  path yet.
- **The console's origin is powerful.** It holds the operator session in
  browser storage and serves an unauthenticated proxy to every component
  (`ui_assets.py:171-175`, `routes/proxy.py:28-33`). The console's own
  files refuse to be framed (`X-Frame-Options: DENY`), but proxied
  responses carry no such header. So an app UI served through the
  console's proxy would run its JavaScript with operator authority.
- **Client keys have the right shape for a spoke.** They carry
  `aud: client`, are accepted only on the gateway's inference doors, are
  scoped by A5 (model allow-list, concurrency, rate), and are revocable
  install-wide by A3. On an enrolled node, minting is forwarded to the
  control root with the operator's credential. **An agent that has not
  enrolled signs with a fresh key on every start** (`app.py:117-119`),
  but every install that finishes the wizard enrols its own agent (M9),
  so this only restricts installs that have not finished setup.
- **Nothing lets anyone put a model into the Library except by writing a
  file into a folder and scanning.** There is no upload or import route.
  A scan is operator-only, and the hub client has no upload call. It is
  read-only, although it does carry an `hfToken`.
- **The tree's branches are hard-coded** (`BRANCH_ORDER`,
  `resourceTree.ts:119-125`). Layers are a closed set copied from the
  website (`navigation.ts:62-155`), and a test asserts there are eight.

---

## 2. An app is not a component

A component is part of the hub. It is in the request path or beside it,
it holds service credentials, and the rest of the hub finds it by kind.
An app sits outside the hub and talks to it. Keeping them in separate
collections is what makes point 1 structural rather than a promise:

| | Component | App |
|---|---|---|
| Declared in | `agent.yaml` → `components` | **`apps.yaml`**, beside it |
| Credential | install verify key, `service:<kind>`, perhaps the master key | **a client key**, and nothing else |
| Python | the agent's venv | **its own environment** |
| Found by | kind, through the proxy | nobody; it finds the hub |
| UI | the console | **its own origin** |
| Added by | a contract change and agent code | **a catalogue entry** |

**A separate file on purpose.** A malformed or unrecognised app entry
degrades the apps collection alone (`apps.yaml.unreadable`, a
`configError` on `/healthz`, the same `load_or_degrade` shape as R1.5).
It never touches the topology or the auth block.

The supervisor's **process** machinery is reused unchanged: back-off,
safe mode, graceful stop with escalation, the Windows Job Object and
health polling. What is new is a second planner, `_AppPlanner`, which
builds argv and environment from a manifest instead of from
`_COMPONENT_SPECS`, and hands over no hub credentials.

---

## 3. Installing an app

The engine store's shape, with Python environments instead of binaries:

```
<install>/apps/<id>/
  <commit>/            one environment per installed version
    venv/              built by uv from the pinned archive
    install.json       {version, commit, installedAt, sizeBytes, python}
  data/                the app's own state, kept across versions
  .staging-<commit>/
```

- **Per-app environments (call #2).** A trainer brings torch; the
  connector brings discord.py; neither belongs in the process holding the
  install's signing key. Uninstall becomes a directory delete. The
  Windows `.exe` lock never arises, because the agent never writes into
  its own venv at run time. `watchdog-venv-is-runtime` is a rule about
  components, and it stays true of them.
- **The pipeline:**
  1. `resolving` checks the pinned commit against the catalogue.
  2. `creating` runs `uv venv` with the manifest's Python.
  3. `installing` runs `uv pip install "<package> @ <archive URL>"`.
  4. `verifying` imports the entry module with that interpreter. This
     closes the "exited with code 1" hole for apps before it can open.
  5. The staging directory is renamed into place, then `install.json` is
     written.

  States, cancellation, one install per app and `RETAINED_BUILDS = 2`
  all match engines.
- **The agent finds `uv`** at the installer's `$PREFIX/bin/uv` (derived
  from `sys.prefix`), then `PATH`, then a `uvBinary` override on the
  config trio. Without it, installing an app is `installable: false`
  with the reason given, and the rest of the product is unaffected.
- **No auto-update**, as for engines. The catalogue names each app's
  pinned commit for this Eugene release. Update is an operator click
  that installs that commit beside the old one; rollback starts the
  retained one.

### 3.1 The catalogue

`apps.yaml` inside the agent wheel lists the apps this release knows,
the same way `starter_models.yaml` ships in the library. A new app in a
later release is a new row.

```yaml
- id: chat
  name: Chat
  summary: A chat app with web search, for people who want one in the box.
  repo: https://github.com/eugene-plexus/chat
  commit: <sha>
  package: eugene-plexus-chat
  python: "3.12"
  entry: eugene_plexus_chat          # run as `python -m <entry>`
  ui: true                           # serves a browser UI on its port
  configTrio: true
  uses: [inference]                  # hub surfaces it needs: §4
  resources: none                    # or `gpu`: §8
```

**Custom entries (call #5):** the operator can add one by repo URL and
commit on the Apps page, with the same fields and a warning that says
plainly the code runs as the install's user with that app's key. This is
how a third-party spoke gets the same supervision ours do, and without
it "use your spokes or ours" only covers ours. Operator-only, never
from a service token, and never fetched from anywhere by itself.

---

## 4. What an app holds

At install, the agent mints a **client key** named `app:<id>@<node>`,
using the operator session that clicked Install. On an enrolled node
that request goes to the control root, as A3 does it. The key's A5 scope
comes from the manifest's `uses`:

- `inference`: every model, A5's default concurrency and rate. The
  operator can narrow both on Home's key list, like any key.
- `library:deposit`: §8.

The token is written once to `apps/<id>/data/client_key` (private file,
the `_private_files.py` pattern). At every spawn the agent hands the app
only:

```
EUGENE_PLEXUS_APP_BIND_PORT   from 8190-8289, allocated like companions
EUGENE_PLEXUS_APP_BIND_HOST   0.0.0.0 only when this node advertises off loopback
EUGENE_PLEXUS_APP_GATEWAY_URL the gateway's advertised URL
EUGENE_PLEXUS_APP_LIBRARY_URL only if `uses` names a library scope
EUGENE_PLEXUS_APP_KEY_FILE    the path above
EUGENE_PLEXUS_APP_DATA_DIR    apps/<id>/data
```

`child_environment` already strips credentials and other prefixes. It
must strip every `EUGENE_PLEXUS_*` variable for apps, not only other
components' prefixes.

**Revoking the key cuts the spoke off,** and it shows in the same list
as every other key. **Uninstalling revokes it.** A third-party spoke is
treated identically, by construction.

Call #4's counter-argument has force. A key on disk that lives for a
year is worse than a token minted per spawn. The recommendation stands
because a per-spawn token would have to be a `service:*` audience, which
§1 showed is a back door, or a new audience the gateway would have to
learn, which is one more thing a third-party spoke cannot have. The
year-long lifetime and the file permissions are the cost, and
revocation is the answer to a leak.

---

## 5. An app's UI

### 5.1 Its own origin, never the console's (call #3)

An app with `ui: true` serves its own UI on its own port. The console's
Apps page shows status and an **Open** link to
`http://<node's advertised host>:<app port>/`, opening in a new tab.
**Not an iframe, and not the console's proxy:** either one would put the
app's JavaScript on the console's origin, beside the operator session
and an unauthenticated proxy to every component (§1). A different port
is a different origin, and the browser keeps the two apart. That is the
whole of the isolation, and it costs nothing to build.

What it costs elsewhere:

- **Reach must cover app ports.** S5's `POST /v1/node/reach` restarts
  components with a new bind host and may add a firewall rule; apps join
  both lists.
- **The proxy loses nothing:** it never served apps.

### 5.2 Signing in (call #6)

The app enforces its own sign-in, since nothing in front of it will. For
the chat app, a passphrase set on first open is enough for now.

Single sign-on with the console would mean the console issuing the app a
token for its own audience. That is a real feature with its own design
(PKCE-shaped, per-app audience) and is deliberately not in this slice.
The counter-argument is recorded because it is right about the friction.

---

## 6. Configuration

Apps we ship implement the config trio (`GET /v1/config{,/schema}`,
`PATCH /v1/config`). The console's Config page renders it with no
app-specific code, reached through a new proxy target `app:<id>` that
resolves to the app's port. The operator's bearer is forwarded as for
components, **but only to the config paths** (the proxy allowlists
`/v1/config*` and `/healthz` for `app:` targets). The console never
drives an app's UI routes through its own origin.

Third-party entries may omit the trio; their page then shows status,
logs and Open only.

**Secrets.** A chat app's search-provider key or a connector's Discord
token is the app's own. It cannot be sealed with the install's master
key, because the app does not get the master key (§4). For now: a
private file in `data/`, with the schema marking the field `secret` so
the console never echoes it. That is weaker than components' sealing and
is recorded as such.

---

## 7. The console

- **An "Apps" branch** in the tree, whose children come from data. Each
  node's `GET /v1/apps` goes through `node:<name>`
  (`one-console-never-hop-nodes`), and machines sit under the branch as
  they do for agents and drivers.
- **An app's pages:** Overview (status, version, `uses`, the key's name
  and a link to it, Open), Config (when the trio exists) and Logs.
- **The catalogue** lives on the install root's Apps page: Install,
  Update, Uninstall (keeping `data/` unless purge is ticked), and Add
  custom.
- **A ninth layer (call #9):** "Apps", drawn **above** the front door,
  added to `navigation.ts`'s `LAYERS` with its own icon, and to the
  website's architecture page. `navigation.test.ts` asserts eight today
  and will fail until both move together, which is the point of that
  test.

---

## 8. The trainer, reserved and not built

Nothing here builds a trainer. It fixes the two surfaces a trainer
would need, so that the registry does not have to change shape when one
arrives.

**GPUs.** An app with `resources: gpu` is admitted like a runtime.
Starting it takes a reservation in the admission ledger (R3.2,
`reservations.py`) for the memory its manifest or its config declares,
so a training run cannot silently take the card from a serving model. It
is refused with numbers when it will not fit, and `force` overrides as
it does for runtimes. Whether a training run should instead be able to
evict idle runtimes is a question for the trainer's own design.

**Deposit (call #8).** A new **public** library endpoint:

```
POST /v1/deposits            {name, files[], source?, card?}
PUT  /v1/deposits/{id}/files/{path}    streamed upload
POST /v1/deposits/{id}/commit
```

- Reached with a client key carrying the `library:deposit` scope. The
  library learns to accept `aud: client` on exactly these paths, the way
  the gateway accepts it on its inference doors, with the same
  revocation guard.
- The Library writes into a folder **it created**, `Trained/` under a
  root the operator picked. That is differentiator #3's own line: *we
  manage what we made and never touch what you put there.* It scans on
  commit.
- Unsloth, axolotl or a script on someone's laptop get the same door
  with a key from the console. That is point 1 applied to model output.
- **Publishing to Hugging Face** is a separate operator action on the
  model's Library page, never something a deposit triggers. Publishing
  is outward-facing and cannot be undone. It needs the hub client's
  first write call and a token with write scope.

---

## 9. What this is not

- **Not in-process plugins.** Nothing loads an app's code into a hub
  process. That is the failure mode the polyrepo rule exists to prevent.
- **Not a marketplace.** The catalogue is a pinned list inside a
  release. Custom entries are an operator typing a URL.
- **Not auto-updating**, like engines.
- **Not a way around the public contract.** If an app needs something,
  the contract grows, and every spoke gets it.
- **Not a change to the playground.** It stays a bare diagnostic, and
  the chat app is one of the clients it diagnoses.

---

## 10. Build order

Each step ships with a check that fails without it. The first app is a
fixture, so the registry is proven before any real app exists to shape
it.

1. **Contract** (`agent.yaml`):
   - `App`, `AppManifest`, `AppCatalogue`, `AppInstall` (states as
     `EngineInstall`);
   - `GET /v1/apps`, `GET /v1/apps/catalogue`;
   - `POST|GET|DELETE /v1/apps/{id}/install`;
   - `POST /v1/apps/{id}/start|stop|restart`;
   - `DELETE /v1/apps/{id}` (`?purge=`), and `POST /v1/apps/custom`.

   Status reuses the component status enum. Radius: `agent`, `control`
   (regen-only) and `ui`; regenerate all six and diff, as always.
2. **Agent:**
   - `apps.yaml` store with isolated degrade;
   - `uv` discovery;
   - the installer (staging, verify-import, retention);
   - `_AppPlanner` with the stripped environment;
   - key minting on install and revocation on uninstall;
   - the `app:<id>` proxy target restricted to config paths;
   - app ports in Reach.

   Acceptance: a fixture app in a throwaway repo, installed from
   nothing, completes one chat request with its key. Then:
   - revoking the key makes the next request 401;
   - a corrupt `apps.yaml` leaves the topology serving;
   - the app's environment shows no hub credential (the fixture dumps
     it).
3. **UI:** the Apps layer and branch, the catalogue page and the app
   pages. Browser acceptance clicks Install through to Open.
4. **Chat app.** Its own repo and its own design doc: the web search
   provider (SearXNG with no key, or a keyed provider), `fetch_url`
   refusing any address that is not `is_global` and pinning the address
   it resolved, a step cap on the tool loop, and read-only tools only.
5. **Connector,** rewritten as a client of `/v1/chat/completions`. It is
   headless, which proves the registry is not shaped around apps that
   have a UI.
6. **Trainer**, whenever it returns: §8's two surfaces, then its own
   design.

---

## 11. Where the build departed, and why

Built 2026-09-23: contract on `agent.yaml` (`/v1/apps`, `/v1/app-catalogue`,
`AppManifest` and friends), `agent/src/eugene_plexus_agent/apps.py` and
`routes/apps.py`, 21 tests in `agent/tests/test_apps.py` (one installs a
real stdlib-only package with `uv` and runs it), and
`scripts/apps-sabotage.py` — **24 sabotages, 24 caught**, after a first
pass that escaped one and named a missing check (the install tools ran
with the hub's variables in their environment; a package's build step is
its author's code).

1. **The manifest names a `source` and a `version`, not a repo and a
   commit.** `source` is what `uv pip install` is given — an archive URL
   at a pinned commit for the shipped catalogue, or a folder on the node
   for a developer's own checkout — and `version` is the label and the
   directory name. A repo-and-commit pair only describes GitHub.
2. **Config goes through the agent, not a proxy target.** §6 proposed an
   `app:<id>` proxy target restricted to config paths. Built instead:
   `GET|PATCH /v1/apps/{id}/config` and `/config/schema` on the agent,
   which checks the operator's session and calls the app on loopback with
   an **admin token the agent generates at each spawn**
   (`EUGENE_PLEXUS_APP_ADMIN_TOKEN`). Two reasons: the app cannot verify
   a hub credential and should never hold one, and an agent route rides
   `node:<name>` like every other per-node surface, which a proxy target
   would not (`one-console-never-hop-nodes`). A `null` in the PATCH is
   forwarded as a `null` — the trio's way of saying *back to the default*
   — and an app that answers with something that is not a config
   document is a 502 naming the app, not a 500 from the agent.
3. **The gateway address for an app on a node without one is the owning
   node's agent proxy**, `<agent>/api/proxy/gateway`, found through the
   control root with the agent's own `service:agent` token (control
   accepts it for reads; there is no operator at a boot). It is the same
   public path a browser uses, reached at the address that node
   announced, so it survives the container's port remap that a
   component's own URL does not (`install_proxy`'s reasoning). On a node
   that runs the gateway it is the gateway itself.
4. **Installing is refused on an agent that has not enrolled.** An
   unenrolled agent signs with a key that changes at every start
   (`app.py`), so an app's key would stop working at the next restart.
   Every install that finishes the wizard enrols its own agent (M9), so
   this only refuses installs that have not finished setup.
5. **Custom entries sit behind `allowCustomApps`, off by default** — the
   posture `allowUnrestrictedEngineLaunch` already has, for the reason it
   has it: this is code the release did not ship, run as the agent's
   user. Catalogue entries need no switch. `uvBinary` sits beside it,
   for a developer install with no installer-provided `uv`.
6. **`resources: gpu` is not in the contract**, for the same reason #8 was
   deferred: nothing uses it until a trainer exists. `AppHubSurface` has
   one member, `inference`, and its description says what arrives with a
   second.

7. **No ninth layer (call #9).** The console files Apps under the
   existing `tools` layer — *"Your tools: anything that speaks the OpenAI
   API, pointed at one URL with one key"* — which is already the layer
   drawn above the front door and describes an app exactly. The call's
   substance (apps sit above the front door) holds; the website's
   architecture page needs no change. The Apps page is the install
   root's, beside Home and Inference, with a machine picker for
   installing; an Apps **branch** appears in the tree once something is
   installed, each app a leaf with Overview and Settings.
8. **`ConfigEditor` takes `endpoints`.** Its defaults are a component's —
   `/v1/config` and `/v1/admin/restart` on its target — and pointed at an
   app's machine they would have edited and restarted the agent. The
   Settings page passes `/v1/apps/{id}/config`, a restart through
   `/v1/apps/{id}/restart`, and no Test button.

The UI: `ui` `fa81e14` (dist `ec4ced9`), `scripts/apps-ui-sabotage.py`
**8 of 8**. The run: `scripts/apps-acceptance.sh`, **58 PASS on the
second execution**; the first failed check 13 whole because a restarted
control root comes back sealed on a keyring-less install, which made the
uninstall's revocation 503 — the rule working, kept as check 12b.

**Not done, named:** rollback to the retained version
has no route (the environment is kept, nothing starts it); an app's own
secrets are a file in its data directory, weaker than components'
sealing; the gateway address is resolved per start and not re-read while
an app runs; nothing has installed an app from an `https://` archive
(the tests and the fixture use a folder source); no browser spec clicks
Install through to Open; and an app on a machine without a gateway has
never sent a request between two machines (the owner-proxy path is
unit-tested only).
