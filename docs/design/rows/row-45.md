# Row 45: TLS for clients, next

Lane TRUST. **High risk** (certificates, a private key sent between
machines, a DNS credential). Sources: `tls-for-clients.md` §8 ("Not in
LT2") and §12 ("Not built, or not measured": built-in ACME, tailnet
certificates, narrowing the CA, rotating the CA; "a request-header deadline
on 8079 after hand-over is not built"), agent `client_tls.py` and
`client_doors.py`, `ClientTls` in `agent.yaml`.

## 1. What it delivers

Four parts, built and merged in this order (45a-45d on one branch):

- **45a. A header deadline on 8079.** A connection that has not sent its
  request line and headers within 10 seconds is closed, on TLS and plain,
  so a slow client cannot hold the console's connections.
- **45b. Tailscale's certificate, where a tailnet is present.** A machine
  on a tailnet offers "Use Tailscale's certificate for
  nas.tail1234.ts.net". One click, and browsers and API clients that open
  that name get a certificate every device already trusts: no CA to
  install.
- **45c. The owner's domain, renewed by Eugene.** On the Access page:
  "Use my domain", a DNS provider and its API token. The root gets a
  wildcard certificate for `*.home.example.com` by DNS-01, renews it, and
  gives it to every machine. Today the owner must bring PEM files and renew
  them by hand.
- **45d. Replace the install CA,** optionally narrower (fewer address
  ranges, extra names), with an overlap: the new CA is published first;
  machines switch to it when the owner says devices trust it.

## 2. Design

### 45a. The header deadline

- In `client_doors.py`, each accepted connection on 8079 (and the other
  client doors) starts a 10-second timer at accept; the timer stops when
  the first request's header block ends (`\r\n\r\n`, or the TLS hand-over
  plus that). On expiry the connection closes without a response and the
  door counts it (`ClientDoor.headerTimeouts`, a new counter).
- Loopback is exempt, as it is from the connection cap. A
  keep-alive connection's later requests are uvicorn's (it has its own
  idle timeout).

### 45b. Tailscale certificates (`ClientTlsSource: tailscale`)

- **Detect:** the agent asks the local Tailscale daemon (its LocalAPI
  socket, or `tailscale status --json` when the socket is not readable)
  for this machine's DNS name and whether the tailnet has HTTPS
  certificates on. Shown on the machine's Access page: "This machine is
  `nas.tail1234.ts.net` on your tailnet."
- **Offer, never automatic:** a tailnet certificate puts the machine's
  tailnet name in the public certificate-transparency logs. The switch
  says so: "Its name, nas.tail1234.ts.net, becomes public in certificate
  logs." Off until the owner turns it on, per machine (call R45-TAILNET).
- **Get and renew:** `tailscale cert` (LocalAPI `cert/<name>`) writes the
  certificate and key into the agent's data folder; the agent renews at
  two thirds of its life, as for the install leaf.
- **Serve by name:** the doors choose the certificate by SNI. The tailnet
  name gets the tailnet certificate; every other name (an IP, `.local`)
  keeps the install CA's leaf. So turning it on breaks nothing that worked.
- **When the tailnet has HTTPS off:** the switch is disabled with "Turn on
  HTTPS certificates in your tailnet's admin console (DNS page)", and a
  link.

### 45c. The owner's domain by DNS-01 (`ClientTlsSource: acme`)

- **Wrap, do not write:** Eugene runs `lego` (the ACME client with DNS
  modules for over 150 providers) as it runs engines: a pinned release
  from GitHub, checksum-checked, kept per platform. No DNS code of ours.
- **The setting (control, root only):** `acme`: `{domain, email,
  provider, credentials (sealed), staging: bool}`. The Access page lists
  the common providers (Cloudflare, Route 53, DigitalOcean, deSEC, DuckDNS,
  Porkbun, Gandi, OVH) with their fields, and "Another lego provider" with
  free environment fields for an expert. The token is sealed in the
  replicated set like provider keys, and never returned.
- **One wildcard, made on the root:** `*.home.example.com` and
  `home.example.com`. A wildcard keeps machine names out of the
  certificate logs. The root runs lego with the credentials in its
  environment, renews at two thirds, and keeps the certificate sealed.
- **To the machines:** each machine fetches it over the machine port (LT1,
  pinned) with its node token, `GET /v1/nodes/{name}/client-certificate`;
  the key travels sealed to the machine's identity key (the same sealing
  the standby's copies use). The machine serves it for SNI under the
  domain, and the install leaf for everything else.
- **Names:** each machine's name under the domain is
  `<machine label>.home.example.com` by default, editable per machine. The
  owner's LAN DNS must answer it with the machine's private address; the
  page checks from the machine (a lookup) and warns: "nas.home.example.com
  does not resolve to 192.168.16.252 from this machine. If your router
  blocks public names that point at private addresses (DNS rebinding
  protection), allow this domain."
- **Failures** name lego's words: "Let's Encrypt refused: too many
  certificates for this domain this week. Eugene tries again on 29 Oct."
  The machines keep the last good certificate until it expires.
- **Supplied PEM files stay** as the expert override (LT2-C1); a supplied
  certificate wins over `acme` on the machine it is set on.

### 45d. Replace the install CA

- **Make the next CA** (Access page, owner): optionally narrow the ranges
  and add dotless names before it is made (§3's "expert narrowing").
  The new CA is published beside the current one (`GET /v1/trust/ca`
  returns both, current first), and the console's trust page offers both.
- **Switch** when the owner presses "Machines now use the new CA": every
  machine asks for a new leaf from it at its next check (within a minute).
  Leaves from the old CA lapse within 90 days (LT2-C6); the owner can
  remove the old CA after the switch, which also stops the root serving it.
- The console shows, for the device it runs on, whether that device trusts
  each CA (its existing probe), so the owner sees readiness before the
  switch.

### Contract

- `agent.yaml`: `ClientTlsSource` gains `tailscale` and `acme`;
  `ClientTls` gains `tailnet` ({name, httpsEnabled, on}) and per-name
  certificates (`certificates`: [{names, source, notAfter}]); `ClientDoor`
  gains `headerTimeouts`.
- `control.yaml`: the `acme` settings (credentials write-only), the
  machine's client-certificate route, CA replacement (`POST
  /v1/trust/ca/next`, `POST /v1/trust/ca/switch`, `DELETE
  /v1/trust/ca/{id}`), and `GET /v1/trust/ca` listing both.

## 3. Repositories and files

specs (`agent.yaml`, `control.yaml`), agent (`client_doors.py`,
`client_tls.py`, a new `tailnet.py`, the lego wrapper beside the engine
acquisition code), control (`install_ca.py`, sealed `acme` settings, the
renew loop, the new routes), ui (the Access page, the trust page).
Regenerate every consumer and diff.

## 4. Tests that fail before

- agent `test_client_doors.py::test_a_silent_connection_is_closed_after_10_seconds`
  and `test_loopback_is_exempt` (the test shortens the deadline).
- agent `test_tailnet.py::test_the_tailnet_name_is_served_its_own_certificate_by_sni`
  (a fake LocalAPI) and `test_https_off_disables_the_switch_with_the_reason`.
- control `test_acme.py::test_the_wildcard_is_requested_with_the_providers_environment`
  (a fake lego binary that records its arguments and environment) and
  `test_the_token_is_never_returned`.
- control `test_install_ca.py::test_a_next_ca_is_published_beside_the_current`
  and `test_switch_issues_leaves_from_the_new_ca`.

## 5. Acceptance (CI, Linux and Windows, about 6 minutes)

`specs/scripts/row45-tls-next-acceptance.py` on row 2's harness, with a
root and one worker:
1. **Deadline:** a socket that sends half a request line is closed after
   the (shortened) deadline; the console still answers others.
2. **Tailnet:** a fake LocalAPI reports a name; turned on, an `openssl
   s_client -servername <tailnet name>` sees the tailnet certificate and
   `-servername <IP>` the install leaf.
3. **ACME:** Pebble (Let's Encrypt's test ACME server) with its fake DNS
   (`pebble-challtestsrv`) and lego's `exec` provider: the root obtains the
   wildcard, the worker fetches it over the machine port, and both serve
   it by SNI; the token appears in no response and no log line.
4. **CA replacement:** the next CA is published; after the switch the
   worker's leaf chains to it; the old CA is removed.
5. **Sabotage:** serve the tailnet certificate for every name; step 2's IP
   check must fail.

**The reviewer should attack:** the wildcard key's path to machines
(sealing, a machine that was removed, a node token for another machine),
the DNS token's custody (logs, responses, lego's own files and cache),
SNI selection with odd names, a CA switch that strands machines, and the
deadline's effect on slow but honest clients.

## 6. Do not change

- The machine port and LT1 pins (`machine_port.py`, `machine_trust.py`),
  and row 3's key-change files.
- control `oidc.py`, `sealing.py` beyond calling it (row 5).

## 7. Size and risks

L (the roadmap said M), about 4 days, in lane TRUST after rows 4, 5, 36
and 39. One adversarial review after 45c.

Risks:
- **A wildcard key on every machine:** a stolen machine leaks a key good
  for the whole domain until it expires. The owner may give machines
  their own names instead (one certificate each, names in the logs); the
  page says so. Call R45-WILDCARD.
- **A DNS token can change the owner's whole zone** with most providers.
  The page asks for a token limited to one zone where the provider allows
  it, and says so.
- **Rate limits** at Let's Encrypt: the staging switch for trying it
  first, and renewal at two thirds leaves a month of retries.

**Calls:** R45-TAILNET (tailnet certificates offered, off until turned on,
because the name becomes public) and R45-WILDCARD (one wildcard for every
machine rather than one certificate per machine).
