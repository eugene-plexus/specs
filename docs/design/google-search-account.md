# Google Search as a search account, beside Brave

**Status:** designed 2026-10-09; every call taken by Troy (GS1-GS9); built and
pinned 2026-10-09, one live search with Troy's key (`docs/acceptance/google-search-run.md`).
**Issue:** inference-driver#6 (the search half; code execution is its own
slice, GS2). Follows `gemini-provider.md` (G6) and P8's
`server-run-tools.md`.

**Why now (Troy, 2026-10-09):** some people keep a Gemini key only for its
search. So Google Search is offered as a web-search option right alongside
Brave and SearXNG, for any model the install serves, not only when the
model answering is Gemini.

## 1. What measuring found (2026-10-09)

- **Google's search is reached through a model.** There is no plain search
  endpoint for a Gemini key: a `generateContent` call with the
  `googleSearch` tool lets the model run queries and answer from them.
  The candidate carries `groundingMetadata`: `webSearchQueries`,
  `groundingChunks[].web{uri, title}`, `groundingSupports[]{segment{text,
  startIndex, endIndex}, groundingChunkIndices}` and
  `searchEntryPoint.renderedContent` (HTML, Google's *Search Suggestions*).
  The chunk `uri` is a Google redirect
  (`vertexaisearch.cloud.google.com/grounding-api-redirect/...`); `title`
  is the site's domain. No domain filter and no location but a
  latitude/longitude (`toolConfig.retrievalConfig.latLng`).
- **Billing:** on Gemini 3 each search query the model runs is billed;
  5,000 a month are free across Gemini 3 models, then $14 per 1,000, plus
  the call's tokens.
- **Google's terms (Gemini API additional terms, 2026-04-28)**, verbatim:
  you "will not modify, or intersperse any other content with, the
  Grounded Results or Search Suggestions"; "will only display the Grounded
  Results with the associated Search Suggestion(s) to the end user who
  submitted the prompt"; "will not ... cache, frame, syndicate, resell,
  analyze, train on, or otherwise learn from Grounded Results or Search
  Suggestions". Grounded Results may be stored in an end user's chat
  history for that user to view.
- **Our side (P8):** the tool driver's contract already allows "a provider
  that searches by asking a hosted model": its words in `answer`, its
  sources in `results`, both handed to the model (`server_tools.py`
  `result_text`). Accounts are tried free first, then own node first
  (`routing.py`). Gemini chats already use the gateway's search loop.

## 2. Troy's calls (2026-10-09)

| # | Call | Taken |
|---|---|---|
| GS1 | Google's terms vs "beside Brave" | **Beside Brave, shaped:** a search account usable by any model; Google's answer passed through unmodified with its Search Suggestions, which Workbench shows; the account's settings say Google's terms bind the key owner |
| GS2 | Order | **Search first**; Gemini code execution is its own slice after |
| GS3 | The searching model | **The cheapest grounding model on the key** (a flash-lite, from Google's listing), changeable on the account |
| GS4 | Search Suggestions | **Carried to every door's extension block; Workbench renders them** on the Sources card; the settings say other apps do not |
| GS5 | Google's redirect links | **Resolved to the real address** (only Google's redirect is asked, for its `Location`; the page is never fetched); one that does not resolve keeps Google's link |
| GS6 | A Gemini chat asking for search | **Eugene's search, like every model** (no Gemini-native grounding path) |
| GS7 | Which account first | **The person sets the order**, on the Routing page as models are ordered there; unset, today's rule (free first, own machine first), shown as the order in effect |
| GS8 | Domain filters | **A `site:` hint, sources filtered, and Google's answer left out** (it may draw on filtered pages and cannot be edited) |
| GS9 | Location | **Named as ignored for now**; saying it in words to the searching model is a later slice |

## 3. The shape

**Tool driver** (`provider: google`, label "Google Search (Gemini API
key)"): `apiKey` (sealed, like Brave's), `searchModel` (unset: the first of
our preference list the key's listing has, shown as the value in effect),
`baseUrl` (unset: Google's). A search is one `generateContent` call:
the query as the user turn with a fixed instruction to search the web for
it and answer briefly, `tools: [{googleSearch: {}}]`. Back:

- `answer`: the candidate's text, verbatim (GS1), unless a domain filter is
  set (GS8);
- `results`: one per grounding chunk, `title` its title, `url` the
  resolved address (GS5), `snippet` the supported segments that cite it,
  joined; filtered by the request's domains (GS8);
- `searchSuggestions`: `searchEntryPoint.renderedContent`, verbatim;
- `ignored`: `userLocation` when given (GS9).

`billing: per_search`; no probes (each costs). Failures name their cause as
the other providers' do: a refused key, a 429 with Google's wait, a model
the key cannot use, a search Google ran but grounded nothing.

**Contract:** `WebSearchResponse.searchSuggestions` (HTML or null). The
gateway's doors carry it as `x_eugene_plexus.search_suggestions` (a list,
one per search that had any); the metrics row keeps none of it.

**Gateway:** `webSearchOrder` (config, string list of account names, each
`name` or `node:name`): listed accounts first in that order, then the rest
by today's rule. `GET /v1/admin/routing` gains `searchAccounts`, in the
order in effect, each with where its place came from.

**Console:** "Google Search (Gemini API key)" when adding a search account;
its page notes Google's terms (GS1, GS4). The Routing page gains
*Web search order*, reordered as model slots are, with *Reset to the
default order*.

**Workbench:** the Sources card renders each search's suggestions in a
sandboxed frame (no scripts, links open in a new tab).

## 4. Proof

A fixture of Google's `generateContent` with `groundingMetadata` and a
redirect host, through a tool driver, a gateway and the unchanged SDKs:
the answer and resolved sources reach the model, the suggestions reach
every door's extension, the domain filter drops the answer, the order set
on the gateway is the order searched. Then one live search with Troy's key
(a fraction of a cent, inside the free 5,000).
