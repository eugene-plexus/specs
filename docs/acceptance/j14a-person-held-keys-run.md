# J14a.1: the owner's own key, checked at the site — run record

**Date:** 2026-10-06. **Design:** [`person-held-keys.md`](../design/person-held-keys.md)
§12 (the slices, calls J50-J54, what building found). **Landed and pinned
2026-10-06 (night)**: site-host `6fe5fca`, agent `5111bea` (which pins that
site host and Workbench dist `06b13e7`, built from `f39f453`), control
`9159ca7`, in both installers. Troy agreed with J50-J54 as taken before
anything landed.

| Repo | Commit | What |
|---|---|---|
| specs | `973064f` | the contract: `SiteAccountLink.keys`, `SiteSigning`, `held`, `/v1/held`, `JobSiteHeld`, `SiteOperation.names` |
| site-host | `cebf319`, `658ef8f`, `6d1b9e6`, `6fe5fca` | `signing.py`; the gate, held changes, J51/J52 in `host.py`; `/v1/held` in `app.py` |
| agent | `f03251e`, `6a495e4` | the key and approval pages on `/link`; `LinkStore.add_key`; `SiteHostSupervisor.held` |
| control | `9159ca7` | 202 `JobSiteHeld`; names on a change; `signing` on the site view |
| agent | `ddb07ea` | the service run's finding: a person's worker can read the interpreter behind uv's version link |
| Workbench | `f39f453` | 202 carried to the page; the site's signing state in words |

## What was run

**Unit and component suites** (each repo's own venv): site-host 213 passed
(28 new in `test_signing.py`; six existing tests changed to the new rule, each
named in its own comment); agent 2001 passed, 16 platform skips (12 new in
`test_site_keys_page.py`); control `test_sites.py` 33 passed (1 new);
Workbench `test_job_sites.py` 13 passed (1 new), web `JobSites.test.tsx` 15
passed (4 new). ruff, ruff format, mypy and `mypy --platform linux` clean in
all four Python repos; tsc, eslint and prettier clean in Workbench's web.
Contracts: `openapi-spec-validator` clean on every document; Redocly clean
once a flow-style description with a comma was quoted (it split into a second
key; the validator had accepted it).

**`scripts/j14a-browser-check.py` — 12/12**, the system Chrome 154 on this
box, unelevated:

1. Chrome makes a key on the link page, the agent pins it, the page goes to approvals.
2. The rules made on the root's word come first, as a whole (J52), then the held change (J50).
3. The rules are shown in the site host's own words.
4. The private half is in IndexedDB, non-extractable: `exportKey` raises `InvalidAccessError`.
5. Both approved in Chrome and taken by the site host's verifier.
6. Without Ed25519 the page falls back to ECDSA P-256.
7. A change is shown as the site host words it, new people marked.
8. WebCrypto's `r||s` P-256 signatures verify at the site host.
9. A change turned down at the machine is dropped.
- S1. The links file holds both keys, each id the SHA-256 of its key.
- S2. The site host applied what Chrome signed.
- S3. Four approvals, each with the next sequence number, each in the audit log.

Its first execution failed check 9's predecessor on a **harness race**: the
page empties its list before it refills it, so "fewer approve buttons than
before" was true mid-reload and the next click counted from zero. It clicks by
item id now. Nothing in the product changed.

**`scripts/job-sites-acceptance.py --root-wsl` — 22 passed, 3 skipped**
(the one-account skips, as at 2b.2), the root in WSL2 and the site on this
Windows box, at site-host `658ef8f`. Updated for J14a: the harness pins the
owner's key in the links file as the starter does, and approves every held
grant through the site host's own `/v1/held`, so every grant in the run went
through the real verifier. New in it:

- **4b.** Before the owner's key is pinned, the site refuses a call (sent
  straight to it, past the root's own checks) saying the owner has added no
  key; it reports `unsigned`, then `signed` once the key is pinned (no rules
  yet, J52).
- **5.** Registering a folder, giving bo read, then write: each answers 202
  *held* through Workbench's routes, the site's report shows it held and
  nothing changed, and it applies only once ada's key approves it. Bo, who has
  no account on the machine, is named on the held change "as Eugene names
  them" (J54).
- **6.** The root forging a grant **in ada's own name** (jo given write) is
  held, never applied; she turns it down at the machine.
- **8.** Letting Eugene's owner in is held for ada's key; turning it off needs
  none (J51); asked again, the same change is held and **her old approval,
  replayed, is refused** (`older than one already used`).

The run of record is the third execution: the first two were started with
interpreters that lack `httpx` and pywin32 (the agent's venv has both). The two
review fixes after it (`6d1b9e6`: a change approved twice applies once; leaving
drops what was held) are unit-tested and in the sabotage pass.

**`scripts/j14a-sabotage.py` — 48 of 48 caught**, after a first pass of 41 of
49. Five gates: the site host's whole suite, the agent's link tests, control's
site tests, Workbench's job-site tests, and the browser check (which alone
catches a private half made extractable). The first pass's eight escapes:

- **Six named a missing check**, now written: the held list's bound (32); a
  reader made a writer, a server turned on, and a tool added for someone
  already listed, each held rather than read as a removal (J51); a signed
  change leaving rules nobody approved as a whole still unapproved (J52); a
  key pinned from JSON sent as `text/plain` (a form can send that; the page's
  own script never does).
- **One was a test that could not fail:** "two approvals of one change apply
  it once" never let the first approval yield, so the second never raced it,
  and its second envelope carried the same sequence number as the first, so
  the replay check refused it for a different reason. The first approval now
  takes a moment to apply, and the second carries the next number.
- **One was a second mechanism**, and the spare is deleted: the sequence store
  refused a number `check` had already refused under the same lock. The store
  now only records.

Every gate passed again restored, and all four checkouts were left clean.

## The Windows service run (Amish_Station, 2026-10-06, night)

**`scripts/job-sites-windows-acceptance.py` — 10 passed, 3 skipped**, run
elevated by the one-UAC-click runner (Troy's click; stopped after the runs).
The agent from this checkout as **LocalSystem**, the real site host as
`NT SERVICE\EugenePlexusApp-site-host`, a throwaway root in the script, and
the owner's browser the **system Chrome, started by LocalSystem in Troy's own
session with his own unelevated token**. The live `EugenePlexusAgent` and
`node-files` were unchanged before and after. The three skips are the
second-person checks (3/4, 7, 9): J14a.1's keys are the owner's, and 2b.2's
test accounts were deleted. New for J14a:

- **K1.** Until the owner's key is pinned no tool runs, and the refusal names
  `http://127.0.0.1:<port>/link/approve`; the rules the root sent before the
  key were applied as the root's word (J48). Workbench's view reads
  `unsigned`, with that page.
- **K2.** Chrome opens the agent's `/link`; the agent, as LocalSystem, finds
  the account at the far end of the connection (another session's process)
  and its link; Chrome makes a key it will not export, and the agent pins it.
- **K3.** The approve page lists the rules first, as a whole, in the site
  host's own words, read by LocalSystem over the site host's loopback API
  with its `local_token`, which only SYSTEM, Administrators and the site
  host's own account may read; Chrome signs and the site is `signed`.
- **K4.** A grant from Workbench answers 202 held and changes nothing until
  Chrome approves it at the machine; bo, with no account there, is named "as
  Eugene names them" (J54).
- **K5.** Taking bo's write away applies at once, no approval, still `signed`.

**What the run found** (five executions; the fifth is the run of record):

- **A real defect from 2b.2, in the agent, fixed (`ddb07ea`).** Once the
  run's install folder was protected as `install.ps1` leaves a service prefix
  (nothing inherited from ProgramData), **the owner's worker never
  connected**: it exited five seconds after each start. uv names the site
  host's interpreter by a link (`pythons\cpython-3.12-…`) to the patch
  version's folder (`cpython-3.12.14-…`); the agent granted people read on the
  link, and Windows checks the target. Every person's worker on a real service
  install would have failed this way. 2b.2's Windows run passed because its
  folder inherited `Users` read from ProgramData, which a real prefix does
  not. The grant now goes on each folder and on where it really is; a unit
  test makes a real junction, and fails with the fix removed.
- **Two harness defects.** The throwaway install folder inherited
  ProgramData's ACL (so `local_token` read as everyone's: run 1); it is
  protected as the installer protects a prefix now, which is what exposed the
  defect above. And three checks read the site's signing state once rather
  than waiting for the site's next report (run 4).
- On failure the script now keeps the agent's logs and the install folder's
  ACLs in the elevated account's temp folder before it removes its own.

## J14a.2: per-user installs (2026-10-06, night)

Design §12.4; calls J55-J59, **approved by Troy as taken (2026-10-07)**.
**Landed and pinned 2026-10-07**: specs contract `c74744d` (prose only),
site-host `f4661ed`, agent `70fcd5c` (which pins that site host; `1044f65` fixed a
test Linux CI caught), in both
installers. Control did not move (§ codegen below).

**Measured first, each on its own platform** (§12.4's table): Linux's
`/proc/net/tcp` in WSL2 (this account 1000, a second 1001), and macOS's
`net.inet.tcp.pcblist_n` on GitHub's macOS 14, 15 and 26 runners (501, and a
second account's 502; an unprivileged `lsof` sees only its own processes).

**The agent's own reader on real macOS** (`j14a2-macos-peer-check.py`, the
`j14a2-macos-peer` branch's workflow): on all three versions, a connection from
this account reads 501, one from a second account reads 502, and a port with no
connection is refused.

**Real Chrome on a per-user page** (`j14a-browser-check.py --per-user`):
12/12, the account read from the real connection, not stubbed.

**`job-sites-acceptance.py`, a real per-user install**, new in its check 11:
the agent from this checkout, unelevated as the harness's account and joined as
a node, installs the site host itself; `site join --no-browser` links ada to
this account and prints the key page; the site names its approve page and has
no link page, and refuses a tool until her key, saying where to add it. Then a
client in this account uses the agent's own `/link` routes as the page script
does (Chrome's half is the browser check's): it makes and pins a key, the rules
sent before it are approved as a whole, ada's call runs, and a write grant from
Workbench is held and approved there.
- **Windows, this box, root in WSL2: 24 passed, 4 skipped** (the one-account
  skips; another account's refusal on Windows needs elevation, see Owed).
- **Linux, WSL2 Ubuntu, root on the same host: 25 passed, 3 skipped**,
  including **another account refused by the page** (the second WSL user,
  through `--stranger-command 'wsl.exe -d Ubuntu -u eptest2 --'`).
- CI's Linux runner has passwordless sudo, so there the stranger is the
  harness's own throwaway account.

Its first two executions failed on the harness: a tool list before any grant
is the root's own refusal, never the site's; and the run's folder was
registered read-only, so no write grant could be given. Nothing in the product
changed.

**`j14a-sabotage.py --gate agent2 --gate site2` — 17 of 17 caught**, over the
code J14a.2 changed and the service run's worker-grant fix: each platform's
reader taking the server's own row, one of several rows, another address's
connection or an unknown layout; the per-user page serving any account,
linking people or offering to remove its link; the key page not offered, or
offered to a Linux system install; the approve page not handed to the site
host or not read by it; the join naming no page, opening one from a system
install's elevated session, or ignoring `--no-browser`; the worker grant on
uv's link alone. Not in the pass, deliberately: *Linux opens a text browser
with no desktop*, whose test runs on Linux and macOS (CI), not on this box.

Codegen at `c74744d` changed one docstring per consumer. The site host and the
agent implement the variable and re-pinned (`f4661ed`, `8850a60`); control
consumes nothing new and was reverted, not re-pinned.

**Workbench needed no change**: it already says *On <machine>, open <page>* for
any site with an approve page, and *cannot take a key yet* stays for the Linux
system install (J14a.3).

## Owed

- J14a.3 (Path B, the Linux system install): until it lands, those sites run no
  tool (J48).
- **Windows: another account refused by a per-user page**, for real. Unelevated
  there is no second account to connect from; the agent's tests carry the
  refusal. One elevated run (a LocalSystem process connecting) would show it.
- The second-person checks under J14a (a linked person's own key): they need
  a second signed-in account, as 2b.2's run had.
