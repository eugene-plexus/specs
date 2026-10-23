# Row 53: one store for the platform half

Lane GW. **High risk** (a new store of people's content, ownership,
deletion). Sources: MRC24 (answered "ok": "if built, app-shaped with
per-person tokens"; option B1, a component with `/v1/files`,
`/v1/uploads` and the vector-store operations, in
`workbench-memory-and-documents.md` §3.3), LD6 and LD7
(`llm-d-lessons.md`: a response store needs DI2's privacy review: TTL,
per-person ownership, the owner may not read people's chats), memory
`project_platform_half_on_roadmap`, gateway `responses.py` (today: "This
gateway keeps no response store"), `admission.py` (`ClientRequest`).

Rows 54 (stored responses), 55 (batches) and 56 (vector stores and
`file_search`) use this store; this row builds it with Files and Uploads,
so it is useful on its own.

## 1. What it delivers

- **An optional app, "Platform store",** installed from the agent's
  catalogue like Workbench. Once installed, the gateway's doors keep what
  OpenAI- and Anthropic-built apps expect to be kept: first files
  (`/v1/files`, `/v1/uploads`), then (rows 54-56) responses, batches and
  vector stores.
- **Not installed, nothing changes:** the doors refuse as today, and each
  refusal names the app: "This install keeps no files. Install Platform
  store (Apps) to keep them."
- **Everything kept has an owner and an end.** An object belongs to the
  person who made it (or, with no person, the key that made it), is seen
  only by that owner, expires on a stated date, and is deleted for good.

## 2. Design

### Where it lives

- A new repo and app, `platform-store` (Python, FastAPI), installed by the
  agent from the catalogue (`apps_catalogue.yaml`) in its own account and
  data folder, like Workbench. One per install; any machine may host it.
- **The gateway is its only door.** The gateway routes the platform paths
  to it through the agent's app registry (`provides: platform-store`,
  the same app-link pattern MV5b uses for memory servers), over the
  machine port when it is on another machine. Clients never talk to it.
- **Why an app and not the gateway** (MRC24): an install can run several
  gateways, each with its own disk; one store behind all of them keeps an
  object findable from any door, and the content lives in an app's
  account, not in the routing tier.

### Ownership

- The gateway passes the verified owner on every call, from its admission
  context, never from the client:
  - `person:<id>` when the root verified a person token
    (`ClientRequest.person_id`);
  - else `key:<lineage>` (row 24's lineage, so a rotated key keeps its
    objects), or `key:<id>` until row 24 merges;
  - `install` for the owner's console session.
- The call carries it in a header the store trusts only from a gateway
  token (`typ: service`, `sub: gateway`); the store refuses anything else.
- **An object is seen only by its owner.** A wrong owner's request gets 404
  with the same body as a missing id (no existence leak).
- **The install owner does not read people's objects** through any door;
  the console shows counts and bytes per owner, never content (LD6's
  privacy rule, the same as Workbench's chats today).

### What is kept, and for how long

| Object | Default life | Who can change it |
|---|---|---|
| File | 30 days after upload, or the request's `expires_after` (OpenAI's field) | the caller per file; the owner sets the install default and maximum |
| Upload in progress | 1 hour (OpenAI's), then its parts are deleted | none |
| (row 54) Stored response | 30 days | the owner's default |
| (row 55) Batch and its files | 30 days after it ends | the owner's default |
| (row 56) Vector store | OpenAI's `expires_after` (days after last use) | the caller |

- **Quotas per owner:** 10 GiB and 10,000 files by default, settable by the
  owner per install and per group (row 70's policies gain
  `platformStoreBytes`). Over quota: 413 with the numbers.
- **Deletion is real:** metadata rows deleted with `secure_delete`, blob
  files unlinked; a blob shared by content address is unlinked when its
  last reference goes. A sweep each hour removes what expired.
- **Removing a person** (row 7) deletes everything they own here.

### Files and Uploads (this row)

- `POST /v1/files` (multipart, at most the gateway's 16 MiB body),
  `GET /v1/files`, `GET /v1/files/{id}`, `GET /v1/files/{id}/content`,
  `DELETE /v1/files/{id}`, OpenAI's shapes and `purpose` values.
- Larger files through `/v1/uploads` (create, add parts of at most 16 MiB,
  complete with the part order and an optional sha256), assembled as LS10
  assembles prepared files: written to a temporary file, size and hash
  checked, then renamed.
- Anthropic's Files API (`/v1/files` with `anthropic-beta: files-api`) maps
  to the same objects; the door decides by the request's headers.
- **Using a file:** a `file_id` in a chat, Responses or Messages request is
  resolved by the gateway from the store (same owner only) into the inline
  content the drivers take today, within today's attachment limits. That
  removes today's "file_id is refused".

### Storage (the app)

SQLite (`store.sqlite3`: objects, owners, expiry, parts) and a blob folder
addressed by SHA-256, in the app's data folder; schema migrations with a
copy before each, as Workbench does. Backups: the agent's app backup path
(`updateBackup` in the catalogue).

### Contract

- `openapi/platform-store.yaml` (new): the app's internal API (the
  objects, the owner header, the sweep's status) for the gateway's
  codegen.
- `gateway.yaml`: the Files and Uploads paths and schemas, the refusal
  wording when the app is absent, and `file_id` resolution on the doors.
- `agent.yaml`: `provides: platform-store` in the app link list.

## 3. Repositories

New `platform-store` (CI from the template every repo uses, pre-commit,
DCO), gateway (routing to the app, `file_id` resolution, the refusals),
agent (catalogue entry, app link), specs (contracts, installers' app pin
through `ship.py`, acceptance), ui (the app's card; owner counts per
person). The new repo joins `scripts/worktree.py`, `ship.py`,
`release-inputs.py` and the CI planner.

## 4. Tests that fail before

- gateway `test_files_door.py::test_files_are_refused_naming_the_app_when_absent`
  (wording) and `test_a_file_id_resolves_for_its_owner_only`.
- platform-store `test_owner.py::test_another_owners_id_is_a_plain_404`
  and `test_only_a_gateway_token_may_name_the_owner`.
- platform-store `test_uploads.py::test_parts_assemble_and_a_bad_hash_is_refused`.
- platform-store `test_expiry.py::test_expired_files_are_deleted_by_the_sweep`.
- platform-store `test_quota.py::test_over_quota_is_413_with_the_numbers`.

## 5. Acceptance (CI, Linux and Windows, about 5 minutes)

`specs/scripts/row53-platform-store-acceptance.py` on row 2's harness: a
root, an agent with the app installed, the gateway, the fixture backend,
two people with Workbench-style person tokens and one plain key:
1. Person A uploads a file (one request) and a 40 MiB file (uploads, three
   parts); lists and reads them; a chat request with A's `file_id`
   reaches the fixture backend as inline content.
2. Person B's list is empty; B's request for A's id is the same 404 as a
   missing id; B's chat with A's `file_id` is refused the same way.
3. The plain key's files are its own.
4. A file with `expires_after` 1 s is gone after the sweep (shortened), from
   the database and the disk.
5. A is removed (row 7): A's files and blobs are gone.
6. **Sabotage:** drop the owner filter on listing; step 2 must fail.

**The reviewer should attack:** the owner header's trust (a client header,
a non-gateway token, a gateway token replayed with another owner),
existence leaks through timing, sizes or errors, path handling of blob
names, upload part reuse across owners, the sweep's deletion (shared
blobs), and the console's owner view.

## 6. Do not change

- Gateway admission and routing internals (rows 11 and 37): read
  `ClientRequest`, do not reshape it.
- Workbench's own files and knowledge index (row 56 decides any reuse, by
  copying code, never by importing it).

## 7. Size and risks

L, about 4 days, plus a new repo's setup. One adversarial review.
Risks:
- **People's content in a new place:** per-owner isolation, real deletion,
  expiry by default, no owner reading; the acceptance and the review target
  each.
- **A new repo** costs CI time and a place in every tool; the setup is
  mechanical (the `w0` templates).
- **Body limits:** 16 MiB per request; large files go through uploads.

**Calls:** R53-REPO (a new app repo rather than serving the platform API
from Workbench). MRC24 is answered (app-shaped); the defaults above (30
days, 10 GiB) follow OpenAI's and DI2's and are settings.
