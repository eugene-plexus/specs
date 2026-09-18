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

**There is no GPU in here and there never will be.** The agent must run on
the host that has the GPU, the engine binaries and your own model
directories — it downloads engine builds, reads your files, and drives a
vLLM that compiles at first use. Containerising that is the wall Home
Assistant hit, and the reason their awkward "Supervised" tier exists. So the
GPU boxes run [`install.sh`](../../scripts/install.sh) on bare metal and
`join` this control plane.

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
three components with `$HOME` set to a directory it cannot write. What it
loses is engine acquisition, which writes under `$HOME/.eugene-plexus/engines`
— and this container has no GPU to run an engine on, so there is nothing to
lose.

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
host, which replaces the install's signing key. Set it before the first
start, or accept it.

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
control root holds the install's signing key sealed with your passphrase. On
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

The trust root seals the install's signing key with your passphrase. On a
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
- **Windows GPU box — and which install you have decides the answer**
  (corrected 2026-09-17; this bullet used to say the agent runs "not in your
  desktop session", which is false for the default install — and is why a
  mapped `Y:` worked on the live worker).
  - **Default, unelevated install (a logon task):** the agent runs **in your
    own session**, so a mapped drive letter and your own saved share
    credentials both work. The cost is that it starts at sign-in and stops at
    sign-out.
  - **Elevated install (the real service):** it runs as LocalSystem, where a
    drive letter does not exist and `cmdkey` in your account buys nothing —
    the credential would have to belong to the machine account. Use the UNC
    path and prefer a share the machine account can read (Public, or an ACL
    granting the computer object) over saved credentials.
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

## Adding a GPU machine

1. In the UI, **Nodes → Add a node**. It mints a join token, good once, and
   renders the command.

2. On the GPU machine — bare metal, not a container:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/scripts/install.sh \
     | sh -s -- --join http://<control-host>:8083 --token <jwt>
   ```

   Windows GPU boxes use `install.ps1 -Join <url> -Token <jwt>`. The machine
   enrolls, adopts the install's signing key, and declares no control plane of
   its own.

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
they pass:** `.github/workflows/container.yml` runs all twenty-three checks in
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
nobody having opened Config.

There is still no container runtime on the development machine, so running
that script locally skips the runtime half and says so. CI is where it runs.

---

## Why not a container on the GPU machine too?

Because of what the agent does there, not because of a preference:

- it downloads engine binaries and puts them where it can execute them;
- it reads **your** model directories, wherever you keep them, which in a
  container means a bind mount per directory and a broken promise that your
  files stay yours;
- vLLM compiles at first use, so the unit of operation is a Python
  environment plus a C toolchain plus the interpreter's dev headers — a
  container that JIT-compiles on first request is a support problem, not a
  deployment;
- and GPU passthrough means `nvidia-container-toolkit` on every host.

The control plane has none of those properties. That asymmetry is §1 of the
design and it is the whole reason there are two paths instead of one.
