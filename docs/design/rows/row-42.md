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

## 8. What building found (2026-11-16)

- **Where the container runtime is reported:** `EngineList.containerRuntime`
  (`GET /v1/engines`), not the control root's `Node`: the Engines page
  reads that list already, and `Node` lives in `control.yaml`, which this
  row does not touch (no root deploy is needed first).
- **The image pins are per GPU kind:** `release/manifest.json` `vllmImages`
  {`cuda`: v0.33.0, `cuda12`: v0.32.0-cu129, `rocm`: AMD's `rocm/vllm`
  0.29.0, untested}, by digest; the agent carries the same pins in
  `engines/vllm_images.json`. The CUDA 12 image exists because v0.33.0's
  default image is CUDA 13 (driver R580+): a CUDA 12 driver gets the last
  release with a `-cu129` tag. The two copies are kept equal by hand;
  `ship.py` could copy them in a later row.
- **No per-runtime image (`containerImage`) was built.** Only the agent's
  `vllmContainerImage` (Config, owner only, by digest). A per-runtime image
  would be a new image field an operations token must not set, and the hold
  on an older image is row 13/73's (a rollout over images); not needed here.
  The profile gains `source` and `shmSizeGiB`, neither naming a file,
  image, volume, device or variable, so an operations token may set them.
- **`--pull never`:** a runtime start never pulls; a missing image says
  "pull it on the Engines page". A pull is only an install, and the image
  pulled is in use at the next start (no staging; row 13's checked update
  over images is later work). The image before it is kept; the one before
  that is removed (`docker image rm` of the recorded ID only).
- **Env values never reach a command line:** `-e NAME` pairs, values in
  the CLI's own environment. `--security-opt no-new-privileges` is added;
  no `--init`, as upstream's own `docker run` has none.
- **The tokenizer must be inside the model's folder** in a container (a
  draft model's folder is mounted read only, as designed); elsewhere the
  launch is refused, naming the folder rule and the way out (your own vLLM).
- **Card pins** (`CUDA_VISIBLE_DEVICES`, UUIDs from row 43) become
  `--gpus '"device=..."'` (Docker parses the value as CSV, so a list is
  quoted inside it) or Podman's CDI `nvidia.com/gpu=<id>`; ROCm gets
  `/dev/kfd` and `/dev/dri`. With no GPU on the host and none reaching
  containers, no GPU option is passed and vLLM says what it found.
- **Default `source`:** the container when an image is pulled, a container
  runtime can be used and no vLLM program is set (`vllmBinary` or the
  runtime's `binary`); otherwise the owner's own vLLM.
- **Labels carry an agent ID** (a hash of the agent's data folder) beside
  the node name: two agents on one host never sweep each other's containers.
  The orphan sweep is `docker rm -f` of every container with this agent's
  label, at start, before any runtime starts.
- **Host history:** the container's main pid (`docker inspect`) joins the
  engine pids on native Docker; on Docker Desktop GPU memory for Eugene is
  "unknown" with the reason, never 0.
- **Not run:** real vLLM in its image on a GPU (no GPU on the runners), and
  a chat through a gateway in the acceptance (the engine is reached on its
  own port; routing does not depend on how a runtime started). SELinux
  hosts (Fedora, RHEL) may need a relabel option on the model mount; not
  handled, not tested.
- **Which kills leave an orphan (found by the first CI run):** killing the
  agent alone on Linux does not. Its children get SIGTERM when it dies
  (`orphan_kill`, `PR_SET_PDEATHSIG`), and the attached `docker run`
  forwards it to the container, which then stops and is removed. An orphan
  is left when the agent's whole tree is killed at once (systemd's final
  SIGKILL of the service's control group, the OOM killer on the cgroup),
  when Windows' job object ends the CLI (TerminateProcess forwards
  nothing), or when the CLI alone dies. The acceptance kills the whole tree.
