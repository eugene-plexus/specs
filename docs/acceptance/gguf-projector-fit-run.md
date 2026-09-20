# GGUF projector fit correction — 2026-09-20

Found while accepting R6.1 on the operator's RTX 5090. Starting the previously
working 70,000-context Huihui-Qwen3.8-27B-abliterated-Q6_K_L profile was refused:
29.4 GiB required versus 28.8 GiB free, with no managed runtime holding memory.
The error was in required-memory accounting, not an identified VRAM reservation.

Library contract `918bbda`; Library implementation `766ecb8`, pinned by both
installers. The NAS Library supplies the Windows agent's fit answer, so updating
the NAS container supplies this correction without a Windows agent update.

The scanner correctly includes the optional projector in a model's disk total.
The fit route incorrectly reused that total for GPU weights and maximum context.
The catalogue already excludes the separately listed projector. The actual
runtime argv loads the main GGUF at 70,000 context and has no `--mmproj`.

| Term | Bytes | GiB |
| --- | ---: | ---: |
| Main GGUF | 24,945,124,640 | 23.2320 |
| f16 KV at 70,000, from its actual header | 4,587,520,000 | 4.2725 |
| Existing compute-buffer allowance | 1,073,741,824 | 1.0000 |
| Correct main-model estimate | 30,606,386,464 | 28.5044 |
| Unused mmproj-model-bf16.gguf | 931,145,888 | 0.8672 |
| Previous estimate, including projector | 31,537,532,352 | 29.3716 |

The route now removes the known separate GGUF projector size from both memory
calculations. Disk totals, shard accounting and safetensors accounting are
unchanged. Fit notes explicitly say that loading the projector for images needs
additional memory. An unknown projector size cannot be subtracted.

Verification:

- Real loopback Library process with disposable config/state scanned the NAS
  model directory read-only. At a caller-supplied 28.8 GiB budget and 70,000
  context, its HTTP fit response was `fits`, 30,606,386,464 required bytes,
  maximum context 74,752. The actual agent `LibraryFitClient` fetched the same
  answer over HTTP. No engine was launched or installed service changed. The
  temporary server exited through uvicorn shutdown.
- `tests/test_guidance.py::test_a_projector_on_disk_does_not_change_text_model_fit`
  scans real fixture GGUF files, adds a projector, fully rescans, and verifies
  disk size grows while required bytes, verdict and maximum context stay fixed.
  Runs for single-file and two-shard models at an exact memory-fit boundary.
- Independent deliberate regressions in disposable source copies restore the
  old disk-total input to required memory and to maximum context separately.
  Both are caught; baseline and restored checks pass.
- Full Library suite: Windows **489 passed, 24 skipped**; Linux/Python 3.12
  **492 passed, 21 skipped**. Skips cover opt-in hub/model tests and unavailable
  platform link types. Ruff lint/format and mypy pass; codegen regenerated from
  the published contract. No wire shape changed. Gateway/UI consume only a
  description change here and retain their pins; other consumers do not generate
  Library schemas.

This verifies the corrected estimate and client path, not a new GPU engine load.
The operator's next runtime/benchmark run verifies that after updating the NAS.
