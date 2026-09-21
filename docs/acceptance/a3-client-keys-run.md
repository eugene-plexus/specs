# A3 install-wide client-key acceptance

Run date: 2026-09-21 (America/Chicago). All execution used disposable loopback
processes and temporary state. The live NAS, Windows service and GPU workload were
not updated or used. Troy can continue accumulating slices before a live update.

## Isolated process acceptance

`scripts/a3-client-keys-acceptance.py` starts one real control root, two real agents
and two real gateways. Enrollment, key management and authorization use HTTP.
Gateways receive public Ed25519 verification material and service tokens only.
Existing signed client tokens and their old-format local metadata exercise migration.

| Check | Windows | WSL/Linux |
| --- | --- | --- |
| Import active and revoked legacy records; retain IDs and show origin/status | Pass | Pass |
| Mint through agent A; use at both gateways; revoke through agent B | Both deny in 0.185 s | Both deny in 0.226 s |
| Restart gateway while local agent is down | Revocation retained; permission expires | Same |
| 24 simultaneous requests, no cache, real unresponsive HTTP source | 0.427 s; one policy read; all 503 | 0.442 s; one policy read; all 503 |
| Control outage; restart both gateways with stale persisted caches | Both fail closed; revoked keys stay refused | Same |
| Restore agent/control; keep operator management usable | Pass | Pass |
| Invalid, expired and unregistered credentials after recovery | Refused | Refused |

The process instrument uses shortened settings: 0.15 s refresh, 0.4 s total
gateway timeout, 3.5 s maximum policy age and 0.1 s initial retry. It separately
asserts production defaults of **15 s / 4 s / 60 s**. These timings demonstrate
the implemented mechanism, not a measurement of the live install or a load limit.
Production's documented healthy revocation bound is 20 seconds; an outage cannot
extend cached permission past 60 seconds plus five seconds clock tolerance.

Run logs and state were retained at `%TEMP%/ep-a3-acceptance-8z3ie7nv` and
`/tmp/ep-a3-acceptance-gz5_ht7s`. CI runs this same instrument on Windows and Linux
against the exact development installer pins.

## Baseline reproduction

A separate isolated HTTP probe ran the pre-A3 gateway at `9f56fbb` and the new
gateway with the same correctly signed, unregistered client key, no reachable
agent and no policy cache. The old gateway returned **200**; A3 returned **503**.
Neither process received a private signing key. Probe logs were retained at
`%TEMP%/ep-a3-before-after-dplnu7ou`.

## Component and delivery checks

- **Agent:** 954 tests pass on Windows (4 platform skips); 938 pass on Linux
  (20 platform/environment skips). Atomic-write failure does not acknowledge a
  change or replace the previous record file. Corrupt storage fails closed;
  an unreadable revocation never turns into an active key.
- **Control:** 172 tests pass on both systems. New operations participate in
  byte-identical log replay, snapshot bootstrap and compaction. Signed imports
  are idempotent, preserve revocations and refuse collisions/forgeries. Services
  cannot mint or revoke; only agent/gateway services may read minimal policy.
- **Gateway:** 468 tests pass on both systems. Coverage includes missing/corrupt/
  stale/wrong-scope/future caches, clock rollback, revision regression, shared
  refresh cancellation, retry backoff, persistence failure and both API error
  formats. Known revocations survive restart and clock rollback.
- **UI:** 759 tests pass. Migration origin, errors, recovery refresh and registry
  scope are exercised. TypeScript, lint, formatting and production export pass.
  All 184 static assets are byte-identical in the staged build, distribution
  checkout and built wheel.
- Python lint, formatting and type checks pass. OpenAPI validation and lint pass.
  The R8/A2 isolated HTTP regression still preserves caller settings, profiles,
  structured output and fallback. Installer isolation and release-pin checks pass.

## Implementation and delivery

The [design](../design/install-wide-client-keys.md) was committed before the
contract consumers. The [operator guide](../client-keys.md) explains migration,
update order, outage behavior and recovery. Client metadata lives in the existing
control log and snapshots; no separate identity service was added. Standalone
agents keep their local registry. No release tag or alpha asset was changed.

| Component | Commit |
| --- | --- |
| Contract | `5cb26fe1c44a41f1a93184a687bafcfb1ff50f75` |
| Agent | `c11dbfdb6e560a6121e1de1f03a23935bf3b6956` |
| Control | `1b335ea42a079988d2758bf1c8cb57dbcea99f93` |
| Gateway | `26cf68ed52278e2c2aa5c692915d15ee2effb134` |
| Inference driver | `42e741fa328add00cd57502e0a8d40a20ada1793` |
| Library | `68051487672b096e5218c02c15f9a76dbeb9a976` |
| UI source | `3db56af6af7e8f5b647d73e01c1c32d646ccdca9` |
| UI distribution | `e9c97d58527883020462efaed40ee864b3c0cb3d` |
| Development installer delivery | `4b0024b62c49d7ebb4a29ed44ac9f9354ed44833` |

All six component workflows passed: [agent](https://github.com/eugene-plexus/agent/actions/runs/35596003731),
[control](https://github.com/eugene-plexus/control/actions/runs/35595921315),
[gateway](https://github.com/eugene-plexus/gateway/actions/runs/35595925881),
[driver](https://github.com/eugene-plexus/inference-driver/actions/runs/35595967802),
[library](https://github.com/eugene-plexus/library/actions/runs/35595970166), and
[UI](https://github.com/eugene-plexus/ui/actions/runs/35595931018).
The installer delivery's [cross-repository CI](https://github.com/eugene-plexus/specs/actions/runs/35596081631)
and [container build](https://github.com/eugene-plexus/specs/actions/runs/35596081537)
also passed, including the new five-process acceptance on both CI operating systems.
The alpha tag still resolves to `501e23c58957a49afb587df28f4ce3419c09908a`.
No live upgrade is required for A3 acceptance.
