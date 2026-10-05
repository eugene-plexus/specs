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

> **▶ Scope narrowed by Troy the same day: files, not inference.** *"I'm not
> specifically interested in out of LAN inference."* What he wants is
> Workbench on the server using the file helper on a remote box. **§7 is the
> answer to that question, and it does not need Tailscale or a tunnel.** The
> file path already runs entirely on connections the node opens; what is
> missing is a public route to the root for node traffic only, and a
> files-only kind of node. §7 also covers:
>
> - the name (**Job Site**, Troy's; §7.1);
> - whether to split it into its own install;
> - whether it is MCP (it is not);
> - Troy's question of whether Workbench belongs on the server at all;
> - planning for a hundred tools and Windows' own MCP connectors, which argues
>   for carrying MCP between the box and the root before a fifth tool (§7.8);
> - membership is not access: Eugene's owner manages which machines are in
>   the Plexus, and only a site's owner grants its tools (§7.11).
>
> §0-§6 stay as the analysis for inference across networks, and as the
> inventory behind §7.

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

---

## 7. Files only: Job Sites, machines outside the LAN

**The narrowed question (Troy, 2026-10-05).** Workbench runs on the server
(the NAS). Troy wants it to use the file helper on a remote box, one that is
not on the NAS's network. Inference stays on the LAN.

### 7.1 A name

Troy has been calling it *"Workbench's local MCP server"*. Today its names
are plain:

- the console says **Files on your machines**;
- the code says *node file helper*;
- the design is [`node-file-helpers.md`](node-file-helpers.md).

**Job Site** (Troy, 2026-10-05; recommended over the first proposal, *Job
Box*). Workbench is the shop. Each machine a person works on from it is a job
site: the crew goes out to it from the shop. That fits what Troy wants it to
be (§7.9): one person, several machines of their own, worked on from one chat.

| Name | Where | Meaning |
|---|---|---|
| **Job sites** | Workbench and the design docs | *your machines*; *Add a job site* is joining one |
| **Files on your machines** | The console | Unchanged, under Troy's rule that keeps workshop names to Workbench |
| *node file helper* | The code | Unchanged until the protocol change in J6 renames it |

*Job Box* named the component on each machine, the lockable chest kept at the
site. One name is better than two: people think in machines, not components.
The workshop list in `workbench.md` §6 still fits around it: **work orders**
can later be sent out to job sites. Two minor costs:

- *site* also reads as *web site*;
- to an MSP, *site* means a customer's location. That is apt rather than
  confusing.

### 7.2 What it is: not MCP

A bounded custom protocol of four tools, each a `{tool, arguments}` command:

- `inspect`;
- `list_directory`;
- `read_text`, up to 32 KiB;
- `write_text`, up to 8,192 characters, hash-checked.

**One operation, end to end:**

1. **Workbench** turns the tools into function tools for the model, each call
   approved by the person. It posts the call to control's
   `/oidc/node-helpers/execute` with its own client credential and the
   person's (`W/node_folders.py`; `C/routes/node_helpers.py:237-309`).
2. **Control** checks the grant and queues the job. It hands the job to the
   box's next poll, and checks the grant again before the result is released
   (`C/node_helpers.py:118-186`).
3. **The box's agent** claims the job. It hands the job to the helper over
   loopback with a separate random credential. The helper is a stdlib HTTP
   worker in a restricted OS account (`A/node_file_helper.py:234-299`;
   `A/_node_file_helper/__main__.py`).

**Why it must not become an MCP server on the box.** Workbench does speak MCP,
but as a client of network MCP servers (C5a, `workbench-mcp.md`). An MCP
client *dials* its server, which brings back exactly the problem in §0. The
pull through control is what keeps the box undialled. If any MCP client
should ever use the Job Site, the MCP endpoint belongs at the root, in front of
the queue (call J6).

### 7.3 Nothing on its path dials the box

| Step | How it reaches the box | Anchor |
|---|---|---|
| Turn file support on | A replicated setting, delivered in the answer to the box's own poll; the agent then installs and starts the helper | `C/routes/node_helpers.py:105-111`; `A/node_file_helper.py:144-200,285-286` |
| Register a folder | An `inspect` job the box claims through the same poll | `C/routes/node_helpers.py:114-180` |
| A read or write from Workbench | A job, as above | `C/node_helpers.py:118-186` |
| Its trust bundle | The box pulls it every 60 s (N3) | `A/app.py:541-577` |
| "Available" | The box polled within 25 s (`ONLINE_SECONDS`); **the probe is not consulted** | `C/node_helpers.py:26,103-116` |

**A node with no recorded address is already skipped** by:

- the probe, which reports *no url recorded* (`C/nodes_client.py:145-146`);
- the trust push (`C/trust.py:212`);
- the gateway's node map (`G/routing.py:1074-1080`);
- control's install views.

So of §0's twelve root→node connections, **the Job Site needs none**, and most
of what an outbound-only node needs exists already.

**What is missing:**

- **The box cannot reach control from outside.** Control's port is
  LAN-only. The entry point's nodes name must name its source networks
  (`A/entrypoint.py:205-206`), and it routes control's whole API, sign-in and
  admin included (`:546-547`).
- **The box would announce its own LAN address.** It derives it from the
  socket (N1), and the root would then dial that address and report *down*.
- **The helper's root client hard-codes `trust_env=False`**
  (`A/node_file_helper.py:272-274`). That overrides `client_for`'s
  per-address rule, so a network that forces a proxy blocks it.

### 7.4 The proposal: a node-only public route and a files-only node

1. **A node-only public mode for the nodes name.** `public_nodes: true`, with
   a risk acknowledgement like `public_console`'s. From any network the name
   answers exactly these, and refuses everything else with one sentence
   saying where the console is:
   - `POST /v1/nodes/enroll`;
   - `GET /v1/trust/bundle`, which becomes token-gated (see 7.5);
   - `POST /v1/node-helpers/poll`;
   - `POST /v1/node-helpers/operations/{id}/claim` and `…/result`.

   Behind NPM this is the setup Troy already runs: NPM forwards the name to
   the entry point in proxy mode.
2. **A files-only node.** Row 3's join tokens already carry `grants`; add a
   `files` role.
   - **Joins through the public route may only take this role.**
   - The node records no address. The root refuses one if offered. The agent
     does not derive or announce one.
   - It gets no gateway grant, and no runtimes may be declared on it.
   - The library run-operations poll (N7) is off.
   - Its status is *last contact N s ago*, from its authenticated poll, not
     *down: no url recorded*.
   - A console hop to it says *this machine only connects out; its files are
     under People*.
3. **The helper's client honours proxy settings** for a root URL that is not
   on the local network: drop the explicit `trust_env=False`.
4. **The join command for an outside machine** is the existing installer with
   one more flag, roughly:

   ```
   install.ps1 -Join https://nodes.example.com -Token … -NodeName … -FilesOnly
   ```

**Contract changes:**

- `control.yaml`: the `files` grant, `Node.lastContactAt`, and an
  address-less enrolment.
- The entry point's settings gain `public_nodes`.
- No change to Workbench, and none to the helper protocol.

**Performance.**

- Each operation is two or three round trips over a poll the box already
  holds open (8 s), so one or two internet round trips plus the proxies:
  roughly 100-300 ms (estimated, not measured).
- `JOB_SECONDS` (20 s) is the ceiling.
- Payloads stay well inside Cloudflare's limits (125 s to first byte; 100 MB
  requests).

### 7.5 Security

- **The box listens on nothing public.** Its agent and helper stay on
  loopback.
- **What the internet can reach before authentication:**
  - the join-token check on enrolment;
  - token verification on the helper routes;
  - the bundle read.

  The bundle is public today, and it lists every machine's name, public key,
  grants and revoked session ids. On the public route it should require a
  node token. A revoked node then cannot pull it, which is correct.
- **A leaked join token** lets someone on the internet join a machine within
  the token's 15 minutes. Through this route it can only be a files-only,
  address-less node. It is visible under People, it starts disabled, and it
  gets only folders the operator registers on it. **The rule that public
  joins are files-only is what stops a rogue node announcing an address and
  being sent prompts.**
- **A stolen box key** reaches, from anywhere, the bundle and that box's own
  helper jobs. That is narrower than the same key on the LAN (row 3: the
  library catalogue and topology too). Revoking it is one step.
- **A compromised root** reaches every folder registered on every helper,
  within its grants. This is unchanged by the route.
- **Rate limits** are needed on enrolment and on the poll from public
  sources. The existing per-node bound of 8 jobs limits a stolen key's queue.
- **Cloudflare.** If the nodes name is proxied (orange cloud), Cloudflare
  terminates TLS and sees file contents, as it already sees Workbench chats.
  DNS-only (grey cloud) keeps it out, where NPM is reachable directly
  (call J7).

### 7.6 Its own install, or a role on the node?

| Problem | Separate install | Files-only node (7.4) |
|---|---|---|
| Root unreachable from the box | Same: needs the public node-only route | Same |
| False *down*, probe timeouts, gateway and console noise | Gone, because it is not a node | Gone: no address, so nothing dials it |
| A leaked join token | Scoped to file jobs by construction | Scoped by rule: public joins are files-only |
| Proxy; Cloudflare seeing content | Same | Same |
| **What sits on the box owner's PC** | **One unprivileged service that touches only folders the owner shared, with no listener at all** | The full agent: a privileged supervisor that can install and run software. The role switches that off, but it is installed |
| Cost | A new identity type at control, a second installer and updater, its own service-account setup, a third copy of the folder code (`folder_io.py` is already in the agent and Workbench, with a drift check). It also reverses Troy's 2026-10-04 call of *one installation, one enrollment* | Small: mostly 7.4 |

**Recommendation:**

- **Troy's own remote box:** build the files-only node.
- **Someone else's PC** (a friend, or an MSP customer, whose owner is
  trusting the install): the split earns its cost. *"Eugene can read the
  folders I shared"* is an easier ask than *"Eugene's supervisor runs on my
  PC"*.

The role's surface is exactly what a standalone Job Site helper would implement, so
the split can follow without rework (call J5).

### 7.7 Why the field runs the interface where the files are

Troy: *"Claude Code... Codex... Hermes... OpenClaw... everyone else runs the
interface where the files are instead of splitting them up. There has to be a
good reason for that."* There are five, and the first is this whole document:

1. **Every connection leaves the user's machine.** A local agent dials the
   model, which works through any NAT, proxy or CGNAT. A central interface
   reaching into a personal machine needs a connection in the other direction
   (§0). The Job Site survives only because it was built as a pull.
2. **Authority stays with the person.** A local agent runs as you, while you
   are there. A central service that holds standing grants into many
   machines is one target that opens all of them.
3. **Real file work needs a shell, search, git and builds.** Those cannot be
   brokered safely across machines. Four bounded text tools will always be a
   thin subset of what Claude Code does on the same folder.
4. **A task is hundreds of small operations.** Each crosses three machines
   here, and none crosses any for a local agent.
5. **The approval belongs where the person and the files are.** Here, the
   person, the interface and the files can be on three machines.

The cloud agents confirm the pattern. Claude Code on the web and Codex cloud
copy the repository to where the agent runs; neither reaches back into your
PC. Desktop chat apps (Claude Desktop) run their file servers locally, beside
the interface.

**What it means for Workbench.** Putting it on the server was right for what
it was built to be:

- chat for everyone, from any device;
- one key held server-side;
- history kept centrally;
- several people;
- the small-business case.

That is the shape of every server-hosted chat UI (Open WebUI, LibreChat,
ChatGPT), and none of them reach into a PC's folders either. **The unusual
move is a central interface working on files on a personal machine.** It
pays for itself in exactly one case: **the files are on a machine you are not
sitting at** (your phone, asking about a document on the home PC). There are
three placements, and only the last pays this document's cost:

| Where the files are | Interface | Cost |
|---|---|---|
| On the server | Central Workbench + C6 host folders | None. Works today, no network hop |
| On the machine you are sitting at | An agent on that machine, pointed at Eugene's gateway: Claude Code (`/v1/messages`), Codex (`/v1/responses`), OpenCode, or Workbench installed there | Inference must be reachable from that machine: on the LAN today, from outside through the entry point's opt-in inference name and a client key |
| On a machine you are away from | Central Workbench + the Job Site | §7.3-7.5 |

**Troy's brief for Workbench also bears on this:** *"it can not have access to
anything in Eugene that any other harness wouldn't have."* Today the Job Site
is reachable only through an Eugene-specific API under `/oidc`, which only
Workbench calls. A remote MCP server at the root would be the
brief-respecting face for it, usable by any MCP client:

- the MCP endpoint at the root, in front of the existing queue;
- OAuth through Eugene sign-in, which the root already provides.

That is a design of its own (call J6).

### 7.8 Planning for many tools

Troy, the same day: *"We only have 4 file tools today. That could be 100 next
year. Even Windows is planning to grant MCP access to system settings and
tools. I want to make sure that we're set for that more controlled local
future."*

**What Windows has shipped.** It is a preview, in Windows 11 Insider build
26220.7344 (2025-12-05):

- native MCP;
- an **on-device registry (ODR)** for MCP servers;
- two built-in **agent connectors**, File Explorer and Windows Settings.

On File Explorer, agents *"manage, organize and retrieve local files on a
user's device with their consent"*. Connectors in the registry are *"contained
in a secure environment with their own identity and audit trail"*. The post
says nothing about remote access. Source:
https://blogs.windows.com/windows-insider/2025/12/05/announcing-windows-11-insider-preview-build-26220-7344-dev-beta-channels/

**What changes if the Job Site is to carry that future.**

1. **The protocol should be MCP, before the fifth tool.** Today the four
   tools are named in four places:
   - Workbench's tool definitions;
   - control's broker;
   - the agent's validation;
   - the helper.

   So each new tool is a release of three repos. MCP already provides what a
   growing tool set needs:
   - discovery (`tools/list`, `list_changed`);
   - schemas and annotations;
   - progress;
   - cancellation.

   So the box↔root channel should carry MCP messages, and the four file tools
   become **one MCP server on the box**, Eugene's own. Other servers sit beside
   it: ones the owner adds, and Windows' own connectors through the registry.
   A new tool is then a new server on the box, with no Eugene release.
2. **Policy has two layers, and the box's is final.**
   - **The root** decides what the install allows: people, grants, approvals.
   - **The box** decides what is exposed at all: which servers, which tools,
     read-only or write. Default deny.

   The box's layer is the owner's, on the owner's machine, and Windows'
   connectors already carry their own consent and audit. The Job Site should
   meet Windows as a local agent with its own identity, so Windows' consent
   prompts and audit name it rather than "Eugene".
3. **The channel grows from a queue to a held connection, at the message
   level.**
   - Request/response tool calls fit today's long poll.
   - MCP's server-initiated messages (`list_changed`, progress, elicitation)
     and long-running tools want a connection the box holds open both ways:
     a WebSocket from the box carrying MCP JSON-RPC.
   - That is §3.2's tunnel, **but carrying messages rather than bytes**, so
     the root sees each call and can authorize, log or refuse it, which a byte
     tunnel cannot.
   - Today's limits are file-tool limits and become per-tool: 32 KiB reads,
     70 KB results, 20 s per job, 8 jobs per node.
   - Build the held channel when the first feature needs it.
4. **The root presents the box's servers as one remote MCP endpoint** (MCP over
   HTTP, OAuth through Eugene sign-in). Then Workbench, Claude Desktop, Claude
   Code, Codex and Open WebUI all reach node tools the same way, which is what
   Troy's brief for Workbench requires (§7.7). It is the tool-side twin of the
   gateway's *one endpoint for every model*.
5. **It dissolves the placement question in §7.7.** With MCP servers on the
   box:
   - an agent sitting at the box uses them directly and locally;
   - central Workbench uses the same servers through the root.

   One box-side piece serves both placements, so server-or-client stops being
   either/or.
6. **The blast radius grows with the tool list.** With system tools exposed,
   a compromised root or Workbench session reaches every box's exposed tools.
   So:
   - default deny on the box;
   - tools marked destructive or system-level need approval **on the box**,
     or the owner's standing pre-approval there;
   - an audit log on each box that its owner can read;
   - the box-side piece never runs inside a privileged supervisor, which
     moves call J5 toward a standalone, unprivileged Job Site helper.

### 7.9 What Troy wants it to be (later the same day)

Troy's reply:

> - I want one user to be able to access multiple machines under their
>   control
> - Many people who are interested in local LLM hate Cloud services
> - Multiple machine control from a central chat window enables file copy
>   and other functions that usually require cloud based services, but a
>   local user might want to handle independently.

That answers J2, which asked whether he would be at the box or away from it:
**away from it, and many machines at once.** Claude Code and Codex work on the
one machine they run on, so this is the case only a central interface can
serve. It is also the case that justifies §7.7's unusual split. It adds three
requirements, set out in 7.10.

### 7.10 Three requirements and what they change

1. **One person, several machines of their own.**
   - **Today the operator joins every machine** and grants every folder,
     their own included. A site should belong to a person, and its tools
     should be used only by explicit grant. Troy took this further the same
     day: Eugene's owner gets no access at all (7.11).
   - **Who may add a site** is call J9: operator only, as today, or any
     signed-in person for their own machines.
   - A files-only site keeps self-service small. It has no inference, no
     address, and nothing it can be told to run.
2. **No cloud in the path.** This audience distrusts cloud services, so the
   feature must work with no third party at all.
   - That rules out Tailscale for this feature: it needs Tailscale's cloud
     coordination. Headscale remains for anyone who wants a mesh.
   - It rules out Cloudflare's proxy, which decides J7.
   - The route in 7.4 is already self-hosted: the owner's router forwards one
     port to the root's entry point.
   - Even the public CA and the DNS name can be optional. The join command
     can carry the root's certificate fingerprint, so a site pins the root at
     join and reaches it by bare address, using the entry point's own CA.
   - Only a root on CGNAT needs anything outside the home: a relay the owner
     runs (a VPS), or IPv6.
3. **Operations across machines from one chat**: copy a folder from the
   desktop to the NAS, and the other jobs people otherwise hand to Dropbox,
   OneDrive or Google Drive.
   - **Neither site can dial the other, so a copy goes site A → root →
     site B.** It is streamed and never stored at the root. Its speed is the
     slowest of A's upload, the root's link and B's download. Two sites on the
     root's own LAN copy at LAN speed.
   - **It needs what the four tools never did:** chunked, resumable,
     hash-verified transfer (the library's downloads already work this way),
     on a stream of its own so a copy never stalls a chat. That is the held
     channel of 7.8, point 3, now with a feature that needs it.
   - **A tool spanning two sites lives at the root** and drives each site's
     own tools. Policy is checked at both ends: A must allow the read and B
     the write, and each site's own rule is final (J8). The approval shows
     both sites and both paths.
   - **Contents never enter the replicated log.** This is already the
     helper's rule.
   - **On-demand operations only.** Continuous sync, with its conflicts,
     deletions and versions, is a separate product.
   - **The root's reach grows to moving data between all of a person's
     machines,** so a compromised root costs more. That is why J8's
     site-final policy and each site's audit log are not optional.

### 7.11 Membership is not access

Troy, the same day: *"Maybe Eugene doesn't automatically grant the owner
access to all files on Job Sites. Maybe instead the owner can help a Job Site
join or leave the Plexus, but rights to the Job Site tools must be explicitly
given to a user before they can be used?"*

**What the code does today** (control `b667699`):

- **Nobody has access by default.** A folder's `ownerAccess` starts at
  `none` (`C/routes/node_helpers.py:45-48`).
- **The owner is the one who grants.** The owner gives themselves access in
  one click (`PATCH …/folders/{id}`, `:51-69`; `C/node_helpers.py:61-70`).
  The owner also sets every person's grants (`PATCH /v1/people/{id}`
  `helperGrants`, owner-only, `C/routes/people.py:56,159-185`).
- **The owner can become anyone.** The owner sets any person's password
  (`PUT /v1/people/{id}/password`, `:196-206`), signs in as them, and uses
  their grants.
- **Workbench can show the owner what was read.** Its `ownerReadsChats`
  setting (W4, off by default) lets the owner read people's chats, and those
  chats hold every file result a person approved (`W/api.py:203-215,
  464-470`).

So *the owner is not granted access* is true today, and means nothing while
the owner is the one who grants, can become any person, and can read their
chats. **The rule needs five companions:**

1. **A job site belongs to a person, and only that person grants its tools,**
   including to themselves. Eugene's owner manages membership:
   - invite a site to join;
   - remove it;
   - see that it exists and whether it is online.

   The owner does not see its folders, their contents, or who holds grants.
   `ownerAccess` goes, and `helperGrants` stops being an owner-only write.
2. **The invitation names the person, and the person confirms at the
   machine.** Eugene's owner helps by minting an invitation for that person.
   At the machine, the join asks that person to sign in with their own
   password. The site records its owner from that, so it is bound by presence
   plus the person's own credential, never by anything the owner holds.
3. **The site keeps its own list (J8) and refuses anyone not on it.** Then
   editing the root's state is not enough to get in.
4. **Eugene's owner cannot become a person.** Two possible shapes:
   - the owner may disable or remove an account, but not set its password;
   - an owner's password reset suspends that person's site grants until they
     confirm again at a site (call J12).
5. **`ownerReadsChats` never shows a job-site result.** The owner sees that a
   tool ran on which site, not what it returned (call J13).

**Leaving needs no one's permission.** Eugene's owner can remove a site, which
revokes it at once. The site's owner can leave from the machine
(`POST /v1/node/unenroll`, which exists).

**The human is two people in the model.** The admin role is the passphrase
session; using sites needs a person account. A solo owner makes one for
themselves and owns their own sites. This is a little friction for a solo
install, and it is also what makes the MSP case honest: the MSP runs the
Plexus, each employee owns their PC's job site, and the MSP cannot read it.

**The limit, stated plainly.** Items 1-5 stop Eugene's owner *through the
product*. A compromised root, or an owner willing to edit the root's state
and keys directly, can still mint a sign-in for "Alice", and the site accepts
it, because the site trusts the root to say who Alice is. Closing that needs
a credential the root cannot mint: each person's own key, such as a passkey,
registered at their site, with tool calls signed by it (call J14). It is
end-to-end authorization and a design of its own.

### 7.12 Calls for Troy (files scope)

| # | Call | Recommendation | Counter-argument |
|---|---|---|---|
| J1 | The name | **Job Site** (Troy's, recommended): *Job sites (your machines)* in Workbench; the console keeps *Files on your machines* | Two words for one thing across the console and Workbench, softened by the S8 rule that pairs a workshop name with its plain meaning. *Site* also reads as *web site* |
| J2 | Which use is this, really: at the box, or away from it? | **ANSWERED (Troy, 2026-10-05): away, and many machines at once.** One person controls several of their own machines from one central chat window, including operations across them (§7.9). That is the case only the central interface can serve, so J3-J5 are needed | — |
| J3 | A node-only public mode for the nodes name (`public_nodes`) | **Yes**, limited to the five paths in 7.4, with an acknowledgement | It is the first internet-facing node surface. The enrolment, token and bundle parsers become reachable by anyone. The rule *nodes are never public* (2026-10-05) is narrowed |
| J4 | A files-only node: no address, no inference, no run jobs, status from last contact. Public joins can only take it | **Yes**, as one slice with J3 | A second kind of node, which every screen showing nodes must handle |
| J5 | A standalone Job Site helper install now | **Not yet, but build toward it** (revised for 7.8). Ship the files-only role first. Build the box-side piece as a self-contained, unprivileged local MCP host with its own policy, which the agent supervises today and which can ship alone when someone else's PC is the case | For anyone else's PC the owner's trust argument is strong from day one. With system tools coming, a piece shipped inside a privileged supervisor is the wrong shape even on Troy's own box |
| J6 | MCP between the box and the root, and an MCP endpoint at the root | **Yes to the first, now, before a fifth tool** (revised for 7.8): the four tools become Eugene's own MCP server on the box. The root's endpoint for other clients follows as its own design | Eugene takes on MCP's spec versions and its server-initiated features, which the long poll does not carry. The four bespoke tools work today, and their limits are tight on purpose |
| J7 | Third parties in the path (revised for 7.10) | **None.** The nodes name is DNS-only, or a bare address with the root's certificate pinned at join. No Cloudflare proxy, no Tailscale | It exposes the home IP and gives up Cloudflare's DDoS shield. Pinning means every site joins again if the root's CA changes, so a rotation path is needed before it ships |
| J8 | Where policy is final | **On the site**: default deny per server and per tool; destructive or system tools need approval there or the owner's standing pre-approval; each site keeps an audit log | Approval on a machine nobody is sitting at blocks the *away from it* case, which is the case (J2). In practice that use gets read-only tools unless the owner pre-approves more |
| J9 | Who may add a job site | **Any signed-in person, for their own machines**, as files-only sites they own (7.10, item 1). An operator-approval setting is available for installs that want it | A household member can attach any PC to the install. Join tokens become per-person, and the People page gains states. Today only the operator joins machines, which is simpler to reason about |
| J10 | Cross-site copy as the first tool spanning machines | **Yes, after J6.** Streamed through the root and never stored there, resumable and hash-verified, on its own stream, with policy checked at both sites | It is the first feature that moves bulk data through the root, so the root's bandwidth and the cost of a compromised root both rise. It also invites requests for continuous sync, which is a different product |
| J11 | Membership is not access (Troy's proposal, 7.11) | **Yes.** Eugene's owner invites, removes and sees status. Only a site's owner grants its tools, themselves included. `ownerAccess` and owner-written `helperGrants` go | A solo owner needs a person account to use their own machines. The owner can no longer fix a person's broken grants for them |
| J12 | The owner setting another person's password | **Remove it.** The owner may disable or remove an account, but not set its password. If a recovery path is needed, an owner's reset suspends that person's site grants until they confirm at a site | People without email have no self-service recovery, so a forgotten password means a new account and re-granting |
| J13 | `ownerReadsChats` and job-site results | **Never show a job-site result to the owner**: show that a tool ran and on which site, not what it returned | A business that turned it on to supervise work loses sight of exactly the work done on files |
| J14 | Person-held keys checked at the site (end-to-end) | **Later, its own design.** Items 1-5 of 7.11 first | Until then, a compromised root reads every site anyone has been granted, and a site's owner is trusting the root's word for who is asking |

**What this does to §4.** Calls 1, 6 and 7 (inference across networks,
remote models, the tunnel) lose their urgency. Call 3's checks become mostly
J4's *last contact* status. Calls 9 (offices) and 10 (the commitment's
wording) stand unchanged.
