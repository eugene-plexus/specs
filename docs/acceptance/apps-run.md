# Apps: the hub and its spokes — acceptance run

**2026-09-23, this Windows box, beside the live worker install (8079
untouched, healthy before and after).** Script:
[`scripts/apps-acceptance.sh`](../../scripts/apps-acceptance.sh).
Design: [`docs/design/apps-and-spokes.md`](../design/apps-and-spokes.md).
**58 PASS, zero failures, second execution.**

Pins under test: agent `6f2e860`, control `2a8ce85` (regen-only), ui
`fa81e14` / dist `ec4ced9`, contract specs `a4a2922`. Gateway, library
and driver at their existing pins; they codegen nothing that changed.

## What ran

A throwaway install on +100 ports, every ambient `EUGENE_PLEXUS_*`
variable dropped: agent, control, gateway and library from the working
trees, the root initialized and the node **enrolled** (an app is refused
on an agent that is not), and a driver on a real `llama-server` b10948.
The app is `scripts/fixtures/app-fixture`, stdlib only, added as a
custom entry from a folder and installed by the agent with `uv`.

| # | Check | Result |
|---|---|---|
| 2 | The catalogue says it cannot install and names uv; installable once `uvBinary` is set; the shipped catalogue is empty | PASS |
| 3 | A custom entry is 403 until `allowCustomApps` is on, then 201 | PASS |
| 4 | Install watched to `done`; the key `app:fixture@node-a` appears in the install's key list; the token is in the app's data directory and in no config file | PASS |
| 5 | Running on its own port (8190), answering `/healthz` itself; `uiUrl` names that port | PASS |
| 6 | Every `EUGENE_PLEXUS_*` variable the app holds is an `APP_` one | PASS |
| 7 | The app completes a chat through the gateway with **its** key, served by the llama.cpp driver | PASS |
| 8 | That key is 401 on gateway config/admin/metrics, the agent (including `/v1/apps` and minting), the library and the control root | PASS |
| 9 | The app's settings read, changed and **reset with a null** through `/v1/apps/fixture/config`, and the app itself reflects each | PASS |
| 10 | The app refuses the operator's own token and no token; only the agent's per-spawn admin token opens its settings | PASS |
| 11 | An agent restart brings an enabled app back; a stopped app stays stopped, with nothing on its port | PASS |
| 12 | An unreadable `apps.yaml`: `/healthz` degraded with `appsError`, the topology intact, no apps, the file kept as `apps.yaml.unreadable`; restoring it brings the app back | PASS |
| 12b | **With the control root sealed, an uninstall is 503 and removes nothing** — the app still installed, running, key file in place | PASS |
| 13 | Uninstall: 204, the gateway refuses the key **1 s** later (refresh 3 s), environments gone, data kept without the dead key, nothing on the port | PASS |

## The one finding, and it was the harness

The first execution passed checks 0-12 and failed all of 13. Every agent
restart in checks 11 and 12 restarts the control root, and on an install
with no keyring the root comes back **sealed**; the client-key registry
lives there, so the gateway could not confirm the app's key and the
uninstall's revocation was refused. The refusal is the design working —
*an app is never gone while its key still works* — so the fix was to
unlock the root after a restart the way the console's sign-in does, and
to keep the sealed moment as check 12b rather than lose it.

## Not proved here

- **An app on a machine without a gateway.** Both ends were one node, so
  the app was handed the local gateway. The owner-agent-proxy path is
  unit-tested (`test_the_gateway_is_found_on_this_node_or_through_its_owners_agent`)
  and has never carried a request between two machines.
- **An `https://` archive source.** The fixture installs from a folder;
  the shipped catalogue is empty until the chat app exists.
- **The browser.** The UI's pages are driven in vitest against the
  wire shapes (`src/app/apps/*.test.tsx`, 8 of 8 sabotages caught) but no
  Playwright spec clicks Install through to Open yet.
- **Linux and macOS.** The agent's real-`uv` unit test runs in CI on
  Linux; this run is Windows only.
