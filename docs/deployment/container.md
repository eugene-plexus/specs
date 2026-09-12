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

**Not yet verified:** the build itself, and the container coming up healthy.
`scripts/compose-acceptance.sh` runs nine structural checks that need no
runtime and eight more that do, and it says plainly which half it ran. If you
have a Docker host, running it there is what closes the gap.

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
