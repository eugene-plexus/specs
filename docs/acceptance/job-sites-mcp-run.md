# Job Sites, slice 2: the run (2026-10-05)

MCP between site and root (J6), and the site's own policy, final on it (J8),
with one file server per machine (J6g).

Design: [`docs/design/remote-nodes.md`](../design/remote-nodes.md) §3.4, §5.2,
§6.2 and §6.3.
Script: [`scripts/job-sites-acceptance.py`](../../scripts/job-sites-acceptance.py).
It extends slice 1's script ([record](job-sites-run.md)).
Sabotage: [`scripts/job-sites-mcp-sabotage.py`](../../scripts/job-sites-mcp-sabotage.py).

Pinned:
- agent `f6705fc`, which pins site-host `38d7ed8` and Workbench dist
  `bf4aeef` (from `d872e00`);
- control `d4a7dda`;
- ui `52d84f7`, dist `8cbe323`;
- contracts `29cbf3c` and `b98899c`.

## What ran

Slice 1's setup is unchanged:
- **The root** is the real control root behind real Caddy 2.11.7, on a bare
  address with `public_nodes`.
- **The site** is a real agent, joined with the real CLI over the public
  route. It is pinned to the root's identity key, and its password is
  confirmed at the machine.

**The files** now run through the agent's real relay (`SiteHostRelay`) and
the real site host:
- The host is installed from this checkout of `site-host`, the way the agent
  installs it (`EUGENE_PLEXUS_AGENT_SITE_HOST_SOURCE`).
- It starts with the environment the relay builds, and restarts when that
  changes, as the agent restarts it.
- It runs over the real public route, with the pins the site saved at its
  join.
- A service install's OS account is the one thing a test process cannot give
  the site agent (C1's disposable runners own it). So the script starts the
  host, not the site agent's app manager.

**Workbench** is played by a client with Workbench's credentials. It sends MCP
requests of the 2026-07-28 revision to `/oidc/sites/mcp`. Workbench's own half
is its suite's: one server per machine, narrowed to a chat's folders, and the
Job sites page.

**Editing the root's state** is played by a hook the script adds to the root
it hosts (`/acceptance/forge`, loopback only). It can queue an operation the
root's routes would refuse, or name another owner for the site.

**A local server** is added the way `eugene-plexus-agent site server add` adds
one after its elevation check. That check is the agent's unit test, and the
run first shows the real CLI refusing an unelevated account.

## Topologies

| Where | Root | Site | Result |
|---|---|---|---|
| This machine | WSL2 Ubuntu, behind its NAT, one port reached through it | Windows 11, the agent's venv | **23 of 23**, three runs in a row; one run before them failed (below) |
| One Linux host (CI's shape) | — | — | runs in specs CI after the pins |

## The checks

1-11 are slice 1's, unchanged except check 7, which now also asserts the
site pinned ada as its owner from `Enrollment.owner`.

12. ada's site registers a folder itself, under a name unique on it, and
    nobody may use it yet.
13. **Default deny, and rule 2.** The site refuses bo, even when the root
    itself sends his call.
14. `tools/list` and a read go through the public route, by the site's own
    list. The one file server's `folder` argument names only bo's folders.
15. A write needs the site owner's standing pre-approval, and runs with it.
16. The site's audit log records who asked and what it decided, never
    contents. Only its owner reads it.
17. The site keeps the owner it pinned at its join when the root names
    someone else.
18. A fifth tool, from a local server added at the machine, works through the
    same route, with no change to control, the agent or Workbench.
19. **J9:** a server marked `system` will not turn on without an
    administrator's consent recorded at the machine.
20. Production: Eugene's owner cannot read the site, by grant or by listing.
21. **Dev mode:** the owner grants themselves a folder. The site refuses it
    until its owner lets them in there (J6e); then it opens.
22. Back in production, the owner's own grant stops at once.
23. ada takes her machine out herself; it is gone at once.

The LAN node's half is
[`scripts/node-file-helpers-acceptance.py`](../../scripts/node-file-helpers-acceptance.py):
- the installed site host in node mode, with the real relay and the real root;
- the person's grants on each call, and one file server whose `folder`
  argument names them;
- read and edit, containment, revocation, and a refused duplicate name;
- no file content in replicated state.

It **passed** on this machine.

## Found by running, and fixed

- **The SDK refuses a 2026-07-28 request without `clientCapabilities` in
  `_meta`.** The contract had said it was optional. Workbench now sends it,
  and its fake refuses a request without it.
- **`site server add --command X` started a whole agent.** The option shared
  its argparse dest with the subcommand. The run found it by calling the CLI
  unelevated. An argument beginning with `-` is given as `--arg=-x`.
- **A slice 1 defect: the root's TLS key list was decoded with no clock
  leeway.** WSL2 ran 2.4 s ahead, and the join failed with *"not signed by its
  pinned key"*. It now allows the 300 s every token allows.
- **A reader's refused write said "may not use 'write_text'".** It now says
  they may read but not change files, and who can let them.
- **Harness, not product:** from Git Bash on Windows, a child that inherited
  the script's standard input hung at start, twice: the site agent, and the
  build backend uv ran for the site host. Every child gets `DEVNULL` now.

**One run with the same code failed, at check 21's opt-in**, and its answer
was not printed. The next three runs passed, and the assertion now prints
the answer. It is recorded here rather than explained.

## Sabotage

**45 of 45 caught**, after one pass that caught 43. Each mutation is restored
from a byte copy, and the pass opens with every gate passing unsabotaged. The
gates are:
- the site host's suite;
- the agent's relay, CLI and TLS tests;
- control's node-helper and job-site tests;
- Workbench's machines' tools and Job sites tests;
- this acceptance, for the one mutation only a running site can show: the
  join not pinning its owner.

**Both escapes in the first pass named a missing check, not a weak fix:**
- *A claim naming another machine's key.* The relay checks the key against
  this machine's identity and against the root's record. The test changed
  only the claim, so the record's check always caught it first. It now also
  makes the record agree on the wrong key.
- *Eugene's owner's grants working in production.* The call was refused at
  the root in production, but nothing tested the listing, which would have
  named the folders. It now does.

**The first site-host pass caught 17 of 18.** The escape was a test that
could not reach its check: no folder was writable, so `write_text` was never
offered and its folder check never ran. It uses a writable folder now.

## Not covered, named

- **The service install.** The host in its own OS account is C1's
  disposable-runner check:
  [`node-file-helpers-service-acceptance.py`](../../scripts/node-file-helpers-service-acceptance.py),
  a manual dispatch of `.github/workflows/node-file-helpers.yml`. It needs
  the pushed pins.
- **Workbench end to end.** Its suite drives one server per machine,
  narrowed folders, a site's local server as a chosen tool, and the Job
  sites page against a fake Eugene. Here a client with its credentials calls
  Eugene's routes.
- **Approving each call at the machine.** That waits for the held channel
  (slice 3).
