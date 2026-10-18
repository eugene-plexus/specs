# Host history acceptance

2026-10-18, Amish_Station (RTX 5090 beside the AMD integrated GPU, Windows 11),
llama.cpp b11719. Design: [`docs/design/host-history.md`](../design/host-history.md),
Troy's calls H1-H6. Agent d65ffa4; UI a40a37d5.

## The run

`python scripts/host-history-acceptance.py --server C:/sd1-acceptance/engine/b11719/llama-server.exe --model C:/sd1-acceptance/models/unsloth/Qwen3.5-9B-MTP-GGUF/Qwen3.5-9B-Q4_K_M.gguf`,
from the agent's venv, with every `EUGENE_PLEXUS_*` cleared. It started a control root and two
enrolled agents on ports the OS picked, both recording every 2 s. B listened on this machine's
LAN address only, because A's proxy refuses a node that advertises loopback. Exit 0, 6 of 6:

| Check | Result |
| --- | --- |
| Both record; the console reads both through A's proxy | PASS: every series fresh; nothing unreadable on this box (NVML gives temperature and power) |
| A model loaded on A | PASS: A holds 5.9 GiB of a 5.5 GiB file and runs 1 runtime; B, on the same card, sees it rise 5.8 GiB and holds nothing |
| Unloaded | PASS: A's share back to 0 MiB; the window shows the rise to 5.9 GiB and the fall |
| B stopped, then started | PASS: A's proxy answered 502 naming B's address; B's window shows 7 empty buckets with null values between recorded ones |
| Recording off, DELETE, on | PASS: no new sample, the record still readable with `enabled: false`; DELETE emptied it; on again, it records |
| Settings | PASS: 1 s refused; the retention fields say "This machine's history takes 0.4 MB on disk now." |

The first two attempts stopped on harness setup, not product defects: B advertised loopback
(the proxy refuses it by design), then the real llama-server sat outside `engineBinaryRoots`.

## Measured, not checked by the script

- One sample: 1.4 ms wall, 1.6 ms CPU (0.016% of a core at 10 s).
- The store at full default retention, 17 series: 7.6 MB.

## Not covered

- Linux and amdgpu probes are unit-tested against fakes only; no AMD Linux machine reported.
- The Hosts page was tested with vitest against a mocked agent (fleet row, a machine not
  answering, "not reported" with the reason, a gap, recording off). This run did not open it in
  a browser.
- Needs the GPU, so it does not run in CI.
