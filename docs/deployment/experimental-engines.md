# Experimental engines

Eugene's first experimental integration is **Strata v0.1.39 on Windows x64
with NVIDIA and a CUDA 13 capable driver (580 or later)**. Experimental means
limited integration and support. The label remains after successful hardware
tests. This integration ships through Edge; the published v0.1.0 installers
do not include it.

## Install and add a model

1. Open **Backends**, then **Overview**, and find Strata in the selected node's engines. Choose
   **install**. Eugene verifies pinned source and native archives, then creates
   a private Python environment with the server and CUDA dependencies. Model
   downloads and preparation are separate. macOS has no install recipe.
2. Prepare a model. In **Discover**, pick the node, open an entry of
   *Strata's list* and choose **Download and prepare for Strata**: one action
   downloads its files at the revision Strata pins, prepares them with
   Strata's own setup on that node, and starts the result. A GGUF on the list
   that is already in the Library has **Prepare for Strata** on its Library
   page instead. Before it starts, each says how much more disk Strata's setup
   needs on that node, by setup's own rule, and offers setup's context sizes
   (its recommendation for the machine by default; the context is fixed when
   the model is prepared, and preparing it again with another one takes
   seconds). The run's line in the task tray shows setup's own step, what it
   has written and its warnings; **Cancel** stops setup. The first
   preparation also fetches Strata's preparation tools (its Python packages
   and llama.cpp's `gguf-py`) and its MTP helper (about 5 GB,
   once per Library folder).

  For models that support images, **Images** offers **Off** (the default),
  **CPU** or **GPU**. Enabling it downloads an additional encoder and adds
  about 1 GB to the disk estimate; serving also needs additional memory.
  Unsloth UD-Q4_K_XL does not offer images. If setup falls back from GPU to
  CPU, the run fails explicitly rather than claiming GPU encoding. Prepare
  again with a supported mode. Re-preparing with changed settings restarts
  an existing runtime; finish active requests first.

   The prepared files go into `Strata-data` at the top of the Library folder
   holding the GGUF: Strata's configuration, its pack, tokenizer and MTP helper,
   and the model's `<name>.eugene-prepared.json`. The GGUF itself is not
   changed (setup leaves a `.done` mark beside each shard). Strata reads the
   GGUF and its pack while it answers, so they belong on a fast drive of the
   node that runs it; a Library folder on another machine works, slowly
   (agent#12).
3. A model prepared outside Eugene with
   [Strata's setup](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/INSTALL.md)
  (`--vision no` for text only, or `--vision cpu` / `--vision gpu` for images)
  can be
   adopted instead: open **Library**, pick that node in the header and choose
   **add prepared model**. Enter the JSON configuration's path on the node, a
   name (clients request the model by it) and the Library folder to keep its
   record in; optionally the Library model it was made from. Eugene writes one
   small file, `<name>.eugene-prepared.json`, into that folder and lists the
   model. Nothing of Strata's is copied or changed. A file of that shape
   written by hand is found by the next scan just the same.
4. Select the model and choose **Run**. Like any Library model it gets a
   profile, a runtime and a row on Inference; it is offered for inference only
   after Strata reports that its model is loaded. Loading errors, including a
   file the configuration names that is not there, appear on the run and the
   model's row. To remove the model from the Library, delete its
   `.eugene-prepared.json` file; Strata's files are not touched.

An existing installation can be borrowed: set **Strata server (experimental)**
in the node's Settings to its `serve/server.py`. That checkout must contain
`.venv/Scripts/python.exe` and `engine/strata.exe`. Its native binary must be
compatible with this integration. Borrowed installations are never uninstalled
by Eugene.

Eugene launches its own copy of the prepared configuration, supplies its native
executable and loopback address, and assigns the saved alias. It preserves the
original JSON. Configured commands, MCP servers and unsupported native flags
are refused with a specific error. Image configurations keep their encoder
assets, but Eugene uses its own installed encoder executable, not a command
from the configuration. The JSON controls prepared model assets and supported
native settings; Eugene captures the engine's output.

## Switch models

Add and Run each model separately from the Library. With one ready and
another stopped, use **Switch model** in the Strata section of **Inference**. Eugene checks the target's prepared assets and
engine environment before stopping the source. It waits up to 30 seconds for requests through
its gateway to finish, then stops the source and starts the target. If draining
times out, the source stays running. The target's row reports loading, ready or
failure; a failed target is not routed to. Start the old model again if needed.

Models keep their own aliases. Switching does not send a request for model A to
model B, replay a partial answer or automatically evict other models. Traffic
sent directly to an engine, or through another gateway, is outside this gateway's
drain accounting; finish that traffic before switching. Both saved runtimes must
have start on demand disabled.

## Stop and remove

Use **stop** to release a model's memory while retaining its saved configuration.
Stop all runtimes for an engine, and finish or cancel any installation and any
preparation, before choosing **uninstall** on its engine entry. The confirmation explains that
Eugene-managed builds will be removed. Model files, saved runtimes, borrowed
installations and shared dependencies remain. Install again to use the saved
runtimes later. Removing a saved runtime also leaves the model files intact.

The API provides `POST /v1/engines/strata/install`, its progress GET, and
`POST /v1/engines/strata/uninstall`. `DELETE .../install` only cancels an install
job. Model switching uses `POST /v1/runtimes/switch` on the gateway with
`source`, `target` and optional `node` names. These management actions require
an operator session.

## Current limits

- Text chat, streaming, reasoning text and reported token usage; one concurrent
  request by default. A prepared config's optional parallel setting is retained.
- Prepared models only, made from the nine models Strata's own setup offers
  (*Strata's list*: the original Qwen3.8-Flash-Next in four sizes, Swift 1.5
  in two, the Coder, Unsloth's two), each at the revision Strata pins; Strata
  prepares only those files, by name, as its setup does. Preparation is on one
  GPU (the one with the most memory), with the experimental speed
  projection off. Setup's tuning (`--calibrate`) is not run.
- Image preparation and routing are experimental. The driver advertises image
  input only when the loaded model reports an enabled, available encoder with
  no error. Native CPU/GPU image inference and visual-answer correctness still
  require hardware validation; automated checks do not establish those results.
- Memory fit is **unknown**. The JSON file's size is never treated as the model's
  memory footprint. Automatic wake and eviction are disabled for Strata.
- **Tools and structured output work** (since 2026-10-12; measured on
  Qwen3.8-Flash-Next, `docs/design/tools-assumed.md`), so Workbench's Search the
  web and agentic clients such as Codex can use a Strata model. Strata ignores
  `tool_choice` `required` or a named function, and `parallel_tool_calls: false`.
  Those are sent and named in the answer's `x-eugene-plexus-ignored-settings`
  header, not refused. Structured output together with tools is Strata's own
  refusal, in its words.
- `seed`, `frequency_penalty` and `presence_penalty` are passed through (since 2026-10-12). A seed
  must be a positive whole number: Strata ignores 0 or below, so Eugene refuses it. By Strata's own
  documentation, a sampled answer repeats run to run only with static expert residency, not on its
  default adaptive tier. `logprobs` is refused.
- No audio, video, embeddings, raw completions or llama.cpp slot pinning. Other explicit
  request settings Strata does not support are refused.
- NInfer and imp remain future adapters. The Experimental designation and shared
  install/removal/switch lifecycle are the foundation for adding them.

See the [verification record](../acceptance/strata-engine-run.md) for what was
tested and the outstanding real-model acceptance run.
