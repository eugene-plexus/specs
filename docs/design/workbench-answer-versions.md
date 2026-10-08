# Workbench: kept versions of an answer

**Status: designed 2026-10-08, on Troy's six calls (§1).** This is roadmap
A6's next Workbench item ([`workbench-v1.md`](workbench-v1.md) W1 and §6,
[`audience-roadmap.md`](audience-roadmap.md) A6).

Today, *Try again* deletes the last answer, and editing a message deletes
everything after it. After this slice, a chat is a **tree**. *Try again* on
any answer, or an edit of any message, starts a new branch beside the old
one, and the old branch is kept whole. A person moves between versions with
arrows on the message. **What is on screen is the path the model is sent.**

## 0. What exists to build on

- **An answer is one row in `messages`**, and that row holds everything:
  - the text, including its draft (what it wrote before its last web search);
  - its reasoning, sources, status, model and finish;
  - every tool round, with its calls and results (`tool_rounds`, schema 4).
- **The model is sent the chat's rows** through `conversation.request_for`,
  which `_ask` builds once per answer from `store.messages()`. An assistant
  row becomes its tool transcript and its answer, without the draft. Tool
  rounds extend that same request; they do not read the store again.
- **One answer runs per chat** (`Answers.running`). Sending and Try again
  refuse while one runs. Tool rounds continue the same row after approval.
- **The page already copes with an unknown message in the event stream.**
  It reloads the chat (the W1 offsets and gap rule).
- **Two lines of copy already exist:**
  - under an edit: *"Asking again replaces everything after this message."*;
  - under tool calls: *"Stopping, editing or retrying a chat does not undo
    actions a tool has already taken."*

## 1. Calls taken (Troy, 2026-10-08)

| # | The call | Taken |
|---|---|---|
| V1 | How far versions reach | **A full branching tree.** Every version keeps its own continuation, and choosing an old one brings its branch back |
| V2 | Try again while an answer is running | **Stops it, keeps it as a stopped version, starts the next** |
| V3 | Editing a message | **The edit is a new version of that message**; the old message and everything after it stay as the other branch |
| V4 | A cap on versions | **None.** A version is text, and a chat is deleted whole |
| V5 | The owner's read-only view (W4) | **Every branch**, stepped through read-only, with the job-site redaction (J13a) applied along each branch. Otherwise a person could hide a branch from oversight by switching away from it |
| V6 | Which answers Try again works on | **Any answer.** It starts a branch there, and the old answer and everything after it stay |

**Two smaller calls, taken here:**

- **Versions cannot be switched while an answer is running.** The arrows
  are disabled, and their title says *Wait for the answer, or stop it.*
  So a running answer, and any tool call waiting for approval, always stays
  on the path being shown, where its Stop and its approval are. *Try again*
  is the exception: under V2 it stops the running answer first.
- **Export writes the path shown.** When the chat has other branches, the
  export says so in one line: *Exported as shown; other versions of some
  messages are not included.*

## 2. The tree

- **Each message has a parent:** the message it follows (`parent_id`), or
  none for the chat's first message. Messages with the same parent are
  **versions** of one another. A user message's versions are its edits, and
  an answer's versions are its tries. They are numbered in the order they
  were made.
- **In each group of versions, one is chosen** (`chosen`). The **path** is
  the chat as it is shown: start at the chosen first message, then follow
  each message's chosen child until there is none.
- **Each branch remembers where it was.** Choosing a version restores that
  version's own chosen descendants, so going back to version 1 brings back
  the whole conversation that followed it.
- **A version is a whole message.** For an answer, that is a complete row
  with its draft, reasoning, sources, searches, status, error, model, finish
  and tool rounds. A stopped, failed or interrupted answer is still a
  version, and it keeps the sentence that names its cause. Each answer
  records its own model. Pick another model and try again, and the two
  versions compare the models.
- **Tools ran in every version.** A version that used tools made its own
  calls, and each call that needed approval asked again. Switching does not
  undo what a tool did, and the existing line under tool calls stays.

## 3. What a person does

- **Try again, on any answer** (V6): adds a version of that answer under the
  same user message. The new branch is chosen, so the path now ends with
  the new answer. If an answer is running anywhere in the chat, it is
  stopped first and kept (V2).
- **Edit, on any message** (V3): adds a version of that user message with
  the edited text and the same attachments, then asks for an answer to it.
  The old message and its whole branch stay. The edit's note becomes:
  *Your earlier version and what followed it are kept. Use the arrows to
  go back.*
- **The arrows:** a message with versions shows **`‹ 2 of 3 ›`**. On an
  answer, the version's model follows it. Its accessible name is *Answer 2
  of 3* or *Message 2 of 3*. Moving chooses that version, and the choice is
  saved. Every tab watching the chat follows, and the next message
  continues from the path shown.
- **Sending** continues from the end of the path shown.
- **Copy, the time and the model** belong to the version shown.

## 4. What the store keeps (schema 6)

Two columns on `messages`:

- **`parent_id TEXT`**: null for a chat's first message.
- **`chosen INTEGER NOT NULL DEFAULT 1`**: exactly one row in each group
  of versions has it.

**`seq` stays as the order rows were made.** Sibling numbers come from it,
and so do the stream offsets it already serves.

**The migration links the existing chats as they are.** Each row's parent is
the row before it in `seq`, and every row is chosen. The statement is one
`UPDATE` with a correlated subquery. A schema-5 chat opens as the same
conversation, with no versions.

`Store` methods:

- **`messages(chat_id)` returns the path.** Every existing caller keeps its
  meaning without changing: the request builder, Try again's "last answer",
  export, and the owner's default view.
- **`tree(chat_id)`** returns every row, for the page and the owner's view.
- **`add_message(message, parent_id)`** inserts a row as the chosen child of
  its parent and clears its siblings, in one transaction. A new user
  message's parent is the path's last message. An answer's parent is the
  user message it answers. A version's parent is its sibling's parent.
- **`choose(message_id)`** makes a row the chosen one among its siblings.
- **`delete_messages_from`** is no longer used: nothing is deleted except a
  whole chat.
- **`mark_interrupted()`** still marks every running row.

## 5. The API

- **`GET /api/chats/{id}`** returns the path as `messages`, as today, so
  the page still renders a list. Each message on it carries
  `versions: {index, count, ids}`, its place among its siblings.
- **`GET /api/chats/{id}?via={message_id}`** returns the path through that
  message and its remembered descendants, **without saving anything**. The
  owner's view uses it to step through branches (V5).
- **`POST /api/chats/{id}/messages/{mid}/retry`** (V6) adds a version of
  that answer and starts it. The chat-level `/retry` stays as "the last
  answer on the path", so nothing that uses it breaks.
- **`POST /api/chats/{id}/messages/{mid}/edit`** adds a version of that user
  message instead of replacing it.
- **`POST /api/chats/{id}/messages/{mid}/choose`** chooses a version. It
  returns 409 while an answer runs (§1).
- **Events:** a change of path (Try again, edit or choose) sends a `path`
  event. Every tab reloads the chat, then follows the new answer's events
  as today.

## 6. What the next turn sees, and what others see

- **The model is sent the path and nothing else:** each answer's tool
  transcript and its answer without the draft, through the unchanged
  `request_for`. A branch that is not shown never reaches the model.
- **The owner's read-only view (W4) shows the person's current path** when
  it opens. The owner can step through every branch with the same arrows,
  through `?via=`. That never moves the person's choice (V5).
- **The job-site redaction (J13a) runs along a path.** It hides a message
  when that message, or anything before it on its own path, holds a
  job-site result the owner may not read. On a tree this is one walk from
  each first message: a message is hidden if its parent is, or if it holds
  such a call itself. A branch that never touched a job site stays visible.
- **Export** writes the path shown, with the line from §1 when other
  branches exist.
- **Deleting a chat** deletes every branch. **A restart** mid-answer marks
  the running answer *interrupted*, as W1 does today.

## 7. The checks

- **Store:**
  - A schema-5 chat opens as schema 6 as the same conversation: every
    parent is the row before it, and every row is chosen.
  - `add_message` leaves exactly one chosen row per group.
  - The path follows the chosen versions, and choosing restores a branch's
    remembered descendants.
  - `messages()` never returns a row off the path.
- **API:**
  - Try again on an earlier answer leaves the old branch whole and starts a
    new one at that answer.
  - An edit keeps the old message and its branch.
  - Choose, then send: the fake gateway's recorded request holds the
    chosen path's text and tool transcripts, and nothing from other
    branches.
  - Choose while an answer runs is refused. Try again while one runs
    leaves it as a stopped version (V2).
  - `?via=` changes nothing saved.
  - The owner's view reaches every branch, and redaction hides a branch from
    its first job-site result while leaving a sibling branch visible.
  - Export notes other branches.
- **Page:**
  - The arrows count, choose, and are disabled while an answer runs.
  - Every tab reloads on a `path` event.
  - The owner's arrows only look.
  - The edit note says the earlier version is kept.
- **Chrome,** against the real app and the fake gateway: send, try again
  on the first answer, edit the first message, go back to the first
  version, then send. The gateway must be sent the first branch with the
  new message, and the other branches must still be there.
- **Sabotage** on the changed code:
  - `messages()` returns every row;
  - a new version is not chosen;
  - choose ignores a running answer;
  - edit or Try again deletes the old branch;
  - `?via=` saves;
  - redaction checks only the message itself, not its path;
  - the migration leaves a parent missing.

## 8. Order

1. Schema 6, the migration and the `Store` methods, with their tests.
2. The API, the events and the redaction on a path, with their tests.
3. The page: the arrows, the edit note, per-answer Try again, Try again
   while running, and the owner's arrows.
4. The Chrome check and the sabotage pass.
5. Workbench `dist`, then the agent's catalogue pin and the specs pin.

## 9. Not in this slice

- Deleting one branch.
- Seeing two versions side by side, or a map of the whole tree.
- Naming a branch.
