# Strata experimental integration — 2026-10-04

Edge implementation. No live-install update or GPU model run.

Upstream source is `Niko1221/Strata` v0.1.39,
`6f32ec070f23ced9f50e704d854d775da52591ab`. Windows native asset SHA-256:
`a862bcfa2330cd1c23f9b5d6e49f4027da8f8313842bd62e858ec6cd4533813a`.
Source ZIP SHA-256:
`d91a853d731c9fc3b60962523eac089f5132dcf6364977e357307915f31424b6`.

## Measured on Windows

- Installed the real pinned source, native release and isolated Python/CUDA
  dependencies under a fresh `eugene-strata-install-check-*` temporary directory.
  Source/native downloads totaled 139,088,009 bytes; the Python wheel downloads
  are additional. Recipe completed in about 17 seconds on this machine.
- Invoked the native executable's `--help`. This caught the CUDA 13 wheel's
  nested `nvidia/cu13/bin/x86_64` DLL layout: using `*/bin` failed with Windows
  `0xC0000135`. The adapter now resolves the actual DLL directories, and the
  native executable exits 0. The installer performs this check before promotion.
- Ran Strata's actual Python server with its upstream **mock engine**, using
  an ephemeral loopback port. Eugene's adapter observed readiness and the
  resolved 32,768-token context. The driver received separate reasoning and text
  in both non-streaming and incremental streaming responses (28 stream frames).
  The public model identity and token usage survived translation. Harness:
  `scripts/strata-protocol-check.py <isolated-build>/serve/server.py`.
- Removed the real installation through the managed-store removal code, repeated
  removal, and checked an operator-owned model sentinel remained unchanged.
  Removal took about 0.33 seconds. The live Eugene installation was not touched.

## Automated coverage

Agent tests cover prepared paths and immutable originals, private aliases,
unsupported executable hooks/flags, missing assets, readiness with `loaded:false`,
platform/version gates, unknown memory fit, cancellation (including cancellation
before the worker starts), receipt ownership, partial removal, repeated removal,
authentication and refusal while a runtime is running.
Admission also checks mapped config paths and their prepared assets before a
switch; it writes no launch configuration during that dry run.

Driver tests cover capability limits, explicit unsupported settings, context,
model identity and the distinction between Strata's compatibility endpoints and
llama.cpp slot/progress semantics. Gateway tests cover draining an active answer,
serialized switches, an unconfirmed stop, failed target start and recovery text.
After a confirmed stop, a failed agent refresh cannot restore a stale ready
status for the old model.
UI tests exercise saving a prepared model and switching on the selected node,
alongside the existing Inference page suite. Python lint/type checks and the
production UI build were also run.

The inference-driver full suite passed (976 tests, 5 skipped). Broad agent and
gateway runs found direct clock calls in the new code that violated the existing
clock rule; those were fixed and the affected checks rerun successfully. Final
focused agent runs passed 122 lifecycle/acquisition/config tests and 83
admission/lifecycle tests; gateway switch/lifecycle and clock checks passed.
The Inference page and new component tests passed (42 tests), as did type
checking, lint, formatting, vendored-contract integrity and run-protocol conformance.

## Edge delivery

API contracts are committed as
`9ea5359008c828c0bbd75e831a4003c6f12c121d`. Agent, driver, gateway, control,
Library and UI consume that snapshot; generated files were regenerated from
the local specs checkout. The contracts were pushed before the consumers so
remote code generation can resolve the pin. The production UI export is packaged
in its `dist` branch with installer-ref `main`.

Edge's shared manifest and both installers pin:

| Component | Commit |
| --- | --- |
| Agent | `8f2d75ac05ca7724bca685143ef6f440036dffb4` |
| Inference driver | `02beb480eb19af45d71435947291f1387d53060e` |
| Gateway | `2c92e568c96f71442605df5f79f07ff4304d808c` |
| Control | `569eed6fa2584654fe4018873070503df0831c10` |
| Library | `98daf3038090ff60b26c5a1cf09b1b7937ff8543` |
| UI source | `58d13798acebf6a89f6d18f65b58e9d4ebb25ac5` |
| UI distribution | `23fad73ebf45c994d09b0073f8f3b5bc42c5ad5f` |

The distribution archive was checked for all 253 exported files, the Strata
controls, source provenance and its own substituted commit stamp. Edge becomes
eligible for in-app updates only after every workflow on its installer commit
passes. The container workflow verifies the built image before publishing
`ghcr.io/eugene-plexus/control-plane:edge`. Published v0.1.0 assets remain unchanged.

## Still required before claiming real-model validation

A prepared model on supported NVIDIA hardware: initial load, MTP generation,
stream cancellation, complete server/native-child shutdown, switching between
two prepared models, a failed target load, and stop/uninstall/reinstall through
the UI. Confirm measured RAM/VRAM release and client behavior under a real long
answer. No throughput or full client-compatibility claim follows from the mock
run. Strata remains Experimental after this hardware validation.
