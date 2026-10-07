# J14a.1: the owner's own key, checked at the site — run record

**Date:** 2026-10-06. **Design:** [`person-held-keys.md`](../design/person-held-keys.md)
§12 (the slices, calls J50-J54, what building found). **Branch:** `j14a-keys`
in specs, site-host, agent, control and Workbench; **not landed, not pinned**
(see *Owed*).

| Repo | Commit | What |
|---|---|---|
| specs | `973064f` | the contract: `SiteAccountLink.keys`, `SiteSigning`, `held`, `/v1/held`, `JobSiteHeld`, `SiteOperation.names` |
| site-host | `cebf319`, `658ef8f`, `6d1b9e6`, `6fe5fca` | `signing.py`; the gate, held changes, J51/J52 in `host.py`; `/v1/held` in `app.py` |
| agent | `f03251e`, `6a495e4` | the key and approval pages on `/link`; `LinkStore.add_key`; `SiteHostSupervisor.held` |
| control | `9159ca7` | 202 `JobSiteHeld`; names on a change; `signing` on the site view |
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

## Owed

- **The Windows service run.** The agent as LocalSystem pinning a key for a
  real second account and reading the site host's `local_token` across
  accounts. Needs elevation (Troy's UAC click, the 2b.2 runner).
- **Landing and pins.** Push the five branches, rebuild Workbench's `dist`,
  pin the site host in the agent (`SITE_HOST_COMMIT`) and Workbench in its
  catalogue, then both installers. **The root first**: a J14a site host is
  refused by an older root (§12.3).
- J14a.2 (per-user installs) and J14a.3 (Path B, the Linux system install):
  until they land, those sites on edge run no tool (J48).
