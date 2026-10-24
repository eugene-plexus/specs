# Row 48, part 2: when the Library is down

Lane LIB. Part 1 (`GET /v1/models` in pages) merged and shipped: library
40d911e, ui e41db18. This document designs part 2, the answer to "the
Library is down", in two parts:

- **48b: keep working without the Library.** Size M, cross-component.
  Repos: agent, gateway, library, ui, specs. Ready to build.
- **48c: a standby Library. Not built** (R48-STANDBY, Troy 2026-10-24:
  Choice 3, 48b alone). Most installs keep their models on one NAS, and a
  standby cannot read the models while that NAS is down. §3 stays as the
  design if this is asked for again.

Sources: the code on every repo's `main` on 2026-10-23 (read for this
design; references below are `A/` agent, `G/` gateway, `L/` library, `C/`
control, `U/` ui); `node-local-model-copy.md` §4.3;
`model-generation-defaults.md`; `library-folders-and-reach.md` §8;
`warm-standby.md`; `rows/row-04.md`.

## 1. What happens today when the Library is down

Most of the install keeps working already:

- **Chat keeps working.** Routing and the gateway's `/v1/models` come
  from the agents and drivers, not the Library (`G/routing.py`). An
  engine that is already loaded keeps serving. The inference-driver,
  Workbench and site-host never call the Library.
- **The gateway never fails a request because of the Library.** Profile
  defaults: fresh for 30 s, then the last values for 300 s more, then the
  gateway's own defaults (temperature 0.7, no max-tokens cap)
  (`G/profiles.py:61-109`). Special tokens: the last known ones, with no
  limit (`G/control_tokens.py:290-319`). Both caches are in memory only.
- **A worker can still start a model when the share is reachable.** The
  launch spec is in `agent.yaml`; the folder list is the saved
  `library_folders.json`; fit falls back to the file size
  (`A/admission.py:1478-1492`).

Four things are wrong:

1. **A worker's own copy is ignored exactly when it is needed.** A copy
   is "current" only when its size and mtime match the source file on
   the share, which the agent reads directly (`A/model_copies.py:406-430`).
   When the Library's machine is down, its share is usually down too. The
   copy is then ignored, and admission refuses with 422 "…is not on
   {node}…" (`A/admission.py:1770-1814`). On a hung SMB mount the `stat`
   can also block. (`node-local-model-copy.md` §4.3 said "against the
   library's own listing"; the code checks the share. The share check is
   kept; the doc text changes.)
2. **A model's settings change silently after five minutes.** After 330 s
   without the Library, the gateway drops the model's profile and uses
   its own defaults. A gateway restart during the outage drops them at
   once. Nothing tells the person.
3. **A Library in safe mode can erase a worker's saved mounts.** After 5
   crashes the agent restarts the Library in safe mode, which ignores its
   config, so `/v1/folders` answers with the default folders and no
   mounts (`L/routes/models.py:48-60`, `L/app.py:70-76`). The agent saves
   whatever it receives (`A/library_folders.py:273`). Read from the code;
   not yet exercised.
4. **There is exactly one Library.** The proxy, the control lookup and the
   default topology all assume one (`A/routes/proxy.py:115-118`,
   `A/install_proxy.py:326-330`, `A/default_topology.py:3-5`). Nothing
   replicates its state: profiles, folder config, the model cache, run
   operations. Control's log holds none of it.

## 2. 48b: keep working without the Library

### 2.1 A worker starts from its own copy when the source cannot be checked

- **A record beside each copy.** When a copy completes, the agent writes
  `<copy>.source.json`: `{source, size, mtime, copiedAt}`. Existing
  copies get one at the next successful check.
- **The check has a time limit.** `_stat` of a source runs in a thread
  with a 5 s limit. A timeout counts as "cannot be checked", not as
  "different".
- **"Cannot be checked" means the folder cannot be read:** the source's
  Library folder root (its mount on this machine) raises an `OSError`
  or passes the time limit. A folder that reads but no longer holds the
  file means the model was removed or moved: the copy is not used, as
  today.
- **When the source cannot be checked**, the copy is used when its own
  size equals the recorded size. The
  runtime gets a note, shown on its card: "Started from this machine's
  copy. \\\\nas\\models could not be checked: the network path was not
  found." The note clears at the next start that checks the source.
- **When the source answers and differs**, the copy is refreshed as
  today. Nothing restarts a running engine when the source comes back.
- **No record and no source** (a copy made before this row, with the
  share down): the copy is not used, and the 422 names the cause: "The
  copy of qwen3-8b on Amish_Station was made before Eugene recorded its
  source, and \\\\nas\\models cannot be checked now."
- **Doc fix:** `node-local-model-copy.md` §4.3 says "against the source
  file", with a pointer here.

### 2.2 The gateway keeps a model's settings while the Library cannot answer

- **The last known profile defaults stay in effect while the Library
  cannot answer**, with no time limit. "Cannot answer" means a transport
  error, a 502/503/504 from the proxy, or the time limit. An answer from
  the Library always replaces them, including "no profile".
- **`profileMaxStaleSeconds` stays** as the expert override. Its new
  default is empty (null), which means "no limit while the Library
  cannot answer"; the schema text and the field say so. 0 keeps its
  meaning, "never use stale values", and a number set by hand is kept.
- **The caches survive a restart.** The gateway writes its profile and
  special-token caches to `library-cache.json` beside its config file,
  at most once a minute and only when they changed. At start it loads
  them as stale, never as fresh.
- **The gateway says so.** `GET /v1/info` gains `library: {reachable,
  since, cause, modelsOnSavedSettings}`. The console's gateway card shows
  one line: "The Library is not answering. 3 models use their last known
  settings."

### 2.3 The agent never saves a safe-mode folder list

- **The Library marks it.** `GET /v1/folders` gains `safeMode: true` when
  the Library runs in safe mode (`library.yaml` `FolderList.safeMode`).
- **The agent keeps its saved copy** when the answer is in safe mode, and
  records why: "The Library is in safe mode, so this machine keeps the
  folder list from 12:04."

### 2.4 The console says what still works

- **One sentence where the Library is needed** (Library, Discover, Home's
  model card, a profile editor), in place of the proxy's raw error: "The
  Library on NAS is not answering (connection refused). Running models
  keep serving, and machines start models from their own copies." The
  details link shows the proxy's cause.
- **Machines shows the Library's state** on its machine's card, with the
  cause and the existing Restart action.

### 2.5 Tests that fail before

- agent: a copy with a record is used when the source `stat` raises, and
  when it blocks past the limit; the runtime carries the note. A copy
  without a record is refused with the new 422 text.
- agent: a safe-mode folder answer does not replace the saved list.
- gateway: with the Library failing, defaults saved 400 s ago still apply;
  a gateway built from a saved `library-cache.json` uses them before any
  Library answer; an answer of "no profile" clears them.
- library: `/v1/folders` in safe mode says `safeMode: true`.
- ui: the Library page with a 502 from the proxy shows the sentence.
- specs: `scripts/r8-profile-checks.py` case `stale-bound` breaks today's
  300 s bound. It changes to break the new rule (stale values dropped
  while the Library cannot answer), and must still be caught.

### 2.6 Acceptance

Branch integration in CI (cross-component). One acceptance script,
`row48b-library-down-acceptance.py`, on Linux and Windows: a control
root, an agent with a gateway, a Library and a stand-in engine, and a
model folder the test can make unreachable (a folder renamed away on
POSIX; a `subst` drive removed on Windows). It stops the Library and
removes the folder, then checks: chat still answers with the profile's
temperature after 6 minutes of fake time (the gateway's clock is
injected); the runtime restarts from the node copy with the note; the
console's Library proxy answers the sentence. Then it restores both and
checks the note clears at the next start.

## 3. 48c: a standby Library (not built)

Troy chose 48b alone (R48-STANDBY, 2026-10-24). This section is kept as
the design, not as work.

This follows control's warm standby (`warm-standby.md`, SB1-SB4) and row
4's promotion rules, with one difference: **a standby Library answers
reads by itself while the active one is down.** Writes wait for an owner
to promote it.

### 3.1 The grant and the credential

- **A `library-standby` grant on one named machine**, given only by an
  owner on Machines, as SB1. One at a time. Removing the grant deletes
  the replica.
- **The standby's agent starts a Library in standby role** when it sees
  the grant, pointed at the active Library through the install's proxy.
- **The credential:** a service token `sub: library-standby`, `aud:
  [library]`, signed by the standby's node key, 15 minutes, valid only
  with the grant. Only the replication route accepts it.

### 3.2 What the standby copies

- **A snapshot every 30 s:** `GET /v1/replica/snapshot` on the active
  Library returns the config (`library.yaml` without secrets), profiles,
  the model cache and `keptFrom` records, with an ETag. 304 when nothing
  changed. These are kilobytes to a few megabytes.
- **Not copied:** run operations in flight (they hold 120 s leases and
  fail with their cause on failover), download partial files, Ollama
  reports (each agent sends them again within 60 s), and catalogue
  tokens. A token is sealed with the active machine's master key, which
  the standby cannot open. After a promotion, Discover names each
  catalogue source that needs its token again.
- **Model ids stay the active Library's.** An id is a hash of the active
  host's path spelling (`L/paths.py:79-82`). The standby keeps those ids
  and paths, and maps each folder to its own mount with the existing
  per-node folder mounts. The standby's card lists any folder it cannot
  reach.
- **Lag** is the snapshot's age, recorded by the active Library when the
  standby pulls (as SB4).

### 3.3 Reads while the active Library is down

- **The agent's proxy falls back for reads.** When the active Library
  does not answer (connection error, 502, or 5 s), a `GET` to the
  `library` target goes to the standby. The answer carries
  `Eugene-Plexus-Replica: <snapshot time>`.
- **The standby refuses writes** with 503: "The Library on NAS is not
  answering. This is its copy on Amish_Station from 12:01, which only
  reads. An owner can make it the active Library on Machines."
- **The gateway's profile reads** then come from the standby, so its
  settings stay current to the last snapshot.

### 3.4 Promotion

- **An owner promotes on Machines:** "Make Amish_Station's Library the
  active one". It takes the passphrase, as control's promotion does.
- **An epoch decides which Library is active.** The promoted Library
  takes epoch n+1. Topology records `{node, epoch}` for the active
  Library; agents route to the highest epoch, as row 4 does for control.
- **The old Library, when it returns**, sees the higher epoch and starts
  as a standby of the new one. It never writes in a folder again until
  an owner makes it active.
- **Automatic promotion is not built.** Two Libraries that both believe
  they are active would both write in the same folders (downloads,
  Keep, relocate, delete).

### 3.5 Tests that fail before

- library: the snapshot route refuses a session-less caller, a token
  without the grant, and any other route with the standby token; the
  standby refuses each write route with the 503 text.
- agent: the proxy sends a `GET` to the standby when the active Library
  refuses, never a `POST`; a returning old Library with a lower epoch
  starts as a standby.
- control: the grant, the epoch record and promotion (a passphrase
  check).

### 3.6 Acceptance

High risk, so an acceptance script in CI on Linux and Windows, and one
adversarial review by a second model. Two agents on one runner (free
ports), each with a Library: grant the standby, change a profile on the
active Library, wait for the snapshot, stop the active Library, read the
profile through the first machine's proxy (from the standby, with the
header), see a write refused with the sentence, promote, write, restart
the old Library and see it follow. Sabotage: a token signed by a machine
without the grant must be refused.

## 4. Files other lanes own

- Row 63 (ENG) owns `A/engines/strata.py` and `L/engine_fit.py`; this row
  does not touch them.
- Row 4 (TRUST) owns `A/standby.py` and `A/machine_trust.py` until it
  merges; 48c starts after it.
- Row 16's `L/routes/models.py` changes are merged; row 22 (relocate) and
  row 65 (Keep) also change it. Merge order decides.

## 5. Calls

- **R48-STANDBY** (answered 2026-10-24: Choice 3): 48b alone. No second
  Library; 48c is not built.
- **R48-STALE** (answered 2026-10-24: Choice 1, as built): the gateway
  keeps a model's last known settings for the whole outage and across a
  restart; experts can still set a limit (`profileMaxStaleSeconds`).
