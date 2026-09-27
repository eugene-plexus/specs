# After a folder's mount changes: the run

**2026-09-27.** Two reports from Troy on the live install, the same hour:

1. After he saved a Library folder's Windows mount, the page said *"Nodes
   pick the change up at their next launch."* He read it as "reboot every
   node". Nothing needed a reboot. Each machine reads the folders when the
   page checks it, and resolves a model's path every time that model starts.
   Only the models already running were left on the old file.
2. Amish_Station then refused to start the model: *"Nothing exists at
   /models/huihui-ai/…Q6_K_L.gguf. If these files live on another machine …
   mount that share here and say where: on the Library folder's mounts"* —
   the mount he had just set.

**Results:**
- The two-machine run (`scripts/library-folders-acceptance.sh`): **61 of 61**.
- The sabotage pass (`scripts/folders-restart-sabotage.py`): **17 of 17 caught**.
  Two of them escaped the first pass (§3).
- The agent suite passes (1,379), and so does the UI suite (1,253).

| Repo | Commit | What changed |
| --- | --- | --- |
| `specs` | `8e52f7c`, `24429e1` | `Runtime.openedPath`; `LibraryFolderReach.libraryError` |
| `agent` | `c53a9db` | the opened path, Restart re-reading the folders, the kept reason |
| `control` | `bf0884f` | regenerated |
| `ui` | `9ea1dfe`, dist `6a55e4c` | the list and its Restart; the named machine |

---

## 1. Why the worker refused

Amish_Station had **never read the Library's folders**. There was no
`library_folders.json` beside its `agent.yaml`. With no folder list it has no
inherited mounts, so it tried the Library's own spelling, `/models/...`.

**The cause is the address the install records for the NAS.** A worker finds
the Library by asking the control root where the Library's node is. Inside a
container, that node's agent registers itself at `http://127.0.0.1:8079/`
(`docs/deployment/container.md`, "tell the container its own address"). The
worker's lookup refuses a loopback address, so it never reads the folders. On
2026-09-12 that address was set by hand. The fresh container made for row 3
would have lost it.

**This reasoning was checked on one box, not on the live install.** Its logs
are private to SYSTEM by design, and the registry needs a token. The one-box
run below shows the path works when the address is right.

**The fix on the live install:** on the NAS, open Config → Agent @ NAS →
Advertise address and set `http://192.168.16.252:8279`.

**The product defect** was that nothing said any of this:
- the lookup's own sentence, which names the fix, went only to an INFO log;
- the Folders check returned `libraryConsulted: false` with no reason;
- the refusal blamed the path.

Now:
- **The node's copy of the folder list keeps why its last read failed.**
- **The Folders check carries that reason** as `libraryError`, and the page
  names the machine in a red box.
- **A refusal that applied no mount says the folders were unread, and why.**
  It no longer tells the operator to set a mount.
- **The loopback sentence names the UI field** (Advertise address).

## 2. The models left on the old file

- **The contract:** `Runtime.openedPath` is the file the running process was
  handed. `localPath` is recomputed on every read, so the two differ exactly
  when the rules moved after that process started.
- **Loading the page, and saving folders or overrides,** now reads every
  machine's runtimes and lists each model that differs.
- **One Restart covers them all.** It sends each restart to that model's own
  machine through `node:<name>`. Restart re-reads the Library's folders
  first, because a restart is a launch.
- **The status line** says which machines have read the folders. It makes a
  promise only for a machine that did not answer, since every model start
  reads the folders. A machine that answered and could not read them gets no
  promise.

## 3. The sabotage pass

- **A crashed runtime reporting its old file escaped the first pass.** The
  only check stopped the runtime, and a stop discards the planner, so the
  status guard was never needed there. The crash test now asserts it.
- **The Restart re-read's anchor matched nothing.** My Python edits wrote
  four files with CRLF endings: `Path.write_text` does that on Windows. The
  files were converted back to LF, and the anchor then matched and was
  caught.

## 4. The acceptance script was stale since row 3

`library-folders-acceptance.sh` is the one script that has a worker read the
Library through the install. It had not been moved to per-node tokens. It
now does four things differently:
- it asks the library with a session addressed to node A;
- it asks node B with node B's own session;
- node B trusts the llama-server directory, which R7 requires;
- node A's join grants `gateway`.

A browser check matched a label that the Config page now shows four times;
it now takes the first.

## 5. Not proved

- **The cause on the live install is unconfirmed** until the Advertise address
  is set and the model starts.
- **The panel's Restart was not driven against a real engine.** Restart itself
  was: the agent's end-to-end test restarts a real process, and `openedPath`
  follows it.
- **A worker whose model runs from its local copy** is left out by design.
  `localPath` then resolves to the copy, so the two paths agree. There is no
  test with a copy.
