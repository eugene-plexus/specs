# Shared update status — 2026-10-04

Reported sequence: update the NAS container, see a Needs Attention warning
about differing versions, then open Machines and find only “Up to date” cards.
The issue list and Machines read independently, and the workers' channel
checks could be six hours old. An Edge container can also publish before the
remaining native installation checks finish.

The console now shares one snapshot and one poll across Machines, Needs
Attention and Home. A mismatch refreshes stale enabled checks. Machines
repeats the mismatch explanation and says “No newer update found” when a
verified update is not available. It distinguishes failed checks from an
all-clear, compares every shared stamped component (including UI), and clears
the warning and page notice together when versions match. No installation,
channel change or downgrade is performed by these checks.

Source: `ui@23ffef4cd4c0b967c9f617e8ee6768d0f815f3c9`.
Packaged export: `ui@b7131c33ac5d9be2577d7f384a55e15946932935` (`dist`).
Agent and all other component pins are unchanged from the preceding Edge.

## Local evidence

- UI: **1,666 tests passed**, 138 files; lint, typecheck, formatting and
  production static export passed.
- New regressions exercise shared reads, stale worker checks, automatic retry
  throttling, disabled checks, HTTP failures, a refresh during an old read,
  full commit comparison, UI-only releases, differing channels and an update
  already in progress.
- `node scripts/update-status-browser-acceptance.mjs out
  test-results/update-status`: **four checks passed in Chrome**, no browser
  errors. This serves the actual production export against disposable
  responses, never the developer's running installation:
  1. A stale worker checks automatically; pending Edge is explained in both
     places without “Up to date” beside the mismatch.
  2. Check now changes the worker's available action and the warning together.
  3. A failed check says so instead of claiming the machine is current.
  4. Observing matching versions clears the already open warning and the
     Machines notice without F5.
- The browser check made three check requests and no installation request.
  It is now part of the UI's CI workflow.

## Publication gates

The release manifest and both generated installers pin the packaged export.
Publishing follows the normal Edge checks: UI CI, specs CI (Windows/Linux
installation acceptance), A4 macOS installation, and the container build,
compose and recovery checks. The native updater continues to require a
completed successful workflow set; the UI does not bypass this gate to make
the warning go away.

The five-minute browser retry cooldown is per machine and per open console
session. The agent's ordinary six-hour cadence remains unchanged; manual
Check now and the final check on Update remain available.
