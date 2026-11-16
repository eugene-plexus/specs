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

## Calls answered by Troy (2026-10-22)

- **R37-FIRST: several groups stay, and the person chooses.** A person in
  several groups picks which group's set of models they work from (the
  **active group**). Built as:
  - `Person.activeGroup` (one of their groups, or null for the first in
    their list), set by the person themselves in Workbench Settings and the
    console ("Work with: Sales models"), and by the owner on the person's
    page; control refuses a group the person is not in.
  - `roleRouting` and `allowedModels` come from the active group only (not
    the union), so the person's model set is exactly one group's. The
    other row 70 policies (queue band, summary percent) keep the
    most-generous rule across all their groups.
  - The choice reaches the gateway in the admission check and the sign-in
    claim at the next token refresh; the picker says so.
  - Tests: `test_role_routing_follows_the_active_group`,
    `test_allowed_models_are_the_active_groups_only`,
    `test_a_person_cannot_pick_a_group_they_are_not_in`; the acceptance's
    person B switches active group and gets the other group's models.

## What building found (2026-11-16)

Built on one branch, `r37-group-routing`, in specs, control, gateway, agent
and ui. The agent changes only by regenerating: it validates the root's
admission answer with a model that forbids unknown fields, so an agent that
predates the new fields would refuse every answer that carries them.

- **Absent means the old behaviour, everywhere.** A group record keeps
  `roleRouting` and `allowedModels` only when set; a person record keeps
  `activeGroup` only when chosen; the admission answer carries
  `roleRouting`, `allowedModels` and `modelGroup` only when the person's
  active group sets one of them. `PoliciesInEffect.activeGroup` is said
  only when that group sets one of them, so a person whose groups set
  neither reads what a row 70 root said.
- **Mixed versions fail closed.** A standby from before row 37 cannot apply
  a group that sets either policy or a person with an `activeGroup`: update
  standbys with the root. An agent or gateway from before row 37 refuses an
  admission answer with the new fields, so a person whose active group sets
  them gets a 503 there until it is updated; never a request outside their
  models. Edge ships the agent, gateway and control together.
- **The sign-in claim is unchanged.** `eugene_policies` keeps only the row
  70 policies. Workbench (row 70c) refuses a claim with fields it does not
  know, so adding the row 37 fields would have stopped every member's
  sign-in to an older Workbench. Apps read routing from the gateway, which
  reads the root at each request.
- **Changes reach the next request, not the next token refresh.** The root
  reads the group and the person's choice at every admission check. A
  change to the person's model list ends a running request's lease (409 on
  renew), as a change to the key's limits does; a routing change does not.
  A change while a request waits in the gateway's line is refused at its
  acquire (row 11 blocker 1).
- **A group write keeps a policy it leaves out.** Inside `policies`, a
  policy left out keeps its value and `null` clears it (row 70 cleared one
  left out). Without this a row 70 console, which sends only the two
  policies it knows, would clear a group's routing and models on any save.
- **The person chooses at `POST /oidc/active-group`** (and reads it with
  GET), with their own access token, through any machine's agent as the
  other `/oidc` writes go. A POST, not a PUT: the agent's `/oidc` forward
  passes GET and POST only. The owner chooses on the person's page; a
  delegated administrator may not. Workbench Settings has no picker yet
  (a follow-up issue on workbench).
- **The gateway applies the person's list wherever it applied the key's.**
  `ClientRequest.allowed_models` is a `ModelScope` (the key's list and the
  person's) when the root verified a person whose group limits models; the
  slot resolution, fallbacks, `GET /v1/models` and the server-run image
  tool all read it. A `role:*` name is checked against the key only; any
  other name the person asks for must be in their list, a slot alias too.
  A role their group routes resolves to the group's list less what they
  may not reach; when nothing is left, the install's list, filtered.
- **The acceptance asks `role:agentic`, not `role:embeddings`,** for the
  role G1 does not route: the fixture drivers serve chat only, and the
  check is the same (the install's list, filtered).
- **The sabotage is made in the sabotaged gateway's own process** (its
  resolution skips the person's list before the app starts), so no file
  changes and nothing needs restoring.

## Call R37-SELF, Choice 3: default built (2026-11-16)

A person still chooses their active group, but it decides **routing by role
only**. Model limits come from **every** group they are in that sets a
model list: a model must be in all of those lists (a group with no list
adds no limit; with none, the key's list applies as before). Choosing a
group with no list, or a wider one, never widens what they reach; leaving
a group widens it at their next request. This replaces "`allowedModels`
from the active group" above.

- The admission answer carries `modelLimits` (each limiting group's
  `{id, name}` and list, sorted by name) and `routingGroup` (with
  `roleRouting`); `allowedModels` and `modelGroup` are gone from it. The
  gateway's 403 names the first group whose list leaves the model out.
- `PoliciesInEffect` carries `modelLimits` the same way; the person page
  says "m1 (from Sales)", or every list when several narrow them.

## The second model's review, answered (2026-11-16)

- **B1, a slow body wrote back an old record.** `POST /oidc/active-group`
  read the person, awaited the body, then wrote the whole record it read: a
  person holding the body back undid a disable, a removed group, revoked
  grants and a password reset. It now reads the body first and writes a
  `setPersonActiveGroup` entry that changes only `activeGroup` on the record
  as it is when the entry applies (an older standby cannot apply it). Test:
  `test_oidc_active_group.py::test_a_slow_body_*`.
- **S1, matching on the event loop.** `*` patterns are matched by finding
  the parts left to right (linear), in the gateway and in the vendored
  `client_admission.py` (agent and control); a name over 256 characters is
  never matched; a group's entry holds at most 8 `*`.
- **S2, a row 37 console against a row 70 root.** The console sends
  `roleRouting` and `allowedModels` only when the root's group records
  carry them, so a save there is not a 422.
- **S3, a route the group's own list leaves out** is a 422 naming the model
  (settings never lie).
- **S4, the acceptance's sabotage step** now requires a 200 from m3 and m3's
  count to rise, after waiting with a person's request.
- **S5, one change a minute.** A second change within a minute is a 429
  `slow_down` with `Retry-After`; each change is a log record.
- Notes: the Responses door's 403 carries `model_not_allowed`; the owner's
  token gets 403 `not_a_person`; a person's check that an agent answers
  with a 500 says an agent older than its root cannot pass on group models.
