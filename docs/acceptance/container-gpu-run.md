# Models in the control-plane container, on a passed-through NVIDIA card

**Status: NOT RUN.** Built 2026-09-23; CI covers everything below that does
not need a GPU. The physical run is owed on a real host, and the first one
available is the author's Unraid server with a **Quadro P4000** (Pascal,
compute capability 6.1) on driver **575.51.02** (CUDA 12.9) — the case that
exercises the most of what changed.

## What changed, and why it needed a physical host

The container was documented as unable to run inference. That was a
packaging decision, not a technical limit: the agent in it is a full agent,
and the A7 recovery check had already served real completions from a
derivative of the image that added one library. Making it real took three
fixes, two of which no container check could have found:

| Where | Change | Found by |
|---|---|---|
| agent `442af42` | A CUDA build is chosen by the card's compute capability as well as the driver's CUDA version. CUDA 13 builds carry no code below 7.5; the last Pascal driver (580) reports 13.0; so a Pascal card was handed a build with no kernels for it. An older major is now taken when the driver's own major cannot serve the card. | Asking what the container would do on a P4000 |
| gateway `46526f3` | A driver on the gateway's own node is dialled at its loopback `url`, not its `advertiseUrl`. In the container the latter is the NAS address with an unpublished port, so a model launched there was unroutable. | Reading the gateway before building the image |
| specs (image) | `libgomp1`; engines at `/data/engines`; CUDA cache at `/data/cuda-cache` (4 GiB cap); `NVIDIA_DRIVER_CAPABILITIES=compute,utility`; GPU opt-in in the template and Compose file | — |

## What CI already proves (no GPU)

`scripts/compose-acceptance.sh`, 27 checks, on every image build: `libgomp`
loads (26); as `--user 99:100` the agent's own `engine_root()` is
`/data/engines` and writable, as is the CUDA cache (27); engines and cache are
on the volume under the variable the agent reads (24); a GPU is opt-in in the
image, the template and the Compose file (25). `scripts/a7-container-acceptance.sh`
serves a real Qwen3-0.6B completion from the **published image itself** on CPU.

Unit level: 17 agent tests (8 fail against the old selection; sabotage 8/8)
and 5 gateway tests (sabotage 6/6, including the pre-change code).

## The physical run — steps and what each must show

Prerequisites: the `edge` image built from the specs commit that pins agent
`442af42` and gateway `46526f3`; the Nvidia Driver plugin installed.

1. **Pass the card.** Edit the container: add Variable
   `NVIDIA_VISIBLE_DEVICES` = the P4000's GPU UUID; Advanced View → append
   `--runtime=nvidia` to Extra Parameters; Apply.
   - `docker exec eugene-plexus nvidia-smi` prints the Quadro P4000.
2. **Detection.** `GET /v1/engines` on 8279 (operator token): llama.cpp's
   `acquisition.detected` reads `accelerator: cuda`,
   `acceleratorVersion: 12.9`, `computeCapability: 6.1`; `variant` reads
   `ubuntu-cuda-12.8-x64`.
3. **Launch.** Library → score & launch on `eugene-plexus` → a model that
   fits 8 GB (the starter set's pick) → Run. The engine installs into
   `/data/engines`.
   - Record: time to `ready` on the **first** load (includes the PTX JIT).
   - `nvidia-smi` on the Unraid host shows `llama-server` holding VRAM.
   - The runtime's log shows layers offloaded to `CUDA0`.
4. **Routing.** A completion through the published gateway (`:8280`)
   answers, with `x_eugene_plexus` naming the `eugene-plexus` node. This is
   gateway `46526f3`'s claim: before it, this step 502s.
5. **The cache holds.** Stop and start the runtime.
   - Record: time to `ready` on the second load. It should be materially
     shorter than step 3's; `/data/cuda-cache` is non-empty.
6. **An update neither re-downloads nor recompiles.** Force Update the
   container.
   - The engine is not fetched again (same build in `/data/engines`, no
     download in the agent log); the load time matches step 5, not step 3.
7. **Opt-out still starts.** Remove the variable and the flag, Apply: the
   container comes up healthy and scores that node as CPU-only.

## Not covered by this run

- A 580 driver (CUDA 13.0) with Pascal — the selection's headline case. The
  Unraid plugin offers nothing past 575 for this card, so it is unit-tested
  only. A 3090 fitted beside the P4000 would exercise the lowest-card rule
  (both cards → the 12.8 build) on the same box.
- Compose with `deploy.resources` on a non-Unraid host.
- AMD and Intel cards (not built), vLLM (not offered in the container).
