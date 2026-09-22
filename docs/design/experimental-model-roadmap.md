# Experimental model roadmap: MLX and typed decisions

**Status: B1 and B2 built 2026-09-22; the slices' pending physical and credentialed checks are listed in their records.** Troy requested these two slices
after the adoption roadmap and Dependabot maintenance. A1-A8 and A6b retain
their recorded completion and outstanding physical checks. No release has been
published from this work; alpha.2 stands.

**B1 is integrated on main and packaged in the development installers**
(specs `7da4944`, driver `2ce5412`, agent `5787dbb`, gateway `4464bbb`,
library `ec9ab0f`, control `6a21348`, ui `4f31556` / dist `92421cf`; both
installers re-pinned). The blocker closed as the branch document recommended —
`upstreamModelId` on the driver, routed/authorized/reported on the public
`modelId` — and the two-node identity acceptance ran green with a sabotage
pass: [`docs/acceptance/mlx-identity-run.md`](../acceptance/mlx-identity-run.md).
Design and the pending physical Apple silicon checklist:
[`docs/design/mlx-engine.md`](mlx-engine.md). **The physical Mac results are
still owed and separately recorded** — the feature stays experimental and the
support matrix says exactly what that means. B2 did not depend on them.

**B2 is built and live-verified on WSL CPU** (specs `1526ff2`+`5641822`,
driver `847a282`..`1525f45`, gateway `024004b`+`5b0db63`, agent `3453198`+
`5ccfe2e`, library `40393b6`, control `6dbb4b9`, ui `bda9605`+`4b2e281` /
dist `633abbf`): `POST /v1/systemone` in the pinned TypeSafe shape as the
fifth client-key door, the `systemone_http` driver protocol with hosted
(`typesafe`) and BYO (`systemone_custom`) providers, `EngineKind.kev`
supervising the pinned `jaredpalmer/kev-0.8b` for real, the library's
`head.pt` checkpoint recognition, and the playground's decision panel.
Design and upstream pin ledger:
[`docs/design/decision-models.md`](decision-models.md); evidence:
[`docs/acceptance/decision-run.md`](../acceptance/decision-run.md),
whose product finding — a door missing from the gateway's client
admission path set has NO client admission — is fixed and pinned by
test. User docs: the Kev and BYO-server recipe with its contract checks
in [`application-workflows.md`](../application-workflows.md#typed-decisions-with-kev-experimental-b2),
the boundaries in [`api-compatibility.md`](../api-compatibility.md#typed-decisions-b2),
and the Kev environment in the [recovery inventory](../recovery.md). **Owed:** hosted Jev needs one real credentialed request (Troy's;
fixture-covered and labeled unverified until then); the TypeSafe SDK
half is blocked on distribution (PyPI's `typesafe` is an unrelated
package, measured); Kev on CUDA/ROCm/Metal each need their own
evidence. No release is published from this work; alpha.2 stands and
`v0.1.0-alpha.3` remains the target once release authorization exists.

## Outcome and release approach

A tester can install a released Eugene build, choose an appropriate runtime,
and connect an application without checking out feature branches. An Apple
Silicon user can try MLX; an application author can run typed decisions locally
or explicitly select a hosted provider through Eugene's existing controls.

Target `v0.1.0-alpha.3` for the next publication. Each slice must produce tested
component pins, packaged UI, installation instructions, and a reproducible
tester example. Publish completed scope without waiting for every hardware
combination or every community project. Release authorization is separate;
retain alpha.2's immutable tag, assets and image. Do not describe experimental
Mac support as physically verified before receiving that evidence.

| Slice | Deliverable | Completion boundary |
| --- | --- | --- |
| B1 | MLX integrated on main and installable as an experimental Apple Silicon engine | Routing/lifecycle regressions pass; tester installation is packaged; physical Mac results are separately recorded |
| B2 | Typed decision API, a supervised local Kev runtime, and an optional hosted Jev adapter | Real local inference through Eugene and the documented client passes; hosted claims require a real provider check |

## B1 — MLX available to alpha testers

**User task:** On an Apple Silicon Mac, configure an isolated MLX environment,
select a compatible model, launch it through Eugene, and use it from Playground
or an existing supported application. Start/stop/restart and errors are visible
in the same console as the other engines.

### Starting point and blocker

The retained `feat/mlx-engine` branches contain specs `60cc15e` and agent
`0a4da70`: an adapter, configuration and fixture tests. They predate substantial
main-branch changes. Port the useful implementation onto current contracts;
do not replace current generated files with the branch's old versions.

The branch's [design record](https://github.com/eugene-plexus/specs/blob/feat/mlx-engine/docs/design/mlx-engine-unverified.md)
identifies the unresolved model-name problem. A public Eugene alias must be
independent of the backend's model identifier. Two MLX runtimes must never become
replicas merely because both accept `default_model`.

### Work

1. Add an optional upstream model identifier to driver configuration and the
   relevant contracts. Default it to the existing public model ID for backward
   compatibility. Route and authorize against the public ID; translate only at
   the driver/backend boundary. Normalize response identity, including streams,
   and preserve useful upstream identity in diagnostics without leaking local
   paths into public model lists. Supervised runtimes supply the mapping.
2. Reconcile the MLX adapter with current engine discovery, HTTP client reuse,
   process supervision, startup diagnostics, capability reporting and recovery.
   Pin a supported released mlx-lm version after verifying its actual flags and
   behavior. Current upstream main changed health handling since the old adapter
   was written; it is evidence to investigate, not a substitute for checking the
   selected release. A listening HTTP port alone must not enable Send. Avoid
   generating a token on every steady-state poll if residency can be established
   reliably another way. Bound probes and expose prolonged loading/failure.
3. Offer a versioned installation recipe using a separate native ARM Python
   environment and an explicit executable path. Show the experimental option
   only on appropriate hardware; explain missing dependencies. It must survive
   an agent restart and work through the documented launchd environment. Do not
   silently install MLX into Eugene's environment or rely on an interactive shell.
4. Make Library/profile selection recognize compatible model assets. Safetensors
   alone does not prove compatibility. Start with a pinned, small, known-compatible
   MLX model and retain its provenance/license. Check unified-memory admission;
   show unknown estimates honestly and do not treat all host RAM as free VRAM.
   Reject unsupported benchmark, vision or embedding actions with a useful reason.
5. Update all affected generated consumers, UI packaging, development pins and
   recovery guidance. Existing configurations and llama.cpp/vLLM behavior remain
   covered. Include the MLX environment/model dependencies in the recovery inventory
   and explain what requires separate reconstruction.

**Likely repositories:** specs, agent, inference-driver, gateway, library and UI;
control regeneration where shared contracts require it. Website installation
and support wording change with the eventual release.

### Acceptance and evidence

- Two independent backend fixtures both accept the same upstream sentinel but
  return distinguishable output. Requests to two public aliases reach the right
  runtime through real gateway/driver processes, in streaming and non-streaming
  modes. Include two-node routing, replica identity, scoped model access, restart
  and a request that attempts to select the other backend's model directly.
- Existing configurations without the new mapping still work. Keys, local-only
  policy, cancellation and conservative failover retain their semantics.
- Exercise slow loading, failed loading, dead processes, malformed health replies,
  missing executables and bounded probes. Stop/restart must not leave owned engine
  children running; fixture results are explicitly labeled simulated.
- On a physical Apple Silicon Mac: fresh install, model acquisition, first reply,
  streaming and cancellation, stop and memory observations, restart, agent restart,
  documented login startup, and an application call from a second machine. Record
  hardware, macOS, Python architecture, engine/model revisions and logs. Include
  a Rosetta-started install when a tester can run it.
- Lack of Mac hardware leaves the last check pending and the feature experimental;
  it does not keep the integration inaccessible on a private branch. A known
  routing or shutdown defect is a blocker; missing hardware evidence is a stated
  alpha testing limitation. Record this distinction in the support matrix.

**Out of scope:** MLX training/conversion tooling, every model architecture,
speculative decoding tuning, guaranteed tool/vision support, and performance
claims borrowed from another engine.

## B2 — Host local decision models and connect hosted Jev

**User task:** Send a support-ticket record and typed questions to one Eugene
endpoint; receive structured decisions from a locally hosted model. Optionally
use hosted Jev under a separate configured alias and explicit cloud permission.
The calling application owns any subsequent action.

### Evidence and the support promise

Research checked 2026-09-22. Recheck and pin upstream versions at implementation;
the links describe current interfaces, not Eugene features already delivered.

| Source | Finding and consequence |
| --- | --- |
| [TypeSafe models](https://docs.typesafe.ai/models) | Jev is documented as a hosted service. No downloadable official weights/self-hosting distribution was identified in the reviewed official material. Promise access to hosted Jev, not local hosting of Jev itself. |
| [TypeSafe API](https://docs.typesafe.ai/api) | `POST /v1/systemone` accepts model, state and named questions. Noul represents a yes probability; Choice returns an option distribution; Score uses ordered criteria. This needs a decision protocol, not chat-message wrapping. |
| [Kev README](https://github.com/jaredpalmer/kev/blob/1c351992ba3df4a0a0f2ae03051b25466a2c7bcb/README.md) | Open checkpoints and a TypeSafe-compatible server make Kev the first concrete local target. Its custom loader and adapter/base-model dependencies require their own runtime; it is not an ordinary GGUF chat model. Start with the smallest published checkpoint. |
| [Open-Jev README](https://github.com/Zefan-Cai/Open-Jev/blob/ed45657bf726c3b77408942830e5578f99df904e/README.md) | Another implementation uses adapters plus a decision head and its own loader. Use it to check extension boundaries; support is not implied by a similar name or checkpoint extension. |
| [Vercel evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation) | `/v1/evaluate` uses a different dialect, including Boolean and different usage fields. TypeSafe compatibility alone must not be advertised as AI SDK evaluation compatibility. |

### Work

1. **Define a decision capability and endpoint.** Add the public TypeSafe-shaped
   `POST /v1/systemone` and a signed internal driver operation. Preserve structured
   state, question IDs, instructions, criteria and question independence; validate
   against the pinned protocol and refuse unsupported fields. Non-streaming is the
   initial scope. Model discovery identifies decision-only models, supported question
   kinds and limits; chat and embedding calls to these models fail clearly.
2. **Keep backend protocols in drivers.** Add a reusable System One HTTP adapter
   with explicit public/upstream names and provider capabilities. Configure local
   endpoints or TypeSafe's hosted endpoint using protected credentials. Do not
   pass client-supplied destinations or provider secrets through the public request.
   Hosted Jev is optional and cloud-classified; it is never a local fallback.
3. **Actually host one open model.** Add a Kev engine adapter to supervise its
   pinned server in an isolated environment: acquisition instructions, executable,
   checkpoint/base-model revisions, device selection, readiness, log capture,
   stop/restart and concurrency limits. Begin acceptance on isolated Linux/WSL with
   available hardware; Mac/ROCm claims need their own evidence. Bind the managed
   backend to loopback because Eugene supplies the authenticated front door.
   Connecting an already-running server is useful but does not complete hosting.
4. **Make assets reproducible and visible.** Library/profile metadata must retain
   the base weights, adapter/decision head, tokenizer and calibration artifacts the
   loader needs, along with versions and licenses. Expose total disk/memory needs
   or mark them unknown. Do not suggest a GGUF quant or ordinary chat runtime for
   these assets. Prove a second launch from downloaded, pinned local artifacts
   with outbound access disabled; loading dependencies and inference egress are
   separate policy concerns. Document external-environment recovery.
5. **Apply existing controls to the new operation.** Reuse key authentication,
   revocation, model scopes, shared request/concurrency admission, deadlines,
   cancellation, usage attribution and local-only checks at gateway and driver.
   Bound body size, question/option counts and response size before backend work.
   Disable hidden SDK retries; retain A6b's uncertain-outcome rules. A timeout
   after possible execution does not justify silently sending the same decision
   to a different model. Capacity must remain occupied while known local work
   continues after a client disconnect; do not over-admit a non-cancellable engine.
6. **Preserve decision meaning.** Validate answer keys/types, legal choices,
   distributions, finite numeric bounds and score ranges before returning success.
   Malformed output is a backend error, never an invented decision. Preserve
   provider probabilities and calibration provenance without claiming they are
   comparable across models. Do not manufacture confidence from generated prose
   or silently substitute a JSON-prompted chat model. Record provider/model revision,
   latency and reported usage; leave unavailable accounting unknown. Avoid logging
   raw state by default.
7. **Provide a usable first client.** Add a small decision test panel with a sample
   ticket, the three question types, result inspection and copyable request. Ship
   curl and a pinned TypeSafe Python SDK example using Eugene's base URL/key. Add
   a concise recipe for registering another System One-compatible server and the
   contract checks it must pass. Full compatibility with Vercel `/v1/evaluate`
   and AI SDK is a follow-up unless it can be delivered with a real pinned-client
   test; do not delay the local endpoint to reproduce another gateway's metadata.

**Likely repositories:** all six active consumers. Specs owns the decision
contract, agent owns Kev processes, library owns assets, driver owns protocols,
gateway owns policy/routing, control carries shared configuration as required,
and UI owns discovery/configuration/testing. B1's model-name mapping is reusable;
the local decision runtime does not require MLX.

### Acceptance and evidence

- A real pinned Kev checkpoint answers mixed Noul/Choice/Score questions through
  an authenticated gateway and driver, first with curl and then with the documented
  SDK. Test string/object/array state, structured instructions, repeated question
  IDs in separate requests, and two public aliases with distinguishable backends.
- Exercise the engine lifecycle and offline second launch. Record hardware,
  environment, all model artifacts and revisions, cold-start time, peak memory,
  single-request p50/p95 and a small bounded concurrent workload. Publish measured
  capacity only; fixtures alone do not close the local-hosting requirement.
- Compare direct and proxied calls on a frozen, small labeled example set. Check
  schema validity, routing fidelity and latency separately from model accuracy.
  Include missing evidence and reordered options; retain disagreements rather
  than claiming Jev-equivalent quality, calibration or speed.
- Negative HTTP tests cover missing/extra answers, wrong types, invalid numbers,
  unsupported options, oversized inputs, partial bodies, 429, backend death,
  disconnects and ambiguous timeouts. Verify bounded work and capacity release
  when backend work actually finishes.
- Repeat A3/A5/A6/A6b behaviors for decisions, including revocation, denied model
  aliases, multi-gateway limits and local-only denial with zero cloud requests.
  A decision response must not execute a tool or change routing policy itself.
- Hosted Jev requires one actual synthetic-data request with authorized provider
  credentials, pinned model and recorded result. Without credentials, complete
  fixture tests but label the hosted path unverified. This need not hold a proven
  local release; it must not be reported as verified Jev support.
- Run existing chat/Anthropic/embedding regressions, package the UI, update pins
  and publish installation/API/support documentation with the eventual alpha.

**Out of scope:** training a competing model, automatic tool execution or approval,
turning Eugene into an agent harness, semantic equivalence between providers,
every Jev-inspired project, and a new general benchmarking dashboard.

## Execution and completion rules

Use isolated ports, identities, environments and owned processes. Do not take over
the owner's live GPU, services or NAS for acceptance. Follow the existing signed
commit and specs-first consumer-generation workflow. Record implementation SHAs,
tests, actual client versions, hardware evidence and pending checks in a slice
acceptance record; update this pickup after each slice.

The current [support matrix](../support-matrix.md) continues to describe alpha.2
until a new release exists. The [adoption roadmap](adoption-roadmap.md) retains
moderated sessions, Windows boot/service and other physical obligations. These
two slices supersede its deferral of MLX and add only the named decision workflow.

MLX upstream source inspected for planning:
[server.py at c69d128](https://github.com/ml-explore/mlx-lm/blob/c69d1288440a0dc4e6401fc417098b07598dccd5/mlx_lm/server.py).
This is not a selected production dependency version.
