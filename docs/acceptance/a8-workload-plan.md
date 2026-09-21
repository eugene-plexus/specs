# A8 declared workload and acceptance targets

Declared before measuring on 2026-09-21. The isolated Windows host has a Ryzen
9 9950X (16 cores / 32 logical processors) and 93.56 GiB RAM. No live service,
NAS, GPU workload, firewall or host startup setting is changed.

Use the A4 Gemma 4 E4B IT Q4_K_M model with the CPU-only llama.cpp b11065 build,
eight inference threads, five continuous-batching slots, 81,920 total context
(16,384 per slot), batch 256 and microbatch 128. This measures text workloads;
image correctness retains its separate A4 evidence. GPU layers are zero and the
CPU build does not load CUDA. Model files are existing read-only assets.

The real client paths are Open WebUI 0.11.3 on WSL2 (authenticated application
chat API through its actual processing/translation stack) and native Windows
Claude Code 2.1.207 (confined Read/Edit/Bash coding task in a new repository).
This is not five people operating browsers. A4 separately exercised the browser,
image attachment and Stop controls. No stub supplies an inference result.

1. **Cold start:** one short Open WebUI question with the runtime stopped.
   “Cold” means engine not running, not a flushed OS file cache.
2. **One client:** 12 sequential short chat requests, then one Claude coding
   task. Chat asks for the sum of two integers in one sentence, capped at 96
   output tokens. Coding inspects two files, fixes a clamp function and runs its
   three checks; at most ten turns, 2,048 output tokens per request.
3. **Five clients:** a barrier releases three chat workers and two Claude tasks
   together. Each chat worker makes four requests with one second between its
   responses and its next request. Coding tasks independently finish their
   bounded tool loops. No retries are added by the load instrument.
4. **Saturation/cancellation:** hold three long generations under the Open WebUI
   key, request a fourth, close the admitted streams, then submit fresh work.
   Check real engine slots and retained gateway metrics, not just HTTP status.

A5 admission: the Open WebUI application key has three concurrent requests;
each coding task's key has one. All are limited to this model, local-only,
120 requests/minute. These are application-key limits, not an automatic global
five-user limit. Adding keys without budgeting engine slots can oversubscribe it.

Targets for this CPU demonstration: cold first text within 60 s and completion
within 120 s; warm single-chat first text within 30 s and completion within 60 s;
mixed-chat first text within 90 s and completion within 180 s; each coding task
finishes its verified edit/check within 600 s. No admitted work hangs beyond the
configured 600 s gateway deadline. Saturated gateway admission returns an
intelligible 429 with retry guidance within 2 s. After cancellation, owned engine
slots become idle and the same key can start fresh work within 10 s.

Report failures against these targets; do not loosen them after observing data.
An exceeded latency target is evidence of a workload limit, not automatically
a gateway bug. Investigate starvation or leaked work and fix a demonstrated
defect before repeating its affected run.

Record per-request monotonic first-content and completion timings, backend
prompt/completion token counts when supplied, status/stream errors, cancellation,
input/output character counts and overlap. A transparent local observer adds a
hop: its timings include gateway/driver/engine work, while client timings also
include application processing. Report both separately. First-content means text
or tool output, not headers, keepalives or a role-only event. Throughput is known
completion tokens divided by the measured phase wall time, with its scope stated.
p50/p95 use nearest rank and disclose sample counts; 12 chats do not establish a
stable service-level percentile or a universal user capacity. Raw records exclude
keys, prompts, image bodies and private model paths.

Carried Mac, modest-GPU, physical reboot-before-sign-in and native Linux boot
checks remain pending unless actual new evidence establishes them. CI services,
WSL systemd and synthetic hardware fixtures must remain separately labelled.
