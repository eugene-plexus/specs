# R8 — model profile generation defaults

Executed 2026-09-20 on Windows and Ubuntu under WSL. Contract `88a6f63`;
gateway `aa24529`, Library `db66715`, UI source `d384ba2`, UI dist `11c0a72`.
Both installers pin these published versions. Source CI passed: gateway
`35533501920`, Library `35533504000`, UI `35533508847`.

## Reproduction and implementation

The gateway previously used only its install-wide defaults. The roadmap also
mistook author sampling metadata for persisted profile fields: creating a
profile with `maxTokens`, `temperature`, and `topP` against the old Library
stored none of them. The contract and persistence now carry all three optional
fields, with maximum output tokens at least one, temperature 0–2, and top-p 0–1.
Existing profiles remain valid; blank editor fields clear an override.

The model's default profile supplies omitted generation settings. Caller
values, including zero temperature/top-p/seed, always win; remaining omissions
use gateway configuration. There is no new global top-p default. Profile launch
settings still copy into a runtime when launched; generation settings are read
for subsequent requests without restarting it.

For each backend attempt, resolve the selected node/driver's runtime and
reverse-lookup its Library `modelPath`, then read that model's profiles. This
preserves replica identity, aliases, node-local copies, and cross-model fallback.
Cloud backends without a managed runtime keep gateway defaults. The gateway
uses its service token through its agent's Library proxy. Defaults are cached
for 30 seconds, with 300 additional seconds of stale reuse on failure, a
five-second failure retry delay, and a 256-entry limit. Both lifetimes are
configurable through the existing UI. Successful empty responses clear defaults.
See the [design](../design/model-generation-defaults.md).

## Live process acceptance

`scripts/r8-profile-acceptance.py` runs actual gateway and Library processes
with disposable state, ephemeral Ed25519 credentials, dynamic loopback ports,
and a fixture HTTP agent proxy/driver. Profiles are created, edited and deleted
through the real Library API; captured driver requests expose the result.
Windows and Linux both passed:

1. OpenAI and Anthropic batch and streaming requests use saved profile defaults.
2. Explicit caller values win, including zeroes, and fully specified requests
   bypass Library lookup. Anthropic's required token limit stays the caller's.
3. Edits appear after refresh; outages reuse defaults only within the grace
   period and then fall back to gateway configuration.
4. Recovery resumes profile reads; changing the default selects it, deleting
   it promotes the remaining profile, and deleting the final profile restores
   gateway defaults.

No live NAS or Windows install, model files, runtime state, keyring, service,
firewall, or saved operator profile was changed. The driver is a fixture, so
these checks verify routing and parameters, not GPU output quality.

## Regression and packaging checks

| Consumer | Windows passed / skipped | Linux passed / skipped |
| --- | --- | --- |
| Gateway | 399 / 0 | 399 / 0 |
| Library | 487 / 24 | 490 / 21 |

Platform-specific and opt-in external model/hub checks account for the skips.
Gateway and Library lint and mypy passed; codegen used the published contract.
UI typecheck, lint and **731 tests** passed, including profile edit/save/clear
and range-validation tests. Source CI also checks formatting and codegen
freshness. An isolated production export was packaged into the dist branch
and a wheel; **all 184 static assets match byte-for-byte**, and the bundles
contain the generation-default controls.

Gateway checks cover alias/replica isolation, fallback model changes, no-profile
and cloud behavior, cache limits, shared concurrent reads, and cancellation
during profile lookup. In-flight reservations remain held during lookup and
are released if the request is cancelled. Library checks save, replace, reload,
clear and reject invalid values.

`scripts/r8-profile-checks.py` mutates disposable source copies only. Baselines
must pass, each mutation must produce a test failure, saved bytes are restored,
and final baselines must pass. **10/10 caught on Windows and Linux**: disconnected
resolver wiring, lost caller zero, wrong default selection, local-copy path
lookup, bypassed fresh cache, unlimited stale reuse, absent retry delay, retained
deleted settings, unbounded cache, and lost create-time persistence.

Specs CI runs live acceptance and the mutation gate on Windows and Linux
against the installer pins. Reproduce with the consumers' dev dependencies
installed in one disposable Python environment:

```text
python scripts/r8-profile-acceptance.py
python scripts/r8-profile-checks.py
```

R8 is complete. R5/R6 and the unchanged release gate remain; physical checks
previously owed for other slices are not claimed by this acceptance.
