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
