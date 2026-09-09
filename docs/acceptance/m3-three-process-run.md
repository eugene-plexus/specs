# M3 acceptance — three processes, and a model fetched through the UI's own proxy

**Status:** passed 2026-09-09. Script:
[`scripts/m3-acceptance.sh`](../../scripts/m3-acceptance.sh).
Follows [M2's five-process run](m2-five-process-run.md).

```
watchdog ──spawns──> library
ui (next start) ──> /api/proxy/library/… ──> watchdog topology ──> library
```

What separates this from M0 and M2: **every call goes through the UI's
proxy**, not at a component port. That is the seam M3 adds, and the one
no single-component test can reach — the browser knows no component
URLs, so a request has to be resolved through the watchdog's topology by
*kind* before it arrives anywhere. M0's equivalent seam had two defects
in it.

It also reaches the **live** HuggingFace hub rather than a mock. Five of
the behaviours M3 is built on are upstream's, and a mock agrees with
whatever we believed when we wrote it. Cost: about 15 MB transferred and
a minute of wall clock.

The gateway and the inference-driver are not started. They take no part
in discovery; this is the M3 surface, not a smaller version of M2's run.

---

## What it proved

Twenty-seven checks, all green on the final run.

- **The UI's proxy resolves the library by kind.** No `LIBRARY_URL`
  anywhere: the browser asks `/api/proxy/library/…`, the proxy reads the
  watchdog's `/v1/components` with the operator's own bearer token, and
  finds the single entry of kind `library`. Every stage below went
  through that path.
- **`/discover` renders and serves its search box** from a production
  build.
- **Free memory is below total, and that is the number scored against.**
  The run asserts the inequality rather than printing it: 26,272 MiB
  free of 32,607 on this box, the rest already held by the desktop
  before an engine starts.
- **One repo became 25 launchable choices**, with 2 vision projectors
  and 5 other files pulled out — from 30 `.gguf` entries. Every label
  distinct, which is asserted explicitly because that is the defect the
  first live run found (four files all reading `UD-Q6_K`).
- **All 25 carry a fit verdict on the same response.** Discovery and
  guidance are one call; the run fails if any candidate arrives
  unscored.
- **A split candidate is one row of two files, summed.** Scoring the
  file named on the launch line would understate it by 4.35 GiB.
- **Bits per weight is measured for all 25** — `size × 8 ÷ parameters`,
  both terms free from the hub.
- **The recommendation names its arithmetic:** *"UD-Q6_K is the largest
  option that fits entirely in GPU memory at 32,768 tokens: 20.47 GiB of
  weights plus 3.07 GiB of KV cache, 24.54 GiB in total against 25.67
  GiB free."*
- **A remote header read for 12 MB.** `general.file_type = 15`
  machine-read off a 16.5 GB file in one second, and the fit upgraded
  from `estimate` to `metadata` as a result.
- **Hybrid attention detected: 16 of 65 layers.** Asserted, not noted —
  assuming all 65 would over-estimate the KV cache by 4×.
- **A real download, verified.** Destination resolved before a byte
  moved, pinned to commit `4ca720788d1e` rather than a moving branch,
  digest checked before the rename, landed as
  `…/unsloth/Qwen3.8-27B-GGUF/imatrix_unsloth.gguf` — its own upstream
  name, filed under publisher and repo, with no `.part` left behind.
- **The download became a library entry** without a manual scan, and
  that entry answered a fit query.
- **`catalogueEnabled: false` answers 409 through the proxy**, not a
  timeout. The air-gap switch is a configuration, not a failure mode.
- **The model outlived the processes.** The last check runs after
  teardown: deleting us does not delete models.

---

## What it found

### 1. A Git Bash path in a component's config is not the path the component reads

The first honest run failed two checks, and the cause is the same
POSIX/Windows class this project has now met four times.

`EP_MODEL_ROOT` defaulted to `/tmp/ep-m3-acceptance/models`. That is a
Git Bash **mount**, not a directory: bash resolves it to
`C:\Users\…\AppData\Local\Temp\…`, while Python reads the same string as
the drive-relative `\tmp\…` and writes to `C:\tmp\…`. The download
succeeded, the digest verified, and the file was real — it was just in a
place the shell would never look. Both halves were internally correct
and they disagreed about where the disk is.

The fix is to translate at the boundary in both directions: a native
path (`cygpath -m`) goes into the component's config, and the native
path the component reports comes back through `cygpath -u` before the
shell tests it. Sibling of the `SPECS_REF` BOM and the mangled `PATH`
entry, and the reason those are worth writing down.

A weaker version of the check had *passed* before the fix, which is
worse than failing: the un-normalized `\tmp\…` string happened to
satisfy `[ -f ]` while the layout assertion silently fell through to a
`NOTE`. An assertion that cannot fail is not an assertion.

### 2. `library exited rc=1` after auth init is the supervisor, not a crash

Initializing auth restarts every supervised child on purpose — that is
how they receive the master key — so the library that was running a
moment earlier is gone and a fresh one is coming up. The log line reads
like a crash and is not one. The script now waits for the restart rather
than racing it, and says why in a `NOTE`, because the next person to
read that log will have the same moment of doubt.

### 3. The auth response field is `sessionToken`

Not `token`. Both this script and M2's take it from
`/v1/auth/initialize`; the first draft of this one guessed, got an empty
string from a `200 OK`, and reported "no session token" — a confusing
failure whose cause was in the reader, not the responder.

---

## What it does not cover

- **No browser.** Every stage exercises the UI's server and its proxy,
  which is where the M3-specific plumbing is, but nothing here clicks a
  button or looks at a pixel. The candidate table, the fit disclosures,
  the download progress bar and the quant reference have been rendered
  by `next build` and served, not driven.
- **No gateway, no driver, no engine.** Nothing in this run launches a
  model. M2's run covers that, and the routing gap it found is still
  open.
- **One repo, one small file.** The 13.6 MB calibration matrix proves
  the transfer loop; it does not prove a 40 GB download, a resume across
  a process restart, or a pause. Those are covered by the library's own
  suite against a mock transport, which is the right place for them —
  they need a controllable failure, and upstream will not drop a
  connection on request.

---

## Running it

```bash
scripts/m3-acceptance.sh
```

Needs outbound HTTPS, a built UI (`npm run build` in `ui/`), and a
watchdog venv that can import both `eugene_plexus_library` and `httpx` —
M3 added that dependency, and the watchdog's venv is the runtime venv
for every component it spawns.

Everything else is a throwaway: the topology, the config, the model
directory and the downloaded file all live under `EP_WORKDIR` and start
empty.
