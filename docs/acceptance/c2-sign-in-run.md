# C2 acceptance: signing in with Eugene

**2026-10-01.** On the pins: control `b9f55d7`, agent `8da2fb4`, ui `1e8fbb8`
(dist `fa89cf1`). Design: [`../design/sign-in-with-eugene.md`](../design/sign-in-with-eugene.md).

| Run | Result |
| --- | --- |
| `scripts/c2-sign-in-acceptance.py`, a real OpenID Connect client (Authlib 1.8.0, the library Open WebUI uses) | **42 of 42**; in specs CI from this commit |
| `scripts/c2-browser-acceptance.py`, the system Chrome | **6 of 6** |
| `scripts/c2-sabotage.py` | **46 of 46 caught** (44 of 46 on the first pass; both escapes are below) |
| `c1-app-accounts.yml` on GitHub's Windows and Ubuntu runners, on the candidate pins | **42 of 42 on each** (run 36882831166) |
| Every script specs CI runs, locally, before the pin | **24 of 24** |

The acceptance run onboards a control root and an enrolled agent through
the API, registers an app the way the console does, and signs in through
the agent's `/oidc` the way a browser does: it opens the page, posts the
form, follows the redirect and trades the code with PKCE. It validates every
ID token itself, against the JWKS and the nonce.

## Before: the failing check

On the pins of the day (control `71aa23a`, agent `bd4f4e8`), the run stops
at check 10: the agent answers `/oidc/.well-known/openid-configuration`
with **404**. Nothing could sign anyone in with Eugene; the only way an app
could know who was using it was its own accounts.

## After

- **The provider is where the app is told it is** (10-14). Discovery at the
  agent's `/oidc` names that address as the issuer, ID tokens are RS256
  only, PKCE S256 is offered with the code flow and nothing else, and the
  JWKS holds one RSA key with a `kid`.
- **An app is registered once and its secret shown once** (20-21).
- **With nobody added, the page asks for Eugene's passphrase** (30-36). A
  wrong one stays on the page with no code. The ID token says the owner
  signed in; userinfo agrees; **the ID and access tokens each open nothing
  in the hub** (401 at the agent's `/v1/node` and `/v1/logs` and the control
  root's `/v1/nodes`; the refresh token likewise in control's unit tests); a
  code works once.
- **The protocol's guards** (40-43): a wrong PKCE verifier, a wrong client
  secret, a request with no PKCE challenge and an unregistered return
  address are each refused, the last as a page and never a redirect.
- **People** (50-59). Once someone is added, the page asks for a name. The
  list never shows a password or its verifier. A wrong password and an
  unknown name get the same answer. The owner still signs in as
  `operator`. A person limited to one app is refused another with a
  sentence and no code.
- **Taking it back** (60-67). A new password set by the owner ends the
  person's earlier sign-ins at their next refresh, and the old password no
  longer works. Turning a person off ends their sign-ins the same way, and
  the page tells them signing in is off for them. An app that revokes its
  refresh token ends that sign-in.
- **A person makes their password their own** (68-69) on the sign-in page,
  is signed in, and their sign-in from before the change does not refresh.
- **A sign-in is not a console session** (70).

## In Chrome

`c2-browser-acceptance.py` runs an agent that supervises the control root,
as on a real control host, and drives the system Chrome:

- **The sign-in page renders under its own CSP**, and posting the
  passphrase follows the redirect to the app with a code. Chrome applies
  `form-action` to that redirect, which is why the policy names the app's
  origin; the code traded for an ID token that names the owner.
- **On the People page** the sign-in address is the page's own address
  with `/oidc`, a person added by clicks appears in the list, and an app
  added there shows its secret once; "I have copied it" removes it from the
  page.
- **That person signs in from Chrome and changes their password on the
  sign-in page**; the code traded for an ID token with their id, and their
  `passwordChangedAt` moved.
- **No CSP violation, no page error, and no failed request** from the
  sign-in page or the People page.

## What the build found, each fixed

1. **D10 was not built.** The design says a person changes the password
   the owner gave them on the sign-in page; the first build had no way to.
   The page now offers it to people (not to the owner), and checks 68-69
   and three unit tests hold it.
2. **The control root never declared `python-multipart`.** Its sign-in
   page and token endpoint read form posts. Every install worked only
   because the gateway, in the same environment, declares it. Control's own
   test environment failed on it.
3. **A sentence that told the owner something untrue.** The sign-in page
   answered an owner who tried to change the passphrase there with "it is
   changed on the console". There is no way to change Eugene's passphrase
   anywhere yet; it says so now, and so does the contract (`4e6dadc`).
4. **A test that could not fail** (sabotage escape). The unit test for
   "the forwarded host is believed only beside an agent's token" forged a
   gateway token from a node that holds no gateway grant, which the token
   rules refuse before the provider looks. It now enrolls a node with the
   gateway grant and proves the token verifies, so only the provider's own
   check refuses it.
5. **A check that could not run** (sabotage escape). The route's own
   password-length check sat behind the contract's `minLength: 12`, which
   refuses first. It is deleted; a test holds the 422 on both routes.
6. **The light sign-in page's button was under the contrast minimum**
   (Chrome's screenshot): dark text on its blue was 3.9 to 1. It is white
   there now, and a test computes every text colour on the page against its
   background in both schemes.

## Found, not fixed

- **Next's segment prefetches 404 on every page of the export**, People's
  and every older one alike: the client asks for
  `people/__next.people.__PAGE__.txt` and the export writes
  `people/__next.people/__PAGE__.txt`. Pages load; the prefetch is wasted.
  Not C2's, and not looked into further.

## What this does not show

- **Open WebUI itself.** Authlib is its client library, used here
  unchanged; Open WebUI's own configuration is C4.
- **A registry app signing in end to end on a runner.** The agent's half
  (register at install, the secret file, the environment, systemd's
  `LoadCredential`) is unit-tested, and the C1 runners prove an app's unit
  still starts with the new credential line. No app in the catalogue signs
  people in yet; Workbench (C3) is the first. The runners ran with control
  `dc1b76b`; `b9f55d7` changes the sign-in page's colours only.
- **Two machines.** Every run is on one box. The issuer comes from the
  host the agent was reached at, so an app on another machine needs that
  machine's address for this one, or the root's `oidcIssuer` set.
- **Plain HTTP.** Passwords and codes cross the network in the clear
  unless the operator puts HTTPS in front (§7 of the design).
