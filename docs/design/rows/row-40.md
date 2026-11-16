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

## What building found (2026-11-16)

- **Whose price list.** The owner's rate is kept at the control root, one list
  for the install (`setModelPrice`, `GET`/`PUT /v1/usage/prices`), not in each
  gateway's settings as §2 said: two gateways with their own lists would count
  one request at two prices, and a money allowance is install-wide. The root
  prices each request itself. The gateway tells it what only the gateway knows,
  as a `ModelPriceHint`: at `acquire` for the model asked for, at `release` for
  the model that served it (`locality`, and the provider's price its drivers
  report). Order: the owner's rate, else the provider's price, else free for a
  model every backend of which is local, else unknown. The gateway's `/v1/models`
  lists the provider's price as `provider_price`, so the console shows it
  beside the owner's rate. The design's gateway tests `test_prices.py` and
  `test_usage_release.py` exist in the gateway (the hint, the listing, the
  release); the owner-rate rules are tested at the root
  (`control/tests/test_usage.py`).
- **Provider prices: no table (orchestrator's call, 2026-11-16).** Prices come
  only from the owner's rates and from a price a provider itself reports: an
  OpenRouter account reads `pricing.prompt` and `pricing.completion` from its
  listing (dollars a token as strings; `-1`, missing, or a float is no price).
  §2's price table for OpenAI, Anthropic and Gemini (`docs/data/model-prices.json`)
  was built and then removed: a list written down once, from memory, would show
  stale prices as facts, against "settings never lie". A model whose provider
  reports no price, and which the owner has not priced, is unpriced: counted as
  such, never as free, and refused under a money limit with the reason.
- **Money is exact.** A rate is whole micro-dollars a million tokens, which is
  one pico-dollar a token, so a request's cost is the integer
  `prompt * input + completion * output` pico-dollars. Counters keep
  pico-dollars; the API says dollars as a twelve-place decimal string
  (`costUsd`). The console and Workbench convert between typed dollars and
  micro-dollars on the digits.
- **The refusal** is OpenAI's own for a spent quota: 429, `type` and `code`
  `insufficient_quota` (not `allowance_exhausted`: full OpenAI compatibility),
  the root's sentence as the message, and `Retry-After` in seconds until the
  reset. The Anthropic door says `rate_limit_error`, the Gemini door
  `RESOURCE_EXHAUSTED`; the Responses door's stream frame keeps
  `rate_limit_exceeded`. The root also refuses a `check` on arrival when a
  token allowance is spent and the check names a model, so a refused request
  never waits in a queue; a model list (no model) is not refused. The unpriced
  sentence says "The owner sets one on the Usage page.", where prices are set.
- **Counting.** A release that ends a lease still held counts once, for the key's
  lineage, the person the acquire verified and their groups then (the acquire's
  log entry remembers the person, `usageOpen`). A second release of one request
  counts nothing. Each subject keeps its newest 62 days and 13 months with use,
  at most 32 models a period (the rest under `*`), held by count on every count
  (see the review below); the count rides on the release's existing
  `putClientAdmission` entry, so counting adds no log entries.
- **Allowances do not cut a running request**: they are left out of the policy a
  lease is bound to, and out of every admission answer.
- **A group's allowance** is one pool for its members. A person whose groups set
  an allowance of one kind is refused only when every one of those groups has
  spent it (row 70's most generous rule). A money allowance never refuses a
  model that costs nothing, and refuses a model with no price.
- **A person's own usage** is at `GET /oidc/usage` (not `/v1/usage/me`): an app
  reaches the root at its issuer, and the agent forwards `/oidc/*` there.
  Workbench's Settings shows it, and says so plainly for an Eugene that counts
  none.
- **The console**: a Usage page under the gateway (per key, group and person,
  day, month, allowances, by model; and every served model's price, the
  provider's beside the owner's rate, which it sets and clears). A key's
  allowances are offered only where an install's root counts them; a group's
  only to a root that answers them.
- **A standalone agent** (a machine that joined no install) refuses a token or
  money allowance with a sentence that says why: no root counts it there.
- **Known gap.** A fallback to a cloud model with no price inside a request
  admitted on a priced model is priced at the admitted model (review S1); a
  fallback whose provider reports a price is priced at it. The gateway's routing
  does not skip unpriced fallback targets under a money allowance.
- **A deleted key, person or group** keeps its counters (bounded, at most 75
  periods); nothing prunes subjects that no longer exist.

### Mixed versions

- **Log version 2.** A standby a release behind stops at the first key or group
  that sets an allowance and at the first `setModelPrice` (it refuses a field
  and an op it does not know). The root refuses those writes with 409 "Update
  <standby> first" while its standby reports log version 1, as row 5's ops do.
  A standby a release behind ignores the counts on `putClientAdmission`: it
  keeps no counters until it is updated.
- **A gateway a release behind** sends no price hint and no usage: its requests
  are not counted, and a money allowance refuses them as unpriced unless the
  owner set a rate for the model. Allowances never appear in an admission
  answer, so it reads every key as before.
- **A root or agent a release behind** refuses the hint and the usage (422); the
  gateway asks again without them and leaves them out for five minutes. Such a
  root enforces no allowance, which it does not know.
- **A console a release behind** does not offer allowances or prices; a root
  before row 40 refuses a group or key write that sets one.

## Review (2026-11-16): two blockers and six should-fix, all fixed

- **B1, a cut answer counted nothing.** A stream that ends without the backend's
  count (the caller hangs up, the Stop button, the backend fails after its first
  token, the gateway stops a repetition), and a non-streamed request whose caller
  left after a backend was asked, now release the gateway's estimate: the
  queue's prompt estimate (else the request's size, four bytes a token) and the
  output forwarded (at least a token a fragment, at most four characters a
  token), marked `estimated`. The gateway's `BoundClient` notes each backend
  asked and each fragment forwarded on the request's admission. A backend that
  failed before any output, with the caller still waiting, counts nothing.
- **B2, counters pruned against one record's date.** A root whose clock was a
  year ahead for one release wiped every counter, and later a subject could hold
  more periods than `validate` accepts, so the root could not reload its own
  snapshot. Now each subject keeps its newest 62 days and newest 13 months *by
  count*, on every count; no state `counted` writes can fail `validate`. Default
  built, not the reviewer's second idea: a record is **not** moved to the newest
  day counted. After a clock that ran a year ahead, that would count every later
  request into the future day while the allowance reads today's: free use for a
  year. A stray future period is one of the 75 kept and wipes nothing.
- **S1, served under another name.** A release whose serving model has no price
  at the root is priced at the model its lease was acquired for; the gateway
  also gives a served name it does not route the hint of the model asked for.
- **S2, an older console cleared allowances.** On `PUT .../limits` and on a group
  replace, an allowance (or any group policy) left out keeps its value and `null`
  clears it. The console sends `null` to clear one the key had.
- **S3, a lost release was silent.** It is logged and retried in the background,
  with a growing pause, for up to 30 s (a lease's life).
- **S4, a missing count became 0.** It is the B1 estimate, marked `estimated`.
- **S5, who reads whose usage** is pinned by tests: the owner sees all; a
  directory administrator no keys; a membership administrator only their groups
  and members; a person only themselves, and their groups' totals without any
  per-model breakdown of other members' use.
- **S6, allowances reported for a past period.** Allowance state is always now:
  the current UTC day and month, whatever period the report shows.
- The acceptance now streams two of step 1's requests, cuts one stream after its
  first fragment (it must still count), and its sabotage must fail for the
  sabotage's own reason ("the root counted both gateways' requests").

