# C4 acceptance: Open WebUI from the app registry

**2026-10-02.** Design: [`../design/c4-open-webui.md`](../design/c4-open-webui.md),
with Troy's three calls. Pins: agent `9b5a07c` (catalogue entry, the
registry's new fields, the launcher), control `dca6827` (a person's email,
the `email` scope), ui `f463c16` / `dist` `66b80b4` (the People page's email,
the Apps card's links). Contract specs `f768bc5`.

| Run | Result |
| --- | --- |
| `scripts/c4-open-webui-acceptance.py` on GitHub's Windows and Ubuntu runners (`c4-open-webui.yml`), a real service install and Open WebUI 0.11.4 from PyPI | **39 of 39 on each** ([run 36969009184](https://github.com/eugene-plexus/specs/actions/runs/36969009184)) |
| The same run on the installer's pins before C4 | **11 of 12 on each**: it stops at check 30, the catalogue has no Open WebUI |
| Sabotage: agent (`c4-agent-sabotage.py`), control (`c4-control-sabotage.py`), ui (`c4-ui-sabotage.py`) | **27 of 27, 11 of 11, 7 of 7** |
| Every script specs CI runs, locally, on the candidates | **25 of 25** |
| Suites | agent 1,590; control 330; ui 1,611 |

## What the run does

It installs Eugene as each runner's service, the way a person does: elevated
`install.ps1` on Windows (LocalSystem), `sudo install.sh` on Ubuntu (the
`eugene-plexus` account). It then:
- onboards the install through the API;
- adds a fixture model behind the gateway the way the console's *Add an app
  you already run* does;
- installs Open WebUI from the catalogue;
- signs people in through Eugene's real sign-in page as a browser does, with
  cookies, redirects and the form, over plain HTTP.

## After

- **The entry** (30-33): it is offered from PyPI at 0.11.4, with its licence
  link, needing an account of its own. It installs, and answers `/ready`.
  - Install from PyPI: 43 s on Ubuntu and 116 s on Windows, then 23 s and
    46 s for the reinstall, from uv's cache.
  - Ready after the install: 27 s on Ubuntu, and 72 s (first start) and 51 s
    on Windows.
- **Its own account** (34). The agent reports `own_account`, and the process
  on its port runs as `NT SERVICE\EugenePlexusApp-open-webui` on Windows and
  as the dynamic user `eapp-…` on Ubuntu.
- **Its writes and downloads** (35-36). No model was downloaded: embeddings
  and transcription are pointed at the gateway. Its static files, secret,
  database and caches are in its data directory.
- **Signing in through Eugene** (40-46):
  - the owner signs in with the passphrase and arrives as **Open WebUI's
    admin**, with the placeholder `oidc@operator.local`;
  - a person added with an email arrives as a **user** with that email;
  - a person without one arrives as a user with the placeholder;
  - a person turned off in Eugene is refused at Eugene's page.
- **A chat** (50-51) answers from the fixture model through the gateway, and
  the gateway records its requests under the app's key and no other.
- **Settings across starts** (60-65):
  - a banner its admin sets survives a plain restart;
  - an uninstall that keeps its data, then a reinstall, mints a different
    key (checked by id). The launcher sets `RESET_CONFIG_ON_START` for that
    start, its log says why, and the chat works on the new key.
- **Uninstall** (70-72) removes its sign-in at the root, and nothing listens
  on its port.

## Found by the run

**In the harness, both runners, first execution:** checks 61 and 63 failed
with *Not authenticated*. Once the install has people, Eugene's page asks the
owner for a name as well as the passphrase (C2, D4), and the run signed in
with the passphrase alone. The product was right; the run now gives the
owner's name.

## Found by reading, while building

- **Eugene ignored scopes it did not know by narrowing to `openid`**, so an
  app asking for `email` silently got no email. It now grants what it knows
  (`openid`, `profile`, `email`) and ignores the rest.
- **The control root's log refuses a person record with an unknown field**,
  so `email` had to be allowed there too. Otherwise every person with an
  email would have been refused when it was applied.
- **One bad catalogue entry used to empty the whole catalogue.** It now
  costs only that entry, named in the log.

## What this does not show

- **A browser.** The run signs in over plain HTTP, the way a browser does,
  but no Chrome drove Open WebUI's own page.
- **The owner's own email.** The owner has none in this slice, by design
  (control #4 holds that, and Google and Microsoft sign-in).
- **Open WebUI's web search, image generation and log export** through the
  hub. They are off or not wired (design §5).
- **A live install.** Troy's NAS container cannot have app accounts, so Open
  WebUI installs on `Amish_Station` (a Windows service) and not on the NAS.
- **What a Windows start costs.** Each start re-grants the app's account
  across its 1.8 GB environment. The runner's restart came back within the
  run's wait, but it was not timed separately.
