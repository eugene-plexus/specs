# The chat app: our first spoke

**Status: designed 2026-10-01, nothing built.** Written fresh from Troy's
2026-09-24 brief. The 2026-09-23 draft of this file was deleted on purpose,
and nothing in it binds. This is roadmap A6. It builds on the apps registry
([`apps-and-spokes.md`](apps-and-spokes.md), built 2026-09-23), which is
unchanged except where §3 says so.

Three calls were taken on 2026-10-01 (Troy):

1. **Version 1 is chat and web search.** Web search goes through P8's
   tool-driver, which runs in the hub. MCP servers and filesystem tools
   come later, each with its own design.
2. **Apps get an OS account of their own first, before chat v1** (§2).
3. **Open WebUI goes into the registry, after the apps account** (§5).

The calls still open are in §7. Each has a recommendation, and none is
taken.

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
([`playground-diagnostic.md`](playground-diagnostic.md)). The chat app is a
separate, optional install.

**What the audience asks for** (the A6 row): a chat screen beginners stay
in. The bar is low. Several T1 commenters call llama-server's own web UI
enough, and the 2026-09-11 call was "adequate". One counter-signal (62
points) asks for "a simple built in agent harness". The brief aims past
both, one slice at a time.

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
way to send it out. Chat v1 runs nothing the model chooses, so it would be
safe without the account. Troy's call puts the account first anyway: every
later slice needs it, and Open WebUI needs it on day one (§5).

---

## 2. C1: an OS account for apps

**The goal:** a process in an app's account can read its own
`apps/<id>/` directory and its key file, and reach the gateway over HTTP.
It cannot open:

- `node.yaml` or `agent.yaml`;
- the passphrase file;
- the control root's data directory;
- the install's keyring entry;
- another app's directory.

**Where it can exist.** A second account needs administrator rights at
install time:

- **The Windows service install:** yes. The installer is elevated, and the
  agent runs as LocalSystem.
- **The Linux system install:** yes. The installer runs with `sudo`.
- **Windows per-user, Linux `--user` and macOS:** no. Nothing there may
  create an account, and macOS cannot yet run Eugene under its own account
  either (A4's record). §7 call 2 says what an app may do on those
  installs.

**Two shapes, and C1 starts by measuring them** (§7 call 1):

- **The OS service manager runs each app in an account of its own.**
  Windows creates a virtual service account per service
  (`NT SERVICE\<name>`), and systemd gives a template unit `DynamicUser=`.
  Neither has a password to keep. Apps are also kept apart from each
  other. The cost is that supervision moves out of the agent: start, stop,
  back-off and log capture become requests to the service manager, where
  today they are the supervisor's own (Job Object, graceful stop with
  escalation, piped stdout).
- **The agent starts every app in one apps account.** On Windows,
  LocalSystem can log a local account on without a password (S4U) and
  create the process with that token. On Linux, the installer would grant
  the agent one narrow rule to start processes as `eugene-plexus-apps`.
  Supervision is unchanged. Apps can read each other's files unless each
  directory is locked to its own app, which one shared account cannot do.

**What stays the same:** the client key, the per-app environment, the
app's own port and origin, and no back doors. The key file and the app's
directory are made readable by the app's account and nobody else. The
registry's code paths are the same for every account.

**The failing check, first.** An app that tries to open each file in the
goal list. Today every open succeeds, on both installs that can have the
account. After C1, each is refused, and the same app still answers a chat
request through the gateway with its key. It runs:

- **Windows service install:** on a GitHub Windows runner, whose account is
  an administrator, as A4 used the macOS runners. Troy's box needs his word
  to run elevated.
- **Linux system install:** on an Ubuntu runner with passwordless `sudo`,
  and in WSL as `row2-system-install-acceptance.sh` does.

A sabotage pass follows the project's rules: restore from a copy, and open
with a baseline that passes.

---

## 3. C2: chat v1

**What it is.** A browser chat on the app's own port, served by its own
Python process:

- a conversation list;
- streaming answers with Stop, Try again and editing a message;
- Markdown and code;
- reasoning shown collapsed;
- a model picker;
- attachments (images, PDFs and audio, which the gateway already carries,
  P2a);
- sampling settings;
- a **Search the web** switch.

That is roughly llama-server's own web UI, plus search. Conversations live
in SQLite in the app's data directory.

**How it reaches the hub: only as any client does.**

- **Its key** is `app:chat@<node>`, minted at install as the registry does
  today. Revoking it cuts the app off.
- **Models** come from `GET /v1/models` on the gateway.
- **Answers** come from the gateway's OpenAI-compatible door (§7 call 4).
- **Web search** goes through P8, asked for in the request the way any
  client asks. The key's tool scope decides, as for any key. With no search
  account in the install, the switch is off and says why, naming *Backends
  → Add a search account*.

If chat v1 needs something the public contract does not offer, that is a
gap in the contract, fixed there for every client (apps call #1 in
`apps-and-spokes.md`).

**Its own sign-in** (apps call #6, already taken). How it is set is §7
call 5.

**Model output is untrusted.** Search results and answers render as
Markdown with no raw HTML. The app's own origin already keeps a bad answer
away from the console's session; sanitizing keeps it away from the app's.

**One trap known in advance.** The registry installs an app from a GitHub
archive at a pinned commit, and an archive carries no gitignored build
output. That is how the console's wheel installed with no UI in it until
`ui` grew its `dist` branch. Chat's built front end needs the same
treatment, and its acceptance run installs from the pinned archive, never
from a working tree.

**The checks:**

- Chrome drives the app against a real local model: a conversation,
  streaming, Stop, an attachment, a searched answer (through a fixture
  SearXNG, and the WSL one).
- The gateway's records show only `app:chat@<node>`.
- Revoking the key stops the app, with a sentence saying so.
- The app is given exactly one URL, the gateway's, and talks to nothing
  else.
- A turn with search, on a key whose tool scope denies it, is refused with
  the reason shown.

---

## 4. Later, each with its own design

Both run model-chosen actions in the app's process, so both need C1:

- **MCP servers the person adds.** They are processes the app starts, in
  the app's account.
- **Filesystem tools.** These need one more decision first: which folders
  an app may reach, and how a person grants it.

Neither is designed here.

---

## 5. C3: Open WebUI in the registry

Troy rejected wrapping Open WebUI *instead of* building our own (memory,
2026-09-23). Offering it *beside* ours is a different thing: it is the
"choice" half of the brief, and the first app in the registry we did not
write.

**Why it waits for C1:** Open WebUI runs Python tools and functions,
installed by its admin, in its own server process. In the agent's account,
on the Windows service install, that is code as LocalSystem.

**What the entry has to settle, measured at the build:**

- **It does not start the way the registry expects.** The manifest runs
  `python -m <entry>` and passes `EUGENE_PLEXUS_APP_*` variables. Open
  WebUI starts with `open-webui serve`. It reads its own variables for its
  data directory, its backend URL and its key, and wants the key as a
  variable, not a file. So a catalogue entry may need the manifest to grow
  a start command and an environment mapping. That is a registry change,
  made once and reused by later third-party entries.
- **Its supported Python version**, which the entry pins.
- **Its licence.** It has carried a branding clause since 2025. We install
  it unmodified from PyPI, and the entry's text is read against the pinned
  version's licence before it ships.
- **Its own sign-in,** first account and all. That fits apps call #6
  as it is.

---

## 6. Order

1. **C1, the apps account:** the measurement (§7 call 1), then the build,
   with the failing check first.
2. **C2, chat v1,** in its own repo.
3. **C3, Open WebUI.** It depends on C1 only, so it can move ahead of C2 if
   Troy wants the choice first.
4. MCP servers, then filesystem tools, each designed first.

Each slice ends the project's way: every specs CI script run locally before
an installer pin, a sabotage pass, and both installers re-pinned.

---

## 7. Calls for Troy

None of these is taken. Each has a recommendation so a build could start.

| # | The call | Recommendation | Counter-argument |
| --- | --- | --- | --- |
| 1 | Who runs an app's process (§2) | **Measure both on a GitHub Windows runner and in WSL first, then decide.** Leaning: the OS service manager with an account per app, because it also keeps apps apart and has no password to keep | Supervision moves out of the agent for apps only: two ways to run a child, two log paths, two back-off rules |
| 2 | What an app may do on installs that cannot have an apps account (Windows per-user, Linux `--user`, macOS) | **Install an app there only if its manifest says it runs nothing the model chooses.** Chat v1 says so; Open WebUI does not. Anything else is refused, with the reason and the install that would allow it | Refusing Open WebUI on a Mac sends the Mac user to install it by hand, where it runs as them anyway |
| 3 | The chat app's repo and catalogue id | **`eugene-plexus/chat`, id `chat`** | A product name, if one is wanted before the first release that ships it |
| 4 | Which door the app uses | **`/v1/chat/completions`**, the door every OpenAI-compatible backend and client speaks, so our app exercises the commonest path | `/v1/responses` carries server tools natively and is where Codex lives |
| 5 | How the app's sign-in is first set | **A passphrase set on first open, and only from a browser on the same machine (loopback)**, so a stranger on the LAN cannot claim it first | A beginner opening it from their phone first gets "open this on the computer"; the console's passphrase would need single sign-on, which apps call #6 deferred |
| 6 | The app's front-end stack | **The console's: a Next static export with the Plexus tokens copied** (no shared code across repos), served by the app's Python process | A smaller stack builds faster and carries no `dist` branch |
