# Single-port HTTPS entry point

2026-10-04. Implements the approved [design](../design/single-port-entrypoint.md).
Migration instructions: [One HTTPS port](../deployment/container.md#one-https-port).
Existing installations retain their ports until explicitly migrated.

## Evidence

- Agent: full Windows development suite 1,767 passed, 17 platform skips; after
  the final lifecycle guard, 60 targeted app/sign-in/entry-point tests passed.
  The Linux [source CI](https://github.com/eugene-plexus/agent/actions/runs/37237867023)
  passed lint, types, code generation and its full test suite.
- Control: 358 passed, 2 platform skips locally; its
  [source CI](https://github.com/eugene-plexus/control/actions/runs/37237749183)
  passed. Exact public-to-local transport mapping preserves node credentials.
- Console: 1,668 browser unit tests and production build passed in
  [source CI](https://github.com/eugene-plexus/ui/actions/runs/37237753204), including
  the actual Chrome checks for loading, recovery and consistent update notices.
- Workbench: frontend's 62 tests, lint, types and production build passed. Its
  full server run exposed a formatting-sensitive existing source check: a
  multiline constructor was falsely reported as missing `trust_env=False`.
  The check now inspects Python syntax and also covers synchronous clients.
  The [corrected source run](https://github.com/eugene-plexus/workbench/actions/runs/37237978098)
  runs the complete Windows and Linux suites with this correction.
- Real Caddy 2.11.7, with verified TLS (no verification bypass): CA provisioning,
  exact SNI/Host, unknown names, spoofed headers, private console and node routes,
  separately reachable sign-in, inference route restriction, 32 MiB body and
  32 KiB header limits, stopped-app 503 and uninterrupted SSE across reload passed
  in an isolated Linux environment. The same instrument runs inside every image.
- The [initial packaged run](https://github.com/eugene-plexus/specs/actions/runs/37237904395)
  passed the build and NAS Workbench migration step. It installs Workbench in
  direct-port mode as uid 99 with `HOME=/`, creates a chat, recreates the container
  with the same volume and one HTTPS mapping, rotates exact OIDC callbacks using
  the operator's credential, and checks the preserved chat, host-only Secure
  cookies, required request secret, sibling-origin rejection and private backend
  listeners. App stop/start removes and restores its route while preserving the
  new sign-in. A request outside the container verifies the published port.
- Recovery roundtrip checks preserve CA identity and configuration, excluding
  regenerated proxy configuration, the local admin socket and the derived CA
  bundle. Published Workbench and console archives include their static assets
  and report their actual distribution commit through Git's archive stamp.

The final installer pins also run the existing Windows/Linux system-install and
recovery gates and macOS 14/15/26 acceptance. Container publication is conditional
on its migration, adversarial proxy and recovery checks succeeding; the image
that passed is the image pushed to Edge.

## Limits

This is an opt-in Linux-container entry point. DNS and certificate trust require
operator setup. Source-network policies require direct connections with preserved
client addresses; forwarded headers from another proxy are not trusted. Only
Workbench is published as an optional UI app in this version. Hostnames do not
provide user or tenant authorization; account/node/folder grants remain required,
and MSP customer installations remain separate. These are regression checks, not
an independent security certification or a physical test on Troy's NAS.
