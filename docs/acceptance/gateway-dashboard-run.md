# Gateway operations dashboard — 2026-10-15

Request: make Gateway Metrics a substantial administrator dashboard, with
varied dials where the measurement has a meaningful denominator.

Published UI source: `e1fdfbac9b6bd2be1c36938f244ea776ff96d3c9`.
Installable UI distribution: `9ebaed4e2662c5640d1f19b123dc0384330ee2d4`.
The release manifest and both installers select that distribution. Other
component pins and the public contracts are unchanged.

## Browser evidence

The production static export ran in system Chrome on Windows against isolated
fixture APIs on an OS-assigned loopback port. No live gateway, runtime, client
key, or model was changed. The shell's read-only folder check was intercepted;
the dashboard made no API mutations.

- [Overview and success donut](gateway-dashboard-data/metrics-desktop.png)
- [Capacity needles and segmented cache ring](gateway-dashboard-data/metrics-capacity.png)
- [Mobile overview](gateway-dashboard-data/metrics-mobile.png)
- [Light theme](gateway-dashboard-data/metrics-light.png)
- [Machine-readable checks](gateway-dashboard-data/browser.json)

Chrome verified unique backend counting across model aliases, capacity and
sleeping-route status, hourly panels, server outcome filtering, retained request
traces, and a downloaded JSON snapshot with exact values and explicit scopes.
The page fit 1600, 1280, 768, 390 and 320 px widths without page overflow.
Detailed comparison/usage tables retain their own horizontal scroll containers.

Injected failures verified that a failed refresh retains a visibly stale
snapshot and disables export, a routing read failure leaves historical panels
available, dropped and expired measurements remain visible, and disabled
recording differs from an empty window. No browser exceptions occurred.

## Checks and review

The full pre-dial UI suite passed: 2,079 tests in 165 files. After the dial
addition and final visual adjustments, all 57 affected tests in six files
passed, including three new gauge tests. TypeScript, ESLint, Prettier, production
build, whitespace checks and staged source/distribution secret scans passed.

Four temporary-copy mutations were detected by assertions: double-counting
model aliases, merging same-name drivers on different nodes, ignoring the
request-outcome filter, and showing an absent p99 as zero. Original source
fingerprints were preserved. The checker and browser acceptance now run in CI.

Adversarial review covered aggregation identity, null/zero distinctions,
scope changes, partial reads, out-of-order responses, hidden table accessibility,
export scope/freshness, dial denominators and overload, and chart color-independent
encoding. Visual inspection caught a needle overlapping its percentage label,
the comparison dash applied to a point rather than the line, and excess space
in the three-backend layout; the final export and screenshots include the fixes.

## Installable artifact

The exact published GitHub archive matched every changed product module and all
267 assets in the Chrome-tested export. The distribution differs from its source
only by static assets and BUILD_INFO (`installer-ref: main`). Its exported
installed-commit stamp matches the distribution SHA.

A wheel built from that archive imported under Python 3.12.14, reported that
same commit, and contained all 267 assets byte for byte. Wheel SHA-256:
`8d518cf3d9d4091ad2390f5d2ad17d5dce1368364378674f85beadfb9fa0d088`.

Installer regeneration/freshness and release-artifact checks passed, including
the intentional divergent-platform-pin mutation. The previous engine-overview
CI finished successfully. [This UI CI run](https://github.com/eugene-plexus/ui/actions/runs/38839072444)
was in progress when checked; publication does not wait for CI.

No live installation was upgraded. These screenshots show fixture traffic,
not measured production QWen performance. This is gateway request/routing
observability; host hardware history, alert delivery and SLO policies remain
separate work, as recorded in the [design](../design/gateway-operations-dashboard.md).
