# A8 shared application load

Completed 2026-09-21. The [workload and targets](a8-workload-plan.md) were declared
before measuring. These are development-build results on one host, with CPU
inference. They are not a five-user product guarantee or a GPU benchmark.

## Configuration and scope

| Part | Measured configuration |
| --- | --- |
| Host | Windows 11 Pro x64, 10.0.26200; Ryzen 9 9950X, 16 cores / 32 logical processors; 93.56 GiB RAM. Existing interactive host, not a dedicated benchmark server. |
| Runtime | CPU-only llama.cpp b11065, 0.4.1-dev, commit `ce8caa6e6`; 8 inference threads; batch 256 / microbatch 128; 5 slots; 81,920 total context, 16,384 per slot. Zero GPU layers; no CUDA build/context. |
| Model | Gemma 4 E4B IT Q4_K_M, 5,335,291,936 bytes; SHA-256 `0ffb122c8b6921f13cbc34186e052524d0b5803b17f4867b7197a561400b3770`. Existing local file, no projector in this text load test. |
| Claude Code | Native Windows 2.1.207, bare mode with the A4 effort/settings recipe; Read/Edit/Bash restricted to a new two-file clamp task. No subscription model or external inference. |
| Open WebUI | 0.11.3, WSL2 Ubuntu 26.04, Python 3.12.14; new data directory and local login; actual authenticated application chat API and its provider translation. No RAG/indexing or title-generation background work. |
| Eugene | agent `d1cfe73`, gateway `899ae99`, inference-driver `9d2b0b4`; Windows Python 3.14.3 editable checkouts at those revisions. One isolated standalone agent with supervised gateway, driver and real engine. No control root or second gateway in this load run; A5 separately covers shared admission across gateways. |
| Access | Registered keys restricted to this model and local-only. WebUI's connection key permits 3 concurrent requests; each of two coding keys permits 1; each has a 120 requests/minute ceiling. Missing credentials return 401. |

Cold means the engine was stopped and awakened by the first request. The OS
file cache was not flushed. Later phases reuse the engine and its default prompt
cache. Temperature is zero; short chat has a 96-token output cap, coding 2,048
per request, saturation 512. Backend completion counts include hidden reasoning;
they are not a count of visible answer tokens. The instrument records **first
visible text or tool output**, not the first HTTP header or keepalive.

The three WebUI load workers use one application account/connection, submitting
three independent request sequences through WebUI's actual HTTP application
path. They do not simulate three browser UIs or three employee identities. A4's
actual browser/image/Stop evidence remains separate. The two coding clients are
real Claude Code processes and execute their confined tool loops.

## Results

**All declared targets passed in the final run**, `%TEMP%/ep-a8-run8`.
[Recomputed summary](a8-data/summary.json), [per-request observations](a8-data/requests.json),
[client measurements](a8-data/clients.json), [phase durations](a8-data/phase-times.json),
[saturation](a8-data/saturation.json), [retained gateway attempts](a8-data/gateway-metrics.json).
The public record excludes credentials, prompts, answer bodies and private paths.
The summary was recomputed successfully from these exported files alone.

Client-observed chat timings, in seconds:

| Workload | Samples | First text p50 / p95 | Completion p50 / p95 | Result |
| --- | ---: | ---: | ---: | --- |
| Engine stopped, one chat | 1 | 13.74 / 13.74 | 14.41 / 14.41 | Cold wake and answer succeeded. With n=1 these are the same observation. |
| Warm, one chat at a time | 12 | 3.00 / 3.03 | 3.67 / 3.73 | 12 correct answers; no errors or rejections. |
| Three chat workers alongside two coding tasks | 12 chats | 5.44 / 8.38 | 7.00 / 9.25 | 12 correct answers; no errors or rejections. Five requests overlapped at the gateway. |

The single Claude task completed in **72.57 s** (four model turns). The two
concurrent coding tasks completed in **97.04 s** (four turns) and **140.59 s**
(five turns). All three performed Read → Edit → Bash, produced the correct
clamp function, left the check file unchanged, passed all three assertions and
had no permission denials. The private transcripts contain successful check tool
results, independently corroborated by the instrument rerunning the checks.
Three small tasks do not establish general coding reliability.

Gateway-observer measurements include policy checks, driver and engine time,
but exclude WebUI/client setup outside that hop:

| Phase | Completed requests | First content p50 / p95 (s) | Completion p50 / p95 (s) | Known generated tokens / phase wall time | Aggregate tokens/s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single chat | 12 | 2.86 / 2.88 | 3.53 / 3.59 | 487 / 33.77 s | 14.42 |
| Single coding task | 4 | 12.27 / 16.45 | 12.98 / 24.78 | 1,041 / 72.60 s | 14.34 |
| Mixed chat + coding | 21 | 7.94 / 26.91 | 8.80 / 31.19 | 3,430 / 141.01 s | 24.32 |

The mixed phase is a finite burst: chat workers finish before the coding tasks.
It is not sustained five-client traffic. Throughput includes hidden reasoning
and measures aggregate generated tokens over the whole phase, not per-user
decode speed. The short requests had 32 prompt tokens and 11–56 completion
tokens (21–50 visible characters). Coding requests had 883–1,293 prompt tokens
and 100–784 completion tokens, below their 2,048 cap. The engine confirmed five
slots with 16,384 context each. Nearest-rank p95 with 12 samples is the largest
sample; none of these short runs establishes a stable service-level percentile.

Saturation held **three engine slots actively decoding at least eight tokens**
under WebUI's three-request key. A fourth request received HTTP **429 in 18 ms**,
`rate_limit_error` and `Retry-After: 29`; it was not queued for inference. Closing
all three application streams made the slots idle in **0.207 s**. The same key's
fresh request produced visible text **3.131 s after cancellation** and completed
successfully. The retry hint is conservative lease-based guidance, not a claim
that released capacity remains blocked for 29 seconds.

Across the final run: **39 completed inference requests, one intentional
admission refusal and three cancellations; zero unexpected HTTP/stream errors**.
All three cancelled request IDs appear in retained gateway metrics with
`retryDisposition: indeterminate` and unknown usage. Tokens already computed
during those cancellations are not counted as zero or included in the known
throughput totals. All acceptance-owned processes exited after the run.

## Defects found and corrected

Before the driver correction, the first real WebUI request with a local-only
key failed. The gateway's policy-confirmation read has a four-second budget,
but `/v1/info` performed image, context and embedding probes sequentially against
the stopped runtime. The embedding probe could even inherit the long generation
timeout. Consequently the gateway refused with 403 before waking the local model;
WebUI surfaced the upstream refusal as a 400. Declaring the custom backend local
did not fix the timeout.

The new endpoint regression took **4.538 s** before the fix and failed the
3.5-second gate. Driver `9d2b0b4` probes independent optional capabilities in
parallel with a 2.5-second limit each. Known active-engine locality, runtime
identity, tools and settings remain available. Timeout results are conservative:
image false, context/embeddings unknown. Probe tasks are cancelled, and a later
successful read can recover the capabilities. The gateway's policy deadline and
local-only enforcement were not relaxed. Actual cold wake succeeded afterward.

No API schema, UI or generated-contract change was required. Both development
installers select the corrected components. Frozen alpha assets and the owner's
running Windows service, GPU workload and NAS remain unchanged.

The next complete load attempt (`ep-a8-run7`) exposed a second defect during
cancellation. Three genuinely decoding engine slots were released, but the next
request received a “Backends cooling down” stream error: the gateway had counted
client cancellations as three backend failures. Five new regression cases failed
before correction (generate, stream cancellation, stream close, embeddings and a
cancelled recovery probe).

Gateway `899ae99` now treats cancellation as neutral circuit evidence. It releases an
owned recovery probe without counting either success or failure, changing a real
cooldown or clearing another probe's ownership. Attempt metrics still retain
indeterminate usage, and cancellation does not authorize replay. Existing real
backend failures, bounded retry hints and the two-success recovery rule retain
their tests. The final run repeats the workload against both corrections.

## Instrument findings and retained failed runs

Early setup attempts refused the unnecessary `--slots` extra argument (the engine
already enables that endpoint), then found the new WebUI data directory had to
exist before its database opened. The instrument was corrected; no application
result came from those attempts. Two subsequent cold-start attempts reproduced
the real capability-probe defect above.

The first post-fix measurement completed the baseline and mixed coding tasks,
but its chat checker searched only for decimal digits, misclassifying number-word
answers. A separate diagnostic confirmed “Forty plus twenty-five equals
sixty-five.” The corrected checker accepts the expected number in either form
and retains answers privately for review. The final workload uses the same
prompts, limits and latency targets.

That run's saturation setup also waited for visible text; the reasoning model
spent its entire 512-token cap before producing visible text, so it never reached
the intended cancellation step. The corrected instrument waits for three actual
engine slots to be decoding at least eight tokens, then disconnects their client
streams. This tests cancellation during computation, including hidden reasoning,
without assuming that visible output has begun. Failed/preliminary measurements
remain under `%TEMP%/ep-a8-run1` through `ep-a8-run6`; they are not silently pooled
into the final sample.

## Reproduction and interpretation

Use `scripts/a8-shared-load.py --help` with a disposable new `--directory`, the
CPU engine/model paths, native Claude executable, existing WSL WebUI Python and
the WSL host interface address. The driving Python needs the agent/gateway/driver
revisions above plus httpx, PyYAML, FastAPI and uvicorn. The script binds its
observer only to the WSL host interface and uses temporary ports; it changes no
firewall, service registration or persistent Eugene environment. It signals
only its own agent and WebUI for shutdown; the agent stops its children.

The new private WebUI data directory lives in the WSL user's cache and must be
protected like the run directory. Do not publish `private-*.json`, application
databases, `agent.yaml`, client-key stores, engine props or Claude transcripts.

Run `python scripts/a8-summarize.py RUN_DIRECTORY` to recompute the summary;
`--export NEW_DIRECTORY` writes only the public measurement records. Quantiles
use nearest rank. Distinguish whole coding-task latency from its individual
model requests, and client-observed chat latency from the observer's gateway
stream timings. Report unknown usage on cancellations as unknown, not zero.
The checked-in data can also be verified with
`python scripts/a8-summarize.py docs/acceptance/a8-data` without running a model.

Validation: Windows gateway **550 passed**; driver **508 passed, three opt-in
provider checks skipped**; lint, formatting and gateway type checking passed.
Exact-revision component CI passed for
[gateway `899ae99`](https://github.com/eugene-plexus/gateway/actions/runs/35633334156)
and [driver `9d2b0b4`](https://github.com/eugene-plexus/inference-driver/actions/runs/35632646757).
The release-artifact check confirmed frozen installer bytes/checksums and matching
Windows/POSIX development component pins.

For a pilot, use the [support matrix](../support-matrix.md), keep one application
endpoint, and budget key concurrency against engine slots. Increasing the number
of independently allowed keys can oversubscribe an engine; these settings are
not a global five-user scheduler. Physical GPU capacity, native Linux unattended
boot, remaining owner Windows service checks, Mac acceptance and moderated
friend sessions remain separate obligations.
