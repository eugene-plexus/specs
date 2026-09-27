# v0.1.0-alpha.4 distribution acceptance, 2026-09-27

Troy authorized alpha.4 on 2026-09-27: *"I think we're ready to update the
website and the alpha release."* It is a prerelease, not a stable release, and
does not close the owed physical checks or the moderated sessions.

**alpha.3 upgrades in place:** run the installer again. From alpha.4 on, each
machine updates from the console.

## Fixed distribution

- [GitHub prerelease](https://github.com/eugene-plexus/specs/releases/tag/v0.1.0-alpha.4):
  explicitly a prerelease. The annotated tag resolves to specs
  `da76daf2aec63356f5cea86ad6c040d7627ffc94`.
- **Assets:** `install.ps1`, `install.sh`, `manifest.json` and `SHA256SUMS`,
  generated from committed blobs by `scripts/release-artifacts.py`.
- **Component pins:**

  | Component | Pin |
  | --- | --- |
  | agent | `1b416da` |
  | control | `40ec143` |
  | gateway | `f6e0211` |
  | library | `cec7815` |
  | inference-driver | `8c6f5a8` |
  | ui dist | `a7ab175` (from ui `5506613`) |

- **The UI export names this release.** It was built with
  `NEXT_PUBLIC_EUGENE_PLEXUS_INSTALLER_REF=v0.1.0-alpha.4`, so Add a node's join
  commands name the alpha.4 installer. The pinned archive was checked: a built
  chunk carries `v0.1.0-alpha.4`, `BUILD_INFO` records it, and `_build.py`
  carries the archive's own commit.
- **[CI on the exact tag](https://github.com/eugene-plexus/specs/actions/runs/36351990826)**
  passed: 12 jobs, 1 skipped.
- **[Versioned image build](https://github.com/eugene-plexus/specs/actions/runs/36351992279)**
  passed 28 checks with zero failures before publishing.
  - Image: `ghcr.io/eugene-plexus/control-plane:v0.1.0-alpha.4`.
  - Immutable reference:
    `ghcr.io/eugene-plexus/control-plane@sha256:a33e239385d6841dd9659e880f1c1ebb358309605e8b93d4b33c7b0276c9fb85`.
  - An anonymous GHCR manifest request returned that digest, checked against
    the response bytes.
- **The updater's `releases` channel** reads `v0.1.0-alpha.4` and all six pins
  from the published manifest. An install from these installers therefore
  recognises itself as on `releases`.

| Asset | SHA-256 |
| --- | --- |
| install.ps1 | `96a53b37a46c415e0458f282891fef83097192cb87d4ee1e2e50a12dca4256dc` |
| install.sh | `25e25489c1c569e210a76c453e2e34ea8476ef7e05ce7e49a4b16c8e620768f4` |
| manifest.json | `ebcfcf45f4fe96b91d08f930cd5d4297d6f48f7217d54cbd4168c0cb45e6ca64` |

All four uploaded assets were downloaded anonymously. `sha256sum -c` passed,
and each one matched the packaged file byte for byte. The tag's raw
`install.ps1` has the same hash.

## Installer execution

The packaged installers were passed to `scripts/s10-acceptance.py --installer`
on Windows and in WSL, in new isolated prefixes. Each run covered setup, engine
acquisition, Home's first reply and a separate authenticated API request.

**The installers are byte-identical to the ones run.** The first artifacts were
built from `0727968`. The tag commit `da76daf` changes only the S10 instrument,
and its installer hashes match.

| Target | Install | Install to first visible token | Reply |
| --- | ---: | ---: | --- |
| Windows | 12.8 s | 39.5 s | "Hello, how are you?" |
| WSL | 9.5 s | 37.2 s | "Hello!" |

Both runs took five clicks, 93 keydowns, one typed value and no typed paths.
The Windows run confirmed the live service and the persistent environment were
unchanged.

Test conditions:
- the existing Ryzen 9950X host;
- CPU-only fixtures, with isolated ports and fresh identities;
- a seeded Qwen3-0.6B Q4_K_M (`ep-a1-model.gguf`).

These are not full-download timings, clean-OS tests or GPU measurements.

**The first Windows execution failed, and the failure was in the instrument.**
The fixture that makes the run CPU-only hid the vendor GPU tools. It did not
hide `gpu_probe`, which since 2026-09-27 lists every GPU through DXCore in the
agent and the library. So the run saw this box's integrated Radeon, scored the
seeded model against its 1.36 GiB, and refused the launch. The fixture now hides
`gpu_probe` in both (specs `da76daf`), and the second execution passed.

## Upgrading alpha.3

`scripts/updates-system-install-acceptance.sh` with
`EP_FROM=v0.1.0-alpha.3` passed 17 of 17, as root in WSL2 with systemd:
- alpha.3's own `install.sh` made a system install, and a passphrase was set;
- this release's installer, run over it, upgraded it in place;
- the passphrase set before the upgrade still signed in;
- the root helper and its units were installed;
- an update was asked for the way the app asks, and root carried it out;
- the agent that came back reported it.

**Not run here:** a Windows alpha.3 install upgraded in place. The Windows
service upgrade by re-running the installer is the path the owner's worker has
taken repeatedly.

## Website

Website `981d9ce`:
- selects the alpha.4 manifest, and moves alpha.3 into `archived-releases.json`;
- **Install:**
  - from alpha.3, run the install command again;
  - from alpha.4 on, update from Nodes → Versions, and the check can be turned
    off;
  - alpha.2 is still a fresh install;
  - a container keeps its data folder, and sets its Advertise address when
    workers join.
- **The Linux section describes the default since alpha.3:** a system service
  under its own account, after one `sudo` prompt. It had still described the
  per-user layout, which is now the `--user` option.
- **Home:**
  - the graphics-card requirement names AMD, Intel and integrated graphics;
  - the privacy answer says Eugene asks GitHub every six hours whether a newer
    version is out.
- **Architecture:** the boundaries as of alpha.4, with an Updates and logs row.
- **Recovery:**
  - the alpha.3 move is in place;
  - an update from the console makes no checkpoint for you;
  - the guide is `docs/recovery.md` at `da76daf`.

Checks:
- Astro check: zero errors, warnings or hints.
- **85 browser cases passed across five widths** on the second run. The first
  run failed twice at every width, and neither failure was in the release:
  - a new privacy sentence was 39 words against the site's 25-word limit, and
    was split;
  - a no-JavaScript check expected one paragraph in the container details,
    which now has three.
- [Website CI](https://github.com/eugene-plexus/website/actions/runs/36352449188)
  and the [Pages deployment](https://github.com/eugene-plexus/website/actions/runs/36352581728)
  passed.

Anonymous requests to the live homepage, `/install/`, `/recovery/` and
`/architecture/` returned 200. The installers at `/releases/<version>/` serve
each release's recorded hash (alpha.4 `96a53b37…`, alpha.3 `9b7fe903…`,
alpha.2 `543d7930…`). The Windows install command is
`irm https://eugeneplexus.com/releases/v0.1.0-alpha.4/install.ps1 | iex`.

## Remaining limits

The owed checks, as listed in the [release notes](../releases/v0.1.0-alpha.4.md):
- an Intel Arc card;
- two physical cards in one machine;
- a Windows machine updating itself from the console;
- the container on a passed-through NVIDIA card;
- a physical Mac;
- modest-GPU capacity;
- native Linux unattended boot;
- the Windows reboot-before-sign-in sequence;
- moderated sessions with people new to Eugene.

Artifacts:
- Windows: `%TEMP%/ep-alpha4-artifacts`, `%TEMP%/ep-alpha4-release`,
  `%TEMP%/ep-alpha4-windows`;
- WSL: `/home/tcorbin/.cache/ep-alpha4-wsl`.
