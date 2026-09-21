# v0.1.0-alpha.1 distribution acceptance, 2026-09-20

Troy authorized the first alpha and website installation instructions so other
people can test. This does not declare the moderated sessions complete or a
stable v0.1 release ready.

## Published distribution

- [GitHub prerelease](https://github.com/eugene-plexus/specs/releases/tag/v0.1.0-alpha.1),
  explicitly prerelease, not latest stable. The annotated tag resolves to specs
  `501e23c58957a49afb587df28f4ce3419c09908a`; it has not been moved.
- Four assets: `install.ps1`, `install.sh`, `manifest.json`, `SHA256SUMS`.
  The manifest names six full component commits; the UI is its built dist commit.
  These are the same component pins exercised in S10, with no application changes.
- Linux amd64 control plane: `ghcr.io/eugene-plexus/control-plane:v0.1.0-alpha.1`.
  Immutable image reference:
  `ghcr.io/eugene-plexus/control-plane@sha256:4c2cecb3201eedc66d966e272c4b6460e62a36b845d41aa8759560856a44d17a`.
- The release image passed **24 checks, zero failures** in
  [the tagged build](https://github.com/eugene-plexus/specs/actions/runs/35547089903).
  This workflow checks out the version tag and pushes the exact tested image;
  versioned publication does not advance `edge`.
- Anonymous HTTP downloads of both installer assets matched the manifest.
  An anonymous GHCR manifest request returned the same image digest.

| Asset | SHA-256 |
| --- | --- |
| install.ps1 | `934f5e3022de3828c81812b1a1a1301dce3d3cb9c35f7640ba619f69c185e38f` |
| install.sh | `3ce9b5ba547c05b1ca5fcbf100273503770f521a0cfb82038e905642c88f8635` |
| manifest.json | `c087f62178276d69eecb01220ee1ecef1407cc352ccd5886ccd0bc2e5ea5e5ee` |

`release-artifacts.py` reads committed Git blobs, not checkout text, so CRLF
conversion cannot alter the release bytes. Its checks reject divergent Windows
and POSIX pins and refuse to overwrite an existing output directory. Both OS
jobs passed in [specs CI](https://github.com/eugene-plexus/specs/actions/runs/35547076906).
This fixes Eugene source revisions, not upstream tools, Python dependencies,
model files or engine release selection.

## Uploaded installer execution

Downloaded the actual GitHub assets, verified their hashes, and passed them to
`s10-acceptance.py --installer` in new isolated prefixes. Both used a seeded
Qwen3-0.6B Q4_K_M file, newly acquired CPU llama.cpp, and the S10 CPU/port fixture.
No live GPU workload, service or NAS configuration was changed. This is a seeded
installation smoke check, not another full-download timing measurement.

**Windows passed:** 38.373 s to first visible text, five clicks, 91 keydowns,
one configuration value, zero paths. Home answered “Hello, how are you?” and a
separate curl request with Home's connection strings returned nonempty content.
The live Windows service and persistent Eugene environment matched before/after.

**WSL's first request failed, and is not counted as a pass.** Home enabled Send
while the runtime was still `loading`. The gateway returned HTTP 503 with the
specific “still coming up” explanation. This is an actual alpha UI readiness
limitation, not a broken installer and not an instrument error.

Reopened the same disposable installation, signed in through the UI, waited for
the agent to report the runtime `ready`, then sent from Home. The real response
was HTTP 200, contained “hello”, and ended with `[DONE]`. The application and
children shut down cleanly afterward. This proves serving after readiness; it
does not erase the failed first request or establish a clean five-click WSL pass.
The release notes and installation troubleshooting page name the limitation and
the workaround: wait for loading to finish, then send again. Fixing the early
composer enablement remains follow-up work.

## Website

Website source `246010187c887fca296134f6d7f0f93079eda513` adds
[the installation page](https://eugeneplexus.com/install), linked from the
homepage and navigation. It covers requirements, Windows/Linux installation,
Mac testing limits, first reply, connecting apps and a phone, updates, removal,
network storage and reports. Copy buttons have a selectable-text fallback;
the instructions work without JavaScript.

Versioned installer paths are generated during the site build from the manifest's
immutable specs commit. Each download must match its expected size and SHA-256;
there is no separately edited installer copy in the website. Deliberately setting
an incorrect checksum made the build fail; restoring the manifest made it pass.

**45 browser checks passed**, across 320, 390, 768, 1440 and 1920 px: copied
commands, exact served installer bytes, keyboard navigation, no-JavaScript use,
accessibility, overflow and existing site behavior. Astro check reported no
errors, warnings or hints. A small-phone spacing failure was corrected before
publication. The original website preview was left running; local validation
used a separate temporary project.

[Website CI](https://github.com/eugene-plexus/website/actions/runs/35547491596)
passed. The [manual publication workflow](https://github.com/eugene-plexus/website/actions/runs/35547542856)
builds and checks the same source before deployment.

## Local evidence

Windows artifacts: `%TEMP%/ep-alpha1-artifacts`, `ep-alpha1-downloaded`,
`ep-alpha1-windows`, `ep-alpha1-website`. WSL:
`/home/tcorbin/.cache/ep-alpha1-wsl`, including the original failure and recovery
logs. `%TEMP%/ep-alpha1-wsl-recovery.json` and `ep-alpha1-wsl-recovered.png`
record the successful post-readiness browser check. Disposable credentials stay
local and are not release assets.
