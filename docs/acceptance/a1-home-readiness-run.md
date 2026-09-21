# A1: Home readiness, drafts and cancellation

Completed 2026-09-20. This is development acceptance, not a new release.
The original [alpha first-request failure](alpha1-release-run.md) is preserved.

## Implementation

UI source `78e8285c4cb95672a9ca78cff117c437f1f5fa50`; packaged UI/dist
`6090b6c037587e6e74fe159fc41093e5ca5aba2b`. Both development installers now pin
that dist revision. No gateway/agent contract or implementation changed. The
published alpha tag, assets and website version remain unchanged.

Home's Send button now follows the selected gateway routing slot, including
its replicas and fallback targets. A ready backend permits sending; a stopped
runtime explicitly configured for on-demand start also permits sending. Loading,
failed, stopped/manual and unavailable states explain why Send is unavailable.
The prompt remains editable while loading. A routing read failure does not
reuse a previous ready answer. The fast Home reads have request timeouts.

Drafts remain in per-tab session storage across navigation. A request that
fails before delivering an answer restores the prior conversation, so resending
does not duplicate the prompt. Pending work is not saved as completed/replayable
conversation history. A partial answer remains visible after interruption.

Cancel and leaving Home abort the fetch. The shared streaming client now applies
the existing ten-minute Home timeout across both response headers and the body;
previously the streaming path ignored that option. Neither cancellation nor
navigation automatically resends a request. Home still delegates wake/start to
the gateway and never issues a second start or completion in the background.

## Regression and automated checks

`ui/scripts/a1-browser-acceptance.mjs` serves the static export on a new loopback
port and intercepts API responses in Chrome. It does not contact the live install.
The original alpha export failed its first assertion: Send was enabled while the
fixture reported loading. The final packaged export passes six scenarios:

1. Slow healthy startup: type while loading, block Send/Enter, preserve the
   prompt, enable on readiness, send exactly once.
2. Failed startup: replace loading with an actionable failure and keep the draft.
3. Stopped/manual refuses sending; stopped/on-demand permits a single request.
4. Unreachable routing disables stale readiness; a send-time 503 restores the
   draft and retry includes it once in history.
5. Cancel keeps the unfinished draft; returning to Home does not resend.
6. Navigate away with a request pending: preserve the draft and exclude the
   unanswered turn from the shared transcript; returning does not replay it.

The sixth check exposed a navigation race during implementation: Playground could
read the pending transcript before Home's effect cleanup. Persisting only the
previous history until an answer begins fixes the race; the test now passes.

There were six explicit submitted requests across those scenarios and zero
browser errors. Controlled responses test the UI state transitions; they are
not evidence of real-model inference. The separate fresh-install runs below are.
The browser regression is now in UI CI after the static build.

- Full UI suite: **756 passed**, including routing decisions for same-named
  replicas, external backends and on-demand fallbacks.
- Eight streaming cancellation/deadline checks cover proxy and direct transport,
  before headers and during body reading. Existing streaming/tool tests pass.
- Lint, formatting, TypeScript and production static/package build pass.
- UI [CI run 35552327830](https://github.com/eugene-plexus/ui/actions/runs/35552327830)
  passes, including the new browser check, wheel build and codegen freshness.
- S10 isolation/network instruments and release-artifact checks pass. Their
  deliberate regressions are caught; no new release assets were generated.

## Fresh application installs with actual inference

Ran `scripts/s10-acceptance.py` on Windows and WSL with new prefixes, the updated
development installers, normal setup/login, engine acquisition, model start,
packaged Home and a separate authenticated API request. The browser instrument
now waits for the visible Send button to become available before its **first**
submission; it does not retry a failed completion or poll readiness through a
private test-only path.

| Target | Install to first visible token | First request | UI interactions | Separate API request |
| --- | --- | --- | --- | --- |
| Windows | 67.769 s | HTTP 200, `Hello!`, completed stream | 5 clicks, 91 keydowns, 1 configuration value, 0 paths | Nonempty answer |
| WSL | 49.822 s | HTTP 200, `Hi there!`, completed stream | 5 clicks, 91 keydowns, 1 configuration value, 0 paths | Nonempty answer |

Conditions: same AMD Ryzen 9 9950X host; fresh isolated application installs,
not clean operating systems. CPU-only fixture hides accelerators and assigns
isolated ports. Model is **Qwen3-0.6B-Q4_K_M**, seeded from the previous alpha's
test file and named `ep-a1-model.gguf` in these installs. Engine is acquired
llama.cpp **b11065**, CPU build. The starter catalogue's 8B row remains in the
instrument's metadata but was not the inference workload in seeded mode. These
times are not full-model-download measurements or physical GPU acceptance.

All 184 exported UI assets match the freshly installed Windows package. The
Windows acceptance's before/after snapshot confirms the live service and
persistent Eugene environment are unchanged. The WSL test records no Windows
snapshot; it uses its own isolated identity, model copy, ports and processes.
Both disposable agents and their children shut down after acceptance.

Artifacts: Windows `%TEMP%/ep-a1-windows` and WSL
`/home/tcorbin/.cache/ep-a1-wsl`, each with installer/agent/browser logs, JSON
measurements and first-reply screenshot. Browser transition checks:
`ui/test-results/a1/browser.json` and `home-a1.png`; the original failing
instrument record is `%TEMP%/ep-a1-before`. Disposable connection credentials
remain in local artifacts and are not checked into the repository.

## Boundaries

This closes A1's implementation and acceptance. It does not close friend
sessions, physical Mac verification, Windows reboot-before-sign-in verification,
image/API compatibility, shared-client policies or concurrent GPU capacity.
Readiness is a snapshot: a backend can still fail after Send becomes available.
That failure is shown and the unsatisfied prompt is retained; no silent retry
is introduced. Per-tab browser storage remains the persistence boundary.
