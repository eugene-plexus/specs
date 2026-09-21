# A6b failover safety — 2026-09-21

A6b is implemented and packaged for the development installers. The public
`v0.1.0-alpha.1` assets and the live NAS/Windows services were not changed.

## What changed

Only connection establishment failures and explicit pre-execution refusals permit
automatic fallback. Unclassified server failures, lost replies, partial writes,
deadlines and CLI failures have an indeterminate outcome and stop the request.
HTTP 429 preserves its retry hint. Generic upstream 503 is deliberately not
treated as proof that no work occurred. First text or tool output commits a
stream, regardless of a later failure's claimed disposition.

One gateway request ID reaches every driver and HTTP upstream attempt. A single
deadline covers admission, preparation, model wake, inference and fallback.
Disconnect and expiry cancel owned work and release admission. Shared driver
circuits skip cooling connections, allow one concurrent recovery probe and
require two successful probes before restoring normal traffic. Required tools,
images, explicit settings, model permissions and locality survive fallback.
Applying model profile defaults now also preserves the local-only flag and ID.

Metrics keep request IDs, full elapsed time, attempt dispositions and known versus
unknown usage. Preparation failures can have zero attempts. SQLite v2/v3 records
survive migration; old attempts' usage remains unknown. The UI shows these facts,
including a single failed attempt rather than only multi-attempt cascades.

## Evidence

Four new regression cases first reproduced unsafe replay on read/write/protocol
errors and an unclassified 503. They passed after the taxonomy change, then were
expanded across generation, streaming and embeddings. Tests also cover partial
text/tool output, bounded cooldown, concurrent recovery exclusion, both chat
APIs' deadlines, embeddings, cancellation during profile preparation and wake,
admission release, stale capability metadata and policy after profile defaults.

[`a6b-failover-acceptance.py`](../../scripts/a6b-failover-acceptance.py) runs a real
gateway, two real HTTP drivers and a real driver with a controlled Codex adapter
subprocess fixture. Its HTTP fixture counts accepted application requests and
correlation headers. The CLI fixture writes an action marker and exits with an
error; the marker occurs once and the fallback receives no request.

- Windows evidence: `%TEMP%/ep-a6b-acceptance-w7ixi_za`.
- Linux/WSL evidence: `/tmp/ep-a6b-acceptance-iri_w18n`.
- Both prove overload cooldown and two-probe recovery, shared IDs, no replay of
  accepted-but-failed/malformed results, no mixed partial text/tool streams,
  deadline/disconnect cancellation, safe rescue after connection refusal, and
  retained uncertain usage across gateway restarts.
- The signed A5/A6 process instruments passed again with these components,
  including both chat APIs, embeddings, shared reservations and zero requests
  to disallowed/external fallbacks. A2/R8's eight wire-shaping cases passed with
  the primary restored through cooldown between independent failure scenarios.

Windows gateway suite: 535 passed before the final eight parametrized safety
cases; all 43 affected safety/lifetime/stream bookkeeping checks passed after
the final edits. Driver: 506 passed, three opt-in live-provider tests skipped.
UI: 764 passed. Python lint/types and UI lint/types/production export passed.
All six consumers regenerated from published specs `25534e6`.

## Delivered revisions

| Component | Revision |
| --- | --- |
| agent | `bdd684c09d25757f957977e992e5756dbbd07c3e` |
| control | `7fe2d17c213b27860cd6bbf9db406b4f0973ae39` |
| gateway | `4ead7e830693e8dba13bc7386dcaf76ef7a83175` |
| inference-driver | `352993a351ce2925fb7a0532fb7028175a15d364` |
| library | `8502ac33cb6ac5bf66e07ac1a0afe39967ef98e1` |
| UI source | `eea85b9fcacec198a9559dcf898be22fe34c7d0e` |
| UI distribution | `0e3a2028f8c7dffae55f6507818e964c47e6c0cd` |

All 184 static export files match the packaged wheel byte-for-byte. Wheel SHA256:
`bda06288ffea65a196093464414a54c759b80a001d0596073063e8328846bc90`.
Both development installers point to these revisions.

## Limits

The instrument uses controlled HTTP/CLI fixtures, not paid provider accounts or
the live 5090. A provider is trusted to use refusal status codes honestly.
Cancellation does not prove remote work stopped. Request IDs are correlation,
not idempotency keys. Tool execution and reconciliation belong to the executor;
this is not an exactly-once guarantee. Circuits are per gateway, not distributed
provider quotas. Older drivers with unknown capabilities cannot serve explicit
settings they have not advertised. Unknown usage is not a billing total.

The next slice is A7 recovery, followed by A8 measured capacity/support limits.
