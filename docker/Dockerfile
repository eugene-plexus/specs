# Eugene Plexus — the control plane, containerised. Install-paths §9 step 5.
#
# **This image runs an agent, and that is the whole design rather than a
# compromise.** §4: "Path C's image is Path B's install with no GPU and
# no engines — because the control-plane container runs an agent too."
# `control` is supervised by the local agent like any other component,
# every component is handed `<KIND>_AGENT_URL`, and M7's `Runtime.node`
# and `advertiseUrl` work presumes an agent per host. **A Compose file
# that ran the four components directly, with no agent, would be
# fighting the design.**
#
# **It can run models too, since 2026-09-23 — on the CPU as shipped, and
# on an NVIDIA card when the host passes one through** (`--runtime=nvidia`
# plus `NVIDIA_VISIBLE_DEVICES`, the same two settings a Plex container
# uses; docs/deployment/container.md, "Running models in the container").
# This comment used to say there was no GPU here and never would be, and
# gave §1's reasons: the agent downloads engine binaries, reads the
# user's own model directories, drives a vLLM that compiles at first use,
# and GPU passthrough needs the NVIDIA toolkit on the host. Checked
# against a NAS that already shares its card with Plex, none of them
# held: binaries land on the /data volume below, the models folder is
# already mounted, llama.cpp is the engine and compiles nothing, and the
# toolkit is already installed. It was a packaging decision, not a
# technical limit — the agent in here is a full agent, and CI's recovery
# check has served real completions from this image since A7.
#
# What is still NOT here: any engine, baked in. The agent fetches the
# llama.cpp build that fits the card it finds, exactly as on bare metal,
# so the image does not grow by a CUDA runtime nobody without a GPU
# needs. No vLLM, which is a Python environment plus a toolchain, and no
# AMD or Intel passthrough yet. And machines with their own GPUs still
# run `install.sh` and `join` this — that topology is unchanged.
#
# The image is Path B's install run by Path B's own script. The six
# pinned commits live in exactly one file, `scripts/install.sh`, and a
# version bump is one edit rather than three.
#
#   docker compose -f docker/compose.yaml up -d --build
#
# Build context is the repository root:
#   docker build -f docker/Dockerfile -t eugene-plexus/control-plane:0.1 .

# Pinned to a Debian release rather than `stable-slim`, which silently
# becomes a different major version on release day -- the staleness
# family this project keeps writing down.
FROM debian:trixie-slim

# `curl` is here for two jobs: install.sh fetches uv with it, and the
# HEALTHCHECK below uses it. `ca-certificates` because both talk TLS.
# `libgomp1` is the one shared library upstream's Linux llama.cpp builds
# need that a slim Debian lacks (OpenMP, for the CPU backend every build
# carries). Before it was here, the A7 recovery check had to add it to
# a derivative image of its own before a llama-server would start, and
# an engine the agent installed in this image had nothing to load.
# The CUDA runtime is NOT here: each CUDA build arrives with its own
# (the cudart companion archive), and libcuda comes from the host's
# driver through the NVIDIA toolkit. Nothing else: uv brings its own
# Python, so this image needs no system interpreter, no build toolchain
# and no pip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# A control plane that needs root to run is one more reason not to run
# it. A fixed uid so a bind-mounted /data has predictable ownership.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin plexus \
 && mkdir -p /opt/eugene-plexus /data \
 && chown plexus:plexus /opt/eugene-plexus /data

USER plexus

# `--no-service --no-start`: there is no systemd in here and the
# container runtime is the supervisor of the supervisor. Everything
# else install.sh does is exactly what this image wants, including its
# own check that what landed can actually serve -- so a broken pin
# fails the BUILD rather than the first boot.
COPY --chown=plexus:plexus scripts/install.sh /tmp/install.sh
RUN sh /tmp/install.sh --prefix /opt/eugene-plexus --no-service --no-start \
 && rm /tmp/install.sh

# **The four BIND_HOST variables are what make this container
# reachable, and they are not redundant with the agent's own.**
# A component binds 0.0.0.0 only when its node advertises a non-loopback
# address (see docs/deployment/tailnet.md, which calls getting that
# order right "the single most important instruction in this document").
# Inside a container there is no address to advertise at build time and
# no config file to write it into -- and a component bound to 127.0.0.1
# is unreachable through a published port, because the runtime's proxy
# connects to the container's own IP.
#
# The supervisor spawns children with `os.environ.copy()`, so these
# reach every component without the agent knowing anything about
# containers. Verified as a plain process before this file was written:
# all four sockets came up on 0.0.0.0 with nothing but these set.
#
# It also means the container cannot make the mistake the tailnet doc
# warns about -- enrollment does not restart the control root, so an
# advertise address discovered late leaves it on loopback forever. Here
# the environment is fixed before the first process starts.
#
# **`LIBRARY_DEFAULT_MODEL_ROOTS` is the one that makes the library
# useful in here, and it is a default, not a setting.** The library
# boots with no model directories and waits for someone to add one under
# Config -- right on bare metal, where nothing but the operator knows
# where the models are, and useless in a container, where the only paths
# the picker can show are paths inside the container and none of them is
# anywhere a GPU node can reach. The image DOES know one thing about its
# layout before anyone opens the UI: the models volume is mounted at
# /models. So that is the field's default: the schema reports it, the UI
# shows it and replaces it like any other value, and clearing the field
# returns to it. Nothing about it is written to the operator's config
# file. Mount nothing there and the library says so -- the scan reports
# /models missing and health goes degraded naming it -- rather than
# scanning an empty directory in the container's own layer, which is
# where a download would then land and be lost on the next recreate.
# That is also why the image does not `mkdir /models`: the directory
# existing means it was mounted.
#
# **`ENGINE_ROOT` and the two `CUDA_CACHE_` variables put everything a
# running model writes on the data volume too.** The agent keeps engine
# builds under `$HOME` by default, and here `$HOME` is either the image's
# own layer (lost on every recreate, so every update re-downloads a CUDA
# build of a gigabyte or more) or, under the Unraid template's
# `--user 99:100`, a uid with no home at all, where the download fails.
# The CUDA cache is where the driver keeps the kernels it compiles at
# first load for a card the build carries no ready binary for -- Pascal,
# with every build upstream ships -- and a cache that is not kept means
# minutes of compiling on every start. 4 GiB is the ceiling NVIDIA
# accepts; it is a cap, not a reservation, and the default of a few
# hundred MB can evict llama.cpp's kernels part-way through a load.
#
# **`NVIDIA_DRIVER_CAPABILITIES` is set and `NVIDIA_VISIBLE_DEVICES` is
# not, and the difference is the opt-in.** The first only matters once
# the NVIDIA runtime is in use: `compute` brings libcuda, `utility`
# brings `nvidia-smi`, which is how the agent finds the card and reads
# its compute capability. The second is what hands a card over, so it is
# the operator's to set -- baked in here, every host whose default
# runtime is NVIDIA would pass its GPUs to this container unasked.
ENV EUGENE_PLEXUS_AGENT_CONFIG_FILE=/data/agent.yaml \
    EUGENE_PLEXUS_AGENT_ENGINE_ROOT=/data/engines \
    CUDA_CACHE_PATH=/data/cuda-cache \
    CUDA_CACHE_MAXSIZE=4294967296 \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_CONTROL_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_GATEWAY_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_LIBRARY_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_DRIVER_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_LIBRARY_DEFAULT_MODEL_ROOTS=/models \
    PATH=/opt/eugene-plexus/venv/bin:/usr/local/bin:/usr/bin:/bin

# Everything that outlives the container. `agent.yaml` and `node.yaml`
# are the install's identity; `control.yaml` plus the replicated log are
# the trust root's state; `gateway.yaml` and `metrics.sqlite3` are M8's
# retained request history; `logs/` is the only record of what happened.
# The agent derives all of them from the config file's directory, so one
# volume covers the lot. `engines/` and `cuda-cache/` are here too, by the
# two variables above: re-fetchable, but a gigabyte and minutes of
# compiling respectively, and neither is worth paying on every update.
# The recovery tool already treats `engines/` under a state directory as
# engine builds rather than models (docs/recovery.md).
#
# /models is deliberately NOT declared a VOLUME. A declared volume that
# nobody binds becomes an anonymous one under the runtime's own
# directory -- a managed store with the user's model files in it,
# invisible from the host and gone with `down -v`, which is the exact
# thing this project promises never to build. The operator binds their
# own directory there (the Unraid template's "Models", the Compose
# file's commented line), or the library reports it missing.
WORKDIR /data
VOLUME ["/data"]

# 8079 the web UI and the browser's proxy, 8080 the OpenAI-compatible
# endpoint, 8083 the control root where worker nodes enroll. 8082 (the
# library) is deliberately NOT exposed: the browser reaches it through
# the agent's proxy and the gateway reaches it in-process-adjacent, so
# publishing it would widen the surface for nobody. Nor is any port of a
# model running in here, or of its companion driver: the gateway dials a
# driver on its own node at the loopback address the agent binds it on
# (gateway 46526f3). Before that it dialled the node's advertised address
# with the driver's port -- the NAS, on a port this image never publishes
# -- and a model launched in here was unroutable from the gateway beside it.
EXPOSE 8079 8080 8083

# `start-period` is generous because a first boot seeds the topology and
# starts three children before any of this is true.
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fsS -o /dev/null http://127.0.0.1:8079/healthz || exit 1

# `--unattended` for the reason step 4 recorded: the unattended path is
# declared, never inferred from the absence of a terminal. A container
# has no TTY today, and an entry point that relies on that is one
# `docker run -it` away from hanging on a question nobody can answer.
CMD ["eugene-plexus-agent", "--unattended"]
