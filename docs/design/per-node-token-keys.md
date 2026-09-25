# Per-node token keys: a leaked key costs one machine

**Status: designed 2026-09-25. Troy delegated the calls ("use SOTA
security practices"); each decision below cites the practice it follows.
No migration: there is no release, and the only existing install is a
development one, which re-installs.**

Row 3 of the key-exposure work, after row 1 (other accounts on the
machine, `install-permissions-run.md`) and row 2 (the agent's own
account, `own-account-run.md`). The token flows it replaces were
measured first: `docs/private/row3-token-flows-2026-09-24.md`.

## 0. The problem and the goal

**Today one key is the install.** Enrollment sends every node the
install's private Ed25519 signing key in plaintext
(`control/routes/nodes.py:513`), and every node keeps it in `node.yaml`.
Tokens carry no issuer and no key id. So one node's key is enough to
mint:

- an **operator session**, accepted by every agent and by the control root;
- a **`service:control` token**, which declares runtimes (any binary on
  any node) and reads the replication snapshot (the salt and the
  passphrase verifier, for an offline guess);
- **every other audience**.

Two more exposures do not need the key at all:

- **Service tokens are replayable anywhere.** They name a kind, not a
  recipient, so a token one node receives works against every other.
  The control root hands every node a year-long `service:control` token
  on every poll.
- **Every node sees the operator's session.** The console forwards it
  to each node on every poll (`node:<name>` hops, every 30 s), so a
  compromised worker collects it without touching any key.

**The goal: whatever one non-console node holds, whether its key file or
the whole live process, it buys that machine and nothing more.** The
remaining limits are named in §5:

- the machine the operator is signing in on;
- the machine that runs the control root;
- the machine granted the gateway role.

## 1. Decisions

### D1. Every issuer has its own key, generated where it is used, never transmitted

- **The control root** has a *root token key*. This is today's
  `signing_key`, unchanged in how it is generated and sealed in the
  snapshot. It no longer leaves the root.
- **Every agent** generates a *node token key* the first time it starts
  and stores it in `node.yaml` (0600, plus the protections rows 1 and 2
  added).
  - Enrollment sends the **public** half.
  - Nothing ever sends a private token key over the wire.
- **The root identity key** (today's `controlPublicKey`, already pinned
  on every node at enrollment) signs trust bundles (D3). It signs no
  JWTs.
- **The node identity keys** (X25519 for sealing, Ed25519 for address
  announcements) keep their jobs.

*Practice:* **generate private keys in place**, never transport them
(SPIFFE/SPIRE; NIST SP 800-57 Part 1 §5.2 and §6.1). **Give each key
one purpose** (NIST SP 800-57 §5.2, key-usage separation). And
**domain-separate every signature** over a canonical message (D3).

### D2. One token profile, checked the same way everywhere

Every token is a JWS compact JWT.

**Header:** `{"alg": "EdDSA", "typ": <class>, "kid": <thumbprint>}`.

- `kid` is the RFC 7638 JWK thumbprint of the public key.
- `typ` is one of three classes:
  - `ep-session+jwt`: an operator session, or one obtained from a
    session by exchange (D7);
  - `ep-service+jwt`: one process calling another;
  - `ep-client+jwt`: a key an app outside the install holds.

**Claims:**

- `iss`: `control` or `node:<name>`;
- `sub`: `operator`, the calling component's kind, or a client key's name;
- `aud`: an array of recipients:
  - `node:<name>` covers every component on that machine;
  - `control` is the root;
  - `gateway` is the install's front door, for client keys only;
- `iat`, `exp`, `jti`;
- on an exchanged token: `act` (the node that asked) and `sid` (the
  session it came from).

**A verifier:**

1. Reads `kid`. A key the current trust bundle does not list is refused.
2. Takes the algorithm **from the key, never from the header**.
3. Checks the signature, `exp`/`iat` with the existing 300 s leeway,
   and `typ` against the classes this route accepts.
4. Checks that `iss` equals the key's issuer in the bundle and that
   `aud` names this recipient.
5. Checks that the issuer is **granted** this kind of token (D4).
6. Checks that the token lives no longer than its class allows:
   - a service token addressed to another machine: 1 hour;
   - a service token addressed to the issuer's own machine: 400 days;
   - a session: 14 days;
   - an exchanged token: 10 minutes;
   - a client key: 400 days.

*Practice:* RFC 8725 (JWT BCP):

- §3.1: the algorithm comes from the key, and verification is pinned to
  it;
- §3.9: audience restriction;
- §3.11: explicit typing, so a session cannot be passed off as a
  service token or the reverse;
- §3.12: key and issuer bound together.

RFC 9068's claim set, RFC 7515 `kid`, RFC 7638 thumbprints and RFC 8037
EdDSA. **Short lifetimes wherever a human does not have to paste the
token** (RFC 9700 §2.2 and §4.14; SPIFFE JWT-SVIDs).

### D3. Verifiers trust a signed, versioned trust bundle

The root publishes the set of keys and what each may issue.

```json
{
  "version": 812,
  "epoch": 3,
  "iat": 1790337600,
  "authority": "<root identity public key, base64>",
  "keys": [
    {"kid": "…", "issuer": "control", "publicKey": "…", "grants": ["authority"]},
    {"kid": "…", "issuer": "node:nas", "publicKey": "…", "grants": ["node", "gateway"]},
    {"kid": "…", "issuer": "node:gpu-box", "publicKey": "…", "grants": ["node"]}
  ],
  "revokedSessions": [{"jti": "…", "exp": 1790000000}]
}
```

**Signing.** It travels as a compact JWS with
`typ: ep-trust-bundle+jwt`, signed with the root identity key. Every
node already pins that key from enrollment. A JWS signs the payload's
exact bytes, so nothing is re-serialized before checking it. That is
the trap a canonical-JSON signature over a parsed body walked into at
M9.

- `version` is the replicated log's index, so it only ever grows, and
  it grows across a promotion too.
- A verifier refuses a bundle whose signature fails, whose `authority`
  is not the pinned key, or whose `version` is lower than the one it
  holds. Refusing a lower version is the rollback protection.
- An **equal** version replaces the held one. Two builds at one log
  index differ only in `iat` and in pruned, already-expired
  sign-outs, so replacing is harmless.
- The root keeps its last signed bundle on disk, so a sealed root still
  serves one.

**Distribution.**

- The root **pushes** the bundle to every node when it changes, as a
  signed body with no bearer (`POST /v1/node/trust-bundle`).
- Every agent also **pulls** it every 60 s and whenever the root
  becomes reachable again (`GET /v1/trust/bundle`, public). This is
  what "re-keyed on reconnect" was promised to be and never was.
- The agent writes the bundle atomically beside `node.yaml` and passes
  its children:
  - the path;
  - the pinned authority key;
  - their own recipient name.
- Children verify the signature themselves and reload the file when it
  changes.

**No hard expiry.** TUF expires metadata to defeat a *freeze* attack:
an attacker who blocks updates keeps a revoked key trusted. Here that
would cost the data path its M5 guarantee, which is to keep serving
while the root is dead. So a bundle never expires. **Its age is
reported instead:** `/healthz` details carry it, and it is an Issues
entry past 10 minutes. That is the same call this project made for
clock skew: report it, do not refuse traffic between healthy hosts.

*Practice:* SPIFFE trust bundles. TUF (versioned, signed metadata;
rollback protection). The expiry trade is recorded here rather than
hidden.

### D4. Who may issue what

| Issuer (bundle grant) | May issue |
| --- | --- |
| root key (`authority`) | sessions; exchanged tokens; client keys; service tokens with `sub: control` to any recipient |
| node key (`node`) | service tokens to **its own machine**, any `sub` (its children and itself); service tokens with `sub: agent` to other machines and to `control` |
| node key with `gateway` | also service tokens with `sub: gateway` to other machines and to `control` |
| standalone agent (not enrolled) | acts as its own authority, in a bundle it signs with its own identity key; nothing else trusts it |

**The `gateway` grant is given by the operator, not claimed by the
node.** A join token carries `grants`. The wizard mints the control
host's join token with `["gateway"]`, because the gateway is seeded
there. `/nodes` mints workers' tokens without it. A node reporting that
it runs a gateway changes nothing.

*Practice:* least privilege by issuer. Authorization comes from the
authority's registration record (SPIRE registration entries), never
from the workload's own claim.

### D5. Who accepts what

| Recipient, route class | Accepts |
| --- | --- |
| agent: operator-only | a session or exchanged token addressed to this node |
| agent: reads (`/v1/node`, components, runtimes, engines, admission) | the above; service tokens from this machine, from `control`, or `sub: gateway` |
| agent: runtime start and stop, client-key policy | a session; `sub: gateway` |
| agent: declare a runtime | a session; a `control` service token |
| library: reads | a session; this machine's services; `sub: agent` or `sub: gateway` from any member |
| inference-driver: `/v1/info`, `/v1/generate` | a session; this machine's services; `sub: gateway` |
| gateway: front door | a session; this machine's services; a client key (still on the root's positive list) |
| control: reads | a session; `sub: agent` or `sub: gateway` from any member |
| control: client-key policy and admission | a session; `sub: agent` or `sub: gateway` |
| control: replication log and snapshot | a session only |
| control: everything else | a session only |

**Exact kinds, finally.** "Any `service:*`" is gone. That is the
promise `agent/security.py:346-348` made and no verifier kept.

### D6. Operator sessions: minted by the root, bound to the console machine

- **Only the root mints sessions.** An enrolled agent's
  `POST /v1/auth/login`:
  1. verifies and unlocks locally, if it has a passphrase of its own;
  2. forwards the passphrase to the root, with its own node-signed
     service token as proof of which machine is asking;
  3. returns the root's session.
- **The session's `aud` is `["node:<that machine>", "control"]`.**
  That machine's origin is the only place the browser can use the
  session anyway, because `sessionStorage` is per origin.
- **A worker can be a console now.** It no longer answers "no local
  passphrase".
- **If the root is down,** sign-in says so and fails. Sessions already
  issued keep working, and inference is unaffected.
- **A login made directly at the root** (the wizard, the sealed-root
  unlock) gets `aud: ["control"]`.
- **Sign-out is install-wide.** The console agent forwards it, the root
  appends a replicated `revokeSession` entry, and the bundle's
  `revokedSessions` carries it to every verifier. Verifiers also check
  an exchanged token's `sid` against that list. The per-node list
  stays, for a sign-out made while the root is down.

*Practice:* authenticate at the authority, not at a resource server
(OAuth 2.0 / OIDC). Audience-restrict the session. Make logout take
effect everywhere the session works.

### D7. The console acts on other machines by token exchange, never by forwarding the session

The console agent's proxy is the single place a credential crosses
machines.

**On any forward to another machine** (a `node:<name>` hop, or a
component that lives elsewhere):

- A token **already addressed to the destination** passes unchanged. A
  session carries `control`, so a worker console reaching the root is
  not an exchange.
- A **session** addressed to this node is exchanged at the root:
  - `POST /v1/auth/token`, RFC 8693, with the session as the subject;
  - this node's service token is the actor;
  - the result is addressed to the destination node, carries `act` and
    `sid`, and lives 5 minutes. The console caches it per
    (session, destination) until 60 s before it expires.
- A **service token from this machine's own children** is re-minted
  for the destination, under the same `sub`, only if D4 allows that
  `sub` off this machine.
- A **client key** passes through unchanged.
- **Anything else is stripped.** A credential this node cannot vouch
  for never leaves it.

**What this buys:**

- A worker sees only 5-minute tokens addressed to itself. The session
  never reaches it.
- Revoking a console node kills every session bound to it. A verifier
  refuses a session whose `aud` names a node no longer in the bundle,
  and an exchanged token whose `act` does.
- **If the root is down,** acting on *other* machines from the console
  fails, with a message saying so. The console's own machine and the
  data path keep working.

*Practice:* RFC 8693 token exchange, with `act` for delegation. RFC 8707
and RFC 8725 §3.9 for audience-restricted tokens. Never forward a bearer
beyond its audience.

### D8. Machine-to-machine calls use short-lived per-recipient tokens from the caller's own agent

- **The gateway** asks its own agent for a token per destination:
  - `POST /v1/auth/service-token {audience}`, authenticated with its
    local token;
  - it gets a 15-minute token and refreshes it at half-life.
  - The agent mints one only if its bundle entry carries the grant.
  - No root is involved, so the data path survives a dead root exactly
    as M5 requires.
- **A worker agent** mints its own `sub: agent` token when it reaches
  the library on another machine.
- **The root** mints a 5-minute `control` token per node per call.
- **Children get a local token at spawn.** It is addressed to their own
  machine only, so it is worthless anywhere else.

### D9. Revoking a node removes its key; nothing else is rotated

`DELETE /v1/nodes/{name}`:

1. appends one `revokeNode` entry;
2. rebuilds the bundle, now without that node's key;
3. pushes the bundle.

Every token that node ever minted, and every session bound to it as a
console, stops verifying at each machine as soon as that machine holds
the new bundle. **Nobody else is logged out, no client key is
reissued, and no private key moves.** A node that was offline picks up
the bundle when it next reaches the root.

The whole install-wide rotation behind revocation, including the
mixed-key state and "re-keyed on reconnect", **is deleted**. It existed
only because every node held the same key.

### D10. Rotating the root token key

`POST /v1/control/rotate-key`:

1. generates a new root token key;
2. seals and logs it;
3. publishes a bundle naming only the new key.

Every session and client key dies, as today. This is the emergency
lever for "the root's key may have leaked". Nothing is distributed but
the bundle.

### D11. Nothing old survives

There is no migration, so the following are **deleted**, not kept for
compatibility:

- HS256 and 32-byte keys;
- `AUTH_SIGNING_KEY` and `AUTH_VERIFY_KEY`;
- `Enrollment.signingKey` and `signingKeyId`;
- the re-key message and `POST /v1/node/rekey`;
- the `service:<kind>` audience strings.

The development install re-installs.

## 2. What a leaked key costs afterwards

| What leaks | Costs |
| --- | --- |
| a worker's `node.yaml`, or the live worker | that worker. Off the machine it can only read the library catalogue and topology. It can mint no session, declare nothing, start nothing and read no snapshot. It is revoked in one step without logging anyone out. |
| the gateway-role machine's node key | that machine, plus starting, stopping and running inference on other machines' **already declared** runtimes, until it is revoked. Still no session, no declaration and no snapshot. |
| a token in transit or in a log | at most 5 to 15 minutes, at the one machine it names |
| the root token key | the install. It is sealed at rest under the passphrase; `passphrase_file` and `os_keyring` trade that for unattended restarts, as recorded in row 2. |

## 3. What stays true

- **The data path survives a dead root.** Gateway→driver and
  gateway→agent tokens come from the gateway's own agent.
- **One console.** Every node can be the console now, and it drives
  every other node, through exchange.
- **A headless GPU box restarts with nobody there.** Its node key is
  local and its bundle is cached.
- **Clock skew is tolerated to 300 s,** and reported beyond 2 s.

## 4. Contract changes

**`control.yaml`:**

- adds `GET /v1/trust/bundle`, public and signed;
- adds `POST /v1/auth/token` (exchange);
- `EnrollmentRequest.tokenPublicKey` is required;
- `Enrollment` gains `trustBundle` and loses `signingKey` and
  `signingKeyId`;
- `JoinTokenRequest.grants` and `Node.grants` are added;
- `DELETE /v1/nodes/{name}` no longer rotates;
- `rotate-key` rotates only the root token key;
- `LogOp` gains `revokeSession`.

**`agent.yaml`:**

- adds `POST /v1/node/trust-bundle`, replacing `POST /v1/node/rekey`;
- adds `POST /v1/auth/service-token`;
- login forwards to the root when enrolled;
- `NodeIdentity` reports `trustBundleVersion` and `trustBundleAge`.

**`common.yaml`:** adds `TrustBundle` and `TrustKey`, and the token
profile in prose. **Gateway, library and driver documents:** the auth
prose.

## 5. Residual risks, named

- **The console machine and the control-root machine are trusted by
  construction.** The console serves the page the passphrase is typed
  into. The root holds the root key unsealed while it runs.
- **A bearer token can be replayed within its lifetime at its one
  recipient.** DPoP (RFC 9449) or mTLS-bound tokens (RFC 8705) would
  close that. They are not built: the browser→console→node hop would
  need a proof per hop.
- **Node keys can be exported.** A TPM or DPAPI-backed non-exportable
  key would stop the file leak outright. Recorded, not built.
- **Freeze.** A node cut off from the root keeps its last bundle. The
  age is reported, not enforced (D3).
- **The standby follower has no production credential,** a
  pre-existing gap. Replication stays session-only until a standby
  identity is designed.

## 6. Build order

Each step lands with checks that reproduce the defect before the fix.
The last step ends in a live multi-process run and a sabotage pass.

1. **Contracts** (specs).
2. **A token module,** copied into all five Python repos (no shared
   core): bundle verification, the D2 checks, minting.
3. **control:** the bundle, enrollment, exchange, root-only sessions,
   revocation without rotation, replicated sign-out.
4. **agent:** node key, bundle sync, local minting, login forwarding,
   proxy exchange, children's environment.
5. **gateway, library, inference-driver:** verify from the bundle;
   gateway per-destination tokens.
6. **ui:** the wizard's gateway grant, and one login instead of two.
7. **Acceptance:** a root and two agents, where a stolen worker key is
   tried against every surface. Then pins in both installers.

## 7. Built (2026-09-25)

All seven steps. `tokens.py` is one file, byte-identical in the five
Python repos, and so are its tests apart from the import line.

| Repo | Commit | Sabotage |
| --- | --- | --- |
| control | `11e662d`, `9669978`, `b14bd57` | 13 of 14; the escape is a route check the verifier already makes, kept as policy |
| agent | `fd4fe3c`, `0ab922d`, `a5a15b6`, `ce90e34` | 26 of 26, after ten first-pass escapes each earned a test; 5 of 5 for the bundle age |
| gateway | `84a0b4b`, `d9d4ccb`, `53e98ae` | 13 of 13, and 3 of 3 for naming a refused mint |
| library, inference-driver | `e6ee80a`/`47dfdf0`, `24bfd1d`/`f754620` | 8 of 8 together |
| ui | `3a33350`, `9faffb5`, `53d465f`, dist `53d465f` | 2 of 2, and 3 of 3 for the new issue |

`scripts/row3-per-node-keys-acceptance.py` runs a root, two enrolled
agents, and a gateway and library started with the environment an agent
hands a child. It steals the worker's token key and tries twelve tokens
against the other processes; each is refused. What the key still buys
is asserted: library reads and root reads as that worker's agent, which
§2 predicts. It then revokes the worker, and after that the key buys
nothing, with no restart. A sign-out on one machine ends the session on
every machine. 26 checks pass. The browser hop through a console's
proxy runs only with `--lan`, because the hop refuses a loopback
advertise address by design. CI runs it with `--lan`.

**Three findings the build made:**

- **Most sabotage escapes named missing checks, not weak code.** In
  the agent, one first-pass escape was a distinction nothing could
  observe: an epoch lower than the held bundle's, answered as a rollback
  rather than a fence. Both are one 409. It was deleted. The fence that
  matters on its own is the epoch recorded in `node.yaml`, which holds
  when the kept bundle is lost. That fence is now tested.
- **The library's own sub check is redundant for another machine's
  key**, because the verifier's grant rule refuses that key first. It
  still matters for tokens the root signs. The test now uses those.
- **A 503 at sign-in is not "set up this install".** The login page
  read every 503 as a fresh install. With sign-in forwarded to the
  root, a root the agent could not reach would have sent an installed
  user to the setup wizard.

**The client-key import is gone** (contract `8296e4a`). It carried a
standalone machine's key records into the root's registry. Under
per-node keys those keys cannot verify anywhere in the install, so the
records looked active and were refused. The import was also the one
write a stolen worker `node.yaml` still had on the root: unbounded
appends to the replicated log, signed with a key meant only for address
announcements. A standalone machine's keys now stop working when it
joins, and the Home card says so.

**The bundle's age was measured from the wrong moment.** A pull returns
the same signed bundle until something changes, so its `iat` grows
without limit on a quiet install. It would have read as stale while
being current. `trustBundleAgeSeconds` is now the time since the node
last took a bundle, and it survives a restart through the kept file's
own time. It rides on `/healthz`, and past ten minutes the console lists
it as an issue. D3 promised both, and neither had been built.

**Two findings from the CI-script rewrite:**

- **A missing grant was silent.** Without the `gateway` grant the agent
  refuses to mint, and the far side answers "401 Missing token". The
  gateway's routing view now carries the agent's own refusal.
- **One control test was green for the wrong reason.** A check that
  imported fields are refused passed a malformed payload, which is
  refused whatever it carries. It now shows a clean record accepted
  before any refusal counts.

**Not done, named:**

- **Some manual acceptance scripts still speak the old model:** `m7`,
  `m9`, `r24`, `b1`, `b2` and `r36`.
- **An install from before this change must be installed again.** Its
  `node.yaml` has no token key the root knows.

## Sources

- RFC 8725, JSON Web Token Best Current Practices (§3.1, §3.9, §3.11, §3.12)
- RFC 7515 (JWS `kid`), RFC 7519 (JWT), RFC 7638 (JWK Thumbprint), RFC 8037 (EdDSA in JOSE)
- RFC 9068, JWT Profile for OAuth 2.0 Access Tokens
- RFC 8693, OAuth 2.0 Token Exchange (`act`)
- RFC 8707, Resource Indicators for OAuth 2.0
- RFC 9700, OAuth 2.0 Security Best Current Practice
- RFC 9449 (DPoP), RFC 8705 (mTLS-bound tokens): residual risk, not built
- NIST SP 800-57 Part 1 Rev. 5, Recommendation for Key Management
- SPIFFE / SPIRE: workload identity, trust bundles, registration entries
- The Update Framework (TUF) specification: signed versioned metadata, rollback and freeze attacks
