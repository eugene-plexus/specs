# Job Sites slice 3: copying between machines

**Status:** a design, 2026-10-09. Nothing in it is built. **Calls J92-J99
(§6) are Troy's to take.** It is J10 (`remote-nodes.md` §3.5): copy a folder
from one machine to another, site A → root → site B, the job people otherwise
hand to Dropbox or OneDrive. It builds on J14b's signed calls
(`person-held-keys.md` §13) and does not reopen J1-J91.

Code anchors are at the pins of 2026-10-09: control `2b2ae24` (`CT/`),
site-host `db20f3e` (`SH/`), agent `16edbac` (`AG/`), library (`LB/`).

---

## 0. The shape, in one page

**Neither machine can reach the other, so the bytes go through the root,
streamed, never stored there.** What has to be decided is the road they take,
because today's road was built for small messages:

- **The operation queue carries JSON of at most 70,000 bytes, one operation
  at a time per site** (`CT/sites.py:38-46, :360`, `SH/channel.py:87-118`), and
  **the public site route caps a request at 1 MiB** (`AG/entrypoint.py:816-829`).
  A copy chunked through it moves about 50 KB per operation, and each
  operation is three requests in a row (claim, run, answer).
- **The design so far said the held WebSocket arrives with this slice** (J6a,
  `remote-nodes.md:686`). Measuring what it would take found a cheaper road
  for bytes: **two plain HTTP requests per piece, one uploading from A, one
  downloading to B, which the root joins with a small buffer.** Every proxy in
  front of Troy's root (Caddy, Nginx Proxy Manager, Cloudflare) passes them as
  they are; the site's pinned HTTPS client already streams; nothing new is
  installed on a site.

**Recommended (J92): bytes on paired HTTP streams, orders on the queue.** The
queue keeps carrying the small things (start, a manifest, the end), and a
transfer is its own pair of requests, so a copy never stalls a chat. The held
WebSocket stays banked until something needs the root to speak first.

**What the person sees:** in a chat, *copy Projects from Amish_Station to the
NAS*: one approval naming both machines and both folders, signed for each
machine's half (J14b), then progress, then a report of what was copied,
skipped and why.

---

## 1. What exists today (measured 2026-10-09)

| What | Today | Where |
|---|---|---|
| Per operation | JSON, 70,000 bytes answered, 40,000 asked | `CT/routes/sites.py:101-102` |
| A site's operations | one at a time (poll, claim, run, answer, poll) | `SH/channel.py:87-118` |
| Operations waiting per site | 8 (429 above) | `CT/sites.py:360-364` |
| An operation's life | 20 s at the root, 30 s on its envelope | `CT/sites.py:38`, `sites.yaml:929` |
| The public site route | six POST paths and one GET, body at most 1 MiB | `AG/entrypoint.py:51-64, 816-829` |
| Caddy for it | `flush_interval -1`, `read_timeout 60s`, `idle_timeout 2m` | `AG/entrypoint.py:750-755, 816-829` |
| The site's client | httpx, HTTP/1.1, TLS pinned by SPKI | `SH/root_link.py:199-312` |
| WebSockets | in control, agent, Workbench (uvicorn[standard]); **none on a site** | the venvs |
| File tools | UTF-8 text only; reads 16 MiB, writes 32 KiB, in place | `SH/workspace_tools.py:46-93`, `SH/folder_io.py:31-296` |
| Resumable downloads | `.part` + Range, whole-file SHA-256, `os.replace` | `LB/downloads.py:11-605` |
| Cloudflare (free plan) | request bodies at most 100 MB (413 above); WebSockets need a heartbeat | Cloudflare's docs (§8) |

**Round trips were never measured.** §3.8's 100-300 ms per operation over the
internet is an estimate. Building this slice measures it on Troy's real route
(NAS, Nginx Proxy Manager, Cloudflare) before choosing piece sizes.

## 2. Three roads for the bytes (J92)

| | **A. The queue, chunked** | **B. Paired HTTP streams** (recommended) | **C. A held WebSocket** |
|---|---|---|---|
| What moves | base64 in JSON, ~0.7 MiB a piece (the 1 MiB cap) | raw bytes, one piece per request pair, up to 64 MiB | frames on one connection the site holds |
| Speed, estimated, 50 ms round trip | 3 requests a piece: about 3-5 MB/s | the slower link's speed, less one round trip a piece | the slower link's speed |
| Through Caddy / NPM / Cloudflare | as today | plain POST and GET; pieces under Cloudflare's 100 MB | an upgrade on a new GET path; a heartbeat under ~100 s idle |
| New on the site | nothing | nothing (httpx streams) | a WebSocket client with the SPKI pin (none today) |
| New at the root | operation kinds | two routes, a bounded relay buffer | a connection manager, framing, flow control |
| Blocks a chat while copying | yes: one operation at a time | no: transfers are not operations | no |
| Also gives | nothing | nothing else | server-initiated MCP messages, progress pushed |

**B because** it is the fastest road that adds nothing to a site, and every
hop already passes it. A is too slow for a folder of photos and stalls the
site's other calls. C buys what nothing needs yet (commands already answer
with handles, J84), at the cost of a second transport with its own pinning,
heartbeat and reconnection. **Trade-off:** B is copy-only; when the root must
speak first, C is still to build.

## 3. The shape of B

1. **The copy is a job at the root**, in memory, never in the replicated log
   (contents never are; §3.5). Workbench starts it through a new route and
   reads its progress there.
2. **A manifest first.** A new site tool, `copy_list`, lists the source folder
   on A: relative paths, sizes, a SHA-256 each, skipping what A's deny
   patterns hide, links and special files (as the file tools do). It is a read
   on A, so it runs under A's window or its signature (J14b).
3. **The person approves the copy once per machine** (J93): A signs *send
   these N files (S bytes) from A:/Projects*; B signs *receive them into
   B:/Backup/Projects*. Each site checks its own half; the approval names both
   machines and both folders.
4. **Pieces travel in pairs.** For each piece the root queues an order on each
   site (an operation: *upload piece k of file f*, *download piece k into f*).
   A answers by POSTing the piece's bytes to `/v1/sites/transfers/{id}/{k}`;
   B by GETting the same path. The root joins the two streams through a buffer
   of a few MiB; neither request waits on disk at the root.
5. **B writes into `name.part`**, appends piece after piece, checks the whole
   file's SHA-256 against the manifest, and renames: the library's pattern
   (`LB/downloads.py`). A copy that stopped resumes from the `.part`'s size.
6. **Workbench shows progress** (files and bytes, and the current file) and,
   at the end, what was copied, skipped and why.

## 4. Who may copy what

- **Policy at both ends, each final** (§3.5): A allows reading the source
  workspace, B allows changing files in the destination workspace, under each
  person's own rules there.
- **The tools are the person's own on each machine**, run as their account by
  their own worker (2b.2). A copy between two people's machines needs each
  machine to know that person; a share on B (J69) works as it does for a write.
- **Never across the root's own disk**: no piece is kept; the root sees bytes
  only as they pass.

## 5. Limits (J96, to confirm by measuring)

- A piece is at most 64 MiB (under Cloudflare's 100 MB), 8 MiB by default.
- One copy per pair of machines at a time; 4 copies at the root at once.
- At most 10,000 files and 100 GiB a copy; larger is split by the person.
- A piece that fails is retried 5 times with backoff (the library's 2, 5, 15,
  45 s); then the copy stops, keeping what arrived.

## 6. Calls

| # | Call | Recommendation | Trade-off |
|---|---|---|---|
| J92 | How the bytes travel | **B: paired HTTP streams per piece, joined at the root; orders stay on the queue.** The held WebSocket stays banked | J6a had placed the WebSocket here; this defers it until something needs the root to speak first |
| J93 | What the person signs | **One approval per copy, signed once for each machine's half** (A: send this manifest; B: receive it into this folder) | Two signatures (often one gesture: A's read is usually inside an open window) rather than one per file |
| J94 | What an approval covers | **The manifest as listed when approved**: a file that changes after is skipped and reported, not copied | A folder that keeps changing copies as it was |
| J95 | What happens at B when a name exists | **Never overwrite**: the file is skipped and reported; the person copies into a new folder or removes it first | No "update" mode; that is the sync product §3.5 keeps out |
| J96 | Limits | **As §5**, measured on Troy's route during the build | A very large tree is split by hand |
| J97 | Where the copy starts | **A Workbench tool (`copy_between_machines`), backed by a root route** that runs the job; Workbench polls its progress | Only Workbench offers it until the root presents site tools as one MCP endpoint (§3.4's later step) |
| J98 | What may be copied | **Any regular file**, binary too, unlike the text-only file tools; links, devices and what deny patterns hide are skipped | The first tool that moves binary contents |
| J99 | After a stop | **Resume from B's `.part` files** when the same copy is started again; a root restart forgets the job | A copy in flight does not survive a root restart by itself |

## 7. Slices

- **3a, the road:** the transfer routes at the root (POST source, GET sink,
  the bounded relay), the public paths through the entry point, a piece
  measured on Troy's route. Acceptance: a 1 GiB file across `--root-wsl`,
  with the root's memory staying flat.
- **3b, the copy:** `copy_list`, the orders, B's `.part` and verify, the
  approvals (J93), Workbench's tool and progress. Acceptance: a folder of
  mixed files (text, binary, a hidden path, a link) copied and verified, a
  forged copy refused at both ends, a stopped copy resumed.

## 8. Sources

- [Cloudflare: error 413, request bodies by plan](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413)
- [Cloudflare: WebSockets](https://developers.cloudflare.com/network/websockets)
- [Cloudflare: connection limits](https://developers.cloudflare.com/fundamentals/reference/connection-limits/)
