# Row 61: LoRA adapters as Library items, routed to replicas holding them

Lane LIB. Cross risk. Sources: M2-LORA (`m2-model-library.md`: "Detected
and skipped with a reason, not modelled"), `llm-d-lessons.md` (llm-d routes
to replicas holding the adapter; llama-server's
`--lora-init-without-apply` and `/lora-adapters` switch adapters per
request: "Revisit when the Library learns adapters"), library
`formats/safetensors.py` `is_adapter_dir` and `scanner.py` (`SkipReason.adapter`),
agent `engines/mlx.py` `adapterPath`, gateway `routing.py`.

## 1. What it delivers

- **Adapters are Library items.** A GGUF LoRA (`general.type = adapter`)
  or a safetensors adapter folder (`adapter_config.json`) is listed under
  its base model ("2 adapters"), with its name, rank and base, instead of
  being skipped (safetensors) or mistaken for a model (GGUF, today).
- **A runtime can hold adapters.** On a llama.cpp or vLLM profile: "Also
  load these adapters". Each becomes a model clients can name:
  `<base alias>:<adapter>` in `/v1/models`.
- **Requests go to a replica that holds the adapter,** and the engine
  applies it to that request only.

## 2. Design

- **Library:** `LibraryModel` gains `kind` (`model` default, `adapter`) and,
  for adapters, `baseModel` (from `general.base_model.*` in GGUF or
  `base_model_name_or_path` in `adapter_config.json`, matched to a Library
  model by name or file hash; unmatched: "base not in your Library") and
  `rank`. Fit counts an adapter's file size.
- **Agent:** the profile field `adapters` [{model id, name}] on llama.cpp
  and vLLM.
  - llama.cpp: each as `--lora <path>` with `--lora-init-without-apply`
    (loaded, applied at scale 0 until a request asks).
  - vLLM: `--enable-lora --lora-modules <name>=<path>` and `--max-loras`
    from the count.
  - MLX keeps its one `adapterPath`; that runtime's model id names the
    adapter.
  - The runtime reports the adapters it loaded (`Runtime.adapters`), read
    back from `/lora-adapters` (llama-server) or `/v1/models` (vLLM).
- **Driver:** `GenerateRequest.adapter` (a name). llama.cpp: the request's
  `lora: [{id, scale: 1}]` by the id `/lora-adapters` gave it; vLLM:
  `model: <adapter name>`.
- **Gateway:** `/v1/models` lists `<alias>:<adapter>` for each adapter some
  replica holds; routing for that id considers only replicas whose runtime
  reports the adapter, then the usual balancing and failover among them.
  A request for an adapter no replica holds: 404 naming the runtimes that
  could load it.

## 3. Repositories

specs (`library.yaml`, `agent.yaml`, `inference-driver.yaml`,
`gateway.yaml`), library, agent, inference-driver, gateway, ui (adapters
under a model; the profile picker).

## 4. Tests that fail before

- library `test_scanner.py::test_a_gguf_lora_is_an_adapter_of_its_base`
  (today: listed as a model) and `test_a_safetensors_adapter_is_listed`
  (today: skipped).
- agent `test_llama_cpp.py::test_adapters_load_without_apply`,
  `test_vllm.py::test_adapters_become_lora_modules`.
- inference-driver `test_lora.py::test_the_request_names_its_adapter`.
- gateway `test_routing.py::test_an_adapter_routes_only_to_replicas_holding_it`.

## 5. Acceptance (CI, Linux, about 4 minutes)

The real llama.cpp CPU build with the harness's tiny model and a tiny LoRA
made for it (a fixture GGUF adapter): two runtimes, one holding the
adapter; requests for `<alias>:<adapter>` all reach that one and differ
from the base's answer with a fixed seed; a request for the base reaches
either.

## 6. Size and risks

L (the roadmap said M), about 3 days. Risks: an adapter applied to the
wrong base (the base match is checked at profile save and at load, and a
mismatch refuses naming both); llama-server's per-request `lora` field
depends on the build (checked against the managed build's `/props`).

**Calls:** none.
