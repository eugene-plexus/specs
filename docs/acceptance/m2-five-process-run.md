# M2 acceptance — five processes, launched from the library

**Status:** passed 2026-09-08. Script: [`scripts/m2-acceptance.sh`](../../scripts/m2-acceptance.sh).
Follows [M0's four-process run](m0-four-process-run.md).

```
watchdog ──spawns──> gateway
         ──spawns──> inference-driver
         ──spawns──> library
         ──spawns──> llama-server      ← declared at runtime, not in the topology
```

What separates this from M0: **the engine runtime is not written into
`watchdog.yaml`.** It is created the way the UI's Launch button creates
one — read a profile from the library, `POST /v1/runtimes` on the
watchdog with the model's path and the profile's flags. That composition
lives in the caller and crosses two components, which is exactly the
seam no single-component test covers and where M0's run found its two
defects.

The run is written to find rather than to pass. Where the flow still
needs a human step, the script performs that step explicitly and says
so, instead of pre-arranging the install so the gap cannot show.

---

## What it proved

Thirteen stages, all green on the final run.

- **The supervisor spawns a `library`.** A new `ComponentKind`, one line
  in the component-spec table, service token and log prefix threaded
  like every other kind.
- **The library scanned a real directory** — `~/.lmstudio/models`, two
  models from four files, both vision projectors skipped with reasons.
  Nobody typed a model path anywhere in the run.
- **It described the model** it found: `Q4_K_M` / `file_type 15`,
  architecture `qwen35`, 262,144 trained context, 248,320-token vocab,
  17.5 GB across two files, projector attached rather than listed.
- **Reverse lookup by path** resolved to exactly that entry — the join
  the runtime dashboard uses to get from a `Runtime.modelPath` back to a
  library entry.
- **One validator, in the right place.** A profile carrying
  `nGpuLayers` — a flag that does not exist — was stored `201` by the
  library, which validates nothing, and the runtime using it was
  refused `400` by the watchdog, which owns the curated surface. Both
  halves asserted, not assumed.
- **The launch composed cleanly.** Profile fields are `RuntimeSpec`
  fields, so the POST body is a copy. No `host`, no `port` — the
  supervisor binds loopback and assigns the port, and the caller does
  not restate either.
- **The engine reached `ready`** and reported capabilities read back off
  the loaded model: `contextLength 4096` (what the flags asked for, not
  the 262,144 the file was trained at — the two numbers live in
  different components for exactly this reason).
- **The argv is what it should be:**
  ```
  llama-server.EXE --model C:\...\Qwen3.6-27B-Q4_K_M.gguf --host 127.0.0.1
    --port 8090 --alias Qwen3.6-27B-Q4_K_M --ctx-size 4096 --n-gpu-layers 99 --parallel 1
  ```
  An explicit `--model` at the operator's own path. No `-hf`, which
  would have downloaded into llama.cpp's own cache.
- **One completion** through gateway → driver → engine returned `391`.
- **The engine died with the supervisor.** No orphan.

---

## What it found

### 1. Launch declares a runtime; nothing makes it routable

**Stage 9 is the finding.** After the engine reached `ready`, the
gateway listed no models at all:

```
== 9. is it routable yet?
  gateway /v1/models: []
```

The gateway builds its routing table from the **drivers**, and nothing
pointed a driver at a port the watchdog only chose at launch. The model
was loaded, serving, and unreachable.

Stage 10 closes it by hand — `PATCH` the driver's `baseUrl` to the
runtime's `url`, restart the driver — and stage 11 then routes and
completes normally. So everything downstream works; the missing link is
one step in the middle that a human currently performs.

**This is not a bug in what M2 built.** The milestone's scope is
scan / describe / profile / launch, and all four work. But "launch"
stops one step short of "servable", and an operator pressing a Launch
button reasonably expects to be able to chat with the result.

**The contract already anticipates the fix.** `RuntimeSpec.name` is
documented as *"Referenced by an inference-driver's config to say which
runtime it fronts"* — but no driver config field does that. A driver has
`baseUrl`, a literal URL, and nothing else. Closing the gap means giving
the driver a way to follow a runtime by name and resolve its URL from
the watchdog topology, which is the shape the spec already describes.

Who then *creates* the driver — the wizard declaring a pool, or the
launch flow declaring one per runtime — is a routing-policy question,
and routing policy is M5 (swap on demand, idle unload, load balancing
across drivers serving one model). Recorded here rather than solved.

Until it is closed, the UI's post-launch message names the remaining
step instead of implying the model is ready to use.

### 2. A library-launched runtime carries no `binary`

M0's topology hardcoded `binary: <path>`. A profile cannot: asking an
operator for a binary path on a Launch button would defeat M1's
acquisition entirely. So the engine must be **discoverable**, and
discovery precedence is `explicit binary > managed install > PATH`.

The first run failed here — llama.cpp on this box is neither managed nor
on PATH — with the right error, naming all three fixes:

> `no 'llama-server' found for engine 'llama_cpp' — install one with POST /v1/engines/llama_cpp/install, set 'binary' on the runtime, or put it on PATH`

Correct behaviour, worth exercising. A real first run reaches the
managed branch; the script uses PATH so it does not re-download 500 MB
per invocation. Both are genuine origins. Writing the path into the
runtime spec would not have been — the UI never does that.

### 3. A `C:/...` PATH entry does not survive Git Bash

Cost the second run a confusing failure. Git Bash rewrites `PATH` into
Windows form when spawning a native process, and a Windows-style entry
is mangled by that conversion — `shutil.which` in the child returns
`None` and the engine reads as not installed. `cygpath -u` first.

The same POSIX/Windows class as the `SPECS_REF` BOM trap and the
heredoc-backslash trap. Development is Windows, the audience is Linux
and macOS, and every one of these is found only by running the thing.

---

## Running it

```bash
scripts/m2-acceptance.sh
```

Needs a real engine binary and a real multi-gigabyte model, which is why
it is a script and not a pytest — a green CI run that silently skipped
both would be worse than no test at all.

| Variable | Default |
|---|---|
| `EP_ROOT` | `/d/py/eugene-plexus` |
| `EP_WATCHDOG_PY` | the watchdog's venv python |
| `EP_LLAMA_SERVER` | `.../llamacpp/llama-server.exe` |
| `EP_MODEL_ROOT` | `~/.lmstudio/models` — scanned for real |
| `EP_MODEL_NAME` | `Qwen3.6-27B` — substring match against what was scanned |
| `EP_WORKDIR` | `$TMPDIR/ep-m2-acceptance` |

**All four components must import from `EP_WATCHDOG_PY`.** The watchdog
spawns every child with its own `sys.executable`, so the library has to
be installed into the watchdog's venv — the first run of this script
failed on exactly that, which is the standing
`watchdog-venv-is-runtime` trap collecting its fourth victim.
