# Remote nodes: a machine outside the control root's network

**Status:** design for Troy to decide on, 2026-10-05. **Nothing here is built.**
It answers Troy's question of 2026-10-05 about a PC behind a business NAT, and
replaces the "public nodes name" idea floated the same day, which cannot work on
its own (§0, finding 1).

**The short answer.** Every inference request is a connection the root opens
*to* the worker. A NAT in front of the worker refuses it, so a node the root
cannot dial serves nothing, whatever name the root itself is published under.
There are two ways out:

- put both machines on one private network that crosses NAT for them, which is
  Tailscale today and is the architecture's stated commitment; or
- have the node hold a connection open to the root and carry the root's calls
  back over it. That is a tunnel we would build and own.

**Recommendation:** a better-guided Tailscale path now. It covers four of the
five scenarios outright and the fifth technically. It costs documentation and
four small product checks, and no transport code. Keep the built-in tunnel as
the long-term direction, and decide on it when someone cannot or will not use a
mesh. §4 holds the calls.

Sources for every upstream claim are in §6. They were fetched on 2026-10-05.

---

## 0. Every connection between a root and a node

Read from the code at agent `a8cfdde`, control `b667699`, gateway `219b191`,
inference-driver, library, tool-driver and workbench `main` (2026-10-05). The
code was read, not this repo's notes. The paths are abbreviated:

| Prefix | Repo path |
|---|---|
| `A/` | `agent/src/eugene_plexus_agent` |
| `C/` | `control/src/eugene_plexus_control` |
| `G/` | `gateway/src/eugene_plexus_gateway` |
| `D/` | `inference-driver/src/eugene_plexus_inference_driver` |
| `T/` | `tool-driver/src/eugene_plexus_tool_driver` |
| `L/` | `library/src/eugene_plexus_library` |
| `W/` | `workbench/src/eugene_plexus_workbench` |
| `U/` | `ui/src` |

The token kinds below are as follows:

| Token | What it is |
|---|---|
| **svc:control** | A 5-minute token that control mints per node per call. |
| **svc:gateway** | A 15-minute token for `node:X`, signed by the gateway host's agent. It needs the `gateway` grant. |
| **svc:agent** | A 15-minute token the node's own agent mints. |
| **xchg** | An operator session exchanged at the root for a token of at most 5 minutes, addressed to one node and carrying `act`. |

**Nothing between machines uses TLS.** Node and component URLs are built as
`http://` (`A/node_identity.py:197-201`, `A/routes/components.py:96`). On a
tailnet, WireGuard encrypts the traffic. On a LAN, prompts and tokens cross in
clear text.

### 0.1 Opened by the root's host: a NAT in front of the worker breaks every one

| # | Initiator → target | Endpoint | Purpose | Auth | How often | Size | If it fails | Anchors |
|---|---|---|---|---|---|---|---|---|
| R1 | root gateway → worker driver | `POST /v1/generate`, `/v1/generate/stream`, `/v1/embed`, `/v1/image*`, `/v1/speak`, `/v1/transcribe`, `/v1/video*`, `/v1/decide`, `/v1/moderate`, at the driver's `advertiseUrl` | **Inference** | svc:gateway | Every request. 600 s deadline, 10 s connect | Up to 16 MiB in; SSE token stream out | Fails over to a replica or a later tier before the first token; a circuit breaker per driver, 1→60 s | `G/driver_client.py:394,522`, `G/routing.py:1438-1442`; `D/routes/generate.py:50,78` |
| R2 | root gateway → worker driver | `GET /v1/info` | Discovery and liveness | svc:gateway | Every 15 s (`routingRefreshSeconds`); per request when a key is `localOnly` or names settings | 1-5 KB | Driver marked `unreachable`, not routed | `G/routing.py:1563-1583`; `D/routes/info.py:29` |
| R3 | root gateway → worker agent | `GET /v1/components`, `GET /v1/runtimes` at `Node.url` | Driver URLs, runtime state | svc:gateway | Every 15 s, 5 s timeout | A few KB | Keeps the node's last good facts | `G/routing.py:1416,1470,1345-1359` |
| R4 | root gateway → worker agent | `POST /v1/runtimes/{n}/stop`, `/start`, `GET /v1/runtimes/{n}`, `POST /v1/runtimes/admission` | Idle unload, wake on demand, eviction | svc:gateway | Idle sweep every 15 s; wake per request, polled every 1 s up to `swapWaitSeconds` | < 1 KB | Wake fails with a 503 naming the cause; a stop is retried next sweep | `G/lifecycle.py:79-145,374-484` |
| R5 | root gateway → worker tool-driver (direct) | `GET /v1/info`, `POST /v1/tools/web_search` | Web search | svc:gateway | Every refresh; per tool call (30 s) | Small | Tries the next account | `G/routing.py:1516-1553`, `G/tool_client.py:116,138` |
| R6 | root control → node agent | `GET /v1/node` | Liveness probe | svc:control | Every 15 s (`nodePollIntervalSeconds`), 5 s timeout | 2-10 KB | `reachable: false` with `lastError`. **Reporting only:** nothing routes on it (finding 3) | `C/app.py:287-368`, `C/nodes_client.py:137-179` |
| R7 | root control → every node agent | `GET /v1/components`, `GET /v1/runtimes` | Install-wide views | svc:control | Every call to control's views: the Inference page every 3 s, and every agent's lookup cache miss (N5) | A few KB per node | Node listed in `unreachableNodes` | `C/nodes_client.py:190-242`, `C/routes/topology.py:78-85` |
| R8 | root control → node agent | `POST /v1/runtimes` | Forwards an operator's launch on that node | svc:control | On click | ~1 KB | 502 relaying the agent's answer | `C/nodes_client.py:261-282` |
| R9 | root control → node agent | `POST /v1/node/trust-bundle` | **Push** of the signed trust bundle: a new node, a revocation, a sign-out, a rotation, a new epoch | None; a JWS signed by the root's identity key, which the node pinned at join | On each of those events | 1-10 KB | Logged, not retried; **the node's 60 s pull (N3) replaces it** | `C/trust.py:170-219`; `A/routes/node.py:414` |
| R10 | root agent (console) → worker agent | `ANY /api/proxy/node:<name>/…` | Every per-machine console action: start, stop, engines, apps, settings, logs (SSE), updates | xchg | On click; Needs Attention reads 5 endpoints per node every 30 s | Streams; up to 32 MiB | 502 "Upstream unreachable" | `A/routes/proxy.py:364-406,500-577,651`; `U/lib/useIssues.ts:53,148-159` |
| R11 | root agent → worker agent → worker component | `ANY /api/proxy/<driver-or-tool>/…` | Console reaching a remote component's settings | xchg | On click | Small | 502 | `A/routes/proxy.py:281-361` |
| R12 | worker OS → file server (often the root host or a NAS) | SMB 445, `WNetAddConnection2W` | Model files and the node-local copy, which **reads the share, not HTTP** | Share credentials sealed on the node | Every model load; the copy once per model | GBs | Launch falls back to opening the share directly | `A/share_credentials.py:163`, `A/model_copies.py:36-40,361` |

**R13**: when a console hops to another node, the agent serving the browser
dials that node directly at the `Node.url` it got from control. From a worker's
console that hop is worker → worker and never passes the root
(`A/routes/proxy.py:364-406`).

### 0.2 Opened by the worker: these survive a NAT in front of the worker

They still need **the root** to be reachable from the worker's network.

| # | Initiator → target | Endpoint | Purpose | Auth | How often | If it fails | Anchors |
|---|---|---|---|---|---|---|---|
| N1 | worker agent → control host:port | TCP connect only | Derives the advertise host from the local end of the socket | None | At join, at boot, on change | Falls back to the stored address | `A/node_identity.py:204-231` |
| N2 | worker agent → control | `POST /v1/nodes/enroll` | Join | Single-use join token (900 s) | Once | Nothing recorded | `A/enrollment.py:202`; `C/routes/nodes.py:427` |
| N3 | worker agent → control | `GET /v1/trust/bundle` | **Pull** of the bundle: revocations and epoch fencing | None; JWS checked against the pinned key | Every 60 s | Keeps the bundle it has | `A/app.py:541-577`; `C/routes/control.py:338` |
| N4 | worker agent → control | `PATCH /v1/nodes/{name}` `{url, sequence, signature}` | Address announcement | Ed25519 signature by the node's identity key | Boot, a change to `advertiseUrl`, the Reach switch. **Not retried, and not sent on a network change** | Root keeps the old URL until the next trigger | `A/enrollment.py:279-337`, `A/app.py:417,625-662`; `C/routes/nodes.py:155-323` |
| N5 | worker agent → control | `GET /v1/components` + `GET /v1/nodes` | "Who runs X, at which agent URL" | svc:agent | Cached 30 s; each miss makes control fan out R7 to every node | 503 naming the missing address | `A/install_proxy.py:84-89,223-269` |
| N6 | worker agent → **root agent** `/api/proxy/library` | `GET /v1/folders`, `/v1/models`, `/v1/models/{id}/fit` | Library folders, admission fit | svc:agent | Per launch path; `folders/check` via Needs Attention every 30 s | Admission falls back to file size | `A/admission.py:257-349`, `A/library_folders.py:249-274` |
| N7 | worker agent → root agent → library | `GET /v1/run-operations/assigned`, claim, checkpoint | Library-owned "run this model" jobs | svc:agent | **Every 2 s** | Retried in 2 s | `A/run_worker.py:188-232,322-338` |
| N8 | worker agent (console) → root agent | `/api/proxy/{gateway,library,control}` | The worker's console showing install pages | Session to `control` passes unchanged, else xchg | UI polling | 502/503 with the reason | `A/routes/proxy.py:328-361` |
| N9 | worker agent → control | `POST /v1/auth/token` | RFC 8693 exchange | svc:agent as actor | Cached per session and audience | 503 "Control root unreachable" | `A/routes/proxy.py:497-523` |
| N10 | worker agent → control | `POST /v1/auth/login`, sign-out, unenrol | Forwarded sign-in and sign-out | svc:agent / the session | On click | 503; unenrol goes ahead with `controlNotified: false` | `A/routes/auth.py:422-475`, `A/routes/node.py:376-411` |
| N11 | worker agent → control | `/v1/auth/client-keys*`, `…/admission` | Client-key registry and admission | svc:agent (+ subject token) | Log-ingress key check every 15 s; per request for a gateway on a worker | **Fails closed**: 503 | `A/client_key_registry.py:82-139` |
| N12 | worker agent → control | `GET/POST /oidc/*` | Sign in with Eugene for apps on the worker; Workbench node folders | Forwarded headers + node token; client secrets checked at the root | Per sign-in step | 503 `temporarily_unavailable` | `A/routes/oidc_forward.py:76-123` |
| N13 | worker agent → control | `POST /v1/oidc/clients`, `PUT …/redirect-uris`, client keys | App install on the worker; callbacks moved at boot | svc:agent (+ subject token on install) | On install; at boot, retried 5→120 s | Install fails | `A/sign_in_refresh.py:36-62`, `A/routes/apps.py:296-361` |
| N14 | worker agent → control | `POST /v1/node-helpers/poll` (long poll, 8 s) | File-helper work queue: **the root never dials the node** | svc:agent | Continuous | Silent retry after 5 s | `A/node_file_helper.py:262-309`; `C/node_helpers.py:25,188-207` |
| N15 | worker app → root agent `/api/proxy/gateway` | OpenAI-compatible `/v1/*` | Workbench or Open WebUI on a worker using inference | App client key | Per request (SSE) | Named to the user | `A/app.py:685-726`, `W/hub.py:81-82` |
| N16 | standby control → active control | `GET /v1/control/log`, `/snapshot` | Replication | **None sent; the routes need a session**, so every tick is a 401 (§5) | Every 2 s | Retries forever | `C/app.py:142-151`, `C/dependencies.py:175-183` |

Each node also fetches updates, engines and app packages from GitHub and PyPI
itself. The root never tells a node to update (`A/updates.py:70-79`).

### 0.3 What the inventory says

1. **Inference is root → node and has no fallback.** R1-R5 are opened by the
   gateway, per request or every 15 s. The "public nodes name" floated on
   2026-10-05 would carry only N-rows (join, announcements, bundle pulls,
   helpers). The nodes hostname routes to control alone
   (`A/entrypoint.py:546-547`), and N6, N7, N8 and N15 dial the root *agent*,
   which is not on it. So a worker behind NAT could join and then serve nothing.
   An open port at the root, NPM's included, carries connections *to* the root.
   R1-R12 leave it.
2. **Of the twelve root → node connections, only the trust-bundle push (R9) has
   a worker-initiated replacement** (the N3 pull). R8 has a partial one, the
   library run-operations poll (N7). The file helpers (N14) already show the
   pull pattern: a long poll, and nothing dials the node.
3. **"Down" is reporting only.** Control's probe (R6) feeds the Nodes page. The
   gateway builds its node map from every node with a URL, ignoring
   `reachable` (`G/routing.py:1074-1080`), and stops routing to a driver only
   when its own calls fail. A node behind NAT shows *down: timed out* with
   nothing that names the cause or the fix.
4. **Behind a NAT, the derived advertise address is the worker's private
   address.** The worker learns it from the local end of its connection to the
   root (N1), and nothing checks that the root can dial it back. The join
   succeeding proves only the outbound half. `tailnet.md` §6 says so, and the
   product does not.
5. **One address per node, used by every caller.** N5-N8 and N15 dial the root
   agent at the root's single `Node.url`. On Troy's install that is a LAN
   address, `192.168.16.252:8279`. A remote node reaches it only if the private
   network carries that LAN (a Tailscale subnet route), or if every machine
   moves to tailnet addresses.
6. **Address rules.**
   - Moving from a private address to a public one is refused (409), and **any
     hostname counts as public** (`C/node_address.py:117-159`). A node joined
     at a LAN IP cannot later announce a MagicDNS name or a tunnel hostname; it
     must join again.
   - A tailnet address in `100.64.0.0/10` counts as private, which is right.
   - Driver URLs use the driver's own bind port, unadjusted for remaps
     (`A/routes/components.py:92-96`). Port forwarding would have to forward
     every companion port, 8090-8189, one for one.
7. **The rekey is gone.** It was replaced by the signed bundle on 2026-09-25
   (row 3). Its helpers survive as dead code in `C/sealing.py:185-244`.
8. **Model files reach a node over SMB (R12).** A remote node can run only what
   the root's library catalogues, so its models cross the WAN once, into the
   node-local copy, at the WAN's speed (§1).

---

## 1. Scenarios

"Today" means the shipped product with nothing but its own docs.

| # | Scenario | Root → node today | Node → root today | What it needs | Also bites |
|---|---|---|---|---|---|
| 1 | Home LAN, plus a friend's PC on another home network (consumer NAT both ends) | Refused at the friend's router | Refused at Troy's router unless control's port is forwarded, and the nodes name may not be public | A private network that crosses both NATs, or a tunnel from the friend's PC to a reachable root | The friend's PC must not see Troy's whole network (§2, Tailscale ACLs); models cross the WAN |
| 2 | Office PC behind business NAT, outbound TCP 443 only, perhaps an HTTP proxy | Refused | Only to 443, maybe only through the proxy | Something that rides TCP 443 through a CONNECT proxy | **Whether a VPN or tunnel client may run on that PC is the office's decision, not ours** (call 9) |
| 3 | CGNAT on either end | Impossible to forward into a CGNAT side | Fine from a CGNAT worker if the root is reachable; impossible *into* a CGNAT root | NAT traversal with a relay fallback. A root on CGNAT needs a relay even for a built-in tunnel | Relayed paths are slower (§2.2) |
| 4 | GPUs in two buildings, each with its own internet (Troy's plan) | Refused | Refused unless forwarded | As 1, with one owner at both ends | Models cross the WAN; clock skew (`tailnet.md` §7) |
| 5 | A laptop node moving between networks | Works only on the network where it announced | Works where the root is reachable | A stable address, or no address at all (a node-held tunnel) | The announcement is sent at boot and on a settings change, **not when the network changes, and not retried** (N4) |

**Model files, under every option.** A remote node opens models through a
Library folder mount (R12). Over a WAN, that means SMB across the private
network into the node-local copy, once per model. Two figures below are
arithmetic, not measurements:

- A 23.8 GB model at a 40 Mbit/s home upload takes about **80 minutes**.
- The same model at the ~10 Mbit/s one Tailscale issue reports over a relay
  (#18017) takes about **5 hours**.

No transport choice changes the upload speed. A node that downloads from
Hugging Face itself would sidestep it (call 6).

---

## 2. Options

### 2.1 Matrix

"Steps" counts what a weekend user does to add **one** remote node to an
existing install. Troy's bar: *"no weekend LLM enthusiast is going to do all of
this."*

| Option | Reachable from the internet | Steps / accounts | 443-only / proxy | CGNAT | Path and speed | Dependency when it fails | Our code | Fits the mesh commitment |
|---|---|---|---|---|---|---|---|---|
| **Tailscale** | Nothing. WireGuard answers only peers; relays carry ciphertext | ~5 steps, 1 account (a friend's PC needs none, with a tagged auth key) | Yes: DERP over HTTPS 443, through a CONNECT proxy; NTLM proxies are doubtful | Yes, relayed when both ends are hard NAT | Direct when hole-punched; DERP is QoS'd (#14661, #18017); peer relays need UDP | Coordination outage: existing paths keep working, no new joins (§6 cites eight partial outages Jul-Oct 2026) | Docs + four small checks (§3) | Yes, as written |
| **Headscale** | The Headscale server (HTTPS 443) and its DERP | ~10 steps plus a VPS, a domain and TLS; no vendor account | Same client as Tailscale | Yes (its own DERP, or Tailscale's by default) | Same as Tailscale | You run it | As Tailscale + docs | Yes |
| **Plain WireGuard** | One UDP port on a hub with a public address | ~5-8 steps per node (keys, configs, a forward); admin on Windows | **No** (UDP only) | **No** without a public hub | Direct, kernel speed | None | Docs only | Yes |
| **ZeroTier** | Nothing on ours | ~5 steps, 1 account, authorise each member | TCP relay on 443, "slow"; proxy not documented | Relayed via roots | Relayed is "slow" | Central down: existing paths continue | Docs only | Yes, but the controller is source-available non-commercial since 1.16.0, and the free tier is 10 devices, non-commercial |
| **NetBird** | Nothing on ours | ~4 steps, 1 account (setup keys) | Yes (WebSocket relay on 443); proxy partial (#5798) | Relayed | Relay ~25 Mbit/s reported (#6021) | Outages documented; existing paths stayed up | Docs only | Yes; the server is AGPL |
| **Nebula** | A lighthouse and relays on public UDP | ~7 steps self-managed PKI; Managed Nebula needs 1 account | **No** (UDP only, #1001) | Via a public relay host | Direct or relayed | Lighthouse | Docs only | Yes |
| **Cloudflare Tunnel + Access** | A public hostname per worker port, gated by an Access service token; **Cloudflare terminates TLS and sees every prompt** | ~6 steps, 1 account + a domain on Cloudflare, per worker | **No: needs outbound 7844**, and ignores `HTTPS_PROXY` (#1076) | Yes | Edge-proxied. **125 s to first response byte** (cold loads exceed it); 100 MB request cap | Cloudflare down = tunnel down | Large: per-driver Access headers, per-port routes for dynamic companion ports, early headers that undo R2.5's first-chunk rule | No: an internet-facing proxy, not a mesh |
| **frp** (supervised, self-hosted) | frps on the root, on one public port (TLS + token) | Root port forward + configs; we could automate both | Yes, in TCP mode through a proxy | Worker yes; **root on CGNAT, no** | Direct to the root; multiplexed TCP; ~390 MB/s with TLS here (§2.3) | None (self-hosted); **Defender quarantines `frps.exe`** (§2.3) | Medium-large: supervise frpc/frps, map every dynamic port, a second auth system beside ours | Partly: a tunnel, not a mesh |
| **rathole / ssh -R** | sshd or the rathole server on the root | Per-port forwards, keys | Yes (ssh via ProxyCommand) | Root on CGNAT, no | One TCP connection per call (rathole); HOL on one SSH link | None | As frp; rathole dormant since 2023, autossh since 2019 | Partly |
| **ngrok** | A public endpoint per tunnel; ngrok terminates TLS | 1 account, a card for TCP | Yes | Yes | Edge-proxied | ngrok down = down | Medium | No; proprietary agent, **1 GB/month** free |
| **Port forward + mTLS** | **The worker's agent, drivers and tool-drivers, to the whole internet** | A forward per port (~100), our own CA, client certs | n/a (inbound) | **Impossible** | Direct | None | Large: TLS on every port, a CA, remap-aware URLs, the public-address rule reversed | No; breaks "nodes are never public" |
| **IPv6 direct** | The worker's ports over IPv6 | A router firewall rule per port, at both ends | n/a | Bypasses IPv4 CGNAT where IPv6 exists (~41-52% of users, APNIC/Google) | Direct | None | As port forward | No; same exposure |
| **Built-in tunnel** (§3.2) | **On the node, nothing.** On the root, one hub endpoint on the nodes name, with a signed handshake before anything else | Root: one forward of 443 + a name (or Cloudflare/Funnel in front); node: the join command. No account | Yes: WSS on 443, `HTTPS_PROXY` honoured by `websockets` | Worker yes; **a root on CGNAT still needs a relay in front** | Node ↔ root directly, no third party; one TCP link (head-of-line on loss) | None | **Large**: framing, per-stream flow control, handshake, hub routing, gateway/control/console transport, UI, degraded mode | Needs the commitment revisited (call 7) |

### 2.2 What separates the top three

- **Tailscale** is the only option that crosses NAT and CGNAT at both ends,
  runs over a 443-only proxy, and needs no public endpoint anywhere.
  - Its costs are a third-party account and a coordination server we do not
    control.
  - Its default policy is **allow-all**: a friend's PC added to Troy's tailnet
    can reach every device on it, and the reverse, until an ACL says otherwise.
  - A user device's key expires after 180 days by default, and the Windows
    client disconnects at sign-out unless `--unattended` is set. Both would
    silently drop a headless GPU box. A tagged auth key fixes the first, and
    the guide must cover both.
- **A built-in tunnel** needs no account and no VPN anywhere.
  - It moves the reachability problem from N nodes to **one** root: one port
    forward or one relay instead of a client on every machine.
  - It does not solve a root on CGNAT.
  - It puts the first pre-authentication surface for nodes on the internet.
- **Cloudflare Tunnel** looks closest to what Troy already runs, and fails
  three ways here:
  - it needs port 7844, not 443, and no HTTP proxy;
  - a cold model load overruns its 125 s first-byte deadline;
  - **Cloudflare decrypts every prompt** on a product whose reason to exist is
    local inference.

  Cloudflare Mesh (formerly WARP Connector, 2026-04) is layer 3 and free for 50
  nodes. Its nodes are Linux-only today. Worth re-reading when it reaches
  Windows and Docker.

### 2.3 Measured on this box

**Setup.**
- Ryzen 9 9950X, running Windows 11 and WSL2 in NAT mode (172.19.x).
- A stub SSE server sends 200 frames at 10 ms intervals, so the ideal total is
  2.0 s.
- An unbuffered raw-socket client makes 50 requests per path, each on a fresh
  connection, after 5 warm-ups.
- Each path also carries three 2 GiB bulk transfers.
- frp v0.71.0. Scripts are in the session scratchpad (`remote-nodes/`).
- **Every number is a local hop.** None includes a WAN round trip.

| Path | TTFT median / p90 (ms) | SSE total median (ms) | Max gap p90 (ms) | Bulk MB/s |
|---|---|---|---|---|
| Windows → WSL direct | 0.35 / 0.59 | 2000.6 | 10.58 | 3167-4593 |
| frp, tcp + mux, TLS off | 1.33 / 1.90 | 2001.8 | 10.44 | ~540 |
| frp, tcp + mux, TLS on (its default) | 1.09 / 1.64 | 2001.5 | 10.50 | ~390 |
| frp, WebSocket transport | 1.08 / 1.75 | 2001.5 | 11.09 | ~255 |
| Python asyncio reverse relay (node dials out; one stream, no framing) | 1.25 / 1.53 | 2001.5 | 10.47 | ~1,980 |
| WireGuard, two netns on one kernel (MTU 1420) | 0.74 / 0.82 | 2000.9 | 10.37 | ~64 (iperf3 538 Mbit/s) |

**What it says:**
- **No hop hurts token streaming.** Every path holds the 2.0 s total. A hop
  adds 0.4 to 1 ms to the time to first token, and about 0.1 ms to the worst
  gap between tokens.
- **On a real remote node, the WAN round trip dominates**: 10-60 ms at home,
  more through a relay. That figure is estimated, not measured; there is no
  second site here.
- **Python can carry a tunnel's bytes.** A plain asyncio relay moved about
  2 GB/s, far above any home upload. Framing and per-stream flow control will
  cost some of that, but not two orders of magnitude.
- **The WireGuard figure is a worst case.** Both ends encrypt on one kernel, so
  it is not a two-host rate.
- **Windows Defender quarantined `frps.exe` as `Trojan:Win32/Kepavll!rfn` the
  moment it was unzipped.** This counts against shipping frp to a Windows
  root. The measurement ran frps in WSL instead, with the Windows side as an
  frp visitor.

**Not measured:**
- Tailscale or Headscale. Joining a tailnet needs an account, which is
  outward-facing and was not done.
- DERP.
- Any path with real WAN latency or loss.

---

## 3. Recommendation

### 3.1 Short term: guided Tailscale (narrow, what first)

**Does a better-guided Tailscale path cover most of the five scenarios before
anything is built? Yes.**

| Scenario | Covered? | Notes |
|---|---|---|
| 1. Friend's PC | Yes | Tagged auth key, so the friend needs no account; an ACL |
| 2. Office PC | Technically yes | DERP over 443 through a CONNECT proxy. Subject to the office's policy; an NTLM proxy is doubtful |
| 3. CGNAT | Yes | Relayed when both ends are hard NAT |
| 4. Two buildings | Yes | Usually direct |
| 5. Moving laptop | Yes | Its 100.x address does not change, so the missing re-announcement (N4) never matters |

Three gaps remain:

- model files over the WAN, which no transport fixes;
- a user who will not take a third-party account;
- an office that forbids VPN clients.

The work, in order:

1. **A guide**: `docs/deployment/remote-nodes.md`, or a section of
   `tailnet.md`. It should:
   - **Lead with the subnet-router layout for an install that already exists**
     (call 2): the root host runs Tailscale and advertises its LAN route; the
     remote node accepts routes and joins at the root's *LAN* address. The
     remote node then reaches the root agent's existing `Node.url` (finding 5).
     Its derived advertise address is its own 100.x, because its connection to
     the root leaves through `tailscale0`, and the root dials that back. **Zero
     product changes.** This is reasoned from the code, not measured: there is
     no Tailscale account on this box. It is also unverified for a root in
     Docker on Unraid, where the container's outbound traffic must route to
     `100.64.0.0/10` through the host.
   - Give **an ACL to paste** before the node joins:
     - the remote node may reach only the root on 8079, 8083 and 8080 (8080
       for its apps);
     - the root may reach the node on 8079, 8090-8189 and its tool-driver
       ports;
     - nothing else.
   - Explain **a tagged, pre-approved auth key** for a machine whose owner has
     no account (no expiry, no login), and `--unattended` on Windows.
   - Say **what not to do**: Funnel, port forwards, the public console as a
     substitute.
   - Treat **models on a remote node** honestly: the first launch copies over
     the WAN.
2. **A return-path check at join.** Right after enrolment, control probes the
   announced URL once (short timeout). The 201 carries the result, and the
   installer and the Nodes page print it, in the spirit of *explain a real
   failure, do not predict one*:

   > *This machine joined, but the root cannot open a connection to
   > http://10.0.0.5:8079 (timed out). It is on another network the root
   > cannot reach. Put both machines on Tailscale, then join again.*

3. **"Running but unreachable" as its own state.** Today the root cannot tell a
   NAT'd node from a dead one: its only node→root traffic is the public bundle
   pull. Give the pull an optional node token (or add a signed heartbeat) so
   the root records *last heard from*. A node heard from, whose probe fails, is
   then an Issue that names the cause and the fix, not *down: timed out*. This
   follows the failures-must-inform rule.
4. **Say which network each node's address is on.** Show the address the root
   actually dials and its class: LAN (RFC 1918), tailnet (`100.64.0.0/10`,
   `fd7a:115c:a1e0::/48`), public, or loopback. This follows settings-never-lie.
   Where a Tailscale interface exists, the Reach switch and `--advertise`
   propose it beside the LAN address.

Items 2-4 are small and touch `control.yaml` (one field on the enrolment
response, one on `Node`). The address-announcement retry
([agent#8](https://github.com/eugene-plexus/agent/issues/8)) is a defect on
any install and is filed separately.

### 3.2 Long term: a node-held tunnel in the agent (open)

If a real install cannot or will not use a mesh, this is the option that needs
no account and no port on any node. The shape below follows the prior art in
§6: Rancher's remotedialer, Kubernetes Konnectivity, Teleport's reverse
tunnel, Tailscale DERP, and the yamux and chisel designs.

- **Agent to agent only.** A remote node's agent holds one WSS connection to a
  *hub*: the agent on the gateway's host, normally the control host. Gateway and
  control never see the tunnel. For a tunnelled node, the hub serves a
  loopback relay URL, `…/v1/relay/<node>/<port>/…`, and they dial that. The
  tunnel stays inside one component, so "components share schemas, not code"
  holds. It is the existing `node:<name>` hop with a second transport.
- **The hub is a byte relay, not an authority.**
  - Tokens stay end-to-end: addressed to `node:X` and verified at X, exactly
    as today. The hub checks only that a caller's token names X before
    forwarding.
  - The node allowlists what may be opened: its agent, its drivers, its
    tool-drivers. Engines stay on loopback and off the list.
  - **The root computes the relay URL itself and never takes one from the
    node.**
- **The handshake is signed by the node's identity key** (the key that already
  signs announcements), over a fresh server nonce bound to the TLS session.
  Revocation removes the key from the bundle and closes the tunnel.
- **The frames are what the prior art converged on.**
  - `stream_id` + type + length.
  - Frame types OPEN, DATA, END, RST, WINDOW, PING, DRAIN and RESTARTING.
  - **Credit windows per stream**, so one large transfer cannot stall a token
    stream. Konnectivity #881 was exactly that stall.
  - Bulk copies never share the link with inference.
  - Keepalives under 25 s, for proxies.
  - Jittered reconnect.
- **The root must be reachable on 443.** That means a port forward plus the
  entry point's nodes name, which the existing Caddy setup already provides.
  Behind CGNAT it needs a relay in front: Cloudflare (WebSocket),
  Tailscale Funnel, or a VPS. Tailscale has no such limit.
- **Degraded mode.** A dropped tunnel is a node *unreachable: its tunnel to the
  hub closed at T (reason)*. In-flight streams fail as a backend failure before
  the first token (cascade) and truncate after it, which is R2.5's rule
  unchanged.
- **A middle step to consider before building transport:** the agent
  supervises an unmodified `tailscaled` (userspace mode, BSD-3), the same way it
  supervises Caddy, and the operator pastes an auth key once. It is the biggest
  cut in steps that keeps the mesh commitment (call 8). Tailscale's provisioning
  for third-party apps is alpha and single-tailnet, so the key is pasted, not
  minted for the user.

---

## 4. Calls for Troy

| # | Call | Recommendation | Counter-argument |
|---|---|---|---|
| 1 | The short-term remote-node path | **Guided Tailscale** (§3.1): a guide plus the three product checks. No public nodes name, no tunnel yet | It makes a third-party account a prerequisite for a remote node. Coordination outages block new joins (traffic continues), and there were eight partial ones Jul-Oct 2026 |
| 2 | Which layout the guide leads with | **Subnet router on the root host** for an existing LAN install; every machine on the tailnet for a new one | Subnet routes need approval in the admin console and `--accept-routes` on Linux. The root becomes a door to the whole LAN unless the ACL narrows it. Unverified in Docker on Unraid |
| 3 | Build the return-path check, the "running but unreachable" state and the address class (§3.1 items 2-4) | **Yes**, one slice, contract change in `control.yaml` | The probe already says *down*. Item 3 adds an authenticated periodic call and a field. And it diagnoses a setup the guide should already prevent |
| 4 | Make the ACL a required step in the guide, not optional | **Required for any machine whose owner is not you** (scenario 1), recommended otherwise | ACL JSON is the step hobbyists most often get wrong. A broken ACL looks exactly like the NAT problem it was meant to sit beside |
| 5 | The ACL itself is our security boundary for a friend's PC? | **No.** Our tokens stay the boundary (row 3: a stolen worker key buys one machine). The ACL limits what the *friend's PC* can touch on Troy's network, which our auth cannot | — |
| 6 | Models on a remote node | **Accept one WAN copy per model (node-local copy over the tailnet share) for now.** Design "the node downloads from Hugging Face itself" when a remote node is real | 24 GB at a home upload is over an hour, and hours over a relay. The first remote user hits it at once. A node-side download is a second downloader beside the library's |
| 7 | The long-term direction: an agent-held tunnel (§3.2) | **Keep it as the direction, do not build now.** Revisit when a real install cannot or will not use a mesh (a refusal of accounts, an office that forbids VPN clients) | It is the only option with no accounts and no client on any node. Every month on Tailscale only makes "a third-party account" part of the multi-host story. And building it makes the nodes name public (pre-auth surface: TLS + one handshake parser + join), revising "nodes are never public" and the mesh commitment's "the tailnet is the perimeter" |
| 8 | Agent-supervised `tailscaled` as a middle step | **Not yet.** Ship the guide, watch where people trip, then decide | It is the largest cut in steps available without owning transport, and Caddy is the precedent for supervising an unmodified binary |
| 9 | The office scenario | **State plainly that a VPN or tunnel on a managed PC is the office's decision.** The guide says *ask IT*, and nothing is designed to look like web traffic in order to get past a policy | A WSS tunnel on 443 looks like web traffic whatever our intent, and Tailscale's DERP was built to look like WebSockets |
| 10 | The commitment's wording, *"Mesh VPN (Tailscale / WireGuard) for component-to-component auth"* | **Amend the wording now to what row 3 made true**: components authenticate with our own signed tokens on any network, and a mesh VPN is the supported way between networks. Revisit the substance only with call 7 | The commitment is listed as immutable, and changing its words without a decision behind it is the kind of drift that list exists to stop |

---

## 5. What this design does not cover

- **Clients reaching the install from outside** (phones, apps, browsers to the
  gateway or console). That is the entry point and `public_console`, decided on
  2026-10-05 in `single-port-entrypoint.md`.
- **The design of a node-side model download** (call 6), and SMB tuning over a
  WAN.
- **Several hubs or several roots.** Tunnel peering across roots is Teleport's
  RFD 69 problem. A standby root cannot follow today anyway: the follower sends
  no credential and replication requires an operator session (N16;
  acknowledged in `C/dependencies.py:178-183`). Filed as
  [control#5](https://github.com/eugene-plexus/control/issues/5).
- **TLS between machines on a LAN.** Today that traffic is clear text, and
  every internet path in §3.2 requires TLS. Whether the LAN gets it too is
  separate.
- **Corporate proxies that need NTLM or Kerberos.** Tailscale's Windows client
  sends a single Negotiate token, which suggests a multi-leg NTLM challenge
  fails. That is read from source, not measured.
- **macOS** (Tailscale's macOS client is closed source; nothing here was tried
  on a Mac), and Cloudflare Mesh until it supports Windows and Docker.
- **Defects found on the way, filed rather than fixed:**
  - [agent#8](https://github.com/eugene-plexus/agent/issues/8): the address announcement (N4) is not retried
    when the root is unreachable at boot, and is not re-sent when the derived
    address changes. That costs a laptop its route, and costs any node whose
    DHCP lease moved during a power cut.
  - [agent#9](https://github.com/eugene-plexus/agent/issues/9): applying the HTTPS entry point on an enrolled
    worker binds its drivers to loopback (`A/app.py:748-758`). The root's
    gateway then loses them, and nothing says why.

---

## 6. Sources (fetched 2026-10-05)

**Tailscale.**
- v1.102.5, 2026-09-29, BSD-3 client: https://github.com/tailscale/tailscale
- Pricing: https://tailscale.com/pricing
- Ports and DERP: https://tailscale.com/kb/1082/firewall-ports, https://tailscale.com/kb/1232/derp-servers, https://tailscale.com/blog/how-nat-traversal-works
- The DERP proxy path in source: `derp/derphttp/derphttp_client.go`, `net/tshttpproxy/tshttpproxy_windows.go`
- Connection types: https://tailscale.com/docs/reference/connection-types
- Peer relays: https://tailscale.com/docs/features/peer-relay
- Auth keys and tags: https://tailscale.com/kb/1085/auth-keys, https://tailscale.com/kb/1068/tags
- Default allow-all policy: https://tailscale.com/kb/1192/acl-samples
- Unattended Windows: https://tailscale.com/kb/1088/run-unattended
- Coordination server down: https://tailscale.com/docs/reference/coordination-server-down
- Status history: https://status.tailscale.com/history
- Funnel: https://tailscale.com/kb/1223/funnel
- OAuth device provisioning (alpha, single tailnet): https://tailscale.com/docs/features/oauth-apps/device-provisioning
- Issues: #14661, #18017 (DERP throughput); #17698, #20801 (proxies); #18827, #18483 (serve streaming)

**Headscale.**
- v0.29.4, BSD-3: https://github.com/juanfont/headscale
- DERP and registration docs: `docs/ref/derp.md`, `docs/ref/registration.md`

**WireGuard.**
- https://www.wireguard.com/known-limitations/ (no TCP)
- https://www.wireguard.com/quickstart/

**ZeroTier.**
- 1.16.0 licence change: https://github.com/zerotier/ZeroTierOne/blob/dev/RELEASE-NOTES.md
- Pricing: https://www.zerotier.com/pricing/
- TCP relay: https://docs.zerotier.com/relay

**NetBird.**
- v0.80.0, BSD-3 client / AGPL server: https://github.com/netbirdio/netbird/blob/main/LICENSE
- Pricing: https://netbird.io/pricing
- Ports: https://docs.netbird.io/about-netbird/ports-and-firewalls
- Issues: #6021, #5798

**Nebula.**
- v1.11.2, MIT: https://github.com/slackhq/nebula
- Issue #1001 (no TCP)

**Cloudflare.**
- Ports (7844): https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/
- Proxy (#1076): https://github.com/cloudflare/cloudflared/issues/1076
- Buffering and SSE: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/
- 125 s / error 524: https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/
- Connection limits: https://developers.cloudflare.com/fundamentals/reference/connection-limits/
- Service tokens: https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- Mesh: https://blog.cloudflare.com/mesh/

**Reverse tunnels.**
- frp v0.71.0: https://github.com/fatedier/frp
- rathole: https://github.com/rapiz1/rathole
- ngrok free plan limits: https://ngrok.com/docs/pricing-limits/free-plan-limits/
- ngrok TCP endpoints: https://ngrok.com/docs/universal-gateway/tcp/
- OpenSSH on Windows: https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-overview

**IPv6 and certificates.**
- https://stats.labs.apnic.net/ipv6/XA
- Google's IPv6 statistics
- RFC 6092
- Let's Encrypt ending client authentication: https://letsencrypt.org/2025/05/14/ending-tls-client-authentication

**Prior art.**
- https://github.com/rancher/remotedialer
- https://github.com/kubernetes-sigs/apiserver-network-proxy (#881, #180)
- https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/1281-network-proxy
- Teleport RFD 69: https://github.com/gravitational/teleport/blob/master/rfd/0069-proxy-peering.md
- Tailscale `derp/derp.go`
- https://github.com/jpillora/chisel
- https://github.com/hashicorp/yamux/blob/master/spec.md
- https://github.com/erebe/wstunnel
- `websockets` keepalive, memory and proxies: https://websockets.readthedocs.io/en/stable/topics/
