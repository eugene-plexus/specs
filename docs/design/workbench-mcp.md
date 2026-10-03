# Workbench MCP tools (C5)

The next Workbench slice after C4. C1–C4 are built; the roadmap's C4 pickup
was stale. Workbench remains an ordinary gateway client. Tool discovery and
execution belong to Workbench, using MCP, never an operator door in Eugene.

## C5a: network servers

The owner adds a named Streamable HTTP MCP server in **Toolbox · Tools**.
This starts the workshop vocabulary chosen for the second tool (C3 call 1),
with the plain meaning beside the name. Chats keep their plain name.
The form says that this connection is shared with everyone signed in. An
optional bearer credential stays in Workbench's private SQLite database,
like its sign-in refresh tokens; reads expose only whether one is stored.
HTTPS is required except for loopback HTTP. Credentials in URLs, fragments
and query strings are refused. Redirects are refused. Eugene's client key,
sign-in credentials and environment are never given to MCP servers.

Each chat chooses server connections, off by default. Workbench discovers
their tools for each answer and uses stable, namespaced function names in
the public chat/completions request. A tool call pauses for the chat's owner
to approve its exact server, tool and JSON arguments. Declining returns a
tool result to the model without executing the call. Server annotations
are descriptive, never permission to bypass approval. The install owner
reading another person's chat cannot approve its calls.

Connections are immutable: replace one by removing it and adding another.
Removing a connection prevents later calls, including ones already awaiting
approval. Calls already sent may finish. No retries are made after dispatch:
a lost connection may mean an action happened. Stop and restart record that
uncertainty; neither resumes a tool call. Answers and tool records remain
visible after tabs close. Pending approval expires after 30 minutes.

Tool arguments and results are bounded. Only text/structured results enter
the model conversation; other content is identified as unsupported. Tool
history is stored with its answer and sent on later turns as ordinary
assistant tool calls and tool results. Editing/retrying still follows C3's
replacement rule and explicitly warns that this does not undo tool actions.
The loop stops after eight rounds or sixteen calls, and malformed calls or
incompatible tools fail with an actionable message.

The official Python MCP SDK owns transport and protocol negotiation. This
slice uses its released 2.3 series, not a hand-written MCP implementation:
[client documentation](https://py.sdk.modelcontextprotocol.io/client/).

## Next slices

C5b adds stdio servers in the app's OS account. Before that ships, settle
process installation, per-person access to shared app files, and the
permission signal from the launcher; then change the app manifest's local
actions requirement. C5a starts no processes and grants no folders.

C6 designs folder grants and filesystem tools. Dedicated media screens can
use the gateway's existing media doors; managing local media engines also
needs the resource ledger. Answer versions and the working animation remain
separate Workbench slices.

## Evidence required

Exercise a real MCP HTTP server through Workbench and a scripted gateway:
discovery, fragmented calls, approval/decline, continuation, later history,
revocation, credentials, hostile results, Stop, interrupted calls and schema
upgrade. Run the Python and browser suites, lint, type checks and a page
build. Record deployment separately from implementation: a main-tree build
does not update the catalogue's dist pin.
