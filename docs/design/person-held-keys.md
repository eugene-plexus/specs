# Person-held keys, checked at the site (J14)

**Status:** a design, 2026-10-06. Nothing in it is built. **Calls J39-J49
(§6) are Troy's to take.** It is the session J29 asked for: the check that
goes back once J20 removes the by-hand folder permission. It builds on
[`job-sites-own-enrollment.md`](job-sites-own-enrollment.md) §2.8 (the
sketch) and J29 (the release gate), and on [`remote-nodes.md`](remote-nodes.md)
§3.3 (membership is not access, and its stated limit). It does not reopen
J1-J38.

The measurements in §2 were taken on this box on 2026-10-06; they decide the
shape, so they come first, as the S4U measurement did for 2b.2.

Code anchors are at the pins landed 2026-10-06:

| Prefix | Repo, path | Commit |
|---|---|---|
| `SH/` | `site-host/src/eugene_plexus_site_host/` | `044c159` |
| `CT/` | `control/src/eugene_plexus_control/` | `89a89fd` |
| `AG/` | `agent/src/eugene_plexus_agent/` | `d83712c` |
| `WB/` | `workbench/src/eugene_plexus_workbench/`, `WEB/` = `workbench/web/src/` | `53f6e81` |
| `PL/` | `specs/platform/1.0.0/` (vendored `tokens.py`, `sealing`-style helpers) | — |

---

## 0. The shape, in one page

**A person-held key is one the control root never sees and cannot substitute,
whose public half the *site* pins at the machine, and against which the site
checks each thing done in that person's name.** It is what turns the root from
*the authority on who did what* into *a courier that cannot forge*.

- **The threat it closes (T1): a compromised or malicious root forging a
  person's intent.** Today the site believes a `subject` string the root
  asserts (`SH/host.py:465-490`, `CT/routes/sites.py:615-646`). A key the root
  cannot mint, pinned at the machine, is what the site checks instead.
- **What stays the root's (not closed, by design):** membership (who exists,
  who is invited, revocation) and availability (the root can still withhold or
  delay). These need the root; a key does not change them.
- **What a key only *reduces* (T2): a compromised Workbench the person uses.**
  Central Workbench is served from the root's own machine, so its code is the
  root's to tamper with. A hardware key (passkey) limits that to "one thing
  signed per gesture, with the content not shown"; a software key in that same
  origin does not limit it at all (§2.6). J14 does not claim to close T2;
  remote-nodes.md §3.3 already said so.

**The one measurement that reshapes the sketch** (§2): a passkey cannot bind
to an IP address, and plain HTTP on a LAN address is not a secure context, so
**neither a passkey nor WebCrypto works in Workbench on the default LAN-only
install.** A key usable *from central Workbench* needs the HTTPS entry point
with a DNS name and a certificate the device trusts. The only secure context
every install has, with no entry point and no cloud, is **the machine's own
loopback page** — which is exactly where the link ceremony already happens, and
exactly where the root is not.

**So the design splits by where the signing happens, not by what the key is:**

| Where the person signs | Works on | Root-proof because | Costs |
|---|---|---|---|
| **At the site machine** (the agent's loopback page) | every install, plain-HTTP LAN included | the root is a different machine; the page is served by the local agent, not the root | the person must reach that machine's loopback (be at it, or tunnel/tailnet to it) |
| **From central Workbench**, with a passkey | installs with the HTTPS entry point + a DNS name + a trusted cert | the private key is in the person's own device authenticator, which the root never holds | the entry point and a trusted cert; a gesture per signature; the content is not shown by the authenticator |

**J14a** (signed policy edits) is built first and gates the release of
owner-run sites. **J14b** (signed calls) ships with commands (2b.4). Both
reuse what already exists: the at-the-machine link ceremony (root-proof,
`AG/routes/site_link.py`), the site's pinned-root verification
(`SH/root_link.py:152-191`), canonical-JSON Ed25519 signing
(`CT/sealing.py`), and a monotonic sequence against replay
(`CT/applied.py:202-204, 526-551`).

---

## 1. The threat model, exactly (J39)

Three parties, three different trust positions. The site is a different
machine from the root (Amish_Station vs the NAS container), which is what makes
an at-the-machine ceremony mean anything.

**T1 — the root forges a person's intent.** The control component, its
replicated state, its keys, or whoever holds them. It authenticates to the
site with the site's own bearer over the pinned TLS link, and puts a `subject`
string on every operation (`CT/sites.py:176-190`). The site checks a policy
edit only by comparing that root-asserted `subject` to the owner id it pinned
at join (`SH/host.py:465-490`) — so a root that puts the owner's id on a forged
edit is obeyed. It can also mint a sign-in for any person (the refresh token is
checked with the provider key the root itself holds, `CT/oidc.py:58, 262-320`),
so a forged call passes the site's per-person routing too.

- **J14a stops T1 for policy edits.** The site verifies a signature by a key
  the root never held, over the edit, against the public key pinned for that
  person at the machine.
- **J14b stops T1 for calls.** Each call the person approves carries a
  signature the site checks. This is what makes "ask" a check the site makes
  itself (today it cannot, `SH/host.py:337-341`), and it is what commands
  need: once a tool can run a program, a forged call is the person's whole
  account.

**T2 — the person's Workbench is the attacker's.** Central Workbench runs on
the control host (the root's machine, `remote-nodes.md:492-496`), serves its
own frontend JS (`WB/web.py:49-54`), and the browser signs inside that origin.
So a root that owns that machine owns the signing code.

- A **passkey** holds its private key in the person's device authenticator,
  which that JS cannot read or export; the JS can still *ask* for a signature,
  but each one needs a user gesture and the authenticator does not show what is
  being signed. So T2 is reduced to "one wrong thing per gesture," not closed.
- A **software key in Workbench's origin** is fully the attacker's under T2:
  the JS can use it silently and at scale. It therefore defends T1 **only on a
  site machine's own loopback page**, where the serving code is the local
  agent and not the root. It is not a defense in central Workbench. This is the
  single most important consequence of §2.

**T3 — not in scope, named so it is not confused with T1:** what the root can
already do *on a node*. The root's reach into a node it enrolled is broad by
design (it places runtimes and pushes topology). J14 does not try to narrow
that; it is a node-trust question, not a site one. J14 is only about not
forging a *person's* intent at a *site*. The site holds its own key, policy and
audit log precisely so that this is a separable boundary (`SH/identity.py`,
`SH/policy.py`, `SH/audit.py`).

**Out of J14 entirely:** membership and revocation (the root's, and must be —
a key the person holds cannot remove that person); availability (the root
relays, so it can delay or drop; the site's audit log is how that becomes
visible after the fact).

---

## 2. What a browser actually allows, by origin (measured 2026-10-06)

Measured on this box (Windows 11 Pro 10.0.26200) against the system **Chrome
154.0.8037.98**, driven by Playwright. WebAuthn was exercised two ways: a CDP
**virtual** platform authenticator (to read what each origin *offers*), and a
**real** run with no virtual authenticator and no certificate-trust flag (to
catch what the virtual one masks). Names were pointed at the server with
`--host-resolver-rules`; a private CA stood in for a trusted local CA via
`--ignore-certificate-errors-spki-list`. Scripts and raw JSON are in the
session scratchpad (`webauthn/`), not committed.

### 2.1 The table

| Origin Workbench can have | Secure context | WebCrypto (`crypto.subtle`) | Non-extractable key, ECDSA P-256 + Ed25519 | Key `export` refused | Passkey (`navigator.credentials.create/get`) |
|---|---|---|---|---|---|
| `http://<LAN IP>:port` (direct mode, the LAN default) | **no** | no | — | — | **no** (`navigator.credentials` absent) |
| dotless LAN name, `http://amish-station:port` | **no** | no | — | — | no |
| mDNS `http://amish-station.local:port` | **no** | no | — | — | no |
| `http://127.0.0.1:port` (the agent link page) | yes | yes | yes | yes | **no** — `SecurityError: invalid domain` |
| `http://localhost:port` | yes | yes | yes | yes | yes, RP ID `localhost` |
| `https://<LAN IP>` | yes | yes | yes | yes | **no** — `invalid domain` (an IP cannot be an RP ID) |
| `https://workbench.home.arpa` (Caddy local CA) | yes | yes | yes | yes | **yes, iff the cert is trusted** |
| `https://<name>.ts.net` (tailnet) | yes | yes | yes | yes | yes, iff the cert is trusted |
| `https://localhost` | yes | yes | yes | yes | yes |

### 2.2 The findings that decide the design

1. **An IP address can never hold a passkey.** `https://192.168.16.75` and
   `http://127.0.0.1` both answer `SecurityError: This is an invalid domain`
   to `create`. The handoff's premise is confirmed. So a passkey needs a DNS
   name, which the direct-port install (an IP, or a plain-HTTP dotless/.local
   name) does not have.

2. **Plain HTTP on a LAN address is not a secure context at all.** No
   `crypto.subtle`, no `navigator.credentials`. So the default LAN-only
   Workbench (`http://<LAN IP>:<port>`, `AG/apps.py:1299-1310`) can hold
   **no key of any kind** — not a passkey, not a WebCrypto key. Only
   `127.0.0.1`, `localhost`, and HTTPS are secure.

3. **A passkey needs a certificate the device trusts.** With the leaf trusted,
   `create` succeeds on an HTTPS name. With the certificate *untrusted and the
   warning clicked through*, a **real** authenticator refuses in ~1 ms:
   `NotAllowedError: WebAuthn is not supported on sites with TLS certificate
   errors`. The virtual authenticator hid this (it returned success), which is
   why the real cross-check mattered. **Consequence:** Caddy's private local CA
   works only once each device the person uses has trusted its `root.crt`
   (`container-access.md:228-233`); Let's Encrypt will not issue for
   `.home.arpa`/`.local`/`.internal` (`AG/entrypoint.py:271-299`); a tailnet
   name with a `tailscale` certificate, or an owner-supplied certificate, is
   trusted without a per-device step.

4. **WebCrypto is available on far more origins than WebAuthn**, including
   `http://127.0.0.1` and `http://localhost`, where a passkey is refused. A
   non-extractable ECDSA P-256 **and** Ed25519 key both generate and sign; a
   `CryptoKeyPair` persists in IndexedDB; and `exportKey` on the private half
   raises `InvalidAccessError` — the browser will not hand the key back to
   script. So a software key at the loopback page is real and cannot be
   exfiltrated by the page's own JS.

5. **Related Origin Requests works, for HTTPS siblings only.** A passkey made
   with RP ID `workbench.home.arpa` was usable (both `get` and `create`) at
   `https://amish.tail1234.ts.net` **when** `workbench.home.arpa` served
   `/.well-known/webauthn` listing that origin. Without the file it failed
   (`not a registrable domain suffix…`). But **loopback is never covered**:
   `http://localhost` and `http://127.0.0.1` were refused even when listed
   (`no listed origin matched the caller` / `invalid domain`). So one passkey
   can span the several HTTPS names one Workbench answers at (LAN name + tailnet
   name), but cannot span the HTTPS Workbench *and* the loopback link page.

6. **A passkey's RP ID can only be the registrable domain it was made under.**
   So the passkey is bound to Workbench's name, and the site must verify a
   WebAuthn *assertion* (parse `authenticatorData`, check the RP-ID hash, the
   flags, the sign counter; check `clientDataJSON` carries our challenge),
   not a raw signature. A loopback WebCrypto key, by contrast, is a raw
   signature the site verifies directly — materially less code on the site
   (`SH/`), which has no WebAuthn verifier today.

### 2.3 What the code already gives us

- **The link page is at `http://127.0.0.1:<agent port>`** (`AG/routes/
  site_link.py:280-281`), a secure context that does WebCrypto but **not**
  WebAuthn. If an at-the-machine *passkey* is ever wanted, that page must move
  to `http://localhost` (same socket-owner check, `AG/site_link.py:97-157`).
  For an at-the-machine *WebCrypto* key, `127.0.0.1` is already right.
- **The site already pins and verifies the root's Ed25519 key** over a signed
  list (`SH/root_link.py:152-191`, EdDSA, `typ`, origin, 300 s leeway) and
  refuses an older `iat` (`:131-139`). J14's verifier is the same shape with
  the person's key in place of the root's.
- **Canonical JSON + detached Ed25519 already exists** in the root
  (`CT/sealing.py`: `json.dumps(sort_keys=True, separators=(",",":"))`,
  `sign_*`/`verify_*` over PyNaCl). Vendor it into `SH/` as `tokens.py` was.
- **A monotonic sequence against replay/rollback already exists** for node
  address announcements (`CT/applied.py:202-204, 526-551`;
  `AG/enrollment.py:296-300`). Policy edits want the same, per (site, person).
- **A fresh-window replay guard already exists on the site** (`SH/host.py:
  167-174`, a used-id set + a 30 s window). Reuse it for the signature's
  nonce/expiry; use the sequence for durable ordering.

---

## 3. Where the key lives, and where signing happens (J40, J41, J42)

### 3.1 The recommendation

**Two paths, one key model.** In both, the key is person-held, its public half
pinned at the machine (§4), and the private half is somewhere the root cannot
reach.

- **Path A — at the site machine (the baseline; every install).** The agent
  serves a signing page on loopback — today's link page, extended. The person's
  key is a **non-extractable WebCrypto key** created there and kept in that
  page's IndexedDB. It signs policy edits. It is root-proof because the site is
  a different machine and the page is served by the local agent, not the root.
  It works on plain-HTTP LAN installs, because `127.0.0.1` is secure
  everywhere.

- **Path B — from central Workbench (remote; needs the entry point).** The
  person's key is a **passkey** in their own device's authenticator, created in
  Workbench's HTTPS origin and reused across Workbench's names by Related
  Origin Requests. It signs policy edits (and, at J14b, calls) without the
  person being at the machine. It needs the HTTPS entry point, a DNS name, and
  a certificate the device trusts.

**A software key in central Workbench's origin is explicitly rejected** (§2.6,
T2): the root serves that JS, so such a key defends nothing against T1. The
WebCrypto key is used **only** at the loopback page, where the serving code is
not the root's.

### 3.2 Why this split, and the call it forces (J41)

The measurement leaves no third option. To sign *remotely* with any
root-resistance, the key must be a hardware authenticator (the root serves the
page, so a software key is the root's), and WebAuthn needs HTTPS + a name + a
trusted cert. To sign on *every* install with no entry point, the only secure
context is loopback, which means at the machine.

So **J41 is Troy's to take: does running tools as each person (2b.2, the
release J29 gates) *require* the HTTPS entry point?**
- **Recommended: no — require only that the owner has a key, by Path A.** A
  LAN-only install can run owner-run sites once the owner has paired a
  loopback key at the machine (they are usually at it — it is their PC). Remote
  per-person signing (Path B) is then an *option* that lights up when the entry
  point is set. This keeps the LAN-only, no-cloud install working, which is
  Troy's constraint, and keeps the entry point optional.
- **The trade-off:** a *remote* person on a LAN-only install cannot sign their
  own workspace rules (2b.3) without either reaching the machine's loopback
  (tailnet/tunnel to that machine) or the install adding the entry point.
  Owner membership edits are fine (the owner is at their machine); the friction
  lands on multi-person LAN installs with people who are never at the machine —
  which, today, is the MSP case, not the household.
- **The alternative:** require the entry point for any owner-run site. Simpler
  (one signing path, Path B only), and remote signing always works — but it
  makes every install that wants Job Sites set up an HTTPS name first, and on a
  private local CA that means every device trusting a CA, which is close to a
  setup step for the end user.

### 3.3 The certificate, without the cloud or a per-device CA step (J42)

Path B needs a trusted cert. The entry point already offers three cert modes
(`AG/entrypoint.py:233-312`). For WebAuthn specifically:
- **Private local CA** (the local default): works, but only after each device
  the person signs in from has trusted the CA's `root.crt`. That is a real
  step on each laptop and phone, and fiddly on mobile.
- **A tailnet name with a `tailscale` certificate:** trusted by default (public
  chain), no per-device step, no public exposure. Nothing wires Workbench to a
  `.ts.net` name today (the entry point would accept the name; no doc describes
  it). This is the lowest-friction trusted-cert path for a no-cloud user who
  already runs a tailnet.
- **Owner-supplied certificate:** for an owner who has their own CA or cert.
- **Let's Encrypt:** needs a public name and port 443; out of the no-cloud
  path, and refused for the private suffixes anyway.

**Recommendation:** keep Path A (loopback WebCrypto) as the floor so *some*
person-held signing works with no cert at all; for Path B, document the local
CA (with its per-device trust) and support a tailnet name as the
no-per-device-step option. **Do not** make a trusted public cert a hard
requirement of Job Sites — that would drag the cloud, or a public domain, into
the path.

### 3.4 Keys per person

A person may pin **several keys** — a loopback WebCrypto key at each machine
they use, a passkey on their laptop, a passkey on their phone. Any one signs.
This is what makes "lost a device" survivable (§5) and what lets the same
person be at-the-machine on one site and remote on another.

---

## 4. Pinning the key so the root cannot substitute it (J43)

The site must learn the person's public key **without the root being able to
swap it**. Two shapes, by path.

### 4.1 Path A: created at the machine, pinned there, no code needed

The loopback signing page is already root-proof: the agent reads the OS account
from the socket (`AG/site_link.py:97-157`) and the root is a different machine.
So a key created on that page is bound to the account the page already
verified. The flow extends the existing link ceremony:
1. The person signs in at `http://127.0.0.1:<port>/link` (today's flow,
   establishing person ↔ OS account, `AG/site_link.py`).
2. The same page generates the non-extractable WebCrypto keypair and shows the
   person the public key's short fingerprint.
3. The page hands the **public** key to the **site host** — not the root —
   over a local channel. The agent and the site host are both on this machine;
   the links file is already the agent→site-host, admin-only hand-off
   (`AG/site_links.py`, `SH/links.py`). The pinned public key sits beside the
   link, written by the agent (SYSTEM / root), read-only to the site host.
4. The site host now has a key for that person that never touched the root.

No pairing code is needed, because nothing crossed the root. This is the clean
case and the reason to prefer Path A as the baseline.

### 4.2 Path B: created in Workbench, pinned by a code shown at the machine

A passkey must be created in Workbench's origin (its RP), so its public key
comes back to Workbench and would travel Workbench → root → site — where a
compromised root could swap it. The sketch's pairing code closes that:
1. At the machine (the loopback page, or the headless one-liner's terminal),
   the **site host** generates a short code and shows it. The code never leaves
   the machine and never goes through the root.
2. The person types the code into Workbench. Workbench creates the passkey and
   sends `{credentialId, publicKey, MAC}` toward the site, where
   `MAC = HMAC(code, canonical(credentialId ‖ publicKey ‖ site ‖ enrolledAt ‖
   person))`.
3. The site host accepts the key **only if the MAC checks** against the code it
   generated. A root that swaps the public key cannot forge the MAC without the
   code, which it never saw.

The code is generated and verified by the **site host**, and merely *displayed*
by the agent's page (they are different processes, §A1); the site host hands
the agent only the code to show, and checks the returned MAC itself. The code
is single-use, short-lived (reuse `SH/host.py`'s window), and rate-limited.

### 4.3 The call (J43)

**Recommended:** Path A pins with no code (the key is born root-side-blind);
Path B pins with a machine-shown code and a MAC. **Trade-off:** two pinning
paths to build and test. The alternative — one path, always the pairing code —
is uniform but adds a code to the common at-the-machine case that does not need
one, and a code the person must carry from the machine to Workbench even when
they are standing at the machine.

---

## 5. What is signed, and how the site checks it (J44, J45)

### 5.1 The signed envelope (J44)

Canonical encoding is `CT/sealing.py`'s already: `json.dumps(sort_keys=True,
separators=(",",":"))`, vendored into `SH/`. The signed object binds:

```
{ "site": <site id>, "enrolledAt": <site enrolledAt>,
  "person": <subject>, "key": <credential/key id>,
  "act": <"folder.add" | "folder.people" | "access.set" | …>,
  "args": <the edit's arguments, canonical>,
  "seq": <monotonic per (site, person)>, "iat": <unix seconds> }
```

- **site + enrolledAt** reuse the binding the site already checks on every
  operation (`SH/channel.py:109-110`), so a signature for one enrollment cannot
  be replayed into a later one.
- **person + key**: the site verifies the signature against a public key it has
  pinned **for that person** (§4), not against the root-asserted `subject`
  alone. This is the whole change: the `subject` on the operation is now a
  claim the site *checks*, not one it *trusts*.
- **seq** reuses the node-address monotonic-sequence pattern
  (`CT/applied.py:526-551`): the site refuses a `seq` not greater than the last
  it accepted for that (site, person), which stops a root replaying or
  reordering a person's own past edits.
- **iat** plus the existing fresh-window (`SH/host.py:167-174`) bounds
  staleness; the nonce is `(person, seq)`.
- **Path A** signs this with the raw WebCrypto key (direct Ed25519/ECDSA
  verify). **Path B** signs it as a WebAuthn assertion whose challenge is
  `SHA-256(canonical envelope)`; the site verifies the assertion (RP-ID hash,
  flags, counter, challenge) and the signature against the pinned credential
  key. The site gains a small WebAuthn verifier for Path B only.

### 5.2 Who may sign what (J44)

- **The owner** signs edits about **who may use the site** and any cross-person
  grant (today's `folder.people`, `access.set`, `server.enable`,
  `settings.set` — the owner-only edits at `SH/host.py:465-490`). The site
  checks the signature against the owner key it pinned at join.
- **Each linked person** signs **their own** workspaces and rules, once 2b.3
  gives them their own (today there is only the owner's policy; §2.6 of the 2b
  design). The site checks against that person's pinned key.
- **People with no link (J27)** hold no key — they have no account at the
  machine and no ceremony. Their access is the **owner's** to grant and runs as
  the owner, confined (`SH/host.py:219-232`). So the owner signs "share folder
  X with person P"; P signs nothing and can forge nothing, because P acts only
  as the owner within the owner's grant. Correct and unchanged.
- **Eugene's owner in dev mode (J6e, J13b)** stays **root-trusted and
  dev-mode-gated**, and J14 deliberately puts **no** key behind it. Eugene's
  owner *is* the root operator; a key they hold is a key the root holds, which
  defeats the purpose. Dev-mode grants already come from the replicated log,
  only in dev mode, only for files (`CT/sites.py:83-107`,
  `SH/host.py:436-461`). A new install starts in production (`remote-nodes.md`
  §3.3), so this is off by default and visible when on.

### 5.3 Lost or replaced keys (J45)

- **A new device or a cleared browser** means the pinned public key no longer
  has its private half. The person **re-pairs at the machine** (Path A) or
  pairs a new passkey with a fresh code (Path B). Because a person may hold
  several keys (§3.4), losing one is not a lockout if another is pinned.
- **Grants a gone key signed stay in force.** Policy is durable state, not a
  per-signature fact; the site does not un-share a folder because a key
  rotated. New *edits* need a current key. Removing a key is itself an edit,
  signed by another of the person's keys, or made at the machine.
- **The owner can see and clear a person's keys at the machine** (root-proof,
  the same place the links live). Clearing a person's last key returns that
  person to "cannot edit policy" and leaves their existing grants until the
  owner changes them.
- **If the owner loses every key:** re-pair at the machine. Presence at the
  machine is the recovery, which is consistent with J6b (the owner confirms at
  the machine at join).

---

## 6. Per-platform (J46)

Where the ceremony happens, and who can perform it, by install. Builds on the
2b.2 rows (`job-sites-own-enrollment.md` §3.2).

| Install | At-the-machine signing page (Path A) | Remote passkey (Path B) | Notes |
|---|---|---|---|
| **Windows service** | the agent's loopback page, already served (`AG/site_host.py:246-249`), extended to create and pin a WebCrypto key | yes, if the entry point is set | the common multi-person machine |
| **Windows per-user / Linux `--user` / macOS** | one person (the installer). The join opens a loopback page in their desktop browser to create and pin their key | yes, if the entry point is set | a desktop session exists, so a browser exists |
| **Linux system install, headless** | **no browser at the machine.** The elevated one-liner (`install.sh --site-link`, J36) prints a **pairing code** at the terminal the admin is already at; the person pairs a passkey from their laptop against it (Path B's code, no browser needed at the server) | the only path here, and it needs the entry point | if there is no entry point, a headless site is **unsigned** (§7) and stays root-trusted until a key is paired |

The one real gap is the headless Linux server with no entry point: it has
neither a browser for Path A nor an HTTPS Workbench for Path B. **Recommended:**
it runs unsigned (§7) until either is present; the one-liner can still print a
code the day the entry point is added. The alternative — a key file the
one-liner writes as root — is *machine-held*, not person-held, so it does not
close T1 (a compromised root of *that machine* could read it), and headless
servers are the MSP/managed case where J16's bulk enrollment is the real
answer later. Do not build the key-file shortcut.

---

## 7. Migration and unsigned sites (J48)

**J34's precedent holds: nothing converts.** Edge is the only user, and no
release has run tools as its people yet. A site that predates J14 simply has
**no pinned keys**.

- **An unsigned site runs as today** — the root asserts `subject`, the site
  obeys — and **says so.** Settings never lie: the site's page shows *"Policy
  on this machine is trusted to the root until someone adds a key here,"* with
  the pair action. This is the honest state for a site that has not paired.
- **The release gate (J29) is "no owner-run tools without the owner's key."**
  2b.2 (tools as each person) ships **disabled** on a site until the owner has
  pinned a key (J14a). 2b.3 (each person's own rules) needs each person's key.
  2b.4 (commands) needs J14b. Edge may carry the earlier slices unsigned, with
  the limit stated, because Troy is edge's only user (J29).
- **Old records replay unchanged.** Keys are additive state; nothing in the
  replicated log changes shape.

---

## 8. J14b's shape, built with commands (J47)

Designed now, built with 2b.4. Each call the person approves is signed, and the
site checks it — which is what finally makes "ask" a check the site makes
itself (`SH/host.py:337-341`'s "not available yet" goes away).

- **The signed object** is §5.1's envelope with `act: "call"` and `args` the
  tool call (`server`, `tool`, `arguments`). The site runs an **ask** tool only
  with a valid signature over the call; a **standing** (pre-approved) grant is
  itself a signed policy edit (J14a), so no per-call signature is needed for it.
- **The gesture cost is the open question, and it is Troy's (J47).** A passkey
  gesture per call is right for a destructive or command call (a forged one is
  the account) but heavy for a Claude-Code-like loop that reads and searches
  dozens of times a turn.
  - **Recommended:** sign **writes and commands per call** (per gesture, Path
    B; free and per-call on Path A's WebCrypto key), and let **reads/searches**
    run under a **short-lived signed capability** the person signs once ("these
    read tools, this workspace, N minutes"). The damage a forged read can do is
    bounded (it exfiltrates, it does not change the machine), and the capability
    is itself a signed, time-boxed, sequence-numbered object the site checks.
  - **Trade-off:** the capability window is a gap where a compromised Workbench
    (T2) could issue reads the person did not intend. Bounding it to reads, to
    one workspace, and to minutes is the mitigation; the alternative (a gesture
    for every read) closes the gap at a cost that makes the agent unusable.
- **Path A and calls:** a WebCrypto key signs calls with no gesture, but only a
  caller *at the machine* can use it, so J14b's strong, remote form is Path B.
  A person at the machine gets silent per-call signing for free.

---

## 9. Slices and done-when (J49)

**J14a — signed policy edits.** Built before owner-run sites ship (J29).
- the signed envelope and the site's verifier (`SH/`), vendored canonical-JSON
  Ed25519 + a WebAuthn-assertion verifier for Path B;
- Path A: the loopback page creates, pins (no code) and signs with a WebCrypto
  key; the pinned key stored beside the link, agent-written, site-host-read;
- Path B (where the entry point is set): a passkey in Workbench, pinned by a
  machine-shown code + MAC, Related-Origin-Requests across Workbench's names;
- the per-(site, person) sequence; the fresh-window reused;
- the owner signs owner edits; unsigned sites say so and refuse owner-run
  tools.

*Done when:*
- a policy edit with a signature by a key pinned at Amish_Station is applied,
  and the **same edit with the root's `subject` and no signature is refused**;
- a root that swaps the pinned public key in transit is caught (Path B, the
  MAC fails; Path A, nothing crossed the root);
- a replayed or reordered past edit (lower-or-equal `seq`) is refused;
- an unsigned site shows the honest state and refuses to run tools as its
  people;
- a person with two keys loses one and still signs with the other.

**J14b — signed calls.** Built with 2b.4 (commands).
- `act: "call"`, the write/command-per-gesture rule, the read capability;
- "ask" becomes a site-checked signature; standing grants ride on J14a.

*Done when:*
- a write or command runs only with a valid per-call signature, and a forged
  one (root-asserted, unsigned) is refused and audited;
- a read runs under a valid signed capability and is refused outside it;
- a command — the first tool that can run a program — cannot be forged by the
  root.

**Not built here, named:** OS-enforced confinement on Windows for people with
no account (J27's later hardening); a tailnet-named Workbench origin (§3.3) as
a wired path; bulk enrollment for headless/managed fleets (J16); showing the
person *what* a passkey signs (intrinsically impossible in the authenticator;
§1 T2's residual).

---

## 10. Calls

| # | Call | Recommendation |
|---|---|---|
| J39 | What J14a protects, J14b adds, what stays root-trusted | **T1 (forged intent) is closed by signatures; T2 (compromised Workbench) is only reduced, by a passkey; membership, revocation and availability stay the root's.** §1 |
| J40 | Where the private key lives | **Path A: a non-extractable WebCrypto key at the machine's loopback page. Path B: a passkey in the person's device, used from Workbench.** A software key in central Workbench's origin is rejected (the root serves that JS). §3.1 |
| J41 | Does running tools as each person require the HTTPS entry point? | **No — require only the owner's key, by Path A.** Remote signing (Path B) lights up when the entry point is set. Trade-off: a never-at-the-machine person on a LAN-only install cannot sign remotely until the entry point exists. §3.2 |
| J42 | A trusted certificate without the cloud or a per-device CA step | **Keep Path A as the floor (no cert needed); for Path B, document the local CA's per-device trust and support a tailnet-named, `tailscale`-certified Workbench as the no-per-device-step option.** Do not require a public cert. §3.3 |
| J43 | Pinning without the root substituting the key | **Path A pins at the machine with no code; Path B pins with a machine-shown code + MAC the site checks.** §4 |
| J44 | What is signed, and how the site checks it | **A canonical envelope binding site, enrolledAt, person, action, args, a per-(site,person) sequence and iat; verified against the key pinned for that person, not the root's `subject`.** Owner signs membership; each person signs their own rules; no-link people and Eugene's dev-mode owner hold no key. §5 |
| J45 | Lost or replaced keys | **Re-pair at the machine; several keys per person; grants a gone key signed persist; the owner can clear a person's keys at the machine.** §5.3 |
| J46 | Per-platform ceremony | **Windows service: the loopback page. Per-user: the join opens a loopback page. Headless Linux: a code from the one-liner, Path B only; unsigned until an entry point exists. No machine-held key-file shortcut.** §6 |
| J47 | J14b's gesture granularity | **Writes and commands per call; reads under a short-lived signed capability.** Trade-off: the read-capability window is a bounded T2 gap. §8 |
| J48 | Migration, and what an unsigned site does | **None (J34). An unsigned site runs root-trusted, says so, and is refused from running tools as its people.** §7 |
| J49 | Slices and done-when | **J14a first (gates the release); J14b with commands (2b.4).** §9 |

### 10.1 Troy's answers

**2026-10-06, by two standing principles.** Troy did not pick a path; he gave
two principles and asked them to decide it: *privacy and security of a user is
the project's top priority; ease of use is extremely important but must never
interfere with the first.*

The principles settle the path question, because **the paths are equally secure
against the threat J14 exists for.** Against a compromised root forging a
person's intent (T1), Path A and Path B are the same strength: the root holds
neither private key, and the site checks against a key pinned at the machine.
Path B's only security edge is against a compromised Workbench (T2), which it
merely *reduces* and J14 cannot close (§1). And Path B's low-friction setup —
a private CA trusted on each device — is itself a mild hazard, training users to
install custom certificate authorities. So security does not favour Path B, and
the one place ease-of-use could quietly weaken security is inside Path B.

- **J40 — both key types stand.** Kept as designed (§3.1).
- **J41 — do NOT require the HTTPS entry point for owner-run sites.** Path A (a
  key at the machine) is the **required floor**; Path B (a passkey from
  Workbench) is an **optional upgrade** where the entry point is already set.
  Principle 1: equal security, and Path A avoids Path B's certificate hazard.
  Principle 2: Path A needs no setup and no certificate; Path B adds remote
  convenience without ever being forced. Requiring the entry point would buy no
  security and spread the certificate burden to everyone.
- **J42 — never require a trusted/public certificate to use Job Sites.** Path A
  is the floor precisely so the feature works with no certificate at all. Where
  Path B is wanted, document the private-CA per-device trust honestly as the
  hazard it is, and prefer a tailnet-certified name where the user has one.
- **J47 — the strong, hardware, per-gesture signature is required for commands
  done *remotely*** (built with 2b.4). Sensitive actions at the machine work on
  any install (Path A); doing them from afar needs the front door and a passkey.
  This is principle 1 applied to the one tool whose forgery is the whole
  account.
- **J39, J43-J46, J48-J49 follow as recommended** under the same principles;
  none asks a security trade-off these principles decide differently. J44's rule
  — the site checks a signature against the key pinned for the person, never the
  root-asserted `subject` — is the core of principle 1 and is not optional.

**Not yet taken, flagged for Troy:** nothing blocks J14a. One related
security note principle 1 may want to revisit separately (not J14): on a
plain-HTTP LAN install the site's link to the root is unpinned and unencrypted,
and Workbench is not a secure context there at all. J14 works around it (Path A
on loopback), but it is a transport weakness worth its own look.

---

## 12. Building J14a: the slices, and the calls building made (J50-J54)

Started 2026-10-06. §9 named J14a as one slice; it is three, because each
needs a different ceremony and each must leave edge working:

- **J14a.1 — the site's check, and Path A on a Windows service install.**
  The site host verifies signed changes, holds unsigned ones, keeps a
  sequence per person, and refuses every tool until its owner's key has
  approved its rules (J48). The agent's loopback link page makes and pins
  the key and is where held changes are approved. Workbench and the root
  carry the new *held* answer. This is where Troy's own site lives.
- **J14a.2 — per-user installs** (Windows, Linux, macOS): the same pages,
  served to the one account the agent runs as, checked from the connection.
- **J14a.3 — Path B**: a passkey from Workbench, pinned with a code shown at
  the machine (§4.2). It is also the Linux system install's only path (J46).

**Until J14a.2 and J14a.3 land, a per-user or Linux system site on edge runs
no tools** (J48: an unsigned site refuses them, and says so). Troy is edge's
only user and his site is a Windows service install, which pairs in J14a.1.

### 12.1 The calls building made

**Troy agreed with all five as taken (2026-10-06, before J14a.1 landed).**

| # | Call | Taken | Trade-off |
|---|---|---|---|
| J50 | Where a Path A change is written and signed | **Written in Workbench as today; the site *holds* it; the person approves it at the machine**, on a loopback page that shows the change in the site host's own words and signs only there. Workbench is told *held, approve it at <machine>*, not *refused*. | A change needs a visit to the machine. The alternatives were an editor at the machine (a second editor to build and keep) and a change carried in a URL from Workbench (the person must be on that machine, and the page would show what root-served code put in the URL). |
| J51 | Changes that only take access away | **Need no signature**: removing a folder, turning a server off, a folder's or a server's list made smaller, dev mode turned off. They are applied at once and keep the rules approved. | A compromised root can take access away. It could already: availability is the root's (§1). Revocation from a phone stays instant, which matters more. |
| J52 | The rules made before the owner's first key | **Approved as a whole, at the machine, before any tool runs.** The site signs the digest of its whole policy; the page lists every rule. An empty policy needs nothing. | One extra approval at pairing. Without it, a grant a root forged before the key existed would outlive the key. |
| J53 | How a signed approval reaches the site host | **Over the site host's loopback API**, with a token it writes in its own data directory, which its starter reads. The signature, not the courier, is the authority: the same verifier will take Path B's approvals through the root. | One more loopback surface. The token keeps the list of held changes (folder paths, names) from other local accounts. |
| J54 | Names in a held change | **The root sends the names it knows with the change**, and the page marks them *as Eugene names them*; a linked person is named from the link, with the account. | A compromised root can mislabel a person it does not link. The page says which names it can vouch for. |

### 12.2 What J14a.1 signs and checks

The envelope of §5.1, with a type and version so the key's signature over it
can never be mistaken for anything else:

```
{"typ": "eugene-plexus/site-edit", "v": 1,
 "site": <site id>, "enrolledAt": <the enrollment's>,
 "person": <subject>, "key": <key id>,
 "act": <the action, or "rules.confirm">, "args": <its arguments>,
 "seq": <greater than the last this person's key signed here>,
 "iat": <unix seconds>}
```

Canonical JSON (`sort_keys`, no spaces, UTF-8) built by the site host, signed
by the page as given, and checked by the site host against its own record of
the held change: the bytes must be canonical, every field must match, `seq`
must be greater than the last accepted for that person, `iat` no older than
ten minutes, and the signature must verify with a key pinned to that person
in the links file. Keys are Ed25519, or ECDSA P-256 where a browser lacks
Ed25519; key id = the first 16 bytes of SHA-256 over the raw public key.

### 12.3 What building J14a.1 found

- **A policy file edited behind the site's back now runs nothing.** The
  approval is a digest of the whole policy, so a change written to
  `policy.json` by anything but the site host's own handlers (a restore, an
  old build, a hand edit) leaves the rules unapproved until the owner approves
  them at the machine. Before J14a such an edit simply took effect.
- **The owner's key lives on the owner's link.** Removing the owner's link
  removes their key, and the site becomes unsigned: no tool runs, a linked
  person's included. A test that said "a linked person is not held up by the
  owner's missing link" was rewritten to say the opposite, on purpose (J48).
- **A grant the server's own tool list refuses is refused before it is held.**
  Otherwise a destructive tool granted without a standing pre-approval would
  wait for the owner's approval and then fail.
- **Deploy order: the root first.** A J14a site host reports `signing` and
  link `keys`, and may answer `held`; a root older than J14a refuses all three
  (its contract is closed). A machine that updates before its root goes offline
  until the root updates. On Troy's install: the NAS container first, then
  Amish_Station.
- **The browser half was checked in the browser.** `j14a-browser-check.py`
  drives the system Chrome against the agent's own routes and page script and
  the site host's own app: an Ed25519 key, and a P-256 one with Ed25519 withheld,
  each made, pinned, and accepted by the site host's verifier; WebCrypto refuses
  to export the private half to the page's own script. What it cannot do
  unelevated is the Windows service install itself (the agent as LocalSystem
  reading the site host's token across accounts): that run is owed.

---

## 11. What this design does not cover

- **Single sign-on itself** (control#4). J14 is built so a passkey and a link
  survive Google/Microsoft sign-in (the key is bound to the person and the
  machine, not to a password), but SSO is its own work.
- **Showing the person what a passkey signs.** A WebAuthn authenticator does
  not display arbitrary content; this is T2's irreducible residual (§1).
- **OS-enforced confinement on Windows** for people with no account (J27).
- **Bulk/headless enrollment and key custody at scale** (J16, the MSP case).
- **A wired tailnet origin for Workbench** (§3.3); the entry point would accept
  the name, but nothing describes it yet.
- **TLS between machines on a LAN** (`remote-nodes.md` §7), unchanged.
