# S8 vocabulary and configuration grouping — 2026-09-20

UI source `48488adc5e8855ecb2dfd14831c7bd27e1deb39d`; static distribution
`ad6836f0ae5a66e66446befbc6876b7f3583fb88`. Both installers carry that distribution.
No API contract or backend behavior changed.

The system keeps its layer map and adds an offline twelve-term glossary. The
panel scrolls within 70% of the viewport, so its final definition remains reachable
on a phone. Enter toggles the glossary; Escape closes The system and restores focus.
The existing component names stay: the Backends/Chat relabel is a separate decision.

Config puts common categories first and moves infrequently changed settings into
one Show more group per component page. The group appears only when at least
three currently applicable fields qualify. This is a UI presentation list, not a
new schema flag: unknown fields remain visible, and backend defaults, descriptions,
validation, provider conditions, and save/restart semantics remain authoritative.

- Agent: engine binary overrides and first-run reset (4 fields).
- Control root: replication, join lifetime, polling, logging and first-run reset (6).
- Gateway: profile cache timing, routing/idle polling, root URL and logging (6).
- Library: startup scan, catalogue URL, starter list override and logging (4).
- Driver: only logging qualifies, so there is no disclosure.

Collapsed inputs remain mounted. Their drafts still save, the disclosure counts
unsaved changes, and rejected fields reopen after Save. The new-field and
conditional-field cases are covered. Common storage, access, model, and connection
settings remain visible. Config descriptions remain technical help; the golden-path
plain-copy limit is not presented as a rewrite of every backend error or schema.

The golden-path gate now includes the shared discovery, run, profile and benchmark
components. It bans the user-facing noun runtime/runtimes, exempts API paths and
expert hints, and reads wrapped JSX through TypeScript's parser. The original
single-line string checks still cover messages and labels. Sentences are counted
individually, not whole paragraphs. Existing size/context formatters retain explicit
units; no raw byte counts or silent GB/GiB conversion were introduced.

Verification:

- UI suite: **742 tests passed**. ESLint, TypeScript and Prettier passed. UI CI
  **35541048229** green, including production build, wheel and codegen freshness.
- Four deliberate regressions in a disposable worktree were caught: removing the
  glossary from The system, lowering the three-field threshold, failing to reveal
  rejected hidden settings, and disabling wrapped JSX extraction. Baseline and
  restored checks passed. Failures were actual test assertions, not compilation errors.
- `node ui/scripts/s8-copy.mjs <copy.txt>` exports the checked source fragments.
  Pasted into the actual free Hemingway web editor on 2026-09-20: **Grade 6**,
  below the Grade 9 gate. This is the extracted source-copy corpus, not every possible
  API error or user-supplied value. The editor also flagged hard sentences; its
  overall grade is not a claim that every fragment is equally easy to read.
- An isolated production export produced a wheel, installed into the disposable
  integration environment. All **184 assets** matched export, dist and wheel byte
  for byte. Wheel SHA-256:
  `29d6b66f21f99a2e845c4f44658ff13d8b1820f2cbe5fbb83b59d659b1ab77b2`.
- The wheel-served browser drove a real disposable agent: common/hidden fields,
  keyboard disclosure, edit while expanded, collapse, real PATCH, reload and persisted
  value. The glossary had twelve entries, scrolled at 390px without horizontal
  overflow, and returned focus on Escape. No page errors. The temporary agent shut
  down cleanly; no installed service or model was changed.

Reproduce the packaged browser check after installing the new UI wheel and agent
into an isolated Python environment, with UI Node dependencies in the sibling repo:

```text
python scripts/s8-ui-acceptance.py --output <new-disposable-directory>
```

The output directory contains screenshots and a disposable session; do not commit
the session. Local evidence is under `%TEMP%/ep-s8-browser`; Hemingway evidence is
`%TEMP%/ep-s8-hemingway.png` and `ep-s8-readability.txt`.

S9 remains the next slice. This verifies the new glossary at phone width, not the
whole UI's phone layout: Config's fixed label column and Library's detail pane
still belong to that pass. S10's download timing and moderated sessions remain owed.
