# v0.1.0-alpha.5 distribution acceptance, 2026-09-29

Troy authorized alpha.5 on 2026-09-29: *"Publish the alpha and update the
website so it is current to the latest alpha."* It is a prerelease, not a stable
release, and does not close the owed physical checks or the moderated sessions.

**alpha.4 updates from the console** (Nodes → Versions → Update); alpha.3 runs
the installer again.

## Fixed distribution

- [GitHub prerelease](https://github.com/eugene-plexus/specs/releases/tag/v0.1.0-alpha.5):
  explicitly a prerelease. The annotated tag resolves to specs
  `a1f7f40548a6168ed2040c021fab2a37219a8d4a`.
- **Assets:** `install.ps1`, `install.sh`, `manifest.json` and `SHA256SUMS`,
  generated from committed blobs by `scripts/release-artifacts.py`.
- **Component pins:**

  | Component | Pin |
  | --- | --- |
  | agent | `8935860` |
  | control | `847200f` |
  | gateway | `9d3dcd7` |
  | library | `f4e7979` |
  | inference-driver | `89770ea` |
  | ui dist | `678588b` (from ui `6209595`) |

- **The UI export names this release.** It was built with
  `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF=v0.1.0-alpha.5`, so Add a node's join
  commands name the alpha.5 installer. The pinned archive was checked: a built
  chunk carries `v0.1.0-alpha.5` and `BUILD_INFO` records it.
- **[CI on the exact tag](https://github.com/eugene-plexus/specs/actions/runs/36565900048)**
  passed: 12 jobs, 1 skipped.
- **[Versioned image build](https://github.com/eugene-plexus/specs/actions/runs/36565902947)**
  passed 28 checks with zero failures before publishing.
  - Image: `ghcr.io/eugene-plexus/control-plane:v0.1.0-alpha.5`.
  - Immutable reference:
    `ghcr.io/eugene-plexus/control-plane@sha256:83c2274a69204a2891f4c6d87328e6bb6acef28f793bb5a71f7e2604da425e14`.
  - An anonymous GHCR manifest request returned that digest, checked against
    the response bytes.

| Asset | SHA-256 |
| --- | --- |
| install.ps1 | `e44c0675142f942c3919ec135aa1fd41c7f67a34baaf42204c5be93a4092d6e5` |
| install.sh | `16217d7abb85d980beb29265e12675a0b327aff6da6855ecba080c1b5b08b6b6` |
| manifest.json | `64cfdd869cc1de87709407b643ab716a99d4db13666c6c5d3ee8708a1ae695fb` |

## Before the tag

- **Every acceptance script specs CI runs** passed locally on the final pins:
  16 of 16, plus the pin-agreement, S10 instrument and A8 checks.
- **The playground's browser run** passed 11 of 11 against this UI build.

## Installer execution

The packaged installers were passed to `scripts/s10-acceptance.py --installer`
on Windows and in WSL, in new isolated prefixes. Each run covered setup, engine
acquisition, Home's first reply and a separate authenticated API request.

**The installers are byte-identical to the ones run.** The artifacts were built
from `ff895ee`. The tag commit `a1f7f40` changes only the upgrade instrument,
and its installer hashes match.

| Target | Install | Install to first visible token | Reply |
| --- | ---: | ---: | --- |
| Windows | 14.2 s | 42.3 s | "Hi there!" |
| WSL | 9.3 s | 38.9 s | "Hello!" |

Both runs took five clicks, 93 keydowns, one typed value and no typed paths.
The Windows run confirmed the live service and the persistent environment were
unchanged.

Test conditions:
- the existing Ryzen 9950X host;
- CPU-only fixtures, with isolated ports and fresh identities;
- a seeded Qwen3-0.6B Q4_K_M (`ep-a1-model.gguf`).

These are not full-download timings, clean-OS tests or GPU measurements.

## Upgrading alpha.4

`scripts/updates-system-install-acceptance.sh` with `EP_FROM=v0.1.0-alpha.4`
and `EP_TARGET` the release commit passed **16 of 16**, as root in WSL2 with
systemd:
- alpha.4's own `install.sh` made a system install with its root helper;
- an update to alpha.5 was requested through the request file the app's route
  writes, and root carried it out;
- the agent that came back reported it, running all six alpha.5 commits, six
  of them new;
- **new check 6f:** the old default output cap (2048) that every install before
  2026-09-28 wrote into `gateway.yaml` is gone after the update, and the
  gateway's marker is written.

**The first execution failed on the instrument's input:** `EP_TARGET` was a
short SHA, and the helper refused it (*"did not name a specs commit or a
release tag"*). A full SHA passed.

**Not run here:** a Windows alpha.4 install updated from the console.

## Website

Website `efa8a49`, [CI](https://github.com/eugene-plexus/website/actions/runs/36566915318)
and the [Pages deployment](https://github.com/eugene-plexus/website/actions/runs/36567123014)
passed:
- selects the alpha.5 manifest, and moves alpha.4 into
  `archived-releases.json`;
- **Install:** from alpha.4, update from the console; from alpha.3, run the
  install command again; a container from alpha.3 or alpha.4 keeps its data
  folder;
- **Home:** the tools answer names speech, transcription, images, video and
  plain completions;
- **Architecture:** the boundaries as of alpha.5, with the new endpoints and
  provider accounts in the Client APIs row;
- **Recovery:** the alpha.4 move, and the guide is `docs/recovery.md` at
  `a1f7f40` (unchanged since alpha.4).

Checks:
- Astro check: zero errors, warnings or hints.
- **85 browser cases passed across five widths.**
- The built site serves each release's recorded installer hash at
  `/releases/<version>/` (alpha.5 `e44c0675…`, alpha.4 `96a53b37…`).

Anonymous requests to the live homepage, `/install/`, `/recovery/` and
`/architecture/` returned 200, the live installers served those hashes, and the
install page's commands name alpha.5. The Windows install command is
`irm https://eugeneplexus.com/releases/v0.1.0-alpha.5/install.ps1 | iex`.

**The updater sees it:** `updates.newest_release()` reads `v0.1.0-alpha.5` and
all six pins from the published manifest, so an alpha.4 machine following
`releases` offers the update under Nodes → Versions.

## Remaining limits

As listed in the [release notes](../releases/v0.1.0-alpha.5.md):
- an Intel Arc card;
- two physical cards in one machine;
- the container on a passed-through NVIDIA card;
- a physical Mac;
- modest-GPU capacity;
- native Linux unattended boot;
- the Windows reboot-before-sign-in sequence;
- moderated sessions with people new to Eugene.

Artifacts:
- Windows: `%TEMP%/ep-alpha5-artifacts`, `%TEMP%/ep-alpha5-release`,
  `%TEMP%/ep-alpha5-windows`;
- WSL: `/home/tcorbin/.cache/ep-alpha5-wsl`.
