# R7 asymmetric token signing and migration

Agent and control mint tokens. Gateway, library and inference-driver verify
them. New installs and explicit key rotations use Ed25519 with JWT `alg: EdDSA`.
The existing audiences, lifetimes, revocation rules, and clock-skew policy stay
in force. Token-signing keys, master encryption keys, and node/root identity
keys have separate jobs and are not interchangeable.

## Key formats and bootstrap

`signingKey` in enrollment and signed re-key requests remains a base64 string.
Its decoded bytes are unencrypted PKCS8 Ed25519 private PEM. Trusted enrolled
agents persist that private material in their existing node record and use it
to mint sessions, client keys and child service tokens. The root seals it in its
existing `sealedSigningKey` envelope. Node and root identity keys still sign
the canonical three-field re-key message; its bytes and signature protocol do
not change.

The agent derives SubjectPublicKeyInfo Ed25519 public PEM and base64-encodes it
as `EUGENE_PLEXUS_<KIND>_AUTH_VERIFY_KEY` for verifier children. It also supplies
each child's service token. Library and driver retain the separate master key
for stored API credentials; gateway receives no master key. Backend subprocesses
receive neither signing nor verification material (R7 step 1).

Verifier bootstrap accepts public Ed25519 PEM only in `AUTH_VERIFY_KEY`.
Malformed, private, empty, wrong-key-type, and ambiguous dual-variable inputs
fail closed. The existing standalone mode is available only when neither key
input is supplied and no other credential requires authentication. Legacy
`AUTH_SIGNING_KEY` accepts only the old 32-byte HMAC format, never private PEM.
No new configurable user setting is needed; this is supervisor bootstrap wiring.

## Existing-install upgrade

1. Update all five components and standby roots before rotating. Upgraded
   components can read the existing 32-byte HS256 key, and an ordinary restart
   or login does not rotate it. Such installs retain the old symmetric trust
   boundary until the explicit rotation completes.
2. Use the existing control-root key-rotation operation. It creates an Ed25519
   key, seals it, advances the generation, and redistributes it with the existing
   identity-signed re-key message. The receiving node does not need a valid
   bearer minted under the new key to authenticate that message.
3. Each agent validates private key format, signature, generation and epoch;
   persists it in its existing enrollment; and restarts children with public
   verification material and newly minted service tokens. Its node identity,
   name, enrollment, root identity, and master encryption key are retained.
4. Log in again and replace client keys, as for any existing key rotation.
   Old tokens no longer verify on migrated components. Offline or old-version
   nodes remain visible as pending in the existing rotation tracker; bring them
   online/update them and use the existing retry/rotation flow. No re-enrollment
   is necessary. Do not report a partially distributed rotation as complete.

Algorithm selection is based on trusted key format, never the JWT header.
Each process accepts exactly one algorithm for its current key. There is no
mixed-algorithm verification allowlist and no fallback after a signature error.
After adopting Ed25519, a node rejects a signed re-key that offers HS256 even
at a newer generation/epoch. An older standby must be updated and catch up before
promotion; a newer epoch cannot undo the asymmetric boundary.

This change does not provide an OS sandbox. Trusted minter nodes still possess
private signing authority by the recorded architecture decision. The property
being enforced is that a verifier's assigned credentials cannot mint an
operator session.

Reference: [PyJWT EdDSA usage](https://pyjwt.readthedocs.io/en/stable/usage.html#encoding-decoding-tokens-with-eddsa-edd25519)
and [algorithm allowlist guidance](https://pyjwt.readthedocs.io/en/stable/api.html#jwt.decode).
