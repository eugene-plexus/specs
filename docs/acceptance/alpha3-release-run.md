# v0.1.0-alpha.3 distribution acceptance, 2026-09-26

Troy authorized alpha.3 after the one-command join passed on his worker
("My friend is ready, and so am I. Lets go for alpha.3"). His calls the same
day: alpha.3 requires a fresh install from alpha.2 (per-node token keys have
no migration), and the one-command join ships in it. This publishes a
prerelease, not a stable release, and does not close the owed physical checks
or the moderated sessions.

## Fixed distribution

- [GitHub prerelease](https://github.com/eugene-plexus/specs/releases/tag/v0.1.0-alpha.3):
  explicitly a prerelease, not the latest stable (the repository still has
  none). The annotated tag resolves to specs
  `9f23fc2bcd5d93ab497c5c7edd7941867dd6880c`.
- Four assets: `install.ps1`, `install.sh`, `manifest.json` and `SHA256SUMS`,
  generated from committed blobs by `scripts/release-artifacts.py`.
- Component pins:

  | Component | Pin |
  | --- | --- |
  | agent | `8a87b1d` |
  | control | `b14bd57` |
  | gateway | `2f4d8dd` |
  | library | `47dfdf0` |
  | inference-driver | `f754620` |
  | ui dist | `20c972f` (from ui `21de80e`) |

  The UI export was built with
  `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF=v0.1.0-alpha.3`, so Add a node's
  join commands name this release's installer, and a worker installs the
  version its root runs. That was checked in the pinned archive (the built
  chunk carries `e="v0.1.0-alpha.3"`, and `BUILD_INFO` records it). After
  tagging, the tag URL served `install.ps1` with the release hash.
- [Exact tagged source CI](https://github.com/eugene-plexus/specs/actions/runs/36282546028)
  passed: 11 jobs, 1 skipped.
- [Versioned image build](https://github.com/eugene-plexus/specs/actions/runs/36283001971)
  passed 28 checks with zero failures before publishing the tested image.
  Image: `ghcr.io/eugene-plexus/control-plane:v0.1.0-alpha.3`. Immutable
  reference:
  `ghcr.io/eugene-plexus/control-plane@sha256:e030d2cb02cfeb15c0fb45c3eed78f6df516d767915c248fe18dbdb8d540a6cb`.
  An anonymous GHCR manifest request returned that digest, and it was checked
  against the response bytes. The digest is in the GitHub release notes.

| Asset | SHA-256 |
| --- | --- |
| install.ps1 | `9b7fe90300a5b3cd3c1093a7bafa0973021b005ffbc518f962044859b7bb3a2f` |
| install.sh | `457c9b067450f1b5a6d581d037fb57ef54ca2af0e685161adfe26b39802f9bb2` |
| manifest.json | `1d22dd81863f21c3e27065db0d67abe6f671d376915ee48cf87e869ca74ac60b` |

All four uploaded assets were downloaded anonymously. `sha256sum -c` passed,
and each one was compared byte for byte with the packaged file. The alpha.1
and alpha.2 tags, assets and containers are unchanged.

## Installer execution

The exact packaged installers were passed to `scripts/s10-acceptance.py
--installer` on Windows and WSL, in new isolated prefixes. Each run covered
setup, engine acquisition, Home's first reply and an independent authenticated
API request. The published installers are byte-identical to the ones run: the
first artifacts were built from `c8fbcd6`, and the tag commit `9f23fc2`
changes only the S10 instrument.

| Target | Install | Install to first visible token | First browser request | Separate API request |
| --- | ---: | ---: | --- | --- |
| Windows | 12.5 s | 38.5 s | HTTP 200, streamed "Hello, how are you?" | "Hi! Have a great day!" |
| WSL | 9.3 s | 34.6 s | HTTP 200, completed stream | "Hello! 🌸" |

Both runs took five clicks, 92 keydowns, one configuration value and no typed
paths. The Windows before/after snapshot of the live service and persistent
environment passed.

Test conditions:
- the existing Ryzen 9950X host;
- CPU-only fixtures, with isolated ports and fresh identities;
- a seeded Qwen3-0.6B Q4_K_M (`ep-a1-model.gguf`).

These are not full-model-download timings, clean-OS tests or GPU measurements.

**The first execution failed on both targets, and the failure was in the
instrument.** Each run stopped at "first visible assistant text was observed",
with the reply on screen and the stream complete. Since the response
timestamps (2026-09-22), an assistant message's first child is a
screen-reader `<time>`. The observer's `.group.items-start > div:first-child`
therefore matched nothing. It now reads the message bubble by `data-testid`
(specs `9f23fc2`), and the second execution passed on both targets.

## The one-command join

- **Windows (owner):** Amish_Station rejoined a new control root on its first
  run of the Nodes page's command, 2026-09-26.
- **WSL2 as a system service:** each of four joins was refused, and each left
  the machine as it was, with its service running again where there had been
  one:
  - an unreachable root;
  - a root refusing the token;
  - a clean machine;
  - a leftover alpha.2 folder (9,074 files byte-identical afterwards).
- **Pester:** 46 tests, on real folders with every service cmdlet mocked.
- **Sabotage:** 23/23 installer, 5/5 agent, 5/5 UI.
- **Not run physically:** a successful Linux join, and a failed Windows join
  restoring the machine.

## Website

Website `b32de81`:
- selects the alpha.3 manifest, and keeps alpha.2 and alpha.1 in
  `archived-releases.json`;
- says that moving from alpha.2 is a fresh install, on the install,
  architecture and recovery pages;
- tells a container coming from alpha.2 to start with a new, empty data
  volume;
- describes the join taking over an existing install;
- describes alpha.3's boundaries (per-node keys, the Codex door, the Anthropic
  door's images and `top_k`) instead of alpha.2's;
- renders the recovery guide from `docs/recovery.md` at the release commit.

Checks:
- Astro check: zero errors, warnings or hints.
- 85 browser cases passed across five widths. The first run had two stale
  assertions (the old trust-boundary sentences, and a recovery link pinned
  to alpha.2's commit), and both were corrected.
- [Website CI](https://github.com/eugene-plexus/website/actions/runs/36283028246)
  and the [Pages deployment](https://github.com/eugene-plexus/website/actions/runs/36283094996)
  passed.

Anonymous requests to the live homepage, `/install/`, `/recovery/` and
`/architecture/` returned 200 and alpha.3. The alpha.3, alpha.2 and alpha.1
installers at `/releases/<version>/` all returned 200, with their recorded
hashes. The Windows install command is
`irm https://eugeneplexus.com/releases/v0.1.0-alpha.3/install.ps1 | iex`.

## Remaining limits

The owed checks, as listed in the [release notes](../releases/v0.1.0-alpha.3.md):
- a physical Mac;
- the container on a passed-through NVIDIA card;
- modest-GPU capacity;
- native Linux unattended boot;
- the Windows reboot-before-sign-in sequence;
- moderated sessions with people new to Eugene.

The first outside tester, a friend of Troy's, installs alpha.3 into a freshly
reinstalled Windows sandbox next. His alpha.2 install found the `systemprofile`
models folder and the certificate failure that alpha.3 fixes.

Artifacts:
- Windows: `%TEMP%/ep-alpha3-artifacts`, `%TEMP%/ep-alpha3-release`,
  `%TEMP%/ep-alpha3-windows`;
- WSL: `/home/tcorbin/.cache/ep-alpha3-wsl`.
