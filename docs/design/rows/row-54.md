# Row 54: stored responses and conversations, with the chain as the conversation key

Lane GW, after row 53 (the `store` component). **High risk** (people's chats
in a new place). Sources: LD6 (`llm-d-lessons.md`: "A response store …
The chain is an exact conversation key … It needs the same privacy review
as DI2's disk cache"), gateway `responses.py` (today: `previous_response_id`,
`conversation` and `prompt` are a 400; `store: true` is accepted, ignored
and reported), `affinity.py` (keys: `prompt_cache_key`, Claude Code's
session id, or a hash of the model and the first messages).

## 1. What it delivers

- **Apps that chain by id work.** On every install, a
  Responses request with `store: true` is kept, and the next request can
  send `previous_response_id` instead of the whole history. The OpenAI
  Agents SDK and other clients that chain this way stop getting a 400.
- **`GET /v1/responses/{id}`, `DELETE /v1/responses/{id}` and
  `GET /v1/responses/{id}/input_items`** answer for the owner.
- **The chain keeps a conversation on one replica.** Affinity uses the
  chain's root id before any hash, so two chats that open the same way no
  longer share a replica by accident, and one chat stays where its cache
  is.

## 2. Design

### Storing

- The gateway's Responses door, when the request says `store: true` (OpenAI's default), writes after the answer
  ends: the request's input items, the output items, the model, usage,
  `previous_response_id`, and the chain's root id. Streams are stored when
  they complete; a cancelled stream stores what was sent, marked
  `incomplete`, as OpenAI does.
- **Owner and life** as row 53: `person:` or `key:`, 30 days by default
  (OpenAI's own retention), deleted for good at expiry or on `DELETE`.
- **The install setting** "Keep responses when apps ask (`store: true`)"
  in Settings → Store: on by default (R54-DEFAULT, answered: full
  compatibility). Off: `store: true` is reported as ignored, as today, and
  `previous_response_id` gets the 400 naming the setting.
- **Not stored:** `store: false` requests (Codex sends these), and any
  request whose owner is the console's session without a person.

### Chaining

- `previous_response_id`: the gateway loads the chain (owner checked,
  newest first, up to the model's context), rebuilds the input as the
  conversation so far plus the new input, and sends the driver the whole
  conversation, as it does for a client that sends it all.
- A missing, expired or other owner's id: 404 `response_not_found` with
  one sentence: "No stored response response_abc… for this key. It may
  have expired (responses are kept 30 days)."
- **Conversations (54b):** `/v1/conversations` (create, get, update,
  delete) and `/v1/conversations/{id}/items` (list, create, get, delete),
  OpenAI's shapes, in the store with the same owner and life. A Responses
  request with `conversation` reads the conversation's items as the input
  so far and appends the new input and output items when it ends. A
  request may send `conversation` or `previous_response_id`, not both
  (OpenAI's 400).
- `prompt` (reusable prompts made in OpenAI's dashboard) stays a 400 that
  names the reason: Eugene has no prompt dashboard.
- `instructions` are not carried along a chain (OpenAI's rule), and the
  door says so in the ignored-settings header when a client relies on it.

### Affinity (`affinity.py`)

The affinity key order becomes: the conversation id or the chain's root
response id (new), then
`prompt_cache_key`, then Claude Code's session id, then the hash. Recorded
in the request row (`affinityKey: chain`).

### Contract (`gateway.yaml`)

The Responses paths (`GET`, `DELETE`, `input_items`), the Conversations
paths and objects, and the stored response object; the `store`,
`previous_response_id` and `conversation` descriptions; `store.yaml`
gains the response and conversation kinds.

## 3. Repositories

gateway (`responses.py`, `affinity.py`, the new paths), store (the
response and conversation kinds, chain reads), specs (contracts,
acceptance).

## 4. Tests that fail before

- gateway `test_responses_store.py::test_previous_response_id_rebuilds_the_conversation`
  (today: 400).
- gateway `test_responses_store.py::test_another_owners_id_is_the_missing_404`.
- gateway `test_responses_store.py::test_store_false_is_never_kept`.
- gateway `test_affinity.py::test_the_chain_root_keys_affinity_before_the_hash`.
- gateway `test_conversations.py::test_a_conversation_carries_items_between_requests`
  (today: 400).
- store `test_responses.py::test_expired_responses_are_gone`.

## 5. Acceptance (CI, Linux, about 4 minutes)

`specs/scripts/row54-stored-responses-acceptance.py` on row 2's harness
with the store, two replicas of the fixture backend and two people:
1. Person A sends a Responses request with `store: true`, then three more
   chained by `previous_response_id`; the fixture backend receives the
   whole conversation each time, and every request lands on the same
   replica.
2. A's `GET`, `input_items` and `DELETE` work; after `DELETE` the chain's
   next request is the 404.
3. Person B chaining from A's id: the 404; B's `GET` of A's id: the 404.
4. `store: false`: nothing is kept (the store's count for A is unchanged).
5. A creates a conversation and sends three Responses requests with it;
   the fixture backend receives the whole conversation each time; B
   cannot read or use it (the 404).
6. **Sabotage:** drop the owner check when loading a chain; step 3 must
   fail.

**The reviewer should attack:** chain loading across owners, a chain that
loops or forks, context overflow when rebuilding, what a cancelled stream
stores, and whether anything stored reaches logs or metrics.

## 6. Do not change

Row 53's ownership and expiry code (call it); row 11's queue and row 37's
routing (read their interfaces).

## 7. Size and risks

L, about 3 days (54a responses, 54b conversations). One adversarial
review. Risks:
- **Chats kept for 30 days in a new place:** per-owner, deleted at expiry,
  never readable by the install owner; the setting turns it off.
- **Rebuilt conversations can exceed the context:** the door's existing
  context handling (truncation reported in headers) applies, as for a
  client that sends it all.

**Calls:** R54-DEFAULT answered (Troy, 2026-10-23): kept when apps ask,
on by default, as part of full OpenAI API compatibility.
