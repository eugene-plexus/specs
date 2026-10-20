# TLS between machines

**Status: designed 2026-10-20. Troy took every call the same day: LT-C1 8083
(no new port), LT-C2 yes, LT-C3 later, LT-C4 yes.**

Troy, 2026-10-20: *"Let's make TLS between machines change #1. This is more
important than what we learned from DeepInfer."* He also agreed to the route:
all traffic between machines goes through each node's agent, on one TLS port.

The facts below were read from the code on 2026-10-20 at these heads:
- agent `95ee562`
- control `2d153b4`
- gateway `6a614a2`
- inference-driver `9ef3e7d`
- library `c5c5c31`
- tool-driver `9fcc047`
- workbench `a1f6151`
- site-host `097a89c`
- ui `47ff152d`

Path prefixes are as in `remote-nodes.md` Appendix A, plus `S/` for site-host.

## 1. What crosses the LAN in clear text today

Every connection one machine of an install opens to another is `http://`, with
two exceptions:
- **Job Sites** reach the root over HTTPS, pinned to a key list the root signs.
- **A container root's "nodes name"** goes through Caddy.

Both are container-only (`A/entrypoint.py:1160`). URLs to other machines are
built as `http` in two places: `format_url` (`A/node_identity.py:197-201`) and
a component's `advertiseUrl` (`A/routes/components.py:92-96`).

`remote-nodes.md` Appendix A lists the connections as they stood on
2026-10-05.

**Re-checked on 2026-10-20:**
- R1-R13 and N1-N16 are still present, with three exceptions:
  - N14 is gone (the file helpers were deleted).
  - N16 now authenticates.
  - R1 gained `/v1/rerank` and `/v1/generate/count`.
- **Ten new connections cross machines.** None of them is encrypted except X2.
  - X1: standby control → active control, every 2 s. Its snapshot carries
    the whole replication set, sealed keys included.
  - X2: site host → root. Already HTTPS with a pinned key.
  - X3: a site-hosting node → control.
  - X4: control → a site's agent.
  - X5: an agent's `/link` pages → control.
  - X6: LS10's 16 MiB chunks → the library owner's agent.
  - X7: a gateway on a worker → control.
  - X8: control → its own nodes name.
  - X9: update-all → every node.
  - X10: the Hosts page → every node, every 15 s.

**What that traffic carries:**
- **Every prompt and every answer** a gateway sends to a driver on another
  machine (R1).
- **Every token, readable while it is valid:**
  - 15-minute service tokens;
  - 5-minute exchanged operator tokens;
  - the client-key checks.
- **Sign-in steps**, through the forwarded `/oidc` and the login routes (N10,
  N12).
- **The replication snapshot,** which holds sealed key material (X1).

**Who must be reachable from other machines today:**
- the agent on 8079;
- control on 8083;
- every inference-driver and tool-driver on its own port, 8090-8189.

These are bound to `0.0.0.0` whenever the node advertises an address
(`A/app.py:810-859`). The gateway, library, site host, standby control and
engines already bind to loopback.

## 2. What this covers, and what it does not

There are two kinds of LAN traffic, and only one of them can be fixed with
Eugene's own keys:

| Traffic | Ends | Who controls both ends | This design |
| --- | --- | --- | --- |
| **Inside the install:** gateway → driver, worker → control, console hops, standby → root, Library uploads | Eugene ↔ Eugene | Eugene | **LT1** |
| **Into the install:** a laptop's Claude Code or Open WebUI → the gateway on 8080, a browser → the console on 8079, a browser → an app, app sign-in redirects | someone's client ↔ Eugene | Only one end | **LT2**, designed separately |

**After LT1 alone, prompts from people's apps to the gateway still cross the
LAN in clear text.** On a business LAN that is most of the prompts.

A client cannot pin a node key. It needs a certificate it already trusts:
either a domain with a public certificate, or Eugene's CA installed on each
device. That is an extension of the container's HTTPS entry point
(`single-port-entrypoint.md`) to every install, and the order is LT-C4.

**Out of scope:**
- **Model files over SMB (R12).** They are opened by the OS, not by Eugene's
  HTTP. Encryption there is a share setting on the file server: SMB 3
  `EncryptData` on Windows, `smb encrypt = required` in Samba. A later check
  could report the share's setting.
- **Job Sites (X2).** They already have TLS through Caddy and stay as they
  are.
- **Tailnets.** WireGuard already encrypts them, and LT1 runs inside it
  unchanged. There is one path, with no special case.

## 3. The design (LT1)

### 3.1 One TLS door per machine: the machine port

**The machine port is 8083 on every node (LT-C1, taken).** Troy wants no new
port. 8083 already exists, and it is already the port for machines only: the
container docs call it "the control root: enrollment and log replication, for
every GPU machine that joins", and no browser uses it.
- **On the root,** the agent takes 8083. Control moves behind it to a
  loopback port, the same way a standby control already picks the first free
  port from 8083 (`A/standby.py:39,138`).
- **On a worker,** 8083 is free today.
- **The published set does not change.** A root publishes 8079, 8080 and
  8083, as now. A worker stops exposing its driver range, 8090-8189, to the
  LAN, and exposes 8079 and 8083 instead.
- **The agent's 8079 stays as it is** for the browser, and moves to TLS in
  LT2.

The machine port forwards to this machine's own listeners on loopback:

```
https://<node>:8083/agent/...                 → the agent's own API
https://<node>:8083/control/...               → control (on the root)
https://<node>:8083/library/...               → the library, where this node holds it
https://<node>:8083/gateway/...               → a gateway on this node
https://<node>:8083/drivers/<name>/...        → an inference-driver or tool-driver on this node
```

**What the machine port does:**
- **Resolves only against this node's own topology.** It never asks control
  where a component is, so inference keeps working with the root down (M5's
  rule). Today's `/api/proxy` breaks that rule for remote targets
  (`A/install_proxy.py:223-261`).
- **Streams the request body** with no 30 s write timeout. Today's proxy
  buffers up to 32 MiB in RAM (`A/routes/proxy.py:456-478`), which is wrong
  for 16 MiB generate bodies and LS10 chunks.
- **Translates no tokens.** Every caller already sends a token addressed to
  the target (`svc:gateway` for `node:X`, `svc:control`, `svc:agent`), and the
  target component checks it, as it does now. The machine port adds
  encryption and the node's identity. It does not add a second authority.

### 3.2 Keys and pins: no CA

**Each node gets a TLS key of its own.** It is ECDSA P-256, generated by the
agent beside the three it already has (`A/node_identity.py:398-443`). It is
stored in `node.yaml` (mode 0600) and comes with a long-lived self-signed
certificate.
- It is a separate key so that TLS never signs with the key that signs
  address announcements or tokens.
- P-256 because every TLS stack takes it.

**The pin** is the SHA-256 of that key's SPKI, the same form Job Sites use
(`C/root_tls.py:58-66`).

**How a node registers its pin:**
- The pin rides the existing address announcement (N4,
  `A/enrollment.py:375-432`), which the node signs with its Ed25519 signing
  key.
- Control verifies the signature against the key it already holds
  (`C/applied.py:220-260`), and records the pin and the machine URL in the
  node's record.
- A machine on the LAN cannot register a pin for a node, because it does not
  hold that node's signing key.

**How pins are published:**
- Control publishes every node's machine URL and pins in a list signed by the
  root's identity key.
- This extends the list Job Sites already fetch (`ep-root-tls+jwt`,
  `GET /v1/trust/tls`, `C/routes/control.py:397-424`) rather than adding a
  field to the trust bundle, which older nodes might refuse.
- Every node pinned the root's identity key at join, so the chain is: root
  identity key → signed list → pin → TLS.
- Agents fetch the list every 60 s with the bundle, keep it on disk, and give
  its path to their children.

**How a caller checks a pin:**
- Python's `ssl` has no certificate-verification callback, so the pin is
  checked right after the handshake and before any request byte is sent.
- That is what site-host's pinned client already does with a custom httpcore
  network backend (`S/root_link.py:199-228,272-315`).
- That backend moves into the platform `_http.py`. For an `https` URL whose
  host and port belong to a node on the list, it requires that node's pin.
  Every other URL keeps normal certificate checks. There is one place per
  repo, `ssl_context()` and its clients.
- **Names are not checked**, because addresses change with DHCP. The pin is
  the identity.

**Why no CA:**
- A CA needs its private key held at the root, issuance, renewal and its own
  rotation. Warm standby would have to replicate the CA key too.
- Pins reuse what exists: signed announcements, a signed list, and a pinned
  client already proven in Job Sites.

**Rotation:**
- A new key is announced with both pins for an overlap, the listener reloads,
  and the old pin is dropped.
- Removing a machine (CX6) deletes its record, so its pins leave the list and
  every caller refuses it.

### 3.3 Who changes

- **Agent:**
  - the TLS key, the machine port and its forwarding;
  - announcing the pin;
  - `advertiseUrl` and `Node.url` built as `https://<host>:8083/...` once
    the node has a pin;
  - the remote leg of `/api/proxy` (console hops, N8, N15, X6) moves to
    machine ports;
  - the bind rule (3.5).
- **Control:**
  - pins in the node record (a replicated-log entry);
  - the signed list;
  - enrolment over TLS (3.4);
  - its own calls to agents (R6-R9, X4) go to machine ports.
- **Platform `_http.py`:** the pinned backend. It is copied into gateway,
  control, library, inference-driver, tool-driver and site-host. The agent's
  diverged copy gets the same change. Workbench reaches other machines only
  through its own agent (N15), so it needs nothing.
- **Gateway:** nothing beyond `_http.py`. It already uses `advertiseUrl` and
  `Node.url` as opaque bases (`G/routing.py:1186-1192,1533-1537`).
- **UI:** each machine's state on Machines (3.6), and the join command
  carrying the root's pin.
- **Specs:** `agent.yaml` (components and node), `control.yaml` (node record,
  announcement, the signed list), and the docs that call 8083 control's port.
  The template and compose files already publish 8083 and need no change.

### 3.4 Joining

- **Today a LAN join is unpinned.** The worker posts the join token to
  `http://<root>:8083/v1/nodes/enroll` and pins whatever `controlPublicKey`
  the answer carries (`A/enrollment.py:227,272-304`). An impostor on the LAN
  could answer first.
- **With LT1 the join token carries the root's pin.** The console's join
  command and the wizard's pasted code already carry the token, so the pin
  costs the person nothing (`U/lib/joinCommand.ts:82`).
- **The worker enrols over TLS** to the root's machine port and checks the
  pin before sending the token. That closes the trust-on-first-use gap for
  the root's identity key as well.

### 3.5 Turning it on

**Upgrades need no step from anyone:**
1. **The root is upgraded first,** as the rule already says. Its agent makes
   the key, takes 8083 and announces its own pin.
2. **Each worker picks it up when it updates,** by in-app update or update
   all. It makes its key, takes 8083, announces its pin over the existing
   channel (the announcement is signed and public), and fetches the signed
   list.
3. **Callers use TLS to any node that has a pin and can be reached on its
   machine port, and plain HTTP to the rest (mixed).** Machines says which
   is which (3.6).
4. **"Encryption between machines: required".** When it is set:
   - every caller refuses plain HTTP to another machine;
   - control, drivers and tool-drivers bind to loopback on every node, so the
     only doors left between machines are the machine ports;
   - Windows' firewall rules follow the listeners by themselves
     (`A/firewall_follow.py:44-56`).
   - The gateway's client door (8080), the console (8079) and apps stay on
     the LAN until LT2.

**Taken (LT-C2):** an upgraded install switches to "required" by itself once
every enrolled machine has a pin and answers on 8083, with a notice on
Machines. An expert can turn it back off, with a warning. A new install starts
required.

**Old and new machines share 8083 during the switch.** A worker that has not
updated yet still speaks plain HTTP to the root's 8083. Until "required" is
set, the root's 8083 therefore takes both:
- A small switch in front reads each connection's first byte. A TLS
  handshake starts with `0x16`; an HTTP request starts with a letter.
- TLS goes to the machine port's forwarding. Plain HTTP goes to control, as
  it does today.
- Once "required" is set, the plain branch refuses.

Only machines use 8083, so the console's connections never pass through the
switch. That was the objection to sharing 8079.

**A single-HTTPS-port container** already gives workers a TLS door to the
root: the nodes name on 8443, pinned through the same signed list
(`C/root_tls.py`, X8). There, workers reach the root through it, and the root
reaches workers on their 8083.

### 3.6 What a person sees

Machines shows each machine's link to the others:
- **Encrypted**;
- **Not encrypted: Amish_Station runs v0.3.1; update it**, with the Update
  button that already exists;
- **Not encrypted: the NAS can't reach Amish_Station on port 8083
  (connection refused)**, with the fix for that platform.

A wrong pin is refused, and the failure names it: *"Amish_Station's machine
key doesn't match the one it registered. Nothing was sent to it."* That is a
security event in the log, not a retry.

### 3.7 Platforms

- **Windows:** the firewall follows the listener. The TLS stack is Python's
  bundled OpenSSL. `firewall_follow` needs no installer change.
- **Linux and macOS installs** manage no firewall today, so this changes
  nothing there.
- **Containers in bridge mode,** like the Unraid template (`<Network>bridge`),
  already publish 8083, so nothing changes in their settings.
- **Reverse proxies and Cloudflare stay out of machine traffic.** Machines
  dial each other directly. A proxy that terminates TLS would present its own
  key, and the pin check refuses it by design. The one case where a proxy
  holds the certificate, the nodes name behind NPM, is already pinned to that
  proxy's key (X8).

### 3.8 Cost

- **One TLS session per pair of machines,** kept alive by the clients that
  already exist (one HTTP client per instance).
- **One extra loopback hop** on the far side.
- **Inference streams are small events.** Bodies reach 16 MiB on generate and
  LS10 chunks, and X1's snapshot is the largest message.
- **AES-GCM in OpenSSL costs little next to Python's own forwarding.** The
  measurement that matters is whether the far side's forwarding moves:
  - first-token time;
  - tok/s on one stream and on the DI3 sweep;
  - a 16 MiB upload.

### 3.9 What it builds toward

- **The machine port is the door `remote-nodes.md` B.5's tunnel would carry.**
  An agent-held tunnel to the root would forward the same paths over one
  outbound WSS connection.
- **Mutual TLS is later (LT-C3).** Callers would then present their own node
  keys. Two things are not built now:
  - only enrolled machines could open the port at all;
  - tokens could be bound to the connection (RFC 8705), which
    `per-node-token-keys.md` lists as not built.

  Python's `ssl` checks a client certificate only against CAs it has loaded,
  so per-node pins on the server side need each node's certificate loaded as
  an anchor. That is workable, but it is fiddly to keep current as nodes come
  and go. Tokens are encrypted once LT1 lands, which removes the replay risk
  that came from sniffing them.

## 4. Slices

| Slice | What | Risk |
| --- | --- | --- |
| **LT1a** | Keys, pins, the signed list, 8083 as the machine port (the first-byte switch, control behind it) and its forwarding, `https` advertise URLs, pinned callers in every repo's `_http.py`, mixed mode, Machines status | High (auth, transport): one adversarial review |
| **LT1b** | Required: plain refused (the 8083 switch's plain branch closes), the loopback bind, join over TLS with the pin in the join token | High (enrolment, binds) |
| LT2 | Clients and browsers: the HTTPS entry point on every install | Designed separately |

## 5. Acceptance

**Real environment, high risk:** two machines on a real LAN, never the live
install. The core is a canary check:
- **A prompt carrying a unique string** goes through the root's gateway to a
  driver on the worker.
- **Packets are captured on the wire.** `tcpdump` on the container bridge, or
  `pktmon` on Windows (elevated, so ask Troy).
- **The check fails before LT1:** the canary is in the capture.
- **It passes after:** the canary, `Bearer` and `eyJ` are in no capture.

**Sabotage, scoped with `--labels` and restored from a copy:**
- a wrong pin is refused;
- a removed machine is refused;
- with "required" on, a plain URL is refused;
- a node announcing a pin with a bad signature is refused;
- the root stopped: inference to a worker driver continues on the pins kept
  on disk.

**Platforms:**
- a Windows worker joined to a container root, checking `firewall_follow`
  and the bind rule;
- a Linux pair in containers in CI.

**The cost:** first-token time and tok/s with and without the machine port,
on one stream.

## 6. Calls for Troy

| # | Question | Recommended |
| --- | --- | --- |
| LT-C1 | Which port carries machine traffic? (Revised: Troy wants no new port.) | **Taken: 8083 on every node.** It is already the port for machines only, and the root already publishes it. On the root, control moves behind the agent to a loopback port. During the switch, 8083 tells TLS from plain HTTP by the first byte, and only machines ever pass through that. Rejected: a new port (one more to publish and proxy), and sharing 8079 (every console connection would pass through the switch). |
| LT-C2 | When does an upgraded install switch to "required"? | **Taken: yes.** By itself, once every enrolled machine has a pin and answers on its machine port,** with a notice on Machines. An expert can turn it back off, with a warning that prompts will cross the LAN in clear text. A new install starts required. |
| LT-C3 | Mutual TLS in LT1, or later? | **Taken: later.** Tokens authenticate every caller and are encrypted once LT1 lands. Mutual TLS adds "only enrolled machines connect" and connection-bound tokens. It is worth doing, but not at the price of delaying encryption. |
| LT-C4 | LT2 (clients and browsers) straight after LT1? | **Taken: yes, designed next.** Without it a business LAN still carries most prompts in clear text. Its first decision is where a certificate comes from on a plain install: the owner's domain and ACME, or Eugene's CA pushed to each device (an MSP can do that by policy). |

## 7. Building LT1a

**Landing (Troy, 2026-10-20: branch only).**
- LT1a and LT1b are built together on the branch **`lt1`**, in worktrees,
  and merged once.
- The steps below are the build order. They no longer have to be inert one
  by one, since nothing reaches `main` until the merge.
- **The one set of checks is at the end, before the merge:**
  - the suites for every touched repo, run by `runner`;
  - the Docker-pair check of record and its sabotage;
  - the Windows platform check;
  - one adversarial review;
  - CI started by hand on `lt1`.
- **Then fast-forward, then `ship.py`.** Rebase onto `main` first if it
  moved. Troy then tests on Edge.

### 7.1 Steps, in landing order

0. **The failing check first:** `scripts/lt1-machine-tls-acceptance.py`.
   - A root (control, plus `agent-a` with the gateway grant and a gateway)
     and a worker (`agent-b`, with an inference-driver over a stub
     OpenAI-compatible engine).
   - A prompt carrying a random canary goes through the gateway to the
     worker, and the check asserts that the canary, `Bearer` and `eyJ` are
     absent from what crossed the wire.
   - **It fails today, and is committed failing.**
   - **The instrument must see the real wire, and one host with a relay
     cannot.** Control refuses a loopback advertise address for a remote node
     (`A/routes/node.py:275`), and a worker that advertises a LAN address
     binds `0.0.0.0`, so a relay cannot stand in front of it.
   - **Recommended: two containers on a Docker bridge network with `tcpdump`
     on the bridge.** That runs in CI on GitHub's Linux runners. A Windows
     worker joined to a container root is the platform check.
   - For the sabotage pass, a man-in-the-middle container on the bridge
     terminates TLS with its own key, and the caller must refuse it.
1. **Contracts (specs):**
   - **The address announcement** takes an optional `tlsPin` (base64url
     SHA-256 of the SPKI) and `machineUrl`. Both are covered by the node's
     signature.
   - **The node record** gains `tlsPins` and `machineUrl`.
   - **The signed TLS list** (`ep-root-tls+jwt`) gains
     `nodes: [{name, machineUrl, pins}]`.
   - **A component** gains `machineUrl` beside `advertiseUrl`. A new caller
     prefers it when the target has a pin, and an old caller keeps
     `advertiseUrl`. That is how mixed mode works with no flag.
2. **Platform `_http.py`, the pinned backend (inert):**
   - It works per connection: a host and port listed in the pins file get a
     no-chain context and the SPKI check before the first request byte.
     Anything else gets `ssl_context()`'s normal verification.
   - It covers both async and sync clients.
   - The file comes from `EUGENE_PLEXUS_MACHINE_PINS_FILE`. With no file,
     behaviour is exactly today's.
   - Tests:
     - a pinned peer is accepted;
     - a wrong pin is refused, with no byte written;
     - an unlisted `https` URL is verified normally;
     - plain `http` is untouched.
   - The `editor` agent copies it into gateway, control, library,
     inference-driver, tool-driver and site-host. site-host has uncommitted
     `_http.py` edits as of 2026-10-20, so those are settled first. The
     agent's diverged copy is changed by hand.
3. **Control (root first, inert until agents announce):**
   - It records pins from a correctly signed announcement as a
     replicated-log entry, and publishes them in the signed list.
   - It refuses a pin whose signature does not verify.
4. **Agent, the turn-on:**
   - **The node's key.** A P-256 TLS key and a self-signed certificate
     beside `node.yaml`, and its pin.
   - **The 8083 front.** A same-process switch on the first byte:
     - TLS goes to a loopback uvicorn with the machine port's routes;
     - plain HTTP goes to a loopback control forwarder, on the root only.
     - Both restore the real peer from the front's map of loopback source
       ports, strip any incoming peer and forwarding headers, and set the
       peer header themselves.
   - **The routes.**
     - `/agent/*` is served in-process, with the real peer in `scope`.
     - `/control`, `/library`, `/gateway` and `/drivers/<name>` go over
       loopback, streamed both ways with no 30 s write timeout.
     - They resolve against this node's own topology only.
   - **On the root, control moves** to a loopback port, the first free from
     8084. Local children are given that URL.
   - **Pins in, pins out.** The agent announces its pin and `machineUrl`. It
     fetches the signed list with the bundle every 60 s, and writes the pins
     file for its children.
   - **Its own calls.** `machineUrl` is served on components and on the
     node, and the remote leg of `/api/proxy` uses machine URLs.
5. **UI:** each machine's state on Machines (3.6).

Then the acceptance of record (§5), the sabotage, a Windows worker joined to
a container root, one adversarial review, and `ship.py`.

### 7.2 Traps found while planning (2026-10-20)

- **A loopback hop makes a remote caller look local.**
  - `peer_of` trusts the peer header only when the immediate peer is
    loopback (`A/peer.py:119-131`, `C/peer.py`).
  - A raw byte pump on 8083 would therefore let any machine on the LAN name
    its own address. That means unlimited guesses past control's sign-in
    rate limit, which is keyed on that address
    (`C/routes/administration.py:49-56`, `C/routes/auth.py:249`).
  - Every hop strips incoming peer and forwarding headers and sets its own,
    as `/api/proxy` already does (`A/routes/proxy.py:627-632`).
- **`/link` pages identify the person by the loopback socket's owner**
  (`A/loopback_peer.py`). That is why the agent's own API is served
  in-process on the machine port: no loopback socket stands in for a remote
  caller.
- **A standby control takes the first free port from 8083**
  (`A/standby.py:39,138`). With the agent on 8083, it takes the next.
- **site-host's pinned client sets `transport._pool`,** which is private to
  httpx. The platform version builds its pool through httpcore's public
  classes, or pins httpx's range with a test that fails when the attribute
  moves.
- **Python's `ssl` has no verify callback.** Pins are checked after the
  handshake and before the first request byte (`S/root_link.py:199-228`).

### 7.3 What building found (2026-10-20)

**Decisions made while building.**
- **The carrying lives in `_http`, not at the call sites.** The table the
  agent writes (`machine_pins.json`, `EUGENE_PLEXUS_MACHINE_PINS_FILE`) maps
  another machine's plain agent and control addresses to its TLS address
  (`http://w:8079` → `https://w:8083/agent`), and the internal clients'
  transport carries the request there and checks the pin. Every caller in
  every repo is covered with no change (R6-R9, X1-X10, the console's remote
  leg), and "required" is enforced in that one place. Drivers keep the
  explicit `Component.machineUrl` of §7.1 step 1: the gateway prefers it when
  it holds the pin.
- **The signed list is its own document**, `GET /v1/trust/machines`
  (`ep-machines+jwt`), not a field on the Job Sites' list: that one answers
  503 whenever the root cannot read its nodes name, which must not stop
  machine traffic. It carries `version` for rollback; `iat` alone could not
  rise twice in a second without dating the list in the future.
- **The root's own pin comes from its agent, never from a node.** The agent
  hands control its machine key's pin (`EUGENE_PLEXUS_CONTROL_MACHINE_PINS`);
  control signs it into the list as `controlPins` and puts it on node join
  tokens. A node that claimed to host control could otherwise have pinned the
  root's address to its own key.
- **A node reaches the root at the address it joined with**, over TLS, under
  `/control`. The first-byte switch makes that the same host and port, so it
  holds through a container's port remap with nothing to configure.
- **A node's machine URL** is `https://<advertise host>:8083`, shifted by the
  advertised agent port's offset (8279 → 8283, the console's own guess), or
  the `machineUrl` config field. It is announced only while the port listens.
- **The machine port binds wide where control's port used to be wide**: the
  agent binds wide, the node advertises an address, or it is a container.
- **`machineEncryption` is a control config field** (`automatic`, `required`,
  `off`), replicated by `patchConfig`, not a new log op: an older standby
  stops on an op it does not know.
- **Required still lets two kinds of plain request through the root's 8083**:
  from this machine (the root's own agent often joined at `127.0.0.1:8083`),
  and a Job Site's own routes (`/v1/sites/*`, `/v1/trust/tls`), which §2 left
  as they are; one that joined at a plain LAN address keeps working.
- **Only drivers restart when required changes.** Control is behind the port
  already, and restarting it brought it back sealed.
- **An older root refuses the five-field announcement** (401); the agent then
  announces the address alone, so a worker updated before its root keeps its
  address current.
- **Join tokens are `<secret>.<pin>`**; the root hashes the part before the
  dot, so it takes either form.
- **Two agents on one host** set `EUGENE_PLEXUS_AGENT_MACHINE_PORT`. Only the
  real server entry point opens the port (`machine_port_enabled`), so test
  apps and in-process harnesses never bind 8083.

**Found by the capture, each now a regression test or a check.**
- **`transport=None` turned the machine transport off.** Callers pass the
  test seam through unset; the transport took a present key as a transport,
  and a worker's topology reads went to the root in plain HTTP with tokens.
- **The root reached a node it had just enrolled in plain HTTP**: the first
  bundle push left before its agent's copy of the list named the node. The
  active root now builds its own table from its own records.
- **A NAT rule moves new connections only.** A pooled TLS session to the real
  worker never idles (the gateway polls every second), so the impostor saw
  nothing until the gateway started again; the `wrong-pin` label restarts it.

**The adversarial review (2026-10-20), and what changed.**
- **A node could register another machine's door** (the root's included)
  with its own key, and the tables merged keys per door. Now: a machine
  URL's host is the node's own address's host, no two nodes hold one door,
  and a table never merges keys from two claimants; the root's door is
  authoritative and a node on it must present the root's own key.
- **Dot segments slipped past the plain branch's Job Site rule**
  (`/v1/sites/../nodes/enroll`, normalised by httpx on the way out). Both
  branches now refuse `.`/`..` segments, encoded dots and backslashes, and
  forward the raw path, so no two hops read one path differently.
- **A party in the middle could clear a node's key** by stripping it from a
  plain announcement: the node took any 401 as "an older root" and announced
  the address alone. It now falls back only for a root that serves no
  machine list, settles on what the root took, and announces again whenever
  the root's signed list records something else.
- **The front's pumps could hang open** (no idle bound, one side waiting on
  the other). They end together, idle out after 15 minutes, and connections
  are capped (2048, 512 from one address).
- **The list's version was local to one control's files**, so a promoted
  standby started below what nodes held. It follows the replicated log index
  now.
- **Under required, an address the table did not name went plain.** A
  blanket refusal would break model servers on the LAN, so the rule is
  about what is sent: no token of this install (a JWS with `typ: ep-*`)
  goes to another machine in plain HTTP, whatever the table says. This
  machine under its own LAN address is listed as `local`.
- **A pin cut short in a copied join command** made the join plain. It is
  an error now, and the join token's key gives way to the signed list's.
- **Control moved off 8083 even when the machine port could not open.** It
  moves only when 8083 is free, and is kept on loopback only behind a
  machine port that started.
- **A root whose machine key changed would strand every node**: their pinned
  calls are refused, the list's included. The list is public, signed and
  versioned, so a node then fetches it once in plain HTTP (the plain branch
  serves `/v1/trust/machines` under required for this) and takes it only if
  it verifies.
- **Found safe:** the pin form on both sides, IPv6 normalisation, the check
  before the first byte with no fallback to chain verification, peer
  restoration only for a loopback immediate client, header stripping, the
  in-process `/agent` dispatch (`/link` needs plain `http` on loopback), and
  no open proxy through `/drivers` or `/control`.
- **Not changed:** pooled sessions are not cut when a machine is removed
  (its tokens are revoked anyway), and a node with no list yet accepts any
  validly signed one. Since LT1b a node's first list comes over TLS to the
  key in its join token; only a node upgraded in place fetches its first
  list in plain HTTP.

**Not built, or not measured.**
- **Key rotation** (two pins over an overlap): the record and the list hold a
  list of pins, but a node announces one and nothing rotates it.
- **A promoted standby on a version older than LT1** keeps no pins (its apply
  ignores the new fields), and nodes re-announce only on a change, so its list
  is empty until they do.
- **The cost** (§3.8), measured on the Docker pair with `--measure 300`: a
  non-streaming chat root gateway -> worker driver -> stub engine took p50
  5.46 ms over the machine port and 4.99 ms plain on `main` (+0.47 ms); p95
  7.99 ms and 8.18 ms. One host, a stub engine and no streaming: first-token
  time and tok/s on a real engine are not measured.
