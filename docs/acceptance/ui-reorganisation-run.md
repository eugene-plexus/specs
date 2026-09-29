# The UI reorganised: Backends owns its page, Settings by topic — run record, 2026-09-29

Design: [`../design/ui-settings-reorganisation.md`](../design/ui-settings-reorganisation.md).
Troy's brief: no new features; the tree's *Inference drivers* branch held
only each driver's config while start and stop lived on the install root,
and settings were filed by process — four minutes to find one.

## What was run

| Gate                                    | Result                                                                                                     |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `npx tsc --noEmit`, `eslint`, `prettier` | clean                                                                                                      |
| `npx vitest run`                        | **117 files, 1428 tests, all green** (was 1422; `settingsTopics.test.ts` is new and `config/page.test.tsx` was rewritten) |
| `npm run build`                         | 20 routes, static                                                                                          |
| `scripts/navigation-acceptance.sh`      | three executions; see below                                                                                |
| `scripts/library-folders-acceptance.sh` | two agents, +100 ports: **all five browser checks PASS**; nine launch checks FAIL because the live install's model held 30.5 of 32.6 GiB and admission refused a 3.1 GiB runtime — unrelated to this work, and the browser checks ran regardless |
| sabotage pass                           | **20 of 20 caught**, after three escaped on the first pass (below)                                          |

### navigation-acceptance.sh

- **First execution:** 14 of 15 browser tests passed. The one failure was
  *the layer colours are still the architecture page's*, which asserts
  the modern theme's pink and blue and had been reading the **default**
  theme — plexus, apricot on the right roles, since 2026-09-17. A latent
  failure this run was the first to meet: **the check now sets the
  modern theme before it looks.** Nothing about the colours changed.
- **Second execution:** 15 of 15 browser tests passed; the script's own
  checklist reported two "did not run" because it greps test names and
  two tests were renamed. The checklist was corrected and a third
  execution recorded below.
- **Third execution: ALL CHECKS PASSED** — 8 API checks and 15 browser tests, 42 s of browser time, on the one-box install the script builds on +100 ports.

The tree spec now asserts: the four branches by name and the absence of
*Inference drivers*, *Control root* and *Agents* as visible labels; one
machine leaf per machine under Machines; the backend leaf under its
machine (two) or straight under Backends (one), whose click lands on
`/inference` with that backend's row marked and the actions on it, and
whose Settings is one menu entry away; a bare `/config` selecting the
install with every topic card and a search that shrinks the page and
opens a fold; a machine's own Settings as that machine's share with no
Theme and no first-run flag anywhere on it.

### The sabotage pass

Twenty sabotages across `settingsTopics.ts`, `resourceTree.ts`,
`ConfigEditor.tsx`, `config/page.tsx`, `AppShell.tsx`, `inference/page.tsx`
and `navigation.ts`, each restored from a copy, none a no-op (the script
refuses a mutation that leaves the file's hash unchanged). Seventeen were
caught first time. **Three escaped, and each named a second mechanism
rather than a weak check:**

1. *The editor shows hidden keys.* The Settings page filters
   `HIDDEN_KEYS` before the editor sees a field, so removing the editor's
   own filter changed nothing on that page. The editor's guard is for the
   plain page a backend gets; it has its own case now
   (`ConfigEditor.test.tsx`).
2. *The bar counts sections, not changes.* The save-all test had two
   sections with one change each, so the two counts agreed. It edits two
   fields in one section now, and reads *3 unsaved changes in 2 sections*.
3. *The scope never narrows the machines.* Every Inference fixture had one
   machine, so a scope that showed every machine showed the same one.
   A two-machine case asserts the second machine's section is absent when
   one backend is selected and present for the branch.

All three are caught now; the pass was re-run for each.

## Not done, named

- No moderated session has seen the new tree; the labels and the branch
  order are decisions (design §Decisions) and Troy's to change.
- The two-agent browser run covered Library's node rows and Folders, not
  a backend under a machine group in a browser (the unit fixtures do).
- `uiTheme`, `uiFontSize` and `firstRunComplete` are hidden by the UI, not
  deleted from the agent's and the control root's schemas.
- Nothing is pushed, packaged into `dist` or pinned: the tree's shape and
  its words are for Troy to look at before an install sees them.
