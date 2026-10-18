# Testing and release architecture: first live Edge publication

Result: the protected Edge marker and registry alias were published by the new
workflow, followed by the agent reader and its release pins. Independent public
registry reads and the real native reader agreed with the promotion receipt.
GitHub run timestamps below are on 2026-10-18 UTC.

Policy: [testing and release runbook](../maintenance/testing-and-release.md).
Earlier evidence: [local checks](testing-release-architecture-local.md).

## Rollout and repairs

1. Set `EDGE_PUBLICATION_PAUSED=true` and created ruleset `25342422`, scoped
   exactly to `refs/heads/edge`: active, deletion and non-fast-forward updates
   prohibited, no bypass actors. Troy explicitly approved this protection.
2. Pushed infrastructure `b18606226aab239a613e34ee0ee6a0ee55637db6` without
   changing component pins. Manual publisher run `39126601973` failed with
   the explicit safety-hold error; the Edge ref remained absent.
3. The real gates found two harness defects. Selecting Python 3.12 exposed
   the container checks' undeclared PyYAML dependency. Open WebUI's log check
   still filtered an obsolete reset phrase on both platforms, although
   reinstall and chat passed. Repair `55d1d7de575e9d1f6b3bdf5cbdf156e6e4868e8a`
   installs pinned PyYAML and matches the actual pinned launcher's reset note.
   Dependency-order regression and a real two-start launcher probe discriminate
   both repairs; no gate was removed or suppressed.
4. Full CI `39128593630` and container run `39128593623` passed. Linux and
   Windows service/integration checks, macOS 14/15/26, Compose and container
   recovery ran. The exact build digest was retained in `verified-container`.
5. Set the hold false. Publisher `39129999160` created the first protected
   marker at `55d1d7d`, after verifying and retagging its tested image.
6. Only then pushed agent `f4792ebb10b5f4d6526124e5aec7fcc98d0516fe`. Its CI
   `39130393694` passed. Updater regression: 61 passed, 2 POSIX-only skips on
   Windows; repository-configured Ruff passed after the commit hook corrected
   import ordering. Live marker discovery also passed before repinning.
7. Pushed the three agent pins as specs
   `5e72f613d7d9c54131edf8331ccded99b56292ce`. CI `39130830857` selected the
   reduced plan and passed; container `39130830820` passed. Automatic publisher
   `39131495187` advanced the protected marker, retaining its receipt.

## Published boundary

Verified candidate: `5e72f613d7d9c54131edf8331ccded99b56292ce`.

Verified image digest:
`sha256:d723e1cb0d3b7e2b7a12cab688ef14ab8158853e16b9ac23fe6c0dedb2234cbc`.

- Actual remote Edge ref matched the candidate; ruleset remained active.
- Public GHCR HEAD and GET returned 200 for `:edge`, `sha-<candidate>` and the
  immutable digest. Every manifest header and downloaded manifest SHA-256
  matched the receipt's tested digest. Anonymous authentication stayed in
  memory; no token was printed or retained.
- The actual published agent source's `updates.newest_edge()` returned that
  specs ref and seven full pins, including agent `f4792eb`. All matched the
  remotely fetched immutable release manifest; both installer URLs returned
  HTTP 200. No agent or application was started to perform this check.
- Promotion artifact `12137953383` independently bound the candidate, digest
  and CI run `39130830857`; its image run was `39130830820`.

Subsequent documentation-only publication can advance the marker while reusing
these unchanged runtime/image inputs. It does not require a new image build.

## Coverage and cost

The pin-only plan set runtime, launch, installers, instruments, macOS and
container true; full, dev, uninstall and contracts were false. macOS 26 ran;
the full-only app-account, Open WebUI, folder-tool and other unrelated jobs
were skipped. They had passed in the preceding full infrastructure run.

Comparable CI-only receipts, using workflow start to last job completion:

| Measure | Full infrastructure | Reduced agent pins |
| --- | ---: | ---: |
| CI run | 39128593630 | 39130830857 |
| Successful / skipped jobs | 27 / 3 | 11 / 10 |
| Elapsed | 1,116 s (18m36s) | 544 s (9m04s) |
| Summed non-skipped jobs | 5,435 s (90m35s) | 1,572 s (26m12s) |

Observed reductions: 51.3% elapsed and 71.1% summed job time. These are different
commits and intentionally different coverage, not a fixed-workload benchmark
or a guaranteed per-slice saving. Parallel workflow wall times were not added.

## Limits and preservation

The hold/failure/repair/retry path and both real promotions were exercised.
No mid-promotion network outage was injected. Registry retagging and Git ref
movement remain separate operations, not an atomic transaction. Real native
installation/upgrade, live NAS operation, GPU inference and full versioned
Release qualification were not run as part of this publication trial.

No running installation was restarted or reconfigured. The unrelated two-host
acceptance changes and local PowerShell indentation edits were left uncommitted
and untouched. The known preexisting unused import in the C4 harness was not
changed. Secret scans covered the exact changed inputs before each push.