# Row 38: dashboards for administrators

Lane WEB, after row 12 (metrics with names that last). Low risk. Sources:
memory `project_admin_dashboards` (Troy, 2026-09-30: AWS-console-style
dashboards for system administrators, the longer-term audience; per-node
series that can be aggregated), `gateway-operations-dashboard.md` and
`host-history.md` (alerts and SLOs named as left out),
`metrics-dashboard.md` ("wake cost has no chart"), row 12's design (rollups
served by `bucket=hour`; charts over rollups are this row's).

## 1. What it delivers

- **Longer history:** the metrics charts reach 90 days from the hourly
  rollups row 12 serves (today: 7 days of raw rows).
- **Fleet views:** one page for every machine together: GPU memory and
  utilisation summed and per machine, temperatures, power, disk, and
  runtimes per machine, over the same ranges.
- **Wake cost:** per model, how often it was started to answer a request
  (`swapped_in`), how long the person waited, and the energy the start
  cost; the biggest offenders first, with "keep loaded" one click away.
- **SLOs:** the owner sets targets per model or key (for example "99% of
  requests succeed; 90% of first tokens within 2 s over 30 days"); the
  page shows each target, how it stands and the error budget left.
- **Alerts:** rules on those same numbers and on machine health (a machine
  down, a disk over 90%, a GPU over 85 °C, failures over 5% for 10
  minutes, an SLO budget burning fast). An alert shows on Home and, if the
  owner sets one, is posted to a webhook (JSON that Slack, Discord, ntfy
  and Home Assistant take).

## 2. Design

- **Where alerts are evaluated:** the agent on the root's machine, once a
  minute, reading the gateway's metrics API, each machine's host history
  and control's issues. One evaluator per install, moving with the root on
  a takeover. Rules and webhooks live in control's replicated config (the
  webhook URL sealed like other secrets).
- **Alert states:** firing, resolved; each with when, the rule, the value
  and a link. A rule fires after its "for" duration and resolves after the
  same quiet time, so a flapping value does not post every minute.
- **Webhook:** `POST` with `{rule, state, value, threshold, machine, model,
  url, at}`; a failed post is retried three times and then shown on Home
  ("The alert webhook did not answer: <cause>").
- **SLOs:** computed from rollups (success ratio, latency percentiles
  where row 12's histograms allow, else the p50/p90 the rollups keep);
  error budget = allowed failures left in the window.
- **Pages** (`ui`): Dashboards (fleet, wake cost, SLOs), Alerts (rules,
  history, webhook); the existing Metrics and Hosts pages gain 30 and 90
  days.

## 3. Repositories

specs (`control.yaml` rules and webhooks, `agent.yaml` alert state),
agent (the evaluator), control (config), gateway (nothing beyond row 12's
rollups), ui.

## 4. Tests that fail before

- agent `test_alerts.py::test_a_rule_fires_after_its_duration_and_resolves`,
  `test_a_failed_webhook_is_retried_then_shown`.
- ui `Dashboards.test.tsx`: wake cost ranks models by starts × wait.
- agent `test_alerts.py::test_the_evaluator_moves_with_the_root`.

## 5. Acceptance (CI, Linux, about 3 minutes)

On row 2's harness: a fixture webhook receiver; a failure-rate rule over a
fixture backend that fails half its requests fires and posts, then
resolves when the backend recovers; a stopped machine fires "machine
down".

## 6. Size and risks

L, about 4 days. Risks: noisy alerts (durations and resolve times); a
webhook URL is a secret (sealed, never shown back).

**Calls:** none.

## What building found (2026-11-16)

- **The evaluator runs in the active control root, not in the root
  machine's agent** (default built; the design said the agent). Every read
  it needs already takes the root's own service token: each agent's
  `GET /v1/node/history` (the root polls `GET /v1/node` the same way), and
  the gateway's `GET /v1/metrics` and `GET /v1/metrics/clients`, which now
  accept the root's token and nothing else new. An agent has no credential
  the gateway or another machine's agent takes for these; giving it one
  would have been three new paths into those machines. The root moves on a
  takeover: `start_root_tasks` starts the evaluator, so a promoted standby
  starts it, and a standby or a locked root does not evaluate. The alert
  state is therefore in `control.yaml` (`GET /v1/alerts`), not `agent.yaml`,
  and the agent is unchanged.
- **How the root reaches the gateway:** through its own machine's agent's
  proxy (`/api/proxy/gateway/...`), with a 5-minute token addressed to the
  gateway's machine, which the proxy passes unchanged. The gateway's machine
  is found from the machines' `GET /v1/components`, every ten minutes.
- **Rules and the webhook** are one `setAlerting` entry (log version 2;
  `PUT /v1/alerting` is refused while the standby applies an older log). The
  webhook address is sealed under the master key, listed in the sealed
  inventory, and sealed again by a passphrase change. Only its host is
  shown back.
- **Built-in rules** apply until the owner saves rules (`defaults: true`):
  a machine down 5 minutes, a disk over 90% for 10, a GPU over 85 °C for 5,
  failures over 5% over 10 minutes (at least 10 requests), and an SLO
  burning 14.4 times too fast for 5. They show on Home only; nothing is
  sent anywhere until the owner sets a webhook.
- **A failure-rate rule fires at once**: it is already a rate over its
  `forMinutes`. Every other rule fires after its condition held that long.
  All resolve after the same quiet time. A reading that could not be made
  (a machine's history, the gateway) leaves its alerts as they were.
- **SLOs:** success over the window from the hourly totals (rollups past
  retention), so up to 90 days. A first-token target is a percentile
  (50, 90 or 99) over the requests the gateway keeps whole, and says over
  how many days. A client key's SLO has success only, over the kept
  requests. The burn rate is the last hour's failure share over the share
  the target allows.
- **Who reads what:** the owner reads everything and alone sets the rules,
  the targets and the webhook. A person with any operations power reads
  `GET /v1/alerts` with their administration session: alerts about the
  machines their powers reach and about models, and SLOs set on a model.
  An SLO set on a client key, and its alerts, stay the owner's. The gateway's
  per-key usage stays owner-only for people, as row 39 left it.
- **Wake cost** needed the wait past retention: metrics store v16 adds
  `waited_ms_sum` to the hourly rollup, and every group carries
  `waitedMsSum`. Hours rolled up before v16 have it at 0 and the console
  says those starts' wait was not kept. Energy is an estimate: the wait
  times the machine's GPUs' mean power over the window, from host history.
  "Keep loaded" links to the machine's backends, where the runtime's
  unloading is turned off: a change there restarts a running runtime, so it
  is not done in one click from the dashboard.
- **90 days on Metrics:** raw groups now carry `latencyMeanMs` too, so a
  day joins hours inside retention with the rollup's hours: counts summed,
  latency the request-weighted mean. Hosts needed no agent change: its hour
  buckets already reach 90 days.
- **Home** lists each firing alert with its fix, except a machine that does
  not answer, which the node list already reports; and a webhook that
  stopped answering, with its cause.
- **Not built:** the CI acceptance in section 5. Row 12's harness starts
  control and the gateway outside the agent, so the root would have no
  agent proxy and no component list to find the gateway by; the evaluator
  is covered by unit tests of each part (the rule state machine, the
  webhook's retries, the reads' URL and token, the gateway's acceptance of
  the token, the owner and operations views). The alert state is not
  replicated: a root that takes over starts empty and fires again what
  still holds.
