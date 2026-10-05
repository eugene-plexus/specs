# Job Sites, slice 1: the run (2026-10-05)

Design: [`docs/design/remote-nodes.md`](../design/remote-nodes.md) §3, §5, §6
and §6.1. Script: [`scripts/job-sites-acceptance.py`](../../scripts/job-sites-acceptance.py).
Sabotage: [`scripts/job-sites-sabotage.py`](../../scripts/job-sites-sabotage.py).

## What ran

**The root** is the real control root behind the real entry point. Caddy
2.11.7 (pinned, checksum-verified) runs the configuration the agent's own
`caddy_config` generates. That configuration has a **bare-address** nodes origin and
`public_nodes`, in front of `control` given the nodes origin and probe the
agent hands it. Caddy's own networks are a TEST-NET range, so every
connection the site makes is a public one.

**The site** is a real agent:
- it joined with the real CLI (`join --job-site`, the owner's password on
  stdin);
- it was then started and left to run, so its own trust-bundle pull and its
  own file-helper poll crossed the public route, pinned to the root's identity
  key (J7a).

**The file read** runs the agent's real relay (`NodeFileHelper`) and the real
helper worker wheel. It goes over the real public route, with the TLS pins
the site saved at its join. A service install's OS account is the one thing
a test process cannot give the site agent itself; C1's disposable runners own
that check.

**Workbench** is played by a client with Workbench's own credentials: a
registered sign-in client, plus each person's refresh token from the real
sign-in page, calling the routes Workbench calls. Workbench's own half (the
mode line, the change notice, the redaction) is its own suite's
(`workbench/tests/test_job_sites.py`, `web/src/components/JobSites.test.tsx`).

Two topologies, both green, 17 checks each:

| Where | Root | Site | Result |
|---|---|---|---|
| This machine (the doc's stand-in) | WSL2 Ubuntu, behind WSL's NAT, one port reached through it, a bare address (`172.19.x`) | Windows 11, the agent's venv | **17 of 17** |
| One Linux host (CI's shape) | WSL2 Ubuntu | the same WSL2 host, as a public caller | **17 of 17** |

The doc's §5 put WSL2 on the site's side. The entry point is the Linux
container's, so the root is the one in WSL2, and the site joins from outside
its NAT.

## The checks

1. The root is set up with two people and Workbench's sign-in.
2. From another network the nodes name refuses the API, sign-in, and a bundle
   request without a token.
3. The root signs the TLS key its bare-address nodes name presents, and the
   list verifies against the key in the invitation.
4. J9: a person invites their own machine from Workbench; Eugene's owner
   cannot.
5. A join command naming another root's key sends nothing and records
   nothing.
6. A leaked token yields nothing without its person's password. An ordinary
   node's token cannot join from outside.
7. The site joined over the public route as ada's: files only, no address.
   Her password is kept nowhere on it.
8. The site agent says it is a job site, has no address, and listens on
   loopback only.
9. Eugene's owner sees it online, with its last contact, and nothing of its
   files.
10. The site pulls each new trust bundle itself, pinned, with its own token.
    The root revoked another machine, and the site took the new version.
11. J4: nothing runs on a job site.
12. ada turns on her site's helper, registers a folder, and grants it,
    herself included.
13. A person she granted reads the file through the public route, marked as a
    job site's.
14. Production: Eugene's owner cannot read it, by grant or by listing.
15. Dev mode: the owner sees the site's folders, grants themselves one and
    reads it, and every app can tell everyone the mode and when it changed.
16. Back in production the owner's own grant stops at once.
17. ada takes her machine out herself; it is gone at once.

## Measured on real Caddy before the script existed

The product's generated configuration was probed with a forged
`X-Eugene-Plexus-Entry` on every request:
- The six node paths reached the root with the mark **overwritten** to
  `public-nodes`.
- Every other path, sign-in and `/oidc` included, got *"This name serves
  machines only. Eugene's console is at …"*.
- A TLS session made for the console's name, sent to the address, got 421.

## Found by running, and fixed

- **Caddy refused the bare address's handshake**: no TLS policy matched a
  client that sends no SNI. Then its server-wide strict SNI check answered 421
  to every such request. Fixed with a `default_sni` policy and the strict
  check made by route for an address origin (§5.1).
- **Folder registration was the operator's, in the relay and again in the
  worker**: ada's registration was refused twice, with two different
  sentences. The root now names a site's owner in the poll answer, and only
  the relay decides (§5.1).
- **Harness, not product:**
  - Caddy cannot make its admin socket on a drive WSL mounts from Windows.
  - Health probes carried the root's bearer.
  - A keyword named `path` collided with the route argument.

## Sabotage

**45 of 45 caught**, after one pass that caught 43. Each mutation is restored
from a byte copy, and the pass opens with every gate passing unsabotaged. The
gates are control, the agent, Workbench, the console, and this acceptance
for the one mutation only a running site can show (the site pulling the
bundle without its token).

**The two that escaped first each named a missing check, not a weak fix:**
- *A job site shown by its probe's error.* The test had never put a probe
  result in front of the view, so `lastError` was empty either way. It does
  now.
- *The TLS list signed as something else.* The test compared the header with
  the module's own constant, and the sabotage changed both. It asserts the
  contract's literal, `ep-root-tls+jwt`, which is what a site checks.

The pass also crashed once on the console's code page, printing a gate's last
line; it prints with replacement now.

## Not covered, named

- **The service install**: a site's helper in its own OS account is C1's
  disposable-runner check. Here the relay and worker run as this account.
- **Workbench end to end**: its page and its redaction are its own suites';
  here a client with its credentials calls its routes.
- **A site behind a forcing proxy**: the pinned client through a CONNECT
  proxy is unit-tested (`agent/tests/test_root_tls.py`), not run across a
  real one.
- **NPM in front**: the root reading the key its public name presents, when an
  outside proxy holds the certificate, has not run anywhere (control's tests
  stand in for the probe). Troy's NAS is where it will first run.
