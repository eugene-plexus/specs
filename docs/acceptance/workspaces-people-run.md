# 2b.3b: each person's workspaces, rules and keys — run record

**Date:** 2026-10-07. **Design:**
[`job-sites-own-enrollment.md`](../design/job-sites-own-enrollment.md) §3.3
(J67-J80, *What building 2b.3b found*, *What the acceptance found*).
**Landed and pinned 2026-10-07**, without the Windows two-person run (Troy,
2026-10-07: land now, run it later). **Deployed** by Troy the same day (the
NAS root, then Amish_Station). **The Windows two-person run passed
2026-10-08** (below).

2b.3b gives each linked person their own workspaces on a job site, their own
allow/ask/deny rules, approved with their own key, and Workbench's rules
editor and prompts: "allow" runs without asking, "ask" asks each time,
"deny" is never offered.

| Repo | Commit | What |
|---|---|---|
| site-host | `26a4f0f` | per-person policy and keys, `workspace.add`/`remove`, `rules.set`, `SiteCall.asked`; this record's three fixes on `6773d81` |
| control | `be2dec1` | the root's job-site routes for a linked person's own items; per-person permissions (J77); audit lines per reader (J80) |
| ui | `db4bf501`, dist `c595c2a` | each person's job-site permissions on the People page (J77) |
| workbench | `9e61bef`, dist `ce2103f` | per-person workspaces and rules; ask only where the site says; this record's two fixes on `f206b8f` |
| agent | `aa2fe11` | pins site host `26a4f0f` and Workbench dist `ce2103f` |
| specs | this push | contract `652ddc5`; `job-sites-acceptance.py` (B1-B7), `job-sites-windows-acceptance.py` (J1-J6), `b3b-browser-check.py`/`.mjs` (new), `b3b-browser-sabotage.py` (new), `b23b-sabotage.py`; both installers, `release/manifest.json` |

## What was run

**`scripts/job-sites-windows-acceptance.py --person-account jessie --keep` —
19 passed, 1 skipped** (2026-10-08, run 1 of the elevated runner, 07:07 to
07:08; the run of record). On Amish_Station, from an elevated shell, against
the checkouts at their pins: agent `47a2e5f`, site host `26a4f0f`, control
`de4c619`. The agent ran as LocalSystem as a service install would, on its own
ports and folder; the site host as its own virtual account; troyc the owner
and `jessie`, a standard local account signed in and switched away from, the
second person. J1-J6 ran for the first time, all passing:

| Check | What passed |
|---|---|
| J1 | jessie, linked with no key yet, adds a workspace from Workbench: 202 held, counted on her view and not the owner's |
| J2 | her Chrome, in her own session, makes her key at the machine and approves it; her approve page lists only her change and the owner's only his; her workspace runs as her account, reading with no word and changing only when Workbench says she was asked (J72) |
| J3 | a rule the root forges in her name is held for her key, never applied, and she turns it down from Workbench; in the owner's name it finds no such workspace |
| J4 | a path she denies is left out of `glob` and `grep` run as her account, and refused by name, its 8.3 short name too, whether or not it exists |
| J5 | the owner sees none of her workspaces: not his view, live list, tools or audit lines, and his call naming one reads nothing; the root's console carries no path of hers |
| J6 | with `use-job-sites` taken away on the People page, her sign-in on the machine's link page is refused in the root's words and no link is made; given back, she links again |

The 2b.2 and J14a checks in the same run passed too (1-8, K1-K5). Check 9
(signed out, her calls are refused) is skipped without `--sign-out`, which
signs her out. Afterwards the runner's cleanup removed the run's folder and
processes; no `EugenePlexusAcceptance-*` task or site host service was left,
and the machine's own `EugenePlexusAgent` was still running.

**CI, Linux sudo mode (specs `59195b0`, run 37681026593) —
`job-sites-acceptance.py` 36 passed**, B1-B7 included, with the host, ada and
jo each their own account.

**`scripts/job-sites-acceptance.py --root-wsl` — 35 passed, 4 one-account
skips** (run 5; the root in WSL2 behind the real Caddy, the site host and a
stand-in worker on Windows). B1-B7, through the root: jo's workspace waits for
her own key (J68); neither person's key approves the other's change (J67); a
rule the root forges is refused and an edited policy file runs nothing (J79);
allow, ask and deny at the site (J70, J72); a denied path is hidden from
`list_directory`, `glob` and `grep`; the owner sees none of jo's workspaces
(J76, J80); without `use-job-sites` nothing of jo's own runs (J77). The four
skips need a second OS account: CI's Linux sudo run makes them, and runs
B1-B7 with two real accounts for the first time once this push lands.

**`scripts/b3b-browser-check.py` — 11 passed, 0 failed** (the run of record,
against Workbench dist `ce2103f` and site host `26a4f0f`). New: the system
Chrome drives Workbench's own page, signed in as ada on Eugene's own page,
against a real root, an agent supervising the real gateway and an
inference-driver whose engine is a scripted model, and the real site host with
a worker. The model makes the tool calls each step needs and records what it
was offered; the site's own audit log says what it applied.

| Step | What Chrome did, and what was checked |
|---|---|
| W0, W0b | ada signs in; adds a workspace from the Job sites page; it waits for her key, and once approved at the machine it is listed with read *Without asking* and change *Ask me each time* (J68, J69) |
| W1 | a read runs with no prompt: *Finished*, and the site's line says `allow`, not asked |
| W1b | the chat's folder list does not say every file operation waits for approval |
| W2a | a write prompts; nothing reaches the site or the disk while it waits; approved, it runs and the site's line says `ask`, asked (J72) |
| W2b, W2c | a declined write, and Stop while a write waits, never run and never reach the site |
| W3 | change set to *Never* in the rules editor applies at once (J51); the next answer is offered no write tool, and a write tool the model remembers is refused before anything reaches the site |
| W3b | a change back to *Ask me each time* waits for her key, and the editor keeps showing *Never*, before and after a reload |
| W4 | a 40-call answer (one `glob`, one `grep`, 38 reads) finishes with no prompt: 40 calls *Finished*, 40 allowed at the site, every result back to the model (J71) |
| W5 | Stop ends an answer that would go on reading; no call reaches the site or the model after it |

**`scripts/b3b-browser-sabotage.py` — 5 of 5 caught** (after one entry was
moved; below). Each entry undoes one rule in a `git archive` copy of what
ships and runs the whole check against it:

| Sabotage | Caught by |
|---|---|
| a call the rules allow is asked about anyway (Workbench) | W1, W4 (and W5) |
| a call the rules ask about runs without asking (Workbench) | W2a, W2b, W2c |
| Workbench never tells the site the person was asked (J72) | W2a |
| Stop does not end the answer (Workbench) | W2c, W5 (and W3, W4, which a running answer blocks) |
| the site offers a change tool its rules deny (site host) | W3 |

The first pass sabotaged the site's listing filter (`target.allowed`) for the
last entry, and it escaped: the person's offer is built without a denied
workspace's change tools, so the filter had nothing to drop. The entry now
sabotages the offer, where "deny" is decided; the filter stays as a second
guard. W1b and W3b were shown to fail by the first run, against the dist
without their fixes (`24bd35e`).

**Unit tests.** Site host 306 passed (last session's three new tests each
sabotage-checked); Workbench web 100 passed, with three new tests, each failing
with its fix taken out (three sabotages, three caught); typecheck, lint and
prettier clean.

## What the acceptance found

Six product defects, each fixed with a test that fails without the fix.

**The `--root-wsl` run (site host, fixed in `26a4f0f`):**
1. **The channel dropped `asked`.** The site host built a `SiteCall` from the
   root's operation without the field, so every "ask" call Workbench approved
   was refused at the site (J72). The unit tests called the host directly.
2. **With nothing offered, the refusal named the first blocked workspace**,
   not the one the call named: jo, asking about the owner's shared workspace
   while the owner's rules were unconfirmed, was told to approve her own rules
   (J79).
3. **`check-person` hid the root's 403 reason** behind a generic sentence;
   it relays the root's one-line reason now (J77).

**The browser check (Workbench, fixed in `9e61bef`):**

4. **The rules editor showed a held change as in effect.** After *Save rules*
   on a change that gives more (held for the person's key, J68), the selects
   kept the value asked for, and only a reload showed the rule in effect. The
   owner's sharing list did the same. Both now show a person's edits only
   until Save, then what the machine reads back live.
5. **The chat's folder list said every file operation waits for approval.**
   On a job site the rules decide (J70); Workbench's own folders still ask
   each time (J75), and the words now say which is which.
6. **The Job sites page said each listing, read or write needs approval**;
   it now says the person's rules decide what runs without asking.

In the scripts: a check that looked for a Windows path in JSON
(`str(path) in json.dumps(...)`) could never fail, since JSON doubles the
backslashes; both acceptance scripts compare the escaped form now, with a
positive control where the path is expected.

## Not done

- **Check 9 on Windows** (`--sign-out`): it signs jessie out, and she stays
  signed in between runs.
- **The fixes landed after the deploy** (control#7, agent#8, agent#9) reach
  the NAS root and Amish_Station with their next update, root first.
- The browser check runs one person on one account; two people in one
  browser each seeing only their own is `--root-wsl`'s B6 through the root's
  routes, not through Workbench's page.
