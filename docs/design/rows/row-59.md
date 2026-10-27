# Row 59: more server-run tools: Tavily, and remote MCP on Responses

Lane GW. **High risk** for 59b (the hub dials a URL a caller supplies).
Sources: P8-later and §9 #1 of `server-run-tools.md` ("Remote MCP in P8?
No. The hub would dial caller-supplied URLs with caller-supplied
credentials. Revisit as its own slice." and "Tavily later"), the boundary
in §1 (server-run tools live in a tool driver; the gateway never holds a
tool's key), tool-driver `providers.py` (SearXNG, Brave).

## 59a. Tavily as a search provider (S, low)

- A third provider in the tool driver: `search_tavily` (`POST
  https://api.tavily.com/search`, the account's key, `search_depth` basic
  by default, `max_results` from the request, include and exclude domains
  mapped from `web_search`'s filters, Tavily's `answer` kept as the
  provider's summary the way SearXNG's answers are).
- Failures in Tavily's words (rate limit with its retry time, a bad key,
  quota used up), as Brave's are.
- The console's search account form gains Tavily (key field, "basic or
  advanced depth" with the credit cost of each in one line).
- Contract: the provider enum and its settings in `tool-driver.yaml`.

## 59b. Remote MCP on the Responses door (M, high)

### What it does

A Responses request may carry `{"type": "mcp", "server_label",
"server_url", "headers" or "authorization", "allowed_tools",
"require_approval"}`, as on OpenAI. Eugene connects to that MCP server,
lists its tools (`mcp_list_tools` item), lets the model call them
(`mcp_call` items with output), and asks for approval where the request
says so (`mcp_approval_request` items, answered by
`mcp_approval_response` items in the next request, sent whole or chained
by `previous_response_id` once row 54 is built).

### Where it runs

In the tool driver, as a new tool kind, not in the gateway: egress,
timeouts and caller credentials live with the other server-run tools.
The gateway runs the loop and calls the tool driver for `list_tools` and
`call_tool`, passing the server URL and the caller's headers for that one
request.

### What it may reach

- **Internet only, by default.** The tool driver resolves the host once,
  refuses private, loopback, link-local, CGNAT, multicast and metadata
  addresses (the same predicate `node_address` uses, built from
  `is_global`), and connects to the address it checked (no second lookup,
  so DNS rebinding cannot switch it). `https` only.
- **The owner's setting** "Remote MCP from API clients": Off, Internet
  only (default), or Internet and this network (an expert's choice, with
  "a client could then reach services on your network through Eugene").
  Call R59-MCP.
- **Per key:** a key's `allowedTools` (A5) must allow `mcp`; a key with no
  tool limit may use it.

### What is never kept

The caller's headers and tokens exist for the request only: never logged,
never in metrics or stored responses (row 54 stores the items without
`headers` and `authorization`).

### Limits

30 s per call, 8 MiB per answer (row 29's cap), 64 tools listed, 20 calls
per response; each limit names itself when hit.

## Contract

`gateway.yaml` (the `mcp` tool type and its items), `tool-driver.yaml`
(Tavily; the MCP call API between the gateway and the tool driver),
`agent.yaml` if the tool driver's GUI schema lives there.

## Tests that fail before

- tool-driver `test_tavily.py::test_results_and_answer_map_to_found` and
  `test_a_rate_limit_names_the_retry`.
- tool-driver `test_mcp_remote.py::test_a_private_address_is_refused` (one
  case per range), `test_rebinding_cannot_switch_the_address`,
  `test_http_is_refused`.
- gateway `test_responses_mcp.py::test_list_tools_and_a_call_round_trip`
  (today: refused) and `test_approval_requests_wait_for_a_response`.
- gateway `test_responses_mcp.py::test_headers_never_reach_metrics_or_logs`.

## Acceptance (CI, Linux, about 4 minutes)

`specs/scripts/row59-remote-mcp-acceptance.py` on row 2's harness: a
fixture MCP server on a public-looking address (the harness maps a
TEST-NET address to it under an expert setting that the test turns on,
and checks the refusal with the default), the fixture backend scripted to
call its tool; then a server URL on `127.0.0.1` and on `169.254.169.254`
refused by default naming the rule; the caller's header seen by the
fixture MCP server and absent from the gateway's log and metrics.

**The reviewer should attack:** every way to reach a private address
(redirects, IPv6 forms, DNS answers with several addresses, `0.0.0.0`,
decimal IPs, the expert setting's scope), credential leaks (logs, errors
echoing headers, stored responses), and a malicious MCP server's answers
(size, tool names that collide with function tools, instructions in tool
descriptions reaching the model — the same exposure a client's own tools
have).

## Size and risks

M in total, about 2 days; 59b gets one adversarial review. Risks:
- **SSRF from the hub's network position:** internet only by default, the
  checked address pinned for the connection, `https` only.
- **A caller's token passes through Eugene:** used for one request, never
  written anywhere.

**Calls:** R59-MCP (remote MCP allowed to the internet only, by default).

## Calls answered by Troy (2026-10-22)

- **R59-MCP: Choice 1.** Remote MCP servers named by API clients are
  allowed to internet addresses only; the owner can turn it off, or (expert)
  also allow this network.

## Calls answered by Troy (2026-10-27)

- **R59-PROXY: Choice 1, as built.** Remote MCP never goes through the
  user's proxy, so the address check is the one that applies; an install
  that reaches the internet only through a proxy cannot reach a remote MCP
  server.
- **R59-HOME: Choice 1, as built.** Remote MCP runs in a search account's
  process; an install with no search account refuses it and says to add
  one.

## What building found (2026-10-26)

- **`is_global` alone is not a safe predicate.** On Python 3.12 it is True
  for `224.0.0.1` and `ff02::1` (multicast), `fec0::1` (site-local) and
  `64:ff9b::7f00:1` (NAT64's spelling of 127.0.0.1). The tool-driver's
  `egress_guard` checks metadata, unspecified, link-local, multicast,
  loopback and reserved first, and judges an IPv6 address that carries an
  IPv4 one (mapped, NAT64, 6to4, Teredo) by the IPv4 address too.
- **One pooled client per (reach, scheme).** A connection pool keyed by
  origin would otherwise hand a connection checked under the expert reach
  to a request under the default one.
- **Defaults built where the design was silent:**
  - *This network* does not include this machine: loopback is refused
    under every reach, because this install's own services listen there and
    some trust a loopback caller. The acceptance therefore puts its MCP
    server on the runner's own private address.
  - Plain `http` is allowed under the expert reach, to this network only;
    `https` stays required for the internet. A LAN MCP server rarely has a
    certificate.
  - Remote MCP never uses the user's proxy: through a proxy the proxy
    resolves the name and the address check means nothing. An install that
    reaches the internet only through a proxy cannot reach a remote MCP
    server (call R59-PROXY).
  - Remote MCP runs in a search account's process (every tool-driver lists
    `mcp`, set up or not). An install with no search account refuses it,
    saying to add one (call R59-HOME).
  - A local-only key is refused, as for search: the model's arguments leave
    the machine.
  - MCP calls have their own budget, 20 a response, which `max_tool_calls`
    lowers; the install's search default (5) does not apply to them.
  - `require_approval` in its object form: a tool neither filter names
    needs approval, unless only `always` was given.
  - A redirect is followed only as a 307 or 308 to the same origin.
  - Only the Streamable HTTP transport; a server that answers with
    neither JSON nor an event stream is named as not one.
- **The caller's credential is scrubbed, not only unlogged.** A server that
  echoes the caller's token in an error, a tool description or an output
  gets it back as `[redacted]` (values of 8 characters or more), so it
  cannot reach a log, a metrics row or a stored response that way.
- **httpx logged every request's URL at INFO** in the tool-driver: a
  SearXNG search's query text, and an MCP server's path and query, which
  can carry a key. `__main__` sets httpx and httpcore to WARNING.
- **An approval's id is checked for consistency, not authenticity.**
  Without a stored response the caller sends the request item back itself;
  a caller who forges one can only make Eugene call the caller's own server
  with the caller's own credential, which it could do directly.
- **Tavily's country boost takes a country's English name**, not the code a
  request carries; a location is named as ignored. There is no Tavily key
  on the development box: the provider follows Tavily's API reference.
- **"8 MiB per answer" is per call.** Counted per HTTP answer, a server
  that split its tool list over 32 pages could make the tool-driver hold
  256 MiB; every answer of one call now counts against one 8 MiB.
- **The metrics row gains `mcpCalls`.** Split on "not an image", MCP calls
  would have been counted as web searches. A row names neither the server
  nor the tool: they are the caller's words.
