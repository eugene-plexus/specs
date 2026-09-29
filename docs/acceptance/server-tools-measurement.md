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

## 3. SearXNG's JSON answer (measured 2026-09-29)

Instrument: `searxng/searxng@4e2c1ea` (2026-09-29) cloned into WSL2 Ubuntu,
its `requirements.txt` in a Python 3.13 venv, `python -m searx.webapp` with a
settings file of `use_default_settings: true`, `server.limiter: false` and
`search.formats: [html, json]`. No container runtime was needed.

- `GET /search?q=llama.cpp+rpc+server&format=json`: **200 in 0.57 s**,
  `application/json`, 34 results. Top-level keys: `query`, `results`,
  `answers`, `corrections`, `infoboxes`, `suggestions`,
  `unresponsive_engines`. **There is no `number_of_results`.**
- Each result carries `url`, `title`, `content` (the excerpt), `engine`,
  `engines`, `score`, `category`, `publishedDate` (ISO 8601 or `null`),
  `pubdate`, `thumbnail`, `parsed_url` and presentation fields
  (`template`, `img_src`, `iframe_src`, `audio_src`, `length`, `views`,
  `author`, `metadata`, `priority`, `positions`, `open_group`,
  `close_group`).
- `unresponsive_engines` is a list of pairs: `[["duckduckgo", "CAPTCHA"]]`
  on this run. A search can succeed with some engines down.
- **A format that is not enabled is `403` with an HTML body** ("You don't
  have the permission to access the requested resource"), not JSON. So the
  one thing a SearXNG user needs to be told — switch JSON output on — has to
  be inferred from a 403 on a JSON request.
- No `q` is `400 {"error": "No query"}`.
- `time_range=week` is accepted (the documentation lists day, month, year).
- `site:github.com llama.cpp` returned only github.com results: the operator
  reaches the engines.

The answer is kept as the tool-driver's test fixture
(`tool-driver/tests/fixtures/searxng-answer.json`, trimmed).

## 4. Owed

- **What Codex does with `web_search_call` items** in a Responses stream
  (needs a capture mode that answers with them).
- **Brave, live**: no Brave key on this box. Built from its API
  documentation (`X-Subscription-Token`, `count` at most 20, `web.results[]`
  with `title`, `url`, `description`, `age`, `page_age`, `extra_snippets`;
  401, 422, 429).
- A live Anthropic answer to the same search request, to copy its block
  shapes exactly rather than from documentation.
