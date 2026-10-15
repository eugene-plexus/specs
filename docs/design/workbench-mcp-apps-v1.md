# Workbench MCP Apps backend (G2)

The backend implements the published MCP Apps specification 2026-01-26 at the
commit and hashes in `protocols/ui-sources.lock.json`. Browser sandboxing and
the iframe message bridge remain G5. `supportedProtocols` stays empty until a
renderer passes that gate; `backendProtocols` describes the headless backend.

## Sources and discovery

Configured Streamable HTTP and owner-only stdio MCP connections advertise
`io.modelcontextprotocol/ui` with `mimeTypes: [text/html;profile=mcp-app]`.
Job Site proxies and folder tools do not implement this extension. Discovery
retains bounded tool metadata, including `_meta.ui.resourceUri` and visibility.
Visibility defaults to model and app. App-only tools never enter model tool
definitions, and guessed model calls to them fail. App calls reject model-only
tools. Invalid UI metadata disables UI for that tool without losing its ordinary
text result; invalid visibility fails discovery closed.

A completed model tool call with a valid `ui://` linkage publishes a durable
surface. Its input, tool descriptor and complete bounded result (including
UI-only `_meta`) are saved outside model history. Normal content and structured
content still use the existing tool-result normalization. An oversized or
unsupported app description leaves the ordinary readable tool result intact.
Each surface binds owner, chat, answer, source tool, connection configuration
fingerprint and resource URI. No browser input can select or replace a source.
Surfaces expire after 24 hours; reloading or restarting does not extend expiry.

## Headless host API

All endpoints use the existing first-party Workbench session, secret and Origin
checks. They are for a trusted host, never direct iframe access. The host must
not forward cookies, secrets, MCP credentials or connection configuration to an
app. A future bridge must authenticate its frame and expose only these methods.

`POST /api/v1/chats/{chat_id}/interactions/surfaces/{surface_id}/mcp-apps/read`
accepts `{revision, method, params}`. Methods:

| Method | Behavior |
| --- | --- |
| `ui/initialize` | Requires protocolVersion 2026-01-26, appInfo and appCapabilities; returns backend host info and serverTools/serverResources capabilities. No sandbox, links, logging or display capabilities are claimed. |
| `ping` | Empty params, verifies the saved binding and current access. |
| `tools/list` | Empty params, fresh app-visible tools on the bound connection. |
| `resources/read` | Exactly `{uri}`; only the surface's bound `ui://` HTML resource is permitted. |

Reads reconnect to the same configured MCP source, rediscover its current tool
linkage, and check person, selected branch, session lease, source configuration,
source selection, expiry and revision before and after network IO. Resource
bytes are returned as JSON data, never as an executable same-origin HTML page.
Responses use no-store and nosniff. Remote failures expose no remote error text.
At most eight reads run concurrently; each has a 45-second overall deadline.
Resource listing/subscription, arbitrary URIs, cross-source calls, app-provided
tools, links, logging, downloads, sampling and elicitation are unsupported.

HTML resources require exactly one matching content item, the pinned MIME type,
UTF-8 text or valid base64 UTF-8 blob, and an HTML document with doctype/html.
The resource response is bounded to 256 KiB JSON / 192 KiB decoded HTML, including
metadata. Preserve `_meta.ui` CSP, permission, domain and border requests after
shape validation; these are requests, not grants. G5 must enforce them in an
isolated origin before executing any bytes. Only named pinned metadata fields
are accepted for the resource's UI policy. No URL in it is fetched by the backend.

## Approved operations

Use G1 proposals and decisions; the action name is the MCP method:

* `tools/call`: arguments `{name, arguments}`. Resolve the raw tool name on a
  fresh bound connection, enforce app visibility and current JSON Schema, and
  recheck authorization immediately before one session-level MCP call. Every
  call requires explicit approval, including read-only annotations. No SDK
  elicitation/header retry loop is used. Remote error results are completed
  protocol results with `isError`; lost or oversized results are uncertain.
* `ui/message`: `{role: "user", content: {type: "text", text}}`, max 8192
  characters. Approval adds attributed app text to the next explicit user turn;
  it does not start an autonomous generation.
* `ui/update-model-context`: optional text-only `content` array (max 16) and/or
  object `structuredContent`, at least one required. Approval replaces that
  surface's previous context for subsequent explicit user turns.

Model projections contain only normalized tool content or the approved context /
message fields, never UI metadata or HTML. They are ordinary attributed user
context, never system instructions; selected-branch projections are bounded to
64 KiB, with older entries omitted first. No provider call is made by a proposal.
The original session decides its own action. G1 replay, stale revision, branch,
stop, revocation, quotas and crash/uncertainty rules apply unchanged. A reconnect
discovery failure before the tool request is a certified no-effect failure;
after dispatch, an unknown outcome is never retried. Pending approvals are
cancelled on restart; saved active surfaces reconnect after a fresh sign-in.

Acceptance uses the real MCP SDK over loopback HTTP/SSE and a headless
authenticated Workbench client. Browser conformance is explicitly not claimed.
