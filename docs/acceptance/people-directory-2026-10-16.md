# People directory and account details

Implemented after Troy reviewed the first U2/U3 Edge build. Included in the
[SSO Edge publication](edge-sso-2026-10-16.md); no running installation was upgraded.

## Behavior

- People opens with a table, ten accounts per page, with 25/50 options, search
  across names/email/groups, and active/disabled filters. Names sort naturally.
- Selecting a person opens only that person's account and permissions editor.
  Both the owner and named-administrator pages use this directory. Their existing
  authorization and allowed controls remain separate.
- Account detail editors are visible sections: Account details, Groups and app
  access, Administration permissions, and Account actions. Wide owner layouts
  place access and administration side by side; narrow screens stack the cards.
  Only explanatory job-site help remains collapsed. Password reset, disable and
  delete are separated from everyday account/access editing. Delete still asks
  for confirmation; delegates never gain owner-only controls.
- A rejected password reset preserves the draft for retry; only a successful
  save clears it and displays confirmation. Writes disable their related inputs.
  Removing an email also clears the input only after success.
- Back to people preserves filters and page. Existing `#person-<id>` links,
  reload, browser Back and keyboard focus work. Deleting an account removes its
  editor; deleting the last row on a page clamps the list to a remaining page.
- Polling preserves a selected account's draft. Directory forms remain mounted
  while hidden, so opening details does not discard unfinished group/app edits
  or a newly issued app secret. A group-load failure stays visible in details.
- One People entry sits in the install tree beside the machine-related entries.
  Accounts stay inside the paginated directory rather than becoming tree leaves.
- The administration explanation renders “Grant only what Archonas needs.”

Pagination is in the browser over the existing directory response. It bounds
rendered rows and account forms; it does not introduce a paginated backend API or
change which people the root permits an administrator to read.

## Evidence

152 focused UI checks cover visible editors, password-reset failure/retry,
account mutations, delegated authority, directory
pagination/search/history, draft isolation, missing/deleted accounts, preserved
one-time secrets and tree routing. Temporarily replacing the page slice with
the full list made the pagination regression fail (26 rows instead of 10);
the original source bytes were restored. Wrapping the new account sections in
closed disclosures made the visible-editor regression fail on the hidden email
input; the original source bytes were restored. TypeScript, ESLint, formatting and the
production export/Python static staging passed.

`u2-administration-acceptance.py --production-ui` uses disposable real control,
agent and Workbench processes, ephemeral ports, cleared Eugene environment values
and system Chrome. The agent serves the production export; no browser responses
are intercepted. The directory contains 28 accounts before the delegated creation
step. Chrome checks pagination, browser Back, direct-link reload, owner grant
save/persistence, visible controls, a real password reset, delegated account
creation and scoped group assignment, immediate
delegation revocation and 390 px layouts. Desktop/mobile screenshots were
visually inspected for both account editors. There are no page errors or viewport
overflow. Another person's private chat survives the root restart and remains
inaccessible to the delegate.

[Directory desktop](assets/people-directory/people-directory-desktop.png),
[directory mobile](assets/people-directory/people-directory-mobile.png),
[account details](assets/people-directory/people-detail-desktop.png),
[details mobile](assets/people-directory/people-detail-mobile.png),
[account actions desktop](assets/people-directory/people-actions-desktop.png),
[account actions mobile](assets/people-directory/people-actions-mobile.png),
[delegated details desktop](assets/people-directory/administration-desktop.png),
[delegated details mobile](assets/people-directory/administration-mobile.png),
[browser results](assets/people-directory/browser-result.json),
[integration results](assets/people-directory/result.json).

## Previous Edge CI follow-up

Workbench's corrected [CI](https://github.com/eugene-plexus/workbench/actions/runs/38934252445)
and [macOS acceptance](https://github.com/eugene-plexus/specs/actions/runs/38933301537)
passed. Specs' C3 video crash fixture still submitted directly with only an app
key, which U3 correctly rejects. The fixture now includes its disposable owner's
current person proof and refuses to continue without a valid submitted handle.
No production gate was relaxed. The local catalogue-install acceptance passed
50/50 checks, including resumed video recovery and gateway attribution. That
instrument correction is included in the SSO Edge publication; its asynchronous
remote CI result is not claimed here.
