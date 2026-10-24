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
| File | Until deleted, as OpenAI keeps it; or the request's `expires_after` (OpenAI's field, one hour to 30 days) | the caller per file; the owner may set a default life (review, 2026-10-24) |
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
- **Removing a person** (row 7) hides everything they own here at once and
  deletes it 30 days later, as Workbench does (R53-REMOVE, Choice 2).

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
5. A is removed (row 7): A's files are hidden (404 to A and to B) and stay
   on disk; A restored, the same ids and bytes come back; A removed again,
   the owner's Delete now deletes A's files and blobs at once, every copy;
   with the days shortened, the sweep after the date deletes them.
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

**Calls:** R53-REPO, R54-DEFAULT and R53-NAME answered (Troy,
2026-10-23): a core component named `store`, on by default, aiming at full
OpenAI API compatibility. The defaults above (30 days, 10 GiB) follow
OpenAI's and DI2's and are settings.

- **R53-REMOVE: Choice 2 (Troy, 2026-10-24).** When the root removes a
  person, what they own in the store is hidden at once, from everyone,
  and deleted 30 days later by the sweep. Restoring the person within the
  30 days brings everything back unchanged. It matches MRC27 and row 7:
  the owner's Delete now deletes at once and for good, every copy, and
  row 7's legal-hold setting governs the store too (keep 30 days, the
  default, or not at all). The signal is row 7's (the root's answer about
  its people). The mass-removal brake is dropped: the 30-day window
  replaces it. Building it is described under "Defaults built".

## 8. What building found (2026-10-23)

- **No `/store/` route on the machine port.** Another machine's gateway
  reaches the store the way it reaches the library: its own agent's
  `/api/proxy/store`, which finds the store in the install's topology and
  forwards to the holding machine's agent through its machine port,
  re-minting the gateway's token for that machine. A separate `/store/`
  route would be a second path to the same listener, and it could not carry
  the token anyway: the machine port translates none, and the gateway holds
  no token addressed to another machine. Only a machine whose key holds the
  `gateway` grant can name owners at the store.
- **Removal needs the root, so control and the agent changed.** The store's
  own token cannot leave its machine, so it asks its agent
  (`POST /v1/people/known`, this machine's store only), and the agent asks
  the root with its node token (`POST /v1/people/known` on control,
  `sub: agent` only). Nothing is said while the root is locked or a standby;
  a root that cannot be asked deletes nothing.
- **A rotated key's lineage is a reader first.** `ClientAdmissionResult`
  gains an optional `lineage`; the gateway takes it when present and uses
  the key id otherwise. The authority does not send it yet: an older reader
  refuses an unknown field (`extra=forbid`), so it starts once every reader
  has shipped. Until then a rotated key starts a new owner, and its old files
  end on their own date.
- **The files doors are outside `CLIENT_ADMISSION_PATHS`**, because
  `admission.py` belongs to rows 11 and 37 now. Each door makes its own
  check-only `ClientRequest` (the same `check` the inference doors make
  first), so a revoked key, a removed person and a person token without its
  app key are refused as anywhere; a file request holds no lease and counts
  against no rate. Their 16 MiB limit is their own middleware
  (`FilesBodyLimit`), because the shared limit matches exact paths only.
  They are not answered cross-origin yet.
- **Two port walks could hand out 8084 twice.** `ports.first_free` returns
  its preferred port whenever the operating system says it is free, and at
  boot nothing listens yet: a root that moves control behind the machine
  port, and a root that gains the store, both walked from a port another
  entry already declared. Both now start past every declared port.
- **The dev bootstrap does not install the store yet.** It clones each
  repository's `main`, and the store's `main` holds nothing until this row
  merges. A follow-up adds it to `bootstrap.sh` and `bootstrap.ps1`.

### Defaults built

- **A file is kept until it is deleted**, as OpenAI keeps one (Troy's
  standing rule: full OpenAI compatibility by default; set by the review,
  2026-10-24, replacing the 30-day default in section 2's table). An app may
  ask for an end with `expires_after`, within OpenAI's bounds (one hour to 30
  days). The owner may set a default life in Settings (`fileDefaultDays`, 0
  by default). An upload in progress still ends after an hour, as OpenAI's.
- **10 GiB and 10,000 files** per owner, install-wide. The per-group quota
  (row 70's `platformStoreBytes`) is not built: it needs control's policy
  schema and the gateway to carry it, and is a follow-up.
- **A removed person is hidden, then deleted** (R53-REMOVE, Choice 2,
  replacing the immediate delete and the brake built first). The sweep
  (hourly, or Sweep now) asks the root about every person who owns
  something here, the hidden ones too, through the agent's
  `POST /v1/people/known`, which gives the answer Workbench gets from
  `/oidc/subjects`. A person it no longer has is hidden at once: lookups
  and listings answer the same 404 as a missing id, to the person and to
  everyone; nothing new is kept for them (403, "Eugene removed this
  person"); the console shows only their counts, the day they were hidden
  and their delete date. The date is fixed when they are hidden
  (`removedPeopleDays`, 30, 1 to 365); a later change never shortens it.
  `removedPeopleRetention` "Not at all" deletes at once instead. The keys,
  values and wording are row 7's.
- **Restored within the days, everything comes back unchanged:** the same
  ids and bytes, at the next sweep after the root has the person again (or
  at once with Sweep now). A file whose own `expires_after` passed while
  its owner was hidden is deleted on time, as it would have been.
- **Delete now** (Settings -> Files apps keep, per removed person;
  `POST /v1/removals/delete`, an operator session only) deletes at once and
  for good: rows, blobs no one else names, and the person's rows in every
  copy kept before a migration (MRC27). It refuses a person Eugene still
  has (404): their files are theirs.
- **A root that cannot be asked** hides and restores nobody; a date that
  has passed is still kept to, as row 7 keeps it (the date was decided when
  the root answered).
- **The quota and the disk:** a hidden person's objects stay counted against
  them until deleted, and nothing new is kept for them, so no upload
  reclaims what they kept. Deleting is fenced by the generation read before
  the root was asked.
- **A switch for files only.** Responses, batches and vector stores get
  theirs with rows 54-56; a switch for a part that does not exist would show
  a setting that does nothing.
- A `file_id` on chat, Responses and Messages carries a **PDF, an image or
  UTF-8 text**; anything else is refused, naming its type. Anthropic's
  uploaded files read as `downloadable: true`: the owner may read back what
  it kept.
- The owner's console shows counts and bytes per owner by the person's or
  key's name, never a file name or content.

### The review (2026-10-24)

A second model reviewed the row and found no way for a client to name an
owner. It found, and building fixed, each with a test that fails without the
fix and one sabotage of each new check:

- **`file_id` expansion went past the attachment limit.** A 6 MiB text file
  named twice expanded to 12 MiB of text the later checks never count. The
  files one request names now share the 11 MiB attachment budget, a file
  named twice counted twice, checked from each file's recorded size before
  its bytes are read.
- **The quota did not bound the disk.** A whole file and a part were written
  before their checks, two `complete` calls joined one upload twice, and an
  ended file left the accounting while its bytes stayed until the sweep.
  Room is now taken under the lock before any byte is written; an upload is
  joined once at a time (409), its parts checked by reading and deleted as
  they are joined; an ended file counts until its bytes are deleted, and an
  owner at its quota has its own ended files deleted first.
- **Removal could race a person restored under the same id.** Every file
  and upload carries the store's generation; the sweep reads it before it
  asks the root and deletes only what is older.
- **The standby could still take a port the store declared.**
  `ports.first_free` now never returns a reserved port, the preferred one
  included, so every allocator skips a declared port.
- **A caller's `text/plain` on bytes that are not UTF-8 was a 500.** Text is
  only what decodes as UTF-8; anything else is refused naming its type.
- **Coverage:** the gateway's files doors have an admission matrix (no
  credential, an expired key, a session for another machine, another
  machine's service token, a person token beside a session, a person the
  root no longer knows, a key revoked for real); the acceptance checks
  another owner's file, content and deletion, and sabotages the listing and
  the lookup by id separately.
