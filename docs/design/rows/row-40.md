# Row 40: usage and money limits per person and key

Lane GW, after rows 11 (one fair queue) and 24 (key lineage). **High
risk** (it refuses requests). Sources: A5 (attribution per key, person and
app in the gateway's request rows; "pricing/billing and monetary budgets
are not required for the initial local-inference pilot"),
`openai-inference-compatibility.md` ("A per-key spend limit is deferred";
per-door units are "the plumbing a spend limit will read later"),
`workbench-media-screens.md` ("money across chat, metrics and per-person
limits is its own later design"), gateway `metrics.py` (no cost column;
video's `cost_usd` is the only money), control `client_admission.py`
(concurrency and rate per key).

## 1. What it delivers

- **Usage per person and per key**, for a day, a month and a chosen range:
  requests, tokens in and out, by model, across every gateway of the
  install (today usage is per gateway and per key only).
- **Limits:** a key, a person or a group (row 70's policies) can be given
  a token allowance per day and per month, and a money allowance per
  month. A request over its allowance is refused, saying which allowance,
  how much was used and when it resets: "Your group Sales used 4.0 of its
  $4.00 for October. It resets on 1 November."
- **The owner sets the price of every served model** (call R40-LOCAL,
  Troy's Choice 3): a rate per million tokens in and out. A cloud model
  starts at its provider's published price, which the owner can change; a
  local model has no price until the owner sets one. Eugene does not
  estimate electricity, hardware or connection costs: the owner knows
  them, Eugene does not. The console shows each person's and key's spend
  at those rates, and money allowances count them.

## 2. Design

### Counting, install-wide (control)

- The gateway already knows each request's tokens at the end. It reports
  them when it releases the request's admission lease (`release` gains
  `promptTokens`, `completionTokens`, `cost` in micro-dollars, `model`).
- Control keeps counters per key lineage, person and group, per UTC day
  and per calendar month, in applied state (one log entry per release
  already exists for leases; the counts ride on it). Counters older than
  13 months are dropped.
- `GET /v1/usage` (owner; a person sees their own; a group manager sees
  their group's) returns the counters with the allowances.

### Prices

- **The owner's rate wins.** Each served model in the gateway's settings
  gains `price` {`inputPerMillionMicros`, `outputPerMillionMicros`,
  `source`: `owner` | `provider`}. The gateway computes each request's cost
  from its usage and that rate.
- **Cloud, until the owner sets a rate:** the driver reports the
  provider's published price (OpenRouter's pricing per token, already read
  for video; Anthropic, OpenAI and Gemini from a price table in specs,
  `docs/data/model-prices.json`, updated by a script at release), shown as
  "provider's price". A cloud model with neither: cost unknown, shown as
  unknown, and a money allowance refuses it ("no price is set for <model>,
  so a money limit cannot allow it. Set one in Models.").
- **Local, until the owner sets a rate:** free (cost 0, shown as "no price
  set"). Setting a rate makes it count from the next request; past
  requests keep the cost they had.

### Limits (admission)

- `ClientKeyLimits` gains `tokensPerDay`, `tokensPerMonth`,
  `costPerMonthMicros`; `GroupPolicies` the same (the most generous of a
  person's groups, row 70's rule); a person's own limit is a group of one.
- `acquire` refuses when any applicable allowance is spent, before the
  request runs, with the sentence above (HTTP 429, `type:
  allowance_exhausted`). A request that crosses the line while running
  finishes; the next is refused.
- **Who is counted:** the key's lineage always; the person when the root
  verified one; their groups' pooled allowance when a group sets one.

### Console

Usage page: per person, key and group, day and month, tokens and cost by
model; the allowances and how much is left. Each served model's page
holds its price, with the provider's price beside it for a cloud model.
People see their own usage in Workbench's Settings.

## 3. Repositories

specs (`client-keys.yaml`, `control.yaml`, `gateway.yaml` usage and the
429), control (counters, usage route, limits in admission), gateway
(release with usage and cost, price lookup), inference-driver (prices per
model), ui, workbench (the person's own usage line).

## 4. Tests that fail before

- control `test_client_admission.py::test_a_spent_monthly_allowance_refuses_with_the_reset_date`.
- control `test_usage.py::test_two_gateways_count_into_one_total`.
- control `test_usage.py::test_a_group_allowance_pools_its_members`.
- gateway `test_usage_release.py::test_release_carries_tokens_and_cost`.
- gateway `test_prices.py::test_an_unknown_price_is_unknown_not_zero`.
- gateway `test_prices.py::test_the_owners_rate_wins_over_the_providers_price`
  and `test_a_local_model_counts_once_it_has_a_rate`.

## 5. Acceptance (CI, Linux, about 5 minutes)

`specs/scripts/row40-allowances-acceptance.py` on row 2's harness with two
gateways and the fixture backend (a priced "cloud" model and a local one):
a key with 1,000 tokens a day is refused on the request after it passes
1,000, through either gateway; a person in a group with $0.01 a month is
refused on the priced model and served on the local one until the owner
gives the local one a rate, then refused there too; usage totals match the
fixture's counts. **Sabotage:** count only the first gateway's
releases; the two-gateway step must fail.

**The reviewer should attack:** a key escaping its allowance (lineage after
rotation, a second gateway, a request in flight at the boundary), a person
avoiding a group allowance, an unknown price treated as free, and the
log's growth from counting.

## 6. Size and risks

L, about 4 days. One adversarial review. Risks:
- **Refusing a paying customer by mistake:** counters are install-wide and
  tested across gateways; the refusal names the allowance and its reset.
- **Prices go stale:** each price records its source and date; the release
  script refreshes the table.

## Calls answered by Troy (2026-10-22)

- **R40-LOCAL: Choice 3.** "Owner gets to set their own money rate, per
  served model. We can not accurately estimate electricity, cost to
  purchase hardware, Internet connection, etc." No electricity estimate;
  every served model has an owner-set rate, cloud models starting at the
  provider's price.
