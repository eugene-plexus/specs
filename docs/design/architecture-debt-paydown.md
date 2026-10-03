# Architecture debt paydown

Implemented on 2026-10-03 across agent, control, gateway,
inference-driver, Library, tool-driver, UI, Workbench and specs. This change
preserves independently installable services and their HTTP boundaries.

## Storage owns its version

Library's version 2 scan/download cache no longer contains profiles. A separate
`*.profiles.json` version 1 document owns profile records and enough model
identity to recover them when the cache is missing. The first migration preserves
the legacy bytes in `*.preserved` before writing the separate document. Cache
rescans never rewrite profiles. Invalid profiles and unknown versions make writes
unavailable, report degraded health, and retain the original files. A corrupt
legacy combined document is not treated as an empty collection.

Workbench reads and checks the SQLite schema version before changing anything.
Each migration and its version update now share one transaction. The version 2
migration recognizes the old partially applied column additions; a failed
migration rolls back, and a newer database is refused without modification.

Back up the entire stopped installation, including the new profile sidecar and
run journal. Installing an older executable does not reverse a storage migration;
restore matching software and state using the existing recovery procedure.

## A run is a server resource

`openapi/run-operations.json` describes Library's `/v1/run-operations` resource.
The browser submits a model or download intent with an idempotency ID and target
node, observes progress, and sends install decisions or cancellation. It no
longer performs the download/install/profile/launch sequence.

Library persists the intent before any download starts. The target agent claims
a 120-second lease and advances one stage at a time. Decisions, progress and
profile snapshots survive restarts. Download IDs and runtime names are stable;
profile selection and runtime creation reconcile an existing side effect after
a lost response. A runtime with different flags, environment or model at the
same name is a conflict, not an object to overwrite. Runtime launch still uses
the same local admission and measurement guard as an HTTP launch.

Only operator sessions may submit, answer, cancel or dismiss. An authenticated
agent may claim its own node's existing work, checkpoint it, and select/create
that operation's default profile. It cannot edit existing profiles or submit
arbitrary work. No session or service bearer is stored in the journal. A stale
lease cannot checkpoint after cancellation or a new claim.

Cancellation prevents subsequent stages. An install or runtime already started
is not rolled back or stopped implicitly, since other work may use it. An
operation's own download is cancelled; completed model files remain. Explicit
download pauses are durable and take precedence over automatic restart recovery.
Legacy `runWhenReady` intent clears only after its replacement operation exists.

Admission to this queue is bounded at 128 active operations. Lists are bounded
and prioritize active work; individual receipts remain retrievable. Completed
IDs and aliases remain as durable idempotency receipts. Lease expiry permits
recovery; runtime loading and post-download cataloguing have finite deadlines.

## One gateway attempt implementation

`gateway/execution.py` owns candidate iteration, circuit admission, attempt
metrics, cleanup and the retry boundary for whole responses and streams. Each
modality supplies its call and, where needed, a stream policy. Output commitment
prevents cascading into a second provider. Cancellation and incomplete streams
close the attempt exactly once. The selected driver is published before the
first output so streaming headers and envelopes identify the correct attempt.

## Provider wire dialects are explicit

The OpenAI-compatible driver uses immutable descriptors in
`engines/dialects.py`. Named providers select their descriptor directly. A custom
compatible backend exposes `wireDialect`, allowing OpenAI/OpenRouter/Ollama/LM
Studio behavior behind a proxy. `auto` retains compatibility using parsed host
identity; URL paths, user information and deceptive hostnames cannot select
OpenAI behavior. A stale custom setting cannot override a named provider.

## Shared code has a canonical source

`platform/1.0.0` owns the identical token, admission, GPU probe, HTTP, body-limit,
security, private-file and build helpers selected in `platform/manifest.json`.
Distinct implementations, such as the agent's HTTP pool, remain separate.
`scripts/vendor-platform.py` generates consumer copies and `VENDORED.json` with
normalized-content SHA-256 digests. Every consumer checks its copies offline in
CI; the central generator's `--check` verifies the full workspace against the
canonical snapshot. `platform-checks.py` deliberately damages a copy and checks
that integrity verification catches it and regeneration restores it.

The additive run protocol is also vendored to its three consumers. Library
compares its exposed schema to the snapshot. UI generates the new protocol types
offline with `npm run codegen:runs`; aggregate `SPECS_REF` generation remains
available for existing contracts. To change shared source, edit the canonical
source, advance the snapshot version for a published change, regenerate, and
review the consumer diffs together.

## Release inputs are reproducible

`release/manifest.json` is the source of component commits and interpreter/tool
bounds. `release/requirements.lock` pins runtime and wheel-build dependencies
with hashes and cross-platform markers. Both installers embed the same lock,
install its wheels with hash verification, build Eugene packages without
resolving additional dependencies, and check the resulting environment. The
container already uses the shell installer and therefore receives the same lock.

Run `python scripts/release-inputs.py` after pin edits. Dependency updates are
explicit: `python scripts/release-inputs.py --resolve --uv <path-to-uv>` resolves
the sibling projects and updates the lock. CI checks generated installers,
constraints and manifest digests. Release packaging reads committed Git blobs
and verifies their agreement before creating artifacts.

Interpreter patch downloads, uv bootstrap binaries, OS image/packages, engines,
and models are outside this Python lock; the artifact manifest states this
scope. Frontend dependencies continue to use the existing npm lockfiles.

The reusable specs workflow accepts candidate refs for agent, control, gateway,
inference-driver, Library, tool-driver, UI and Workbench. Each consumer PR passes
its proposed SHA; runtime acceptance retains the other release pins. Run recovery
checks activate when both relevant consumers provide the additive protocol,
allowing the initial staged rollout to pass legacy compatibility checks.

## Admission stays responsive during durable writes

Control uses one bounded admission worker. The complete decision plus durable
commit runs under the state-machine lock on that worker, including the shared
concurrency allowance. The event loop serves health and committed-state reads
while disk I/O waits. Overload returns an unavailable response rather than growing
an unbounded queue. Disconnecting a caller does not abandon a queued write.
Administrative mutations retain their existing state-machine serialization.

## Validation and rollout

Regression coverage includes failed and partial migrations, unreadable/future
storage, cross-node authorization, duplicate submissions and claims, stale
leases, cancelled requests, replay after profile/runtime persistence, runtime
name collisions, MLX compatibility, and expert-offload context sizing. Existing
full component suites exercise gateway modality behavior and provider dialects.

`scripts/run-operations-checks.py` connects the real agent worker to Library's
HTTP resource in isolated ASGI applications. It injects lost responses after
profile and runtime side effects, reopens storage, creates a fresh worker, and
requires exactly one profile, install, declaration and start. No real GPU or
model download is needed for that recovery test.

Local validation completed on Windows, with the POSIX installer harness run in
Ubuntu/WSL:

| Component        | Full suite passed | Skipped |
| ---------------- | ----------------: | ------: |
| Agent            |             1,701 |      17 |
| Control          |               332 |       2 |
| Gateway          |             1,182 |       1 |
| Inference driver |               972 |       5 |
| Library          |               623 |      25 |
| UI               |             1,604 |       0 |
| Workbench        |                64 |       0 |

After the final recovery refinements, focused Agent (8), Control worker (1),
Library/download (80), and UI observer (10) tests also passed. Python lint, formatting and type checks,
UI lint/type checks and production build passed. The six-consumer signing
conformance check, run-protocol schema/recovery checks, vendoring drift checks,
release generation/artifact checks, and installer isolation checks passed.
The POSIX architecture harness passed 141 simulated-platform checks. Its first
attempt in Git Bash stopped on an unsupported Windows group lookup; the
Ubuntu/WSL run passed without changes to the installer.
The Windows installer preflight and recovery suite passed all 78 tests.

A fresh Python 3.12 environment installed the hashed dependency lock and all
eight local Python packages without dependency resolution during package builds;
the resulting environment passed dependency consistency checks. OpenAPI
validation and lint passed for the amended Library contract. Skips cover
hardware/live services and platform capabilities unavailable in these test
environments. Hosted CI, real engine/model downloads and live installation or
deployment have not been performed.

Publish specs/workflow support first, then Library, then agents, and finally UI.
Library continues serving the older endpoints during this sequence. Once those
commits are reviewable, update the canonical release pins, regenerate installers,
and run acceptance against that exact candidate set before publishing a release.
The source pins still describe the existing published release. Publishing these
architecture changes does not promote their component commits into a release;
update release pins only after acceptance passes for the chosen candidate set.
