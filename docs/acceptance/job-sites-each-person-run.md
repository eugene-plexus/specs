# Job Sites, slice 2b.2: each person as themselves (2026-10-06)

A person's calls on a job site run as their own OS account. The site host
holds the site and opens no one's files; a **worker** per linked person runs
their tools as that person, over a local channel that checks the worker's
account on every connection. A link between a Eugene person and an OS
account is made **at the machine**: on Windows through the agent's loopback
`/link` page, at the join for the owner, and on Linux by root (J24-J27,
J36-J38). On Windows a worker runs only while its person is signed in (J25
as revised).

Design: [`docs/design/job-sites-own-enrollment.md`](../design/job-sites-own-enrollment.md)
§2.4, §2.4.1, §3.2 and §3.2.1.
Scripts: [`scripts/job-sites-windows-acceptance.py`](../../scripts/job-sites-windows-acceptance.py)
(new: Windows, real accounts, real sessions),
[`scripts/job-sites-acceptance.py`](../../scripts/job-sites-acceptance.py)
(both slices, Windows-with-WSL2 and Linux),
[`scripts/job-sites-sabotage.py`](../../scripts/job-sites-sabotage.py).
Slice 2b.1's record: [`job-sites-own-enrollment-run.md`](job-sites-own-enrollment-run.md).
The two slices land together.

Built on branch `slice2b1-sites`, on top of 2b.1:
- contract: specs `f52f8d4` (on `main` before the build);
- site-host `01e47a4`, `331d172`, `4ea7562`;
- agent `f30f6c7`, `8657314`, `0bc34b5`, and from this run `36f5a66`,
  `e924ff3`;
- control `2f3240a`, `89a89fd`;
- Workbench `53f6e81`;
- installers: specs `8113d96`.

## What ran

| Where | Who | Result |
|---|---|---|
| Amish_Station, Windows 11 Pro 10.0.26200 | `troyc` (a Microsoft account, an administrator, at the console) and `jessie` (a local standard account, signed in through *Switch user*, her session disconnected) | **9 of 9**, third run |
| This machine, the root in WSL2 behind its NAT | one account (the one-account mode) | **21 of 21** |
| Linux, one host, passwordless sudo (as root in WSL2) | throwaway accounts for two people, the site host and a stranger | **21 of 21**, at this run's fixes |

**The Windows run is real end to end.** It starts a control root in its own
process and an agent from this checkout **as LocalSystem** (a one-shot
scheduled task), told it is a service install
(`EUGENE_PLEXUS_AGENT_ACCEPTANCE_MECHANISM`). That agent installs the site
host from the sibling checkout as the C1 service `EugenePlexusApp-site-host`,
running as its virtual account, and starts each person's worker into their
own session with their own session token (`WTSQueryUserToken`). Who a call
ran as is read from the file it wrote: Windows makes a new file's owner the
user of the token that made it. Everything is under a throwaway folder in
`%ProgramData%`, on free ports. The live install (`EugenePlexusAgent`,
`EugenePlexusApp-node-files`, the tray task) was checked unchanged before
and after each run, and nothing touched the Unraid root.

Run elevated, once, by Troy's UAC click: a PowerShell loop that ran only
this script on a trigger file, for the three runs, then stopped.

## The checks (Windows)

1. **The owner's link is made at the join**, from the account that ran it
   (`troyc`). The site host runs as `NT SERVICE\EugenePlexusApp-site-host`.
   The links file is writable by SYSTEM and Administrators only; the site
   host's account may only read it.
2. **The owner's calls run as the owner**: the file the owner's call wrote is
   owned by `troyc`, not by Administrators, so the worker had the filtered
   token.
3. **Jessie links at the machine.** A program in her own session opens the
   agent's `/link` page, which names her Windows account; signs in to Eugene
   as herself through the agent's `/oidc` (the built-in `eugene-site-link`
   client, PKCE); and confirms. The link is written, and her worker starts in
   her session as her.
4. **Her calls run as her.** Her file is hers. A file only `troyc` may read is
   refused to her, and one only she may read is refused to `troyc`, by
   Windows. Nothing was granted by hand.
5. **Someone with no link** (`bo`) runs as the owner, inside the folder the
   owner gave them, and a path out of it is refused (J27).
6. **A worker started for an account it does not run as** (Jessie's SID,
   started by the elevated owner) refuses to serve.
7. **Jessie removes her link from Workbench**: the root asks the agent
   (`DELETE /v1/site/links/{subject}`), her worker stops, her next call runs
   as the owner, and a raw connection to the channel from her session is
   refused.
8. **No route makes a link**: the agent's one link route removes; the root's
   only link routes are the person check and the removal.
9. **Signed out, refused (J25).** Linked again, then signed out with
   `logoff`: her worker ends with her session, and her next call is refused
   saying she is not signed in there.

In the third run the site host's service started 30 s after the run began
(installing it included); the owner's worker started 9 s later, and
Jessie's 0.2 s after her link was confirmed.

## Found by running, and fixed

- **`site join` raced the install** (run 1). It took "the site host's venv
  has a `python.exe`" to mean "installed", but uv makes a venv's interpreter
  before it installs anything into it. The join called it 16 s in and got
  `No module named eugene_plexus_site_host`. Any first `site join` on a
  Windows service install would have met this. **Fixed** (agent `36f5a66`):
  the site host is prepared when `apps.yaml` records its version. A test
  holds it.
- **The second person's worker never started** (run 2): `Access is denied`
  from `AssignProcessToJobObject`, every five seconds. All workers shared one
  job. A process that is already in a job may join another only while that
  one is empty or on its own job's chain, and an agent that is itself in a
  job (Task Scheduler puts each task in one) hands its job to each worker. So
  the shared job took the owner's worker and refused Jessie's. A real
  service, under the service manager, is in no job, so this needs the agent
  to be in one; but nothing in the product required that it not be. **Fixed**
  (agent `e924ff3`): each worker gets a job of its own, which is empty when
  it joins and still kills the worker when the agent goes. Tests hold it with
  Windows' rule built into the fake.
- **The one-account stand-in worker had gone stale** (the harness, found by
  the sabotage pass's baseline): `refuse_to_serve` gained a `shared` keyword
  in site-host `331d172`, and the cross-platform script's stand-in replaced it
  with a function that took none. Fixed in specs `6ab7746`.
- **Teardown left a file nobody but Jessie could delete** (the harness): the
  file check 4 made hers alone refuses even an administrator's delete. The
  teardown now takes the folder back (`takeown`, `icacls /reset`) before
  removing it. Not yet run: the one file left by run 3 goes with the test
  accounts' cleanup.

## Found by CI after landing, and fixed

The first CI run at the new pins passed the Linux Job Sites acceptance
(21 of 21) and failed five cheap checks: four contract descriptions split at a
comma (Redocly, red since 2b.1's contract), the site host's installer pin read
as an eighth component, mypy on Linux over Windows-only `ctypes`, one
unformatted test, and two secret-scan false positives on key type
annotations. Fixed in specs `0bce164`, agent `b6f08a1`, site-host `044c159`.

The agent's Linux tests, which that CI run never reached, then found a real
defect: **a service install with broken accounts** (pywin32 missing, or an
old `install.sh`'s units) was read as a per-user install (J38), so the agent
would have run the site host as its own child, as LocalSystem or its own
account. It now hosts no site there until repaired (agent `d83712c`). The
test meant to hold this had passed only where uv could not be found. The app's
own site-host loop now idles in unit tests, where it raced tests that put a
host record. One sabotage added for it (283), caught. The installers still
pin agent `c3a718c`; this rides the next pin.

**The site host's Linux tests hung on GitHub's runner for an hour**, and had
never run there (each earlier CI run stopped at a lint step). The tests'
"account nobody holds" was a fixed uid 1001, and **GitHub's runner is uid
1001**, so every stranger check tested the test's own account; one waited
for a refusal that never came. WSL (uid 1000) could not show it. It is now
this uid plus one (site-host `6a5ad13`, `a4121ce`), proved on a throwaway
branch run on GitHub (181 passed), and the job times out at 15 minutes
(`f3573e3`). Test code only.

## Not done, named

- **CI's Linux runner** (a sudo-capable user, not root) runs the
  cross-platform script at the new pins; it has not yet. Here it ran as root,
  so its one SKIP is the agent's unelevated refusals, which the agent's own
  tests carry.
- **Windows signed-out service**: by J25 as revised, none. After a reboot a
  person's calls on the machine wait until they sign in.
- **An Entra ID or domain account** was not a worker here; neither exists on
  this machine.
- **Network shares from a worker** were not reached: the only other machine
  on this network is the root, which was not touched.
- From §3.2.1, still: a root-owned way to add local servers on a Linux system
  install, and Workbench telling a per-user install from a Linux system one
  when `linkPage` is null.
- **J14** (person-held keys) is the next design, and gates any release with
  sites running as their people (J29).

## Sabotage

**279 of 282 caught, three expected escapes, none unexpected**, over both
slices (`scripts/job-sites-sabotage.py`; 2b.1's pass had 114). Restores are
from byte copies, the pass opens with every gate passing unsabotaged, and an
anchor found other than exactly once stops it. Every repo was clean after it.

The three that escape, each declared in the script:
- a site token whose header names another algorithm: `decode()` is also
  given `algorithms=['EdDSA']`, a second mechanism (2b.1's survivor);
- the link page serving other systems: its test runs on Linux and is skipped
  on Windows, so CI catches it;
- a person check answered while Eugene is locked: the site-token dependency
  refuses a locked root first, a second mechanism.

The pass's first attempt last night was stopped by a restart. Its missing
checks were written then (site-host `4ea7562`, agent `0bc34b5`, control
`89a89fd`). Tonight's first attempt stopped at its baseline, on the stale
stand-in above. The six sabotages for this run's two agent fixes were caught
before the full pass, and again in it.
