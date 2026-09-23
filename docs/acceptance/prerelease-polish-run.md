# Pre-release UI and security polish

Executed 2026-09-22 on Windows, with the backend suites also run under WSL.
Twelve UI fixes and five security fixes from a pre-release survey, plus the
small follow-ups the survey named. No OpenAPI or generated-model change, so no
consumer moved `SPECS_REF`.

Revisions: agent `74ba99f`, control `84e410f`, gateway `ade140f`,
inference-driver `3a50ac4`, library `ea19464`, ui `72b5b6d` packaged as `dist`
`f62c358`. Both installers pin exactly these. Acceptance scripts were updated in
`3eea438`.

## What changed

**UI.** A failed Config save keeps the form and the draft; the save banner names
fields by label; Discard. Config, Routing and Library Folders ask before a
navigation or tab close drops unsaved edits, and Routing's Refresh keeps a dirty
draft. The setup gate gives up after ten seconds with Try again. A refused
session says so on the sign-in page, streaming included. A styled 404 page.
Links that opened an empty Config page select what they name. Turning off a
client key, deleting a profile, forgetting a model and clearing the playground
ask first, through one `ConfirmButton`. The Library list has a filter. Sizes and
times read as people read them (a token's time left, GB, dated week-old
requests, idle minutes). Server sentences instead of `HTTP 500`, and
`role="alert"` on error banners. Labels tied to inputs across Config, the wizard
and the backend form; dialog semantics, focus and Escape on the folder picker;
colour is no longer the only channel on reach dots and selected rows. Enter no
longer sends mid-IME-composition, and the playground composer grows.

**Security.** An image in model output renders as a link, never an `<img>`, so
it cannot exfiltrate data when loaded. Secret-bearing files are written 0600 and
atomically in all five components. First-run initialize requires a passphrase
of at least 12 characters in the agent, control and the wizard (sign-in is
unchanged). Sign-out is enforced at the agent's browser proxy and persisted
across restarts; operator tokens carry a random `jti`. A Host allowlist defeats
DNS rebinding: on every agent route, and on control's initialize and login only.
The agent proxy caps request bodies at 32 MiB, the gateway and driver cap their
embeddings and decision bodies, and agent responses carry `nosniff` and
`no-referrer`.

## Behaviour an operator can notice

- Reaching the agent by a public DNS name (for example behind a reverse proxy)
  returns 403 until the name is added under **Config → Agent → Allowed host
  names** (comma-separated; `*` allows any). IP literals, `localhost`, dotless
  names, `.local`, `.lan`, `.home.arpa`, `.internal`, `.ts.net`, the machine's
  own name and the advertise host need nothing. Control's check covers only its
  browser-facing unauthenticated routes, with `EUGENE_PLEXUS_CONTROL_ALLOWED_HOSTS`
  as the override; the agent proxy strips `Host`, so console sign-in is unaffected.
- A new install refuses a passphrase shorter than 12 characters. Existing
  installs keep theirs.

## Verification

Every new regression check failed against the previous code before its fix.

| Repo | Result |
| --- | --- |
| ui | 982 tests; typecheck, lint and format clean; static export built |
| agent | 1085 passed, 12 skipped (Windows); 1076 passed, 21 skipped (WSL) |
| control | 219 passed, 2 skipped (Windows); 221 passed (WSL) |
| gateway | 582 passed, 1 skipped (Windows); 583 passed (WSL) |
| inference-driver | 563 passed, 4 skipped (Windows); 564 passed, 3 skipped (WSL) |
| library | 497 passed, 25 skipped (Windows); 501 passed, 21 skipped (WSL) |

`scripts/login-unlock-check.sh` passed against the combined local build: real
agent, control, gateway and library processes on +100 ports, a sealed root, and
Chrome signing in through the served UI. The pinned `dist` archive was fetched
from GitHub and grepped for the new 404 page and new UI strings.

## Not run

- `m9-acceptance.sh`, the browser walk through the wizard, because its up-front
  port clearing can reach the live worker's drivers on this box. The wizard's
  12-character rule and the setup-gate timeout are covered by unit tests.
- `install-acceptance.sh`, for the reason recorded at M11: the Windows installer
  writes the user-scope configuration variable the live worker depends on.
- No physical reverse-proxy or second-device check of the Host allowlist.
