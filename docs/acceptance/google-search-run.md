# Google Search beside Brave — run record

**Date:** 2026-10-09. **Design:**
[`google-search-account.md`](../design/google-search-account.md) (GS1-GS9,
all Troy's, taken from his phone and at the machine the same morning).
**Issue:** inference-driver#6 (the search half; Gemini code execution is
the next slice, GS2).

A Gemini API key is now a web-search account beside Brave and SearXNG,
for any model the install serves: Google's grounded answer and its sources
reach the model, Google's Search Suggestions reach the person, and the
person sets which account a search tries first.

| Repo | Commit | What |
|---|---|---|
| specs | `c112691` | contract: `WebSearchResponse.searchSuggestions`; `x_eugene_plexus.search_suggestions` (chat), on a Responses `web_search_call` item and an Anthropic `web_search_tool_result` block; `RoutingTableView.search_accounts` (`SearchAccountView`); the design |
| tool-driver | `7081c79` | the `google` provider: one `generateContent` with `googleSearch`; answer verbatim; sources from `groundingChunks`, redirects resolved; the cheapest flash-lite on the key's listing, or `searchModel`; domain filters drop the answer; 61 tests (`tests/test_google_search.py`, built on the answer Google sent live) |
| gateway | `a1e6188` | the suggestions to every door, never the model, metrics, logs or headers; `webSearchOrder`, read at every search; the routing view's `search_accounts` |
| ui | `a2f8298`, dist `fe5ffe2` | "Google Search (Gemini API key)" when adding a search account, with its cost and Google's terms; *Web search order* on Routing |
| workbench | `17fbd28`, dist `0735ff9` | the Sources card shows each search's suggestions in a sandboxed frame; kept with the message (schema 8) and never sent to a model |
| agent | `c82975b` | catalogue: Workbench dist `0735ff9` |
| specs | this push | `scripts/google-search-acceptance.py` (new, in CI); pins |

## What was run

**`scripts/google-search-acceptance.py --live` — 8 passed**, 2026-10-09,
the run of record, against the working trees (interpreter the agent's
venv; the OpenAI SDK 3.20.0 and Anthropic SDK 1.9.0 from their own). A
control root, an enrolled agent, a gateway, a local tool-calling model, and
two search accounts the agent spawned and that were set up through its
proxy by name: `google` over a fixture of Google's grounded answer (shaped
from the live answer) with its own redirect host, and `brave` over Brave's
documented API.

| Check | What passed |
|---|---|
| 1 | both accounts spawned and set up by name; the Gemini key sealed at rest (no plaintext under the install) and redacted on read; Google bills per search |
| 2 | by default Brave is searched first (both bill per search, then by name), as the routing view says; `webSearchOrder: ["google"]` puts Google first on the next search with no restart, Brave after "by default" |
| 3 | chat, plain and streamed: the model read Google's answer verbatim ("Answer from the search provider: ...") and its sources at their real addresses, each with the sentences that cite it; Google's redirect was asked, the page never fetched; the answer's citation is the real address; the Search Suggestions came back in `x_eugene_plexus` byte for byte and never reached the model; the cheapest model on the key's paginated listing was used, and the account's settings name it |
| 4 | Responses (`web_search_call` item, final and streamed `output_item.done`) and Anthropic messages (`web_search_tool_result` block, plain and streamed) each carry the suggestions unmodified |
| 5 | with `allowed_domains`, Google is asked with a `site:` hint, only the matching source reaches the model, and Google's own answer is left out |
| 6 | the suggestions are in no metrics row and no process log; the key rode `x-goog-api-key`, never a URL or a log |
| 7 | `webSearchOrder: []` returns to the default rule, as the routing view says |
| L | **live:** one real Google search through Troy's key, the account re-pointed at Google and the key sealed through the proxy: three real addresses reached the model (canakit.com among them) and Google's Search Suggestions came back. The run's state was checked for the key in plaintext (none) and deleted |

**Sabotage, once each, restored from a copy:** redirects not resolved
(check 3), the answer kept under a filter (check 5), chat dropping the
suggestions (check 3), the Anthropic block dropping them (check 4), the
order ignored (check 2). All caught.

**Unit tests:** tool-driver 155 passed, 1 skipped (the agent's 22
sabotages of the provider caught 21; the miss is a filter the service
applies again); gateway 1,272 passed, 1 skipped (10 sabotages caught);
ui 1,747 vitest; Workbench 248 passed, 12 skipped (opt-in browser runs),
front end 208 (11 sabotages caught). ruff, `ruff format`, `mypy` and
`mypy --platform linux` clean in every Python repo; `tsc` and eslint in
both front ends; gitleaks clean over the five trees.

**Measured live first** (one grounded call on `gemini-3.5-flash-lite`,
inside the 5,000 free a month): `searchEntryPoint.renderedContent` is a
self-contained `<style>` and chip carousel linking to google.com searches;
each source is a `vertexaisearch.cloud.google.com/grounding-api-redirect/`
link whose `GET` answers `302` to the real page; a segment's
`startIndex` is omitted when 0; text parts carry a `thoughtSignature`.
The flash-lite answer itself was wrong once ("llama.cpp v0.6.0") while
its sources were right.

## Not yet run

- Workbench's Sources card with real suggestions in a browser (the frame is
  checked by its unit tests: the sandbox, the bytes, no frame when absent).
- Google's error shapes (a refused key, `RESOURCE_EXHAUSTED` with
  `RetryInfo`, a region refusal) are from Google's documentation; the one
  key on the box was used for successful calls only.
