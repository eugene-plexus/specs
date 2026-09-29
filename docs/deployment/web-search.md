# Web search for local models

Codex's live search, Claude Code's WebSearch and any chat app that sends
`web_search_options` ask the *provider* to search the web. A local model has
no provider behind it, so before P8 those searches were lost: Codex quietly
went without, and Claude Code's WebSearch failed. With a **search account**,
Eugene runs the search itself and hands the results to the model, which then
answers with sources.

## Add a search account

In the console: **Backends → Add a search account**. Choose one:

| Provider | What it costs | What you give it |
| --- | --- | --- |
| **SearXNG** | Free. It runs on your own computer or server and asks other engines for you. | Its address, e.g. `http://192.168.1.20:8888` |
| **Brave Search** | Paid; Brave counts every search against your plan. | Your API key from api-dashboard.search.brave.com |

The page creates the account, saves its settings and runs one real test
search before it says web search is on. If the test fails, it says what to
change.

With both, Eugene tries the free account first and uses the paid one only when
the free one could not answer.

### SearXNG must allow JSON output

A SearXNG instance answers requests for JSON with **403 Forbidden** unless its
`settings.yml` allows it. Add `json` to `search.formats`:

```yaml
search:
  formats:
    - html
    - json
```

Restart SearXNG, then press **Try again** on the page. (Public SearXNG
instances almost never allow JSON; run your own. The official container is
`searxng/searxng`.)

## Using it

- **Codex:** set `web_search = "live"` in its `config.toml`. Codex's default
  (`cached`) sends `external_web_access: false`, which asks for no live
  search, so Eugene runs none and says so in the `x-eugene-plexus-web-search`
  response header.
- **Claude Code:** WebSearch works as it is.
- **Chat apps:** send `web_search_options` (the playground's *Search the web*
  switch does).

The model must be able to call tools (llama.cpp with a tool-calling chat
template, most current instruct models). A model that cannot is refused with
a message saying so. A cloud model that searches by itself is sent the request
as it is, and Eugene runs no search of its own for it.

Up to five searches run for one request unless the app sets its own limit
(`max_tool_calls` in Codex, `max_uses` in Claude Code). Change the
default under **Gateway → Settings → Web searches per request**.

## Images from a local model

An app on OpenAI's Responses API can offer the model an `image_generation`
tool. With a local model, Eugene runs it: the model asks for an image, Eugene
has it made by one of the install's image models (a provider account that
makes images, such as OpenAI or OpenRouter, under **Backends**) and hands the
image to the app. The model is told the image was made; it never sees it.

- With one image model, it is used. With several, set **Gateway → Settings →
  Image model for tools**, or have the app name one as the tool's `model`.
- A key can be kept from making images the same way as from searching.
- Every image is billed by the provider that makes it. Images and searches
  share one limit per request (*Web searches and images per request*).
- Codex does not send this tool; an app built on the OpenAI Agents SDK or
  the Responses API directly may.

## Privacy

The words searched for go to the internet, even through a SearXNG on your own
network, which forwards them to public engines. So:

- A client key marked **local-only** never has a search run for it.
- Any key can be kept from searching: open its permissions and turn off
  *Let apps using this key search the web*.
- No query is kept. The gateway's metrics record that a search ran, on which
  account, how long it took and how many results it gave -- never what was
  searched for.
