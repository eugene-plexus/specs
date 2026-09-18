# Notes for a future wiki / user guide

**Status: a holding pen, not a document.** Nothing here is written for a reader
yet. It is operator-facing knowledge that surfaced while building — facts a user
guide would need and that would otherwise be lost when engineering notes are
collapsed. **Do not link anyone here.** When a wiki or a user guide is actually
written (R5/R6 territory), these become sections written *for that audience*,
not pasted into it.

Started 2026-09-18, when the completed-milestone memories were collapsed into
component-keyed ones and this material had nowhere else to go.

**Everything below was true when it was measured and carries the date.** Check
before publishing: several items are about upstream projects that move.

---

## 1. Installing

**The one-liner installs everything into one prefix** and touches nothing on
PATH. It brings its own Python (via `uv`), so the machine needs none.

**On Windows, how you run the installer decides what you get:**

| | unelevated | elevated |
| --- | --- | --- |
| location | `%LOCALAPPDATA%` | `%ProgramData%` |
| autostart | logon scheduled task | a real Windows service |
| starts at | your login | boot, without login |
| stopping engines | graceful | hard kill (a service has no console) |

**Do not "re-run it elevated" to fix a problem.** Until R2.2 that switched the
prefix, unregistered the first install's task silently, and stranded its
passphrase, models folder, keyring entry and enrolled workers.

**On Linux the unit is a *user* service**, because the agent reads your model
directories and your keyring. That means it starts at login unless you run
`loginctl enable-linger`, which the installer prints.

**macOS is written and has never been run.** Say so rather than implying
support.

**Upgrading**: the installer stops the running agent first — a Windows process
holds its own `.exe` open. Upgrading a *running* install is a different path
from installing onto a clean machine, and only the second is covered by an
acceptance run.

---

## 2. Reaching the install from another device

**Three things must all be true, and all three fail identically — "connection
refused":**

1. something is listening on an address other than loopback;
2. the node advertises that address;
3. the host firewall lets it in.

Home's *Reach it from other devices* switch sets all three where it can. Notes a
guide will need:

- **A listening socket is fixed for the life of a process.** The switch restarts
  the components; the agent cannot restart itself without being asked, so it
  reports `restartRequired` rather than claiming success.
- **A firewall verdict is not proof.** Host-local traffic is not filtered, so a
  page can load from the LAN address on the same machine while that port is
  genuinely blocked from outside. The only *proof* is `lastReachedFrom` — an
  off-host caller that actually arrived.
- **On Windows you may already be allowed by a PROGRAM rule** created by the
  Security Alert dialog the first time the agent ran. That rule names a
  *versioned* interpreter path and stops applying the day the interpreter is
  upgraded. A rule we add is scoped to ports instead.

**For a headless install, the five environment variables are the reliable
route** (they are read at every process start, so there is no ordering to get
wrong): `EUGENE_PLEXUS_AGENT_BIND_HOST`, `…_CONTROL_BIND_HOST`,
`…_GATEWAY_BIND_HOST`, `…_LIBRARY_BIND_HOST` and **`…_DRIVER_BIND_HOST`** (note:
`DRIVER`, not `INFERENCE_DRIVER`).

**The config-file route has an ordering trap**: enrollment deliberately does not
restart the control root, so an advertise address set *after* the first start
leaves the trust root on loopback in an install that looks healthy.

---

## 3. Running the control plane in a container

- **`/models` must be mounted.** It is deliberately not a `VOLUME` and not
  created by the image: an anonymous volume would be the managed store this
  project refuses to be, and an empty directory would scan nothing and then
  accept a 20 GB download into the container's own layer. Unmounted is reported
  *missing*, health *degraded*, with a log line saying so.
- **A container has no OS keyring** — no Credential Manager, no Keychain, no
  Secret Service — so a restarted control root comes back **sealed**, and every
  health check still says `ok`. Set `securityMode: passphrase_file` and mount the
  secret, or sign in through the browser after every restart.
- **Use a file, not an environment variable, for the passphrase.** `docker
  inspect` shows environment values to anything that can reach the Docker socket,
  including Unraid's own template UI, on screen.
- **Mounting the same secret on a standby removes the promotion caveat** the OS
  keyring carries (the keyring is host-bound; a file is not).
- The image ships as `ghcr.io/eugene-plexus/control-plane:edge`. **`edge`, not
  `latest`** — nothing is released.

### Unraid specifics (read from dockerMan's source, 2026-09-13)

- **Never leave an author template in `templates-user/`.** Force Update recreates
  the container from the *first* `.xml` in that folder, in case-insensitive name
  order, whose `<Name>` matches — so `eugene-plexus.xml` shadows
  `my-eugene-plexus.xml` and reverts your ports **and your Data path** on every
  update. A fresh data directory is a second install whose workers are enrolled
  to a root that no longer exists.
- **`TemplateURL` does nothing** — the function that reads it begins with
  `return;`.
- **No container on Unraid picks up new template fields on its own.** A new path
  or variable must be added by hand on the Edit page of an existing container.
- The template runs the image as `--user 99:100` because Unraid owns appdata as
  `nobody:users`. If you reuse a data directory an older container created, chown
  it (`chown -R 99:100`).

---

## 4. Models on disk

- **Your files stay yours.** Downloads land in your own directories as
  plainly-named files. Delete Eugene Plexus and your models are still there,
  correctly named, where you put them.
- **A moved model reads as a new model.** The old entry goes `missing` and keeps
  its profiles so you can copy them across. Nothing guesses that a file which
  vanished from one folder and appeared in another is the same file — a wrong
  guess would apply one model's tuning to another.
- **Deleting a model in the UI never deletes a file.** It drops the saved
  profiles, which is the only thing the library owns.
- **Every model a node runs must be inside a Library folder.** A folder states
  where other machines reach it **once**, as mounts; nodes inherit the mount
  matching their OS, and a per-node override exists for the exception.
- **On Windows the mount must be a UNC path** (`\\TOWER\models`), not a mapped
  drive letter: the agent runs as a logon task or a service, outside the desktop
  session where the letter was mapped.
- **Over a network share, every start re-reads the whole file.** Measured on
  gigabit SMB: a 23.8 GB model took **3 min 55 s** to load, and later **~10
  min** once llama.cpp's default mmap was accounted for (a mapped read over SMB
  gets 41 MB/s where a buffered one gets 97). The per-node **local copy** toggle
  takes that to **21 s**.

---

## 5. Choosing a model

- **Discover suggests before it asks.** With nothing typed you get the starter
  set — one card naming the model this machine should take, and why.
- **This works with the hub down.** The starter endpoint makes no upstream call.
- **A "fits" verdict is about memory at a stated context**, not about speed, and
  it is scored against **free** memory on **the node you would launch on** — not
  the machine the library happens to run on.
- **On a machine with no accelerator the recommendation inverts to the
  smallest**, because the question a person on a CPU has is about speed.
- **We state what fits, never what is better.** Relative quant *quality* is
  upstream research; the quant reference explains the schemes and scores no
  model.

---

## 6. Connecting your apps

- **Make a client key** — a named, long-lived bearer you can hand to one app and
  take back. It is shown **once**. Turning it off takes effect within the
  routing-refresh interval (15 s by default), not instantly.
- The key works on the three OpenAI paths and nowhere else: it cannot touch
  config, admin or metrics, by the shape of its audience rather than by a list.
- Recipes exist for Continue, Cline, Open WebUI, SillyTavern, OpenCode,
  `OPENAI_BASE_URL`/`OPENAI_API_KEY` and `curl`. **None has been tested against
  the real product** — they are written from each product's documented shape.
- **Claude Code is deliberately absent.** It speaks the Anthropic Messages API at
  `/v1/messages`; this gateway serves the OpenAI shape, so a snippet would 404.
  **Revisit when R4 lands** — that is the slice that adds it.
- **If a request needs failover, do not stream it.** Failover is possible until
  the first token and impossible after it: retrying past that would splice two
  models into one answer with no marker at the seam.

---

## 7. Understanding what you are measuring

- **An external backend's own model load is inside the number.** An Ollama cold
  start is indistinguishable from a slow backend — 5 tok/s against 116.8 on the
  same backend and the same model. Warm up first, and read the sample count next
  to every median.
- **Our tokens/sec is a whole-request rate, not a decode rate.** Prefill and
  backend queueing are inside it, so a 6-token reply scores lower than a
  100-token one from the same engine. Only comparable at the same prompt and
  `max_tokens`.
- **Wake latency is a property of the engine, not of the control plane.** A
  cross-host wake took 21.4 s on vLLM against 2.5 s for llama.cpp on one box, and
  none of the difference was the network.

---

## 8. Troubleshooting notes a guide would want

- **"No models" with everything healthy** usually means the gateway could not
  reach the control root, or the root is sealed. Every other surface says either
  "fine" or "nothing here"; only the root's own API says `503 Locked`.
- **Intermittent 401s between two machines is a clock.** Tokens are accepted
  within a 300 s window; beyond that they are refused, and the symptom appears in
  the *worker's* log while the cause is the other host. Keep time sync running.
- **Engine store sizes:** a Windows CUDA build is ~704 MB unpacked (516 MB
  transferred), and the current plus previous build are retained, so budget
  ~1.4 GB.
- **Windows + CUDA is a two-archive install** — the server zip carries no CUDA
  runtime. If one is missing, the binary dies at load on `cudart64_13.dll`.
- **An engine update never touches a running model.** Builds are versioned and a
  runtime picks up the current build when it next starts — so after an update you
  can be running two builds at once until you restart. Nothing rolls them for you
  yet.

---

## 9. Things to correct before any of this is published

- The Linux + NVIDIA refusal is **gone** (upstream publishes CUDA builds since
  ~2026-09-16). Any older text saying we refuse it is wrong.
- The Vulkan "badge it permanently" degradation was **never built** and is moot.
- `eugeneplexus.ai` is unregistered and is not a decision anyone is waiting on.
- Nothing is released. There are zero GitHub Releases, nothing on PyPI or npm,
  and one container tag called `edge`.
