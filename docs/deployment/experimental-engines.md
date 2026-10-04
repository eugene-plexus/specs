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
2. Prepare a compatible model with [Strata's setup instructions](https://github.com/Niko1221/Strata/blob/v0.1.39/docs/INSTALL.md).
   Select text-only operation (`--vision no`) and one request at a time
   (`--parallel 1`) when preparing it.
   Keep its weights, pack, tokenizer and optional MTP assets in your own folders.
   Put the prepared JSON configuration in a folder registered in Eugene's
   Library. Its paths must resolve on the selected node. If you move the JSON,
   keep its `cwd` pointing at the original directory or use absolute asset paths.
3. Choose **Add prepared Strata model**, enter a saved name, a unique public
   model alias and the JSON path. **Save model** creates a stopped runtime.
4. Use that model's **start** button. It is offered for inference only after
   Strata reports that its model is loaded. Loading errors appear on the model's
   row and in its engine log. The model alias is the name clients should request.

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

Save each model separately. With one ready and another stopped, use **Switch
model** in the Strata section. Eugene checks the target's prepared assets and
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
Stop all runtimes for an engine and finish or cancel any installation before
choosing **uninstall** on its engine entry. The confirmation explains that
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
- Prepared model configurations only. Arbitrary GGUFs, automatic conversion,
  download/preparation and tuning are not offered by this integration.
- Memory fit is **unknown**. The JSON file's size is never treated as the model's
  memory footprint. Automatic wake and eviction are disabled for Strata.
- No tools, structured output, media, embeddings, raw completions or llama.cpp
  slot pinning. Explicit unsupported request settings are refused.
- NInfer and imp remain future adapters. The Experimental designation and shared
  install/removal/switch lifecycle are the foundation for adding them.

See the [verification record](../acceptance/strata-engine-run.md) for what was
tested and the outstanding real-model acceptance run.
