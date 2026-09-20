# Control-plane measurements

Collected for R5 on 2026-09-20 from the linked acceptance records. These are
historical observations of particular setups, not a benchmark of the current
release, a comparison with other products, or a prediction for another machine.
The engine determines model throughput. These records concern routing,
streaming delivery, process wake-up, and model loading around it.

## Can a request survive a stopped replica?

The [M6 six-process run](m6-six-process-run.md), on 2026-09-10, used two
llama.cpp replicas of Qwen3-1.7B Q8_0 on one RTX 5090 in Windows. After one
engine was killed, the next completion came from the surviving replica in
**172 ms**, with **one attempt**. The gateway refresh had already excluded the
dead replica. This proves survival in that scenario; it does **not** measure
failure detection time or the latency of trying a failed backend and cascading.
It is not a two-GPU or two-machine performance result.

## How long did an idle model take to wake?

In the same M6 run, a request for the idle-unloaded alias waited **2,546 ms**
for wake-up, spent **141 ms** generating, and finished in **2,953 ms** wall
time. Exactly one replica woke. Both replicas had previously unloaded,
releasing **2,762 MiB** of GPU memory. These timings describe that small
model and machine; larger models and cold storage can take much longer.

## Does the browser proxy buffer the whole answer?

The [cross-node console run](cross-node-console-run.md) sent the same request
through two agent proxies and directly to the gateway on the live LAN install.
Both routes delivered **71 stream frames**. Through the proxies, the first
token arrived at **179 ms**, **6.8%** of that request's duration; directly, it
arrived at **12.9%** of that request's duration. The model was
`qwen3-coder:30b`.

This was a check that streaming began well before completion. The percentages
have different request-duration denominators, and the record does not provide
a repeated, controlled latency comparison. They do **not** show that proxying
is faster, nor do they isolate proxy overhead. R5's earlier “5–6.8%” shorthand
is narrowed here to the **6.8%** observation supported by this record.

## What did a node-local copy change?

The [node-local copy run, section 14.3](../design/node-local-model-copy.md)
used the Windows RTX 5090 worker and a NAS-hosted Library on 2026-09-17. The
model was Huihui-Qwen3.8-27B-abliterated Q6_K_L, **24.95 GB** (about 23.2 GiB).

| Start | Time to serving |
| --- | --- |
| Read the model over SMB | 266 s |
| First start with copying enabled | 290 s: 260 s copying and 30 s loading |
| Subsequent start from the local copy | 21 s |

The first copied start cost **24 seconds more** than the SMB baseline. The
subsequent local start used a **warm filesystem cache**, because the file had
just been copied. Cold loading after reboot was not measured. The result shows
the value of reusing local bytes in that setup; it does not promise a
21-second cold start. Original Library files remained untouched.

## How much overhead did the request layer add?

The [R1.1 one-client run](one-client-run.md), on Windows 11 and Python 3.12
on 2026-09-18, reported **3.2 ms** end-to-end control-plane overhead against a
fixed-delay stub backend. It isolated HTTP client construction and scheduling
without a GPU or model. The earlier approximately **116 ms** observation was
an implementation defect caused by rebuilding HTTP clients per request,
subsequently fixed. This is an internal before/after measurement, not an engine
or competitor benchmark, and predates R8's cached Library lookups.

## What remains unmeasured?

R6 will add the profile benchmark instrument for speed at the context depth
chosen by the operator. Memory-fit guidance currently estimates capacity; it
does not measure that machine's decode speed. The ten-minute first-use target,
moderated usability sessions, and outstanding physical-host checks remain
under the [release roadmap](../design/release-roadmap.md). These historical
numbers do not satisfy those gates.
