# Cleanup before v0.2.0: every pre-v0.2 compatibility shim

Troy, 2026-10-09: *I do not value compatibility with v0.1*. v0.2 is the
oldest supported version, and the shims kept for older consoles, agents,
Libraries, gateways, drivers, sites and files go before v0.2.0 ships
(specs#22). Swept 2026-10-10 across every repo; removed the same night.

**Call building made, for Troy's veto:** shims that serve an older client,
component, protocol or file layout are removed; shims that carry a person's
**stored data** forward are kept, and listed below for his call, because
removing one loses data on an install not yet upgraded rather than merely
refusing an old client.

## Removed

| Repo | What | Commit |
| --- | --- | --- |
| specs | `GET /v1/catalogue/search` (B37); `EngineDescriptor.modelFormats` reworded as the summary Home reads | `bb95734` |
| specs | `GET /v1/auth/client-keys/revoked` and `ClientKeyRevocations`; update states `pending` and `inferred`; `UpdateStatus.channel` required | `beece23` |
| specs | the download claim and `runWhenReady` | `a2a66ad` |
| specs | the run protocol's `Intent.downloadId` and `runWhenReady` | `e332dde` |
| specs | `OutdatedDriver`, `outdated_drivers`, `DriverHealth.outdated` | `bfedd8b` |
| agent | B3/B24/B6 worker fallbacks; B25 Strata runtime on its configuration (now refused, naming why); keyring single-slot fallback; update-channel settling; the revoked-keys route | `527c88e` |
| library | B34 old catalogue keys (migrate, mirror, PATCH); B37 GET search; v0.1's Download-and-run (claim, `runWhenReady`, `downloadId`) | `aa3da2e` |
| gateway | drivers from before P1; the one-off 2048 `defaultMaxTokens` clearing; the `conversation` alias | `9e1313f`, `e4e2b52` |
| ui | B67, B3/B16/B24, B37 fallbacks; v0.1 download resume; pre-P1 drivers; old update states and the `ahead` guess; cyberpunk alias; `/runtimes` redirect; bare folder string | `97244f79` |
| control, site-host, workbench | Job Site hosts and roots older than 2b.x (folder routes and actions), keyring fallback, `public-nodes` header, pre-M5 404, the approve page from `link_page`, older-gateway branches | (below) |

`EngineDescriptor.modelFormats` stays: it is required, predates `accepts`,
and Home reads it as a summary; nothing judges from it any more.

## Kept (stored data): Troy's call

1. Library state v1 → v2 (profiles stored inside the state file).
2. Site host `policy.json` v1 (people's sharing rules).
3. Workbench store schema steps (chats) and gateway metrics schema
   v2-v11 (metrics history).
4. The control root's replay of retired log entries (Troy's NAS root log
   probably holds some).
5. Client keys with no limits (live keys in people's apps).

Also kept: saved profiles with llama.cpp's boolean `flashAttention`; the
update checker reading alpha releases without a tool-driver pin; the
driver's optional `model`; the guidance `fitModel` default; bare-string
`modelRoots` (the setup wizard sends them).

## What it changed for a person

- A Library config file from before the source list now gets the default
  list: a hub token kept only in the old keys must be entered again.
- A Strata runtime declared on Strata's configuration is refused, naming
  why (none exist outside test installs).
- An install that never saved an update channel follows the default
  (`releases`, or `edge` in the `:edge` container).
- POST search with *Search and download models* off answers each hub's
  problem rather than refusing the whole search.

## Checks

Before the pins: agent 2,167 passed (ruff, format, mypy for Windows and
Linux, vendored check); library 748; gateway 1,269; ui 1,831 (tsc, eslint,
prettier, vendored check); the LS1-LS8, LS7b and A3 client-key acceptances;
the run-protocol check; the vendored-file check. The run-protocol check's
fake agent reported no `accepts` and its fake Library served no judge, so it
had relied on the B3 fallback: it now reports `accepts` and serves the
Library's own `POST /v1/eligibility`.

Manual scripts not in CI that exercised removed shims are left as records of
their runs: `client-keys-acceptance.sh` (the revoked route),
`download-and-run-acceptance.sh` (the claim; the feature is gone),
`m3-acceptance.sh` and `starter-set-acceptance.sh` (GET search),
`r12-acceptance.sh` (`catalogueBaseUrl`). The per-slice sabotage scripts'
anchors drift as code changes; refresh them before the release's full
sabotage pass.
