# Row 37: routing per permission group, by model role

Lane TRUST. **High risk** (a new permission that limits which models a
person reaches). Size L. Sources: `shared-accounts-and-sso.md` §"Model
routing and a simple default experience" (direction agreed 2026-10-16),
Troy's MODEL-JOBS answer (2026-10-21: "each permission group (company) can
have their own routing rules for each type of role"), row 70 (group
policies, delivered in the admission check and the sign-in claims) and
row 71 (a role is a gateway model slot named `role:<role>`).

## 1. What it delivers

- **A group chooses its own models for each role.** On the group's page,
  under Policies: "Chat: Qwen3 32B, then Llama 3.3 70B"; "Embeddings:
  install default". A member who asks for `role:chat` (Workbench does)
  gets the group's list; everyone else gets the install's.
- **A group can limit which models its members reach.** "Models: All" by
  default, or a chosen list (exact names or patterns such as `qwen3-*`).
  The gateway checks every model a member's request actually reaches,
  fallbacks included, and `GET /v1/models` lists only those.
- **Nothing changes for an install with no group policies.** A
  one-person install never sees any of it (the simple-default rule).

## 2. Design

### The data (`control.yaml`, `GroupPolicies`)

Two new optional policies on a group, beside `queueBand` and
`summaryContextPercent`:

```yaml
GroupPolicies:
  roleRouting:          # null or absent: the install's routing for every role
    type: [object, 'null']
    propertyNames: {$ref: components/common.yaml#/components/schemas/ModelRole}
    additionalProperties:
      type: array       # the models to try, in order; 1..16 entries
      items: {type: string, minLength: 1}
  allowedModels:        # null or absent: every model
    type: [array, 'null']
    maxItems: 64
    items: {type: string}   # the client keys' matcher: an exact id or a pattern with *
```

**Per person, not only per group:** a person needing their own routing gets
a group of one. Policies stay on groups, so there is one place to look and
one data format (the roadmap's "fix its data format before more
per-person settings arrive").

### A person in several groups

- `allowedModels`: the union, as row 70's "most generous" rule; a group
  with no limit lifts the limit.
- `roleRouting`: **not merged.** For each role, the first group in the
  person's `groups` list that sets it decides (the owner orders that
  list). The person page says which: "Chat routes by Sales (first of B's
  groups that sets it)". Call R37-FIRST. A role whose list holds no model
  the person may reach falls back to the install's list, filtered.
- `PoliciesInEffect` and `PoliciesSetBy` gain both, so the console, the
  claim and the admission check share one function,
  `permissions.effective_policies`.

### Delivery to the gateway

- `ClientAdmissionResult` gains `roleRouting` and `allowedModels` (the
  effective values), set only when the root verified a person, as
  `queueBand` is (row 70). A key with no person (Open WebUI's shared key,
  Claude Code) gets neither: the install's routing and the key's own
  `allowedModels`, as today.
- **Before shipping, check `extra=forbid`** on the gateway's generated
  `ClientAdmissionResult`. If an older gateway refuses unknown fields,
  ship the gateway before the root on Edge and say so in the release
  notes (an older gateway beside a newer root would refuse every person's
  request).

### The gateway

- **A role request** (`role:chat`) resolves through the person's
  `roleRouting[chat]` when set, else the install slot (row 71), then drops
  every model outside the effective allowed set. The usual slot failover
  runs over what is left.
- **Every actual target is checked:** the requested model, each fallback,
  and the models server-run tools call for the request
  (`server_tools.py` already reads `allowed_models`). Allowed = the key's
  `allowedModels` ∩ the person's. The gateway's own decision model, which
  routes for the install and never answers the person, is not a target.
- **Refusal:** 403 `model_not_allowed`: "Your group Sales does not include
  Llama 3.3 70B. Ask the owner, or choose another model." For a role with
  nothing left: 404 "No model your groups allow has the role Chat."
- `GET /v1/models` with a person token lists only allowed models, and each
  `role:*` entry the person can use.

### Console (ui)

- `PermissionGroups.tsx`, Policies: **Models** ("All models" or a picker
  with patterns) and **Routing by role** (each role: "Install default" or
  an ordered list, the same picker row 71's Model roles page uses).
  "Changes reach people within <token life>", as row 70 says.
- The people page shows each person's effective models and routing, and
  which group set each.

### Workbench

No code change beyond regenerating: its model list comes from the
gateway's `/v1/models` with the person's token, which is now filtered.
Its role requests (row 30 `role:reads-pages`) follow the person's
routing by themselves.

## 3. Repositories and codegen

specs (`control.yaml`, `components/client-keys.yaml`), control
(`permissions.py`, `applied.py`, `oidc.py` claims, the admission check),
gateway (`admission.py`, the slot resolution, `/v1/models`, refusals),
ui (`PermissionGroups.tsx`, `app/people/page.tsx`). Regenerate every
consumer and diff.

## 4. Tests that fail before

- control `test_permissions.py::test_role_routing_takes_the_first_group_that_sets_it`
  and `test_allowed_models_are_the_union_and_null_lifts_the_limit`.
- control `test_client_admission.py::test_a_verified_person_carries_routing_and_allowed_models`
  and `test_a_key_without_a_person_carries_neither`.
- control `test_applied.py::test_a_group_entry_without_the_new_policies_loads`.
- gateway `test_model_slots.py::test_a_role_resolves_through_the_persons_group_routing`.
- gateway `test_client_key_policy.py::test_a_fallback_outside_the_groups_models_is_never_reached`
  and `test_models_listing_is_filtered_for_a_person`.
- ui `PermissionGroups.test.tsx`: Models and Routing by role save and show
  "Install default".

## 5. Acceptance (CI, Linux and Windows, about 4 minutes)

`specs/scripts/row37-group-routing-acceptance.py` on row 2's harness: a
root, the gateway, the fixture backend serving m1, m2 and m3, two groups
(G1: models m1, m2; chat → m2, m1. G2: models m3; chat → m3), person A in
[G1], person B in [G2, G1], every `EUGENE_PLEXUS_*` cleared.
1. A asks `role:chat`: m2 answers. m2 is stopped: m1 answers. A asks m3:
   403 naming G1. A's `/v1/models` lists m1, m2 and `role:chat`.
   A asks `role:embeddings`, which G1 does not route; the install's list
   is m3, m1: m1 answers (m3 is dropped, not tried).
2. B asks `role:chat`: m3 answers (G2 is first). B may reach m1, m2, m3.
3. A key with no person: the install's routing; m3 reachable.
4. The owner removes m1 from G1; after A's token refresh, m1 is refused.
5. **Sabotage:** skip the allowed filter on a role's list; step 1's
   `role:embeddings` request then reaches m3, and the run must fail.

**The reviewer should attack:** a person widening their own models (a
forged claim, a header, a request body field); a fallback, a server-run
tool or a role list reaching a model outside the allowed set; a key with
no person getting a person's limit or escaping its own; a stale admission
cache keeping a removed model; an older root or gateway beside a newer one.

## 6. Do not change

- gateway `routing.py` and `admission.py` queue parts that row 11 changes:
  if row 11 has not merged, build on its branch's interfaces or wait; the
  orchestrator decides when the row starts. Lane TRUST runs rows 4, 5 and
  36 in the same control files first.
- control `machine_list.py` and the root-address files row 4 changes.

## 7. Size and risks

L, about 3 days, after row 11 (both change the gateway's admission path).
Split on one branch: **37a** contract, control and effective values;
**37b** gateway enforcement and listing; **37c** console. One adversarial
review after 37b.

Risks:
- **A permission now limits models.** An enforcement gap reaches a model
  a group was meant not to; the acceptance's sabotage step and the review
  target that.
- **Token life:** a removed model stays reachable until the person's next
  token refresh, as row 70's policies do; the group page says so.
- **Mixed versions** of root and gateway; see "Delivery".
