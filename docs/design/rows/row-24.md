# Row 24: client keys, rotate and record last use

Lane GW; built before row 11, which uses its shared bucket. Sources: A3, A5, `components/client-keys.yaml`.

## 1. What it delivers

- Each key says when it was last used, to the minute: "last used 3 min ago", or "no use recorded".
- **Rotate** makes a new token with the same name and limits and shows it once. The old token works for an overlap the operator picks (default 1 day, or Stop now). Then new requests on it are refused as "replaced", and running ones finish.
- During the overlap, the old and new tokens share one concurrency and rate allowance.
- An app's key is rotated by the agent on the app's machine. It writes the new token to the app's key file, and restarts the app if the app reads its key only at start.

## 2. Design

**Contract** (`client-keys.yaml`; paths in `control.yaml` and `agent.yaml`):
- `ClientKey` gains `retiresAt`, `replaces` and `replacedBy`. `lastUsedAt` is now described as "When the authority last admitted a check or acquisition with this key, to the minute. Absent: no use recorded."
- New `ClientKeyRotateRequest`: `overlapSeconds` from 0 to 2,592,000 (default 86,400), and `ttlDays` (default: the old key's lifetime).
- `POST /v1/auth/client-keys/{keyId}/rotate` returns 201 with `ClientKeyCreated`. It returns 404 for an unknown key, 409 for a key that is off, and 503 when the root is locked. Operator only, with the same `may_name` rule as create.
- `ClientKeyPolicyEntry` stays as it is. It is `extra=forbid`, so a new field would break every older gateway. The root serves `expiresAt = min(expiresAt, retiresAt)`, which older gateways already enforce.

**Control:**
- The rotate route writes one log entry, `OP_ROTATE_CLIENT_KEY {oldId, retiresAt, key}`. The new record copies the old one's limits exactly, so a legacy key stays unrestricted. It carries `lineage = old.lineage or old.id`.
- `applied.py` allows the four new fields. The A3 node import strips them.
- Admission buckets are keyed by `lineage`, which defaults to the key's own id, so the ledger needs no migration.
- `check` and `acquire` refuse a retired key with a 401 saying it was replaced. `renew` and `release` accept it, so streams finish.
- On acquire, `state_machine.admit` adds `usedAt` (UTC, to the minute) to the admission entry it already writes. On check, it appends `OP_TOUCH_CLIENT_KEY` at most once per key per minute. `lastUsedAt` only moves forward.

**Agent:**
- `routes/auth.py` forwards rotate to the root. The standalone store mirrors the fields, the shared bucket, retirement and last use.
- For an app installed on this node, a helper in `routes/apps.py` writes the token with `write_private` and calls `AppStore.put_key`. It calls `AppManager.restart` when the manifest fills `{clientKey}`. Workbench re-reads its key file on every request.
- An `app:<id>@<node>` key from another node gets a 409 naming that machine. The console sends the request to that node's agent through the proxy.

**Gateway:** `client_keys.py` refuses a token as `replaced` when its policy `expiresAt` has passed and is earlier than the token's own `exp`. `dependencies.py` and `anthropic.py` say so.

**Failures, with their causes:**
- A key that is off: 409 "This key is turned off / expired / already replaced by …x7Yb2c."
- A key file that cannot be written: 500 "Could not write Workbench's key file (PermissionError). The old key works until 22 Oct 14:05."
- A replaced token at a door: 401, or 403 on `/v1/messages`: "This key was replaced. Paste its replacement into this app, or make a new key under Home → Use it from your apps."

**UI** (`lib/clientKeys.ts`, `UseFromAppsCard.tsx`):
- The status line gains "last used 3 min ago".
- **Rotate** sits beside Turn off. It reads: "Make a new key now. This one keeps working for [1 day]." The choices are Stop now, 1 hour, 1 day, 7 days and 30 days, with "If this key leaked, choose Stop now."
- For Open WebUI it adds: "Open WebUI restarts, and settings changed inside it go back to their defaults."
- The token is shown once: "Paste the new key into each app that uses …k9Q0Xz."
- The old row reads: "replaced by …x7Yb2c, works until 22 Oct 14:05".

**Defaults:** the 1-day overlap keeps a leaked key working for a day unless the operator picks Stop now (flagged; the panel says so). Nothing is deleted, and the token is never stored. There are no new metrics.

## 3. Repositories and codegen

specs, control, agent, gateway and ui. Regenerate control, agent, ui and gateway (the gateway reads `client-keys.yaml` directly), and diff each.

## 4. Tests that fail before

- control `test_client_keys.py::test_rotate_returns_a_replacement_and_retires_the_old_token` asserts that the old policy entry's `expiresAt == retiresAt`. Today the route gives 405.
- control `test_client_admission.py::test_acquire_records_last_used_to_the_minute`, `test_old_and_new_tokens_share_one_concurrency_limit` and `test_a_retired_key_renews_but_cannot_acquire`.
- gateway `test_client_key_policy.py::test_a_replaced_key_is_refused_as_replaced`. Today the refusal says "not registered".
- agent `test_client_keys.py::test_standalone_rotation_and_last_use` and `test_apps.py::test_rotating_an_app_key_rewrites_its_key_file`.

## 5. Acceptance (CI, Linux, about 3 minutes)

`specs/scripts/ck-rotate-acceptance.py`, built on A5's harness. It starts a real root and standby, one enrolled agent, one gateway and the fixture backend. It uses OS-assigned loopback ports and temporary folders, with every `EUGENE_PLEXUS_*` variable cleared. It checks:
1. A request and a model listing set `lastUsedAt`.
2. A 40-second stream runs on the old token while the key is rotated with a 5-second overlap. Both tokens work, and with a limit of 1 the new token is refused while the old one streams.
3. After the overlap, the old token is refused as replaced on both doors, and the stream finishes through a renewal.
4. A root restart and the standby's replay keep all of these fields.
5. An installed app's key file is rewritten with mode 0600.

**The reviewer should attack:** a revoked key brought back by rotate or replay; a retired token outliving `retiresAt` through the cached policy and the 5-second clock tolerance; a token reaching the log; how many log entries a `/v1/models` poll loop writes; a forged `lineage` on import; the key file's permissions.

## 6. Do not change

- agent `apps.py`, `apps_catalogue.yaml` and `client_doors.py` (AG2; this row only calls into them), and `tokens.py` (AG2 35).
- control `person_access.py`, `permissions.py`, `oidc.py` and `tokens.py` (TRUST).
- ui `settingsTopics.ts` (WEB 33), and every `scripts/codegen.py` (OPS 1).

## 7. Size and risks

M, about 2 days. Build it on one branch as 24a (last use, S) then 24b (rotation, M), with one acceptance run and one review. The risks:
- Both control roots must be updated together, because an older standby stops at the new ops.
- Rotating Open WebUI's key resets its in-app settings.

**Found:** app keys get the 365-day default and are replaced only when their file is missing, so every installed app stops working a year after install.
