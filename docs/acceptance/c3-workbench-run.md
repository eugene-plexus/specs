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
- **Many people at once**, Postgres, a phone, HTTPS, two machines.
- **A vision model live.** The live model takes no images, so its image
  check is the refusal.
