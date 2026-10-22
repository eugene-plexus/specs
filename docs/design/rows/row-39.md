# Row 39: operations rights for people who are not the owner

Lane TRUST. **High risk** (a new credential and new gates on every
machine). Sources: `console-ux-pass.md` ("Operations rights for people
other than the owner break 'no role sees everything' today"),
`remote-nodes.md` §"no role sees everything", the MSP and automated tools,
assignable capabilities and the novice default, `shared-accounts-and-sso.md`
U2 (delegated administration: `AdministrationGrants`, the named
`ep-administration+jwt` session), memory `feedback_no_role_sees_everything`.

## 1. What it delivers

- **The owner can let someone run the machines without being the owner.**
  On a person's Administration access, beside U2's account powers, three
  operations powers:
  - **Models:** download, delete and re-scan models; edit profiles; create,
    start, stop, restart and change runtimes.
  - **Updates and restarts:** update Eugene and engines (Update all),
    install engine builds, restart components.
  - **Logs:** read machines' logs (off unless given: logs can hold file
    names and fragments of requests).
  Each can be limited to chosen machines (an MSP technician, one site's
  machines).
- **Everyone with any power can see** machines, runtimes, models, host
  history and health issues, read only.
- **What stays the owner's, always:** provider keys and other secrets,
  people's chats, sign-in keys and the passphrase, enrolling and removing
  machines, Job Sites, routing and backends, client keys, folder access,
  and delegating powers. No combination of powers sees everything.
- **Every operations change says who made it.** Each machine keeps a record
  ("Dana stopped qwen3-32b, 14:05"), which the owner reads on the
  machine's page.

## 2. Design

### Grants (`control.yaml`, `AdministrationGrants`)

```yaml
AdministrationGrants:          # U2's three, plus:
  operateModels:   boolean
  operateMachines: boolean     # updates, engine installs, restarts
  readLogs:        boolean
  operationsMachines: [string] | null   # node names; null = every machine
```

Only the owner sets them (`/v1/people/{id}/administration`, owner-only as
today). Changing them bumps `administrationVersion`, as U2 does, which ends
existing sessions.

### The credential

- **Sign-in:** a person with any operations power signs in to the console
  at `/login` with their Eugene name and password (or external sign-in),
  through U2's administration login. Their control session (1 hour,
  version-checked) stays addressed to control only.
- **Per-machine tokens:** the console exchanges the control session at
  control for a short **operations token** per machine: `typ: operations`,
  `aud: [node:<name>]`, `sub` = the person, `ops` = the powers, 10 minutes,
  signed by the root's token key that every agent already trusts (the
  trust bundle). Control checks the grants, the machine scope and the
  version at every exchange. The agent's proxy passes a token addressed to
  the destination machine through unchanged (it already does), and strips
  it toward any other.
- **Revocation:** logout and every grant change publish
  `OP_REVOKE_SESSION` in the trust bundle, as U2's logout does; agents
  check the revocation list today. The worst case is the 10-minute token
  life when a machine cannot fetch the bundle.

### The gates (agent, library, gateway)

One dependency in each, `require_operation(power)`: an owner session, or an
operations token addressed to this machine that holds `power` and is not
revoked. It replaces `require_operator_session` / `require_operator` on
exactly these routes, and nowhere else:

| Power | Agent | Library | Gateway |
|---|---|---|---|
| (any power: read) | `GET` node, runtimes, host history, updates status, issues | `GET` models, profiles, downloads | `GET /v1/roles`, metrics |
| `operateModels` | runtimes create, start, stop, restart, PATCH, DELETE | downloads (start, cancel), model delete, profile writes, scan | none |
| `operateMachines` | engine install/uninstall, node update, Update all, component restart | none | none |
| `readLogs` | `GET /v1/logs` | none | none |

Every other route keeps its gate. A test lists every mutating route in the
three apps and fails when one accepts an operations token without being in
this table (the table is the allowlist).

### Console (ui)

- After sign-in, a person with operations powers sees the console with
  only the pages their powers use: Home, Models, Runtimes, Machines (read),
  Updates (with `operateMachines`), Logs (with `readLogs`). Everything else
  is absent from the menu, and a direct link shows "Only the owner can do
  this". A line under the header: "Signed in as Dana: models, updates".
- Pages work with a 403 by saying what is missing, never by failing blank.
- The owner's delegation editor (`AdministrationGrants.tsx`) gains the
  three powers and the machine picker, each with one line on what it
  allows and "Never: secrets, chats, sign-in keys".

### The record of who did what

- Each agent keeps an operations log in its data folder (SQLite, 90 days,
  10,000 rows), one row per gated mutation on that machine, the library's
  and gateway's included (they report to their agent): time, person, power,
  action, target, result. The owner's own actions are recorded too.
- `GET /v1/node/operations-log`: owner only. The machine's page shows it.

## 3. Repositories and files

specs (`control.yaml`, `agent.yaml`, `library.yaml`, `gateway.yaml` for the
new 403 wording and the log route), control (`administration.py`,
`routes/administration.py` exchange, `tokens.py` new `typ`), agent
(`dependencies.py`, `trust.py`, `routes/proxy.py` pass-through check,
routes in the table, the operations log), library and gateway
(`dependencies.py`, the routes in the table), ui (sign-in, navigation by
powers, `AdministrationGrants.tsx`, the machine page's log). Regenerate
every consumer and diff.

## 4. Tests that fail before

- control `test_administration.py::test_operations_token_carries_powers_and_machine_scope`
  and `test_exchange_refuses_a_machine_outside_the_scope`.
- agent `test_operations_gates.py::test_every_mutating_route_is_in_the_table`
  (the allowlist test), `test_stop_with_operate_models`,
  `test_engine_install_needs_operate_machines`,
  `test_a_revoked_operations_token_is_refused`.
- library `test_operations_gates.py::test_download_with_operate_models`,
  `test_config_patch_stays_owner_only`.
- gateway `test_operations_gates.py::test_config_patch_stays_owner_only`.
- ui: the navigation for a person with Models only.

## 5. Acceptance (CI, Linux and Windows, about 5 minutes)

`specs/scripts/row39-operations-acceptance.py` on row 2's harness: a root,
two machines (A, B), the library, the gateway and the fixture engine; the
owner gives Dana `operateModels` on machine A only.
1. Dana signs in, gets an operations token for A, starts and stops a
   runtime on A: both succeed and A's operations log names Dana.
2. Dana's exchange for B: refused, naming the scope. Dana's token for A
   sent to B through the proxy: stripped, 401.
3. Dana tries, on A: engine install, `PATCH /v1/config` on the agent, the
   gateway and the library, client key create, a provider key, logs: each
   403 naming the missing power or "only the owner".
4. The owner removes Dana's power: within the token life her next call is
   refused (the test shortens it to 30 s); logout revokes at once.
5. **Sabotage:** add a route to the table by mistake (config PATCH): the
   allowlist test and step 3 must fail.

**The reviewer should attack:** the exchange (scope, version, a disabled
person, an owner-only route reached through the proxy), token audience and
`typ` confusion with sessions and service tokens, a library or gateway
route left out of the table, the revocation path when the bundle is stale,
and the log record's actor (it must come from the token, never a header).

## 6. Do not change

- control `oidc.py`, `sealing.py`, `passphrase_file.py`, `keyring_store.py`
  (row 5), the root-address files (row 4), `routes/nodes.py` announce
  (row 36).
- gateway admission and routing (rows 11 and 37).

## 7. Size and risks

L (the roadmap said M), about 4 days, after rows 4, 5 and 36 in lane TRUST.
Split on one branch: **39a** grants, the exchange and the agent gates;
**39b** library and gateway gates and the operations log; **39c** the
console. One adversarial review after 39b.

Risks:
- **A gate left open** gives a non-owner an owner's power on a machine.
  The allowlist test fails on any mutating route that accepts the token
  without being listed.
- **Tokens outlive a removed power** by up to 10 minutes on a machine that
  cannot fetch the trust bundle; the owner's page says so.
- **Logs** can hold fragments of what people asked; `readLogs` is its own
  power, off by default.

**Calls:** R39-LOGS (logs as a separate power, off by default) and
R39-DELETE (Models includes deleting model files).

## Calls answered by Troy (2026-10-22)

- **R39-LOGS: Choice 2.** Reading machines' logs comes with **Updates and
  restarts** (`operateMachines`); there is no separate `readLogs` power.
  The gate table gives `GET /v1/logs` to `operateMachines`, and the
  delegation editor's line for that power says it includes logs.
- **R39-DELETE: Choice 1.** The Models power includes deleting model files,
  each delete in the machine's record.
