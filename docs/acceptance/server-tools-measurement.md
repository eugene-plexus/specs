# Server-run tools: what the clients send (P8-0), 2026-09-29

Measurements behind [`../design/server-run-tools.md`](../design/server-run-tools.md).
Each client was pointed at a throwaway loopback listener with an isolated
config directory, so nothing reached a real provider and no live credential
was recorded.

## 1. Claude Code 2.1.283: WebSearch is its own request

Instrument: `scripts/r4-capture.py --mode websearch`, which answers the main
loop's first request with a `WebSearch` tool call and records what the client
does to run it. Isolated `CLAUDE_CONFIG_DIR`, a throwaway approved key,
`claude -p "Search the web for eugene plexus and tell me what it is"
--model qwen3-8b --allowedTools WebSearch`.

Five requests: a session-title request (no tools), the main loop (29 client
tools, `WebSearch` among them), **the search**, and the main loop again with
the result.

The search is a separate `POST /v1/messages?beta=true`, streamed, with the
same `x-api-key`, and exactly one tool:

```json
{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}
```

Its system prompt is Claude Code's own (*"You are an assistant for performing
a web search tool use"*), its one user message is *"Perform a web search for
the query: eugene plexus local inference"*, `tool_choice` is `auto`,
`max_tokens` 32000, `output_config.effort` `high`. No `allowed_domains` or
`blocked_domains` for a plain query.

**What it does with the answer:** the listener answered with plain text
(`websearch-ok`) and no search blocks. Claude Code accepted it and handed the
main loop this `tool_result`:

```
Web search results for query: "eugene plexus local inference"

websearch-ok

REMINDER: You MUST include the sources above in your response to the user using markdown hyperlinks.
```

So the client needs an answer from the search request, not a particular
block shape. Returning `server_tool_use` and `web_search_tool_result` blocks
as Anthropic does is still the right answer (it gives the client real
sources); a text answer is enough not to break it.

**Today the gateway refuses that request with a 400** (`anthropic.py:614`:
any tool with a `type` is refused at the door), so Claude Code's WebSearch
fails on every local model.

## 2. Codex CLI 0.130.0: one tool, one flag

Instrument: `scripts/responses-capture.py`, an isolated `CODEX_HOME` naming a
custom `responses` provider, `codex exec --skip-git-repo-check "say ok"` with
stdin closed (Codex otherwise waits on it). One run per `web_search` setting:

| `web_search` in `config.toml` | The tool on every request |
| --- | --- |
| (not set) | `{"type": "web_search", "external_web_access": false}` |
| `"cached"` | `{"type": "web_search", "external_web_access": false}` |
| `"live"` | `{"type": "web_search", "external_web_access": true}` |
| `"disabled"` | no `web_search` tool (9 tools instead of 10) |

So the default is cached, and `true` is Codex's user asking for live search.
`include` was empty in all four.

## 3. Owed

- **What Codex does with `web_search_call` items** in a Responses stream
  (needs a capture mode that answers with them).
- **SearXNG's JSON answer**, from a real instance with `json` enabled in its
  `search.formats` (no container runtime on this box).
- A live Anthropic answer to the same search request, to copy its block
  shapes exactly rather than from documentation.
