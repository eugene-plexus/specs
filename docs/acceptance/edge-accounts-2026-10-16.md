# Edge: account administration, enforcement and simpler setup

Troy authorized publishing the held batch to Edge on 2026-10-16 to review account
management before U4 external SSO. This is an Edge update; v0.2.3 remains the
stable release. Publication does not update Troy's running installation.

## Scope

- U2: named directory administration, independent account/group-management
  grants, scoped membership assignment, and separate owner controls.
- U3: current person/app enforcement for Workbench model requests, owner identity
  for background work, bounded revocation, access history and gateway attribution.
- Discover download-to-run guidance, durable launch continuation and Workbench
  handoff; Library completion waits for the runnable model ID.
- Contextual settings customization and search, clearer model choices, and
  sliders paired with precise numeric inputs for suitable settings.

Google, Microsoft and generic OIDC remain U4. Per-group model-role profiles and
chat-model sorting are not included. No physical GPU compatibility claim changed.

Feature acceptance: [U2](u2-administration-2026-10-16.md),
[U3](u3-person-access-2026-10-16.md), and the two UX implementation records in
[the shared-accounts design](../design/shared-accounts-and-sso.md).

## Candidate

| Component | Commit |
| --- | --- |
| Agent | `8402ef44bd8e19e43f43ce635afe6ea7915f00d9` |
| Control | `b8d5eb0517bda7afdb44134ceb119b1eed7fbd59` |
| Gateway | `470ed6487ad46953d3167c6313af28e0952518bd` |
| Library | `963a0cc057cb773e1115c56bb0591fd3d0bd933f` |
| Inference driver | `c2e64f47070d37db1cb97ef755fc9b85730ef345` |
| Tool driver | `bb21b5ccf5d680cadeb36b0532508fad08facd53` |
| UI distribution | `32e444783381b9ad1423f6d19e24e0f1dd0256e5` |
| Workbench distribution, in the agent catalogue | `61b87b2a2768e9c3b9b0125422b29968a8c7d1ca` |

The UI distribution contains 276 production files built from
`e4ea32b78cde41bcabb0b2a93a862d23dff0e797`, with the Edge installer reference
`main`. Workbench contains 183 production files built from
`d1dd7b3235dfb0a048c5e9839e6b087cf04134b2`. Every committed static file was
compared byte for byte with its production build after commit hooks. An
intermediate UI distribution omitted its assets during packaging; a forward
correction restored and verified them before any Edge manifest selected it.

The published HTTP contracts are pinned at
`61b1c2d1c9f43c8d5600efaf4eab3d57bed2ab5c`; each changed consumer regenerated
with its own tools. The shared platform token/admission sources were synchronized
and all consumer integrity manifests regenerated. Library's run-operation
snapshot was refreshed for description-only changes; paths and schema structure
were checked to be unchanged. Both installer manifests agree, and the existing
hashed Python dependency lock is unchanged.

## Validation and rollout

Python lint/format/types, frontend lint/format/production builds, staged secret
scans and source whitespace checks passed. Focused checks covered the refreshed
platform, token gates, admission, Library handoff and run-protocol agreement.
The wider UI suite exposed a missing administration-route classification and an
assertion for the old launch wording; the route is explicitly outside owner
navigation, and the test now checks the actual continuation link.

Upgrade the active and standby roots, then enrolled nodes/gateways and Workbench.
Workbench is a separate app update even when the control-plane container is
updated. Mixed old/new person-proof participants refuse model requests until
updated. Existing private accounts, chats, documents and metrics retain the
migration and revocation bounds recorded in U3.

The container workflow must build and test the exact pinned image, including
Compose, NAS Workbench installation and recovery, before uploading `edge`.
Publication results and registry verification are recorded below once complete.
