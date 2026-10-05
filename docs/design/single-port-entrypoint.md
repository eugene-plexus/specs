# One HTTPS entry point for the container

Approved by Troy, 2026-10-04. This supersedes the requirement for a separate
published Workbench port in `apps-and-spokes.md`; separate browser origins remain
required. Existing containers retain their current ports until explicitly migrated.

The agent supervises a pinned, unmodified Caddy distribution. A startup JSON file
selects the HTTPS listener, exact service origins, TLS certificate source and an
independent source-network allowlist for each service. The file is
`entrypoint.json` beside `agent.yaml` (`/data/entrypoint.json` in the image),
read only where the bundled proxy exists, or the path in
`EUGENE_PLEXUS_AGENT_ENTRYPOINT_CONFIG`; its presence is the opt-in. Agent,
components and apps bind loopback in this mode, **except the control root's own
port when the node hostname is not configured** (2026-10-05): enrolled machines
know the root by that address, its port takes only signed and authenticated
calls, as before, and moving it behind the entry point meant editing every
machine's `node.yaml` by hand. With the node hostname configured, the control
root binds loopback too and machines use that name. No arbitrary
upstream URL, wildcard hostname, caller-selected target or inferred public address
is accepted. Unknown hosts fail closed, and TLS SNI must match the HTTP hostname.

The console and Workbench have different hostnames. The console's `/oidc/*` routes
use Workbench's network policy so members can sign in without gaining access to
the console. Console administration, inference and node enrollment each have
separate explicit network policies; nothing becomes public merely because
Workbench is public. Backend authentication and per-person node/folder grants
still apply. Hostnames never identify users, roles or MSP tenants. Separate
customer installations remain the isolation boundary.

The proxy removes incoming forwarding and Eugene internal peer headers and writes
its own metadata. The agent accepts proxy metadata only from loopback with a
per-process secret that is not passed to apps. Other requests retain their real
socket peer. Hostnames and callback addresses come from configuration, never from
forwarding headers. Caddy's management API uses a private Unix socket. Request
headers, bodies and read times are bounded; response streaming remains supported.

Workbench receives these additional startup variables from the agent:

* `EUGENE_PLEXUS_APP_PUBLIC_ORIGIN`: canonical HTTPS browser origin. Used for exact
  Origin checks and callback URLs. Cookies remain host-only, Secure and HttpOnly;
  HTTPS cookies use the `__Host-` prefix. The request secret remains mandatory.
* `EUGENE_PLEXUS_APP_OIDC_BACKCHANNEL`: an explicitly configured loopback `/oidc`
  transport for this container. Only URLs under the configured public issuer can
  be translated to it. Discovery and JWT issuer validation still require the
  canonical public issuer. Browser authorization URLs stay public. This avoids
  hairpin NAT and distributing a proxy credential or TLS private key to apps.

When an app's origin changes, **the agent moves its exact registered callbacks
at boot**, with its own node token (Troy, 2026-10-05; until then this needed an
operator Restart from a console the move had just made harder to reach). The
control root accepts a node's own token only on
`PUT /v1/oidc/clients/{id}/redirect-uris`, only for clients named
`app:<id>@<that node>`, and changes nothing but the redirect URIs: the same client
id and secret, so sign-ins and chats are kept. The node gains nothing by it: it
runs those apps and holds their client secrets, so every sign-in to them already
passes through it. An operator Start/Restart moves a stale client the same way,
and registers a new one only for a client the root no longer has. New
installations register the public callback immediately. Going back to the direct
ports moves the callbacks back the same way.

Caddy's configuration is regenerated from installed service records, including
Workbench's actual assigned port. Uninstalled or disabled Workbench returns 503,
never another app that later occupies the port. Reloads preserve active streams.
Before replacing the app, its public route is removed synchronously. A new process
is published only after its health response confirms the configured public origin
and origin-isolation capability; rolling back to an older build stays unavailable.
An invalid startup configuration file is fatal in this opt-in mode, never a
fallback to the direct listeners. A variable naming a file that does not exist
falls back to the direct ports with a warning in the log and on `/healthz`
(Troy, 2026-10-04, after the first live migration: a missing file crash-looped the
container and left no console to repair it from). The direct ports are reachable
only where the owner still publishes them. Proxy failure does not widen backend
bindings.

Home installations may use Caddy's internal CA, explicitly trusting its public
root on their browsers and nodes. Businesses should supply certificates from
their managed CA or a publicly trusted CA. TLS verification is never disabled.
The local CA is provisioned before child processes start. Internal Python clients
trust the OS certificate store and explicit certificate bundles. The control root
reaches its own supervising agent through an exact configured loopback transport
mapping, preserving the original node credential and audience.
Direct mode uses the socket client's address for CIDR policy. An explicit proxy
mode accepts only individually configured proxy IPs, requires HTTPS forwarding
metadata, and uses Caddy's strict right-to-left client-IP parsing. Missing,
invalid or proxy-only client addresses are refused rather than inheriting the
proxy's network privileges. Proxy mode can use private HTTP on an isolated
same-host Docker network, or supplied TLS certificates across machines. It never
changes public HTTPS origins, cookies, callbacks or per-person permissions.

Automatic public certificates use Caddy's ACME issuer, explicitly accepted CA
terms, and TLS-ALPN validation on public port 443. Certificate acquisition and
renewal stay with Caddy; the app does not implement ACME. This mode cannot use
local-only names or a different public port. For LAN/VPN/CGNAT installations,
DNS-validated certificates can be managed by the existing reverse proxy or a
certificate manager that mounts its renewed PEM files into Eugene. Supplied
certificate changes reload without restarting apps; failed reloads retain the
last working certificate. Changing trusted CA roots still requires restart.

The console's access setup page previews and validates configuration without
changing listeners. It generates two hostnames from a base domain by default, the
console and Workbench; the inference and node names are opt-in extras. Preview
does not request certificates, modify DNS or claim network reachability.
Existing installations never switch implicitly.

**Apply** (2026-10-05) checks the configuration with the bundled proxy, writes the
file and restarts the agent in place: the lifespan stops every child, and the
process re-executes itself, so the container keeps running. **An applied
configuration is on approval**, because the page that applied it stops answering
at the address it was opened at: until an operator session arrives through the new
entry point, the previous file is kept aside, and if none arrives within 15
minutes of a start, or the start fails, the agent puts it back, keeps the failed
one as `entrypoint.json.reverted` and reports why. A file copied in by hand is not
on approval. Turning it off from the same page keeps the file as
`entrypoint.json.disabled` and restarts on the direct ports.

Every refusal says which check failed and what the proxy saw, as plain text: an
untrusted connecting address, a proxy that did not say who the visitor is, a
request not marked HTTPS, a visitor outside a name's networks (with its own answer
when the request came through Cloudflare, whose addresses every visitor then
appears to have), and an unknown hostname. A refusal names only what the caller
sent or is, never a trusted address, an allowed network or another hostname.

Release checks cover exact hosts/SNI, forwarding spoofing, private console with
reachable Workbench sign-in, callback migration, cookie and sibling-origin CSRF
protection, backend port privacy, dynamic app routing, and actual HTTPS requests
through the packaged proxy. This is a tested security boundary, not a claim of
independent security certification.
