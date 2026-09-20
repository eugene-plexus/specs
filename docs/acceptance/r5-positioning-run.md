# R5 — positioning

Completed 2026-09-20. Website `4ebd94a`, UI source `fa69ae6`, UI dist
`a04a5eb`; both installers pin the new dist. Measurement evidence was
published in specs `3b493e7`. This slice changes copy and documentation,
not inference behavior or the release gate.

## What changed

Website `0fd2e83` had already completed much of the scope on another work
session, including both API formats, the first three positioning claims in
the adopted order, and optional local copies instead of “never copied.” Its
README also records removal of the standalone numbers showcase on September
20. R5 preserves that work and its Modern design.

The site now leads with engine setup, describes R8's saved model defaults and
caller precedence, updates the architecture dependency on Library, and
replaces the obsolete unfinished-R7 claim with public-key verification and
explicit legacy rotation. Its Windows note distinguishes CI-tested service
start/stop from outstanding reboot-before-sign-in verification. It retains
the no-public-release notice, API limits, and physical-hardware caveats.

Home now explains downloads into the operator's own folders and starting
settings chosen for the machine. The existing-app action names subscriptions,
and the connection card names Claude Code alongside OpenAI-compatible tools.
No workflow, action order, visual theme, or runtime state changed.

## Positioning coverage

The [adopted seven lines](../design/local-inference-control-plane.md) retain
their existing idea numbers. The first three lead the website's Platform
section; the remaining lines appear in the routing workflow and FAQs.

| Idea | Public surface | Console surface |
| --- | --- | --- |
| Install, update and restart engines | Engine setup card and Run workflow | First-model explanation and existing engine confirmation |
| Fit guidance and starting settings | Settings card and Discover/Configure workflow | Machine-specific recommendation and starting-settings copy |
| Discover into owned folders | Files card and Discover workflow | Download destination explanation and existing-models link |
| One endpoint for tools | Hero, Route workflow and client FAQ | App connection card and existing recipes for both protocols |
| Existing backends and subscriptions | Route workflow and engine FAQ | Existing app or subscription action |
| Reach from other devices | Multi-machine FAQ, trusted LAN/mesh VPN guidance | Existing Reach card and its state-specific steps |
| Grow into a homelab | Platform introduction, multi-machine FAQ and architecture | Existing install resource tree and remote management |

## Measurements

The architecture page links [control-plane measurements](control-plane-measurements.md).
It consolidates dated source records instead of adding a prominent benchmark
section. The 172 ms result did not exercise a failed backend attempt; the wake
wait was 2,546 ms within a 2,953 ms request; the streaming percentages have
different total-duration denominators; and the 21-second local start had a warm
cache after a first copied start that took 290 seconds. HTTP overhead was
measured against a stub and predates R8. No GPU load, engine kill, new benchmark,
or change to the operator's live installation was performed for this slice.

## Validation and distribution

- UI typecheck and lint pass, with **78 focused Home, state and vocabulary
  tests** passing. Full UI CI `35534746735` passed its tests, formatting,
  codegen freshness, production build and wheel build.
- Website Astro checks report no errors, warnings or hints. **30 browser
  checks pass** across 320, 390, 768, 1440 and 1920 pixel widths, covering
  current claims, local assets, overflow, accessibility, keyboard navigation,
  and JavaScript-disabled browsing. Phone and desktop screenshots reviewed.
- The first longer hero draft pushed the workflow navigation below the initial
  320×740 viewport. Shortening the copy restored the existing layout check.
- A pre-existing Astro preview was left running. Local browser verification
  used a temporary config with `--ignore-lock`, its own foreground preview on
  port 4322, and the unchanged production tests. The temporary config was
  removed; the existing preview was not stopped or reused.
- UI built from committed source in an isolated worktree. **184 static assets
  match byte-for-byte** between the production export, dist branch and Python
  wheel, and the packaged bundle contains the updated app-connection copy.
- Website publication uses the existing manual Pages workflow; a source push
  alone does not publish it. The updated UI ships through both installers and
  the container build. This is a development update, not a platform release.

R6 begins with the profile benchmark button. Its usability work and the
unchanged release checks remain outstanding.
