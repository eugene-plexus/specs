# Workbench AG-UI backend v1

G4 implements two explicit directions: **serve** adapts Workbench's existing
answer loop; **connect** consumes a configured external agent. Neither changes
the gateway or inference-driver contract. This is a headless backend; G5 still
owns browser rendering. The HTTP contract is
[workbench-ag-ui.yaml](../../openapi/workbench-ag-ui.yaml).

## Baseline and supported events

Protocol **1.0**, from AG-UI `release/2026-10-13`, commit
`b3f61a96fa3c755f37558ac44f4acc5b1c3828f1`. The unmodified normative JSON
schema, MIT license and selected upstream conformance streams are vendored in
`protocols/ag-ui/`; `SOURCE.json` records hashes. This is a deliberately strict
subset, not a claim to implement every SDK convenience or optional capability.

Both directions support RUN_STARTED, RUN_FINISHED, RUN_ERROR, the
TEXT_MESSAGE_START/CONTENT/END and TOOL_CALL_START/ARGS/END/RESULT families,
MESSAGES_SNAPSHOT and STATE_SNAPSHOT. Connect also accepts STATE_DELTA (all six
RFC 6902 operations), STEP_STARTED/FINISHED and CUSTOM. Text-only messages are
supported. Tools are traces: an external tool event never invokes a Workbench
tool. Connect CUSTOM values are inert data; they cannot create surfaces, fetch
resources or dispatch actions. Serve uses CUSTOM `eugene.interactions` for
authenticated interaction references and STATE_SNAPSHOT for pending approvals.
Tool approval continues through Workbench's existing authenticated decision API.

Chunks, reasoning, activity, multimodal and subagent events, RAW and unknown
events are refused with RUN_ERROR. No draft shape silently becomes success.
Schema-invalid events, mismatched run/thread IDs, duplicate active IDs,
content without a start, unclosed messages/tools/steps and events after a terminal
event fail the run. Tool streams can interleave by ID. State patches apply
atomically, with RFC JSON Pointer escaping and array semantics; references never
retrieve remote schemas. Terminal success is committed only after clean upstream
EOF. RUN_ERROR may be the first event, as allowed by the pinned protocol.
Removing the entire state document is refused; use a root replacement with null.
Native tool results have a 16,000-character text excerpt with an explicit note
that the saved answer holds the full result. Reasoning is not projected.

## Identity and configuration

All routes require the existing Workbench session cookie and
X-Workbench-Secret. Writes require the canonical Origin. The person must own the
chat, including reads; the install owner's read-only chat privilege grants no
AG-UI access. A gateway key is not a person's identity.

Only an install owner can add/remove external agents. Each configuration has a
name, fixed HTTP(S) URL, optional bearer token and explicit allowed subject IDs.
URLs may not contain userinfo, query strings or fragments. Credentials remain
in the server database; list and run responses never return them. HTTP is for
explicitly configured trusted networks; operators should use HTTPS otherwise.
Connections use system TLS trust, no ambient proxy, redirects, retry or failover.
The server supplies `forwardedProps.eugene.subject`; caller-supplied forwarded
properties, tools and context are refused. Config deletion revokes running work.
Configuration is immutable: replacing credentials creates a new agent ID.

## Input and continuation

Start in an empty chat. `threadId` must equal the chat ID; `runId` is a caller
chosen 1–80 character ASCII identifier (`A-Za-z0-9_-`). The chat is then bound to
one direction and, for connect, one agent ID. Existing chats can use a new empty
chat for AG-UI; importing arbitrary client history is not supported.

The first input contains exactly one new user text message and empty state.
Subsequent inputs name the immediately preceding `parentRunId`, repeat its exact
authoritative `messages` and `state`, then append one new user text message.
GET thread returns this saved input seed. The saved host answer must still be
the selected chat tip: edits, retries and ordinary chat turns invalidate AG-UI
continuation. Client input cannot inject system instructions, assistant/tool
results, state changes, local tools or arbitrary execution targets.
After a null state snapshot, omit the input's `state` field: the pinned upstream
input schema does not admit an explicit null there. Native initialization also
requires its messages snapshot to fit the event bound, before inference starts.

Connect also supports an interrupt outcome followed by a new run with `resume`:
every outstanding interrupt is answered exactly once with resolved/cancelled
status, and resolved payloads satisfy its optional responseSchema. Schema
references and regular expressions are refused; response schemas are bounded to
4 KiB and resolved payloads to 16 KiB. Interrupt expiry is enforced. Resume
repeats saved messages/state and adds no user message. A parent can have only one successor,
including after failure or uncertain execution. Native approval remains in the
existing tool-decision API; native interrupt/resume input is refused.

## Durability and streaming

The run intent and request hash are committed before inference or an external
POST. Reusing a run ID with identical input returns its saved stream; conflicting
input returns 409. This remains true after failure, cancellation, sign-out and
restart. A successor is claimed atomically. It is never an automatic retry.

POST returns `text/event-stream`; each data object is a pinned AG-UI event and
each SSE id is a durable per-run integer, starting at 1. GET run/events and
repeated POST accept Last-Event-ID and return only later events. Invalid/future
cursors are refused. An authoritative run snapshot includes messages, state,
status, cursor, outcome and host answer ID. Replay contains no execution.
Client disconnect leaves the run going. Session validity and source access are
rechecked while running and while replaying; revocation ends the stream/work.
Ordinary chat sends and branch mutations are refused while an AG-UI run is active.

Stop cancels the local task and closes the upstream HTTP response. Serve reports
cancelled once its answer loop stops; connect reports uncertain because closing
a socket cannot establish rollback at an external agent. Truncated responses,
timeouts, protocol errors after dispatch, process termination and shutdown are
also uncertain, with a durable RUN_ERROR and no automatic replay. Remote
RUN_ERROR is a recorded failure; error details are bounded and never include
request headers/credentials. Local validation failures before dispatch are errors.
Plain text is saved as an ordinary chat answer; state, custom data and remote
tool traces remain outside model inference history.

## Bounds and retention

Requests and saved projections: 512 KiB each; state: 128 KiB; event/frame: 128 KiB;
256 messages; JSON depth 32; 64 operations per state patch; 4 MiB/4,096 events per
run (with reserved terminal-error capacity). At most 8 live runs, 32 runs per
chat, 64 runs per person and 64 configured agents. Run lifetime is at most one
hour; upstream inactivity at most 60 seconds. Records remain until their chat
is deleted. Quotas refuse new work rather than evicting idempotency records.
Deleting a chat stops its run before deleting records. Restart marks unfinished
runs uncertain. An open message/tool on an aborted run remains a partial trace;
RUN_ERROR is the terminal marker. State snapshots, messages and events commit
in the same database transaction.

## Acceptance gate

Use a reference HTTP client against serve and a real HTTP fixture agent against
connect, plus the pinned conformance streams. Prove ordered interleaved tool
events, state patch semantics, normal and interrupt continuation, errors,
cancellation, disconnection, process restart, identity/source revocation, quota
and input refusal, and duplicate run/successor submissions without a second
counted effect. Report serve/connect separately. Sabotage copies must demonstrate
that the checks detect removed validation, identity and replay guards. No
production browser capability is advertised by this gate.
