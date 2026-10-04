# Workbench conveniences and update notices — 2026-10-04

Troy requested 10–12 everyday Workbench improvements, then asked for three
related console fixes while implementation was underway. All are included
in this Edge candidate.

## Workbench: twelve additions

1. Search chat names, case-insensitively, with clear and no-match states.
2. Group recent chats by local calendar dates, newest first.
3. Keep text drafts per person and chat in this tab, including refreshes;
   clear them on send, deletion and sign-out. Attachments are not draft storage.
4. Drop files on the composer.
5. Paste images into the composer.
6. Show which attachment is uploading and keep Send disabled until uploads finish.
7. Grow the composer with its contents, with a bounded height.
8. Jump back to the latest answer after scrolling up.
9. Copy user messages as well as answers and code, with success/failure feedback
   and a fallback for browsers without the Clipboard API.
10. Export a Markdown snapshot including message text, reasoning, tool records,
    sources and attachment names, without fetching attachment contents.
11. Show local message times, with the full date on hover.
12. Keyboard shortcuts for new chat, chat search and the composer, with visible help.

Chat creation, renaming and deletion now report failures. Renaming and delete
confirmation fit a phone. A model that disappeared remains explicitly unavailable
and cannot be sent to. Ordinary paste and IME composition retain their behavior.

## Console and agent corrections

- The cached update check can be six hours old. Update confirmation now asks the
  selected machine for its current channel target before submitting it. The agent
  independently rechecks before starting; a failed check never installs the cached
  target, and a concurrent newer publication produces a refusal rather than an old install.
- Needs Attention refreshes after relevant actions, when a node's version/update
  state changes in the Versions poll, and when focus returns. Its ordinary poll
  continues to cover changes made elsewhere. API reads bypass the browser cache.
- Unsupported optional engines are information on the engine card. Their mere
  presence no longer produces an unresolvable warning. A requested runtime that
  needs an unavailable, un-installable engine still receives an actionable warning.

## Validation

Uses isolated temporary Workbench state, a fixture OIDC provider and gateway,
and ephemeral ports. No live install or model process is changed. The Chrome
flow covers draft restoration and separation, search, shortcuts, composer growth,
send, copy, timestamps, scrolling, Markdown download, a 320px viewport, and sign-out
cleanup. Component tests also drive dropped/pasted files, upload/send races,
failed sends, account isolation, clipboard failure and export contents.

Console regression tests keep the issue badge mounted across a version repair,
drive its refresh from a write and an observed version change, and verify that
folder checks cannot create a polling loop. Update tests advance the channel
between the displayed offer and confirmation and refuse a failed final refresh.

Local results: Workbench 61 frontend tests and 142 Python tests passed, including
the Chrome flows for tools, folder access and these conveniences. Three POSIX-only
checks are skipped on this Windows host and remain covered by Linux CI. Reviewing
the phone screenshot found an absolutely positioned screen-reader status that
expanded the document below the viewport; it is now anchored to Copy, and the
browser test checks vertical as well as horizontal overflow. That final build's
Chrome flow passed again. Console: 1,653 tests passed, followed by the added
version-observation regression (22/22 in that file). Agent apps and update tests:
70 passed, two POSIX-only checks skipped locally. Lint, types, formatting and builds
passed. Published archive contents and their own commit stamps were verified.

## Release inputs

| Component | Commit |
| --- | --- |
| Workbench source | `6797491fd344020b288dab4294ffc16fd547cbe4` |
| Workbench distribution | `37441cd0feee15b79733fbf667764d3cd23508f8` |
| Console source | `3928db517fa37fb5051d27c40b2d004ccd4e80a7` |
| Console distribution | `7529f9c94e0eb7916c7b5544a1bb8f13469f71c7` |
| Agent and app catalogue | `d38450a85276227b25821dc70dbe11f30fb4e52e` |

The release manifest and both generated installers pin this agent and console.
The agent catalogue pins the Workbench distribution. Edge is offered only after
all workflows on the release commit succeed. Physical updates of Troy's container
and Amish_Station are not part of this run.
