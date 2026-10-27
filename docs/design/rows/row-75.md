# Row 75: show Eugene's version in the console

Lane WEB, risk cross, size S-M. Troy asked for it first: v0.4.0 is not easy
to find anywhere in the console. There is no design doc besides the row's
text in `roadmap.md` and the issue (specs#119); this file is both the design
and what building found.

## 1. What it delivers

- Each machine's card on Machines says the version it runs: `v0.4.0`, `Edge,
  built 2026-10-24`, `development build`, or `not a published release`.
- The bottom of the resource tree says the version of the machine serving the
  console, small and muted: "Eugene Plexus v0.4.0". The seven commits are
  behind a Details control in both places, never in the line.
- An agent from before this field sends none. The card then says what it said
  before (it names a release only when the commits already prove it), and the
  tree shows no line.

## 2. Contract

`NodeIdentity.version` (`GET /v1/node`), a `NodeVersion`:

| `kind`        | Meaning                                                              | Other fields                      |
| ------------- | -------------------------------------------------------------------- | --------------------------------- |
| `release`     | every commit is the one a published release pins                     | `release`, `publishedAt`          |
| `edge`        | every commit is the one the Edge marker pins                         | `publishedAt`, `specsCommit`      |
| `development` | a git checkout: nothing to match                                     |                                   |
| `unmatched`   | matches no release and not Edge: "not a published release"           | `checkedAt`, `error` when stale   |
| `unknown`     | not matched yet, or the lookup failed, or the commits just changed   | `error` names the cause           |

No request or report a machine sends gains a field. The root does not read
`NodeIdentity.install`, `update` or `version`; the console does, through the
agent's proxy, and reads each tolerantly (absent means "no version shown").

## 3. How the agent works it out

`VersionResolver` in `agent/src/eugene_plexus_agent/updates.py`.

- **Match.** Every component's installed commit must equal the one the
  target pins, and a component the target does not pin must not be installed
  (the store joined at row 53: an install that has it is newer than a release
  that lacks it, never that release). Releases are tried newest first from the
  published list (twenty), then the Edge marker. A release wins over Edge when
  both pin the same commits.
- **When.** With the update check: a minute after start, every six hours,
  and on `POST /v1/node/update/check`. Never on the `GET /v1/node` path, which
  reads memory only, so startup and the node report never wait on GitHub.
- **Kept on disk** in `<prefix>/update/version.json` as `{commits, version}`,
  and used only while the installed commits are the same ones. So it shows
  offline and after a restart; after an update the answer is `unknown` until
  the new commits are matched (the agent restarts after an update, and the
  check runs a minute later).
- **Final or retried.** A `release` or `edge` match is final for those
  commits. `unmatched` is retried at every check, since a release can be
  published later from the same commits. A failed lookup keeps an earlier
  answer for the same commits and puts the cause on `error`; with no earlier
  answer the kind is `unknown`. A release manifest is read once per process
  (a published release never changes).
- **Never invented.** `unknown` is never turned into a guess, and the console
  does not name a version the agent did not match.

## 4. Calls (defaults built)

Nothing deletes data or keeps chats anywhere new. The agent writes one small
file (`update/version.json`).

- **R75-C1, wording of a checkout.** The brief said "development checkout".
  The console already says "Development build" on the card (headline and
  version), so the new field uses `development build`: one word for one
  meaning.
- **R75-C2, Edge reach.** Only the *current* Edge marker's pins are compared.
  An Edge install that was not matched while it was newest, and has since been
  passed by a later Edge build, reads "not a published release" (its commits
  are in Details). Matching older Edge builds would mean walking the history
  of `scripts/install.sh` on specs; the call is whether that is worth it.
  Default: no.

## What building found

- The agent's `update` and `install` already reached the Machines card
  through `useIssues`; the card's old rule named a release only when the
  commits equalled the *channel's newest*, so a v0.4.0 install following
  `edge` showed no version at all. That is why v0.4.0 was hard to find.
- Pins are not level: the agent and ui SPECS_REF moved from their old pins to
  the row's specs commit, which also carried other rows' contract text. The
  agent's regenerated models changed only descriptions besides `NodeVersion`;
  the ui's `gateway.ts` and `store.ts` types changed by other rows'
  additions, and the ui typechecks with them.
- No existing acceptance script starts an agent from the branch and reads the
  Machines page. `ui/e2e/tree.spec.ts` (the navigation acceptance, run by
  hand on Windows) gained one check for the footer line; it was not run here.
  The Linux system-install acceptance reads `/v1/node` but installs from the
  published pins, not the branch, so it cannot see this field.
