# R3.8 - contract and duration-clock sweep

2026-09-20. Contract `239fb04`. Roadmap section 4 item 8.

The reproduction reported eight stale contract claims: an omitted security
mode, two bcrypt descriptions, install-wide runtime-name uniqueness, a
guaranteed metadata basis for on-disk models, an incomplete fit-basis
description, an unresolved latency diagnosis, and an undocumented metric
clock. These are corrected. R3.3 already corrected positional tier semantics;
the sweep protects both empty tiers and the virtual-alias exception.

`SecurityMode.passphrase_file` describes the control root's existing option.
The agent's config still offers `prompt_on_startup` and `os_keyring`; adding
the shared enum value does not add an agent configuration mode. Authentication
behavior and the signing-key design are unchanged; the latter is R7.

## Verification

```powershell
../agent/.venv/Scripts/python.exe scripts/r38-contract-checks.py --polyrepo .. --sabotage
```

- Eight failures before the contract correction; the corrected gate passes.
- 175 non-generated source files across all five active Python consumers have
  no calls to `time.monotonic()` or its nanosecond form. The AST check also
  recognizes module aliases and imported function aliases. No duration code
  needed changing; R1.1 had already removed those calls.
- 11/11 in-memory sabotages caught; unchanged baseline passes.
- Redocly 2.30.4 and openapi-spec-validator pass. Redocly retains the existing
  unused `StreamToken` warning in inference-driver.yaml.
- Focused Windows tests: agent **51**, control **26**, gateway **59**, library
  **60**, inference-driver **35**; total **231 passed**. Coverage includes auth,
  config, duration/client reuse, runtime lifecycle, routing, and fit behavior.
- Mypy passes in all five consumers. Specs CI `35523277582` passed.

## Generated consumers and distribution

| Consumer | Published commit | Change |
| --- | --- | --- |
| agent | `52c1109` | Regeneration in `99501e4`, then portable regression fixtures |
| control | `b192481` | Shared enum and corrected descriptions |
| gateway | `dfdf5df` | Shared enum and corrected descriptions |
| library | `b3ad977` | Shared enum and corrected descriptions |
| inference-driver | `5c9e3c6` | Regeneration in `cf5307c`, then isolated request fixture |

Each Python consumer was regenerated in temporary directories at its old
specs pin and at `239fb04fbcfc061a88d98e2664ef2c07b28fdcbf`. The old generation
matched its committed output. Comparing Python ASTs with docstrings removed
identified the enum addition in all five, so all five pins moved. Generated
code was produced with each repo's own script and environment, never edited.

The UI was also regenerated at its actual pin, at the pre-R3.8 specs revision,
and at the new revision. Its pinned output matches; the R3.8 delta changes
comments only across all five generated documents. No UI pin or dist rebuild
is needed. The earlier intentionally deferred R3.4 fields remain deferred.

Both installers carry the five published Python commits. This work does not
restart or reconfigure the live install. R3.7's physical Mac acceptance remains
pending; R7 is the next implementation stage.

## CI follow-up

The first agent CI run reproduced the five Linux test failures already
documented in R3.6: two seeding tests assumed the sibling packages were
installed, and three Windows-policy tests never selected the Windows branch
on Linux. The fixtures now supply those facts at their module boundaries.
The held-port and action-order checks remain intact; no tests were skipped
to obtain a pass. The inference-driver's ordinary-request check also assumed
a real `claude` binary. It now injects a successful adapter and asserts both
HTTP 200 and its answer, strengthening the previous `< 500` assertion.

Clean Linux Python 3.12 environments installed with only each repo's own dev
dependencies pass their complete suites: **agent 862 passed / 17 skipped**,
**inference-driver 407 passed / 3 skipped**. The skips are existing hardware
and opt-in live checks. On Windows the changed agent files pass **60 tests /
1 skipped**, and the driver's disconnect file passes **7 tests**.

Post-push control CI `35523383946`, gateway CI `35523386470`, library CI
`35523388171`, and corrected driver CI `35523573849` pass. Agent's corrected
CI is tracked at its final pin. All five installer archives resolve and both
installers carry matching pins.
