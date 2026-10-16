# Two hostnames and an automatic sign-in address

Implemented and verified locally; included in the
[Edge publication](edge-two-host-access-2026-10-16.md). No running service,
DNS record, proxy host, certificate trust or stable tag was changed.
The preceding SSO Edge container and broader specs CI were checked and passed
before this work began (runs 38956595889 and 38956596394).

## Result

New access setups use the console and Workbench HTTPS names on one port. The
optional model API uses `https://eugene.<domain>/inference/v1`, with its own
network rules and gateway authentication. The existing Engines page at
`/inference/` remains reachable under the console's policy. Workbench retains
its separate browser origin.

Existing setups retain their saved console placement, hostnames and access
rules, including IPv4-only public inference policies. Selecting the shared API
address offers to retain the old inference hostname and its policy until clients
have moved. The old hostname is removed only when the owner chooses that option
and applies the configuration. Preparing or opening setup changes no running state.

SSO uses the root's managed console address plus `/oidc` when no explicit
override exists. Discovery, app registrations and provider setup agree on that
address. Existing overrides stay in effect. People displays the effective value,
callback URL, and an advanced override/reset control. Request headers cannot
establish a canonical address for enabling external sign-in.

## Evidence

- Real Caddy 2.11.7 on disposable WSL ports: **22 checks passed**. The run covered
  prefix/query/body preservation, SSE arriving before completion, retained legacy
  clients, removal of the old alias, independent API/console networks, disabled
  API refusal, no fallthrough to administration, the Engines page, stripped
  spoofed authority and retained gateway authorization. Backend servers recorded
  requests; they were fixtures, not live inference engines.
  Run: `/tmp/ep-two-host-proxy-zz9j2e6e`.
- Real root/agent and production UI in Chrome: two-host setup preview, generated
  API URL, managed SSO callback, persisted explicit override, reset to automatic,
  desktop/mobile layout and no browser errors passed. The final state retained
  no issuer override and no applied entry-point configuration. No API responses
  were intercepted. Run:
  `C:/Users/troyc/AppData/Local/Temp/ep-two-host-ui-yx8g_e07`.
- **83 agent tests**, **98 control tests**, and **45 UI tests** passed for the
  changed entry-point, setup, SSO, OIDC, config and People surfaces.
- Python lint/format/type checks (including agent on Linux), frontend lint/type
  checks, production export, OpenAPI validation, shell/workflow/example syntax
  and staged secret scans passed. Existing dependency/deprecation warnings remain.
- Sabotage removed the prefix rewrite. The real-Caddy check failed on the first
  forwarded path; the original source was restored byte-for-byte.
- Review caught the collision with the existing `/inference/` console page and
  narrowed the reserved namespace to `/inference/v1`. It also retained custom
  hostnames and exact network policies when reopening or migrating setup.

[Proxy results](assets/two-host-access/proxy-result.json),
[browser results](assets/two-host-access/browser-result.json),
[setup desktop](assets/two-host-access/access-desktop.png),
[setup mobile](assets/two-host-access/access-mobile.png),
[automatic SSO desktop](assets/two-host-access/sso-derived-desktop.png),
[automatic SSO mobile](assets/two-host-access/sso-derived-mobile.png).

## Publication and limits

All eight Python consumers and all six UI OpenAPI inputs were regenerated in
temporary directories against the before/after contracts. The
[measured radius](assets/two-host-access/codegen-radius.json) is control's provider
list plus descriptive changes in agent/control/UI. Other consumers are unchanged.
Agent, control and UI were subsequently pinned and regenerated from published
contracts `c3f59f743e8b14f2beb5ae1c3be16e1c14d5009a`. The console distribution was
rebuilt and the release pins updated together with the new container acceptance
check. The agent's older pin also picked up the existing person-subject description;
no unrelated schema behavior changed.

The container workflow now includes the two-host proxy checks. The actual new
container build runs asynchronously after publication; local verification used the same pinned
Caddy binary in WSL. Live Google/Microsoft registration was not exercised here.

Enrolled machines retain their existing control address and port. Keep its port
mapping while they use it; automatic worker control-address migration remains a
separate change. Active and standby roots must share the canonical sign-in address.
