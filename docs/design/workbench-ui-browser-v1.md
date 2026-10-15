# Workbench interactive content browser, G5

This is the product renderer for the subsets in the G1–G4 contracts. Wire
versions remain MCP Apps 2026-01-26, A2UI 0.9.1 forms-v1, and AG-UI 1.0.

## Trust and lifecycle

The conversation reads the authenticated interaction snapshot. Only surfaces
attached to messages on the displayed branch appear. Read-only, expired, deleted,
unsupported, incomplete and disconnected surfaces retain their text fallback.
An inaccessible snapshot removes its active views. Reloading never approves or
retries an action. Forms and apps propose actions; a separate host-owned review
shows the method and exact arguments before Allow once or Decline. The server
remains authoritative for revision, access, approval, source and dispatch.

## MCP Apps constrained renderer

Self-contained HTML runs only after Open app, in an opaque-origin proxy and a
second sandboxed iframe. Both deny same-origin access, popups, navigation of the
host, downloads and devices. A response-header CSP permits inline scripts and
styles, embedded images/fonts, but denies network, workers, plugins, forms and
base changes. The proxy accepts its first document only from its actual parent;
it forwards JSON-RPC only from its own child. The host checks source, opaque
origin and a fresh per-mount channel. Messages and outstanding requests are
bounded. Stopping/unmounting invalidates all pending bridge replies.

This intentionally differs from the upstream web proxy requirement for a
separate origin with allow-same-origin. It is **not full MCP Apps browser
conformance**. Requested nonempty CSP domains, device permissions or a domain
are refused, rather than silently granting access. No sandbox service, DNS
configuration or credentials are required. Capability metadata identifies this
as `opaque-offline`, with these limits.

The bridge implements initialization, initialized, tool-input then tool-result,
host-context changes, size changes, ping, tools/list, bound resources/read and
the G2 action methods. Unsupported RPC requests get Method not found; malformed
requests get Invalid request. No generic API proxy, direct external navigation,
or remote-origin messages are accepted. Host context reports inline display,
light/dark theme, locale and the actual empty CSP/permission grants.

## A2UI forms

Render the eight validated forms-v1 components with native accessible elements,
plain text, labeled fields, keyboard buttons and the Workbench theme. Layout
hints stay within local styles. Four pure local functions resolve data bindings
and validation; they cannot call APIs. Explicit Save field commits a changed
input using its expected revision before server actions become available.
Checks show their messages. Server actions use their declared event/context and
the durable host review. Unsupported action functions remain inert with a
visible explanation. No remote code, CSS, assets or schemas load.

## AG-UI conversations

An empty owned chat can choose ordinary chat, Workbench through AG-UI, or an
authorized configured agent. An AG-UI thread stays with its original source.
The UI starts runs with unique IDs, reads the authoritative persisted projection,
and continues with exact saved messages/state and parentRunId. Reload performs
reads only. Disconnects never resubmit a POST. A failed start requires inspecting
the saved run before another attempt. Stop uses the explicit run stop endpoint.
Interrupted runs show each request and accept a JSON response or cancellation;
server schema/expiry checks remain authoritative. Uncertain outcomes are named
and never automatically retried. Tool traces and state are inspectable text;
remote custom events never become trusted HTML or A2UI surfaces.

Owners configure immutable agent connections (name, URL, optional bearer token,
people) and remove them in the GUI. Tokens are sent once and never read back.
`GET /api/v1/ag-ui/people` is an owner-only grant picker returning known signed-in
people's `{sub, name}` records, including the owner. It grants no chat access
and works independently of the owner's read-chats setting.
Read-only views retain the saved normal answer and cannot start/resume a run.

## Release gate

Advertise renderer capability only with browser acceptance for both iframe
boundaries, CSP, forged messages, actual reviewed effects, branch/reload/stop,
fallback, keyboard labels and themes. Record limits, source/dist pins and exact
validation in the G5 acceptance record. Existing artifact rendering is unchanged.
