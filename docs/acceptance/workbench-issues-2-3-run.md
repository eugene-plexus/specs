# Workbench #2 and #3 — record

**2026-10-08. Fixed, run and pinned.** Neither issue needed a design call or
a contract change.

- [workbench#2](https://github.com/eugene-plexus/workbench/issues/2): the
  edit box and the composer were both named *Your message*.
- [workbench#3](https://github.com/eugene-plexus/workbench/issues/3): a
  removed attachment still counted against the chat's 11 MiB.

| Repo | Commit |
|---|---|
| workbench (`main`) | `14bf1cf` |
| workbench (`dist`) | `8cc975c` |
| agent (catalogue) | `af6c371` |

## What changed

**#2.** The edit box is now named *Edit your message*. The composer keeps
*Your message*. The answer-versions Chrome check now finds the edit box by
its own name, and checks that exactly one box is named *Your message*.

**#3.** The composer's **Remove** now deletes an upload that has not been
sent, both its row and its bytes. It calls a new route,
`DELETE /api/chats/{chat_id}/files/{file_id}`:

- **204:** the chat has the file and no message refers to it. The row and
  the bytes are deleted, so the file stops counting against the chat's
  limit.
- **409:** a message refers to the file: *"This file was sent with a
  message, so it stays with the chat. Deleting the chat deletes it."*
- **404:** another person's chat, the owner's read-only view, or a file
  that isn't this chat's (a bin's original, or another chat's file).

In the composer:

- A refused Remove keeps the chip and says why: *"dot.png was not removed: …"*.
- **Send** waits while a Remove is under way.

**Two tabs.** A send in one tab and a Remove in another can interleave. The
store settles them, because both checks run in transactions on the store's
one thread:

- `add_message` refuses attachments its chat no longer has
  (`AttachmentGone`). The send route answers 400, *"An attachment is not in
  this chat."*, and adds nothing.
- `delete_unsent_file` refuses a file a message names (`FileInUse`).

**Send to a chat (M7).** The copy waiting in the new chat's composer is
removed on its own. The bin keeps its original.

The 413 wording now names the next step that has become possible:
*"…because the whole chat is sent each time. Remove a file not yet sent, or
start a new chat to attach more."*

**Not changed: files already orphaned.** Uploads removed before this fix
keep their rows and bytes until their chat is deleted. Freeing them would
need a sweep, which is a separate decision. Ask Troy only if he wants one.

## Tests

- **Python** (`tests/test_chats.py`, `tests/test_media.py`):
  - Upload and remove: the bytes and the row are gone, and a second Remove
    gets 404.
  - Three 4 MiB PDFs, each removed before the next, then a fourth is still
    accepted. Without the fix the route does not exist (405) and the third
    upload is refused.
  - A sent file gets 409 and stays. A removed file can't be sent.
  - Another person, the owner's read-only view and another of the owner's
    chats each get 404.
  - A send whose file was removed after the send read it gets 400 and adds
    nothing (staged in-process).
  - The store-level race, run directly against `Store`.
  - A Send-to-a-chat copy is removed alone: the original stays on disk and
    readable, and can't be removed through the chat.
- **Vitest** (`web/src/components/Composer.test.tsx`):
  - With a message in edit mode beside the composer, each box is found by
    its own name, exactly once.
  - Remove calls the route and then drops the chip.
  - A refused Remove keeps the chip and says why.
  - Send waits while a Remove is under way.
- **Chrome:**
  - `media-browser.mjs` now removes the copy that *Send to a chat* put in
    the composer, checks the DELETE returned 204, attaches a new PNG and
    sends it. `test_media_browser.py` checks that the model got the new
    PNG's bytes and that the only file left on disk is that attachment.
  - `versions-browser.mjs` is described under #2 above.
- **Full suite:** locally, without Chrome, pytest 239 passed and 12 skipped
  (opt-in Chrome, Linux-only and POSIX-only), and vitest 200 passed. That
  run may have started before the last test was added (the staged send).
  The sabotage baseline ran that test, and Workbench CI on `14bf1cf` ran the
  whole suite: both green.
- **Static checks:** `ruff check`, `ruff format --check`, `mypy src` and
  `mypy --platform linux src` are clean. `prettier --check`, `tsc` and
  `eslint` are clean.

## Sabotage

`scripts/check-attachments-sabotage.py`, with `WORKBENCH_PLAYWRIGHT` set:
**15 of 15 caught**, restored from exact bytes, and the restored baseline
passes. The baseline was 12 checks. Each case names its check:

1. No Remove route (the bug as filed).
2. Remove keeps the row.
3. Remove keeps the bytes.
4. A sent file is deleted.
5. The owner's read-only view removes.
6. A file of another chat is removed.
7. A bin's original is removed through a chat.
8. The store keeps a message naming a lost file.
9. A send that lost its file becomes a 500.
10. Remove only drops the chip.
11. A refused Remove drops the chip anyway.
12. Send isn't held during a Remove.
13. The edit box has the composer's name (the bug as filed).
14. Chrome: Remove only drops the chip.
15. Chrome: the edit box has the composer's name.

## The run of record

`scripts/c3-workbench-acceptance.py --browser`, from `agent/.venv`, without
`--openrouter-live` (nothing here is paid, and nothing was spent).

**62 of 62 passed.** The registry installed Workbench from the agent's
catalogue entry, at the pinned `dist` archive `8cc975c`. ML, SL and VL need
the live flag, so they did not run.

c3 checks that the pinned archive installs and that every earlier check
holds against it. The behaviour of Remove is checked by Workbench's own
tests above, including the Chrome check.

## Every CI acceptance script, locally

All 27 other scripts that specs CI runs passed, from `agent/.venv` with
`EP_SDK_PYTHON` set to a scratch venv holding `openai` 3.20.0 and
`anthropic` 1.9.0. `job-sites-acceptance.py` is Linux-only and was skipped.
Highlights:

- r7 signing 13/13, rotation 8/8, row 3 27 PASS
- p2 18, p3 27, p4 15, p5 8, p6 9, p8 15
- c2 42/0
- r8-profile-checks 10 regressions caught
- r38 sabotage 11/11

The runner didn't capture exit codes for 24 of them. Every log ends on its
pass or summary line, and none holds a FAIL line, an assertion or a
traceback.

## CI

- Specs `1bd7f88` (the previous record): green.
- Workbench `14bf1cf`: green.
