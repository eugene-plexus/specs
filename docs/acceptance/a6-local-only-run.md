# A6 local-only routing acceptance — 2026-09-21

Implemented against specs `e8b4b1a12797b34d26eb86aecbd2e5b48f0273b7`.
The [operator/design guide](../design/local-only-routing.md) records the trust
boundary, rollout requirement, custom-endpoint assertion and refusal behavior.

## Process acceptance

Run `python scripts/a6-local-only-acceptance.py` in an environment with the
five Python components installed. The runner creates a real control root,
enrolled agent, gateway and four real HTTP drivers with Ed25519 service auth,
plus a counting upstream model fixture. Every process/configuration/port is
isolated; all owned children are stopped in `finally`. No installed service,
model or external inference provider is touched.

Passed on Windows/Python 3.14 and WSL/Linux/Python 3.12:

- A local-only client key lists only local models and eligible aliases.
- Both chat APIs, streaming and embeddings serve through local drivers.
- External and unknown destinations receive zero protected application
  requests, including valid attached-image requests and primary-model outage.
- An unrestricted key can use the configured external fallback in the same
  installation. The single observed external application request is this
  deliberate positive control.
- Replacing a driver's active endpoint/classification on the same address
  cannot exploit the gateway's old routing snapshot. Directly sending the
  stale protected request to the driver is also refused before upstream use.
- Refusal diagnostics contain no application content.

Windows evidence: `ep-a6-acceptance-jla3i2ql`; Linux:
`ep-a6-acceptance-y_wj_jvg`. These temporary trees retain process logs and
`summary.json`, not committed operator secrets. The fixture counts marked
application input separately from the driver's existing one-character
embedding capability probe; the latter carries no application data.

## Regression coverage

The initial driver policy checks failed in ten cases against the old request
handling. After implementation, all 24 driver locality tests pass, including
construction-time classification for managed/custom/cloud/CLI engines and
the stale-info replacement race. Gateway locality tests cover both chat APIs,
streaming, embeddings, aliases, unknown/older/unreachable drivers, model scope,
stale metadata and a simulated wake. Only local wake candidates are offered,
and selection is rechecked after start. This is not physical GPU acceptance.

Agent and control tests preserve local-only limits across registry restart and
snapshot recovery, and invalidate old leases when the policy changes. The UI
creates a local-only key through the normal form and retains existing edit
behavior. New keys remain unrestricted by locality unless the operator selects
the restriction; prior model/rate/concurrency defaults are unchanged.

Windows suites: agent 960 passed / 4 platform skips; control 185 passed;
gateway 512 passed, then the added local-wake test passed with all 12 locality
tests; driver 492 passed / 3 live-provider skips; UI 763 passed. Python lint
and type checks, UI lint/type checks and production export passed. The same
process acceptance runs in Windows/Linux CI using the installer pins.

## Limits

Custom endpoint locality is an operator trust assertion. Eugene does not
sandbox a malicious backend or guarantee exactly-once tool execution. The
classification belongs to the active engine until restart. Older drivers
cannot serve a local-only key. All components must be updated before enabling
the policy. Public `v0.1.0-alpha.1` assets and live installations are unchanged.
Failover retry classification, total request deadlines, cooldowns and expanded
attempt accounting are the separate A6b slice.

## Published component pins

- ui: `0ce61cf91732101e7cff4b1b49585952dfe542df`
- gateway: `be733789db9f9252f7a1cc9c8e2f2872d98e2a82`
- agent: `a9f62198d614e8f68068e264134979ca2c5e66fb`
- control: `8b374c55243b8772172cea827779b0bd9b24c2f4`
- library: `becd5f6cda8479f52c5f947108af5ab24f00ea2f`
- inference-driver: `b7db417f60aa9bfa44a270e22c277ebd98639082`
- ui-dist: `7feb3de7dc5370a9ef23915d146620e600e6e3fe`

Packaged UI: 184 export files match the wheel byte-for-byte.
