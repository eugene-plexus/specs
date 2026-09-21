# A5: scoped keys, shared admission and attributable usage

2026-09-21. Implemented against the published A5 contract `f657f5d`.

## Instrument and boundary

`scripts/a5-scoped-keys-acceptance.py` starts an isolated real control root, two
real enrolled agents and two real gateways. A sixth process supplies counting
HTTP model backends; it does not run an LLM. Every port is ephemeral loopback,
all state is disposable, and all owned processes stop in `finally`. No installed
service, NAS root, personal model or private image participates.

The same instrument passes on Windows/Python 3.14 and WSL Linux/Python 3.12.
It is included in the installer-pin CI matrix on Windows and Linux.

## Observed behavior

- App A permits `alias` and `allowed`, one concurrent request and four requests
  per rolling minute. App B permits `excluded` and `embedding`, two concurrent
  requests and two requests/minute. Both gateways show each key only its models
  and permitted alias backends. Direct requests to excluded IDs return 403.
- A held response stream at gateway A occupies App A's allowance at gateway B.
  B returns 429 with Retry-After before the fixture receives another generation.
  App B retains its own allowance. Its streamed chat and embedding use the same
  rate window even though they pass through different gateways.
- Closing App A's client stream frees its slot; the next request succeeds at the
  other gateway. The cancelled request still consumes one rate admission.
- A failing primary cannot reach the excluded fallback. Editing App A through
  the other agent allows that target without changing its token or resetting its
  counter. The next request falls back once, and the following request is 429.
- Stopping the root makes client discovery/inference return 503 at both gateways;
  operator configuration still answers 200. Restarting and unlocking the root
  restores coordination while both exhausted rate allowances remain exhausted.
- Retained metrics identify both keys through streaming, embeddings, failure,
  cancellation and fallback. Caller `user`, prompt/input markers and bearer
  values are absent from the metric APIs. In this run App A served two requests
  with five backend attempts; App B served two with two attempts. Failed-admission
  totals can vary with the disconnect/recovery polling race and are not fixtures.
  The incomplete-usage count includes cancellation and the successful fallback,
  whose failed attempt did not report token consumption.

## Additional regression evidence

Authority tests cover log replay, snapshot bootstrap/compaction, atomic-write
failure, idempotency, release-before-late-acquire, dead-gateway lease expiry,
rolling-window expiry, separate keys, model scope, policy changes, revocation,
service/operator boundaries and a clock independent of wall time. Standalone
agent tests cover durable admission and failed atomic replacement. Legacy import
cannot undo an operator's limits or revocation. Replay equivalence includes both
new log operations.

Gateway tests drive both chat APIs in streaming and non-streaming forms plus
embeddings, filtered alias discovery/fallback, renewal failure, browser retry
headers, and cancellation during generation, streaming, embedding and wake.
Nested attempt collection preserves interrupted-stream attribution. A schema-2
metrics database upgrades in place, retaining its old unattributed history.

The A3 process regression also passes. Its offline-cache test now explicitly
waits for revocation to be persisted before restarting: A5's current authority
check can reject the key before the authentication-cache refresh interval.
The 24-request cold-cache outage remains bounded (one policy read in the local
Windows run). A3's cache is authentication state, not permission to bypass A5.

Local suites: agent 959 passed / 4 platform skips on Windows and 943 / 20 on
Linux; control 184 passed on Linux, with its changed replay/authority tests also
passing on Windows; gateway 501 tests on each platform plus focused cancellation/metrics/CORS
checks; UI 763 tests, lint, types, format and production export passed.

## Deliberate limits

This proves shared policy/admission and application accounting, not GPU memory
allocation, model quality or provider billing. Per-key usage is per gateway over
retained raw rows; unknown tokens are not invented. Existing keys remain visibly
unrestricted until edited. All components must be updated before relying on A5.
The existing single-active-root promotion/fencing requirement remains. Local-only
routing is the separate A6 slice.

See [operator instructions](../client-keys.md) and the
[admission design](../design/scoped-client-access.md).

## Published component pins

- agent: `4c3e95d04e2b996e40bee07aaef96b4ff0b0c3b2`
- control: `eef1bac002235d7167e72fdfb3bdf3004a9a129d`
- gateway: `6e94d374504664acd08484246126e895b83336a8`
- library: `8ba5c2fba171718114985a9d323e54d942c212d4`
- inference-driver: `22c91ecd4b4723cd288d8b77e075fb19bfcf570c`
- ui: `170881f3f4edf2a3542813cf14d7c04faf840cfb`
- ui-dist: `c3e20833c27849480be3ebbfdd7f0f454cf6fe17`

The UI wheel matches all 184 production export files byte-for-byte. The frozen
`v0.1.0-alpha.1` tag and assets are unchanged. Live installs were not updated.

Delivery caught a pre-existing POSIX installer defect when GitHub returned 504
for a package archive: `run_step` printed the error but returned zero, allowing
Docker to build an incomplete image. The helper now preserves the failing
command's status, and failed container builds print their captured output.
The installer regression injects bootstrap, virtualenv and package failures;
all three preserve status 37 and prevent a Docker-style command chain from
continuing. These checks fail against the old helper; all 97 installer checks
pass with the fix.
