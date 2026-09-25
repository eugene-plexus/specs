# Running the control plane in a container

Path C of [install paths](../design/install-paths-and-distribution.md) §4:
the control plane on an ordinary VM or NAS, with the GPU machines joining it
over the network.

**The container runs a node agent, which supervises the control root, the
gateway and the model library.** One service, not four. That is not a
packaging convenience — `control` is supervised by the local agent like any
other component, every component is handed `<KIND>_AGENT_URL`, and M7's
`Runtime.node` / `advertiseUrl` work presumes an agent per host. A Compose
file that ran the four components directly would be fighting the design.

**It can run models too.** On the CPU as shipped, and on an NVIDIA card
when the host shares one with containers — the Nvidia Driver plugin on
Unraid, or the NVIDIA Container Toolkit anywhere else, the same thing a Plex
container uses. The agent in here is a full agent: it finds the card, fetches
the llama.cpp build that fits it, and launches models exactly as it does on
bare metal. See [Running models in the container](#running-models-in-the-container).
Other machines with GPUs still run [`install.sh`](../../scripts/install.sh)
and `join` this control plane; that is unchanged.

Until 2026-09-23 this document said *"there is no GPU in here and there never
will be"*. That was a packaging decision, not a technical limit, and it is
corrected in [the section that used to argue it](#when-a-separate-gpu-machine-is-still-the-better-answer).

---

## Docker Compose

```sh
git clone https://github.com/eugene-plexus/specs
cd specs
docker compose -f docker/compose.yaml up -d --build
```

Then open `http://<host>:8079/` and finish the first-run wizard.

[`docker/compose.yaml`](../../docker/compose.yaml) is the reference and is
commented throughout — read it before changing anything, particularly the
note about what publishing an un-set-up control plane exposes.

---

## Without Compose — UnRAID, Synology, or any plain Docker host

No clone and no registry needed: Docker can build straight from the
repository URL, fetching it inside the builder.

```sh
docker build -t eugene-plexus/control-plane:0.1 \
  -f docker/Dockerfile \
  https://github.com/eugene-plexus/specs.git#main
```

Make the data directory first and give it to the image's user. **uid 10001
is not an arbitrary number** — the image creates a `plexus` user with it, and
a bind mount owned by anyone else leaves the container unable to write its own
config:

```sh
mkdir -p /mnt/user/appdata/eugene-plexus
chown -R 10001:10001 /mnt/user/appdata/eugene-plexus
```

Then run it:

```sh
docker run -d \
  --name eugene-plexus-control-plane \
  --restart unless-stopped \
  --init \
  --stop-timeout 60 \
  -p 8079:8079 \
  -p 8080:8080 \
  -p 8083:8083 \
  -v /mnt/user/appdata/eugene-plexus:/data \
  eugene-plexus/control-plane:0.1
```

`--init` and `--stop-timeout 60` are the two flags that are easy to drop and
should not be. The agent is a supervisor, so PID 1 in this container has
children and something has to reap them; and on stop it runs its lifespan
shutdown, which is where the gateway closes its metrics database and the
control root closes its replicated log. The runtime's 10-second default would
turn an ordinary `docker stop` into the hard kill that install-paths §12
step 2 went to some trouble to avoid.

### If you would rather use the host's own uid

On UnRAID the convention is `nobody:users` (99:100). That works too:

```sh
docker run -d --user 99:100 ... eugene-plexus/control-plane:0.1
```

with the appdata directory owned by 99:100 instead. The agent does not need a
writable home directory — **verified**: it comes up healthy and supervises all
three components with `$HOME` set to a directory it cannot write. It used to
lose engine acquisition that way, which wrote under `$HOME/.eugene-plexus/engines`;
since 2026-09-23 the image puts engine builds in `/data/engines` and the CUDA
kernel cache in `/data/cuda-cache`, so it loses nothing (CI checks 20 and 27).

### Ports

| Port   | What                                                | Needed by                     |
| ------ | --------------------------------------------------- | ----------------------------- |
| `8079` | Web UI, and the browser's pass-through to everything | you, in a browser             |
| `8080` | The OpenAI-compatible endpoint                       | your tools and agent harnesses |
| `8083` | The control root: enrollment and log replication     | every GPU machine that joins  |

`8082` (the library) is deliberately not published: the browser reaches it
through the agent's proxy on 8079, so exposing it would widen the surface for
nobody. Remap the left-hand side freely if something on the host already has
one of these — `-p 18080:8080` and point your tools at 18080.

### If you remapped a port, tell the container its own address

A container derives its advertise address from the interface it used to reach
the control root — and its control root is in the same container, so it
derives **`http://127.0.0.1:8079/`** and registers that as this node's address.
Correct, and reachable by nothing. The symptom is one-directional and easy to
misread: the control host can reach every GPU machine, and no GPU machine's
browser can reach the control host's gateway or library.

Set it once, in the UI on the control host: **Config → Agent → Advertise
address**, or over the API:

```sh
curl -X PATCH http://<nas>:8279/v1/config   -H 'authorization: Bearer <operator token>'   -H 'content-type: application/json'   -d '{"advertiseUrl":"http://<nas>:8279"}'
```

**Give the address you type in the browser, port included** — which is the
*published* port, not the one the agent binds inside the container. It is
announced to the control root the moment you change it; no restart, no
re-enrollment.

One caveat, and it is why this is a manual step rather than a default. The
agent stamps each component it spawns with *the advertise host plus that
component's own port*, which under a remap names a port the host does not
publish. Nothing consumes those today — the gateway reaches cross-host
**drivers**, which run on bare metal where no remap applies — but do not
build on them from inside a container.

---

## Unraid, from the GUI

There is a Community-Applications-style template in the `specs` repo:

```
https://raw.githubusercontent.com/eugene-plexus/specs/main/unraid/eugene-plexus.xml
```

**Put it where Unraid keeps user templates, under the name Unraid itself
would give it**, then install from the dropdown:

```sh
curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/unraid/eugene-plexus.xml \
  -o /boot/config/plugins/dockerMan/templates-user/my-eugene-plexus.xml
```

**Docker → Add Container → Template → `eugene-plexus`**, under *User
templates*. It fills in the three ports, the Data and Models paths, the
`ExtraParams` that are not optional, and an advanced section for the
passphrase file. Set your host-side values and Apply; dockerMan writes them
back into that same file.

**Why that filename matters more than it looks** is the next section. In
short: never let a second copy of the template sit in that folder under any
other name.

**Leave `--hostname` in `ExtraParams`.** A node's name in this install is
whatever `socket.gethostname()` returns when it enrols, and a container's
default hostname is its own container ID — so without it the control host
joins as something like `468e3ed662bf` and carries that hex string in the
node registry, on its Config tab, in the resource tree, and in Home's
"kept on …" line. **A node cannot be renamed afterwards**: the name is the
registry key, and `PATCH /v1/nodes/{name}` announces an address rather than
a name. Changing it later means un-enrolling and re-enrolling the control
host, which signs everyone out. Set it before the first start, or accept it.

It pulls `ghcr.io/eugene-plexus/control-plane:edge`, which CI builds and
**verifies before pushing** — `scripts/compose-acceptance.sh` runs its
twenty-three checks against the built image, and a failure means nothing is
published. `edge` rather than `latest` on purpose: nothing here is released,
and `latest` is the tag every registry convention reads as "the supported
one".

**One-time, and only the repository owner can do it:** a package pushed by
Actions starts **private**, so the first pull fails with an authentication
error that looks like a bad image name. Make it public once at
`github.com/orgs/eugene-plexus/packages` → control-plane → Package settings →
Change visibility.

### Exactly one template file, and it is named `my-eugene-plexus.xml`

dockerMan saves a container's settings to `templates-user/my-<Name>.xml`.
On every **Force Update it recreates the container from the first `.xml`
file under `templates-user/` whose `<Name>` matches the container**, walking
the folder in case-insensitive name order (`getUserTemplate` in
`DockerClient.php`, `updateContainer` in `CreateDocker.php`; read
2026-09-13 in `unraid/webgui`, `master`). A copy of the author template in
that folder under its own name, `eugene-plexus.xml`, sorts before
`my-eugene-plexus.xml`, carries the same `<Name>`, and wins. The container
comes back with the defaults, ports and Data path both.

That is exactly what happened to the first person to run this template, on
every update, until the copy was removed. Check once:

```sh
ls /boot/config/plugins/dockerMan/templates-user/ | grep -i eugene
# my-eugene-plexus.xml   <- the only line you want
```

Anything else there, delete it, then Edit the container and Apply once so
the `my-` file holds your values:

```sh
rm /boot/config/plugins/dockerMan/templates-user/eugene-plexus.xml
```

Verified on a real box 2026-09-12. The install path above, straight to the
`my-` name, follows from the same code and has not yet been exercised on a
box; the cleanup has.

**What it was not.** For a day this document blamed the template's
`<TemplateURL>` field and removed it. dockerMan's source says that field is
inert: the one function that reads it, `updateUserTemplate`, returns on its
first line ("Don't update templates, but leave code in place for future
reference"), and nothing is ever downloaded from it. Every Community
Applications template carries the field and none of them loses its ports.
The field is back; the shadowing copy was the whole bug.

**It is not only the ports.** The whole file is replaced, so the data path
reverts to `/mnt/user/appdata/eugene-plexus` as well — and unlike a port, that
one is not fixed by retyping it. A fresh data directory is a *second install*,
whose worker nodes are still enrolled to a trust root that no longer exists.
If you customised Data, check it after any update until the folder holds the
one file.

### The data directory must be owned by 99:100

The container runs as `nobody:users`, so the directory you point Data at has
to be writable by that user. Unraid creates appdata that way; **Docker does
not** — a bind-mount source that does not exist yet is created as `root:root`,
and a directory created by an *older* container of this image is owned by uid
`10001`, which is what the image bakes in.

```sh
chown -R 99:100 /mnt/user/appdata/eugene-plexus
```

Skip it and the agent comes up without its log file and says so on the
console; if `/data` itself is unwritable it will get further and fail on
something else. Neither is a bug in the container — both are this one line.

This is the exact failure the template's first user hit, on an appdata
directory an earlier hand-built container had created as uid 10001.

### Adopting a container you already run

The template's defaults are 8079/8080/8083 and
`/mnt/user/appdata/eugene-plexus`. If your existing container uses different
ones, set the template's **host-side** values to match before you hit Apply:

- **Point Data at the directory you already have — and chown it**, per the
  section above; an older container of this image owned it as uid 10001.
  That directory is the install — its identity, enrollment and replicated log. A fresh one is a
  second install, and your GPU machines stay enrolled to a root that no
  longer exists.
- **Keep the control-root host port the same.** Enrolled nodes record the
  *address*, not the name. Move 8083 and every one of them is calling
  somewhere nothing answers, with no error until routing fails.

Container-side ports never change; only the left-hand side of the mapping
does.

**Remapped ports are exactly the settings a shadowing author copy eats**, so
check the folder above before you trust them to survive an update. The author of this
project runs the control plane on 8279/8280/8283 because the defaults clash
with other containers on that box, and re-entered all three on every update
until this was diagnosed.

### What the GUI still cannot do

**Unlock the trust root after a restart** — but the web UI can, on the Nodes
page, and the passphrase file in the template's advanced section removes the
need entirely. See "Unattended unlock" below.

**Pick up new template fields on its own.** The code in dockerMan that would
merge an updated author template into your `my-*.xml` is disabled upstream,
for every container on the box, so a Path or Variable this template gains
later (the Models path on 2026-09-12, the model-directory variable on
2026-09-13) has to be added on the container's Edit page by hand: **Add
another Path, Port, Variable, Label or Device**. A fresh install from the
current template gets them automatically.

---

## Upgrading a control plane that is already running

A rebuild replaces **all six packages**, not one. The six pinned commits live
in `scripts/install.sh`, which the image `COPY`s before running — so a version
bump changes that layer's hash and the rebuild picks it up by itself.
`--no-cache` is not needed, and if the pins have not moved the cache is right
to reuse everything.

**Your data directory is the install.** `agent.yaml` and `node.yaml` are its
identity, `control.yaml` and the replicated log are the trust root's state,
`metrics.sqlite3` is the retained request history. Keep the same `-v` and an
upgrade is an upgrade; point at a fresh directory and you have built a second
install, whose worker nodes are still enrolled to a root that no longer exists.
Nothing needs to re-enroll across an upgrade that keeps the directory.

```sh
# 1. Rebuild. Nothing to clone -- the builder fetches the repo itself.
docker build -t eugene-plexus/control-plane:0.1 \
  -f docker/Dockerfile \
  https://github.com/eugene-plexus/specs.git#main

# 2. Stop the old one, giving it time to shut down properly.
docker stop -t 60 eugene-plexus-control-plane
docker rm eugene-plexus-control-plane

# 3. Run the new one -- the SAME command you used the first time,
#    with the same -v and the same port mapping.
docker run -d --name eugene-plexus-control-plane ...
```

**`-t 60` on the stop is the flag to get right, and it is easy to miss for a
reason that is not obvious: a container's own stop timeout was fixed when it
was created.** If the running container was started without `--stop-timeout
60`, it gets the runtime's 10-second default no matter what the image or this
document says, and you cannot change that without recreating it — which is the
thing you are trying to do. `docker stop -t 60` overrides it for that one
call. Getting this wrong turns an ordinary upgrade into the hard kill that
install-paths §12 step 2 went to some trouble to avoid: the gateway does not
close its metrics database and the control root does not close its log.

**Compose users have none of that to remember**: `docker compose up -d
--build` rebuilds, stops and recreates in one step, and `stop_grace_period:
60s` lives in the file, so it applies to the container being replaced as well
as the one replacing it. The named volume is kept unless you ask for `down
-v` — which is the one command in this document that destroys an install.

**The restart leaves the trust root LOCKED, and nothing says so.** The
control root holds its token key sealed with your passphrase. On
a host install the OS keyring opens it unattended; **a container has no
keyring**, so it comes back initialized-but-locked after every restart --
upgrades included -- until somebody logs in **to the control root itself**.
Until then the gateway cannot read the install's topology, so it routes
nothing.

**Every surface reports healthy while this is true.** Measured on a real
restart: the agent, gateway and control root all answer `/healthz` with
`"status":"ok"`, and the control root's own health even reports
`initialized: true`, `nodes: 2`, `epoch: 1`, `safeMode: false` -- the log is
intact, only the seal is shut. `GET /v1/models` comes back with an empty
`data` array and no explanation. The only surface that says what is wrong is
the control root's own API, which 503s every path with `Locked`:

```sh
curl -s http://<control-host>:8083/v1/nodes | head -c 200
# {"detail":{... "title":"Locked", "status":503,
#   "detail":"This control root is initialized but locked ..."}}
```

**Signing in to the web UI unlocks it, since 2026-09-13.** The login page
posts your passphrase to the agent *and* to the control root, which the
first-run wizard set up with the same passphrase — so the sign-in you do
after an update is the unlock. **An existing browser session does not**:
that login already happened, and it went to the agent, which is not what is
sealed, so every page keeps rendering as if nothing is wrong. Sign out and
in again, or open `/nodes`, which recognises the sealed root and offers its
own unlock form (and is the fallback if the root somehow holds a different
passphrase from the agent). Until one of those, `/v1/models` is empty and
the gateway routes nothing.

**Log in to the control root directly.** It is the one route a locked root
still answers, because it is the way in:

```sh
curl -X POST http://<control-host>:8083/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"passphrase": "your-passphrase"}'
```

A wrong passphrase answers 401 and a locked-out one would answer 503, so the
status tells you which problem you have. Then check `/v1/models` is non-empty
before believing an upgrade landed.

**Or set up unattended unlock once and stop having this problem** — see the
next section. It is off by default because it is a real trade, and it is the
difference between a NAS that reboots at 3am and comes back, and one that
comes back serving nothing.

**Then check what you actually got, from the outside.** A green build log says
the packages installed, not that the running container is serving them — and
the whole point of a pinned upgrade is a capability that was not there before.
Ask the gateway's own schema:

```sh
curl -fsS http://<control-host>:8080/openapi.json | grep -q '"tool_choice"' \
  && echo "tool calling: yes" \
  || echo "tool calling: NO -- still the old image"
```

Only `curl` and `grep`, because a NAS shell may have neither `python3` nor
`jq`. `/openapi.json` needs no token, which `/v1/models` does. For the whole
field list where `python3` happens to exist:

```sh
curl -fsS http://<control-host>:8080/openapi.json | python3 -c \
  'import json,sys; print(sorted(json.load(sys.stdin)["components"]["schemas"]["ChatCompletionRequest"]["properties"]))'
```

A build carrying tool calling lists `tools`, `tool_choice` and
`response_format` alongside the original nine fields. One that does not lists
exactly `max_tokens messages model seed stop stream temperature top_p user` —
which is what every agent harness sees as "this server cannot take my tools".
**`/healthz` reports `0.1.0` on both and cannot tell them apart**, which is why
the check is against the schema and not the version.

---

## Unattended unlock

Skip this and every restart of this container needs a person at a browser.
Set it up and the install comes back on its own.

The trust root seals its token key with your passphrase. On a
host install the OS keyring opens it unattended; a container has no keyring,
so it needs the passphrase from somewhere. **Point it at a file.**

```sh
# 1. Put the passphrase in a file. printf, not echo -- see below.
printf 'your-passphrase' > /mnt/user/appdata/eugene-plexus-secret
chmod 400 /mnt/user/appdata/eugene-plexus-secret

# 2. Mount it and name it, adding these to your existing docker run:
#      -v /mnt/user/appdata/eugene-plexus-secret:/run/secrets/passphrase:ro
#      -e EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE=/run/secrets/passphrase

# 3. Turn it on, once, in the UI: Settings -> Security mode ->
#    "Passphrase file auto-unlock". Or over the API:
curl -X PATCH http://<control-host>:8083/v1/config \
  -H "Authorization: Bearer <operator token>" \
  -H "Content-Type: application/json" \
  -d '{"securityMode": "passphrase_file"}'
```

With Compose, use a real secret rather than a bind mount:

```yaml
secrets:
  control_passphrase:
    file: ./control-passphrase

services:
  control-plane:
    secrets:
      - control_passphrase
    environment:
      EUGENE_PLEXUS_CONTROL_PASSPHRASE_FILE: /run/secrets/control_passphrase
```

**A file and not `EUGENE_PLEXUS_CONTROL_PASSPHRASE=...`**, which is the
obvious move and is the wrong one here. The agent spawns every component with
a copy of its own environment and filters nothing, so a passphrase in the
environment is handed to the gateway, the library and every inference-driver;
and `docker inspect` shows environment values to anything that can reach the
Docker socket, including your NAS's own container template, in a text box on
screen. A file is neither broadcast into every process nor visible to
`inspect`. Be honest about what it does not buy: inside one container every
process runs as the same user and can read the file, so this is about not
*spreading* the secret, not about hiding it from your own components.

**`printf`, not `echo`.** `echo` appends a newline. One trailing newline is
stripped for exactly this reason, so `echo` works too — but nothing else is
trimmed, because a passphrase may legitimately start or end with a space and
silently trimming it would present as "my passphrase is not accepted" with
nothing to distinguish it from a typo.

**What this trades away.** Anyone who can read that file can unlock the
install without knowing the passphrase. That is the same reduction the OS
keyring makes, moved from "can run code as this user" to "can read this
path". It is off by default for that reason. It buys an install that survives
a power cut with nobody present.

**It is also better than the keyring in one way.** The keyring is host-bound,
so a standby control root on another machine cannot inherit auto-unlock and
asks for the passphrase at promotion — which is fine when a human is doing
the promoting and not fine at 3am. A file is not host-bound: mount the same
secret on the standby and a failover needs nobody either.

If the file is missing, unreadable or holds the wrong passphrase, the root
comes up locked, says which of those it was in the log, and leaves your file
alone. `POST /v1/auth/login` still works, so the way out is always open.

---

## Where the models go

The library runs **in this container**, so the only directories it can
see are the container's own — and none of those is anywhere a GPU node
can reach. Two facts follow, and the whole setup is making them meet:
**the library's directory has to be a mounted share, and every GPU node
has to mount the same share.**

### 1. Give the container the directory

Map the directory you keep models in — or want to — to **`/models`**
inside the container. The UnRAID template calls it **Models** and
defaults to the user share `/mnt/user/models`; Compose has the line
commented, one edit away. **That is the whole library-side setup.** The
image tells the library that `/models` is where the models are
(`EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS`, set in the Dockerfile), so
a fresh container scans it at startup with nobody having opened Config,
and downloads from Discover land there. The files are catalogued as they
are; nothing is renamed, hashed or moved; delete the container and they
are still where you put them.

It is a *default*, not a lock. **Config → Library → Model directories**
shows `/models`, you can replace it with other directories, and clearing
the list returns to it. It is never written into your config file, so a
container that came up before this default existed — with an empty list
saved from its first boot — picks it up on the next start with nothing
to edit.

**If your container predates the Models path** (the template gained it on
2026-09-12; an existing `my-eugene-plexus.xml` does not grow new fields
by itself): Edit the container → **Add another Path, Port, Variable…** →
Config Type *Path*, Container Path `/models`, Host Path your share →
Apply. Until then the library reports `/models` as **missing**, its
health as **degraded**, and its log says what that means:

```
[library] WARNING: /models does not exist -- in a container that means nothing is mounted there.
```

That is deliberate. The alternative — an empty `/models` baked into the
image — would scan nothing and then accept a 20 GB download into the
container's own writable layer, where the next update deletes it.

### 2. Let the GPU machines reach the same files

A GPU node launches a model by path, and the library only knows the path
on *its* host. So the node needs the files, and it needs to know where
they are. **The files come from a share** — the NAS's, mounted on the
GPU box however you already mount things:

- **UnRAID:** the directory is already a user share. Export it: **Shares
  → models → SMB Security Settings → Export: Yes**, with Security
  *Private* and a user that can read it (write too, if you want to be
  able to delete models from that machine), or *Public*. Linux GPU boxes
  can use NFS instead: **NFS Security Settings → Export: Yes**.
- **Windows GPU box — a service since R2.6 (2026-09-18), which changes
  the answer.** This bullet has now been wrong twice, in opposite
  directions, and the corrections are kept because the shape of the
  mistake is the useful part: it first said the agent runs "not in your
  desktop session" (false for the old default, and why a mapped `Y:`
  worked on the live worker), then described two installs of which the
  service was the rare one. It is now the ordinary one.
  - **A Windows install is a service.** It runs as LocalSystem: **a
    mapped drive letter does not exist**, and the share credential you
    once typed into File Explorer is in *your* profile and invisible to
    it. **Use the UNC path**, and put the login in **Config → Agent →
    Storage → Logins for file servers** — one row per server, which is
    all Windows allows.
  - **A share with no password is not a share anything can open.**
    Measured on the live install: Windows 11 refuses an unauthenticated
    guest connection by default (`EnableInsecureGuestLogons` is 0), so a
    Public UnRAID share answers `WinError 1272` to a service that has no
    credential. A row under Logins for file servers is the fix; turning
    guest logons back on machine-wide is not, and Eugene will not do it
    for you.
  - **`install.ps1 -NoService`** keeps the old per-user install — your
    own session, your drive letters, your saved credentials — at the
    cost that it starts at sign-in and stops at sign-out.
  - Either way the UNC path is the portable answer, and it is what the
    folder's Windows mount should carry.
- **Linux GPU box:** mount it where you like (`/mnt/models` via `fstab`,
  NFS or CIFS); the folder's mounts, below, say where.

**Then one setting, on the folder, once** (2026-09-14): **Library →
Folders**, the row for `/models`, two boxes — *mounted on Windows nodes
at* `\\TOWER\models`, *mounted on Linux/macOS nodes at* `/mnt/models`.
Every node of that kind inherits it; a new GPU box needs nothing typed.
The rest of the path is carried over, so one folder record covers every
model under it. A machine that mounts the share somewhere else gets one
override under **Library → `<node>` → Folders**, whose **Browse** lists
that machine's own disk from whichever console you are sitting at, and
whose **Test** checks the unsaved override against the library's real
files on that node. (Before 2026-09-14 the same row lived on every node's
agent as *Model directory mappings*, one per node per folder; those rows
still work, as that node's overrides.)

**A node can keep its own copy since 2026-09-17, and by default does not.** A
model downloaded to the NAS is a model any node that mounts the share can
serve, read over the wire on every start; turn the per-node copy on and the
first start copies it once to local disk and every start after that is local.
Measured on the live install: **21 s to serving against 266 s** for a 23.8 GB
model. The copy lives in a directory we created, named at the model's own
relative path, and is deleted by us — your Library folder is never written to.
See `docs/design/node-local-model-copy.md`. Skip the mount and the
Library screen says so before you press Launch: *"Not on `<node>`:
`/models/…` does not exist there"*, with a link to the setting; a launch
that slipped past is refused the same way, with the same fix in the
message. Before M11 it was accepted and crashed at spawn. **And a node
runs only what the Library catalogues**: a runtime declared from a path
under no Library folder is refused outright (*"is not under any Library
folder"*) — add the directory under **Library → Folders** first.

The declaration keeps the library's spelling. `Runtime.modelPath` stays
`/models/…` — that is what links the runtime to its library entry — and
`Runtime.localPath` on the Inference screen shows what the node actually
opened. Change the folder's mount or a node's override and the next
start uses it; nothing has to be re-declared.

**One thing to expect the first time:** without the per-node copy, the engine
reads the weights over the network on every cold start, and it is slower than
arithmetic suggests. Measured 2026-09-17 on the live install: a ~24 GB model
over gigabit took **ten minutes**, not the three this paragraph used to claim —
because llama.cpp memory-maps the file by default and **a mapped read over SMB
gets 41 MB/s where a buffered read gets 97 and a plain copy gets 113.6**
(`--load-mode none` on that runtime brought it to 4m16s). It is visible on the Inference screen as
`loading` — **with a real progress bar only on the buffered path**
(`--load-mode none`), because a memory-mapped read moves no counted bytes, so
the default path shows elapsed time instead. Either way it is a state, not a
hang. **Turning the
per-node copy on takes the second and every later start to 21 s.**

---

## Running models in the container

The container is a node like any other: it shows up under **Library →
score & launch on** by its hostname (`eugene-plexus`), and a model launched
there runs in the container, beside the gateway that serves it.

**On the CPU** nothing needs setting. That suits a small model on a NAS with
nothing else to run it; the starter set picks the smallest one for a machine
with no accelerator, for exactly that reason.

**On an NVIDIA card**, the host has to share the card with containers first:

- **Unraid:** install the **Nvidia Driver** plugin from Community
  Applications (if Plex already uses the card, it is installed). On the
  container's **Edit** page:
  1. Set **NVIDIA GPU** to the card's GPU UUID from the plugin's page, or
     `all`.
  2. Switch to **Advanced View** and add `--runtime=nvidia` to **Extra
     Parameters**, after what is already there.
  3. **Apply.**

  Both steps or neither. The variable alone does nothing, and
  `--runtime=nvidia` on a server without the plugin stops the container from
  starting, which is why the template does not ship it. On a container
  created from an older template the **NVIDIA GPU** field is not there; add
  it with **Add another Path, Port, Variable, Label or Device** → Variable,
  key `NVIDIA_VISIBLE_DEVICES`. Unraid never merges new template fields into
  a container you already have (see [What the GUI still cannot
  do](#what-the-gui-still-cannot-do)).

- **Compose:** with the NVIDIA driver and the [NVIDIA Container
  Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  installed on the host, uncomment the `deploy:` block in `compose.yaml` and
  `docker compose up -d`.

- **Plain `docker run`:** add `--gpus all` (or `--runtime=nvidia -e
  NVIDIA_VISIBLE_DEVICES=all`).

**Check it took**, before launching anything:

```sh
docker exec eugene-plexus nvidia-smi
```

It should print the card (under Compose the container is
`eugene-plexus-control-plane`). Then open **Inference** on the
`eugene-plexus` node, or ask the agent directly: in `GET /v1/engines` on
port 8079, llama.cpp's `acquisition` names the `variant` it would install
(`ubuntu-cuda-12.8-x64` for a Pascal card) and `detected` carries
`accelerator: cuda`, the driver's CUDA version and the card's
`computeCapability`. Launch a model on that node and the agent installs that
build.

**Older cards are handled.** From CUDA 13 the toolkit no longer builds for
Maxwell, Pascal or Volta, and the last driver branch those cards get (580)
reports CUDA 13.0, so choosing a build by driver alone would install one with
no code for the card. The agent reads the card's compute capability too and
takes the CUDA 12 build for anything below 7.5 (agent `442af42`). A Pascal
card has one more cost: every build upstream ships carries its code as PTX,
which the driver compiles the first time a model loads. That can take
minutes. It happens once, because the image keeps the driver's cache in
`/data/cuda-cache`.

**What lands in `/data`:** engine builds in `/data/engines` (the current and
previous build, a gigabyte or more each for CUDA) and the kernel cache in
`/data/cuda-cache` (up to 4 GiB, usually far less). Both survive updates, so
an update neither re-downloads nor recompiles, and both are safe to delete:
the agent fetches and the driver recompiles.

**Not yet:** AMD and Intel cards in the container (the agent's detection is
there; passing `/dev/dri` through and the Vulkan runtime are not), and vLLM,
which is a Python environment plus a toolchain rather than a download.

---

## Adding a GPU machine

1. In the UI, **Nodes → Add a node**. It mints a join token, good once, and
   renders the command.

2. On the GPU machine:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.sh \
     | sh -s -- --join http://<control-host>:8083 --token <jwt>
   ```

   Windows GPU boxes use `install.ps1 -Join <url> -Token <jwt>`. The machine
   enrolls with its own key, takes the install's trust bundle, and declares no
   control plane of its own.

3. Back in the UI, launch a runtime on that node. The agent there declares a
   companion inference-driver for it, and the gateway joins driver to runtime
   by name and starts routing.

Nothing in that flow is container-specific, which is the point of running an
agent in the container too.

If the GPU machine needs to be *called back* — which it does, for idle unload
and start-on-demand — it must advertise an address the control host can reach.
`join` derives one from the route it used to reach the control root, which is
right on a flat network and on a mesh VPN. Pass `--advertise` when it is not.

---

## What is verified, and what is not

**Verified as a process, not in a container:** the four services bind
`0.0.0.0` from nothing but the five `EUGENE_PLEXUS_*_BIND_HOST` variables the
image sets; the agent survives an unwritable home directory; a SIGTERM runs
the agent's and all three children's ASGI lifespan shutdown. Those are the
claims the image depends on and they were measured on Linux.

**Checked by CI on every image build, and the image is published only when
they pass:** `.github/workflows/container.yml` runs all twenty-seven checks in
`scripts/compose-acceptance.sh` against the artifact it just built, then
re-tags that same image for GHCR rather than rebuilding — so what ships is
what was tested. That covers the twelve runtime checks that had never run
anywhere: the build itself, the container coming up healthy, all four
services on 0.0.0.0 inside, the UI and control root on their published ports,
8082 staying unpublished, a graceful stop, state surviving a down/up,
starting as `--user 99:100` against a directory owned by 99:100 — the uid the
image does not contain and the one the Unraid template ships — degrading to
console-only output when `logs/` is unwritable instead of dying on it, and
the two halves of "Where the models go": a container with nothing mounted at
`/models` reports it **missing** rather than scanning an empty directory, and
a GGUF placed in a directory mounted there is catalogued at startup with
nobody having opened Config. Since 2026-09-23 also: `libgomp.so.1` loads in
the image, the agent's engine root and the CUDA cache are on `/data` and
writable as 99:100, a GPU is opt-in in all three deployment files, and the
A7 recovery check serves a real CPU completion from the published image
itself rather than from a derivative of it.

**Not checked by CI, because its runners have no GPU:** passthrough, the
agent finding a card from inside the container, and a CUDA build loading
there. Those are checked on a real host —
[`docs/acceptance/container-gpu-run.md`](../acceptance/container-gpu-run.md).

There is still no container runtime on the development machine, so running
that script locally skips the runtime half and says so. CI is where it runs.

---

## When a separate GPU machine is still the better answer

This section used to be called *"Why not a container on the GPU machine
too?"* and gave four reasons, each true in general and none true on the host
that asked (2026-09-23: an Unraid server already sharing a Quadro P4000 with
Plex):

- *it downloads engine binaries and puts them where it can execute them* —
  into `/data/engines`, a volume, like any other state;
- *it reads your model directories, which in a container means a bind mount
  per directory* — the container already mounts `/models`, and every other
  node reaches the same files through it;
- *vLLM compiles at first use* — true, and vLLM is still not offered in
  here; llama.cpp is a download and compiles nothing;
- *GPU passthrough means `nvidia-container-toolkit` on every host* — on a NAS
  that already gives its card to Plex, it is installed.

So the container runs models when the host offers a card, and a separate
machine is the better answer when:

- **the GPU is in a desktop, not the server** — the common case, and
  `install.sh` there is simpler than any passthrough;
- **the engine is vLLM**, or anything else that is an environment rather
  than a binary;
- **the card is AMD or Intel**, until passthrough for those is built;
- **the machine should sleep** — a GPU in the NAS keeps the NAS awake.
