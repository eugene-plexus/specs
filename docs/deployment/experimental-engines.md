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

   The prepared files go into `Strata-data` at the top of the Library folder
   holding the GGUF: Strata's configuration, its pack, tokenizer and MTP helper,
   and the model's `<name>.eugene-prepared.json`. The GGUF itself is not
   changed (setup leaves a `.done` mark beside each shard). Strata reads the
   GGUF and its pack while it answers, so they belong on a fast drive of the
   node that runs it; a Library folder on another machine works, slowly
   (agent#12).
3. A model prepared outside Eugene with
   [Strata's setup](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/INSTALL.md)
   (text only, `--vision no`; one request at a time, `--parallel 1`) can be
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
original JSON. Configured commands, MCP servers, vision, batching and unsupported
native flags are refused with a specific error. The JSON controls prepared model
assets and the supported native settings; Eugene captures the engine's output.

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
  request per managed runtime.
- Prepared models only, made from the nine models Strata's own setup offers
  (*Strata's list*: the original Qwen3.8-Flash-Next in four sizes, Swift 1.5
  in two, the Coder, Unsloth's two), each at the revision Strata pins; Strata
  prepares only those files, by name, as its setup does. Preparation is text
  only, on one GPU (the one with the most memory), with the experimental speed
  projection off. Setup's tuning (`--calibrate`) is not run.
- Memory fit is **unknown**. The JSON file's size is never treated as the model's
  memory footprint. Automatic wake and eviction are disabled for Strata.
- No tools, structured output, media, embeddings, raw completions or llama.cpp
  slot pinning. Explicit unsupported request settings are refused.
- NInfer and imp remain future adapters. The Experimental designation and shared
  install/removal/switch lifecycle are the foundation for adding them.

See the [verification record](../acceptance/strata-engine-run.md) for what was
tested and the outstanding real-model acceptance run.
