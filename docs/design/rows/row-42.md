# Row 42: vLLM from its official container image

Lane ENG, after row 41. Sources: VDK (a business candidate,
`docs/history/audience-roadmap.md`), M4's decision to drive vLLM rather than
manage its Python environment (`m4-second-engine-vllm.md`), the earlier
reasons against containers (`install-paths-and-distribution.md`: the
container toolkit, a bind mount per model folder, compiling at first use),
agent `engines/vllm.py`, `supervisor.py`, `model_paths.py`.

## 1. What it delivers

- **vLLM without building a Python environment.** Where Docker or Podman
  can reach the GPUs, the owner picks "Run vLLM from its official
  container" and Eugene pulls `vllm/vllm-openai` at the version this
  release pins, then runs each vLLM runtime in it. Today the owner must
  install vLLM into a venv by hand and point Eugene at it.
- **vLLM on Windows through Docker Desktop.** Docker Desktop's WSL 2
  backend passes NVIDIA GPUs to containers, so a Windows machine runs vLLM
  with the agent on Windows; today the agent itself must run inside WSL.
- **Everything else stays as it is:** the same profiles, flags,
  speculation, health checks, failure explanations and gateway routing.
  The venv path stays for experts ("Use my own vLLM").

## 2. Design

### The container runtime (agent, `container_runtime.py`, new)

- **Detect** at start and every 10 minutes: `docker version` and
  `docker info --format json` (else `podman`), whether this account may
  use it (a permission error says "Add this account to the docker
  group"), and whether GPUs reach containers (`docker info` lists the
  `nvidia` runtime or CDI devices `nvidia.com/gpu`; Docker Desktop reports
  GPU support on WSL 2).
- **Report** on the node: `containerRuntime` {kind, version, gpus: bool,
  error}. The machine's Engines page shows it: "Docker 27.3, GPUs
  available" or the reason it cannot be used, with the fix.
- **Eugene itself in a container** (Unraid, Compose): no Docker socket is
  mounted, and this row does not ask for one (the socket is root on the
  host). The page says: "Eugene runs in a container without Docker access.
  To run vLLM's container, install Eugene on the host, or (expert) give
  this container the Docker socket, which gives it control of the host."

### The image

- **Pinned per release:** `release/manifest.json` gains
  `vllmImage: vllm/vllm-openai@sha256:<digest>` with its version; the agent
  pulls by digest, never by a moving tag. An expert can set another image
  (`vllmContainerImage`), and AMD's `rocm/vllm` is offered on ROCm hosts,
  labelled untested (never block what is untested).
- **Pulled as an engine build:** the pull is an engine install with
  progress (`docker pull` output, about 10 GB), shown as a managed engine
  with `version` and `previousVersion`; two images are kept, as two builds
  are (`engines/acquisition.py`). Row 13's checked update and row 73
  build on this.

### Running a runtime in it

- **The same argv** from `VllmAdapter.build_argv`, minus the binary, after
  the image's entrypoint (`vllm serve`), with:
  - `docker run --rm --name ep-<node>-<runtime> --label
    eugene-plexus.node=<node> --label eugene-plexus.runtime=<runtime>`;
  - GPUs: `--gpus all`, or `--gpus device=<uuid,…>` from the profile's
    pins (row 43's UUIDs where present);
  - shared memory: `--shm-size` (default 8 GiB, a profile field), not
    `--ipc=host`, which would share the host's IPC namespace;
  - port: `-p 127.0.0.1:<allocated port>:8000` (the profile's host when it
    is not loopback, as native runtimes bind);
  - the model: its folder bind-mounted **read only** at `/models/<id>`, and
    the path rewritten through `model_paths` (the draft model's folder
    too); `HF_HUB_OFFLINE=1`;
  - a per-runtime compile cache: `<agent data>/vllm-cache/<runtime>`
    mounted at `/root/.cache/vllm`, so a restart reuses compiled graphs
    (row 18 found the native cache survives; this keeps that true);
  - the profile's `env` as `-e` pairs.
- **Supervision:** the supervisor runs `docker run` in the foreground and
  reads its output as the engine's log. **Stop** is `docker stop -t 30
  <name>`, never killing the CLI alone (that leaves the container
  running). At agent start, containers labelled with this node and no
  runtime that owns them are stopped (orphans), and the log says so.
- **Which processes are the runtime's:** `docker inspect` gives the
  container's main pid on the host; host history attributes GPU memory to
  that pid's tree, as for native runtimes (on Docker Desktop the pids are
  inside the VM, so attribution is "unknown" there, not zero).
- **Failures** read the container's words: an image pull that fails names
  the registry's answer; "could not select device driver" says the
  NVIDIA container toolkit is missing and links its install guide; the
  existing `/dev/shm` explanation now names `--shm-size`.

### Contract (`agent.yaml`)

- `Node.containerRuntime` (above).
- The vLLM adapter's GUI schema gains `source` (`container` default where
  a container runtime with GPUs is present, else `binary`),
  `containerImage` (expert) and `shmSizeGiB`.
- `Runtime.container` {id, image, digest} when it runs in one.

## 3. Repositories and files

specs (`agent.yaml`, `release/manifest.json` and `scripts/release-inputs.py`
for the pinned image), agent (`container_runtime.py`, `engines/vllm.py`,
`engines/acquisition.py`, `supervisor.py` stop and orphan paths,
`host_probes.py` pid attribution), ui (the Engines page). Regenerate agent
and ui and diff.

## 4. Tests that fail before

- agent `test_container_runtime.py::test_docker_with_gpus_is_detected` and
  `test_a_permission_error_names_the_docker_group` (a fake `docker` on the
  path).
- agent `test_vllm.py::test_container_argv_mounts_the_model_read_only_and_binds_loopback`,
  `test_device_pins_become_gpus_device_uuids`, `test_shm_size_not_ipc_host`.
- agent `test_supervisor.py::test_container_stop_uses_docker_stop` and
  `test_orphaned_labelled_containers_are_stopped_at_start`.
- specs `test_release_inputs.py::test_the_vllm_image_is_pinned_by_digest`.

## 5. Acceptance (CI, Linux, about 5 minutes)

`specs/scripts/row42-vllm-container-acceptance.py`. GitHub's Linux runners
have Docker and no GPU, so the run uses a small fixture image built in the
job (an OpenAI-compatible fixture server answering `/health`,
`/v1/models`, `/version` and a chat completion) set as
`vllmContainerImage`, and checks Eugene's side of the contract:
1. The agent detects Docker (GPUs: false) and reports it.
2. A vLLM runtime in container mode starts: the container is labelled,
   the model folder is mounted read only (a write from inside fails), the
   port is bound on loopback only, the gateway routes a chat to it.
3. Stop: the container is gone within 30 s. Kill the agent: at its next
   start the orphan is stopped.
4. A bad image reference: the start fails naming the registry's answer.

**Real vLLM on a GPU:** the orchestrator runs it on this machine's RTX
5090 if Docker Desktop with GPU support is installed; it is not a roadmap
item otherwise (Troy, 2026-10-21).

## 6. Do not change

- `engines/speculation.py` (row 41, merged: call it).
- `engines/llama_cpp.py`, and the native vLLM path except to share the argv
  builder.
- `docker/Dockerfile`, `docker/compose.yaml` and the Unraid template (no
  socket is added).

## 7. Size and risks

M-L, about 3 days. Cross (it installs and runs third-party software, from
a digest this release pins); the orchestrator reads the launch and stop
code closely. Risks:
- **A container left running** holds the GPU; labels, `docker stop` and
  the orphan sweep at start cover it, and the acceptance kills the agent
  to prove it.
- **The image is large** (about 10 GB) and pulls once per version; the
  pull is an engine install with progress, never a silent first start.
- **Root in the container:** the image runs as root inside; the model is
  read only, the port is loopback unless the profile says otherwise, and
  no Docker socket is ever given to Eugene by this row.
