# SD1 acceptance: speculative decoding for llama.cpp

2026-10-18, Amish_Station (RTX 5090, Windows 11), llama.cpp b11719 (CUDA 13.4).
Design: [`docs/design/speculative-decoding.md`](../design/speculative-decoding.md),
Troy's calls S1-S5.

## The run through the agent

`python scripts/sd1-acceptance.py --server C:/sd1-acceptance/engine/b11719/llama-server.exe --models C:/sd1-acceptance/models`,
from the agent's venv, on its own ports with every `EUGENE_PLEXUS_*` cleared.
Files: `unsloth/Qwen3.5-9B-MTP-GGUF/Qwen3.5-9B-Q4_K_M.gguf` (its own head),
`ggml-org/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q4_K_M.gguf` with
`mtp-Qwen3.6-27B-Q4_0.gguf`. Context 32,768, one code-edit prompt, thinking off,
512 tokens. Exit 0, 8 of 8:

| Check | Result |
| --- | --- |
| S1 the Library says what each model can draft with | PASS: 9B `mtpHead`; 27B `draftFiles` [the MTP file, `mtp`]; the file skipped as `draft` |
| S2 a companion outside the model's folder is refused at declaration | PASS: 400, "must be in the model's own folder" |
| S3 no speculation flags still reuses repeated text, and says so | PASS: `--spec-type ngram-mod --metrics`; 931 drafted, 248 kept |
| S4 the model's own head | PASS: `ngram-mod,draft-mtp`; 1,161 drafted, 394 kept |
| S5 a companion file | PASS: `--spec-draft-model` the MTP file, named on the run; 1,198 drafted, 370 kept |
| S6 admission at least the GPU's use, own head | PASS: requires 9.47 GiB, used 7.72 GiB |
| S6 admission at least the GPU's use, companion | PASS: requires 24.35 GiB, used 23.39 GiB |

Default runtime (S3): admission 7.72 GiB, GPU 6.75 GiB, 266.5 tok/s.

The first attempt stopped at S3: its prompt left thinking on, so the 384
tokens were reasoning with nothing for the n-gram to repeat. The script now asks
for a file back, as the S4 measurement did.

## The S4 measurement

llama-server directly, before admission's allowances were written; the table is
in the design doc ("Measured on the 5090"). Admission counts 256 MiB for reusing
repeated text (measured 163-183 MiB), 1,792 MiB of draft context for the model's
own head or a companion (measured 996 MiB on the 9B, 1,446 MiB on the 27B, at
peak), and a companion's file.

## Sabotage

`speculation._same_folder` made to answer True, restored from a copy (`cmp`
identical): `tests/test_speculation.py::test_a_companion_must_sit_beside_its_model`
failed, alone, 1 of 67 across `test_speculation.py` and `test_runtimes.py`; 67 of
67 again after the restore.

## Rerun with the companion fetched through Discover (library#13, 2026-10-18)

`--from-discover`, from the agent's venv on its own ports with every
`EUGENE_PLEXUS_*` cleared, library 22ee70d, agent 8920021, b11719. The Library
got hard links to the two models without the MTP file, and fetched it the way
Discover does. 10 of 10:

| Check | Result |
| --- | --- |
| D1 the catalogue offers the MTP files as companions, not DFlash as versions, and says where the owned 27B sits | PASS: companions BF16, Q4_0, Q8_0; versions Q4_K_M, Q8_0, BF16; `root` and `folder` `ggml-org/Qwen3.6-27B-GGUF` |
| D2 the companion downloads alone into the 27B's folder | PASS: `mtp-Qwen3.6-27B-Q4_0.gguf` beside the model |
| S1-S6 | PASS, the same counts as above: S3 931/248, S4 1,161/394, S5 1,198/370; S6 9.47 ≥ 7.72 GiB and 24.35 ≥ 23.39 GiB |

Decode: default 265.8 tok/s, own head 318.8, companion 140.7.
