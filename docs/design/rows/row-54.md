# Row 54: stored responses, with the chain as the conversation key

Lane GW, after row 53 (the platform store). **High risk** (people's chats
in a new place). Sources: LD6 (`llm-d-lessons.md`: "A response store …
The chain is an exact conversation key … It needs the same privacy review
as DI2's disk cache"), gateway `responses.py` (today: `previous_response_id`,
`conversation` and `prompt` are a 400; `store: true` is accepted, ignored
and reported), `affinity.py` (keys: `prompt_cache_key`, Claude Code's
session id, or a hash of the model and the first messages).

## 1. What it delivers

- **Apps that chain by id work.** With the Platform store installed, a
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

- The gateway's Responses door, when the store app is installed and the
  request says `store: true` (OpenAI's default), writes after the answer
  ends: the request's input items, the output items, the model, usage,
  `previous_response_id`, and the chain's root id. Streams are stored when
  they complete; a cancelled stream stores what was sent, marked
  `incomplete`, as OpenAI does.
- **Owner and life** as row 53: `person:` or `key:`, 30 days by default
  (OpenAI's own retention), deleted for good at expiry or on `DELETE`.
- **The install setting** "Keep responses when apps ask (`store: true`)":
  on by default when the store app is installed (call R54-DEFAULT). Off:
  `store: true` is reported as ignored, as today.
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
- `conversation` objects (`/v1/conversations`) are not in this row; the
  400 for `conversation` stays, naming `previous_response_id` as what
  works.
- `instructions` are not carried along a chain (OpenAI's rule), and the
  door says so in the ignored-settings header when a client relies on it.

### Affinity (`affinity.py`)

The affinity key order becomes: the chain's root response id (new), then
`prompt_cache_key`, then Claude Code's session id, then the hash. Recorded
in the request row (`affinityKey: chain`).

### Contract (`gateway.yaml`)

The Responses paths (`GET`, `DELETE`, `input_items`) and the stored
response object; the `store` and `previous_response_id` descriptions;
`platform-store.yaml` gains the response object kind.

## 3. Repositories

gateway (`responses.py`, `affinity.py`, the new paths), platform-store
(the response kind, chain reads), specs (contracts, acceptance).

## 4. Tests that fail before

- gateway `test_responses_store.py::test_previous_response_id_rebuilds_the_conversation`
  (today: 400).
- gateway `test_responses_store.py::test_another_owners_id_is_the_missing_404`.
- gateway `test_responses_store.py::test_store_false_is_never_kept`.
- gateway `test_affinity.py::test_the_chain_root_keys_affinity_before_the_hash`.
- platform-store `test_responses.py::test_expired_responses_are_gone`.

## 5. Acceptance (CI, Linux, about 4 minutes)

`specs/scripts/row54-stored-responses-acceptance.py` on row 2's harness
with the store app, two replicas of the fixture backend and two people:
1. Person A sends a Responses request with `store: true`, then three more
   chained by `previous_response_id`; the fixture backend receives the
   whole conversation each time, and every request lands on the same
   replica.
2. A's `GET`, `input_items` and `DELETE` work; after `DELETE` the chain's
   next request is the 404.
3. Person B chaining from A's id: the 404; B's `GET` of A's id: the 404.
4. `store: false`: nothing is kept (the store's count for A is unchanged).
5. **Sabotage:** drop the owner check when loading a chain; step 3 must
   fail.

**The reviewer should attack:** chain loading across owners, a chain that
loops or forks, context overflow when rebuilding, what a cancelled stream
stores, and whether anything stored reaches logs or metrics.

## 6. Do not change

Row 53's ownership and expiry code (call it); row 11's queue and row 37's
routing (read their interfaces).

## 7. Size and risks

M, about 2 days. One adversarial review. Risks:
- **Chats kept for 30 days in a new place:** per-owner, deleted at expiry,
  never readable by the install owner; the setting turns it off.
- **Rebuilt conversations can exceed the context:** the door's existing
  context handling (truncation reported in headers) applies, as for a
  client that sends it all.

**Calls:** R54-DEFAULT (keep responses when apps ask, on by default once
the store app is installed).
