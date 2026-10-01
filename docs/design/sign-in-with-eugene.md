# C2: signing in with Eugene

**Status: designed 2026-10-01; Troy took the four calls in §9 the same day.
Not built.** Slice C2 of
[`workbench.md`](workbench.md) §4. Troy's calls so far: sign-in comes from
Eugene; a solo install signs in with the Eugene passphrase and no second
one; a small business gets real accounts, each revocable without touching
anyone else; both in one slice. The security decisions below follow the
standards they cite, the practice Troy asked for on 2026-09-25 (*"use SOTA
security practices ... we can be the most security conscious"*). The calls
that are his are in §9.

## 0. What exists today

Measured 2026-10-01 in control, the agent and the UI:

- **One identity.** Every session's `sub` is `"operator"`, and
  `operatorName` is hard-coded. There is no account model anywhere.
- **Sessions are the root's.** `POST /v1/auth/login` on control checks the
  passphrase (Argon2id, t=3, m=64 MiB, p=4), unseals, and mints an
  `ep-session+jwt` (EdDSA, root token key, 14 days). An enrolled agent
  forwards sign-in to the root.
- **No OAuth or OIDC code.** The only OAuth-shaped piece is the console's
  RFC 8693 token exchange.
- **Keys are Ed25519 and X25519 only.** No RSA anywhere; HS256 refused.
- **Apps hold a client key** (`aud: gateway`) and a per-spawn admin token.
  Nothing lets a person sign in to an app.

## 1. The shape

**Eugene becomes an OpenID Connect provider.** An app sends the person's
browser to Eugene; Eugene asks who they are; the browser comes back to the
app with a code; the app's server trades the code for tokens that say who
signed in. That is OIDC's Authorization Code flow, the one every sign-in
library speaks, so any app that can use "Sign in with Google" can use
Eugene the same way. Open WebUI is one of them.

- **The control root issues** (it holds the identity, the people and the
  keys). The browser reaches it through the **control host's agent**, at
  `/oidc/`: browsers reach the agent's port, and the agent already forwards
  sign-in to the root.
- **The issuer** is one URL, `<control host's agent>/oidc`, published at
  `/oidc/.well-known/openid-configuration`. It is shown on the console and
  written into each app's settings. Changing it is an operator action,
  because every app has it.
- **What an app gets is who the person is, nothing more.** Its access to
  models stays its client key. A sign-in token opens nothing in the hub
  (§3, D3).

## 2. People

- **The operator** is the install's owner and signs in with the Eugene
  passphrase, as today. It is not a record: it is the identity that already
  exists, `sub: "operator"`.
- **A person** is an account the operator adds:
  - name (unique, compared case-folded), display name;
  - a password, stored as an Argon2id verifier with the passphrase's
    parameters;
  - which apps they may use: all, or a list;
  - created, password changed, disabled.
- **People live in the control root's replicated log**, beside nodes and
  keys, so a standby keeps them. New operations: `putPerson`,
  `setPersonPassword`, `disablePerson`, `enablePerson`, `deletePerson`.
  The snapshot already carries the passphrase verifier and is readable only
  by `service:control` (R2.4); people's verifiers ride the same way.
- **A person is not an operator.** They sign in to the apps they are given
  and nothing else: no console, no settings, no keys. A person's sign-in
  mints no `ep-session+jwt`.

## 3. Decisions

### D1. OIDC Authorization Code with PKCE, and nothing else

OpenID Connect Core 1.0, the Authorization Code flow, with PKCE (S256)
required of every client. That is the OAuth 2.0 Security Best Current
Practice (RFC 9700) and OAuth 2.1. There is no implicit flow, no hybrid
flow, no password grant and no device flow. `state` and `nonce` are
required. Discovery (OIDC Discovery 1.0) and a JWKS are published.

### D2. Confidential clients only, in this slice

Every client has a server and a secret (`client_secret_basic`). Workbench
and Open WebUI both do. A browser-only or phone app (a public client) is
not supported yet (§9 call 4).

### D3. ID tokens are RS256, and open nothing in the hub

- **RS256** is the one algorithm OIDC requires every provider to offer, so
  it is what every relying party supports. The root makes a 3072-bit RSA
  key at first need. It is sealed under the master key like the root token
  key, published in the JWKS with an RFC 7638 `kid`, and rotated with the
  root's keys (both published while the old one's tokens can live).
- **Every Eugene verifier refuses them by construction.** Hub tokens are
  `ep-*` classes signed with EdDSA, and every verifier checks both. An ID
  token's `typ` is `JWT`, its algorithm RS256, its `aud` the app's
  `client_id`, so no hub API accepts it, ours included. No back doors,
  structurally.

### D4. One sign-in page for both cases

Served by the root at `/oidc/authorize`, as a plain server-rendered page.
It is not the console's app, so nothing of the console's session is on it.

- **With no people on the install,** the page asks for Eugene's passphrase
  and nothing else: the solo case, with no second passphrase.
- **With people,** it asks for a name and a password, and the owner signs
  in with their own name (`operator`, or what the console shows for them)
  and the passphrase.
- **The same answer for a wrong name and a wrong password.** Rate-limited
  per address (the console's limiter: 5 failures a minute) and per name.
- **CSRF:** the form carries the pending request's id, held by the root
  for 10 minutes and good once. `Content-Security-Policy` and
  `frame-ancestors 'none'` on every page.

### D5. Every app asks (Troy, §9 call 3)

No sign-in is remembered across apps: there is no session cookie at the
provider. A person signed in to Workbench signs in again for Open WebUI.
That leaves nothing at the provider to steal or to outlive a revocation,
and `prompt` is ignored because every request already shows the page.
### D6. Codes, tokens, lifetimes

- **Code:** random, single use, 60 seconds. It is bound to the client, the
  redirect URI, the PKCE challenge and the nonce, and held in the root's
  memory (a root restart costs only the sign-ins in flight).
- **ID token:** RS256, 10 minutes. Claims: `sub` (the person's id, or
  `operator`), `name`, `preferred_username`, `eugene_role` (`operator` |
  `member`), `auth_time`, `nonce`.
- **Access token:** RFC 9068 JWT, RS256, 10 minutes, `aud` the client. It
  is good only at `/oidc/userinfo`.
- **Refresh token:** a signed token good at `/oidc/token` only, 30 days.
  Each refresh checks the person is still enabled and their password
  unchanged since it was issued, and that the sign-in was not signed out.
  So a revoked person is out within the ID token's 10 minutes at an app
  that refreshes, as ours does. Confidential clients make rotation optional
  (RFC 9700 §4.14); refresh tokens are not rotated in this slice.

### D7. Which apps may ask

- **A client** is `{client_id, name, secret verifier (SHA-256 of 32 random
  bytes), redirect URIs (exact match), owner}`, in the replicated log.
- **Registry apps register themselves at install.** A manifest that says
  `signIn: true` names its callback path. The agent registers the app with
  the callback on each address it is opened at, and writes the secret
  beside its key, delivered the same way (a file in its own account's
  folder, or a systemd credential). Uninstall removes the client.
- **Any other app** is added by the operator on the console: a name and its
  redirect URIs. The secret is shown once.
- **Plain `http` redirect URIs are allowed**, because a home network has no
  certificates; exact matching is what keeps a code from being sent
  elsewhere (RFC 9700 §4.1).

### D8. Who may use which app

A person's app list is checked at sign-in. Someone not allowed sees a
sentence naming the app and saying the owner can allow it, and no code is
issued. The operator may use every app.

### D9. Revocation and sign-out

- **Disabling a person** refuses their next sign-in and their next refresh
  at once.
- **An app that refreshes** (ours, every 10 minutes) loses them within 10
  minutes.
- **An app that keeps its own session after sign-in** (Open WebUI does)
  loses them only when that session ends. The console says so beside the
  Disable button.
- **Sign-out at the provider** (`/oidc/logout`, RP-Initiated Logout 1.0)
  ends the refresh tokens from that sign-in.

### D10. Forgotten passwords (§9 call 2)

The operator sets a new password on the console; the person changes it on
the sign-in page after signing in. There is no email.

## 4. The console

Plain words here; the workshop names are Workbench's.

- **People**, on the install root:
  - add a person, with a first password;
  - disable, enable, delete;
  - set a new password;
  - choose their apps.
- **Apps that sign in with Eugene**, on the same page: the registered
  clients, which app or person registered each, adding one for another app
  (the secret shown once), and removing one.
- **The issuer URL**, with a copy button, for configuring another app.

## 5. Contract

- **`control.yaml`:**
  - the OIDC endpoints: discovery, JWKS, authorize, token, userinfo,
    logout;
  - `/v1/people` and `/v1/oidc/clients`, operator-only;
  - `LogOp` gains the person and client operations;
  - `Person`, `OidcClient`, and their requests.
- **`agent.yaml`:**
  - the control host's agent serves `/oidc/*` and forwards it to its root;
  - `AppManifest.signIn` and `signInCallbackPath`;
  - `App.signIn`.
- **`common.yaml`:** no change. Hub tokens are untouched.

## 6. Order

1. **Contract**, regenerated in every consumer it reaches.
2. **control:** people and clients in the log; the RSA key; the OIDC
   endpoints; the sign-in page.
3. **agent:** the `/oidc/` forward on the control host; registering a
   registry app as a client at install; delivering its secret.
4. **ui:** People, and Apps that sign in with Eugene.
5. **The failing check first:** a run with a real OIDC client library
   (Authlib, which Open WebUI uses) that signs in as the operator and as a
   person, is refused for an app the person is not given, and is cut off
   within 10 minutes of being disabled. Before the build every step fails.
   Then a sabotage pass.

## 7. Residual risks, named

- **Plain HTTP on a home network** carries passwords and codes in the
  clear on that network, as the console's passphrase already is. HTTPS is
  the operator's (a reverse proxy, Tailscale's certificates).
- **An app that keeps its own session** outlives a revocation by that
  session's length (D9).
- **The control host is trusted** (per-node-token-keys §5): it holds the
  RSA key unsealed while it runs, as it holds the root token key.

## 8. Not in this slice

- Per-person usage and limits at the gateway (§9 call 1).
- Public clients: browser-only and phone apps (§9 call 4).
- Self-service password reset.
- Two-factor sign-in.
- Signing in to the console as a person.

## 9. Calls taken (Troy, 2026-10-01)

| # | The call | Taken |
| --- | --- | --- |
| 1 | Whether the gateway sees each person | **Later, its own slice.** Models are used with the app's key |
| 2 | How a forgotten password is reset | **The owner sets a new one** on the console (D10) |
| 3 | Whether a sign-in is remembered across apps | **No: every app asks** (D5) |
| 4 | Browser-only and phone apps | **Not in this slice** (D2) |