# Row 26: long chats that outgrow the context

Lane WB, after row 30. Risk: cross (it changes what every model receives). Sources: the rich-content roadmap's out-of-scope list, `prompt-cache.md` (PC4), `llm-d-lessons.md` (96% of agent turns reuse 90% of their prompt as a prefix), and `workbench-memory-v2.md` (past chats, notes).

**Store migration.** The store is at 27. Rows 7, MV5b, 28 and 27 take 28 to 32, and row 30 may take one. This row takes the next free number (33 if row 30 takes none). Whichever row merges later renumbers.

## 1. What it delivers

- **A chat that grows long keeps working.** When the next request would pass 80% of the model's window, Workbench summarises a middle block of earlier turns with the chat's own model. It sends the summary in their place.
- **The prompt cache keeps working.** The system message and the first exchange stay byte for byte the same. The summary goes after them, and later turns only append. The summary request reuses the engine's cache of the conversation.
- **The originals stay.** Workbench never changes or deletes a message. The summarised messages fold into "Earlier messages summarised", with Show them and Read the summary.
- **Workbench knows how full a chat is.** It records each answer's real token use and window. The chat's drawer says "About 21,400 of 32,768 tokens · summarises at 26,200".
- **A chat that cannot fit is refused before it is sent,** with the cause. Today the answer fails with the engine's words.
- **A backend that drops the middle without a word** (the gateway's `prompt_truncated`) is named under the answer, and the next turn summarises.
- **Models outside the install's machines** also summarise at 128,000 tokens, because every turn bills the whole history.

## 2. The design

### What happens today (read 2026-10-21)

- `conversation.request_for` sends every message on the path, every turn. `context.py` says "history is never cut": retrieval gives way first.
- `documents_api.check_send` checks the window only when the chat holds a document (`_has_documents`).
- A text chat past the window is sent whole. llama-server refuses it ("exceeds the available context size"). The gateway answers 400 `invalid_request_error` with `code: null` and "The backend rejected the request: <words>" (`routes/inference.py:5392`). The answer fails with those words (`answers.py:535`).
- Workbench reads no usage. `_take` keeps only reasoning tokens, and nothing reads `prompt_truncated`.
- Workbench sends no `prompt_cache_key`. The gateway's affinity key is the model, the first system message and the first user message (`affinity.key_for`). So a stable first exchange also keeps a chat on the replica that holds its cache.

### How full a chat is

- **The window, W.** First choice: `x_eugene_plexus.context_length` from `/v1/models` (`memory_api.model_facts`). That is the smallest replica's window, read back from the engine after it loads. Second choice: the window the last answer's stream reported, now kept on the message. With neither, the window is unknown, and only the reactive path below runs.
- **The next request's size, F.** The last answer's real `usage.prompt_tokens + completion_tokens` (of its last request), plus the estimate of what is new: the person's message, its attachments and the turn's blocks. Without usage (a new model, or an engine that reports none), `context.count_messages` of the whole planned request, which is deliberately high.
- **The reserve, R.** `saved_api._reserve(chat)`, as today.
- **The trigger, T.** `T = W × summariseAt`, default 80%. For a model outside the install's machines, `T` is the lesser of that and `outsideCeilingTokens` (default 128,000; 0 means none).
- **Summarise when `F + R > T`.**
- A window under 8,192 tokens is too small to summarise into. Such a chat is refused when full.

### What is summarised

The path is a list of exchanges: a person's message and the answer that follows it, with its tool rounds.

- **Head:** the first exchange, sent verbatim. It holds the task, and it keeps the affinity key. If the head alone is more than 25% of W, only the first message is head, and its answer joins the middle.
- **Pinned:** an exchange whose message carries an attached document is never summarised. MR2 says a document is never cut unless the person chooses how.
- **Tail:** the newest exchanges that fit in 25% of W. The person's new message is always tail.
- **Ranges:** the runs of exchanges between head, pinned exchanges and tail.

**Planning a request:**
1. Use the fewest summaries that make the request fit. If the whole path is under T, send it whole.
2. Otherwise, use valid summaries first, oldest first.
3. If the request is still over T, summarise the oldest unsummarised range, then the next, until the request is at most 50% of W. That leaves room for several turns before the next summary.
4. If every range is summarised and the request is still over T, refuse with the cause (below).

**Between summaries, every request is the one before it plus new messages.**

**Size.** A summary aims at `clamp(8% of W, 512, 4,000)` tokens. When the summaries together pass 25% of W, the oldest two merge into one. That rewrites the prompt from the first summary on, and the head stays cached.

### Where a summary goes

- The system message is never changed. The head is never changed.
- Each summary is a delimited block at the start of the first user message sent verbatim after its range:

  `<earlier-turns-XXXXXXXX from="3" to="18" date="2026-10-21">`

  The block opens: "A summary of turns 3 to 18 of this conversation, written by qwen3-8b. The original messages are kept in Workbench and not sent here."
- The suffix is random, chosen when the summary is made and kept with it, as documents' suffixes are. So the block is the same bytes every turn.
- No new message is added, so the roles still alternate, which strict chat templates (Gemma, Mistral) require.

### The summary request

- **Model:** the chat's own model (call CTX-C1). The range is already in its cache. The content goes nowhere it was not already going. Every install has that model.
- **Messages:** the previous request's messages up to the end of the range, the same bytes, then one user message with the instruction. The engine reuses all of it but the instruction. The model and first messages are the same, so the request goes to the same replica.
- **The instruction, fixed and versioned:** "Summarise turns 3 to 18 of the conversation above, so that it can go on without them. Keep what the person wants and their exact requirements; decisions and why; names, numbers, paths, code identifiers and commands exactly as written; what tools found that still matters; open questions and unfinished tasks. Leave out what later turns replaced. At most N words, in the conversation's language. Do not answer the person."
- **No tools and no web search.** `max_tokens` is N, plus the chat's own `maxTokens` when reasoning is on. The request carries the person's token, as answers do.
- **A summary cut at its limit** is kept, and it says so ("cut at its limit").
- **Memory results.** The range is replayed with the request's own allowance (`transcript(notes=…, chats=…)`), so the bytes match. The summary records what it carries (`notes`, `chats`). A later request that may not carry those does not use it. It makes a new summary from the strict view instead. This keeps call 12 and MV2-C1 true.

### The reactive path

- **An overflow refusal before any token arrives** is a 400 whose words match the gateway's own list (`responses._CONTEXT_WORDS`, copied, with a test that holds the two lists together). Workbench then summarises once, with `W = 0.9 × F`, and sends again once.
- **When the range alone overflows,** it is summarised in pieces that fit. Only the head is then cached.
- **`prompt_truncated: true`** in an answer's stream is said under the answer. The next turn summarises.
- **Inside one answer's tool rounds,** an overflow ends the answer with: "This answer's tool results filled qwen3-8b's window after 9 rounds. Send again: earlier messages will be summarised." Summarising during an answer is banked.

### The store (migration)

- `messages` gains `prompt_tokens`, `completion_tokens`, `cached_tokens` and `context_length`, all nullable integers taken from the answer's last request.
- **New `chat_summaries`** table:
  - `id`, `chat_id`, `owner`;
  - `first_id`, `last_id` and `digest` (SHA-256 of the range as sent);
  - `text`, `nonce`, `tokens`, `source_tokens`;
  - `model`, `made_at`;
  - `carries` (JSON), `cut`, and `how` (`auto`, `overflow` or `merge`).
- **A summary is valid** when `first_id..last_id` is a contiguous run on the request's path and the digest matches. A version switch inside the range makes it unused. It is kept, so switching back uses it again.
- **A deleted chat** deletes its summaries in the same transaction. Row 28's branch delete deletes every summary whose range held a deleted message, so a delete stays a true delete. `chat_summaries` joins row 7's `PERSON_TABLES`. Its `owner` and `chat_id` columns put it under row 7's guard test.
- **Summaries are never indexed** as past chats, never read by memory learning, and not exported: the originals are.

### What the person sees

- **While it runs,** the answer's progress line says: "Summarising 16 earlier messages to fit qwen3-8b's window…"
- **In the chat,** the range folds into one row: "Earlier messages summarised · 16 messages · Show them · Read the summary" (call CTX-C3).
  - Show them unfolds the originals in place, under a band: "Sent to the model as a summary."
  - A past-chats result or a link into the range unfolds it.
  - Read the summary shows the text and "Written by qwen3-8b on 21 Oct from about 18,400 tokens; 1,240 tokens."
- **The chat drawer:**
  - "About 21,400 of 32,768 tokens · summarises at 26,200 · 1 summary";
  - the switch "Summarise when this chat is long: On";
  - with no window known: "This model's window is not known. Workbench summarises only when the model says the chat is too long."
- **An answer's "what was sent"** lists "A summary of messages 3-18 (1,240 tokens)".
- **The owner's read-only view** (`ownerReadsChats`) shows the same, as it shows the chat.

### Failures, each naming its cause

- **Summarising off, chat too long** (409 before anything is kept): "This chat is about 33,100 tokens, more than qwen3-8b's window of 32,768 leaves room for. Turn on summarising for this chat, start a new chat, or pick a model with a larger window."
- **No room even with every range summarised:** "The first message and attached documents fill about 30,000 of qwen3-8b's 32,768 tokens, so summarising cannot make room. Start a new chat, choose Search it instead for report.pdf, or pick a model with a larger window." This offers MR4's choice.
- **The summary call failed** (the answer fails, and Try again works): "Workbench could not summarise earlier messages: <the gateway's words>. The chat is about 33,100 of 32,768 tokens."
- **The backend dropped part of the chat:** "qwen3-8b on tower dropped part of this chat to fit its window, so this answer may miss earlier messages. The next message is sent with a summary."

### Settings (Workbench `/v1/config`, shown on Workbench's Settings page)

- `longChats.summarise`: default on. Each chat can turn it off.
- `longChats.summariseAtPercent`: 50-95, default 80.
- `longChats.outsideCeilingTokens`: 0, or 16,000 to 2,000,000. Default 128,000.
- `longChats.summaryModel`: empty means the chat's own model. Otherwise it names a model on the install's machines, so content never goes somewhere new. When that model does not answer, the chat's own model summarises, and the summary names the model that wrote it.

The drawer's numbers are computed from the values in effect.

### Defaults

- **Summarising is on for every chat, old ones too.** It acts only where a chat would otherwise fail.
- **Flagged: it keeps chat content somewhere new.** Summaries are new copies of chat text, in the same store file, deleted with their chat (AGENTS.md: say so).
- **Nothing is deleted.**

## 3. Repositories and files

**Workbench only.** No contract and no codegen consumer.

- New `long_chats.py`: pure rules, as `context.py` is (window, fullness, segments, validity, placement). Every claim in it gets a unit test.
- New `summaries.py`: the summary call, the store glue and merging.
- `conversation.py`: `request_for` takes the planned segments and places the summary blocks.
- `api.py`: `_ask` plans before it builds. `send` refuses before anything is kept.
- `documents_api.py`: `check_send` also checks text chats.
- `answers.py`: records usage, `context_length` and `prompt_truncated`; sends again once after an overflow.
- `hub.py`: an overflow becomes `HubError(kind="context")`.
- `store.py`: the migration, the summaries' methods, and the delete hooks.
- `config.py`: the `longChats` settings.
- `web/src/components/ChatView.tsx`, new `SummaryFold.tsx`, and `ChatSettings.tsx`.

**Found:** the gateway's chat door gives an overflow no machine-readable code. File a gateway issue to set `code: "context_length_exceeded"` there (row 1 owns `routes/inference.py`). After that, Workbench reads the code first.

## 4. Tests that fail before the change

- **`tests/test_long_chats.py::test_a_chat_past_the_trigger_is_sent_with_a_summary`.** A fake hub reports a window of 8,192, and the chat has 30 exchanges of about 400 tokens. Sending the 31st:
  - (a) the system message and the first exchange are byte-identical to the previous request's;
  - (b) the first user message after the head starts with the summary block;
  - (c) the newest exchanges are verbatim;
  - (d) `count_messages` plus the reserve is at most 80% of 8,192;
  - (e) the store holds all 61 messages, unchanged.

  It fails today on (b) and (d): all 61 messages are sent.
- **Also:**
  - `test_summary_request_is_the_previous_prompt_plus_one_message`: byte for byte, the same model, no tools;
  - `test_turns_after_a_summary_only_append`;
  - `test_overflow_refusal_summarises_and_sends_again_once` (window unknown);
  - `test_a_document_turn_is_never_summarised`;
  - `test_a_version_switch_inside_the_range_leaves_the_summary_unused`;
  - `test_a_summary_carrying_notes_is_not_sent_to_an_outside_model`;
  - `test_off_refuses_before_anything_is_kept`;
  - `test_an_outside_model_summarises_at_its_ceiling`;
  - `test_deleting_a_chat_deletes_its_summaries`;
  - `test_migration_adds_usage_and_summaries`;
  - `test_prompt_truncated_is_said`;
  - `test_overflow_words_match_the_gateways`;
  - web `SummaryFold.test.tsx`: folds, unfolds, and a link into the range unfolds it.

## 5. Acceptance

**CI (Linux, about 4 minutes): `workbench/scripts/row26-long-chats-acceptance.py`.** It starts:
- a real Workbench, gateway and inference driver, on OS-assigned ports (never 8079-8083), with `EUGENE_PLEXUS_*` cleared;
- a recording stand-in engine. It refuses a prompt past 8,192 tokens with llama-server's own error body, and reports usage.

It checks the request shapes only: prefix equality turn to turn, the summary request's prefix, the fold, the refusals, and that `/v1/models` gives the window.

**One run of record with a real engine, on Amish_Station.** It runs llama-server with a small model at `--ctx-size 8192` for 60 scripted turns, one of them with tools. It checks:
- no answer fails;
- the summary request's `cached_tokens` is at least 90% of its prompt;
- the turn after a summary reuses at least the head;
- turns between summaries reuse at least 90% of their prompt;
- a code word stated in turn 3 (ORCHID-42) is answered right at turn 50.

A stand-in cannot prove cache reuse (the recurring trap), so only the real run claims it.

**What to watch** (no adversarial review is owed for a cross row):
- a summary sent where its notes may not go;
- a stale summary after a version switch;
- a cache break between summaries;
- a summary of a deleted branch left behind.

## 6. Do not change

- **workbench:** `tools.py` (29, 32), `projects.py` (27, 47), `knowledge/ingest.py` and `folder_sync.py` (30), `artifacts.py`, `Markdown.tsx` and `MessageView.tsx` (31), `folder_windows.py` and `folder_linux.py` (23), `local_tools.py`, `mcp_sandbox.py` and `mcp_apps.py` (52, 60), `connections.py`, `connections_api.py` and `job_sites_api.py` (25), `memory_servers.py` and `past_chats.py` (7, 27).
- **Every `scripts/codegen.py`** (1).
- **Shared:**
  - `store.py`: add the migration and methods only; do not reorder `_MIGRATIONS`;
  - `answers.py`: row 28 comes earlier in the lane, so rebase on it and add only;
  - `context.py`: row 32 comes later; add functions only.
- **gateway:** nothing. The overflow code is the issue named in §3.

## 7. Size, split, risks and calls

**L, about 5 days,** on one branch, `r26-long-chats`. Each step merges on its own:
- **26a (S-M): measure and say.** The usage columns (the migration, with an empty `chat_summaries` so there is one migration), the drawer's line, the refusal before sending, `prompt_truncated`, and the overflow words.
- **26b (M): summarise.** `long_chats.py`, `summaries.py`, placement, the reactive path, the fold and the chat switch.
- **26c (S): expert settings and merging.** The percentage, the outside ceiling, the summary model, merging summaries, and Read the summary's details.

After 26b comes the real-engine run.

**Risks:**
- A bad summary loses a fact. The instruction keeps exact strings, the tail stays verbatim, and the originals stay readable. A tool that lets the model read the originals of a summarised range is banked.
- Prefill time for a reasoning model's summary.
- Engines that report no usage fall back to the high estimate, which summarises early.

**Calls only Troy can make:**
- **CTX-C1, which model summarises.** Recommended: the chat's own model. The range is in its cache, the content goes nowhere new, and every install has it. A smaller model on the machines is the expert override. A smaller model that is the default would read the whole range cold and add a model every install must run.
- **CTX-C2, when.** Recommended: 80% of the served window. For models outside the machines, also at 128,000 tokens, for cost and long-context accuracy. Both are settings.
- **CTX-C3, folded or shown.** Recommended: folded, with Show them, so the person sees what the model no longer gets verbatim. The alternative leaves every message shown, with a band.
- **CTX-C4, on by default** for existing chats, keeping summaries as new copies of chat text. Recommended: on, since it acts only where a chat would fail.
