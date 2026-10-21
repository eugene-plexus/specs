# Row 25: connect an app on this machine (CONNECT, MR9b Open WebUI)

Lane AG2, high risk: auth, and writes in a person's home folder. Sources: Troy's idea of 2026-10-19 (`docs/history/audience-roadmap.md`, the CONNECT line), MR9b (`workbench-memory-and-documents.md` §10.3, §10.7), Job Sites (`job-sites-own-enrollment.md` §2.4-§2.7, `person-held-keys.md`), CX5.

**Store migration.** The store is at 27. Rows 7, MV5b, 28 and 27 take 28 to 32. This row takes the next free number when it merges. Whichever row merges later renumbers.

**Row 24 is not needed.** The credential here is a Workbench connection token, not a client key. Remove `needs: [24]`.

## 1. What it delivers

- On Memory > Connections, Workbench lists Claude Code and Codex on each Job Site you are linked to: found or not found, with versions.
- You pick a client, its rights and its expiry, and press Connect. You approve at the machine, or with a passkey in Workbench, as you approve a new workspace. Your own worker on that machine then writes the client's setup:
  - Claude Code, through its own tool (`claude mcp add --scope user`);
  - Codex, through a merging edit of `~/.codex/config.toml`, with a backup.
- The token goes Workbench → root (in memory) → site host → your worker → the file. It never passes through a browser.
- Revoke stops the token at once. The entry leaves the client now, or when the machine is next reachable.
- Open WebUI gets Workbench as a tool server from Eugene. Each person turns it on for themselves in Workbench. No token is copied.
- The copied setup stays as the expert route.

## 2. The design

### The credential (call CONNECT-C1)

Each client on each machine gets its own Workbench connection (MR9b): a `wbc_` token, rights the person picks, an expiry of 30, 90 or 365 days, and life only inside the person's live Workbench sign-in (MRC29). It is not a gateway client key:
- client keys have no owner, and only an operator makes one (control `may_name`);
- they open models, not notes;
- rows 37 and 40 own giving keys an owner.

Pointing a client at Eugene's models stays the CX5 recipe.

### The two clients

| Client | Program found at | Written with | Removed with |
|---|---|---|---|
| Claude Code (the VS Code extension reads the same file) | PATH, then `~/.local/bin`, `~/.claude/local`, `%APPDATA%\npm`, Homebrew, `~/.nvm/versions/node/*/bin` | `claude mcp add --transport http --scope user workbench <address> --header "Authorization: Bearer <token>"` | `claude mcp remove --scope user workbench` |
| Codex (the VS Code extension's own binary too) | PATH, npm, Homebrew, `~/.vscode*/extensions/openai.chatgpt-*/bin/*/` | `[mcp_servers.workbench]` with `url` and `http_headers` in `$CODEX_HOME/config.toml` (format checked with Codex 0.162) | Our table and its marker comment |

- **The search goes past PATH.** A Linux system worker starts under systemd, whose PATH has no `~/.local/bin`. An nvm `claude` needs its own `node`, so the worker puts the program's folder first on PATH for that run.
- **Which entry is ours.** The site host keeps a record per setup in its own folder (`client_setups.json`): connection id, client, entry, address and the token's SHA-256. An entry is ours only while its address and bearer hash match. Codex's table also carries `# Added by Eugene Plexus for Workbench connection <id>`. An entry named `workbench` that is not ours is replaced only when the person presses Replace.
- **The Codex edit.** It uses `tomlkit`, which keeps comments and order (a new dependency; `ship.py` asks for the lock). The worker copies the file to `config.toml.eugene-<time>.bak` and keeps our newest 3. It then writes a temporary file and replaces the original, after checking that the original's hash is unchanged.
- **Paths.** The worker runs as the person (J24), so the home folder is their own: `%USERPROFILE%` on Windows (only while the person is signed in, J25), `$HOME` on Linux, the installing person on macOS. Docker is not a site.
- **No link, no setup.** The worker never writes as the owner for a person who has no link on the machine.

### The flow

1. **Detect.** `client.list` is a read and needs no signature. For each client it returns `found`, `program`, `version`, `config`, the entries that point at this Workbench, and `problem`.
2. **Ask.** The browser sends `POST /api/connections/setups {site, client, name, rights, days}`. Workbench checks the cap of 10 and keeps a setup row, `waiting`, with no token. It then sends `client.connect {client, entry, addresses, connection: {id, name, rights, expiresAt}}`. The address candidates are Workbench's `public_origin`, then the page's own origin.
3. **Check, then hold.** The worker checks that the client is found and the file can be read. It sends a GET to each address. The first address that answers with Workbench's `401 Bearer realm="workbench"`, with TLS checked against the OS trust store, is the one written. The site then holds the change in `Calls` (in memory, 30 minutes) as a new kind, `client`. The envelope is `act: client.connect` over everything in step 2 except the address list, plus the chosen address. A setup always waits for the person's key, the owner's too (call CONNECT-C5).
4. **Approve.** At the machine (Path A), or with a passkey in Workbench (the existing held approve route).
5. **Finish.** A Workbench task polls each waiting setup every 10 s for 30 minutes, with the person's newest session. It sends `{held}` with no token.
   - While the answer is `held`, it waits.
   - When the answer is `approved`, it mints the token, keeps the connection, and sends `{held, token}`. The site requires the arguments, without the token, to equal the signed ones. The worker writes, the site records the setup, and the held item is dropped.
   - If the write fails, Workbench deletes the connection.
6. **Revoke.** Workbench deletes the connection, as today, so the next call gets 401. It marks the setup `removing` and sends `client.disconnect`. That only takes access away, so it needs no signature (J51). The worker removes the entry only if it is still ours. A failure is tried again every hour for 30 days.

**The token is never kept or shown outside the client's file.** It is in no browser response, no held item, envelope, word list or audit line, and nothing the root replicates (operations never are). The site keeps only its hash. `audit.CONTENT_KEYS` gains `token`. The control route logs no body.

### Open WebUI (25c)

- **Agent.** A new placeholder, `{workbenchMcp}`, is filled when Workbench runs on the same machine. It is a one-item `TOOL_SERVER_CONNECTIONS` list: `type: mcp`, `url: http://127.0.0.1:<port>/mcp`, `auth_type: system_oauth`, for every user. With that auth type, Open WebUI 0.11.4 forwards the user's Eugene access token (`utils/tools.py:154`). The agent also passes Workbench `EUGENE_PLEXUS_APP_PEER_APPS`: the id, name and OIDC client id of each app here that signs people in.
- **Workbench `/mcp`.** It now takes an Eugene access token beside a `wbc_` token:
  1. It asks the root's `/oidc/userinfo` to check the token. The answer is cached 60 s by the token's hash.
  2. It reads the token's `client_id` and requires it to be a peer app's.
  3. It requires the person's app connection, then their live Workbench sign-in.

  `CanonicalOrigin` lets a loopback `Host` reach `/mcp`, which never reads a cookie.
- **The app connection.** It is a connection row with a new `app` column. Its token hash comes from a value that is never shown. It lasts until the person turns it off.
- **Installs from before this row.** A new environment variable would reset Open WebUI's in-app settings once (`resetOnConnectionChange`). `AppManifest` gains `seededOnce`, which keeps the variable out of the reset fingerprint. Older installs see the values to add in Open WebUI's Admin Settings > External Tools (call CONNECT-C3).

### Contracts

- `site-host.yaml`:
  - `SiteManageAction` gains `client.list`, `client.connect` and `client.disconnect`;
  - new `SiteClientKind` (`claude-code`, `codex`), `SiteClientList`, `SiteClientConnect` (`held`, and a `writeOnly` `token`), `SiteClientDisconnect` and `SiteClientSetup`;
  - `SiteHeldCallKind` gains `client`.
- `control.yaml`: `POST /oidc/job-sites/{site}/clients`, `.../clients/connect` (200, or 202 when held; needs J77's `use-job-sites`) and `.../clients/disconnect`. Each takes Workbench's client authentication and the person's refresh token.
- `agent.yaml`: `AppManifest.seededOnce`, `{workbenchMcp}` and `EUGENE_PLEXUS_APP_PEER_APPS`.

### Failures, each naming its cause

- "Claude Code was not found for you on Amish_Station. Install it there, then Check again."
- "You are not signed in on Amish_Station. Sign in there to set up apps on it."
- "Claude Code could not add the server: claude exited 1: <its last line>."
- "Codex's config.toml could not be read: line 12: <parser words>. Nothing was changed."
- "Amish_Station could not reach Workbench at https://192.168.16.252:8390/mcp: the certificate is not trusted there. Trust Eugene on Amish_Station, or use Workbench's public address."
- "Revoked. Its entry stays in Codex on Amish_Station until you sign in there. It no longer works."
- "Revoked. Codex's workbench entry on Amish_Station was changed by hand, so Workbench left it."

### UI text

- **Connections:** "Set up an app on your machine". One block per site: "Claude Code 2.1.288 · Connect", "Codex · Not found".
- **The dialog** keeps MR9b's rights, expiry and outside-model sentence, adds "Writes ~/.claude.json on Amish_Station", and ends with "Copy the setup instead".
- **Waiting:** "Waiting for your approval on Amish_Station, or approve here with a passkey."
- **Done:** "Connected. Start a new Claude Code session to use it."
- **At the machine:** "Add Workbench to Claude Code for troyc · notes, documents, until 19 Jan 2027 · https://…/mcp · Workbench sends the key after you approve."
- **Open WebUI:** "Open WebUI on this install · Off · Turn on". The dialog adds: "Open WebUI's administrators can run code inside it that sees what it reads for you."
- **The console's Connect apps page** gains one line: "To let Claude Code or Codex read your Workbench notes, connect them in Workbench." It links with `workbenchLink`.

**Defaults.** Nothing is deleted except lines Workbench added and still owns, after a backup. The Open WebUI tool server is on for new installs, and it reads nothing until a person turns it on.

## 3. Repositories and files

- **specs:** the three documents above; `scripts/row25-connect-app-acceptance.py` and its `ci.yml` step; MR9b §10.7 item 9.
- **control:** `routes/sites.py`.
- **site-host:** `host.py`, `calls.py`, `worker.py`, new `client_setup.py`, `audit.py`, `pyproject.toml`.
- **agent:** `apps.py`, `app_launcher.py`, `apps_catalogue.yaml`.
- **workbench:**
  - `connections.py`, `connections_api.py`, new `client_setups.py`;
  - `job_sites_api.py`, `node_folders.py`, `public_origin.py`, `settings.py`;
  - `store.py` (`connection_setups`, `connections.app`);
  - `Connections.tsx`.
- **ui:** `app/connect/page.tsx` and Open WebUI's app page.

Codegen: control (`control.yaml`, `agent.yaml`), site-host (`site-host.yaml`), agent (`agent.yaml`, `site-host.yaml`), ui. Regenerate each and diff. Workbench hand-writes its control client.

## 4. Tests that fail before the change

- **site-host `test_client_setup.py::test_codex_entry_merged_with_backup_and_removed_byte_for_byte`.** A temporary home holds a `config.toml` with comments and another server. After connect, the original text is intact around our table, and a backup exists. After disconnect, the file equals the original. It fails today: there is no `client_setup` module.
- **Also, in site-host:**
  - `test_claude_code_added_with_its_own_tool` (a stand-in `claude` records its argv);
  - `test_held_item_holds_no_token`;
  - `test_resend_with_other_arguments_is_refused`;
  - `test_entry_changed_by_hand_is_left`;
  - `test_person_without_a_link_is_refused`;
  - `test_address_with_quote_or_newline_is_refused`.
- **workbench `test_client_setups.py`:**
  - `test_no_browser_response_holds_a_token`;
  - `test_revoke_stops_the_token_before_cleanup`;
  - `test_failed_write_deletes_the_connection`;
  - `test_open_webui_token_needs_the_persons_app_connection`;
  - `test_token_of_another_client_is_refused`.
- **control:** `test_client_routes_log_no_token`.
- **agent:** `test_open_webui_gets_workbench_tool_server` and `test_seeded_once_does_not_reset`.

## 5. Acceptance (CI, Linux and Windows, about 6 minutes)

**`row25-connect-app-acceptance.py`** starts:
- a control root, an agent, Workbench at its pin, and a per-user site host with one worker as the runner's account;
- a temporary home folder;
- Claude Code and Codex from npm at pinned versions.

Every process gets an OS-assigned loopback port (never 8079-8083), with every `EUGENE_PLEXUS_*` variable cleared.

**Checks:**
1. Both clients are not found, then found after the install.
2. Claude Code connects after Path A approval. `claude mcp get workbench` shows the address. An MCP `initialize`, sent with the header read from `.claude.json`, lists the chosen tools.
3. Codex connects. `codex mcp list` shows it. The original text of its file is intact, and a backup exists.
4. A resend with a different address is refused.
5. `wbc_` is in no browser response, root log, replicated log, site audit, held list, site record, Workbench log, store or WAL.
6. After a revoke, the next call gets 401, both entries are gone, and `config.toml` equals its original.
7. A revoke while the site host is stopped gets 401 at once. The entry goes after the restart.
8. An entry changed by hand is left, and the page says so.
9. A peer-app token works only for a person who turned the app on. Another client's token gets 401.

**Real-machine run on Amish_Station** (one run of record):
- native `claude.exe` and the VS Code extension's Codex, as troyc;
- the same as jessie, signed in;
- installed Open WebUI calling `search_notes`.

**The reviewer should attack:**
- the token reaching a browser, a log, an envelope, a backup or a command line (`claude.cmd` puts it in argv for under a second; prefer `claude.exe`);
- a connect without the person's signature: a stolen session, a swapped address, a replay after 30 minutes;
- argument injection into `claude`, TOML injection, and tricks through `CODEX_HOME` or a link;
- a write as the wrong account;
- removing an entry that is not ours;
- the Open WebUI path: a wrong `client_id`, a person who never turned it on, and the loopback exemption reached from another machine;
- a compromised site host. It can already act as any linked person within the rules (§2.4), and this row widens that to two client files. Row 51's "worker checks signatures" closes it.

## 6. Do not change

- **agent:** `machine_port.py`, `node_identity.py`, `trust.py`, `standby.py`, `keyring_store.py` (3, 4, 46); `reach.py`, `__main__.py` (8, 2); `admission.py`, `engines/*` (ENG); `routes/directories.py` (23); `tray.py`, `tokens.py` (35).
- **control:** `oidc.py`, `sealing.py`, `trust.py`, `replication.py` (3-5); `person_access.py`, `permissions.py`, `administration.py` (37, 39); `client_admission.py`, `routes/client_keys.py` (11, 24, 40); `tokens.py` (46).
- **workbench:** `context.py`, `conversation.py` (26); `answers.py` (28); `tools.py` (29, 32); `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (52, 60); `folder_windows.py`, `folder_linux.py` (23); `memory_servers.py`, `past_chats.py`, `projects.py` (7, 27).
- **ui:** `ResourceTree.tsx`, `settingsTopics.ts` (33); `ConfigField.tsx`, `configValue.ts` (62); `GatewayOperations.tsx` (38); `lib/clientKeys.ts` (24).
- **Every `scripts/codegen.py`** (1).

**Shared:**
- workbench `store.py`: add the migration and methods only, and add `connection_setups` to row 7's `PERSON_TABLES`.
- site-host `worker.py` and `signing.py` (row 51) and agent `apps_catalogue.yaml` (row 34) come earlier in this lane. Rebase on them.

## 7. Size, split, risks and calls

**M-L, about 4 days,** on one branch, `r25-connect-app`:
- **25a (S, low):** the contracts, the control routes and `client.list`. Workbench shows what each site found.
- **25b (M, high):** connect and disconnect for both clients, and Workbench's setups with their migration.
- **25c (M, high):** Open WebUI.
- **25d (S):** the console line and the docs.

One acceptance run, one adversarial review and the real-machine run come after 25c.

**Risks:**
- Client formats drift. Each format is pinned to a version a real client checked, and CI runs the real clients.
- A running Codex reads its file only at start, so the page says to start a new session.
- Windows workers run only while the person is signed in.

**Calls only Troy can make:**
- **CONNECT-C1, the credential.** Recommended: one Workbench connection per client and machine. Model access stays the copied recipe until keys get an owner (rows 37, 40).
- **CONNECT-C2, the next clients.** Recommended: none in this row. Gemini CLI, VS Code's `mcp.json` and Cursor follow, each S, each after a real client reads what was written. Claude Desktop's file takes only local programs.
- **CONNECT-C3, Open WebUI installs from before this row.** Recommended: no reset; show the values to add. The alternative resets Open WebUI's in-app settings once, at the update.
- **CONNECT-C4, Open WebUI's administrators.** Admin-pasted functions can read users' forwarded tokens (`functions.py:279`), so the owner, as Open WebUI's admin, could read the notes of a person who turned it on. Recommended: per-person opt-in, off by default, with that sentence in the dialog. The alternative drops 25c.
- **CONNECT-C5, the owner's own machine.** Recommended: a setup always waits for the person's key, the owner's too. This is stricter than J52, because the write lands in a program that runs commands.
