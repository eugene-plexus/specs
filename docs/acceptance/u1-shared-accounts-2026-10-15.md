# U1: shared accounts and permission groups

Accepted 2026-10-15 on Windows 11. This is the account/group foundation of
[the approved SSO plan](../design/shared-accounts-and-sso.md), not external SSO
or delegated console administration. Live installed services were not changed.

## Published revisions

| Repository | Revision |
| --- | --- |
| Contract | `340de14e6efdbf9410b340da01a150bcf744a727` |
| Control | `ea2440d49809910bbdc99e40c1148e1ff3c09002` |
| UI source | `1208b6be4c0618ebd11076e1016619ce72af6412` |
| UI distribution | `102f76513e8136dcf42e9c1393b016e8dc589da6` |
| Workbench source | `5b86d49d1484dce567632fb70d6d58c7d5a6bc14` |
| Workbench distribution | `bccae9820b92c7077ed4120f5f4d48eae756a4e3` |
| Agent catalogue | `ceca698e4354736d3e32f106187511079e5b56bd` |

The release manifest and both installers carry the control, UI and agent pins.
The agent catalogue carries the Workbench distribution. Intermediate agent
changes since the previous installer pin were Workbench catalogue updates only.

## Observed behavior

`control/.venv/Scripts/python specs/scripts/u1-accounts-acceptance.py` launched
an actual root, agent and Workbench from their own virtual environments on
three ephemeral loopback ports. Ambient `EUGENE_PLEXUS_*` settings were removed;
all data, keyring state and credentials were disposable. No inference ran.

- A pre-existing central account signed into real Workbench and created a chat.
- Chrome opened the production static export served by the actual agent, created
  a group and assigned it to that person through the actual proxy. There were no
  intercepted API responses. Effective access matched the root's answer.
- Desktop (1500 px) and mobile (390 px) fit their viewports, with no page errors.
- Signing in after assignment retained the same subject and existing private chat.
- Restarting the root replayed the group policy and memberships without changes.
- Deleting the last group left explicit empty membership and effective grants.
  Advancing only the disposable Workbench session's refresh deadline triggered
  its real network refresh, which was refused. This checks the refresh boundary,
  not ten minutes of wall-clock waiting.
- Explicitly restoring individual access allowed sign-in to the same account
  and existing chat.

[Desktop](assets/u1-accounts/accounts-desktop.png),
[mobile](assets/u1-accounts/accounts-mobile.png),
[browser results](assets/u1-accounts/browser-result.json),
[integration results](assets/u1-accounts/result.json).

An initial acceptance setup omitted the control component from the test agent's
empty topology; the UI correctly reported that it could not find control.
Registering that real component through the agent API corrected the harness.
The run above is the successful run of record.

## Checks and review

- Control: full suite 532 passed, 2 expected POSIX-mode skips on Windows.
  After the code-exchange policy fix: 60 relevant OIDC/group tests passed;
  the final variable cleanup was checked by all 7 group tests.
- UI: 32 People-page/permission-summary tests passed. Production build,
  TypeScript, ESLint and formatting passed.
- Workbench: 21 sidebar tests passed, including owner-only directory links
  independent of private-chat oversight. Production build, TypeScript,
  ESLint, Python Ruff and mypy passed.
- Agent catalogue: 3 focused tests passed; Ruff, mypy on Windows and Linux passed.
- Control Ruff, formatting and mypy on Windows and Linux passed; staged secret
  scans passed in each changed repository. Redocly validated the control contract
  (three pre-existing warnings).
- Every Python consumer was regenerated from the before/after contract with its
  own environment into temporary outputs. Only control models changed. UI's
  aggregate regeneration changed only control types; unrelated consumers stayed
  at their pins. Existing gateway/driver generated-header edits were preserved.

The adversarial review covered empty memberships, union policy, owner protection,
member administration denial, unknown memberships, group/app deletion, replication
and sign-in boundaries. It found the approval-to-code-exchange timing gap, now
closed by rechecking current access before issuing tokens. No other blocker found.

`control/scripts/check-groups-sabotage.py` mutated disposable copies and caught
all five regressions: empty groups inheriting access, refresh ignoring group
revocation, snapshot losing groups, members managing groups, and code exchange
ignoring a revocation. It never edited the real checkout.

## Packaged artifacts and rollout

Downloaded the actual published GitHub archives and verified source modules,
BUILD_INFO, substituted commit stamps, and every built asset against the local
production exports. Built wheels from those archives and checked import/commit
stamps under Python 3.12 plus asset byte equality:

| Package | Assets | Wheel SHA-256 |
| --- | ---: | --- |
| UI | 267 | `f5d8b677303270dd883166df2a637c26e30c602146a215afb0ecacf1a00e0733` |
| Workbench | 183 | `4dd1273b08482f33abee225075a6ca9d5092a4fc607abdbe3db45087f70f0b8d` |

Upgrade the active root and standbys before using group mutations: older roots
cannot replay the two new operations. Existing accounts retain their stable IDs
and individual access until explicitly switched to groups. Existing snapshots
without groups load unchanged. Workbench observes withdrawal on its next refresh
(within the existing ten-minute bound); job-site checks use current root policy.

Only the owner manages accounts/groups in U1. Groups currently govern app sign-in
and the two implemented job-site permissions. U2 adds delegated administration;
U3 handles person identity and policy at the gateway; U4 adds Google, Microsoft
and generic OIDC with explicit identity linking and shared sign-in sessions.
