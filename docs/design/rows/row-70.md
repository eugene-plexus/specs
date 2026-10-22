# Row 70: policies per permission group

Lane TRUST, high risk (permissions, a new claim in sign-in tokens). Size L. Sources: Troy's answers of 2026-10-21: GROUP-POLICY (Choice 2: all group policies in one row, before rows 11, 26 and 27), LD-C3 and LD-C4 (queue priority from groups), CTX-C2 (each group sets its own summary percent), MEM-INSTALL (a group's shared memory servers, which members cannot turn off), MODEL-JOBS (later: routing per group and per model role, row 37).

**Workbench store migration:** if Workbench keeps its group policies in its store, this row takes the next free number when it starts (row 7 has 28).

## 1. What it delivers

- **A Policies section on each permission group.** The owner (or a person with `manageGroups`) sets it in the console on the group's page, beside its apps and permissions.
- **Three policies, stored and delivered, so the rows that use them only read them:**
  - **Queue priority** (`queueBand`: interactive, background or sheddable). The root returns a person's effective band in its admission check. Row 11's queue uses it.
  - **Summary percent** (`summaryContextPercent`, 50-95). Workbench reads it for the signed-in person. Row 26 uses it.
  - **Shared memory servers.** The owner adds memory servers to a group in Workbench's Settings. A member cannot turn them off. Row 27 sends chats to them.
- **Unset means "no policy".** A person in no group with a policy gets the install's default (interactive; 80%; no shared memory server). Nothing changes for an install that sets no policy.
- **A person in two groups gets the most generous value of each policy:** the highest band, the larger percent, and every shared memory server of every group (no duplicates).
- **The person can see what applies to them.** Workbench's Settings shows "Set by your group: <group>" beside each value a group sets, with no control to change it.

## 2. The design

### Where each policy lives

| Policy | Read by | Stored in | Edited in |
|---|---|---|---|
| `queueBand` | the gateway (row 11) | control: `PermissionGroup.policies` | console, the group's page |
| `summaryContextPercent` | Workbench (row 26) | control: `PermissionGroup.policies` | console, the group's page |
| shared memory servers | Workbench (row 27) | Workbench: a server record owned by `group:<id>` | Workbench Settings, owner only, a "Groups" section |

**Why the memory servers stay in Workbench.** A memory server record holds an address and a credential. Workbench already keeps those for a person's own servers (MV5a), with its address rule. Control holding app-side credentials would put an app's secrets in the trust root. So control says who is in which group; Workbench owns its servers. The console's group page links to Workbench Settings for them (cross-link rule).

### Control (`specs/openapi/control.yaml`, control)

- `PermissionGroup` and `PermissionGroupWrite` gain `policies` (optional object, `additionalProperties: false`): `queueBand` (enum `QueueBand`, nullable), `summaryContextPercent` (integer 50-95, nullable). The object is the place later policies go (row 37's routing per role). Name the enum.
- **Older roots refuse unknown fields** (`extra=forbid`). Deploy the root first; the console hides the Policies section when the root's group record has no `policies`.
- The replicated log: a group write carries `policies`; `applied.py` checks it as it checks the other group fields. An old log entry without `policies` loads as "no policy".
- **Effective policies, one function:** `permissions.effective_policies(state, person) -> Policies`, using the combination rule in section 1. Tested on its own.
- **Admission check:** `ClientAdmissionResult` gains `queueBand` (nullable), set only when the root verified a person (a person token). For a key with no person (Open WebUI, Claude Code), it is absent and the key's own band applies (row 11).
- **Sign-in claims:** the ID token and `/oidc/userinfo` gain `eugene_groups` (a list of `{id, name}`, at most 64) and `eugene_policies` (`{queueBand?, summaryContextPercent?}`, the effective values). Only for apps the person may use. Group names are not secret to the person in them.

### Workbench

- `signin.py` reads `eugene_groups` and `eugene_policies` into the session's identity. A token refresh refreshes them, so a change reaches a signed-in person within one access-token life.
- **Group memory servers:** a server record may have `owner = "group:<id>"`. The owner adds one in Settings > Groups > <group> > Memory servers, with the same connect and test flow as a person's own server. Row 70 stores and tests it; row 27 sends chats to it.
- The person's Settings shows each value a group sets as "Set by your group: <group>", read only.

### Console (ui)

- `PermissionGroups.tsx`: a Policies section with "Queue priority" (Not set, Interactive, Background, Sheddable) and "Summarise long chats at" (Not set, 50-95%). Each says in one line what it does. A link "Memory servers for this group: Workbench Settings".
- The people page shows, per person, the effective policies and which group set each.

### Gateway

- Regenerate only. Row 11 reads `queueBand`. Nothing reads it before row 11, so this row changes no gateway behaviour.

## 3. Repositories and codegen

- **specs:** `openapi/control.yaml`, `openapi/components/client-keys.yaml` (`ClientAdmissionResult`).
- **control:** `permissions.py`, `routes/people.py`, `applied.py`, `oidc.py`, the admission check.
- **workbench:** `signin.py`, `memory_servers.py` (group owner only), the Settings page and its API.
- **ui:** `PermissionGroups.tsx`, `app/people/page.tsx`.
- **gateway, agent, tool-driver:** regenerate where their codegen names these documents; measure the radius by regenerating every consumer and diffing.

## 4. Tests that fail before the change

- control `test_permissions.py::test_effective_policies_take_the_most_generous_value` (two groups: background and interactive gives interactive; 70 and 85 gives 85; none gives unset).
- control `test_client_admission.py::test_a_verified_person_carries_their_groups_band` and `test_a_key_without_a_person_carries_no_band`.
- control `test_oidc.py::test_the_id_token_names_the_persons_groups_and_policies`.
- control `test_applied.py::test_an_old_group_entry_without_policies_loads`.
- workbench `test_signin.py::test_groups_and_policies_come_from_the_claims`, and a test that a group memory server is listed for every member and a member cannot remove it.
- ui `PermissionGroups.test.tsx`: the Policies section saves and shows "Not set".

## 5. Acceptance (CI, Linux and Windows)

`scripts/row70-group-policy-acceptance.py`, on ports away from the defaults, with every ambient `EUGENE_PLEXUS_*` cleared:
1. Start a root with two people (A, B) and two groups (G1 background + 70%; G2 interactive + 85%). A is in G1; B in G1 and G2.
2. A client key with a person token for A: the admission check says `background`; for B: `interactive`.
3. Sign in to Workbench as A and B: the claims carry the groups and the effective values (70%, 85%).
4. The owner adds a memory server to G1 in Workbench Settings; A and B both see it as "Set by your group: G1" and cannot remove it.
5. Remove B from G2: after a token refresh, B's band is `background` and B's percent is 70.
6. **Sabotage:** make `effective_policies` take the first group's value; step 2 for B must fail.

**The reviewer should attack:** a person setting their own policy (a forged claim or header); a group id from another install; a member removing a group server; a person removed from a group keeping its server after refresh; a key without a person getting a person's band; an older root receiving `policies`; the claim's size with many groups.

## 6. Do not change

- gateway `admission.py`, `budget.py`, `routing.py` (row 11 changes them).
- workbench `store.py` beyond the one migration, `past_chats.py` (row 7); `context.py`, `conversation.py` (row 26).
- control `machine_list.py`, agent `node_identity.py`, `machine_trust.py`, `machine_key_change.py` (row 3).

## 7. Size, split, risks

**Size:** L. One branch, `r70-group-policies`: **70a (M)** control and contract (policies, effective values, admission result, claims); **70b (S)** the console's Policies section; **70c (M)** Workbench (claims, group memory servers, "Set by your group"). One adversarial review after 70a and 70c (Codex).

**Risks:**
- Claims are cached for an access token's life. A removed membership lasts until the next refresh. Say so on the group page: "Changes reach people within <token life>."
- A group server sends the chats of everyone in the group to one place. The dialog that adds it says so, and row 27 shows each member where their chats go.

**Calls:** none open. GROUP-POLICY, LD-C3, LD-C4, CTX-C2 and MEM-INSTALL are answered.
