# Workbench signing decisions during Job Site polling

Follow-up to [Workbench #13](https://github.com/eugene-plexus/workbench/issues/13),
approved by Troy before publishing the two-host access changes to Edge.

## Behavior

A decision accepted while a Job Site poll is in flight is consumed when the
same held request returns. A decline ends the tool call without another attempt.
An approval retries the held call, whose signature remains checked by the site.

The new checks found a related defect: a completed approval was retained even
when the site returned a different held ID or different words to sign. Workbench
now presents the changed request and waits for its own approval. A decline still
cancels the tool call even if the site's request changed. The existing overall
signing timeout remains in effect.

## Verification

- Before the fix: 12 checks passed and both changed-request approval cases failed
  (`id` and `words`), showing `running` where a new signing prompt was required.
- After the fix: **38 tests passed** across `test_signed_calls.py`,
  `test_node_folders.py`, and `test_agui_lifecycle.py` (30.73 seconds, Windows,
  Workbench's Python 3.12 environment).
- The two delayed-poll acceptance cases use a real Workbench HTTP server and
  sign-in/decision endpoints. A fixture upstream holds its second HTTP response
  behind an event until the decision endpoint returns 204. Decline produces zero
  writes and no further poll; approval produces exactly one write. Test servers
  use isolated state and ephemeral loopback ports. The upstream identity/model/
  Job Site services are fixtures; this does not revalidate physical-machine
  signature cryptography or WebAuthn.
- Unit cases cover pending, approved and declined decisions when the held ID or
  displayed words change, as well as both decisions on an unchanged request.
- **Three mutations caught** in temporary source copies: replacing a completed
  decision, losing a decline during an actual HTTP poll, and carrying an approval
  to a changed request. Working source hashes remain unchanged. The sabotage
  harness now sets its child's output encoding explicitly for Windows.
- Workbench Ruff, format and mypy checks passed. No frontend behavior or contracts
  changed in this fix. Distribution packaging is rebuilt for publication.

The earlier [G5 record](genui-browser-run.md) deliberately left this issue open.
This follow-up covers its remaining approval and delayed-poll cases.
