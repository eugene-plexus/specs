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
The snapshot's optional `sourceName` names the configured originating connection
in host-owned text beside the surface and its action review; it comes from the
server's connection record, never from embedded HTML.

## MCP Apps constrained renderer

Self-contained HTML runs only after Open app, in an opaque-origin proxy and a
second sandboxed iframe. Both deny same-origin access, popups, navigation of the
host, downloads and devices. A response-header CSP permits inline scripts and
styles, embedded images/fonts, but denies network, workers, plugins, forms and
base changes. The proxy accepts its first document only from its actual parent;
it forwards JSON-RPC only from its own child. The host checks source, opaque
origin and a fresh per-mount channel. Messages and outstanding requests are
bounded (24 KiB proxy messages, 20 KiB RPC requests, 40 messages/second,
16 pending and 128 distinct requests per mount). Stopping/unmounting invalidates
all pending bridge replies. The host sends ping every two seconds and closes
a view that does not reply for six seconds; initialization has a 60-second bound.
An empty proxy that has not announced readiness after three seconds may be
replaced up to six times, to recover Chrome's lingering blocked sandbox process.
A proxy that has loaded an app is never retried automatically.

This intentionally differs from the upstream web proxy requirement for a
separate origin with allow-same-origin. It is **not full MCP Apps browser
conformance**. Requested nonempty CSP domains, device permissions or a domain
are refused, rather than silently granting access. No sandbox service, DNS
configuration or credentials are required. Capability metadata identifies this
as `opaque-offline`, with these limits.

The bridge implements initialization, initialized, tool-input then tool-result,
host-context changes, size changes, ping, tools/list, bound resources/read and
the G2 action methods. Unsupported RPC requests get Method not found; oversized
requests get Invalid request and malformed envelopes are ignored. No generic API proxy, direct external navigation,
or remote-origin messages are accepted. Host context reports inline display,
light/dark theme and locale; host capabilities report the actual empty
CSP/permission grants.

## A2UI forms

Render the eight validated forms-v1 components with native accessible elements,
plain text, labeled fields, keyboard buttons and the Workbench theme. Layout
hints stay within local styles. Four pure local functions resolve data bindings
and validation; they cannot call APIs. Explicit Save changes commits changed
inputs sequentially, starting at the revision where editing began and carrying
forward each returned revision. A partial failure leaves the drafts visible;
Discard unsaved changes reloads the current saved values. Server actions wait
until all drafts are saved. Intermediate updates do not remount a dirty form.
Checks show their messages. Server actions use their declared event/context and
the durable host review. Unsupported action functions remain inert with a
visible explanation. No remote code, CSS, assets or schemas load.
Text and button labels are plain text. Layout alignment is supported; theme
color and weight hints are not applied. Buttons containing another interactive
control are refused with a readable fallback. Shared component references have
distinct DOM label IDs; only checks reachable from root affect submission.

## AG-UI conversations

An empty owned chat can choose ordinary chat, Workbench through AG-UI, or an
authorized configured agent. An AG-UI thread stays with its original source.
The UI starts runs with unique IDs, reads the authoritative persisted projection,
and continues with exact saved messages/state and parentRunId. Reload performs
reads only. Disconnects never resubmit a POST. A failed start requires inspecting
the saved run before another attempt. Its run ID is retained in session storage
under the person/chat key until the saved run is found; out-of-order reads cannot
roll the UI back. Ordinary send controls wait for this lookup. Native mode has
a model selector. Stop uses the explicit run stop endpoint.
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

| Protocol | Product capability | Limits |
| --- | --- | --- |
| MCP Apps 2026-01-26 | `rendererProfile: opaque-offline`, `browserConformance: constrained`; reviewed G2 methods | Self-contained apps only; the proxy differs from upstream's allow-same-origin requirement; no network/device grants |
| A2UI 0.9.1 | forms-v1 eight-component renderer, four pure functions, reviewed actions | Local catalog only; plain text and host palette; no remote assets/code |
| AG-UI 1.0 | Serve/connect selection, native approvals, projection, stop, interrupt/resume | G4 event subset; plain remote output and inspectable state/tool traces; no remote custom-HTML promotion |

`supportedProtocols` includes these three only when the shipped UI build includes
its `ui-capabilities.json` marker. Source-only/headless installs retain
`renderer: false`. The MCP capability also reports limits `no-network`,
`no-devices`, `opaque-proxy-origin`. Projections refresh once per second; the
G1/G4 stream endpoints remain available for other clients.

Advertise renderer capability only with browser acceptance for both iframe
boundaries, CSP, forged messages, actual reviewed effects, branch/reload/stop,
fallback, keyboard labels and themes. Record limits, source/dist pins and exact
validation in the G5 acceptance record. Existing artifact rendering is unchanged.
