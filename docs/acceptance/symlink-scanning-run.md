# R3.5 - the symlink switch controls the scan

**2026-09-20. Built, verified and published.** Roadmap
section 4 item 5, review section 6.2 finding 27. Library commit:
`127c70c0f02d393f8530f2e7b9e8a8890d3b952f`. Implementation and tests touch only
the library; this repo carries the acceptance, sabotage, and record. No API
schema, generated model, or UI source changed. Both installers pin the library
commit above; its archive resolves and CI run `35517442527` passed.

## Reproduction

The first check drove the existing config and scan API over a real directory
link. Saving `followSymlinks: true` succeeded, but the linked model was absent.
On Windows the reverse was also wrong: a directory junction was traversed with
the setting **off**. `is_dir(follow_symlinks=False)` does not exclude junctions.

The adjacent file-link cases failed too: a named GGUF link and an HF snapshot
whose config and weights were links both produced no model. The setting's
label says **directories**; file enumeration independently excluded links.
An HF fixture made from copied files had never exercised that layout.

## Behavior

- `app` gives `ScanManager` a live config reader, evaluated once per scan and
  passed to `Scanner`. A PATCH affects the next scan without a restart.
- Directory symlinks and Windows junctions are skipped by default and followed
  when enabled. An explicitly configured linked root is still scanned.
- File links are read regardless of the directory switch. Model paths, IDs,
  file paths, and roots keep their declared names, never resolved blob paths.
- Each walk branch tracks directory `(st_dev, st_ino)` ancestry. A link back
  to an ancestor is reported in `skipped` as a directory link cycle, using
  existing `not_a_model`; it is not descended into. A global visited set would
  wrongly erase distinct aliases, whose path-derived identities are deliberate.
- A self-referential file link raises during inspection on Linux. That failure
  is reported per entry; healthy siblings remain discoverable.
- Switching off retains an undiscovered model **if it has a profile**, marking
  it missing. Switching on restores the same identity and profile. This is the
  existing store policy, not a new retention rule. Model files are never changed.
- The schema-driven UI already exposes the switch. Its runtime description now
  explains the actual behavior; timeout advice no longer blames cycles this
  traversal detects. No UI rebuild or specs regeneration is needed.

## Verification

| Gate                                         | Result                                        |
| -------------------------------------------- | --------------------------------------------- |
| Full library suite, WSL Python 3.12.14       | 471 passed, 21 skipped                        |
| Full library suite, native Windows repo venv | 468 passed, 24 skipped                        |
| Mypy, library configuration                  | 39 source files, no issues                    |
| Ruff lint                                    | Library and both new scripts pass             |
| `scripts/r35-acceptance.py`, Linux           | 10 PASS                                       |
| `scripts/r35-acceptance.py`, Windows         | 10 PASS                                       |
| `scripts/r35-sabotage.py`, Linux             | 12/12 caught, baseline green before and after |
| `scripts/r35-sabotage.py`, Windows           | 11/11 caught, baseline green before and after |

The acceptance starts a real library on loopback port **8182**, refuses an
occupied port, clears inherited `EUGENE_PLEXUS_*` variables for its child, uses
temporary config/state/model fixtures, and stops only its owned PID. It checks
default-off startup, the existing boolean field, live toggle, cycle reporting,
missing/present transitions, stable identity, saved-profile retention, the
persisted setting on a **real process restart**, and byte-identical model files.
No agent, engine, GPU, model download, live model folder, or service is involved.

The sabotage script copies the library source and tests outside the checkout.
It restores mutations from those copied bytes, never Git, and isolates bytecode
caches per run. Caught mutations remove each wiring link, freeze the config at
startup, force following on/off, disable ancestry at three points, lose cycle
diagnostics, replace aliases with targets, drop file links, discard siblings
after a file-link error, or let junctions bypass the off switch. Linux and
Windows runs share ten mutations; two file-link mutations run on Linux and the
junction-specific mutation runs on Windows. Counts are **23 executions of 13
distinct mutations**, not 23 different defects. Collection errors or hangs do
not count as caught regressions.

Run from specs on Windows with the library's dev interpreter:

```powershell
& ../library/.venv/Scripts/python.exe scripts/r35-acceptance.py
& ../library/.venv/Scripts/python.exe scripts/r35-sabotage.py
```

The equivalent Linux commands use its dev interpreter and the same scripts.
This run used `/home/tcorbin/.cache/eugene-r35-venv/bin/python`, installed from
the library's `[dev]` extra with Python 3.12. The scripts accept `--library`;
acceptance also accepts `--port`.

## Instrument Corrections

The first Windows reproduction failed **before the product**: symlink creation
raised WinError 1314. No elevation was attempted. Tests explicitly skip that
case without the privilege, use real junctions on Windows, and run real
symlinks on Linux. The initial WSL venv under `/tmp` disappeared between tool
calls; the home-directory environment above remained usable.

Two assumptions in the first API test were corrected: config returns
`applied`/`rejected`, not `errors`; and a disappeared entry becomes missing
only when it holds a profile. The finished test saves a profile and checks
both toggles and restoration, rather than changing the store to fit the test.
Adding the self-referential file-link case caught an implementation defect
before the sabotage pass: an `is_file()` exception discarded the whole listing.
The per-entry fix was rerun against that exact failing case before proceeding.

## Limits And Shipping

Windows **junctions** were exercised natively; native Windows symlinks were not,
because this session lacks symlink privilege. No macOS or SMB/NFS filesystem
was used, so directory identity behavior there remains unmeasured. HF-shaped
snapshots use real links and real small format fixtures, not a downloaded model.
No browser clicked the existing generic config control. Live-hub and real-model
tests remain opt-in and were skipped; existing FastAPI/Starlette deprecation
warnings remain.

The library change was committed with DCO sign-off and published directly to
`main` under the standing landing workflow, then pinned in both installers.
No codegen, UI rebuild, service restart, or live-install update was performed.
The roadmap remains the only pickup-point document.