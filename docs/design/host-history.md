# Host history

**Status: calls H1-H6 taken 2026-10-18 (Troy took every recommendation);
building.** Contract: `GET`/`DELETE /v1/node/history` and the `HostHistory`
schemas in `agent.yaml`.

The second half of the sysadmin dashboards (memory `project_admin_dashboards`;
[audience roadmap](audience-roadmap.md), "Owed, small"). The gateway half is
built ([gateway operations dashboard](gateway-operations-dashboard.md)) and
says what it left out: "Historical CPU/GPU/RAM telemetry, alert
rules/notifications, SLO evaluation and longer/finer-grained retention are
separate capabilities". This is the first of those: what each machine's
hardware did over time.

## What exists

- **Live reads, no history.** The agent reads each GPU's memory for admission
  (`gpu_probe`: DXCore and the `GPU Adapter Memory` PDH counters on Windows,
  sysfs on Linux, Metal on macOS) and serves it in `GET /v1/node` as
  `devices` (`ComputeDevice`: kind, name, index, memory total and free,
  shared). The library's `HostHardware` adds CPU count and RAM total and
  available. Nothing is kept: each read replaces the last.
- **The root already polls every node.** Control asks each node's
  `GET /v1/node` every `nodePollIntervalSeconds` and keeps the latest
  `devices` on the `Node` record, with `lastSeenAt`.
- **Not read anywhere:** GPU utilization, temperature, power, CPU use, disk
  space of the model and engine folders, network.
- **The pattern to copy:** the gateway's metrics store (SQLite, raw rows
  plus hourly rollups, retention in days, served by `groupBy` and windows,
  shown as hourly charts with tables beside them).

## The design

1. **Each agent records its own host (H1).** A sampler in the agent, every
   10 seconds, writes one row to a SQLite file in its state directory, and
   rolls rows up into minute and hour buckets (min, mean, max per series).
   A single-machine install gets history with no control root involved, a
   node that loses the root keeps recording, and the replicated log never
   carries time series.
2. **What a sample holds (H2).** Every series is `null` when this host cannot
   read it, never 0, and the screen says "not reported" with the reason.
   - Per GPU: memory used and total; **Eugene's share** of it (what the
     agent's own runtimes hold, from the admission ledger, against everything
     else); utilization percent; temperature; power in watts.
   - CPU use percent, RAM used and total, swap used.
   - Free space on each model folder's and the engine folder's volume.
   - Runtimes running, and loading.
   - Where each reading comes from, vendor-neutral first: utilization from the
     `GPU Engine` PDH counters on Windows and `gpu_busy_percent` on amdgpu;
     temperature and power from NVML (`nvml.dll` / `libnvidia-ml.so`, which
     every NVIDIA driver installs, loaded with `ctypes`, no dependency) and
     amdgpu's hwmon; Apple silicon reports memory only until measured
     otherwise. Spawning `nvidia-smi` every 10 seconds is not used.
3. **Retention (H3).** Raw 10-second rows for 6 hours, minute buckets for 7
   days, hour buckets for 90 days: about 14,000 rows, a few megabytes for a
   two-GPU host (estimated, to measure). Each is a setting with the size on disk beside it.
4. **One endpoint per agent (H4).** `GET /v1/node/history?from=&to=&step=`
   returns buckets for the series asked, with the resolution chosen from the
   window unless `step` names one, and says when a bucket is partial or a
   sample was missed. The console reads every node through the agent's
   proxy (`node:<name>`), so a fleet view is one screen, not a hop between
   node UIs. A node that does not answer is shown as not answering, with
   its last reading's age.
5. **The screen (H5).** A **Hosts** page beside Gateway metrics, in the same
   reading order: a fleet row per machine (GPU memory, utilization,
   temperature and Eugene's share as small charts over the window, plus
   now-values), then one machine's detail with its charts and tables beside
   them, the windows the gateway page uses (1 h, 6 h, 24 h, 7 d, 30 d), and
   JSON export. Dials only where there is a real denominator (memory of
   total, utilization of 100%), as on the gateway page.
6. **Settings (H6).** `hostHistory`: on or off (on by default), sample
   seconds, the three retentions, all through `PATCH /v1/config` with the
   usual metadata and shown on the node's settings page. Turning it off
   deletes nothing until asked.

## Not in this slice

Alerts and notifications, SLOs, fleet-wide aggregates stored at the root,
network throughput, per-process CPU, and history from before an install
upgrades to this.

## Calls for Troy

| Call | Question | Recommendation |
| --- | --- | --- |
| H1 | Where does history live? | **Each agent, for its own host** (above). The alternative, the root keeping what its node poller already reads, is less work but loses single-machine installs and gaps whenever the root is away, and puts time series in the replicated store |
| H2 | Which readings? | **All of the list above**, with `null` and a reason where a host cannot read one. The smaller choice is memory only, which needs no new probes but answers little that the live view does not |
| H3 | Retention | **6 h raw, 7 d minutes, 90 d hours**, each a setting |
| H4 | Contract | **`GET /v1/node/history`** on the agent (new schemas `HostHistory`, `HostSeries`, `HostBucket`), plus the `hostHistory` settings. This is the contract change to approve |
| H5 | The screen | **A Hosts page beside Gateway metrics**, fleet first, then one machine. Or: a History section on each node's existing page |
| H6 | On by default? | **On.** The cost is a few probe calls every 10 s and a few megabytes (both to measure before it ships), and history is only useful when it was already recording before something went wrong |

## Calls taken (Troy, 2026-10-18)

All six recommendations: H1 each agent records its own host; H2 every reading,
`null` with a reason where unreadable; H3 6 h raw, 7 d minutes, 90 d hours; H4
`GET /v1/node/history` plus the `hostHistory*` settings; H5 a Hosts page
beside Gateway metrics; H6 on by default once measured.

## What building found

- **The sampler's cost on this box** (RTX 5090 beside the AMD integrated GPU,
  Windows 11, 2026-10-18): one full sample (PDH `GPU Engine` utilization over
  789 instances, `GPU Process Memory`, `GPU Adapter Memory`, NVML
  utilization/temperature/power/memory, psutil CPU/RAM/swap/two disks) took
  1.4 ms of wall time and 1.6 ms of CPU, 0.016% of one core at one sample
  per 10 s. NVML's first load took 10 ms. On by default stands.
- **Eugene's share is measured per process, not taken from the admission
  ledger.** The ledger only holds reservations for launches that have not
  taken their memory yet (`reservations.py`); a ready runtime is not in it.
  The share is the sum of the runtimes' process trees' memory on each card:
  the `GPU Process Memory` counters on Windows (every vendor), NVML's process
  lists on Linux NVIDIA, `fdinfo` on amdgpu.
- **`DELETE /v1/node/history`** was added: "turning it off deletes nothing
  until asked" needed a way to ask.

## Build order

1. Contract (H4).
2. Agent: sampler and probes, store and rollups, endpoint, settings, with
   tests against fake probes and a measured run on this machine (the 5090
   and the AMD integrated GPU) and on Linux CI.
3. UI: the Hosts page, against the endpoint and a node that does not
   answer.
4. Acceptance: two nodes, a model loaded and unloaded during the window,
   the series and Eugene's share following it, a node stopped and its gap
   shown as a gap.
