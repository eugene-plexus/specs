# Row 47: shared team knowledge, and sharing a project

Lane WB, after rows 70 (groups reach Workbench as sign-in claims) and 27
(project extras). **High risk** (access to other people's knowledge, a
store migration). Sources: MRC25 (answered "ok": "owner-granted stores like
folder grants; a collection per chat later"), MV7's "Sharing a project with
another person" (`workbench-memory-v2.md` §MV7 "not in this slice"), R8
("per-person isolation at retrieval; sharing is an owner grant",
`workbench-memory-and-documents.md`), Workbench `projects.py`,
`knowledge/index.py`, `memory.py`, `conversation.py`.

## 1. What it delivers

- **Team knowledge.** The owner (or a group's manager, row 70) makes a
  collection, "Acme handbook", and gives it to people or groups: **Read**
  (their chats can search it) or **Contribute** (they can also add
  documents and notes). A chat or project with the collection attached
  searches it beside the person's own documents and memory, and answers
  cite it as "Acme handbook: Onboarding.pdf".
- **Sharing a project.** A project's owner shares it with people or groups.
  They get the project's instructions, documents and memory, and start
  their own chats in it. **Chats are never shared**: each person's chats in
  a shared project stay theirs.
- **The MSP case:** a technician in two client groups sees each client's
  collection only in that client's project.

## 2. Design

### Collections

- A collection holds documents and notes, like a person's, in its own
  index file (`knowledge/collections/<id>.sqlite3`), not in any person's.
- **Owner of a collection:** `install` or `group:<id>`. Grants: people or
  groups, each `read` or `contribute`. Only the owner of the install, or a
  person with `manageGroups` for that group (row 70), edits grants.
- **Retrieval** (R8 extended): a chat's search scopes are the person's own,
  plus each collection attached to the chat or its project that the person
  can read now. The check runs per search against the person's current
  groups (from the sign-in claims, refreshed within one token life).
- **Notes in a collection** are never kept automatically. A model may
  propose one (MV3's inbox); a contributor accepts it. An instruction is
  what an injection wants to plant, and here it would reach everyone.
- **Attribution:** each document and note records who added it; answers
  and the collection page show it.

### Sharing a project

- A project gains `sharedWith` (people and groups) and its knowledge moves
  into a collection owned by the project (`project:<id>`), created when the
  project is first shared: its documents (`project:<id>` index scope today)
  and its general memory. Members read it; the project's owner chooses
  who may contribute.
- Instructions (pinned `instruction` and `procedure` notes, MV7-C3) are
  part of the shared project: members get them in their chats there, read
  only.
- Members' chats in the project are theirs: the project page shows each
  person only their own chats, and the owner sees a count, never content.
- **Leaving:** a member removed from the share (or from the group) loses
  the project's knowledge at the next search; their own chats in it stay
  theirs, detached from the project's knowledge, with a line saying so.

### When people leave

Row 7 removes a person's own data. What they contributed to a collection
stays with the collection, attributed "former member" (call R47-LEAVE);
the owner can delete it there.

### Storage and contract

One store migration (next free number when the row starts): `collections`,
`collection_grants`, `collection_items` (provenance), `project_shares`.
Workbench's API only; no specs contract (row 70's claims are the input).

## 3. Repositories and files

workbench: `knowledge/index.py` (a second index kind), `knowledge`
retrieval in `conversation.py`/`api.py` `prepare`, `memory.py` (collection
notes, the inbox), `projects.py`, `store.py` (migration), row 7's removal
code, `web/src` (Collections page under Documents, the project's Share
dialog, citations). No other repo.

## 4. Tests that fail before

- `test_collections.py::test_a_read_grant_lets_a_chat_search_the_collection`
  and `test_no_grant_finds_nothing_and_says_nothing` (no leak of titles in
  errors or counts).
- `test_collections.py::test_a_group_grant_follows_membership_after_refresh`.
- `test_collections.py::test_a_model_proposed_note_waits_for_a_contributor`.
- `test_projects.py::test_a_shared_project_shares_knowledge_not_chats`.
- `test_projects.py::test_leaving_detaches_knowledge_and_keeps_own_chats`.
- `test_person_removal.py::test_contributions_stay_attributed_to_a_former_member`.

## 5. Acceptance (CI, Linux and Windows, about 4 minutes)

`specs/scripts/row47-team-knowledge-acceptance.py` on row 2's harness:
Workbench, the gateway with the fixture backend (and embeddings), a root
with people A, B, C and groups G1 (A, B) and G2 (C):
1. The owner makes "Handbook", grants G1 read, adds a document. A's chat
   with it attached cites it; C's chat with the same id attached gets
   nothing, and nothing in C's response names it.
2. A shares project P with B: B sees P's instructions and documents and
   starts a chat; A cannot open B's chat by id; the owner sees a count.
3. B leaves G1: after a token refresh, B's search of Handbook finds nothing.
4. A model-proposed note in Handbook waits in the inbox until A (a
   contributor) accepts it.
5. **Sabotage:** drop the grant check from retrieval; step 1's C must then
   find the document and the run must fail.

**The reviewer should attack:** retrieval scopes (an attached collection id
the person cannot read; a project id), leaks through citations, counts,
error texts or search timing; a shared project exposing chats; group
claims after removal; the inbox path for injected instructions.

## 6. Do not change

- Row 26's context files (`context.py`); row 31's page files.
- Row 70's claim handling in `signin.py` (read it).

## 7. Size and risks

L, about 4 days, after rows 70 and 27. One adversarial review.
Risks:
- **One retrieval bug shares a person's knowledge with others.** The grant
  check sits in one function every search goes through, and the sabotage
  step tests it.
- **Shared instructions reach everyone in a project:** only the project's
  owner and contributors write them, and model proposals wait for a
  person.

**Calls:** R47-LEAVE (a removed person's contributions stay with the team,
attributed).
