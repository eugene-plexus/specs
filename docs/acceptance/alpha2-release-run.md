# v0.1.0-alpha.2 distribution acceptance, 2026-09-21

Troy authorized updating the public alpha after A8, while independently updating
the live NAS and Windows worker. This publishes A1-A8 and A6b without declaring
the remaining moderated sessions or physical platform checks complete.

## Fixed distribution

- [GitHub prerelease](https://github.com/eugene-plexus/specs/releases/tag/v0.1.0-alpha.2),
  explicitly prerelease, not latest stable. Annotated tag resolves to specs
  `ba0e6f7273ccc7063045da64cfe860ec87d7316c`.
- Four assets: `install.ps1`, `install.sh`, `manifest.json`, `SHA256SUMS`.
  The manifest records all six component source pins and the built UI export.
  Files were generated from committed blobs, not checkout line endings.
- [Exact tagged source CI](https://github.com/eugene-plexus/specs/actions/runs/35636628448)
  passed, including Windows/Linux integration and recovery checks.
- [Versioned image build](https://github.com/eugene-plexus/specs/actions/runs/35636880110)
  passed 24 checks with zero failures before publishing the tested image.
  Image: `ghcr.io/eugene-plexus/control-plane:v0.1.0-alpha.2`.
  Immutable reference:
  `ghcr.io/eugene-plexus/control-plane@sha256:3b5ae6eac6d0d842587f7a398dfc642ef5981579b74ba3fae02b4168e7857404`.
- Anonymous GHCR manifest access returned that digest, independently checked
  against the response bytes. Versioned publication did not advance `edge`.

| Asset | SHA-256 |
| --- | --- |
| install.ps1 | `543d79300dcc6ca7eca0d2a8d6ad12599496095f9fe12facf120994951fe7669` |
| install.sh | `6590a62ec23d2c9af6350a1e4c4b370603565813f8789005ed6d6bbbf700ad1f` |
| manifest.json | `0603c514bfeb30976d027fa5b50c47f10a83695646e032935898896e948b6072` |

Downloaded all four uploaded assets and compared them byte-for-byte with the
packaged files. After publication, anonymous HTTP downloads of all four again
matched. The original alpha.1 tag remains at
`501e23c58957a49afb587df28f4ce3419c09908a`; its anonymous container digest remains
`sha256:4c2cecb3201eedc66d966e272c4b6460e62a36b845d41aa8759560856a44d17a`.

## Installer execution

Before publication, passed the exact packaged installers to
`scripts/s10-acceptance.py --installer` on Windows and WSL, in new isolated
prefixes. Actual setup, engine acquisition, Home first reply and an independent
authenticated API request all passed. The published bytes are identical to
these exercised files.

| Target | Install to first visible token | First browser request | Separate API request |
| --- | ---: | --- | --- |
| Windows | 42.519 s | HTTP 200; "Hello, how are you?"; completed stream | Nonempty answer |
| WSL | 49.871 s | HTTP 200; "Hi, there!"; completed stream | Nonempty answer |

Both used five clicks, 91 keydowns, one configuration value and no typed paths.
Conditions: existing Ryzen 9950X host, CPU-only fixture, isolated ports and fresh
identities, seeded Qwen3-0.6B Q4_K_M (`ep-a1-model.gguf`). The instrument's shipped
8B starter row is metadata, not the model used in seeded mode. These are not
full-model-download timings, clean-OS tests, GPU measurements or a test of the
owner's live upgrade. Home waited for readiness before the first submission.

The Windows before/after snapshot passed for its live service and persistent
environment. WSL made no Windows snapshot. Both acceptance-owned agents and
their children exited. The owner's concurrent live update is separate evidence.

## Website

Website source `553aefb5f82e9dca76d7d84917ec1602766d8574` selects the alpha.2
manifest and retains alpha.1 in `archived-releases.json`. Both versions' installer
routes are generated from immutable Git blobs with size/hash checks. Homepage,
architecture, installation and recovery copy now describe alpha.2. Recovery
keeps a separate cold-copy path for the first upgrade from alpha.1.

Astro check: zero errors, warnings or hints. All 50 browser cases passed locally
across five widths, including current/archived installer bytes, copy commands,
responsive layout, accessibility and no-JavaScript instructions. The initial run
had stale architecture-copy assertions and an axe scanner mistakenly placed in
a JavaScript-disabled context; these instrument errors were corrected, and the
ten affected cases passed. [Website CI](https://github.com/eugene-plexus/website/actions/runs/35637162611)
then passed the entire suite.

The [GitHub Pages publication](https://github.com/eugene-plexus/website/actions/runs/35637370493)
passed. Anonymous requests to the live homepage, `/install/` and `/recovery/`
returned HTTP 200 and the alpha.2 version. The recovery page retained its separate
alpha.1 precautions. Both alpha.2 installers and both preserved alpha.1 installers
returned HTTP 200 from their versioned website URLs, with exact manifest sizes
and SHA-256 hashes. No redirect substitutes a newer installer for an old URL.

## Local evidence and remaining limits

During publication, Troy reported both live nodes updated and reachable. His
first Playground request in direct mode targeted port 8080; read-only checks
found the actual gateway healthy on the container's published port 8280, with a
successful browser CORS preflight. Port 8080 belonged to a different HTTP
service. Troy confirmed the same inference request succeeded through the agent's
proxy. He was given the correct direct Base URL; a successful direct retry has
not yet been reported. This does not replace the outstanding physical checks.

Artifacts: `%TEMP%/ep-alpha2-artifacts`, `ep-alpha2-downloaded`,
`ep-alpha2-windows`, `ep-alpha2-windows.log` and
`/home/tcorbin/.cache/ep-alpha2-wsl`. Disposable connection credentials and
private installation state remain local. No live enrollment, service, firewall,
model or NAS configuration was changed by these acceptance commands.

Use the [release notes](../releases/v0.1.0-alpha.2.md) and
[support matrix](../support-matrix.md). The measured CPU burst, simulated hardware
fixtures and owner observations do not close pending physical Mac, modest-GPU,
native Linux boot or remaining Windows service checks. Moderated sessions remain
open. Source pins do not lock upstream Python dependencies, engines or models.
