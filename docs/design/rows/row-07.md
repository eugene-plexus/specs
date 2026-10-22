# Row 7: a removed person's data goes with them

Lane WB, high risk. This row takes Workbench store migration 27 → **28**. MV5b's
`memory_servers.linked` then becomes **29**. Whichever merges second renumbers,
and the roadmap's MV5b line must be edited to match.

## 1. What it delivers

- **Within an hour, their data is hidden.** When the root removes a person, Workbench hides their data. Their sign-ins and connections end, and background work for them stops.
- **After 30 days, it is deleted.** A restart-safe job deletes their chats, files, media, notes, documents, past-chat index, projects and connections. It also forgets what Workbench sent to their memory server.
- **The owner decides from Settings > People.** The page lists each removed person with a delete date and offers Keep and Delete now. Export appears only while `ownerReadsChats` is on.
- **Everyone can download their own data** at any time.
- **A re-created person is a new person.** Someone re-created with the same name sees none of the old data.
- **Nothing is deleted on a guess.** People removed before this update wait for the owner. So do three or more removals found at once.

## 2. The design

**How Workbench finds out.** The person's `sub` is control's `uuid4().hex`. Re-creating a person makes a new one, so the re-creation rule already holds. But `deletePerson` keeps no tombstone, and a refused refresh does not say why. So `control.yaml` gains one endpoint:

- `POST /oidc/subjects` (`oidcSubjects`), authenticated with `client_secret_basic`, as `/oidc/revoke` is.
- Request: `{subjects: string[1..500]}`.
- Response: `{known: [], unknown: []}`. An id is known when a person record exists, enabled or disabled, or when it is the owner.
- Errors: 401 `invalid_client`; 503 `temporarily_unavailable` while the root is locked or a standby.
- It answers only for the ids sent, so it cannot be used to list people. The agent's `/oidc/{path}` forwarder already carries it.

Workbench asks at start, every hour, when the owner opens People, and one minute after any refused refresh. `people.known_at` records Eugene's last confirmation; a sign-in also sets it.

**Migration 28.** It adds:

- `people.known_at`;
- `removed_people (sub, name, state held|hidden|kept|purging|purged, found_at, clock_from, steps JSON, attempts, last_error, purged_at)`;
- `exports (id, asker, subject, scope self|owner, state, size, error, created_at, expires_at)`.

The delete date is `clock_from + removedPeopleDays`, computed when read. So the date shown follows the setting in effect.

**When Eugene answers "unknown".**

- If `known_at` is set, the person becomes `hidden` and their clock starts.
- If `known_at` is null, they become `held`: hidden, with no clock. This covers everyone removed before this update.
- If three or more are unknown in one answer, nothing changes until the owner confirms.
- If a later answer says "known", the row is dropped. A purge that has started still finishes.

**Hiding.** One transaction deletes their sessions, their connections and their unsent memory-server exchanges. Then Workbench:

- stops their running answers;
- closes their index, and refuses `Indexes.get(create=True)` for them, so no late job re-creates the folder;
- stops folder sync, learning and the courier for them.

**The purge job.** It runs every hour, and when the owner presses Delete now. It commits `purging` before it changes anything. Every step can run twice safely and is recorded in `steps`, so a restart resumes.

1. **Memory server.** On the person's own server, `forget` each exchange Workbench sent. Never `purge`, because the server may hold other apps' memories. On an install-owned MV5b bank, `purge` it, then `list` to check. After three failures, record the cause.
2. **`knowledge/<key>`.** Rename it to `.purge-<key>`, then remove it. Retry a Windows lock and name its cause.
3. **`files/<key>`.** The same.
4. **Their export files.**
5. **The store, in one transaction.** Delete every row in `PERSON_TABLES` (one list, in `store.py`), the chats with them, then the `people` row. Set `memory_measurements.owner` to NULL. Then run `wal_checkpoint(TRUNCATE)` and `VACUUM`; `secure_delete` is already on.
6. **Every `*.schema-N.bak` copy.** Run the same purge on each copy (its own `PERSON_TABLES` for its schema), then `VACUUM` it. The copies stay as the recovery path for everyone else; only this person leaves them.
7. **`purged`.** Keep the id, name and dates.

**A true delete (Troy, 2026-10-21, MRC27).** Some data must be gone at once and for good, for example card numbers. "Delete now" is that delete: it runs steps 1-7 immediately, and when it finishes, no file Workbench keeps holds the person's data: not the store, the WAL, a `.bak` copy, an export, an index or a folder. The 30-day purge runs the same steps, so it is a true delete too.

**Export.** A ZIP, built in the background, kept 24 hours, downloadable only by the asker. It holds:

- `README.txt`;
- the chats, as `*.md` (the chosen path) plus `chats.json` (every version);
- files, media and artifacts;
- today's memory export (`memory.json`, `memory.md`, `memory-server.json`);
- the original documents;
- `projects.json` and `connections.json` (never tokens).

A self-export holds everything. The owner's export of another person follows W4. It is offered only while `ownerReadsChats` is on, and it holds the chats, their files, artifacts and media. It never holds notes or documents (memory design §4.9).

**Shared things.** There are none today. Row 47 must add its rule for who takes over shared items, and its tables to `PERSON_TABLES`.

**Failures, each naming its cause.**

- "Workbench could not ask Eugene who was removed: {cause}. Last asked {time}."
- "Jessie's data was deleted except her documents: {cause}. Try again"
- "Jessie's memory server was not cleared: {cause}. What it keeps stays there."
- "The download could not be made: {cause}."

**UI text.**

- Banner: "2 removed people's data will be deleted on 20 Nov. Review"
- Hidden: "Jessie · removed 21 Oct · deleted on 20 Nov". Buttons: Export, Keep, Delete now.
- Kept: "Jessie · kept until you delete it". Buttons: Delete in 30 days, Delete now.
- Held: "Jessie · removed before this update · nothing is deleted until you choose"
- Brake: "Eugene no longer knows 5 people who use Workbench. Nothing was hidden." Buttons: They were removed, Not now.
- Delete now asks: "Delete Jessie's chats, files, notes and documents now? This cannot be undone."
- Console Delete account: "Workbench deletes their data after a waiting period. Export it in Workbench first." It links to Workbench through `workbenchLink`.
- The button says Keep, not Restore. Nothing is given back to anyone.

**Defaults.**

- **Deletes data, on (P4; Troy confirmed the 30 days and asked for Delete now as a true delete):** the 30-day purge. The overrides are `removedPeopleDays` (1-365, in `/v1/config`), Keep, and Delete now.
- **Exposes no private data:** the owner's export follows `ownerReadsChats`, which is off.

## 3. Repositories and files

- **specs:**
  - `openapi/control.yaml`;
  - `scripts/row7-person-removal-acceptance.py` and its `ci.yml` step;
  - W4 and MRC27;
  - the roadmap's MV5b line.
- **control:** `routes/oidc.py` and tests. Control regenerates.
- **workbench:**
  - `store.py`, plus new `removal.py` and `exports.py`;
  - `sessions.py`, `knowledge/index.py`, `knowledge/folder_sync.py`;
  - `memory_servers.py`, `memory_learn.py`;
  - `config.py`, `api.py`, `app.py`;
  - `SettingsPage.tsx`, plus new `RemovedPeople.tsx` and `YourData.tsx`.

  Workbench hand-writes its control client and does not generate code from `control.yaml`.
- **ui:** `src/app/people/page.tsx`. No new pin.

## 4. Tests that fail before the change

- **workbench `tests/test_person_removal.py::test_purge_leaves_nothing_of_the_person`.** Two people each have a row in every table. After `purge_person(a)`, no row of `a`'s is left in any `sqlite_master` table that has an `owner`, `sub`, `chat_id`, `message_id` or `note_id` column, and `b`'s rows are unchanged. It fails today: `purge_person` does not exist. It is also the guard against a new table that the purge misses.
- **Also:** `test_unknown_after_known_hides`, `test_never_confirmed_is_held`, `test_three_at_once_brakes`, `test_purge_resumes_after_restart` and `test_hidden_person_index_not_recreated`.
- **control `test_oidc_subjects.py::test_removed_person_is_unknown`.** A deleted id comes back as `unknown`. Without client authentication, the call gets 401.

## 5. CI acceptance and review

`row7-person-removal-acceptance.py` runs on Windows and Linux. It starts:

- a control root and an agent on OS-assigned free ports (never 8079-8083), with `EUGENE_PLEXUS_*` cleared;
- Workbench from the catalogue at its pin;
- a stand-in engine;
- a stand-in MCP memory server that records calls and can hold one open.

It checks:

1. Owner, Ann and Ben each make a chat with a unique marker, an attachment, a note, a document and a connection. Ann connects the memory server.
2. Ann's export holds all of hers.
3. Remove Ann, then Check now. Her connection gets 401, her data is still on disk, the delete date shows, and Ben works.
4. Delete now while `forget` is held open. Kill Workbench hard. The agent restarts it, and the purge finishes.
5. Ann has no rows in any table (the store opened read-only) and no folders. Her marker is in no file under Workbench's data folder: the store, the WAL, every `.bak` copy, exports, indexes and logs. `forget` went for her exchange only. Ben is unchanged.
6. A re-created "Ann" gets a new id and an empty Workbench.
7. Removing three people at once hides nothing, and the brake line shows.
8. The owner's export of Ben is refused while `ownerReadsChats` is off. With it on, the export has no `memory.json`.

**The reviewer should attack:**

- mass deletion from a wrong answer: a restored root, a new issuer, a promoted standby, the brake threshold;
- removal used to get around `ownerReadsChats`;
- missed tables, folders, `.bak` copies or WAL pages;
- a late job re-creating a folder;
- Windows file locks;
- a hidden person's open stream;
- `/oidc/subjects` as an oracle;
- clearing a server Workbench does not own.

## 6. Do not change (other lanes' hot files)

- **control:**
  - `oidc.py`, `trust.py`, `replication.py`, `sealing.py` (rows 3-5);
  - `person_access.py`, `permissions.py`, `administration.py`, `client_admission.py` (rows 11, 37, 39, 40).
- **workbench:**
  - `tools.py` (29);
  - `artifacts.py`, `Markdown.tsx`, `MessageView.tsx` (31);
  - `folder_windows.py`, `folder_linux.py` (23);
  - `local_tools.py`, `mcp_sandbox.py`, `mcp_apps.py` (52, 60).
- **ui:** `ConfigField.tsx` (62), `ResourceTree.tsx` (33).

## 7. Size, risks, open questions

**Size M.** **Risk high:** deletion, a migration and a new authenticated endpoint.

1. **May the owner export someone's data while `ownerReadsChats` is off?** Recommend no. The person exports first; otherwise removal becomes a way to read someone's chats.
2. **May the owner give the old data to a re-created account?** Recommend not now. The root cannot prove the account belongs to the same person.
3. **Should the purge clear a person's own memory server?** Recommend no. Forget only what Workbench sent.
4. **How many removals at once trip the brake?** Recommend 3.
5. **The `.bak` copies.** Decided by Troy's MRC27 answer: the purge removes the person from each copy and keeps the copy for everyone else.

## Calls answered by Troy (2026-10-21)

- **R7-OWNER-EXPORT: Choice 2.** The owner can always export a removed person's data. Each export is logged with who, when and what. Troy's reason: legal requests in the USA. Federal discovery (FRCP 26 and 34) reaches data in an organisation's "possession, custody, or control", and a litigation hold must keep it. This is not legal advice; an organisation's counsel decides its own duties.
- **R7-REGIVE-2: Choice 1.** When a new account signs in through an outside identity provider that says the email is verified, and that email matches a removed person's, Eugene links the old data to the new account by itself and tells the owner. Only while the data is still kept. Built as part **7b** after this row merges; this row keeps the removed person's email with the hidden data so 7b can match it.
- **LEGAL-HOLD: a retention setting instead.** The owner chooses how long a removed person's data is kept: 30 days (the default) or not at all. With "not at all", removal runs the true delete at once. Changing the setting does not shorten the time of people already removed. Built in this row.
