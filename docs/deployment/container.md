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

**Docker → Add Container → Template → paste that URL.** It fills in the three
ports, the data path, the `ExtraParams` that are not optional, and an advanced
section for the passphrase file.

**Then do the one-line cleanup in the next section.** Until you do, Unraid has
nowhere to keep your settings and every Force Update resets them.

It pulls `ghcr.io/eugene-plexus/control-plane:edge`, which CI builds and
**verifies before pushing** — `scripts/compose-acceptance.sh` runs its
eighteen checks against the built image, and a failure means nothing is
published. `edge` rather than `latest` on purpose: nothing here is released,
and `latest` is the tag every registry convention reads as "the supported
one".

**One-time, and only the repository owner can do it:** a package pushed by
Actions starts **private**, so the first pull fails with an authentication
error that looks like a bad image name. Make it public once at
`github.com/orgs/eugene-plexus/packages` → control-plane → Package settings →
Change visibility.

### After the first Apply, delete the author copy

**Do this once, or every update throws your settings away.** Verified on a
real box 2026-09-12, after it happened to the first person to use this
template.

```sh
rm /boot/config/plugins/dockerMan/templates-user/eugene-plexus.xml
```

Then Edit the container, re-enter your values, and Apply. Confirm you now
have a `my-eugene-plexus.xml` in that folder:

```sh
ls /boot/config/plugins/dockerMan/templates-user/ | grep eugene
# my-eugene-plexus.xml   <- correct
# eugene-plexus.xml      <- delete this one
```

**Why.** Pasting a URL downloads the template into `templates-user/` under
*our* filename. Unraid treats any file already in that folder as the user
template and writes your settings back into it, so the `my-<name>.xml` it
normally maintains is never created — your config and the author template
become the same file. A Community Applications app never hits this, because
its author template lives in CA's feed and your `my-*.xml` is separate; that
is why every other container on the box keeps its ports and this one did not.

The template used to carry a `<TemplateURL>` pointing at the same raw URL,
which is the address Unraid re-downloads that file from — so a refresh
overwrote the user's config with the defaults. **That field is gone now**, so
a current install no longer gets clobbered on its own. The cleanup above is
still worth doing: it gets you a properly-named user template that nothing
will ever overwrite, including a future re-paste of the URL.

**It is not only the ports.** The whole file is replaced, so the data path
reverts to `/mnt/user/appdata/eugene-plexus` as well — and unlike a port, that
one is not fixed by retyping it. A fresh data directory is a *second install*,
whose worker nodes are still enrolled to a trust root that no longer exists.
If you customised Data, check it after any update until you have the `my-`
file.

**Untested alternative that skips the cleanup:** download the template
straight to the user-template name and install from the dropdown instead of
by URL.

```sh
curl -fsSL https://raw.githubusercontent.com/eugene-plexus/specs/main/unraid/eugene-plexus.xml   -o /boot/config/plugins/dockerMan/templates-user/my-eugene-plexus.xml
```

Then **Docker → Add Container →** pick `eugene-plexus` from the user-template
dropdown. This should never produce an author copy to collide with, but it has
not been run — the paste-then-clean path above is the one that was verified.

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

**Remapped ports are exactly the settings the author copy eats**, so do the
cleanup above before you trust them to survive an update. The author of this
project runs the control plane on 8279/8280/8283 because the defaults clash
with other containers on that box, and re-entered all three on every update
until this was diagnosed.

### What the GUI still cannot do

**Unlock the trust root after a restart** — but the web UI can, on the Nodes
page, and the passphrase file in the template's advanced section removes the
need entirely. See "Unattended unlock" below.

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

**Signing in to the web UI does NOT unlock it**, which is the trap. That
login posts to the *agent*, and the agent is not the thing that is sealed — so
the UI keeps working, every page renders, and an existing browser session
carries on as if nothing is wrong. The only UI screens that talk to the
control root are `/nodes` and the first-run wizard, so unless you open
`/nodes` there is nothing to see. Meanwhile `/v1/models` is empty and the
gateway routes nothing.

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
they pass:** `.github/workflows/container.yml` runs all nineteen checks in
`scripts/compose-acceptance.sh` against the artifact it just built, then
re-tags that same image for GHCR rather than rebuilding — so what ships is
what was tested. That covers the ten runtime checks that had never run
anywhere: the build itself, the container coming up healthy, all four
services on 0.0.0.0 inside, the UI and control root on their published ports,
8082 staying unpublished, a graceful stop, state surviving a down/up, and
starting as `--user 99:100` against a directory owned by 99:100 — the uid the
image does not contain and the one the Unraid template ships — and degrading to
console-only output when `logs/` is unwritable instead of dying on it.

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
