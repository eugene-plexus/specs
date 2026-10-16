# Workbench A2UI backend (G3)

The backend implements A2UI 0.9.1 from the exact source lock, with the explicit
forms catalog in `protocols/a2ui/forms-v1.json`. Catalog IDs are identifiers,
never URLs to fetch. Its eight components are Text, Row, Column, Card, Divider,
Button, TextField and CheckBox. Static child references and absolute JSON Pointer
bindings are supported. The pure local functions required/and/or/not are supported
for checks and context resolution; a function action never becomes a server call.
External assets, templates, regex validation and arbitrary functions are refused.
The upstream schema accepts both v0.9 and v0.9.1 envelopes; that compatibility is
retained. Backend capability version is 0.9.1. Headless installs report renderer
false; the implemented [G5 product UI](workbench-ui-browser-v1.md) adds forms rendering.

## Typed source and capability negotiation

The first transport is an explicit Workbench MCP extension, not an A2A transport
claim or a heuristic applied to ordinary JSON answers. Configured HTTP and
owner-only stdio MCP sources may use `com.eugeneplexus/a2ui`:

* Client extension capability: `{version: "0.9.1", catalogIds: [forms catalog ID]}`.
* Producer tool `_meta` entry: `{version: "0.9.1", catalogId: forms catalog ID,
  actionTool: "handle_ui"}`. The named action tool must be on the same connection
  and app-visible under the existing MCP tool visibility policy.
* Completed tool-result `_meta` entry: `{mimeType: "application/a2ui+json",
  messages: [A2UI server messages], fallback: "Readable summary"}`.

The model receives ordinary normalized tool content; the typed UI metadata is
kept separately. A malformed, unsupported or oversized UI envelope leaves the
ordinary result intact. Nothing retries a tool to repair UI. Fragmented MCP or
model output is never published before a complete result exists.

## State and identity

An envelope contains at most 64 messages for one wire surface ID. Every envelope
is applied atomically. Create precedes updates/deletion. Component updates merge
by ID, replacing each named component; data updates replace/create the value at
the path or remove it when value is absent. Root paths are omitted, empty or `/`.
Array positions must exist or append at their length; sparse allocation is refused.
JSON Pointer escaping is honored; malformed escapes, unsafe object keys and
relative paths are refused.

Missing component references remain progressive placeholders (`ready: false`);
server actions require a complete reachable root. Cycles anywhere are refused.
Limits: 64 KiB per envelope/data model, 256 components, 512 edges, depth 32,
1,024 expanded component visits, 80-character component/surface IDs and
256 KiB total persisted surface. Existing G1 person/chat quotas still apply.

The durable namespace binds the original answer/run, person and MCP connection.
The source's configuration and producer declaration are pinned in the binding;
each action rediscovers current tools and rechecks access. Incremental updates
retain that origin. Delete creates a tombstone; a later create of the same wire
ID gets a fresh durable incarnation, so an old action can never address the new
surface. Stop disables the namespace until a new answer creates a new one.

## Form input and actions

`POST /api/v1/chats/{chat_id}/interactions/surfaces/{surface_id}/a2ui/input`
accepts `{revision, componentId, value}`. Only the chat owner on the current
branch may change a reachable TextField string (at most 8,192 characters) or
CheckBox boolean whose value is a declared binding. The host derives the path;
the request cannot name an arbitrary path. It changes local data and advances
the revision, cancelling stale proposals. It does not call a tool. Sign-in,
branch, source and revision checks precede the transactional write.

G1 action name `a2ui/action` takes the pinned client-to-server event object as its
arguments. Name, source component and wire surface must match a reachable saved
Button event. The backend resolves the event context against the saved data and
requires an exact match, including JSON types. Registered checks must evaluate
true. Client-local function buttons and error reports cannot request server work.

After explicit host approval, reconnect once to the bound source, rediscover and
validate the action tool's current schema, then issue one session-level tools/call
with `{event: <client event>}` and, only when sendDataModel is true,
`dataModel: <saved model>`. Neither the browser nor a model supplies the target.
No elicitation/header-mismatch retry loop is used. New UI messages in the tool's
result are validated and committed in the same transaction as action completion;
the action's own revision update does not invalidate its completion. Other stale
actions are cancelled. Invalid returned UI preserves the prior state and a
readable result/error, without replay. Unknown effects remain uncertain.

All endpoints use the ordinary Workbench session, secret and Origin checks.
Snapshots/events reuse G1. No public endpoint publishes arbitrary surfaces.
No credentials or connection configuration enter the saved view. This does not
advertise a production renderer, agent-to-agent networking or a model's ability
to produce valid A2UI. Local-model generation reliability is measured separately.
