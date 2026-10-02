# C3 acceptance: Workbench, version 1

**2026-10-01.** Design: [`../design/workbench-v1.md`](../design/workbench-v1.md).
The repo is new: [`eugene-plexus/workbench`](https://github.com/eugene-plexus/workbench).
Installed from `dist` `736e1ce`, which is `main` `ac56025` plus the built
page; `main` is at `718c126`, which adds only tests and the README. Agent `409bd01` adds
the catalogue entry. Gateway `a8fbc6c` carries the contract change, specs
`dcb0a5d`.

| Run | Result |
| --- | --- |
| `scripts/c3-workbench-acceptance.py --browser`, with real processes, Workbench installed from the agent's catalogue at its pinned archive, and the system Chrome | **36 of 36** |
| The same with `--engine --gguf --searxng`: a real `llama-server` (b11322, CPU build) with Qwen3-0.6B (Q4_K_M), and the SearXNG in WSL | **34 of 34** |
| `scripts/c3-sabotage.py` across Workbench, the gateway and the agent | **46 of 46 caught**, after two passes; the escapes are below |
| Workbench's own suites | 52 Python tests (Windows and Ubuntu in its CI), 28 page tests |
| Every script specs CI runs, locally, before the pin, in a venv shaped like CI's | **25 of 25** |
| specs CI on the pin (`643062d`), C3 included, on GitHub's Ubuntu and Windows runners | **green**; A4 failed once on macos-26 and passed on the re-run (below) |
| After the live install found the console loop (below): the harness with a second machine as the console, installing through its hop, with Chrome | **37 of 37**; before the fix it stops at check 4 |
| `scripts/c3-sabotage.py` with the fix's 14 sabotages | **60 of 60 caught** |

## Before: the failing check

The same run against agent `8da2fb4`, the pin of the day, stops at check
2. The agent's catalogue was empty, so there was no Workbench to install.
Without the gateway's change, check 9 fails as well: an older gateway does
not say whether a search can run, so Workbench offers the switch and only
learns from the refusal.

## What the run does

The harness onboards one control root and one enrolled agent through the
API. As on a real install, the agent supervises:

- a gateway;
- an inference-driver;
- a SearXNG search account.

A fixture plays three parts:

- the engine, which calls tools;
- SearXNG;
- a page that counts any fetch made of it.

Workbench is installed through `POST /v1/apps/workbench/install`. That
call:

- mints Workbench's key;
- registers it to sign people in with Eugene;
- builds its environment with uv from the GitHub archive at the `dist`
  commit;
- starts it.

Everything after that is done the way a person's browser does it, against
Eugene's real sign-in page.

## After

- **The install** (checks 2-6) comes from the catalogue, at an archive
  pinned to its own commit:
  - the manifest says Workbench signs people in, has settings, and runs
    nothing a model chooses;
  - it runs, and its page is the built front end;
  - its key is `app:workbench@c3-node`, and it has a sign-in client.
- **Signing in** (7-8). The owner signs in on Eugene's page with the
  passphrase, comes back signed in, and Workbench knows them as the owner.
- **Search, before and after an account exists** (9-10). With the search
  account declared but not set up, the switch is off in the gateway's own
  words: *the install's search account (searx) is not set up yet*. Once it
  is set up, the switch is on.
- **Chats** (11-15):
  - an answer streams;
  - an image reaches the model as an image;
  - a searched answer runs on the search account and keeps its sources;
  - Stop keeps what had arrived;
  - an answer with no tab watching finishes and is kept.
- **The key everyone shares** (16):
  - the gateway's records show Workbench's requests under the app's key
    and no other;
  - once the key is revoked, the next answer says *Eugene refused the key
    this Workbench uses* and what the owner can do (26).
- **A session needs both halves** (17). The cookie alone is a 401, and a
  call carrying another origin is a 403.
- **Two people** (18-23):
  - Ada and Bo, added in Eugene, sign in with their own names and
    passwords;
  - each sees only their own chats;
  - with `ownerReadsChats` turned on from the console's app page, through
    the agent's admin-token path, the owner reads Ada's chat read-only,
    cannot post in it, and Ada is told;
  - turned back off, the owner cannot read it.
  - Ada, turned off in Eugene, is signed out at her next refresh with the
    sentence saying why, and Bo keeps working. The run stands in for the
    ten minutes by marking her session due.
- **A key that may not search** (24). With the app's key limited to no
  tools, the switch is off with *this key's tool scope does not include
  web_search*. A searched turn is refused in the gateway's words.
- **Logs** (25). Workbench's own line, *Ada signed in*, is on the agent's
  Logs page.

**In Chrome** (B1-B10):

- signing in on Eugene's page;
- a message sent with Enter;
- **an image an answer names, shown as a link and never fetched**: the
  fixture's page counted 0 fetches (B9);
- an attached image, shown back from a `blob:` address;
- a searched answer with its sources;
- Stop;
- an answer whose tab was closed mid-way, whole when the chat was opened
  again;
- signing out.

There was no Content Security Policy refusal, page error or server error
in any tab.

**Live** (`--engine --gguf --searxng`), with the same checks against a
real model:

- **11:** the model answers.
- **12:** an image sent to a model that cannot see is refused in the
  gateway's words: *No ready backend serving this model confirms image
  input*.
- **13:** the search runs on the WSL SearXNG. The answer cites
  `eugeneplexus.com/architecture/`, `eugeneplexus.com`, the alpha-testers
  thread and an unrelated page.
- **14:** a long story is stopped mid-way.
- **15:** an answer with no tab finishes.
- **B5:** Chrome shows the answer's sources under *Sources (1 search)*.

## Found by the run, fixed before it passed

**In Workbench, found by Chrome:**

- **Toggling search dropped the answer just received.** The reply to the
  switch's save was merged into a copy of the chat taken before the answer
  arrived. Every local change now applies to the chat as it is.
- **The switch and the model picker waited for the server** before they
  moved. They change at once now, and a refusal puts them back.
- **The view stopped following an answer** once an image above it loaded
  late. It follows any growth now, and stops only when the reader scrolls
  up.
- **The chat list's "running" dot outlived the answer.** The list now
  refreshes when an answer ends.

**In Workbench, found writing the live check:**

- **A searched answer that cited nothing looked unsearched.** It now says
  how many searches ran and that it links none of the pages found.
- **Every request to the gateway was a log line.** httpx's request logging
  is off, so the Logs page holds Workbench's own lines.

**In packaging:**

- **`git archive` stamped `main`'s commit into `_build.py` on `dist`.** A
  follow-up commit put the placeholder back, so an archive of `dist` names
  its own commit, as the first `dist` did.

**In the harness:**

- the fixture's `Request` was a local import, which postponed annotations
  read as a query parameter, so every answer was a 422;
- the agent ran without its log file, so the Logs page had nothing;
- Eugene's page asks for a name once people exist, and the owner's is
  `operator`;
- the image fixture answered every turn of a chat that once had an image.

## The sabotage pass, and what it found

**First pass**, 46 sabotages:

- **One escape, a weak check.** Reusing a sign-in was refused anyway, by
  Eugene's single-use code and by the binding cookie already being gone.
  The test now re-presents the binding and requires Workbench to refuse
  *before* Eugene is asked.
- **One hang, which the runner counted as a crash.** A refresh that kept a
  revoked session left a test's event stream open forever. That test is
  bounded now, and a run that times out counts as caught.

**Second pass**, 44 of 46, with two missing checks:

- with `ownerReadsChats` on, nothing asked whether another *member* could
  open a person's chat;
- a streamed piece the page already had was tested only as the last one,
  so cutting off what followed it went unseen.

Both are tests now, and both sabotages are caught (46 of 46).

## Found in CI, not in C3

A4's macOS run failed once on macos-26 at its check 69, and the re-run
passed on all three Macs. The cause was a race in A4's harness:

- it waited until the gateway *listed* the llama.cpp model;
- a listed model can still be loading, and the gateway learns it is ready
  at its next routing refresh;
- so the completion 20 ms after the agent said *ready* got the gateway's
  honest 503, *still coming up*.

The harness now waits until the gateway reports a ready backend
(`ready_backends`) before each completion.

## Found on the live install, after the pin

**Installing Workbench from another machine's console signed the
operator out, every time** (Troy, 2026-10-01, the NAS console installing
on `Amish_Station`).

What happened:

1. The console reaches another machine with a five-minute token
   addressed to that machine alone (per-node token keys, D7).
2. The install there needs two things only the root can do: the app's
   key and its sign-in registration. It sent the token it had been
   handed on to the root. That is a bearer forwarded past its audience,
   which D7 forbids.
3. The root refused it: *the token is addressed to ['node:c3-node'], not
   to 'control'*. The 401 came back through both proxies to a browser
   that reads any 401 as its session ending.

The run above never went this way. It installed on the enrolled agent
directly, with a session made there, and that session is addressed to
the root as well.

**Before the fix** (agent `409bd01`, control `b9f55d7`): the harness now
has a second machine that is only a console, and installs through its
`node:` hop. It stops at check 4 with exactly that 401.

**The fix** (contract `a76f7ae`; design: per-node-token-keys D5 and D7):

- **The worker acts for the operator.** It sends its own `agent` token,
  with the operator's token beside it as the subject. A session already
  addressed to the root still goes unchanged.
- **The root takes that pair on four operations only**: making and
  revoking an app's key, and registering and removing its sign-in. Each
  is only for names `app:<id>@<that node>`.
- **A refusal at the root is a 502 from the worker**, naming the root's
  reason, so it can no longer sign anyone out. The worker's own calls
  keep the root's 401, because admission says "revoked" that way.

**After:**

- The harness runs every check through the console where the console is
  what a person would use: the install, the settings switch, and a new
  check 27, uninstalling from the console. **37 of 37**, with Chrome.
  The two agents advertise this host's routable address and bind every
  interface, because a console will not hop to a loopback address.
- New tests: 10 at the root (`test_acting_node.py`) and 4 at the agent
  (`test_acting_for_operator.py`).
- `c3-sabotage.py` gains 14 sabotages, including both over-corrections:
  - every caller's token sent as a subject, a session addressed to the
    root included;
  - every root 401 turned into a 502, a revoked client key's included.

  **60 of 60 caught**, on the first pass.

Pinned: agent `5c456fe`, control `28ea3e3`.

**On the live install, both have to update.** With only the agent
updated, the install fails with a 502 that names the root's refusal, and
no longer signs anyone out. It works once the root is updated too.

## The first run by a person

**2026-10-01, Troy, on the live two-machine install.** Every run before
this was a harness, a unit test or a scripted Chrome.

1. He updated both machines to the fix's pins: the NAS container (control
   root and console) and `Amish_Station` (the GPU worker).
2. He set up a Brave search account.
3. From the NAS console, he installed Workbench on `Amish_Station`.
4. He asked a Qwen model about Eugene Plexus. It reasoned, ran a web
   search, read the project's website, and answered correctly.

That covers, in one sitting, three things no person had done before:

- installing from one machine's console onto another;
- signing in with Eugene;
- a search on the install's search account, behind a chat answer.

This is a report, not a capture: nothing recorded which account served
the search or the exact model.

**Captured afterwards (the same evening).** Troy exported the chat from
Workbench's own API. A plain browser visit to that API is refused, because
every call also needs the request secret (W3), so the export ran from the
signed-in tab's console. Workbench has no export button.

- **Model:** `Huihui-Qwen3.8-27B-abliterated-Q6_K_L` on llama-server, on
  the 5090. **Search account:** Brave.
- **Three questions, three replies:** 21 s with 3 searches, 46 s with 2,
  39 s with 1. Every source the searches returned was this project's own:
  eugeneplexus.com and its GitHub repositories.
- It found three defects, all filed:
  - [workbench #1](https://github.com/eugene-plexus/workbench/issues/1):
    two of the three replies hold two complete answers. Text written
    before a search is stored, shown and sent back as part of the answer.
  - [gateway #4](https://github.com/eugene-plexus/gateway/issues/4): the
    chat door forces a search on turn 0 (`tool_choice: required`), and
    llama-server does not enforce it. The last reply reasoned "No tools
    needed", answered, then searched. Design §3 says the caller gets only
    the final answer; the chat door returns every turn's text.
  - [tool-driver #3](https://github.com/eugene-plexus/tool-driver/issues/3):
    two searches in one turn sent the second to Brave straight after the
    first, and the free plan refused it with 429. Nothing paces requests
    or retries. The model said the search failed, as the gateway told it
    to.

## What this does not show

- **Workbench in an account of its own.** These runs are not a service
  install, so Workbench ran in the agent's account. It declares
  `localActions: false`, so it installs there. C1's runners prove the
  account; nothing ran Workbench in one.
- **Ten real minutes.** The run marks a session due rather than waiting
  for Eugene's ID token to expire.
- **Open WebUI beside it.** That a cookie alone opens nothing is checked.
  A second app on the same host actually receiving Workbench's cookie is
  C4's to show.
- **Many people at once**, Postgres, a phone, HTTPS. Two machines: only by
  hand, in the run above. The harness puts both agents on one host.
- **A vision model live.** The live model takes no images, so its image
  check is the refusal.
