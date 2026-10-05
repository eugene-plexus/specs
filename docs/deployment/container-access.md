# Choose how to reach Eugene and Workbench

Open **Settings → Container access setup**, choose one of the setups below and
press **Prepare setup**: the page checks your choices and lists what to set up
around them (it does not test DNS). **Apply** then saves it and restarts Eugene
in place. Open the console address and sign in within 15 minutes; if nobody does,
Eugene goes back to how it was by itself, so a mistake never locks you out. The
[migration steps](container.md#one-https-port) say what changes and how to go back.

| Your setup | Choose | Published ports and certificates |
| --- | --- | --- |
| NAS with Nginx Proxy Manager, Caddy or Traefik | My reverse proxy | Proxy owns HTTPS; Eugene publishes no ports on the same Docker host |
| Home or small business with a domain and inbound TCP 443 | Eugene automatic Let's Encrypt | One TCP port, automatic issuance and renewal; no port 80 needed |
| LAN or VPN without a public domain | Eugene local certificates | One HTTPS port; local DNS and CA trust on each device |
| LAN, VPN or CGNAT with a domain, but no inbound ports | DNS-capable proxy or supplied certificates | External DNS-01 automation; local/VPN routing still needed |
| SMB/MSP with organisation PKI | Supplied certificate files | One HTTPS port, automatically reloaded PEM files; organisation CA trust |
| Reverse proxy on a different machine | My reverse proxy, with HTTPS upstream | Verified TLS on both legs; Eugene's port restricted to the proxy |

**Where you open the console** is a choice of its own. By default it stays on its
own port on your network, as before, and only Workbench goes through the setup;
the console's name is then used only for Workbench's sign-in, so it still needs a
proxy host, but nobody needs a local DNS entry. This is the setup to start with
when Workbench is reached from outside, for example through Cloudflare.

Every mode keeps separate exact console and Workbench hostnames, browser HTTPS,
sign-in and per-user node/folder grants. Those two names are the default; an
inference name (for apps on other machines) and a node name are extras. Without a
node name, machines you have connected keep reaching this one at the control
root's port, 8083 in the container, so keep that port published while any are
enrolled. Accounts are not isolated MSP tenants;
use a separate Eugene installation for each customer requiring that boundary.
Legacy direct ports remain available. The managed entry point runs in the Linux
container; browsers and enrolled Windows/macOS/Linux machines can use it.

## Existing reverse proxy on the same Docker host

**Two addresses, and they are easy to swap.** Your proxy forwards to *Eugene's*
address on the Docker network they share, port `8088`, plain `http`. Eugene's
**Trusted proxy IP addresses** is *the proxy's* address on that same network:
not its LAN address, and one address, not a network. **Allowed private networks**
is neither: it is where the people using the console are, such as your home
network. To list both containers' addresses on a network:

```sh
docker network inspect <network> -f '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'
```

Give the proxy a fixed address on that network (Unraid: the container's **Fixed
IP address**), or it can change when the proxy is recreated and Eugene will stop
trusting it.

Best is a **dedicated Docker bridge network shared only by Eugene and the proxy**.
The HTTP hop stays on that host; do not publish it on the LAN. Choose a subnet
that does not overlap existing Docker, LAN or VPN networks. For example:

```sh
docker network create --subnet 172.30.0.0/29 eugene-ingress
```

Add that external network to your proxy's existing Compose service, retaining its
existing networks, data volumes and published ports. The fixed address must match
Eugene's `proxy.addresses`:

```yaml
services:
  your-existing-proxy:
    networks:
      eugene-ingress:
        ipv4_address: 172.30.0.2
      # Retain its other networks here.
networks:
  eugene-ingress:
    external: true
    name: eugene-ingress
```

Use [compose.behind-proxy.yaml](../../docker/compose.behind-proxy.yaml) as the
standalone Eugene definition, **not an overlay on a file that publishes ports**.
Set `EUGENE_DATA_VOLUME` to the existing volume's actual Docker name. For Unraid
or bind-mounted appdata, retain your existing host path mapped to `/data` instead
of changing to a named volume. Attach the dedicated network; once Workbench
answers through the proxy, the gateway and Workbench port mappings can go. **Keep
the console's mapping (container port `8079`) while the console stays on its own
port, which is the default: it is then the only way into the console.** It can go
only if you moved the console through the setup too and it answers there. Keep the
control root's `8083` while other machines are enrolled. Keep the
hostname, model mounts, GPU settings and user ID from your existing installation.
On Unraid, a shared custom network your proxy already uses (often a
`proxynet`-style bridge) works the same way; other containers on it are refused,
because only the proxy's own address is trusted.

The [proxy example](../../docker/entrypoint.proxy.example.json) uses port `8088`
inside the container and HTTPS port 443 outside. Replace its names and client
networks. `proxy.addresses` accepts individual IPs, never broad LAN subnets.
The allowed service networks describe **users and nodes**, not the proxy's IP.
Eugene rejects requests from untrusted connections and those without a valid
client address and `X-Forwarded-Proto: https`. It reads trusted forwarding chains
from right to left, so a caller cannot insert a private address to become an
administrator. The outer proxy must replace or correctly append forwarding data.
When Eugene refuses a request, the answer says which of these failed and the
address it saw, such as *it came from 172.18.0.4, which is not a proxy Eugene
trusts*.

### Behind Cloudflare

With Cloudflare's proxy (the orange cloud) in front of your own, every visitor
arrives as a Cloudflare address. The simplest setup is the default one: keep the
console on its own port, and only Workbench (and its sign-in) goes through
Cloudflare. If you move the console through the setup too:

- Set Cloudflare's **SSL/TLS** mode to **Full** or **Full (strict)**. With
  *Flexible*, your proxy tells Eugene the request was not HTTPS, and Eugene
  refuses it.
- Workbench works through Cloudflare when **Allow Workbench access from any
  network** is ticked.
- The console only answers your own networks, so through Cloudflare it refuses
  you, and says so. To reach it from home, add a local DNS entry (router, Pi-hole,
  or the hosts file) pointing the console name at your proxy's LAN address, so
  home traffic skips Cloudflare. A Cloudflare *Origin* certificate on your proxy
  is not trusted by browsers when they skip Cloudflare; use a Let's Encrypt
  certificate there instead.
- Or tick **Allow the console from any network, with sign-in**. Read what it
  risks first; the page lists it and asks you to confirm:
  - anyone on the internet can open the console's sign-in page and try
    passphrases, and your passphrase is then all that stands between them and
    the whole install (models, backends and their keys, Library folders, apps,
    people's accounts, connected machines);
  - Eugene allows 5 wrong passphrases a minute from each visitor address, and
    behind Cloudflare visitors share Cloudflare's addresses, so an attacker
    spread across them gets more tries, and other people's wrong guesses can
    lock you out for a minute;
  - a signed-in console stays signed in for 14 days, from wherever it is;
  - a flaw found later in the console or its API is reachable from the
    internet, not just your network.

  Use a long passphrase used nowhere else. Safer ways to reach the console
  from outside: a VPN such as Tailscale, or Cloudflare Access in front of the
  console's name. Connections from other machines stay limited to your
  networks either way. In the file this is `"public_console": true` with the
  console's networks `["0.0.0.0/0", "::/0"]`; without the flag such networks
  are refused.

### Nginx Proxy Manager

Create a Proxy Host for each enabled name (or one with all the exact names):

- Forward scheme: `http`; hostname: `eugene-plexus-control-plane`; port: `8088`.
- SSL: choose/request the appropriate certificate and enable **Force SSL**.
- Preserve the original Host; use normal forwarding headers. Do not add a
  custom location that replaces client IPs with the proxy's IP.
- Disable asset caching for these hosts. Keep streaming enabled; if using custom
  Nginx configuration, disable proxy buffering and allow long inference responses.

NPM manages certificate issuance/renewal. For private names under a domain you
own, use its DNS challenge support and local DNS pointing at the proxy. Keep
NPM's own administration interface private. See its [Docker network guidance](https://nginxproxymanager.com/advanced-config/#best-practice-use-a-docker-network).

### Caddy as your existing proxy

With the dedicated network and proxy address above, this routes exact names to
Eugene while Caddy handles external HTTPS:

```caddyfile
eugene.example.org, workbench.example.org, inference.example.org, nodes.example.org {
    reverse_proxy eugene-plexus-control-plane:8088 {
        flush_interval -1
    }
}
```

Keep your existing certificate configuration; remove disabled names. Default
Caddy preserves Host and supplies client forwarding metadata. Configure any
additional upstream CDN/proxy trust explicitly on that outer Caddy, never with
unrestricted trusted networks. See [Caddy reverse proxy documentation](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

### Traefik as your existing proxy

For an existing Docker provider, `websecure` entry point and certificate resolver
named `letsencrypt`, add these labels to Eugene. Substitute your actual entry
point/resolver names and remove disabled hostnames:

```yaml
labels:
  traefik.enable: "true"
  traefik.docker.network: eugene-ingress
  traefik.http.routers.eugene.rule: Host(`eugene.example.org`) || Host(`workbench.example.org`) || Host(`inference.example.org`) || Host(`nodes.example.org`)
  traefik.http.routers.eugene.entrypoints: websecure
  traefik.http.routers.eugene.tls: "true"
  traefik.http.routers.eugene.tls.certresolver: letsencrypt
  traefik.http.routers.eugene.service: eugene
  traefik.http.services.eugene.loadbalancer.server.port: "8088"
  traefik.http.services.eugene.loadbalancer.server.scheme: http
  traefik.http.services.eugene.loadbalancer.passhostheader: "true"
```

Attach Traefik at the fixed trusted IP and keep forwarded-header insecure mode
disabled. These labels assume an already secured Traefik installation; Eugene
does not need the Docker socket. See [Traefik's Docker provider](https://doc.traefik.io/traefik/reference/install-configuration/providers/docker/).

## Let Eugene obtain certificates

Choose automatic certificates and accept the linked Let's Encrypt subscriber
agreement. The [example](../../docker/entrypoint.automatic.example.json) deliberately
leaves `accept_terms: false` until you accept it. Provide a contact email and real
hostnames under a domain you control.

Point public DNS A/AAAA records at this connection and forward TCP **443** to
Eugene's internal listener, normally `443:8443`. Every advertised IPv4/IPv6 address
must work. Caddy uses TLS-ALPN-01; **port 80 is neither opened nor required**. A
TLS-terminating proxy in front prevents this challenge; use proxy mode instead.
The challenge can succeed while console and node routes remain restricted to
your private client ranges. Split DNS can direct LAN clients to the NAS address.

Certificates, ACME account keys and renewal state persist under
`/data/entrypoint/tls`; preserve and protect the data volume. Caddy renews
certificates automatically. Logs report DNS, connectivity and issuance failures.
Staging is available for testing issuance without production rate limits; its
certificates are deliberately untrusted. Set `staging: false` and recreate before
normal use. Do not disable certificate verification to use staging.

DNS ownership and routing cannot be inferred safely. Dynamic public IPs need
dynamic DNS. CGNAT without an inbound route cannot use this direct issuance mode.
Eugene does not store DNS-provider API keys or ship provider-specific Caddy
plugins: use a DNS-capable existing proxy or certificate manager for DNS-01.
DNS verification obtains a certificate; it does not create remote connectivity.
See [Let's Encrypt challenge types](https://letsencrypt.org/docs/challenge-types/).

## Private networks and supplied certificates

Local-CA mode needs no public domain. Point local names such as
`eugene.home.arpa` and `workbench.home.arpa` at the server and trust the generated
**public** `root.crt` on each connecting device. Never distribute CA private keys.
Businesses can distribute CA trust through their normal device management.

For supplied certificates, mount a **directory** read-only, including any symlink
targets used by the certificate manager. Single-file bind mounts can remain tied
to an old inode after atomic replacement. Set absolute `certificate` and
`private_key` container paths. The chain must cover every configured hostname.
The agent notices changed PEM contents and asks Caddy to reload them, normally
within a few seconds. Invalid or incomplete replacements keep the previous
working certificate; review logs and repair renewal before it expires. Changing
the configured paths requires recreating the container.

Use `trusted_ca` for an organisation/private issuer. This also works in private
HTTP proxy mode when the outer proxy uses that issuer. Eugene loads this public
CA into its own services' trust bundle. Changing that trust file requires a
container restart; browser, node and proxy trust is administered separately.

## Proxy on another machine

Select **Use HTTPS between my proxy and Eugene**. Mount a certificate/key on
Eugene, use `proxy.transport: https`, and restrict its published listener to the
proxy's address with the host firewall. The proxy must verify Eugene's issuer
and use the corresponding public hostname for both Host and TLS SNI.

For example, on an existing Caddy proxy this block serves the console; repeat
for each enabled hostname with its own fixed `tls_server_name`:

```caddyfile
eugene.example.org {
    reverse_proxy https://192.168.16.252:8443 {
        header_up Host eugene.example.org
        transport http {
            tls_server_name eugene.example.org
            tls_trust_pool file /etc/caddy/eugene-ca.pem
        }
        flush_interval -1
    }
}
```

Omit the custom trust pool for a public issuer already trusted by the proxy.
For Nginx use upstream certificate verification, an appropriate CA file and SNI
explicitly; selecting `https` alone is insufficient. Never disable verification.
If another NAT/proxy hides the original client, configure its authenticated
forwarding boundary correctly before allowing remote access; do not allow its
LAN address as if every caller were an administrator.
