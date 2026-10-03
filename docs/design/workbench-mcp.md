# Workbench MCP tools (C5)

The next Workbench slice after C4. C1–C4 are built; the roadmap's C4 pickup
was stale. Workbench remains an ordinary gateway client. Tool discovery and
execution belong to Workbench, using MCP, never an operator door in Eugene.

**C5a and C5b are built and pinned 2026-10-03:**
[network tools](../acceptance/c5-mcp-run.md),
[local tools](../acceptance/c5-local-tools-run.md).

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

## C5b: local servers

The install owner can add a stdio server with an absolute executable path,
an argument array and optional environment values. Saving does not execute
code. **Start and check** starts that exact program and lists its tools;
selecting it for a chat starts one process for that answer. The model can
choose only the listed tools and their validated arguments, never the
executable, arguments or environment. Individual tool calls retain C5a's
approval and durable-intent rules.

**Provisioning:** the machine administrator installs the program and its
dependencies, using their upstream instructions, in a location the app's
account can execute. Workbench does not install packages or run shell
command strings. On Windows the command must be an `.exe`; Python and
Node scripts name their interpreter and put the script in the argument
array. This keeps tool dependencies out of Workbench's own environment
and leaves package updates with the operator. A missing executable or
permission failure is reported from the attempted start.

**Access:** local servers are owner-only in C5b. This is a deliberate limit:
all code in the app's account can read its files, including other people's
chats and Workbench's app-scoped credentials. A separate working directory
is not a sandbox. The owner must trust the server and its dependencies;
the page explains this before starting one. Other people cannot list,
select, check or execute it. Folder grants and per-person process isolation
remain later work; a shared local executable cannot promise those boundaries.

**Launch signal:** the agent's account supervisor records `accountKind` in
the launch spec. The launcher supplies `EUGENE_PLEXUS_APP_ACCOUNT_KIND`
only from that field, replacing any ambient or manifest environment value.
Workbench accepts `windows_service` or `systemd`; missing or unrecognized
values disable local starts. The Workbench catalogue now declares
`localActions: true`, so C5b installs only where C1 can provide an account.
Existing per-user installs keep C5a until moved to a supported system
install. A manually launched development copy still serves chat and HTTP
tools, with local processes disabled by default.

The app uses the official SDK's stdio transport. Each connection has its own
directory under Workbench's `tools/`, also its processes' home and cache directory.
Its environment contains OS essentials and the owner's explicit values,
never inherited Eugene or provider credentials. Environment values stay
in private SQLite storage; reads return their names only. Executable
arguments must not contain secrets: process lists can show them. Stderr is
discarded because third-party programs can print those credentials; failures
name the observed transport/start condition and how to check configuration.

At most four local processes run at once. A process lives through the
answer, including approval waits, and closes on completion, Stop or graceful
shutdown. The SDK closes stdin, waits, then terminates an unresponsive
process tree; it does not restart failed servers. On POSIX a small stdio
guard remains the process-group leader until shutdown and reaps the group
even when the server exits normally: SDK 2.3 otherwise leaves that server's
ordinary children running. A real child-process test failed before the guard
and passes with it. Windows uses the SDK's Job Object. Programs must remain
attached to stdio and must not daemonize. The C1 service manager owns the
app's final shutdown boundary. Removing a connection prevents pending calls
but does not undo dispatched actions or delete program-created data.

## Next slices

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

For C5b, also install that published archive on disposable Windows service
and Linux system installs. Exercise actual app-account identity, protected
files, clean environment, ordinary child cleanup, owner/member access and
saved results after a verified process restart. Run a real stdio server in
the transport tests and Chrome, including Stop, startup failure, process
limits and migration from the HTTP-only schema.
