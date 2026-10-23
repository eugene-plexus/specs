# Row 51: Job Sites, banked items

Lane AG2. Six items banked while Job Sites were built
(`person-held-keys.md` §3.3, §11, "Banked for ease" and §13.4's residual;
`job-sites-own-enrollment.md` J27 and J80). Each is a part with its own
branch suffix, risk and review; build them in this order. Parts 51a, 51b
and 51f are small; 51c, 51d and 51e are high risk.

## 51a. A QR code beside the pairing code (S, low)

- The machine's `/link` page (`agent/routes/site_link.py`, "Show a code for
  a passkey") shows a QR code beside the 10-character code. It encodes
  Workbench's pairing address with the code in the fragment:
  `https://<Workbench origin>/job-sites/<site>/pair#code=<code>`. A
  fragment never reaches a server log.
- `install.sh --site-pair` prints the same QR code in the terminal.
- Workbench reads `#code=` into the code field and clears the fragment; the
  person still presses Pair.
- No QR code when Workbench has no https origin (passkeys need one anyway);
  the page says so.
- Library: `segno` (pure Python, no dependencies, BSD) in the agent and
  site-host for SVG and terminal output.

## 51b. Workbench says when passkeys must be paired again (S, low)

- Each paired passkey records its RP ID (`passkeys.json`). When it differs
  from Workbench's current one (`job_sites_api._relying_party`), the Job
  Sites page says, per site: "Your passkey for Amish_Station was made for
  nas.local. Workbench now answers at nas.home.example.com, so it cannot
  sign here. Pair it again." with the Pair button, and the approval panel
  offers only "Approve at the machine" for those calls.

## 51c. An auditor at a site (M, high: a read permission over others' lines)

- **Today** (J80) each audit line belongs to one person, who alone reads
  it; the owner also reads lines that name no one.
- **New:** the site's owner may name auditors among the people linked to
  that site. An auditor reads every line at that site, not chats or files.
  It is granted in the site's rules, which the owner signs as other rule
  changes are signed, so control alone cannot grant it.
- Site host: `Audit.newest` returns every line to an auditor;
  `audit.read` takes `all: true` from an auditor only. Control relays it
  (`POST /oidc/job-sites/{site}/audit` with `all`). Workbench's audit panel
  gains "Everyone's lines" for an auditor.
- **People see it:** the panel says "Your lines here can also be read by:
  Dana (auditor)." Settings never lie.
- Tests: an auditor reads others' lines; a non-auditor's `all: true` is
  refused; an auditor named only by control (not signed) is refused.

## 51d. The worker checks the person's signature itself (M, high)

- **Today** the site host checks each command's signature and passes the
  call to the person's worker, which checks only the administrator's
  consent (`commands_consented`, read from `servers.yaml`, which only an
  administrator can write). A compromised site host on a machine with
  consent can run commands as every linked person.
- **New:** the administrator's consent (the tray's "Allow commands…",
  behind UAC, or `site consent`) also records each person's passkey public
  keys, shown to the administrator by name and device ("Jessie: Pixel 8,
  paired 7 Oct"). The host passes the signed envelope and assertion with
  each command; the worker verifies them against the keys in the consent
  file before it runs anything (`signing.check_envelope` and the
  assertion check, shared code).
- **The anchor** is the consent file, which the host's account cannot
  write. A passkey paired later signs commands only after the
  administrator refreshes consent; the pairing panel says so.
- Tests: a command with a host-forged envelope is refused by the worker
  even when the host accepts it (sabotage the host's check); a key not in
  the consent file is refused; consent refreshed adds it.

## 51e. OS-enforced confinement on Windows for people with no account (L, high)

- **Today** (J27) a person with no account on the machine gets a folder
  through the owner's worker, confined by Eugene's own path checks
  (`folder_io`, `folder_windows`: one component at a time, no reparse
  points). A bug there exposes the owner's account.
- **New:** their calls run in a child of the owner's worker inside an
  AppContainer named for the site and folder
  (`CreateAppContainerProfile`, `DeriveAppContainerSidFromAppContainerName`).
  The owner's worker adds that AppContainer's SID to the shared folder's
  permissions (read, or read and write, as granted), which it may do as the
  folder's owner, with no administrator. The child runs the same file
  server over a pipe; Windows refuses it everything else.
- The path checks stay, as a second wall. Linux keeps Landlock.
- A folder whose permissions the owner cannot change (a network share):
  the share is refused for no-account people with the reason, as today's
  rules would allow it in code only. Call R51-SHARES.
- Tests (Windows CI): the child cannot open a file outside the folder
  even with the path checks disabled (sabotage); removing the share
  removes the SID's permission.

## 51f. Workbench at its tailnet name too (S-M, cross; after row 45b)

- Workbench's entry point takes a second public origin, the machine's
  tailnet name from row 45b. `Settings.public_origin` becomes a list;
  `CanonicalOrigin` allows each; cookies are per host already (`__Host-`);
  the sign-in issuer is chosen per request host, as http and https are
  today.
- Passkeys are per RP ID, so a passkey works at the name it was paired on;
  51b tells the person which.

## Repositories

agent (51a, 51e consent recording in the tray and CLI), site-host (51a CLI,
51c, 51d, 51e), workbench (51a, 51b, 51c, 51f), control (51c relay),
specs (`site-host.yaml`, `control.yaml` for 51c; the installer for 51a).

## Acceptance

One script, `specs/scripts/row51-job-sites-acceptance.py`, extended per
part, on the Job Sites harness (`job-sites-acceptance.py`): 51c's three
cases; 51d's forged envelope refused by the worker with the host's check
sabotaged; 51e on the Windows runner. 51a, 51b and 51f are unit and page
tests.

**The reviewer should attack (51c-51e):** granting audit without the
owner's signature; the worker's verification reusing state the host can
write; a key added to the consent file without UAC; the AppContainer's
SID left on a folder after a share ends; a junction inside the shared
folder.

## Size and risks

L in total (51e alone is M-L). One adversarial review after 51d and one
after 51e. Calls: R51-SHARES (no-account people cannot be given a network
share, since Windows cannot confine one for them).

## Calls answered by Troy (2026-10-22)

- **R51-SHARES: Choice 2.** A network share stays available to people with
  no account on the machine, confined by Eugene's own path checks as today
  (the AppContainer cannot be given a network share's permissions). 51e
  confines every local-disk folder with the AppContainer and keeps the
  path checks alone for network shares; the share dialog says which
  applies.
