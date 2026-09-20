# R7 steps 2–4 — asymmetric signing and live rotation

Executed 2026-09-20 on Windows and Ubuntu under WSL. Contract `4b5d80a`;
agent `c5ad280`, control `5cd8733`, gateway `e232fce`, library `337c987`,
inference-driver `4dc12fe`. Both installers pin those commits and UI dist
`bd0b456`, built from UI source `bec0a4f`.

## Reproduction and implementation

Before production changes, the new signing/bootstrap checks produced 35
failures and five passes across the five consumers. A further downgrade check
returned 200 instead of the required 409 before its guard was implemented.

New signing keys are Ed25519 private PKCS8 PEM. Agent and control mint EdDSA
tokens; gateway, library and driver receive only public SubjectPublicKeyInfo
PEM through `AUTH_VERIFY_KEY`. Legacy `AUTH_SIGNING_KEY` accepts only 32-byte
HMAC keys until explicit rotation. Each verifier chooses one algorithm from
trusted key material. Private PEM, malformed public keys and simultaneous
bootstrap variables fail closed. There is no JWT-header-selected algorithm or
signature-error fallback. A migrated node rejects signed HS256 downgrades.

The enrollment/rekey field remains base64 `signingKey`; the canonical signed
message is unchanged. Stored root signing material remains sealed. The master
encryption key and node/root identity keys retain their existing roles.
Five independent security implementations preserve the schemas-only sharing
boundary. See the [migration contract](../design/r7-asymmetric-signing.md).

## Live acceptance

`scripts/r7-rotation-acceptance.py` seeds a legacy root in disposable state,
then starts actual control, agent, gateway, library and driver processes on
loopback ports 8179–8183. It refuses occupied ports and uses no real model,
external backend, keyring or installed configuration. It passed on both hosts:

1. Legacy enrollment/login and all three children work under HS256.
2. The control rotation endpoint migrates the enrolled agent and children to
   Ed25519. The existing tracker reports completion. No node is re-enrolled.
3. Node identity, name, enrollment timestamp and root identity are unchanged.
   The driver retains its encrypted API-key envelope and decrypts it with the
   same master key.
4. Old tokens fail on all five processes. A forged HS256 session made with the
   raw public key fails on all five. Public-only material cannot sign EdDSA.
5. After stopping and restarting the root, agent and children, unlock/login
   preserves the migrated key and enrollment and public-key verification works.

The operator's running install, ports 8079–8083, tasks and configs were not
changed. Existing installs need all components/standbys upgraded before an
explicit rotation. Rotation invalidates old sessions and client keys; login
again and replace client keys. Offline nodes remain pending until retried.

## Regression and packaging checks

| Consumer | Windows passed / skipped | Linux passed / skipped |
| --- | --- | --- |
| Agent | 917 / 4 | 904 / 17 |
| Control | 169 / 0 | 169 / 0 |
| Gateway | 380 / 0 | 380 / 0 |
| Library | 480 / 24 | 483 / 21 |
| Inference-driver | 426 / 3 | 426 / 3 |

Skips cover platform capabilities, optional packaged UI on Linux, and opt-in
live external model/CLI/API tests. Ruff lint/format and mypy pass for all five.
All six consumers were regenerated against `4b5d80a`. UI regeneration also
picked up stale topP/seed/finish-reason types: type-check, lint and all 729 UI
tests pass. The UI static export was rebuilt in an isolated checkout; all
184 assets match the wheel byte-for-byte. The live editable UI tree was not
used for the build.

`scripts/r7-signing-checks.py` copies source/tests to temporary trees, requires
baseline success, deliberately breaks 23 guards one at a time, requires the
targeted test to fail with an assertion, restores saved bytes, and reruns the
baseline. **23/23 caught on Windows and Linux.** Mutations cover algorithm
selection, legacy compatibility, public bootstrap/application wiring, rejection
of private material in the legacy variable, new-key generation, child-key
delivery and downgrade fencing.

Specs CI runs this gate and the live rotation on Windows and Linux against
the exact installer-pinned commits. The earlier R7 launch-boundary gate remains
enabled. To reproduce in a disposable environment with all five consumers'
`[dev]` dependencies installed:

```text
python scripts/r7-signing-checks.py
python scripts/r7-rotation-acceptance.py
```

This enforces the assigned-credential boundary, not an OS sandbox. Trusted
agents still hold minting authority by design; a compromised process running
as the same OS user is outside this slice's isolation guarantee.
