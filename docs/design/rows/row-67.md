# Row 67: local image models and local media

Lane LIB. Cross risk. Sources: Troy, 2026-10-09 (memory
`project_image_models_after_v02`: after v0.2, Stable Diffusion-style
models in the Library with an engine to run them; keep general: Civitai as
a catalogue source, an engine `accepts` field, an image fit model by
resolution and batch, shared-file-safe delete, an image-generation
capability), `library-sources-and-engines.md` (ModelScope, Ollama
registry and Civitai not built), `workbench-media-screens.md` (the four
media screens exist; "local media models need their own admission
design"), `workbench.md` §8 (a GPU app admitted by the agent's ledger),
`images-run.md` (stable-diffusion.cpp, speaches and Kokoro unmeasured).
The audience research found no recorded demand yet; Troy put this at the
back.

## 1. What it delivers

- **Local image generation:** image models (Stable Diffusion 1.5, SDXL,
  Flux, as GGUF or safetensors) in the Library, run by stable-diffusion.cpp
  (wrapped and acquired like llama.cpp), served on the gateway's existing
  `/v1/images/generations`, and so on Workbench's Images screen and the
  `image_generation` tool.
- **Local speech:** text to speech and transcription engines (Kokoro;
  whisper.cpp) the same way, on the existing speech doors.
- **Civitai as a catalogue source** for image models, beside Hugging Face.

## 2. Design

- **Library:** recognises image model files (architecture from headers:
  SD1.5, SDXL, Flux; VAE and text encoders as companions, as projectors
  are), lists them with `capabilities: [image-generation]`; fit by
  resolution and batch (an image fit model: VRAM for the UNet or DiT at the
  chosen resolution, plus encoders and VAE); shared-file-safe delete.
- **Engines:** `stable-diffusion-cpp` (its server mode; managed builds per
  GPU like llama.cpp), `whisper-cpp` (server), `kokoro` (a pinned
  release); each an adapter with its GUI schema.
- **Admission:** an image or speech runtime takes VRAM like a chat runtime
  in the agent's ledger; Workbench's media screens see them as local
  models (`locality: local`).
- **Gateway:** image, speech and transcription doors route to local
  runtimes the way chat does, with model roles `image`,
  `text-to-speech`, `speech-to-text` (row 71).
- **Civitai:** a `CatalogueSourceKind` with search, model versions and
  downloads (API token optional), and its licence shown before download.

## 3. Repositories

library, agent, inference-driver (image and audio calls to the new
engines), gateway (routing), ui, specs (contracts: capability, source
kind, engine kinds).

## 4. Tests that fail before

Recognition of each file family; fit at 512, 1024 and 1536 px; the
adapters' argv; routing of `/v1/images/generations` to a local runtime.

## 5. Acceptance

CI on Linux with the CPU builds of stable-diffusion.cpp and whisper.cpp
and tiny fixture models: one image and one transcription through the
gateway. The GPU measurement is the orchestrator's on the 5090 when the
row is built.

## 6. Size and risks

L, built in parts (67a images, 67b speech, 67c Civitai). Risk: large
downloads and licences (shown before download); admission counting image
memory correctly (the fit model is measured on the 5090 first).

**Calls:** none.
