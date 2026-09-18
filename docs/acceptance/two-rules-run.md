# R1.2 — two rules the product states and does not enforce: the run

**2026-09-18. `scripts/r12-acceptance.sh`, 21 PASS, zero failures, third
execution. `scripts/r12-sabotage.py`, 20 sabotages, 20 caught, 0 escaped.**
Roadmap: [`../design/release-roadmap.md`](../design/release-roadmap.md) §2.2.
Findings closed: review §6.1 #1 (the forwarded-header trust chain), §6.2 #14
(a download destination that can leave every Library folder), §6.3 #32 (frame
headers on the agent-served UI).

Repos: `agent`, `control`, `gateway`, `library`, `inference-driver`. **No
contract change** and **no UI change** — nothing here is on the wire between
components, so `dist` is untouched and neither installer is re-pinned. The six
pins stay as R1.1 left them, to be bumped once at the end of R1.

---

## 0. What was wrong, in three sentences

**The login limiter's key was whatever the caller said it was.** uvicorn ships
`ProxyHeadersMiddleware` on by default, trusting `X-Forwarded-For` from
`127.0.0.1`, and the browser reaches every component through the agent's own
loopback proxy — which forwarded the caller's headers verbatim. So one bucket
per attempt, and the limiter counted to one forever; the same lever wrote the
Reach card's only *proof* that another device ever got in.

**And with no header at all, that one bucket was shared by the whole install.**
Five mistyped passphrases from one person locked every browser out for a
minute. That half needs no attacker and is the one a real person meets.

**A single-file download's `filename` was joined onto the resolved directory
with no bounds check** — the one its sibling field `subdirectory` gets two
functions earlier — so an operator-supplied name could name a destination
anywhere the library process can write. That is calling #3, the non-negotiable
one, and **a rule the product does not enforce is a slogan.**

---

## 1. The shape of the fix

**One header we own, believed only where it can only be ours.** The agent's
proxy strips every forwarding header *and* a caller's copy of our own
(`peer.FORWARDING_HEADERS` and `peer.PEER_HEADER` in
`routes/proxy.py`'s stripped set), then sets `PEER_HEADER` from the peer it
actually saw. Every entrypoint passes `forwarded_allow_ips=[]`, so uvicorn
believes nothing. Both login routes and the off-host witness read
`peer.peer_of(tcp_peer, header)`, which takes the header **only when the TCP
peer is loopback** — the one case where the peer is our own proxy and says
nothing. Off-host the peer is the truth, which is what makes a forged header
worthless from anywhere it could be forged.

`peer.py` exists twice, in `agent` and `control`, like `security.py` exists
five times: components share schemas, not code. The control copy is the reading
half — the trust root proxies nothing — and drops `header_of`, which only the
agent's ASGI middleware needs.

**`resolve_file` in `library/downloads.py`** resolves and bounds-checks the
destination of *every* file, not just a renamed one, and refuses with
`PathTraversal` rather than sanitising: a silently renamed file is worse than a
400, because the operator asked for a name, got another, and finds out when a
runtime points at a path that is not there. It runs once before the network (so
a bad name costs no round trip) and once per entry in the loop.

**`FRAME_HEADERS` in `ui_assets.py`**, on the static mount and on the degraded
"no UI installed" page. `frame-ancestors` only: a full CSP over a Next static
export means enumerating its inline bootstrap and chunk origins, which is a real
slice with a real chance of shipping a blank page.

---

## 2. What the live run proves that the unit checks cannot

**The instrument is the interesting part: the client binds its own source
address.** Two "browsers" are `127.0.0.2` and `127.0.0.3` — distinct peers on a
real socket, both loopback, so the proxy sees two callers and the component
behind it sees one. That is exactly the arrangement the finding is about, and it
needs no LAN bind, no second machine, and nothing this box's live install could
notice. `curl` cannot bind a source address per request, so the run carries a
40-line raw client instead.

| check | what it shows |
| --- | --- |
| 2 | five wrong passphrases through the real proxy, each claiming a different origin, **still 429 the sixth** — `401,401,401,401,401,429` |
| 3 | the locked browser stays locked (429), a **second browser is 401**, a **direct caller is 401**, and the second browser's correct passphrase still signs in |
| 5 | `lastReachedFrom` is empty after a request carrying `X-Forwarded-For: 203.0.113.9` — the proof is not forgeable from this box |
| 6 | `X-Frame-Options: DENY` and `frame-ancestors 'none'` on `GET /` and on a deep link |
| 7 | a traversing `filename` is `PathTraversal`, **before any upstream call**, with nothing queued and nothing on disk |
| 8 | an ordinary rename **passes the guard and reaches the hub** |

---

## 3. The sabotage pass

`scripts/r12-sabotage.py`: baseline green in all five repos, **20 sabotages, 20
caught, 0 escaped**, all five gates green again after every restore. Restores
from a copy taken up front, never `git checkout --`.

**One escaped on the first pass, and the escape was the point.** Removing
`peer.PEER_HEADER` from the proxy's stripped set changed nothing any check
could see, because `_request_headers` overwrites the header one line later
anyway. The two guards are not redundant, though: the overwrite runs only when
there **is** a peer, and `scope["client"]` is `None` on some transports — so
the strip is the only guard for that case, and it was untested rather than
unnecessary. `test_a_request_with_no_peer_cannot_launder_our_header` is the
check that gap earned. Same family as R1.1's double-checked lock, from the
opposite direction: there the sabotage was wrong, here the *check set* was
incomplete.

**And one paired sabotage, deliberately.** The library validates a destination
twice on purpose, so the sabotage that means anything removes both the
pre-network check and the per-entry resolve. Either alone is covered by the
other, and disabling one would have been the sabotage's fault.

---

## 4. Three harness defects, all in the instruments this run added

None were product defects, and each would have reported a correct
implementation as broken or the reverse.

**The raw client cannot unframe a chunked body.** A proxied response is a
`StreamingResponse`, so `json.loads(payload)` raised and three checks reported
an empty string as a failure. Read as a substring now, with the limitation in
the client's own docstring.

**`github.com` contains "hub".** Check 7's "was this refused before any
upstream call" matched `*hub*` against the Problem's own `type` URL and called
a correct pre-network refusal a post-network one. The markers are the dead port
and `catalogue-unreachable` now.

**And check 8 was green for the wrong reason on its first execution.** With
`catalogueEnabled: false` the route refuses before `start()` runs at all, so
"an ordinary rename is not refused as a traversal" would have passed against a
guard that refused everything one step earlier. The catalogue is **on** now with
its hub pointed at the discard port, so an accepted name must get past the
guard and die at the hub — which also makes check 7's *before any upstream
call* meaningful.

**The code reaches the wire lower-cased**, inside the Problem's `type` fragment
(`...library#pathtraversal`); `DownloadError.code` builds that fragment and
nothing else carries it. Worth knowing before writing a client that matches on
it.

---

## 5. What the unit checks pin

- `agent/tests/test_forwarded_peer.py` — 24 cases. The ones that matter drive
  the request through the **actual** `ProxyHeadersMiddleware`, configured from
  the **actual** `uvicorn.Config` that `build_server` produces. A check that
  drove only the FastAPI app would have been green throughout, which is this
  project's recurring shape.
- `control/tests/test_forwarded_peer.py` — the same, with `trusted_hosts` taken
  from what `main()` hands `uvicorn.run` rather than from a literal, plus a
  check that no file in `control/src` reads a forwarding header by name.
- `gateway`, `library`, `inference-driver` — one check each, driving `main()`
  with `uvicorn.run` captured. These components have no login; the rule is all
  five entrypoints because `scope["client"]` is caller-controlled today in the
  access log and in whatever reads it next.
- `library/tests/test_download_destination_stays_in_the_root.py` — 8 cases,
  including the manager's own path, because `resolve_file` being right proves
  nothing about `start()` calling it.

---

## 6. Not covered

- **No second machine and no genuinely off-host caller.** Every peer in the run
  is loopback by design. The off-host branch (`peer` wins over a supplied
  header) is unit-tested and has never been exercised over a LAN.
- **No browser.** The frame headers are read off `curl`; no page was actually
  refused a frame by Chrome.
- **The live install is untouched**, so the worker node's own agent is still on
  the previous build and neither installer pins any of this.
- **IPv6 peers are unit-tested only** (`::1`, `::ffff:127.0.0.1`); nothing in
  this run spoke IPv6.
- **The limiter's window is not exercised over time** — nothing waits sixty
  seconds to watch a bucket drain.
