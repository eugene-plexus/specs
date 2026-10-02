# v0.1.0-alpha.6 distribution acceptance, 2026-10-01

Troy authorized alpha.6 on 2026-10-01: *"I'm happy to publish this page, but
also to publish the next alpha, including Workbench."* He chose to fix the
three defects the first person's chat found before tagging (C3 record, *The
three fixed, for alpha.6*). It is a prerelease, not a stable release, and does
not close the owed physical checks or the moderated sessions.

**alpha.5 and alpha.4 update from the console** (Nodes → Versions → Update;
the page is under Machines once a machine runs alpha.6); alpha.3 runs the
installer again.

## Fixed distribution

- [GitHub prerelease](https://github.com/eugene-plexus/specs/releases/tag/v0.1.0-alpha.6):
  explicitly a prerelease. The annotated tag resolves to specs
  `ee3acf1466a160bb2c0abe6b69dc66dd2de0f6b2`.
- **Assets:** `install.ps1`, `install.sh`, `manifest.json` and `SHA256SUMS`,
  generated from committed blobs by `scripts/release-artifacts.py`.
- **Component pins:**

  | Component | Pin |
  | --- | --- |
  | agent | `cd34826` (its catalogue pins Workbench `dist` `5ed0001`, from Workbench `576ec85`) |
  | control | `6a3c24b` |
  | gateway | `05efc88` |
  | library | `6e22230` |
  | inference-driver | `53412d5` |
  | tool-driver | `df23d92` (new since alpha.5) |
  | ui dist | `872abd5` (from ui `2c6e5e5`) |

- **The UI export names this release.** It was built with
  `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF=v0.1.0-alpha.6`, so Add a node's join
  commands name the alpha.6 installer: a built chunk carries `v0.1.0-alpha.6`
  and `BUILD_INFO` records it.

| Asset | SHA-256 |
| --- | --- |
| install.ps1 | `fdd2d007c2a54080b50c3dd1f8296a424136bb9e16ec93c8fca05572bf72aace` |
| install.sh | `7831851cb51cc9e86222b818df05fa20c0e3829091c1cbed8fa83d0388a56ce0` |

## Before the tag

- **The three fixes** each passed their repository's suite and a sabotage pass
  (gateway 6 of 6, Workbench 15 of 15, tool-driver 25 of 25). C3's new check
  13b fails on the old Workbench (27 of 28) and passes on the pinned one, 38 of
  38 with Chrome, Workbench installed from the catalogue's archive.
- **Every script specs CI runs** passed locally on the final pins, 25 of 25, in
  a Python 3.12 environment shaped like CI's.
- **CI on the pin commit** `9476d7b`: CI, the A4 macOS run and the container image all passed.

## Installer execution

The packaged installers were passed to `scripts/s10-acceptance.py --installer`
on Windows and in WSL, in new isolated prefixes. Each run covered setup, engine
acquisition, Home's first reply and a separate authenticated API request.

**The installers are byte-identical to the ones run.** The artifacts were built
from `9476d7b`. The tag commit adds only the release notes, and its installer
hashes match.

| Target | Install | Install to first visible token | Reply |
| --- | ---: | ---: | --- |
| Windows | 15.4 s | 43.8 s | "Hello, how are you?" |
| WSL | 9.7 s | 45.5 s | "Hello, how are you, there!" |

Both runs took five clicks, 94 keydowns, one typed value and no typed paths,
and the separate API request answered "Hello!". The Windows run confirmed the
live service and the persistent environment were unchanged.

Test conditions:
- the existing Ryzen 9950X host;
- CPU-only fixtures, with isolated ports and fresh identities;
- a seeded Qwen3-0.6B Q4_K_M (`ep-a1-model.gguf`).

These are not full-download timings, clean-OS tests or GPU measurements.

## Upgrading alpha.5

`scripts/updates-system-install-acceptance.sh` with `EP_FROM=v0.1.0-alpha.5`
and `EP_TARGET` the pin commit (`9476d7b…`, full SHA) passed **16 of 16**, as
root in WSL2 with systemd:
- alpha.5's own `install.sh` made a system install with its root helper;
- an update was requested through the request file the app's route writes, and
  root ran the new installer;
- the agent that came back reported it, running all seven alpha.6 commits,
  seven of them new: the tool-driver arrived with the update.

**Not checked by that run:** that the updated install's app helper
(`eugene-plexus-apps-ctl.path`) is enabled, and Workbench installed on it.
The new installer writes them, and C1 checks them on fresh installs.

**Not run here:** a Windows alpha.5 install updated from the console.

## Tag CI and the image

- **[CI on the exact tag](https://github.com/eugene-plexus/specs/actions/runs/36961190597)**:
  passed: 12 jobs, 1 skipped (the DCO check, which runs on pull requests).
- **[Versioned image build](https://github.com/eugene-plexus/specs/actions/runs/36961193162)**
  passed **29 checks** with zero failures before publishing.
  - Image: `ghcr.io/eugene-plexus/control-plane:v0.1.0-alpha.6`.
  - Immutable reference:
    `ghcr.io/eugene-plexus/control-plane@sha256:89ba518c1b42e9255a9716890908d20aad9110a79785ef8c40c9c6fdb789c7f1`.
  - An anonymous GHCR manifest request returned that digest, checked against
    the response bytes.
- **The release assets were rebuilt from the tag**, and the installers'
  hashes match the ones run. `manifest.json` is
  `e04ab1ca86985a43c2cfea578e82e9fcebfd9a5172445ce599b4ed66b90adc6f`.

**Found while publishing, filed:** a recovery checkpoint leaves out an app's
data on a Linux system install, where systemd keeps it outside the prefix
([specs #11](https://github.com/eugene-plexus/specs/issues/11)). Found by
reading `recovery.py` against C1's unit, not by a run. It is a known issue in
the release notes and on the website's recovery page.

## Website

Website `652b167`, [CI](https://github.com/eugene-plexus/website/actions) and
the [Pages deployment](https://github.com/eugene-plexus/website/actions/runs/36961961695)
passed:
- selects the alpha.6 manifest, and moves alpha.5 into
  `archived-releases.json`;
- **Install:** from alpha.4 or alpha.5, update from the console; the console's
  alpha.6 names (*Settings → Updates*, *Settings → Access & security*,
  *Settings → Model storage on each machine*, *Machines*), which the
  reorganised UI changed after alpha.5;
- **Home:** MLX no longer called experimental, web search on the tools answer,
  and a *Is there a chat app?* answer for Workbench;
- **Architecture:** the alpha.6 snapshot, web search in Client APIs, MLX in
  Engines and hosts, and a new *Apps and sign-in* row;
- **Recovery:** the alpha.5 move, the guide unchanged (its `recovery.py` link
  now at the tag), and the app-data gap (specs #11);
- **[It looked itself up](https://eugeneplexus.com/first-search/):** *Try it*
  says Workbench and web search are in this release, and its notes say what
  alpha.6 fixed.

Checks:
- Astro check: zero errors, warnings or hints.
- **109 browser cases passed across five widths.**
- The built site serves each release's recorded installer hash at
  `/releases/<version>/` (alpha.6 `fdd2d007…`, alpha.5 `e44c0675…`).

Anonymous requests to the live homepage, `/install/`, `/recovery/`,
`/architecture/` and `/first-search/` returned 200, the live installers served
those hashes, and the install page's commands name alpha.6. The Windows install
command is `irm https://eugeneplexus.com/releases/v0.1.0-alpha.6/install.ps1 | iex`.

**The updater sees it:** `updates.newest_release()` reads `v0.1.0-alpha.6` and
all seven pins from the published manifest, so an alpha.5 or alpha.4 machine
following `releases` offers the update.

## Remaining limits

As listed in the [release notes](../releases/v0.1.0-alpha.6.md):
- an Intel Arc card;
- two physical cards in one machine;
- the container on a passed-through NVIDIA card;
- a physical Mac;
- modest-GPU capacity;
- native Linux unattended boot;
- the Windows reboot-before-sign-in sequence;
- moderated sessions with people new to Eugene;
- a live Brave account (its rate-limit headers are read as Brave documents
  them);
- Workbench running in an app account of its own.

Artifacts:
- Windows: `%TEMP%/ep-alpha6-artifacts`, `%TEMP%/ep-alpha6-windows`;
- WSL: `/home/tcorbin/.cache/ep-alpha6-wsl`;
- upgrade: `%TEMP%/ep-alpha6-upgrade.log`.
