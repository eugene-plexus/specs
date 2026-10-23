# Row 53: one store for the platform half

Lane GW. **High risk** (a new store of people's content, ownership,
deletion, a new component). Sources: calls R53-REPO and R54-DEFAULT
(Troy, 2026-10-23: "If this is necessary for full OpenAI API
compatibility, then it should not be an optional extra app, it should be
a core module like the Gateway. Our default posture should aim to be 100%
compatible with our OpenAI API endpoint."), which reverses MRC24 ("if
built, app-shaped"); option B1 in `workbench-memory-and-documents.md`
§3.3 (a component with `/v1/files`, `/v1/uploads` and the vector-store
operations); LD6 and LD7 (`llm-d-lessons.md`: a response store needs
DI2's privacy review: TTL, per-person ownership, the owner may not read
people's chats); memory `project_platform_half_on_roadmap`; gateway
`responses.py` (today: "This gateway keeps no response store"),
`admission.py` (`ClientRequest`); the machine port
(`tls-between-machines.md` §3.1).

Rows 54 (stored responses and conversations), 55 (batches) and 56 (vector
stores and `file_search`) use this store; this row builds it with Files
and Uploads, so it is useful on its own.

## 1. What it delivers

- **A new core component, `store`,** beside the gateway. Every install
  has one, started by default like the gateway and the library. The
  gateway's doors keep what OpenAI- and Anthropic-built apps expect to be
  kept: first files (`/v1/files`, `/v1/uploads`), then (rows 54-56)
  responses, conversations, batches and vector stores.
- **The default posture is full compatibility.** Nothing is switched off
  by default; an owner may turn a part off in the store's settings, and the
  door then says so in one line ("This install keeps no responses: the
  owner turned it off in Settings → Store").
- **Everything kept has an owner and an end.** An object belongs to the
  person who made it (or, with no person, the key that made it), is seen
  only by that owner, expires on a stated date, and is deleted for good.

## 2. Design

### Where it lives

- A new repo and component, `store` (Python, FastAPI; package
  `eugene_plexus_store`, PyPI `eugene-plexus-store`). `ComponentKind`
  gains `store`. Default port **8084 on loopback**; other machines reach it
  through the machine port as `https://<node>:8083/store/...`, so no port
  is published (Troy's no-new-ports rule).
- **One per install, on the root by default**, beside control: the
  installers and the container image install and start it with the other
  root components; the agent supervises it like the gateway. Topology is
  config: an owner may move it to another node, as with the library.
- **It runs as Eugene's own account**, with its data in Eugene's data
  folder (`<data>/store/`), like the library. It implements the standard
  config endpoints (`GET /v1/config`, `GET /v1/config/schema`,
  `PATCH /v1/config`) and starts in degraded mode on a bad config.
- **The gateway is its only client door.** Clients never talk to it; the
  gateway finds it through its topology like the library, and calls it
  with its own per-node key.
- **Why a component and not inside the gateway:** an install can run
  several gateways, each with its own disk; one store behind all of them
  keeps an object findable from any door, and the gateway stays a stateless
  routing tier above the drivers (the two-layer rule). Components share
  schemas, never code, so the store owns its own SQLite and blobs.

### When the store is unreachable

The platform paths answer 503 with the observed cause ("Eugene's store on
nas is not answering: connection refused. Chat keeps working; files and
stored responses wait for it."). Chat, completions and Messages without a
`file_id` or `previous_response_id` never depend on the store.

### Ownership

- The gateway passes the verified owner on every call, from its admission
  context, never from the client:
  - `person:<id>` when the root verified a person token
    (`ClientRequest.person_id`);
  - else `key:<lineage>` (row 24's lineage, so a rotated key keeps its
    objects);
  - `install` for the owner's console session.
- The call carries it in a header the store trusts only from a gateway's
  component token (per-node key, `sub: gateway`); the store refuses
  anything else, including another component's token.
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
| (row 54) Stored response and conversation | 30 days | the owner's default |
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

### Storage

SQLite (`store.sqlite3`: objects, owners, expiry, parts) and a blob folder
addressed by SHA-256, in `<data>/store/`; schema migrations with a copy
before each, as Workbench does. Backups and upgrades: the same path as the
library's data.

### Console

Settings → Store (the standard config page): default lives, quotas, and a
switch per part (files, responses, batches, vector stores), all on. The
install's machine page lists the store like the gateway. Counts and bytes
per owner, never content.

### Contract

- `openapi/store.yaml` (new): the component's internal API (the objects,
  the owner header, the sweep's status, the config endpoints) for the
  gateway's codegen.
- `components/common.yaml`: `ComponentKind` gains `store` (every consumer
  that names it regenerates: measure by regenerating and diffing).
- `gateway.yaml`: the Files and Uploads paths and schemas, the 503 wording
  when the store is unreachable, and `file_id` resolution on the doors.
- `agent.yaml`: the store as a supervised component and topology entry.

## 3. Repositories

New `store` (public, Apache 2.0, DCO; CI from the template every repo
uses, pre-commit; the orchestrator creates the repo when the row starts),
gateway (routing to the store, `file_id` resolution, the 503), agent
(supervision, topology, the machine port's `/store/` route), specs
(contracts, installers' `PIN_STORE` and default start, the container
image, acceptance), ui (the component on machine pages, Settings → Store).
The new repo joins `scripts/worktree.py`, `ship.py`, `release-inputs.py`,
`release/manifest.json`, the installers and the CI planner.

## 4. Tests that fail before

- gateway `test_files_door.py::test_files_are_503_naming_the_cause_when_the_store_is_down`
  and `test_a_file_id_resolves_for_its_owner_only`.
- store `test_owner.py::test_another_owners_id_is_a_plain_404`
  and `test_only_a_gateway_token_may_name_the_owner`.
- store `test_uploads.py::test_parts_assemble_and_a_bad_hash_is_refused`.
- store `test_expiry.py::test_expired_files_are_deleted_by_the_sweep`.
- store `test_quota.py::test_over_quota_is_413_with_the_numbers`.
- agent `test_components.py::test_a_root_install_starts_the_store_by_default`.

## 5. Acceptance (CI, Linux and Windows, about 5 minutes)

`specs/scripts/row53-store-acceptance.py` on row 2's harness: a root, an
agent that starts the store by default, the gateway, the fixture backend,
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
6. The store is stopped: `/v1/files` is the 503 naming the cause; a plain
   chat still answers.
7. **Sabotage:** drop the owner filter on listing; step 2 must fail.

**The reviewer should attack:** the owner header's trust (a client header,
a non-gateway token, a gateway token replayed with another owner),
existence leaks through timing, sizes or errors, path handling of blob
names, upload part reuse across owners, the sweep's deletion (shared
blobs), the machine port's `/store/` route, and the console's owner view.

## 6. Do not change

- Gateway admission and routing internals (rows 11 and 37): read
  `ClientRequest`, do not reshape it.
- Workbench's own files and knowledge index (row 56 decides any reuse, by
  copying code, never by importing it).

## 7. Size and risks

L, about 5 days, plus a new repo's setup. One adversarial review.
Risks:
- **People's content in a new place:** per-owner isolation, real deletion,
  expiry by default, no owner reading; the acceptance and the review target
  each.
- **A new component** costs CI time and a place in every tool, the
  installers and the image; the setup is mechanical (the `w0` templates,
  the library as the model).
- **Body limits:** 16 MiB per request; large files go through uploads.

**Calls:** R53-REPO and R54-DEFAULT answered (Troy, 2026-10-23): a core
component, on by default, aiming at full OpenAI API compatibility. The
name `store` and port 8084 are defaults built (call R53-NAME). The
defaults above (30 days, 10 GiB) follow OpenAI's and DI2's and are
settings.
