# TLS for clients and browsers (LT2)

**Status: designed 2026-10-20. Troy took every call as recommended the same
day: LT2-C1 the install CA by default with supplied PEM as the override, LT2-C2
private addresses and local suffixes only, LT2-C3 the existing doors, LT2-C4
plain off by the owner, LT2-C5 sign-in follows the page.**

LT2 is the second half of [TLS between machines](tls-between-machines.md)
(§2, §3.9, LT-C4). LT1 encrypted traffic inside the install, where Eugene holds
both ends and pins its own keys. LT2 encrypts traffic into the install: a
person's browser, Claude Code, Open WebUI or a script talking to the console,
the gateway or an app. Those clients cannot pin a node key. They need a
certificate they already trust.

It is built on branch `lt1`, on top of LT1, and the whole branch merges once.

The facts below were read from the code on 2026-10-20 at these heads:
- agent `a4d461c` (branch `lt1`)
- control `53b9730` (`lt1`)
- gateway `dd0ef74` (`lt1`)
- ui `a573be2a` (`lt1`)
- workbench `a1f6151` (`main`)

Path prefixes as in `tls-between-machines.md`, plus `W/` for workbench.

## 1. What a client sends in clear text today

On a plain install (Windows, Linux or macOS, no container), every door a
client uses is plain HTTP once the node advertises a LAN address:

| Door | Process | Bind | Decided at |
| --- | --- | --- | --- |
| Console, 8079 | the agent | `0.0.0.0` when the advertise host is not loopback | `A/node_identity.py:303-307`, `A/__main__.py:251-288` |
| Gateway, 8080 | the gateway | `0.0.0.0` the same way (`BIND_HOST`) | `A/app.py:968-972`, `G/__main__.py:62-65` |
| Apps (Workbench), from 8190 | the app | the agent's `BIND_HOST` | `A/apps.py:1063-1065` |

**What crosses:**
- every prompt and answer from a client on another machine to the gateway;
- client keys (`Authorization: Bearer`) on every gateway request;
- the console passphrase at sign-in, and session cookies afterwards;
- Workbench sign-in through `/oidc` (issuer `http://<host>:8079/oidc`,
  `A/app.py:798-804`) and its session cookie.

**HTTPS exists only in the container.** The agent supervises a bundled Caddy
(`docker/Dockerfile:64-76`) with an internal CA, ACME by TLS-ALPN on 443, or
supplied PEM files (`A/entrypoint.py:207-325,786-820`). It is refused on
anything but a Linux container (`A/entrypoint_setup.py:71-80`,
`A/entrypoint.py:1159-1160`), and no installer ships Caddy.

**No product code issues certificates.** The only certificate builder in
`src/` is LT1's self-signed machine certificate
(`A/node_identity.py:319-353`).

## 2. Where the certificate comes from (LT2-C1)

| | **Eugene's own CA** | **The owner's domain** (ACME or supplied) |
| --- | --- | --- |
| Needs | nothing outside the LAN | a domain, a DNS provider API token (DNS-01, since a LAN door can't answer HTTP-01 or TLS-ALPN), and LAN DNS that answers the name with a private address |
| Per device | trust the CA once: a GUI step on Windows and macOS, two on iOS (profile, then the trust switch), one on Android, where only Chrome honours it, not other apps | nothing |
| Per API client | Claude Code: nothing once the OS trusts it (native installs read the OS store by default). Python (`openai`, `requests`, httpx) and Open WebUI read certifi, not the OS: they need `SSL_CERT_FILE` or `REQUESTS_CA_BUNDLE` | nothing |
| Addresses | IPs, `<host>.local`, `.home.arpa`, `.internal`: whatever the leaf names | DNS names under the domain only; no IPs, no `.local` |
| Renewal | Eugene issues and renews leaves itself, offline | every 45-90 days over the internet (Let's Encrypt: 64-day default from 2027-02-10, 45 days from 2028-02-16) |
| Traps | a CA in a device's trust store can sign for any name unless name-constrained; its key must be held and replicated sealed | routers with DNS-rebinding protection (dnsmasq/OpenWrt, Unbound's `private-address`, many ISP boxes) drop public answers that point at private addresses; certificate-transparency logs publish the names unless the certificate is a wildcard |
| Who it suits | every install, including one with no domain and no internet | a business or a homelabber who already runs a domain and DNS |

**Recommended: Eugene's CA as the default, and the owner's certificate as the
expert override that replaces it.**
- The CA is the only option that works on every install with nothing outside
  it, which is the "easy default" rule. A novice has no domain.
- An MSP pushes a CA to every managed device by policy (GPO, Intune, MDM) in
  one step; that is how businesses already trust their own services.
- The owner's certificate costs nothing per device and is better wherever a
  domain exists, so it stays one setting away, as supplied PEM files on the
  same page (any certbot, acme.sh or reverse-proxy-managed certificate).
  Built-in DNS-01 ACME is later (§8): every DNS provider needs its own API
  module.

**The main trade-off:** the CA needs a trust step on each device, and an extra
variable in each Python-based client, before that device's traffic is
encrypted. Until then those clients keep using plain HTTP, so plain stays on
until the owner turns it off (LT2-C4).

**Rejected:**
- *A Eugene-run DNS and certificate service* (the `plex.direct` model: a
  wildcard under our domain per install). Nothing per device, but a service of
  ours in every install's name resolution and certificate issuance, against
  the "no cloud service in the path" commitment, with rate limits and running
  costs.
- *Self-signed certificates per node*: a trust step per node per device, and
  again whenever a node's address changes.

## 3. The install CA

- **Made by control on the root**, once, when LT2 starts. ECDSA P-256. Subject
  `Eugene Plexus <install label> CA`, valid 20 years.
- **Held sealed in the replicated set,** like the other sealed key material
  (X1 in `tls-between-machines.md` §1), so a promoted standby can issue. This
  is the cost §3.2 of the LT1 doc avoided; LT2 cannot, because clients cannot
  pin.
- **Name-constrained (LT2-C2).** Permitted subtrees:
  - IP: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`
    (tailnets and CGNAT), `127.0.0.0/8`, `fc00::/7`, `fe80::/10`, `::1`;
  - DNS: `local`, `home.arpa`, `internal`, `lan`, `localhost`.

  With the key stolen, a forger can then sign only for private addresses and
  local names, not for `bank.com`. A dotless name (`amish-station`) cannot be
  permitted without permitting it by name at the CA's birth, so Eugene's URLs
  use the IP or `<host>.local`. An expert may narrow the ranges or add names
  before the CA is made.
- **Its certificate is public.** Served by control (`GET /v1/trust/ca`, PEM
  and DER) and by every agent's console, so a device can fetch it from any
  node it can reach.

## 4. Each node's certificate

- **One leaf per node, for the TLS key LT1 already made** (`node.yaml`
  `tls_private_key`). The machine port keeps its self-signed certificate:
  pins are of the key, so LT1 is unaffected, and one TLS key per node is
  enough.
- **Issued by control on request,** over the machine port, with the node's
  token: `POST /v1/nodes/{name}/certificate` with a CSR for that key.
  Control signs only names that are the node's own:
  - the advertise host from its signed announcement (an IP or a name);
  - `<node name>.local`;
  - `localhost`, `127.0.0.1`, `::1`;
  - names the owner listed for that node.

  It refuses a CSR for another key, so a node cannot obtain a certificate for
  a key it does not hold.
- **Valid 90 days (397 as designed; LT2-C6), renewed at two thirds,** and re-issued as soon as the
  node announces a new address (DHCP).
- **The root issues its own** from the same CA, in process.
- **Kept on disk** beside `node.yaml`, so the doors keep serving with the
  root down.

## 5. The doors: TLS and plain HTTP on the same ports (LT2-C3)

**No new ports.** Each client door takes both, told apart by the first byte as
the machine port does (`A/machine_port.py:531`):

| Door | TLS branch | Plain branch |
| --- | --- | --- |
| 8079, console | the agent's app, served in process with the real peer (as `/agent` on the machine port) | the same app, as today |
| 8080, gateway | terminated in the agent, then piped to the gateway on a loopback port (the gateway never reads the peer address) | piped as today |
| Each app's port | terminated in the agent, then forwarded with the proxy metadata the container entry point already gives Workbench (`EUGENE_PLEXUS_APP_PUBLIC_ORIGIN`, the per-process request secret) | as today |

- **The agent owns the front.** The machine port's switch, caps and pumps are
  generalised into one front per door. The gateway and apps move to loopback
  ports behind it, as control did behind 8083.
- **The certificate is reloaded in place** when the leaf is renewed or the
  owner supplies a new one; connections stay open.
- **The container's Caddy entry point stays.** Its internal CA becomes the
  install CA (Caddy loads the leaf as supplied files), so a person trusts one
  CA, not two.

## 6. What a person sees

**In a browser:**
- A console page opened over `http://` probes `https://` on the same host and
  port. If the device trusts the CA, the probe succeeds and the page moves to
  `https://` by itself.
- If it does not, the page says so in one line: *"This connection isn't
  encrypted. Trust Eugene on this device."* That opens a page with the CA to
  download and the steps for this device's OS, detected from the browser.
- Machines, or a new Access page, lists the doors and how many requests each
  took in clear text in the last 7 days, by client address.

**For API clients:** "Connect a client" shows the `https://` base URL and the
client's own extra step:
- Claude Code: none once the OS trusts the CA;
- Python and the OpenAI SDK: `SSL_CERT_FILE` pointing at a bundle (certifi
  plus the CA), downloadable from the same page;
- Open WebUI installed by Eugene's catalogue: the agent sets its variables
  and mounts the bundle itself.

**When the owner's certificate is supplied,** the trust page and the extra
steps disappear, and the URLs use the owner's names.

## 7. Plain HTTP for clients, and sign-in

**Plain stays on until the owner turns it off (LT2-C4).** Unlike LT1's
"required", Eugene cannot know that every device trusts the CA. Turning plain
off is the owner's switch on the Access page:
- it is offered once no client has used plain HTTP for 7 days;
- with it on, a plain request from another machine gets a refusal naming the
  `https://` URL; loopback stays plain (the `/link` pages need it);
- a new install starts with plain on, for the same reason.

**Sign-in follows the page (LT2-C5).**
- Today the issuer comes from the request (`C/routes/oidc.py:77-87`), and
  cookies take `__Secure-` / `__Host-` and `Secure` only over HTTPS
  (`C/external_sign_in.py:244-261`, `W/sessions.py:74`).
- A Workbench page over `https://` signs in through the `https://` issuer, and
  one over `http://` through the `http://` issuer, so a password is never
  typed over plain HTTP on a page that had TLS.
- The agent registers both origins' callbacks for each app, and moves them at
  boot as it already does (`A/sign_in_refresh.py`).
- With plain off, only the `https://` callbacks remain.

## 8. Not in LT2

- **Built-in ACME by DNS-01.** It needs a module per DNS provider. Supplied
  PEM files cover anyone who runs certbot, acme.sh or a proxy that renews.
- **Tailnet certificates** (`tailscale cert`, a public certificate for
  `<machine>.<tailnet>.ts.net` at no cost). A good automatic option where a
  tailnet is present: a later slice.
- **Passkeys.** They need an HTTPS DNS name the device trusts
  (`person-held-keys.md` §2.2). LT2 gives them that with `<host>.local` and
  the CA, or with the owner's names.

## 9. Slices

| Slice | What | Risk |
| --- | --- | --- |
| **LT2a** | The CA (sealed, replicated, name-constrained), leaf issuance and renewal, `GET /v1/trust/ca`, the fronts on 8079, 8080 and app ports serving TLS beside plain, the console's probe and trust page | High (a CA, key custody, transport) |
| **LT2b** | Sign-in over HTTPS (both callbacks, per-page issuer), "Connect a client" and Open WebUI's bundle, the supplied-certificate override, the Caddy entry point on the install CA, plain off | High (auth) |

## 10. Acceptance

The Docker pair from LT1, plus a client container on the same bridge:
- **The canary check:** the client trusts the CA (its own trust store, no
  verification flag) and sends a prompt with a canary to the root's gateway on
  8080 over `https://`. The canary, `Bearer` and `eyJ` are in no capture.
  The check fails before LT2 (the client used `http://`).
- **A browser:** headless Chromium with the CA in its NSS store signs in to the
  console and to Workbench over `https://`; the passphrase is in no capture.
- **Sabotage, with `--labels`:**
  - a leaf for an address the node doesn't hold is refused by control;
  - a CSR for another key is refused;
  - with plain off, a plain request from the client container is refused;
  - a forged leaf for a public name, signed by the CA, is refused by the
    client (the name constraint holds).
- **Windows:** the worker check, plus the CA trusted in the current user's
  store and Edge reaching the console over `https://`.

## 11. Calls for Troy

| # | Question | Recommended |
| --- | --- | --- |
| LT2-C1 | Where does a client's certificate come from on a plain install? (LT-C4's first decision) | **Taken: Eugene's own CA by default, the owner's certificate (supplied PEM) as the override.** The CA works with nothing outside the LAN and an MSP pushes it by policy; it costs a trust step per device and a variable per Python client. The owner's domain costs nothing per device but needs a domain, a DNS API token and LAN DNS that survives rebinding protection. |
| LT2-C2 | What may the CA sign for? | **Taken: private addresses and local suffixes only** (§3), so a stolen key cannot forge public names; Eugene's URLs use IPs or `<host>.local`, not dotless names. |
| LT2-C3 | New HTTPS ports, or TLS on the existing doors? | **Taken: the existing doors**, told apart by the first byte as 8083 does. No new port to publish or proxy. |
| LT2-C4 | When is plain HTTP for clients turned off? | **Taken: by the owner, offered once no client has used it for 7 days.** Never automatically: Eugene can't know every device trusts the CA. |
| LT2-C5 | Which issuer does sign-in use during the switch? | **Taken: the page's own**: `https://` pages sign in over `https://`, so a password never goes plain from a page that had TLS. |

## 12. What building found

Built on `lt1`, 2026-10-20. The check of record is
`scripts/lt2-client-tls-acceptance.py` (§10), on the LT1 Docker pair.

### 12.1 LT2a

**Decisions made while building.**
- **TLS ends on the connection itself, in the agent.** A door reads a
  connection's first bytes; a handshake gets asyncio's `SSLProtocol` over the
  same transport (`client_doors`), a plain request the inner protocol
  directly. On 8079 that inner protocol is uvicorn's own (`Config.http`), so
  the agent's one server serves both branches: the app sees the real socket,
  the real peer and `scheme: https`, `/link` still reads the caller's own
  loopback socket (LT1 §7.2's first trap does not arise), and no hop strips
  or sets headers. The design's "served in process with the real peer" holds
  with no loopback hop at all. LT1's machine port keeps its own front.
- **The gateway keeps its topology URL.** Its door holds the published port
  (8080) and the gateway is spawned on a loopback port of its own
  (`BIND_PORT`), so nothing that names the gateway changes: its advertised
  address, the URL apps are given, the supervisor's health check. The door
  opens before any child starts. If 8080 is held by something else, the
  gateway binds it itself, plain only, as before.
- **An app knows the page's scheme from the port a connection arrives at.**
  Each app gets two loopback ports behind its door: plain, and one for TLS
  connections, decrypted (`EUGENE_PLEXUS_APP_TLS_PORT`). Workbench has no
  per-process request secret to carry a forwarded scheme (§5 assumed one);
  a port is the socket's own and nothing a caller sends can choose it. An
  app that does not listen on the second port gets its TLS connections at
  the first. `{port}` and `{bindHost}` in a manifest name the loopback port.
- **Plain use is counted by connection, not request.** The pump on 8080 and
  app ports sees connections only; one carries many requests. Counted per
  door and client address for 7 days (`client_plain.json`).
- **This machine is never "another machine".** Loopback, or a connection
  whose source is the address it arrived at: a process on the root that
  opens its own console at the LAN address was counted, and would have been
  refused once plain is off (found by the check's door counts).
- **The CA is a log op, `setInstallCa`, not a config field** (LT1 used
  `patchConfig` for `machineEncryption` so an older standby would not stop).
  A config value would have put the sealed key in `control.yaml` and
  `GET /v1/config`. An older standby stops on the op until it is updated;
  LT2 ships with LT1, and every node updates together.
- **The node's CSR names nothing**; control signs every name of the node's
  own that the CA may sign for. The agent never has to know the
  constraints, and asks again when its advertise address changes
  (`issuedFor`), not when a name is missing: a public address is never in
  the leaf and would have asked every minute. A CSR that does name something
  is checked name by name, and one name that is not the node's refuses the
  whole request.
- **The CA's subject names the install** (`Eugene Plexus install <6 hex of
  the control identity> CA`), so two installs' CAs are told apart in one
  trust store. A leaf's CN is its first DNS name, or empty with a critical
  SAN.
- **Connections are capped by transport, not by protocol:** uvicorn swaps
  the protocol on a WebSocket upgrade, and a count kept by the protocol
  leaked. Loopback has no per-address cap.
- **The plain-off switch waits for every machine to answer** before it is
  offered (the UI), not only for the ones that did to show no plain use.

**Found by the check.**
- **The leaf took a minute to arrive after a node joined:** the loop looked
  every 60 s whatever it held. It looks every 15 s until it holds one.
- **Playwright 1.48's `--with-deps` names Debian 12 packages**; the check's
  image is `python:3.12-slim-bookworm`.
- The forged-leaf label proves the constraint on today's clients: curl
  (OpenSSL 3) refuses a CA-signed leaf for a public name with "permitted
  subtree violation", Chromium with `ERR_CERT_INVALID`; the same forgery for
  a private address is accepted by both, so it is the constraint that
  refuses the first.

**Run of record for LT2a** (2026-10-20, `run5`): every check and all four
labels pass.

### 12.2 LT2b

**Decisions made while building.**
- **Sign-in follows the page with two providers in Workbench.** The issuer
  the agent hands Workbench is `http://<host>:8079/oidc`; behind its door,
  Workbench also builds the same issuer over `https://` and an https page
  (the TLS loopback port) signs in through it. A refresh or a revocation
  goes to the provider whose issuer issued the token (the token's `iss`,
  read only to choose; that provider then verifies strictly). Control
  re-issues a refresh under the token's own issuer whatever endpoint it
  came through, so neither side had to change how tokens are bound.
- **The console needed no change for LT2-C5**: the agent's `/oidc` forward
  already passes the page's scheme, and on 8079 the scheme is the
  connection's own.
- **Both return addresses per app.** Each app behind a door registers an
  `https://` return address beside each `http://` one; from another
  machine, only `https://` once plain is off (loopback stays plain). The
  addresses move again (`sign_in_refresh`) when the root's list turns
  plain off or on. The console opens an app at `http://` while plain is on
  (the first address), and at `https://` once it is off.
- **Apps trust the CA through `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`**: a
  bundle of certifi's roots, any bundle the agent was already given (the
  container's), and the install CA. Python's ssl, httpx and requests all
  read them. Apps read them at start, so running apps restart once when a
  CA this node did not hold arrives: once in an install's life.
- **An app on a machine with no gateway reaches the owner's console over
  `https://`** once this node holds the CA (it is handed
  `<owner>/api/proxy/gateway`). While the install does not require
  encryption between machines, the door is tried first and an older
  machine stays plain; once it requires it, https with no probe, so
  nobody in the middle can turn an app's traffic plain by blocking TLS.
- **Owner-listed names** (§4) are a node field set by an operator with the
  membership capability (`PUT /v1/nodes/{name}/certificate-names`, a
  `setNodeCertificateNames` entry), checked at the writer: only names the
  CA may sign, and none another node holds or lists. The Access page edits
  them.
- **The container's Caddy on the install CA.** Applying a setup with its
  own CA lists the setup's names at the root with the operator's own
  session; once this node's leaf holds every one, Caddy loads it as files
  (`client_tls.crt`, `client_tls.key`) and makes no CA of its own. Until
  then, and for a name the install CA may not sign, Caddy keeps its own,
  as before. The agent's own clients trust the install CA as soon as it
  holds a leaf.
- **The owner's own certificate** is two node settings,
  `clientCertificateFile` and `clientKeyFile`, read again within a minute
  of either file changing (certbot, acme.sh, a proxy's renewals). A pair
  that does not load is said in `clientTls.error` and the install's leaf
  comes back. `clientTls.source` says which is presented; with `supplied`,
  Connect hides the trust steps.

**Not built, or not measured.**
- **Built-in ACME (DNS-01) and tailnet certificates** (§8).
- **An expert narrowing the CA's ranges before it is made** (§3): the CA
  is made at the first unseal with the fixed set; nothing narrows it.
- **Rotating the CA**: made once, by design; a stolen key forges only
  private names (the check's forged-leaf label).

### 12.3 The adversarial review of LT1 and LT2 (2026-10-20), and what changed

- **A node could be issued a certificate for another machine's address**
  (blocker). Nothing stopped a node whose keys were stolen announcing the
  root's address; issuance trusted the announced host, and the machine
  tables keyed routes by agent address, so the same move also took over
  the root's LT1 route. Now: enrolment and announcement refuse another
  node's address (same origin), its `.local` name or a name listed for it
  (409, asked again later, so a DHCP shuffle settles once the other
  machine announces); the same address on another port (two agents on
  one machine) is let in, and then no leaf names it, because a leaf never
  holds a name another node holds; a shared agent address, or one equal
  to the root's, is carried for nobody in either machine table.
- **Only plain hostname labels are signed** (no `*`, no `_`).
- **The CA is downloaded over plain HTTP**, so someone in the path could
  swap in a CA of their own. The console shows the CA's SHA-256
  fingerprint and Windows thumbprint where they cannot be changed (the
  Access page, signed in over https; `/trust` on a secure page), and a
  plain page says where to compare before installing. The first trust is
  still the person's to check; that is the residual risk of LT2-C1.
- **The bundle served to devices carried the container's own CA**, which
  has no name constraint and keeps its key on disk. The served bundle is
  certifi's roots and the install CA only; the container's CA stays in
  this machine's apps' bundle.
- **Leaves lived 397 days** with no revocation, so a revoked or moved
  machine's leaf stayed good for its old address for a year. 90 days,
  renewed at 60 (call LT2-C6, below).
- **The LAN could fill the connection cap** that loopback shared. Loopback
  is not counted, and an IPv6 /64 is one address. A request-header
  deadline on 8079 after hand-over is not built (uvicorn has none; 8079
  had no cap at all before LT2).
- **An https page could be served as plain during an app restart** (the
  TLS port refused, the connection fell back to the plain port). Once an
  app has answered on its TLS port, a TLS connection is never carried to
  the plain one.
- **The plain refusal echoed the `Host` header**: a malformed one is
  dropped, and an IPv6 address is bracketed.
- **The agent and control disagreed on which names may be signed**: the
  agent now uses control's ranges and labels.
- **Not changed, recorded:** with the owner's own certificate and machine
  encryption required, an app on another machine reaches the gateway's
  console by its address, and the owner's certificate must name it; the
  console's probe line still offers "Trust Eugene" on a page opened by an
  address the owner's certificate does not name.
- **Found safe:** CA key custody (sealed op, memory only, cleared with
  the master key, never logged or returned); CSR and SAN handling; the
  constraint encoding; "this machine" from the real socket; loopback
  trust through the pumps (no pumped child reads a peer); Workbench's
  scheme by port, cookie names and issuer choice; the operator's header
  forwarded only to the enrolled root; plain-off decided per connection.

### 12.4 The branch's one set of checks (2026-10-20)

On the final code of `lt1` (LT1 and LT2), after the review's fixes:
- **Suites:** agent 2715 passed (one test listing settings fixed after the
  run, rerun); control, Workbench and the UI passed but for load-timing
  flakes that pass alone (control 626, Workbench 2414, UI 2273).
- **LT1 Docker pair:** `--labels bad-signature,wrong-pin,root-stopped,
  removed-machine`, then `--labels automatic`: every check passes.
- **LT2 Docker pair** (`ep-lt2:7e558d71bb9a7bd7`): every check and all four
  labels pass, Workbench's https sign-in included.
- **Windows** (`lt1-windows-worker-check.py --lt2`): the worker joins over
  TLS, its leaf names `192.168.16.75` and `windows-worker.local`, Edge with
  the CA in the current user's Root store opens the worker's and the root's
  consoles over https, the wire is TLS only; the CA was removed after.
- **CI** on `lt1` in all ten repos (specs with every component's `lt1` head
  as its candidate).

## 13. Calls for Troy (from building)

| # | Question | Taken by default |
| --- | --- | --- |
| LT2-C6 | How long is a node's leaf valid? (§4 said 397 days.) | **90 days, renewed at 60.** Renewal is automatic and offline, so a shorter life costs nothing while the root is up; a revoked or moved machine's leaf lapses within 90 days instead of 397. The trade-off: with the root down for more than 30 days past a renewal, clients see an expired certificate on that node until the root is back. 397 is one constant to put back. |
