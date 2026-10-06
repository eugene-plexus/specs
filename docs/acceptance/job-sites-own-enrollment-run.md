# Job Sites, slice 2b.1: a site of its own (2026-10-06)

A Job Site is its own enrollment, held by the site host program and never by
a node (J19, J23). It joins with a site invitation that names its owner,
polls its root with a token its own key signs, and answers what the root
queues for it. The console shows membership only (J19, J33). The node folders
are gone (J20).

Design: [`docs/design/job-sites-own-enrollment.md`](../design/job-sites-own-enrollment.md),
§2.2-§2.4 and §3.1.
Script: [`scripts/job-sites-acceptance.py`](../../scripts/job-sites-acceptance.py),
rewritten for this slice.
Sabotage: [`scripts/job-sites-sabotage.py`](../../scripts/job-sites-sabotage.py),
which replaces slices 1 and 2's two scripts.

Built on branch `slice2b1-sites` in each repo:
- contract: specs `6df2373`, `25eccf9`, `c2ecfc6`, plus `c6fb890` (the site
  host vendors `_http.py` and `_private_files.py`);
- control `5f51c58` and `1099d5d`;
- site-host `e91ab06`;
- agent `171d1f3`;
- Workbench `9392826`;
- ui `f33a6c5` and `20cbc74`;
- installers: specs `0ab24e1`.

**2b.1 ships with 2b.2, not alone.** In 2b.1 the site host still runs in its
isolated account, so the by-hand folder permission is still there. It goes
in 2b.2.

## What ran

The root is the real control root behind real Caddy 2.11.7, configured by
the agent's own `caddy_config` for a bare-address nodes origin with
`public_sites`. A second control with no entry point, and `siteJoinUrl` set
to its own HTTP address, is the LAN-only install.

The site is the real site host, installed from this checkout. It joins with
its own `join` command, the owner's password on its standard input, then
serves and polls. No agent relays for it. The account kind is the one the
agent would report for this OS, because a service install's OS account is
the one thing a test process cannot give it.

| Where | Root | Site | Result |
|---|---|---|---|
| This machine | WSL2 Ubuntu, behind its NAT, one port reached through it | Windows 11, the site host from this checkout | **15 of 15**, four runs |

## The checks

1. The entry point's public mode answers a site's six paths and nothing
   else. The trust bundle, `/v1/nodes`, a node's enrollment, sign-in and
   Workbench's routes are refused through the nodes name.
2. A site invitation names a person. Workbench's invite answers `joinUrl`,
   the nodes origin; Eugene's owner cannot invite from Workbench.
3. Over the public route, a wrong root key sends nothing, and a wrong
   password refuses the join and keeps the invitation. The right one joins,
   pinned to the root's identity key, as ada's site. Her password is on no
   disk.
4. Started, the site host polls. The console lists it online with its owner
   and last contact, with no `dev` view in production. It listens on
   loopback only.
5. ada registers a folder and gives bo read access through Workbench's
   routes; bo reads a file through `/oidc/sites/mcp`. Writing and the audit
   log are as in slice 2.
6. **Editing the root's state is not enough.** A forged owner, an operation
   in bo's name, and an operation bound to an earlier enrollment all run
   nothing.
7. The site's token opens its own routes only: `/v1/nodes`, `/v1/sites`,
   `/v1/config`, `/v1/people` and minting an invitation are refused, directly
   and through the nodes name. A tampered token is refused.
8. A local MCP server added at the machine, and J9's consent for a `system`
   one, as in slice 2.
9. Production hides the site's results from Eugene's owner; dev mode opens
   them only once the site's owner lets them in (J13b, J6e), as in slice 2.
10. **LAN-only (J31):** a second site host joins the second control over
    plain HTTP, pins nothing, and polls.
11. A node says which site it hosts (J32): the console shows `hostNode`, and
    a node cannot speak for another.
12. Removed from the console, the site's next poll is refused, its
    `/healthz` says so, and its enrollment stays on its disk.
13. The agent's `site join` refuses an unelevated caller. The elevated half
    is in the script for an elevated runner; this run was not elevated.
14. The site's own `leave` tells the root and forgets its enrollment, key and
    pins. The root lists it no more, and the old token is refused.
15. Setup: the root, two people and Workbench's sign-in.

## Found by running, and fixed

- **A site host restarted mid long-poll stranded the next call.** The old
  poll, still open at the root, was offered the call and answered a closed
  socket. An offered operation is never offered twice, so the call waited
  20 s and failed. This is in slice 2's broker too; the agent restarting the
  host on a new local server would meet it. **Fixed** (control `1099d5d`): an
  offer not claimed within five seconds goes back to the queue. A claim is
  still once, so nothing runs twice. The script's 9 s wait for it is gone,
  and two runs passed without it. A unit test fails with the lease removed.

## Not done, named

- **The elevated `site join`** was not run end to end here (this process is
  not elevated). Its unit tests run the site host's join with the password
  piped, and the script runs it on an elevated runner.
- **No machine that is only a site.** Until the standalone install (J21), a
  site's machine must already be a node. Slice 1's site-only machine over
  the public route ends with this slice.
- **On Linux, `site join` runs the agent's code as root**, through `sudo`, as
  `site server add` already does. The agent's own account can write that
  code. 2b.2's rule, that the program run as a person is root-owned, closes
  it.
- **The Linux one-host topology** (CI's) has not run the new script yet. It
  runs at the new pins.

- **Deleting a person left calls queued for their sites waiting 20 s.** The
  registry removed their sites at once, but the broker kept what was queued
  for them. **Fixed** (control `7da8ee7`): it ends them at once, as removing
  a site does.

## Sabotage

**113 of 114 caught.** The one survivor is expected: a site token with
another signing algorithm in its header is also refused by `decode()`
pinning EdDSA, a second mechanism. Restores are from byte copies, the pass
opens with every gate passing unsabotaged, and an anchor found other than
exactly once stops it. About 85 sabotages are this slice's; about 25 are
slice 1 and 2's whose code still exists. Unit gates catch all but the public
route's two, which the acceptance and the agent's entry point tests catch.

**Every escape in the first passes named a missing check**, and each got
one; no product code was weakened:
- **The root pin had no tests at all.** `root_link.py` moved from the
  agent's `root_tls.py` and its tests were deleted with the old file. They
  are ported (site-host `tests/test_root_link.py`), with four more: a list
  not made as a TLS list, an expired key, a join that pins before it sends,
  and a join that sends nothing to an impostor.
- **The entry point's public route had no test** (agent
  `tests/test_entrypoint.py`, five new): the six paths and no more, the
  `public-sites` mark set there and stripped everywhere else, `public_sites`
  needing a nodes name, the old `public_nodes` spelling still read, and
  only the nodes name a bare address.
- **Control** (`tests/test_sites.py`): reports, last contact and operations
  bound to their own enrollment and site; another person's name with the
  right password; a locked root not spending the invitation; the invitation
  cap; a dated mode change; the owner's production message; a retired files
  node refused a runtime.
- **The site host**: an owner named in the launch environment is not the
  owner.
- Two sabotages were rebuilt rather than answered: Workbench's three
  `jobSite` marks back each other up, so they are removed together.
