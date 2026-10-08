# Workbench: our first app

**Status: designed 2026-10-01, revised the same day on Troy's answers.
C1 is built the same day** ([record](../acceptance/c1-app-accounts-run.md):
42 of 42 on GitHub's Windows and Ubuntu runners, where the same run failed
14 checks before). §3.1 says where the build departed from §2-§3. **C2 is
built the same day**, designed in
[`sign-in-with-eugene.md`](sign-in-with-eugene.md) ([record](../acceptance/c2-sign-in-run.md)).
**C3 is built the same day**, designed in [`workbench-v1.md`](workbench-v1.md)
([record](../acceptance/c3-workbench-run.md)). **C4 is built 2026-10-02**
([design](c4-open-webui.md), [record](../acceptance/c4-open-webui-run.md)).
**C5a, network MCP tools, is built 2026-10-03**, designed in
[`workbench-mcp.md`](workbench-mcp.md)
([record](../acceptance/c5-mcp-run.md)). **C5b, owner-only local MCP tools,
is built and pinned 2026-10-03**
([record](../acceptance/c5-local-tools-run.md)). **C6, person-specific folder
tools, is built and pinned 2026-10-03** ([design](workbench-files.md),
[record](../acceptance/c6-folder-tools-run.md)). Written fresh from Troy's 2026-09-24 brief. The 2026-09-23
draft of this file was deleted on purpose, and nothing in it binds. This is
roadmap A6. It builds on the apps registry
([`apps-and-spokes.md`](apps-and-spokes.md), built 2026-09-23). Where this
document changes the registry, it says so.

**Its name is Workbench** (Troy, 2026-10-01): repo
`eugene-plexus/workbench`, catalogue id `workbench`, key
`app:workbench@<node>`. "Chat" undersold it: it is meant to grow into tool
calls on the person's machine, image, speech and video work, and use by a
whole small business. The name sets a tone that runs through its menus and
parts (§6).

## Calls taken (Troy, 2026-10-01)

1. **Version 1 is chat and web search.** Web search goes through P8's
   tool-driver, which runs in the hub. MCP servers and filesystem tools
   come later, each with its own design.
2. **Apps get an OS account of their own first** (C1, §2), before the app.
3. **Open WebUI goes into the registry, after the apps account** (C4, §7).
4. **No measurement before C1.** This is an old problem with known
   answers: the OS service manager runs each app in an account of its own.
   **The two log paths that would create become one:** a log ingress in
   Eugene that any tool can send to, ours or not (§3).
5. **Installs that cannot have an apps account:** Troy left this call to
   Claude. An app may install there only if it runs nothing the model
   chooses (§2).
6. **The app uses the same doors as everyone else.** That means the
   gateway's public endpoints, each for its own job.
7. **Sign-in comes from Eugene** (C2, §4), for two cases:
   - **The solo enthusiast** signs in with the Eugene passphrase. There is
     no second passphrase.
   - **A small business** has real user accounts, so a fired employee is
     revoked without touching anyone else.

   This replaces apps call #6 ("the app's own sign-in") for any app that
   uses it.
8. **The stack is built for what comes later** (§5): image, speech and
   video work through this app (Stable Diffusion- and ElevenLabs-style),
   and many people connected at once in a small business.

---

## The brief, in Troy's words

> [The chat app] should aim to eventually be full featured. Tool calls, web
> search, filesystem tools, etc. Main constraint: it can not have access to
> anything in Eugene that any other harness wouldn't have. It must
> communicate strictly by the same rules as any other chat app.

> "Chat app" and "read only file access" are not the future of local LLMs.
> Users want more and more tool calls, more autonomous action, more
> automation, etc. But they also want choice. Eugene and its tools and apps
> for users that want it, easily slide in your own MCP servers or chat app
> if you don't.

The playground stays as it is: a diagnostic with no tool execution
([`playground-diagnostic.md`](playground-diagnostic.md)). The app is a
separate, optional install.

**What the audience asks for** (the A6 row): a chat screen beginners stay
in. The bar is low. Several T1 commenters call llama-server's own web UI
enough, and one counter-signal (62 points) asks for "a simple built in
agent harness". The threads recorded no demand for multi-user accounts.
The small-business case is Troy's.

---

## 1. Why the account comes first

**Measured 2026-10-01 against agent `05d88f8`:** an app runs as the agent's
OS account. `apps.py` starts it with `child_environment()`, which strips
every hub credential from the environment, so the environment is not the
leak. Files and the keyring are:

| Install | The agent's account | What an app in that account can read |
| --- | --- | --- |
| Windows service (elevated) | LocalSystem | everything on the machine |
| Windows per-user (logon task) | the person | the prefix, which row 1 limits to the person, SYSTEM and Administrators |
| Linux system (row 2's default) | `eugene-plexus` | `node.yaml`, `agent.yaml`, the 0400 passphrase file |
| Linux `--user`, macOS | the person | the same, and the person's keychain |

The three rows of the key-exposure work each closed something else:

- **Row 1** keeps *other* accounts out. An app is not another account.
- **Row 2** moved Eugene off the person's account on Linux. That protects
  Eugene from harnesses the person runs, not from apps Eugene runs itself.
- **Row 3** made a worker's `node.yaml` worth that worker only. A
  beginner's install is one machine: the control root, the console and the
  gateway machine at once. There, the agent's account reaches the root
  token key's unlock (the keyring entry or the passphrase file), and that
  key is the install ([`per-node-token-keys.md`](per-node-token-keys.md) §2,
  last row).

So anything the model chooses that runs in an app's process can reach the
install. A file tool pointed at `node.yaml` is enough, and web search is a
way to send it out.

---

## 2. C1: an OS account for each app

**The goal:** a process in an app's account can read its own app
directory and its key file, reach the gateway, and send to the log ingress
(§3). It cannot open:

- `node.yaml` or `agent.yaml`;
- the passphrase file;
- the control root's data directory;
- the install's keyring entry;
- another app's directory.

**The shape: the OS service manager runs each app in an account of its
own.** Neither OS needs a password kept for it:

- **Windows service install:** one service per app,
  `EugenePlexusApp-<id>`, under its virtual account
  `NT SERVICE\EugenePlexusApp-<id>`. The agent runs as LocalSystem and may
  create, start and stop services. The service's program is our
  **launcher**, a small service host using `pywin32` (already the
  `[service]` extra).
- **Linux system install:** a template unit
  `eugene-plexus-app@<id>.service` with `DynamicUser=yes`, running the
  same launcher. `install.sh` (under `sudo`) installs the unit and one
  polkit rule. The rule lets `eugene-plexus` start, stop and query
  `eugene-plexus-app@*` and nothing else.

**What the launcher does,** inside the app's account and with none of the
hub's credentials:

- it starts the app's command;
- it forwards the app's stdout and stderr to the log ingress, tagged with
  the app's key;
- on Windows, it turns the service manager's stop into the graceful stop
  the supervisor uses today (the console break event, then escalation).

The service manager restarts an app that crashes, with its own back-off.
The agent asks it for status. A GPU app later (§8) still takes its
admission reservation from the agent before the agent asks the service
manager to start it.

**What stays the same:** the client key, the per-app environment, the
app's own port and origin, and no back doors. The app's directory and key
file are made readable by its own account and nobody else.

**Installs that cannot have an apps account** (Windows per-user, Linux
`--user`, macOS; Claude's call, delegated by Troy). Creating an account
needs administrator rights, and these installs have none:

- **Each catalogue entry declares `localActions`**: whether it runs
  anything the model chooses on the machine.
- **There, an app with `localActions: false` installs** and runs as the
  agent's account under today's supervisor. The only code running there
  is the app's own, which the operator chose to install. Its logs go
  through the same ingress.
- **An app with `localActions: true` is refused** there. The reason names
  the install that would allow it.
- **A custom entry that does not say is treated as `true`.**

App v1 declares `false`. Open WebUI declares `true` (§7).

**The failing check, first.** An app that tries to open each file in the
goal list. Today every open succeeds. After C1, each is refused, and the
same app still answers a chat request through the gateway with its key. It
runs:

- **Windows service install:** on a GitHub Windows runner, whose account is
  an administrator, as A4 used the macOS runners. Troy's box needs his word
  to run elevated.
- **Linux system install:** on an Ubuntu runner with passwordless `sudo`,
  and in WSL as `row2-system-install-acceptance.sh` does.

A sabotage pass follows the project's rules: restore from a copy, and open
with a baseline that passes.

---

## 3. One log path: an ingress any tool can send to

**What it fixes.** Moving apps out to the service manager would give
Eugene two ways to collect a child's output. Instead every app's output
reaches the same place, the Logs page (`GET /v1/logs`, built 2026-09-27).
And a third-party app gets the same path ours does.

**The standard, not our own format: OpenTelemetry's OTLP over HTTP**, at
`POST /v1/logs` on the app's own node's agent. That is OTLP's own logs
path, beside the existing `GET /v1/logs` read. So:

- **A tool that already exports OpenTelemetry** needs only an address and
  a key, given in OpenTelemetry's own environment variables.
- **A tool that only prints** is forwarded by the launcher.

**Who may send.** Any client key granted a `logs` scope, beside A5's model
and tool scopes:

- The registry grants it to its apps through `uses: [logs]`.
- An operator may grant it to any key, so a tool outside the registry can
  send too.
- The agent stamps every line with the key's name, so one sender cannot
  pass as another. Each key has a size and rate limit.
- Lines are masked on the way out, as today.

**The one exception, named:** the agent refuses client keys everywhere
today, by construction. This path accepts one, for writing only. That
mirrors the gateway, which accepts client keys on its OpenAI paths and
nowhere else. Reading logs stays operator-only.

So an app is given two addresses: the gateway, and its own node's
ingress.

### 3.1 C1 as built: where it departed

- **The launcher is standard library only, with no pywin32.** It is one
  file for both systems, copied to `<apps>/launcher/` and run with the app's
  own interpreter: an app's account must not need the agent's environment,
  which on Linux it cannot even see. On Windows it is a service through
  ctypes, and it gives the app a console so a stop can be a console break.
- **Linux: the agent asks a root helper.** The agent is unprivileged and
  its unit sets `NoNewPrivileges`, which rules out sudo, and polkit is not
  on every system. So it writes a request that a root path unit carries
  out, the in-app updater's shape. The helper takes start, stop, restart or
  clean, of one `eugene-plexus-app@` unit, for an id the registry could
  have issued.
- **Linux: one dynamic user per app, named by a hash.** A template unit's
  dynamic user is named after the template, so every app shared one uid
  until the helper wrote a drop-in per instance (`User=eapp-<hash>`;
  systemd takes 31 characters and an id may be 40).
- **Every app's key may send logs; there is no `uses: [logs]`.** The
  launcher forwards for every app, so every registry app's key has
  `writeLogs`. A key outside the registry gets it from the operator.
- **A record's own time is not used.** Lines are stamped when they arrive,
  as every line in the log is.
- **App interpreters live in `<apps>/pythons`, copied, not linked.** An
  app's account is granted those and never the agent's, and a grant on a
  venv's files touches nothing that shares their inode in uv's cache.
- **An app keeps running when the agent stops.** It is the service
  manager's, and the agent coming back finds it running and takes back the
  admin token it was started with.
- **A stop or removal the service manager refuses fails out loud.** The
  first Windows run's uninstall reported success while the service lived
  on.

---

## 4. C2: signing in with Eugene

**Built 2026-10-01.** The detailed design and what the build departed from
are [`sign-in-with-eugene.md`](sign-in-with-eugene.md) (§10); this section
is the outline it started from.

**The two cases, one mechanism.** Eugene becomes the sign-in provider for
apps, over **OpenID Connect** (the authorization code flow with PKCE). It
is issued by the control root, which already issues every session since
row 3.

- **Solo:** the operator signs in to the app with the Eugene passphrase.
  The app sends them to Eugene's sign-in page and gets them back signed in.
  There is no second passphrase.
- **Small business:** the root also holds **people's accounts**, each with
  its own password. The operator adds and revokes a person on the console.
  Revoking one person ends their sign-in everywhere and touches nobody
  else.

**Why OpenID Connect and not our own protocol: fairness.** Any app that
speaks it can sign in with Eugene the same way ours does. The operator
registers it as a client. The registry registers its own entries at
install. Open WebUI already accepts a generic OpenID Connect provider,
which C4 confirms against its pinned version.

**Accounts are not operators.** A person may use the apps the operator
gives them. They cannot open the console or change the install. The
operator's own account is the existing one, so a solo install has exactly
one account and nothing new to set up.

**Where it lives.** People's accounts go in the control root's replicated
log beside nodes and keys, so a standby keeps them. Passwords are stored
the way the passphrase is (Argon2id).

**Revocation, stated honestly.** Our app checks a person's standing every
time its short-lived tokens are refreshed, so a revoked person is out
within minutes. An app that keeps its own session after signing in ends a
revoked person's access only when that session expires.

**Not decided here** (C2's build decides, or Troy does):

- whether the gateway sees each person, for per-person limits and usage,
  or keeps seeing the app's one key;
- password reset for a person who forgets one.

---

## 5. C3: Workbench, version 1

**Built 2026-10-01**: the detailed design, its calls and where the build
departed are [`workbench-v1.md`](workbench-v1.md). Version 1 uses plain
words (its call 1), so the names in §6 wait for a second tool.

**What it is.** A browser app on its own port, served by its own process:

- a conversation list;
- streaming answers with Stop, Try again and editing a message;
- Markdown and code;
- reasoning shown collapsed;
- a model picker;
- attachments: images, PDFs and audio, which the gateway already carries
  (P2a);
- sampling settings;
- a **Search the web** switch.

That is roughly llama-server's own web UI, plus search and sign-in.

**How it reaches the hub: through the same doors as everyone else.**

- **Its key** is `app:workbench@<node>`, minted at install. Revoking it cuts
  the app off.
- **Models** come from `GET /v1/models`.
- **Chat** goes through `/v1/chat/completions`.
- **Web search** goes through P8, asked for in the request as any client
  asks. The key's tool scope decides. With no search account in the
  install, the switch is off and says why, naming *Backends → Add a search
  account*.
- **Later work uses the doors that already exist:** images (P4), speech
  (P3), transcription (P3b) and video (P5).

If the app needs something the public contract does not offer, that is a
gap in the contract, fixed there for every client (apps call #1).

**The stack, for what comes later:**

- **A Python server (FastAPI)**, as every Eugene process is:
  - It holds the key, so no browser ever sees it.
  - It knows who each person is, and keeps each person's conversations and
    files apart.
  - It streams to many browsers at once: many people in a small business,
    and several tabs each.
- **Storage behind one interface:**
  - SQLite by default, so a solo install needs nothing.
  - A Postgres option for a business that outgrows it, added when one
    does.
- **Media as files** in the app's data directory, referred to by id and
  streamed, never kept in the database. A long job (video) is a tracked
  job the browser can leave and return to, as P5's handles are.
- **A React and TypeScript front end, built to static files** and served
  by the app's server: the console's stack, with the Plexus tokens copied
  (no shared code across repos). React is where the editors image and
  audio work will need already exist: canvases, masks and waveforms.

**Model output is untrusted.** Search results and answers render as
Markdown with no raw HTML. The app's own origin already keeps a bad answer
away from the console's session; sanitizing keeps it away from the app's.

**One trap known in advance.** The registry installs an app from a GitHub
archive at a pinned commit, and an archive carries no gitignored build
output. That is how the console's wheel installed with no UI in it until
`ui` grew its `dist` branch. The app's built front end needs the same
treatment, and its acceptance run installs from the pinned archive, never
from a working tree.

**The checks:**

- Chrome drives the app against a real local model: sign in with the
  Eugene passphrase, a conversation, streaming, Stop, an attachment, a
  searched answer (through a fixture SearXNG, and the WSL one).
- **Two people, one app.** Each sees only their own conversations.
  Revoking one ends that person's sign-in, and the other keeps working.
- The gateway's records show only the app's key. Revoking the key stops
  the app, with a sentence saying so.
- The app talks to two addresses only, the gateway and its node's
  ingress, and its logs appear on the Logs page under its key's name.
- A searched turn on a key whose tool scope denies search is refused, and
  the reason is shown.

---

## 6. Names and faces

**Workshop names with plain words beside them** (Troy, 2026-10-01).
Workbench's menus and parts take names from a workshop, but a hint never
replaces the plain word:

- **Every workshop name carries its plain meaning** where a person first
  meets it, as a subtitle or a tooltip.
- **The console's copy rules still apply:** plain words, the glossary,
  and the Grade 6 gate (S8).
- **Eugene's own terms keep Eugene's words:** model, key and gateway. So a
  person moving between the console and Workbench meets one vocabulary for
  the hub.

**Proposed vocabulary, Troy's to change:**

| Workbench says | It means | Where |
| --- | --- | --- |
| **Toolbox** | the tools a model may use: web search now, MCP servers and file tools later | a menu, and a switch in each chat |
| **Jigs** | saved setups (a model, its settings and its instructions), reused so a job comes out the same every time | a menu |
| **Work orders** | long jobs that run without anyone watching: a video, a batch of images | a list with progress |
| **Bins** | the files a person brought in, and the media Workbench made | a menu |
| **Crew** | the people who may use this Workbench, a business's accounts (C2) | the owner's menu |
| **The shop** | the owner's settings: the crew, and who may use which models and tools | the operator's menu only |
| **Chats** | conversations, kept plain because a conversation is not a job | the side list |

**The same names inside the code, where they fit,** so a contributor reading
the source finds the same map: `toolbox/`, `jigs/`, `work_orders/`,
`bins/`, `crew/`. Two parts have no menu of their own:

- **Dispatch:** sends each answer to every browser watching it.
- **Foreman:** starts, watches and resumes work orders.

**Eugene's logo and mascot make it friendlier.** They are copied from the
website, byte for byte, the way `gpu_probe.py` is copied between the agent
and the library:

- **The logo** marks the header and the browser tab. The tab should differ
  from the console's, which uses `eugene-icon.svg`, so the two tabs can be
  told apart; `eugene-face.svg` is the candidate.
- **The four mascot poses,** at the moments the website uses them:
  - *welcome* (`eugene-welcome.svg`): sign-in and the first open;
  - *guide*: an empty Workbench and its first steps, such as no chats
    yet or no search account;
  - *working*: a work order running, or a model loading;
  - *curious*: nothing found, a page that is gone, or a failed answer.
    It sits beside the sentence naming the cause, and never stands in for
    it.

**Decoration, never information.** A pose carries no meaning a screen
reader would miss (`alt=""`, as on the website), stands still, and stays
off the chat itself. The bench is for the work. The one exception is §6.1.
The colours are the console's Plexus tokens, whose apricot is the mascot's
shirt.

### 6.1 The working animation (Troy, 2026-10-01; a late slice)

Every major LLM app shows that the model is working. Claude's is an
animated logo with funny words. **Workbench's is Eugene at the bench:** a
series of short loops in which he measures a board, checks it with a
square, hammers a nail, and so on. A workshop phrase sits beside each:

- *Measuring twice…*
- *Squaring up…*
- *Hammering it out…*
- *Sawing…*
- *Sanding the edges…*
- *Checking the level…*
- *Clamping…*

**It is made with an LLM, as Eugene's SVG was** (Troy, 2026-10-01: *"if
it's not acceptable in an AI platform, we shouldn't be building a
platform"*). It is a late slice. The four still poses carry Workbench
until it arrives.

**So the format is the one an LLM writes well: animated SVG** (call 4,
taken). It is plain text, needs no player library, and Eugene already
exists in it. Lottie was the animator's format, and its JSON of keyframe
curves is the wrong thing to ask a language model for.

**The brief, written to be handed to the model:**

- **Start from Eugene's existing figure** (`website/public/mascots/`,
  about 14 KB each: 8 groups, 27 paths). Ask for it to be regrouped into
  named `<g>` parts, then add the bench and the tool. The style stays his
  because the drawing is his.
- **One file per scene,** self-contained: an inline `<style>` with CSS
  `@keyframes`, no `<script>`, no external reference, no raster image.
- **Animate only `transform` and `opacity`, on named groups,** with
  `transform-box: fill-box` and an explicit `transform-origin`. Without
  those two, SVG rotates a part about the drawing's corner, which is the
  mistake models most often make with an arm and a hammer.
- **Each loop** is 2-4 seconds, and seamless: the `0%` and `100%`
  keyframes are identical.
- **The file is its own still.** It carries
  `@media (prefers-reduced-motion: reduce)` turning its animation off,
  and its first frame is a good pose.
- **A transparent background,** legible from 48 to 160 px, on both the
  dark and the light theme.
- **About the poses' size,** and under 32 KB.

**A gate makes the model's output trustworthy, as everywhere else here.**
A test in Workbench reads every animation file as text. It fails on:

- a `<script>` or an external reference;
- a missing reduced-motion rule;
- `0%` and `100%` keyframes that differ;
- a file over the budget.

Then a browser check renders each scene at both themes and both sizes.
Adding a scene is a new file the gate already covers.

**The rights are the existing SVGs' rights.** It ships the way Eugene's
mascot already does, under the repo's Apache-2.0 licence.

**Where it runs:**

- **On a turn,** from the moment it is sent until the first token
  arrives.
- **On a work order,** for as long as it runs.
- **Not on a stream that is already flowing.** By then the words arriving
  are the sign of work.
- **Never for an error.** A failure gets the still *curious* pose and the
  sentence naming its cause.

**The joke never stands in for the state:**

- **The real progress shows beside it, in plain words,** wherever there is
  some: a model loading, a long prompt being read (the progress built
  2026-09-27), or a work order's percentage.
- **A screen reader hears the plain state,** not the phrase.
- **With reduced motion requested** (S9), the loop is replaced by the still
  *working* pose. The phrase stays.

**Calls taken (Troy, 2026-10-07):**

1. **One scene first, then the rest.** *Measuring twice…* is drawn, gated and
   wired first; the other six follow once Troy has approved its style.
2. **It runs whenever the plain progress line shows**, not only until the
   first token: a search running, the model reading what it found, reasoning
   folded away. **It stops while the person is asked to approve tool calls**,
   since that is waiting on them, not work.
3. **A long wait moves to the next scene every 12 seconds** (about three
   loops), starting from a random one.
4. **It appears only after 0.6 seconds.** The plain line shows at once, so a
   fast answer never flashes Eugene.

**What building found (2026-10-07):**

- **The gate is a test of its own.** `web/src/sceneGate.ts` reads each file,
  and `web/src/scenes.test.ts` runs it over `web/public/scenes/` and over a
  good file broken 32 ways, one rule each. Beyond the four rules above it
  holds the brief: no SMIL (`<animate>` ignores the reduced-motion rule), one
  animation per named `<g>` with no `transform` attribute (the animation would
  replace it), `transform-box: fill-box` and a `transform-origin`, one loop
  length per file of 2-4 s, no delay, `infinite`, and only `transform` and
  `opacity` in keyframes. The reduced-motion rule must say
  `animation: none !important`: in a `*` rule without it, an id rule outranks
  it and keeps running.
- **A scene file is its file plus a line in `web/src/lib/scenes.ts`** (file
  and phrase); the gate fails on either alone.
- **Scenes get their own policy.** The page's `style-src 'self'` would block a
  scene's inline `<style>` in a browser that applies an image's own policy.
  Chrome does not (probed), and no other browser was at hand, so
  `/scenes/*.svg` is served with `default-src 'none'; style-src
  'unsafe-inline'` and nothing else gets it.
- **Chrome does not pass an emulated reduced-motion setting into an image's
  document.** The file's own rule is proved by opening the scene as a
  document under reduced motion; the page proves the still pose. Whether the
  real OS setting reaches an image was not tested.
- **The face is the website's, byte for byte**, spliced from
  `eugene-working.svg` into a `#head` group; the laptop becomes a bench, a
  board, a tape and a pencil. 15.5 KB.
- **Checked:** the browser check (`tests/test_scenes_browser.py`) passes;
  `scripts/check-scenes-sabotage.py` caught 20 of 20 (16 in the unit tests,
  4 in Chrome), restoring exact bytes. Its first run stopped on a mutation
  that no longer compiled, which proves nothing; that one now compiles.

---

## 7. C4: Open WebUI in the registry

Troy rejected wrapping Open WebUI *instead of* building our own (memory,
2026-09-23). Offering it *beside* ours is a different thing: it is the
"choice" half of the brief, and the first app in the registry we did not
write.

**Why it waits for C1:** Open WebUI runs Python tools and functions,
installed by its admin, in its own server process. So it declares
`localActions: true`. In the agent's account, on the Windows service
install, that would be code running as LocalSystem.

**What the entry has to settle at the build:**

- **It does not start the way the registry expects.** The manifest runs
  `python -m <entry>` and passes `EUGENE_PLEXUS_APP_*` variables. Open
  WebUI starts with `open-webui serve`. It reads its own variables for its
  data directory, its backend URL and its key, and wants the key as a
  variable, not a file. So the manifest grows a start command and an
  environment mapping. That is a registry change, made once and reused by
  later third-party entries.
- **Sign-in** through C2's OpenID Connect, and log export through C1's
  ingress where its OpenTelemetry support reaches. Otherwise the launcher
  forwards what it prints.
- **Its supported Python version**, which the entry pins.
- **Its licence.** It has carried a branding clause since 2025. We install
  it unmodified from PyPI, and the entry's text is read against the pinned
  version's licence before it ships.

---

## 8. Later, each with its own design

These run model-chosen actions in the app's process, so each needs C1:

- **MCP servers the person adds.** They are processes the app starts, in
  the app's account.
- **Filesystem tools.** Built as C6 on 2026-10-03: the owner assigns
  existing host folders to named people, read-only by default, with an
  explicit write option and approval for every call. The administrator
  provisions Workbench's OS access ([design](workbench-files.md)).
- **Local image, speech and video models.** A GPU app, admitted by the
  agent's ledger (apps §8 reserved `resources: gpu` for this).

Not a model-chosen action, but late too: **the working animation**
(§6.1), made with an LLM against the gate there.

---

## 9. Order

1. **C1, an account per app,** with the launcher and the log ingress (§2,
   §3). **Built 2026-10-01.**
2. **C2, signing in with Eugene** (§4). **Built 2026-10-01.**
3. **C3, Workbench's version 1,** in `eugene-plexus/workbench`. **Built
   2026-10-01.**
4. **C4, Open WebUI.** It needs C1, and C2 for sign-in. **Built
   2026-10-02** ([`c4-open-webui.md`](c4-open-webui.md),
   [record](../acceptance/c4-open-webui-run.md)).
5. **C5, MCP servers** ([design](workbench-mcp.md)): **C5a and C5b built and
   pinned 2026-10-03**, network connections and owner-only local processes
   under C1, with approval for each call. **C6 is built and pinned
   2026-10-03**, folder grants and built-in filesystem tools, with
   person-specific access ([design](workbench-files.md)). Local
   media models also need their own design.
6. **The working animation** (§6.1): the gate first, then the scenes. The
   still poses stand in until then.

Each slice ends the project's way: every specs CI script run locally before
an installer pin, a sabotage pass, and both installers re-pinned.

---

## 10. Calls for Troy

| # | The call | Recommendation | Counter-argument |
| --- | --- | --- | --- |
| 1 | ~~The app's name~~ | **Taken 2026-10-01: Workbench**, with workshop names in its menus and parts (§6) | — |
| 2 | ~~Workbench's vocabulary~~ | **Taken 2026-10-01 for version 1: plain words** (*Tools*, not *Toolbox*). The §6 table starts when there is more than one tool ([`workbench-v1.md`](workbench-v1.md) §9) | Each workshop name is one more word a beginner must learn |
| 3 | ~~What C2 builds first~~ | **Taken 2026-10-01: both cases in one slice.** The protocol is the same, and per-person revocation is the reason the business case exists | The solo case alone ships sooner and is the whole of today's audience |
| 4 | ~~The animation's format~~ | **Taken 2026-10-01: animated SVG, made with an LLM** against a text gate (§6.1) | — |
