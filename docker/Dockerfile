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
# What is NOT here, deliberately: a GPU, the CUDA/ROCm/Vulkan runtimes,
# and any inference engine. §1 — the agent must run on the *host*
# because it supervises GPU processes, downloads engine binaries, reads
# the user's own model directories, and drives a vLLM that compiles at
# first use. Containerising that is the wall Home Assistant hit and the
# entire reason their awkward "Supervised" tier exists. So: the control
# plane runs here, the GPU boxes run `install.sh` and `join` this.
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
# Nothing else: uv brings its own Python, so this image needs no
# system interpreter, no build toolchain and no pip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
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
ENV EUGENE_PLEXUS_AGENT_CONFIG_FILE=/data/agent.yaml \
    EUGENE_PLEXUS_AGENT_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_CONTROL_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_GATEWAY_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_LIBRARY_BIND_HOST=0.0.0.0 \
    EUGENE_PLEXUS_DRIVER_BIND_HOST=0.0.0.0 \
    PATH=/opt/eugene-plexus/venv/bin:/usr/local/bin:/usr/bin:/bin

# Everything that outlives the container. `agent.yaml` and `node.yaml`
# are the install's identity; `control.yaml` plus the replicated log are
# the trust root's state; `gateway.yaml` and `metrics.sqlite3` are M8's
# retained request history; `logs/` is the only record of what happened.
# The agent derives all of them from the config file's directory, so one
# volume covers the lot.
WORKDIR /data
VOLUME ["/data"]

# 8079 the web UI and the browser's proxy, 8080 the OpenAI-compatible
# endpoint, 8083 the control root where worker nodes enroll. 8082 (the
# library) is deliberately NOT exposed: the browser reaches it through
# the agent's proxy and the gateway reaches it in-process-adjacent, so
# publishing it would widen the surface for nobody.
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
