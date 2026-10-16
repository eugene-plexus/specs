# Edge: two-host access and signing decisions

Publication on 2026-10-16 follows Troy's approval of the pre-Edge issue review.
The container workflow builds and publishes Edge asynchronously after its
acceptance checks pass. This record does not claim that the image build or
upload has finished. No stable tag or running installation was changed.

## Included changes

- Two public HTTPS hostnames for Eugene and Workbench; an optional model API
  at Eugene's `/inference/v1`, with its own network policy and authentication.
- Existing hostnames, console placement and network policies retained. The old
  inference hostname can remain available while clients migrate.
- SSO derives its canonical address from managed access setup unless the owner
  has an explicit override. The effective address and callback are visible.
- Workbench keeps decisions received during Job Site polling, requests fresh
  approval if the held request changes, and always honors a decline.
- The issue review retains stored-data migrations and leaves the five deferred
  feature requests in the backlog.

## Published inputs

Contracts were published first at `c3f59f743e8b14f2beb5ae1c3be16e1c14d5009a`.
Agent, control and UI regenerated from that GitHub archive in their own environments.
The measured contract radius and prior local acceptance remain recorded in the
[two-host run](two-host-access-2026-10-16.md).

| Component | Commit |
| --- | --- |
| Agent | `2b4e6a0207d2f7b4559f8007cf0149c7e2771b84` |
| Control | `77a15f0f1b74e83aa8c569bf88ccfc9a688bbe62` |
| Console source | `3ec4bc08cb7eba8d4a6c9d671d6845f17657abbe` |
| Console distribution | `b94cef8d2e105e2a8d04915d61c846ca80330e43` |
| Workbench source | `d7531f564d0ec82a3dee7072e25262c4d3ae6e94` |
| Workbench distribution | `5d14e4caaa0181e319d72cd67f205b2c9a10e86b` |

The other component pins and dependency lock are unchanged. The agent catalogue
names the new Workbench distribution. Both distribution commits retain their
previous distribution and current source histories. All 277 console files and
183 Workbench files were compared against committed Git blob hashes after commit
hooks and matched the production build bytes. Console builds use
`NEXT_PUBLIC_INSTALL_REF=main`.

Python lint, format and type checks (agent on Windows and Linux), console lint,
production frontend builds, published-contract regeneration, staged secret scans
and installer consistency checks passed. The earlier two-host acceptance passed
226 focused tests, 22 real-Caddy checks and desktop/mobile browser checks. The
[signing follow-up](signed-call-poll-race-2026-10-16.md) passed 38 tests and caught
all three targeted mutations. Full suites and container acceptance run in CI.

## Rollout

Keep the existing control-port mapping while enrolled machines use that address.
This release does not rewrite worker control addresses. Active and standby roots
must share the canonical sign-in address. Workbench has its own app update in
addition to the control-plane container update.
