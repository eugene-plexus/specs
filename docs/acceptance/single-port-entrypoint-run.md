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
operator setup. Direct connections must preserve client addresses. The follow-up
below adds explicit trusted-proxy mode; forwarded metadata is otherwise ignored. Only
Workbench is published as an optional UI app in this version. Hostnames do not
provide user or tenant authorization; account/node/folder grants remain required,
and MSP customer installations remain separate. These are regression checks, not
an independent security certification or a physical test on Troy's NAS.

## Guided setup and certificate management follow-up

2026-10-04. [Setup recipes](../deployment/container-access.md) cover an existing
NPM/Caddy/Traefik proxy, direct automatic Let's Encrypt, private local CA, supplied
organisation/DNS-managed certificates and verified TLS to a proxy on another host.
The preview endpoint validates an operator's configuration without changing files,
starting listeners or contacting a certificate authority.

- Agent Windows development suite: **1,786 passed, 17 platform skips**; Ruff and
  mypy passed. Tests include preview authorization/non-mutation and ambiguous or
  overly broad trust configuration rejection.
- `scripts/entrypoint-proxy-checks.py`, run with the real pinned Caddy in isolated
  Linux processes: private HTTP and verified HTTPS proxy transport; forged,
  missing and duplicated forwarding headers; untrusted source connections;
  separate public Workbench/private administration policies; IPv4/IPv6 clients.
  Supplied certificate rotation succeeds without process restart, and a malformed
  replacement leaves the previously working certificate in service.
- `scripts/entrypoint-acme-checks.py`: real TLS-ALPN issuance, short-lived automatic
  renewal and certificate persistence across Caddy restart, using Let's Encrypt's
  Pebble v2.10.1 in a temporary directory with a pinned archive digest. Challenges
  and certificate verification stay enabled. Its isolated DNS responder changes
  no system DNS/trust and no requests are sent to a public CA.
- Packaged checks **33–35** repeat certificate/proxy checks inside the image and
  migrate the existing NAS fixture again, to private HTTP behind a second Caddy
  HTTPS proxy. The latter repeats real Workbench OIDC sign-in, cookie/CSRF, chat,
  private listener and app restart checks while preserving the existing identity.
  Container publication requires these checks to pass.
- Console: **1,671 tests passed**, lint, types, formatting and production build
  passed. Tests exercise setup validation, explicit subscriber agreement, edited
  and stale previews. `ui/scripts/access-browser-acceptance.mjs` drives the exported
  page in Chrome for all four modes, verifies downloaded JSON bytes and narrow
  screen scrolling. The source workflow runs it alongside the existing UI checks.

NPM and Traefik recipes follow their documented forwarding interfaces; their
management UIs are not exercised by these acceptance instruments. Public Let's
Encrypt reachability and each operator's DNS still require deployment setup.
Native DNS-provider integrations are not shipped: DNS-01 certificates come from
an existing proxy or external manager. No live customer installation was changed.

## Released to Edge

2026-10-04, specs `440a3c6`. Pins: agent `5bb6a38`, control `e9cc3a7`,
ui `6aa1223` / dist `24268f7` (its `BUILD_INFO` names `ui@6aa1223`); the
other four unchanged.

- All four push workflows passed: [CI](https://github.com/eugene-plexus/specs/actions/runs/37242018227)
  (Windows/Linux system installs, recovery, offline removal, R7/R8/A2/A3/A5),
  [A4 macOS](https://github.com/eugene-plexus/specs/actions/runs/37242018236)
  (macOS 14, 15 and 26) and the
  [container image](https://github.com/eugene-plexus/specs/actions/runs/37242018384),
  35 of 35 checks including 33–35 above.
- The registry's `edge` tag is `sha256:89a1228732b29967b05dd3d2d4f93c5a8c30bfe7a46535d6d5884644b13bda9b`,
  the digest that run pushed as `sha-440a3c6` after its checks passed.
- The agent's own `newest_edge()` resolves to `440a3c6` with the pins above, so
  native installs on Edge are offered this build.
- CI needed one rerun. Attempt 1 failed `a5-scoped-keys-acceptance.py:449` on
  Windows: a request on gateway-b was refused 429 right after a 503 on gateway-a,
  for a key limited to one concurrent request. The gateway frees the key's shared
  slot after the response has been sent, so an immediate next request can still
  find it held. The rerun passed with no change. Filed as
  [gateway #9](https://github.com/eugene-plexus/gateway/issues/9). It is not
  caused by this slice.

Existing containers keep their published ports until the owner applies a
configuration from Settings → Container access setup.
